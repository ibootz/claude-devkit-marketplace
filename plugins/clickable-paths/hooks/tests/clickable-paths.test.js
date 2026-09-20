#!/usr/bin/env node
// clickable-paths 的回归用例（1.3.0 双挂之后加的）。
//
// 守三组判据：
//   1. 双挂回声——hookSpecificOutput.hookEventName 必须与入参 hook_event_name 一致，
//      写死任一个都会让另一路**静默失效**（不报错、不告警，与「压根没挂」外观相同）。
//      1.2.0 及之前只挂 UserPromptSubmit，子代理从来收不到注入，正是这类失效。
//   2. 示范本身必须是裸链接（1.8.0）——注入里的正例曾被反引号包成 inline code，模型
//      照抄示范即产出被反引号包住的整条链接：markdown 只生成 code span，终端拿不到
//      URL、不发 OSC 8，看着像链接却点不动。这类失效不报错，只能靠用例钉住。
//   3. 形态跟宿主走（1.9.0）——四宿主实测两两无交集，写死一种就有宿主里点不动。
//
// **每次 run() 都先把四个探测变量从 env 里删掉**，否则跑测试那台机器自己的宿主会渗进
// 子进程：在 VS Code 内置终端里跑，TERM_PROGRAM=vscode 会让「默认形态」那几条用例
// 实际验的是 vscode-terminal 分支，换个终端跑结论就变——测试本身变成不可复现的。
//
// 用 spawnSync 直接把 JSON 喂给子进程 stdin，不经过 shell。
// 跑法：node plugins/clickable-paths/hooks/tests/clickable-paths.test.js

'use strict'

const { spawnSync } = require('child_process')
const fs = require('fs')
const os = require('os')
const path = require('path')

const HOOK = path.join(__dirname, '..', 'clickable-paths.js')

// detectHost() 读的全部变量。逐个删，让每条用例自己声明宿主。
const PROBE_VARS = ['CLAUDE_CODE_ENTRYPOINT', 'TERM_PROGRAM', 'VSCODE_INJECTION', 'WT_SESSION']

// 非 webview 的三个宿主在同一平台上共用一种形态，所以用例只能分出「webview / 其余」
// 两档——这不是测试偷懒，映射本身就是两态的，见 hook 里的 pickInlineForm()。
const IS_WIN = process.platform === 'win32'
const ABS_SCHEME = IS_WIN ? 'vscode://file/' : 'file:///'
const INLINE_SAMPLE = IS_WIN
  ? '[decisions.md:130](vscode://file/C:/abs/path/decisions.md:130)'
  : '[decisions.md:130](file:///abs/path/decisions.md#130)'
const WEBVIEW_SAMPLE = '[decisions.md:130](docs/decisions.md#130)'
const PERSISTED_SAMPLE = '[decisions.md:11](vscode://file/abs/path/decisions.md:11)'

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

// 造一个带 `.keeper/<交付id>/{debug,chore}` 的临时项目根，用来验 1.5.0 的现算前缀。
// 只建目录、不放条目文件——探测只看队列目录存不存在。
function makeKeeperProject() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'clickable-paths-test-'))
  for (const q of ['debug', 'chore']) {
    fs.mkdirSync(path.join(root, '.keeper', 'D-001-feat-x', q), { recursive: true })
  }
  return root
}

// 一个确定没有 `.keeper/` 的目录：临时目录本身（上溯 8 层也碰不到队列）。
function makeBareProject() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'clickable-paths-bare-'))
}

const queueLines = (c) =>
  c.split('\n').filter((l) => l.startsWith('- debug：') || l.startsWith('- chore：'))

const cases = [
  {
    name: '主会话事件：回声 UserPromptSubmit 并注入正文',
    run: () => run({ hook_event_name: 'UserPromptSubmit', prompt: 'x' }),
    check: (r) => {
      if (r.status !== 0) return `exit=${r.status}，期望 0`
      const d = JSON.parse(r.stdout)
      if (d.hookSpecificOutput.hookEventName !== 'UserPromptSubmit') return '事件名未按入参回声'
      if (!d.hookSpecificOutput.additionalContext.includes(ABS_SCHEME)) return '注入正文缺链接形态'
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
      if (!d.hookSpecificOutput.additionalContext.includes(ABS_SCHEME)) return '注入正文缺链接形态'
      return null
    },
  },
  {
    name: '落盘 md 那一轨恒为 vscode:，不随宿主变（文件会被别的机器读到）',
    run: () => run({ hook_event_name: 'UserPromptSubmit', prompt: 'x' }),
    check: (r) => {
      const c = ctxOf(r)
      if (!c.includes(PERSISTED_SAMPLE)) return '缺落盘 md 那一轨的裸链接示范'
      if (!c.includes('不跟宿主变')) return '未写明落盘那一轨不跟宿主变'
      return null
    },
  },
  {
    name: '两路注入内容一致（同一份规约，不因事件而变）',
    run: () => ({
      a: run({ hook_event_name: 'UserPromptSubmit' }),
      b: run({ hook_event_name: 'SubagentStart' }),
    }),
    check: (r) => (ctxOf(r.a) === ctxOf(r.b) ? null : '两路注入正文不一致'),
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
    name: '注入正文点名四种漏套形态（1.4.0 起三种，1.8.0 补第四种）',
    run: () => run({ hook_event_name: 'UserPromptSubmit' }),
    check: (r) => {
      const c = ctxOf(r)
      // 前三种管的是「路径被写成了 inline code」：只写文件名、裸 path:行号、inline code。
      // 第四种不同——链接已经写对，只是外面多套一层反引号，整条一起失效。
      for (const kw of ['只写文件名', 'path/to/file.ext:130', 'inline code', '把整条链接']) {
        if (!c.includes(kw)) return `注入正文缺「${kw}」这条判据`
      }
      return null
    },
  },
  {
    name: '第四种漏套写明后果：code span / 不产生 link 节点 / 不发 OSC 8（1.8.0）',
    run: () => run({ hook_event_name: 'UserPromptSubmit' }),
    check: (r) => {
      const c = ctxOf(r)
      // 后果必须一起写。只说禁令，模型不会把它当硬约束。
      for (const kw of ['反引号', 'code span', 'link 节点', 'OSC 8']) {
        if (!c.includes(kw)) return `注入正文缺「${kw}」`
      }
      return null
    },
  },
  {
    name: '注入正文的示范本身是裸链接，全文没有被反引号包起来的链接模板（1.8.0）',
    run: () => ({
      bare: run({ hook_event_name: 'UserPromptSubmit' }),
      web: run({ hook_event_name: 'UserPromptSubmit' }, { CLAUDE_CODE_ENTRYPOINT: 'claude-vscode' }),
    }),
    check: (r) => {
      for (const [who, res] of Object.entries(r)) {
        const c = ctxOf(res)
        // 1.7.0 及之前，正例自己就是被反引号包住的整条链接——模型照抄示范即产出坏形态，
        // 而那种链接看着像链接、点不动、不报错。这条把「示范必须可逐字照抄」钉住。
        if (c.includes('`[')) return `${who}：注入正文里仍有被反引号包起来的链接模板`
      }
      if (!ctxOf(r.bare).includes(INLINE_SAMPLE)) return '缺本平台对话正文那一轨的裸链接示范'
      if (!ctxOf(r.web).includes(WEBVIEW_SAMPLE)) return '缺 webview 那一支的裸链接示范'
      if (!ctxOf(r.bare).includes(PERSISTED_SAMPLE)) return '缺落盘 md 那一轨的裸链接示范'
      return null
    },
  },
  {
    name: '注入正文不含尖括号占位符（尖括号是非法 URL 字符，照抄即坏链）（1.8.0）',
    run: () => ({
      bare: run({ hook_event_name: 'UserPromptSubmit', cwd: makeKeeperProject() }),
      web: run(
        { hook_event_name: 'UserPromptSubmit', cwd: makeKeeperProject() },
        { CLAUDE_CODE_ENTRYPOINT: 'claude-vscode' }),
    }),
    check: (r) => {
      // 判据是「注入里的每一个字符都可以被逐字抄进输出」：模板一旦留占位符，照抄它的人
      // 得到的是含尖括号的非法 URL，iTerm2 识别失败、整条静默失效。
      for (const [who, res] of Object.entries(r)) {
        for (const line of ctxOf(res).split('\n')) {
          if (line.includes('<') || line.includes('>')) return `${who} 残留尖括号占位符：${line}`
        }
      }
      return null
    },
  },
  {
    name: '注入正文圈定适用面：表格 / 列表 / 现场证据 / 转述回执',
    run: () => run({ hook_event_name: 'UserPromptSubmit' }),
    check: (r) => {
      const c = ctxOf(r)
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
      const c = ctxOf(r)
      // 3.3 与 readable-citations 每轮都注入裸 `path:行号` 的模板，
      // 不写明关系时模型满足了它们就以为交付完了，本条静默失效。
      if (!c.includes('working-discipline 3.3')) return '未提 working-discipline 3.3'
      if (!c.includes('同时满足两边')) return '未写明套成链接同时满足两边'
      return null
    },
  },
  {
    name: '注入正文把队列编号圈进适用面，并写死两队列的文件名（1.5.0）',
    run: () => run({ hook_event_name: 'UserPromptSubmit' }),
    check: (r) => {
      const c = ctxOf(r)
      // 编号在模型的对象模型里是「一条 issue」不是「一个文件」，只写「提到文件就套
      // 链接」它不会触发。debug→issue.md、chore→item.md 必须写死，两者混用会指向
      // 一个不存在的路径，而链接坏掉不报错。
      for (const kw of ['DBG-140', 'CHR-014', 'issue.md', 'item.md', '不可互换']) {
        if (!c.includes(kw)) return `注入正文缺「${kw}」`
      }
      return null
    },
  },
  {
    name: '有 .keeper 的项目：注入现算的真实队列前缀（1.5.0）',
    run: () => run({ hook_event_name: 'UserPromptSubmit', cwd: makeKeeperProject() }),
    check: (r) => {
      const c = ctxOf(r)
      if (!c.includes('队列前缀')) return '未注入队列前缀段'
      const links = queueLines(c)
      if (links.length !== 2) return `期望 debug/chore 各一行，实得 ${links.length} 行`
      for (const l of links) {
        if (!l.includes(ABS_SCHEME)) return `队列前缀不是当前宿主的绝对形态：${l}`
        if (!l.includes('D-001-feat-x')) return `队列前缀没算进实际交付 id：${l}`
      }
      if (!links[0].includes('issue.md') || !links[1].includes('item.md')) {
        return 'debug/chore 的条目文件名对错了位'
      }
      return null
    },
  },
  {
    name: '没有 .keeper 的项目：不注入队列前缀段（1.5.0）',
    run: () => run({ hook_event_name: 'SubagentStart', cwd: makeBareProject() }),
    check: (r) => {
      const c = ctxOf(r)
      if (c.includes('队列前缀')) return '没有队列的项目不该注入队列前缀段'
      if (!c.includes(ABS_SCHEME)) return '主体规约本身仍应注入'
      return null
    },
  },
  {
    name: '队列前缀里没有未归一化的反斜杠（1.7.0）',
    run: () => run({ hook_event_name: 'UserPromptSubmit', cwd: makeKeeperProject() }),
    check: (r) => {
      for (const l of queueLines(ctxOf(r))) {
        if (l.includes('\\')) return `队列链接含未归一化的反斜杠：${l}`
      }
      return null
    },
  },

  // —— 1.9.0 宿主自适应 ——
  {
    name: '宿主 webview：对话正文切相对 workspace 根路径（绝对路径在那里全点不开）',
    run: () =>
      run({ hook_event_name: 'UserPromptSubmit' }, { CLAUDE_CODE_ENTRYPOINT: 'claude-vscode' }),
    check: (r) => {
      const c = ctxOf(r)
      if (!c.includes(WEBVIEW_SAMPLE)) return '对话正文未切成相对路径形态'
      if (!c.includes('这个宿主里绝对路径一条都点不开')) return '未写明绝对路径在这里失效'
      // 落盘那一轨仍是 vscode:，webview 下也不例外。
      if (!c.includes(PERSISTED_SAMPLE)) return 'webview 下落盘那一轨丢了'
      return null
    },
  },
  {
    name: '宿主 webview：队列前缀也跟着走相对路径，不带 scheme',
    run: () =>
      run(
        { hook_event_name: 'UserPromptSubmit', cwd: makeKeeperProject() },
        { CLAUDE_CODE_ENTRYPOINT: 'claude-vscode' }),
    check: (r) => {
      const links = queueLines(ctxOf(r))
      if (links.length !== 2) return `期望 debug/chore 各一行，实得 ${links.length} 行`
      for (const l of links) {
        if (l.includes('file://')) return `webview 下队列链接不该带 scheme：${l}`
        if (!l.includes('.keeper/D-001-feat-x/')) return `队列相对路径算错：${l}`
        if (l.includes('\\')) return `队列链接含未归一化的反斜杠：${l}`
      }
      return null
    },
  },
  {
    name: '宿主 webview 的判据优先于 VS Code 内置终端（顺序不可调换）',
    run: () =>
      run(
        { hook_event_name: 'UserPromptSubmit' },
        // 扩展启动的 CLI 会同时带上 VS Code 自己那套变量；先判 TERM_PROGRAM
        // 就会把 webview 错归成内置终端，注入一套在那里全点不开的绝对路径。
        { CLAUDE_CODE_ENTRYPOINT: 'claude-vscode', TERM_PROGRAM: 'vscode', VSCODE_INJECTION: '1' }),
    check: (r) => (ctxOf(r).includes(WEBVIEW_SAMPLE) ? null : '被错归成内置终端'),
  },
  {
    name: '三个终端宿主（内置终端 / Windows Terminal / 兜底）共用同一形态',
    run: () => ({
      term: run({ hook_event_name: 'UserPromptSubmit' }, { TERM_PROGRAM: 'vscode' }),
      wt: run({ hook_event_name: 'UserPromptSubmit' }, { WT_SESSION: 'abc-123' }),
      bare: run({ hook_event_name: 'UserPromptSubmit' }),
    }),
    check: (r) => {
      const [a, b, c] = [ctxOf(r.term), ctxOf(r.wt), ctxOf(r.bare)]
      if (a !== b || b !== c) return '三个终端宿主的注入正文本应逐字相同'
      if (!a.includes(INLINE_SAMPLE)) return `未用本平台的绝对形态 ${INLINE_SAMPLE}`
      return null
    },
  },
  {
    name: '认不出宿主时兜底到本平台的绝对形态，而不是不给链接',
    run: () => run({ hook_event_name: 'SubagentStart' }),
    check: (r) => {
      const c = ctxOf(r)
      if (!c.includes(INLINE_SAMPLE)) return `兜底未落到 ${INLINE_SAMPLE}`
      if (!c.includes('对话正文每提到一个本机文件')) return '兜底把主体规约也丢了'
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
