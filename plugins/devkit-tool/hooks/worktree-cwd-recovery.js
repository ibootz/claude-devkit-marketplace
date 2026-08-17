// worktree-cwd-recovery.js — restore the session cwd before removing its worktree.
//
// A deleted worktree cannot be inspected after `git worktree remove` completes. This
// hook therefore resolves the outermost project while the worktree still exists and
// appends a shell `cd` to the narrow, command-shaped removal form it recognizes.

'use strict'

const childProcess = require('child_process')
const fs = require('fs')
const path = require('path')

const MAX_SUPERPROJECT_DEPTH = 64
const REMOVAL_COMMAND = /^\s*(?:(?:[A-Za-z_][A-Za-z0-9_]*=[^\s]+)\s+)*git(?:\s+(?:-C\s+(?:'[^']*'|"[^"]*"|[^\s]+)|--[A-Za-z-]+))*\s+worktree\s+remove(?:\s+--[A-Za-z-]+)*(?:\s+(?:'[^']*'|"[^"]*"|[^\s]+))+\s*$/

function canonicalPath(value) {
  try {
    return fs.realpathSync(value)
  } catch {
    return path.resolve(value)
  }
}

function hasUnquotedShellOperator(command) {
  let quote = ''
  for (let i = 0; i < command.length; i++) {
    const char = command[i]
    if (quote) {
      if (char === quote) quote = ''
      continue
    }
    if (char === "'" || char === '"') {
      quote = char
      continue
    }
    if (';&|<>`$\\\n'.includes(char)) return true
  }
  return false
}

function git(cwd, args) {
  try {
    return childProcess.execFileSync('git', ['-C', cwd, ...args], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
  } catch {
    return ''
  }
}

function isWorktree(cwd) {
  const gitDir = path.resolve(git(cwd, ['rev-parse', '--git-dir']))
  const commonDir = canonicalPath(git(cwd, ['rev-parse', '--git-common-dir']))
  return Boolean(gitDir && commonDir && gitDir !== commonDir)
}

function submoduleWorkingTree(cwd) {
  const commonDir = git(cwd, ['rev-parse', '--git-common-dir'])
  const marker = `${path.sep}.git${path.sep}modules${path.sep}`
  const markerIndex = commonDir.indexOf(marker)
  if (markerIndex < 0) return ''

  const aggregateRoot = commonDir.slice(0, markerIndex)
  const modulePath = commonDir.slice(markerIndex + marker.length)
    .replace(new RegExp(`${path.sep}worktrees${path.sep}[^${path.sep}]+$`), '')
  const candidate = path.join(aggregateRoot, modulePath)
  return fs.existsSync(candidate) ? candidate : ''
}

function outermostProject(cwd) {
  if (!isWorktree(cwd)) return null

  let current = path.resolve(cwd)
  let outermostSuperproject = ''
  for (let i = 0; i < MAX_SUPERPROJECT_DEPTH; i++) {
    const superproject = git(current, ['rev-parse', '--show-superproject-working-tree'])
    if (!superproject) break
    outermostSuperproject = canonicalPath(superproject)
    current = outermostSuperproject
  }

  if (outermostSuperproject) return outermostSuperproject

  const nestedSubmodule = submoduleWorkingTree(cwd)
  if (nestedSubmodule) {
    const aggregate = git(nestedSubmodule, ['rev-parse', '--show-superproject-working-tree'])
    if (aggregate) return canonicalPath(aggregate)
  }

  const commonDir = canonicalPath(git(cwd, ['rev-parse', '--git-common-dir']))
  if (!commonDir || path.basename(commonDir) !== '.git') return null
  return path.dirname(commonDir)
}

function shellQuote(value) {
  return `'${value.replace(/'/g, `'"'"'`)}'`
}

function recoverInput(payload) {
  if (!payload || payload.tool_name !== 'Bash') return null
  const input = payload.tool_input
  if (!input || typeof input.command !== 'string' || hasUnquotedShellOperator(input.command) || !REMOVAL_COMMAND.test(input.command)) return null

  const cwd = typeof payload.cwd === 'string' && payload.cwd ? payload.cwd : process.cwd()
  const projectRoot = outermostProject(cwd)
  if (!projectRoot) return null

  return {
    ...input,
    command: `${input.command} && cd ${shellQuote(projectRoot)}`,
  }
}

function main() {
  let payload
  try {
    payload = JSON.parse(fs.readFileSync(0, 'utf8') || '{}')
  } catch {
    return
  }

  const updatedInput = recoverInput(payload)
  if (!updatedInput) return

  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      updatedInput,
    },
  }) + '\n')
}

if (require.main === module) main()

module.exports = {
  REMOVAL_COMMAND,
  outermostProject,
  recoverInput,
  shellQuote,
}
