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
// 2. 从 transcript_path 取本轮的用户提问与工具调用摘录（每条截 300 字，总量上限
//    CONTEXT_BUDGET，超出时保留最近的），连同 last_assistant_message 拼成与离线评测
//    （.scratch/conclusion-flip/eval/run_eval.py）同形的判定输入。
// 3. 调 `claude -p` 用 claude-sonnet-5-5 判定，取 structured_output 的 {ok, reason}。
// 4. ok=false 时 stdout 输出 {"decision":"block","reason":...}，harness 把 reason 交回主模型、
//    本轮继续；其余一切情形（判定满足、超时、claude 找不到、输出解析失败）放行。
//
// 【失灵时怎样】一律放行（fail-open），不会出现永久打回：最坏情形是本轮没审。
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
const { spawnSync } = require('child_process')

const MODEL = 'claude-sonnet-5-5'
const CHILD_TIMEOUT_MS = 75000
const CUT = 300
const CONTEXT_BUDGET = 12000
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

// 本轮 = 最后一条真实用户提问之后的所有行。返回 [user 行, ...工具调用与结果行]。
function buildContextLines(raw) {
  const rows = []
  for (const ln of raw.split('\n')) {
    if (!ln.trim()) continue
    try { rows.push(JSON.parse(ln)) } catch { /* 跳过损坏行 */ }
  }
  let start = -1
  let prompt = null
  for (let i = rows.length - 1; i >= 0; i--) {
    const t = userPromptText(rows[i])
    if (t != null) { start = i; prompt = t; break }
  }
  if (start < 0) return []
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
  const head = `[user]: ${cut(prompt)}`
  let budget = CONTEXT_BUDGET - head.length
  const kept = []
  for (let i = events.length - 1; i >= 0; i--) {
    if (budget - events[i].length - 1 < 0) break
    budget -= events[i].length + 1
    kept.unshift(events[i])
  }
  const omitted = events.length - kept.length
  return omitted > 0 ? [head, `[…本轮更早的 ${omitted} 条工具调用已省略…]`, ...kept] : [head, ...kept]
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

function judge(claudeBin, input) {
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
    env: { ...process.env, DEVKIT_STOP_AUDIT_CHILD: '1' },
    maxBuffer: 16 * 1024 * 1024,
  })
  if (p.error || p.status !== 0 || !p.stdout) return null
  const j = JSON.parse(p.stdout)
  return j.structured_output || null
}

function main() {
  if (process.env.DEVKIT_STOP_AUDIT === 'off' || process.env.DEVKIT_STOP_AUDIT_CHILD === '1') return
  let hookInput
  try { hookInput = JSON.parse(fs.readFileSync(0, 'utf8')) } catch { return }
  if (hookInput.stop_hook_active || !hookInput.last_assistant_message) return

  const promptTemplate = fs.readFileSync(path.join(__dirname, 'stop-audit-prompt.txt'), 'utf8').trimEnd()
  let contextLines = []
  try {
    if (hookInput.transcript_path) contextLines = buildContextLines(readTail(hookInput.transcript_path))
  } catch { /* 读不到 transcript 就只审最后一条回复 */ }

  const claudeBin = resolveClaude()
  if (!claudeBin) return
  let verdict = null
  try { verdict = judge(claudeBin, buildJudgeInput(hookInput, contextLines, promptTemplate)) } catch { return }
  if (!verdict || verdict.ok !== false || !verdict.reason) return
  // 同步写：紧接着 process.exit(0)，异步的 stdout.write 写管道时可能被截断
  fs.writeSync(1, JSON.stringify({ decision: 'block', reason: verdict.reason }))
}

if (require.main === module) {
  try { main() } catch { /* fail-open */ }
  process.exit(0)
}

module.exports = { buildContextLines, buildJudgeInput, userPromptText, cut, resolveClaude, judge }
