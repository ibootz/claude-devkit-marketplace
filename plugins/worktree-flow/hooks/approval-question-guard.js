#!/usr/bin/env node
// approval-question-guard.js — 防止 AI 伪造 Human 的 worktree-flow 授权回答
//
// 固定授权问题若带 answers / annotations 预填字段，PreToolUse 直接拒绝。只有 AskUserQuestion UI
// 真正返回的 tool_response 才可触发 PostToolUse 写授权状态。

'use strict'

const fs = require('fs')
const { APPROVAL_SOURCE, isApprovalRequest } = require('./lib/round-approval')

function main() {
  if (process.env.WORKTREE_GUARD === 'off') process.exit(0)

  let payload
  try {
    payload = JSON.parse(fs.readFileSync(0, 'utf8'))
  } catch (_) {
    process.exit(0)
  }

  const input = payload.tool_input
  if (!input || input.metadata?.source !== APPROVAL_SOURCE) process.exit(0)

  if (!isApprovalRequest(input)) {
    process.stderr.write(
      '[L1-BLOCKER] tool=AskUserQuestion check=worktree-flow-approval finding="worktree-flow 授权问题结构不符，或携带了 AI 预填的 answers/annotations" hint="必须原样使用 main-branch-guard finding 给出的 AskUserQuestion 输入；不得传 answers 或 annotations，由 Human 在 UI 中亲自选择"\n'
    )
    process.exit(2)
  }

  process.exit(0)
}

main()
