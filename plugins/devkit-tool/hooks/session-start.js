#!/usr/bin/env node
// devkit-tool · SessionStart hook（会话级规则注入）
//
// 【作用】把 context/session-start.md 作为 additionalContext 注入会话
//   （matcher * 覆盖 compact，auto-compact 后自动重注）。规则随本插件分发，
//   2026-10-13 从用户级 ~/.claude/CLAUDE.md 迁入。
//
// 【失败策略】纯注入，读不到文件就静默退出，绝不阻断会话启动。
//
// 【Codex 宿主不注入（6.40.0 加）】注入内容整段讲跨会话通信：`ListAgents` / `SendMessage`、
//   `CLAUDE_CODE_MESSAGING_SOCKET`、resume 交接——全是 Claude Code 专属工具与机制，Codex
//   没有对应物，注进去只会让模型去找不存在的工具。判据：环境变量 PLUGIN_ROOT 非空或入参含
//   turn_id（与 devkit-task-keeper 的 debug_worktree_destroy_guard.py 同一判据；不用
//   CLAUDE_PLUGIN_ROOT，Codex 也设它）。Claude 侧输出逐字不变，见 hooks/tests/session-start-host.js。
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
function readPayload() {
  try {
    return JSON.parse(fs.readFileSync(0, 'utf8'))
  } catch (_) {
    return null
  }
}

function isCodex(payload) {
  return Boolean(process.env.PLUGIN_ROOT) ||
    Boolean(payload && typeof payload === 'object' &&
      Object.prototype.hasOwnProperty.call(payload, 'turn_id'))
}

function resolveEvent(payload) {
  if (payload === null) return EVENT
  const name = payload && payload.hook_event_name
  if (name === undefined || name === null || name === '') return EVENT
  return name === EVENT ? EVENT : null
}

function main() {
  const payload = readPayload()
  if (isCodex(payload)) process.exit(0)
  const event = resolveEvent(payload)
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
