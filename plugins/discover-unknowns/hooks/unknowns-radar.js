// unknowns-radar.js — UserPromptSubmit hook
// 每轮注入一段极短的"未知雷达"：只提醒"何时该想起发现未知的方法论"，
// 具体执行细则全部留在 skill 里（/discover-unknowns、/brainstorm、/quiz）。
// 刻意保持 4 条以内、路标级措辞，避免与 working-discipline 等每轮注入插件的指令重叠。
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
    '- 任务含糊、领域陌生或颗粒度过大时：先暴露未知再动手——按需进入 /discover-unknowns（盲点扫描/参考）或 /brainstorm（发散原型 + 一问一答收敛），不要抓起第一条相关命令就实现。',
    '- 用户给出参考实现/样例（源代码最佳）时：先复述你理解到的语义与用户对齐，再复刻语义而非细节。',
    '- 实现中撞上迫使偏离既定方案的边界情况：这是新暴露的未知——选保守方案、显式记录偏离并告知用户，不要静默变通。',
    '- 长会话大量变更后用户要合并时：建议先 /quiz 确认理解再 merge。',
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
