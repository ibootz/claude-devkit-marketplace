#!/usr/bin/env node
// Build the human blind-review packet for ticket 06.
// One pair per scenario: new vs baseline, same scenario, run index picked at random,
// A/B order randomised. Writes ../blind/packet.md (no arm labels) and
// ../blind-key/unblind.json (kept in a separate directory; open only after reviewing).

import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const EVAL = path.dirname(HERE)
const RAW = path.join(EVAL, 'raw')

const mask = (t) => String(t || '')
  .replace(/\/Users\/[^\s`'")\]]*?\/eval-runs(?:-new)?\/(?:baseline|no-style|new)\/[^\s`'")\]/]+/g, '<工作目录>')
  .replace(/\/private\/tmp\/[^\s`'")\]]*/g, '<临时目录>')

const runsOf = (arm, sc) => fs.readdirSync(path.join(RAW, arm, sc)).filter((f) => /^run-\d+\.json$/.test(f)).sort()
const load = (arm, sc, f) => JSON.parse(fs.readFileSync(path.join(RAW, arm, sc, f), 'utf8'))

const scIds = fs.readdirSync(path.join(EVAL, 'scenarios')).sort()
const key = []
const L = ['# 盲评材料包（06 号票）', '',
  '每一对是同一个场景、同一条提问下，两个版本助手的回复。A、B 的顺序是随机的，材料里不标版本。',
  '',
  '每对请填四项：',
  '',
  '1. **偏好**：A / B / 平局——哪份让你更容易建立正确理解。',
  '2. **理由**：一两句话。',
  '3. **读完能否复述**：结论 / 段落之间的关系 / 代价 / 下一步，各写「能」或「不能」。',
  '4. 可选：哪一句让你卡住了。',
  '',
  '**全部填完之后**，再打开 `../blind-key/unblind.json` 揭盲。', '']

scIds.forEach((sc, i) => {
  const meta = JSON.parse(fs.readFileSync(path.join(EVAL, 'scenarios', sc, 'meta.json'), 'utf8'))
  const common = runsOf('new', sc).filter((f) => runsOf('baseline', sc).includes(f))
  const f = common[crypto.randomInt(common.length)]
  const sides = crypto.randomInt(2) === 0 ? ['new', 'baseline'] : ['baseline', 'new']
  const pairId = `P${String(i + 1).padStart(2, '0')}`
  key.push({ pairId, scenarioId: sc, run: f, A: sides[0], B: sides[1] })
  const recs = sides.map((arm) => load(arm, sc, f))
  L.push('---', '', `# ${pairId}：${meta.title}`, '')
  recs[0].turns.forEach((t, k) => {
    L.push(`## 用户（第 ${k + 1} 轮）`, '', mask(t.prompt).trim(), '')
    ;['A', 'B'].forEach((side, s) => {
      L.push(`## 回复 ${side}（第 ${k + 1} 轮）`, '', '````markdown', mask(recs[s].turns[k].assistantText).trim(), '````', '')
    })
  })
  L.push(`## ${pairId} 评价`, '', '- 偏好（A / B / 平局）：', '- 理由：',
    '- 读完能否复述——结论：　关系：　代价：　下一步：', '- 卡住的句子（可选）：', '')
})

fs.mkdirSync(path.join(EVAL, 'blind'), { recursive: true })
fs.mkdirSync(path.join(EVAL, 'blind-key'), { recursive: true })
fs.writeFileSync(path.join(EVAL, 'blind', 'packet.md'), L.join('\n'))
fs.writeFileSync(path.join(EVAL, 'blind-key', 'unblind.json'), JSON.stringify(key, null, 2) + '\n')
console.log(`pairs=${key.length}`)
