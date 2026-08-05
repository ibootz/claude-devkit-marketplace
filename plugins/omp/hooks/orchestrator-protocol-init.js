// orchestrator-protocol-init.js — SessionStart hook
//
// 在每次 Claude Code 会话开始时，向 AI 注入 omp 编排协议。
// 主模型 = Orchestrator（思考、规划、编排、审阅），omp 命名子代理 = Worker（机械执行）。
// 决策标准：按认知价值分层，而非按工具类型一刀切。
//
// 与 orchestrator-protocol-remind.js 配合：本 hook 立纪律（详细版，含分类举例），
// remind 每轮只重申决策标准本身（不重发这里的分类举例）。
//
// 开关：环境变量 OMP_PROTOCOL_ENABLED ∈ {1,true,on,yes}（大小写不敏感）才注入；
//       未设置 / 其他值 → 静默放行，不写任何上下文。
//
// Trigger: SessionStart
// Output: hookSpecificOutput.additionalContext → 注入到 Claude 上下文

'use strict'

function isEnabled() {
  const v = String(process.env.OMP_PROTOCOL_ENABLED || '').trim().toLowerCase()
  return v === '1' || v === 'true' || v === 'on' || v === 'yes'
}

function main() {
  if (!isEnabled()) {
    process.exit(0)
  }

  const protocol = [
    '<EXTREMELY-IMPORTANT>',
    '# omp 协议：你=Orchestrator（思考+编排），omp 命名子代理=Worker（机械执行）。',
    '',
    '## 决策树',
    '问自己：这属于机械化执行，还是需要思考/判断/编排？',
    '',
    '### 你自己做',
    '- 需求理解、方案设计、技术选型、架构判断',
    '- 流程编排：拆分/排序/并发策略；审阅子代理结果，决定接受/打回/追问',
    '- 快速取上下文：read/grep/bash 小命令；纯讨论/概念解释',
    '- 用户写"你直接做"/"不用 omp"',
    '',
    '### 委派给 omp 命名子代理',
    '- 大规模代码实现/重构/批量修改、已有清晰方案只需执行 → omp-task',
    '- 代码库探索/依赖追踪/模式搜索（>5 文件或 >10 次 grep）→ omp-explore',
    '- 架构设计/技术方案/任务拆解 → omp-plan',
    '- 长输出命令（构建、测试、日志分析、git log/diff）→ omp-task',
    '',
    '## prompt 写法',
    '给明确目标和约束，让子代理自主完成，不要手把手写步骤。',
    '✅ "在 src/auth/ 下实现 JWT 刷新逻辑，参考 token.ts 的错误处理模式"',
    '❌ "第 42 行插入 `const token = ...`，第 58 行..."',
    '',
    '## 调用方式',
    '唯一路径：Agent 工具派发 omp-explore/omp-plan/omp-task，禁止自拼 `omp -p`。',
    'prompt 含 5 要素：【目标】【上下文】【约束】【期望输出】【角色指令】。',
    '',
    '角色指令须显式取角色，否则落 default、推理深度不足：',
    '- omp-explore/omp-task → `--model "$(omp config get modelRoles | jq -r .task)"`',
    '- omp-plan             → `--model "$(omp config get modelRoles | jq -r .plan)"`',
    '',
    '链路：explore → plan → task（每段验收），简单任务可单段直达。',
    '',
    '## 优先级',
    '用户当前消息显式豁免 > 本协议。',
    '</EXTREMELY-IMPORTANT>',
  ].join('\n')

  const output = {
    hookSpecificOutput: {
      hookEventName: 'SessionStart',
      additionalContext: protocol,
    },
  }

  process.stdout.write(JSON.stringify(output) + '\n')
  process.exit(0)
}

main()
