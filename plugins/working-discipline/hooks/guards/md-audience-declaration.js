// md-audience-declaration.js — PreToolUse 门控钩子（matcher: Write|Edit）
//
// 【用途】
// 写 md 文档前必须先判定主受众是人还是 AI，并在对话里留痕。原纪律自己就写着
// 「防止 AI 心里想过就跳过」——这正说明它靠自觉守不住：受众分辨的三分支准则
// 约 900 字符常驻注入，却仍然经常被跳过，纯粹是在消耗注意力预算。
//
// 判定「是否留过痕」是 100% 机械的字符串检查（本轮 assistant 文本里有没有出现
// 「受众判定」），所以这条最适合硬化：常驻注入只留一行提示，完整三分支准则
// 挪到本 hook 的 deny reason 里——写 md 前才付这份 token 成本。
//
// 【触发条件】
// - 工具：Write / Edit
// - tool_input.file_path 扩展名为 .md / .markdown
// - 本轮（按 prompt_id 界定）assistant 文本里不含「受众判定」字样
//
// 【放行场景】
// - 非 md 文件（源码、json、yaml 等一律不管）
// - 本轮已声明受众判定
// - transcript 读不到 / 解析失败 —— 静默放行，基础设施异常不该表现为纪律违规
//
// 【熔断（2026-07-28 事故后补）】
// 判据依赖 transcript 的行结构，属于对外部格式的脆弱依赖。这份依赖一旦失配，表现就是
// "AI 明明声明了却永远拿不到放行"——2026-07-28 真实撞过一次死循环：tool_result 行的
// type 也是 'user' 且带本轮 promptId，导致轮起点被推到最近一次工具调用之后，AI 每次
// 重新声明都被自己新产生的 tool_result 挤出判定窗口（根因与修法见 ../lib/transcript.js
// 头注释）。所以除了修根因，这里再加一层次数兜底：同一 (轮次, 目标文件) 连续 deny 达到
// DENY_LIMIT 次后，不再 deny，而是转成 'ask' 交给用户拍板——既不无限阻塞 AI，也不替
// 用户自动批准写入（用 'allow' 会绕过用户的权限确认，那是越权）。
// 同时把判据本身写进 deny 文案（起点行号 / 定位方式 / 读到多少字符）：上次事故之所以从
// bug 升级成僵局，正是因为 AI 看不到 hook 凭什么说"没声明"，只能猜，然后选择绕过。
//
// 【为什么不豁免 Edit】
// 「大改 md」与「小改 md」无法从 tool_input 机械区分，而受众判定本身只要一句话，
// 成本远低于误放行的代价（AI 会顺着旧结构继续写，受众错配一路传染）。若只是改
// 一个错别字，声明一句「本次 md 受众判定：<沿用原判定>，理由：仅修正错别字」
// 即可通过——这句话本身也提醒了 AI 别顺手扩大改动范围。
//
// Input: JSON on stdin with tool_name / tool_input.file_path / transcript_path / prompt_id
// Exit 0（始终）——放行与 deny 都走 exit 0，靠 stdout 的 JSON 表达决定

'use strict'

const fs = require('fs')
const path = require('path')
const { currentTurnAssistantTextWithMeta } = require('../lib/transcript')
const { bumpCounter } = require('../lib/notify-once')

const MD_EXTENSIONS = new Set(['.md', '.markdown'])

// 同一 (轮次, 目标文件) 允许 deny 的次数上限；超过即转 'ask'。
// 正常情况下 AI 第二次尝试就带上声明了，连撞 3 次说明判据本身可疑。
const DENY_LIMIT = 3

const AUDIENCE_GUIDE = [
  '写 md 文档前必须先判定主受众，并在对话里留痕——本轮还没有出现「受众判定」声明。',
  '',
  '**先在对话里显式输出这一句**（必须先于任何写 md 的工具调用）：',
  '  「本次 md 受众判定：{人 / AI / 人机混合}，理由：……」',
  '',
  '然后按判定对应的准则组织内容，写完再自检一遍：',
  '',
  '- **偏向人读**（方案 / 报告 / README / 使用说明）→ 用通俗直白的话叙述，按',
  '  「结论前置 → 展开原因或机制 → 举具体例子落地」组织；能一句话说清不写一段；',
  '  避免堆砌术语与缩写；重要结论放显眼位置；标题层级不要过深；示意图/表格能替代',
  '  长段就替代。**必检**：结论前置 / 避免堆术语 / 示例落地。',
  '',
  '- **偏向 AI 读**（skill 指令 / reference 参考文档 / 下一段 AI 会话的交接文档）→',
  '  上下文交代齐备（不假设 AI 已知的前置背景一律显式写明，包括所在仓库、目标目录、',
  '  依赖状态、已发生的关键决策）；用词精确无歧义（「可能/也许/大概/看情况」要么给出',
  '  判定准则要么删掉）；关键对象一次点名到位（文件路径、函数名、参数、错误消息原文、',
  '  命令原文）；示例同时覆盖典型场景与边界场景（如「什么时候不触发」）；避免比喻/',
  '  双关/反语。**必检**：上下文齐备 / 用词精确 / 示例覆盖典型与边界。',
  '',
  '- **人机混合读**（既要人看懂又要 AI 照字面执行，如带示例的 CLAUDE.md / plugin',
  '  README / 命令手册）→ 双要求叠加：结构对人友好 + 用词对 AI 精确 + 示例齐全；',
  '  写完后分别以「人快速扫读」和「AI 完全按字面执行」两种视角各复读一遍，看哪种',
  '  视角下会漏掉信息或产生误解，再补回去。**必检**：上面两组共六条。',
  '',
  '如果这次只是极小改动（改错别字 / 调格式），声明',
  '「本次 md 受众判定：<沿用原判定>，理由：<原因>」即可通过。',
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

  const toolName = payload.tool_name
  if (toolName !== 'Write' && toolName !== 'Edit') process.exit(0)

  const filePath = (payload.tool_input && payload.tool_input.file_path) || ''
  if (!filePath) process.exit(0)
  if (!MD_EXTENSIONS.has(path.extname(filePath).toLowerCase())) process.exit(0)

  // 字段名两种写法都接受：payload 的键名随 harness 版本可能变化，读不到轮次标识时
  // transcript 库会降级到"最后一个真实用户消息行"，不影响判定正确性。
  const promptId = payload.prompt_id || payload.promptId
  const turn = currentTurnAssistantTextWithMeta(payload.transcript_path, promptId)
  // 读不到 transcript（路径缺失 / 解析失败 / 尚未落盘）一律放行，不误拦
  if (turn === null) process.exit(0)
  if (turn.text.includes('受众判定')) process.exit(0)

  const denyCount = bumpCounter('mdaudience', payload.session_id, `${promptId || 'noprompt'}:${filePath}`)
  const diagnosis =
    `\n\n（hook 判据诊断：本轮起点 = transcript 第 ${turn.startIdx} 行 / 全文 ${turn.totalRows} 行，` +
    `定位方式 ${turn.matchedBy}，本轮读到 assistant 文本 ${turn.text.length} 字符；本文件本轮第 ${denyCount} 次拦截。` +
    `若你确信已经原样输出过该声明，请把这段诊断连同现象告知用户——这说明判据失灵，` +
    `应修 hooks/lib/transcript.js 的轮次界定，而不是绕过工具去写文件。）`

  if (denyCount > DENY_LIMIT) {
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          permissionDecision: 'ask',
          permissionDecisionReason:
            `受众判定门控已连续拦截本文件 ${denyCount} 次，超过上限 ${DENY_LIMIT}，判据可能失灵，转由你拍板。\n\n` +
            `目标文件：${filePath}${diagnosis}`,
        },
      }) + '\n'
    )
    process.exit(0)
  }

  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: `${AUDIENCE_GUIDE}\n\n本次目标文件：${filePath}${diagnosis}`,
      },
    }) + '\n'
  )
  process.exit(0)
}

main()
