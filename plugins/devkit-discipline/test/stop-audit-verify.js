#!/usr/bin/env node
// stop-audit-verify.js — stop-audit.js 的回归套件
//
// 用法：node plugins/devkit-discipline/test/stop-audit-verify.js
// 退出码 0 = 全绿，1 = 有用例失败。
//
// 判定模型用桩代替（DEVKIT_STOP_AUDIT_CLAUDE 指向一个按环境变量吐固定 structured_output 的
// node 脚本），只测本脚本自己的分支：放行条件、打回输出形态、fail-open、轮起点与摘录。
// 判定质量不在这里测，见 README 4.9.0 的离线评测。用 spawnSync 喂 stdin，不经 shell。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')

const HOOK = path.join(__dirname, '..', 'hooks', 'stop-audit.js')
const { buildContextLines, buildJudgeInput } = require(HOOK)
const DIR = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'wd-stop-audit-test-')))

let pass = 0
let fail = 0

function check(name, cond, detail) {
  if (cond) {
    pass += 1
  } else {
    fail += 1
    console.log(`FAIL ${name}${detail ? `\n     ${detail}` : ''}`)
  }
}

// 桩：STUB_MODE=block 吐 ok=false，pass 吐 ok=true，garbage 吐非 JSON，exit1 以退出码 1 结束；
// 每次被调用都在 STUB_LOG 追加一行，用来断言「没调模型」。
const STUB = path.join(DIR, 'stub-claude')
fs.writeFileSync(STUB, `#!/usr/bin/env node
const fs = require('fs')
const inp = fs.readFileSync(0, 'utf8')
const isLink = inp.includes('回合末链接审查')
if (process.env.STUB_LOG) fs.appendFileSync(process.env.STUB_LOG, (isLink ? 'link' : 'source') + '\\n')
const m = isLink ? (process.env.STUB_LINK || 'pass') : process.env.STUB_MODE
if (m === 'exit1') process.exit(1)
if (m === 'garbage') { process.stdout.write('not json'); process.exit(0) }
const so = m === 'block' ? { ok: false, reason: isLink ? '回合末链接审查：\\n- 链接' : '回合末出处审查：\\n- 测试' } : { ok: true }
process.stdout.write(JSON.stringify({ structured_output: so }))
`)
fs.chmodSync(STUB, 0o755)

function run(input, env = {}) {
  const log = path.join(DIR, `log-${pass + fail}`)
  const r = spawnSync('node', [HOOK], {
    input: typeof input === 'string' ? input : JSON.stringify(input),
    encoding: 'utf8',
    env: { ...process.env, DEVKIT_STOP_AUDIT: '', DEVKIT_STOP_AUDIT_CHILD: '', DEVKIT_STOP_AUDIT_CLAUDE: STUB, DEVKIT_STOP_AUDIT_LOG: path.join(DIR, 'default-audit.log'), STUB_LOG: log, ...env },
  })
  return { status: r.status, stdout: r.stdout, called: fs.existsSync(log) }
}

const base = { hook_event_name: 'Stop', stop_hook_active: false, last_assistant_message: '结论：X 不存在。' }

// ---- 放行与打回 ----
{
  const r = run(base, { STUB_MODE: 'block' })
  let j = null
  try { j = JSON.parse(r.stdout) } catch { /* 下面断言会报 */ }
  check('判不满足 → stdout 输出 decision=block', r.status === 0 && j && j.decision === 'block', r.stdout)
  check('打回 reason 原样取自判定结果', j && j.reason === '回合末出处审查：\n- 测试', r.stdout)
  check('打回输出里没有提示词原文', !r.stdout.includes('要判定的条件'), r.stdout)
}
{
  const r = run(base, { STUB_MODE: 'pass' })
  check('判满足 → 无输出放行', r.status === 0 && r.stdout === '' && r.called, r.stdout)
}
{
  const r = run({ ...base, stop_hook_active: true }, { STUB_MODE: 'block' })
  check('stop_hook_active=true → 不调模型直接放行', r.stdout === '' && !r.called)
}
{
  const r = run(base, { STUB_MODE: 'block', DEVKIT_STOP_AUDIT: 'off' })
  check('DEVKIT_STOP_AUDIT=off → 不调模型直接放行', r.stdout === '' && !r.called)
}
{
  const r = run(base, { STUB_MODE: 'block', DEVKIT_STOP_AUDIT_CHILD: '1' })
  check('判定子进程里 → 不递归', r.stdout === '' && !r.called)
}
{
  const r = run({ ...base, last_assistant_message: '' }, { STUB_MODE: 'block' })
  check('没有 last_assistant_message → 放行', r.stdout === '' && !r.called)
}

// ---- fail-open ----
for (const [name, input, env] of [
  ['stdin 不是 JSON', 'oops', { STUB_MODE: 'block' }],
  ['判定输出不是 JSON', base, { STUB_MODE: 'garbage' }],
  ['判定进程退出码非 0', base, { STUB_MODE: 'exit1' }],
  ['claude 路径不存在', base, { STUB_MODE: 'block', DEVKIT_STOP_AUDIT_CLAUDE: path.join(DIR, 'nope') }],
  ['transcript_path 不存在', { ...base, transcript_path: path.join(DIR, 'nope.jsonl') }, { STUB_MODE: 'pass' }],
]) {
  const r = run(input, env)
  check(`fail-open：${name} → 退出码 0 且不打回`, r.status === 0 && !r.stdout.includes('"block"'), `${r.status} ${r.stdout}`)
}

// ---- 轮起点与摘录 ----
const user = (content, extra = {}) => ({ type: 'user', message: { role: 'user', content }, ...extra })
const toolUse = (name, input) => ({ type: 'assistant', message: { role: 'assistant', content: [{ type: 'tool_use', id: 't', name, input }] } })
const toolResult = (content) => user([{ type: 'tool_result', tool_use_id: 't', content }])
const jsonl = (rows) => rows.map((r) => JSON.stringify(r)).join('\n') + '\n'
{
  const L = buildContextLines(jsonl([
    user('上一轮的问题'),
    toolUse('Bash', { command: 'ls old' }),
    toolResult('old'),
    user('本轮的问题'),
    toolUse('Bash', { command: 'ls /tmp' }),
    toolResult([{ type: 'text', text: 'a\nb' }]),
    user('<system-reminder>注入</system-reminder>', { isMeta: true }),
    toolUse('Agent', { description: '查 X', prompt: '去查' }),
    toolResult('done'),
  ]))
  check('轮起点取最后一条真实用户提问', L[0] === '[user]: 本轮的问题', L[0])
  check('tool_result 行与 isMeta 行不当轮起点', !L.join('\n').includes('上一轮') && !L.join('\n').includes('注入'), L.join(' | '))
  check('tool_use 摘录命令', L.includes('[tool_use Bash]: ls /tmp'), L.join(' | '))
  check('tool_result 数组形态拼成文本、换行转 ⏎', L.includes('[tool_result]: a ⏎ b'), L.join(' | '))
  check('Agent 摘录 description | prompt', L.includes('[tool_use Agent]: 查 X | 去查'), L.join(' | '))
}
{
  const L = buildContextLines(jsonl([user([{ type: 'text', text: '带图的提问' }, { type: 'image', source: {} }])]))
  check('数组形态的用户提问（带图）可作轮起点', L[0] === '[user]: 带图的提问', L.join(' | '))
}
{
  const rows = [user('问')]
  for (let i = 0; i < 200; i++) rows.push(toolUse('Bash', { command: `cmd-${i} ${'x'.repeat(200)}` }))
  const L = buildContextLines(jsonl(rows))
  check('超出预算时保留最近的、标出省略条数', L[1].startsWith('[…本轮更早的') && L[L.length - 1].includes('cmd-199'), L[1])
  check('摘录总量不超过预算', L.join('\n').length <= 12000 + 40, String(L.join('\n').length))
}
{
  check('无用户提问时返回空', buildContextLines(jsonl([toolResult('x')])).length === 0)
  check('损坏行被跳过', buildContextLines('not json\n' + jsonl([user('问')]))[0] === '[user]: 问')
}
{
  const s = buildJudgeInput({ ...base, cwd: '/p' }, ['[user]: 问'], 'A $ARGUMENTS B $ARGUMENTS')
  check('判定输入：$ARGUMENTS 全部替换', !s.includes('$ARGUMENTS') && s.split('last_assistant_message').length === 3, s)
  check('判定输入：带 harness 同款问句与 transcript 包装', s.startsWith('<transcript>\n[user]: 问\n\n[assistant]: 结论：X 不存在。\n</transcript>') && s.includes('Condition: A {'), s.slice(0, 200))
}

{
  const { childEnv } = require(HOOK)
  const third = { PATH: '/bin', ANTHROPIC_BASE_URL: 'https://api.deepseek.com/anthropic', ANTHROPIC_AUTH_TOKEN: 't', ANTHROPIC_API_KEY: 'k', ANTHROPIC_MODEL: 'deepseek-chat', ANTHROPIC_DEFAULT_SONNET_MODEL: 'deepseek-chat' }
  const e1 = childEnv(third)
  check('第三方端点 → 剥掉端点、凭据与模型覆盖', !('ANTHROPIC_BASE_URL' in e1) && !('ANTHROPIC_AUTH_TOKEN' in e1) && !('ANTHROPIC_API_KEY' in e1) && !('ANTHROPIC_MODEL' in e1) && !('ANTHROPIC_DEFAULT_SONNET_MODEL' in e1), JSON.stringify(e1))
  check('第三方端点 → 其它变量与防递归标记保留', e1.PATH === '/bin' && e1.DEVKIT_STOP_AUDIT_CHILD === '1', JSON.stringify(e1))
  const e2 = childEnv({ ANTHROPIC_BASE_URL: 'https://api.anthropic.com', ANTHROPIC_API_KEY: 'k' })
  check('官方地址 → 原样继承', e2.ANTHROPIC_BASE_URL === 'https://api.anthropic.com' && e2.ANTHROPIC_API_KEY === 'k', JSON.stringify(e2))
  const e3 = childEnv({ ANTHROPIC_API_KEY: 'k' })
  check('未设端点 → API key 原样继承', e3.ANTHROPIC_API_KEY === 'k', JSON.stringify(e3))
  check('端点写错（解析不了）→ 按第三方处理', !('ANTHROPIC_BASE_URL' in childEnv({ ANTHROPIC_BASE_URL: 'not a url' })))
  const e4 = childEnv({ CLAUDE_CODE_EFFORT_LEVEL: 'high', API_TIMEOUT_MS: '600000' })
  check('子进程推理强度固定 medium、不继承用户的 high', e4.CLAUDE_CODE_EFFORT_LEVEL === 'medium', JSON.stringify(e4))
  check('子进程单次请求超时固定 25 秒、不继承用户的 600 秒', e4.API_TIMEOUT_MS === '25000', JSON.stringify(e4))
}

// ---- 4.17.0 两路并行判定：出处 + 链接 ----
{
  const { loadAudits, mergeReasons } = require(HOOK)
  const on = loadAudits({})
  check('默认跑两路：source 在前、link 在后', on.length === 2 && on[0].kind === 'source' && on[1].kind === 'link')
  check('出处那路提示词不含链接类', !on[0].template.includes('编号没给链接') && on[0].template.includes('二、能查没查'))
  check('链接那路提示词只审链接、带 $ARGUMENTS', on[1].template.includes('回合末链接审查') && on[1].template.includes('$ARGUMENTS') && !on[1].template.includes('能查没查'))
  for (const v of ['off', 'OFF', '0', 'false']) {
    const off = loadAudits({ CLICKABLE_PATHS: v })
    check(`CLICKABLE_PATHS=${v} → 只跑出处一路`, off.length === 1 && off[0].kind === 'source')
  }
  check('CLICKABLE_PATHS=on → 两路', loadAudits({ CLICKABLE_PATHS: 'on' }).length === 2)
  const S = { kind: 'source', verdict: { ok: false, reason: 'A' } }
  const L = { kind: 'link', verdict: { ok: false, reason: 'B' } }
  check('合并：两路都打回 → 出处在前、空一行', mergeReasons([L, S]) === 'A\n\nB')
  check('合并：一路放行、一路失败 → 空', mergeReasons([{ kind: 'source', verdict: { ok: true } }, { kind: 'link', verdict: null }]) === '')
  check('合并：出处失败、链接打回 → 只有链接', mergeReasons([{ kind: 'source', verdict: null }, L]) === 'B')
}
{
  const r = run(base, { STUB_MODE: 'pass', STUB_LINK: 'block' })
  let j = null
  try { j = JSON.parse(r.stdout) } catch { /* 下面断言会报 */ }
  check('端到端：只有链接打回 → reason 只含链接那路', j && j.decision === 'block' && j.reason === '回合末链接审查：\n- 链接', r.stdout)
}
{
  const r = run(base, { STUB_MODE: 'block', STUB_LINK: 'block' })
  let j = null
  try { j = JSON.parse(r.stdout) } catch { /* 下面断言会报 */ }
  check('端到端：两路都打回 → 合成一条', j && j.reason === '回合末出处审查：\n- 测试\n\n回合末链接审查：\n- 链接', r.stdout)
}
{
  const log = path.join(DIR, 'kinds-default')
  run(base, { STUB_MODE: 'pass', STUB_LOG: log, CLICKABLE_PATHS: '' })
  const kinds = fs.readFileSync(log, 'utf8').trim().split('\n').sort().join(',')
  check('端到端：默认两路各调一次', kinds === 'link,source', kinds)
  const log2 = path.join(DIR, 'kinds-off')
  run(base, { STUB_MODE: 'pass', STUB_LOG: log2, CLICKABLE_PATHS: 'off' })
  check('端到端：CLICKABLE_PATHS=off 只调出处一路', fs.readFileSync(log2, 'utf8').trim() === 'source')
}
{
  const r = run(base, { STUB_MODE: 'exit1', STUB_LINK: 'block' })
  check('端到端：出处那路失败不影响链接那路打回', r.stdout.includes('回合末链接审查'), r.stdout)
}

// ---- 4.17.0 词条核对（wiki-check.js，不经模型）----
{
  const { checkWikiFile, wikiFilesThisTurn, parseSource, wikiReason } = require(path.join(__dirname, '..', 'hooks', 'wiki-check.js'))
  const { userPromptText } = require(HOOK)
  const docs = path.join(DIR, 'repo', 'docs')
  fs.mkdirSync(docs, { recursive: true })
  const SRC = path.join(docs, 'design.md')
  const pad = Array.from({ length: 60 }, (_, i) => `填充行 ${i + 1}`)
  pad[9] = '## 定时催办'
  pad[10] = '- **定时催办**：到期前一天自动提醒负责人，'
  pad[11] = '  提醒走钉钉工作通知。'
  pad[49] = '评估 Plugin 是给作答打分的规则包。'
  fs.writeFileSync(SRC, pad.join('\n') + '\n')
  const wikiDir = path.join(DIR, 'claude-wiki', 'repo')
  fs.mkdirSync(wikiDir, { recursive: true })
  const W = (name, body) => { const f = path.join(wikiDir, name); fs.writeFileSync(f, body); return f }
  const src = (line) => `—— [design.md:${line}](vscode://file${SRC}:${line})`

  const good = W('good.md', [
    '# 定时催办', '',
    '> 「定时催办：到期前一天自动提醒负责人，提醒走钉钉工作通知。」', src(11), '',
    '> 评估 Plugin 是……打分的规则包', src(50), '',
    '## 未找到', '- 谁负责维护', '',
    '## 相关词条', '- [评估 Plugin](./eval-plugin.md)', '',
    '<!-- 写于 2026-11-21，会话主题：测试 -->', '',
  ].join('\n'))
  check('词条核对：合格词条（跨行摘录、去粗体与列表符、删节号、未找到、相关词条、注释）→ 无问题', checkWikiFile(good).length === 0, JSON.stringify(checkWikiFile(good)))

  const prose = W('prose.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', src(11), '', '它的作用是减少逾期，这次改动会用到它。', ''].join('\n'))
  const pp = checkWikiFile(prose)
  check('词条核对：骨架外的自写句子 → 报出行号', pp.length === 1 && pp[0].includes('第 6 行') && pp[0].includes('自写句子'), JSON.stringify(pp))

  const h2 = W('h2.md', ['# 定时催办', '', '## 是什么', '> 到期前一天自动提醒负责人', src(11), ''].join('\n'))
  check('词条核对：自写小标题（如「是什么」）→ 报出', checkWikiFile(h2).some((x) => x.includes('是什么')), JSON.stringify(checkWikiFile(h2)))

  const reword = W('reword.md', ['# 定时催办', '', '> 到期前一天会自动提醒负责的人', src(11), ''].join('\n'))
  check('词条核对：改了字的摘录 → 找不到逐字原文', checkWikiFile(reword).some((x) => x.includes('找不到逐字原文')), JSON.stringify(checkWikiFile(reword)))

  const splice = W('splice.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人……是给作答打分的规则包', src(11), ''].join('\n'))
  check('词条核对：用删节号拼两处原文 → 各片段都在文件里时放行（行号只核第一段）', checkWikiFile(splice).length === 0, JSON.stringify(checkWikiFile(splice)))
  const tiny = W('tiny.md', ['# 定时催办', '', '> 到期……提醒……负责', src(11), ''].join('\n'))
  check('词条核对：短于 4 字的片段 → 报「像在拼句」', checkWikiFile(tiny).some((x) => x.includes('像在拼句')), JSON.stringify(checkWikiFile(tiny)))

  const badLine = W('badline.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', src(58), ''].join('\n'))
  check('词条核对：行号注错（原文在 11 行、注 58 行）→ 报行号', checkWikiFile(badLine).some((x) => x.includes('行号注错')), JSON.stringify(checkWikiFile(badLine)))
  const outRange = W('outrange.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', src(999), ''].join('\n'))
  check('词条核对：行号超出文件范围 → 报出', checkWikiFile(outRange).some((x) => x.includes('超出文件范围')), JSON.stringify(checkWikiFile(outRange)))

  const noSrc = W('nosrc.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', '', '## 未找到', '- 维护人', ''].join('\n'))
  const ns = checkWikiFile(noSrc)
  check('词条核对：摘录下没有出处行 → 报出，且算「没有一段带出处的摘录」', ns.some((x) => x.includes('没有紧跟出处行')) && ns.some((x) => x.includes('没有一段带出处的摘录')), JSON.stringify(ns))

  const self = W('self.md', ['# 定时催办', '', '> 定时催办', `—— [good.md:1](vscode://file${good}:1)`, ''].join('\n'))
  check('词条核对：出处指向词条目录 → 报出', checkWikiFile(self).some((x) => x.includes('词条目录')), JSON.stringify(checkWikiFile(self)))

  check('出处解析：file:///abs#12 与 #L12 都认', parseSource(`file://${SRC}#12`).line === 12 && parseSource(`file://${SRC}#L12`).line === 12)
  check('出处解析：vscode 链接带列号也认', parseSource(`vscode://file${SRC}:12:3`).line === 12)
  check('出处解析：Windows 盘符去掉前导斜杠', parseSource('vscode://file/C:/a/b.md:3').file === 'C:/a/b.md')

  const raw = jsonl([
    user('上一轮'),
    toolUse('Write', { file_path: prose, content: '' }),
    user('本轮'),
    toolUse('Write', { file_path: good, content: '' }),
    toolUse('Edit', { file_path: reword, old_string: 'a', new_string: 'b' }),
    toolUse('Write', { file_path: path.join(DIR, 'not-wiki.md'), content: '' }),
    toolUse('Write', { file_path: reword, content: '' }),
  ])
  const files = wikiFilesThisTurn(raw, userPromptText)
  check('本轮词条：只取本轮、只取 claude-wiki 下的 md、去重', files.length === 2 && files[0] === good && files[1] === reword, JSON.stringify(files))
  const reason = wikiReason(raw, userPromptText)
  check('打回 reason：标题、只列不合格的词条、带改法', reason.startsWith('回合末词条核对') && reason.includes('reword.md') && !reason.includes('good.md：') && reason.includes('未找到出处'), reason)
  check('打回 reason：全合格 → 空', wikiReason(jsonl([user('本轮'), toolUse('Write', { file_path: good, content: '' })]), userPromptText) === '')
  check('打回 reason：词条已被删掉 → 不核', wikiReason(jsonl([user('本轮'), toolUse('Write', { file_path: path.join(wikiDir, 'gone.md'), content: '' })]), userPromptText) === '')

  // 真实原文形态：代码注释前缀、md 表格与链接、带空格与括号的路径
  const codeSrc = path.join(docs, 'hook.js')
  fs.writeFileSync(codeSrc, "'use strict'\n// 1. stop_hook_active=true（本轮已打回过一次）→ 直接放行，\n//    不调模型。\n# python 注释：默认只检查，\n# --apply 才改动。\n")
  const code = W('code.md', ['# stop_hook_active', '', '> stop_hook_active=true（本轮已打回过一次）→ 直接放行，不调模型。', `—— [hook.js:2](vscode://file${codeSrc}:2)`, '', '> 默认只检查，--apply 才改动。', `—— [hook.js:4](vscode://file${codeSrc}:4)`, ''].join('\n'))
  check('词条核对：跨行的 // 与 # 注释原文 → 去掉注释前缀后比对通过', checkWikiFile(code).length === 0, JSON.stringify(checkWikiFile(code)))
  const tblSrc = path.join(docs, 'table.md')
  fs.writeFileSync(tblSrc, '| 档 | 说明 |\n|---|---|\n| `SessionStart` | 背景规则，见 [hook-restraint](./x.md) 的强度阶梯 |\n')
  const tbl = W('tbl.md', ['# SessionStart', '', '> | SessionStart | 背景规则，见 hook-restraint 的强度阶梯 |', `—— [table.md:3](vscode://file${tblSrc}:3)`, ''].join('\n'))
  check('词条核对：摘 md 表格行（含行内代码与链接）→ 通过', checkWikiFile(tbl).length === 0, JSON.stringify(checkWikiFile(tbl)))
  const spDir = path.join(DIR, 'dir with space(1)')
  fs.mkdirSync(spDir, { recursive: true })
  fs.copyFileSync(SRC, path.join(spDir, 'design.md'))
  const enc = encodeURI(path.join(spDir, 'design.md')).replace(/\(/g, '%28').replace(/\)/g, '%29')
  const spOk = W('sp-ok.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', `—— [design.md:11](vscode://file${enc}:11)`, ''].join('\n'))
  check('词条核对：路径含空格与括号、按 %20 %28 %29 编码 → 通过', checkWikiFile(spOk).length === 0, JSON.stringify(checkWikiFile(spOk)))
  const spRaw = W('sp-raw.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', `—— [design.md:11](vscode://file${path.join(spDir, 'design.md')}:11)`, ''].join('\n'))
  const spr = checkWikiFile(spRaw)
  check('词条核对：路径空格括号没编码 → 报「出处格式不对」并给编码写法，不误报成自写句子', spr.some((x) => x.includes('出处格式不对') && x.includes('%20')) && !spr.some((x) => x.includes('自写句子') || x.includes('没有紧跟出处行')), JSON.stringify(spr))
  const many = W('many.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', src(11), '', '## 未找到', '- a1', '- a2', '- a3', '- a4', '- a5', '- a6', ''].join('\n'))
  check('词条核对：「未找到」超过 5 条 → 报出', checkWikiFile(many).some((x) => x.includes('超过 5 条')), JSON.stringify(checkWikiFile(many)))
  const ownSrc = W('own-src.md', ['# 定时催办', '', '> 到期前一天自动提醒负责人', src(11), ''].join('\n'))
  check('词条核对：出处文件本轮被 Write / Edit 过 → 不算现有原文', checkWikiFile(ownSrc, new Set([path.resolve(SRC)])).some((x) => x.includes('本轮被你改写过')), JSON.stringify(checkWikiFile(ownSrc, new Set([path.resolve(SRC)]))))
  const { wikiFilesInReply } = require(path.join(__dirname, '..', 'hooks', 'wiki-check.js'))
  const inReply = wikiFilesInReply(`见 [定时催办](file://${encodeURI(prose)})（「到期前一天」），另 \`${reword}\``)
  check('回复里链到的词条：file:// 链接与行内代码路径都取到', inReply.length === 2 && inReply[0] === prose && inReply[1] === reword, JSON.stringify(inReply))
  const rr = wikiReason(jsonl([user('本轮')]), userPromptText, `复用旧词条 [定时催办](file://${prose})`)
  check('打回 reason：本轮没写、但回复里链到的旧词条也核', rr.includes('prose.md') && rr.includes('自写句子'), rr)
  const rr2 = wikiReason('', userPromptText, `[x](file://${prose})`)
  check('打回 reason：读不到 transcript 时仍核回复里链到的词条', rr2.includes('prose.md'), rr2)

  const tp = path.join(DIR, 'transcript-wiki.jsonl')
  fs.writeFileSync(tp, raw)
  const r = run({ ...base, transcript_path: tp }, { STUB_MODE: 'block' })
  let j = null
  try { j = JSON.parse(r.stdout) } catch { /* 下面断言会报 */ }
  check('端到端：模型打回与词条核对合成一条，词条在最后', j && j.reason.startsWith('回合末出处审查') && j.reason.includes('\n\n回合末词条核对'), r.stdout)
  const r2 = run({ ...base, transcript_path: tp }, { STUB_MODE: 'pass', DEVKIT_STOP_AUDIT_CLAUDE: path.join(DIR, 'no-such-claude') })
  check('端到端：找不到 claude 时词条核对照样打回', r2.stdout.includes('回合末词条核对'), r2.stdout)
  const r3 = run({ ...base, transcript_path: tp, stop_hook_active: true }, { STUB_MODE: 'pass' })
  check('端到端：stop_hook_active=true 时词条也不核（每轮只打回一次）', r3.stdout === '', r3.stdout)
}

// ---- 失败日志 ----
{
  const logFile = path.join(DIR, 'audit.log')
  run(base, { STUB_MODE: 'exit1', DEVKIT_STOP_AUDIT_LOG: logFile })
  run(base, { STUB_MODE: 'garbage', DEVKIT_STOP_AUDIT_LOG: logFile })
  run(base, { STUB_MODE: 'pass', DEVKIT_STOP_AUDIT_LOG: logFile })
  const rows = fs.existsSync(logFile) ? fs.readFileSync(logFile, 'utf8').trim().split('\n').map((l) => JSON.parse(l)) : []
  check('失败日志：退出码非 0 与输出不是 JSON 各记一行，判定成功不记', rows.length === 2 && rows[0].kind === 'exit-nonzero' && rows[0].status === 1 && rows[1].kind === 'bad-json', JSON.stringify(rows))
  check('失败日志：带耗时与截断后的 stdout', typeof rows[1]?.ms === 'number' && rows[1].stdout === 'not json', JSON.stringify(rows[1]))
}

fs.rmSync(DIR, { recursive: true, force: true })
console.log(`stop-audit: ${pass} passed, ${fail} failed`)
process.exit(fail === 0 ? 0 : 1)
