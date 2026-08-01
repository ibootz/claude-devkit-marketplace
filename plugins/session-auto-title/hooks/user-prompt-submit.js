#!/usr/bin/env node
// user-prompt-submit.js — session-auto-title 的 hook 本体
//
// 【为什么挂 UserPromptSubmit 而不是 SessionStart】
// 两个事件的 hookSpecificOutput schema 都有 sessionTitle 字段，但落地路径不同：
// UserPromptSubmit 会把标题写进会话 jsonl 的 custom-title 行（与 /rename 完全同一条路径），
// SessionStart 只改内存——终端标题和输入框徽章会变，但 /resume 列表里看不到。
// 2026-08-01 用隔离环境实测确认过 UserPromptSubmit 这条路径确实落盘、且能反复覆盖。
//
// 【为什么必须异步】
// UserPromptSubmit 是阻塞的：它跑多久，用户按下回车后就要等多久。生成标题要调一次模型
// （几秒），同步做等于每轮都卡顿。所以本脚本只做三件快事——回填上一次的结果、数轮数、
// 决定要不要起后台生成——全程不发起任何网络请求。代价是标题永远慢一轮。
//
// 【防递归】
// 后台起的 `claude -p` 自身也是一个 Claude Code 会话，也会触发本 hook。不拦就是
// 每个生成进程再生成一个，指数爆炸。两道防护：子进程带 CLAUDE_AUTO_TITLE_CHILD 环境
// 变量（本脚本第一件事就是检查它），以及每会话一个带时间戳的锁文件。
//
// 【失败策略】任何异常都静默 exit 0。这个 hook 的价值远低于「不打断用户」。

'use strict'

const fs = require('fs')
const path = require('path')
const { spawn } = require('child_process')

const S = require('./lib/shared.js')

function emit(title) {
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'UserPromptSubmit',
        sessionTitle: title,
      },
    })
  )
}

function readStdin() {
  try {
    return JSON.parse(fs.readFileSync(0, 'utf8'))
  } catch {
    return null
  }
}

// 锁存在且未过期 = 已有一个生成进程在跑，不要重复发起。
function generationInFlight(sessionId) {
  try {
    const stat = fs.statSync(S.lockPath(sessionId))
    return Date.now() - stat.mtimeMs < S.LOCK_STALE_MS
  } catch {
    return false
  }
}

function main() {
  // 防递归第一道：后台生成进程里不再做任何事。
  if (process.env[S.CHILD_ENV_FLAG]) return

  const payload = readStdin()
  if (!payload) return

  const sessionId = payload.session_id
  const transcriptPath = payload.transcript_path
  if (!sessionId || !transcriptPath) return

  const state = S.readState(sessionId)

  // 回填：上一轮后台生成的结果在这里交出去。这是本脚本唯一会产生输出的分支。
  if (state.pendingTitle && state.pendingTitle !== state.appliedTitle) {
    emit(state.pendingTitle)
    state.appliedTitle = state.pendingTitle
    state.appliedAt = new Date().toISOString()
    try {
      S.writeState(sessionId, state)
    } catch {
      // 写不回去只会导致下一轮重复输出同一个标题，Claude Code 侧对相同值有幂等判断，无害。
    }
  }

  const { turns, work } = S.scanTranscript(transcriptPath)
  const lastGenTurn = Number(state.lastGenTurn) || 0
  const lastGenWork = Number(state.lastGenWork) || 0

  // 两条独立的到期判据，命中任一即生成：
  //   轮数——多轮对话的常规路径，首次第 FIRST_TURN 轮、之后每 REGEN_INTERVAL 轮；
  //   工作量——单 prompt 长会话的兜底，轮数永远不涨，只能看 assistant 行数。
  // lastGenWork 的 `> 0` 守卫是为了旧 state 兼容：1.0.0 写的缓存没有这个字段，
  // 缺省 0 会让任何长会话在升级后立刻重算一次；加上守卫就退回纯轮数判据。
  // 工作量分支额外要求 turns >= 1：没有任何真人 prompt 就没有素材，
  // generate-title.js 会直接返回不写 state，于是 lastGenTurn 恒为 0、
  // firstDue 每轮都成立——白跑一个子进程且永不收敛。
  const firstDue =
    lastGenTurn === 0 &&
    (turns >= S.FIRST_TURN || (turns >= 1 && work >= S.FIRST_WORK_LINES))
  const regenDue =
    lastGenTurn > 0 &&
    (turns - lastGenTurn >= S.REGEN_INTERVAL ||
      (lastGenWork > 0 && work - lastGenWork >= S.REGEN_WORK_LINES))
  if (!firstDue && !regenDue) return

  if (generationInFlight(sessionId)) return

  const generator = path.join(__dirname, 'generate-title.js')
  try {
    const child = spawn(
      process.execPath,
      [generator, sessionId, transcriptPath, String(turns), String(work)],
      {
        detached: true,
        stdio: 'ignore',
        env: Object.assign({}, process.env, { [S.CHILD_ENV_FLAG]: '1' }),
      }
    )
    child.unref()
  } catch {
    // 起不来就算了，下一轮还会再试。
  }
}

try {
  main()
} catch {
  // 静默降级
}
process.exit(0)
