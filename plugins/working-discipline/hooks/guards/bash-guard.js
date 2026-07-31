// bash-guard.js — PreToolUse 门控钩子（matcher: Bash）
//
// 【用途】
// 针对 Bash 这一个对象的**唯一** hook。3.0.0 起本插件按拦截对象收敛挂载拓扑：
// Agent → agent-dispatch.js，Bash → 本文件，Write|Edit → write-guard.js。
//
// 本文件是 block-cd.js（1.x 引入）与 agent-browser-launch.js（原 agent-browser-headed.js）
// 合并的产物。两者原本各自挂 PreToolUse(Bash)、各自读一遍 stdin、各自解析一遍命令行，
// 且**串行短路**——第一个 guard 拦下后第二个根本不执行，AI 改完第一处才看见第二处。
// 合并后一次解析、一次把所有问题报清，同一条命令的多类违规一轮改完。
//
// 【两条判据的真实覆盖面（3.6.0 按审计实测如实改写）】
// 3.6.0 前本注释写着独立 cd「由 shell-parse 逐字符切分后**精确定位**」。
// 2026-07-31 审计跑了 103 条真实 payload，证伪了"精确"二字。如实表述如下：
//
//   - 独立 cd：实际判据是「剥掉 heredoc 与子 shell 后，由 `; && || | \n` 切出的顶层
//     片段，trim() 后以 `cd` 开头」。它抓的是**文本形态**，不是"这条命令是否改变父
//     shell 的 cwd"。已知**不覆盖**（实测全部放行，且全都真的污染 cwd）：
//     `pushd` / `source` 或 `.` 引入的脚本 / `eval 'cd ...'` / `\cd` / `builtin cd` /
//     `command cd` / `"cd" /tmp` / `CDPATH=/ cd tmp` / `time cd` / `git status & cd /tmp`
//     （单个 `&` 在 splitSegments 里没有语义）/ `if...then cd` `{ cd; }` `for...do cd`
//     `case...) cd` 与函数体内的 cd（分支标签排在 cd 之前）。
//     还有一个通用绕过点：lib/shell-parse.js 的 stripSubshells 括号匹配不感知引号，
//     `echo "(start" && cd /tmp && echo "end)"` 里的真 cd 会被假括号配对整段吃掉。
//     **这也解释了 `(cd /abs && cmd)` 为什么放行**——不是因为判定了"变更不泄漏到父
//     shell"，而是因为括号里的文本被删掉了。旁证：`(cd /tmp && ls) && cd /var` 仍拦。
//     结论：这条判据只拦得住「裸 cd 开头」这一种形态，是**提醒**不是**保证**。
//
//   - agent-browser 启动参数：命令名按 basename 匹配（含 npx / bunx / pnpm dlx 前缀）、
//     子命令取第一个位置参数并在已知词表内匹配、`--headed`/`--profile` 在**该次调用的
//     tail 内**判定。已知**不覆盖**：`$(which agent-browser) open`、`AB=agent-browser;
//     $AB open` 等命令替换与变量间接调用；不在词表里的子命令（未知即放行，CLI 新增
//     启动类子命令时本判据静默失效）；白名单里的 `read <URL>` 等在 daemon 不存在时
//     会自行拉起 headless 实例的子命令。
//
// 【检查一：独立 cd 污染 cwd】
// Bash 工具的 cwd 在多次调用之间持久保留，AI 一旦在中间执行 `cd /tmp`，后续所有相对
// 路径操作都会失准（"为什么找不到 requirements/foo"这类诡异现象的根因）。
// 放行：`(cd /path && cmd)` 子 shell / `$(cd /path && pwd)` 命令替换 / 字符串内的 cd /
//       heredoc 正文里的 cd / 以单个 `&` 后台化的片段 / no-op cd（目标解析后等于当前
//       cwd，如 `cd .`、`cd $PWD`、`cd <当前目录绝对路径>`、符号链接或大小写等价路径）
// 处置里第 3 条专门推荐 `git -C`：真实事故（2026-07-20，D-001 会话）AI 用
//   (cd /path/to/claude-devkit-marketplace && git push origin main)
// 推一个与当前项目无关的仓库，被 sdlc 插件 hooks/lib/worktree-utils.js 的
// resolveGitCwd() 误拦——它用 /^cd\s+.../ 识别 cd 前缀来判定 git 命令作用于哪个仓库，
// 子 shell 语法带括号、不以 cd 开头，正则匹配不上就 fall back 到当前 worktree，把发往
// 第三方仓库的 push 误判成本项目 delivery 分支的 push。`git -C <path>` 语义等价、不含
// cd token、不进子 shell，能同时躲开本 hook 与这类跨插件误伤。
//
// 3.6.0 修掉的四类误杀（均为审计实测的真实 BLOCK）：
//   1. heredoc 正文（最严重）：`ssh prod bash -s <<'EOF' / cd /srv/app / ... / EOF`
//      被判本地污染，而那个 cd 在远程主机执行；`python3 - <<'EOF'` 里的 cd 甚至不是
//      shell 命令。且原 hint（改绝对路径 / 套子 shell）对 heredoc 正文完全无解。
//      现在 checkCd 前先调 stripHeredocs 剥离正文。
//   2. `cd /tmp &`：`&` 结尾的命令在子 shell 异步执行，父 shell cwd 不变。
//   3. 符号链接：macOS 上 cwd=/private/tmp 时 `cd /tmp` 实为 no-op，原实现只做
//      path.resolve 字符串归一，不 realpath。
//   4. `cd $PWD` 与大小写等价路径（APFS 默认大小写不敏感），同上。
//
// 【检查二：agent-browser 启动——headless 默认下的新四护栏】
// 沿革：3.6.0 前本检查强制 --headed + --profile，起因是 2026-07-20 D-001 verify 事故——
// AI 用 headless 起 Chrome for Testing 复现前端问题，用户看不到窗口、只看到权限申请弹窗，
// 质疑"你现在是创建了一个 headless 的 chrome 实例吗？"。3.7.0 应产品要求**改为默认 headless**：
// 用户接受 headless 作为常态，但要求用四道新机制替代"看到窗口"提供的监督——
//   ①鉴权前置（headless 下人类无法中途授权，启动前必须备好登录态）
//   ②实例上限 4（agent-browser 无内置并发上限，--session 只隔离不计数，须外部强制）
//   ③登录态复用（保留原 --profile 硬要求，沿用 3.6.0 的判据）
//   ④安全边界提醒（--allowed-domains / --content-boundaries，仅提醒级，不阻断）
// 故删掉 --headed 强制，新增 ①②，③保留，④降为 hint。
//
// 3.7.0 四护栏的判据（均只在该次调用自己的 tail + 紧邻环境变量前缀里判定，不跨片段共用）：
//   - ①缺鉴权：启动类子命令且 tail/env 里无 --profile / --state / --headers / --restore
//     任一持久化鉴权方式（也无对应 env 前缀 AGENT_BROWSER_PROFILE 等）→ BLOCK
//   - ②实例超限：启动类子命令时同步 run `agent-browser session list`，活动实例 ≥4 → BLOCK；
//     CLI 不存在 / 超时 / 解析失败 → 放行（不因工具未装而误拦，沿用"未知即放行"方向）
//   - ③登录态复用：并入 ①——缺鉴权判据已覆盖"无 --profile"情形，不再单列
//   - ④安全边界：tail 无 --allowed-domains 且无 --content-boundaries → 追加 hint，不阻断
// 放行：子命令不在启动类集合（snapshot/click/... 白名单）/ 未知子命令 / tail 含
//       --help / -h / --version / -V / `chat` 后没接 URL（纯 REPL 模式）
//
// 沿用 3.6.0 的工程改进（不再重复审计，仅记要点）：
//   - 逐片段独立判定，不跨片段共用结果（修掉"口令退化"）
//   - 命令名按 basename 匹配，认 npx/bunx/pnpm dlx 前缀与绝对路径
//   - tail 含 --help/-h/--version/-V 直接放行；--profile="" 视为空值
//   - 环境变量前缀 AGENT_BROWSER_PROFILE=<非空值> 等可替代对应 flag
//   - 未知子命令一律放行（CLI 新增启动类子命令时本判据静默失效，已知代价，不改变方向）
//
// 【阻塞行为】
// 任一检查命中即 exit 2 阻断，stderr 一次输出全部 findings（stderr 会作为附加上下文注入
// Claude，控制在 400 字符量级——本插件存在的目的就是避免上下文膨胀，拦截文案自己不能违规）。
// 3.6.0 修：违规片段原样回灌曾把 20 多行测试数据塞进 finding（实测单条 900+ 字符），
// 现在片段截断到 SEGMENT_ECHO_LIMIT 字符。
//   [L1-BLOCKER] tool=Bash check=bash-guard finding="..." hint="..."
//
// Input: JSON on stdin with tool_name / tool_input.command / cwd
// Exit 0 = 放行; Exit 2 = 阻断

'use strict'

const fs = require('fs')
const path = require('path')
const {
  splitSegments,
  stripSubshells,
  stripHeredocs,
  tokenize,
  stripQuotes,
} = require('../lib/shell-parse')

// 回灌进 finding 的违规片段最大长度
const SEGMENT_ECHO_LIMIT = 120

function truncate(text, limit) {
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

// ── 检查一：独立 cd ──────────────────────────────────────────────────

// 独立 cd 命令的锚点：行首 / 命令分隔符之后（分隔符 ; && || | 换行）
const CD_PATTERN = /(^|[;&|\n])\s*cd(\s|$)/

// `cd $PWD` / `cd ${PWD}` 定义上等于当前目录（引号已由 parseCdTarget 剥掉）
const PWD_TARGETS = new Set(['$PWD', '${PWD}'])

// 如果 segment 是 cd 命令，返回其目标字符串（去引号）；否则返回 undefined。
// `cd` 不带参数时返回空串（代表 home）。
function parseCdTarget(segment) {
  const trimmed = segment.trim()
  if (!/^cd(\s|$)/.test(trimmed)) return undefined
  const rest = trimmed.slice(2).trim()
  if (!rest) return ''
  // 取第一个 token（cd 实际只关注第一个参数）
  const m = rest.match(/^("([^"]*)"|'([^']*)'|(\S+))/)
  if (!m) return ''
  return (m[2] !== undefined ? m[2] : m[3] !== undefined ? m[3] : m[4]) || ''
}

function normalizePath(p) {
  let n
  try {
    n = path.resolve(p)
  } catch (_) {
    n = p
  }
  if (process.platform === 'win32') n = n.toLowerCase()
  return n.replace(/[\\/]+$/, '')
}

// 解析符号链接；路径不存在等异常时原样返回（不因此判定为非 no-op）
function realpathOrSelf(p) {
  try {
    return fs.realpathSync(p)
  } catch (_) {
    return p
  }
}

// 判定 cd 目标是否为 no-op（解析后等于当前 cwd）
function isNoOpCd(target, cwd) {
  if (target === undefined || target === null) return false
  if (target === '') return false // `cd` 单独 → home，非 no-op
  if (target === '.' || target === './' || target === '.\\') return true
  if (PWD_TARGETS.has(target)) return true

  const resolved = path.isAbsolute(target) ? target : path.join(cwd, target)
  if (normalizePath(resolved) === normalizePath(cwd)) return true

  // 符号链接等价（macOS /tmp → /private/tmp）
  const realTarget = normalizePath(realpathOrSelf(resolved))
  const realCwd = normalizePath(realpathOrSelf(cwd))
  if (realTarget === realCwd) return true

  // 大小写不敏感文件系统（APFS / HFS+ 默认）上只有大小写不同即同一目录
  if (process.platform === 'darwin' && realTarget.toLowerCase() === realCwd.toLowerCase()) {
    return true
  }
  return false
}

// 片段以单个 `&` 结尾 → 后台化，在子 shell 异步执行，父 shell 的 cwd 不变。
// （splitSegments 已把 `&&` 切开，正常不会出现 `&&` 结尾，仍显式排除以防万一。）
function isBackgrounded(segment) {
  const trimmed = segment.trim()
  return trimmed.endsWith('&') && !trimmed.endsWith('&&')
}

// 返回违规片段字符串，或 null
function checkCd(command, cwd) {
  // 先剥 heredoc 正文（那是喂给别的解释器 / 远端的文本），再剥子 shell，
  // 剩下的才是会污染父 shell 的部分
  const stripped = stripSubshells(stripHeredocs(command))
  if (!CD_PATTERN.test(stripped)) return null

  // 只要存在一个会改变 cwd 的 cd 就违规；全是 no-op 则放行
  for (const seg of splitSegments(stripped)) {
    const target = parseCdTarget(seg)
    if (target === undefined) continue
    if (isBackgrounded(seg)) continue
    if (!isNoOpCd(target, cwd)) return seg.trim()
  }
  return null
}

// ── 检查二：agent-browser 启动（headless 默认下的新四护栏）──────────

// 启动类子命令：会真正拉起一个新 CFT 实例的子命令
const LAUNCH_SUBCOMMANDS = new Set(['open', 'connect', 'chat'])

// 白名单子命令：即使含 agent-browser 也放行，不触发本规则
const ALLOWLIST_SUBCOMMANDS = new Set([
  // 只读探测类
  'skills', 'doctor', 'install', 'upgrade',
  // 生命周期无关类（browser 实例已存在或与启动无关的管理动作）
  'close', 'mcp', 'dashboard', 'session', 'plugin', 'auth', 'profiles', 'confirm', 'deny',
  // 后续操作类（browser 已启动后的动作，不触发新的 launch）
  'snapshot', 'click', 'dblclick', 'fill', 'type', 'press', 'hover', 'focus',
  'check', 'uncheck', 'select', 'upload', 'download', 'scroll', 'scrollintoview',
  'drag', 'wait', 'screenshot', 'pdf', 'eval', 'get', 'is', 'find', 'mouse', 'set',
  'network', 'cookies', 'storage', 'tab', 'diff', 'trace', 'profiler', 'record',
  'console', 'errors', 'highlight', 'inspect', 'clipboard', 'stream', 'react',
  'vitals', 'pushstate', 'removeinitscript', 'back', 'forward', 'reload', 'read',
  'batch', 'keyboard',
])

const ALL_KNOWN_SUBCOMMANDS = new Set([...LAUNCH_SUBCOMMANDS, ...ALLOWLIST_SUBCOMMANDS])

// 查帮助 / 查版本不会拉起任何浏览器实例
const HELP_FLAGS = new Set(['--help', '-h', '--version', '-V'])

// URL 位置参数判定（chat 子命令专用）：形如 scheme://
const URL_PATTERN = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//

// 命令前的环境变量赋值前缀，如 `FOO=bar cmd`
const ENV_ASSIGN_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*=/

// ── 护栏①：鉴权前置 ──
// headless 下人类无法中途授权，启动前必须备好登录态。任一持久化鉴权方式存在即满足：
//   --profile / --state / --headers / --restore（含 =值 与 空格分两 token 两种形态）。
// flags 不含 --restore 的"无值"布尔形态也认（--restore 本身就是"启用恢复"的开关）。
const AUTH_FLAGS = new Set(['--profile', '--state', '--headers', '--restore'])

// 环境变量替代形态（紧邻命令的 VAR=值 前缀）。任一非空即算提供了鉴权机制。
// 注意 PROFILE 只要求非空（--profile="" 实际传空值，已在 flag 判据里单独处理）。
const AUTH_ENV_PATTERNS = [
  /^AGENT_BROWSER_PROFILE=.+$/,
  /^AGENT_BROWSER_HEADERS=.+$/,
  /^AGENT_BROWSER_STATE=.+$/,
]

// ── 护栏②：实例上限 ──
// agent-browser 无内置并发上限，--session 只隔离不计数；本 guard 在启动前查 session list。
const INSTANCE_LIMIT = 4
// daemon 输出形如 "Active sessions:\n-> default\n   agent1" —— 数顶层（-> 开头）条目数
const SESSION_TOPLEVEL_PATTERN = /^->/m

// 在某个顶层片段里定位处于**命令名位置**的 agent-browser 调用。
// 命令名位置 = 跳过 `VAR=值` 前缀后的第一个 token，或其后紧跟的 npx / bunx / pnpm dlx。
// 返回 { tail, envPrefix }；不是调用则返回 null。
function findInvocation(segment) {
  const tokens = tokenize(segment).map(stripQuotes)
  let i = 0
  while (i < tokens.length && ENV_ASSIGN_PATTERN.test(tokens[i])) i++
  const envPrefix = tokens.slice(0, i)

  if (i >= tokens.length) return null
  if (tokens[i] === 'npx' || tokens[i] === 'bunx') i++
  else if (tokens[i] === 'pnpm' && tokens[i + 1] === 'dlx') i += 2
  if (i >= tokens.length) return null

  // 命令名允许带路径前缀：/usr/local/bin/agent-browser
  const basename = tokens[i].split('/').pop()
  if (basename !== 'agent-browser') return null

  return { tail: tokens.slice(i + 1), envPrefix }
}

// 子命令 = tail 里第一个位置参数（跳过 flag 及其值）。取第一个而非"第一个词表命中"，
// 避免 `--profile open` 这类 flag 值被误当子命令。不在词表里返回 null（未知即放行）。
function findSubcommand(tail) {
  for (let i = 0; i < tail.length; i++) {
    const t = tail[i]
    if (t.startsWith('-')) continue
    const prev = tail[i - 1]
    if (prev && prev.startsWith('-') && !prev.includes('=')) continue // 是上一个 flag 的值
    return ALL_KNOWN_SUBCOMMANDS.has(t) ? t : null
  }
  return null
}

function hasHelpFlag(tail) {
  return tail.some((t) => HELP_FLAGS.has(t))
}

// 护栏①判据：tail 或紧邻 env 前缀里是否提供了任一持久化鉴权方式。
// flag 形态分两种：
//   (a) `--flag=<非空值>` —— --restore 是布尔开关，`--restore` 与 `--restore=true` 都认；
//       --profile/--state/--headers 必须有非空值（空值视为没提供，见下方 stripQuotes 复剥）
//   (b) `--flag <值>` —— 值是下一个 token，不能以 `-` 开头（否则那是另一个 flag）
// env 前缀：AGENT_BROWSER_PROFILE/HEADERS/STATE 任一非空即满足
function hasAuthMechanism(tail, envPrefix) {
  if (envPrefix.some((t) => AUTH_ENV_PATTERNS.some((re) => re.test(t)))) return true

  for (let i = 0; i < tail.length; i++) {
    const t = tail[i]
    // `--restore` 无值布尔开关：单独出现即满足
    if (t === '--restore') return true
    // `--profile` / `--state` / `--headers` 接下一个 token 当值
    if (t === '--profile' || t === '--state' || t === '--headers') {
      const next = tail[i + 1]
      if (next && !next.startsWith('-') && stripQuotes(next).length > 0) return true
      continue
    }
    // `--flag=<值>` 形态
    for (const flag of ['--profile=', '--state=', '--headers=', '--restore=']) {
      if (t.startsWith(flag)) {
        const val = stripQuotes(t.slice(flag.length))
        // --restore=<bool> 任意非空都算启用；其余要非空真值
        if (flag === '--restore=' ? val.length > 0 : val.length > 0) return true
      }
    }
  }
  return false
}

// 护栏④判据（仅提醒级）：tail 里是否有 --allowed-domains 或 --content-boundaries
function hasSafetyBoundary(tail) {
  return tail.some(
    (t) =>
      t === '--allowed-domains' ||
      t.startsWith('--allowed-domains=') ||
      t === '--content-boundaries'
  )
}

// 护栏②判据：run `agent-browser session list` 数当前活动实例数。
// CLI 不存在 / 超时 / 输出无法解析 → 返回 -1（调用方据此放行，不因工具未装而误拦）。
// 测试桩：设环境变量 WD_AB_INSTANCE_COUNT=<整数> 可绕过真实 CLI（仅用于回归测试）。
function countActiveInstances() {
  if (process.env.WD_AB_INSTANCE_COUNT !== undefined) {
    const n = Number(process.env.WD_AB_INSTANCE_COUNT)
    return Number.isFinite(n) ? n : -1
  }
  const { execSync } = require('child_process')
  try {
    const out = execSync('agent-browser session list', {
      timeout: 3000,
      stdio: ['ignore', 'pipe', 'ignore'],
      encoding: 'utf8',
    })
    // 数顶层条目（-> 开头的行）；输出空或无 -> 视为 0 个
    const matches = out.match(new RegExp(SESSION_TOPLEVEL_PATTERN.source, 'g'))
    return matches ? matches.length : 0
  } catch (_) {
    return -1 // CLI 未装 / daemon 未起 / 超时 —— 放行
  }
}

// chat 子命令：仅当后面接了 URL 位置参数才算"启动"，纯 REPL 模式不拦
function chatHasUrlArg(tail) {
  const chatIndex = tail.indexOf('chat')
  if (chatIndex === -1) return false
  for (let i = chatIndex + 1; i < tail.length; i++) {
    const t = tail[i]
    if (t.startsWith('-')) continue
    if (URL_PATTERN.test(t)) return true
  }
  return false
}

// 返回 { subcommand, missingAuth, tooManyInstances, instanceCount, missingBoundary } 或 null
//   missingAuth / tooManyInstances → 阻断（exit 2）；missingBoundary → 仅提醒（不阻断）
function checkAgentBrowser(command) {
  if (!/\bagent-browser\b/.test(command)) return null

  for (const segment of splitSegments(command)) {
    const invocation = findInvocation(segment)
    if (!invocation) continue
    const { tail, envPrefix } = invocation

    if (hasHelpFlag(tail)) continue // 查帮助 / 查版本，不拉起实例

    const subcommand = findSubcommand(tail)
    if (!subcommand || !LAUNCH_SUBCOMMANDS.has(subcommand)) continue
    if (subcommand === 'chat' && !chatHasUrlArg(tail)) continue // REPL 模式，不拦

    // 护栏①：缺鉴权 → 阻断
    const missingAuth = !hasAuthMechanism(tail, envPrefix)

    // 护栏②：实例超限 → 阻断（CLI 不可用时 countActiveInstances 返回 -1，放行）
    const instanceCount = countActiveInstances()
    const tooManyInstances = instanceCount >= INSTANCE_LIMIT

    // 护栏④：缺安全边界 → 仅提醒（不参与阻断决策，但带回给调用方拼 hint）
    const missingBoundary = !hasSafetyBoundary(tail)

    // 只有阻断类命中才提前 return；两者都没命中时仍要把 missingBoundary 带回去做提醒
    if (!missingAuth && !tooManyInstances) {
      return missingBoundary ? { subcommand, missingBoundary } : null
    }

    return {
      subcommand,
      missingAuth,
      tooManyInstances,
      instanceCount,
      missingBoundary,
    }
  }
  return null
}

// ── 汇总 ────────────────────────────────────────────────────────────

function main() {
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

  if (payload.tool_name !== 'Bash') process.exit(0)

  const command = (payload.tool_input && payload.tool_input.command) || ''
  if (!command) process.exit(0)
  const cwd = payload.cwd || process.cwd()

  const findings = []
  const hints = []

  const cdSegment = checkCd(command, cwd)
  if (cdSegment) {
    findings.push(
      `独立 \`cd\` 会污染后续所有 Bash 调用的 cwd(cwd=${cwd});违规片段：${truncate(cdSegment, SEGMENT_ECHO_LIMIT)}`
    )
    hints.push('改用绝对路径,或子 shell `(cd /abs/path && cmd)`,git 命令优先 `git -C <path> <cmd>`')
  }

  const ab = checkAgentBrowser(command)
  if (ab) {
    // 护栏①缺鉴权 → 阻断
    if (ab.missingAuth) {
      findings.push(`agent-browser ${ab.subcommand} 缺鉴权机制;headless 下人类无法中途登录授权`)
      hints.push('启动前先向用户索取账密/token/cookie 并注入:--headers {"Authorization":"Bearer <token>"} 注入 token(推荐,origin 作用域),或 --profile <持久化目录> 复用登录态(推荐建独立 AI Testing Chrome profile),或 --state <文件> 加载已保存凭据;详见 agent-browser 插件 SKILL.md')
    }
    // 护栏②实例超限 → 阻断
    if (ab.tooManyInstances) {
      findings.push(`agent-browser ${ab.subcommand} 实例已达上限 ${INSTANCE_LIMIT}(当前 ${ab.instanceCount} 个);无内置并发上限,须外部节制`)
      hints.push(`先 \`agent-browser close\` 或 \`agent-browser close --all\` 释放实例,或等现有任务完成;全局上限 ${INSTANCE_LIMIT} 个并发实例`)
    }
    // 护栏④缺安全边界 → 仅提醒（不阻断；阻断类已命中时合并进 hint，未命中时也不 exit 2）
    if (ab.missingBoundary) {
      hints.push('headless 建议带 --allowed-domains "目标域" 限域 + 禁 WebRTC 防 DNS 旁路,--content-boundaries 隔开网页内容防 prompt 注入,--max-output 50000 防上下文洪泛')
    }

    // 仅护栏④命中（无阻断类）时不阻断，只把提醒作为附加上下文喂回，本轮继续
    const hasBlocker = ab.missingAuth || ab.tooManyInstances
    if (!hasBlocker) {
      if (ab.missingBoundary) {
        process.stderr.write(
          `[L1-ADVISE] tool=Bash check=bash-guard hint="${hints[hints.length - 1]}"\n`
        )
      }
      // 清掉这条 hint，避免它被拼进下面的 findings 输出
      hints.pop()
    }
  }

  if (!findings.length) process.exit(0)

  process.stderr.write(
    `[L1-BLOCKER] tool=Bash check=bash-guard finding="${findings.join(';')}" hint="${hints.join(';')}"\n`
  )
  process.exit(2)
}

main()
