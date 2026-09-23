#!/usr/bin/env node
// wenyan-output-style · UserPromptSubmit hook（每轮短锚）
//
// 【作用】每轮注一行，对抗「回落现代白话」的漂移。静态规则全文不在这里——它在
//   SessionStart 注入里（hooks/session-start.js），每轮重复注入全文只会白烧上下文。
//
// 【为什么需要每轮】文言与模型默认语体正面对抗，属于「对抗 system prompt 的段落」，
//   实测这类约束只放 SessionStart 会在长对话里衰减。参照 caveman 上游同样的两层设计。
//
// 【改动纪律】这一行是每轮成本，上限 300 字符（tests 钉住）。加内容前先问「不加会不会
//   漂」。不会漂的写进 style/wenyan-ultra-rules.md，不要往这里堆。
//
// 【为什么是 JS】同 session-start.js 头注释（1.8.0 由 bash + 内联 Python 迁来）。
//
// 【失败策略】注入类 hook 静默降级，绝不阻断本轮。
//
// Trigger: UserPromptSubmit（主会话）
// Output:  additionalContext → 注入主会话上下文

'use strict'

const fs = require('fs')

const EVENT = 'UserPromptSubmit'

const LINE =
  '文言极简模式生效中：文言语法、字形简体、省主语去系词用单字动词；' +
  '句间因果、条件、转折、时序之词必留，压缩不删关系；' +
  '代码/命令/报错/标识符/行号原样；安全告警与不可逆确认逐段退回白话；' +
  '落盘产出物（代码、commit、md、子代理 prompt）一律白话。' +
  'skill 给的输出模板只管结构骨架（标题层级、表格、字段名照它给的写），' +
  '骨架内你自己的叙述文字仍用文言——模板规定形状，不豁免语体。'

// 入参事件名：读得到就用它（只认本 hook 挂的那个事件），读不到就按本事件处理。
// 返回 null 表示入参明确是别的事件——不回声来路不明的字符串，静默退出。
function resolveEvent() {
  let payload
  try {
    payload = JSON.parse(fs.readFileSync(0, 'utf8'))
  } catch (_) {
    return EVENT
  }
  const name = payload && payload.hook_event_name
  if (name === undefined || name === null || name === '') return EVENT
  return name === EVENT ? EVENT : null
}

function main() {
  const event = resolveEvent()
  if (!event) process.exit(0)

  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: event,
        additionalContext: LINE,
      },
    }) + '\n',
  )
  process.exit(0)
}

main()
