// wiki-check.js — 回合末词条核对（4.17.0，由 stop-audit.js 调用，不单独挂 hook）
//
// 【核什么】三章 3.14 要求词条文件（$TMPDIR/claude-wiki/<仓库>/<词条>.md）只装客观来源的逐字摘录：本机文件，
// 或远端内容（钉钉文档、网页、远端文件）由读取命令直接落盘的快照（$TMPDIR/claude-sources/，4.21.0）。
// 回合末审查的判定模型只看最后一条回复，看不到词条；本模块补这一段，全程机械比对、不经模型：
// 1. 要核的词条 = 本轮（最后一条真实用户提问之后）Write / Edit / MultiEdit 过的 file_path，加上
//    最后一条回复里链到的路径；路径含 claude-wiki 目录段且以 .md 结尾的才算。读盘上的最终内容。
// 2. 骨架：除标题、`>` 摘录、紧跟摘录的出处行、「## 未找到」「## 相关词条」下的列表、HTML 注释、
//    空行外，任何一行都算自写句子。
// 3. 摘录：去掉 markdown 标记与全部空白后，按「……」切开的每个片段（≥4 字）都要在出处文件里
//    逐字找到；第一个片段要落在所注行号前 5 行到后 40 行之内；出处文件不能是词条自己的目录，
//    也不能是本轮刚 Write / Edit 过的文件（那是 AI 自己写的，不算现有原文）。
//
// 【不核什么】Bash heredoc 写、回复里又没链到的词条；回复正文括注里的原文片段（只靠注入）；
// 打回之后续写里新建的词条（stop_hook_active 为真时整段 Stop 审查不跑，每轮只打回一次）。
//
// 【失灵时怎样】任何异常都当作「本文件不核」，不打回；词条被删掉了也不核。只打回一次，
// 由 stop-audit.js 的 stop_hook_active 保证。

'use strict'

const fs = require('fs')
const path = require('path')

const MIN_FRAG = 4
const WIN_BEFORE = 5
const WIN_AFTER = 40
const ALLOWED_H2 = new Set(['未找到', '相关词条'])

function isWikiPath(p) {
  return typeof p === 'string' && /[\\/]claude-wiki[\\/]/.test(p) && /\.md$/i.test(p)
}

// 本轮 Write / Edit / MultiEdit 过的全部路径与其中的词条路径（去重，保持首次出现顺序）。
// 轮起点判定与 stop-audit.js 的 userPromptText 一致。
function turnWrites(raw, userPromptText) {
  const rows = []
  for (const ln of raw.split('\n')) {
    if (!ln.trim()) continue
    try { rows.push(JSON.parse(ln)) } catch { /* 跳过损坏行 */ }
  }
  let start = -1
  for (let i = rows.length - 1; i >= 0; i--) {
    if (userPromptText(rows[i]) != null) { start = i; break }
  }
  if (start < 0) return { all: new Set(), wiki: [] }
  const seen = new Set()
  const all = new Set()
  for (const row of rows.slice(start + 1)) {
    if (row.isSidechain || row.type !== 'assistant') continue
    const c = row.message && row.message.content
    if (!Array.isArray(c)) continue
    for (const b of c) {
      if (!b || b.type !== 'tool_use' || !/^(Write|Edit|MultiEdit)$/.test(b.name)) continue
      const p = b.input && b.input.file_path
      if (typeof p === 'string') all.add(path.resolve(p))
      if (isWikiPath(p)) seen.add(p)
    }
  }
  return { all, wiki: [...seen] }
}

function wikiFilesThisTurn(raw, userPromptText) {
  return turnWrites(raw, userPromptText).wiki
}

// 最后一条回复里链到的词条（复用的旧词条、Bash 写的词条也在这里被核到）。
function wikiFilesInReply(msg) {
  const out = []
  const re = /(?:file:\/\/|vscode:\/\/file)?((?:\/|[A-Za-z]:[\\/])[^\s()<>"'`\]]*?[\\/]claude-wiki[\\/][^\s()<>"'`\]#]*?\.md)/g
  let m
  while ((m = re.exec(String(msg || '')))) {
    let f = m[1]
    try { f = decodeURIComponent(f) } catch { /* 保留原样 */ }
    out.push(f)
  }
  return out
}

// 去掉行首的引用 / 列表 / 标题 / 表格标记。
function stripLinePrefix(line) {
  return line
    .replace(/^\s*(?:>\s?)*/, '')
    .replace(/^\s*(?:\/\/+|\/\*+|\*+\/?|--|;+|%+)(?=\s|$)/, '') // 代码注释前缀：// /* * -- ; %
    .replace(/^\s*(?:[-*+]\s+|\d+[.)]\s+|#{1,6}(?=\s|$)|\|)/, '')
}

// 比对口径：去 markdown 链接、粗体、行内代码标记，再去掉全部空白。
function norm(text) {
  return text
    .split('\n').map(stripLinePrefix).join('\n')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\*\*|__|`/g, '')
    .replace(/\s+/g, '')
}

// 出处链接 → { file, line }；认 vscode://file/<abs>:<line>[:col] 与 file:///<abs>#[L]<line>。
function parseSource(url) {
  let m = /^vscode:\/\/file(\/.+?):(\d+)(?::\d+)?$/.exec(url)
  if (!m) m = /^file:\/\/(\/.+?)#L?(\d+)$/.exec(url)
  if (!m) return null
  let file
  try { file = decodeURIComponent(m[1]) } catch { file = m[1] }
  if (/^\/[A-Za-z]:/.test(file)) file = file.slice(1) // Windows：/C:/x → C:/x
  return { file, line: Number(m[2]) }
}

const SOURCE_RE = /^—— \[[^\]]+\]\(([^)\s]+)\)\s*$/
const RELATED_RE = /^- \[[^\]]+\]\(\.\/[^)\s]+\.md\)\s*$/

function checkExcerpt(quoteLines, url, wikiFile, writtenThisTurn) {
  const src = parseSource(url)
  if (!src) return '出处链接认不出文件与行号，写成 vscode://file/绝对路径:行号'
  if (/[\\/]claude-wiki[\\/]/.test(src.file)) return '出处指向词条目录本身，原文必须来自客观来源（本机文件或远端内容的快照）'
  // 外挂文档（claude-side 目录）由模型后台生成，不是现有原文
  if (/[\\/]claude-side[\\/]/.test(src.file)) return '出处指向外挂文档，那是模型生成的，原文必须来自客观来源（本机文件或远端内容的快照）'
  if (path.resolve(src.file) === path.resolve(wikiFile)) return '出处指向词条自己'
  if (writtenThisTurn && writtenThisTurn.has(path.resolve(src.file))) return `出处文件 ${path.basename(src.file)} 本轮被你改写过，不算现有原文`
  let text
  try { text = fs.readFileSync(src.file, 'utf8') } catch { return `出处文件读不到：${src.file}` }
  const lines = text.split('\n')
  if (!(src.line >= 1 && src.line <= lines.length)) return `出处行号 ${src.line} 超出文件范围（共 ${lines.length} 行）`
  let body = quoteLines.map((l) => l.replace(/^>\s?/, '')).join('\n').trim()
  body = body.replace(/^[「“"]/, '').replace(/[」”"]$/, '')
  const frags = body.split(/……|…|\.\.\./).map(norm).filter(Boolean)
  if (!frags.length) return '摘录是空的'
  const short = frags.find((f) => [...f].length < MIN_FRAG)
  if (short) return `摘录片段「${short}」不到 ${MIN_FRAG} 个字，像在拼句`
  const whole = norm(text)
  const window = norm(lines.slice(Math.max(0, src.line - 1 - WIN_BEFORE), src.line + WIN_AFTER).join('\n'))
  for (const f of frags) {
    if (!whole.includes(f)) return `摘录「${cutFrag(f)}」在 ${path.basename(src.file)} 里找不到逐字原文`
  }
  if (!window.includes(frags[0])) return `摘录「${cutFrag(frags[0])}」不在 ${path.basename(src.file)} 第 ${src.line} 行附近，行号注错了`
  return null
}

function cutFrag(f) {
  const a = [...f]
  return a.length <= 20 ? f : a.slice(0, 19).join('') + '…'
}

// 返回该词条的问题列表（每条一句）；读不到文件返回 []。
function checkWikiFile(file, writtenThisTurn) {
  let text
  try { text = fs.readFileSync(file, 'utf8') } catch { return [] }
  const lines = text.split('\n')
  const problems = []
  let section = null
  let titleSeen = false
  let quote = null // { start, lines }
  let excerpts = 0
  let inComment = false
  let notFound = 0
  const flushQuote = () => {
    if (quote) problems.push(`第 ${quote.start} 行的摘录下面没有紧跟出处行（—— [文件名:行号](vscode://file/绝对路径:行号)）`)
    quote = null
  }
  lines.forEach((raw, i) => {
    const n = i + 1
    const t = raw.trim()
    if (inComment) { if (t.includes('-->')) inComment = false; return }
    if (t.startsWith('<!--')) { if (!t.includes('-->')) inComment = true; return }
    if (!t) return
    if (t.startsWith('>')) {
      if (!quote) quote = { start: n, lines: [] }
      quote.lines.push(t)
      return
    }
    const sm = SOURCE_RE.exec(t)
    if (sm) {
      if (!quote) { problems.push(`第 ${n} 行出处上面没有摘录`); return }
      const p = checkExcerpt(quote.lines, sm[1], file, writtenThisTurn)
      if (p) problems.push(`第 ${quote.start} 行：${p}`)
      excerpts += 1
      quote = null
      return
    }
    if (t.startsWith('—— [')) {
      quote = null
      problems.push(`第 ${n} 行出处格式不对：写成 —— [文件名:行号](vscode://file/绝对路径:行号)，路径里的空格与括号写成 %20、%28、%29`)
      return
    }
    flushQuote()
    if (/^# \S/.test(t) && !titleSeen) { titleSeen = true; return }
    const h2 = /^## (.+)$/.exec(t)
    if (h2) {
      section = h2[1].trim()
      if (!ALLOWED_H2.has(section)) problems.push(`第 ${n} 行小标题「${cutFrag(section)}」是自写内容，只允许「未找到」「相关词条」`)
      return
    }
    if (t.startsWith('- ') && section === '未找到') {
      notFound += 1
      if ([...t].length > 42) problems.push(`第 ${n} 行「未找到」条目超过 40 字，只写找过哪方面`)
      else if (notFound === 6) problems.push(`第 ${n} 行起「未找到」超过 5 条，只留读者最可能问的几项`)
      return
    }
    if (section === '相关词条' && RELATED_RE.test(t)) return
    problems.push(`第 ${n} 行「${cutFrag(t)}」不是摘录、出处或列表，是自写句子`)
  })
  flushQuote()
  if (!titleSeen) problems.unshift('缺标题行「# 原词」')
  if (!excerpts) problems.push('没有一段带出处的摘录；本机找不到原文就不建词条')
  return problems
}

// 本轮写过的词条与最后一条回复链到的词条的打回 reason；全合格或没有词条时返回 ''。
function wikiReason(raw, userPromptText, lastMessage) {
  const out = []
  const { all, wiki } = turnWrites(raw, userPromptText)
  const files = []
  const seen = new Set()
  for (const f of [...wiki, ...wikiFilesInReply(lastMessage)]) {
    const k = path.resolve(f)
    if (!seen.has(k)) { seen.add(k); files.push(f) }
  }
  for (const f of files) {
    let ps
    try { ps = checkWikiFile(f, all) } catch { continue }
    for (const p of ps) out.push(`- ${f}：${p}`)
  }
  if (!out.length) return ''
  return [
    '回合末词条核对（机械比对，不经模型）：',
    ...out,
    '词条只装客观来源的逐字原文（三章 3.14；本机文件，或读取命令直接落盘的远端快照）：自写的句子删掉；摘录照出处文件逐字改正，或改注正确的文件与行号；找不到原文的那段删掉，整份词条没有摘录就删掉文件，正文里对应的释义改成「未找到出处」。改完把整条回复完整重写一遍；只有词条问题时不写更正块。',
  ].join('\n')
}

module.exports = { wikiReason, wikiFilesThisTurn, wikiFilesInReply, checkWikiFile, checkExcerpt, parseSource, norm, isWikiPath }
