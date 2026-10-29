#!/usr/bin/env node
// stop-audit-verify.js — stop-audit.js 的回归套件
//
// 用法：node plugins/devkit-discipline/test/stop-audit-verify.js
// 退出码 0 = 全绿，1 = 有用例失败。
//
// 判定模型用桩代替（DEVKIT_STOP_AUDIT_CLAUDE 指向一个按环境变量吐固定 structured_output 的
// node 脚本），只测本脚本自己的分支：放行条件、打回输出形态、fail-open、轮起点与摘录。
// 判定质量不在这里测，见 README 4.9.0 的离线评测。用 spawnSync 喂 stdin，不经 shell。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')

const HOOK = path.join(__dirname, '..', 'hooks', 'stop-audit.js')
const { buildContextLines, buildJudgeInput } = require(HOOK)
const DIR = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'wd-stop-audit-test-')))

let pass = 0
let fail = 0

function check(name, cond, detail) {
  if (cond) {
    pass += 1
  } else {
    fail += 1
    console.log(`FAIL ${name}${detail ? `\n     ${detail}` : ''}`)
  }
}

// 桩：STUB_MODE=block 吐 ok=false，pass 吐 ok=true，garbage 吐非 JSON，exit1 以退出码 1 结束；
// 每次被调用都在 STUB_LOG 追加一行，用来断言「没调模型」。
const STUB = path.join(DIR, 'stub-claude')
fs.writeFileSync(STUB, `#!/usr/bin/env node
const fs = require('fs')
fs.readFileSync(0)
if (process.env.STUB_LOG) fs.appendFileSync(process.env.STUB_LOG, 'called\\n')
const m = process.env.STUB_MODE
if (m === 'exit1') process.exit(1)
if (m === 'garbage') { process.stdout.write('not json'); process.exit(0) }
const so = m === 'block' ? { ok: false, reason: '回合末出处审查：\\n- 测试' } : { ok: true }
process.stdout.write(JSON.stringify({ structured_output: so }))
`)
fs.chmodSync(STUB, 0o755)

function run(input, env = {}) {
  const log = path.join(DIR, `log-${pass + fail}`)
  const r = spawnSync('node', [HOOK], {
    input: typeof input === 'string' ? input : JSON.stringify(input),
    encoding: 'utf8',
    env: { ...process.env, DEVKIT_STOP_AUDIT: '', DEVKIT_STOP_AUDIT_CHILD: '', DEVKIT_STOP_AUDIT_CLAUDE: STUB, STUB_LOG: log, ...env },
  })
  return { status: r.status, stdout: r.stdout, called: fs.existsSync(log) }
}

const base = { hook_event_name: 'Stop', stop_hook_active: false, last_assistant_message: '结论：X 不存在。' }

// ---- 放行与打回 ----
{
  const r = run(base, { STUB_MODE: 'block' })
  let j = null
  try { j = JSON.parse(r.stdout) } catch { /* 下面断言会报 */ }
  check('判不满足 → stdout 输出 decision=block', r.status === 0 && j && j.decision === 'block', r.stdout)
  check('打回 reason 原样取自判定结果', j && j.reason === '回合末出处审查：\n- 测试', r.stdout)
  check('打回输出里没有提示词原文', !r.stdout.includes('要判定的条件'), r.stdout)
}
{
  const r = run(base, { STUB_MODE: 'pass' })
  check('判满足 → 无输出放行', r.status === 0 && r.stdout === '' && r.called, r.stdout)
}
{
  const r = run({ ...base, stop_hook_active: true }, { STUB_MODE: 'block' })
  check('stop_hook_active=true → 不调模型直接放行', r.stdout === '' && !r.called)
}
{
  const r = run(base, { STUB_MODE: 'block', DEVKIT_STOP_AUDIT: 'off' })
  check('DEVKIT_STOP_AUDIT=off → 不调模型直接放行', r.stdout === '' && !r.called)
}
{
  const r = run(base, { STUB_MODE: 'block', DEVKIT_STOP_AUDIT_CHILD: '1' })
  check('判定子进程里 → 不递归', r.stdout === '' && !r.called)
}
{
  const r = run({ ...base, last_assistant_message: '' }, { STUB_MODE: 'block' })
  check('没有 last_assistant_message → 放行', r.stdout === '' && !r.called)
}

// ---- fail-open ----
for (const [name, input, env] of [
  ['stdin 不是 JSON', 'oops', { STUB_MODE: 'block' }],
  ['判定输出不是 JSON', base, { STUB_MODE: 'garbage' }],
  ['判定进程退出码非 0', base, { STUB_MODE: 'exit1' }],
  ['claude 路径不存在', base, { STUB_MODE: 'block', DEVKIT_STOP_AUDIT_CLAUDE: path.join(DIR, 'nope') }],
  ['transcript_path 不存在', { ...base, transcript_path: path.join(DIR, 'nope.jsonl') }, { STUB_MODE: 'pass' }],
]) {
  const r = run(input, env)
  check(`fail-open：${name} → 退出码 0 且不打回`, r.status === 0 && !r.stdout.includes('"block"'), `${r.status} ${r.stdout}`)
}

// ---- 轮起点与摘录 ----
const user = (content, extra = {}) => ({ type: 'user', message: { role: 'user', content }, ...extra })
const toolUse = (name, input) => ({ type: 'assistant', message: { role: 'assistant', content: [{ type: 'tool_use', id: 't', name, input }] } })
const toolResult = (content) => user([{ type: 'tool_result', tool_use_id: 't', content }])
const jsonl = (rows) => rows.map((r) => JSON.stringify(r)).join('\n') + '\n'
{
  const L = buildContextLines(jsonl([
    user('上一轮的问题'),
    toolUse('Bash', { command: 'ls old' }),
    toolResult('old'),
    user('本轮的问题'),
    toolUse('Bash', { command: 'ls /tmp' }),
    toolResult([{ type: 'text', text: 'a\nb' }]),
    user('<system-reminder>注入</system-reminder>', { isMeta: true }),
    toolUse('Agent', { description: '查 X', prompt: '去查' }),
    toolResult('done'),
  ]))
  check('轮起点取最后一条真实用户提问', L[0] === '[user]: 本轮的问题', L[0])
  check('tool_result 行与 isMeta 行不当轮起点', !L.join('\n').includes('上一轮') && !L.join('\n').includes('注入'), L.join(' | '))
  check('tool_use 摘录命令', L.includes('[tool_use Bash]: ls /tmp'), L.join(' | '))
  check('tool_result 数组形态拼成文本、换行转 ⏎', L.includes('[tool_result]: a ⏎ b'), L.join(' | '))
  check('Agent 摘录 description | prompt', L.includes('[tool_use Agent]: 查 X | 去查'), L.join(' | '))
}
{
  const L = buildContextLines(jsonl([user([{ type: 'text', text: '带图的提问' }, { type: 'image', source: {} }])]))
  check('数组形态的用户提问（带图）可作轮起点', L[0] === '[user]: 带图的提问', L.join(' | '))
}
{
  const rows = [user('问')]
  for (let i = 0; i < 200; i++) rows.push(toolUse('Bash', { command: `cmd-${i} ${'x'.repeat(200)}` }))
  const L = buildContextLines(jsonl(rows))
  check('超出预算时保留最近的、标出省略条数', L[1].startsWith('[…本轮更早的') && L[L.length - 1].includes('cmd-199'), L[1])
  check('摘录总量不超过预算', L.join('\n').length <= 12000 + 40, String(L.join('\n').length))
}
{
  check('无用户提问时返回空', buildContextLines(jsonl([toolResult('x')])).length === 0)
  check('损坏行被跳过', buildContextLines('not json\n' + jsonl([user('问')]))[0] === '[user]: 问')
}
{
  const s = buildJudgeInput({ ...base, cwd: '/p' }, ['[user]: 问'], 'A $ARGUMENTS B $ARGUMENTS')
  check('判定输入：$ARGUMENTS 全部替换', !s.includes('$ARGUMENTS') && s.split('last_assistant_message').length === 3, s)
  check('判定输入：带 harness 同款问句与 transcript 包装', s.startsWith('<transcript>\n[user]: 问\n\n[assistant]: 结论：X 不存在。\n</transcript>') && s.includes('Condition: A {'), s.slice(0, 200))
}

{
  const { childEnv } = require(HOOK)
  const third = { PATH: '/bin', ANTHROPIC_BASE_URL: 'https://api.deepseek.com/anthropic', ANTHROPIC_AUTH_TOKEN: 't', ANTHROPIC_API_KEY: 'k', ANTHROPIC_MODEL: 'deepseek-chat', ANTHROPIC_DEFAULT_SONNET_MODEL: 'deepseek-chat' }
  const e1 = childEnv(third)
  check('第三方端点 → 剥掉端点、凭据与模型覆盖', !('ANTHROPIC_BASE_URL' in e1) && !('ANTHROPIC_AUTH_TOKEN' in e1) && !('ANTHROPIC_API_KEY' in e1) && !('ANTHROPIC_MODEL' in e1) && !('ANTHROPIC_DEFAULT_SONNET_MODEL' in e1), JSON.stringify(e1))
  check('第三方端点 → 其它变量与防递归标记保留', e1.PATH === '/bin' && e1.DEVKIT_STOP_AUDIT_CHILD === '1', JSON.stringify(e1))
  const e2 = childEnv({ ANTHROPIC_BASE_URL: 'https://api.anthropic.com', ANTHROPIC_API_KEY: 'k' })
  check('官方地址 → 原样继承', e2.ANTHROPIC_BASE_URL === 'https://api.anthropic.com' && e2.ANTHROPIC_API_KEY === 'k', JSON.stringify(e2))
  const e3 = childEnv({ ANTHROPIC_API_KEY: 'k' })
  check('未设端点 → API key 原样继承', e3.ANTHROPIC_API_KEY === 'k', JSON.stringify(e3))
  check('端点写错（解析不了）→ 按第三方处理', !('ANTHROPIC_BASE_URL' in childEnv({ ANTHROPIC_BASE_URL: 'not a url' })))
}

fs.rmSync(DIR, { recursive: true, force: true })
console.log(`stop-audit: ${pass} passed, ${fail} failed`)
process.exit(fail === 0 ? 0 : 1)
