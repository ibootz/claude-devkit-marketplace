// orchestrator-protocol-remind.js — UserPromptSubmit hook
//
// 用户每次提交消息时，向 AI 注入 omp 编排协议的精简提醒。
// 与 orchestrator-protocol-init.js 配合：本 hook 持续提醒（短），init 立纪律（长）。
// 主模型 = Orchestrator（思考+编排），omp = Worker（机械执行）。
// 决策标准：按认知价值分层，而非按工具类型一刀切。
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
    /你\s*直接\s*\S+/, // "你直接 X"（X 任意，例如"你直接读"/"你直接帮我看"/"你直接告诉我"）
    /直接\s*(帮|去|来)\s*\S+/, // "直接帮/去/来 X"
    /不用\s*omp/,
    /别\s*用\s*omp/,
    /先?不要?\s*委派/,
    /不\s*通过\s*omp/,
    /no\s+omp/i,
    /skip\s+omp/i,
    /direct(ly)?\s+(do|read|write|edit|run|tell|answer)/i,
  ]
  if (EXEMPT_PATTERNS.some((re) => re.test(userPrompt))) {
    process.exit(0)
  }

  const reminder = [
    '<omp-reminder>',
    '本会话激活了 omp 编排协议（详见 SessionStart 注入的完整版）。',
    '',
    '决策标准：**这属于机械化执行，还是需要思考/判断/编排？**',
    '',
    '- 你在**想**（分析、设计、编排、审阅、快速定位上下文）→ 自己做，该用工具就用',
    '- 你已经**想好了**，只需要**执行** → `omp -p`',
    '- 执行量会**吃掉大量 token**（长输出、多文件、重复操作、批量修改）→ `omp -p`',
    '',
    '给 omp 目标和约束，不要手把手写步骤。',
    '</omp-reminder>',
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
