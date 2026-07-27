// notify-once.js — 「同一轮只提醒一次」的去重状态
//
// 【为什么存在】
// 条件注入类 hook（external-write-readback / nonascii-path）会在同一轮里被多次触发
// （一轮里连续跑 5 条 curl 写命令是常态）。每次都注入同一段长文本会把上下文重新撑大，
// 恰好复现本插件要解决的问题。本模块提供按 (scope, session, prompt, tier) 去重的判定。
//
// 【失败方向】
// 状态文件读写失败一律返回 true（照常注入）——宁可多提醒一次，不能因为临时目录不可写
// 就让提醒整体失效。去重只是体验优化，不是正确性依赖。
//
// 【存储位置】
// 系统临时目录（`os.tmpdir()`），文件名 `wd-<scope>-<session_id>.json`。放临时目录而非
// `~/.claude/` 是为了避免跨会话污染，且系统重启会自然清理；每个 scope 独立文件，避免
// 不同 guard 互相覆盖对方的记录。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')

// 单文件保留的 key 上限：一轮最多产生几个 key，200 足够覆盖长会话，
// 同时避免状态文件无限增长。
const MAX_KEYS = 200

function statePath(scope, sessionId) {
  const safeScope = String(scope).replace(/[^A-Za-z0-9_-]/g, '_')
  const safeSession = String(sessionId || 'nosession').replace(/[^A-Za-z0-9_-]/g, '_')
  return path.join(os.tmpdir(), `wd-${safeScope}-${safeSession}.json`)
}

// 返回 true = 这次应该注入（此前没提醒过）；false = 已提醒过，跳过。
function shouldNotify(scope, sessionId, promptId, tier) {
  if (!promptId) return true // 拿不到轮次标识就不去重，避免整轮漏提醒
  const file = statePath(scope, sessionId)
  const key = `${promptId}:${tier || 'default'}`

  let keys = []
  try {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8'))
    if (Array.isArray(parsed.keys)) keys = parsed.keys
  } catch (_) {
    keys = []
  }

  if (keys.includes(key)) return false

  keys.push(key)
  if (keys.length > MAX_KEYS) keys = keys.slice(-MAX_KEYS)
  try {
    fs.writeFileSync(file, JSON.stringify({ keys }), 'utf8')
  } catch (_) {
    // 写不进去最坏情况是下次同轮再提醒一次，可接受
  }
  return true
}

module.exports = { shouldNotify }
