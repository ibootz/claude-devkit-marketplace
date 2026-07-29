// write-guard.js — PostToolUse 门控钩子（matcher: Write|Edit）
//
// 【用途】
// 针对 Write / Edit 这一个对象的**唯一** hook。3.0.0 起本插件按拦截对象收敛挂载拓扑：
// Agent → agent-dispatch.js，Bash → bash-guard.js，Write|Edit → 本文件。
//
// 本文件是 max-source-lines.js 与 claude-md-max-lines.js 合并的产物——两者原本各自挂
// PostToolUse(Write|Edit)、各自读一遍 stdin、各自 readFileSync 同一个文件。合并后
// 只读一次盘、只起一个进程。
//
// 【判据是纯行数计数，不含任何关键词匹配】
// 3.0.0 删掉了本插件所有靠关键词猜语义的 guard（md-audience-declaration 回读 transcript
// 找声明句、external-write-readback 扫命令里的写操作词表）。本文件两条检查都是
// 「取 file_path → 判扩展名/basename → 数行数 → 比阈值」，误判空间为零。
//
// 【检查一：单一源码文件 > 1000 行】
// 行数超硬阈值是职责过大的信号，提示拆分模块。只管"文件行数"这一维度，不做语法/风格检查。
// 放行：扩展名不在源码列表（.md/.json/.yaml/.toml/.lock 等非源码文件不管）/ 行数 <= 1000
//
// 【检查二：CLAUDE.md > 200 行】
// 目的**不是**"文件不许长"，而是"不许靠压缩正文规避长"——命中后应把细节拆到
// `.claude/rules/{topic}.md`，保留完整的因果链 / file:行号 / 边界示例，而不是把
// 3 段紧凑压成 1 段导致关键约束在压缩中丢失。
//
// 拆过去的文件**不需要**在 CLAUDE.md 里引用——`.claude/rules/**` 由 Claude Code
// 自动加载。实证（2.1.220 二进制）：加载调用是
// `ZPt({rulesDir: <cwd>/.claude/rules, type:"Project", conditionalRule})`，与
// CLAUDE.md 自身的加载函数 `Lpe()` 并列挂在同一条 memory 装配链上；用户级
// `~/.claude/rules/` 同理（`gfo(){return join(fn(),"rules")}`）。内置 `/init`
// 指令的原文也写明「These are loaded automatically alongside CLAUDE.md and can be
// scoped to specific file paths using `paths` frontmatter」。
// 因此 3.1.0 起本 hint 不再要求"用相对链接引用"：那句话基于「不引用就读不到」的
// 错误前提，冗余之外还有实害——AI 读到"引用"会倾向改用 Claude Code 真正的 import
// 语法 `@.claude/rules/x.md`，那会让同一份内容被「目录自动加载 + import」注入两次
// （官方未声明 import 与目录加载之间会去重）。
// 真正值得写进 hint 的是拆分带来的额外能力：rules 文件可用 `paths` frontmatter
// 限定只在改动匹配路径时才加载，比无条件常驻的 CLAUDE.md 更省上下文。
// 命中文件：basename 不区分大小写等于 claude.md（CLAUDE.md / claude.md / Claude.Md），
//           且不限于仓库根——多 CLAUDE.md 项目里子目录下的同名文件同样受约束
// 放行：basename 不是 claude.md / 路径落在 `.claude/rules/**` 下（拆分后的细节页天然可以长）
//       / 行数 <= 200
//
// 【两条检查为什么互斥但仍合并】
// 一个文件不可能同时是 .md 和源码扩展名，所以实际只会命中一条。合并的收益不在"一次报
// 两条"，而在消除一次进程启动 + 一次重复的 readFileSync——PostToolUse 每次写文件都触发，
// 这是热路径。
//
// 【阻塞行为】
// 命中即 exit 2 阻断，stderr 输出：
//   [L1-BLOCKER] file={相对路径} check=write-guard finding="..." hint="..."
// 这是 PostToolUse 钩子：文件已经写完，阻断的是"继续往下走"而非这次写入本身——
// Claude 看到提示后应当拆分 / 精简，而不是无视继续在同一文件里堆内容。
//
// 【放行场景（两条检查共用）】
// - tool_name 不是 Write / Edit
// - file_path 缺失、文件读取失败（如竞态被删除）—— 基础设施异常不误拦
//
// Input: JSON on stdin with tool_name / tool_input.file_path / cwd
// Exit 0 = 放行; Exit 2 = 阻断

'use strict'

const fs = require('fs')
const path = require('path')

const SOURCE_LINE_LIMIT = 1000
const CLAUDE_MD_LINE_LIMIT = 200

// 小写比对，严禁包含 .md/.json/.yaml/.yml/.toml/.env/.lock 等非源码扩展名
const SOURCE_EXTENSIONS = new Set([
  '.java', '.js', '.ts', '.jsx', '.tsx', '.vue',
  '.py', '.go', '.rs', '.rb', '.php',
  '.cpp', '.cc', '.cxx', '.c', '.h', '.hpp',
  '.cs', '.kt', '.swift', '.m', '.mm',
  '.css', '.scss', '.sass', '.less',
  '.sql',
])

// 排除目录段：`.claude/rules/` 下的 md 文件不受 CLAUDE.md 行数约束
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

  const ext = path.extname(filePath).toLowerCase()
  const basename = path.basename(filePath).toLowerCase()
  // 路径统一转 posix 风格（正斜杠）后再判断排除段，兼容 win32 反斜杠路径
  const posixPath = filePath.split(path.sep).join('/')

  const isSource = SOURCE_EXTENSIONS.has(ext)
  const isClaudeMd = basename === 'claude.md' && !EXCLUDED_SEGMENT_PATTERN.test(posixPath)

  // 两条检查都不适用时提前退出，不读盘
  if (!isSource && !isClaudeMd) process.exit(0)

  let content
  try {
    content = fs.readFileSync(filePath, 'utf8')
  } catch (_) {
    // 文件读取失败（竞态删除等基础设施异常）不误拦
    process.exit(0)
  }

  const lineCount = countLines(content)
  const cwd = payload.cwd || process.cwd()
  const relPath = path.relative(cwd, filePath) || filePath

  if (isSource && lineCount > SOURCE_LINE_LIMIT) {
    process.stderr.write(
      `[L1-BLOCKER] file=${relPath} check=write-guard ` +
        `finding="${lineCount} lines exceeds source limit ${SOURCE_LINE_LIMIT}" ` +
        `hint="按职责拆分模块,不要继续在同一文件堆代码"\n`
    )
    process.exit(2)
  }

  if (isClaudeMd && lineCount > CLAUDE_MD_LINE_LIMIT) {
    process.stderr.write(
      `[L1-BLOCKER] file=${relPath} check=write-guard ` +
        `finding="${lineCount} lines exceeds CLAUDE.md limit ${CLAUDE_MD_LINE_LIMIT}" ` +
        `hint="拆到 .claude/rules/{topic}.md(自动加载,不要在 CLAUDE.md 里 @import 或加链接引用;` +
        `可用 paths frontmatter 限定生效路径),禁止压缩正文导致约束丢失"\n`
    )
    process.exit(2)
  }

  process.exit(0)
}

main()
