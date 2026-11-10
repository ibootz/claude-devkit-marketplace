#!/usr/bin/env node
// devkit-readable-citations 的宿主分流用例（2.2.0 加 Codex 分支时加）。
//
//   1. Claude Code 宿主下注入逐字不变：golden-claude/*.txt 是加 Codex 分支**之前**的输出
//      （`--update-golden` 生成）。改 Claude 侧措辞时先说明理由，再重跑 `--update-golden`。
//   2. Codex 宿主（PLUGIN_ROOT 非空，或 payload 含 turn_id）下，对话正文那一轨改成 inline code
//      路径 + `:行号`：Codex 只把 inline code 里的路径渲染成可点击，不认 file:// 等 URI。
//      落盘 md 那一轨（相对路径 + 标题锚点）不跟宿主变。
//
// golden 只在非 Windows 上比。跑法：node .../codex-host.test.js [--update-golden]

'use strict'

const { spawnSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const HOOK = path.join(__dirname, '..', 'readable-citations.js')
const GOLDEN = path.join(__dirname, 'golden-claude')
const UPDATE = process.argv.includes('--update-golden')
const PROBE_VARS = [
  'CLAUDE_CODE_ENTRYPOINT', 'TERM_PROGRAM', 'VSCODE_INJECTION', 'WT_SESSION',
  'PLUGIN_ROOT', 'READABLE_CITATIONS',
]

function run(payload, env = {}) {
  const base = { ...process.env }
  for (const k of PROBE_VARS) delete base[k]
  const r = spawnSync(process.execPath, [HOOK], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    env: { ...base, ...env },
  })
  return { status: r.status, stdout: (r.stdout || '').trim() }
}

const HOSTS = {
  generic: {},
  webview: { CLAUDE_CODE_ENTRYPOINT: 'claude-vscode' },
  'vscode-terminal': { TERM_PROGRAM: 'vscode' },
  'windows-terminal': { WT_SESSION: 'x' },
}

const cases = []

if (process.platform !== 'win32') {
  const snaps = {}
  for (const [host, env] of Object.entries(HOSTS)) {
    for (const ev of ['UserPromptSubmit', 'SubagentStart']) {
      snaps[`${host}-${ev}.txt`] = run({ hook_event_name: ev }, env).stdout
    }
  }
  if (UPDATE) {
    fs.mkdirSync(GOLDEN, { recursive: true })
    for (const [f, s] of Object.entries(snaps)) fs.writeFileSync(path.join(GOLDEN, f), s + '\n')
    console.log(`golden 已写入 ${Object.keys(snaps).length} 份`)
    process.exit(0)
  }
  for (const [f, s] of Object.entries(snaps)) {
    cases.push({
      name: `Claude 宿主输出与 golden 逐字一致：${f}`,
      check: () => {
        const want = fs.readFileSync(path.join(GOLDEN, f), 'utf8').replace(/\n$/, '')
        return s === want ? null : '与 golden 不一致（Claude 侧注入变了）'
      },
    })
  }
}

for (const [label, extra, env] of [
  ['PLUGIN_ROOT 非空', {}, { PLUGIN_ROOT: '/x/plugin' }],
  ['payload 含 turn_id', { turn_id: 't-1' }, {}],
]) {
  for (const ev of ['UserPromptSubmit', 'SubagentStart']) {
    cases.push({
      name: `Codex（${label}）· ${ev}：对话正文改 inline code，落盘轨不变`,
      check: () => {
        const r = run({ hook_event_name: ev, ...extra }, env)
        if (r.status !== 0) return `exit=${r.status}`
        const d = JSON.parse(r.stdout)
        if (d.hookSpecificOutput.hookEventName !== ev) return '事件名未按入参回声'
        const c = d.hookSpecificOutput.additionalContext
        if (!c.includes('`skills/working-discipline/SKILL.md:128`')) return '缺 inline code 示范'
        if (/\]\(file:/.test(c) || /\]\(vscode:/.test(c)) return '对话正文仍在示范 URI 链接'
        if (!c.includes('../working-discipline/SKILL.md#52-模型档位')) return '落盘 md 那一轨丢了'
        if (!c.includes('不跟宿主变')) return '未写明落盘轨不跟宿主变'
        if (!c.includes('相对仓库根')) return '未写仓内路径相对仓库根'
        return null
      },
    })
  }
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
