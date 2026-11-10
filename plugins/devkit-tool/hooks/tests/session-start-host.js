#!/usr/bin/env node
// devkit-tool session-start.js 的宿主分流用例（加 Codex 分支时加）。
//
// 守两件事：
//   1. Claude Code 宿主下输出逐字节等于加 Codex 分支之前的行为：context/session-start.md
//      去首尾空白后整段作为 additionalContext，事件名回声 SessionStart。
//   2. Codex 宿主（环境变量 PLUGIN_ROOT 非空，或入参含 turn_id）下不输出任何东西——
//      注入内容讲的是 ListAgents / SendMessage 跨会话通信，Codex 没有这些工具。
// 跑法：node plugins/devkit-tool/hooks/tests/session-start-host.js

'use strict'

const { spawnSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const HOOK = path.join(__dirname, '..', 'session-start.js')
const BODY = fs.readFileSync(path.join(__dirname, '..', '..', 'context', 'session-start.md'), 'utf8').trim()

function run(input, env = {}) {
  const base = { ...process.env }
  delete base.PLUGIN_ROOT
  const r = spawnSync(process.execPath, [HOOK], { input, encoding: 'utf8', env: { ...base, ...env } })
  return { status: r.status, stdout: r.stdout || '' }
}

const WANT = JSON.stringify({ hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: BODY } }) + '\n'

const cases = [
  ['Claude · 入参 SessionStart：整段注入，逐字节一致', () => run('{"hook_event_name":"SessionStart","source":"startup"}').stdout === WANT],
  ['Claude · 入参为空：按 SessionStart 注入', () => run('').stdout === WANT],
  ['Claude · 入参是别的事件：静默', () => run('{"hook_event_name":"UserPromptSubmit"}').stdout === ''],
  ['Claude · CLAUDE_PLUGIN_ROOT 单独存在不算 Codex', () => run('{"hook_event_name":"SessionStart"}', { CLAUDE_PLUGIN_ROOT: '/x' }).stdout === WANT],
  ['Codex · PLUGIN_ROOT 非空：不注入', () => { const r = run('{"hook_event_name":"SessionStart"}', { PLUGIN_ROOT: '/x' }); return r.status === 0 && r.stdout === '' }],
  ['Codex · 入参含 turn_id：不注入', () => { const r = run('{"hook_event_name":"SessionStart","turn_id":"t-1"}'); return r.status === 0 && r.stdout === '' }],
]

let failed = 0
for (const [name, check] of cases) {
  const ok = check()
  if (!ok) failed += 1
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${name}`)
}
console.log(`\n${cases.length - failed}/${cases.length} passed`)
process.exit(failed === 0 ? 0 : 1)
