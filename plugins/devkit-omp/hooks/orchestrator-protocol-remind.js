// orchestrator-protocol-remind.js — UserPromptSubmit hook
//
// 用户每次提交消息时，向 AI 注入 omp 编排协议的精简提醒。
// 与 orchestrator-protocol-init.js 配合：本 hook 持续提醒（短），init 立纪律（长）。
// 主模型 = Orchestrator（思考+编排），omp = Worker（机械执行）。
// 决策标准：按认知价值分层，而非按工具类型一刀切。
//
// 开关：环境变量 OMP_PROTOCOL_ENABLED ∈ {1,true,on,yes}（大小写不敏感）才注入；
//       未设置 / 其他值 → 静默放行，不读 stdin 也不写任何上下文。
//
// Codex 宿主不注入：协议的唯一调用路径是「`Agent` 工具派发 omp-explore / omp-plan / omp-task」，
// Codex 没有 `Agent` 工具、也不加载插件的 agents/，注进去是一条做不到的指令。判据：环境变量
// PLUGIN_ROOT 非空或入参含 turn_id（与 devkit-task-keeper 的 debug_worktree_destroy_guard.py
// 同一判据；不用 CLAUDE_PLUGIN_ROOT，Codex 也设它）。用例见 hooks/tests/codex-host.test.js。
//
// Trigger: UserPromptSubmit
// Output: hookSpecificOutput.additionalContext → 拼到当前用户消息后的上下文

'use strict'

function isEnabled() {
  const v = String(process.env.OMP_PROTOCOL_ENABLED || '').trim().toLowerCase()
  return v === '1' || v === 'true' || v === 'on' || v === 'yes'
}

function isCodex(payload) {
  return Boolean(process.env.PLUGIN_ROOT) ||
    Boolean(payload && typeof payload === 'object' &&
      Object.prototype.hasOwnProperty.call(payload, 'turn_id'))
}

function main() {
  if (!isEnabled()) {
    process.exit(0)
  }

  // 读 stdin（Claude Code 会把当前用户 prompt 通过 JSON 传入）以判断是否豁免
  let stdinRaw = ''
  try {
    stdinRaw = require('fs').readFileSync(0, 'utf-8')
  } catch (e) {
    stdinRaw = ''
  }

  let userPrompt = ''
  let parsed = null
  try {
    parsed = JSON.parse(stdinRaw)
    userPrompt = String(parsed.prompt || parsed.user_prompt || '')
  } catch (e) {
    userPrompt = stdinRaw
  }
  if (isCodex(parsed)) {
    process.exit(0)
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
    'omp 协议已激活（完整版见 SessionStart）。',
    '',
    '决策标准：机械化执行，还是需要思考/判断/编排？',
    '',
    '- 在想（分析/设计/编排/审阅/定位上下文）→ 自己做',
    '- 想好只需执行，或执行量大（长输出/多文件/批量修改）→ Agent 工具派发 ' +
      'omp-explore/omp-plan/omp-task，不自拼 `omp -p`',
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
