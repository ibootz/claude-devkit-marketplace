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
const STATE_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'wtflow-main-guard-'))

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
    env: Object.assign({}, process.env, { WORKTREE_GUARD_STATE_DIR: STATE_DIR }, env || {}),
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

// WORKTREE_GUARD_EXEMPT 追加目录级豁免前缀
const exemptRepo = makeRepo('main')
check(
  'main 上 WORKTREE_GUARD_EXEMPT 列出的目录 → 放行（带尾斜杠）',
  { tool_name: 'Write', tool_input: { file_path: path.join(exemptRepo, 'docs/guide.md') }, cwd: exemptRepo },
  0,
  { WORKTREE_GUARD_EXEMPT: 'docs/' }
)
check(
  'main 上 WORKTREE_GUARD_EXEMPT 不带尾斜杠 → 自动补，放行',
  { tool_name: 'Write', tool_input: { file_path: path.join(exemptRepo, 'config/app.json') }, cwd: exemptRepo },
  0,
  { WORKTREE_GUARD_EXEMPT: 'config' }
)
check(
  'main 上多目录逗号分隔 → 第二个放行',
  { tool_name: 'Write', tool_input: { file_path: path.join(exemptRepo, 'notes/x.md') }, cwd: exemptRepo },
  0,
  { WORKTREE_GUARD_EXEMPT: 'docs/,notes/' }
)
check(
  'main 上 WORKTREE_GUARD_EXEMPT 未列的目录 → 仍拦（精确前缀，非全放）',
  { tool_name: 'Write', tool_input: { file_path: path.join(exemptRepo, 'src/app.js') }, cwd: exemptRepo },
  2,
  { WORKTREE_GUARD_EXEMPT: 'docs/,config/' }
)

// WORKTREE_GUARD_EXEMPT_DOTDIRS=1 放行所有顶层点开头路径
check(
  'DOTDIRS 开 → main 上顶层点目录 → 放行',
  { tool_name: 'Write', tool_input: { file_path: path.join(exemptRepo, '.githooks/new.sh') }, cwd: exemptRepo },
  0,
  { WORKTREE_GUARD_EXEMPT_DOTDIRS: '1' }
)
check(
  'DOTDIRS 开 → main 上根点文件 → 放行（.gitignore）',
  { tool_name: 'Write', tool_input: { file_path: path.join(exemptRepo, '.gitignore') }, cwd: exemptRepo },
  0,
  { WORKTREE_GUARD_EXEMPT_DOTDIRS: '1' }
)
check(
  'DOTDIRS 开 → main 上非点开头目录 → 仍拦（src/）',
  { tool_name: 'Write', tool_input: { file_path: path.join(exemptRepo, 'src/app.js') }, cwd: exemptRepo },
  2,
  { WORKTREE_GUARD_EXEMPT_DOTDIRS: '1' }
)
check(
  'DOTDIRS 关（默认）→ main 上顶层点目录 → 仍拦（须显式开）',
  { tool_name: 'Write', tool_input: { file_path: path.join(exemptRepo, '.vscode/x.json') }, cwd: exemptRepo },
  2
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

// ── git commit 的暂存区豁免（1.4.0）─────────────────────────────────
//
// 判据两侧都要有用例。这一组的成因：1.3.0 之前 Bash 侧一律 evaluate(dir, null)，
// filePath 为 null 时 isExemptPath 那一步被短路，于是「只提交 .keeper/ 台账」这种
// 本该豁免的提交照样被拦——路径豁免对 Write/Edit 生效、对 git commit 不生效。
console.log('\n[git commit 暂存区豁免 · 应放行 exit 0]')

const stagedRepo = makeRepo('main')
fs.mkdirSync(path.join(stagedRepo, '.keeper/_main/chore/CHR-001'), { recursive: true })
fs.writeFileSync(path.join(stagedRepo, '.keeper/_main/chore/CHR-001/item.md'), 'x\n')
fs.mkdirSync(path.join(stagedRepo, '.claude'), { recursive: true })
fs.writeFileSync(path.join(stagedRepo, '.claude/settings.local.json'), '{}\n')
// -f 是必需的：本机可能有全局 gitignore 忽略 .claude/settings.local.json，用例不能取决于它
git(['add', '-f', '--', '.keeper/_main/chore/CHR-001/item.md', '.claude/settings.local.json'], stagedRepo)

check(
  '暂存区全是豁免路径 → git commit 放行',
  { tool_name: 'Bash', tool_input: { command: 'git commit -m "chore: 台账"' }, cwd: stagedRepo },
  0
)
check(
  '暂存区全豁免 + 显式 pathspec 也豁免 → 放行',
  {
    tool_name: 'Bash',
    tool_input: { command: 'git commit -m "x" -- .keeper/_main/chore/CHR-001/item.md' },
    cwd: stagedRepo,
  },
  0
)
check(
  '暂存区全豁免 + git -C <repo> 从别处调用 → 放行',
  {
    tool_name: 'Bash',
    tool_input: { command: `git -C ${stagedRepo} commit -m "x" --no-verify` },
    cwd: os.tmpdir(),
  },
  0
)
check(
  '暂存区全豁免 + 粘连值 -m"msg" → 放行（短 flag 粘连值不误判成 pathspec）',
  { tool_name: 'Bash', tool_input: { command: 'git commit -m"chore: x"' }, cwd: stagedRepo },
  0
)

console.log('\n[git commit 暂存区豁免 · 应仍阻断 exit 2]')

check(
  '暂存区为空 → 仍拦（证明不了这次提交只动豁免路径）',
  { tool_name: 'Bash', tool_input: { command: 'git commit -m "x"' }, cwd: makeRepo('main') },
  2
)

const mixedRepo = makeRepo('main')
fs.mkdirSync(path.join(mixedRepo, '.keeper'), { recursive: true })
fs.writeFileSync(path.join(mixedRepo, '.keeper/note.md'), 'x\n')
fs.writeFileSync(path.join(mixedRepo, 'src.js'), 'x\n')
git(['add', '-f', '--', '.keeper/note.md', 'src.js'], mixedRepo)
check(
  '暂存区混了源码 → 仍拦（every 而非 some）',
  { tool_name: 'Bash', tool_input: { command: 'git commit -m "x"' }, cwd: mixedRepo },
  2
)

// -a / -A / --all / -i / --include / --amend 在提交那一刻才扩大范围或改写既有提交，
// 事先读到的索引不再是权威，故一律维持阻断。
for (const flag of ['-a', '-am "x"', '-A', '--all', '-i', '--include', '--amend', '--patch']) {
  check(
    `暂存区全豁免但带 ${flag} → 仍拦（提交时才扩大范围 / 改写既有提交）`,
    { tool_name: 'Bash', tool_input: { command: `git commit ${flag} -m "x"` }, cwd: stagedRepo },
    2
  )
}
check(
  '暂存区全豁免但 pathspec 指向源码 → 仍拦',
  { tool_name: 'Bash', tool_input: { command: 'git commit -m "x" -- src.js' }, cwd: stagedRepo },
  2
)
check(
  '暂存区全豁免但 pathspec 带 glob → 仍拦（不展开通配符）',
  { tool_name: 'Bash', tool_input: { command: 'git commit -m "x" -- ".keeper/*"' }, cwd: stagedRepo },
  2
)
check(
  '暂存区全豁免但 --pathspec-from-file → 仍拦（范围来自文件，读不到）',
  {
    tool_name: 'Bash',
    tool_input: { command: 'git commit -m "x" --pathspec-from-file=list.txt' },
    cwd: stagedRepo,
  },
  2
)
check(
  '暂存区全豁免但白名单外的 flag → 仍拦（白名单，未知 flag 维持阻断）',
  { tool_name: 'Bash', tool_input: { command: 'git commit -m "x" --some-future-flag' }, cwd: stagedRepo },
  2
)

fs.rmSync(STATE_DIR, { recursive: true, force: true })
console.log(`\n结果：${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
