#!/usr/bin/env node
// clickable-paths 的回归用例（1.3.0 双挂之后加的）。
//
// 重点验的是双挂回声：hookSpecificOutput.hookEventName 必须与入参 hook_event_name
// 一致，写死任一个都会让另一路**静默失效**——不报错、不告警，与「压根没挂」外观相同。
// 1.2.0 及之前只挂 UserPromptSubmit，子代理从来收不到注入，正是这类失效。
//
// 1.8.0 起另有四条守着「示范本身必须是裸链接」：注入里的正例曾被反引号包成 inline code，
// 模型照抄示范即产出 `[x.js:12](file:///…)` 形态的坏链接（markdown 只生成 code span，
// 终端拿不到 URL、不发 OSC 8，看着像链接却点不动）。这类失效不报错，只能靠用例钉住。
//
// 用 spawnSync 直接把 JSON 喂给子进程 stdin，不经过 shell。
// 跑法：node plugins/clickable-paths/hooks/tests/clickable-paths.test.js

'use strict'

const { spawnSync } = require('child_process')
const fs = require('fs')
const os = require('os')
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
    name: '注入正文含落盘 md 那一轨（vscode: scheme，1.6.0 加）',
    run: () => run({ hook_event_name: 'UserPromptSubmit', prompt: 'x' }),
    check: (r) => {
      const c = JSON.parse(r.stdout).hookSpecificOutput.additionalContext
      if (!c.includes('vscode://file/')) return '缺落盘 md 那一轨（vscode://file/）'
      if (!c.includes('file:///')) return '缺对话正文那一轨（file:///）'
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
      // 实测的漏套形态：只写文件名、裸 path:行号、路径被包成 inline code。
      // 只留「套链接」的正面要求而不点名它们，模型会拿 inline code 当合法替代形态。
      // 第四种「整条链接外面套反引号」另有一条用例守着（1.8.0）。
      for (const kw of ['只写文件名', 'path/to/file.ext:130', 'inline code']) {
        if (!c.includes(kw)) return `注入正文缺「${kw}」这条判据`
      }
      return null
    },
  },
  {
    name: '注入正文的示范本身是裸链接，全文没有反引号包起来的链接模板（1.8.0）',
    run: () => run({ hook_event_name: 'UserPromptSubmit' }),
    check: (r) => {
      const c = JSON.parse(r.stdout).hookSpecificOutput.additionalContext
      // 1.7.0 及之前，正例自己就是 `[<文件名>:<行号>](file:///…)`——模型照抄示范即产出
      // 「整条链接被反引号包住」的坏形态，而那种链接看着像链接、点不动、不报错。
      // 这条把「示范必须是可逐字照抄的裸链接」钉住：`[` 这个组合在注入里一次都不许出现。
      if (c.includes('`[')) return '注入正文里仍有被反引号包起来的链接模板'
      if (!c.includes('[decisions.md:130](file:///')) return '缺对话正文那一轨的裸链接示范'
      if (!c.includes('[decisions.md:11](vscode://file/')) return '缺落盘 md 那一轨的裸链接示范'
      return null
    },
  },
  {
    name: '注入正文点名第四种漏套：整条链接外面再套一层反引号，并写明后果（1.8.0）',
    run: () => run({ hook_event_name: 'UserPromptSubmit' }),
    check: (r) => {
      const c = JSON.parse(r.stdout).hookSpecificOutput.additionalContext
      // 前三种漏套管的是「路径被写成了 inline code」；第四种不同——链接已经写对，
      // 只是外面多套一层反引号，markdown 于是只生成 code span、不生成 link 节点。
      // 后果（拿不到 URL / 不发 OSC 8 / 点不动）必须一起写，只说禁令模型不会把它当硬约束。
      for (const kw of ['把整条链接', '反引号', 'code span', 'link 节点', 'OSC 8']) {
        if (!c.includes(kw)) return `注入正文缺「${kw}」`
      }
      return null
    },
  },
  {
    name: '注入正文不含尖括号占位符（`<` `>` 是非法 URL 字符，照抄即坏链）（1.8.0）',
    run: () => run({ hook_event_name: 'UserPromptSubmit', cwd: makeKeeperProject() }),
    check: (r) => {
      const c = JSON.parse(r.stdout).hookSpecificOutput.additionalContext
      // 判据是「注入里的每一个字符都可以被逐字抄进输出」：模板一旦留占位符，照抄它的人
      // 得到的是含 `<` `>` 的非法 URL，iTerm2 识别失败、整条静默失效。
      for (const line of c.split('\n')) {
        if (line.includes('<') || line.includes('>')) return `残留尖括号占位符：${line}`
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
  {
    name: '注入正文把队列编号圈进适用面，并写死两队列的文件名（1.5.0）',
    run: () => run({ hook_event_name: 'UserPromptSubmit' }),
    check: (r) => {
      const c = JSON.parse(r.stdout).hookSpecificOutput.additionalContext
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
    name: '有 .keeper 的项目：注入现算的真实队列前缀，且不留尖括号占位符（1.5.0）',
    run: () => run({ hook_event_name: 'UserPromptSubmit', cwd: makeKeeperProject() }),
    check: (r) => {
      const c = JSON.parse(r.stdout).hookSpecificOutput.additionalContext
      if (!c.includes('队列前缀')) return '未注入队列前缀段'
      const links = c.split('\n').filter((l) => l.startsWith('- debug：') || l.startsWith('- chore：'))
      if (links.length !== 2) return `期望 debug/chore 各一行，实得 ${links.length} 行`
      for (const l of links) {
        // 占位符是这条规则历史上的失效点：`<` `>` 是非法 URL 字符，iTerm2 识别失败
        // 后整条不可点，而模板本身在示范这个坏形态。现算就是为了根除它。
        if (l.includes('<') || l.includes('>')) return `队列前缀里残留尖括号占位符：${l}`
        if (!l.includes('file:///')) return `队列前缀不是三斜杠绝对路径：${l}`
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
      const c = JSON.parse(r.stdout).hookSpecificOutput.additionalContext
      if (c.includes('队列前缀')) return '没有队列的项目不该注入队列前缀段'
      if (!c.includes('file:///')) return '主体规约本身仍应注入'
      return null
    },
  },
  {
    name: '队列前缀在 Windows 盘符路径下已归一化为正斜杠（1.7.0）',
    run: () => run({ hook_event_name: 'UserPromptSubmit', cwd: makeKeeperProject() }),
    check: (r) => {
      const c = JSON.parse(r.stdout).hookSpecificOutput.additionalContext
      const links = c.split('\n').filter((l) => l.startsWith('- debug：') || l.startsWith('- chore：'))
      for (const l of links) {
        if (l.includes('\\')) return `队列链接含未归一化的反斜杠：${l}`
      }
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
