#!/usr/bin/env node
//
// insight-addon · SessionStart hook（教学洞察附加件）
//
// 【作用】给会话追加一条「何时给 ★ Insight 框」的规则，不定义整体行文风格。
//   设计目标是**可叠加**：它只增加一种额外输出，不规定句子长短、不规定用段落还是
//   列表，因此与 plain-talk-output-style / adhd-output-style 等完整风格插件同时
//   开启不会互相打架。这与官方 explanatory-output-style 不同——后者是一整套风格
//   （含"可超出通常长度限制"的授权），开着它再开别的风格就会冲突。
//
// 【内容来源】★ Insight 的格式与"聚焦本代码库特有门道、不讲通用编程概念"这两点，
//   取自官方 explanatory-output-style 插件的注入原文
//   （~/.claude/plugins/marketplaces/claude-plugins-official/plugins/
//     explanatory-output-style/hooks-handlers/session-start.sh 第 10 行）。
//   触发条件（何时该给、何时不该给）是本仓补充的——官方原文只说"before and after
//   writing code, always provide"，在问答类轮次里会塞出无意义的洞察框。
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
    body = [HEADER, ...['insight.md'].map(read)].filter(Boolean).join('\n\n')
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
