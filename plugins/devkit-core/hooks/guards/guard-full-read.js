// guard-full-read.js — PreToolUse 门控钩子
//
// 【用途】
// 当 AI 试图全文读取知识库或 Skill 参考文档时，检查是否使用了
// 精准读取（offset/limit）。全文读取大文件时阻断并引导 AI
// 先用 Grep 定位关键词，再用 offset/limit 精准取段。
//
// 【触发条件】
// - 工具：Read
// - 路径匹配：knowledge/、references/、_shared-runtime/
// - 未指定 offset/limit/pages（全文读取）
// - 文件行数 > 阈值
// - 文件名不在白名单中
//
// 【白名单】（始终允许全文读取）
// - SKILL.md — Skill 主文件，执行时需全文理解步骤流程
// - _index.md — 索引文件，设计上就是让人全文读的
// - CHANGELOG.md — 变更日志，通常较小且需全文
//
// 【阻塞行为】
// 超阈值时 exit 2 阻断，附带操作指引。AI 必须改用
// Grep 定位 → Read+offset/limit 的方式重试。
//
// Input: JSON on stdin with tool_input.file_path
// Exit 0 = 放行; Exit 2 = 阻断

'use strict'

const fs = require('fs')
const path = require('path')

const LINE_THRESHOLD = 200

const WHITELIST_NAMES = new Set(['SKILL.md', '_index.md', 'CHANGELOG.md'])

const TARGET_PATTERNS = [/\/knowledge\//, /\/_shared-runtime\//, /\/references\//]

function main() {
  let input = ''
  try {
    input = fs.readFileSync(0, 'utf8')
  } catch (_) {
    process.exit(0)
  }

  let filePath = ''
  let toolInput = {}
  try {
    const parsed = JSON.parse(input)
    toolInput = parsed.tool_input || {}
    filePath = toolInput.file_path || ''
  } catch (_) {
    process.exit(0)
  }

  if (!filePath) process.exit(0)

  // Normalize Windows backslashes
  const normalized = filePath.replace(/\\/g, '/')

  // Only intercept target directories
  const isTarget = TARGET_PATTERNS.some((p) => p.test(normalized))
  if (!isTarget) process.exit(0)

  // Whitelist by filename
  const basename = path.basename(filePath)
  if (WHITELIST_NAMES.has(basename)) process.exit(0)

  // Already using targeted read — allow
  if (toolInput.offset || toolInput.limit || toolInput.pages) process.exit(0)

  // Check file line count
  let lineCount = 0
  try {
    const content = fs.readFileSync(filePath, 'utf8')
    lineCount = content.split('\n').length
  } catch (_) {
    process.exit(0) // Can't read file, just allow
  }

  if (lineCount <= LINE_THRESHOLD) process.exit(0)

  // Block and guide
  const msg = [
    'FULL-READ GUARD: 大文件全文读取被拦截',
    '',
    `文件: ${path.basename(filePath)} (${lineCount} 行, 阈值 ${LINE_THRESHOLD})`,
    `路径: ${normalized}`,
    '',
    '请改用以下方式:',
    '1. Grep 搜索关键词定位到具体段落',
    '2. Read + offset/limit 精准读取目标段落',
    '3. 仅当需要全局概览且文件较小(<200行)时才全文读取',
    '',
    '白名单文件(SKILL.md, _index.md, CHANGELOG.md)可全文读取。',
  ]

  process.stderr.write(msg.join('\n') + '\n')
  process.exit(2)
}

main()
