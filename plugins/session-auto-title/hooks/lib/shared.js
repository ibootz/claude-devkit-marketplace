// shared.js — hook 本体与后台生成器共用的常量、路径与 transcript 解析
//
// 单独抽出来是因为两个脚本必须对「什么算一轮真人对话」「缓存放哪」达成一致，
// 这两件事各写一遍迟早会漂移。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')

// 第几轮开始首次生成标题。用户诉求原文是「聊了两轮之后」。
const FIRST_TURN = 2

// 首次之后每隔多少轮重算一次，跟住话题漂移。
// 内建 ai-title 只在第一条 prompt 生成一次、之后永不更新，这个插件存在的意义就是这个间隔。
const REGEN_INTERVAL = 10

// 生成用的模型。与 Claude Code 内建 ai-title 用的是同一档（Haiku 4.5），
// 单次约 400-600 输入 token，成本 1e-4 美元量级。
const MODEL = 'claude-haiku-4-5-20251001'

// 后台生成的超时。超过这个时间认为那次生成已死，允许重新发起。
const LOCK_STALE_MS = 120000

// 喂给模型的最近 N 条真人 prompt，每条截断到 MAX_PROMPT_CHARS。
const RECENT_PROMPTS = 6
const MAX_PROMPT_CHARS = 300

// 标题长度上限（字符数，不是字节数）。
const MAX_TITLE_CHARS = 60

// 子进程环境变量标记。后台起的 `claude -p` 自身也会触发 UserPromptSubmit hook，
// 不拦就是无限递归——每个生成进程再生成一个。hook 本体见到这个变量直接退出。
const CHILD_ENV_FLAG = 'CLAUDE_AUTO_TITLE_CHILD'

function stateDir() {
  return path.join(os.tmpdir(), 'claude-auto-title')
}

function statePath(sessionId) {
  // sessionId 是 UUID，形态可控；仍做一次白名单过滤，避免拼出目录穿越路径。
  const safe = String(sessionId).replace(/[^A-Za-z0-9_-]/g, '')
  return path.join(stateDir(), safe + '.json')
}

function lockPath(sessionId) {
  return statePath(sessionId) + '.lock'
}

function readState(sessionId) {
  try {
    return JSON.parse(fs.readFileSync(statePath(sessionId), 'utf8'))
  } catch {
    return {}
  }
}

// 原子写：先写同目录临时文件再 rename，避免 hook 读到半个 JSON。
function writeState(sessionId, state) {
  const target = statePath(sessionId)
  fs.mkdirSync(path.dirname(target), { recursive: true })
  const tmp = target + '.' + process.pid + '.tmp'
  fs.writeFileSync(tmp, JSON.stringify(state), 'utf8')
  fs.renameSync(tmp, target)
}

// 判定一行 transcript 是不是「真人说的一轮」。
// 判据参照 Claude Code 内建自动命名的筛选（type=user 且非 meta 且不是工具结果），
// 再排掉斜杠命令与 XML 包封——那些内容拿去生成标题只会得到 local-command-stdout 之类的噪音。
function isRealUserTurn(obj) {
  if (!obj || obj.type !== 'user') return false
  if (obj.isMeta) return false
  if (obj.toolUseResult !== undefined) return false
  if (obj.isCompactSummary) return false
  const text = extractText(obj)
  if (!text) return false
  if (text.startsWith('<')) return false
  if (text.startsWith('/')) return false
  return true
}

function extractText(obj) {
  const content = obj && obj.message ? obj.message.content : undefined
  if (typeof content === 'string') return content.trim()
  if (!Array.isArray(content)) return ''
  if (content.some((b) => b && b.type === 'tool_result')) return ''
  return content
    .filter((b) => b && b.type === 'text' && typeof b.text === 'string')
    .map((b) => b.text)
    .join('\n')
    .trim()
}

// 返回 { turns, prompts }：真人轮数，以及最近 RECENT_PROMPTS 条 prompt 文本。
// transcript 可能有几 MB，逐行解析比 JSON.parse 整个文件便宜，且坏行可以单独跳过。
function scanTranscript(transcriptPath) {
  let raw
  try {
    raw = fs.readFileSync(transcriptPath, 'utf8')
  } catch {
    return { turns: 0, prompts: [] }
  }
  const prompts = []
  let turns = 0
  for (const line of raw.split('\n')) {
    if (!line || line[0] !== '{') continue
    let obj
    try {
      obj = JSON.parse(line)
    } catch {
      continue
    }
    if (!isRealUserTurn(obj)) continue
    turns += 1
    prompts.push(extractText(obj).slice(0, MAX_PROMPT_CHARS))
    if (prompts.length > RECENT_PROMPTS) prompts.shift()
  }
  return { turns, prompts }
}

// 逐字符过滤控制字符，不用正则字符类——源码里出现控制字符字面量会破坏文件编码。
// 控制字符必须去掉：标题最终会被写进终端的 OSC 转义序列，混进去会截断或错乱。
function stripControlChars(input) {
  let out = ''
  for (const ch of input) {
    const code = ch.codePointAt(0)
    if (code < 32) continue
    if (code >= 127 && code <= 159) continue
    out += ch
  }
  return out
}

function sanitizeTitle(raw) {
  if (typeof raw !== 'string') return ''
  let t = raw.trim()
  // 模型偶尔把标题包在引号里，或加「标题：」前缀。
  t = t.replace(/^["'「『]+|["'」』]+$/g, '')
  t = t.replace(/^(标题|title)\s*[:：]\s*/i, '')
  t = stripControlChars(t)
  t = t.replace(/\s+/g, ' ').trim()
  return Array.from(t).slice(0, MAX_TITLE_CHARS).join('')
}

module.exports = {
  FIRST_TURN,
  REGEN_INTERVAL,
  MODEL,
  LOCK_STALE_MS,
  RECENT_PROMPTS,
  MAX_TITLE_CHARS,
  CHILD_ENV_FLAG,
  stateDir,
  statePath,
  lockPath,
  readState,
  writeState,
  isRealUserTurn,
  extractText,
  scanTranscript,
  sanitizeTitle,
  stripControlChars,
}
