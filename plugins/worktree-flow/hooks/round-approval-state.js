#!/usr/bin/env node
// round-approval-state.js — main/master 本轮授权状态机
//
// UserPromptSubmit / Stop / SessionEnd：撤销该 session 的本轮授权。
// PostToolUse(AskUserQuestion)：仅当工具输入逐字段匹配本插件的固定问题，且 Human 选择
// “批准本轮”时，才写入 session-scoped 临时授权。拒绝、改走 worktree、无法解析回执皆 fail-closed。

'use strict'

const fs = require('fs')
const {
  APPROVAL_SOURCE,
  grantRound,
  isApprovalResponse,
  revokeRound,
} = require('./lib/round-approval')

const CLEAR_EVENTS = new Set(['SessionStart', 'UserPromptSubmit', 'Stop', 'SessionEnd'])

function main() {
  if (process.env.WORKTREE_GUARD === 'off') process.exit(0)

  let payload
  try {
    payload = JSON.parse(fs.readFileSync(0, 'utf8'))
  } catch (_) {
    process.exit(0)
  }

  const event = payload.hook_event_name
  const sessionId = payload.session_id

  if (CLEAR_EVENTS.has(event)) {
    revokeRound(sessionId)
    process.exit(0)
  }

  if (event !== 'PostToolUse' || payload.tool_name !== 'AskUserQuestion') {
    process.exit(0)
  }
  if (payload.tool_input?.metadata?.source !== APPROVAL_SOURCE) process.exit(0)
  if (!isApprovalResponse(payload)) {
    revokeRound(sessionId)
    process.exit(0)
  }

  if (grantRound(sessionId)) {
    process.stdout.write('worktree-flow：Human 已批准本轮 main/master 写入；下次用户消息或本轮结束时自动恢复保护。\n')
  } else {
    revokeRound(sessionId)
  }
  process.exit(0)
}

main()
