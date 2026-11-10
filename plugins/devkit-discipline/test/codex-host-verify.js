#!/usr/bin/env node
// codex-host-verify.js — working-discipline / dispatch-ledger 的宿主分流回归（4.14.0 加）
//
// 用法：node plugins/devkit-discipline/test/codex-host-verify.js [--update-golden]
//
// 守两件事：
//   1. Claude Code 宿主下三层注入逐字不变。golden-claude/*.txt 是加 Codex 分支**之前**的输出
//      （`--update-golden` 生成；插件根绝对路径替换成 `<PLUGIN_ROOT>`，换机器也能比）。
//      改 Claude 侧措辞时先在 commit 里写清理由，再重跑 `--update-golden`。
//   2. Codex 宿主（环境变量 PLUGIN_ROOT 非空，或入参含 turn_id）下，依赖 Claude Code 专属工具的
//      段落不注入：`Agent` 字段判据与 model 档位、Explore / Plan / general-purpose 类型、
//      `AskUserQuestion`、`TaskList`、team 模式、system prompt 里 AgentTool 禁令的授权对冲、
//      `agent-dispatch.js` 那道闸（它挂在 `Agent` 工具上，Codex 没有这个工具）。
//      与工具无关的纪律（上下文、表达、求真、七章）照常注入。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')

const PLUGIN = path.join(__dirname, '..')
const WD = path.join(PLUGIN, 'hooks', 'working-discipline.js')
const LEDGER = path.join(PLUGIN, 'hooks', 'dispatch-ledger.js')
const GOLDEN = path.join(__dirname, 'golden-claude')
const UPDATE = process.argv.includes('--update-golden')

function run(script, payload, env = {}) {
  const base = { ...process.env }
  delete base.PLUGIN_ROOT
  const r = spawnSync(process.execPath, [script], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    env: { ...base, ...env },
  })
  return { status: r.status, stdout: (r.stdout || '').trim() }
}

const ctxOf = (r) => JSON.parse(r.stdout).hookSpecificOutput.additionalContext
const norm = (s) => s.split(PLUGIN).join('<PLUGIN_ROOT>')

const IMAGE_PROMPT = '看这张图 [Image: source: /Users/me/Desktop/shots/bug.png] 为什么按钮是灰的'

// Claude 侧快照：三个事件 + 有图轮次 + 子代理三种 agent_type。
const SNAPSHOTS = {
  'session-start.txt': { hook_event_name: 'SessionStart', source: 'startup' },
  'user-prompt.txt': { hook_event_name: 'UserPromptSubmit', prompt: 'x' },
  'user-prompt-image.txt': { hook_event_name: 'UserPromptSubmit', prompt: IMAGE_PROMPT },
  'subagent-general.txt': { hook_event_name: 'SubagentStart', agent_type: 'general-purpose' },
  'subagent-explore.txt': { hook_event_name: 'SubagentStart', agent_type: 'Explore' },
  'subagent-untyped.txt': { hook_event_name: 'SubagentStart' },
}

const cases = []

const snaps = {}
for (const [f, payload] of Object.entries(SNAPSHOTS)) snaps[f] = norm(run(WD, payload).stdout)
if (UPDATE) {
  fs.mkdirSync(GOLDEN, { recursive: true })
  for (const [f, s] of Object.entries(snaps)) fs.writeFileSync(path.join(GOLDEN, f), s + '\n')
  console.log(`golden 已写入 ${Object.keys(snaps).length} 份`)
  process.exit(0)
}
for (const [f, s] of Object.entries(snaps)) {
  cases.push({
    name: `Claude 宿主与 golden 逐字一致：${f}`,
    check: () => {
      const want = fs.readFileSync(path.join(GOLDEN, f), 'utf8').replace(/\n$/, '')
      return s === want ? null : '与 golden 不一致（Claude 侧注入变了）'
    },
  })
}

// Codex 下一律不得出现的 Claude 专属工具 / 机制名。
const CLAUDE_ONLY = [
  '`Agent`', 'AskUserQuestion', 'AgentTool', '`Explore`', '`Plan`', 'general-purpose',
  'subagent_type', 'TaskList', 'CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS', 'agent-dispatch',
  'model` 必填', 'sonnet', 'opus', 'SendMessage', 'run_in_background',
]

const CODEX_HOSTS = [
  ['PLUGIN_ROOT 非空', {}, { PLUGIN_ROOT: '/x/plugin' }],
  ['入参含 turn_id', { turn_id: 't-1' }, {}],
]

const KEEP = {
  'session-start': ['## 一、上下文纪律', '**3.4 求真**', '**3.7 裸值带含义**', '## 七、动手与求真边界', '5.5 等齐再总结', '`bash-guard.js`', '`write-guard.js`', '**嵌套上限 2 层**'],
  'user-prompt': ['## 零、并行优先', '## 每轮自查', '## 解释类回复', '## 画图', '在正文里问'],
  subagent: ['# AI 工作纪律（子代理版）', '**一切输出用简体中文**', '## 零、并行优先', '## 一、上下文纪律', '## 三、表达约束', '**嵌套上限 2 层**'],
}

for (const [label, extra, env] of CODEX_HOSTS) {
  for (const [kind, payload] of [
    ['session-start', { hook_event_name: 'SessionStart' }],
    ['user-prompt', { hook_event_name: 'UserPromptSubmit', prompt: 'x' }],
    ['subagent', { hook_event_name: 'SubagentStart', agent_type: 'worker' }],
  ]) {
    cases.push({
      name: `Codex（${label}）· ${kind}：不点名 Claude 专属工具，通用纪律仍在`,
      check: () => {
        const r = run(WD, { ...payload, ...extra }, env)
        if (r.status !== 0) return `exit=${r.status}`
        const d = JSON.parse(r.stdout)
        if (d.hookSpecificOutput.hookEventName !== payload.hook_event_name) return '事件名未按入参回声'
        const c = d.hookSpecificOutput.additionalContext
        const leaked = CLAUDE_ONLY.filter((t) => c.includes(t))
        if (leaked.length) return `仍含 Claude 专属内容：${leaked.join(' / ')}`
        const missing = KEEP[kind].filter((t) => !c.includes(t))
        if (missing.length) return `通用纪律缺失：${missing.join(' / ')}`
        if (c.length > 5000) return `超 5000 自律线：${c.length}`
        return null
      },
    })
  }
}

cases.push({
  name: 'Codex：有图轮次照样附截图路径',
  check: () => {
    const c = ctxOf(run(WD, { hook_event_name: 'UserPromptSubmit', prompt: IMAGE_PROMPT, turn_id: 't' }))
    return c.includes('/Users/me/Desktop/shots/bug.png') ? null : '截图路径段丢了'
  },
})

// dispatch-ledger：它数的是 Claude transcript 里的 `Agent` 派发，Codex 下整段不注入。
function makeTranscript() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'discipline-codex-'))
  const file = path.join(dir, 't.jsonl')
  const rows = []
  for (let i = 0; i < 14; i++) {
    rows.push(JSON.stringify({
      type: 'assistant',
      message: { content: [{ type: 'tool_use', name: 'Read', input: {} }] },
    }))
  }
  fs.writeFileSync(file, rows.join('\n') + '\n')
  return file
}

cases.push({
  name: 'dispatch-ledger · Claude 宿主：过了起注线照常注入',
  check: () => {
    const r = run(LEDGER, { hook_event_name: 'UserPromptSubmit', transcript_path: makeTranscript() })
    return r.stdout.includes('派发账本') ? null : `未注入：${r.stdout}`
  },
})

for (const [label, extra, env] of CODEX_HOSTS) {
  cases.push({
    name: `dispatch-ledger · Codex（${label}）：不注入`,
    check: () => {
      const r = run(LEDGER, { hook_event_name: 'UserPromptSubmit', transcript_path: makeTranscript(), ...extra }, env)
      return r.status === 0 && r.stdout === '' ? null : `stdout=${r.stdout}`
    },
  })
}

let failed = 0
for (const c of cases) {
  const err = c.check()
  if (err) {
    failed += 1
    console.log(`FAIL  ${c.name}\n      ${err}`)
  } else {
    console.log(`ok    ${c.name}`)
  }
}
console.log(`\n${cases.length - failed}/${cases.length} passed`)
process.exit(failed === 0 ? 0 : 1)
