#!/usr/bin/env node
// devkit-ultraverify keyword-trigger.js 的宿主分流用例（加 Codex 分支时加）。
//
// 守两件事：
//   1. Claude Code 宿主下输出逐字不变——golden-claude/*.txt 是加 Codex 分支**之前**的输出
//      （`--update-golden` 生成）。改 Claude 侧措辞时先说明理由，再重跑 `--update-golden`。
//   2. Codex 宿主（环境变量 PLUGIN_ROOT 非空，或入参含 turn_id）下注入不点名 Skill 工具
//      （Codex 没有它），改成「读 ultraverify skill 的 SKILL.md」；关键词判据不变。
// 跑法：node plugins/devkit-ultraverify/hooks/tests/codex-host.test.js [--update-golden]

'use strict'

const { spawnSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const HOOK = path.join(__dirname, '..', 'keyword-trigger.js')
const GOLDEN = path.join(__dirname, 'golden-claude')
const UPDATE = process.argv.includes('--update-golden')

function run(payload, env = {}) {
  const base = { ...process.env }
  delete base.PLUGIN_ROOT
  const r = spawnSync(process.execPath, [HOOK], { input: JSON.stringify(payload), encoding: 'utf8', env: { ...base, ...env } })
  return { status: r.status, stdout: r.stdout || '' }
}

const HIT = { hook_event_name: 'UserPromptSubmit', prompt: '这个结论 ultraverify 一下' }

const SNAPSHOTS = { 'hit.txt': () => run(HIT).stdout }
const cases = []
const snaps = {}
for (const [f, fn] of Object.entries(SNAPSHOTS)) snaps[f] = fn()
if (UPDATE) {
  fs.mkdirSync(GOLDEN, { recursive: true })
  for (const [f, s] of Object.entries(snaps)) fs.writeFileSync(path.join(GOLDEN, f), s)
  console.log(`golden 已写入 ${Object.keys(snaps).length} 份`)
  process.exit(0)
}
for (const [f, s] of Object.entries(snaps)) {
  cases.push([`Claude 宿主与 golden 逐字一致：${f}`, () => {
    if (!s) return '输出为空'
    return s === fs.readFileSync(path.join(GOLDEN, f), 'utf8') ? null : '与 golden 不一致（Claude 侧注入变了）'
  }])
}

cases.push(['Claude · 未写关键词：零输出', () => (run({ prompt: '普通问题' }).stdout === '' ? null : '有输出')])

for (const [label, extra, env] of [
  ['PLUGIN_ROOT 非空', {}, { PLUGIN_ROOT: '/x/plugin' }],
  ['入参含 turn_id', { turn_id: 't-1' }, {}],
]) {
  cases.push([`Codex（${label}）· 写了关键词：注入不点名 Skill 工具，指向 SKILL.md`, () => {
    const r = run({ ...HIT, ...extra }, env)
    if (r.status !== 0) return `exit=${r.status}`
    const c = JSON.parse(r.stdout).hookSpecificOutput.additionalContext
    if (c.includes('Skill 工具')) return '仍点名 Skill 工具'
    if (!c.includes('skills/ultraverify/SKILL.md')) return '缺 SKILL.md 指路'
    if (!c.includes('证伪内环')) return '缺证伪内环五步'
    return null
  }])
  cases.push([`Codex（${label}）· 未写关键词：零输出`, () => (run({ prompt: '普通问题', ...extra }, env).stdout === '' ? null : '有输出')])
}

let failed = 0
for (const [name, check] of cases) {
  const err = check()
  if (err) failed += 1
  console.log(err ? `FAIL  ${name}\n      ${err}` : `ok    ${name}`)
}
console.log(`\n${cases.length - failed}/${cases.length} passed`)
process.exit(failed === 0 ? 0 : 1)
