#!/usr/bin/env node
// devkit-omp 两个注入 hook 的宿主分流用例（加 Codex 分支时加）。
//
// 守两件事：
//   1. Claude Code 宿主下输出逐字不变——golden-claude/*.txt 是加 Codex 分支**之前**的输出
//      （`--update-golden` 生成）。改 Claude 侧措辞时先说明理由，再重跑 `--update-golden`。
//   2. Codex 宿主（环境变量 PLUGIN_ROOT 非空，或入参含 turn_id）下即使 OMP_PROTOCOL_ENABLED 打开
//      也不注入：协议的唯一调用路径是「`Agent` 工具派发 omp-explore / omp-plan / omp-task」，
//      Codex 既没有 `Agent` 工具也不加载插件的 agents/，注进去是一条做不到的指令。
// 跑法：node plugins/devkit-omp/hooks/tests/codex-host.test.js [--update-golden]

'use strict'

const { spawnSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const INIT = path.join(__dirname, '..', 'orchestrator-protocol-init.js')
const REMIND = path.join(__dirname, '..', 'orchestrator-protocol-remind.js')
const GOLDEN = path.join(__dirname, 'golden-claude')
const UPDATE = process.argv.includes('--update-golden')

function run(script, payload, env = {}) {
  const base = { ...process.env }
  delete base.PLUGIN_ROOT
  delete base.OMP_PROTOCOL_ENABLED
  const r = spawnSync(process.execPath, [script], {
    input: payload === undefined ? '' : JSON.stringify(payload),
    encoding: 'utf8',
    env: { ...base, ...env },
  })
  return { status: r.status, stdout: r.stdout || '' }
}

const ON = { OMP_PROTOCOL_ENABLED: '1' }

const SNAPSHOTS = {
  'init.txt': () => run(INIT, { hook_event_name: 'SessionStart', source: 'startup' }, ON).stdout,
  'init-no-stdin.txt': () => run(INIT, undefined, ON).stdout,
  'remind.txt': () => run(REMIND, { hook_event_name: 'UserPromptSubmit', prompt: '帮我看看这个 bug' }, ON).stdout,
}

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

cases.push(['Claude · 开关未开：两个 hook 都静默', () => {
  const a = run(INIT, { hook_event_name: 'SessionStart' })
  const b = run(REMIND, { hook_event_name: 'UserPromptSubmit', prompt: 'x' })
  return a.stdout === '' && b.stdout === '' ? null : '开关未开却有输出'
}])

cases.push(['Claude · 豁免词照旧生效', () => {
  const r = run(REMIND, { hook_event_name: 'UserPromptSubmit', prompt: '你直接读一下' }, ON)
  return r.stdout === '' ? null : `stdout=${r.stdout}`
}])

for (const [label, extra, env] of [
  ['PLUGIN_ROOT 非空', {}, { PLUGIN_ROOT: '/x/plugin' }],
  ['入参含 turn_id', { turn_id: 't-1' }, {}],
]) {
  for (const [name, script, ev] of [['init', INIT, 'SessionStart'], ['remind', REMIND, 'UserPromptSubmit']]) {
    cases.push([`Codex（${label}）· ${name}：开关打开也不注入`, () => {
      const r = run(script, { hook_event_name: ev, prompt: 'x', ...extra }, { ...ON, ...env })
      return r.status === 0 && r.stdout === '' ? null : `exit=${r.status} stdout=${r.stdout}`
    }])
  }
}

let failed = 0
for (const [name, check] of cases) {
  const err = check()
  if (err) failed += 1
  console.log(err ? `FAIL  ${name}\n      ${err}` : `ok    ${name}`)
}
console.log(`\n${cases.length - failed}/${cases.length} passed`)
process.exit(failed === 0 ? 0 : 1)
