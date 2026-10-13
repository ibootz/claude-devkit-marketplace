#!/usr/bin/env node
// zh-disambiguate 形式层扫描：只预警，不判定合规。
//
// 报三类：
//   long        句长（去掉空白后的字符数）超过阈值，默认 60
//   multi-step  一句里出现 >=2 个串联动作的连接词（并 / 再 / 然后 / 同时 / 接着 / 随后）
//   deixis      句首用 该 / 此 / 上述 / 这个 / 那个 指代
//
// 跳过：围栏代码块、行内代码、markdown 表格分隔行、frontmatter。
// 切句：按 。！？；!? 与换行切。列表项、表格单元按行处理。
//
// 用法：node scan.js [--max N] <file>...
// 输出：<file>:<line>: [<kind>] <句子摘录>，末行给统计。退出码恒为 0。

'use strict'

const fs = require('fs')

const CONNECTORS = ['然后', '同时', '接着', '随后', '并', '再']
const DEIXIS = /^(该|此|上述|这个|那个)/

function parseArgs(argv) {
  let max = 60
  const files = []
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--max') max = Number(argv[++i])
    else files.push(argv[i])
  }
  return { max, files }
}

function countConnectors(s) {
  let n = 0
  let rest = s
  for (const c of CONNECTORS) {
    const parts = rest.split(c)
    n += parts.length - 1
    rest = parts.join('\u0000')
  }
  return n
}

function scanFile(file, max) {
  const lines = fs.readFileSync(file, 'utf8').split(/\r?\n/)
  const hits = []
  let inFence = false
  let inFront = lines[0] === '---'
  lines.forEach((raw, idx) => {
    const lineNo = idx + 1
    if (inFront) {
      if (idx > 0 && raw === '---') inFront = false
      return
    }
    if (/^\s*(```|~~~)/.test(raw)) {
      inFence = !inFence
      return
    }
    if (inFence) return
    if (/^\s*\|?\s*:?-{3,}/.test(raw)) return
    const text = raw
      .replace(/`[^`]*`/g, '')
      .replace(/\]\([^)]*\)/g, ']')
      .replace(/^\s*(#+|[-*+]|\d+\.|>)\s*/, '')
    const cells = text.includes('|') ? text.split('|') : [text]
    for (const cell of cells) {
      for (const sentence of cell.split(/[。！？；!?]/)) {
        const s = sentence.replace(/\s+/g, '').replace(/^[*_]+|[*_]+$/g, '')
        if (!s) continue
        const excerpt = s.length > 40 ? s.slice(0, 40) + '…' : s
        if (s.length > max) hits.push(`${file}:${lineNo}: [long ${s.length}] ${excerpt}`)
        const n = countConnectors(s)
        if (n >= 2) hits.push(`${file}:${lineNo}: [multi-step ${n}] ${excerpt}`)
        if (DEIXIS.test(s)) hits.push(`${file}:${lineNo}: [deixis] ${excerpt}`)
      }
    }
  })
  return hits
}

function main() {
  const { max, files } = parseArgs(process.argv.slice(2))
  if (!files.length) {
    console.log('用法：node scan.js [--max N] <file>...')
    return
  }
  let total = 0
  for (const f of files) {
    let hits
    try {
      hits = scanFile(f, max)
    } catch (e) {
      console.log(`${f}: 读取失败：${e.message}`)
      continue
    }
    hits.forEach((h) => console.log(h))
    total += hits.length
  }
  console.log(`共 ${total} 条预警（阈值 ${max} 字）。预警不等于有问题，逐条判定。`)
}

main()
