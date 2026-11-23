// term-links.js — 回合末链接核对：挂过链接的词每次出现都要挂（4.19.0，由 stop-audit.js 调用）
//
// 【核什么】用户 2026-11-21 原话：「不要只在第一次出现时添加编号 而应该是像wiki网页一样 所有出现
// 这个词的地方都可以点击」。最后一条回复里，凡是某个词已经以本机链接（file:// 或 vscode://file）的
// 标签出现过，它在同一条回复别处裸写的次数就要是 0。全程机械比对、不经模型：
// 1. 词表 = 本机链接的标签；标签形如「文件名:行号」时，去掉行号的文件名也算；形如「A · B」时 A 也算。
// 2. 扫描范围 = 去掉围栏代码块、全部 markdown 链接、裸 URL 后的正文。行内代码整段恰好等于某个词时
//    算一次裸写（点不动），行内代码里的命令或更长的串不算。
// 3. 词首 / 词尾是 ASCII 字母数字时，相邻字符不能是 [A-Za-z0-9_./-]（避免 a.md 命中 data.md、路径中段）。
//    词至少 2 个字符，纯数字与纯标点不算。
//
// 4. 链接后紧跟的括注原文（「…」）要能在链接处逐字找到：带行号的按行号附近比，词条文件比全文。
//
// 【不核什么】从没挂过链接的词（该不该挂要猜语义，归模型那路与注入）；跨回复的一致性。
// 【失灵时怎样】任何异常返回 ''，不打回。

'use strict'

const fs = require('fs')
const { checkExcerpt, norm } = require('./wiki-check')

const LINK_RE = /\[([^\]\n]+)\]\(([^)\s]+)\)/g
const LOCAL_URL = /^(?:file:\/\/|vscode:\/\/file)/

function stripFences(text) {
  return text.replace(/^[ \t]*(```|~~~)[^\n]*\n[\s\S]*?^[ \t]*\1[^\n]*$/gm, ' ')
}

function cleanLabel(s) {
  return s.replace(/\*\*|__|`/g, '').trim()
}

function termsOf(label) {
  const out = new Set([label])
  const dot = label.split(/\s+·\s+/)[0]
  if (dot && dot !== label) out.add(dot.trim())
  const m = /^(.+?):\d+(?:[-–]\d+)?$/.exec(label)
  if (m) out.add(m[1].trim())
  return [...out].filter((t) => [...t].length >= 2 && /[\p{L}]/u.test(t))
}

const ASCII_WORD = /[A-Za-z0-9]/
const ASCII_EDGE = /[A-Za-z0-9_./-]/

function countBare(hay, term) {
  let n = 0
  let i = hay.indexOf(term)
  while (i >= 0) {
    const before = hay[i - 1]
    const after = hay[i + term.length]
    const okL = !ASCII_WORD.test(term[0]) || !before || !ASCII_EDGE.test(before)
    // 词尾后紧跟「.」再接空白或行尾（句号）不算粘连
    const okR = !ASCII_WORD.test(term[term.length - 1]) || !after || !ASCII_EDGE.test(after) ||
      (after === '.' && !/[A-Za-z0-9_/-]/.test(hay[i + term.length + 1] || ''))
    if (okL && okR) n += 1
    i = hay.indexOf(term, i + term.length)
  }
  return n
}

// 返回 [{ term, count }]：挂过链接、别处又裸写的词。
function bareRepeats(message) {
  const text = stripFences(String(message || ''))
  const terms = new Set()
  for (const m of text.matchAll(LINK_RE)) {
    if (!LOCAL_URL.test(m[2])) continue
    for (const t of termsOf(cleanLabel(m[1]))) terms.add(t)
  }
  if (!terms.size) return []
  let hay = text
    .replace(LINK_RE, ' ')
    .replace(/<(?:file|vscode|https?):\/\/[^>\s]*>/g, ' ')
    .replace(/(?:file|vscode|https?):\/\/\S+/g, ' ')
  // 行内代码：恰好等于某个词的留下（算裸写），其余整段去掉
  hay = hay.replace(/`([^`\n]+)`/g, (_, code) => (terms.has(code.trim()) ? ` ${code.trim()} ` : ' '))
  const out = []
  // 长词先数，数完从文本里挖掉，避免「README.md:12」与「README.md」重复计数
  for (const t of [...terms].sort((a, b) => b.length - a.length)) {
    const c = countBare(hay, t)
    if (c > 0) {
      out.push({ term: t, count: c })
      hay = hay.split(t).join(' ')
    }
  }
  return out
}

// 链接后紧跟的括注原文：[词](本机链接)（「原文」）。带 #行号 的按行号附近逐字比对；不带 # 的
// （词条文件）在整个文件里逐字比对——词条里装的就是摘录。返回 [{ label, quote, problem }]。
const QUOTE_RE = /\[([^\]\n]+)\]\(((?:file:\/\/|vscode:\/\/file)[^)\s]+)\)\s*[（(]\s*「([^」\n]+)」[^）)\n]{0,40}[）)]/g

function quoteProblems(message) {
  const text = stripFences(String(message || ''))
  const out = []
  for (const m of text.matchAll(QUOTE_RE)) {
    const label = cleanLabel(m[1])
    const url = m[2]
    const quote = m[3]
    let problem = null
    if (/^file:\/\/\/.+#L?\d+$/.test(url) || /^vscode:\/\/file\/.+:\d+(?::\d+)?$/.test(url)) {
      problem = checkExcerpt([quote], url, '/nonexistent/claude-wiki-reply.md', null)
      if (problem && /词条目录/.test(problem)) problem = null
    } else if (/^file:\/\/\/[^#]+$/.test(url)) {
      let file = url.slice('file://'.length)
      try { file = decodeURIComponent(file) } catch { /* 原样 */ }
      let body
      try { body = fs.readFileSync(file, 'utf8') } catch { problem = `链接的文件读不到：${file}` }
      if (body != null) {
        const whole = norm(body)
        const frags = quote.split(/……|…|\.\.\./).map(norm).filter(Boolean)
        const bad = frags.find((f) => !whole.includes(f))
        if (bad) problem = `括注「${bad.length > 20 ? bad.slice(0, 19) + '…' : bad}」在链接的文件里找不到逐字原文`
      }
    }
    if (problem) out.push({ label, quote, problem })
  }
  return out
}

function termLinksReason(message) {
  const hits = bareRepeats(message)
  const quotes = quoteProblems(message)
  if (!hits.length && !quotes.length) return ''
  const lines = ['回合末链接核对（机械比对，不经模型）：']
  if (hits.length) {
    const shown = hits.map((h) => `「${h.term}」${h.count} 处`).join('、')
    lines.push(`- 挂过链接的词别处又裸写：${shown}。像 wiki 一样，本条回复里挂过链接的词每次出现都挂同一个链接；行内代码里单独写这个词也算，改成链接；围栏代码块与命令内部不算。`)
  }
  for (const q of quotes) {
    lines.push(`- 「${q.label}」后的括注原文对不上：${q.problem}。括注只放从链接处逐字摘的原文；摘不到就删掉括注，写「（未找到出处）」。`)
  }
  lines.push('改完把整条回复完整重写一遍；只有链接问题时不写更正块。')
  return lines.join('\n')
}

module.exports = { termLinksReason, quoteProblems, bareRepeats, termsOf, countBare }
