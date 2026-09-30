// 机械可判的断言：只读 transcript.jsonl（claude -p stream-json）与 run 目录下落盘的文件。
// 语义类断言（值(含义) 是否写对、四要素是否齐）交给 LLM 评分，不在这里猜。
// 用法：node grade-mechanical.mjs <runs 根目录>，对每个 run 目录写 grading.mechanical.json。
import fs from 'node:fs'
import path from 'node:path'

const root = process.argv[2]
if (!root) {
  console.error('usage: node grade-mechanical.mjs <runs-root>')
  process.exit(2)
}

function readJsonl(p) {
  if (!fs.existsSync(p)) return []
  return fs.readFileSync(p, 'utf8').split('\n').filter(Boolean).flatMap((l) => {
    try { return [JSON.parse(l)] } catch { return [] }
  })
}

// 主会话的 assistant 消息（排除子代理 sidechain 行）
function assistantMsgs(rows) {
  return rows.filter((r) => r.type === 'assistant' && !r.parent_tool_use_id && r.message && Array.isArray(r.message.content))
}

function toolUses(msg) {
  return msg.message.content.filter((c) => c.type === 'tool_use')
}

// 同一 message.id 的多行合并（stream-json 可能把一条消息拆成多行）
function mergeById(msgs) {
  const byId = new Map()
  for (const m of msgs) {
    const id = m.message.id || Symbol('noid')
    if (!byId.has(id)) byId.set(id, { ...m, message: { ...m.message, content: [] } })
    byId.get(id).message.content.push(...m.message.content)
  }
  return [...byId.values()]
}

function finalText(runDir, rows) {
  const f = path.join(runDir, 'final.md')
  if (fs.existsSync(f)) return fs.readFileSync(f, 'utf8')
  const res = rows.find((r) => r.type === 'result')
  return (res && res.result) || ''
}

const hasMermaidSrc = (t) => /```mermaid[\s\S]*?```/.test(t)
// pretty-mermaid 的 Unicode 渲染用框线字符画框
// insight-addon 插件的「★ Insight ───」分隔线也是框线字符，先剔掉再判
const stripInsight = (t) => t.replace(/^.*Insight ─+.*$|^`?─{20,}`?$/gm, '')
const hasUnicodeDiagram = (t0) => { const t = stripInsight(t0); return /[┌┐└┘├┤│─╭╮╰╯]{1}[\s\S]{0,400}[┌┐└┘├┤│─╭╮╰╯]/.test(t) && (t.match(/[┌┐└┘│─╭╮╰╯]/g) || []).length >= 20 }
const diagramCount = (t) => (t.match(/```mermaid/g) || []).length

function gradeRun(evalName, runDir) {
  const rows = readJsonl(path.join(runDir, 'transcript.jsonl'))
  const msgs = mergeById(assistantMsgs(rows))
  const text = finalText(runDir, rows)
  const allAssistantText = msgs.flatMap((m) => m.message.content.filter((c) => c.type === 'text').map((c) => c.text)).join('\n')
  const exp = []
  const add = (t, passed, evidence) => exp.push({ text: t, passed: !!passed, evidence: String(evidence).slice(0, 400) })

  const firstToolMsg = msgs.find((m) => toolUses(m).length > 0)
  const allTools = msgs.flatMap(toolUses)

  if (evalName === 'cross-service-explain' || evalName === 'design-proposal') {
    // 3.10：图写进 md 文件，正文只给链接。md 可能落在项目外（系统临时目录），从 Write 的 input 取内容
    const mdWrites = allTools.filter((t) => (t.name === 'Write' || t.name === 'Edit') && /\.md$/.test((t.input && t.input.file_path) || ''))
    const mdWithMermaid = mdWrites.filter((t) => hasMermaidSrc(t.input.content || t.input.new_string || ''))
    add('mermaid 图写进了 md 文件', mdWithMermaid.length > 0, mdWrites.map((t) => t.input.file_path).join(', ') || '无 md 写入')
    const linked = mdWithMermaid.map((t) => t.input.file_path).filter((fp) => text.includes('(file://' + fp + ')'))
    add('正文给了该 md 的 file:// 链接且不带 #', linked.length > 0, linked.join(', ') || `正文未见 (file://<md>) 形态；md=${mdWithMermaid.map((t) => t.input.file_path).join(',')}`)
    add('正文没贴 mermaid 源码或字符画', !hasMermaidSrc(text) && !hasUnicodeDiagram(text), `mermaid源码=${hasMermaidSrc(text)} unicode图=${hasUnicodeDiagram(text)}`)
  }
  if (evalName === 'design-proposal') {
    const mdBodies = allTools.filter((t) => (t.name === 'Write' || t.name === 'Edit') && /\.md$/.test((t.input && t.input.file_path) || '')).map((t) => t.input.content || t.input.new_string || '').join('\n')
    const n = diagramCount(mdBodies)
    add('方案至少两张图（改前 / 改后）', n >= 2, `md 里 mermaid 块 ${n} 个`)
    add('未调用 AskUserQuestion', !allTools.some((t) => t.name === 'AskUserQuestion'), allTools.map((t) => t.name).join(','))
  }
  if (evalName === 'parallel-config-audit') {
    const n = firstToolMsg ? toolUses(firstToolMsg).length : 0
    add('第一条带工具调用的消息里并发 ≥2 个调用', n >= 2, `首条工具消息含 ${n} 个 tool_use: ${firstToolMsg ? toolUses(firstToolMsg).map((t) => t.name).join(',') : '无'}`)
  }
  if (evalName === 'write-flow-doc') {
    const writeIdx = msgs.findIndex((m) => toolUses(m).some((t) => (t.name === 'Write' || t.name === 'Edit') && /order-flow\.md/.test(JSON.stringify(t.input))))
    const before = writeIdx < 0 ? '' : msgs.slice(0, writeIdx + 1).flatMap((m) => m.message.content.filter((c) => c.type === 'text').map((c) => c.text)).join('\n')
    add('写 md 前正文出现「本次 md 受众判定」', writeIdx >= 0 && /本次 ?md ?受众判定/.test(before), `write 所在消息序号=${writeIdx}`)
    const doc = path.join(runDir, 'project', 'docs', 'order-flow.md')
    const body = fs.existsSync(doc) ? fs.readFileSync(doc, 'utf8') : ''
    add('落盘文档含 ```mermaid 源码块', hasMermaidSrc(body), body ? `文档 ${body.length} 字符` : '文档不存在')
  }
  if (evalName === 'dispatch-todo-sweep') {
    const agents = allTools.filter((t) => t.name === 'Agent' || t.name === 'Task')
    add('至少派出 3 个子代理', agents.length >= 3, `Agent 调用 ${agents.length} 次`)
    add('每个 Agent 调用都带 name 与 model', agents.length > 0 && agents.every((a) => a.input && a.input.name && a.input.model), agents.map((a) => `${a.input && a.input.name}/${a.input && a.input.model}`).join('; '))
    add('每个 description ≤60 字符', agents.length > 0 && agents.every((a) => a.input && a.input.description && a.input.description.length <= 60), agents.map((a) => a.input && a.input.description).join(' | '))
    add('只读任务用 Explore', agents.length > 0 && agents.every((a) => a.input && a.input.subagent_type === 'Explore'), agents.map((a) => a.input && a.input.subagent_type).join(','))
    const sameMsg = msgs.some((m) => toolUses(m).filter((t) => t.name === 'Agent' || t.name === 'Task').length >= 3)
    add('3 个派发在同一条消息里并发', sameMsg, `同消息最大派发数=${Math.max(0, ...msgs.map((m) => toolUses(m).filter((t) => t.name === 'Agent' || t.name === 'Task').length))}`)
  }
  return exp
}

let n = 0
for (const arm of fs.readdirSync(root)) {
  const armDir = path.join(root, arm)
  if (!fs.statSync(armDir).isDirectory()) continue
  for (const evalName of fs.readdirSync(armDir)) {
    const evalDir = path.join(armDir, evalName)
    if (!fs.statSync(evalDir).isDirectory()) continue
    for (const run of fs.readdirSync(evalDir)) {
      const runDir = path.join(evalDir, run)
      if (!fs.existsSync(path.join(runDir, 'transcript.jsonl'))) continue
      const expectations = gradeRun(evalName, runDir)
      fs.writeFileSync(path.join(runDir, 'grading.mechanical.json'), JSON.stringify({ expectations }, null, 2))
      n += 1
    }
  }
}
console.log(`graded ${n} runs`)
