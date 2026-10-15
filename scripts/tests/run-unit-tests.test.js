#!/usr/bin/env node
// run-unit-tests.test.js — scripts/run-unit-tests.js 的单测，含共用声明样例的对齐
//
// 用法：
//   node scripts/tests/run-unit-tests.test.js            # 跑全部
//   node scripts/tests/run-unit-tests.test.js --update   # 按当前实现重写各样例的 expected.json
//
// --update 只在有意改判定规则时用；改完同步告知 devkit-plugin-eval 的 Python 实现，两边要对齐。

'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')
const lib = require('../run-unit-tests.js')

const FIXTURES = path.resolve(__dirname, '..', 'unit-tests-fixtures')
const UPDATE = process.argv.includes('--update')

const codes = (text) => [...new Set(lib.validateDeclaration(text).errors.map((e) => e.code))].sort()

test('声明校验：合法声明补齐缺省值', () => {
  const { tests, errors } = lib.validateDeclaration('{"tests":[{"run":["node","a.js"]}]}')
  assert.deepEqual(errors, [])
  assert.deepEqual(tests, [{ run: ['node', 'a.js'], timeoutSec: 120, platforms: ['darwin', 'linux', 'win32'] }])
})

test('声明校验：各类不合法给出稳定 code', () => {
  assert.deepEqual(codes('{'), ['not-json'])
  assert.deepEqual(codes('null'), ['not-object'])
  assert.deepEqual(codes('{"tests":{}}'), ['bad-tests'])
  assert.deepEqual(codes('{"tests":[1]}'), ['bad-test'])
  assert.deepEqual(codes('{"tests":[{"run":["node",""]}]}'), ['bad-run'])
  assert.deepEqual(codes('{"tests":[{"run":["node",1]}]}'), ['bad-run'])
  assert.deepEqual(codes('{"tests":[{"run":["node"],"timeout_sec":-1}]}'), ['bad-timeout'])
  assert.deepEqual(codes('{"tests":[{"run":["node"],"platforms":"linux"}]}'), ['bad-platforms'])
  assert.deepEqual(codes('{"tests":[],"version":1}'), ['unknown-field'])
})

test('选插件：只认 plugins/<name>/ 下的文件，去重保序', () => {
  assert.deepEqual(
    lib.selectPlugins([
      'plugins/devkit-tool/README.md',
      'plugin-evals/devkit-spec/drafts/a.json',
      'plugins/devkit-spec/unit-tests.json',
      'plugins/devkit-tool/hooks/x.js',
      'plugins/README.md',
      'scripts/check-versions.js',
      'plugins\\devkit-omp\\a.md',
    ]),
    ['devkit-tool', 'devkit-spec', 'devkit-omp'],
  )
})

test('解释器：python3 依次试 python3 → python → py -3，以 probe 成功为准', () => {
  const tried = []
  const probeOk = (ok) => (argv) => {
    tried.push(argv.join(' '))
    return argv.join(' ') === ok
  }
  const find = (n) => `/bin/${n}`
  assert.deepEqual(lib.resolveInterpreter('python3', { probe: probeOk('python'), find }), ['/bin/python'])
  assert.deepEqual(tried, ['python3', 'python'])
  assert.deepEqual(lib.resolveInterpreter('python3', { probe: probeOk('py -3'), find }), ['/bin/py', '-3'])
  assert.equal(lib.resolveInterpreter('python3', { probe: () => false, find }), null)
  assert.equal(lib.resolveInterpreter('bash', { find: () => null }), null)
})

test('解释器：Windows 按 PATHEXT 找到 .cmd', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rut-pathext-'))
  fs.writeFileSync(path.join(dir, 'tool.cmd'), '')
  const found = lib.findExecutable('tool', { env: { PATH: dir, PATHEXT: '.EXE;.CMD' }, platform: 'win32' })
  // macOS 默认文件系统不分大小写，PATHEXT 的 .CMD 也能命中 tool.cmd
  assert.equal(found.toLowerCase(), path.join(dir, 'tool.cmd').toLowerCase())
  fs.rmSync(dir, { recursive: true, force: true })
})

test('子进程环境剥掉 git 注入的仓库级变量', () => {
  const saved = process.env.GIT_INDEX_FILE
  process.env.GIT_INDEX_FILE = '/nonexistent/index'
  try {
    const env = lib.childEnv()
    assert.equal(env.GIT_INDEX_FILE, undefined)
    assert.equal(env.PATH, process.env.PATH)
  } finally {
    if (saved === undefined) delete process.env.GIT_INDEX_FILE
    else process.env.GIT_INDEX_FILE = saved
  }
})

test('超时：孙进程攥着输出管道也能按时判超时', { skip: process.platform === 'win32' }, async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rut-grandchild-'))
  fs.writeFileSync(path.join(dir, 'unit-tests.json'), JSON.stringify({ tests: [{ run: ['node', 'hang.js'], timeout_sec: 1 }] }))
  // 拉起一个继承 stdout 的孙进程，自己也不退出
  fs.writeFileSync(path.join(dir, 'hang.js'), "require('child_process').spawn('sleep', ['30'], { stdio: 'inherit' }); setTimeout(() => {}, 30000)\n")
  const started = Date.now()
  const r = await lib.runPlugin(dir, { env: process.env })
  assert.equal(r.tests[0].status, 'timeout')
  assert.ok(Date.now() - started < 6000, `耗时 ${Date.now() - started}ms`)
  fs.rmSync(dir, { recursive: true, force: true })
})

test('退出：子进程已退出、孙进程攥着管道时按退出码收尾，不误判超时', { skip: process.platform === 'win32' }, async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rut-orphan-'))
  fs.writeFileSync(path.join(dir, 'unit-tests.json'), JSON.stringify({ tests: [{ run: ['node', 'orphan.js'], timeout_sec: 20 }] }))
  fs.writeFileSync(path.join(dir, 'orphan.js'), "require('child_process').spawn('sleep', ['5'], { stdio: 'inherit', detached: true }).unref()\n")
  const started = Date.now()
  const r = await lib.runPlugin(dir, { env: process.env })
  assert.equal(r.tests[0].status, 'passed')
  assert.ok(Date.now() - started < 4500, `耗时 ${Date.now() - started}ms`)
  fs.rmSync(dir, { recursive: true, force: true })
})

test('CLI：--staged 与插件目录不能同给、--platform 取值受限', () => {
  const cli = path.resolve(__dirname, '..', 'run-unit-tests.js')
  assert.equal(spawnSync(process.execPath, [cli]).status, 2)
  assert.equal(spawnSync(process.execPath, [cli, '--staged', 'plugins/x']).status, 2)
  assert.equal(spawnSync(process.execPath, [cli, 'plugins/x', '--platform', 'macos']).status, 2)
})

// ---------- 共用声明样例 ----------
// 每个样例目录相当于一个插件根；expected.json 是本 JS 实现的判定结果，Python 实现照它对齐。

function normalize(result, platform) {
  return {
    platform,
    declaration: result.declaration,
    errors: result.errors,
    tests: result.tests.map((t) => ({ index: t.index, status: t.status })),
    precommit: lib.precommitVerdict(result),
  }
}

for (const name of fs.readdirSync(FIXTURES).sort()) {
  const dir = path.join(FIXTURES, name)
  if (!fs.statSync(dir).isDirectory()) continue
  test(`共用样例 ${name}`, async () => {
    const expectedPath = path.join(dir, 'expected.json')
    const platform = fs.existsSync(expectedPath) ? JSON.parse(fs.readFileSync(expectedPath, 'utf8')).platform : 'linux'
    const actual = normalize(await lib.runPlugin(dir, { platform, env: lib.childEnv() }), platform)
    if (UPDATE) fs.writeFileSync(expectedPath, JSON.stringify(actual, null, 2) + '\n')
    else assert.deepEqual(actual, JSON.parse(fs.readFileSync(expectedPath, 'utf8')))
  })
}
