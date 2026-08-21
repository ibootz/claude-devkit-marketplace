// main-branch-guard.js — PreToolUse 门控钩子（matcher: Write|Edit|MultiEdit|NotebookEdit|Bash）
//
// 【用途】
// 默认禁止在受保护分支（main / master）上直接改代码。命中即 exit 2 阻断，文案给两条路：
// 开 worktree，或由主会话用 AskUserQuestion 向 Human 申请本轮放行。
//
// 【为什么仍以 deny 起步】
// 本机 Claude Code 的 defaultMode 为 bypassPermissions，`permissionDecision: "ask"` 实测
// 全部失效（弹框不出现、直接放行）。故不能让 PreToolUse 自己 ask：首次命中仍 deny，主会话
// 随后真实调用 AskUserQuestion；PostToolUse 只在 Human 选择固定“批准本轮”项后写 session-scoped
// 临时凭据。本 guard 见凭据才放行，Stop / 下一次 UserPromptSubmit / SessionEnd 即清。
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
// 6. `git commit` 的豁免（1.4.0 新增）：命中受保护分支后，若这次提交能**证明**只动豁免
//    路径则放行。三个条件同时成立才算证明——(a) flag 全在白名单内（`-a` / `-A` / `--all`
//    / `-i` / `--include` / `--amend` / `--patch` / `--pathspec-from-file` 与任何未列入
//    的 flag 都出局，因为它们在提交那一刻才扩大暂存范围或改写既有提交，事先读到的索引
//    不再是权威）；(b) 显式 pathspec 逐条豁免（含 `--` 之后与裸路径形态，通配符与
//    `:` 开头的 magic pathspec 一律判不定）；(c) `git diff --cached --name-only` 非空
//    且逐条豁免。判不定就维持阻断，方向与本机制存在以来一致。
//    修的是这个结构性缺口：Bash 侧走 evaluate(dir, null)，filePath 为 null 时豁免判定
//    整段被短路，于是路径豁免对 Write/Edit 生效、对 `git commit` 不生效——keeper 只提交
//    `.keeper/` 台账也会被拦，而它写那批文件时一路放行。
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
//   - `git commit` 只动豁免路径、但写法不在白名单内（`-a`、`--amend`、罕见 flag、
//     glob pathspec）——仍被拦。这是白名单换来的代价：改法是先窄 `git add` 再不带 `-a`
//     提交，或走 worktree。**不要为了过闸把判据放宽成黑名单。**
//
// Input: JSON on stdin（tool_name / tool_input / cwd）
// Exit 0 = 放行；Exit 2 = 阻断（stderr 作为附加上下文回灌给 Claude）

'use strict'

const fs = require('fs')
const path = require('path')
const { execFileSync } = require('child_process')

const { approvalToolInput, isRoundApproved } = require('../lib/round-approval')

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

// 命中返回 { repoHint, args }（`git -C <path>` 时 repoHint 为那个 path，args 是 `commit`
// 之后的全部 token），否则返回 null
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
    return t === 'commit' ? { repoHint, args: tokens.slice(i + 1) } : null
  }
  return null
}

// ── Bash 侧：这次 `git commit` 是否可证明只动豁免路径 ────────────────
//
// `git commit` 的 flag **白名单**：只列不改变暂存范围、也不改写既有提交的那些。
// 白名单而非黑名单是有意的——未列入的 flag 一律按「证明不了」处理、维持阻断，与本机制
// 存在以来的行为一致。黑名单在这里方向是错的：日后 git 新增一个扩大暂存范围的 flag，
// 黑名单会静默放行它，而白名单最坏只是多拦一次本来安全的写法（出口是 worktree 或授权）。
const COMMIT_FLAGS_NO_VALUE = new Set([
  '-n', '--no-verify', '--verify',
  '-q', '--quiet',
  '-v', '--verbose',
  '-s', '--signoff', '--no-signoff',
  '-e', '--edit', '--no-edit',
  '--allow-empty', '--allow-empty-message',
  '--no-gpg-sign', '--no-post-rewrite',
  '--status', '--no-status',
  '--dry-run',
  // -o/--only 把提交范围**限制**到 pathspec，比默认更窄；pathspec 本身下面逐条校验
  '-o', '--only',
])

// 取一个独立 token（或 --x=y 的 y）作为值；那个值不是 pathspec，不参与豁免判定
const COMMIT_FLAGS_WITH_VALUE = new Set([
  '-m', '--message',
  '-F', '--file',
  '-t', '--template',
  '-c', '--reedit-message',
  '-C', '--reuse-message',
  '--author', '--date', '--cleanup', '--trailer',
  '--fixup', '--squash',
])

// pathspec 里出现这些就不展开、直接判「证明不了」：通配符要 glob、`:` 开头是 magic pathspec
const UNRESOLVABLE_PATHSPEC = /[*?[\]]/

// args 是 `commit` 之后的全部 token。返回 true 仅当能**证明**这次提交只会动豁免路径；
// 任何一处判不定都返回 false（维持阻断）。
//
// 【为什么需要这个函数】Bash 侧走的是 evaluate(dir, null)，filePath 为 null 时
// isExemptPath 那一步被短路，于是路径豁免对 Write/Edit 生效、对 `git commit` 不生效——
// 「只提交 .keeper/ 台账」这种本该豁免的提交照样被拦。这是 1.4.0 修的结构性缺口。
//
// 【为什么 -a/-A/--all/-i/--include/--amend 一律不放】它们在**提交那一刻**才扩大暂存
// 范围（-a 带走所有已跟踪的改动）或改写既有提交（--amend 带走上一个 commit 的内容），
// 事先读到的索引不再是这次提交内容的权威快照。
function commitConfinedToExempt(root, cwd, args) {
  const pathspecs = []
  let afterDashDash = false

  for (let i = 0; i < args.length; i++) {
    const t = args[i]
    if (afterDashDash) {
      pathspecs.push(t)
      continue
    }
    if (t === '--') {
      afterDashDash = true
      continue
    }
    if (COMMIT_FLAGS_NO_VALUE.has(t)) continue
    if (COMMIT_FLAGS_WITH_VALUE.has(t)) {
      i++ // 跳过它的值
      continue
    }
    if (t.startsWith('--') && t.includes('=')) {
      const name = t.slice(0, t.indexOf('='))
      if (COMMIT_FLAGS_WITH_VALUE.has(name) || COMMIT_FLAGS_NO_VALUE.has(name)) continue
      return false
    }
    if (t.startsWith('-') && t.length > 1) {
      // 短 flag 粘连值（-mmsg / -m"msg" 被 tokenize 去引号后成 -mmsg）
      if (t.length > 2 && COMMIT_FLAGS_WITH_VALUE.has(t.slice(0, 2))) continue
      return false // 未列入白名单的 flag，或 -am 这类短 flag 串
    }
    pathspecs.push(t) // `git commit <path>` 不带 -- 也是合法 pathspec
  }

  // 显式 pathspec 会带走**工作区**里那些路径的内容，绕开索引，故必须逐条豁免。
  // pathspec 以命令自己的 cwd 为基准解析（`git -C <path>` 时是那个 path），不是仓根。
  for (const spec of pathspecs) {
    if (!spec || spec.startsWith(':') || UNRESOLVABLE_PATHSPEC.test(spec)) return false
    const abs = path.isAbsolute(spec) ? spec : path.resolve(cwd, spec)
    if (!isExemptPath(canonicalize(abs), root)) return false
  }

  // 索引就是这次提交会带走什么的权威快照。三个 -c 是为了钉死输出形态、不受本机配置影响：
  //   diff.relative=false → 路径恒以仓根为基准（否则会相对 cwd）
  //   core.quotePath=false → 非 ASCII 路径不转义成 \xxx（转义后必然判不豁免、只会多拦）
  //   --no-renames → 重命名摊成 delete + add 两条，避免只看到新名字而漏掉旧名字
  const staged = git(
    [
      '-c', 'diff.relative=false',
      '-c', 'core.quotePath=false',
      'diff', '--cached', '--name-only', '--no-renames', '-z',
    ],
    root
  )
  if (staged === null) return false // 读不到索引 → 判不定
  const files = staged.split('\0').filter(Boolean)
  if (!files.length) return false // 空索引 → 这次提交要么失败，要么在改写别的东西
  return files.every((rel) => isExemptPath(canonicalize(path.resolve(root, rel)), root))
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
      // 命中受保护分支后再看这次提交能不能证明只动豁免路径；能证明就当没命中
      if (hit && commitConfinedToExempt(hit.root, dir, found.args || [])) hit = null
      if (hit) break
    }
  } else {
    process.exit(0)
  }

  if (!hit) process.exit(0)
  if (isRoundApproved(payload.session_id)) process.exit(0)

  const finding = `仓 ${truncate(hit.root, PATH_ECHO_LIMIT)} 当前在受保护分支 ${hit.branch}，本轮尚无 Human 直接写入授权（目标：${truncate(hit.subject, PATH_ECHO_LIMIT)}）`
  const request = JSON.stringify(
    approvalToolInput({ repository: hit.root, branch: hit.branch, target: hit.subject })
  )
  const hint =
    '默认路径：调 EnterWorktree 工具 {"name":"<任务语义-kebab>"}，在临时分支改与提交，再 --no-ff 合回。' +
    `若确需本轮直写：主会话原样调用 AskUserQuestion ${request}；` +
    'Human 选择“批准本轮”后重试，授权覆盖当前会话本轮全部 main/master 写入，下一次用户消息或本轮结束即失效。' +
    '子代理不能提问，须回主会话申请。WORKTREE_GUARD=off 是独立的全局关闭开关，不得拿它冒充 Human 本轮授权。'

  process.stderr.write(
    `[L1-BLOCKER] tool=${tool} check=worktree-flow finding="${finding}" hint="${hint}"\n`
  )
  process.exit(2)
}

main()
