// nonascii-path.js — PreToolUse 门控 + 条件注入钩子（matcher: Bash）
//
// 【用途】
// macOS 下 git 输出的路径是 NFC 归一形态（`core.precomposeunicode`），磁盘上实际文件名
// 则常是 NFD 分解形态——中文等非 ASCII 路径两种形态字节不同、肉眼全同。这条纪律原本
// 约 700 字符常驻注入，但它只在"命令里真的出现非 ASCII 路径"时才有用；改成本 hook 在
// 该时刻注入，并把其中唯一能机械判定的禁止项（探测类命令挂 `2>/dev/null`）升级为硬拦截。
//
// 【两种处置】
// 1. **deny**：探测 / 统计类命令（grep / find / ls / wc / stat / test / rg / git grep 等）
//    同时满足「命令含非 ASCII 字符」与「挂了 `2>/dev/null`」。这是原纪律明列的禁止项：
//    路径形态不一致导致的 No such file 报错会被 `2>/dev/null` 吞掉，空结果随即被误读成
//    「确实没有」——错误结论从此一路传递下去。
// 2. **additionalContext**：命令含非 ASCII 且用了检索/比对类命令时，注入完整规避法。
//    同一轮只注入一次（见 lib/notify-once.js）。
//
// 【为什么不拦所有含非 ASCII 的命令】
// `git commit -m "修复登录"`、`echo "中文"` 这类命令里的非 ASCII 是内容不是路径，与
// NFC/NFD 无关。所以两种处置都要求"命令属于检索/探测类"这个前置条件，把误报压到可接受
// 范围——宁可漏掉少数场景，也不要让每条带中文的命令都被打扰。
//
// 【放行场景】
// - 命令不含非 ASCII 字符
// - 命令不是检索 / 探测 / 比对类（写类、构建类、提交类等一律不管）
// - 已在本轮注入过提醒（deny 不去重，禁止项每次都要拦）
//
// Input: JSON on stdin with tool_name / tool_input.command / session_id / prompt_id
// Exit 0（始终）——deny 靠 stdout JSON 表达，不用 exit 2

'use strict'

const fs = require('fs')
const { shouldNotify } = require('../lib/notify-once')

// 非 ASCII 字符（中文、日文、韩文、emoji、带音标的拉丁字母等）
const NON_ASCII = /[^\x00-\x7F]/

// 探测 / 统计类命令：其"空结果"会被当成结论使用，因此最怕静默失败
const PROBE_COMMANDS = /(^|[\s;|&(])(grep|egrep|fgrep|rg|find|ls|wc|stat|file|test|cat|head|tail|du)\s|git\s+(grep|ls-files)\s/

// 检索 / 比对类命令：跨源比对时最容易踩 NFC/NFD 不一致
const SEARCH_OR_DIFF_COMMANDS = /(^|[\s;|&(])(grep|egrep|fgrep|rg|find|ls|diff|comm|sort|uniq|xargs)\s|git\s+(grep|ls-files|diff|status)\s/

const SILENCE_STDERR = /2>\s*\/dev\/null|2>&1\s*>\s*\/dev\/null|&>\s*\/dev\/null/

const NFC_NFD_GUIDE = [
  '# macOS 中文路径静默漏检（NFC / NFD 形态不一致）',
  '',
  '这条命令里出现了非 ASCII 路径。macOS 下 git 输出的路径是 NFC 归一形态',
  '（`core.precomposeunicode`），磁盘上实际文件名则常是 NFD 分解形态——两种形态字节不同、',
  '肉眼完全相同，一律按「可能不一致」防御。',
  '',
  '**后果**：grep / diff 按字节比较，跨源比对（一边来自 git 输出、一边来自磁盘 find/ls',
  '枚举）会静默匹配不上；git 输出的路径直接拼作文件参数，在部分文件系统（SMB / NFS /',
  'Linux 容器卷等）上报 No such file，报错再被 `2>/dev/null` 吞掉后，空结果就会被误读成',
  '「确实没有」。',
  '',
  '**规避**：',
  '- 非 ASCII 路径检索优先 **git 单源闭环**（`git grep` / `git ls-files`），不要把 git 输出',
  '  与磁盘枚举结果互相 grep',
  '- 必须跨源比对时先统一形态（`iconv -f UTF-8-MAC -t UTF-8` 把 NFD 转 NFC），或把路径里的',
  '  非 ASCII 段换成 glob 通配 `*`',
  '- 探测 / 统计类命令禁挂 `2>/dev/null`（本 hook 会直接拦截这种组合）',
  '- 「非 ASCII 路径 + 空结果」不得直接判「没有」——先 `ls` 父目录确认实体是否存在再下结论',
].join('\n')

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
  if (!command || !NON_ASCII.test(command)) process.exit(0)

  // 处置 1：探测类命令 + 吞 stderr → 硬拦截（每次都拦，不去重）
  if (PROBE_COMMANDS.test(command) && SILENCE_STDERR.test(command)) {
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          permissionDecision: 'deny',
          permissionDecisionReason: [
            '探测 / 统计类命令里出现非 ASCII 路径，同时挂了 `2>/dev/null` —— 这个组合被禁止。',
            '',
            'macOS 的 NFC / NFD 路径形态不一致会让命令报 No such file，而 `2>/dev/null` 会把报错',
            '吞掉，你只会看到一个空结果，并极可能把它当成「确实没有」——错误结论从此一路传递。',
            '',
            '去掉 `2>/dev/null` 重跑，让报错可见。如果确实需要过滤噪声，改成把 stderr 留在屏幕上、',
            '只过滤 stdout；或者改用 git 单源闭环（`git grep` / `git ls-files`）避开形态问题。',
            '',
            `违规命令：\n  ${command}`,
          ].join('\n'),
        },
      }) + '\n'
    )
    process.exit(0)
  }

  // 处置 2：检索 / 比对类命令 → 注入规避法（本轮一次）
  if (SEARCH_OR_DIFF_COMMANDS.test(command)) {
    if (!shouldNotify('nfcnfd', payload.session_id, payload.prompt_id, 'guide')) process.exit(0)
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          additionalContext: NFC_NFD_GUIDE,
        },
      }) + '\n'
    )
    process.exit(0)
  }

  process.exit(0)
}

main()
