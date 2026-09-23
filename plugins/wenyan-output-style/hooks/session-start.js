#!/usr/bin/env node
// wenyan-output-style · SessionStart hook（文言极简输出风格注入）
//
// 【作用】把文言极简规则集 + 本仓补充条款作为 additionalContext 注入会话
//   （matcher * 覆盖 compact，auto-compact 后自动重注）。与 plain-talk / adhd
//   同构——风格 = 一个只做注入的插件，/plugin 里启停即切换。
//
// 【两层注入】静态规则全文在这里（SessionStart，每会话一次）；对抗「默认现代白话」
//   的一行短锚在 hooks/user-prompt-submit.js（每轮）。文言与模型默认语体对抗强，
//   长对话只靠会话头一次注入会漂回白话，故留每轮一行。
//
// 【为什么是 JS（1.8.0 由 bash + 内联 Python 迁来）】
//   旧版有四个静默失效点：hookEventName 写死；heredoc 占了 stdin，读不到入参；
//   `command -v python3` 会被 Windows Store 的零字节桩骗过；报错全被吞成空输出。
//   node 是 macOS / Windows 两边唯一同名的解释器，hooks 配置又没有按平台分 command
//   的机制，故改 JS。注入文本与迁移前逐字一致，由 tests/golden 钉住。
//
// 【出处】档位定义与例句取自 caveman 插件 skills/caveman/SKILL.md 的 wenyan-ultra 档，
//   例句由繁体逐句改为简体（working-discipline 3.5 禁繁体），并补齐上游没有的
//   压缩法、禁忌、降级与产出物边界。
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

const HEADER =
  '文言极简模式已启用，约束本会话每轮回复，含 compact 之后；话题变更不失效，' +
  '长对话不衰减。关闭：/plugin 里停用本插件。'

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
    body = [HEADER, read('wenyan-ultra-rules.md'), read('project-overrides.md')].join('\n\n')
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
