#!/usr/bin/env node
// devkit-tool · SessionStart hook（会话级规则注入）
//
// 【作用】把 context/session-start.md 作为 additionalContext 注入会话
//   （matcher * 覆盖 compact，auto-compact 后自动重注）。规则随本插件分发，
//   2026-10-13 从用户级 ~/.claude/CLAUDE.md 迁入。
//
// 【失败策略】纯注入，读不到文件就静默退出，绝不阻断会话启动。
//
// Trigger: SessionStart（matcher *）
// Output:  additionalContext → 注入主会话上下文

'use strict'

const fs = require('fs')
const path = require('path')

const EVENT = 'SessionStart'
const CONTEXT_FILE = path.join(__dirname, '..', 'context', 'session-start.md')

// 入参事件名：读得到就用它（只认本 hook 挂的那个事件），读不到就按本事件处理。
// 返回 null 表示入参明确是别的事件——不回声来路不明的字符串，静默退出。
function resolveEvent() {
  let payload
  try {
    payload = JSON.parse(fs.readFileSync(0, 'utf8'))
  } catch (_) {
    return EVENT
  }
  const name = payload && payload.hook_event_name
  if (name === undefined || name === null || name === '') return EVENT
  return name === EVENT ? EVENT : null
}

function main() {
  const event = resolveEvent()
  if (!event) process.exit(0)

  let body
  try {
    body = fs.readFileSync(CONTEXT_FILE, 'utf8').trim()
  } catch (_) {
    process.exit(0)
  }
  if (!body) process.exit(0)

  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: event,
        additionalContext: body,
      },
    }) + '\n',
  )
  process.exit(0)
}

main()
