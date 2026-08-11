// cd-guard.js — PreToolUse 门控钩子（matcher: Bash）
//
// 【它拦什么】
// Bash 工具的 cwd 在多次调用之间持久保留，AI 一旦在中间执行 `cd /tmp`，后续所有相对
// 路径操作都会失准（"为什么找不到 requirements/foo"这类诡异现象的根因）。本 guard 在
// 命令真正执行前拦下这类独立 `cd`，并在 finding 里给出可照抄的两个模板。
//
// 【为什么独立成插件（1.0.0 从 working-discipline 3.25.0 拆出）】
// 拆分动因是**它与另一些约束会在特定项目里互相顶死**，而顶死时用户需要一个开关。
// 实证场景：从 worktree 会话里改主仓的常驻产物，写侧的约束要求先 `cd` 到主仓，本 guard
// 把独立 `cd` 判为阻断，而它给的两种改法（绝对路径 / 子 shell）在定义上都不改变会话
// cwd——两条约束都成立，交集为空。此前 cd 检查与 agent-browser 检查合并在
// `working-discipline` 的 `bash-guard.js` 里，想关掉 cd 就得连 agent-browser 护栏一起
// 关，或者停掉整个纪律注入插件。独立成插件后，在这类项目里 `/plugin` 停用本插件即可，
// 其余约束不受影响。
//
// 【判据的真实覆盖面（如实表述，不要写"精确"）】
// 实际判据是「剥掉 heredoc 正文与子 shell 后，由 `; && || | 换行` 切出的顶层片段，
// trim() 后以 `cd` 开头」。它抓的是**文本形态**，不是"这条命令是否改变父 shell 的
// cwd"这个语义。2026-07-31 那次 103 条 payload 的审计给出的漏报清单（实测全部放行，
// 且全都真的污染 cwd）：
//   `pushd` / `source` 或 `.` 引入含 cd 的脚本 / `eval 'cd ...'` / `\cd` / `builtin cd` /
//   `command cd` / `"cd" /tmp` / `CDPATH=/ cd tmp` / `time cd` /
//   `git status & cd /tmp`（单个 `&` 在 splitSegments 里没有语义）/
//   `if...then cd` / `{ cd; }` / `for...do cd` / `case...) cd` / 函数体内的 cd。
// 另有一个通用绕过点在 lib/shell-parse.js 的 stripSubshells（括号匹配不感知引号）：
//   `echo "(start" && cd /tmp && echo "end)"` 里的真 cd 会被假括号配对整段吃掉。
// 结论：这条判据只拦得住「裸 cd 开头」这一族，是**提醒**不是**保证**。19 类漏报按
// 用户拍板不补——补一条就多一个误杀面，且永远补不全 shell 语法。
//
// 【已修掉的四类误杀（均为该次审计实测的真实 BLOCK，随代码一起搬过来）】
//   1. heredoc 正文（最严重）：`ssh prod bash -s <<'EOF' / cd /srv/app / ... / EOF`
//      被判本地污染，而那个 cd 在远程主机执行；`python3 - <<'EOF'` 里的 cd 甚至不是
//      shell 命令。且 hint 给的两个模板对 heredoc 正文完全无解。故 checkCd 前先调
//      stripHeredocs 剥离正文。
//   2. `cd /tmp &`：`&` 结尾的命令在子 shell 异步执行，父 shell cwd 不变。
//   3. 符号链接：macOS 上 cwd=/private/tmp 时 `cd /tmp` 实为 no-op，字符串归一看不出。
//   4. `cd $PWD` 与大小写等价路径（APFS 默认大小写不敏感）。
//
// 【已知误报（未特判）】
// shell 函数定义 `cd() { ...; }` 会被判成独立 cd——切分器只看到段首的 `cd` token，
// 不区分「调用」与「定义」。真实触发过两次（2026-07-26 / 2026-07-29）。这类写法罕见，
// 加一条「后跟 `()` 则跳过」会让解析器为一个近乎不存在的场景变复杂。
//
// 【处置里为什么专门推荐 git -C】
// 真实事故（2026-07-20）：AI 用 `(cd /path/to/other-repo && git push origin main)` 推一个
// 与当前项目无关的仓库，被另一个插件的 `resolveGitCwd()` 误拦——它用 /^cd\s+.../ 识别 cd
// 前缀来判定 git 命令作用于哪个仓库，子 shell 语法带括号、不以 cd 开头，正则匹配不上就
// fall back 到当前 worktree，把发往第三方仓库的 push 误判成本项目的 push。`git -C <path>`
// 语义等价、不含 cd token、不进子 shell，能同时躲开本 guard 与这类跨插件误伤。
//
// 【阻塞行为与逃生口】
// 命中即 exit 2 阻断，stderr 一次输出 finding + hint（stderr 会作为附加上下文注入 Claude，
// 控制在 400 字符量级）。违规片段截断到 SEGMENT_ECHO_LIMIT 字符——原样回灌曾把 20 多行
// 测试数据塞进 finding（实测单条 900+ 字符）。
//   [L1-BLOCKER] tool=Bash check=cd-guard finding="..." hint="..."
// 单次逃生：`CD_GUARD=off` 环境变量。长期关闭：`/plugin` 里停用本插件。
//
// Input: JSON on stdin with tool_name / tool_input.command / cwd
// Exit 0 = 放行; Exit 2 = 阻断

'use strict'

const fs = require('fs')
const path = require('path')
const { splitSegments, stripSubshells, stripHeredocs } = require('../lib/shell-parse')

// 回灌进 finding 的违规片段最大长度
const SEGMENT_ECHO_LIMIT = 120

// 独立 cd 命令的锚点：行首 / 命令分隔符之后（分隔符 ; && || | 换行）
const CD_PATTERN = /(^|[;&|\n])\s*cd(\s|$)/

// `cd $PWD` / `cd ${PWD}` 定义上等于当前目录（引号已由 parseCdTarget 剥掉）
const PWD_TARGETS = new Set(['$PWD', '${PWD}'])

function truncate(text, limit) {
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

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

function main() {
  if (process.env.CD_GUARD === 'off') process.exit(0)

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

  const cdSegment = checkCd(command, cwd)
  if (!cdSegment) process.exit(0)

  process.stderr.write(
    `[L1-BLOCKER] tool=Bash check=cd-guard ` +
      `finding="独立 \`cd\` 会污染后续所有 Bash 调用的 cwd(cwd=${cwd});违规片段：${truncate(cdSegment, SEGMENT_ECHO_LIMIT)}" ` +
      `hint="改用绝对路径,或子 shell \`(cd /abs/path && cmd)\`,git 命令优先 \`git -C <path> <cmd>\`;` +
      `确实必须改变会话 cwd（如从 worktree 会话改主仓常驻产物）时报告用户,由他决定单次 CD_GUARD=off 还是停用 cd-blocker 插件"\n`
  )
  process.exit(2)
}

main()
