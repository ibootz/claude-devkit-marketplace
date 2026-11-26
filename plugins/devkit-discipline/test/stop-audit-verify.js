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

// 桩：STUB_MODE=block 吐 ok=false，pass 吐 ok=true，garbage 吐非 JSON，exit1 以退出码 1 结束，
// badtext 吐合法外层 JSON 但 result 里没有判定；带 --json-schema 时吐 structured_output，否则吐 result 文本；
// 每次被调用都在 STUB_LOG 追加一行，用来断言「没调模型」。
const STUB = path.join(DIR, 'stub-claude')
fs.writeFileSync(STUB, `#!/usr/bin/env node
const fs = require('fs')
const inp = fs.readFileSync(0, 'utf8')
const kind = inp.includes('回合末后台事实审查') ? 'fact' : inp.includes('回合末链接审查') ? 'link' : inp.includes('回合末卡点审查') ? 'stuck' : inp.includes('回合末释义审查') ? 'gloss' : 'source'
const argv = process.argv.slice(2)
const third = argv.includes('--settings')
if (process.env.STUB_ROUTE_LOG) fs.appendFileSync(process.env.STUB_ROUTE_LOG, kind + ':' + (third ? 'third:' + argv[argv.indexOf('--model') + 1] : 'sub:' + argv[argv.indexOf('--model') + 1]) + ':' + (process.env.ANTHROPIC_BASE_URL || '-') + '\\n')
if (process.env.STUB_LOG) fs.appendFileSync(process.env.STUB_LOG, kind + '\\n')
if (process.env.STUB_ARGV_LOG) fs.appendFileSync(process.env.STUB_ARGV_LOG, JSON.stringify({ kind, argv, apiTimeout: process.env.API_TIMEOUT_MS, base: process.env.ANTHROPIC_BASE_URL || null, child: process.env.DEVKIT_STOP_AUDIT_CHILD, watchdog: process.env.CLAUDE_CODE_RETRY_WATCHDOG || null, maxRetries: process.env.CLAUDE_CODE_MAX_RETRIES || null, input: inp }) + '\\n')
if (third && process.env.STUB_THIRD) { const t = process.env.STUB_THIRD; if (t === 'exit1') process.exit(1); if (t === 'garbage') { process.stdout.write('not json'); process.exit(0) } }
const m = kind === 'source' ? process.env.STUB_MODE : (process.env['STUB_' + kind.toUpperCase()] || 'pass')
if (m === 'exit1') process.exit(1)
if (m === 'apierr') { process.stdout.write(JSON.stringify({ type: 'result', is_error: true, result: 'API Error: 503 No available channel for model gemini-4-neon under group default (distributor)' })); process.exit(1) }
if (m === 'sleep') Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10000)
if (m === 'garbage') { process.stdout.write('not json'); process.exit(0) }
const R = { fact: '事实错误：回复说「X 不存在」，但 /tmp/a.js:3 写的是「function X」', source: '回合末出处审查：\\n- 测试', link: '回合末链接审查：\\n- 链接', stuck: '回合末卡点审查：\\n- 卡点', gloss: '回合末释义审查：\\n- 释义' }
const so = m === 'block' ? { ok: false, reason: R[kind] } : { ok: true, reason: '' }
if (process.env.STUB_TAIL_LOG) fs.appendFileSync(process.env.STUB_TAIL_LOG, (inp.includes('只输出一行 JSON') ? 'tail' : 'notail') + ':' + (argv.includes('--json-schema') ? 'schema' : 'text') + '\\n')
if (m === 'badtext') { process.stdout.write(JSON.stringify({ result: '我认为满足条件。' })); process.exit(0) }
if (kind === 'fact' && !argv.includes('--json-schema')) { process.stdout.write(JSON.stringify({ result: m === 'empty' ? '' : m === 'block' ? R.fact : 'PASS' })); process.exit(0) }
if (argv.includes('--json-schema')) process.stdout.write(JSON.stringify({ structured_output: so }))
else process.stdout.write(JSON.stringify({ result: '\\u0060\\u0060\\u0060json\\n' + JSON.stringify(so) + '\\n\\u0060\\u0060\\u0060' }))
`)
fs.chmodSync(STUB, 0o755)

function run(input, env = {}) {
  const log = path.join(DIR, `log-${pass + fail}`)
  const r = spawnSync('node', [HOOK], {
    input: typeof input === 'string' ? input : JSON.stringify(input),
    encoding: 'utf8',
    env: { ...process.env, DEVKIT_STOP_AUDIT: '', DEVKIT_STOP_AUDIT_CHILD: '', DEVKIT_STOP_AUDIT_CLAUDE: STUB, DEVKIT_STOP_AUDIT_LOG: path.join(DIR, 'default-audit.log'), STUB_LOG: log, ...env },
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
  const cur = L.slice(L.indexOf('[…以下是本轮…]') + 1)
  check('轮起点取最后一条真实用户提问', cur[0] === '[user]: 本轮的问题', L.join(' | '))
  check('tool_result 行与 isMeta 行不当轮起点', !cur.join('\n').includes('上一轮') && !L.join('\n').includes('注入'), L.join(' | '))
  check('上一轮的工具调用不进摘录', !L.join('\n').includes('ls old'), L.join(' | '))
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
// ---- 前几轮问答（4.19.0 Q1-a）----
const said = (text) => ({ type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text }] } })
{
  const rows = []
  for (let i = 1; i <= 5; i++) rows.push(user(`第${i}问`), said(`第${i}答-中间`), toolUse('Bash', { command: 'x' }), toolResult('y'), said(`第${i}答-最终`))
  rows.push(user('本轮'), toolUse('Bash', { command: 'ls' }))
  const L = buildContextLines(jsonl(rows))
  const s = L.join('\n')
  check('前几轮：只带最近 3 轮、标明不在审查范围', L[0] === '[…前 3 轮问答，只供理解上下文，不在审查范围…]' && !s.includes('第2问') && s.includes('第3问') && s.includes('第5问'), L.join(' | '))
  check('前几轮：每轮取助手最后一段文字', s.includes('[前轮 assistant]: 第4答-最终') && !s.includes('第4答-中间'), L.join(' | '))
  check('前几轮：按时间正序、本轮在最后', L.indexOf('[前轮 user]: 第3问') < L.indexOf('[前轮 user]: 第5问') && L.indexOf('[…以下是本轮…]') < L.indexOf('[user]: 本轮'), L.join(' | '))
}
{
  const L = buildContextLines(jsonl([user('旧'), said('x'.repeat(5000)), user('q'.repeat(3000))]))
  const s = L.join('\n')
  check('前几轮：助手回复截到 800 字', L.find((l) => l.startsWith('[前轮 assistant]:')).length <= '[前轮 assistant]: '.length + 800, s.length)
  check('本轮提问截到 1500 字', L.find((l) => l.startsWith('[user]: q')).length === '[user]: '.length + 1500, s.length)
}
{
  const rows = []
  for (let i = 0; i < 3; i++) rows.push(user(`问${i}` + 'p'.repeat(700)), said(`答${i}` + 'r'.repeat(900)))
  rows.push(user('本轮'))
  const L = buildContextLines(jsonl(rows))
  const prev = L.slice(1, L.indexOf('[…以下是本轮…]')).join('\n')
  check('前几轮：3 轮都截满时合计仍在 6000 字内', prev.length <= 6000 && prev.includes('问0') && prev.includes('问2'), prev.length)
}
{
  const L = buildContextLines(jsonl([user('有答的一问'), said('答了'), user('被打断的一问'), toolUse('Bash', { command: 'ls' }), user('本轮')]))
  check('前几轮：没有文字回复的轮不占名额', L[0] === '[…前 1 轮问答，只供理解上下文，不在审查范围…]' && L.includes('[前轮 user]: 有答的一问') && !L.join('').includes('被打断'), L.join(' | '))
  const one = buildContextLines(jsonl([user('只有一问')]))
  check('只有本轮时不加前几轮标记', one[0] === '[user]: 只有一问' && one.length === 1, one.join(' | '))
}
{
  const L = buildContextLines(jsonl([user('真实提问'), toolUse('Bash', { command: 'a' }), user('This session is being continued…', { isCompactSummary: true, isVisibleInTranscriptOnly: true }), toolUse('Bash', { command: 'b' })]))
  check('auto-compact 摘要行不当轮起点', L[0] === '[user]: 真实提问' && L.includes('[tool_use Bash]: b'), L.join(' | '))
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
  const e4 = childEnv({ CLAUDE_CODE_EFFORT_LEVEL: 'high', API_TIMEOUT_MS: '600000' })
  check('子进程推理强度固定 medium、不继承用户的 high', e4.CLAUDE_CODE_EFFORT_LEVEL === 'medium', JSON.stringify(e4))
  check('子进程单次请求超时固定 85 秒、不继承用户的 600 秒', e4.API_TIMEOUT_MS === '85000', JSON.stringify(e4))
}

// ---- 4.17.0 两路并行判定：出处 + 链接 ----
{
  const { loadAudits, mergeReasons } = require(HOOK)
  const on = loadAudits({})
  check('默认跑四路：source、link、stuck、gloss', on.map((a) => a.kind).join(',') === 'source,link,stuck,gloss')
  check('卡点那路只审卡点、带 $ARGUMENTS', on[2].template.includes('回合末卡点审查') && on[2].template.includes('$ARGUMENTS') && !on[2].template.includes('释义自写：「'))
  check('释义那路只审释义、带 $ARGUMENTS', on[3].template.includes('回合末释义审查') && on[3].template.includes('$ARGUMENTS') && !on[3].template.includes('卡点没挂：'))
  check('四路提示词都要求全部列出、不再有条数上限', on.every((a) => a.template.includes('只跑一次') && a.template.includes('不设上限') && !a.template.includes('最多')))
  for (const v of ['off', '0', 'false']) {
    check(`DEVKIT_WIKI_AUDIT=${v} → 去掉卡点、释义两路`, loadAudits({ DEVKIT_WIKI_AUDIT: v }).map((a) => a.kind).join(',') === 'source,link')
  }
  check('出处那路提示词不含链接类', !on[0].template.includes('编号没给链接') && on[0].template.includes('二、能查没查'))
  check('链接那路提示词只审链接、带 $ARGUMENTS', on[1].template.includes('回合末链接审查') && on[1].template.includes('$ARGUMENTS') && !on[1].template.includes('能查没查'))
  for (const v of ['off', 'OFF', '0', 'false']) {
    const off = loadAudits({ CLICKABLE_PATHS: v })
    check(`CLICKABLE_PATHS=${v} → 去掉链接那路`, off.map((a) => a.kind).join(',') === 'source,stuck,gloss')
  }
  check('CLICKABLE_PATHS=on → 四路', loadAudits({ CLICKABLE_PATHS: 'on' }).length === 4)
  const K = (kind, r) => ({ kind, verdict: { ok: false, reason: r } })
  check('合并：四路都打回 → 按出处、链接、卡点、释义排', mergeReasons([K('gloss', 'D'), K('stuck', 'C'), K('link', 'B'), K('source', 'A')]) === 'A\n\nB\n\nC\n\nD')
  const S = { kind: 'source', verdict: { ok: false, reason: 'A' } }
  const L = { kind: 'link', verdict: { ok: false, reason: 'B' } }
  check('合并：两路都打回 → 出处在前、空一行', mergeReasons([L, S]) === 'A\n\nB')
  check('合并：一路放行、一路失败 → 空', mergeReasons([{ kind: 'source', verdict: { ok: true } }, { kind: 'link', verdict: null }]) === '')
  check('合并：出处失败、链接打回 → 只有链接', mergeReasons([{ kind: 'source', verdict: null }, L]) === 'B')
}
{
  const r = run(base, { STUB_MODE: 'pass', STUB_LINK: 'block' })
  let j = null
  try { j = JSON.parse(r.stdout) } catch { /* 下面断言会报 */ }
  check('端到端：只有链接打回 → reason 只含链接那路', j && j.decision === 'block' && j.reason === '回合末链接审查：\n- 链接', r.stdout)
}
{
  const r = run(base, { STUB_MODE: 'block', STUB_LINK: 'block' })
  let j = null
  try { j = JSON.parse(r.stdout) } catch { /* 下面断言会报 */ }
  check('端到端：两路都打回 → 合成一条', j && j.reason === '回合末出处审查：\n- 测试\n\n回合末链接审查：\n- 链接', r.stdout)
}
{
  const log = path.join(DIR, 'kinds-default')
  run(base, { STUB_MODE: 'pass', STUB_LOG: log, CLICKABLE_PATHS: '' })
  const kinds = fs.readFileSync(log, 'utf8').trim().split('\n').sort().join(',')
  check('端到端：默认四路各调一次', kinds === 'gloss,link,source,stuck', kinds)
  const log2 = path.join(DIR, 'kinds-off')
  run(base, { STUB_MODE: 'pass', STUB_LOG: log2, CLICKABLE_PATHS: 'off' })
  check('端到端：CLICKABLE_PATHS=off 不调链接那路', fs.readFileSync(log2, 'utf8').trim().split('\n').sort().join(',') === 'gloss,source,stuck')
  const log3 = path.join(DIR, 'kinds-wiki-off')
  run(base, { STUB_MODE: 'pass', STUB_LOG: log3, DEVKIT_WIKI_AUDIT: 'off' })
  check('端到端：DEVKIT_WIKI_AUDIT=off 只调出处、链接两路', fs.readFileSync(log3, 'utf8').trim().split('\n').sort().join(',') === 'link,source')
}
{
  const r = run(base, { STUB_MODE: 'block', STUB_LINK: 'block', STUB_STUCK: 'block', STUB_GLOSS: 'block' })
  let j = null
  try { j = JSON.parse(r.stdout) } catch { /* 下面断言会报 */ }
  check('端到端：四路都打回 → 一次打回里四路问题全在', j && j.reason === '回合末出处审查：\n- 测试\n\n回合末链接审查：\n- 链接\n\n回合末卡点审查：\n- 卡点\n\n回合末释义审查：\n- 释义', r.stdout)
  const r2 = run({ ...base, stop_hook_active: true }, { STUB_MODE: 'block', STUB_STUCK: 'block', STUB_GLOSS: 'block' })
  check('端到端：已打回过一次 → 卡点、释义两路也不再审', r2.stdout.trim() === '', r2.stdout)
}
{
  const r = run(base, { STUB_MODE: 'exit1', STUB_LINK: 'block' })
  check('端到端：出处那路失败不影响链接那路打回', r.stdout.includes('回合末链接审查'), r.stdout)
}

// ---- 4.17.0 词条核对（wiki-check.js，不经模型）----
{
  const { checkWikiFile, wikiFilesThisTurn, parseSource, wikiReason } = require(path.join(__dirname, '..', 'hooks', 'wiki-check.js'))
  const { userPromptText } = require(HOOK)
  const docs = path.join(DIR, 'repo', 'docs')
  fs.mkdirSync(docs, { recursive: true })
  const SRC = path.join(docs, 'design.md')
  const pad = Array.from({ length: 60 }, (_, i) => `填充行 ${i + 1}`)
  pad[9] = '## 定时催办'
  pad[10] = '- **定时催办**：到期前一天自动提醒负责人，'
  pad[11] = '  提醒走钉钉工作通知。'
  pad[49] = '评估 Plugin 是给作答打分的规则包。'
  fs.writeFileSync(SRC, pad.join('\n') + '\n')
  const wikiDir = path.join(DIR, 'claude-wiki', 'repo')
  fs.mkdirSync(wikiDir, { recursive: true })
  const W = (name, body) => { const f = path.join(wikiDir, name); fs.writeFileSync(f, body); return f }
  const src = (line) => `—— [design.md:${line}](vscode://file${SRC}:${line})`

  const good = W('good.md', [
    '# 定时催办', '',
    '> 「定时催办：到期前一天自动提醒负责人，提醒走钉钉工作通知。」', src(11), '',
    '> 评估 Plugin 是……打分的规则包', src(50), '',
    '## 未找到', '- 谁负责维护', '',
    '## 相关词条', '- [评估 Plugin](./eval-plugin.md)', '',
    '<!-- 写于 2026-11-21，会话主题：测试 -->', '',
  ].join('\n'))
  check('词条核对：合格词条（跨行摘录、去粗体与列表符、删节号、未找到、相关词条、注释）→ 无问题', checkWikiFile(good).length === 0, JSON.stringify(checkWikiFile(good)))

  const prose = W('prose.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', src(11), '', '它的作用是减少逾期，这次改动会用到它。', ''].join('\n'))
  const pp = checkWikiFile(prose)
  check('词条核对：骨架外的自写句子 → 报出行号', pp.length === 1 && pp[0].includes('第 6 行') && pp[0].includes('自写句子'), JSON.stringify(pp))

  const h2 = W('h2.md', ['# 定时催办', '', '## 是什么', '> 到期前一天自动提醒负责人', src(11), ''].join('\n'))
  check('词条核对：自写小标题（如「是什么」）→ 报出', checkWikiFile(h2).some((x) => x.includes('是什么')), JSON.stringify(checkWikiFile(h2)))

  const reword = W('reword.md', ['# 定时催办', '', '> 到期前一天会自动提醒负责的人', src(11), ''].join('\n'))
  check('词条核对：改了字的摘录 → 找不到逐字原文', checkWikiFile(reword).some((x) => x.includes('找不到逐字原文')), JSON.stringify(checkWikiFile(reword)))

  const splice = W('splice.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人……是给作答打分的规则包', src(11), ''].join('\n'))
  check('词条核对：用删节号拼两处原文 → 各片段都在文件里时放行（行号只核第一段）', checkWikiFile(splice).length === 0, JSON.stringify(checkWikiFile(splice)))
  const tiny = W('tiny.md', ['# 定时催办', '', '> 到期……提醒……负责', src(11), ''].join('\n'))
  check('词条核对：短于 4 字的片段 → 报「像在拼句」', checkWikiFile(tiny).some((x) => x.includes('像在拼句')), JSON.stringify(checkWikiFile(tiny)))

  const badLine = W('badline.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', src(58), ''].join('\n'))
  check('词条核对：行号注错（原文在 11 行、注 58 行）→ 报行号', checkWikiFile(badLine).some((x) => x.includes('行号注错')), JSON.stringify(checkWikiFile(badLine)))
  const outRange = W('outrange.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', src(999), ''].join('\n'))
  check('词条核对：行号超出文件范围 → 报出', checkWikiFile(outRange).some((x) => x.includes('超出文件范围')), JSON.stringify(checkWikiFile(outRange)))

  const noSrc = W('nosrc.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', '', '## 未找到', '- 维护人', ''].join('\n'))
  const ns = checkWikiFile(noSrc)
  check('词条核对：摘录下没有出处行 → 报出，且算「没有一段带出处的摘录」', ns.some((x) => x.includes('没有紧跟出处行')) && ns.some((x) => x.includes('没有一段带出处的摘录')), JSON.stringify(ns))

  const self = W('self.md', ['# 定时催办', '', '> 定时催办', `—— [good.md:1](vscode://file${good}:1)`, ''].join('\n'))
  check('词条核对：出处指向词条目录 → 报出', checkWikiFile(self).some((x) => x.includes('词条目录')), JSON.stringify(checkWikiFile(self)))

  check('出处解析：file:///abs#12 与 #L12 都认', parseSource(`file://${SRC}#12`).line === 12 && parseSource(`file://${SRC}#L12`).line === 12)
  check('出处解析：vscode 链接带列号也认', parseSource(`vscode://file${SRC}:12:3`).line === 12)
  check('出处解析：Windows 盘符去掉前导斜杠', parseSource('vscode://file/C:/a/b.md:3').file === 'C:/a/b.md')

  const raw = jsonl([
    user('上一轮'),
    toolUse('Write', { file_path: prose, content: '' }),
    user('本轮'),
    toolUse('Write', { file_path: good, content: '' }),
    toolUse('Edit', { file_path: reword, old_string: 'a', new_string: 'b' }),
    toolUse('Write', { file_path: path.join(DIR, 'not-wiki.md'), content: '' }),
    toolUse('Write', { file_path: reword, content: '' }),
  ])
  const files = wikiFilesThisTurn(raw, userPromptText)
  check('本轮词条：只取本轮、只取 claude-wiki 下的 md、去重', files.length === 2 && files[0] === good && files[1] === reword, JSON.stringify(files))
  const reason = wikiReason(raw, userPromptText)
  check('打回 reason：标题、只列不合格的词条、带改法', reason.startsWith('回合末词条核对') && reason.includes('reword.md') && !reason.includes('good.md：') && reason.includes('AI 理解'), reason)
  check('打回 reason：全合格 → 空', wikiReason(jsonl([user('本轮'), toolUse('Write', { file_path: good, content: '' })]), userPromptText) === '')
  check('打回 reason：词条已被删掉 → 不核', wikiReason(jsonl([user('本轮'), toolUse('Write', { file_path: path.join(wikiDir, 'gone.md'), content: '' })]), userPromptText) === '')

  // 真实原文形态：代码注释前缀、md 表格与链接、带空格与括号的路径
  const codeSrc = path.join(docs, 'hook.js')
  fs.writeFileSync(codeSrc, "'use strict'\n// 1. stop_hook_active=true（本轮已打回过一次）→ 直接放行，\n//    不调模型。\n# python 注释：默认只检查，\n# --apply 才改动。\n")
  const code = W('code.md', ['# stop_hook_active', '', '> stop_hook_active=true（本轮已打回过一次）→ 直接放行，不调模型。', `—— [hook.js:2](vscode://file${codeSrc}:2)`, '', '> 默认只检查，--apply 才改动。', `—— [hook.js:4](vscode://file${codeSrc}:4)`, ''].join('\n'))
  check('词条核对：跨行的 // 与 # 注释原文 → 去掉注释前缀后比对通过', checkWikiFile(code).length === 0, JSON.stringify(checkWikiFile(code)))
  const tblSrc = path.join(docs, 'table.md')
  fs.writeFileSync(tblSrc, '| 档 | 说明 |\n|---|---|\n| `SessionStart` | 背景规则，见 [hook-restraint](./x.md) 的强度阶梯 |\n')
  const tbl = W('tbl.md', ['# SessionStart', '', '> | SessionStart | 背景规则，见 hook-restraint 的强度阶梯 |', `—— [table.md:3](vscode://file${tblSrc}:3)`, ''].join('\n'))
  check('词条核对：摘 md 表格行（含行内代码与链接）→ 通过', checkWikiFile(tbl).length === 0, JSON.stringify(checkWikiFile(tbl)))
  const spDir = path.join(DIR, 'dir with space(1)')
  fs.mkdirSync(spDir, { recursive: true })
  fs.copyFileSync(SRC, path.join(spDir, 'design.md'))
  const enc = encodeURI(path.join(spDir, 'design.md')).replace(/\(/g, '%28').replace(/\)/g, '%29')
  const spOk = W('sp-ok.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', `—— [design.md:11](vscode://file${enc}:11)`, ''].join('\n'))
  check('词条核对：路径含空格与括号、按 %20 %28 %29 编码 → 通过', checkWikiFile(spOk).length === 0, JSON.stringify(checkWikiFile(spOk)))
  const spRaw = W('sp-raw.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', `—— [design.md:11](vscode://file${path.join(spDir, 'design.md')}:11)`, ''].join('\n'))
  const spr = checkWikiFile(spRaw)
  check('词条核对：路径空格括号没编码 → 报「出处格式不对」并给编码写法，不误报成自写句子', spr.some((x) => x.includes('出处格式不对') && x.includes('%20')) && !spr.some((x) => x.includes('自写句子') || x.includes('没有紧跟出处行')), JSON.stringify(spr))
  const many = W('many.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', src(11), '', '## 未找到', '- a1', '- a2', '- a3', '- a4', '- a5', '- a6', ''].join('\n'))
  check('词条核对：「未找到」超过 5 条 → 报出', checkWikiFile(many).some((x) => x.includes('超过 5 条')), JSON.stringify(checkWikiFile(many)))
  const ownSrc = W('own-src.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', src(11), ''].join('\n'))
  check('词条核对：出处文件本轮被 Write / Edit 过 → 不算现有原文', checkWikiFile(ownSrc, new Set([path.resolve(SRC)])).some((x) => x.includes('本轮被你改写过')), JSON.stringify(checkWikiFile(ownSrc, new Set([path.resolve(SRC)]))))
  // 4.21.0：远端内容（钉钉文档、网页）由读取命令落到 claude-sources/ 的快照可作出处；本轮 Write / Edit 过的快照不算
  const snapDir = path.join(DIR, 'claude-sources', 'repo')
  fs.mkdirSync(snapDir, { recursive: true })
  const SNAP = path.join(snapDir, 'remote-doc.md')
  fs.writeFileSync(SNAP, '<!-- 原址：https://example.invalid/doc ｜ 读于：2026-11-23 16:17:00 +0800 ｜ 命令：curl -sL -->\n- 归档任务每晚两点运行，失败时次日早上补跑一次。\n')
  const snapW = W('snap.md', ['# 归档任务', '', '> 归档任务每晚两点运行', `—— [remote-doc.md:2](vscode://file${SNAP}:2)`, ''].join('\n'))
  check('词条核对：出处是远端内容的快照（claude-sources/）→ 通过', checkWikiFile(snapW).length === 0, JSON.stringify(checkWikiFile(snapW)))
  check('词条核对：快照本轮被 Write / Edit 过 → 不算现有原文', checkWikiFile(snapW, new Set([path.resolve(SNAP)])).some((x) => x.includes('本轮被你改写过')), JSON.stringify(checkWikiFile(snapW, new Set([path.resolve(SNAP)]))))
  const { wikiFilesInReply } = require(path.join(__dirname, '..', 'hooks', 'wiki-check.js'))
  const inReply = wikiFilesInReply(`见 [定时催办](file://${encodeURI(prose)})（「到期前一天」），另 \`${reword}\``)
  check('回复里链到的词条：file:// 链接与行内代码路径都取到', inReply.length === 2 && inReply[0] === prose && inReply[1] === reword, JSON.stringify(inReply))
  const rr = wikiReason(jsonl([user('本轮')]), userPromptText, `复用旧词条 [定时催办](file://${prose})`)
  check('打回 reason：本轮没写、但回复里链到的旧词条也核', rr.includes('prose.md') && rr.includes('自写句子'), rr)
  const rr2 = wikiReason('', userPromptText, `[x](file://${prose})`)
  check('打回 reason：读不到 transcript 时仍核回复里链到的词条', rr2.includes('prose.md'), rr2)

  const tp = path.join(DIR, 'transcript-wiki.jsonl')
  fs.writeFileSync(tp, raw)
  const r = run({ ...base, transcript_path: tp }, { STUB_MODE: 'block' })
  let j = null
  try { j = JSON.parse(r.stdout) } catch { /* 下面断言会报 */ }
  check('端到端：模型打回与词条核对合成一条，词条在最后', j && j.reason.startsWith('回合末出处审查') && j.reason.includes('\n\n回合末词条核对'), r.stdout)
  const r2 = run({ ...base, transcript_path: tp }, { STUB_MODE: 'pass', DEVKIT_STOP_AUDIT_CLAUDE: path.join(DIR, 'no-such-claude') })
  check('端到端：找不到 claude 时词条核对照样打回', r2.stdout.includes('回合末词条核对'), r2.stdout)
  const r3 = run({ ...base, transcript_path: tp, stop_hook_active: true }, { STUB_MODE: 'pass' })
  check('端到端：stop_hook_active=true 时词条也不核（每轮只打回一次）', r3.stdout === '', r3.stdout)
}

// ---- 4.19.0 链接核对（term-links.js，不经模型）：每次出现都挂、括注原文逐字 ----
{
  const { bareRepeats, quoteProblems, termLinksReason } = require(path.join(__dirname, '..', 'hooks', 'term-links.js'))
  const src = path.join(DIR, 'tl-src.md')
  fs.writeFileSync(src, ['第一行', '本轮打回过一次就直接放行，不调模型。', '第三行'].join('\n'))
  const U = `file://${src}`
  const count = (m) => Object.fromEntries(bareRepeats(m).map((h) => [h.term, h.count]))
  check('裸写两次 → 计 2', count(`[定时催办](${U}#2) 是什么。定时催办会发提醒，定时催办之后再说。`)['定时催办'] === 2)
  check('每次都挂链接 → 不报', bareRepeats(`[定时催办](${U}#2) 与 [定时催办](${U}#2)`).length === 0)
  check('文件名:行号 标签 → 文件名裸写也算', count(`见 [tl-src.md:2](${U}#2)，tl-src.md 里写了`)['tl-src.md'] === 1)
  check('长词先数不重复：README.md:12 与 README.md', JSON.stringify(count(`[README.md:12](${U}#2) 然后 README.md:12 和 README.md`)) === '{"README.md:12":1,"README.md":1}')
  check('路径中段与 data.md 不算', bareRepeats(`[a.md](${U}#1) 见 data.md 与 x/a.md/y`).length === 0)
  check('围栏代码块与 https 链接不算', bareRepeats(`[keeper](${U}#1)\n\`\`\`\nkeeper run\n\`\`\`\n[x](https://e.com/keeper)`).length === 0)
  check('行内代码恰好等于词 → 算裸写', count(`[keeper](${U}#1) 和 \`keeper\``)['keeper'] === 1)
  check('行内代码里更长的命令 → 不算', bareRepeats(`[keeper](${U}#1) 跑 \`keeper run --all\``).length === 0)
  check('非本机链接的标签不进词表', bareRepeats(`[keeper](https://e.com) 与 keeper`).length === 0)
  check('括注是原文 → 不报', quoteProblems(`[放行](${U}#2)（「本轮打回过一次就直接放行」）`).length === 0)
  check('括注用 …… 删节 → 不报', quoteProblems(`[放行](${U}#2)（「本轮打回过……不调模型」）`).length === 0)
  {
    const sideDir = path.join(DIR, 'claude-side', 'r'); fs.mkdirSync(sideDir, { recursive: true })
    const side = path.join(sideDir, 'bg.md'); fs.writeFileSync(side, '模型写的一句背景说明文字\n')
    check('括注摘自外挂文档（claude-side）→ 报：那是模型生成的', quoteProblems(`[背景](file://${side}#1)（「模型写的一句背景说明文字」）`).length === 1)
  }
  check('括注是改写 → 报', quoteProblems(`[放行](${U}#2)（「打回一次后就不再审」）`).length === 1)
  check('括注不带「」 → 不归这里', quoteProblems(`[放行](${U}#2)（我说的白话）`).length === 0)
  check('4.24.0 链解释文件 + 「AI 理解」括注（不加「」）→ 不报', quoteProblems('[审批流转](file:///nonexistent/claude-explain/kit/approval-flow.md)（AI 理解：提交后按角色逐级审）').length === 0)
  check('4.24.0「AI 理解」括注里套「」冒充原文 → 仍按原文比对、报', quoteProblems(`[放行](${U}#2)（「AI 理解：打回一次就放行」）`).length === 1)
  check('不带行号的文件按全文比对', quoteProblems(`[词条](${U})（「不调模型」）`).length === 0 && quoteProblems(`[词条](${U})（「随便编的」）`).length === 1)
  const many = Array.from({ length: 9 }, (_, i) => `[词${i}号](${U}#2) 词${i}号`).join('\n')
  check('不截断：9 个词全列', (termLinksReason(many).match(/号」1 处/g) || []).length === 9)
  check('全合格 → 空串', termLinksReason(`[词](${U}#2)（「不调模型」）`) === '')
  // 4.21.0 拍板 a：claude-sources/ 下的快照本轮被 Write / Edit 过 → 打回；不在这个目录的本轮改过的文件不受影响
  {
    const snapDir = path.join(DIR, 'claude-sources', 'tl'); fs.mkdirSync(snapDir, { recursive: true })
    const snap = path.join(snapDir, 'remote.md'); fs.writeFileSync(snap, '<!-- 原址：x -->\n归档任务每晚两点运行。\n')
    const msgFile = `[定时归档](file://${snap}#2)（「归档任务每晚两点运行」）`
    const msgVs = `[定时归档](vscode://file${snap}:2)（「归档任务每晚两点运行」）`
    const w = new Set([path.resolve(snap)])
    check('快照本轮没写过 → 不报', quoteProblems(msgFile, new Set()).length === 0 && quoteProblems(msgFile).length === 0)
    check('快照本轮被 Write 过（file:// 带 #行号）→ 报', (quoteProblems(msgFile, w)[0] || {}).problem?.includes('本轮被你用 Write / Edit 写过'), JSON.stringify(quoteProblems(msgFile, w)))
    check('快照本轮被 Write 过（vscode://file 带 :行号）→ 报', quoteProblems(msgVs, w).length === 1)
    check('快照本轮被 Write 过（不带行号）→ 报', quoteProblems(`[定时归档](file://${snap})（「归档任务每晚两点运行」）`, w).length === 1)
    check('项目文件本轮改过、括注逐字对得上 → 不报（只查 claude-sources/）', quoteProblems(`[放行](${U}#2)（「本轮打回过一次就直接放行」）`, new Set([path.resolve(src)])).length === 0)
    const tp = path.join(DIR, 'tl-snap.jsonl')
    fs.writeFileSync(tp, jsonl([user('查一下归档'), toolUse('Write', { file_path: snap, content: 'x' }), toolResult('ok')]))
    const r = run({ ...base, transcript_path: tp, last_assistant_message: msgFile }, { STUB_MODE: 'pass' })
    let j = null
    try { j = JSON.parse(r.stdout) } catch { /* 下面断言会报 */ }
    check('端到端：本轮 Write 了快照再引用 → 打回', j && j.decision === 'block' && j.reason.includes('出处快照 remote.md'), r.stdout)
    fs.writeFileSync(tp, jsonl([user('查一下归档'), toolUse('Bash', { command: 'curl -sL x > remote.md' }), toolResult('ok')]))
    const r2 = run({ ...base, transcript_path: tp, last_assistant_message: msgFile }, { STUB_MODE: 'pass' })
    check('端到端：快照由 Bash 读取命令落盘 → 放行', r2.stdout.trim() === '', r2.stdout)
  }
  const r = run({ ...base, last_assistant_message: `[定时催办](${U}#2) 然后定时催办。` }, { STUB_MODE: 'pass' })
  let j = null
  try { j = JSON.parse(r.stdout) } catch { /* 下面断言会报 */ }
  check('端到端：模型全放行、机械核对仍打回', j && j.decision === 'block' && j.reason.includes('「定时催办」1 处'), r.stdout)
  const r2 = run({ ...base, last_assistant_message: `[定时催办](${U}#2) 然后定时催办。` }, { STUB_MODE: 'pass', CLICKABLE_PATHS: 'off' })
  check('端到端：CLICKABLE_PATHS=off 不跑链接核对', r2.stdout.trim() === '', r2.stdout)
}

// ---- 第三方 settings 解析与参数（4.20.0 起只给后台事实审查用；同步四路恒走订阅）----
{
  const { thirdPartySettings, routeArgs, routeEnv } = require(HOOK)
  const sf = path.join(DIR, 'settings.third.json')
  fs.writeFileSync(sf, '{"env":{}}')
  check('没设开关 → 不走第三方', thirdPartySettings({}) === null)
  check('文件不存在 → 当没开', thirdPartySettings({ DEVKIT_STOP_AUDIT_SETTINGS: path.join(DIR, 'nope.json') }) === null)
  check('文件存在 → 返回路径', thirdPartySettings({ DEVKIT_STOP_AUDIT_SETTINGS: sf }) === sf)
  check('订阅参数：模型仍是 claude-sonnet-5-5', routeArgs(null)[routeArgs(null).indexOf('--model') + 1] === 'claude-sonnet-5-5')
  check('订阅参数：不带 --json-schema（单轮文本判定）', !routeArgs(null).includes('--json-schema'))
  check('订阅参数：带 --effort medium', routeArgs(null)[routeArgs(null).indexOf('--effort') + 1] === 'medium')
  const e = routeEnv({ ANTHROPIC_BASE_URL: 'https://api.anthropic.com', ANTHROPIC_AUTH_TOKEN: 'x' }, sf)
  check('第三方子进程剥掉父进程的 ANTHROPIC_*', e.ANTHROPIC_BASE_URL === undefined && e.ANTHROPIC_AUTH_TOKEN === undefined)

  const rl = path.join(DIR, 'route-sync')
  const lg = path.join(DIR, 'route-sync.log')
  const r = run(base, { STUB_MODE: 'block', STUB_ROUTE_LOG: rl, DEVKIT_STOP_AUDIT_SETTINGS: sf, DEVKIT_STOP_AUDIT_LOG: lg })
  const rows = fs.readFileSync(rl, 'utf8').trim().split('\n')
  check('端到端：设了 DEVKIT_STOP_AUDIT_SETTINGS，同步四路仍只走订阅各一次', rows.length === 4 && rows.every((x) => x.includes(':sub:claude-sonnet-5-5')), rows.join(' | '))
  check('端到端：同步路的打回照常生效', r.stdout.includes('回合末出处审查'), r.stdout)
  const lgRows = fs.readFileSync(lg, 'utf8').trim().split('\n').map((l) => JSON.parse(l))
  const oks = lgRows.filter((o) => o.kind === 'ok')
  check('成功判定记日志、route=subscription、四路各一行', oks.length === 4 && oks.every((o) => o.route === 'subscription') && oks.map((o) => o.audit).sort().join(',') === 'gloss,link,source,stuck', JSON.stringify(oks))
  const runRow = lgRows.filter((o) => o.kind === 'run')
  check('整次审查记一行 kind=run、stage=sync、blocked=true', runRow.length === 1 && runRow[0].stage === 'sync' && runRow[0].blocked === true && typeof runRow[0].ms === 'number', JSON.stringify(runRow))
}

// ---- 后台事实审查 stop-fact-audit.js（asyncRewake；4.32.0 起调 agy）----
{
  const FACT = path.join(__dirname, '..', 'hooks', 'stop-fact-audit.js')
  // agy 桩：提示词取自 --print=<全文>；STUB_AGY 选输出形态；每次调用在 STUB_LOG 追加一行
  const AGY = path.join(DIR, 'stub-agy')
  fs.writeFileSync(AGY, `#!/usr/bin/env node
const fs = require('fs')
const argv = process.argv.slice(2)
const pr = (argv.find((a) => a.startsWith('--print=')) || '').slice(8)
if (process.env.STUB_LOG) fs.appendFileSync(process.env.STUB_LOG, 'fact\\n')
if (process.env.STUB_ARGV_LOG) fs.appendFileSync(process.env.STUB_ARGV_LOG, JSON.stringify({ argv, child: process.env.DEVKIT_STOP_AUDIT_CHILD, input: pr }) + '\\n')
const m = process.env.STUB_AGY || 'pass'
const out = (status, response, extra = {}) => process.stdout.write(JSON.stringify({ conversation_id: 'c1', status, response, ...extra }))
if (m === 'exit1') { process.stderr.write('error: invalid model selection (--model "x"): model x is not recognized\\nAvailable models:\\n  Gemini 4 Neon (High)\\n'); process.exit(1) }
if (m === 'sleep') Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10000)
if (m === 'garbage') { process.stdout.write('not json'); process.exit(0) }
if (m === 'staterr') { out('ERROR', '', { error: 'quota exhausted' }); process.exit(0) }
if (m === 'empty') { out('SUCCESS', ''); process.exit(0) }
if (m === 'preamble') { out('SUCCESS', 'I will check the file first.', { denied_actions: [{ action: 'command' }] }); process.exit(0) }
if (m === 'block') { out('SUCCESS', '事实错误：回复说「X 不存在」，但 /tmp/a.js:3 写的是「function X」'); process.exit(0) }
out('SUCCESS', 'PASS\\n')
`)
  fs.chmodSync(AGY, 0o755)
  const runFact = (input, env = {}) => {
    const log = path.join(DIR, `flog-${pass + fail}`)
    const r = spawnSync('node', [FACT], {
      input: typeof input === 'string' ? input : JSON.stringify(input),
      encoding: 'utf8',
      env: { ...process.env, DEVKIT_STOP_AUDIT: '', DEVKIT_STOP_AUDIT_CHILD: '', DEVKIT_FACT_AUDIT: '', DEVKIT_FACT_AUDIT_AGY: AGY, DEVKIT_STOP_AUDIT_LOG: path.join(DIR, 'fact-default.log'), STUB_LOG: log, ...env },
    })
    return { status: r.status, stdout: r.stdout, stderr: r.stderr, called: fs.existsSync(log) }
  }
  const fb = { ...base, cwd: '/proj/demo', last_assistant_message: '结论：X 不存在，见 a.js。' }
  const TAG = '🔍【异步审查 · gemini-4-neon（agy）】'

  const al = path.join(DIR, 'fact-argv')
  const lg = path.join(DIR, 'fact-pass.log')
  const r1 = runFact(fb, { STUB_AGY: 'pass', STUB_ARGV_LOG: al, DEVKIT_STOP_AUDIT_LOG: lg })
  check('事实审查：判满足 → 退出码 0、不写 stderr', r1.status === 0 && r1.stderr === '' && r1.called, `${r1.status} ${r1.stderr}`)
  const calls = fs.readFileSync(al, 'utf8').trim().split('\n').map((l) => JSON.parse(l))
  const a = calls[0].argv
  const after = (f) => a[a.indexOf(f) + 1]
  check('事实审查：只调一次 agy', calls.length === 1, String(calls.length))
  check('事实审查：模型 gemini-4-neon、effort medium、json 输出', after('--model') === 'gemini-4-neon' && after('--effort') === 'medium' && after('--output-format') === 'json', JSON.stringify(a))
  check('事实审查：全权限（等同 gy 别名）——带 --dangerously-skip-permissions、不带 --mode', a[0] === '--dangerously-skip-permissions' && !a.includes('--mode'), JSON.stringify(a))
  check('事实审查：--print-timeout 按超时秒数、--add-dir 加会话 cwd', after('--print-timeout') === '300s' && after('--add-dir') === '/proj/demo', JSON.stringify(a))
  check('事实审查：提示词挂在最后一个参数 --print= 上', a[a.length - 1].startsWith('--print=') && !a.includes('-p'), JSON.stringify(a.slice(-1)).slice(0, 80))
  check('事实审查：子进程带防递归标记', calls[0].child === '1', JSON.stringify(calls[0].child))
  check('事实审查：输入里 $CWD 已替换、带被审回复、带审查员身份', calls[0].input.includes('项目目录：/proj/demo') && !calls[0].input.includes('$CWD') && calls[0].input.includes('[assistant]: 结论：X 不存在') && calls[0].input.startsWith('你是 Claude Code 会话的后台事实审查员'), calls[0].input.slice(0, 300))
  check('事实审查：输入不带同步路的「只输出一行 JSON」', !calls[0].input.includes('只输出一行 JSON'))
  const rows = fs.readFileSync(lg, 'utf8').trim().split('\n').map((l) => JSON.parse(l))
  check('事实审查：成功记 kind=ok、audit=fact、route=agy', rows.some((o) => o.kind === 'ok' && o.audit === 'fact' && o.route === 'agy'), JSON.stringify(rows))
  check('事实审查：记 kind=run、stage=fact、blocked=false', rows.some((o) => o.kind === 'run' && o.stage === 'fact' && o.blocked === false), JSON.stringify(rows))

  const lg2 = path.join(DIR, 'fact-block.log')
  const r2 = runFact(fb, { STUB_AGY: 'block', DEVKIT_STOP_AUDIT_LOG: lg2 })
  check('事实审查：判不满足 → 退出码 2（叫醒主模型）', r2.status === 2, `${r2.status} ${r2.stderr}`)
  check('事实审查：stderr 带判定理由与被审回复开头', r2.stderr.includes('/tmp/a.js:3') && r2.stderr.includes('「结论：X 不存在'), r2.stderr)
  check('事实审查：stderr 要求先核实再改', r2.stderr.includes('先用工具逐条核实'), r2.stderr)
  check('事实审查：叫醒文本以 gemini-4-neon（agy）标识开头', r2.stderr.startsWith(TAG + '后台事实审查'), r2.stderr.slice(0, 60))
  check('事实审查：stdout 为空（不走 decision=block）', r2.stdout === '', r2.stdout)
  check('事实审查：叫醒时 run 行 blocked=true', fs.readFileSync(lg2, 'utf8').trim().split('\n').map((l) => JSON.parse(l)).some((o) => o.kind === 'run' && o.stage === 'fact' && o.blocked === true))

  for (const [name, input, env] of [
    ['DEVKIT_FACT_AUDIT=off', fb, { STUB_AGY: 'block', DEVKIT_FACT_AUDIT: 'off' }],
    ['DEVKIT_STOP_AUDIT=off', fb, { STUB_AGY: 'block', DEVKIT_STOP_AUDIT: 'off' }],
    ['判定子进程里', fb, { STUB_AGY: 'block', DEVKIT_STOP_AUDIT_CHILD: '1' }],
    ['stop_hook_active=true（叫醒那一轮）', { ...fb, stop_hook_active: true }, { STUB_AGY: 'block' }],
    ['没有 last_assistant_message', { ...fb, last_assistant_message: '' }, { STUB_AGY: 'block' }],
    ['agy 路径不存在', fb, { STUB_AGY: 'block', DEVKIT_FACT_AUDIT_AGY: path.join(DIR, 'nope') }],
  ]) {
    const r = runFact(input, env)
    check(`事实审查：${name} → 不调模型、退出码 0`, r.status === 0 && !r.called && r.stderr === '', `${r.status} ${r.called} ${r.stderr}`)
  }
  {
    const r = runFact('oops', { STUB_AGY: 'block' })
    check('事实审查 没跑判定：stdin 不是 JSON → 退出码 0、不叫醒', r.status === 0 && r.stderr === '', `${r.status} ${r.stderr}`)
  }
  const lg3 = path.join(DIR, 'fact-fail.log')
  for (const [name, env, want] of [
    ['agy 退出码非 0：取 error: 开头那行，不取模型清单末行', { STUB_AGY: 'exit1' }, 'error: invalid model selection'],
    ['输出不是 JSON', { STUB_AGY: 'garbage' }, 'bad-json'],
    ['status 不是 SUCCESS：带 status 与 error', { STUB_AGY: 'staterr' }, 'status=ERROR：quota exhausted'],
    ['审查意见为空', { STUB_AGY: 'empty' }, '审查输出为空'],
    ['只有开场白、既无 PASS 也无问题行', { STUB_AGY: 'preamble' }, '既没有 PASS 也没有问题行：I will check'],
  ]) {
    const r = runFact(fb, { ...env, DEVKIT_STOP_AUDIT_LOG: lg3 })
    check(`事实审查 失败也叫醒：${name}`, r.status === 2 && r.stderr.startsWith(TAG) && r.stderr.includes('时失败') && r.stderr.includes('不复查、不重写') && r.stderr.includes('照常做完') && !r.stderr.includes('结束本轮') && r.stderr.includes(want) && !r.stderr.includes('Gemini 4 Neon (High)'), `${r.status} ${r.stderr}`)
  }
  {
    const fa = require(FACT)
    check('parseFactText：单独一行 PASS → 满足', JSON.stringify(fa.parseFactText('PASS')) === '{"ok":true,"reason":""}' && fa.parseFactText('**PASS**\n').ok === true)
    check('parseFactText：问题行 → 不满足、理由为整段文本（同时有 PASS 也算不满足）', fa.parseFactText('事实错误：回复说「a」，但 /x:1 写的是「b」').ok === false && fa.parseFactText('- 漏答：用户问「q」，回复没有回应。\nPASS').ok === false)
    check('parseFactText：非空但既无 PASS 也无问题行 → null（按失败处理）', fa.parseFactText('回复第 3 段的数字对不上') === null)
    check('parseFactText：空文本 → null', fa.parseFactText('') === null && fa.parseFactText('  ') === null && fa.parseFactText(undefined) === null)
    check('factVerdict：status 不是 SUCCESS → null', fa.factVerdict({ status: 'ERROR', response: 'PASS' }) === null && fa.factVerdict({ status: 'SUCCESS', response: 'PASS' }).ok === true)
    check('failDetail：无 JSON、无 error: 行时取 stderr 最后一行', fa.failDetail('exit-nonzero', { stdout: '', stderr: 'a\nboom\n' }) === 'boom')
    check('failDetail：什么都没有时退回失败类别', fa.failDetail('bad-json', { stdout: 'x', stderr: '' }) === 'bad-json')
    check('resolveAgy：DEVKIT_FACT_AUDIT_AGY 不可执行时返回 null', fa.resolveAgy({ DEVKIT_FACT_AUDIT_AGY: path.join(DIR, 'nope') }) === null && fa.resolveAgy({ DEVKIT_FACT_AUDIT_AGY: AGY }) === AGY)
  }
  const lg4 = path.join(DIR, 'fact-timeout.log')
  const r4 = runFact(fb, { STUB_AGY: 'sleep', DEVKIT_FACT_AUDIT_TIMEOUT_MS: '1000', DEVKIT_STOP_AUDIT_LOG: lg4 })
  check('事实审查：超时 → 退出码 2（也叫醒）', r4.status === 2, `${r4.status} ${r4.stderr}`)
  check('事实审查：超时叫醒同样以标识开头', r4.stderr.startsWith(TAG), r4.stderr.slice(0, 60))
  check('事实审查：超时叫醒文案点明没审到、带被审回复开头、不要求复查', r4.stderr.includes('超时') && r4.stderr.includes('没有经过事实审查') && r4.stderr.includes('「结论：X 不存在') && r4.stderr.includes('不复查、不重写') && r4.stderr.includes('照常做完') && !r4.stderr.includes('结束本轮') && !r4.stderr.includes('先用工具逐条核实'), r4.stderr)
  const tr = fs.readFileSync(lg4, 'utf8').trim().split('\n').map((l) => JSON.parse(l))
  check('事实审查：超时记 kind=timeout，run 行 timed_out=true、blocked=false', tr.some((o) => o.kind === 'timeout' && o.audit === 'fact') && tr.some((o) => o.kind === 'run' && o.stage === 'fact' && o.timed_out === true && o.blocked === false), JSON.stringify(tr))
  {
    const fa = require(FACT)
    check('事实审查：超时覆盖只接受小于默认值的正整数', fa.factTimeout({}) === fa.FACT_TIMEOUT_MS && fa.factTimeout({ DEVKIT_FACT_AUDIT_TIMEOUT_MS: 'x' }) === fa.FACT_TIMEOUT_MS && fa.factTimeout({ DEVKIT_FACT_AUDIT_TIMEOUT_MS: '999999' }) === fa.FACT_TIMEOUT_MS && fa.factTimeout({ DEVKIT_FACT_AUDIT_TIMEOUT_MS: '1000' }) === 1000)
  }
  const fr = fs.readFileSync(lg3, 'utf8').trim().split('\n').map((l) => JSON.parse(l))
  check('事实审查：非超时失败的 run 行 timed_out=false、failed=true、共 5 行', fr.filter((o) => o.kind === 'run').every((o) => o.timed_out === false && o.failed === true) && fr.filter((o) => o.kind === 'run').length === 5, JSON.stringify(fr.filter((o) => o.kind === 'run')))
  check('事实审查：失败记日志、audit=fact、route=agy', fr.some((o) => o.kind === 'exit-nonzero' && o.audit === 'fact' && o.route === 'agy') && fr.some((o) => o.kind === 'bad-json' && o.audit === 'fact'), JSON.stringify(fr.map((o) => o.kind + '/' + o.audit)))

  const hj = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'hooks', 'hooks.json'), 'utf8'))
  const stop = hj.hooks.Stop.flatMap((g) => g.hooks)
  const sync = stop.find((h) => h.command.endsWith('/stop-audit.js'))
  const fact = stop.find((h) => h.command.endsWith('/stop-fact-audit.js'))
  check('hooks.json：同步审查 timeout 100、不是 async', sync && sync.timeout === 100 && !sync.async && !sync.asyncRewake, JSON.stringify(sync))
  check('hooks.json：事实审查 asyncRewake、timeout ≥ 300、带一行 rewakeSummary', fact && fact.asyncRewake === true && fact.timeout >= 300 && typeof fact.rewakeSummary === 'string' && !fact.rewakeSummary.includes('\n'), JSON.stringify(fact))
}

// ---- 订阅路文本判定解析 ----
{
  const { parseVerdictText } = require(HOOK)
  check('解析：一行 JSON', JSON.stringify(parseVerdictText('{"ok": false, "reason": "x"}')) === '{"ok":false,"reason":"x"}')
  check('解析：代码块围栏与前后文字', parseVerdictText('结论如下\n```json\n{"ok": true, "reason": ""}\n```\n完').ok === true)
  check('解析：reason 缺省补空串', parseVerdictText('{"ok": true}').reason === '')
  check('解析：ok 不是布尔 → null', parseVerdictText('{"ok": "false"}') === null)
  check('解析：被截断的 JSON → null', parseVerdictText('{"ok": false, "reason": "回合末') === null)
  check('解析：只有后半段（gemini 式截断）→ null', parseVerdictText('改完把整条回复完整重写一遍"}') === null)
  check('解析：非字符串 → null', parseVerdictText(undefined) === null)
  const tl = path.join(DIR, 'tail-sub')
  const r = run(base, { STUB_MODE: 'block', STUB_TAIL_LOG: tl })
  const tails = fs.readFileSync(tl, 'utf8').trim().split('\n')
  check('端到端：订阅路输入末尾带「只输出一行 JSON」、不带 schema', tails.length === 4 && tails.every((x) => x === 'tail:text'), tails.join(' | '))
  check('端到端：订阅路文本判定的打回照常生效', r.stdout.includes('回合末出处审查'), r.stdout)
  const lg = path.join(DIR, 'badtext.log')
  const r2 = run(base, { STUB_MODE: 'badtext', DEVKIT_STOP_AUDIT_LOG: lg })
  const kinds = fs.readFileSync(lg, 'utf8').trim().split('\n').map((l) => JSON.parse(l).kind)
  check('端到端：文本里没有判定 → 放行并记 bad-verdict-text', r2.stdout === '' && kinds.includes('bad-verdict-text'), JSON.stringify(kinds) + ' ' + r2.stdout)
}

// ---- 失败日志 ----
{
  const logFile = path.join(DIR, 'audit.log')
  run(base, { STUB_MODE: 'exit1', DEVKIT_STOP_AUDIT_LOG: logFile })
  run(base, { STUB_MODE: 'garbage', DEVKIT_STOP_AUDIT_LOG: logFile })
  run(base, { STUB_MODE: 'pass', DEVKIT_STOP_AUDIT_LOG: logFile })
  const all = fs.existsSync(logFile) ? fs.readFileSync(logFile, 'utf8').trim().split('\n').map((l) => JSON.parse(l)) : []
  const rows = all.filter((r) => r.kind !== 'ok' && r.kind !== 'run')
  check('日志：成功判定记 kind=ok（4.19.0 起，用来算失败率）', all.filter((r) => r.kind === 'ok').length === 10, JSON.stringify(all.map((r) => r.kind)))
  check('失败日志：退出码非 0 与输出不是 JSON 各记一行', rows.length === 2 && rows[0].kind === 'exit-nonzero' && rows[0].status === 1 && rows[1].kind === 'bad-json', JSON.stringify(rows))
  check('失败日志：带耗时与截断后的 stdout', typeof rows[1]?.ms === 'number' && rows[1].stdout === 'not json', JSON.stringify(rows[1]))
  check('失败日志：带 route 与 audit', rows.every((r) => r.route === 'subscription' && r.audit === 'source'), JSON.stringify(rows))
  const runs = all.filter((r) => r.kind === 'run')
  check('三次审查各记一行 kind=run、stage=sync、都没打回', runs.length === 3 && runs.every((r) => r.blocked === false && r.stage === 'sync'), JSON.stringify(runs))
  const r = run(base, { STUB_MODE: 'block', DEVKIT_STOP_AUDIT_LOG: logFile })
  const last = fs.readFileSync(logFile, 'utf8').trim().split('\n').map((l) => JSON.parse(l)).pop()
  check('打回时 kind=run 记 blocked=true', r.stdout.includes('block') && last.kind === 'run' && last.blocked === true, JSON.stringify(last))
}

// ---- 日志轮转：超过上限改名为 .1 再重写，不清空 ----
{
  const logFile = path.join(DIR, 'rot.log')
  const big = JSON.stringify({ kind: 'ok', pad: 'x'.repeat(1024) }) + '\n'
  fs.writeFileSync(logFile, big.repeat(4 * 1024 + 8))
  run(base, { STUB_MODE: 'pass', DEVKIT_STOP_AUDIT_LOG: logFile })
  check('轮转：旧日志整份改名为 .1', fs.existsSync(logFile + '.1') && fs.statSync(logFile + '.1').size > 4 * 1024 * 1024)
  check('轮转：新日志只剩新写的几行', fs.statSync(logFile).size < 64 * 1024)
}

// ---- 统计脚本 scripts/stop-audit-stats.py ----
{
  const { spawnSync } = require('child_process')
  const py = ['python3', 'python'].find((c) => spawnSync(c, ['--version']).status === 0)
  if (!py) {
    check('统计脚本：找不到 python，跳过', true)
  } else {
    const logFile = path.join(DIR, 'stats.log')
    const now = new Date().toISOString()
    const L = (o) => JSON.stringify({ at: now, ...o })
    fs.writeFileSync(logFile, [
      JSON.stringify({ at: '2026-10-29T00:00:00Z', kind: 'timeout', ms: 75000 }), // 旧格式，默认不算
      L({ kind: 'ok', route: 'third-party', audit: 'source', ms: 10000 }),
      L({ kind: 'ok', route: 'third-party', audit: 'link', ms: 20000 }),
      L({ kind: 'timeout', route: 'third-party', audit: 'stuck', ms: 90000 }),
      L({ kind: 'ok', route: 'fallback', audit: 'stuck', ms: 6000 }),
      L({ kind: 'run', ms: 96000, thirdParty: true, blocked: true }),
      L({ kind: 'ok', route: 'subscription', audit: 'source', ms: 7000 }),
      L({ kind: 'ok', route: 'third-party', audit: 'fact', ms: 60000 }),
      L({ kind: 'timeout', route: 'third-party', audit: 'fact', ms: 300000 }),
      L({ kind: 'run', ms: 8000, stage: 'sync', blocked: false }),
      L({ kind: 'run', ms: 60000, stage: 'fact', blocked: true }),
    ].join('\n') + '\n')
    const STATS = path.join(__dirname, '..', 'scripts', 'stop-audit-stats.py')
    const p = spawnSync(py, [STATS, '--log', logFile, '--json'], { encoding: 'utf8' })
    let j = null
    try { j = JSON.parse(p.stdout) } catch { /* 下面断言会报 */ }
    const tp = j && j.routes['third-party']
    check('统计脚本：后台事实审查单列为 fact，不混进第三方', !!j && j.routes.fact && j.routes.fact.total === 2 && j.routes.fact.ok === 1 && j.routes.fact.fail_kinds.timeout === 1, JSON.stringify(j && j.routes))
    check('统计脚本：整次审查按 stage 分 sync 与 fact', !!j && j.runs.sync && j.runs.sync.n === 1 && j.runs.fact && j.runs.fact.blocked === 1, JSON.stringify(j && j.runs))
    check('统计脚本：第三方 3 次、成功 2、失败 1、超时 1', !!tp && tp.total === 3 && tp.ok === 2 && tp.fail === 1 && tp.fail_kinds.timeout === 1, p.stdout + p.stderr)
    check('统计脚本：第三方成功平均 15 秒', !!tp && tp.avg_ms === 15000, JSON.stringify(tp))
    check('统计脚本：回落订阅单列', !!j && j.routes.fallback && j.routes.fallback.ok === 1, JSON.stringify(j && j.routes))
    check('统计脚本：旧格式行默认不算（订阅只有新格式那 1 行）', !!j && j.routes.subscription && j.routes.subscription.total === 1, JSON.stringify(j && j.routes))
    check('统计脚本：整次审查按开第三方分组', !!j && j.runs['third-party on'] && j.runs['third-party on'].n === 1 && j.runs['third-party on'].blocked === 1, JSON.stringify(j && j.runs))
    const p2 = spawnSync(py, [STATS, '--log', logFile, '--json', '--all'], { encoding: 'utf8' })
    const j2 = JSON.parse(p2.stdout || '{}')
    check('统计脚本：--all 才算旧格式行', j2.routes && j2.routes.subscription && j2.routes.subscription.fail === 1 && j2.routes.subscription.total === 2, p2.stdout)
    const p3 = spawnSync(py, [STATS, '--log', logFile], { encoding: 'utf8' })
    check('统计脚本：表格输出含「第三方」一行', p3.status === 0 && p3.stdout.includes('| 第三方（third-party） | 3 | 2 | 1 | 66.7%'), p3.stdout + p3.stderr)
    check('统计脚本：表格输出含「后台事实审查」两行', p3.stdout.includes('| 后台事实审查（fact） | 2 | 1 | 1 | 50.0%') && p3.stdout.includes('| 后台事实审查（叫醒次数） | 1 | 1 |'), p3.stdout)
  }
}

// ---- 4.33.0 相对 href 核对：链接写了却点不开 ----
{
  const { relativeLinks, isRelativeHref, termLinksReason } = require(path.join(__dirname, '..', 'hooks', 'term-links.js'))
  const { relativeLinkAuditEnabled } = require(path.join(__dirname, '..', 'hooks', 'stop-audit.js'))
  const root = path.join(DIR, 'rel-root')
  fs.mkdirSync(path.join(root, 'docs 2'), { recursive: true })
  fs.writeFileSync(path.join(root, 'docs 2', 'a.md'), 'x')
  check('相对 href 判定', isRelativeHref('docs/a.md') && isRelativeHref('./a.md') && isRelativeHref('../a.md#3') && isRelativeHref('file://docs/a.md'))
  check('绝对与带 scheme 的不判', !isRelativeHref('file:///a/b.md#1') && !isRelativeHref('vscode://file/a/') && !isRelativeHref('https://e.com') && !isRelativeHref('#anchor') && !isRelativeHref('/abs/a.md') && !isRelativeHref('mailto:a@b.c'))
  const r = relativeLinks('见 [a.md:3](docs%202/a.md#3) 与 [docs](docs%202) 与 [丢](nope/x.md)', root)
  check('解析到文件 → 给 file:// 绝对链接带行号', r[0] && r[0].fix === `file://${path.join(root, 'docs%202', 'a.md').replace('docs%202', 'docs%202')}#3`, JSON.stringify(r))
  check('解析到目录 → 给 vscode://file/ 以斜杠结尾', r[1] && r[1].fix === `vscode://file${root}/docs%202/`, JSON.stringify(r))
  check('解析不到 → fix 为 null', r[2] && r[2].fix === null)
  check('同 href 不同标签各列一条', relativeLinks('[A](x.md) [B](x.md) [A](x.md)', root).length === 2)
  check('围栏代码块与行内代码里的不算', relativeLinks('```\n[a](docs/a.md)\n```\n写成 `[a](docs/a.md)` 是错的', root).length === 0)
  check('只开相对核对时不跑裸写核对', termLinksReason('[词](file:///x.md#1) 词', null, { linkAudit: false, relativeAudit: true, cwd: root }) === '')
  check('相对核对 reason 含改法', termLinksReason('[a](docs%202/a.md)', null, { linkAudit: false, relativeAudit: true, cwd: root }).includes('→ 改成 [a](file://'))
  check('默认（旧调用形态）不跑相对核对', termLinksReason('[a](docs/a.md)') === '')
  check('宿主门控：终端开、webview 与 Codex 关', relativeLinkAuditEnabled({}, {}) && !relativeLinkAuditEnabled({ CLAUDE_CODE_ENTRYPOINT: 'claude-vscode' }, {}) && !relativeLinkAuditEnabled({ PLUGIN_ROOT: '/x' }, {}) && !relativeLinkAuditEnabled({}, { turn_id: 't' }))
}

fs.rmSync(DIR, { recursive: true, force: true })
console.log(`stop-audit: ${pass} passed, ${fail} failed`)
process.exit(fail === 0 ? 0 : 1)
