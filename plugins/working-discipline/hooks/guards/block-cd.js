// block-cd.js — PreToolUse 门控钩子
//
// 【用途】
// 阻断会污染会话 cwd 的独立 `cd` 命令。Bash 工具的 cwd 在
// 多次调用之间持久保留，AI 一旦在中间执行 `cd /tmp`，后续
// 所有相对路径操作都会失准（"为什么找不到 requirements/foo"
// 这类诡异现象的根因）。
//
// 【触发条件】
// - 工具：Bash
// - 命令字符串中存在独立 `cd` 命令（不在子 shell 内）
//
// 【放行场景】
// - `(cd /path && cmd)`        子 shell，cwd 不回流父进程
// - `$(cd /path && pwd)`       命令替换，同子 shell
// - `` `cd /path && pwd` ``   反引号命令替换，同子 shell
// - 字符串内的 cd（如 `echo "cd /tmp"`、`git commit -m "..."`）
// - **no-op cd**：目标解析后等于当前 cwd（例如 `cd .`、
//   `cd ./`，或 `cd <绝对路径到当前目录>`）。常见于 AI
//   不确定项目根目录时下意识地"再 cd 一下"，但目标其实
//   就是当前目录，对 cwd 无任何影响。
//
// 【阻塞行为】
// 命令链中存在任意一个会改变 cwd 的 cd 时 exit 2 阻断，stderr 给出三条处置
// （绝对路径 / 子 shell / git 用 `git -C`）+ 违规片段回显，**控制在 300 字符内**。
//
// 【为什么 stderr 必须短】（2026-07-26 精简，原文约 1500 字符）
// stderr 会作为附加上下文注入 Claude，每次拦截都灌进 1500 字符，本身就构成上下文膨胀
// 与注意力抢占——本插件存在的目的正是避免这件事。详细背景挪到下面的注释里给维护者读，
// 不再进 AI 的上下文。
//
// 【背景：为什么第 3 条处置要专门推荐 `git -C`】
// 真实事故（2026-07-20，D-001-feat-job-sequence-model 会话）：AI 用
//   (cd /path/to/claude-devkit-marketplace && git push origin main)
// 推送一个与当前项目完全无关的第三方仓库，却被 sdlc 插件的
// `hooks/lib/worktree-utils.js` 里 `resolveGitCwd()` 误拦，报
// 「BLOCKED: ontology 正向同步未收口 for D-001-feat-job-sequence-model」。
// 根因：`resolveGitCwd()` 用正则 `/^cd\s+.../` 识别 `cd` 前缀来判定一条 git 命令实际
// 作用于哪个仓库；子 shell 语法 `(cd /path && cmd)` 带括号、不以 `cd` 开头，那个正则
// 匹配不上，于是它 fall back 到当前会话所在的 worktree cwd，把发往无关第三方仓库的
// push 误判成当前项目 delivery 分支的 push，触发了不相关的门禁拦截。
// `git -C <path> <cmd>` 是 git 官方支持的全局选项，语义等价但不含 `cd` token、不进
// 子 shell，各类插件的 cwd 探测正则通常会显式支持 `-C`，能同时躲开本 hook 与此类
// 跨插件误伤。
//
// Input: JSON on stdin with tool_input.command 和 cwd
// Exit 0 = 放行; Exit 2 = 阻断

'use strict'

const fs = require('fs')
const path = require('path')
const { splitSegments, stripSubshells } = require('../lib/shell-parse')

// 独立 cd 命令的锚点：行首 / 命令分隔符之后
// 分隔符: ; && || | 换行
const CD_PATTERN = /(^|[;&|\n])\s*cd(\s|$)/

// 如果 segment 是 cd 命令，返回其目标字符串（去引号）；
// 否则返回 undefined。`cd` 不带参数时返回空串（代表 home）。
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

// 判定 cd 目标是否为 no-op（解析后等于当前 cwd）。
function isNoOpCd(target, cwd) {
  if (target === undefined || target === null) return false
  if (target === '') return false // `cd` 单独 → home，非 no-op
  if (target === '.' || target === './' || target === '.\\') return true
  const resolved = path.isAbsolute(target) ? target : path.join(cwd, target)
  return normalizePath(resolved) === normalizePath(cwd)
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

  const command = (payload.tool_input && payload.tool_input.command) || ''
  if (!command) process.exit(0)
  const cwd = payload.cwd || process.cwd()

  // 先剥子 shell，剩下的就是会污染父 shell 的部分
  const stripped = stripSubshells(command)

  if (!CD_PATTERN.test(stripped)) process.exit(0)

  // 切分顶层片段，逐个判断 cd。只要存在一个会改变 cwd 的 cd，就阻断；
  // 全部都是 no-op（目标解析后等于 cwd）则放行。
  const segments = splitSegments(stripped)
  let blockingSegment = null
  for (const seg of segments) {
    const target = parseCdTarget(seg)
    if (target === undefined) continue
    if (!isNoOpCd(target, cwd)) {
      blockingSegment = seg.trim()
      break
    }
  }

  if (!blockingSegment) process.exit(0)

  // stderr 会注入 Claude 上下文，控制在 300 字符内；详细背景见文件头注释
  const msg = [
    'BLOCK-CD: 独立 `cd` 会污染后续所有 Bash 调用的 cwd。三种改法：',
    '  1. 直接用绝对路径，不切目录',
    '  2. 必须切目录时用子 shell：`(cd /abs/path && cmd)`',
    '  3. git 命令优先 `git -C <path> <cmd>`（避免被其他插件的 cwd 探测正则误判）',
    `cwd=${cwd}  违规片段：${blockingSegment}`,
  ]

  process.stderr.write(msg.join('\n') + '\n')
  process.exit(2)
}

main()
