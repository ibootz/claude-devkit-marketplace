// main-branch-guard.js — PreToolUse 门控钩子（matcher: Write|Edit|MultiEdit|NotebookEdit|Bash）
//
// 【用途】
// 禁止在受保护分支（main / master）上直接改代码。命中即 exit 2 阻断，文案里给出可直接
// 照抄的 worktree 开工与合流命令。
//
// 【为什么是 deny 而不是 ask】
// 本机 Claude Code 的 defaultMode 为 bypassPermissions，`permissionDecision: "ask"` 实测
// 全部失效（弹框不出现、直接放行）。强度阶梯上只剩「注入提醒」与「硬拒 deny」两档，
// 由用户 2026-08-11 拍板选 deny，并要求配一个环境变量逃生阀。
//
// 【判据（全部取自确定信息，不猜语义）】
// 1. 逃生阀：环境变量 WORKTREE_GUARD=off → 放行。
// 2. 目标仓：Write/Edit/MultiEdit 取 tool_input.file_path、NotebookEdit 取 notebook_path，
//    向上找到第一个存在的目录后跑 `git rev-parse --show-toplevel`；Bash 用 payload.cwd
//    （或该次 git 调用自己的 `-C <path>`）。
// 3. 分支：`git rev-parse --abbrev-ref HEAD` 的返回值是否**逐字等于** main 或 master。
//    detached HEAD 返回 "HEAD"，不在集合内 → 放行。非 git 目录（命令失败）→ 放行。
// 4. 豁免路径：目标文件相对仓根落在默认三前缀（.claude/ .keeper/ .git/）或
//    WORKTREE_GUARD_EXEMPT 列出的前缀之下 → 放行。默认三处装的是会话产物、任务队列
//    台账与 git 自身元数据，不是「代码」，且 .claude/worktrees/ 本身就是本插件要求的
//    工作区落点——拦它会让流程自锁。WORKTREE_GUARD_EXEMPT 逗号分隔额外前缀，经
//    settings.json 的 env 注入（子进程继承 process.env）。WORKTREE_GUARD_EXEMPT_DOTDIRS=1
//    时另放行所有顶层点开头路径（隐藏目录与根点文件），含 .githooks / .github 等脚本
//    目录——opt-in，默认关。
// 5. 合流进行中豁免：git 目录里存在 MERGE_HEAD / CHERRY_PICK_HEAD / REVERT_HEAD /
//    rebase-merge / rebase-apply 任一 → 放行。理由是「解决冲突」这一步按设计就发生在
//    主分支上，且必须能改文件、能 `git commit` 收尾；不豁免会把本插件推荐的 --no-ff
//    合并流程自己卡死。
//
// 【Bash 侧只认 `git commit` 这一种形态，这是有意的收窄】
// 本仓 .claude/rules/project/hook-restraint.md 明令：判据需要理解语义的规则不得做成 deny。
// 「这条 shell 命令算不算写操作」正是那类判据——`sed -i`、`> file`、`tee`、heredoc 写文件、
// `python - <<EOF` 里的 open(w)，靠正则永远分不清真实调用与字符串字面量。故本 guard 在
// Bash 侧**只**拦 `git commit`：它是闭合的、可定位到命令名位置的确定形态。
//
// 由此**明确的漏报面**（下列在 main 上均放行，本 guard 拦不住，不要以为它们被覆盖）：
//   - `sed -i` / `>` `>>` 重定向 / `tee` / `cp` / `mv` / `rm` / heredoc 写文件
//   - 任何解释器脚本内部的写操作（python / node / awk -i inplace）
//   - `$(which git) commit`、`G=git; $G commit` 等命令替换与变量间接调用
//   - `git commit` 出现在未被 stripHeredocs 剥掉的多行文本里（终止符写法非常规时）
// 真正兜住这些的是同插件注入的流程规约（软约束）+ 人的注意力，不是这道闸。
//
// 【明确的误杀面】
//   - 在 main 上修一个错别字、补一行文档，同样被拦（用户拍板：不按扩展名豁免文档，
//     因为 .json / .yml 这类配置落在代码与文档的灰区，按扩展名切会切出一条模糊边界）。
//     出口是 WORKTREE_GUARD=off。
//   - 仓根就叫 main/master 的分支但用途不是主干（少见）——同样被拦，同一个出口。
//
// Input: JSON on stdin（tool_name / tool_input / cwd）
// Exit 0 = 放行；Exit 2 = 阻断（stderr 作为附加上下文回灌给 Claude）

'use strict'

const fs = require('fs')
const path = require('path')
const { execFileSync } = require('child_process')

const PROTECTED_BRANCHES = new Set(['main', 'master'])

// 相对仓根的默认豁免前缀（会话产物 / 任务台账 / git 元数据，不是代码）。
// 额外前缀经环境变量 WORKTREE_GUARD_EXEMPT 注入（逗号分隔，如 "docs/,config/"），
// 落 settings.json 的 env 字段后会注入会话进程、被本 hook 经 process.env 继承。
const DEFAULT_EXEMPT_PREFIXES = ['.claude/', '.keeper/', '.git/']

function loadExemptPrefixes() {
  const prefixes = DEFAULT_EXEMPT_PREFIXES.slice()
  const extra = process.env.WORKTREE_GUARD_EXEMPT
  if (extra) {
    for (const raw of extra.split(',')) {
      const dir = raw.trim()
      if (!dir) continue
      prefixes.push(dir.endsWith('/') ? dir : dir + '/')
    }
  }
  return prefixes
}

const EXEMPT_PREFIXES = loadExemptPrefixes()

// WORKTREE_GUARD_EXEMPT_DOTDIRS=1 时，所有顶层以点开头的路径（隐藏目录与根点文件）
// 一律豁免。判据是「相对仓根的首段以 . 开头」，机械确定；副作用是 .githooks / .github
// 等 hook/CI 脚本目录也会放行（可在 main 上直改、绕过 worktree 评审），故默认关、opt-in。
const EXEMPT_DOTDIRS = process.env.WORKTREE_GUARD_EXEMPT_DOTDIRS === '1'

// 存在任一即视为「合流进行中」，整仓放行
const IN_PROGRESS_MARKERS = [
  'MERGE_HEAD',
  'CHERRY_PICK_HEAD',
  'REVERT_HEAD',
  'rebase-merge',
  'rebase-apply',
]

const GIT_TIMEOUT_MS = 3000
const PATH_ECHO_LIMIT = 80

function truncate(text, limit) {
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

function git(args, cwd) {
  try {
    return execFileSync('git', args, {
      cwd,
      timeout: GIT_TIMEOUT_MS,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
  } catch (_) {
    return null
  }
}

// 向上找到第一个真实存在的目录（Write 新建文件时父目录可能还不存在）
function nearestExistingDir(target) {
  let dir = target
  for (let i = 0; i < 64; i++) {
    if (fs.existsSync(dir)) {
      try {
        if (fs.statSync(dir).isDirectory()) return dir
      } catch (_) {
        /* 落到下一轮取父目录 */
      }
    }
    const parent = path.dirname(dir)
    if (parent === dir) return null
    dir = parent
  }
  return null
}

// 把路径归一到 realpath 形态。目标本身可以不存在（Write 新建文件）：取最近存在的祖先做
// realpath，再把剩余相对部分接回去。
//
// 这一步不是洁癖：macOS 上 os.tmpdir() 是 /var/folders/…（符号链接），而
// `git rev-parse --show-toplevel` 返回的是 /private/var/folders/…。两侧形态不一致时
// path.relative() 会得到 `../../..` 开头的结果，被 isExemptPath 误判成「不在这个仓里」
// 而整体放行——即 main 分支上的 Edit/Write 全部漏拦。2026-08-11 首轮回归用例实测到。
function canonicalize(target) {
  const existing = nearestExistingDir(target)
  if (!existing) return target
  let real
  try {
    real = fs.realpathSync(existing)
  } catch (_) {
    return target
  }
  const rest = path.relative(existing, target)
  return rest ? path.join(real, rest) : real
}

function repoRoot(dir) {
  if (!dir) return null
  const existing = nearestExistingDir(dir)
  if (!existing) return null
  const root = git(['rev-parse', '--show-toplevel'], existing)
  return root ? canonicalize(root) : null
}

function currentBranch(root) {
  return git(['rev-parse', '--abbrev-ref', 'HEAD'], root)
}

function isOperationInProgress(root) {
  const gitDir = git(['rev-parse', '--absolute-git-dir'], root)
  if (!gitDir) return false
  return IN_PROGRESS_MARKERS.some((marker) => fs.existsSync(path.join(gitDir, marker)))
}

// 目标文件是否落在豁免前缀下；不在这个仓里也视为豁免（交给它自己那个仓的判定）
function isExemptPath(filePath, root) {
  const rel = path.relative(root, filePath)
  if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) return true
  const normalized = rel.split(path.sep).join('/')
  if (EXEMPT_DOTDIRS && normalized.split('/')[0].startsWith('.')) return true
  return EXEMPT_PREFIXES.some(
    (prefix) => normalized === prefix.slice(0, -1) || normalized.startsWith(prefix)
  )
}

// ── Bash 侧：定位命令名位置的 `git commit` ──────────────────────────

const ENV_ASSIGN_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*=/

// 剥掉 heredoc 正文（那是喂给别的解释器或远端的文本，不是本地 shell 命令）
function stripHeredocs(command) {
  const lines = command.split('\n')
  const kept = []
  let terminator = null
  for (const line of lines) {
    if (terminator !== null) {
      if (line.trim() === terminator) terminator = null
      continue
    }
    kept.push(line)
    const m = line.match(/<<-?\s*(["']?)([A-Za-z_][A-Za-z0-9_]*)\1/)
    if (m) terminator = m[2]
  }
  return kept.join('\n')
}

// 按顶层分隔符切片段；引号内的分隔符不切
function splitSegments(command) {
  const segments = []
  let cur = ''
  let quote = null
  for (let i = 0; i < command.length; i++) {
    const c = command[i]
    if (quote) {
      cur += c
      if (c === quote && command[i - 1] !== '\\') quote = null
      continue
    }
    if (c === '"' || c === "'") {
      quote = c
      cur += c
      continue
    }
    if (c === '\n' || c === ';') {
      segments.push(cur)
      cur = ''
      continue
    }
    if ((c === '&' || c === '|') && command[i + 1] === c) {
      segments.push(cur)
      cur = ''
      i++
      continue
    }
    if (c === '|') {
      segments.push(cur)
      cur = ''
      continue
    }
    cur += c
  }
  segments.push(cur)
  return segments.filter((s) => s.trim())
}

function tokenize(segment) {
  const tokens = []
  let cur = ''
  let quote = null
  for (const c of segment) {
    if (quote) {
      if (c === quote) quote = null
      else cur += c
      continue
    }
    if (c === '"' || c === "'") {
      quote = c
      continue
    }
    if (/\s/.test(c)) {
      if (cur) {
        tokens.push(cur)
        cur = ''
      }
      continue
    }
    cur += c
  }
  if (cur) tokens.push(cur)
  return tokens
}

// 命中返回 { repoHint }（`git -C <path>` 时 repoHint 为那个 path），否则返回 null
function findGitCommit(segment) {
  const cleaned = segment.replace(/^[\s(){]+/, '').replace(/[)}\s]+$/, '')
  const tokens = tokenize(cleaned)
  let i = 0
  while (i < tokens.length && ENV_ASSIGN_PATTERN.test(tokens[i])) i++
  if (i >= tokens.length) return null
  if (tokens[i].split('/').pop() !== 'git') return null
  i++

  let repoHint = null
  for (; i < tokens.length; i++) {
    const t = tokens[i]
    if (t === '-C') {
      repoHint = tokens[i + 1] || null
      i++
      continue
    }
    if (t.startsWith('--git-dir=') || t.startsWith('--work-tree=')) {
      repoHint = t.slice(t.indexOf('=') + 1) || null
      continue
    }
    if (t === '-c') {
      i++
      continue
    }
    if (t.startsWith('-')) continue
    return t === 'commit' ? { repoHint } : null
  }
  return null
}

// ── 汇总 ────────────────────────────────────────────────────────────

// 返回 { root, branch, subject } 或 null
function evaluate(dirForRepo, filePath) {
  const root = repoRoot(dirForRepo)
  if (!root) return null // 非 git 仓

  const branch = currentBranch(root)
  if (!branch || !PROTECTED_BRANCHES.has(branch)) return null

  if (isOperationInProgress(root)) return null // 合流进行中，解决冲突需要写

  // 两侧都归一到 realpath 形态后再比，否则符号链接会让 relative() 给出 `..` 开头的结果
  const canonicalFile = filePath ? canonicalize(filePath) : null
  if (canonicalFile && isExemptPath(canonicalFile, root)) return null

  return {
    root,
    branch,
    subject: canonicalFile ? path.relative(root, canonicalFile) : '`git commit`',
  }
}

function main() {
  if (process.env.WORKTREE_GUARD === 'off') process.exit(0)

  let input = ''
  try {
    input = fs.readFileSync(0, 'utf8')
  } catch (_) {
    process.exit(0)
  }

  let payload
  try {
    payload = JSON.parse(input)
  } catch (_) {
    process.exit(0)
  }

  const tool = payload.tool_name
  const toolInput = payload.tool_input || {}
  const cwd = payload.cwd || process.cwd()

  let hit = null

  if (tool === 'Write' || tool === 'Edit' || tool === 'MultiEdit') {
    const file = toolInput.file_path
    if (!file) process.exit(0)
    const abs = path.isAbsolute(file) ? file : path.resolve(cwd, file)
    hit = evaluate(abs, abs)
  } else if (tool === 'NotebookEdit') {
    const file = toolInput.notebook_path
    if (!file) process.exit(0)
    const abs = path.isAbsolute(file) ? file : path.resolve(cwd, file)
    hit = evaluate(abs, abs)
  } else if (tool === 'Bash') {
    const command = toolInput.command || ''
    if (!command) process.exit(0)
    for (const segment of splitSegments(stripHeredocs(command))) {
      const found = findGitCommit(segment)
      if (!found) continue
      const dir = found.repoHint
        ? path.isAbsolute(found.repoHint)
          ? found.repoHint
          : path.resolve(cwd, found.repoHint)
        : cwd
      hit = evaluate(dir, null)
      if (hit) break
    }
  } else {
    process.exit(0)
  }

  if (!hit) process.exit(0)

  const finding = `仓 ${truncate(hit.root, PATH_ECHO_LIMIT)} 当前在受保护分支 ${hit.branch}，禁止直接改代码（目标：${truncate(hit.subject, PATH_ECHO_LIMIT)}）`
  const hint =
    '先开工作区：调 EnterWorktree 工具 {"name":"<任务语义-kebab>"}，它建临时分支并把会话切进去，在那里改与提交；' +
    '收尾回到主目录后照抄三步：git -C <仓根> merge --no-ff <临时分支> ；' +
    'git -C <仓根> worktree remove <worktree 路径> ；git -C <仓根> branch -d <临时分支>。' +
    '临时分支不 push remote。确需在主分支直接写时用 WORKTREE_GUARD=off 临时关闭本闸。'

  process.stderr.write(
    `[L1-BLOCKER] tool=${tool} check=worktree-flow finding="${finding}" hint="${hint}"\n`
  )
  process.exit(2)
}

main()
