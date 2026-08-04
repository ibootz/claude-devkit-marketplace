#!/usr/bin/env node
/**
 * working-discipline · UserPromptSubmit：派发账本（纯注入，零拦截）
 *
 * 【要解决什么】
 *   零章「并行优先」每轮都在注，但主代理**察觉不到自己的实际派发率**。task-keeper
 *   的队列快照能起作用，靠的正是「把磁盘现算的状态摆在眼前」而不是「重复一遍规则」；
 *   派发这件事此前一个数都没有。2026-08-02 实测：本仓一次跨插件排查里，主代理连续
 *   多轮做多文件调查、`Agent` 调用 0 次，而它每轮都读到了零章——缺的不是规则，是
 *   「我这一小时 0 派发」这个事实。
 *
 * 【判据全部机械，只数不判】
 *   从 `transcript_path` 逐行读 JSONL，数三个数：
 *     · 主会话工具调用 = `type==="assistant"` 且 `isSidechain !== true` 的消息里
 *       `content[]` 中 `type==="tool_use"` 的块数；
 *     · 派发 = 其中 `name==="Agent"`（或 `Task`，旧版工具名）的块数；
 *     · 自上次派发以来的检索次数 = 顺序扫描时遇 `Agent`/`Task` 清零、遇 `PROBE_TOOLS`
 *       里的工具名加一。JSONL 本身按时间顺序排列，所以顺序扫一遍就能得到这个量，
 *       不需要任何额外数据源。
 *   不解析语义、不判断"这一步该不该派"——那是语义判断，按本仓 hook 克制原则
 *   （.claude/rules/hook-restraint.md）只能靠注入软约束，不能做成判定。
 *
 * 【为什么加第三个数（2026-08-04）】
 *   前两个数是**全会话累计**，回答的是"我这一小时派了几次"。但零章检查点②的判据是
 *   「自上次派发以来已 ≥6 次只读检索 **且** 手上仍有 ≥2 个互不依赖待查项」——累计数
 *   答不了它，而原文却写着"你自己数得出来"。实测（本仓 2026-08-04 会话）：主代理连发
 *   9 次只读检索才派出第一个 Explore，它读得到"73 次调用 / 3 次派发"，却数不出"这一段
 *   连续查了 9 次"。**能机械算的那一半就不该让 AI 自己数。**
 *
 * 【第三个数的两处已知不精确，都朝"高估"方向，如实记录】
 *   1. `Bash` 一律计入，不区分只读与写操作。检查点②原文说的是"只读 Bash"，但要区分
 *      读写就得解析命令语义——这正是同插件 guards/bash-guard.js 实测 19 类漏报的老路
 *      （见 .claude/rules/hook-restraint.md 实证 2）。宁可高估：多提示一次的代价，远低
 *      于再造一个有误判面的近似解析器。
 *   2. `MAX_BYTES` 尾部截断时，若真正的"上一次派发"落在被截掉的头部，计数从截断点重新
 *      起算，结果偏大（把截断前那段也算成"未派发"）。8MB 窗口下实际会话基本不命中。
 *   两处都只影响提示时机，不影响任何操作——本 hook 仍是纯注入、零拦截。
 *
 * 【为什么不做成硬拦截】
 *   检查点②是合取判据，另一半"手上是否仍有 ≥2 个互不依赖的待查项"是 AI 脑内状态，
 *   transcript 里没有任何字段能提取。只对可算的那一半做 deny，会误杀"次数够了但待查项
 *   只剩 1 个"的正当情形。所以这里只把数字和判据摆出来，答不答仍由 AI 自己交代。
 *
 * 【为什么读 transcript 是安全的（与实证 3 的区别）】
 *   hook-restraint 的实证 3 说的是「靠回读 transcript 做**门控判定**」不可靠——那里
 *   的失败模式是 deny 把 AI 卡死。本 hook 是**纯注入**：读不到就不注入，读错了最坏
 *   结果是数字偏小，不会阻断任何操作。而且它不依赖"轮起点"这种脆弱概念，只做全量
 *   计数，行格式变化最多让某些行数不进去。
 *
 * 【失效时不谎报】
 *   transcript 读不到 / 解析不出任何 assistant 行 → **不注入**，而不是注一行
 *   「派发 0 次」。注 0 会把"我没数到"说成"你没派过"，比不注入更糟。
 *
 * 【零成本保证】
 *   会话早期（主会话工具调用 < MIN_CALLS）不注入——刚开始几轮谈不上派发率，
 *   每轮注一行纯属噪音。达到阈值后每轮一行，约 60-140 字符。
 *
 * 【为什么独立成脚本，不并进 working-discipline.js】
 *   那个脚本是纯静态文本拼装、无 IO；本 hook 要读一个可能几十 MB 的 JSONL。
 *   失败面完全不同（文件不存在 / 超大 / 行损坏），混在一起会让静态注入也跟着挂。
 *
 * 【改完要重启】cc hook 在会话启动时加载。
 */

'use strict'

const fs = require('fs')

// 低于这个主会话工具调用数不注入：会话刚起步时派发率没有意义。
const MIN_CALLS = 12
// 主会话工具调用达到这个数仍 0 派发时，追加一句提示。
const NUDGE_AT = 20
// 自上次派发以来的只读检索次数达到这个数，追加"过线了"提示。
// 取 6 是照抄零章检查点②原文的次数线，不是另立标准——两处必须一致，
// 否则注入的数字和它引用的判据对不上，AI 会不知道该信哪个。
const PROBE_LIMIT = 6
// 计入"只读检索"的工具名。Bash 一律计入（不区分读写），理由见文件头。
const PROBE_TOOLS = new Set(['Read', 'Grep', 'Glob', 'Bash'])
// transcript 读取上限（字节）。超大文件只读尾部——派发率看近况即可，
// 且全量读一个几十 MB 的 JSONL 会让每轮 prompt 提交肉眼可见地卡一下。
const MAX_BYTES = 8 * 1024 * 1024

function readEvent() {
  try {
    const raw = fs.readFileSync(0, 'utf8')
    if (!raw || !raw.trim()) return {}
    return JSON.parse(raw)
  } catch (e) {
    return {}
  }
}

// 读 transcript 尾部若干字节。返回完整行数组（首行可能被截断，丢弃它）。
function readTail(filePath) {
  const stat = fs.statSync(filePath)
  if (stat.size <= MAX_BYTES) {
    return fs.readFileSync(filePath, 'utf8').split('\n')
  }
  const fd = fs.openSync(filePath, 'r')
  try {
    const buf = Buffer.alloc(MAX_BYTES)
    fs.readSync(fd, buf, 0, MAX_BYTES, stat.size - MAX_BYTES)
    const lines = buf.toString('utf8').split('\n')
    lines.shift() // 首行大概率被从中间切断
    return lines
  } finally {
    fs.closeSync(fd)
  }
}

/**
 * 数主会话的工具调用、派发，以及自上次派发以来的只读检索次数。
 * @returns {{calls: number, dispatches: number, probesSince: number, parsed: number}}
 *   parsed = 成功解析出的 assistant 行数，用于区分「真的 0 派发」与「什么都没读到」。
 *   probesSince = 顺序扫描到最后时刻的值：遇 Agent/Task 清零、遇 PROBE_TOOLS 加一。
 *     从未派发过时它等于全会话的检索总数——语义上一致（"上一次派发"是会话开头）。
 */
function count(lines) {
  let calls = 0
  let dispatches = 0
  let probesSince = 0
  let parsed = 0
  for (const line of lines) {
    if (!line || line.charCodeAt(0) !== 123 /* '{' */) continue
    let row
    try {
      row = JSON.parse(line)
    } catch (e) {
      continue
    }
    if (row.type !== 'assistant' || row.isSidechain === true) continue
    const content = row.message && row.message.content
    if (!Array.isArray(content)) continue
    parsed += 1
    for (const block of content) {
      if (!block || block.type !== 'tool_use') continue
      calls += 1
      if (block.name === 'Agent' || block.name === 'Task') {
        dispatches += 1
        probesSince = 0
      } else if (PROBE_TOOLS.has(block.name)) {
        probesSince += 1
      }
    }
  }
  return { calls, dispatches, probesSince, parsed }
}

function render(calls, dispatches, probesSince) {
  const head = `# 派发账本（harness 现算，非你的记忆）\n\n本会话至此：主会话工具调用 ${calls} 次 / \`Agent\` 派发 ${dispatches} 次。`
  const tail = `自上次派发以来，你已亲手检索 ${probesSince} 次（Read/Grep/Glob/Bash，只读写不分）。`

  if (dispatches === 0 && calls >= NUDGE_AT) {
    return `${head}整段会话一次没派过，这一段连查 ${probesSince} 次——回看零章检查点②：手上是否还有 ≥2 个互不依赖的待查项？有就派，别再自己顺手查。`
  }
  if (probesSince >= PROBE_LIMIT) {
    return `${head}${tail}**已过检查点②的次数线（≥${PROBE_LIMIT}）。** 判据的另一半——手上是否仍有 ≥2 个互不依赖的待查项——harness 算不出来，只有你知道。现在就答它：有，则下一个动作是派 \`Explore\` 而不是再读一个文件；没有，才继续自己查。别跳过这个自问。`
  }
  return `${head}${tail}`
}

function main() {
  const ev = readEvent()
  const p = ev.transcript_path
  if (!p) return

  let lines
  try {
    lines = readTail(p)
  } catch (e) {
    return // 读不到就不注入，绝不谎报 0
  }

  const { calls, dispatches, probesSince, parsed } = count(lines)
  if (parsed === 0) return // 一行 assistant 都没解析出来 = 判据失灵，不注入
  if (calls < MIN_CALLS) return

  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'UserPromptSubmit',
      additionalContext: render(calls, dispatches, probesSince),
    },
  }))
}

try {
  main()
} catch (e) {
  // 注入类 hook 一律静默降级，绝不阻断用户提交
}

module.exports = { count, render, MIN_CALLS, NUDGE_AT, PROBE_LIMIT, PROBE_TOOLS }
