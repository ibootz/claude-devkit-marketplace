#!/usr/bin/env node
// Blind LLM judge for the wenyan discourse-coherence eval (ticket 05).
//
// For every raw run record under ../raw/<arm>/<scenario>/run-<n>.json this script
// builds an arm-free item (scenario title + full dialogue transcript, with local
// run-directory paths masked), assigns it an opaque item id, and asks a judge
// model to score it against system-prompt.md with the JSON schema in schema.json.
//
// The judge never sees the arm. The item-id -> arm mapping lives only in
// unblind-map.json, which this script writes but never feeds to the judge.
//
// Judge sessions run with `--setting-sources local` plus judge.settings.json
// (disableAllHooks) so no user CLAUDE.md, rules, plugins or hooks leak in.
// Verified 2026-09-23: the judge context then contains only the built-in
// Environment / userEmail sections.
//
// Usage:
//   node score.mjs --arms baseline,no-style,new --passes 2 [--concurrency 4] [--limit N]
// Re-running skips outputs that already exist, so it can resume after a failure.

import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const EVAL = path.dirname(HERE)
const RAW = path.join(EVAL, 'raw')
const OUT = path.join(HERE, 'out')
const MAP_FILE = path.join(HERE, 'unblind-map.json')
const SYSTEM_PROMPT = fs.readFileSync(path.join(HERE, 'system-prompt.md'), 'utf8')
const SCHEMA = fs.readFileSync(path.join(HERE, 'schema.json'), 'utf8')
const SETTINGS = path.join(HERE, 'judge.settings.json')
const JUDGE_MODEL = 'claude-opus-5-5'
const JUDGE_CWD = process.env.JUDGE_CWD || '/Users/zhangq/.claude/jobs/f077ba4f/tmp/judge'

function parseArgs() {
  const a = { arms: ['baseline', 'no-style', 'new'], passes: 2, concurrency: 4, limit: Infinity }
  const v = process.argv.slice(2)
  for (let i = 0; i < v.length; i++) {
    if (v[i] === '--arms') a.arms = v[++i].split(',')
    else if (v[i] === '--passes') a.passes = Number(v[++i])
    else if (v[i] === '--concurrency') a.concurrency = Number(v[++i])
    else if (v[i] === '--limit') a.limit = Number(v[++i])
  }
  return a
}

// Mask local run directories so the judge cannot read the arm out of a path.
function mask(text) {
  return String(text || '')
    .replace(/\/Users\/[^\s`'")\]]*?\/eval-runs(?:-new)?\/(?:baseline|no-style|new)\/[^\s`'")\]/]+/g, '<工作目录>')
    .replace(/\/private\/tmp\/[^\s`'")\]]*/g, '<临时目录>')
}

function buildItem(rec) {
  const lines = [`## 场景：${rec.scenarioTitle}`, '', '## 对话记录', '']
  rec.turns.forEach((t, i) => {
    lines.push(`### 用户（第 ${i + 1} 轮）`, '', mask(t.prompt).trim(), '')
    lines.push(`### 助手（第 ${i + 1} 轮）`, '', mask(t.assistantText).trim(), '')
  })
  lines.push('---', '', '请按系统提示里的标准，评估整段对话中**助手回复**的可理解性。多轮对话时，按全部助手回复作为一个整体打分。')
  return lines.join('\n')
}

function loadMap() {
  return fs.existsSync(MAP_FILE) ? JSON.parse(fs.readFileSync(MAP_FILE, 'utf8')) : {}
}

function collect(arms, map) {
  const byKey = Object.fromEntries(Object.entries(map).map(([id, m]) => [`${m.arm}|${m.scenarioId}|${m.runIndex}`, id]))
  const items = []
  for (const arm of arms) {
    const armDir = path.join(RAW, arm)
    if (!fs.existsSync(armDir)) continue
    for (const sc of fs.readdirSync(armDir).sort()) {
      for (const f of fs.readdirSync(path.join(armDir, sc)).filter((x) => /^run-\d+\.json$/.test(x)).sort()) {
        const rec = JSON.parse(fs.readFileSync(path.join(armDir, sc, f), 'utf8'))
        if (rec.failed) continue
        const key = `${arm}|${rec.scenarioId}|${rec.runIndex}`
        let id = byKey[key]
        if (!id) {
          id = crypto.randomBytes(5).toString('hex')
          map[id] = { arm, scenarioId: rec.scenarioId, runIndex: rec.runIndex, rawFile: path.relative(EVAL, path.join(armDir, sc, f)) }
        }
        items.push({ id, input: buildItem(rec) })
      }
    }
  }
  return items
}

function runJudge(input) {
  return new Promise((resolve) => {
    const args = [
      '-p', '--model', JUDGE_MODEL,
      '--setting-sources', 'local',
      '--settings', SETTINGS,
      '--system-prompt', SYSTEM_PROMPT,
      '--json-schema', SCHEMA,
      '--tools', '',
      '--output-format', 'json',
      '--no-session-persistence',
    ]
    const p = spawn('claude', args, { cwd: JUDGE_CWD })
    let out = ''
    let err = ''
    p.stdout.on('data', (d) => (out += d))
    p.stderr.on('data', (d) => (err += d))
    p.on('close', (code) => resolve({ code, out, err }))
    p.stdin.end(input)
  })
}

function parseVerdict(stdout) {
  const j = JSON.parse(stdout)
  if (j.is_error) throw new Error(`judge error: ${j.result}`)
  if (j.structured_output) return { envelope: j, verdict: j.structured_output }
  return { envelope: j, verdict: JSON.parse(String(j.result).replace(/^```json\s*|\s*```$/g, '')) }
}

async function main() {
  const args = parseArgs()
  fs.mkdirSync(OUT, { recursive: true })
  fs.mkdirSync(JUDGE_CWD, { recursive: true })
  const map = loadMap()
  const items = collect(args.arms, map)
  fs.writeFileSync(MAP_FILE, JSON.stringify(map, null, 2) + '\n')
  const cli = spawnSync('claude', ['--version'], { encoding: 'utf8' }).stdout.trim()
  const promptSha = crypto.createHash('sha256').update(SYSTEM_PROMPT + SCHEMA).digest('hex')

  const jobs = []
  for (const it of items) for (let k = 1; k <= args.passes; k++) {
    const file = path.join(OUT, `${it.id}.p${k}.json`)
    if (!fs.existsSync(file)) jobs.push({ ...it, k, file })
  }
  const todo = jobs.slice(0, args.limit)
  console.log(`items=${items.length} pending=${jobs.length} running=${todo.length} cli=${cli}`)

  let idx = 0
  let failed = 0
  async function worker() {
    while (idx < todo.length) {
      const job = todo[idx++]
      let lastErr = ''
      for (let attempt = 1; attempt <= 3; attempt++) {
        const r = await runJudge(job.input)
        try {
          const { envelope, verdict } = parseVerdict(r.out)
          fs.writeFileSync(job.file, JSON.stringify({
            itemId: job.id, pass: job.k, judgeModel: JUDGE_MODEL, cliVersion: cli,
            judgePromptSha256: promptSha, attempt, input: job.input, verdict,
            costUsd: envelope.total_cost_usd, rawResult: envelope.result,
          }, null, 2) + '\n')
          console.log(`ok ${job.id}.p${job.k} (attempt ${attempt})`)
          lastErr = ''
          break
        } catch (e) {
          lastErr = `${e.message} | code=${r.code} | ${r.err.slice(-300)}`
        }
      }
      if (lastErr) { failed++; console.log(`FAIL ${job.id}.p${job.k}: ${lastErr}`) }
    }
  }
  await Promise.all(Array.from({ length: args.concurrency }, worker))
  console.log(`done failed=${failed}`)
  process.exit(failed ? 1 : 0)
}

main()
