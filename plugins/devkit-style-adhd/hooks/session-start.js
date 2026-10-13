#!/usr/bin/env node
//
// devkit-style-adhd · SessionStart hook（ADHD 友好输出风格注入）
//
// 【作用】把上游 i-have-adhd 的完整规则集 + 本仓补充条款作为 additionalContext
//   注入会话（matcher * 覆盖 compact，auto-compact 后自动重注）。与 plain-talk /
//   explanatory 一样，风格 = 一个只做 SessionStart 注入的插件，/plugin 里启停即切换。
//
// 【与上游的两点差异】
//   1. 上游是「skill 手动触发 /i-have-adhd + 手工创建 ~/.claude/.i-have-adhd-always
//      标记文件才常驻」的双通道设计。本仓拉平成纯 SessionStart 注入，与其余风格插件
//      同构——开关只有 /plugin 一个地方，不引入界面上看不见的隐藏开关。
//   2. 追加 style/project-overrides.md，解决上游 Rule 9（列表封顶 5 条）与本仓
//      devkit-discipline「拍板材料必须含起源/差距/影响/现场证据四要素」的冲突。
//      解法不是让 ADHD 风格让位，而是明确「四要素约束的是信息，不是形状」。
//
// 【规则原文】style/upstream-rules.md 是上游 SKILL.md 剥掉 YAML frontmatter 后的
//   正文，逐字未改，便于与上游比对。要改行为请改 project-overrides.md，不要改它。
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

const HEADER = 'ADHD MODE ACTIVE for the rest of this session, including after context ' +
  'compaction; it does not lapse when the topic changes. Disable it in ' +
  '/plugin (devkit-style-adhd).'

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
    body = [HEADER, ...['upstream-rules.md', 'project-overrides.md'].map(read)].filter(Boolean).join('\n\n')
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
