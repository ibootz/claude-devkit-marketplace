// orchestrator-protocol-remind.js — UserPromptSubmit hook
//
// 用户每次提交消息时，向 AI 上下文注入一句"你必须委派给 ompi"的精简提醒。
// 与 orchestrator-protocol-init.js 配合：本 hook 持续提醒（短），init 立纪律（长）。
//
// 设计前提：AI 在长会话中会逐渐淡化 SessionStart 注入的协议，需要在每个用户回合
// 重新上膛。但要短，避免上下文污染。
//
// Trigger: UserPromptSubmit
// Output: hookSpecificOutput.additionalContext → 拼到当前用户消息后的上下文

'use strict'

function main() {
  // 读 stdin（Claude Code 会把当前用户 prompt 通过 JSON 传入）以判断是否豁免
  let stdinRaw = ''
  try {
    stdinRaw = require('fs').readFileSync(0, 'utf-8')
  } catch (e) {
    stdinRaw = ''
  }

  let userPrompt = ''
  try {
    const parsed = JSON.parse(stdinRaw)
    userPrompt = String(parsed.prompt || parsed.user_prompt || '')
  } catch (e) {
    userPrompt = stdinRaw
  }

  // 用户当前消息显式豁免 → 不注入提醒，让 AI 自由执行
  const EXEMPT_PATTERNS = [
    /你\s*直接\s*\S+/,            // "你直接 X"（X 任意，例如"你直接读"/"你直接帮我看"/"你直接告诉我"）
    /直接\s*(帮|去|来)\s*\S+/,   // "直接帮/去/来 X"
    /不用\s*ompi/,
    /别\s*用\s*ompi/,
    /先?不要?\s*委派/,
    /不\s*通过\s*ompi/,
    /no\s+ompi/i,
    /skip\s+ompi/i,
    /direct(ly)?\s+(do|read|write|edit|run|tell|answer)/i,
  ]
  if (EXEMPT_PATTERNS.some(re => re.test(userPrompt))) {
    process.exit(0)
  }

  const reminder = [
    '<ompi-reminder>',
    '⚠ 本会话激活了 ompi Orchestrator-Worker 协议（详见 SessionStart 注入的完整版）。',
    '',
    '回复前自检四条：',
    '1. 我打算调 Read / Edit / Write / Grep / Glob？→ **停**。改 `omp -p` 委派。',
    '2. 我打算用 Bash 跑非 `omp -p` 命令？→ **停**。改 `omp -p` 委派。',
    '3. 我用"我看到 / 我记得"代替查事实？→ **停**。让 ompi 拿事实。',
    '4. 我打算"先想详细方案，再让 ompi 落地写文件"？→ **停**。这是假委派——让 ompi 自己想方案，你只描述目标和约束。',
    '',
    '价值划分铁律：思考、设计、列大纲、分析 RCA、总结 = ompi 的活；你的活只有 Why / Whether / 审阅 / 修订指令 4 件。',
    '',
    '唯一豁免 = 用户**当前**消息明说"你直接做" / "不用 ompi"。',
    '本能上的"自己干更快" / "这事很小" / "就看一眼" / "我先想清楚再委派" 全部无效。',
    '</ompi-reminder>',
  ].join('\n')

  const output = {
    hookSpecificOutput: {
      hookEventName: 'UserPromptSubmit',
      additionalContext: reminder,
    },
  }

  process.stdout.write(JSON.stringify(output) + '\n')
  process.exit(0)
}

main()
