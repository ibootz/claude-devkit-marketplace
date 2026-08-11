// main-branch-guard 回归用例
//
// 运行：node plugins/worktree-flow/tests/main-branch-guard.test.js
//
// 设计要点：
//  - 在临时目录里**真建 git 仓**，不 mock git；判据依赖的就是 git 的真实输出。
//  - 用 spawnSync 喂 JSON 到 stdin，**不经过 shell**。经 shell 的测试脚本一旦引号失衡，
//    guard 会把测试数据当成真命令拦下并原样回灌进 finding（本仓 2026-07-31 真撞过一次）。
//  - 两侧都测：该拦的确实拦（exit 2），该放的确实放（exit 0）。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync, execFileSync } = require('child_process')

const GUARD = path.join(__dirname, '..', 'hooks', 'guards', 'main-branch-guard.js')

let passed = 0
let failed = 0

function git(args, cwd) {
  execFileSync('git', args, { cwd, stdio: ['ignore', 'ignore', 'ignore'] })
}

// 建一个仓，默认分支名由 branch 指定
function makeRepo(branch) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wtflow-'))
  git(['init', '-q', '-b', branch], dir)
  git(['config', 'user.email', 'test@example.com'], dir)
  git(['config', 'user.name', 'test'], dir)
  fs.writeFileSync(path.join(dir, 'seed.txt'), 'seed\n')
  git(['add', '-A'], dir)
  git(['commit', '-q', '-m', 'seed'], dir)
  return dir
}

function run(payload, env) {
  const res = spawnSync(process.execPath, [GUARD], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    env: Object.assign({}, process.env, env || {}),
  })
  return { code: res.status, stderr: res.stderr || '' }
}

function check(label, payload, expectedCode, env) {
  const { code, stderr } = run(payload, env)
  if (code === expectedCode) {
    passed++
    console.log(`  PASS  ${label}`)
  } else {
    failed++
    console.log(`  FAIL  ${label} — 期望 exit ${expectedCode}，实际 ${code}`)
    if (stderr) console.log(`        stderr: ${stderr.trim().slice(0, 200)}`)
  }
}

// ── 该拦的 ──────────────────────────────────────────────────────────
console.log('\n[应阻断 exit 2]')

for (const branch of ['main', 'master']) {
  const repo = makeRepo(branch)
  check(
    `${branch} 分支上 Edit 源码`,
    { tool_name: 'Edit', tool_input: { file_path: path.join(repo, 'src.js') }, cwd: repo },
    2
  )
  check(
    `${branch} 分支上 Write 新文件（父目录尚不存在）`,
    { tool_name: 'Write', tool_input: { file_path: path.join(repo, 'a/b/c.js') }, cwd: repo },
    2
  )
  check(
    `${branch} 分支上 git commit`,
    { tool_name: 'Bash', tool_input: { command: 'git commit -m "x"' }, cwd: repo },
    2
  )
  check(
    `${branch} 分支上 git -C <repo> commit（从别处调用）`,
    {
      tool_name: 'Bash',
      tool_input: { command: `git -C ${repo} commit -am "x"` },
      cwd: os.tmpdir(),
    },
    2
  )
  check(
    `${branch} 分支上 git add 后接 git commit（多片段）`,
    { tool_name: 'Bash', tool_input: { command: 'git add -A && git commit -m "x"' }, cwd: repo },
    2
  )
  check(
    `${branch} 分支上 README.md（不按扩展名豁免文档）`,
    { tool_name: 'Edit', tool_input: { file_path: path.join(repo, 'README.md') }, cwd: repo },
    2
  )
}

// ── 该放的 ──────────────────────────────────────────────────────────
console.log('\n[应放行 exit 0]')

const featureRepo = makeRepo('main')
git(['checkout', '-q', '-b', 'feat-x'], featureRepo)
check(
  'feature 分支上 Edit',
  { tool_name: 'Edit', tool_input: { file_path: path.join(featureRepo, 'src.js') }, cwd: featureRepo },
  0
)
check(
  'feature 分支上 git commit',
  { tool_name: 'Bash', tool_input: { command: 'git commit -m "x"' }, cwd: featureRepo },
  0
)

const detachedRepo = makeRepo('main')
git(['checkout', '-q', '--detach', 'HEAD'], detachedRepo)
check(
  'detached HEAD 上 Edit',
  { tool_name: 'Edit', tool_input: { file_path: path.join(detachedRepo, 'src.js') }, cwd: detachedRepo },
  0
)

const mainRepo = makeRepo('main')
for (const exempt of ['.claude/settings.local.json', '.keeper/x/debug/issue.md', '.git/config']) {
  check(
    `main 上豁免路径 ${exempt}`,
    { tool_name: 'Write', tool_input: { file_path: path.join(mainRepo, exempt) }, cwd: mainRepo },
    0
  )
}
check(
  'main 上 sed -i（已知漏报，判据只认 git commit）',
  { tool_name: 'Bash', tool_input: { command: 'sed -i "" s/a/b/ src.js' }, cwd: mainRepo },
  0
)
check(
  'main 上 git status（非 commit 子命令）',
  { tool_name: 'Bash', tool_input: { command: 'git status --short' }, cwd: mainRepo },
  0
)
check(
  'main 上 git log --grep commit（commit 出现在 flag 值里，非子命令位）',
  { tool_name: 'Bash', tool_input: { command: 'git log --grep commit -n 5' }, cwd: mainRepo },
  0
)
check(
  '逃生阀 WORKTREE_GUARD=off',
  { tool_name: 'Edit', tool_input: { file_path: path.join(mainRepo, 'src.js') }, cwd: mainRepo },
  0,
  { WORKTREE_GUARD: 'off' }
)
check(
  '非 git 目录',
  { tool_name: 'Edit', tool_input: { file_path: path.join(os.tmpdir(), 'nowhere.js') }, cwd: os.tmpdir() },
  0
)
check(
  '未覆盖的工具（Read）',
  { tool_name: 'Read', tool_input: { file_path: path.join(mainRepo, 'src.js') }, cwd: mainRepo },
  0
)

// 合并冲突进行中：制造一个真冲突
const mergeRepo = makeRepo('main')
fs.writeFileSync(path.join(mergeRepo, 'conflict.txt'), 'base\n')
git(['add', '-A'], mergeRepo)
git(['commit', '-q', '-m', 'base'], mergeRepo)
git(['checkout', '-q', '-b', 'other'], mergeRepo)
fs.writeFileSync(path.join(mergeRepo, 'conflict.txt'), 'other\n')
git(['commit', '-q', '-am', 'other'], mergeRepo)
git(['checkout', '-q', 'main'], mergeRepo)
fs.writeFileSync(path.join(mergeRepo, 'conflict.txt'), 'mine\n')
git(['commit', '-q', '-am', 'mine'], mergeRepo)
spawnSync('git', ['merge', '--no-ff', 'other'], { cwd: mergeRepo, stdio: 'ignore' }) // 必然冲突
check(
  'main 上合并冲突进行中 → Edit 放行',
  { tool_name: 'Edit', tool_input: { file_path: path.join(mergeRepo, 'conflict.txt') }, cwd: mergeRepo },
  0
)
check(
  'main 上合并冲突进行中 → git commit 放行',
  { tool_name: 'Bash', tool_input: { command: 'git commit --no-edit' }, cwd: mergeRepo },
  0
)

console.log(`\n结果：${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
