#!/usr/bin/env node
// Aggregate judge outputs into ../scores.json and ../report-data.md.
// Decision rules are the pre-registered ones in README.md ("判定口径"); do not
// change them after looking at results.

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const EVAL = path.dirname(HERE)
const ARMS = ['baseline', 'no-style', 'new']
const METRICS = ['conclusion_recall', 'relation_recall', 'certainty_separation', 'tradeoff_scope_recall',
  'next_step_recall', 'overturn_condition_recall', 'link_information_scent', 'residual_uncertainty_recall']
const HNS = ['no_ceremony', 'link_not_explanation', 'inference_not_fact', 'nl_approval_not_bypass', 'artifact_plain_style']
const LOSE_CLEARLY = 0.5

const map = JSON.parse(fs.readFileSync(path.join(HERE, 'unblind-map.json'), 'utf8'))
const outs = {}
for (const f of fs.readdirSync(path.join(HERE, 'out'))) {
  const j = JSON.parse(fs.readFileSync(path.join(HERE, 'out', f), 'utf8'))
  ;(outs[j.itemId] ||= []).push(j)
}
const scenarios = Object.fromEntries(fs.readdirSync(path.join(EVAL, 'scenarios')).map((s) =>
  [s, JSON.parse(fs.readFileSync(path.join(EVAL, 'scenarios', s, 'meta.json'), 'utf8'))]))

const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null)
const sd = (xs) => { const m = mean(xs); return xs.length ? Math.sqrt(mean(xs.map((x) => (x - m) ** 2))) : null }
const f2 = (x) => (x === null || x === undefined ? '—' : x.toFixed(2))

// Per-run records
const runs = []
let passDiffs = []
let hnDisagree = 0
for (const [id, m] of Object.entries(map)) {
  const passes = (outs[id] || []).sort((a, b) => a.pass - b.pass)
  if (!passes.length) continue
  const metric = {}
  for (const k of METRICS) {
    const vals = passes.map((p) => p.verdict.metrics[k].score).filter((v) => v !== null)
    metric[k] = vals.length ? mean(vals) : null
    if (passes.length === 2) {
      const [a, b] = passes.map((p) => p.verdict.metrics[k].score)
      if (a !== null && b !== null) passDiffs.push(Math.abs(a - b))
    }
  }
  const hn = {}
  for (const k of HNS) {
    const vs = passes.map((p) => p.verdict.hard_negatives[k].verdict)
    if (new Set(vs).size > 1) hnDisagree++
    hn[k] = vs.includes('fail') ? 'fail' : vs.includes('pass') ? 'pass' : 'na'
    hn[`${k}_evidence`] = passes.filter((p) => p.verdict.hard_negatives[k].verdict === 'fail').map((p) => p.verdict.hard_negatives[k].evidence)
  }
  const nonNull = METRICS.map((k) => metric[k]).filter((v) => v !== null)
  const raw = JSON.parse(fs.readFileSync(path.join(EVAL, m.rawFile), 'utf8'))
  const chars = raw.turns.reduce((a, t) => a + [...(t.assistantText || '')].length, 0)
  runs.push({ id, ...m, passes: passes.length, metric, score: mean(nonNull), hn, chars,
    injection: raw.turns.map((t) => t.injectionProof && t.injectionProof.occurrences) })
}

const sel = (arm, sc) => runs.filter((r) => r.arm === arm && (!sc || r.scenarioId === sc))
const scIds = Object.keys(scenarios).sort()
const core = scIds.filter((s) => scenarios[s].core)

const table = {}
for (const sc of scIds) for (const arm of ARMS) {
  const rs = sel(arm, sc)
  table[`${arm}|${sc}`] = {
    n: rs.length, runScores: rs.map((r) => r.score), mean: mean(rs.map((r) => r.score)), sd: sd(rs.map((r) => r.score)),
    relation: mean(rs.map((r) => r.metric.relation_recall).filter((v) => v !== null)),
    chars: mean(rs.map((r) => r.chars)),
  }
}

// 6c checks
const coreRows = core.map((sc) => {
  const b = table[`baseline|${sc}`].mean
  const n = table[`new|${sc}`].mean
  return { sc, b, n, delta: n !== null && b !== null ? n - b : null }
})
const atLeastEqual = coreRows.filter((r) => r.delta !== null && r.delta >= 0).length
const clearLosses = coreRows.filter((r) => r.delta !== null && r.delta <= -LOSE_CLEARLY)
const newRuns = sel('new')
const hnFailures = newRuns.flatMap((r) => HNS.filter((k) => r.hn[k] === 'fail').map((k) => ({ run: `${r.scenarioId} run-${r.runIndex}`, hn: k, evidence: r.hn[`${k}_evidence`] })))
const relCore = (arm) => mean(runs.filter((r) => r.arm === arm && core.includes(r.scenarioId)).map((r) => r.metric.relation_recall).filter((v) => v !== null))
const relNoStyle = relCore('no-style')
const relNew = relCore('new')
const reopen = relNoStyle !== null && relNew !== null && relNoStyle >= relNew

const verdict = {
  c1_atLeastEqualIn5of6: { count: atLeastEqual, holds: atLeastEqual >= 5 },
  c2_noClearLoss: { losses: clearLosses.map((r) => r.sc), holds: clearLosses.length === 0 },
  c3_allHardNegativesEveryRun: { newRuns: newRuns.length, failures: hnFailures.length, holds: newRuns.length > 0 && hnFailures.length === 0 },
  reopenTriggered: { relationNoStyle: relNoStyle, relationNew: relNew, triggered: reopen },
}
verdict.go = verdict.c1_atLeastEqualIn5of6.holds && verdict.c2_noClearLoss.holds && verdict.c3_allHardNegativesEveryRun.holds

fs.writeFileSync(path.join(EVAL, 'scores.json'), JSON.stringify({ verdict, table, runs,
  judgeAgreement: { meanAbsDiff: mean(passDiffs), metricPairs: passDiffs.length, hnDisagreements: hnDisagree } }, null, 2) + '\n')

// report-data.md
const L = []
L.push('# 05 号票评分数据（由 judge/aggregate.mjs 生成，勿手改）', '')
L.push(`judge 两遍评分的逐项平均绝对差：${f2(mean(passDiffs))}（共 ${passDiffs.length} 对）；硬负例两遍判定不一致 ${hnDisagree} 处。`, '')
L.push('## 一、各场景 rubric 均分（括号内为组内标准差，方括号为逐次运行得分）', '')
L.push('| 场景 | core | baseline | no-style | new | new − baseline |', '|---|---|---|---|---|---|')
for (const sc of scIds) {
  const cell = (arm) => { const t = table[`${arm}|${sc}`]; return t.n ? `${f2(t.mean)} (±${f2(t.sd)}) [${t.runScores.map(f2).join(', ')}]` : '—' }
  const b = table[`baseline|${sc}`].mean, n = table[`new|${sc}`].mean
  L.push(`| ${sc} | ${scenarios[sc].core ? '是' : '否'} | ${cell('baseline')} | ${cell('no-style')} | ${cell('new')} | ${b !== null && n !== null ? (n - b >= 0 ? '+' : '') + f2(n - b) : '—'} |`)
}
L.push('', '## 二、关系回忆（relation_recall）', '')
L.push('| 场景 | baseline | no-style | new |', '|---|---|---|---|')
for (const sc of scIds) L.push(`| ${sc} | ${f2(table[`baseline|${sc}`].relation)} | ${f2(table[`no-style|${sc}`].relation)} | ${f2(table[`new|${sc}`].relation)} |`)
L.push(`| **六个核心场景合并** | ${f2(relCore('baseline'))} | ${f2(relNoStyle)} | ${f2(relNew)} |`)
L.push('', '## 三、各指标在六个核心场景上的合并均分', '')
L.push('| 指标 | baseline | no-style | new |', '|---|---|---|---|')
for (const k of METRICS) {
  const v = (arm) => f2(mean(runs.filter((r) => r.arm === arm && core.includes(r.scenarioId)).map((r) => r.metric[k]).filter((x) => x !== null)))
  L.push(`| ${k} | ${v('baseline')} | ${v('no-style')} | ${v('new')} |`)
}
L.push('', '## 四、硬负例逐次记录（fail = 两遍中任一遍判 fail；na 不计）', '')
L.push(`| 组 | 场景 | run | ${HNS.join(' | ')} |`, `|---|---|---|${HNS.map(() => '---').join('|')}|`)
for (const arm of ARMS) for (const r of sel(arm).sort((a, b) => a.scenarioId.localeCompare(b.scenarioId) || a.runIndex - b.runIndex))
  L.push(`| ${arm} | ${r.scenarioId} | ${r.runIndex} | ${HNS.map((k) => r.hn[k]).join(' | ')} |`)
L.push('', '### new 组硬负例 fail 的判定依据（judge 原文摘录）', '')
if (!hnFailures.length) L.push('无。')
for (const f of hnFailures) L.push(`- ${f.run} · ${f.hn}：${f.evidence.map((e) => `「${e}」`).join(' / ')}`)
L.push('', '## 五、长度（观察项，不参与判定）', '')
L.push('| 场景 | baseline 字符 | no-style 字符 | new 字符 |', '|---|---|---|---|')
for (const sc of scIds) L.push(`| ${sc} | ${Math.round(table[`baseline|${sc}`].chars || 0)} | ${Math.round(table[`no-style|${sc}`].chars || 0)} | ${Math.round(table[`new|${sc}`].chars || 0)} |`)
L.push('', '## 六、6c 机械判定', '')
L.push(`1. 六个核心场景中 new ≥ baseline 的个数：${atLeastEqual} / ${core.length}（要求 ≥ 5）→ ${verdict.c1_atLeastEqualIn5of6.holds ? '成立' : '不成立'}`)
L.push(`2. 明显落败（new − baseline ≤ −${LOSE_CLEARLY}）的场景：${clearLosses.length ? clearLosses.map((r) => `${r.sc}（${f2(r.delta)}）`).join('、') : '无'} → ${verdict.c2_noClearLoss.holds ? '成立' : '不成立'}`)
L.push(`3. new 组 ${newRuns.length} 次运行的硬负例 fail 次数：${hnFailures.length} → ${verdict.c3_allHardNegativesEveryRun.holds ? '成立' : '不成立'}`)
L.push(`4. 重开条件：六个核心场景合并的 relation_recall，no-style ${f2(relNoStyle)}，new ${f2(relNew)} → ${reopen ? '**触发层级决策的重开条件**' : '未触发'}`)
L.push('', `**总判定：${verdict.go ? '通过（go）' : '不通过（no-go）'}**`)
L.push('', '## 七、注入状态（每轮各风格插件 header 出现次数）', '')
for (const arm of ARMS) {
  const occ = sel(arm).flatMap((r) => r.injection)
  const tally = {}
  for (const o of occ) { const k = JSON.stringify(o); tally[k] = (tally[k] || 0) + 1 }
  L.push(`- ${arm}：${Object.entries(tally).map(([k, v]) => `${k} × ${v} 轮`).join('；')}`)
}
fs.writeFileSync(path.join(EVAL, 'report-data.md'), L.join('\n') + '\n')
console.log(JSON.stringify(verdict, null, 2))
