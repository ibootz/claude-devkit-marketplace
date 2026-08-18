'use strict'

const crypto = require('crypto')
const fs = require('fs')
const os = require('os')
const path = require('path')

const APPROVAL_SOURCE = 'worktree-flow'
const APPROVAL_HEADER = '主分支写入'
const APPROVAL_QUESTION_SUFFIX = '是否批准本轮直接写入？'
const WORKTREE_LABEL = '改走 worktree (Recommended)'
const APPROVE_LABEL = '批准本轮'
const WORKTREE_DESCRIPTION =
  '保持主分支保护；AI 改在临时 worktree 提交，再以 --no-ff 合回主分支。'
const APPROVE_DESCRIPTION =
  '本轮所有 main/master 写入与 git commit 均放行；下次用户消息、回合结束或会话结束时自动失效。'

const STATE_VERSION = 1
const MAX_STATE_AGE_MS = 24 * 60 * 60 * 1000
const PROTECTED_BRANCHES = new Set(['main', 'master'])

function cleanEvidence(value) {
  return String(value || '').replace(/[\x00-\x1f\x7f]/g, ' ').trim()
}

function approvalQuestion(evidence) {
  const facts = {
    repository: cleanEvidence(evidence?.repository),
    branch: cleanEvidence(evidence?.branch),
    target: cleanEvidence(evidence?.target),
  }
  return (
    '起源：操作命中 main/master 保护。' +
    `\n现场证据：${JSON.stringify(facts)}` +
    '\n现状：默认应改走 worktree；期望：确需直写时由 Human 当轮批准。' +
    '\n影响：批准将放行当前会话本轮所有 main/master 写入与 git commit；下次用户消息、回合结束或会话结束即恢复保护。' +
    `\n${APPROVAL_QUESTION_SUFFIX}`
  )
}

function approvalToolInput(evidence) {
  return {
    questions: [
      {
        header: APPROVAL_HEADER,
        question: approvalQuestion(evidence),
        multiSelect: false,
        options: [
          { label: WORKTREE_LABEL, description: WORKTREE_DESCRIPTION },
          { label: APPROVE_LABEL, description: APPROVE_DESCRIPTION },
        ],
      },
    ],
    metadata: { source: APPROVAL_SOURCE },
  }
}

function hasExactKeys(value, keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const actual = Object.keys(value).sort()
  const expected = keys.slice().sort()
  return actual.length === expected.length && actual.every((key, index) => key === expected[index])
}

function evidenceFromQuestion(question) {
  if (typeof question !== 'string') return null
  const lines = question.split('\n')
  if (
    lines.length !== 5 ||
    lines[0] !== '起源：操作命中 main/master 保护。' ||
    !lines[1].startsWith('现场证据：') ||
    lines[2] !== '现状：默认应改走 worktree；期望：确需直写时由 Human 当轮批准。' ||
    lines[3] !==
      '影响：批准将放行当前会话本轮所有 main/master 写入与 git commit；下次用户消息、回合结束或会话结束即恢复保护。' ||
    lines[4] !== APPROVAL_QUESTION_SUFFIX
  ) {
    return null
  }

  let evidence
  try {
    evidence = JSON.parse(lines[1].slice('现场证据：'.length))
  } catch (_) {
    return null
  }
  if (!hasExactKeys(evidence, ['repository', 'branch', 'target'])) return null
  if (!PROTECTED_BRANCHES.has(evidence.branch)) return null
  if (!evidence.repository || !evidence.target) return null
  if (question !== approvalQuestion(evidence)) return null
  return evidence
}

function isApprovalRequest(input, allowAnswers = false) {
  const baseInput = hasExactKeys(input, ['metadata', 'questions'])
  const answeredInput =
    allowAnswers && hasExactKeys(input, ['metadata', 'questions', 'answers'])
  if (!baseInput && !answeredInput) return false
  if (!hasExactKeys(input.metadata, ['source'])) return false
  if (input.metadata.source !== APPROVAL_SOURCE) return false
  if (!Array.isArray(input.questions) || input.questions.length !== 1) return false
  if (input.answers !== undefined && !hasExactKeys(input.answers, [input.questions[0]?.question])) {
    return false
  }

  const actual = input.questions[0]
  if (
    !hasExactKeys(actual, ['header', 'question', 'multiSelect', 'options']) ||
    actual.header !== APPROVAL_HEADER ||
    !evidenceFromQuestion(actual.question) ||
    actual.multiSelect !== false ||
    !Array.isArray(actual.options) ||
    actual.options.length !== 2
  ) {
    return false
  }

  const expectedOptions = approvalToolInput(evidenceFromQuestion(actual.question)).questions[0].options
  return expectedOptions.every(
    (option, index) =>
      hasExactKeys(actual.options[index], ['label', 'description']) &&
      actual.options[index].label === option.label &&
      actual.options[index].description === option.description
  )
}

function isApprovalResponse(payload) {
  if (!isApprovalRequest(payload?.tool_input, true)) return false

  const response = payload.tool_response
  if (!hasExactKeys(response, ['questions', 'answers'])) return false
  if (!hasExactKeys(response.answers, [payload.tool_input.questions[0].question])) return false
  if (JSON.stringify(response.questions) !== JSON.stringify(payload.tool_input.questions)) return false
  if (
    payload.tool_input.answers !== undefined &&
    payload.tool_input.answers[payload.tool_input.questions[0].question] !== APPROVE_LABEL
  ) {
    return false
  }

  return response.answers[payload.tool_input.questions[0].question] === APPROVE_LABEL
}

function stateRoot() {
  if (process.env.WORKTREE_GUARD_STATE_DIR) {
    return path.resolve(process.env.WORKTREE_GUARD_STATE_DIR)
  }
  const uid = typeof process.getuid === 'function' ? process.getuid() : 'user'
  return path.join(os.tmpdir(), `worktree-flow-${uid}`)
}

function stateFile(sessionId) {
  if (typeof sessionId !== 'string' || !sessionId) return null
  const key = crypto.createHash('sha256').update(sessionId).digest('hex')
  return path.join(stateRoot(), `${key}.json`)
}

function ensureStateRoot() {
  fs.mkdirSync(stateRoot(), { recursive: true, mode: 0o700 })
}

function grantRound(sessionId) {
  const file = stateFile(sessionId)
  if (!file) return false

  try {
    ensureStateRoot()
    const now = Date.now()
    const temp = `${file}.${process.pid}.${now}.tmp`
    fs.writeFileSync(
      temp,
      JSON.stringify({ version: STATE_VERSION, approvedAt: now, expiresAt: now + MAX_STATE_AGE_MS }) + '\n',
      { encoding: 'utf8', mode: 0o600, flag: 'wx' }
    )
    fs.renameSync(temp, file)
    return true
  } catch (_) {
    return false
  }
}

function revokeRound(sessionId) {
  const file = stateFile(sessionId)
  if (!file) return false
  try {
    fs.unlinkSync(file)
    return true
  } catch (error) {
    return error && error.code === 'ENOENT'
  }
}

function isRoundApproved(sessionId) {
  const file = stateFile(sessionId)
  if (!file) return false

  try {
    const state = JSON.parse(fs.readFileSync(file, 'utf8'))
    if (
      state.version !== STATE_VERSION ||
      typeof state.expiresAt !== 'number' ||
      state.expiresAt <= Date.now()
    ) {
      revokeRound(sessionId)
      return false
    }
    return true
  } catch (_) {
    revokeRound(sessionId)
    return false
  }
}

module.exports = {
  APPROVE_LABEL,
  APPROVAL_SOURCE,
  approvalToolInput,
  grantRound,
  isApprovalRequest,
  isApprovalResponse,
  isRoundApproved,
  revokeRound,
}
