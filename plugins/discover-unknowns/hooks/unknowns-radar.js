// unknowns-radar.js — UserPromptSubmit hook
// 每轮注入一段极短的"未知雷达"：3 条各给一个当轮可自检的触发条件（"没读过要改的
// 模块""用户给了参考实现""编码中想抄近路"等），不用"任务含糊/领域陌生"这类
// 无法自检的软提示；执行细则留在 skill 里（/discover-unknowns、/brainstorm）。
// 刻意保持 4 条以内，避免与 working-discipline 等每轮注入插件的指令重叠。
//
// 2.2.0 起不再注入"合并前先跑 /quiz"：quiz 改为纯按需触发，只有用户明确要求时
// 才出报告与测验，merge/push 默认不受测验阻挡。
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
    '- 没读过要改模块、或无验收标准：先跑 /discover-unknowns 或 /brainstorm，别凭猜测开工。',
    '- 有参考实现：先复述理解的语义对齐，再复刻语义而非逐行抄——语言/框架差异别当行为差异搬进来。',
    '- 想绕开既定方案抄近路：这是新暴露的未知，选保守方案、告知用户偏离处，不悄悄变通。',
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
