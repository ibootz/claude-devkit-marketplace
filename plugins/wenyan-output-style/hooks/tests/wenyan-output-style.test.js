#!/usr/bin/env node
// wenyan-output-style 的回归用例（1.8.0 hook 由 bash 迁 JS 时加）。
//
// 守三类东西：
//   1. 协议：事件名按入参回声、空 stdin / 畸形 JSON 照常注入、别的事件静默退出。
//      旧 bash 版写死事件名、读不到 stdin，这几条在它身上都不成立。
//   2. 注入预算：SessionStart 正文 ≤ 6400 字符、每轮短锚 ≤ 300 字符。超了就把内容
//      挪到指针后面，不是调大这两个数。
//   3. golden：tests/golden/*.json 是注入文本的基准。改规则文字后按 README 的
//      「改规则后刷新 golden」重生成，并在 commit 里说明为什么变。
//
// 用 spawnSync 直接把 JSON 喂给子进程 stdin，不经过 shell。
// 跑法：node plugins/wenyan-output-style/hooks/tests/wenyan-output-style.test.js

'use strict'

const { spawnSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const HOOKS = path.join(__dirname, '..')
const PLUGIN_ROOT = path.join(HOOKS, '..')
const SESSION_START = path.join(HOOKS, 'session-start.js')
const USER_PROMPT = path.join(HOOKS, 'user-prompt-submit.js')
const GOLDEN = path.join(__dirname, 'golden')

const SESSION_START_BUDGET = 6400
const ANCHOR_BUDGET = 300

function run(hook, payload) {
  const r = spawnSync(process.execPath, [hook], {
    input: typeof payload === 'string' ? payload : JSON.stringify(payload),
    encoding: 'utf8',
  })
  return { status: r.status, stdout: (r.stdout || '').trim() }
}

function context(r) {
  return JSON.parse(r.stdout).hookSpecificOutput.additionalContext
}

function golden(name) {
  const raw = fs.readFileSync(path.join(GOLDEN, name), 'utf8')
  return JSON.parse(raw).hookSpecificOutput.additionalContext
}

function sessionBody() {
  return context(run(SESSION_START, { hook_event_name: 'SessionStart' }))
}

const cases = [
  {
    name: 'SessionStart：回声事件名，注入正文与 golden 逐字一致',
    run: () => run(SESSION_START, { hook_event_name: 'SessionStart', source: 'startup' }),
    check: (r) => {
      if (r.status !== 0) return `exit=${r.status}，期望 0`
      const d = JSON.parse(r.stdout)
      if (d.hookSpecificOutput.hookEventName !== 'SessionStart') return '事件名未按入参回声'
      if (d.hookSpecificOutput.additionalContext !== golden('session-start.json')) {
        return '注入正文与 golden/session-start.json 不一致'
      }
      return null
    },
  },
  {
    name: 'UserPromptSubmit：回声事件名，短锚与 golden 逐字一致',
    run: () => run(USER_PROMPT, { hook_event_name: 'UserPromptSubmit', prompt: 'x' }),
    check: (r) => {
      if (r.status !== 0) return `exit=${r.status}，期望 0`
      const d = JSON.parse(r.stdout)
      if (d.hookSpecificOutput.hookEventName !== 'UserPromptSubmit') return '事件名未按入参回声'
      if (d.hookSpecificOutput.additionalContext !== golden('user-prompt-submit.json')) {
        return '短锚与 golden/user-prompt-submit.json 不一致'
      }
      return null
    },
  },
  ...[
    ['SessionStart', SESSION_START],
    ['UserPromptSubmit', USER_PROMPT],
  ].flatMap(([event, hook]) => [
    {
      name: `${event}：空 stdin 照常注入，事件名取本 hook 的事件`,
      run: () => run(hook, ''),
      check: (r) => {
        if (r.status !== 0 || !r.stdout) return `exit=${r.status} stdout=${r.stdout}`
        const d = JSON.parse(r.stdout)
        if (d.hookSpecificOutput.hookEventName !== event) return `事件名应为 ${event}`
        return d.hookSpecificOutput.additionalContext ? null : '注入正文为空'
      },
    },
    {
      name: `${event}：畸形 JSON 照常注入`,
      run: () => run(hook, '{not json'),
      check: (r) => {
        if (r.status !== 0 || !r.stdout) return `exit=${r.status} stdout=${r.stdout}`
        return JSON.parse(r.stdout).hookSpecificOutput.hookEventName === event
          ? null
          : `事件名应为 ${event}`
      },
    },
    {
      name: `${event}：入参是别的事件时静默退出，不回声来路不明的字符串`,
      run: () => run(hook, { hook_event_name: 'PreToolUse' }),
      check: (r) => (r.status === 0 && r.stdout === '' ? null : `exit=${r.status} stdout=${r.stdout}`),
    },
  ]),
  {
    name: `注入预算：SessionStart 正文 ≤ ${SESSION_START_BUDGET} 字符`,
    run: () => sessionBody(),
    check: (c) =>
      c.length <= SESSION_START_BUDGET ? null : `正文 ${c.length} 字符，超出 ${SESSION_START_BUDGET}`,
  },
  {
    name: `注入预算：每轮短锚 ≤ ${ANCHOR_BUDGET} 字符`,
    run: () => context(run(USER_PROMPT, { hook_event_name: 'UserPromptSubmit' })),
    check: (c) => (c.length <= ANCHOR_BUDGET ? null : `短锚 ${c.length} 字符，超出 ${ANCHOR_BUDGET}`),
  },
  {
    name: 'plugin.json 两个事件都用 node 调 .js，不再引用 .sh',
    run: () => fs.readFileSync(path.join(PLUGIN_ROOT, '.claude-plugin', 'plugin.json'), 'utf8'),
    check: (raw) => {
      if (raw.includes('.sh')) return 'plugin.json 仍引用 .sh'
      const hooks = JSON.parse(raw).hooks
      for (const [event, file] of [
        ['SessionStart', 'session-start.js'],
        ['UserPromptSubmit', 'user-prompt-submit.js'],
      ]) {
        const cmd = hooks[event][0].hooks[0].command
        if (cmd !== `node \${CLAUDE_PLUGIN_ROOT}/hooks/${file}`) return `${event} 的 command 为 ${cmd}`
      }
      return null
    },
  },
  {
    name: '压缩法明文让位于关系词（1.8.0 篇章连贯）',
    run: () => sessionBody(),
    check: (c) => {
      // 旧规则只在降级条款里说「压缩造成歧义才退白话」，症状依旧；这里钉住的是
      // 「关系词不算冗词、八条压缩法让位于它」这条正面规定本身。
      for (const kw of ['不删**关系**', '不算冗词', '让位于关系']) {
        if (!c.includes(kw)) return `缺「${kw}」`
      }
      return null
    },
  },
  {
    name: '篇章连贯一节在场；断言分层、承重概念与信息气味指向 working-discipline（1.8.0 迁出）',
    run: () => sessionBody(),
    check: (c) => {
      for (const kw of ['## 篇章连贯', '先立情境', '关系可读', '断言分层', '渐进披露', '信息气味',
        '归 `working-discipline` 3.4', '归 `working-discipline` 3.9']) {
        if (!c.includes(kw)) return `缺「${kw}」`
      }
      return null
    },
  },
  {
    name: '链接与章节引用只引用 clickable-paths / readable-citations，不另立格式',
    run: () => sessionBody(),
    check: (c) => {
      if (!c.includes('链接形态归 `clickable-paths`')) return '未把链接形态交给 clickable-paths'
      if (!c.includes('章节引用归\n  `readable-citations`') && !c.includes('章节引用归 `readable-citations`')) {
        return '未把章节引用交给 readable-citations'
      }
      if (c.includes('标题锚点')) return '注入里自带了锚点算法，应留给 readable-citations'
      return null
    },
  },
  {
    name: '落盘产出物边界与 working-discipline 分工仍在',
    run: () => sessionBody(),
    check: (c) => {
      if (!c.includes('会落盘或发出去的用白话')) return '缺落盘产出物边界'
      if (!c.includes('归 `working-discipline` 管')) return '缺「断言对错归 working-discipline」的分工'
      return null
    },
  },
  {
    name: '不再指示调用 AskUserQuestion：每处提及都是否定或限定语境（1.8.0 正文拍板）',
    run: () => sessionBody(),
    check: (c) => {
      // 允许出现的只有三种语境：不调它、worktree-flow 的授权只认它、仍用弹框时的白话要求。
      const allowed = /不调 `AskUserQuestion`|只认\n?\s*`AskUserQuestion`|`AskUserQuestion` 界面/
      const hits = c.split('\n').filter((l) => l.includes('AskUserQuestion'))
      for (const l of hits) {
        if (!allowed.test(l)) return `可疑提及：${l.trim()}`
      }
      return hits.length > 0 ? null : '连「不调 AskUserQuestion」都没写'
    },
  },
  {
    name: '正文拍板流程：四要素归属、小写字母选项、答后闭环落盘、非机械授权',
    run: () => sessionBody(),
    check: (c) => {
      for (const kw of [
        '归 `working-discipline` 3.3',
        '小写字母',
        '答后闭环',
        '`## Comments`',
        '`docs/adr/`',
        '正文回答不是机械授权',
        '默认引导进 worktree',
        '归 `working-discipline` 3.8',
        '要信息与要授权分开问',
      ]) {
        if (!c.includes(kw)) return `缺「${kw}」`
      }
      return null
    },
  },
  {
    name: 'hooks 目录无残留 bash 脚本',
    run: () => fs.readdirSync(HOOKS).filter((f) => f.endsWith('.sh')),
    check: (left) => (left.length === 0 ? null : `残留：${left.join(', ')}`),
  },
]

let failed = 0
for (const c of cases) {
  let err
  try {
    err = c.check(c.run())
  } catch (e) {
    err = `异常：${e.message}`
  }
  if (err) {
    failed += 1
    console.log(`FAIL  ${c.name}\n      ${err}`)
  } else {
    console.log(`ok    ${c.name}`)
  }
}

console.log(`\n${cases.length - failed}/${cases.length} passed`)
process.exit(failed === 0 ? 0 : 1)
