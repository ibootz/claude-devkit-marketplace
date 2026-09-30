// shell-parse.js — Bash 命令字符串的轻量解析工具
//
// 【为什么存在】
// 多个 PreToolUse guard（历史上的 block-cd / agent-browser-launch / nonascii-path）都要把
// 一条 Bash 命令字符串切成"顶层命令片段"再逐段判定。splitSegments 曾在两个 guard 里各有
// 一份逐字符相同的实现，第三个 guard 落地时会变成三份——抽到此处作为单一真相源。
//
// 【3.26.0 起只剩 bash-guard 一个消费者，导出面随之收窄】
// 独立 cd 检查整体搬去了 `cd-blocker` 插件，它带走了自己那半：`stripSubshells` 与
// `stripHeredocs`（连同 heredoc 定界符解析）现住在 `plugins/cd-blocker/hooks/lib/shell-parse.js`
// 那份副本里。本文件删掉它们不是精简，是**去掉无消费者的代码**——留着会让读者以为
// 还有 guard 在用。要恢复时从那份副本拷回，两份的实现当时逐字相同。
//
// 【设计边界】
// 这不是完整的 shell 语法解析器，只覆盖 guard 判定需要的部分：命令分隔符切分、
// 引号感知、token 切分。不处理变量展开、glob 展开、转义序列语义（除 `\"` 外）。
// guard 判定容许少量误差——宁可放行也不误拦，各 guard 自己承担"命中后再确认"的责任。
//
// 【导出】
// - splitSegments(cmd)   : 按 `; && || |` 与换行切分顶层片段，引号内的分隔符不切
// - tokenize(segment)    : 按空白切 token，引号内空白不切（保留引号字符）
// - stripQuotes(token)   : 去掉 token 首尾成对的单/双引号

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

module.exports = { splitSegments, tokenize, stripQuotes }
