#!/usr/bin/env node
// cd-guard.test.js — cd-guard 的回归套件
//
// 用法：node plugins/cd-blocker/tests/cd-guard.test.js
// 退出码 0 = 全绿，1 = 有用例失败。
//
// 【为什么用 spawnSync 而不是 shell 管道】
// guard 的输入是命令字符串，而测试数据里大量出现引号、heredoc、子 shell。若用
// `echo '<payload>' | node <guard>` 这种形式，测试脚本自身的 shell 引号一旦失衡，
// 后面的测试数据就变成裸命令——2026-07-31 审计真撞过一次：guard 把审计脚本里 20 多行
// 测试数据当成真命令拦下，并原样回灌进 finding（单条撑到 900+ 字符）。spawnSync 直接
// 把字符串写进子进程 stdin，全程不经过 shell，杜绝这类自伤。
//
// 【判据两侧都要有用例】
// 每组都同时覆盖「曾经误杀、现在应放行」与「原本正确拦截、现在仍应拦截」。只测前者会
// 把 guard 改废；只测后者发现不了误杀。
//
// 【cwd 用真实临时目录】
// no-op 判定要 realpath 与大小写归一，都需要目标目录真实存在——用一个不存在的假路径
// 当 cwd，符号链接那两条用例会静默退化成字符串比较，测不到它们要测的东西。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')

const GUARD = path.join(__dirname, '..', 'hooks', 'guards', 'cd-guard.js')

const FIXTURE_ROOT = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'cd-guard-')))
const PROJECT = path.join(FIXTURE_ROOT, 'proj')
fs.mkdirSync(PROJECT, { recursive: true })

let pass = 0
const failures = []

function check(label, expect, actual, detail) {
  if (expect === actual) {
    pass++
    return
  }
  failures.push({ label, expect, actual, detail })
}

function run(payload, env) {
  const r = spawnSync('node', [GUARD], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    env: env ? { ...process.env, ...env } : process.env,
  })
  return { code: r.status, err: (r.stderr || '').trim() }
}

function bash(label, command, cwd, expect, env) {
  const r = run({ tool_name: 'Bash', tool_input: { command }, cwd }, env)
  check(label, expect, r.code, r.err)
  return r
}

const BLOCK = 2
const PASS = 0

// ── 曾经误杀，现在应放行 ──────────────────────────────────────────────
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
  // macOS 上 /tmp 是 /private/tmp 的符号链接；只做字符串归一会误拦
  bash('符号链接等价 (/tmp ↔ /private/tmp)', 'cd /tmp', '/private/tmp', PASS)
  // APFS 默认大小写不敏感
  bash('大小写等价路径', `cd ${PROJECT.replace('/Users/', '/users/')}`, PROJECT, PASS)
}

// ── 仍必须拦 ─────────────────────────────────────────────────────────
const blocked = bash('裸 cd', 'cd /tmp', PROJECT, BLOCK)
check('finding 回灌违规片段', true, /违规片段：cd \/tmp/.test(blocked.err), blocked.err)
check('hint 给出子 shell 模板', true, /\(cd \/abs\/path && cmd\)/.test(blocked.err), blocked.err)
check('hint 给出 git -C 模板', true, /git -C <path> <cmd>/.test(blocked.err), blocked.err)
check('hint 指出停用途径', true, /CD_GUARD=off|cd-blocker/.test(blocked.err), blocked.err)

bash('链尾 cd', 'ls && cd /tmp', PROJECT, BLOCK)
bash('换行后 cd', 'npm run build\ncd dist && ls', PROJECT, BLOCK)
bash('cd ..', 'cd ..', PROJECT, BLOCK)
bash('cd 无参数(回 home)', 'cd', PROJECT, BLOCK)
bash('子 shell 之后仍有裸 cd', '(cd /tmp && ls) && cd /var', PROJECT, BLOCK)
bash('heredoc 结束之后的真 cd', "cat <<'EOF'\nhello\nEOF\ncd /tmp", PROJECT, BLOCK)

// ── 原本正确放行，不得因收窄而回归成误杀 ──────────────────────────────
bash('子 shell', '(cd /tmp && ls)', PROJECT, PASS)
bash('嵌套子 shell', '(cd /tmp && (cd /var && ls))', PROJECT, PASS)
bash('命令替换 $()', 'X=$(cd /tmp && pwd)', PROJECT, PASS)
bash('字符串内的 cd', 'echo "cd /tmp" | bash', PROJECT, PASS)
bash('cd .', 'cd .', PROJECT, PASS)
bash('cd 当前目录绝对路径', `cd ${PROJECT}`, PROJECT, PASS)
bash('here-string 不是 heredoc', 'bash <<< "echo hi"', PROJECT, PASS)

// ── 逃生口与基础设施异常 ──────────────────────────────────────────────
// CD_GUARD=off 是本插件唯一的单次逃生口；它失效就只剩"停用整个插件"这一条路，
// 而那要用户去 /plugin 操作，长任务中途没法用。
bash('CD_GUARD=off 放行', 'cd /tmp', PROJECT, PASS, { CD_GUARD: 'off' })
bash('CD_GUARD 非 off 不放行', 'cd /tmp', PROJECT, BLOCK, { CD_GUARD: '1' })

check('tool_name 非 Bash 不管', PASS, run({ tool_name: 'Read', tool_input: { command: 'cd /tmp' }, cwd: PROJECT }).code)
check('command 缺失', PASS, run({ tool_name: 'Bash', tool_input: {}, cwd: PROJECT }).code)
check('stdin 不是 JSON 时放行', PASS, spawnSync('node', [GUARD], { input: 'not json', encoding: 'utf8' }).status)
// cwd 缺失时回落 process.cwd()，不能因此崩掉或误拦
check('cwd 缺失不崩', BLOCK, run({ tool_name: 'Bash', tool_input: { command: 'cd /definitely-not-cwd' } }).code)

// ── 收尾 ─────────────────────────────────────────────────────────────
fs.rmSync(FIXTURE_ROOT, { recursive: true, force: true })

const total = pass + failures.length
if (failures.length === 0) {
  console.log(`✓ cd-guard 回归 ${total}/${total} 全部通过`)
  process.exit(0)
}

console.log(`✗ cd-guard 回归 ${pass}/${total} 通过，${failures.length} 条失败：\n`)
const verdictLabel = (v) => (v === BLOCK ? 'BLOCK' : v === PASS ? 'PASS' : String(v))
for (const f of failures) {
  console.log(`  [want ${verdictLabel(f.expect)} got ${verdictLabel(f.actual)}] ${f.label}`)
  if (f.detail) console.log(`      ${f.detail}`)
}
process.exit(1)
