// write-guard.js — PostToolUse 事后提醒钩子（matcher: Write|Edit）
//
// 【用途】
// 针对 Write / Edit 这一个对象的**唯一** hook。3.0.0 起本插件按拦截对象收敛挂载拓扑：
// Agent → agent-dispatch.js，Bash → bash-guard.js，Write|Edit → 本文件。
//
// 本文件是 max-source-lines.js 与 claude-md-max-lines.js 合并的产物——两者原本各自挂
// PostToolUse(Write|Edit)、各自读一遍 stdin、各自 readFileSync 同一个文件。合并后
// 只读一次盘、只起一个进程。
//
// 【它不是拦截器，是事后提醒——2026-07-31 审计实测确认】
// 本 hook 挂在 **PostToolUse**，触发时文件**已经落盘**：第 149 行 readFileSync 读到的
// 就是写入后的内容（finding 里报的行数本身即证据）。三条实测证据：
//   1. 本文件全文只有两处 readFileSync（读 stdin、读目标文件），无任何 fs 写操作，
//      不做也无法做回滚。审计连续 6 次拦同一个 12436 行文件后复核 md5 与 mtime 未变。
//   2. Claude Code 2.1.220 二进制明文：`On PostToolUse, the reason is fed back to
//      Claude and the turn continues.`
//   3. 真能停住回合的是 JSON 顶层 `continue: false`（配 stopReason），而本文件走
//      stderr.write + exit(2)，不输出 JSON。
// 净效果：超长文件已在盘上，本 hook 只是把一句话喂给 Claude，**这一轮继续往下走**。
// 因此任何「会被拦下所以不用担心写出超长文件」的表述都是错的——注入纪律里的对应
// 措辞已在 3.6.0 一并改正。
//
// 【判据是扩展名/basename + 路径段 + 纯行数计数，覆盖边界如下】
// 3.6.0 前本注释写着「误判空间为零」。审计用真实文件跑真 guard 证伪了这句：扩展名
// 不能区分源码与数据/产物/依赖，行数计数带 +1 偏移，basename 不能区分本项目与第三方。
// 三类误判已按下面的方式收窄，但**没有归零**——留下的已知边界写在各检查项里。
//
// 【检查一：单一源码文件 > 1000 行】
// 行数超硬阈值是职责过大的信号，提示拆分模块。只管"文件行数"这一维度，不做语法/风格检查。
// 放行：扩展名不在 SOURCE_EXTENSIONS / 路径命中依赖·产物·生成物模式 / 行数 <= 1000
// 3.6.0 收窄（审计实证，均为真实 BLOCK）：
//   - `.sql` 与 `.css/.scss/.sass/.less` **移出**源码集合。3539 行的全库建表 DDL 被判
//     「按职责拆分模块」毫无意义，拆成 4 个文件只会破坏可执行性；vendored 的
//     animate.css（4073 行）同理。行数与"职责过大"在这类文件上不成立。
//   - 新增 GENERATED_PATH_PATTERN / GENERATED_NAME_PATTERN：node_modules 里的第三方
//     依赖、dist/target/build 里的构建产物、.min./.generated. 文件不再受约束。
//     审计实测被误拦的真实样本：node_modules/animate.css/animate.css、
//     target/classes/db/schema.mysql.sql、dist/hooks/bridge.js（2511 行打包产物）。
//   - 补齐扩展名黑洞：`.mjs/.cjs/.sh` 等原本**不在**集合里，1710 行的
//     keyword-detector.mjs 与 2657 行的 setup.sh 实测全部放行——"AI 把 3000 行堆进
//     一个文件"换个扩展名就完全不受约束，方向刚好反了。
// 已知未覆盖：手写的超长样式表与 SQL 不再有任何约束（换取上面那批误判归零）；
//   .ipynb / .tf / .json 等按行数衡量无意义的类型仍不纳入。
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
// 3.6.0 收窄（审计实证）：**必须落在当前项目树内**（path.relative(cwd, filePath)
//   不以 `..` 开头）。这条约束的依据是"该文件常驻当前会话上下文、吃上下文预算"，
//   而那取决于它在不在当前 cwd 树里。审计实测被误拦的真实样本：
//   ~/.claude/plugins/marketplaces/context-engineering-kit/CLAUDE.md（257 行）与
//   .../xxstar-prod-ai/CLAUDE.md（217 行）——改插件市场缓存里别人的 CLAUDE.md 时
//   被按本项目预算拦下。
//   同时把 `.claude/rules/` 排除**从"路径任意位置包含"改为"项目内相对路径以此开头"**。
//   旧实现 /(^|\/)\.claude\/rules\// 是个绕过点，审计实测：
//     BLOCK | <别处>/ccg-workflow/CLAUDE.md                                （686 行）
//     PASS  | <本仓>/.claude/rules/../../../../<别处>/ccg-workflow/CLAUDE.md（同一文件）
//     BLOCK | <本仓>/docs/research/../../../../<别处>/ccg-workflow/CLAUDE.md（对照组）
//   对照组证明放行是那个路径段导致的、不是 `..` 导致的。改用 path.relative 归一化后
//   判断，`..` 爬出项目的场景先被"项目树内"检查挡掉，绕过点随之消失。
// 放行：basename 不是 claude.md / 不在当前项目树内 / 项目内路径以 `.claude/rules/`
//       开头 / 路径命中依赖·产物模式 / 行数 <= 200
//
// 【行数计数：3.6.0 修掉 +1 偏移】
// 旧实现 content.split('\n').length 在文件以换行结尾时（POSIX 文本文件常态）多算
// 一行。审计两组实测：wc -l 得 12436、guard 报 12437；wc -l 得 685、guard 报 686；
// tail -c 1 | xxd 确认结尾是 0a。后果是阈值文案与实际行为差一——正好 1000 行且以
// 换行结尾的文件被算成 1001 行拦下，而 finding 告诉 Claude 的是「limit 1000」，
// 按 1000 行去卡会反复撞闸。现在末尾换行不再产生额外空行。
//
// 【两条检查为什么互斥但仍合并】
// 一个文件不可能同时是 .md 和源码扩展名，所以实际只会命中一条。合并的收益不在"一次报
// 两条"，而在消除一次进程启动 + 一次重复的 readFileSync——PostToolUse 每次写文件都触发，
// 这是热路径。
//
// 【阻塞行为】
// 命中即 exit 2，stderr 输出：
//   [L1-BLOCKER] file={相对路径} check=write-guard finding="..." hint="..."
// 如上「它不是拦截器」一节所述：文件已经写完，这次写入不会回滚、这一轮也不会停，
// stderr 只是作为附加上下文喂给 Claude。Claude 看到提示后应当拆分 / 精简，而不是
// 无视继续在同一文件里堆内容。
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

// 小写比对。严禁包含 .md/.json/.yaml/.yml/.toml/.env/.lock 等非源码扩展名，
// 也不含 .sql 与样式表——它们的行数与"职责过大"无关（见文件头【检查一】收窄说明）。
const SOURCE_EXTENSIONS = new Set([
  '.java', '.kt', '.kts', '.scala', '.groovy', '.gradle',
  '.js', '.mjs', '.cjs', '.ts', '.mts', '.cts', '.jsx', '.tsx',
  '.vue', '.svelte', '.astro',
  '.py', '.go', '.rs', '.rb', '.php', '.pl', '.lua', '.dart',
  '.cpp', '.cc', '.cxx', '.c', '.h', '.hpp',
  '.cs', '.swift', '.m', '.mm',
  '.hs', '.ex', '.exs', '.erl', '.clj', '.cljs',
  '.sh', '.bash', '.zsh',
])

// 依赖 / 构建产物 / 虚拟环境目录：这些文件不是"我们在写的源码"，行数约束无意义。
// 以 posix 风格相对或绝对路径匹配，任一路径段命中即放行。
const GENERATED_PATH_PATTERN =
  /(^|\/)(node_modules|bower_components|vendor|third_party|Pods|dist|build|target|out|\.next|\.nuxt|\.output|coverage|__pycache__|\.venv|venv|site-packages)\//

// 生成物命名约定：foo.min.js / foo.generated.ts / foo.g.dart / foo.bundle.js / foo_pb2.py
const GENERATED_NAME_PATTERN = /(\.min\.|\.generated\.|\.g\.|\.bundle\.|_pb2?\.|\.pb\.)/

// `.claude/rules/` 下的 md 不受 CLAUDE.md 行数约束（拆分后的细节页天然可以长）。
// 只匹配**项目内相对路径的开头**——不是"路径任意位置包含"，后者是绕过点（见文件头）。
const RULES_DIR_PREFIX = '.claude/rules/'

// 按 `\n` 字面分割计数，末尾换行不产生额外空行（见文件头【行数计数】）。
// 空文件（content === ''）显式计 0 行，避免 ''.split('\n') 天然返回长度 1 造成误判。
function countLines(content) {
  if (content === '') return 0
  const body = content.endsWith('\n') ? content.slice(0, -1) : content
  return body.split('\n').length
}

// 转 posix 风格（正斜杠），兼容 win32 反斜杠路径
function toPosix(p) {
  return p.split(path.sep).join('/')
}

// 返回文件在当前项目树内的 posix 相对路径；不在项目树内返回 null。
// path.relative 会先归一化，因此 `<repo>/.claude/rules/../../../x` 这类爬出去的路径
// 会得到以 `..` 开头的结果，被判为项目外。
function projectRelative(filePath, cwd) {
  let rel
  try {
    rel = path.relative(cwd, filePath)
  } catch (_) {
    return null
  }
  if (rel === '') return null // filePath 就是 cwd 本身，不可能是文件
  if (rel.startsWith('..')) return null
  if (path.isAbsolute(rel)) return null // win32 跨盘符
  return toPosix(rel)
}

function isGenerated(posixPath, basename) {
  return GENERATED_PATH_PATTERN.test(posixPath) || GENERATED_NAME_PATTERN.test(basename)
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
  const posixPath = toPosix(filePath)
  const cwd = payload.cwd || process.cwd()

  // 依赖 / 产物 / 生成物：两条检查都不适用
  if (isGenerated(posixPath, basename)) process.exit(0)

  const isSource = SOURCE_EXTENSIONS.has(ext)

  // CLAUDE.md 检查要求文件落在当前项目树内，且不在 .claude/rules/ 下
  let isClaudeMd = false
  if (basename === 'claude.md') {
    const rel = projectRelative(filePath, cwd)
    isClaudeMd = rel !== null && !rel.startsWith(RULES_DIR_PREFIX)
  }

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
