#!/usr/bin/env node
'use strict'

const assert = require('assert')
const childProcess = require('child_process')
const fs = require('fs')
const os = require('os')
const path = require('path')

const hook = require('../worktree-cwd-recovery.js')

function run(cwd, args) {
  return childProcess.execFileSync('git', ['-C', cwd, ...args], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'inherit'],
  }).trim()
}

function makeRepo(root) {
  fs.mkdirSync(root, { recursive: true })
  run(root, ['init', '-q'])
  run(root, ['config', 'user.email', 'test@example.invalid'])
  run(root, ['config', 'user.name', 'Test'])
  fs.writeFileSync(path.join(root, 'README.md'), 'fixture\n')
  run(root, ['add', 'README.md'])
  run(root, ['commit', '-qm', 'fixture'])
}

function payload(cwd, command) {
  return hook.recoverInput({
    tool_name: 'Bash',
    cwd,
    tool_input: { command, description: 'fixture' },
  })
}

const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'devkit-worktree-cwd-'))
try {
  const parent = path.join(tempRoot, 'parent')
  const worktree = path.join(tempRoot, 'worktree')
  makeRepo(parent)
  run(parent, ['worktree', 'add', '-q', worktree, '-b', 'fixture-worktree'])

  const parentCanonical = fs.realpathSync(parent)
  const worktreeCanonical = fs.realpathSync(worktree)
  const ordinary = payload(worktree, `git -C ${parent} worktree remove --force ${worktree}`)
  assert.strictEqual(ordinary.command, `git -C ${parent} worktree remove --force ${worktree} && cd '${parentCanonical}'`)
  assert.strictEqual(ordinary.description, 'fixture')

  assert.strictEqual(payload(parent, `git -C ${parent} worktree remove --force ${worktree}`), null)
  assert.strictEqual(payload(worktree, `git -C ${parent} worktree list`), null)
  assert.strictEqual(payload(worktree, `git -C ${parent} worktree remove --force ${worktree} && printf done`), null)
  const quoted = payload(worktree, `git -C ${parent} worktree remove --force \"${worktree}\"`)
  assert.strictEqual(quoted.command, `git -C ${parent} worktree remove --force \"${worktree}\" && cd '${parentCanonical}'`)

  const submodule = path.join(tempRoot, 'submodule')
  const aggregate = path.join(tempRoot, 'aggregate')
  const submoduleWorktree = path.join(tempRoot, 'submodule-worktree')
  makeRepo(submodule)
  makeRepo(aggregate)
  run(aggregate, ['-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', submodule, 'src/module'])
  run(aggregate, ['commit', '-qm', 'add submodule'])
  run(path.join(aggregate, 'src/module'), ['worktree', 'add', '-q', submoduleWorktree, '-b', 'fixture-submodule-worktree'])

  const nested = payload(submoduleWorktree, `git -C ${path.join(aggregate, 'src/module')} worktree remove --force ${submoduleWorktree}`)
  assert.strictEqual(nested.command, `git -C ${path.join(aggregate, 'src/module')} worktree remove --force ${submoduleWorktree} && cd '${fs.realpathSync(aggregate)}'`)

  console.log('worktree-cwd-recovery: all tests passed')
} finally {
  fs.rmSync(tempRoot, { recursive: true, force: true })
}
