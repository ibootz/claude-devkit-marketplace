#!/usr/bin/env node
// guard-verify.js — bash-guard / write-guard / agent-dispatch 的回归套件
//
// 用法：node plugins/working-discipline/test/guard-verify.js
// 退出码 0 = 全绿，1 = 有用例失败。
//
// 【为什么用 spawnSync 而不是 shell 管道】
// guard 的输入是命令字符串，而测试数据里大量出现引号、heredoc、子 shell。若用
// `echo '<payload>' | node <guard>` 这种形式，测试脚本自身的 shell 引号一旦失衡，
// 后面的测试数据就变成裸命令——2026-07-31 审计真撞过一次：bash-guard 把审计脚本里
// 20 多行测试数据当成真命令拦下，并原样回灌进 finding（单条撑到 900+ 字符）。
// spawnSync 直接把字符串写进子进程 stdin，全程不经过 shell，杜绝这类自伤。
//
// 【为什么 fixture 是临时生成的】
// write-guard 的两条检查都要读真实文件。用机器上现成的大文件做样本有两个问题：
// 换台机器就跑不了，而且找不到"正好 1000 行"这种边界样本（3.6.0 修的 +1 偏移
// 恰恰只在边界上体现）。这里在 os.tmpdir() 下现造一棵最小项目树，跑完即删。
//
// 【判据两侧都要有用例】
// 每组都同时覆盖「3.6.0 前误杀、现在应放行」与「原本正确拦截、现在仍应拦截」。
// 只测前者会把 guard 改废；只测后者发现不了误杀。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')

const HOOKS_DIR = path.join(__dirname, '..', 'hooks')
const BASH_GUARD = path.join(HOOKS_DIR, 'guards', 'bash-guard.js')
const WRITE_GUARD = path.join(HOOKS_DIR, 'guards', 'write-guard.js')
const AGENT_GUARD = path.join(HOOKS_DIR, 'guards', 'agent-dispatch.js')

// ── fixture：一棵最小项目树 ──────────────────────────────────────────
const FIXTURE_ROOT = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'wd-guard-')))
const PROJECT = path.join(FIXTURE_ROOT, 'proj')
const OUTSIDE = path.join(FIXTURE_ROOT, 'outside')

// n 行、以换行结尾（POSIX 文本文件的常态，也是 +1 偏移的触发条件）
const lines = (n) => 'x\n'.repeat(n)

function put(filePath, content) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  fs.writeFileSync(filePath, content)
  return filePath
}

const F = {
  exact1000: put(path.join(PROJECT, 'src/exact1000.js'), lines(1000)),
  over1000: put(path.join(PROJECT, 'src/over1000.js'), lines(1001)),
  bigMjs: put(path.join(PROJECT, 'scripts/big.mjs'), lines(1200)),
  bigSh: put(path.join(PROJECT, 'scripts/big.sh'), lines(1200)),
  bigSql: put(path.join(PROJECT, 'db/schema.sql'), lines(3500)),
  bigCss: put(path.join(PROJECT, 'src/theme.css'), lines(4000)),
  vendorCss: put(path.join(PROJECT, 'node_modules/animate.css/animate.css'), lines(4000)),
  distBundle: put(path.join(PROJECT, 'dist/bundle.js'), lines(2500)),
  targetSql: put(path.join(PROJECT, 'target/classes/schema.sql'), lines(3500)),
  minJs: put(path.join(PROJECT, 'src/vendor.min.js'), lines(2000)),
  claudeMd200: put(path.join(PROJECT, 'CLAUDE.md'), lines(200)),
  claudeMd201: put(path.join(PROJECT, 'docs/CLAUDE.md'), lines(201)),
  rulesClaudeMd: put(path.join(PROJECT, '.claude/rules/CLAUDE.md'), lines(900)),
  rulesTopic: put(path.join(PROJECT, '.claude/rules/hook-restraint.md'), lines(900)),
  outsideClaudeMd: put(path.join(OUTSIDE, 'CLAUDE.md'), lines(700)),
}

// 旧实现 /(^|\/)\.claude\/rules\// 的绕过点：路径任意位置含该段就关闭检查
const RULES_ESCAPE = path.join(PROJECT, '.claude/rules/../../../outside/CLAUDE.md')
// 对照组：换成无关中间段，证明放行（若发生）是那个路径段导致的而非 `..`
const PLAIN_ESCAPE = path.join(PROJECT, 'docs/../../outside/CLAUDE.md')

// ── 执行与断言 ──────────────────────────────────────────────────────
let pass = 0
const failures = []

function run(guard, payload, env) {
  const r = spawnSync('node', [guard], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    env: env ? { ...process.env, ...env } : process.env,
  })
  return { code: r.status, err: (r.stderr || '').trim() }
}

function check(label, expect, actual, detail) {
  if (expect === actual) {
    pass++
    return
  }
  failures.push({ label, expect, actual, detail })
}

function bash(label, command, cwd, expect, env) {
  const r = run(BASH_GUARD, { tool_name: 'Bash', tool_input: { command }, cwd }, env)
  check(label, expect, r.code, r.err)
  return r
}

function write(label, filePath, cwd, expect) {
  const r = run(WRITE_GUARD, { tool_name: 'Write', tool_input: { file_path: filePath }, cwd })
  check(label, expect, r.code, r.err)
  return r
}

const BLOCK = 2
const PASS = 0

// ── bash-guard / 独立 cd ────────────────────────────────────────────
// 3.6.0 前误杀，现在应放行
bash('heredoc: ssh 远端 cd', "ssh prod bash -s <<'EOF'\ncd /srv/app\ngit pull\nEOF", PROJECT, PASS)
bash('heredoc: python 正文 cd', "python3 - <<'EOF'\nprint(1)\ncd /tmp\nEOF", PROJECT, PASS)
bash('heredoc: 无引号定界符', 'cat <<EOF\ncd /tmp\nEOF', PROJECT, PASS)
bash('heredoc: <<- 形态', 'cat <<-END\n\tcd /tmp\n\tEND', PROJECT, PASS)
bash('heredoc: 双引号定界符', 'cat <<"EOF"\ncd /tmp\nEOF', PROJECT, PASS)
bash('后台化 `cd /tmp &`', 'cd /tmp &', PROJECT, PASS)
bash('cd $PWD', 'cd $PWD', PROJECT, PASS)
bash('cd "$PWD"', 'cd "$PWD"', PROJECT, PASS)
bash('cd ${PWD}', 'cd ${PWD}', PROJECT, PASS)
if (process.platform === 'darwin') {
  // macOS 上 /tmp 是 /private/tmp 的符号链接；旧实现只做字符串归一
  bash('符号链接等价 (/tmp ↔ /private/tmp)', 'cd /tmp', '/private/tmp', PASS)
  // APFS 默认大小写不敏感
  bash('大小写等价路径', `cd ${PROJECT.replace('/Users/', '/users/')}`, PROJECT, PASS)
}

// 回归：仍必须拦
bash('裸 cd', 'cd /tmp', PROJECT, BLOCK)
bash('链尾 cd', 'ls && cd /tmp', PROJECT, BLOCK)
bash('换行后 cd', 'npm run build\ncd dist && ls', PROJECT, BLOCK)
bash('cd ..', 'cd ..', PROJECT, BLOCK)
bash('cd 无参数(回 home)', 'cd', PROJECT, BLOCK)
bash('子 shell 之后仍有裸 cd', '(cd /tmp && ls) && cd /var', PROJECT, BLOCK)
bash('heredoc 结束之后的真 cd', "cat <<'EOF'\nhello\nEOF\ncd /tmp", PROJECT, BLOCK)

// 回归：原本正确放行，不得因收窄而回归成误杀
bash('子 shell', '(cd /tmp && ls)', PROJECT, PASS)
bash('嵌套子 shell', '(cd /tmp && (cd /var && ls))', PROJECT, PASS)
bash('命令替换 $()', 'X=$(cd /tmp && pwd)', PROJECT, PASS)
bash('字符串内的 cd', 'echo "cd /tmp" | bash', PROJECT, PASS)
bash('cd .', 'cd .', PROJECT, PASS)
bash('cd 当前目录绝对路径', `cd ${PROJECT}`, PROJECT, PASS)
bash('here-string 不是 heredoc', 'bash <<< "echo hi"', PROJECT, PASS)

// ── bash-guard / agent-browser（3.7.0：默认 headless + 四护栏）─────────
// 模型变更：3.6.0 强制 --headed + --profile；3.7.0 删 --headed，改为
//   ①鉴权前置（缺 --profile/--state/--headers/--restore 任一即拦）
//   ②实例上限 4（查 session list；测试用 WD_AB_INSTANCE_COUNT 注入）
//   ④安全边界提醒（缺 --allowed-domains/--content-boundaries 仅提醒，不阻断）
// 实例计数默认走真实 CLI，测试机通常未装 → countActiveInstances 返回 -1 → 放行，
// 故护栏②的 BLOCK 用例统一用 WD_AB_INSTANCE_COUNT 桩注入确定值。

// 仍应放行（沿用 3.6.0 修复）
bash('open --help', 'agent-browser open --help', PROJECT, PASS)
bash('connect --help', 'agent-browser connect --help', PROJECT, PASS)
bash('open --version', 'agent-browser open --version', PROJECT, PASS)
bash('grep 参数里的 agent-browser', 'grep -rn agent-browser open /tmp', PROJECT, PASS)
bash('白名单子命令', 'agent-browser snapshot', PROJECT, PASS)
bash('chat REPL 无 URL', 'agent-browser chat', PROJECT, PASS)
bash('未知子命令按设计放行', 'agent-browser goto https://x', PROJECT, PASS)
bash('--profile 的值恰为 open', 'agent-browser --profile open snapshot', PROJECT, PASS)

// ── 护栏①：缺鉴权 → 阻断（默认实例数 0，不会触发护栏②）──────────────
bash('open 无任何鉴权', 'agent-browser open https://x', PROJECT, BLOCK)
bash('connect 无任何鉴权', 'agent-browser connect 9222', PROJECT, BLOCK)
bash('chat+URL 无任何鉴权', 'agent-browser chat https://x', PROJECT, BLOCK)
bash('--profile= 空值视为缺鉴权', 'agent-browser open https://x --profile=""', PROJECT, BLOCK)
bash('--profile 分离空值视为缺鉴权', 'agent-browser open https://x --profile ""', PROJECT, BLOCK)
bash('绝对路径调用缺鉴权', '/usr/local/bin/agent-browser open https://x', PROJECT, BLOCK)
// 口令退化回归：鉴权机制只在本次调用自己的 tail + 紧邻 env 前缀里判定，不跨片段
bash('口令: 另一片段的 --profile', 'echo --profile /p; agent-browser open https://x', PROJECT, BLOCK)
bash('口令: JSON 参数里的 --profile', 'agent-browser open https://y --json "{--profile}"', PROJECT, BLOCK)
bash('口令: 另一片段的 PROFILE 环境变量', 'echo AGENT_BROWSER_PROFILE=/x; agent-browser open https://y', PROJECT, BLOCK)

// 护栏①：带了任一鉴权机制即满足（不再要求 --headed）
bash('--profile 满足鉴权', 'agent-browser open https://x --profile /tmp/p', PROJECT, PASS)
bash('--profile= 带值满足', 'agent-browser open https://x --profile=/tmp/p', PROJECT, PASS)
bash('--headers 注入 token 满足', 'agent-browser open https://x --headers \'{"Authorization":"Bearer t"}\'', PROJECT, PASS)
bash('--state 满足', 'agent-browser open https://x --state ./auth.json', PROJECT, PASS)
bash('--restore 布尔开关满足', 'agent-browser --session s1 --restore open https://x', PROJECT, PASS)
bash('AGENT_BROWSER_PROFILE 环境变量满足', 'AGENT_BROWSER_PROFILE=/tmp/p agent-browser open https://x', PROJECT, PASS)
bash('npx 前缀带 profile', 'npx agent-browser open https://x --profile /p', PROJECT, PASS)
bash('显式 headless(无 --headed)带 profile', 'agent-browser open https://x --profile /p', PROJECT, PASS)

// ── 护栏②：实例上限 4（WD_AB_INSTANCE_COUNT 注入计数）────────────────
bash('实例 3 个(<上限)放行', 'agent-browser open https://x --profile /p', PROJECT, PASS, {
  WD_AB_INSTANCE_COUNT: '3',
})
bash('实例 4 个(=上限)阻断', 'agent-browser open https://x --profile /p', PROJECT, BLOCK, {
  WD_AB_INSTANCE_COUNT: '4',
})
bash('实例 5 个(>上限)阻断', 'agent-browser open https://x --profile /p', PROJECT, BLOCK, {
  WD_AB_INSTANCE_COUNT: '5',
})
// 实例超限 + 缺鉴权同时命中：两者都报（阻断类合并）
bash('超限且缺鉴权', 'agent-browser open https://x', PROJECT, BLOCK, {
  WD_AB_INSTANCE_COUNT: '4',
})
// CLI 未装(count=-1)时护栏②放行，但护栏①仍独立生效
bash('count=-1 时仅护栏①生效(缺鉴权仍拦)', 'agent-browser open https://x', PROJECT, BLOCK, {
  WD_AB_INSTANCE_COUNT: '-1',
})
bash('count=-1 且带鉴权放行', 'agent-browser open https://x --profile /p', PROJECT, PASS, {
  WD_AB_INSTANCE_COUNT: '-1',
})

// ── 护栏④：缺安全边界仅提醒（不阻断）────────────────────────────────
// 带 profile 但缺 --allowed-domains/--content-boundaries → 不拦(exit 0)
bash('缺安全边界不阻断(带 profile)', 'agent-browser open https://x --profile /p', PROJECT, PASS)
bash('带 --allowed-domains 放行', 'agent-browser open https://x --profile /p --allowed-domains x.com', PROJECT, PASS)
bash('带 --content-boundaries 放行', 'agent-browser open https://x --profile /p --content-boundaries', PROJECT, PASS)

// ── write-guard ─────────────────────────────────────────────────────
// 行数边界：3.6.0 修掉 +1 偏移，正好 1000 行且以换行结尾的文件不该被拦
write('源码正好 1000 行', F.exact1000, PROJECT, PASS)
write('源码 1001 行', F.over1000, PROJECT, BLOCK)

// 扩展名黑洞：3.6.0 前 .mjs / .sh 完全不受约束
write('.mjs 纳入源码集合', F.bigMjs, PROJECT, BLOCK)
write('.sh 纳入源码集合', F.bigSh, PROJECT, BLOCK)

// 行数与"职责过大"无关的类型：3.6.0 移出源码集合
write('.sql 建表脚本放行', F.bigSql, PROJECT, PASS)
write('.css 样式表放行', F.bigCss, PROJECT, PASS)

// 依赖 / 构建产物 / 生成物
write('node_modules 依赖放行', F.vendorCss, PROJECT, PASS)
write('dist 打包产物放行', F.distBundle, PROJECT, PASS)
write('target 构建产物放行', F.targetSql, PROJECT, PASS)
write('.min.js 生成物放行', F.minJs, PROJECT, PASS)

// CLAUDE.md：边界 + 项目树限定 + rules 排除
write('CLAUDE.md 正好 200 行', F.claudeMd200, PROJECT, PASS)
write('子目录 CLAUDE.md 201 行', F.claudeMd201, PROJECT, BLOCK)
write('项目外 CLAUDE.md 不管', F.outsideClaudeMd, PROJECT, PASS)
write('.claude/rules/ 下的 CLAUDE.md 放行', F.rulesClaudeMd, PROJECT, PASS)
write('.claude/rules/ 下的其他 md 放行', F.rulesTopic, PROJECT, PASS)
write('rules 路径段绕过已失效', RULES_ESCAPE, PROJECT, PASS)
write('对照组: 无关中间段爬出项目', PLAIN_ESCAPE, PROJECT, PASS)

// 基础设施异常不误拦
write('文件不存在', path.join(PROJECT, 'src/ghost.js'), PROJECT, PASS)
check(
  'tool_name 非 Write/Edit',
  PASS,
  run(WRITE_GUARD, { tool_name: 'Read', tool_input: { file_path: F.over1000 }, cwd: PROJECT }).code
)
check(
  'file_path 缺失',
  PASS,
  run(WRITE_GUARD, { tool_name: 'Write', tool_input: {}, cwd: PROJECT }).code
)

// ── 派发账本（dispatch-ledger.js，3.12.0 新增）────────────────────────
//
// 它是纯注入 hook，失败是静默的——没有断言就没人发现它已经不数数了。
// 三件事必须钉住：(a) 数得对；(b) 判据失灵时**不注入**而不是注「0 派发」；
// (c) 会话早期不注入（零成本）。
const LEDGER = path.join(HOOKS_DIR, 'dispatch-ledger.js')

function transcript(rows) {
  const f = path.join(FIXTURE_ROOT, `tr-${Math.random().toString(36).slice(2)}.jsonl`)
  fs.writeFileSync(f, rows.map((r) => JSON.stringify(r)).join('\n'), 'utf8')
  return f
}
// 造一条 assistant 行：tools 是工具名数组
const asst = (tools, sidechain) => ({
  type: 'assistant',
  isSidechain: !!sidechain,
  message: { content: tools.map((name) => ({ type: 'tool_use', name, input: {} })) },
})

function ledger(label, rows, assertFn) {
  const payload = rows === null ? {} : { transcript_path: transcript(rows) }
  const r = spawnSync('node', [LEDGER], { input: JSON.stringify(payload), encoding: 'utf8' })
  const out = (r.stdout || '').trim()
  let ctx = ''
  if (out) {
    try {
      ctx = JSON.parse(out).hookSpecificOutput.additionalContext
    } catch (e) {
      ctx = `<不是合法 JSON: ${out.slice(0, 80)}>`
    }
  }
  const ok = assertFn(ctx)
  check(label, true, ok === true, ok === true ? '' : `实际输出: ${ctx || '(空)'}`)
}

// 15 次主会话调用 + 3 次派发（另有 sidechain 行与 1 条 Task 旧工具名）
ledger(
  '账本计数正确（主会话 16 / 派发 3，sidechain 不计入）',
  [
    asst(['Bash', 'Read', 'Grep', 'Glob', 'Read', 'Bash']),
    asst(['Agent', 'Agent']),
    asst(['Bash', 'Read', 'Grep', 'Glob', 'Read', 'Bash', 'Write']),
    asst(['Task']),
    asst(['Bash', 'Bash', 'Bash', 'Agent'], true), // sidechain：整行不计
  ],
  (c) => c.includes('主会话工具调用 16 次') && c.includes('派发 3 次')
)

ledger(
  '0 派发且调用数达阈值时追加提示',
  [asst(Array(22).fill('Bash'))],
  (c) => c.includes('派发 0 次') && c.includes('检查点②')
)

ledger(
  '有派发时不追加提示（避免每轮唠叨）',
  [asst(Array(22).fill('Bash')), asst(['Agent'])],
  (c) => c.includes('派发 1 次') && !c.includes('检查点②')
)

ledger(
  '会话早期（调用数 < 12）零输出',
  [asst(['Bash', 'Read', 'Grep'])],
  (c) => c === ''
)

ledger(
  '无 transcript_path → 零输出',
  null,
  (c) => c === ''
)

ledger(
  '解析不出任何 assistant 行时不注入（不谎报 0 派发）',
  [{ type: 'user', message: { content: 'hi' } }, { type: 'system', subtype: 'x' }],
  (c) => c === ''
)

ledger(
  '损坏行被跳过而不是整体失败',
  [asst(Array(14).fill('Bash')), asst(['Agent'])],
  (c) => c.includes('派发 1 次')
)

// 损坏行单独造：上面 transcript() 只能写合法 JSON
{
  const f = path.join(FIXTURE_ROOT, 'tr-broken.jsonl')
  fs.writeFileSync(
    f,
    [JSON.stringify(asst(Array(14).fill('Bash'))), '{ 这行不是 JSON', JSON.stringify(asst(['Agent']))].join('\n'),
    'utf8'
  )
  const r = spawnSync('node', [LEDGER], { input: JSON.stringify({ transcript_path: f }), encoding: 'utf8' })
  const ctx = r.stdout ? JSON.parse(r.stdout).hookSpecificOutput.additionalContext : ''
  check('半路损坏行不影响其余计数', true, ctx.includes('主会话工具调用 15 次') && ctx.includes('派发 1 次'), ctx)
}

// ── 派发账本 3.15.0：自上次派发以来的检索计数 ─────────────────────────
//
// 这一段的判据两侧都要覆盖：过线该提示、没过线不该提示、派发后必须真的清零。
// 中间那条最要紧——若清零写漏，提示会从"越界告警"退化成"每轮唠叨"，
// 而唠叨的注入在 AI 眼里等价于噪音，整个反馈回路就白做了。

ledger(
  '自上次派发以来 ≥6 次检索 → 追加越界提示',
  [asst(['Agent']), asst(['Read', 'Grep', 'Glob', 'Bash', 'Read', 'Grep']), asst(Array(8).fill('Read'))],
  (c) => c.includes('已亲手检索 14 次') && c.includes('已过检查点②的次数线')
)

ledger(
  '派发后计数清零 → 不追加越界提示',
  [asst(Array(9).fill('Read')), asst(Array(9).fill('Grep')), asst(['Agent'])],
  (c) => c.includes('已亲手检索 0 次') && !c.includes('已过检查点②的次数线')
)

ledger(
  '未过线（5 次）不追加提示',
  [asst(['Agent']), asst(Array(12).fill('Bash')), asst(['Agent']), asst(Array(5).fill('Read'))],
  (c) => c.includes('已亲手检索 5 次') && !c.includes('已过检查点②的次数线')
)

ledger(
  '写操作与派发外的工具不计入检索数',
  [asst(['Agent']), asst(Array(13).fill('Write')), asst(['Edit', 'TodoWrite', 'Read'])],
  (c) => c.includes('已亲手检索 1 次')
)

// 0 派发分支（calls ≥ NUDGE_AT）优先于越界分支：它的措辞更重，两段一起注是重复唠叨。
ledger(
  '从未派发过时，检索数等于全会话累计（不是 0）',
  [asst(Array(22).fill('Read'))],
  (c) => c.includes('派发 0 次') && c.includes('连查 22 次') && !c.includes('已过检查点②的次数线')
)

// 未到 NUDGE_AT 但已过 PROBE_LIMIT 的中间地带：走越界分支，不走 0 派发分支。
ledger(
  '0 派发但调用数未达 20 时，只给越界提示',
  [asst(Array(14).fill('Read'))],
  (c) => c.includes('已过检查点②的次数线') && !c.includes('整段会话一次没派过')
)

// ── agent-dispatch check 8：name 必须体现插件专用 agent 的身份 ───────
//
// 与上面两个 guard 不同，agent-dispatch **始终 exit 0**，判定表达在 stdout 的 JSON 里：
// deny / 自动补名（updatedInput）/ 静默放行三态，所以不能复用按退出码断言的 bash()。
//
// 判据两侧都覆盖：新增 check 8 该拦的三条（本次事故原样在内）、绝不能误杀的十一条，
// 外加两条旧判据（缺 model / 前缀不符）确认没被 check 8 挤掉。
function agentVerdict(ti) {
  const r = spawnSync('node', [AGENT_GUARD], {
    input: JSON.stringify({ tool_name: 'Agent', tool_input: ti }),
    encoding: 'utf8',
  })
  const out = (r.stdout || '').trim()
  if (!out) return { verdict: 'ALLOW', detail: '' }
  let j
  try {
    j = JSON.parse(out)
  } catch (_) {
    return { verdict: 'UNPARSABLE', detail: out.slice(0, 200) }
  }
  const hso = j.hookSpecificOutput || {}
  if (hso.permissionDecision === 'deny') {
    return { verdict: 'DENY', detail: String(hso.permissionDecisionReason || '').slice(0, 200) }
  }
  if (hso.updatedInput) return { verdict: 'AUTONAME', detail: hso.updatedInput.name }
  return { verdict: 'ALLOW', detail: '' }
}

function agent(label, ti, expect) {
  const r = agentVerdict(ti)
  check(`agent-dispatch: ${label}`, expect, r.verdict, r.detail)
  return r
}

const AD_BASE = { model: 'sonnet', description: '排查登录超时' }
const ad = (over) => Object.assign({}, AD_BASE, over)
// 两个 keeper 类型受 check 9（固定 opus 档）与 check 10（name 逐字固定）双重约束，
// 所以它们**不能再当 check 8 宽松性的载体**——3.14.0 加了 check 10 之后，
// `opus-debug-keeper-open-audit` 这类"含身份词就该放行"的正向用例会被 check 10 拦下，
// 拦得对但验错了东西。check 8 的正向用例改用 `caveman:cavecrew-reviewer` 当载体
// （不在固定名白名单内），keeper 只留在 check 9 / check 10 各自的段落里。
const adO = (over) => Object.assign({}, AD_BASE, { model: 'opus' }, over)

// 该拦：subagent_type 含冒号（插件专用 agent），name 不含任何身份词
const ad8 = agent('本次事故原样 dbg vs debug-keeper', adO({ name: 'opus-dbg-open-audit', subagent_type: 'task-keeper:debug-keeper' }), 'DENY')
check('agent-dispatch: check 8 finding 点明身份词', true, /身份词/.test(ad8.detail), ad8.detail)
agent('chore-keeper 身份丢失', adO({ name: 'opus-ledger-tidy', subagent_type: 'task-keeper:chore-keeper' }), 'DENY')
agent('cavecrew-reviewer 身份丢失', ad({ name: 'sonnet-check-diff', subagent_type: 'caveman:cavecrew-reviewer' }), 'DENY')

// 不得误杀：含任一身份词即可，位置与大小写不限
// 载体用 cavecrew-reviewer 而不是 keeper——理由见上面 adO 的注释（keeper 另受 check 10 约束）
agent('带全身份词', ad({ name: 'sonnet-cavecrew-reviewer-open-audit', subagent_type: 'caveman:cavecrew-reviewer' }), 'ALLOW')
agent('只带尾词 reviewer', ad({ name: 'sonnet-open-audit-reviewer', subagent_type: 'caveman:cavecrew-reviewer' }), 'ALLOW')
agent('只带首词 cavecrew', ad({ name: 'sonnet-cavecrew-open-audit', subagent_type: 'caveman:cavecrew-reviewer' }), 'ALLOW')
agent('大小写不敏感', ad({ name: 'sonnet-Cavecrew-Audit', subagent_type: 'caveman:cavecrew-reviewer' }), 'ALLOW')
agent('下划线分隔', ad({ name: 'sonnet_reviewer_audit', subagent_type: 'caveman:cavecrew-reviewer' }), 'ALLOW')
agent('内建 Explore 不校验', ad({ name: 'sonnet-find-auth-refs', subagent_type: 'Explore' }), 'ALLOW')
agent('内建 general-purpose 不校验', ad({ name: 'sonnet-fix-login', subagent_type: 'general-purpose' }), 'ALLOW')
agent('无 subagent_type 不校验', ad({ name: 'sonnet-fix-login' }), 'ALLOW')
agent('通用词滤空后跳过 foo:use', ad({ name: 'sonnet-do-thing', subagent_type: 'foo:use' }), 'ALLOW')
agent('fpf:fpf-agent 滤掉 agent 只剩 fpf', ad({ name: 'sonnet-fpf-hypothesis', subagent_type: 'fpf:fpf-agent' }), 'ALLOW')
agent('plugin-validator 命中 plugin', ad({ name: 'sonnet-validate-plugin-json', subagent_type: 'plugin-dev:plugin-validator' }), 'ALLOW')

// 旧判据仍然生效
const adNoModel = agent('旧判据: 缺 model 仍 deny', { name: 'sonnet-debug-keeper-x', description: 'x', subagent_type: 'task-keeper:debug-keeper' }, 'DENY')
check('agent-dispatch: 缺 model 的 finding 仍在', true, /缺 model/.test(adNoModel.detail), adNoModel.detail)
agent('旧判据: 前缀与 model 不符仍 deny', { model: 'opus', name: 'sonnet-debug-keeper-x', description: 'x', subagent_type: 'task-keeper:debug-keeper' }, 'DENY')

// 自动补名路径：补出来的名字自己必须满足 check 8，否则等于补了个 guard 不放行的形态
for (const [label, desc] of [['中文 description', '排查登录超时'], ['ASCII description', 'triage open bugs']]) {
  const r = agent(`缺 name 自动补(${label})`, { model: 'opus', description: desc, subagent_type: 'task-keeper:debug-keeper' }, 'AUTONAME')
  if (r.verdict === 'AUTONAME') {
    check(`agent-dispatch: 自动名含身份词(${label})`, true, /debug|keeper/i.test(r.detail), r.detail)
  }
}

// ── agent-dispatch check 9：keeper 类常驻 agent 固定 opus 档 ──────────
//
// 判据两侧都覆盖：该拦的四条（含 2026-08-03 事故原样）、绝不能误杀的五条。
// 重点是最后两条负向用例——判据只看 subagent_type，不看 name；且白名单式枚举，
// 第三方 keeper-like agent 不在表内不该被牵连。

// 该拦：subagent_type 是两个固定 opus 档 keeper，model 却不是 opus
const adK = agent(
  '本次事故原样 debug-keeper 走 sonnet',
  ad({ name: 'sonnet-debug-keeper-085', subagent_type: 'task-keeper:debug-keeper' }),
  'DENY'
)
check('agent-dispatch: check 9 finding 点明固定档', true, /固定 opus 档的常驻 keeper/.test(adK.detail), adK.detail)
agent('chore-keeper 走 sonnet', ad({ name: 'sonnet-chore-keeper-tidy', subagent_type: 'task-keeper:chore-keeper' }), 'DENY')
agent('debug-keeper 走 fable 同样拦', ad({ model: 'fable', name: 'fable-debug-keeper-x', subagent_type: 'task-keeper:debug-keeper' }), 'DENY')
agent('无冒号裸 debug-keeper 也拦', ad({ name: 'sonnet-debug-keeper-x', subagent_type: 'debug-keeper' }), 'DENY')

// 不得误杀
// name 用「固定前缀 + 4 位短哈希」——2026-08-04 起裸固定名会被 check 10 拦下（那条的
// 用例见下一段），这里要验的是"档位对了就不该被 check 9 拦"，所以 name 必须先满足 check 10。
agent('debug-keeper 走 opus 放行', ad({ model: 'opus', name: 'opus-debug-keeper-4bb6', subagent_type: 'task-keeper:debug-keeper' }), 'ALLOW')
agent('chore-keeper 走 opus 放行', ad({ model: 'opus', name: 'opus-chore-keeper-0a9z', subagent_type: 'task-keeper:chore-keeper' }), 'ALLOW')
agent('非 keeper 的插件专用 agent 不受档位约束', ad({ name: 'sonnet-cavecrew-reviewer-diff', subagent_type: 'caveman:cavecrew-reviewer' }), 'ALLOW')
// 判据取 subagent_type，不取 name——name 里出现 keeper 不构成档位要求
agent('name 含 keeper 但类型是 Explore', ad({ name: 'sonnet-keeper-queue-audit', subagent_type: 'Explore' }), 'ALLOW')
// 白名单式枚举：第三方 keeper-like agent 不在表内，不牵连
agent('第三方 queue-keeper 不在白名单', ad({ name: 'sonnet-queue-keeper-x', subagent_type: 'foo:queue-keeper' }), 'ALLOW')

// 缺 name + 合规 opus → 走自动补名，且补出的名字自己必须满足 check 10 的新形态
// （固定前缀 + 4 位小写字母数字），不能补出一个 guard 自己不放行的名字——这是本仓
// 已经踩过的坑（见 hooks/guards/agent-dispatch.js 的 autoName 注释）。
const adAuto = agent('keeper 缺 name 自动补', { model: 'opus', description: '登记三条新报障', subagent_type: 'task-keeper:debug-keeper' }, 'AUTONAME')
if (adAuto.verdict === 'AUTONAME') {
  check('agent-dispatch: keeper 自动名满足新形态(固定前缀+4位短哈希)', true, /^opus-debug-keeper-[0-9a-z]{4}$/.test(adAuto.detail), adAuto.detail)
}

// ── agent-dispatch check 10：keeper 的 name 必须带 4 位短哈希后缀 ────────
//
// 2026-08-04 用户拍板改：旧判据（逐字钉死固定三段名）本身埋了新坑——同一会话内
// 前一个 keeper 实例结束后，若下一个又派成逐字相同的固定名，`SendMessage` 的
// latest-wins 寻址会让唤醒方分不清唤到的是哪一个。新判据要求 name 必须形如
// `opus-<slug>-xxxx`（`xxxx` 恰好 4 位小写字母数字），强制把"名字不可预测"这个
// 事实暴露出来，逼唤醒方必须先读 `.keeper/<交付id>/.keeper-instance.json` 才能拿到
// 当前有效的 name。与 check 8 的区别：check 8 只防遗忘（随便塞个身份词即可过闸），
// 这条同样不校验后 4 位是不是真的取自哈希，只校验形态——假阴性面是"AI 可以随便编
// 4 个字符"，可接受，见 hooks/guards/agent-dispatch.js check 10 注释里的覆盖边界说明。

// 该拦：旧版逐字固定名现在缺后缀
agent('旧版固定名缺后缀也拦', adO({ name: 'opus-debug-keeper', subagent_type: 'task-keeper:debug-keeper' }), 'DENY')
// 该拦：事故原样的旧三位数字后缀，形态本身没问题（3 位不是 4 位），仍要拦
const ad10 = agent('事故原样 opus-debug-keeper-085 位数不对', adO({ name: 'opus-debug-keeper-085', subagent_type: 'task-keeper:debug-keeper' }), 'DENY')
check('agent-dispatch: check 10 finding 给出新形态提示', true, /必须形如 "opus-debug-keeper-xxxx"/.test(ad10.detail), ad10.detail)
// 该拦：大写
agent('后缀大写也拦', adO({ name: 'opus-debug-keeper-4BB6', subagent_type: 'task-keeper:debug-keeper' }), 'DENY')
// 该拦：3 位
agent('后缀 3 位也拦', adO({ name: 'opus-debug-keeper-4bb', subagent_type: 'task-keeper:debug-keeper' }), 'DENY')
// 该拦：5 位
agent('后缀 5 位也拦', adO({ name: 'opus-debug-keeper-4bb6c', subagent_type: 'task-keeper:debug-keeper' }), 'DENY')
agent('chore-keeper 缺后缀也拦', adO({ name: 'opus-chore-keeper', subagent_type: 'task-keeper:chore-keeper' }), 'DENY')
agent('身份词乱序拼名也拦', adO({ name: 'opus-keeper-debug-4bb6', subagent_type: 'task-keeper:debug-keeper' }), 'DENY')

// 不得误杀：新形态（固定前缀 + 4 位小写字母数字）
agent('debug-keeper 新形态放行', adO({ name: 'opus-debug-keeper-4bb6', subagent_type: 'task-keeper:debug-keeper' }), 'ALLOW')
agent('chore-keeper 新形态放行', adO({ name: 'opus-chore-keeper-0a9z', subagent_type: 'task-keeper:chore-keeper' }), 'ALLOW')
// 非 keeper 的插件专用 agent 不受这条约束，仍是"含身份词即可"
agent('cavecrew-reviewer 带任务后缀不受这条约束', ad({ name: 'sonnet-cavecrew-reviewer-diff-audit', subagent_type: 'caveman:cavecrew-reviewer' }), 'ALLOW')
// 白名单式枚举：第三方 keeper-like agent 不在表内，名字自由
agent('第三方 queue-keeper 名字自由', ad({ name: 'sonnet-queue-keeper-anything', subagent_type: 'foo:queue-keeper' }), 'ALLOW')

// ── 收尾 ────────────────────────────────────────────────────────────
fs.rmSync(FIXTURE_ROOT, { recursive: true, force: true })

const total = pass + failures.length
if (failures.length === 0) {
  console.log(`✓ guard 回归 ${total}/${total} 全部通过`)
  process.exit(0)
}

console.log(`✗ guard 回归 ${pass}/${total} 通过，${failures.length} 条失败：\n`)
// agent-dispatch 的用例断言的是字符串判定（DENY / ALLOW / AUTONAME）与布尔，
// 不是退出码；直接套 BLOCK/PASS 映射会把 'DENY' 显示成 'PASS'，反向误导。
const verdictLabel = (v) => (v === BLOCK ? 'BLOCK' : v === PASS ? 'PASS' : String(v))

for (const f of failures) {
  const want = verdictLabel(f.expect)
  const got = verdictLabel(f.actual)
  console.log(`  [want ${want} got ${got}] ${f.label}`)
  if (f.detail) console.log(`      ${f.detail}`)
}
process.exit(1)
