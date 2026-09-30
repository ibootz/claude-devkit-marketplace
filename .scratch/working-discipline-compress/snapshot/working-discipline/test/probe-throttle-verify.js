#!/usr/bin/env node
// probe-throttle-verify.js — probe-throttle.js 的回归套件
//
// 用法：node plugins/working-discipline/test/probe-throttle-verify.js
// 退出码 0 = 全绿，1 = 有用例失败。
//
// 【为什么用 spawnSync 而不是 shell 管道】
// 同 guard-verify.js：payload 是 JSON，经 shell 会因引号问题变形。这里还有第二个理由——
// 本 hook 的判定依赖磁盘 state，必须让每个用例跑在独立进程里才算真实复现。
//
// 【为什么不 sleep 也能测"串行"】
// hook 用 BATCH_WINDOW_MS 时间窗区分「同批并发」与「逐个串行」。要测串行本该等 1 秒以上，
// 6 次用例就是 6 秒多。改为直接把 state 里的 lastAt 改写成 5 秒前——这正是 hook 读到的
// 唯一时间输入，改它等价于"上一次调用发生在很久以前"，比 sleep 快且确定。
// 反过来，测"同批"时连续 spawn 且不动 lastAt，天然落在窗口内。
//
// 【判据两侧都要有用例】
// 一侧是「该拦的拦住」（串行满 6 次 → deny）；另一侧是「不该拦的放行」——尤其
// **同批并发 6 次一次都不许拦**，那是本 hook 最严重的假阳性面，若这条红了说明奖惩反了。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')

const HOOK = path.join(__dirname, '..', 'hooks', 'guards', 'probe-throttle.js')
const M = require(HOOK)

const STATE_DIR = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'wd-probe-test-')))

let pass = 0
let fail = 0

function run(payload, opts) {
  const env = Object.assign({}, process.env, {
    WD_PROBE_STATE_DIR: (opts && opts.stateDir) || STATE_DIR,
  })
  const r = spawnSync(process.execPath, [HOOK], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    env,
  })
  let json = null
  if (r.stdout && r.stdout.trim()) {
    try {
      json = JSON.parse(r.stdout)
    } catch (e) {
      json = { __parseError: r.stdout }
    }
  }
  return { code: r.status, stdout: r.stdout || '', json, stderr: r.stderr || '' }
}

function probe(session, tool) {
  return {
    session_id: session,
    transcript_path: '/tmp/nonexistent.jsonl',
    cwd: '/tmp',
    hook_event_name: 'PreToolUse',
    tool_name: tool || 'Read',
    tool_input: { file_path: '/tmp/x' },
  }
}

function stateFileOf(session, dir) {
  return path.join(dir || STATE_DIR, `${session}.json`)
}

function readState(session, dir) {
  try {
    return JSON.parse(fs.readFileSync(stateFileOf(session, dir), 'utf8'))
  } catch (e) {
    return null
  }
}

function seed(session, state, dir) {
  const f = stateFileOf(session, dir)
  fs.mkdirSync(path.dirname(f), { recursive: true })
  fs.writeFileSync(f, JSON.stringify(state))
}

// 把"上一次调用"推到 5 秒前，让下一次调用被判为串行而非同批。
function markSerial(session, dir) {
  const s = readState(session, dir)
  if (!s) return
  s.lastAt = Date.now() - 5000
  fs.writeFileSync(stateFileOf(session, dir), JSON.stringify(s))
}

function check(name, cond, detail) {
  if (cond) {
    pass += 1
    return
  }
  fail += 1
  console.log(`FAIL  ${name}`)
  if (detail !== undefined) console.log(`      ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`)
}

const out = (r) => (r.json && r.json.hookSpecificOutput) || {}
const isDeny = (r) => out(r).permissionDecision === 'deny'
const hasNotice = (r) => typeof out(r).additionalContext === 'string' && out(r).additionalContext.length > 0

// ── 1. 常量与注入文本口径一致 ────────────────────────────────────────
// DENY_AT 必须等于零章检查点②写的次数线。两处不一致 = AI 读到的判据与真正拦它的判据不同。
{
  const injected = fs.readFileSync(path.join(__dirname, '..', 'hooks', 'working-discipline.js'), 'utf8')
  check('DENY_AT 与注入文本的次数线一致（6）', M.DENY_AT === 6, `DENY_AT=${M.DENY_AT}`)
  check('注入文本里写着 ≥6 次只读检索', injected.includes('≥6 次只读检索'))
  check('NOTICE_AT < DENY_AT', M.NOTICE_AT < M.DENY_AT, `${M.NOTICE_AT} / ${M.DENY_AT}`)
}

// ── 2. 会话早期零成本：前 3 次串行检索不输出任何东西 ──────────────────
{
  const s = 'early'
  for (let i = 1; i <= M.NOTICE_AT - 1; i += 1) {
    const r = run(probe(s))
    check(`第 ${i} 次串行检索无输出`, r.stdout.trim() === '' && r.code === 0, r.stdout)
    markSerial(s)
  }
  check('前 3 次已记账', (readState(s) || {}).probes === M.NOTICE_AT - 1, readState(s))
}

// ── 3. 达到 NOTICE_AT 起注入计数，且不带 permissionDecision ───────────
{
  const s = 'notice'
  seed(s, { probes: M.NOTICE_AT - 1, denies: 0, deniedSinceDispatch: false, lastAt: Date.now() - 5000 })
  const r = run(probe(s))
  check('第 4 次注入 additionalContext', hasNotice(r), r.stdout)
  check('第 4 次不表态权限', out(r).permissionDecision === undefined, out(r))
  check('回声 hookEventName 为 PreToolUse', out(r).hookEventName === 'PreToolUse', out(r))
  check('注入文本含实时计数', /4 次只读检索/.test(out(r).additionalContext || ''), out(r).additionalContext)
}

// ── 4. 达到 DENY_AT 时 deny 一次，finding 里给可照抄出路 ──────────────
{
  const s = 'deny'
  seed(s, { probes: M.DENY_AT - 1, denies: 0, deniedSinceDispatch: false, lastAt: Date.now() - 5000 })
  const r = run(probe(s))
  check('第 6 次串行检索被 deny', isDeny(r), r.stdout)
  const reason = out(r).permissionDecisionReason || ''
  check('deny 文案给了可照抄的并发派发 JSON', reason.includes('"subagent_type": "Explore"'), reason.slice(0, 120))
  check('deny 文案写明重发即放行', reason.includes('原样重发'), reason.slice(0, 120))
  check('deny 文案说明并发不计数', reason.includes('同批'), reason.slice(0, 120))
  check('deny 后置了 deniedSinceDispatch', (readState(s) || {}).deniedSinceDispatch === true, readState(s))
  check('deny 计入 denies', (readState(s) || {}).denies === 1, readState(s))
  check('deny 时退出码仍为 0', r.code === 0, `code=${r.code}`)

  // 自解除：原样重发同一调用应放行（本段不再拦第二次）
  markSerial(s)
  const again = run(probe(s))
  check('deny 后原样重发即放行', !isDeny(again), again.stdout)
  check('重发时仍给计数提示', hasNotice(again), again.stdout)
}

// ── 5. 最严重的假阳性面：同批并发不许拦、不许注入 ─────────────────────
// 一条消息里并发 8 个 Read 会连触发 8 次 hook。这些调用之间没有 markSerial，
// 因此全部落在 BATCH_WINDOW_MS 内。**一次都不能 deny**——否则等于惩罚正确的并行行为。
{
  const s = 'batch'
  let denied = 0
  let noticed = 0
  for (let i = 0; i < M.DENY_AT + 2; i += 1) {
    const r = run(probe(s))
    if (isDeny(r)) denied += 1
    if (hasNotice(r)) noticed += 1
  }
  check('同批并发 8 次一次都不 deny', denied === 0, `denied=${denied}`)
  check('同批并发不重复注入', noticed <= 1, `noticed=${noticed}`)
  check('同批仍照实计数', (readState(s) || {}).probes === M.DENY_AT + 2, readState(s))
}

// ── 6. Agent 派发清零，且不对 Agent 表态权限 ──────────────────────────
{
  const s = 'dispatch'
  seed(s, { probes: M.DENY_AT + 3, denies: 1, deniedSinceDispatch: true, lastAt: Date.now() - 5000 })
  const r = run(Object.assign(probe(s), { tool_name: 'Agent', tool_input: { model: 'sonnet' } }))
  check('Agent 调用不输出任何决定', r.stdout.trim() === '', r.stdout)
  const st = readState(s) || {}
  check('Agent 派发把 probes 清零', st.probes === 0, st)
  check('Agent 派发解除 deniedSinceDispatch', st.deniedSinceDispatch === false, st)
  check('Agent 派发保留 denies 累计（熔断不被绕过）', st.denies === 1, st)

  markSerial(s)
  const after = run(probe(s))
  check('派发后第 1 次检索回到零成本', after.stdout.trim() === '', after.stdout)
}

// ── 7. 旧工具名 Task 同样算派发 ───────────────────────────────────────
{
  const s = 'legacy-task'
  seed(s, { probes: 9, denies: 0, deniedSinceDispatch: true, lastAt: Date.now() - 5000 })
  run(Object.assign(probe(s), { tool_name: 'Task' }))
  check('Task 也清零', (readState(s) || {}).probes === 0, readState(s))
}

// ── 8. 单会话 deny 上限熔断 ───────────────────────────────────────────
{
  const s = 'fuse'
  seed(s, { probes: M.DENY_AT, denies: M.MAX_DENIES, deniedSinceDispatch: false, lastAt: Date.now() - 5000 })
  const r = run(probe(s))
  check('denies 达上限后不再 deny', !isDeny(r), r.stdout)
  check('熔断后仍注入计数', hasNotice(r), r.stdout)
}

// ── 9. 子代理一律放行且不记账 ─────────────────────────────────────────
{
  const s = 'sub'
  seed(s, { probes: M.DENY_AT - 1, denies: 0, deniedSinceDispatch: false, lastAt: Date.now() - 5000 })
  const r = run(Object.assign(probe(s), { agent_id: 'a123-abc' }))
  check('带 agent_id 时无输出', r.stdout.trim() === '', r.stdout)
  check('带 agent_id 时不记账', (readState(s) || {}).probes === M.DENY_AT - 1, readState(s))
}

// ── 10. 事件与工具的门控 ──────────────────────────────────────────────
{
  const s = 'gate'
  seed(s, { probes: M.DENY_AT - 1, denies: 0, deniedSinceDispatch: false, lastAt: Date.now() - 5000 })

  const wrongEvent = run(Object.assign(probe(s), { hook_event_name: 'PostToolUse' }))
  check('非 PreToolUse 事件无输出', wrongEvent.stdout.trim() === '', wrongEvent.stdout)
  check('非 PreToolUse 事件不记账', (readState(s) || {}).probes === M.DENY_AT - 1, readState(s))

  const nonProbe = run(Object.assign(probe(s), { tool_name: 'Write' }))
  check('Write 不计入只读检索', nonProbe.stdout.trim() === '', nonProbe.stdout)
  check('Write 不改计数', (readState(s) || {}).probes === M.DENY_AT - 1, readState(s))

  const bash = run(Object.assign(probe(s), { tool_name: 'Bash', tool_input: { command: 'ls' } }))
  check('Bash 计入并触发 deny（与 dispatch-ledger 同口径）', isDeny(bash), bash.stdout)
}

// ── 11. fail-open：state 目录不可写时放行 ─────────────────────────────
{
  const blocked = path.join(STATE_DIR, 'blocked')
  fs.mkdirSync(blocked, { recursive: true })
  fs.chmodSync(blocked, 0o500) // r-x：不能创建文件
  const r = run(probe('ro'), { stateDir: path.join(blocked, 'nested') })
  check('state 不可写时不 deny', !isDeny(r), r.stdout)
  check('state 不可写时退出码 0', r.code === 0, `code=${r.code} stderr=${r.stderr}`)
  fs.chmodSync(blocked, 0o700)
}

// ── 12. 坏输入 ────────────────────────────────────────────────────────
{
  const empty = spawnSync(process.execPath, [HOOK], { input: '', encoding: 'utf8', env: Object.assign({}, process.env, { WD_PROBE_STATE_DIR: STATE_DIR }) })
  check('空 stdin 不输出、退出码 0', (empty.stdout || '').trim() === '' && empty.status === 0, empty.stdout)

  const bad = spawnSync(process.execPath, [HOOK], { input: '{not json', encoding: 'utf8', env: Object.assign({}, process.env, { WD_PROBE_STATE_DIR: STATE_DIR }) })
  check('坏 JSON 不输出、退出码 0', (bad.stdout || '').trim() === '' && bad.status === 0, bad.stdout)

  const noSession = run({ hook_event_name: 'PreToolUse', tool_name: 'Read' })
  check('缺 session_id 不崩', noSession.code === 0, noSession.stderr)
}

// ── 13. 损坏的 state 文件按零值起算，不崩 ─────────────────────────────
{
  const s = 'corrupt'
  const f = stateFileOf(s)
  fs.mkdirSync(path.dirname(f), { recursive: true })
  fs.writeFileSync(f, '{"probes": "not-a-number", "lastAt": null}')
  const r = run(probe(s))
  check('损坏 state 不崩且不 deny', r.code === 0 && !isDeny(r), r.stdout)
  check('损坏 state 从 1 重新起算', (readState(s) || {}).probes === 1, readState(s))
}

// ── 收尾 ──────────────────────────────────────────────────────────────
try {
  fs.rmSync(STATE_DIR, { recursive: true, force: true })
} catch (e) {
  /* 临时目录清理失败不影响判定 */
}

console.log(`\nprobe-throttle: ${pass} passed, ${fail} failed`)
process.exit(fail === 0 ? 0 : 1)
