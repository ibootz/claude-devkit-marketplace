// stop-fact-audit.js — 回合末后台事实审查（4.20.0 起，Stop hook，asyncRewake）
//
// 【为什么有它】用户 2026-11-23 拍板 Q1-c、Q2-a：同步审查（stop-audit.js）四路全走订阅 sonnet；
// 第三方模型挪到后台，只审核心事实错误与漏答，可读本机文件核实。第三方判定一次要 30～150 秒（2026-11-23 实测），
// 放在同步路径上用户每轮都要干等。
//
// 【它怎么把结果交回主模型】hooks.json 给本脚本配 asyncRewake: true。Claude Code 不等它，回复立即结束；
// 本脚本以退出码 2 结束时，stderr 进给模型的 system-reminder 叫醒主模型开新一轮，界面上只显示
// hooks.json 里 rewakeSummary 那一行（2.1.332 二进制：叫醒消息是 <task-notification><summary>…</summary>，
// 正文在其后的 system-reminder 里）。叫醒那一轮的 Stop 带 stop_hook_active=true，本脚本与 stop-audit.js 都直接放行，不会循环。
//
// 【审查走哪个模型】4.32.0 起（用户 2026-11-26 要求）改调本机 agy CLI（Antigravity），模型 gemini-4-neon、思考等级 medium。
// 此前经 claude -p + DEVKIT_STOP_AUDIT_SETTINGS 指的第三方 settings 调，那条路已删。
// agy 参数（2026-11-26 实测 agy 本机版本）：
//   - 提示词必须挂在 --print=<全文> 上：裸 -p 后面跟别的选项会被当成提示词（报「-p took "--model" as its prompt」），也不读 stdin。
//   - 4.34.0 起（用户 2026-11-26 要求，等同本机别名 gy = agy --dangerously-skip-permissions）：带 --dangerously-skip-permissions、
//     不再带 --mode plan，工具与目录都不限。plan 模式下读 --add-dir 之外的文件会被自动拒绝（headless 不能弹框），
//     回复只剩空串：4.32.0 上线后 6 次审查 5 次因此失败（2026-11-26 日志与复现）。--add-dir <cwd> 保留，只是把项目目录设成工作区。
//     hook 用 spawn 不经 shell，读不到 zsh 别名，所以直接拼出别名展开后的参数。
//   - --output-format json 输出 {status, response, ...}；status 不是 SUCCESS 按失败处理。
//   - 模型名写错时退出码非 0，stderr 第一行是「error: invalid model selection …」，后面跟整张模型清单。
//   - 每次调用都会在 agy 里留一条会话（返回 conversation_id），agy 没有不落盘的开关。
//
// 【什么时候跑】找得到 agy（DEVKIT_FACT_AUDIT_AGY 指定绝对路径，或 PATH、~/.local/bin 里有 agy）就跑；
// DEVKIT_FACT_AUDIT=off 单独关掉本审查，DEVKIT_STOP_AUDIT=off 连同步审查一起关。
//
// 【失灵时怎样】超时、报错、输出不合格式都叫醒（4.26.0 / 4.28.0 用户拍板），只让主模型告诉用户「这条回复没审到」，
// 不复查不重写；失败的叫醒文本带报错原文。
// 输出形态（4.29.0 用户拍板）：审查模型直接写审查意见文本，没问题时只写一行 PASS。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')
const m = require('./stop-audit')

const FACT_TIMEOUT_MS = 300000 // 给工具后多轮读文件，超时 5 分钟；hooks.json timeout 330
// 只给测试缩短超时用；取值必须是小于 FACT_TIMEOUT_MS 的正整数，否则用 FACT_TIMEOUT_MS
function factTimeout(env) {
  const n = Number(env.DEVKIT_FACT_AUDIT_TIMEOUT_MS)
  return Number.isInteger(n) && n > 0 && n < FACT_TIMEOUT_MS ? n : FACT_TIMEOUT_MS
}
const FACT_MODEL = 'gemini-4-neon'
const FACT_EFFORT = 'medium' // 用户 2026-11-26 指定
const SYS_FACT = '你是 Claude Code 会话的后台事实审查员。可以读任意本机文件、搜索文件名与内容、跑命令查状态，用来把最后一条助手回复与本机文件、命令结果、会话记录对照；审查只看不改，不修改任何文件。'

function factAuditEnabled(env) {
  const flag = String(env.DEVKIT_FACT_AUDIT || '').toLowerCase()
  return !(flag === 'off' || flag === '0' || flag === 'false')
}

// agy 可执行文件：DEVKIT_FACT_AUDIT_AGY 优先（给了却不可执行就当没装），再按 PATH 逐项找，最后试 ~/.local/bin。
function resolveAgy(env = process.env) {
  const override = env.DEVKIT_FACT_AUDIT_AGY
  if (override) return m.isExecutable(override) ? override : null
  const names = process.platform === 'win32' ? ['agy.exe'] : ['agy']
  const dirs = (env.PATH || '').split(path.delimiter).filter(Boolean)
  dirs.push(path.join(os.homedir(), '.local', 'bin'))
  for (const d of dirs) {
    for (const n of names) {
      const p = path.join(d, n)
      if (m.isExecutable(p)) return p
    }
  }
  return null
}

function factArgs(input, cwd, timeout) {
  const a = ['--dangerously-skip-permissions', '--model', FACT_MODEL, '--effort', FACT_EFFORT, '--output-format', 'json',
    '--print-timeout', `${Math.max(1, Math.round(timeout / 1000))}s`]
  if (cwd) a.push('--add-dir', cwd)
  a.push(`--print=${input}`)
  return a
}

// 审查意见文本 → 判定：
// - 有以「事实错误：」「漏答：」开头的行 → 不满足，整段文本当审查意见叫醒主模型；
// - 否则有一行恰为 PASS → 满足；
// - 两样都没有（空文本、只有一句开场白之类）→ null，按失败处理（kind=empty-text）。
//   4.32.0 起不再把「非空但无 PASS」当审查意见：agy 动作被拒时会只回一句开场白就结束（2026-11-26 实测，plan 模式下）。
function parseFactText(text) {
  if (typeof text !== 'string' || !text.trim()) return null
  const t = text.trim()
  const lines = t.split('\n').map((l) => l.trim().replace(/^[-*]\s*/, ''))
  if (lines.some((l) => /^(事实错误|漏答)[:：]/.test(l))) return { ok: false, reason: t }
  if (lines.some((l) => /^\**PASS\**[。.]?$/i.test(l))) return { ok: true, reason: '' }
  return null
}
function factVerdict(j) { return j && j.status === 'SUCCESS' ? parseFactText(j.response) : null }

function factEnv(parentEnv) {
  return { ...parentEnv, DEVKIT_STOP_AUDIT_CHILD: '1' }
}

function buildFactInput(hookInput, contextLines, template) {
  const pre = contextLines.length ? contextLines.join('\n') : '[user]: （本轮用户提问未能读取）'
  const cond = template.split('$CWD').join(hookInput.cwd || '（未知）')
  return `${SYS_FACT}\n\n<transcript>\n${pre}\n\n[assistant]: ${hookInput.last_assistant_message}\n</transcript>\n\n${cond}`
}

// 叫醒消息最前面的标识（4.27.0 用户要求）：让人与主模型一眼认出这是后台事实审查、是哪个模型审的。
function tag() { return `🔍【异步审查 · ${FACT_MODEL}（agy）】` }

// 叫醒主模型的消息：点明审的是哪条回复（审查耗时长，叫醒时主模型可能已经往下做了），要求先核实再改。
function wakeText(reason, last) {
  return `后台事实审查（${FACT_MODEL}，可读本机文件）审的是你开头为「${m.cut(last, 40)}」的那条回复，发现：\n${reason.trim()}\n` +
    '先用工具逐条核实。确有错：在回复开头写更正块（原说、实为、错因）后改正；核实后原文无误：用一两句说明依据，不必重写整条回复。'
}

// 超时叫醒的消息：只为让用户知道这条没审到。主模型不复查、不重写，附一句提示。
// 4.31.0：不要求「然后结束本轮」——叫醒与同步审查的叫醒撞在同一回合时，模型会把同步审查要求的整条重写丢掉。
function timeoutText(sec, last) {
  return `后台事实审查（${FACT_MODEL}）审你开头为「${m.cut(last, 40)}」的那条回复时超时（${sec} 秒没有出结果），这条回复没有经过事实审查。\n` +
    `不复查、不重写那条回复。告诉用户一句：「上一条回复（开头为「${m.cut(last, 20)}」）的后台事实审查超时，没有审到。」\n` +
    '本轮手上已有的事（其他 hook 要求的重写、用户的新消息）照常做完，这一句附在回复末尾；手上没别的事就只回这一句。'
}

// 失败原因：agy 的 JSON 里 status 不是 SUCCESS 时取 error / response；输出不合格式时摘 response 开头；
// 都没有就取 stderr 里以 error: 开头的那行（模型名错时 stderr 后面跟整张模型清单，最后一行没用），再没有就取最后一行。
function failDetail(kind, p) {
  try {
    const j = JSON.parse(p.stdout)
    if (j && j.status && j.status !== 'SUCCESS') {
      const msg = [j.error, j.response].find((x) => typeof x === 'string' && x.trim())
      return `status=${j.status}${msg ? `：${msg.trim()}` : ''}`
    }
    if (j && kind === 'empty-text') {
      const r = typeof j.response === 'string' ? j.response.trim() : ''
      return r ? `审查输出既没有 PASS 也没有问题行：${r}` : '审查输出为空'
    }
  } catch { /* stdout 不是 JSON */ }
  const lines = String(p.stderr || (p.error && (p.error.code || p.error.message)) || '').split('\n').map((l) => l.trim()).filter(Boolean)
  return lines.find((l) => /^error[:：]/i.test(l)) || lines.pop() || kind
}

// 非超时失败的叫醒消息：带报错原文，让用户知道是哪里坏了，主模型同样只附一句、手上的事照常做完。
function failText(detail, last) {
  return `后台事实审查（${FACT_MODEL}）审你开头为「${m.cut(last, 40)}」的那条回复时失败，报错：${m.cut(detail, 300)}\n这条回复没有经过事实审查。\n` +
    `不复查、不重写那条回复。告诉用户一句：「上一条回复（开头为「${m.cut(last, 20)}」）的后台事实审查失败，没有审到；报错：${m.cut(detail, 120)}」\n` +
    '本轮手上已有的事（其他 hook 要求的重写、用户的新消息）照常做完，这一句附在回复末尾；手上没别的事就只回这一句。'
}

async function main() {
  if (process.env.DEVKIT_STOP_AUDIT === 'off' || process.env.DEVKIT_STOP_AUDIT_CHILD === '1') return 0
  if (!factAuditEnabled(process.env)) return 0
  let hookInput
  try { hookInput = JSON.parse(fs.readFileSync(0, 'utf8')) } catch { return 0 }
  if (hookInput.stop_hook_active || !hookInput.last_assistant_message) return 0
  const agy = resolveAgy(process.env)
  if (!agy) return 0

  let contextLines = []
  try { if (hookInput.transcript_path) contextLines = m.buildContextLines(m.readTail(hookInput.transcript_path)) } catch { /* 只审最后一条回复 */ }
  const template = fs.readFileSync(path.join(__dirname, 'stop-fact-audit-prompt.txt'), 'utf8').trimEnd()
  const timeout = factTimeout(process.env)
  const t0 = Date.now()
  let failure = null
  const input = buildFactInput(hookInput, contextLines, template)
  const v = await m.judgeAsync(agy, input, {
    name: 'agy', timeout, audit: 'fact', args: factArgs(input, hookInput.cwd, timeout), env: factEnv(process.env),
    verdict: factVerdict, onFail: (kind, p) => { failure = { kind, p } },
  })
  const ms = Date.now() - t0
  const wake = !!(v && v.ok === false && typeof v.reason === 'string' && v.reason.trim())
  // 判超时的口径同 judgeAsync：子进程被 SIGTERM 后的退出码不定，只能按耗时判
  const timedOut = !v && (failure ? failure.kind === 'timeout' : ms >= timeout - 200)
  const failed = !v && !timedOut && !!failure
  m.logFailure('run', {}, ms, { stage: 'fact', blocked: wake, timed_out: timedOut, failed })
  const last = hookInput.last_assistant_message
  if (wake) { fs.writeSync(2, tag() + wakeText(v.reason, last)); return 2 }
  if (timedOut) { fs.writeSync(2, tag() + timeoutText(Math.round(timeout / 1000), last)); return 2 }
  if (failed) { fs.writeSync(2, tag() + failText(failDetail(failure.kind, failure.p), last)); return 2 }
  return 0
}

if (require.main === module) {
  main().then((code) => process.exit(code), () => process.exit(0))
}

module.exports = { parseFactText, factVerdict, FACT_EFFORT, FACT_MODEL, factArgs, factEnv, buildFactInput, wakeText, timeoutText, failText, failDetail, tag, factAuditEnabled, factTimeout, resolveAgy, FACT_TIMEOUT_MS }
