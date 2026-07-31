// shell-parse.js — Bash 命令字符串的轻量解析工具
//
// 【为什么存在】
// 多个 PreToolUse guard（block-cd / agent-browser-launch / nonascii-path）都要把
// 一条 Bash 命令字符串切成"顶层命令片段"再逐段判定。此前 splitSegments 在
// block-cd.js 与 agent-browser-launch.js 里各有一份逐字符相同的实现，第三个
// guard 落地时会变成三份——抽到此处作为单一真相源。
//
// 【设计边界】
// 这不是完整的 shell 语法解析器，只覆盖 guard 判定需要的部分：命令分隔符切分、
// 引号感知、子 shell 剥离、heredoc 剥离、token 切分。不处理变量展开、glob 展开、
// 转义序列语义（除 `\"` 外）。guard 判定容许少量误差——宁可放行也不误拦，
// 各 guard 自己承担"命中后再确认"的责任。
//
// 【已知边界：stripSubshells 的括号匹配不感知引号】
// `\([^()]*\)` 是纯字符匹配，引号里一个不成对的 `(` 会跟后面某个 `)` 配对，把中间
// 的真实内容一起吃掉。2026-07-31 审计实测对照：
//   `echo "(start" && cd /tmp && echo "end)"` → cd 被整段剥离（调用方看不到它）
//   `echo "a)" && cd /tmp`                    → 只有 ) 没有 (，剥不掉，调用方能看到
// 这意味着调用方拿到的"剥离后命令"可能少了真实存在的命令片段。方向是**放行**
// （少看到东西 → 少拦），符合本模块"宁可放行也不误拦"的取向，但调用方不能据此
// 声称自己"精确"覆盖了某类语义。
//
// 【导出】
// - splitSegments(cmd)   : 按 `; && || |` 与换行切分顶层片段，引号内的分隔符不切
// - tokenize(segment)    : 按空白切 token，引号内空白不切（保留引号字符）
// - stripQuotes(token)   : 去掉 token 首尾成对的单/双引号
// - stripSubshells(cmd)  : 递归剥离 $(...) / `...` / (...) 三类子 shell
// - stripHeredocs(cmd)   : 剥离 heredoc 正文（`<<EOF` / `<<-EOF` / `<<'EOF'` 到定界符行）

'use strict'

// 按命令分隔符（; && || | 换行）切分顶层片段，引号内的分隔符不参与切分。
function splitSegments(cmd) {
  const segments = []
  let cur = ''
  let inDouble = false
  let inSingle = false
  for (let i = 0; i < cmd.length; i++) {
    const c = cmd[i]
    const prev = cmd[i - 1]
    if (!inSingle && c === '"' && prev !== '\\') {
      inDouble = !inDouble
      cur += c
      continue
    }
    if (!inDouble && c === "'") {
      inSingle = !inSingle
      cur += c
      continue
    }
    if (!inDouble && !inSingle) {
      if (c === '\n' || c === ';') {
        segments.push(cur)
        cur = ''
        continue
      }
      if (c === '&' && cmd[i + 1] === '&') {
        segments.push(cur)
        cur = ''
        i++
        continue
      }
      if (c === '|' && cmd[i + 1] === '|') {
        segments.push(cur)
        cur = ''
        i++
        continue
      }
      if (c === '|') {
        segments.push(cur)
        cur = ''
        continue
      }
    }
    cur += c
  }
  if (cur.trim()) segments.push(cur)
  return segments
}

// 按空白切分 token，引号内的空白不切（保留引号字符本身，交给 stripQuotes 处理）
function tokenize(segment) {
  const tokens = []
  let cur = ''
  let inDouble = false
  let inSingle = false
  for (let i = 0; i < segment.length; i++) {
    const c = segment[i]
    if (!inSingle && c === '"') {
      inDouble = !inDouble
      cur += c
      continue
    }
    if (!inDouble && c === "'") {
      inSingle = !inSingle
      cur += c
      continue
    }
    if (!inDouble && !inSingle && /\s/.test(c)) {
      if (cur) {
        tokens.push(cur)
        cur = ''
      }
      continue
    }
    cur += c
  }
  if (cur) tokens.push(cur)
  return tokens
}

function stripQuotes(token) {
  if ((token.startsWith('"') && token.endsWith('"')) || (token.startsWith("'") && token.endsWith("'"))) {
    return token.slice(1, -1)
  }
  return token
}

// 剥离所有子 shell（递归处理嵌套）：
//   $(...)   命令替换
//   `...`    反引号命令替换
//   (...)    子 shell（含 (cd && cmd) 这种）
// 剥离后剩下的就是会影响父 shell 状态的部分。
function stripSubshells(cmd) {
  let prev
  let result = cmd
  do {
    prev = result
    // 反引号：成对剥离
    result = result.replace(/`[^`]*`/g, '')
    // $(...)：最内层优先
    result = result.replace(/\$\([^()]*\)/g, '')
    // (...)：最内层优先（在 $() 之后处理，避免吃掉 $）
    result = result.replace(/\([^()]*\)/g, '')
  } while (result !== prev)
  return result
}

// ── heredoc 剥离 ─────────────────────────────────────────────────────
//
// 为什么需要：heredoc 正文是喂给**别的**解释器或**远端主机**的文本，不是本地 shell
// 命令。但正文里的换行会被 splitSegments 当成命令分隔符，于是正文里任何一行都会被
// 当作独立的本地命令来判定。2026-07-31 审计实测的两条误杀：
//   ssh prod bash -s <<'EOF' / cd /srv/app / git pull / EOF   → cd 在远程执行，被判本地污染
//   python3 - <<'EOF' / print(1) / cd /tmp / EOF              → 正文根本不是 shell 命令
// 更糟的是各 guard 给出的处置建议（改绝对路径 / 套子 shell）对 heredoc 正文无从下手。
//
// 覆盖：`<<DELIM` / `<<-DELIM` / `<<'DELIM'` / `<<"DELIM"`，一行内多个 heredoc 按
// 出现顺序依次消费正文。不覆盖：`<<<`（here-string，已显式排除）、定界符含特殊字符
// 的形态、跨行续行符拼出的 `<<`。定界符缺失结束行时把剩余内容全部丢弃（保守放行）。

// 逐字符标记该行每个位置是否处在引号内。每行独立重置状态——heredoc 正文里的
// 不平衡引号不应影响后续行的判定。
function quoteMaskLine(line) {
  const mask = new Array(line.length).fill(false)
  let inDouble = false
  let inSingle = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    const prev = line[i - 1]
    if (!inSingle && c === '"' && prev !== '\\') {
      inDouble = !inDouble
      mask[i] = true
      continue
    }
    if (!inDouble && c === "'") {
      inSingle = !inSingle
      mask[i] = true
      continue
    }
    mask[i] = inDouble || inSingle
  }
  return mask
}

// `<<-?` 后跟定界符；`(?!<)` 排除 here-string `<<<`
const HEREDOC_START = /<<-?(?!<)\s*(?:'([^']+)'|"([^"]+)"|\\?([A-Za-z_][A-Za-z0-9_]*))/g

// 返回该行按出现顺序声明的所有 heredoc 定界符（不含引号内的伪匹配）
function findHeredocDelimiters(line) {
  if (!line.includes('<<')) return []
  const mask = quoteMaskLine(line)
  const delimiters = []
  HEREDOC_START.lastIndex = 0
  let m
  while ((m = HEREDOC_START.exec(line)) !== null) {
    if (mask[m.index]) continue // `<<` 本身在引号里，不是 heredoc 声明
    delimiters.push(m[1] !== undefined ? m[1] : m[2] !== undefined ? m[2] : m[3])
  }
  return delimiters
}

// 保留声明行（它是真实命令），丢弃正文行与定界符行
function stripHeredocs(cmd) {
  if (!cmd.includes('<<')) return cmd
  const lines = cmd.split('\n')
  const kept = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    kept.push(line)
    const delimiters = findHeredocDelimiters(line)
    i++
    for (const delimiter of delimiters) {
      while (i < lines.length) {
        const isTerminator = lines[i].trim() === delimiter
        i++
        if (isTerminator) break
      }
    }
  }
  return kept.join('\n')
}

module.exports = { splitSegments, tokenize, stripQuotes, stripSubshells, stripHeredocs }
