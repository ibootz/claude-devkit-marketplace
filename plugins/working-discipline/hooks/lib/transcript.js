// transcript.js — 从会话 transcript（JSONL）里读取"本轮"内容
//
// 【为什么存在】
// 部分纪律的判据是"AI 在本轮已经说过某句话"（例如写 md 前必须先声明受众判定），
// 或"本轮用户给过截图"（例如派发 subagent 必须附截图路径）。这类判据无法从
// tool_input 单独得出，必须回看 transcript。
//
// 【实测得到的 transcript 事实（2026-07-26 在本项目会话文件上验证）】
// - 路径由 hook payload 的 transcript_path 给出，格式为 JSONL，每行一个 JSON 对象。
// - 行的 type 取值包括：user / assistant / attachment / last-prompt / mode /
//   permission-mode / ai-title / file-history-snapshot。
// - **只有 type=='user' 的行带 promptId，assistant 行的 promptId 是 null**。
//   所以"本轮"只能这样界定：从后往前找最后一个 promptId === payload.prompt_id
//   的 user 行，它之后的所有行即本轮内容。
// - assistant 文本在 message.content[] 里 type=='text' 的块中。
// - **落盘及时**：AI 刚输出的文本，在同一轮的下一次工具调用触发 hook 时已可读到
//   （官方文档提到 transcript 是异步写入，实测在这个时间尺度上不构成问题）。
//
// 【失败一律降级放行】
// 任何读取/解析失败都返回 null 或空数组，绝不让调用方因为"读不到 transcript"
// 而误拦正常操作——基础设施异常不该表现为纪律违规。
//
// 【导出】
// - readCurrentTurnRows(transcriptPath, promptId) : 本轮所有行对象，失败返回 null
// - currentTurnAssistantText(transcriptPath, promptId) : 本轮 assistant 文本拼接
// - currentTurnImagePaths(transcriptPath, promptId)   : 本轮出现的本地图片路径

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

// 界定"本轮"：优先用 prompt_id 精确定位；找不到匹配时降级为"最后一个 user 行之后"。
function readCurrentTurnRows(transcriptPath, promptId) {
  const rows = readLines(transcriptPath)
  if (!rows) return null

  let startIdx = -1
  if (promptId) {
    for (let i = rows.length - 1; i >= 0; i--) {
      if (rows[i].type === 'user' && rows[i].promptId === promptId) {
        startIdx = i
        break
      }
    }
  }
  if (startIdx === -1) {
    for (let i = rows.length - 1; i >= 0; i--) {
      if (rows[i].type === 'user') {
        startIdx = i
        break
      }
    }
  }
  if (startIdx === -1) return rows
  return rows.slice(startIdx)
}

function currentTurnAssistantText(transcriptPath, promptId) {
  const rows = readCurrentTurnRows(transcriptPath, promptId)
  if (!rows) return null
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

module.exports = { readCurrentTurnRows, currentTurnAssistantText, currentTurnImagePaths }
