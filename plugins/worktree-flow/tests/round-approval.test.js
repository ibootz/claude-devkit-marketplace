// worktree-flow Human 本轮授权回归用例
//
// 运行：node plugins/worktree-flow/tests/round-approval.test.js
// 所有 hook 均以 spawnSync 直接喂 JSON，不经过 shell；授权状态落测试专用临时目录。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync, execFileSync } = require('child_process')
const {
  APPROVE_LABEL,
  approvalToolInput,
} = require('../hooks/lib/round-approval')

const ROOT = path.join(__dirname, '..')
const MAIN_GUARD = path.join(ROOT, 'hooks', 'guards', 'main-branch-guard.js')
const QUESTION_GUARD = path.join(ROOT, 'hooks', 'approval-question-guard.js')
const STATE_HOOK = path.join(ROOT, 'hooks', 'round-approval-state.js')
const STATE_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'wtflow-approval-'))
const BASE_ENV = Object.assign({}, process.env, { WORKTREE_GUARD_STATE_DIR: STATE_DIR })

let passed = 0
let failed = 0

function git(args, cwd) {
  execFileSync('git', args, { cwd, stdio: ['ignore', 'ignore', 'ignore'] })
}

function makeRepo(branch = 'main') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wtflow-repo-'))
  git(['init', '-q', '-b', branch], dir)
  git(['config', 'user.email', 'test@example.com'], dir)
  git(['config', 'user.name', 'test'], dir)
  fs.writeFileSync(path.join(dir, 'seed.txt'), 'seed\n')
  git(['add', '-A'], dir)
  git(['commit', '-q', '-m', 'seed'], dir)
  return dir
}

function run(script, payload, extraEnv) {
  const res = spawnSync(process.execPath, [script], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    env: Object.assign({}, BASE_ENV, extraEnv || {}),
  })
  return { code: res.status, stdout: res.stdout || '', stderr: res.stderr || '' }
}

function check(label, condition, detail = '') {
  if (condition) {
    passed++
    console.log(`  PASS  ${label}`)
  } else {
    failed++
    console.log(`  FAIL  ${label}${detail ? ` — ${detail}` : ''}`)
  }
}

function checkCode(label, result, expected) {
  check(
    label,
    result.code === expected,
    `期望 exit ${expected}，实际 ${result.code}；stderr=${result.stderr.trim().slice(0, 180)}`
  )
}

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function approvalPayload(sessionId, request, responseOverrides) {
  const question = request.questions[0].question
  const response = Object.assign(
    {
      questions: clone(request.questions),
      answers: { [question]: APPROVE_LABEL },
    },
    responseOverrides || {}
  )
  return {
    hook_event_name: 'PostToolUse',
    session_id: sessionId,
    tool_name: 'AskUserQuestion',
    tool_input: request,
    tool_response: response,
  }
}

function clearPayload(event, sessionId) {
  return { hook_event_name: event, session_id: sessionId }
}

function editPayload(repo, sessionId, file = 'src.js') {
  return {
    hook_event_name: 'PreToolUse',
    session_id: sessionId,
    tool_name: 'Edit',
    tool_input: { file_path: path.join(repo, file) },
    cwd: repo,
  }
}

function commitPayload(repo, sessionId) {
  return {
    hook_event_name: 'PreToolUse',
    session_id: sessionId,
    tool_name: 'Bash',
    tool_input: { command: 'git commit -m "x"' },
    cwd: repo,
  }
}

console.log('\n[授权问题只能由 Human 回答]')
const repo = makeRepo('main')
const session = 'session-approved-round'
const request = approvalToolInput({ repository: repo, branch: 'main', target: 'src.js' })

checkCode(
  '固定 AskUserQuestion 输入放行',
  run(QUESTION_GUARD, {
    hook_event_name: 'PreToolUse',
    session_id: session,
    tool_name: 'AskUserQuestion',
    tool_input: request,
  }),
  0
)

const prefilled = clone(request)
prefilled.answers = { [request.questions[0].question]: APPROVE_LABEL }
checkCode(
  'AI 预填 answers 被拒绝',
  run(QUESTION_GUARD, {
    hook_event_name: 'PreToolUse',
    session_id: session,
    tool_name: 'AskUserQuestion',
    tool_input: prefilled,
  }),
  2
)

const annotated = clone(request)
annotated.annotations = { [request.questions[0].question]: { notes: '批准' } }
checkCode(
  'AI 预填 annotations 被拒绝',
  run(QUESTION_GUARD, {
    hook_event_name: 'PreToolUse',
    session_id: session,
    tool_name: 'AskUserQuestion',
    tool_input: annotated,
  }),
  2
)

const altered = clone(request)
altered.questions[0].options[1].description = '永久放行'
checkCode(
  '篡改授权影响描述被拒绝',
  run(QUESTION_GUARD, {
    hook_event_name: 'PreToolUse',
    session_id: session,
    tool_name: 'AskUserQuestion',
    tool_input: altered,
  }),
  2
)

console.log('\n[Human 批准后整轮放行]')
checkCode('无授权时 main Edit 拒绝', run(MAIN_GUARD, editPayload(repo, session)), 2)
const granted = run(STATE_HOOK, approvalPayload(session, request))
checkCode('结构化批准回执写状态', granted, 0)
check('批准回执可观测', granted.stdout.includes('Human 已批准本轮'))
checkCode('批准后第一次 Edit 放行', run(MAIN_GUARD, editPayload(repo, session)), 0)
checkCode('同轮第二次 git commit 仍放行', run(MAIN_GUARD, commitPayload(repo, session)), 0)

run(STATE_HOOK, clearPayload('Stop', session))
const answeredInputPayload = approvalPayload(session, request)
answeredInputPayload.tool_input = clone(request)
answeredInputPayload.tool_input.answers = {
  [request.questions[0].question]: APPROVE_LABEL,
}
checkCode('UI updatedInput 含一致 answers 时批准', run(STATE_HOOK, answeredInputPayload), 0)
checkCode('updatedInput 形态批准后放行', run(MAIN_GUARD, editPayload(repo, session)), 0)

checkCode(
  '同轮另一个 main 仓也放行',
  run(MAIN_GUARD, editPayload(makeRepo('main'), session)),
  0
)
checkCode(
  '授权不跨 session',
  run(MAIN_GUARD, editPayload(repo, 'different-session')),
  2
)

console.log('\n[回合边界撤销]')
for (const event of ['SessionStart', 'UserPromptSubmit', 'Stop', 'SessionEnd']) {
  run(STATE_HOOK, approvalPayload(session, request))
  checkCode(`${event} 清理 hook 成功`, run(STATE_HOOK, clearPayload(event, session)), 0)
  checkCode(`${event} 后重新阻断`, run(MAIN_GUARD, editPayload(repo, session)), 2)
}

console.log('\n[非明确批准一律 fail-closed]')
function expectRejected(label, payload) {
  run(STATE_HOOK, approvalPayload(session, request))
  checkCode(`${label}：状态 hook 自身不报错`, run(STATE_HOOK, payload), 0)
  checkCode(`${label}：授权被撤销`, run(MAIN_GUARD, editPayload(repo, session)), 2)
}

const worktreeResponse = approvalPayload(session, request)
worktreeResponse.tool_response.answers[request.questions[0].question] =
  request.questions[0].options[0].label
expectRejected('选择改走 worktree', worktreeResponse)

expectRejected(
  '自由文本存在',
  approvalPayload(session, request, { response: '只允许改一个文件' })
)
expectRejected(
  'Human 备注存在',
  approvalPayload(session, request, {
    annotations: { [request.questions[0].question]: { notes: '只允许 src.js' } },
  })
)
expectRejected('AFK 自动继续', approvalPayload(session, request, { afkTimeoutMs: 60000 }))

const mismatchedInput = approvalPayload(session, request)
mismatchedInput.tool_input = clone(request)
mismatchedInput.tool_input.answers = {
  [request.questions[0].question]: request.questions[0].options[0].label,
}
expectRejected('tool_input 与 tool_response 答案不一致', mismatchedInput)

const noAnswer = approvalPayload(session, request)
noAnswer.tool_response.answers = {}
expectRejected('空 answers / 跳过', noAnswer)

const wrongQuestion = clone(request)
wrongQuestion.questions[0].question += '（已篡改）'
expectRejected('问题正文篡改', approvalPayload(session, wrongQuestion))

const stringResponse = approvalPayload(session, request)
stringResponse.tool_response = JSON.stringify(stringResponse.tool_response)
expectRejected('tool_response 字符串而非结构化对象', stringResponse)

const toolResultOnly = approvalPayload(session, request)
toolResultOnly.tool_result = toolResultOnly.tool_response
delete toolResultOnly.tool_response
expectRejected('只给 tool_result 兼容字段', toolResultOnly)

console.log('\n[无关问答不得改变授权]')
run(STATE_HOOK, approvalPayload(session, request))
checkCode(
  '其他 AskUserQuestion 的 PostToolUse 忽略',
  run(STATE_HOOK, {
    hook_event_name: 'PostToolUse',
    session_id: session,
    tool_name: 'AskUserQuestion',
    tool_input: {
      questions: [{ question: '选颜色？', header: '颜色', options: [], multiSelect: false }],
      metadata: { source: 'other-plugin' },
    },
    tool_response: { questions: [], answers: {} },
  }),
  0
)
checkCode('无关问答后原授权仍有效', run(MAIN_GUARD, editPayload(repo, session)), 0)
run(STATE_HOOK, clearPayload('Stop', session))

console.log('\n[状态损坏与过期 fail-closed]')
run(STATE_HOOK, approvalPayload(session, request))
let files = fs.readdirSync(STATE_DIR)
check('授权状态文件已创建', files.length === 1, `files=${files.join(',')}`)
if (files.length === 1) {
  fs.writeFileSync(path.join(STATE_DIR, files[0]), 'not-json\n')
  checkCode('损坏状态不放行', run(MAIN_GUARD, editPayload(repo, session)), 2)
}

run(STATE_HOOK, approvalPayload(session, request))
files = fs.readdirSync(STATE_DIR)
if (files.length === 1) {
  const file = path.join(STATE_DIR, files[0])
  const state = JSON.parse(fs.readFileSync(file, 'utf8'))
  state.expiresAt = Date.now() - 1
  fs.writeFileSync(file, JSON.stringify(state) + '\n')
  checkCode('过期状态不放行', run(MAIN_GUARD, editPayload(repo, session)), 2)
} else {
  check('过期状态测试前置', false, `files=${files.join(',')}`)
}

checkCode(
  '缺 session_id 的批准不生效',
  run(MAIN_GUARD, editPayload(repo, undefined)),
  2
)

fs.rmSync(STATE_DIR, { recursive: true, force: true })
console.log(`\n结果：${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
