#!/usr/bin/env node
// guard-verify.js — bash-guard / write-guard 的回归套件
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

function run(guard, payload) {
  const r = spawnSync('node', [guard], { input: JSON.stringify(payload), encoding: 'utf8' })
  return { code: r.status, err: (r.stderr || '').trim() }
}

function check(label, expect, actual, detail) {
  if (expect === actual) {
    pass++
    return
  }
  failures.push({ label, expect, actual, detail })
}

function bash(label, command, cwd, expect) {
  const r = run(BASH_GUARD, { tool_name: 'Bash', tool_input: { command }, cwd })
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

// ── bash-guard / agent-browser ──────────────────────────────────────
// 3.6.0 前误杀，现在应放行
bash('open --help', 'agent-browser open --help', PROJECT, PASS)
bash('connect --help', 'agent-browser connect --help', PROJECT, PASS)
bash('open --version', 'agent-browser open --version', PROJECT, PASS)
bash('grep 参数里的 agent-browser', 'grep -rn agent-browser open /tmp', PROJECT, PASS)
bash('AGENT_BROWSER_HEADED=1', 'AGENT_BROWSER_HEADED=1 AGENT_BROWSER_PROFILE=/tmp/p agent-browser open https://x', PROJECT, PASS)
bash('AGENT_BROWSER_HEADED=on', 'AGENT_BROWSER_HEADED=on AGENT_BROWSER_PROFILE=/tmp/p agent-browser open https://x', PROJECT, PASS)

// 3.6.0 把全局口令收窄到单次调用的 tail 后，应新拦住
bash('口令: 另一命令里 echo "--headed"', 'agent-browser open https://x --profile /tmp/p && echo "--headed"', PROJECT, BLOCK)
bash('口令: 另一片段的 --headed', 'echo --headed; agent-browser open https://x --profile /tmp/p', PROJECT, BLOCK)
bash('口令: JSON 参数里的 --headed', 'agent-browser open https://y --profile /p --json "{--headed}"', PROJECT, BLOCK)
bash('口令: 另一片段的 PROFILE 环境变量', 'echo AGENT_BROWSER_PROFILE=/x; agent-browser open https://y --headed', PROJECT, BLOCK)
bash('--profile= 空值', 'agent-browser open https://x --headed --profile=""', PROJECT, BLOCK)
bash('--profile 分离空值', 'agent-browser open https://x --headed --profile ""', PROJECT, BLOCK)
bash('绝对路径调用', '/usr/local/bin/agent-browser open https://x', PROJECT, BLOCK)

// 回归：正常用法不得误拦
bash('完整参数', 'agent-browser open https://x --headed --profile /tmp/p', PROJECT, PASS)
bash('npx 前缀', 'npx agent-browser open https://x --headed --profile /p', PROJECT, PASS)
bash('--headed=false 显式 headless', 'agent-browser open https://x --headed=false --profile /p', PROJECT, PASS)
bash('--headed false 显式 headless', 'agent-browser open https://x --headed false --profile /p', PROJECT, PASS)
bash('白名单子命令', 'agent-browser snapshot', PROJECT, PASS)
bash('chat REPL 无 URL', 'agent-browser chat', PROJECT, PASS)
bash('chat 带 URL 缺参数', 'agent-browser chat https://x', PROJECT, BLOCK)
bash('未知子命令按设计放行', 'agent-browser goto https://x', PROJECT, PASS)
bash('--profile 的值恰为 open', 'agent-browser --profile open snapshot', PROJECT, PASS)

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

// ── 收尾 ────────────────────────────────────────────────────────────
fs.rmSync(FIXTURE_ROOT, { recursive: true, force: true })

const total = pass + failures.length
if (failures.length === 0) {
  console.log(`✓ guard 回归 ${total}/${total} 全部通过`)
  process.exit(0)
}

console.log(`✗ guard 回归 ${pass}/${total} 通过，${failures.length} 条失败：\n`)
for (const f of failures) {
  const want = f.expect === BLOCK ? 'BLOCK' : 'PASS'
  const got = f.actual === BLOCK ? 'BLOCK' : 'PASS'
  console.log(`  [want ${want} got ${got}] ${f.label}`)
  if (f.detail) console.log(`      ${f.detail}`)
}
process.exit(1)
