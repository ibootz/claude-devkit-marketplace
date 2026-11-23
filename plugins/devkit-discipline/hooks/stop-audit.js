// stop-audit.js — Stop 回合末出处审查（command 型，4.9.0 起替代 prompt 型挂载）
//
// 【为什么从 prompt 型改成 command 型】
// prompt 型 hook 判「不满足」时，Claude Code 把打回固定拼成 `[<整段提示词>]: <reason>`
// 显示在对话框里（2.1.311 二进制：`blockingError:`[${Pt}]: ${pt.data.reason}``，同一提示词
// 在会话里出现过后截到前 500 字），配置改不了。command 型的方括号里是命令行本身，
// 所以提示词搬进本脚本旁的 stop-audit-prompt.txt，由本脚本自己调判定模型，界面上只剩
// `[node .../stop-audit.js]: <reason>`。
//
// 【它做什么】
// 1. stop_hook_active=true（本轮已打回过一次）或 DEVKIT_STOP_AUDIT=off → 直接放行，不调模型。
// 2. 从 transcript_path 取本轮的用户提问（截 1500 字）与工具调用摘录（每条截 300 字，总量上限
//    CONTEXT_BUDGET，超出时保留最近的），4.19.0 起再带前 3 轮问答（用户提问截 600 字、助手最后
//    一段文字截 800 字，合计 6000 字，标明不在审查范围），连同 last_assistant_message 拼成与离线评测
//    （.scratch/conclusion-flip/eval/run_eval.py）同形的判定输入。
// 3. 调 `claude -p` 用 claude-sonnet-5-5 判定：订阅路让模型输出一行 JSON 文本 {ok, reason}（4.19.0 起，
//    省掉 --json-schema 多出的一轮工具调用）；第三方路仍取 structured_output。
// 3a. 4.17.0 起同时跑两路判定：stop-audit-prompt.txt 审「无据定论 / 能查没查」（判据与 4.16.0 相同；4.19.0 起去掉「最多 3 句」改为全部列出），
//    stop-audit-link-prompt.txt 审「编号没给链接」。两路并行起子进程，结果合成一条 reason。
//    分开跑是用户拍板 Q2-a：一条提示词只审一件事，两路各自可改可评测、互不牵连。（当初的依据
//    「并进同一次判定后前两类漏拦从 4/20 升到 7/20」复测不成立：只跑出处那一路也是 5/20，四次抽样
//    在 3～7 之间波动，见 README 4.17.0。）
//    CLICKABLE_PATHS 为 off / 0 / false（devkit-clickable-paths 的关闭开关）时不跑链接那一路。
// 3d. 4.20.0 起本脚本只走订阅（用户 2026-11-23 拍板 Q1-c：同步四路全留、全走 sonnet）。
//    DEVKIT_STOP_AUDIT_SETTINGS 不再影响这里，改由 stop-fact-audit.js 在后台用那份第三方 settings
//    审核心事实与漏答（asyncRewake，不阻塞本轮）。4.19.0 的「先第三方、失败回落订阅」已删。
// 3b. 4.17.0 起再加一路不经模型的词条核对（wiki-check.js）：本轮 Write / Edit 过的
//    claude-wiki 词条逐行查自写句子、逐段把摘录与出处文件逐字比对。找不到 claude 也照跑。
// 3b'. 4.19.0 起模型判定再加两路审 3.14：stop-audit-stuck-prompt.txt 审读者会卡住的内部名词没挂链接
//    也没写「AI 理解」或「未找到出处」，stop-audit-gloss-prompt.txt 审释义是自写而不是加「」的原文片段
//    （4.24.0 起以「AI 理解：」开头、不加「」的括注放行；4.25.0 起另审「释义只是提到」：加「」的括注只用到该词、
//    没说它是什么）。
//    DEVKIT_WIKI_AUDIT=off 关这两路与词条机械核对。
//    每轮只打回一次（stop_hook_active），打回后的重写不再审，所以每路一件事、四路并行
//    （总耗时≈最慢一路），各路提示词都要求命中项全部列出、不设上限，机械核对同样不截断。
// 3c. 4.19.0 起再加一路不经模型的链接核对（term-links.js）：最后一条回复里挂过本机链接的词，
//    别处裸写就打回（wiki 式：每次出现都可点）。CLICKABLE_PATHS 关掉时不跑。
// 4. ok=false 时 stdout 输出 {"decision":"block","reason":...}，harness 把 reason 交回主模型、
//    本轮继续；其余一切情形（判定满足、超时、claude 找不到、输出解析失败）放行。
//
// 【失灵时怎样】一律放行（fail-open），不会出现永久打回：最坏情形是本轮没审。判定子进程
// 超时、退出码非 0、输出解析不了时，原因追加到 $TMPDIR/devkit-stop-audit.log。
// 子进程带 DEVKIT_STOP_AUDIT_CHILD=1、cwd 设在临时目录、--setting-sources project（不读用户
// settings，也就不装用户启用的插件），双重防止判定会话自己再触发 Stop hook 形成递归。
// 2026-10-28 用 --debug-file 实测：这样起的判定会话不跑任何 hook（`0 hooks still pending`），
// 上下文里也没有用户级 CLAUDE.md 的内容。
//
// 【跨平台】claude 可执行文件按 PATH 逐项找 claude / claude.exe，再试 ~/.local/bin；
// 也可用 DEVKIT_STOP_AUDIT_CLAUDE 指定绝对路径。npm 装出的 claude.cmd 需经 shell 调起，
// 本脚本不支持，找不到可直接执行的二进制时放行。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync, spawn } = require('child_process')
const { wikiReason, turnWrites } = require('./wiki-check')
const { termLinksReason } = require('./term-links')

const MODEL = 'claude-sonnet-5-5'
// 4.19.0 用户拍板（2026-11-22「整体调大到90秒」）：单路等待 90 秒。4.20.0 起同步只走订阅、没有回落，
// hooks.json 里本脚本的 Stop timeout 相应从 160 改为 100 秒。
const CHILD_TIMEOUT_MS = 90000
const CHILD_API_TIMEOUT_MS = 85000
const THIRD_PARTY_MODEL = 'opus'
const CHILD_EFFORT = 'medium'
const LOG_MAX_BYTES = 4 * 1024 * 1024 // 每轮约 5～9 行、每行约 300 字节，够记几千轮
const CUT = 300
const CONTEXT_BUDGET = 12000
// 4.19.0 用户拍板 Q1-a：判定输入带上前 3 轮问答，审查模型才看得懂「Q1-a」这类简答、
// 认得出用户前几轮说过的词与助手前几轮给过的链接。本轮提问放宽到 1500 字。
const PROMPT_CUT = 1500
const PREV_ROUNDS = 3
const PREV_PROMPT_CUT = 600
const PREV_REPLY_CUT = 800
const PREV_BUDGET = 6000 // 3 轮都截满约 4300 字，这里是兜底
const MAX_TRANSCRIPT_BYTES = 8 * 1024 * 1024

// 与 harness 对 prompt 型 Stop hook 的包装逐字一致（离线评测按此形态跑出的误拦 / 漏拦数据才可沿用）
const SYS = 'You are evaluating a stop-condition hook in Claude Code. Read the conversation transcript carefully, then judge whether the user-provided condition is satisfied.'
const ASK = 'Based on the conversation transcript above, has the following stopping condition been satisfied? Answer based on transcript evidence only.'
const SCHEMA = JSON.stringify({
  type: 'object',
  properties: { ok: { type: 'boolean' }, reason: { type: 'string' }, impossible: { type: 'boolean' } },
  required: ['ok'],
})
const DISALLOWED = 'Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Agent,NotebookEdit'
// 4.19.0 用户拍板 Q1-a（2026-11-22）：订阅路去掉 --json-schema，让模型直接输出一行 JSON 文本。
// --json-schema 要多走一轮 StructuredOutput 工具调用（实测 2 轮 5.9～6.2 秒，文本 1 轮 4.8～5.5 秒）。
// 第三方路保留 --json-schema：gemini 经网关时纯文本只剩最后一段（实测），工具调用的入参是完整的。
const TEXT_TAIL = '\n\n只输出一行 JSON，不要代码块、不要任何其它文字：{"ok": true 或 false, "reason": "不满足时按上面要求的格式写，满足时写空串"}'

function cut(s, n = CUT) {
  s = String(s).replace(/\n/g, ' ⏎ ')
  return s.length <= n ? s : s.slice(0, n - 1) + '…'
}

function readTail(file) {
  const st = fs.statSync(file)
  if (st.size <= MAX_TRANSCRIPT_BYTES) return fs.readFileSync(file, 'utf8')
  const fd = fs.openSync(file, 'r')
  try {
    const buf = Buffer.alloc(MAX_TRANSCRIPT_BYTES)
    fs.readSync(fd, buf, 0, MAX_TRANSCRIPT_BYTES, st.size - MAX_TRANSCRIPT_BYTES)
    const s = buf.toString('utf8')
    return s.slice(s.indexOf('\n') + 1) // 丢掉被截断的首行
  } finally {
    fs.closeSync(fd)
  }
}

function userPromptText(row) {
  if (row.type !== 'user' || row.isMeta || row.isSidechain) return null
  // auto-compact 写入的摘要行也是 type=user，当成轮起点会把真实提问挤出判定输入
  if (row.isCompactSummary || row.isVisibleInTranscriptOnly) return null
  const c = row.message && row.message.content
  if (typeof c === 'string') {
    if (c.startsWith('<command-') || c.startsWith('<local-command')) return null
    return c
  }
  if (Array.isArray(c)) {
    // tool_result 行的 type 也是 'user'，不能当成轮起点
    if (c.some((b) => b && b.type === 'tool_result')) return null
    const t = c.filter((b) => b && b.type === 'text').map((b) => b.text).join('\n')
    return t || null
  }
  return null
}

function toolUseSummary(b) {
  const inp = b.input || {}
  if (b.name === 'Agent') return `${inp.description || ''} | ${inp.prompt || ''}`
  return inp.command || inp.file_path || inp.pattern || JSON.stringify(inp)
}

function toolResultText(b) {
  const c = b.content
  if (Array.isArray(c)) return c.map((x) => (x && typeof x.text === 'string' ? x.text : '')).join(' ')
  return c == null ? '' : String(c)
}

function assistantText(row) {
  const c = row.message && row.message.content
  if (typeof c === 'string') return c
  if (!Array.isArray(c)) return ''
  return c.filter((b) => b && b.type === 'text').map((b) => b.text).join('\n')
}

// 前几轮问答：每轮取用户提问与该轮助手最后一段文字回复，合计不超过 PREV_BUDGET，超出时丢最早的。
// 输出标签用「前轮」，与本轮的 [user] / [assistant] 区分。
function previousRounds(rows, starts) {
  const out = []
  let budget = PREV_BUDGET
  for (let k = starts.length - 2; k >= 0 && out.length < PREV_ROUNDS; k--) {
    const from = starts[k]
    const to = starts[k + 1]
    let reply = ''
    for (let i = to - 1; i > from; i--) {
      const r = rows[i]
      if (r.type !== 'assistant' || r.isSidechain) continue
      const t = assistantText(r)
      if (t.trim()) { reply = t; break }
    }
    // 没有文字回复的轮（被打断、重发）不占名额：审查模型从它读不到任何东西
    if (!reply) continue
    // 标签与本轮的 [user] / [assistant] 区分开，免得审查模型把前轮回复当成被审的那条
    const pair = [`[前轮 user]: ${cut(userPromptText(rows[from]), PREV_PROMPT_CUT)}`, `[前轮 assistant]: ${cut(reply, PREV_REPLY_CUT)}`]
    const len = pair[0].length + pair[1].length + 2
    if (budget - len < 0) break
    budget -= len
    out.unshift(pair)
  }
  return out
}

// 本轮 = 最后一条真实用户提问之后的所有行。返回 [前几轮问答..., user 行, ...工具调用与结果行]。
function buildContextLines(raw) {
  const rows = []
  for (const ln of raw.split('\n')) {
    if (!ln.trim()) continue
    try { rows.push(JSON.parse(ln)) } catch { /* 跳过损坏行 */ }
  }
  const starts = []
  for (let i = 0; i < rows.length; i++) if (userPromptText(rows[i]) != null) starts.push(i)
  if (!starts.length) return []
  const start = starts[starts.length - 1]
  const prompt = userPromptText(rows[start])
  const events = []
  for (const row of rows.slice(start + 1)) {
    if (row.isSidechain) continue
    const c = row.message && row.message.content
    if (!Array.isArray(c)) continue
    for (const b of c) {
      if (!b) continue
      if (row.type === 'assistant' && b.type === 'tool_use') events.push(`[tool_use ${b.name}]: ${cut(toolUseSummary(b))}`)
      else if (row.type === 'user' && b.type === 'tool_result') events.push(`[tool_result]: ${cut(toolResultText(b))}`)
    }
  }
  const head = `[user]: ${cut(prompt, PROMPT_CUT)}`
  let budget = CONTEXT_BUDGET - head.length
  const kept = []
  for (let i = events.length - 1; i >= 0; i--) {
    if (budget - events[i].length - 1 < 0) break
    budget -= events[i].length + 1
    kept.unshift(events[i])
  }
  const omitted = events.length - kept.length
  const cur = omitted > 0 ? [head, `[…本轮更早的 ${omitted} 条工具调用已省略…]`, ...kept] : [head, ...kept]
  const prev = previousRounds(rows, starts)
  if (!prev.length) return cur
  return [`[…前 ${prev.length} 轮问答，只供理解上下文，不在审查范围…]`, ...prev.flat(), '[…以下是本轮…]', ...cur]
}

function buildJudgeInput(hookInput, contextLines, promptTemplate) {
  const args = {
    session_id: hookInput.session_id,
    transcript_path: hookInput.transcript_path,
    cwd: hookInput.cwd,
    permission_mode: hookInput.permission_mode,
    hook_event_name: hookInput.hook_event_name || 'Stop',
    stop_hook_active: !!hookInput.stop_hook_active,
    last_assistant_message: hookInput.last_assistant_message,
  }
  const cond = promptTemplate.split('$ARGUMENTS').join(JSON.stringify(args))
  const pre = contextLines.length ? contextLines.join('\n') : '[user]: （本轮用户提问未能读取）'
  return `<transcript>\n${pre}\n\n[assistant]: ${hookInput.last_assistant_message}\n</transcript>\n\n${ASK}\n\nCondition: ${cond}`
}

// 链接类审查跟随 devkit-clickable-paths 的开关：规约不注入时，回合末也不要求链接。
function linkAuditEnabled(env) {
  const flag = String(env.CLICKABLE_PATHS || '').toLowerCase()
  return !(flag === 'off' || flag === '0' || flag === 'false')
}

// 返回本轮要跑的判定：[{ kind, template }]。kind=source 审出处，kind=link 审链接。
// 词条审查（3.14）单独一个开关：它比另两路更依赖语义判断，打回多了想关时不必连出处审查一起关。
function wikiAuditEnabled(env) {
  const flag = String(env.DEVKIT_WIKI_AUDIT || '').toLowerCase()
  return !(flag === 'off' || flag === '0' || flag === 'false')
}

function loadAudits(env) {
  const read = (f) => fs.readFileSync(path.join(__dirname, f), 'utf8').trimEnd()
  const audits = [{ kind: 'source', template: read('stop-audit-prompt.txt') }]
  if (linkAuditEnabled(env)) audits.push({ kind: 'link', template: read('stop-audit-link-prompt.txt') })
  if (wikiAuditEnabled(env)) {
    audits.push({ kind: 'stuck', template: read('stop-audit-stuck-prompt.txt') })
    audits.push({ kind: 'gloss', template: read('stop-audit-gloss-prompt.txt') })
  }
  return audits
}

// 多路打回合成一条：出处那路在前。各路 reason 原样拼接，中间空一行。
function mergeReasons(verdicts) {
  const order = { source: 0, link: 1, stuck: 2, gloss: 3 }
  return verdicts
    .filter((v) => v && v.verdict && v.verdict.ok === false && v.verdict.reason)
    .sort((a, b) => order[a.kind] - order[b.kind])
    .map((v) => v.verdict.reason.trim())
    .join('\n\n')
}

function isExecutable(p) {
  try {
    fs.accessSync(p, fs.constants.X_OK)
    return fs.statSync(p).isFile()
  } catch {
    return false
  }
}

function resolveClaude() {
  const override = process.env.DEVKIT_STOP_AUDIT_CLAUDE
  if (override) return isExecutable(override) ? override : null
  const names = process.platform === 'win32' ? ['claude.exe'] : ['claude']
  const dirs = (process.env.PATH || '').split(path.delimiter).filter(Boolean)
  dirs.push(path.join(os.homedir(), '.local', 'bin'))
  for (const d of dirs) {
    for (const n of names) {
      const p = path.join(d, n)
      if (isExecutable(p)) return p
    }
  }
  return null
}

// 主会话走第三方 Anthropic 兼容端点（ANTHROPIC_BASE_URL 指向 DeepSeek 等）时，子进程若原样继承，
// 判定请求会带着 claude-sonnet-5-5 发到第三方：要么被拒（2026-10-29 实测端点不可达时耗满 75 秒后
// 静默放行），要么被映射成第三方模型跑出未评测的判定，还把本轮摘录发给第三方。
// 用户拍板（2026-10-29，1a）：此时剥掉端点、凭据与模型覆盖，判定固定走本机的 Claude 登录；
// 本机没有 Claude 登录时子进程报错、本脚本按 fail-open 放行。官方地址与 Bedrock / Vertex 不动。
// 【4.20.0】本脚本的同步判定恒走这里的订阅路径；DEVKIT_STOP_AUDIT_SETTINGS 指的第三方端点只给
// stop-fact-audit.js 的后台事实审查用（见 thirdPartySettings）。
const THIRD_PARTY_KEYS = [
  'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY', 'ANTHROPIC_CUSTOM_HEADERS',
  'ANTHROPIC_MODEL', 'ANTHROPIC_SMALL_FAST_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL',
  'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL',
]

function isThirdPartyBaseUrl(u) {
  if (!u) return false
  try { return new URL(u).hostname !== 'api.anthropic.com' } catch { return true }
}

// 判定子进程不继承用户的推理强度与单次请求超时（用户拍板 2026-10-29，1b 改 medium）：
// 线上 157 次判定里 6 次耗满 75 秒，子进程继承了 settings 里的 API_TIMEOUT_MS=600000，
// 卡住的请求只能等外层超时杀掉；继承的 effort=high 也拉长了每次判定。
function childEnv(parentEnv) {
  const env = { ...parentEnv, DEVKIT_STOP_AUDIT_CHILD: '1', CLAUDE_CODE_EFFORT_LEVEL: CHILD_EFFORT, API_TIMEOUT_MS: String(CHILD_API_TIMEOUT_MS) }
  if (isThirdPartyBaseUrl(parentEnv.ANTHROPIC_BASE_URL)) {
    for (const k of THIRD_PARTY_KEYS) delete env[k]
  }
  return env
}

// 判定失败（超时、退出码非 0、输出解析不了）时放行，原因追加到本地日志，供事后查为什么没审。
// 日志超过 LOG_MAX_BYTES 时把现有文件改名为 <日志>.1（覆盖上一份）再重写，统计脚本两份一起读。
// DEVKIT_STOP_AUDIT_LOG 可改落点（测试用）。
function logFailure(kind, p, ms, extra = {}) {
  try {
    const file = process.env.DEVKIT_STOP_AUDIT_LOG || path.join(os.tmpdir(), 'devkit-stop-audit.log')
    const line = JSON.stringify({
      at: new Date().toISOString(), kind, ms, ...extra,
      status: p.status, signal: p.signal, error: p.error ? String(p.error.code || p.error.message) : undefined,
      stderr: p.stderr ? cut(p.stderr) : undefined, stdout: p.stdout ? cut(p.stdout) : undefined,
    }) + '\n'
    let size = 0
    try { size = fs.statSync(file).size } catch { /* 首次写 */ }
    if (size > LOG_MAX_BYTES) { fs.renameSync(file, file + '.1'); fs.writeFileSync(file, line) }
    else fs.appendFileSync(file, line)
  } catch { /* 日志写不了不影响放行 */ }
}

function judge(claudeBin, input) {
  const t0 = Date.now()
  const p = spawnSync(claudeBin, [
    '-p', '--model', MODEL, '--system-prompt', SYS,
    '--setting-sources', 'project',
    '--strict-mcp-config', '--disable-slash-commands', '--disallowedTools', DISALLOWED,
    '--no-session-persistence', '--output-format', 'json', '--json-schema', SCHEMA,
  ], {
    input,
    encoding: 'utf8',
    timeout: CHILD_TIMEOUT_MS,
    cwd: os.tmpdir(),
    env: childEnv(process.env),
    maxBuffer: 16 * 1024 * 1024,
  })
  const ms = Date.now() - t0
  if (p.error || p.status !== 0 || !p.stdout) {
    logFailure(p.error && p.error.code === 'ETIMEDOUT' ? 'timeout' : p.error ? 'spawn-error' : 'exit-nonzero', p, ms)
    return null
  }
  let j
  try { j = JSON.parse(p.stdout) } catch { logFailure('bad-json', p, ms); return null }
  if (!j.structured_output) logFailure('no-structured-output', p, ms)
  return j.structured_output || null
}

// --effort 写成参数而不只靠环境变量：第三方 settings 文件里的 CLAUDE_CODE_EFFORT_LEVEL 会盖掉子进程环境
// （实测 settings.gemini.json 设了 max，单路从 18 秒拖到 120 秒）。
const JUDGE_ARGS = [
  '-p', '--model', MODEL, '--system-prompt', SYS,
  '--setting-sources', 'project', '--effort', CHILD_EFFORT,
  '--strict-mcp-config', '--disable-slash-commands', '--disallowedTools', DISALLOWED,
  '--no-session-persistence', '--output-format', 'json',
]

// judge 的异步版：多路判定并行时用。失败语义与 judge 相同（记日志、返回 null）。
// 第三方 settings（4.19.0 引入；4.20.0 起只给 stop-fact-audit.js 的后台事实审查用，同步四路不再走）：
// 用户设 DEVKIT_STOP_AUDIT_SETTINGS=<settings 文件> 时，后台审查走该文件里的第三方端点。
// 模型用 opus 别名，由那份文件的 ANTHROPIC_DEFAULT_OPUS_MODEL 映射（用户拍板：用 opus 映射，不用 sonnet）。
// 父进程的 ANTHROPIC_* 一律剥掉，端点与凭据只认那份文件。文件读不到就当没开。
function thirdPartySettings(env) {
  const f = String(env.DEVKIT_STOP_AUDIT_SETTINGS || '').trim()
  if (!f) return null
  const abs = f.startsWith('~/') ? path.join(os.homedir(), f.slice(2)) : f
  try { fs.accessSync(abs, fs.constants.R_OK); return abs } catch { return null }
}

function routeArgs(settings) {
  if (!settings) return JUDGE_ARGS
  const a = JUDGE_ARGS.slice()
  a[a.indexOf('--model') + 1] = THIRD_PARTY_MODEL
  a.splice(1, 0, '--settings', settings)
  a.push('--json-schema', SCHEMA)
  return a
}

// 订阅路的判定是 result 里的一行 JSON 文本。容忍代码块围栏与前后多余文字：取第一个 { 到最后一个 }。
// ok 不是布尔值就当解析失败（返回 null，按 fail-open 放行并记日志）。
function parseVerdictText(text) {
  if (typeof text !== 'string') return null
  const t = text.trim()
  const i = t.indexOf('{')
  const k = t.lastIndexOf('}')
  if (i < 0 || k <= i) return null
  let v
  try { v = JSON.parse(t.slice(i, k + 1)) } catch { return null }
  if (!v || typeof v.ok !== 'boolean') return null
  return { ok: v.ok, reason: typeof v.reason === 'string' ? v.reason : '' }
}

// 从 claude -p 的 json 输出取判定：第三方路读 structured_output，订阅路解析 result 文本。
function verdictOf(j, structured) {
  if (structured) return j.structured_output || null
  return parseVerdictText(j.result)
}

function routeEnv(parentEnv, settings) {
  const env = childEnv(parentEnv)
  if (settings) for (const k of THIRD_PARTY_KEYS) delete env[k]
  return env
}

// 成功判定也记一行（模型、耗时、走哪条路），用来算真实失败率；4.19.0 前只记失败。
function logOk(route, ms, j, audit) {
  logFailure('ok', { status: 0 }, ms, { route, audit, models: Object.keys((j && j.modelUsage) || {}) })
}

// route.args / route.env 给了就用它们（后台事实审查自带工具、提示词与单次请求超时），否则按 settings 取同步判定的参数与环境。
function judgeAsync(claudeBin, input, route = { settings: null, timeout: CHILD_TIMEOUT_MS }) {
  const timeout = route.timeout || CHILD_TIMEOUT_MS
  const routeName = route.settings ? 'third-party' : 'subscription'
  return new Promise((resolve) => {
    const t0 = Date.now()
    let child
    let structured = false
    try {
      child = spawn(claudeBin, route.args || routeArgs(route.settings), { cwd: os.tmpdir(), env: route.env || routeEnv(process.env, route.settings), timeout })
      structured = !!route.settings
    } catch (e) {
      logFailure('spawn-error', { error: e }, 0, { route: routeName, audit: route.audit })
      return resolve(null)
    }
    let stdout = ''
    let stderr = ''
    let error = null
    child.stdout.setEncoding('utf8').on('data', (d) => { stdout += d })
    child.stderr.setEncoding('utf8').on('data', (d) => { stderr += d })
    child.on('error', (e) => { error = e })
    child.stdin.on('error', () => { /* 子进程提前退出时写 stdin 会 EPIPE，按退出结果判 */ })
    child.stdin.end(structured ? input : input + TEXT_TAIL)
    child.on('close', (status, signal) => {
      const ms = Date.now() - t0
      const p = { status, signal, stdout, stderr, error }
      if (error || status !== 0 || !stdout) {
        // claude 收到 SIGTERM 后自己以 143 退出，signal 为 null，只能按耗时判超时
        logFailure(ms >= timeout - 200 ? 'timeout' : error ? 'spawn-error' : 'exit-nonzero', p, ms, { route: routeName, audit: route.audit })
        return resolve(null)
      }
      let j
      try { j = JSON.parse(stdout) } catch { logFailure('bad-json', p, ms, { route: routeName, audit: route.audit }); return resolve(null) }
      const v = verdictOf(j, structured)
      if (!v) logFailure(structured ? 'no-structured-output' : 'bad-verdict-text', p, ms, { route: routeName, audit: route.audit })
      else logOk(routeName, ms, j, route.audit)
      resolve(v)
    })
  })
}

// 并行跑全部判定，返回 [{ kind, verdict }]。评测脚本也走这里。4.20.0 起恒走订阅。
async function runAudits(claudeBin, hookInput, contextLines, env) {
  const audits = loadAudits(env)
  const verdicts = await Promise.all(audits.map((a) => judgeAsync(claudeBin, buildJudgeInput(hookInput, contextLines, a.template), { settings: null, timeout: CHILD_TIMEOUT_MS, audit: a.kind }).catch(() => null)))
  return audits.map((a, i) => ({ kind: a.kind, verdict: verdicts[i] }))
}

async function main() {
  if (process.env.DEVKIT_STOP_AUDIT === 'off' || process.env.DEVKIT_STOP_AUDIT_CHILD === '1') return
  let hookInput
  try { hookInput = JSON.parse(fs.readFileSync(0, 'utf8')) } catch { return }
  if (hookInput.stop_hook_active || !hookInput.last_assistant_message) return

  let contextLines = []
  let raw = ''
  try {
    if (hookInput.transcript_path) {
      raw = readTail(hookInput.transcript_path)
      contextLines = buildContextLines(raw)
    }
  } catch { /* 读不到 transcript 就只审最后一条回复，词条只核回复里链到的 */ }
  let wiki = ''
  try { if (wikiAuditEnabled(process.env)) wiki = wikiReason(raw, userPromptText, hookInput.last_assistant_message) } catch { /* 词条核对失灵就不核 */ }
  let terms = ''
  try {
    if (linkAuditEnabled(process.env)) {
      let written = null
      try { if (raw) written = turnWrites(raw, userPromptText).all } catch { /* 读不出本轮写过哪些文件就不查快照 */ }
      terms = termLinksReason(hookInput.last_assistant_message, written)
    }
  } catch { /* 失灵就不核 */ }

  const claudeBin = resolveClaude()
  const t0 = Date.now()
  const judged = claudeBin ? mergeReasons(await runAudits(claudeBin, hookInput, contextLines, process.env)) : ''
  const reason = [judged, terms, wiki].filter(Boolean).join('\n\n')
  // 整次审查一行（kind=run，stage=sync）：总耗时、是否打回，供 scripts/stop-audit-stats.py 统计
  if (claudeBin) logFailure('run', {}, Date.now() - t0, { stage: 'sync', blocked: !!reason })
  if (!reason) return
  // 同步写：紧接着 process.exit(0)，异步的 stdout.write 写管道时可能被截断
  fs.writeSync(1, JSON.stringify({ decision: 'block', reason }))
}

if (require.main === module) {
  main().catch(() => { /* fail-open */ }).finally(() => process.exit(0))
}

module.exports = { SCHEMA, THIRD_PARTY_MODEL, CHILD_EFFORT, readTail, logFailure, thirdPartySettings, routeArgs, parseVerdictText, TEXT_TAIL, routeEnv, wikiAuditEnabled, loadAudits, mergeReasons, runAudits, judgeAsync, linkAuditEnabled, buildContextLines, buildJudgeInput, userPromptText, previousRounds, cut, resolveClaude, judge, childEnv }
