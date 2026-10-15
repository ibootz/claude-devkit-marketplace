#!/usr/bin/env node
// run-unit-tests.js — 按单测声明 unit-tests.json 跑插件的确定性单测
//
// 【单测声明】
// 插件根下的 unit-tests.json，随插件分发。格式（spec 2.7，issue 18 拍板）：
//   { "tests": [ { "run": ["node", "tests/x.test.js"], "timeout_sec": 120, "platforms": ["darwin", "linux"] } ] }
// - run（必填）：argv 数组，首元素是解释器名，不经 shell；工作目录固定为插件根
// - timeout_sec（可选，缺省 120）：正数，超时判失败
// - platforms（可选，缺省全部）：darwin / linux / win32 的非空子集
// 不收其它字段。同一份声明还由 devkit-plugin-eval 的 Python 闸门检查命令读，两边判定靠
// scripts/unit-tests-fixtures/ 的共用样例对齐：改了这里的判定规则，先改样例与 expected.json。
//
// 【用法】
//   node scripts/run-unit-tests.js --staged              # pre-commit 用：按暂存路径选插件
//   node scripts/run-unit-tests.js plugins/devkit-tool   # 手动跑指定插件（可多个）
//   --json                 # 输出结构化结果（样例对齐用），不改变退出码
//   --platform <p>         # 覆盖当前平台，只影响 platforms 过滤（样例对齐用）
//
// 【判据】（pre-commit 口径；闸门检查命令另有口径，见 spec 2.7 的对照表）
// - 暂存路径命中 plugins/<name>/** 的插件被选中；plugin-evals/<name>/ 不算；插件目录已删则跳过
// - 未声明（无 unit-tests.json）：静默放行；--staged 之外手动跑时提示一行
// - 声明不合法：拦
// - 当前平台不在 platforms：跳过并提示；解释器解析不到：跳过并警告
// - 任一条退出码非零或超时：拦
// 退出码：0 放行，1 拦下，2 用法错误。
//
// 【子进程环境去掉 git 的仓库级环境变量】
// git 调 hook 时会注入 GIT_DIR、GIT_INDEX_FILE 等（git rev-parse --local-env-vars 列出的那一组）。
// 单测里常有在临时目录 git init 再操作的用例，继承这些变量后 git 命令会打到本仓的索引上——
// 轻则单测莫名失败，重则把临时文件写进本次提交。所以跑单测前一律剥掉。

'use strict'

const fs = require('fs')
const path = require('path')
const { spawn, spawnSync } = require('child_process')

const ROOT = path.resolve(__dirname, '..')
const DECL_NAME = 'unit-tests.json'
const DEFAULT_TIMEOUT_SEC = 120
const PLATFORMS = ['darwin', 'linux', 'win32']
const TOP_FIELDS = ['tests']
const TEST_FIELDS = ['run', 'timeout_sec', 'platforms']
const OUTPUT_TAIL_LINES = 40
// git rev-parse --local-env-vars 不可用时的兜底清单（git 2.x 的输出）
const FALLBACK_GIT_LOCAL_ENV = [
  'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_CONFIG', 'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT',
  'GIT_OBJECT_DIRECTORY', 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_IMPLICIT_WORK_TREE', 'GIT_GRAFT_FILE',
  'GIT_INDEX_FILE', 'GIT_NO_REPLACE_OBJECTS', 'GIT_REPLACE_REF_BASE', 'GIT_PREFIX',
  'GIT_SHALLOW_FILE', 'GIT_COMMON_DIR',
]

// ---------- 声明校验 ----------

// 返回 { tests, errors }。errors 每项 { code, message }；code 是与 Python 实现对齐的稳定标识：
// not-json / not-object / unknown-field / bad-tests / bad-test / bad-run / bad-timeout / bad-platforms
function validateDeclaration(text) {
  const errors = []
  const err = (code, message) => errors.push({ code, message })
  let decl
  try {
    decl = JSON.parse(text)
  } catch (e) {
    err('not-json', `不是合法 JSON：${e.message}`)
    return { tests: [], errors }
  }
  if (!isPlainObject(decl)) {
    err('not-object', '顶层必须是对象 {"tests": [...]}')
    return { tests: [], errors }
  }
  for (const k of Object.keys(decl)) {
    if (!TOP_FIELDS.includes(k)) err('unknown-field', `顶层有约定外字段 "${k}"，只允许 tests`)
  }
  if (!Array.isArray(decl.tests)) {
    err('bad-tests', 'tests 必填，且必须是数组')
    return { tests: [], errors }
  }
  const tests = []
  decl.tests.forEach((t, i) => {
    const at = `tests[${i}]`
    if (!isPlainObject(t)) {
      err('bad-test', `${at} 必须是对象`)
      return
    }
    for (const k of Object.keys(t)) {
      if (!TEST_FIELDS.includes(k)) err('unknown-field', `${at} 有约定外字段 "${k}"，只允许 ${TEST_FIELDS.join(' / ')}`)
    }
    const run = t.run
    if (!Array.isArray(run) || run.length === 0 || !run.every((a) => typeof a === 'string' && a !== '')) {
      err('bad-run', `${at}.run 必填，且必须是非空字符串组成的非空数组`)
    }
    if ('timeout_sec' in t) {
      const v = t.timeout_sec
      if (typeof v !== 'number' || !Number.isFinite(v) || v <= 0) err('bad-timeout', `${at}.timeout_sec 必须是正数（秒）`)
    }
    if ('platforms' in t) {
      const p = t.platforms
      if (!Array.isArray(p) || p.length === 0 || !p.every((x) => PLATFORMS.includes(x))) {
        err('bad-platforms', `${at}.platforms 必须是 ${PLATFORMS.join(' / ')} 的非空子集`)
      }
    }
    tests.push({
      run,
      timeoutSec: 'timeout_sec' in t ? t.timeout_sec : DEFAULT_TIMEOUT_SEC,
      platforms: 'platforms' in t ? t.platforms : PLATFORMS,
    })
  })
  return { tests: errors.length ? [] : tests, errors }
}

function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v)
}

// ---------- 选插件 ----------

// 暂存路径 → 被改插件名（去重、保序）。只认 plugins/<name>/ 下的文件。
function selectPlugins(paths) {
  const names = []
  for (const p of paths) {
    const m = /^plugins\/([^/]+)\/./.exec(p.replace(/\\/g, '/'))
    if (m && !names.includes(m[1])) names.push(m[1])
  }
  return names
}

function stagedPaths() {
  // --no-renames：改名时旧路径与新路径都列出，两边插件都会被选中
  const r = spawnSync('git', ['diff', '--cached', '--name-only', '--no-renames', '-z'], { cwd: ROOT, encoding: 'utf8' })
  if (r.status !== 0) throw new Error(`git diff --cached 失败：${(r.stderr || '').trim()}`)
  return r.stdout.split('\0').filter(Boolean)
}

// ---------- 解释器解析 ----------

// 判断一条 argv 能否执行一次 `--version` 成功。注入 probe 便于单测。
function defaultProbe(argv) {
  const exe = findExecutable(argv[0])
  if (!exe) return false
  const r = spawnSync(exe, [...argv.slice(1), '--version'], { stdio: 'ignore', timeout: 10000, windowsHide: true, shell: needsShell(exe) })
  return r.status === 0
}

// 返回解析后的 argv 前缀（数组）或 null。
// python3 依次试 python3 → python → py -3，以实际执行 --version 成功为准：Windows 的
// WindowsApps\python3 是 Microsoft Store 零字节桩，PATH 上查得到却跑不了。
// 其余解释器只解析出可执行文件路径（Windows 上可能是 .cmd）；带路径分隔符的相对插件根解析。
function resolveInterpreter(name, { cwd = process.cwd(), probe = defaultProbe, find = (n) => findExecutable(n, { cwd }) } = {}) {
  if (name === 'python3') {
    for (const cand of [['python3'], ['python'], ['py', '-3']]) {
      if (probe(cand)) return [find(cand[0]) || cand[0], ...cand.slice(1)]
    }
    return null
  }
  const exe = find(name)
  return exe ? [exe] : null
}

function findExecutable(name, { cwd = process.cwd(), env = process.env, platform = process.platform } = {}) {
  if (name.includes('/') || name.includes('\\')) {
    const full = path.resolve(cwd, name)
    return isFile(full) ? full : null
  }
  const exts = platform === 'win32' ? ['', ...(env.PATHEXT || '.COM;.EXE;.BAT;.CMD').split(';').filter(Boolean)] : ['']
  for (const dir of (env.PATH || '').split(path.delimiter)) {
    if (!dir) continue
    for (const ext of exts) {
      const full = path.join(dir, name + ext)
      if (isFile(full) && (platform === 'win32' || isExecutable(full))) return full
    }
  }
  return null
}

function isFile(p) {
  try {
    return fs.statSync(p).isFile()
  } catch {
    return false
  }
}

function isExecutable(p) {
  try {
    fs.accessSync(p, fs.constants.X_OK)
    return true
  } catch {
    return false
  }
}

// Windows 上 .cmd / .bat 不能直接 spawn（Node 18.20+ 报 EINVAL），要经 cmd.exe
function needsShell(exe) {
  return process.platform === 'win32' && /\.(cmd|bat)$/i.test(exe)
}

// ---------- 执行 ----------

function childEnv() {
  const env = { ...process.env }
  const r = spawnSync('git', ['rev-parse', '--local-env-vars'], { encoding: 'utf8' })
  const names = r.status === 0 ? r.stdout.split(/\r?\n/).filter(Boolean) : FALLBACK_GIT_LOCAL_ENV
  for (const n of names) delete env[n]
  return env
}

// 跑一条命令，返回 { status: 'passed'|'failed'|'timeout', code, output, ms }
function runOne(argv, cwd, timeoutSec, env) {
  return new Promise((resolve) => {
    const started = Date.now()
    const shell = needsShell(argv[0])
    const cmd = shell ? argv.map((a) => `"${a}"`).join(' ') : argv[0]
    const child = spawn(cmd, shell ? [] : argv.slice(1), {
      cwd,
      env,
      shell,
      windowsHide: true,
      // POSIX 下自成进程组，超时时整组杀掉：bash 单测拉起的孙进程不然会攥着输出管道不放
      detached: process.platform !== 'win32',
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    const chunks = []
    child.stdout.on('data', (d) => chunks.push(d))
    child.stderr.on('data', (d) => chunks.push(d))
    let timedOut = false
    let exitCode = null
    let done = false
    const finish = (spawnError) => {
      if (done) return
      done = true
      clearTimeout(timer)
      clearTimeout(grace)
      child.stdout.destroy()
      child.stderr.destroy()
      let output = Buffer.concat(chunks).toString('utf8')
      if (spawnError) output += `\n启动失败：${spawnError.message}`
      const status = timedOut ? 'timeout' : exitCode === 0 ? 'passed' : 'failed'
      resolve({ status, code: exitCode, output, ms: Date.now() - started })
    }
    // 正常路径等 close（输出读全）；子进程已退出但孙进程攥着管道时，宽限 2 秒后按退出码收尾
    let grace = null
    const timer = setTimeout(() => {
      timedOut = true
      killTree(child)
      grace = setTimeout(() => finish(), 2000)
    }, timeoutSec * 1000)
    child.on('error', (e) => finish(e))
    child.on('exit', (code) => {
      exitCode = code
      if (!grace) grace = setTimeout(() => finish(), 2000)
    })
    child.on('close', () => finish())
  })
}

function killTree(child) {
  try {
    if (process.platform === 'win32') {
      spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true })
    } else {
      process.kill(-child.pid, 'SIGKILL')
    }
  } catch {
    try {
      child.kill('SIGKILL')
    } catch {}
  }
}

// 对一个插件目录给出结构化结果：
// { plugin, declaration: 'undeclared'|'invalid'|'ok', errors: [code...], messages: [...],
//   tests: [{ index, run, status, code?, ms?, output? }] }
// 每条 status 取值：passed / failed / timeout / skipped-platform / interpreter-missing
async function runPlugin(pluginDir, { platform = process.platform, env = childEnv(), resolve = resolveInterpreter } = {}) {
  const result = { plugin: path.basename(pluginDir), declaration: 'undeclared', errors: [], messages: [], tests: [] }
  const declPath = path.join(pluginDir, DECL_NAME)
  if (!isFile(declPath)) return result
  const { tests, errors } = validateDeclaration(fs.readFileSync(declPath, 'utf8'))
  if (errors.length) {
    result.declaration = 'invalid'
    result.errors = [...new Set(errors.map((e) => e.code))].sort()
    result.messages = errors.map((e) => e.message)
    return result
  }
  result.declaration = 'ok'
  for (const [index, t] of tests.entries()) {
    const entry = { index, run: t.run }
    result.tests.push(entry)
    if (!t.platforms.includes(platform)) {
      entry.status = 'skipped-platform'
      continue
    }
    const prefix = resolve(t.run[0], { cwd: pluginDir })
    if (!prefix) {
      entry.status = 'interpreter-missing'
      continue
    }
    const r = await runOne([...prefix, ...t.run.slice(1)], pluginDir, t.timeoutSec, env)
    Object.assign(entry, r)
  }
  return result
}

// pre-commit 口径：声明不合法、任一条 failed / timeout 即拦
function precommitVerdict(result) {
  if (result.declaration === 'invalid') return 'block'
  return result.tests.some((t) => t.status === 'failed' || t.status === 'timeout') ? 'block' : 'pass'
}

// ---------- 输出 ----------

function report(result, { quietUndeclared }) {
  const tag = `[unit-tests] ${result.plugin}`
  if (result.declaration === 'undeclared') {
    if (!quietUndeclared) console.log(`${tag}：未声明单测（无 ${DECL_NAME}），跳过`)
    return
  }
  if (result.declaration === 'invalid') {
    console.error(`${tag}：${DECL_NAME} 不合法，已拦下`)
    for (const m of result.messages) console.error(`  - ${m}`)
    return
  }
  for (const t of result.tests) {
    const label = `tests[${t.index}] ${t.run.join(' ')}`
    switch (t.status) {
      case 'passed':
        console.log(`${tag}：✓ ${label}（${(t.ms / 1000).toFixed(1)}s）`)
        break
      case 'skipped-platform':
        console.log(`${tag}：跳过 ${label}——当前平台不在 platforms 里`)
        break
      case 'interpreter-missing':
        console.error(`${tag}：⚠ 跳过 ${label}——解释器 ${t.run[0]} 解析不到`)
        break
      case 'timeout':
      case 'failed': {
        const why = t.status === 'timeout' ? `超时（${(t.ms / 1000).toFixed(1)}s）` : `退出码 ${t.code}`
        console.error(`${tag}：✗ ${label}——${why}`)
        const lines = (t.output || '').trimEnd().split(/\r?\n/)
        if (lines.length > OUTPUT_TAIL_LINES) console.error(`    ……（省略前 ${lines.length - OUTPUT_TAIL_LINES} 行）`)
        for (const l of lines.slice(-OUTPUT_TAIL_LINES)) console.error(`    ${l}`)
        break
      }
    }
  }
}

function parseArgs(argv) {
  const opts = { staged: false, json: false, platform: process.platform, dirs: [] }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--staged') opts.staged = true
    else if (a === '--json') opts.json = true
    else if (a === '--platform') opts.platform = argv[++i]
    else if (a.startsWith('--')) throw new Error(`未知参数 ${a}`)
    else opts.dirs.push(a)
  }
  if (opts.staged === (opts.dirs.length > 0)) throw new Error('用 --staged，或给出插件目录，二选一')
  if (!PLATFORMS.includes(opts.platform)) throw new Error(`--platform 只接受 ${PLATFORMS.join(' / ')}`)
  return opts
}

async function main() {
  let opts
  try {
    opts = parseArgs(process.argv.slice(2))
  } catch (e) {
    console.error(`[unit-tests] ${e.message}`)
    console.error('用法：node scripts/run-unit-tests.js --staged | <插件目录>... [--json] [--platform darwin|linux|win32]')
    process.exit(2)
  }
  const dirs = opts.staged
    ? selectPlugins(stagedPaths()).map((n) => path.join(ROOT, 'plugins', n))
    : opts.dirs.map((d) => path.resolve(d))
  const env = childEnv()
  const results = []
  for (const dir of dirs) {
    // 插件目录已删（本次提交删插件）则跳过
    if (!fs.existsSync(dir)) continue
    const r = await runPlugin(dir, { platform: opts.platform, env })
    results.push(r)
    if (!opts.json) report(r, { quietUndeclared: opts.staged })
  }
  const blocked = results.filter((r) => precommitVerdict(r) === 'block')
  if (opts.json) {
    console.log(JSON.stringify(results.map((r) => ({ ...r, verdict: precommitVerdict(r) })), null, 2))
  } else if (blocked.length) {
    console.error(`\n[unit-tests] ${blocked.map((r) => r.plugin).join('、')} 的单测未通过，本次提交已拦下。`)
    console.error('  确需带着失败的单测提交：git commit --no-verify')
  }
  // 用 exitCode 而不是 process.exit：macOS 上 stdout 接管道时是异步写，exit 会截断 --json 的输出
  process.exitCode = blocked.length ? 1 : 0
}

module.exports = { validateDeclaration, selectPlugins, resolveInterpreter, findExecutable, childEnv, runPlugin, precommitVerdict }

if (require.main === module) main()
