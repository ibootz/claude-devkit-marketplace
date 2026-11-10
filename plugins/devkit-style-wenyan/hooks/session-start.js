#!/usr/bin/env node
// devkit-style-wenyan · SessionStart hook（文言极简输出风格注入）
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
//   例句由繁体逐句改为简体（devkit-discipline 3.5 禁繁体），并补齐上游没有的
//   压缩法、禁忌、降级与产出物边界。
//
// 【Codex 宿主（2.2.0）】规则全文「例」一节有一句示范用 `[plugin.json:11](file:///…#11)` 给文件
//   链接——那是 Claude Code 的可点击形态。Codex 只把 inline code 里的路径渲染成可点击、
//   不认 file:// 链接（详见 devkit-clickable-paths 的同名注释），照抄示范就点不动。所以
//   宿主是 Codex（PLUGIN_ROOT 非空或入参含 turn_id）时只把这一句换成 inline code 形态，
//   其余逐字不变；Claude 侧输出由 tests/golden 钉住。
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

// Claude 示范句与它在 Codex 下的替身。替换按整句逐字匹配，规则文件改了这句而这里没跟上时
// 替换静默落空——tests 里有一条用例专门钉住「Codex 输出里不再出现 file:// 示范」。
const CLAUDE_LINK_EXAMPLE = '改 [plugin.json:11](file:///abs/path/plugins/x/.claude-plugin/plugin.json#11)。'
const CODEX_LINK_EXAMPLE = '改 `plugins/x/.claude-plugin/plugin.json:11`。'

function readPayload() {
  try {
    const payload = JSON.parse(fs.readFileSync(0, 'utf8'))
    return payload && typeof payload === 'object' ? payload : {}
  } catch (_) {
    return {}
  }
}

// 入参事件名：读得到就用它（只认本 hook 挂的那个事件），读不到就按本事件处理。
// 返回 null 表示入参明确是别的事件——不回声来路不明的字符串，静默退出。
function resolveEvent(payload) {
  const name = payload.hook_event_name
  if (name === undefined || name === null || name === '') return EVENT
  return name === EVENT ? EVENT : null
}

// Codex 判据：PLUGIN_ROOT 非空或入参含 turn_id（与 devkit-clickable-paths 同一判据）。
function isCodex(payload) {
  return Boolean(process.env.PLUGIN_ROOT) || Object.prototype.hasOwnProperty.call(payload, 'turn_id')
}

function read(name) {
  return fs.readFileSync(path.join(STYLE_DIR, name), 'utf8').trim()
}

function main() {
  const payload = readPayload()
  const event = resolveEvent(payload)
  if (!event) process.exit(0)

  let body
  try {
    body = [HEADER, read('wenyan-ultra-rules.md'), read('project-overrides.md')].join('\n\n')
  } catch (_) {
    process.exit(0)
  }
  if (isCodex(payload)) body = body.replace(CLAUDE_LINK_EXAMPLE, CODEX_LINK_EXAMPLE)

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
