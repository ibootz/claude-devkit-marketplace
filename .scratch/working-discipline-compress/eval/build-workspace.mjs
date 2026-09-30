// 把 harness 的 runs/<arm>/<eval>/run-<n>/ 转成 skill-creator 的 iteration 目录布局，
// 供 aggregate_benchmark.py 与 generate_review.py 读取。
// 用法：node build-workspace.mjs <runs 根目录> <iteration 输出目录>
import fs from 'node:fs'
import path from 'node:path'

const [runsRoot, outRoot] = process.argv.slice(2)
if (!runsRoot || !outRoot) {
  console.error('usage: node build-workspace.mjs <runs-root> <iteration-dir>')
  process.exit(2)
}
const here = path.dirname(new URL(import.meta.url).pathname)
const evals = JSON.parse(fs.readFileSync(path.join(here, 'evals.json'), 'utf8')).evals
const CONFIG = { new: 'new_skill', old: 'old_skill' } // new 排在 old 前

const readJson = (p, d) => (fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : d)
const readJsonl = (p) => fs.readFileSync(p, 'utf8').split('\n').filter(Boolean).flatMap((l) => { try { return [JSON.parse(l)] } catch { return [] } })

fs.rmSync(outRoot, { recursive: true, force: true })
let n = 0
for (const ev of evals) {
  const evalDir = path.join(outRoot, `eval-${ev.name}`)
  fs.mkdirSync(evalDir, { recursive: true })
  fs.writeFileSync(path.join(evalDir, 'eval_metadata.json'), JSON.stringify({ eval_id: ev.id, eval_name: ev.name, prompt: ev.prompt, assertions: [] }, null, 2))
  for (const [arm, config] of Object.entries(CONFIG)) {
    const src = path.join(runsRoot, arm, ev.name)
    if (!fs.existsSync(src)) continue
    for (const run of fs.readdirSync(src).filter((r) => /^run-\d+$/.test(r))) {
      const s = path.join(src, run)
      const d = path.join(evalDir, config, run)
      const out = path.join(d, 'outputs')
      fs.mkdirSync(out, { recursive: true })
      if (fs.existsSync(path.join(s, 'final.md'))) fs.copyFileSync(path.join(s, 'final.md'), path.join(out, 'final.md'))

      // 模型 Write 出来的 md（图示文件可能在项目外），从 transcript 的 tool_use 取内容
      const rows = readJsonl(path.join(s, 'transcript.jsonl'))
      for (const r of rows) {
        if (r.type !== 'assistant' || !r.message || !Array.isArray(r.message.content)) continue
        for (const c of r.message.content) {
          if (c.type === 'tool_use' && c.name === 'Write' && /\.md$/.test(c.input?.file_path || '')) {
            fs.writeFileSync(path.join(out, 'written-' + path.basename(c.input.file_path)), c.input.content || '')
          }
        }
      }

      const mech = readJson(path.join(s, 'grading.mechanical.json'), { expectations: [] }).expectations
      const sem = readJson(path.join(s, 'grading.semantic.json'), { expectations: [] }).expectations
      const expectations = [...mech.map((e) => ({ ...e, text: '[机械] ' + e.text })), ...sem.map((e) => ({ ...e, text: '[语义] ' + e.text }))]
      const passed = expectations.filter((e) => e.passed).length
      const meta = readJson(path.join(s, 'meta.json'), {})
      const result = rows.find((r) => r.type === 'result') || {}
      const u = result.usage || {}
      const tokens = (u.input_tokens || 0) + (u.output_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0)
      const seconds = Math.round((meta.lastAttemptMs || result.duration_ms || 0) / 100) / 10
      fs.writeFileSync(path.join(d, 'grading.json'), JSON.stringify({
        expectations,
        summary: { passed, failed: expectations.length - passed, total: expectations.length, pass_rate: expectations.length ? passed / expectations.length : 0 },
        timing: { total_duration_seconds: seconds },
        execution_metrics: { total_tool_calls: Object.values(meta.stats?.toolCounts || {}).reduce((a, b) => a + b, 0) },
      }, null, 2))
      fs.writeFileSync(path.join(d, 'timing.json'), JSON.stringify({ total_tokens: tokens, duration_ms: meta.lastAttemptMs || 0, total_duration_seconds: seconds, cost_usd: meta.costUsd }, null, 2))
      n += 1
    }
  }
}
console.log(`built ${n} runs into ${outRoot}`)
