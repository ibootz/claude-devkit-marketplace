// claude-md-max-lines.js — PostToolUse 门控钩子
//
// 【用途】
// CLAUDE.md（含子目录里的同名文件，如多 CLAUDE.md 项目的模块级 CLAUDE.md）
// 超过 200 行时拦截。目的**不是**"文件不许长"，而是"不许靠压缩正文规避长"——
// 命中后应把细节拆到 `.claude/rules/{topic}.md`，claude.md 里用相对路径链接
// 引用，保留完整的因果链 / file:行号 / 边界示例，而不是把 3 段紧凑压成 1 段
// 导致关键约束在压缩中丢失。
//
// 【触发条件】
// - 工具：Write / Edit（写入完成后触发，文件已落盘）
// - 文件 basename 不区分大小写等于 "claude.md"（CLAUDE.md / claude.md / Claude.Md 等）
// - 排除：路径中含 `.claude/rules/` 目录段的文件不受限——拆分后的细节页天然可以长
// - 落盘后总行数（按 `\n` 分割，空文件计 0 行）> LINE_LIMIT（200）
//
// 【放行场景】
// - basename 不是 claude.md（大小写不敏感比对）
// - 路径落在 `.claude/rules/**` 下
// - 行数 <= 200
// - file_path 缺失、文件读取失败——静默放行，不因基础设施异常误拦
//
// 【阻塞行为】
// 命中即 exit 2 阻断，stderr 输出（含"往哪拆"的 hint，而非只报数字）：
//   [L1-BLOCKER] file={相对路径} check=claude-md-max-lines finding="{N} lines exceeds limit 200" hint="拆到 .claude/rules/{topic}.md 用相对链接引用,禁止压缩正文导致约束丢失"
//
// Input: JSON on stdin with tool_name / tool_input.file_path / cwd
// Exit 0 = 放行; Exit 2 = 阻断

'use strict'

const fs = require('fs')
const path = require('path')

const LINE_LIMIT = 200

// 排除目录段：`.claude/rules/` 下的 md 文件不受此规则约束
const EXCLUDED_SEGMENT_PATTERN = /(^|\/)\.claude\/rules\//

// 按 `\n` 字面分割计数；空文件（content === ''）显式计 0 行，
// 避免 ''.split('\n') 天然返回长度 1 的数组造成误判。
function countLines(content) {
  if (content === '') return 0
  return content.split('\n').length
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

  const toolName = payload.tool_name
  if (toolName !== 'Write' && toolName !== 'Edit') process.exit(0)

  const filePath = payload.tool_input && payload.tool_input.file_path
  if (!filePath) process.exit(0)

  const basename = path.basename(filePath).toLowerCase()
  if (basename !== 'claude.md') process.exit(0)

  // 路径统一转 posix 风格（正斜杠）后再判断排除段，兼容 win32 反斜杠路径
  const posixPath = filePath.split(path.sep).join('/')
  if (EXCLUDED_SEGMENT_PATTERN.test(posixPath)) process.exit(0)

  let content
  try {
    content = fs.readFileSync(filePath, 'utf8')
  } catch (_) {
    // 文件读取失败（竞态删除等基础设施异常）不误拦
    process.exit(0)
  }

  const lineCount = countLines(content)
  if (lineCount <= LINE_LIMIT) process.exit(0)

  const cwd = payload.cwd || process.cwd()
  const relPath = path.relative(cwd, filePath) || filePath

  const msg =
    `[L1-BLOCKER] file=${relPath} check=claude-md-max-lines finding="${lineCount} lines exceeds limit ${LINE_LIMIT}" ` +
    `hint="拆到 .claude/rules/{topic}.md 用相对链接引用,禁止压缩正文导致约束丢失"`

  process.stderr.write(msg + '\n')
  process.exit(2)
}

main()
