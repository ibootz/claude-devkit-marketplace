#!/usr/bin/env node
// readable-citations 的回归用例。
//
// 用 spawnSync 直接把 JSON 喂给子进程 stdin，**不经过 shell**——经过 shell 的测试脚本
// 一旦引号失衡，本仓其它 guard 会把测试数据当成真命令拦下并原样回灌进 finding。
// 判据见 .claude/rules/project/hook-restraint.md 的「已存在的 hook 怎么办」第 5 条。
//
// 跑法：node plugins/readable-citations/hooks/tests/readable-citations.test.js

'use strict'

const { spawnSync } = require('child_process')
const path = require('path')

const HOOK = path.join(__dirname, '..', 'readable-citations.js')

function run(payload, env = {}) {
  const r = spawnSync(process.execPath, [HOOK], {
    input: typeof payload === 'string' ? payload : JSON.stringify(payload),
    encoding: 'utf8',
    env: { ...process.env, ...env },
  })
  return { status: r.status, stdout: (r.stdout || '').trim() }
}

const cases = [
  {
    name: '主会话事件：回声 UserPromptSubmit 并注入正文',
    run: () => run({ hook_event_name: 'UserPromptSubmit', prompt: 'x' }),
    check: (r) => {
      if (r.status !== 0) return `exit=${r.status}，期望 0`
      const d = JSON.parse(r.stdout)
      if (d.hookSpecificOutput.hookEventName !== 'UserPromptSubmit') return '事件名未按入参回声'
      if (!d.hookSpecificOutput.additionalContext.includes('自足')) return '注入正文缺关键概念'
      return null
    },
  },
  {
    name: '子代理事件：回声 SubagentStart（写死任一事件名会让这一路静默失效）',
    run: () => run({ hook_event_name: 'SubagentStart', agent_type: 'Explore' }),
    check: (r) => {
      if (r.status !== 0) return `exit=${r.status}，期望 0`
      const d = JSON.parse(r.stdout)
      if (d.hookSpecificOutput.hookEventName !== 'SubagentStart') return '事件名未按入参回声'
      return null
    },
  },
  {
    name: '白名单外的事件名：静默退出，不回声来路不明的字符串',
    run: () => run({ hook_event_name: 'PreToolUse' }),
    check: (r) => (r.status === 0 && r.stdout === '' ? null : `exit=${r.status} stdout=${r.stdout}`),
  },
  {
    name: '关闭开关 READABLE_CITATIONS=off：不注入',
    run: () => run({ hook_event_name: 'UserPromptSubmit' }, { READABLE_CITATIONS: 'off' }),
    check: (r) => (r.status === 0 && r.stdout === '' ? null : `exit=${r.status} stdout=${r.stdout}`),
  },
  {
    name: '空 stdin：不崩、不注入',
    run: () => run(''),
    check: (r) => (r.status === 0 && r.stdout === '' ? null : `exit=${r.status} stdout=${r.stdout}`),
  },
  {
    name: '畸形 JSON：不崩、不注入',
    run: () => run('{not json'),
    check: (r) => (r.status === 0 && r.stdout === '' ? null : `exit=${r.status} stdout=${r.stdout}`),
  },
  {
    name: '两轨链接形态都在正文里（落盘 md 走相对路径是本插件的核心判据）',
    run: () => run({ hook_event_name: 'UserPromptSubmit' }),
    check: (r) => {
      const ctx = JSON.parse(r.stdout).hookSpecificOutput.additionalContext
      if (!ctx.includes('file:///')) return '缺对话正文那一轨（绝对路径）'
      if (!ctx.includes('../')) return '缺落盘 md 那一轨（相对路径）'
      return null
    },
  },
]

let failed = 0
for (const c of cases) {
  const err = c.check(c.run())
  if (err) {
    failed += 1
    console.log(`FAIL  ${c.name}\n      ${err}`)
  } else {
    console.log(`ok    ${c.name}`)
  }
}

console.log(`\n${cases.length - failed}/${cases.length} passed`)
process.exit(failed === 0 ? 0 : 1)
