#!/usr/bin/env node
// clickable-paths 的回归用例（1.3.0 双挂之后加的）。
//
// 重点验的是双挂回声：hookSpecificOutput.hookEventName 必须与入参 hook_event_name
// 一致，写死任一个都会让另一路**静默失效**——不报错、不告警，与「压根没挂」外观相同。
// 1.2.0 及之前只挂 UserPromptSubmit，子代理从来收不到注入，正是这类失效。
//
// 用 spawnSync 直接把 JSON 喂给子进程 stdin，不经过 shell。
// 跑法：node plugins/clickable-paths/hooks/tests/clickable-paths.test.js

'use strict'

const { spawnSync } = require('child_process')
const path = require('path')

const HOOK = path.join(__dirname, '..', 'clickable-paths.js')

function run(payload, env = {}) {
  const r = spawnSync(process.execPath, [HOOK], {
    input: typeof payload === 'string' ? payload : JSON.stringify(payload),
    encoding: 'utf8',
    env: { ...process.env, ...env },
  })
  return { status: r.status, stdout: (r.stdout || '').trim() }
}

const cases = [
  {
    name: '主会话事件：回声 UserPromptSubmit 并注入正文',
    run: () => run({ hook_event_name: 'UserPromptSubmit', prompt: 'x' }),
    check: (r) => {
      if (r.status !== 0) return `exit=${r.status}，期望 0`
      const d = JSON.parse(r.stdout)
      if (d.hookSpecificOutput.hookEventName !== 'UserPromptSubmit') return '事件名未按入参回声'
      if (!d.hookSpecificOutput.additionalContext.includes('file:///')) return '注入正文缺链接形态'
      return null
    },
  },
  {
    name: '子代理事件：回声 SubagentStart（1.3.0 补的那一路）',
    run: () => run({ hook_event_name: 'SubagentStart', agent_type: 'Explore' }),
    check: (r) => {
      if (r.status !== 0) return `exit=${r.status}，期望 0`
      const d = JSON.parse(r.stdout)
      if (d.hookSpecificOutput.hookEventName !== 'SubagentStart') return '事件名未按入参回声'
      if (!d.hookSpecificOutput.additionalContext.includes('file:///')) return '注入正文缺链接形态'
      return null
    },
  },
  {
    name: '两路注入内容一致（同一份规约，不因事件而变）',
    run: () => ({
      a: run({ hook_event_name: 'UserPromptSubmit' }),
      b: run({ hook_event_name: 'SubagentStart' }),
    }),
    check: (r) => {
      const ca = JSON.parse(r.a.stdout).hookSpecificOutput.additionalContext
      const cb = JSON.parse(r.b.stdout).hookSpecificOutput.additionalContext
      return ca === cb ? null : '两路注入正文不一致'
    },
  },
  {
    name: '白名单外的事件名：静默退出，不回声来路不明的字符串',
    run: () => run({ hook_event_name: 'PreToolUse' }),
    check: (r) => (r.status === 0 && r.stdout === '' ? null : `exit=${r.status} stdout=${r.stdout}`),
  },
  {
    name: '关闭开关 CLICKABLE_PATHS=off：不注入',
    run: () => run({ hook_event_name: 'UserPromptSubmit' }, { CLICKABLE_PATHS: 'off' }),
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
    name: '注入正文点名三种漏套形态（1.4.0 收紧的那段）',
    run: () => run({ hook_event_name: 'UserPromptSubmit' }),
    check: (r) => {
      const c = JSON.parse(r.stdout).hookSpecificOutput.additionalContext
      // 实测的漏套形态就是这三种：只写文件名、裸 path:行号、inline code。
      // 只留「套链接」的正面要求而不点名它们，模型会拿 inline code 当合法替代形态。
      for (const kw of ['只写文件名', 'path/to/file.ext:130', 'inline code']) {
        if (!c.includes(kw)) return `注入正文缺「${kw}」这条判据`
      }
      return null
    },
  },
  {
    name: '注入正文圈定适用面：表格 / 列表 / 现场证据 / 转述回执',
    run: () => run({ hook_event_name: 'UserPromptSubmit' }),
    check: (r) => {
      const c = JSON.parse(r.stdout).hookSpecificOutput.additionalContext
      // 这四种场合此前都在「对话正文」的字面含义之外，模型据此漏套。
      for (const kw of ['表格', '列表项', '现场证据', '转述子代理回执']) {
        if (!c.includes(kw)) return `注入正文未把「${kw}」圈进适用面`
      }
      return null
    },
  },
  {
    name: '注入正文写明与 working-discipline 3.3 的关系（链接同时满足两边）',
    run: () => run({ hook_event_name: 'UserPromptSubmit' }),
    check: (r) => {
      const c = JSON.parse(r.stdout).hookSpecificOutput.additionalContext
      // 3.3 与 readable-citations 每轮都注入裸 `path:行号` 的模板，
      // 不写明关系时模型满足了它们就以为交付完了，本条静默失效。
      if (!c.includes('working-discipline 3.3')) return '未提 working-discipline 3.3'
      if (!c.includes('同时满足两边')) return '未写明套成链接同时满足两边'
      return null
    },
  },
  {
    name: '注入正文保留 #1 兜底与三斜杠 href 规则',
    run: () => run({ hook_event_name: 'SubagentStart' }),
    check: (r) => {
      const c = JSON.parse(r.stdout).hookSpecificOutput.additionalContext
      if (!c.includes('#1')) return '缺「没有行号写 #1」'
      if (!c.includes('三条斜杠')) return '缺 href 绝对路径规则'
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
