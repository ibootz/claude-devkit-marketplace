// max-source-lines.js — PostToolUse 门控钩子
//
// 【用途】
// 单一源码文件行数超过硬阈值（职责过大信号）时拦截，提示拆分模块。
// 只管"文件行数"这一维度，不做语法/风格检查。
//
// 【触发条件】
// - 工具：Write / Edit（写入完成后触发，文件已落盘）
// - 被写入/编辑文件的扩展名属于源码列表（见 SOURCE_EXTENSIONS）
// - 落盘后总行数（按 `\n` 分割，空文件计 0 行）> LINE_LIMIT（1000）
//
// 【放行场景】
// - 扩展名不在源码列表（.md/.json/.yaml/.yml/.toml/.env/.lock 等非源码文件不管）
// - 行数 <= 1000
// - file_path 缺失、文件读取失败（如竞态被删除）——静默放行，不因基础设施异常误拦
//
// 【阻塞行为】
// 命中即 exit 2 阻断，stderr 输出：
//   [L1-BLOCKER] file={相对路径} check=source-max-lines finding="{N} lines exceeds limit 1000"
// 这是 PostToolUse 钩子：文件已经写完，阻断的是"继续往下走"而非这次写入本身——
// Claude 看到此提示后应当拆分模块 / 精简该文件，而不是无视继续在同一文件里堆代码。
//
// Input: JSON on stdin with tool_name / tool_input.file_path / cwd
// Exit 0 = 放行; Exit 2 = 阻断

'use strict'

const fs = require('fs')
const path = require('path')

const LINE_LIMIT = 1000

// 小写比对，严禁包含 .md/.json/.yaml/.yml/.toml/.env/.lock 等非源码扩展名
const SOURCE_EXTENSIONS = new Set([
  '.java', '.js', '.ts', '.jsx', '.tsx', '.vue',
  '.py', '.go', '.rs', '.rb', '.php',
  '.cpp', '.cc', '.cxx', '.c', '.h', '.hpp',
  '.cs', '.kt', '.swift', '.m', '.mm',
  '.css', '.scss', '.sass', '.less',
  '.sql',
])

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

  const ext = path.extname(filePath).toLowerCase()
  if (!SOURCE_EXTENSIONS.has(ext)) process.exit(0)

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

  const msg = `[L1-BLOCKER] file=${relPath} check=source-max-lines finding="${lineCount} lines exceeds limit ${LINE_LIMIT}"`

  process.stderr.write(msg + '\n')
  process.exit(2)
}

main()
