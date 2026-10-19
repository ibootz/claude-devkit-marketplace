#!/usr/bin/env node
// compact-agent-status-verify.js — compact-agent-status.js 的回归套件
//
// 用法：node plugins/devkit-discipline/test/compact-agent-status-verify.js
// 退出码 0 = 全绿，1 = 有用例失败。
//
// 夹具是手写的最小 JSONL，行形态照抄 Claude Code 2.1.303 真实 transcript 的四类行
// （Agent tool_use / 转后台 tool_result / 三种通知载体 / SendMessage 唤醒回执）。
// 用 spawnSync 喂 stdin，不经 shell（同 guard-verify.js 的理由）。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')

const HOOK = path.join(__dirname, '..', 'hooks', 'compact-agent-status.js')
const DIR = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'wd-cas-test-')))

let pass = 0
let fail = 0
let seq = 0

function check(name, cond, detail) {
  if (cond) {
    pass += 1
  } else {
    fail += 1
    console.log(`FAIL ${name}${detail ? `\n     ${detail}` : ''}`)
  }
}

// ---- 夹具行 ----
function ts(min) {
  return new Date(Date.UTC(2026, 9, 19, 3, min, 0)).toISOString()
}
function launch(toolId, name, desc, min) {
  return {
    type: 'assistant',
    isSidechain: false,
    timestamp: ts(min),
    message: { role: 'assistant', content: [{ type: 'tool_use', id: toolId, name: 'Agent', input: { name, description: desc, prompt: 'x' } }] },
  }
}
function launched(toolId, agentId, min, outFile) {
  return {
    type: 'user',
    isSidechain: false,
    timestamp: ts(min),
    message: {
      role: 'user',
      content: [{
        type: 'tool_result',
        tool_use_id: toolId,
        content: [{ type: 'text', text: `Async agent launched successfully.\nagentId: ${agentId} (internal ID)\noutput_file: ${outFile || `/tmp/tasks/${agentId}.output`}\n` }],
      }],
    },
  }
}
function syncResult(toolId, min) {
  return {
    type: 'user', isSidechain: false, timestamp: ts(min),
    message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: toolId, content: [{ type: 'text', text: '子代理同步回执正文' }] }] },
  }
}
function notice(agentId, status, n) {
  return `<task-notification>\n<task-id>${agentId}</task-id>\n<output-file>/tmp/tasks/${agentId}.output</output-file>\n<status>${status}</status>\n<summary>Agent finished #${n}</summary>\n</task-notification>`
}
function enqueue(agentId, status, min, n) {
  return { type: 'queue-operation', operation: 'enqueue', timestamp: ts(min), content: notice(agentId, status, n) }
}
function queuedAttachment(agentId, status, min, n) {
  return { type: 'attachment', isSidechain: false, timestamp: ts(min), attachment: { type: 'queued_command', prompt: notice(agentId, status, n) } }
}
function userNotice(agentId, status, min, n) {
  return { type: 'user', isSidechain: false, timestamp: ts(min), message: { role: 'user', content: notice(agentId, status, n) } }
}
function resumed(agentId, min) {
  return {
    type: 'user', isSidechain: false, timestamp: ts(min),
    message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: `sm-${min}`, content: [{ type: 'text', text: `{"success":true,"message":"Resuming agent","resumedAgentId":"${agentId}"}` }] }] },
  }
}
function quotedInToolResult(agentId, min) {
  return {
    type: 'user', isSidechain: false, timestamp: ts(min),
    message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: `grep-${min}`, content: [{ type: 'text', text: `grep 命中：${notice(agentId, 'completed', 99)}` }] }] },
  }
}
function promptSnapshot(agentId) {
  // 真实 transcript 里 prompt_snapshot 行带工具描述原文，含 <task-notification> 字样
  return { type: 'attachment', isSidechain: false, attachment: { type: 'prompt_snapshot', systemPrompt: [notice(agentId, 'completed', 98)] } }
}

function writeTranscript(rows) {
  seq += 1
  const p = path.join(DIR, `t${seq}.jsonl`)
  fs.writeFileSync(p, rows.map((r) => JSON.stringify(r)).join('\n') + '\n')
  return p
}

function run(payload) {
  const r = spawnSync(process.execPath, [HOOK], { input: JSON.stringify(payload), encoding: 'utf8' })
  return { code: r.status, stdout: r.stdout || '', stderr: r.stderr || '' }
}
function pre(p) {
  return run({ hook_event_name: 'PreCompact', trigger: 'auto', transcript_path: p })
}
function post(p, source) {
  const r = run({ hook_event_name: 'SessionStart', source: source || 'compact', transcript_path: p })
  let json = null
  if (r.stdout.trim()) {
    try { json = JSON.parse(r.stdout) } catch (e) { json = { __parseError: r.stdout } }
  }
  return Object.assign(r, { json })
}
function lineOf(out, agentId) {
  return out.split('\n').find((l) => l.includes(`agentId ${agentId}`)) || ''
}

// ---- 用例 ----

// 1. sptalent 事故形态：完成通知只以入队行存在（投递副本落在被放弃分支、甚至缺失）
{
  const p = writeTranscript([
    launch('tu1', 'sonnet-spsd-prod-check', '核 spsd 产线', 26),
    launched('tu1', 'aaa111', 26),
    launch('tu2', 'sonnet-upstream-doc-fix', '订正交付文档', 26),
    launched('tu2', 'bbb222', 26),
    enqueue('aaa111', 'completed', 29, 1),
  ])
  const r = pre(p)
  check('事故形态：exit 0', r.code === 0, r.stderr)
  check('事故形态：已完成的判为已完成', lineOf(r.stdout, 'aaa111').startsWith('- 已完成'), r.stdout)
  check('事故形态：未完成的写「未见完成通知」而非「运行中」', lineOf(r.stdout, 'bbb222').startsWith('- 未见完成通知'), r.stdout)
  check('事故形态：PreCompact 输出是纯文本、带写摘要的要求', r.stdout.includes('写摘要时') && !r.stdout.trim().startsWith('{'), r.stdout)
  const s = post(p)
  const ctx = s.json && s.json.hookSpecificOutput
  check('SessionStart(compact)：hookEventName 回声为 SessionStart', ctx && ctx.hookEventName === 'SessionStart', s.stdout)
  check('SessionStart(compact)：表里同样判已完成', ctx && lineOf(ctx.additionalContext, 'aaa111').startsWith('- 已完成'), s.stdout)
}

// 2. 三种载体重复投递同一条通知 → 只算一次，状态正确
{
  const p = writeTranscript([
    launch('tu1', 'a', 'd', 1), launched('tu1', 'c1', 1),
    enqueue('c1', 'completed', 5, 1), queuedAttachment('c1', 'completed', 6, 1), userNotice('c1', 'completed', 6, 1),
  ])
  check('三载体去重：判已完成', lineOf(pre(p).stdout, 'c1').startsWith('- 已完成'))
}

// 3. 完成 → SendMessage 唤醒 → 迟到的同一条通知副本 → 仍判进行中
{
  const p = writeTranscript([
    launch('tu1', 'a', 'd', 1), launched('tu1', 'r1', 1),
    enqueue('r1', 'completed', 5, 1), resumed('r1', 7), queuedAttachment('r1', 'completed', 8, 1),
  ])
  check('唤醒后迟到副本不回滚状态', lineOf(pre(p).stdout, 'r1').startsWith('- 未见完成通知'), pre(p).stdout)
}

// 4. 唤醒后再次完成（新通知）→ 已完成
{
  const p = writeTranscript([
    launch('tu1', 'a', 'd', 1), launched('tu1', 'r2', 1),
    enqueue('r2', 'completed', 5, 1), resumed('r2', 7), enqueue('r2', 'completed', 9, 2),
  ])
  check('唤醒后再次完成', lineOf(pre(p).stdout, 'r2').startsWith('- 已完成'))
}

// 5. failed / killed 状态照实标注
{
  const p = writeTranscript([
    launch('tu1', 'a', 'd', 1), launched('tu1', 'f1', 1), enqueue('f1', 'failed', 3, 1),
    launch('tu2', 'b', 'd', 1), launched('tu2', 'k1', 1), enqueue('k1', 'killed', 4, 1),
  ])
  const out = pre(p).stdout
  check('failed → 失败', lineOf(out, 'f1').startsWith('- 失败'), out)
  check('killed → 已终止', lineOf(out, 'k1').startsWith('- 已终止'), out)
}

// 6. tool_result 里引用的通知原文、prompt_snapshot 里的工具描述 → 都不算通知
{
  const p = writeTranscript([
    promptSnapshot('q1'),
    launch('tu1', 'a', 'd', 1), launched('tu1', 'q1', 1), quotedInToolResult('q1', 3),
  ])
  check('引用的通知原文不算完成', lineOf(pre(p).stdout, 'q1').startsWith('- 未见完成通知'), pre(p).stdout)
}

// 7. 同步返回的子代理不进表；没有后台子代理 → 两种触发都零输出
{
  const p = writeTranscript([launch('tu1', 'a', 'd', 1), syncResult('tu1', 2)])
  check('同步子代理：PreCompact 零输出', pre(p).stdout === '')
  check('同步子代理：SessionStart 零输出', post(p).stdout === '')
}

// 8. 不归本 hook 管的触发 → 零输出
{
  const p = writeTranscript([launch('tu1', 'a', 'd', 1), launched('tu1', 'x1', 1)])
  check('SessionStart(startup) 零输出', post(p, 'startup').stdout === '')
  check('SessionStart(resume) 零输出', post(p, 'resume').stdout === '')
  check('UserPromptSubmit 零输出', run({ hook_event_name: 'UserPromptSubmit', transcript_path: p }).stdout === '')
  check('子代理自己的 PreCompact 零输出', run({ hook_event_name: 'PreCompact', agent_id: 'sub1', transcript_path: p }).stdout === '')
}

// 9. 失效不谎报：transcript 不存在 / 空 stdin → 零输出且 exit 0
{
  const r = pre(path.join(DIR, 'nope.jsonl'))
  check('transcript 不存在：exit 0 零输出', r.code === 0 && r.stdout === '', r.stderr)
  const r2 = spawnSync(process.execPath, [HOOK], { input: '', encoding: 'utf8' })
  check('空 stdin：exit 0 零输出', r2.status === 0 && (r2.stdout || '') === '')
}

// 10. 已结束的只列最近 MAX_FINISHED 个，进行中的全列；同目录回执只写一次目录
{
  const { MAX_FINISHED } = require(HOOK)
  const rows = []
  const total = MAX_FINISHED + 3
  for (let i = 0; i < total; i += 1) {
    rows.push(launch(`tu${i}`, `n${i}`, 'd', 1), launched(`tu${i}`, `z${i}`, 1, `/tmp/tasks/z${i}.output`), enqueue(`z${i}`, 'completed', 10 + i, i))
  }
  rows.push(launch('tuR', 'live', 'd', 30), launched('tuR', 'live1', 30))
  const out = pre(writeTranscript(rows)).stdout
  check('最近结束的列出', lineOf(out, `z${total - 1}`) !== '', out)
  check('最早结束的被截掉', lineOf(out, 'z0') === '', out)
  check('截掉的数目写明', out.includes('另有 3 个更早结束的子代理未列出'), out)
  check('进行中的仍列出', lineOf(out, 'live1').startsWith('- 未见完成通知'), out)
  check('回执目录只写一次', out.includes('回执文件所在目录：/tmp/tasks/') && lineOf(out, `z${total - 1}`).includes(`回执 z${total - 1}.output`), out)
}

// 11. 截断的半行、坏 JSON、非 JSON 行不影响其余判定
{
  const p = writeTranscript([launch('tu1', 'a', 'd', 1), launched('tu1', 'g1', 1)])
  fs.appendFileSync(p, '{"type":"user","message":{"content":"<task-notification><task-id>g1</task-id>\nnot json at all\n')
  check('坏行跳过', lineOf(pre(p).stdout, 'g1').startsWith('- 未见完成通知'), pre(p).stdout)
}

fs.rmSync(DIR, { recursive: true, force: true })
console.log(`compact-agent-status: ${pass} passed, ${fail} failed`)
process.exit(fail === 0 ? 0 : 1)
