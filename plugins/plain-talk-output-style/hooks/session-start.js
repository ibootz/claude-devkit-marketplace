#!/usr/bin/env node
//
// plain-talk-output-style · SessionStart hook（说人话输出风格注入）
//
// 【作用】把「说人话」对话风格作为 additionalContext 注入会话（含每次 auto-compact 后
//   重注，matcher * 覆盖 compact 来源）。与官方 explanatory-output-style 同一实现机制：
//   原生 output style 功能已废弃，风格 = 一个只做 SessionStart 注入的插件，
//   在 /plugin 里启停即切换，多个风格插件之间二选一开启。
//
// 【内容来源】风格条款源自 working-discipline 3.9.0 拆分出的行文风格部分
//   （3.1 术语与指代 / 3.2 引用自带信息 / 3.6 列表编号），叠加用户 2026-07-31 的
//   风格要求：一语中的、几句话讲明白、能表格不成段、不专业化不掉书袋不自造词。
//   纪律类条款（拍板四要素 / 求真 / 简体中文）留在 working-discipline，不随
//   风格切换丢失。
//
// 【2026-08-01 四要素条改写】working-discipline 3.10.0 把 3.3 从「必须用完整段落」
//   重构为「四要素齐备」——形状交给风格插件、信息留在纪律。该条原为一句笼统的
//   让位声明（"仍要把前因后果讲透"），现在改为明确承接：四要素在**本风格下**用完整
//   段落承载。ADHD 风格插件承接的是同样四要素、但形状是排序清单，见
//   plugins/adhd-output-style/style/project-overrides.md。
//
// 【2026-08-05 压缩改写】原「不过于专业化」「不掉书袋」两条合并为一条，「拍板材料」
//   条编号由第 10 条降为第 9 条——style/plain-talk.md 与 README 的条款序号引用需同步这一位移。
//
// 【1.6.0 名词来源改指针】第 5 条原为完整的八类来源与注释通道，与 working-discipline
//   3.37.0 的 3.1 重复，改为一句指向 3.1，真源只留一份。
//
// 【为什么是 JS（2026-10-13 由 bash + 内联 Python 迁来）】
//   旧版要先在 bash 里找 python3 再跑内联 Python：Windows 上 `command -v python3` 会被
//   Microsoft Store 的零字节桩骗过，报错又被 `2>/dev/null || true` 吞成空输出，风格
//   静默不生效；hookEventName 也是写死的。node 是 macOS / Windows 两边唯一同名的
//   解释器，故改 JS。注入文本与迁移前逐字一致。
//
// 【失败策略】注入类 hook 静默降级，绝不阻断会话启动。
//
// Trigger: SessionStart（matcher *）
// Output:  additionalContext → 注入主会话上下文

'use strict'

const fs = require('fs')
const path = require('path')

const EVENT = 'SessionStart'
const STYLE_DIR = path.join(__dirname, '..', 'style')

const HEADER = ''

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

function read(name) {
  return fs.readFileSync(path.join(STYLE_DIR, name), 'utf8').trim()
}

function main() {
  const event = resolveEvent()
  if (!event) process.exit(0)

  let body
  try {
    body = [HEADER, ...['plain-talk.md'].map(read)].filter(Boolean).join('\n\n')
  } catch (_) {
    process.exit(0)
  }

  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: event,
        additionalContext: body,
      },
    }) + '\n',
  )
  process.exit(0)
}

main()
