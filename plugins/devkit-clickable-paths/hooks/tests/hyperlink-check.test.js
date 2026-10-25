#!/usr/bin/env node
// hyperlink-check.js 的回归用例（2.1.0 加）。
//
// 守两侧判据：
//   - 该提醒的：Windows 上 VS Code 内置终端、独立 cmd / PowerShell 窗口，未设 FORCE_HYPERLINK。
//   - 不该提醒的：Windows Terminal、已设 FORCE_HYPERLINK（含 0）、侧边栏扩展、两个关闭开关、
//     非 SessionStart 事件、非 Windows 平台。
//
// 判据只在 win32 上会命中，非 Windows 机器上跑时「该提醒」那几条改为断言静默——映射本身就是
// 平台相关的，这不是测试偷懒。
//
// **每次 run() 都先把全部探测变量从 env 里删掉**，否则跑测试那台终端自己的 WT_SESSION /
// FORCE_HYPERLINK 会渗进子进程，结论随终端变。
//
// 用 spawnSync 直接把 JSON 喂给子进程 stdin，不经过 shell。
// 跑法：node plugins/devkit-clickable-paths/hooks/tests/hyperlink-check.test.js

'use strict'

const { spawnSync } = require('child_process')
const path = require('path')

const HOOK = path.join(__dirname, '..', 'hyperlink-check.js')
const IS_WIN = process.platform === 'win32'

const PROBE_VARS = [
  'CLAUDE_CODE_ENTRYPOINT', 'TERM_PROGRAM', 'VSCODE_INJECTION', 'WT_SESSION', 'FORCE_HYPERLINK',
  'LC_TERMINAL', 'TERMINAL_EMULATOR', 'TERM', 'TMUX', 'CLICKABLE_PATHS',
  'CLICKABLE_PATHS_HYPERLINK_CHECK',
]

function run(env = {}, payload = { hook_event_name: 'SessionStart', source: 'startup' }) {
  const base = { ...process.env }
  for (const k of PROBE_VARS) delete base[k]
  const r = spawnSync(process.execPath, [HOOK], {
    input: typeof payload === 'string' ? payload : JSON.stringify(payload),
    encoding: 'utf8',
    env: { ...base, ...env },
  })
  return { status: r.status, stdout: (r.stdout || '').trim() }
}

const VSCODE_TERM = { CLAUDE_CODE_ENTRYPOINT: 'cli', TERM_PROGRAM: 'vscode', VSCODE_INJECTION: '1' }
const CONHOST = { CLAUDE_CODE_ENTRYPOINT: 'cli' }

const silent = (r) => {
  if (r.status !== 0) return `exit=${r.status}，期望 0`
  return r.stdout === '' ? null : `期望静默，实际输出：${r.stdout.slice(0, 80)}`
}

// win32 上要求注入且含 mustHave 里的每一段；其它平台要求静默。
const remindsOnWin = (mustHave) => (r) => {
  if (!IS_WIN) return silent(r)
  if (r.status !== 0) return `exit=${r.status}，期望 0`
  if (!r.stdout) return '期望注入提醒，实际静默'
  const d = JSON.parse(r.stdout)
  if (d.hookSpecificOutput.hookEventName !== 'SessionStart') return '事件名未回声为 SessionStart'
  const ctx = d.hookSpecificOutput.additionalContext
  for (const s of mustHave) if (!ctx.includes(s)) return `注入正文缺「${s}」`
  return null
}

const cases = [
  {
    name: 'VS Code 内置终端未设 FORCE_HYPERLINK：提醒，并首选 VS Code 终端 env',
    run: () => run(VSCODE_TERM),
    check: remindsOnWin(['VS Code 内置终端', 'terminal.integrated.env.windows', 'FORCE_HYPERLINK',
      'CLICKABLE_PATHS_HYPERLINK_CHECK']),
  },
  {
    name: '独立 cmd / PowerShell 窗口（三个信号都不命中）：提醒，给 ~/.claude/settings.json 与未实测说明',
    run: () => run(CONHOST),
    check: remindsOnWin(['~/.claude/settings.json', '未实测', 'Windows Terminal']),
  },
  {
    name: '已设 FORCE_HYPERLINK=1：静默',
    run: () => run({ ...VSCODE_TERM, FORCE_HYPERLINK: '1' }),
    check: silent,
  },
  {
    name: '已设 FORCE_HYPERLINK=0：静默（用户明确关掉，尊重它）',
    run: () => run({ ...VSCODE_TERM, FORCE_HYPERLINK: '0' }),
    check: silent,
  },
  {
    name: 'Windows Terminal（带 WT_SESSION）：静默',
    run: () => run({ ...CONHOST, WT_SESSION: 'abc-123' }),
    check: silent,
  },
  {
    name: '从 Windows Terminal 启动的 VS Code（终端同时带 vscode 与 WT_SESSION）：静默',
    run: () => run({ ...VSCODE_TERM, WT_SESSION: 'abc-123' }),
    check: silent,
  },
  {
    name: 'JetBrains 内置终端：静默（Claude Code 白名单内）',
    run: () => run({ ...CONHOST, TERMINAL_EMULATOR: 'JetBrains-JediTerm' }),
    check: silent,
  },
  {
    name: '侧边栏扩展（claude-vscode）：静默，那里不经终端渲染',
    run: () => run({ ...VSCODE_TERM, CLAUDE_CODE_ENTRYPOINT: 'claude-vscode' }),
    check: silent,
  },
  {
    name: 'CLICKABLE_PATHS=off：整个插件关掉时这道检查也静默',
    run: () => run({ ...VSCODE_TERM, CLICKABLE_PATHS: 'off' }),
    check: silent,
  },
  {
    name: 'CLICKABLE_PATHS_HYPERLINK_CHECK=off：只关这一道',
    run: () => run({ ...VSCODE_TERM, CLICKABLE_PATHS_HYPERLINK_CHECK: 'off' }),
    check: silent,
  },
  {
    name: '入参是别的事件：不回声、静默',
    run: () => run(VSCODE_TERM, { hook_event_name: 'UserPromptSubmit' }),
    check: silent,
  },
  {
    name: '空 stdin：按 SessionStart 处理，不报错',
    run: () => run(VSCODE_TERM, ''),
    check: remindsOnWin(['FORCE_HYPERLINK']),
  },
  {
    name: '注入正文不含尖括号占位符（照抄即坏，1.8.0 判据）',
    run: () => run(VSCODE_TERM),
    check: (r) => {
      if (!IS_WIN) return silent(r)
      const ctx = JSON.parse(r.stdout).hookSpecificOutput.additionalContext
      return /[<>]/.test(ctx) ? '注入正文出现了 < 或 >' : null
    },
  },
]

let failed = 0
for (const c of cases) {
  const err = c.check(c.run())
  if (err) {
    failed += 1
    console.log(`FAIL  ${c.name}\n      ${err}`)
  } else {
    console.log(`ok    ${c.name}`)
  }
}

console.log(`\n${cases.length - failed}/${cases.length} passed`)
process.exit(failed === 0 ? 0 : 1)
