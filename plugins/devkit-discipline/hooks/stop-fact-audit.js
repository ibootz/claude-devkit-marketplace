// stop-fact-audit.js — 回合末后台事实审查（4.20.0，Stop hook，asyncRewake）
//
// 【为什么有它】用户 2026-11-23 拍板 Q1-c、Q2-a：同步审查（stop-audit.js）四路全留、全走订阅 sonnet；
// 第三方模型（gemini 等）挪到后台，只审核心事实错误与漏答，可用只读工具对照本机文件核实。
// 第三方判定一次要 30～150 秒（2026-11-23 实测），放在同步路径上用户每轮都要干等。
//
// 【它怎么把结果交回主模型】hooks.json 给本脚本配 asyncRewake: true。Claude Code 不等它，回复立即结束；
// 本脚本以退出码 2 结束时，stderr 作为「Stop hook feedback」消息叫醒主模型开新一轮（Claude Code 2.1.330
// 字段说明原文：「If true, hook runs in background and wakes the model on exit code 2 (blocking error).
// Implies async.」；headless 下实测叫醒成功）。叫醒那一轮的 Stop 带 stop_hook_active=true，
// 本脚本与 stop-audit.js 都直接放行，不会循环。
//
// 【什么时候跑】只在设了 DEVKIT_STOP_AUDIT_SETTINGS（第三方 settings 文件，读得到）时跑；
// DEVKIT_FACT_AUDIT=off 单独关掉本审查。没开第三方时不跑，避免给所有人每轮多一次订阅判定。
//
// 【失灵时怎样】超时、报错、无结构化输出：只写日志（audit=fact），退出码 0，不叫醒。
// 判定子进程：cwd 在临时目录、--setting-sources project、DEVKIT_STOP_AUDIT_CHILD=1（同 stop-audit.js 的防递归），
// 只放 Read / Grep / Glob，--add-dir 加上会话的项目目录。

'use strict'

const fs = require('fs')
const path = require('path')
const m = require('./stop-audit')

const FACT_TIMEOUT_MS = 300000 // 用户拍板 Q2-a 给工具后多轮读文件，超时放宽到 5 分钟；hooks.json timeout 330
// 单次 API 请求超时：同步判定给 85 秒（CHILD_API_TIMEOUT_MS），gemini 一次推理常超过 90 秒（2026-11-23 实测），这里放到 150 秒
const FACT_API_TIMEOUT_MS = 150000
const FACT_TOOLS = 'Read,Grep,Glob'
const FACT_DISALLOWED = 'Bash,Write,Edit,NotebookEdit,WebFetch,WebSearch,Agent'
const SYS_FACT = 'You are a background fact-checker for a Claude Code session. Use Read, Grep and Glob to check the last assistant reply against local files and the transcript. You never modify anything.'

function factAuditEnabled(env) {
  const flag = String(env.DEVKIT_FACT_AUDIT || '').toLowerCase()
  return !(flag === 'off' || flag === '0' || flag === 'false')
}

function factArgs(settings, cwd) {
  const a = [
    '-p', '--settings', settings, '--model', m.THIRD_PARTY_MODEL, '--system-prompt', SYS_FACT,
    '--setting-sources', 'project', '--effort', m.CHILD_EFFORT,
    '--strict-mcp-config', '--disable-slash-commands',
    '--allowedTools', FACT_TOOLS, '--disallowedTools', FACT_DISALLOWED,
  ]
  if (cwd) a.push('--add-dir', cwd)
  a.push('--no-session-persistence', '--output-format', 'json', '--json-schema', m.SCHEMA)
  return a
}

function buildFactInput(hookInput, contextLines, template) {
  const pre = contextLines.length ? contextLines.join('\n') : '[user]: （本轮用户提问未能读取）'
  const cond = template.split('$CWD').join(hookInput.cwd || '（未知）')
  return `<transcript>\n${pre}\n\n[assistant]: ${hookInput.last_assistant_message}\n</transcript>\n\n${cond}`
}

// 叫醒主模型的消息：点明审的是哪条回复（审查耗时长，叫醒时主模型可能已经往下做了），要求先核实再改。
function wakeText(reason, last) {
  return `后台事实审查（第三方模型，可读本机文件）审的是你开头为「${m.cut(last, 40)}」的那条回复，发现：\n${reason.trim()}\n` +
    '先用工具逐条核实。确有错：在回复开头写更正块（原说、实为、错因）后改正；核实后原文无误：用一两句说明依据，不必重写整条回复。'
}

async function main() {
  if (process.env.DEVKIT_STOP_AUDIT === 'off' || process.env.DEVKIT_STOP_AUDIT_CHILD === '1') return 0
  if (!factAuditEnabled(process.env)) return 0
  let hookInput
  try { hookInput = JSON.parse(fs.readFileSync(0, 'utf8')) } catch { return 0 }
  if (hookInput.stop_hook_active || !hookInput.last_assistant_message) return 0
  const settings = m.thirdPartySettings(process.env)
  if (!settings) return 0
  const claudeBin = m.resolveClaude()
  if (!claudeBin) return 0

  let contextLines = []
  try { if (hookInput.transcript_path) contextLines = m.buildContextLines(m.readTail(hookInput.transcript_path)) } catch { /* 只审最后一条回复 */ }
  const template = fs.readFileSync(path.join(__dirname, 'stop-fact-audit-prompt.txt'), 'utf8').trimEnd()
  const t0 = Date.now()
  const v = await m.judgeAsync(claudeBin, buildFactInput(hookInput, contextLines, template), {
    settings, timeout: FACT_TIMEOUT_MS, audit: 'fact', args: factArgs(settings, hookInput.cwd),
    env: { ...m.routeEnv(process.env, settings), API_TIMEOUT_MS: String(FACT_API_TIMEOUT_MS) },
  })
  const wake = !!(v && v.ok === false && typeof v.reason === 'string' && v.reason.trim())
  m.logFailure('run', {}, Date.now() - t0, { stage: 'fact', blocked: wake })
  if (!wake) return 0
  fs.writeSync(2, wakeText(v.reason, hookInput.last_assistant_message))
  return 2
}

if (require.main === module) {
  main().then((code) => process.exit(code), () => process.exit(0))
}

module.exports = { factArgs, buildFactInput, wakeText, factAuditEnabled, FACT_TIMEOUT_MS }
