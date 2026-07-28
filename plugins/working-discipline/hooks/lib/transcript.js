// transcript.js — 从会话 transcript（JSONL）里读取"本轮"内容
//
// 【为什么存在】
// 部分纪律的判据是"AI 在本轮已经说过某句话"（例如写 md 前必须先声明受众判定），
// 或"本轮用户给过截图"（例如派发 subagent 必须附截图路径）。这类判据无法从
// tool_input 单独得出，必须回看 transcript。
//
// 【实测得到的 transcript 事实（2026-07-26 首次验证，2026-07-28 补充修正）】
// 验证方式：直接解析 ~/.claude/projects/<项目 slug>/<session_id>.jsonl。
// - 路径由 hook payload 的 transcript_path 给出，格式为 JSONL，每行一个 JSON 对象。
// - 行的 type 取值包括：user / assistant / attachment / last-prompt / mode /
//   permission-mode / ai-title / file-history-snapshot / queue-operation。
// - assistant 行的 promptId 是 null；user 行带 promptId。
// - assistant 的 text 块与 tool_use 块**分成两行**落盘，最终行序里 text 行在前。
//
// 【落盘时序：同一条 message 内的 text 在 PreToolUse 触发时读不到】
// 2026-07-26 的原注释写着"落盘足够及时，同轮下一次工具调用即可读到"，**这个结论是错的**，
// 2026-07-28 实证推翻：它拿历史行的最终排列去推实时可读性。真实行为是——一条 assistant
// message（thinking + text + tool_use）在 API 响应结束后才整体写盘，而 PreToolUse 发生在
// 那之前，所以"AI 说了一句话，紧接着在同一条 message 里调用工具"时，hook 读不到那句话。
//   实证：本仓 session 13db234b 行 178 = assistant[text]（含受众判定声明）、行 179 =
//   assistant[tool_use] Edit、行 180 = 该 Edit 被 deny 的 tool_result。最终行序里 text
//   明明在 Edit 之前，hook 却判定"本轮没有声明"。
//   原注释所依据的自测（"声明后下一次 Bash 调用时已能 grep 到"）验证的是"文本最终可被
//   grep"，不是"hook 触发那一刻可读"——两者不等价。
// 对判定类 guard 的含义：**首次必然读不到、必然 deny 一次**，AI 重试时上一条 message 已
// 落盘才可能通过。这个代价可以接受（deny 一次正好把完整准则灌给 AI），但要求轮次界定不能
// 再把已落盘的旧声明切出窗口——那会让重试也永远失败，见下。
//
// 【2026-07-28 修正的致命误解：tool_result 行的 type 也是 'user'，且带本轮 promptId】
// 工具结果不是独立行类型，而是 `type: 'user'` + `message.content[].type === 'tool_result'`，
// 并且 promptId 与真实用户消息**完全相同**。原实现按"从后往前找最后一个 type==='user'
// 且 promptId 匹配的行"界定轮起点，必然命中**最近一次工具结果**，把 AI 在那之前输出的
// 所有文本切掉 → currentTurnAssistantText 返回空串。
//   实证：本仓 session 13db234b，本轮 promptId=b54341c4，旧算法 startIdx=54（该行是
//   tool_result），切出的 assistant 文本长度 0 字符。
//
// 【两个因素叠加成永久拒绝（真实事故，2026-07-28）】
// 落盘延迟决定"首次必然 deny"，起点算错决定"每次重试时已落盘的旧声明又被最新 tool_result
// 切掉"——两者合起来让 md-audience-declaration.js 对 .md 的 Write/Edit 构成**永久拒绝**，
// 而不只是偶发死循环：AI 每重新声明一次，就又造出一个 tool_result 把声明推出窗口。
// 事故现场里 AI 连撞两次后判断"这是个失灵的时机检查"，转而用 heredoc 绕开 Write 工具去写
// 文件——一个判据不可见的门控，最终会把 AI 逼成绕过它，而不是遵守它。
// 修好起点后的稳态：首次 deny 一次（正好把三分支准则灌给 AI），重试即通过。
//
// 【为什么不能改成"从前往后找第一个匹配的 user 行"】
// 用户中断（Esc）时，上一轮未完成工具的 tool_result 会被打上**新一轮**的 promptId，且
// 行序排在真实用户消息**之前**。实证：session 13db234b 行 37 = user[tool_result]
// pid=b54341c4，行 38 = user[text] "[Request interrupted by user]"，行 40 才是真正的用户
// 消息。取第一个匹配会把起点定到上一轮尾部，让上一轮的 assistant 文本 / 图片被误算进本轮。
//
// 【现行判据】从后往前找最后一个"真实用户消息行"：type==='user' 且 content 里不含
// tool_result 块。优先要求 promptId 匹配；匹配不到再降级为"最后一个真实用户消息行"。
// 注意真实用户消息行的 message.content 可能是 **string**（不是数组），判 tool_result
// 时必须容忍这种形态——实证：session 13db234b 行 40 的 content 就是 string。
//
// 【失败一律降级放行】
// 任何读取/解析失败都返回 null 或空数组，绝不让调用方因为"读不到 transcript"
// 而误拦正常操作——基础设施异常不该表现为纪律违规。
//
// 【导出】
// - readCurrentTurnRows(transcriptPath, promptId)  : 本轮所有行对象，失败返回 null
// - currentTurnAssistantText(transcriptPath, promptId)         : 本轮 assistant 文本拼接
// - currentTurnAssistantTextWithMeta(transcriptPath, promptId) : 同上 + 定位诊断信息，
//   供 guard 把"起点行号 / 定位方式 / 读到多少字符"写进 deny 文案。判据不可见正是这次
//   死循环从 bug 升级成僵局的原因：AI 只能猜 hook 为什么不认，然后选择绕过。
// - currentTurnImagePaths(transcriptPath, promptId)  : 本轮出现的本地图片路径

'use strict'

const fs = require('fs')

// 图片路径：Claude Code 把用户粘贴的截图落到 image-cache 目录；
// 同时兼容用户在消息里直接给出的本地图片绝对路径。
const IMAGE_PATH_PATTERN = /\/[^\s"'`)\]]*(?:image-cache\/[^\s"'`)\]]+|\.(?:png|jpe?g|webp|gif))/gi

function readLines(transcriptPath) {
  if (!transcriptPath) return null
  let raw
  try {
    raw = fs.readFileSync(transcriptPath, 'utf8')
  } catch (_) {
    return null
  }
  const rows = []
  for (const line of raw.split('\n')) {
    const t = line.trim()
    if (!t) continue
    try {
      rows.push(JSON.parse(t))
    } catch (_) {
      // 单行损坏（写入竞态）不影响其余行
    }
  }
  return rows.length ? rows : null
}

// 工具结果行：type==='user' 但 content 里含 tool_result 块。
// content 是 string 时（真实用户消息的常见形态）一定不是工具结果。
function isToolResultRow(row) {
  const content = row && row.message && row.message.content
  if (!Array.isArray(content)) return false
  return content.some((b) => b && b.type === 'tool_result')
}

// "真实用户消息行" = 用户/系统真的向 AI 说了话的那一行，排除工具结果回填。
function isRealUserMessage(row) {
  return !!row && row.type === 'user' && !isToolResultRow(row)
}

// 返回 { startIdx, matchedBy }。matchedBy 取值：
// - 'promptId'       : 按 prompt_id 精确命中本轮用户消息（正常路径）
// - 'lastUserRow'    : promptId 缺失或没命中，降级到最后一个真实用户消息行
// - 'wholeTranscript': 整份 transcript 里找不到真实用户消息行，退回全量
function locateCurrentTurnStart(rows, promptId) {
  if (promptId) {
    for (let i = rows.length - 1; i >= 0; i--) {
      if (isRealUserMessage(rows[i]) && rows[i].promptId === promptId) {
        return { startIdx: i, matchedBy: 'promptId' }
      }
    }
  }
  for (let i = rows.length - 1; i >= 0; i--) {
    if (isRealUserMessage(rows[i])) return { startIdx: i, matchedBy: 'lastUserRow' }
  }
  return { startIdx: 0, matchedBy: 'wholeTranscript' }
}

function readCurrentTurn(transcriptPath, promptId) {
  const rows = readLines(transcriptPath)
  if (!rows) return null
  const { startIdx, matchedBy } = locateCurrentTurnStart(rows, promptId)
  return { rows: rows.slice(startIdx), startIdx, matchedBy, totalRows: rows.length }
}

function readCurrentTurnRows(transcriptPath, promptId) {
  const turn = readCurrentTurn(transcriptPath, promptId)
  return turn ? turn.rows : null
}

// 只取 type==='text' 的块：纪律要求"在对话里显式输出"，thinking 块用户看不到，
// 不能算作留痕，这是有意为之的设计边界。
function collectAssistantText(rows) {
  const parts = []
  for (const row of rows) {
    if (row.type !== 'assistant') continue
    const content = (row.message && row.message.content) || []
    if (!Array.isArray(content)) continue
    for (const block of content) {
      if (block && block.type === 'text' && typeof block.text === 'string') parts.push(block.text)
    }
  }
  return parts.join('\n')
}

function currentTurnAssistantTextWithMeta(transcriptPath, promptId) {
  const turn = readCurrentTurn(transcriptPath, promptId)
  if (!turn) return null
  return {
    text: collectAssistantText(turn.rows),
    startIdx: turn.startIdx,
    matchedBy: turn.matchedBy,
    totalRows: turn.totalRows,
  }
}

function currentTurnAssistantText(transcriptPath, promptId) {
  const meta = currentTurnAssistantTextWithMeta(transcriptPath, promptId)
  return meta ? meta.text : null
}

// 本轮出现过的本地图片路径（去重）。用户粘贴的截图会以 image-cache 路径出现在
// user / attachment 行里；用户直接写出的图片绝对路径也一并识别。
function currentTurnImagePaths(transcriptPath, promptId) {
  const rows = readCurrentTurnRows(transcriptPath, promptId)
  if (!rows) return []
  const found = new Set()
  for (const row of rows) {
    if (row.type === 'assistant') continue // 只看用户侧提供的图片
    let serialized
    try {
      serialized = JSON.stringify(row)
    } catch (_) {
      continue
    }
    const matches = serialized.match(IMAGE_PATH_PATTERN)
    if (matches) matches.forEach((m) => found.add(m))
  }
  return [...found]
}

module.exports = {
  readCurrentTurnRows,
  currentTurnAssistantText,
  currentTurnAssistantTextWithMeta,
  currentTurnImagePaths,
}
