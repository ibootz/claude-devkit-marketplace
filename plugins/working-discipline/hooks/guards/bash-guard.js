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
// 【判据都是命令行的确定结构，没有"猜语义"的词表】
// 3.0.0 删掉了本插件所有靠关键词猜意图的 guard（external-write-readback 扫
// create/update/delete/发布 等词、nonascii-path 把命令行里任何非 ASCII 字节当成"路径"）。
// 留在这里的两条判据性质不同：
//   - 独立 cd：`cd` 是 shell 的确定 token，由 lib/shell-parse.js 逐字符切分后精确定位，
//     引号内的 `cd`、子 shell 里的 `cd`、no-op 的 `cd .` 都能准确排除
//   - agent-browser 启动参数：命令名精确等于 `agent-browser`、子命令在已知词表内精确匹配、
//     `--headed`/`--profile` 是参数存在性判定——三项都是命令行结构事实，不是意图推测
//
// 【检查一：独立 cd 污染 cwd】
// Bash 工具的 cwd 在多次调用之间持久保留，AI 一旦在中间执行 `cd /tmp`，后续所有相对
// 路径操作都会失准（"为什么找不到 requirements/foo"这类诡异现象的根因）。
// 放行：`(cd /path && cmd)` 子 shell / `$(cd /path && pwd)` 命令替换 / 字符串内的 cd /
//       no-op cd（目标解析后等于当前 cwd，如 `cd .`、`cd <当前目录绝对路径>`）
// 处置里第 3 条专门推荐 `git -C`：真实事故（2026-07-20，D-001 会话）AI 用
//   (cd /path/to/claude-devkit-marketplace && git push origin main)
// 推一个与当前项目无关的仓库，被 sdlc 插件 hooks/lib/worktree-utils.js 的
// resolveGitCwd() 误拦——它用 /^cd\s+.../ 识别 cd 前缀来判定 git 命令作用于哪个仓库，
// 子 shell 语法带括号、不以 cd 开头，正则匹配不上就 fall back 到当前 worktree，把发往
// 第三方仓库的 push 误判成本项目 delivery 分支的 push。`git -C <path>` 语义等价、不含
// cd token、不进子 shell，能同时躲开本 hook 与这类跨插件误伤。
//
// 【检查二：agent-browser 启动缺 --headed / --profile】
// 缺 --headed 的真实事故（2026-07-20 D-001 verify）：AI 用 headless 起 Chrome for Testing
// 复现前端问题，用户看不到窗口、只看到权限申请弹窗，质疑"你现在是创建了一个 headless 的
// chrome 实例吗？为啥我看还是在向我使用的 chrome 实例进行权限申请呢"。
// 缺 --profile 的代价：AI 默认用一次性临时 profile 目录起 CFT，每次会话都要在浏览器里
// 手动登录一次业务系统。硬要求 --profile 后可复用专门建的 "AI Testing" Chrome profile
// （与用户日常 Default profile 物理隔离，不抢 SingletonLock），登录态跨会话持久。
// 放行：子命令不在启动类集合（skills/doctor/close/snapshot/click/... 等）/ 两个参数都有 /
//       `--headed false` 显式选择 headless / 环境变量前缀 AGENT_BROWSER_HEADED=true 与
//       AGENT_BROWSER_PROFILE=<值> 可分别替代 / `chat` 后没接 URL（纯 REPL 模式）
//
// 【阻塞行为】
// 任一检查命中即 exit 2 阻断，stderr 一次输出全部 findings（stderr 会作为附加上下文注入
// Claude，控制在 400 字符量级——本插件存在的目的就是避免上下文膨胀，拦截文案自己不能违规）：
//   [L1-BLOCKER] tool=Bash check=bash-guard finding="..." hint="..."
//
// Input: JSON on stdin with tool_name / tool_input.command / cwd
// Exit 0 = 放行; Exit 2 = 阻断

'use strict'

const fs = require('fs')
const path = require('path')
const { splitSegments, stripSubshells, tokenize, stripQuotes } = require('../lib/shell-parse')

// ── 检查一：独立 cd ──────────────────────────────────────────────────

// 独立 cd 命令的锚点：行首 / 命令分隔符之后（分隔符 ; && || | 换行）
const CD_PATTERN = /(^|[;&|\n])\s*cd(\s|$)/

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

// 判定 cd 目标是否为 no-op（解析后等于当前 cwd）
function isNoOpCd(target, cwd) {
  if (target === undefined || target === null) return false
  if (target === '') return false // `cd` 单独 → home，非 no-op
  if (target === '.' || target === './' || target === '.\\') return true
  const resolved = path.isAbsolute(target) ? target : path.join(cwd, target)
  return normalizePath(resolved) === normalizePath(cwd)
}

// 返回违规片段字符串，或 null
function checkCd(command, cwd) {
  // 先剥子 shell，剩下的就是会污染父 shell 的部分
  const stripped = stripSubshells(command)
  if (!CD_PATTERN.test(stripped)) return null

  // 只要存在一个会改变 cwd 的 cd 就违规；全是 no-op 则放行
  for (const seg of splitSegments(stripped)) {
    const target = parseCdTarget(seg)
    if (target === undefined) continue
    if (!isNoOpCd(target, cwd)) return seg.trim()
  }
  return null
}

// ── 检查二：agent-browser 启动参数 ───────────────────────────────────

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

// URL 位置参数判定（chat 子命令专用）：形如 scheme://
const URL_PATTERN = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//

// 在某个顶层片段里定位 agent-browser / npx agent-browser 调用，
// 返回该调用之后（同片段内）的 token 数组；未找到返回 null。
function findInvocationTail(segment) {
  const tokens = tokenize(segment).map(stripQuotes)
  for (let i = 0; i < tokens.length; i++) {
    if (tokens[i] === 'agent-browser') return tokens.slice(i + 1)
    if (tokens[i] === 'npx' && tokens[i + 1] === 'agent-browser') return tokens.slice(i + 2)
  }
  return null
}

// 从调用尾部 token 里找子命令：第一个与已知子命令词表精确匹配的 token。
// 不是"第一个非 flag token"——flag 接值（如 `--profile /tmp/foo`）的值本身不在词表里，
// 天然被跳过，避免误判成子命令。
function findSubcommand(tail) {
  for (const t of tail) {
    if (ALL_KNOWN_SUBCOMMANDS.has(t)) return t
  }
  return null
}

// 在调用尾部 token 里找 --profile <值> 或 --profile=<值>；值本身不做路径合法性校验
// （交给 agent-browser CLI），只要求存在一个非空、不是另一个 flag 的值。
function hasProfileFlagInTail(tail) {
  for (let i = 0; i < tail.length; i++) {
    const t = tail[i]
    if (t === '--profile') {
      const next = tail[i + 1]
      return !!(next && !next.startsWith('-'))
    }
    if (t.startsWith('--profile=')) return t.length > '--profile='.length
  }
  return false
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

// 返回 { subcommand, missingHeaded, missingProfile } 或 null
function checkAgentBrowser(command) {
  if (!/\bagent-browser\b/.test(command)) return null

  // 以下判定对整条命令字符串扫描一次即可，各顶层片段共用结果
  const headedOk =
    /\bAGENT_BROWSER_HEADED=true\b/.test(command) ||
    /--headed\s+false\b/.test(command) ||
    /--headed\b/.test(command)
  const profileEnvOk = /\bAGENT_BROWSER_PROFILE=\S/.test(command)

  for (const segment of splitSegments(command)) {
    if (!/\bagent-browser\b/.test(segment)) continue

    const tail = findInvocationTail(segment)
    if (!tail) continue

    const subcommand = findSubcommand(tail)
    if (!subcommand || !LAUNCH_SUBCOMMANDS.has(subcommand)) continue
    if (subcommand === 'chat' && !chatHasUrlArg(tail)) continue // REPL 模式，不拦

    const missingHeaded = !headedOk
    const missingProfile = !(profileEnvOk || hasProfileFlagInTail(tail))
    if (!missingHeaded && !missingProfile) continue

    return { subcommand, missingHeaded, missingProfile }
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
    findings.push(`独立 \`cd\` 会污染后续所有 Bash 调用的 cwd(cwd=${cwd});违规片段：${cdSegment}`)
    hints.push('改用绝对路径,或子 shell `(cd /abs/path && cmd)`,git 命令优先 `git -C <path> <cmd>`')
  }

  const ab = checkAgentBrowser(command)
  if (ab) {
    if (ab.missingHeaded) {
      findings.push(`agent-browser ${ab.subcommand} 缺 --headed;起 headless CFT 会让用户看不到 AI 操作过程`)
      hints.push('加 --headed(确实要 headless 就显式加 --headed false 或前缀 AGENT_BROWSER_HEADED=true)')
    }
    if (ab.missingProfile) {
      findings.push(`agent-browser ${ab.subcommand} 缺 --profile;每次都要重新登录业务系统,无法复用登录态`)
      hints.push('加 --profile <目录>(复用登录态用专门建的 "AI Testing" Chrome profile 目录;纯隔离场景可用 --profile "$(mktemp -d)";或前缀 AGENT_BROWSER_PROFILE=<目录>)')
    }
  }

  if (!findings.length) process.exit(0)

  process.stderr.write(
    `[L1-BLOCKER] tool=Bash check=bash-guard finding="${findings.join(';')}" hint="${hints.join(';')}"\n`
  )
  process.exit(2)
}

main()
