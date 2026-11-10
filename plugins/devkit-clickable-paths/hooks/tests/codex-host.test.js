#!/usr/bin/env node
// devkit-clickable-paths 的宿主分流用例（2.3.0 加 Codex 分支时加）。
//
// 守两件事：
//   1. Claude Code 宿主下注入逐字不变——golden-claude/*.txt 是加 Codex 分支**之前**的输出
//      （`--update-golden` 生成），任何一个字符不同都算失败。改 Claude 侧措辞时先说明理由，
//      再重跑 `--update-golden` 刷新基准。
//   2. Codex 宿主（环境变量 PLUGIN_ROOT 非空，或 payload 含 turn_id）下改注入 inline code 规则：
//      Codex TUI 只把 inline code 里的路径识别为可点击，`[x](file:///…)` 只渲染成
//      「标签 (路径)」纯文本、不发 OSC 8；Codex 系统提示明令不用 file:// / vscode:// 等 URI。
//
// golden 只在非 Windows 上比：Windows 下对话正文那一轨本来就是 vscode: 形态。
// 跑法：node plugins/devkit-clickable-paths/hooks/tests/codex-host.test.js [--update-golden]

'use strict'

const { spawnSync } = require('child_process')
const fs = require('fs')
const os = require('os')
const path = require('path')

const HOOK = path.join(__dirname, '..', 'clickable-paths.js')
const GOLDEN = path.join(__dirname, 'golden-claude')
const UPDATE = process.argv.includes('--update-golden')
const IS_WIN = process.platform === 'win32'

// 宿主探测读的全部变量，含 Codex 判据 PLUGIN_ROOT。逐个删，让每条用例自己声明宿主。
const PROBE_VARS = [
  'CLAUDE_CODE_ENTRYPOINT', 'TERM_PROGRAM', 'VSCODE_INJECTION', 'WT_SESSION',
  'PLUGIN_ROOT', 'CLICKABLE_PATHS',
]

function run(payload, env = {}) {
  const base = { ...process.env }
  for (const k of PROBE_VARS) delete base[k]
  const r = spawnSync(process.execPath, [HOOK], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    env: { ...base, ...env },
  })
  return { status: r.status, stdout: (r.stdout || '').trim() }
}

const ctxOf = (r) => JSON.parse(r.stdout).hookSpecificOutput.additionalContext

function makeKeeperProject() {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'clickable-codex-')))
  for (const q of ['debug', 'chore']) {
    fs.mkdirSync(path.join(root, '.keeper', 'D-001-feat-x', q), { recursive: true })
  }
  return root
}

// 确定不存在的 cwd：keeperQueues 的 realpathSync 抛错 → 不注入队列段，输出与机器无关。
const NO_CWD = path.join(os.tmpdir(), 'clickable-codex-does-not-exist')

const HOSTS = {
  generic: {},
  webview: { CLAUDE_CODE_ENTRYPOINT: 'claude-vscode' },
  'vscode-terminal': { TERM_PROGRAM: 'vscode' },
  'windows-terminal': { WT_SESSION: 'x' },
}

// Claude 侧 golden：每个宿主 × 两个事件，外加一份带队列前缀的。
function claudeSnapshots() {
  const out = {}
  for (const [host, env] of Object.entries(HOSTS)) {
    for (const ev of ['UserPromptSubmit', 'SubagentStart']) {
      out[`${host}-${ev}.txt`] = run({ hook_event_name: ev, cwd: NO_CWD }, env).stdout
    }
  }
  const root = makeKeeperProject()
  out['generic-keeper.txt'] = run({ hook_event_name: 'UserPromptSubmit', cwd: root }).stdout
    .split(root).join('<TMP>')
  return out
}

const cases = []

if (!IS_WIN) {
  const snaps = claudeSnapshots()
  if (UPDATE) {
    fs.mkdirSync(GOLDEN, { recursive: true })
    for (const [f, s] of Object.entries(snaps)) fs.writeFileSync(path.join(GOLDEN, f), s + '\n')
    console.log(`golden 已写入 ${Object.keys(snaps).length} 份`)
    process.exit(0)
  }
  for (const [f, s] of Object.entries(snaps)) {
    cases.push({
      name: `Claude 宿主输出与 golden 逐字一致：${f}`,
      check: () => {
        const want = fs.readFileSync(path.join(GOLDEN, f), 'utf8').replace(/\n$/, '')
        return s === want ? null : '与 golden 不一致（Claude 侧注入变了）'
      },
    })
  }
}

const CODEX_ENVS = {
  'PLUGIN_ROOT 非空': [{}, { PLUGIN_ROOT: '/x/plugin' }],
  'payload 含 turn_id': [{ turn_id: 't-1' }, {}],
}

for (const [label, [extra, env]] of Object.entries(CODEX_ENVS)) {
  for (const ev of ['UserPromptSubmit', 'SubagentStart']) {
    cases.push({
      name: `Codex（${label}）· ${ev}：注入 inline code 规则，回声事件名`,
      check: () => {
        const r = run({ hook_event_name: ev, cwd: NO_CWD, ...extra }, env)
        if (r.status !== 0) return `exit=${r.status}`
        const d = JSON.parse(r.stdout)
        if (d.hookSpecificOutput.hookEventName !== ev) return '事件名未按入参回声'
        const c = d.hookSpecificOutput.additionalContext
        if (!c.includes('`src/app.ts:42`')) return '缺仓内相对路径示范'
        if (!c.includes('inline code')) return '未点名 inline code 形态'
        if (!c.includes('相对仓库根')) return '未写仓内路径相对仓库根'
        if (!c.includes('绝对路径')) return '未写仓外路径用绝对路径'
        if (!c.includes('行号范围')) return '未写禁止行号范围'
        // 对话正文那一轨不得再示范 markdown 链接；唯一允许的 `](vscode:` 是落盘 md 那一轨的示范
        if (/\]\(file:/.test(c)) return '仍在示范 file: 链接'
        if ((c.match(/\]\(vscode:/g) || []).length !== 1) return 'vscode: 链接只应出现在落盘 md 那一轨'
        return null
      },
    })
  }
}

cases.push({
  name: 'Codex：落盘 md 那一轨照旧是 vscode://file/，不跟宿主变',
  check: () => {
    const c = ctxOf(run({ hook_event_name: 'UserPromptSubmit', cwd: NO_CWD }, { PLUGIN_ROOT: '/x' }))
    if (!c.includes('vscode://file/abs/path/decisions.md:11')) return '缺落盘 md 那一轨'
    if (!c.includes('不跟宿主变')) return '未写明落盘那一轨不跟宿主变'
    return null
  },
})

cases.push({
  name: 'Codex：队列编号给相对仓库根的 inline code 路径',
  check: () => {
    const root = makeKeeperProject()
    const c = ctxOf(run({ hook_event_name: 'UserPromptSubmit', cwd: root }, { PLUGIN_ROOT: '/x' }))
    const want = '`.keeper/D-001-feat-x/debug/DBG-140/issue.md:1`'
    if (!c.includes(want)) return `缺 ${want}`
    if (!c.includes('`.keeper/D-001-feat-x/chore/CHR-014/item.md:1`')) return '缺 chore 队列路径'
    if (c.includes(root)) return '队列路径泄出了本机绝对路径'
    return null
  },
})

cases.push({
  name: 'Codex 判据优先于 VS Code webview 判据（两者同时出现按 Codex）',
  check: () => {
    const c = ctxOf(run({ hook_event_name: 'UserPromptSubmit', cwd: NO_CWD },
      { PLUGIN_ROOT: '/x', CLAUDE_CODE_ENTRYPOINT: 'claude-vscode' }))
    return c.includes('`src/app.ts:42`') ? null : '未走 Codex 分支'
  },
})

cases.push({
  name: 'Codex：关闭开关 CLICKABLE_PATHS=off 照样生效',
  check: () => {
    const r = run({ hook_event_name: 'UserPromptSubmit', turn_id: 't' }, { CLICKABLE_PATHS: 'off' })
    return r.status === 0 && r.stdout === '' ? null : `stdout=${r.stdout}`
  },
})

let failed = 0
for (const c of cases) {
  const err = c.check()
  if (err) {
    failed += 1
    console.log(`FAIL  ${c.name}\n      ${err}`)
  } else {
    console.log(`ok    ${c.name}`)
  }
}
console.log(`\n${cases.length - failed}/${cases.length} passed`)
process.exit(failed === 0 ? 0 : 1)
