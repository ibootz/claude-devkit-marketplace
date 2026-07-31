// unknowns-radar.js — UserPromptSubmit hook
// 每轮注入一段极短的"未知雷达"：4 条各给一个当轮可自检的触发条件（"没读过要改的
// 模块""用户给了参考实现""长会话+要 merge/push"等），不用"任务含糊/领域陌生"这类
// 无法自检的软提示；执行细则留在 skill 里（/discover-unknowns、/brainstorm、/quiz）。
// 刻意保持 4 条以内，避免与 working-discipline 等每轮注入插件的指令重叠。
//
// Trigger: UserPromptSubmit
// Output:  additionalContext → 注入到当前轮次 Claude 上下文
// Opt-out: 环境变量 DISCOVER_UNKNOWNS_RADAR=off（或 0）时不注入

'use strict'

function main() {
  const flag = (process.env.DISCOVER_UNKNOWNS_RADAR || '').toLowerCase()
  if (flag === 'off' || flag === '0' || flag === 'false') {
    process.exit(0)
  }

  const prompt = [
    '# 未知雷达（discover-unknowns）',
    '',
    '- 写代码前，若没读过要改的模块、或用户没给验收标准：先跑 /discover-unknowns 或 /brainstorm，不要凭猜测开工。',
    '- 用户给了参考实现/样例：先复述你理解的语义对齐，再复刻语义而非逐行抄——照抄会把参考的语言/框架差异当成行为差异搬进来。',
    '- 编码中撞上想绕开既定方案、抄近路的边界情况：这就是新暴露的未知——选保守方案、显式告知用户偏离处，禁止悄悄变通。',
    '- 长会话多处变更后用户要 merge/push 前：先跑 /quiz（硬性要求：未过测验不得 merge/push）。',
  ].join('\n')

  const output = {
    hookSpecificOutput: {
      hookEventName: 'UserPromptSubmit',
      additionalContext: prompt,
    },
  }

  process.stdout.write(JSON.stringify(output) + '\n')
  process.exit(0)
}

main()
