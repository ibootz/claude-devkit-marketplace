#!/usr/bin/env node
// devkit-style-wenyan 的宿主分流用例（2.2.0 加）。
//
// Claude Code 宿主：注入与 golden/session-start.json 逐字一致（另一份测试也在钉，这里显式剥掉
// PLUGIN_ROOT 再比一次，防跑测试的机器本身在 Codex 里）。
// Codex 宿主（PLUGIN_ROOT 非空，或入参含 turn_id）：「例」一节那句 file:// 示范换成 inline code，
// 其余逐字相同。
// 跑法：node plugins/devkit-style-wenyan/hooks/tests/codex-host.test.js

'use strict'

const { spawnSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const HOOK = path.join(__dirname, '..', 'session-start.js')
const GOLDEN = path.join(__dirname, 'golden', 'session-start.json')
const CLAUDE_EX = '改 [plugin.json:11](file:///abs/path/plugins/x/.claude-plugin/plugin.json#11)。'
const CODEX_EX = '改 `plugins/x/.claude-plugin/plugin.json:11`。'

function run(payload, env = {}) {
  const base = { ...process.env }
  delete base.PLUGIN_ROOT
  const r = spawnSync(process.execPath, [HOOK], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    env: { ...base, ...env },
  })
  return { status: r.status, ctx: JSON.parse(r.stdout).hookSpecificOutput.additionalContext }
}

const golden = JSON.parse(fs.readFileSync(GOLDEN, 'utf8')).hookSpecificOutput.additionalContext

const cases = [
  {
    name: 'Claude 宿主：与 golden 逐字一致',
    check: () => (run({ hook_event_name: 'SessionStart' }).ctx === golden ? null : '与 golden 不一致'),
  },
  ...[
    ['PLUGIN_ROOT 非空', {}, { PLUGIN_ROOT: '/x' }],
    ['入参含 turn_id', { turn_id: 't' }, {}],
  ].map(([label, extra, env]) => ({
    name: `Codex（${label}）：示范句换成 inline code，其余逐字不变`,
    check: () => {
      const { status, ctx } = run({ hook_event_name: 'SessionStart', ...extra }, env)
      if (status !== 0) return `exit=${status}`
      if (ctx.includes('file://')) return '仍含 file:// 示范'
      if (!ctx.includes(CODEX_EX)) return '缺 inline code 示范句'
      if (ctx !== golden.replace(CLAUDE_EX, CODEX_EX)) return '除示范句外还有别的差异'
      return null
    },
  })),
]

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
