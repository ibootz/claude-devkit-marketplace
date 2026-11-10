// devkit-worktree-flow 的宿主分流用例（加 Codex 分支时加）
//
// 运行：node plugins/devkit-worktree-flow/tests/codex-host.test.js [--update-golden]
//
// 守两件事：
//  1. Claude Code 宿主下，worktree-flow-inject.js 的三路注入与 main-branch-guard.js 的拦截文案
//     逐字不变——golden-claude/*.txt 是加 Codex 分支**之前**的输出（`--update-golden` 生成；
//     临时仓路径替换成 `<REPO>`）。改 Claude 侧措辞时先说明理由，再重跑 `--update-golden`。
//  2. Codex 宿主（环境变量 PLUGIN_ROOT 非空，或入参含 turn_id）下，注入与拦截文案不点名
//     `EnterWorktree` / `ExitWorktree` / `AskUserQuestion`（Codex 没有这三个工具），改给
//     `git worktree` 命令流程；拦截判据本身不变（该拦的照拦）。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync, execFileSync } = require('child_process')

const INJECT = path.join(__dirname, '..', 'hooks', 'worktree-flow-inject.js')
const GUARD = path.join(__dirname, '..', 'hooks', 'guards', 'main-branch-guard.js')
const GOLDEN = path.join(__dirname, 'golden-claude')
const UPDATE = process.argv.includes('--update-golden')
const STATE_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'wtflow-codex-state-'))

function git(args, cwd) {
  execFileSync('git', args, { cwd, stdio: ['ignore', 'ignore', 'ignore'] })
}

function makeRepo(branch) {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'wtflow-codex-')))
  git(['init', '-q', '-b', branch], dir)
  git(['config', 'user.email', 'test@example.com'], dir)
  git(['config', 'user.name', 'test'], dir)
  fs.writeFileSync(path.join(dir, 'seed.txt'), 'seed\n')
  git(['add', '-A'], dir)
  git(['commit', '-q', '-m', 'seed'], dir)
  return dir
}

function run(script, payload, env = {}) {
  const base = { ...process.env, WORKTREE_GUARD_STATE_DIR: STATE_DIR }
  delete base.PLUGIN_ROOT
  delete base.WORKTREE_GUARD
  const r = spawnSync(process.execPath, [script], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    env: { ...base, ...env },
  })
  return { code: r.status, stdout: r.stdout || '', stderr: r.stderr || '' }
}

const repo = makeRepo('main')
const editPayload = { tool_name: 'Edit', tool_input: { file_path: path.join(repo, 'src.js') }, cwd: repo, session_id: 's-codex-test' }
const commitPayload = { tool_name: 'Bash', tool_input: { command: 'git commit -m "x"' }, cwd: repo, session_id: 's-codex-test' }
const norm = (s) => s.split(repo).join('<REPO>')

const SNAPSHOTS = {
  'inject-session-start.txt': () => run(INJECT, { hook_event_name: 'SessionStart' }).stdout,
  'inject-user-prompt.txt': () => run(INJECT, { hook_event_name: 'UserPromptSubmit', prompt: 'x' }).stdout,
  'inject-subagent.txt': () => run(INJECT, { hook_event_name: 'SubagentStart' }).stdout,
  'guard-edit.txt': () => norm(run(GUARD, editPayload).stderr),
  'guard-commit.txt': () => norm(run(GUARD, commitPayload).stderr),
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
    return s === fs.readFileSync(path.join(GOLDEN, f), 'utf8') ? null : '与 golden 不一致（Claude 侧文案变了）'
  }])
}

const CLAUDE_ONLY = ['EnterWorktree', 'ExitWorktree', 'AskUserQuestion']

for (const [label, extra, env] of [
  ['PLUGIN_ROOT 非空', {}, { PLUGIN_ROOT: '/x/plugin' }],
  ['入参含 turn_id', { turn_id: 't-1' }, {}],
]) {
  for (const ev of ['SessionStart', 'UserPromptSubmit', 'SubagentStart']) {
    cases.push([`Codex（${label}）· 注入 ${ev}：给 git worktree 流程，不点名 Claude 专属工具`, () => {
      const r = run(INJECT, { hook_event_name: ev, ...extra }, env)
      if (r.code !== 0) return `exit=${r.code}`
      const d = JSON.parse(r.stdout).hookSpecificOutput
      if (d.hookEventName !== ev) return '事件名未按入参回声'
      const c = d.additionalContext
      const leaked = CLAUDE_ONLY.filter((t) => c.includes(t))
      if (leaked.length) return `仍点名：${leaked.join(' / ')}`
      for (const want of ['git -C <仓根> worktree add', 'merge --no-ff', 'worktree remove', 'WORKTREE_GUARD=off']) {
        if (!c.includes(want)) return `缺：${want}`
      }
      return null
    }])
  }
  for (const [name, payload] of [['Edit', editPayload], ['git commit', commitPayload]]) {
    cases.push([`Codex（${label}）· 守卫 ${name}：照拦，文案给 git worktree 流程`, () => {
      const r = run(GUARD, { ...payload, ...extra }, env)
      if (r.code !== 2) return `期望 exit 2，实际 ${r.code}`
      const leaked = CLAUDE_ONLY.filter((t) => r.stderr.includes(t))
      if (leaked.length) return `仍点名：${leaked.join(' / ')}`
      if (!r.stderr.includes('git -C') || !r.stderr.includes('worktree add')) return '缺 git worktree add 指引'
      if (!r.stderr.includes('[L1-BLOCKER]')) return '缺 finding 前缀'
      return null
    }])
  }
}

cases.push(['Codex · WORKTREE_GUARD=off 照样关闭注入与守卫', () => {
  const a = run(INJECT, { hook_event_name: 'SessionStart', turn_id: 't' }, { WORKTREE_GUARD: 'off' })
  const b = run(GUARD, { ...editPayload, turn_id: 't' }, { WORKTREE_GUARD: 'off' })
  return a.stdout === '' && b.code === 0 ? null : `inject=${a.stdout.slice(0, 40)} guard=${b.code}`
}])

let failed = 0
for (const [name, check] of cases) {
  const err = check()
  if (err) failed += 1
  console.log(err ? `  FAIL  ${name}\n        ${err}` : `  PASS  ${name}`)
}
console.log(`\n${cases.length - failed}/${cases.length} passed`)
process.exit(failed === 0 ? 0 : 1)
