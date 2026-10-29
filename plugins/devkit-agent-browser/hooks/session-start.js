#!/usr/bin/env node
// devkit-agent-browser · SessionStart hook（会话级规则注入）
//
// 【作用】把 context/session-start.md 作为 additionalContext 注入会话
//   （matcher * 覆盖 compact，auto-compact 后自动重注）。规则随本插件分发，
//   2026-10-13 从用户级 ~/.claude/CLAUDE.md 迁入。
//
// 【占位替换】正文里的 `${CLAUDE_PLUGIN_ROOT}` 换成本插件根目录的绝对路径（2.1.0 起）。
//   注入文本会被 AI 当场 Read，相对路径对它的 cwd 不成立；根目录取 __dirname 的上一级，
//   不读环境变量——scripts/install-codex.js 把本 hook 挂到 Codex 时只替换了 command 里的占位，
//   Codex 运行时是否设 CLAUDE_PLUGIN_ROOT 未核实。
//   做法同 devkit-discipline 的 working-discipline.js（REF_DIR = path.join(__dirname, '..', 'references')）。
//
// 【失败策略】纯注入，读不到文件就静默退出，绝不阻断会话启动。
//
// Trigger: SessionStart（matcher *）
// Output:  additionalContext → 注入主会话上下文

'use strict'

const fs = require('fs')
const path = require('path')

const EVENT = 'SessionStart'
const PLUGIN_ROOT = path.resolve(__dirname, '..')
const CONTEXT_FILE = path.join(PLUGIN_ROOT, 'context', 'session-start.md')
const ROOT_PLACEHOLDER = '${CLAUDE_PLUGIN_ROOT}'

// 正文里每一处占位都换成插件根目录绝对路径；用 split/join 而非正则，免得 $ { } 被当元字符。
function expandPlaceholders(text, root) {
  return text.split(ROOT_PLACEHOLDER).join(root)
}

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

  let body
  try {
    body = expandPlaceholders(fs.readFileSync(CONTEXT_FILE, 'utf8'), PLUGIN_ROOT).trim()
  } catch (_) {
    process.exit(0)
  }
  if (!body) process.exit(0)

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

if (require.main === module) main()

module.exports = { expandPlaceholders, PLUGIN_ROOT, ROOT_PLACEHOLDER }
