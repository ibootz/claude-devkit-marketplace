// agent-browser-launch.js — PreToolUse 门控钩子
// （原名 agent-browser-headed.js；2026-07-20 起改名，因本 hook 现在同时管
//  --headed 与 --profile 两个启动参数，旧名字只提"headed"会让后来维护者
//  误以为 --profile 的拦截逻辑在别处）
//
// 【用途】
// AI 会话用 agent-browser 起 Chrome for Testing（CFT）实例时，默认走
// headless 模式——用户视角看不到 AI 点了哪个按钮、填了什么表单、跳到
// 了哪个 URL、遇到了什么弹窗，全是黑箱。真实事故：2026-07-20 D-001
// verify 期间 AI 用 headless 起 CFT 复现前端问题，用户看不到窗口质疑
// "你现在是创建了一个 headless 的 chrome 浏览器实例吗？为啥我看还是
// 在向我使用的 chrome 实例进行权限申请呢"，才发现 --headed 应是硬要求。
//
// 同一会话还暴露了第二个问题：AI 默认用一次性临时 profile 目录
// （如 /tmp/ab-xxx-profile）起 CFT，每次会话都要在浏览器里手动登录一次
// 业务系统（拿 token 注入 URL），浪费大量时间。用户拍板方案：硬要求
// --profile（或 AGENT_BROWSER_PROFILE 环境变量），引导 AI 复用一个专门
// 建立的 "AI Testing" Chrome profile（用户在日常 Chrome 里一次性创建
// 并登录业务系统，profile 目录与用户日常用的 Default profile 物理隔离，
// 不会被 CFT 抢 SingletonLock），登录态跨会话持久化；纯隔离测试场景
// 仍可用 --profile "$(mktemp -d)" 之类的独立临时目录满足硬性要求。
//
// 本 hook 拦住缺 --headed 或缺 --profile 的启动类命令，逼 AI 起可见、
// 登录态可复用的独立 CFT 窗口。
//
// 【触发条件】（需同时满足）
// - 工具：Bash，命令含 `agent-browser` 或 `npx agent-browser`
// - 紧跟其后的子命令属于启动类子命令（见 LAUNCH_SUBCOMMANDS）；
//   `chat` 仅当接了 URL 位置参数才算启动，纯 REPL 模式不拦
// - 以下两条任一命中就拦截：
//   1. 命令整串缺 `--headed`（含 `--headed false` 视为显式选择 headless，放行）
//      且不含 `AGENT_BROWSER_HEADED=true` 环境变量前缀
//   2. 该 agent-browser 调用缺 `--profile <值>`（或 `--profile=<值>`）
//      且不含 `AGENT_BROWSER_PROFILE=<值>` 环境变量前缀
//
// 【子命令识别】
// 找到 agent-browser（或 npx agent-browser）token 后，在同一顶层命令
// 片段（按 ; && || | 换行切分，引号内不切）内向后扫描，取第一个与已知
// 子命令词表（启动类 ∪ 白名单）精确匹配的 token 作为子命令——不是简单
// "第一个非 flag token"：`--profile /tmp/foo` 这类"flag 接一个值"的写法，
// 值本身（`/tmp/foo`）不在词表里会被自然跳过，避免误判成子命令。
//
// 【放行场景】
// - 子命令不在启动类集合（只读探测 skills/doctor/install/upgrade、
//   生命周期无关 close/mcp/dashboard/session/plugin/auth/profiles/
//   confirm/deny、后续操作类 snapshot/click/fill/... 等）
// - 命令含 --headed（且非 `--headed false`）AND 命令含 --profile <值>
// - 命令含 `--headed false`（显式选择 headless）AND 命令含 --profile <值>
// - 命令含 `AGENT_BROWSER_HEADED=true` 可替代 --headed；
//   命令含 `AGENT_BROWSER_PROFILE=<值>` 可替代 --profile
// - `chat` 子命令后没有 URL 位置参数（REPL 模式）——两条检查都跳过
//
// 【阻塞行为】
// 命中即 exit 2 阻断，stderr 输出（示例，同时缺两项时 finding/hint 会
// 各自列出两条问题）：
//   [L1-BLOCKER] tool=Bash check=agent-browser-launch
//     finding="agent-browser {子命令} 缺 --headed;起 headless CFT 会让用户看不到 AI 操作过程"
//     hint="加 --headed 起可见独立 CFT 窗口...;示例:agent-browser --headed --profile \"...\" {子命令} <args>"
//
// Input: JSON on stdin with tool_name / tool_input.command
// Exit 0 = 放行; Exit 2 = 阻断

'use strict'

const fs = require('fs')

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

// 顶层片段切分（; && || | 换行为分隔符，引号内的分隔符不参与切分），
// 与 block-cd.js 的 splitSegments 同思路，避免跨命令误判子命令归属。
function splitSegments(cmd) {
  const segments = []
  let cur = ''
  let inDouble = false
  let inSingle = false
  for (let i = 0; i < cmd.length; i++) {
    const c = cmd[i]
    const prev = cmd[i - 1]
    if (!inSingle && c === '"' && prev !== '\\') {
      inDouble = !inDouble
      cur += c
      continue
    }
    if (!inDouble && c === "'") {
      inSingle = !inSingle
      cur += c
      continue
    }
    if (!inDouble && !inSingle) {
      if (c === '\n' || c === ';') {
        segments.push(cur)
        cur = ''
        continue
      }
      if (c === '&' && cmd[i + 1] === '&') {
        segments.push(cur)
        cur = ''
        i++
        continue
      }
      if (c === '|' && cmd[i + 1] === '|') {
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
    }
    cur += c
  }
  if (cur.trim()) segments.push(cur)
  return segments
}

// 按空白切分 token，引号内的空白不切（保留引号字符本身，交给 stripQuotes 处理）
function tokenize(segment) {
  const tokens = []
  let cur = ''
  let inDouble = false
  let inSingle = false
  for (let i = 0; i < segment.length; i++) {
    const c = segment[i]
    if (!inSingle && c === '"') {
      inDouble = !inDouble
      cur += c
      continue
    }
    if (!inDouble && c === "'") {
      inSingle = !inSingle
      cur += c
      continue
    }
    if (!inDouble && !inSingle && /\s/.test(c)) {
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

function stripQuotes(token) {
  if ((token.startsWith('"') && token.endsWith('"')) || (token.startsWith("'") && token.endsWith("'"))) {
    return token.slice(1, -1)
  }
  return token
}

// 在某个顶层片段里定位 agent-browser / npx agent-browser 调用，
// 返回该调用之后（同片段内）的 token 数组；未找到返回 null。
function findInvocationTail(segment) {
  const tokens = tokenize(segment).map(stripQuotes)
  for (let i = 0; i < tokens.length; i++) {
    if (tokens[i] === 'agent-browser') {
      return tokens.slice(i + 1)
    }
    if (tokens[i] === 'npx' && tokens[i + 1] === 'agent-browser') {
      return tokens.slice(i + 2)
    }
  }
  return null
}

// 从调用尾部 token 里找子命令：第一个与已知子命令词表（启动类 ∪ 白名单）
// 精确匹配的 token。不是"第一个非 flag token"——flag 接值（如
// `--profile /tmp/foo`）的值本身不在词表里，天然被跳过，避免误判。
function findSubcommand(tail) {
  for (const t of tail) {
    if (ALL_KNOWN_SUBCOMMANDS.has(t)) return t
  }
  return null
}

function hasHeadedEnv(command) {
  return /\bAGENT_BROWSER_HEADED=true\b/.test(command)
}

function isExplicitHeadlessFlag(command) {
  return /--headed\s+false\b/.test(command)
}

function hasHeadedFlag(command) {
  return /--headed\b/.test(command)
}

// AGENT_BROWSER_PROFILE=<非空值> 环境变量前缀
function hasProfileEnv(command) {
  return /\bAGENT_BROWSER_PROFILE=\S/.test(command)
}

// 在调用尾部 token 里找 --profile <值> 或 --profile=<值>；
// 值本身不做路径合法性校验（交给 agent-browser CLI 自己校验），
// 只要求存在一个非空、不是另一个 flag 的值。
function hasProfileFlagInTail(tail) {
  for (let i = 0; i < tail.length; i++) {
    const t = tail[i]
    if (t === '--profile') {
      const next = tail[i + 1]
      return !!(next && !next.startsWith('-'))
    }
    if (t.startsWith('--profile=')) {
      return t.length > '--profile='.length
    }
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
  if (!/\bagent-browser\b/.test(command)) process.exit(0)

  // 以下判定对整条命令字符串扫描一次即可，各顶层片段共用结果
  const headedOk = hasHeadedEnv(command) || isExplicitHeadlessFlag(command) || hasHeadedFlag(command)
  const profileEnvOk = hasProfileEnv(command)

  const segments = splitSegments(command)

  for (const segment of segments) {
    if (!/\bagent-browser\b/.test(segment)) continue

    const tail = findInvocationTail(segment)
    if (!tail) continue

    const subcommand = findSubcommand(tail)
    if (!subcommand || !LAUNCH_SUBCOMMANDS.has(subcommand)) continue

    if (subcommand === 'chat' && !chatHasUrlArg(tail)) continue // REPL 模式，不拦

    const missingHeaded = !headedOk
    const missingProfile = !(profileEnvOk || hasProfileFlagInTail(tail))

    if (!missingHeaded && !missingProfile) continue

    const findings = []
    const hints = []
    if (missingHeaded) {
      findings.push('缺 --headed;起 headless CFT 会让用户看不到 AI 操作过程')
      hints.push('加 --headed 起可见独立 CFT 窗口(若确实要 headless 显式加 --headed false 或前缀 AGENT_BROWSER_HEADED=true)')
    }
    if (missingProfile) {
      findings.push('缺 --profile;不设置 profile 每次都要在浏览器里重新登录业务系统,无法复用登录态')
      hints.push('加 --profile <目录>(复用登录态用专门建的"AI Testing" Chrome profile 目录,纯隔离测试场景可用 --profile "$(mktemp -d)" 独立临时目录满足硬性要求;或前缀 AGENT_BROWSER_PROFILE=<目录>)')
    }

    const msg = `[L1-BLOCKER] tool=Bash check=agent-browser-launch finding="agent-browser ${subcommand} ${findings.join(';')}" hint="${hints.join(';')};示例:agent-browser --headed --profile \\"/Users/<user>/Library/Application Support/Google/Chrome/Profile 1\\" ${subcommand} <args>"`
    process.stderr.write(msg + '\n')
    process.exit(2)
  }

  process.exit(0)
}

main()
