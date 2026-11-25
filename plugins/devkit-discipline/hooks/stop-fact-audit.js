// stop-fact-audit.js — 回合末后台事实审查（4.20.0，Stop hook，asyncRewake）
//
// 【为什么有它】用户 2026-11-23 拍板 Q1-c、Q2-a：同步审查（stop-audit.js）四路全留、全走订阅 sonnet；
// 第三方模型（gemini 等）挪到后台，只审核心事实错误与漏答，可用只读工具对照本机文件核实。
// 第三方判定一次要 30～150 秒（2026-11-23 实测），放在同步路径上用户每轮都要干等。
//
// 【它怎么把结果交回主模型】hooks.json 给本脚本配 asyncRewake: true。Claude Code 不等它，回复立即结束；
// 本脚本以退出码 2 结束时，stderr 作为「Stop hook feedback」消息叫醒主模型开新一轮（Claude Code 2.1.330
// 字段说明原文：「If true, hook runs in background and wakes the model on exit code 2 (blocking error).
// Implies async.」；headless 下实测叫醒成功）。叫醒那一轮的 Stop 带 stop_hook_active=true，
// 本脚本与 stop-audit.js 都直接放行，不会循环。
//
// 【什么时候跑】只在设了 DEVKIT_STOP_AUDIT_SETTINGS（第三方 settings 文件，读得到）时跑；
// DEVKIT_FACT_AUDIT=off 单独关掉本审查。没开第三方时不跑，避免给所有人每轮多一次订阅判定。
//
// 【失灵时怎样】超时：也叫醒（4.26.0，用户 2026-11-24 拍板），只让主模型告诉用户「这条回复没审完」，
// 不复查不重写——11-24 实测 32 次里 14 次跑满 300 秒，原先静默丢掉，用户以为机制没生效。
// 报错、空输出：也叫醒（4.28.0，用户 2026-11-24 拍板 Q1-a），叫醒文本带上游报错原文，同样只回一句。
// 11-24 下午的超时根因是网关下架了 gemini-4-neon（立即 503 model_not_found），子进程却继承了
// CLAUDE_CODE_RETRY_WATCHDOG=1，约 35 秒重试一次、跑满 300 秒才被杀。现在剥掉它、重试限 2 次，硬错误几秒内失败。
// 输出形态（4.29.0，用户 2026-11-25 拍板）：不用 --json-schema，审查模型直接写审查意见文本，没问题时只写一行 PASS。
// 11-25 实测 gpt-6.2-sol 带 schema 时 43 次里 12 次没给 structured_output，旧版会话把这种失败当通过、静默丢掉。思考等级 high。
// 判定子进程：cwd 在临时目录、--setting-sources project、DEVKIT_STOP_AUDIT_CHILD=1（同 stop-audit.js 的防递归），
// 只放 Read / Grep / Glob，--add-dir 加上会话的项目目录。

'use strict'

const fs = require('fs')
const path = require('path')
const m = require('./stop-audit')

const FACT_TIMEOUT_MS = 300000 // 用户拍板 Q2-a 给工具后多轮读文件，超时放宽到 5 分钟；hooks.json timeout 330
// 只给测试缩短超时用；取值必须是小于 FACT_TIMEOUT_MS 的正整数，否则用 FACT_TIMEOUT_MS
function factTimeout(env) {
  const n = Number(env.DEVKIT_FACT_AUDIT_TIMEOUT_MS)
  return Number.isInteger(n) && n > 0 && n < FACT_TIMEOUT_MS ? n : FACT_TIMEOUT_MS
}
// 单次 API 请求超时：同步判定给 85 秒（CHILD_API_TIMEOUT_MS），gemini 一次推理常超过 90 秒（2026-11-23 实测），这里放到 150 秒
const FACT_API_TIMEOUT_MS = 150000
// 子进程最多重试 2 次：瞬时 529/5xx 仍有机会恢复，上游配置错（模型下架、鉴权失败）几秒内失败。
const FACT_MAX_RETRIES = '2'
const FACT_TOOLS = 'Read,Grep,Glob'
const FACT_EFFORT = 'high'
// 4.30.0 用户 2026-11-25 拍板：审查换 gemini-4-carbon，它在第三方 settings 里映射在 fable 档，故用 --model fable。
// 模型名一律由 settings 的 ANTHROPIC_DEFAULT_FABLE_MODEL 决定，本脚本只写档位别名。
const FACT_MODEL = 'fable'
const FACT_DISALLOWED = 'Bash,Write,Edit,NotebookEdit,WebFetch,WebSearch,Agent'
const SYS_FACT = 'You are a background fact-checker for a Claude Code session. Use Read, Grep and Glob to check the last assistant reply against local files and the transcript. You never modify anything.'

function factAuditEnabled(env) {
  const flag = String(env.DEVKIT_FACT_AUDIT || '').toLowerCase()
  return !(flag === 'off' || flag === '0' || flag === 'false')
}

function factArgs(settings, cwd) {
  const a = [
    '-p', '--settings', settings, '--model', FACT_MODEL, '--system-prompt', SYS_FACT,
    '--setting-sources', 'project', '--effort', FACT_EFFORT,
    '--strict-mcp-config', '--disable-slash-commands',
    '--allowedTools', FACT_TOOLS, '--disallowedTools', FACT_DISALLOWED,
  ]
  if (cwd) a.push('--add-dir', cwd)
  a.push('--no-session-persistence', '--output-format', 'json')
  return a
}

// 审查意见文本 → 判定：有一行恰为 PASS、且没有以「事实错误：」「漏答：」开头的行，判满足；
// 其余非空文本整段当审查意见叫醒主模型；空文本返回 null，按失败处理（kind=empty-text）。
function parseFactText(text) {
  if (typeof text !== 'string' || !text.trim()) return null
  const t = text.trim()
  const lines = t.split('\n').map((l) => l.trim().replace(/^[-*]\s*/, ''))
  const pass = lines.some((l) => /^\**PASS\**[。.]?$/i.test(l))
  const issue = lines.some((l) => /^(事实错误|漏答)[:：]/.test(l))
  if (pass && !issue) return { ok: true, reason: '' }
  return { ok: false, reason: t }
}
function factVerdict(j) { return parseFactText(j && j.result) }

// 判定子进程的环境：在 routeEnv 之上放宽单次请求超时、剥掉重试看门狗、限重试次数
function factEnv(parentEnv, settings) {
  const env = { ...m.routeEnv(parentEnv, settings), API_TIMEOUT_MS: String(FACT_API_TIMEOUT_MS), CLAUDE_CODE_MAX_RETRIES: FACT_MAX_RETRIES }
  delete env.CLAUDE_CODE_RETRY_WATCHDOG
  return env
}

function buildFactInput(hookInput, contextLines, template) {
  const pre = contextLines.length ? contextLines.join('\n') : '[user]: （本轮用户提问未能读取）'
  const cond = template.split('$CWD').join(hookInput.cwd || '（未知）')
  return `<transcript>\n${pre}\n\n[assistant]: ${hookInput.last_assistant_message}\n</transcript>\n\n${cond}`
}

// 叫醒消息最前面的标识（4.27.0，用户 2026-11-24 要求）：harness 显示成「Stop hook blocking error from command "Stop": <stderr>」，
// 与同步审查的打回长得很像，加标识让人一眼认出这是第三方异步审查、是哪个模型审的。
// 模型名取第三方 settings 里 fable 档映射的那个（本脚本用 --model fable 调，4.30.0 起），读不到写「第三方模型」。
function modelLabel(settings) {
  try {
    const v = JSON.parse(fs.readFileSync(settings, 'utf8')).env.ANTHROPIC_DEFAULT_FABLE_MODEL
    if (typeof v === 'string' && v.trim()) return v.trim()
  } catch { /* 读不到就用通用名 */ }
  return '第三方模型'
}
function tag(settings) { return `🔍【异步审查 · ${modelLabel(settings)}】` }

// 叫醒主模型的消息：点明审的是哪条回复（审查耗时长，叫醒时主模型可能已经往下做了），要求先核实再改。
function wakeText(reason, last) {
  return `后台事实审查（第三方模型，可读本机文件）审的是你开头为「${m.cut(last, 40)}」的那条回复，发现：\n${reason.trim()}\n` +
    '先用工具逐条核实。确有错：在回复开头写更正块（原说、实为、错因）后改正；核实后原文无误：用一两句说明依据，不必重写整条回复。'
}

// 超时叫醒的消息：只为让用户知道这条没审到。主模型不复查、不重写，回一句就结束本轮。
function timeoutText(sec, last) {
  return `后台事实审查（第三方模型）审你开头为「${m.cut(last, 40)}」的那条回复时超时（${sec} 秒没有出结果），这条回复没有经过事实审查。\n` +
    `不复查、不重写。只回用户一句：「上一条回复（开头为「${m.cut(last, 20)}」）的后台事实审查超时，没有审到。」然后结束本轮。`
}

// 失败原因：claude -p 的 JSON 里 is_error=true 时 result 是上游报错原文（如「API Error: 503 No available channel
// for model …」，2026-11-24 实测）；没有就取 stderr 最后一行，再没有就用失败类别。
function failDetail(kind, p) {
  try {
    const j = JSON.parse(p.stdout)
    if (j && j.is_error && typeof j.result === 'string' && j.result.trim()) return j.result.trim()
  } catch { /* stdout 不是 JSON */ }
  const line = String(p.stderr || (p.error && (p.error.code || p.error.message)) || '').trim().split('\n').filter(Boolean).pop()
  return line || kind
}

// 非超时失败的叫醒消息：带报错原文，让用户知道是哪里坏了（模型下架、鉴权、网关不通），主模型同样只回一句。
function failText(detail, last) {
  return `后台事实审查（第三方模型）审你开头为「${m.cut(last, 40)}」的那条回复时失败，报错：${m.cut(detail, 300)}\n这条回复没有经过事实审查。\n` +
    `不复查、不重写。只回用户一句：「上一条回复（开头为「${m.cut(last, 20)}」）的后台事实审查失败，没有审到；报错：${m.cut(detail, 120)}」然后结束本轮。`
}

async function main() {
  if (process.env.DEVKIT_STOP_AUDIT === 'off' || process.env.DEVKIT_STOP_AUDIT_CHILD === '1') return 0
  if (!factAuditEnabled(process.env)) return 0
  let hookInput
  try { hookInput = JSON.parse(fs.readFileSync(0, 'utf8')) } catch { return 0 }
  if (hookInput.stop_hook_active || !hookInput.last_assistant_message) return 0
  const settings = m.thirdPartySettings(process.env)
  if (!settings) return 0
  const claudeBin = m.resolveClaude()
  if (!claudeBin) return 0

  let contextLines = []
  try { if (hookInput.transcript_path) contextLines = m.buildContextLines(m.readTail(hookInput.transcript_path)) } catch { /* 只审最后一条回复 */ }
  const template = fs.readFileSync(path.join(__dirname, 'stop-fact-audit-prompt.txt'), 'utf8').trimEnd()
  const timeout = factTimeout(process.env)
  const t0 = Date.now()
  let failure = null
  const v = await m.judgeAsync(claudeBin, buildFactInput(hookInput, contextLines, template), {
    settings, timeout, audit: 'fact', args: factArgs(settings, hookInput.cwd), env: factEnv(process.env, settings),
    verdict: factVerdict, onFail: (kind, p) => { failure = { kind, p } },
  })
  const ms = Date.now() - t0
  const wake = !!(v && v.ok === false && typeof v.reason === 'string' && v.reason.trim())
  // 判超时的口径同 judgeAsync：claude 被 SIGTERM 后以 143 退出、signal 为空，只能按耗时判
  const timedOut = !v && (failure ? failure.kind === 'timeout' : ms >= timeout - 200)
  const failed = !v && !timedOut && !!failure
  m.logFailure('run', {}, ms, { stage: 'fact', blocked: wake, timed_out: timedOut, failed })
  const last = hookInput.last_assistant_message
  if (wake) { fs.writeSync(2, tag(settings) + wakeText(v.reason, last)); return 2 }
  if (timedOut) { fs.writeSync(2, tag(settings) + timeoutText(Math.round(timeout / 1000), last)); return 2 }
  if (failed) { fs.writeSync(2, tag(settings) + failText(failDetail(failure.kind, failure.p), last)); return 2 }
  return 0
}

if (require.main === module) {
  main().then((code) => process.exit(code), () => process.exit(0))
}

module.exports = { parseFactText, FACT_EFFORT, FACT_MODEL, factArgs, factEnv, buildFactInput, wakeText, timeoutText, failText, failDetail, modelLabel, tag, factAuditEnabled, factTimeout, FACT_TIMEOUT_MS }
