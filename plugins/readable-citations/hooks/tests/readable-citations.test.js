#!/usr/bin/env node
// readable-citations 的回归用例。
//
// 用 spawnSync 直接把 JSON 喂给子进程 stdin，**不经过 shell**——经过 shell 的测试脚本
// 一旦引号失衡，本仓其它 guard 会把测试数据当成真命令拦下并原样回灌进 finding。
// 判据见 .claude/rules/project/hook-restraint.md 的「已存在的 hook 怎么办」第 5 条。
//
// 1.3.0 起对话正文那一轨跟宿主走，所以**每次 run() 都先把四个探测变量从 env 里删掉**：
// 不删的话，跑测试那台机器自己的宿主会渗进子进程，换个终端跑结论就变。
//
// 跑法：node plugins/readable-citations/hooks/tests/readable-citations.test.js

'use strict'

const { spawnSync } = require('child_process')
const path = require('path')

const HOOK = path.join(__dirname, '..', 'readable-citations.js')

const PROBE_VARS = ['CLAUDE_CODE_ENTRYPOINT', 'TERM_PROGRAM', 'VSCODE_INJECTION', 'WT_SESSION']

// 非 webview 的三个宿主在同一平台上共用一种形态，见 hook 里的 pickInlineForm()。
const ABS_SCHEME = process.platform === 'win32' ? 'vscode://file/' : 'file:///'

function run(payload, env = {}) {
  const base = { ...process.env }
  for (const k of PROBE_VARS) delete base[k]
  const r = spawnSync(process.execPath, [HOOK], {
    input: typeof payload === 'string' ? payload : JSON.stringify(payload),
    encoding: 'utf8',
    env: { ...base, ...env },
  })
  return { status: r.status, stdout: (r.stdout || '').trim() }
}

const ctxOf = (r) => JSON.parse(r.stdout).hookSpecificOutput.additionalContext

const cases = [
  {
    name: '主会话事件：回声 UserPromptSubmit 并注入正文',
    run: () => run({ hook_event_name: 'UserPromptSubmit', prompt: 'x' }),
    check: (r) => {
      if (r.status !== 0) return `exit=${r.status}，期望 0`
      const d = JSON.parse(r.stdout)
      if (d.hookSpecificOutput.hookEventName !== 'UserPromptSubmit') return '事件名未按入参回声'
      if (!d.hookSpecificOutput.additionalContext.includes('自足')) return '注入正文缺关键概念'
      return null
    },
  },
  {
    name: '子代理事件：回声 SubagentStart（写死任一事件名会让这一路静默失效）',
    run: () => run({ hook_event_name: 'SubagentStart', agent_type: 'Explore' }),
    check: (r) => {
      if (r.status !== 0) return `exit=${r.status}，期望 0`
      const d = JSON.parse(r.stdout)
      if (d.hookSpecificOutput.hookEventName !== 'SubagentStart') return '事件名未按入参回声'
      return null
    },
  },
  {
    name: '白名单外的事件名：静默退出，不回声来路不明的字符串',
    run: () => run({ hook_event_name: 'PreToolUse' }),
    check: (r) => (r.status === 0 && r.stdout === '' ? null : `exit=${r.status} stdout=${r.stdout}`),
  },
  {
    name: '关闭开关 READABLE_CITATIONS=off：不注入',
    run: () => run({ hook_event_name: 'UserPromptSubmit' }, { READABLE_CITATIONS: 'off' }),
    check: (r) => (r.status === 0 && r.stdout === '' ? null : `exit=${r.status} stdout=${r.stdout}`),
  },
  {
    name: '空 stdin：不崩、不注入',
    run: () => run(''),
    check: (r) => (r.status === 0 && r.stdout === '' ? null : `exit=${r.status} stdout=${r.stdout}`),
  },
  {
    name: '畸形 JSON：不崩、不注入',
    run: () => run('{not json'),
    check: (r) => (r.status === 0 && r.stdout === '' ? null : `exit=${r.status} stdout=${r.stdout}`),
  },
  {
    name: '两轨链接形态都在正文里（落盘 md 走相对路径是本插件的核心判据）',
    run: () => run({ hook_event_name: 'UserPromptSubmit' }),
    check: (r) => {
      const c = ctxOf(r)
      if (!c.includes(ABS_SCHEME)) return '缺对话正文那一轨（本平台的绝对形态）'
      if (!c.includes('../')) return '缺落盘 md 那一轨（相对路径）'
      if (!c.includes('vscode://file/')) return '缺「落盘 md 指向源码用 vscode:」这条出口'
      return null
    },
  },

  // —— 1.3.0 宿主自适应 ——
  {
    name: '宿主 webview：对话正文切相对 workspace 根路径',
    run: () =>
      run({ hook_event_name: 'UserPromptSubmit' }, { CLAUDE_CODE_ENTRYPOINT: 'claude-vscode' }),
    check: (r) => {
      const c = ctxOf(r)
      if (!c.includes('相对 workspace 根的路径 + 行号')) return '对话正文未切成相对路径形态'
      if (!c.includes('这个宿主里绝对路径一条都点不开')) return '未写明绝对路径在这里失效'
      return null
    },
  },
  {
    name: '落盘 md 那一轨恒为相对路径 + 标题锚点，webview 下也不变',
    run: () => ({
      bare: run({ hook_event_name: 'UserPromptSubmit' }),
      web: run({ hook_event_name: 'UserPromptSubmit' }, { CLAUDE_CODE_ENTRYPOINT: 'claude-vscode' }),
    }),
    check: (r) => {
      for (const [who, res] of Object.entries(r)) {
        const c = ctxOf(res)
        // 文档 commit 后会被别的机器与 GitLab 网页读到，这一轨跟着本机宿主变
        // 只会在别处变成死链，而死链不报错。
        if (!c.includes('../working-discipline/SKILL.md#52-模型档位')) {
          return `${who}：落盘那一轨的相对锚点形态丢了`
        }
        if (!c.includes('不跟宿主变')) return `${who}：未写明落盘那一轨不跟宿主变`
      }
      return null
    },
  },
  {
    name: '宿主 webview 的判据优先于 VS Code 内置终端（顺序不可调换）',
    run: () =>
      run(
        { hook_event_name: 'UserPromptSubmit' },
        { CLAUDE_CODE_ENTRYPOINT: 'claude-vscode', TERM_PROGRAM: 'vscode', VSCODE_INJECTION: '1' }),
    check: (r) =>
      ctxOf(r).includes('相对 workspace 根的路径 + 行号') ? null : '被错归成内置终端',
  },
  {
    name: '三个终端宿主共用同一形态，认不出时兜底到同一支',
    run: () => ({
      term: run({ hook_event_name: 'UserPromptSubmit' }, { TERM_PROGRAM: 'vscode' }),
      wt: run({ hook_event_name: 'UserPromptSubmit' }, { WT_SESSION: 'abc-123' }),
      bare: run({ hook_event_name: 'UserPromptSubmit' }),
    }),
    check: (r) => {
      const [a, b, c] = [ctxOf(r.term), ctxOf(r.wt), ctxOf(r.bare)]
      if (a !== b || b !== c) return '三个终端宿主的注入正文本应逐字相同'
      if (!a.includes(ABS_SCHEME)) return '未用本平台的绝对形态'
      return null
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
