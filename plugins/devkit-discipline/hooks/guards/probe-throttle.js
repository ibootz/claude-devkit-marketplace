#!/usr/bin/env node
// probe-throttle.js — PreToolUse 决策时刻闸（matcher: Agent|Read|Grep|Glob|Bash）
//
// 【用途：把检查点②从"回合开头的统计"搬到"要按下第 N 次 Read 之前"】
// dispatch-ledger.js 挂 UserPromptSubmit，在 prompt 提交那一刻摆出派发数字。但决定
// "这一步该自己查还是派 Explore"的时刻不在回合开头，而在 AI 即将发起第 N 次只读检索
// 的那一瞬间。本 hook 落在那一瞬间，做两件事：
//   · 串行检索数达到 NOTICE_AT → 注一行实时计数（additionalContext，零拦截）
//   · 达到 DENY_AT 且本段还没拦过 → deny 一次，强制在那一刻做出决定（可自解除）
// 两者共用同一个计数器，Agent 派发时清零。
//
// 【为什么自己记账，不回读 transcript】
// hook-restraint.md 实证 3：靠回读 transcript 做门控判定会永久拒绝——一条 assistant
// message 要等 API 响应结束才整体写盘，而 PreToolUse 发生在那之前，同一条 message 里的
// 内容在它自己的 tool_use 触发 hook 时读不到。本 hook 不需要读历史：它自己就在每一次
// 工具调用上被触发，把计数落盘即可。这既规避了那条死局，也比 dispatch-ledger 的 8MB
// 尾读快一个数量级（每次只读写一个几十字节的 JSON）。
//
// ── 六问（hook-restraint.md 要求，逐条回答）─────────────────────────────
// 0. 挂哪个事件、能不能阻止操作？
//    PreToolUse。permissionDecision: "deny" 能真正拦下这次调用（对照：write-guard 挂
//    PostToolUse，拦不住任何东西）。本 hook 的 deny 是**可自解除**的，见下面第 4 问。
// 1. 判据的确定字段是哪个？
//    tool_name（闭合枚举比较）+ 磁盘计数器整数与阈值比较 + 两个时间戳之差与阈值比较。
//    不解析 tool_input、不看语义、不读 transcript。
// 2. 假阳性长什么样？
//    最严重的一类已在设计上排除：同一条消息并发 5 个 Read 会连触发 5 次 hook，若按
//    纯次数判定，第 6 次就把**正确的并行行为**拦下——奖惩正好反了。故加 BATCH_WINDOW_MS
//    时间窗：距上次记账不足该窗口的视为同批，只计数、不 deny、不注入。
//    剩余假阳性：AI 确实连查了 6 次、且手上真的只剩 1 个待查项（合取判据的另一半算不出
//    来）。这一类的代价被压到"重发同一调用即放行"，见第 4 问。
// 3. 假阴性长什么样？
//    (a) 把 6 次检索拆进两条消息、每条 3 个并发 → 时间窗判为同批，不拦。但那正是本
//        规则想要的行为（并行），不该拦，所以这不是缺陷而是判据收窄的目的。
//    (b) 用 Task 之外的工具做检索（WebFetch / MCP 工具 / TaskOutput）不计数。
//    (c) 同批 hook 并发读写同一 state 文件会丢失更新，计数偏小 → 少拦。方向保守。
// 4. AI 撞到之后能不能一次改对？
//    finding 里给两条可直接照抄的出路：一条是并发派 3 个 Explore 的完整 JSON（照抄即
//    合规），另一条是"若确认无 ≥2 个互不依赖的待查项，**重发本次调用即放行**"——因为
//    deny 那一刻就置了 deniedSinceDispatch，同一段内不会再拦第二次。所以它不是墙，是
//    减速带：强制一次真实的决定，但从不把 AI 卡死。
// 5. 失灵时会怎样？
//    state 文件读写失败 / payload 缺字段 / 任何异常 → 静默 exit 0，既不 deny 也不注入
//    （fail-open）。另有两道熔断：单会话 deny 上限 MAX_DENIES，以及 tmpdir 被系统清理
//    时计数归零（最坏结果是少提示一次）。判据不依赖任何外部数据结构（transcript 行格式、
//    JSONL 字段名），所以不存在"上游改格式导致永久拒绝"这条路径。
// ────────────────────────────────────────────────────────────────────
//
// 【子代理不参与】
// payload.agent_id 仅在 hook 从子代理内部触发时存在（2.1.220 二进制里该字段的 describe
// 原文：Present only when the hook fires from within a subagent）。子代理层不适用本规则：
// 嵌套深度上限 2 层，第 2 层压根不许再派，拦它等于把它卡死；第 1 层的检索本身就是父代理
// 派发的产物，再要求它派下一层是反向激励。所以带 agent_id 时直接放行、也不记账。
//
// 【时间窗是本文件唯一的非纯计数判据，如实记录】
// BATCH_WINDOW_MS 依赖系统时钟，同一输入在不同时序下可得不同结论——严格说不满足
// hook-restraint 里"同一输入永远得到同一结论"。之所以仍然采用：它只在**减少** deny 的
// 方向上起作用（判为同批 → 不拦），不会凭它多拦任何一次。取 1000ms 的依据是两个数量级
// 的差：同批 hook 触发间隔在百毫秒内，而 AI 逐个发起调用之间必须经过一次模型往返（秒级）。
//
// 【改完要重启】cc hook 在会话启动时加载。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')

// 计入"只读检索"的工具名。与 dispatch-ledger.js 的 PROBE_TOOLS 同口径（Bash 一律计入，
// 不区分读写——区分要解析命令语义，那是 bash-guard 实测 19 类漏报的老路）。
const PROBE_TOOLS = new Set(['Read', 'Grep', 'Glob', 'Bash'])
// 派发工具名。Task 是旧版工具名，一并认。
const DISPATCH_TOOLS = new Set(['Agent', 'Task'])
// 达到这个串行检索数开始注一行实时计数（零拦截）。
const NOTICE_AT = 4
// 达到这个数且本段未拦过时 deny 一次。取 6 是照抄零章检查点②的次数线——两处必须一致，
// 否则 AI 读到的判据和实际拦它的判据对不上。
const DENY_AT = 6
// 单会话 deny 上限（熔断）。超过后只注入不拦，避免长会话被反复打断。
const MAX_DENIES = 3
// 同批判定窗口（毫秒）。距上次记账不足此值 = 同一条消息里的并发调用，只计数不干预。
const BATCH_WINDOW_MS = 1000

function readEvent() {
  try {
    const raw = fs.readFileSync(0, 'utf8')
    if (!raw || !raw.trim()) return null
    return JSON.parse(raw)
  } catch (e) {
    return null
  }
}

// state 落在 tmpdir：它是运行态而非用户数据，被系统清理只会让计数归零（安全降级）。
// 允许用环境变量改写，仅供回归用例隔离，不供正常使用。
function stateDir() {
  return process.env.WD_PROBE_STATE_DIR || path.join(os.tmpdir(), 'wd-probe-ledger')
}

// session_id 来自 payload，虽是 UUID 但不能直接拼进路径——只保留安全字符，
// 空值时退回一个固定名（同一台机器上多会话共用一个计数器，偏严但不出错）。
function stateFile(sessionId) {
  const safe = String(sessionId || 'unknown').replace(/[^A-Za-z0-9_-]/g, '')
  return path.join(stateDir(), `${safe || 'unknown'}.json`)
}

function loadState(file) {
  try {
    const s = JSON.parse(fs.readFileSync(file, 'utf8'))
    return {
      probes: Number.isFinite(s.probes) ? s.probes : 0,
      denies: Number.isFinite(s.denies) ? s.denies : 0,
      deniedSinceDispatch: s.deniedSinceDispatch === true,
      lastAt: Number.isFinite(s.lastAt) ? s.lastAt : 0,
    }
  } catch (e) {
    return { probes: 0, denies: 0, deniedSinceDispatch: false, lastAt: 0 }
  }
}

function saveState(file, state) {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true })
    fs.writeFileSync(file, JSON.stringify(state))
    return true
  } catch (e) {
    return false // 写不进去就当没记账，不影响放行
  }
}

// 可照抄的并发派发骨架。与注入文本里那份保持同源同形（改一处要改两处）——
// bash-guard 的正向对照：finding 给可照抄模板时 AI 一次改对，只写"禁止 X"则反复试错。
const DISPATCH_TEMPLATE = [
  '```json',
  '// 一条消息里发多个 Agent 调用 = 并发。三个分片各自独立，互不等待。',
  '{ "name": "sonnet-probe-config-layer", "model": "sonnet", "subagent_type": "Explore",',
  '  "description": "查配置层加载顺序", "run_in_background": true, "prompt": "<四段式>" }',
  '{ "name": "sonnet-probe-hook-wiring", "model": "sonnet", "subagent_type": "Explore",',
  '  "description": "查 hook 挂载与触达面", "run_in_background": true, "prompt": "<四段式>" }',
  '{ "name": "sonnet-probe-test-fixture", "model": "sonnet", "subagent_type": "Explore",',
  '  "description": "查回归用例现有形态", "run_in_background": true, "prompt": "<四段式>" }',
  '```',
].join('\n')

function denyReason(probes) {
  return [
    `[L1-BLOCKER] tool=probe-throttle check=serial-probe-limit`,
    `finding="自上次 \`Agent\` 派发以来，你已**逐个**发起 ${probes} 次只读检索（同一条消息里的并发调用不计入这个数）。检查点②的次数线是 ${DENY_AT}，已过线。"`,
    '',
    '判据的另一半 harness 算不出来，只有你知道——**现在答它**：手上还有 ≥2 个互不依赖的待查项吗？',
    '',
    `- **有** → 照抄下面这个整体派发，一条消息里发完（分片依据写进 \`name\`）：`,
    DISPATCH_TEMPLATE,
    `- **没有**（只剩 1 个待查项 / 后一步依赖前一步输出 / 写同一资源 / 待用户拍板）→ **原样重发刚才那次调用即放行**，本段不会再拦第二次。不必改写命令、不必绕道，也不要为了过闸去凑一个假的派发。`,
    '',
    `hint="这道闸只数**串行**次数：并发发出的调用判为同批、一次不计。所以把独立的检索合并进同一条消息发出，既是正解也天然不撞闸。"`,
  ].join('\n')
}

function noticeText(probes, denied) {
  const head = `# 串行检索计数（harness 现算）：自上次 \`Agent\` 派发以来，你已逐个发起 ${probes} 次只读检索。`
  if (denied) {
    // 本段已拦过一次，不再重复整套说辞，只给数字与一句指向。
    return `${head}本段已提示过一次，不再拦你——但数字还在涨。若剩余待查项 ≥2 个且互不依赖，现在派 \`Explore\` 仍然划算。`
  }
  return `${head}到 ${DENY_AT} 次会强制中断一次让你决定。想避开：把独立的待查项合并进同一条消息（并发不计数），或现在就派 \`Explore\`。`
}

function emit(hookEventName, payload) {
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: Object.assign({ hookEventName }, payload),
  }))
}

function main() {
  const ev = readEvent()
  if (!ev) return

  // 回声必须与入参一致（本仓硬要求：写死任一个会让另一路静默失效）。
  // 这里只挂 PreToolUse，所以非该事件一律不表态。
  if (ev.hook_event_name !== 'PreToolUse') return

  // 子代理不参与，见文件头。
  if (ev.agent_id) return

  const tool = ev.tool_name
  const file = stateFile(ev.session_id)

  if (DISPATCH_TOOLS.has(tool)) {
    // 派发即清零。不表态权限（Agent 的权限判定归 agent-dispatch.js）。
    saveState(file, { probes: 0, denies: loadState(file).denies, deniedSinceDispatch: false, lastAt: Date.now() })
    return
  }

  if (!PROBE_TOOLS.has(tool)) return

  const now = Date.now()
  const st = loadState(file)
  const isBatch = st.lastAt > 0 && now - st.lastAt < BATCH_WINDOW_MS
  st.probes += 1

  // 同批：只计数，不干预（不 deny、不注入）。见文件头假阳性一节。
  if (isBatch) {
    st.lastAt = now
    saveState(file, st)
    return
  }

  const shouldDeny = st.probes >= DENY_AT && !st.deniedSinceDispatch && st.denies < MAX_DENIES
  if (shouldDeny) {
    st.deniedSinceDispatch = true
    st.denies += 1
    st.lastAt = now
    saveState(file, st)
    emit('PreToolUse', {
      permissionDecision: 'deny',
      permissionDecisionReason: denyReason(st.probes),
    })
    return
  }

  st.lastAt = now
  saveState(file, st)

  if (st.probes >= NOTICE_AT) {
    emit('PreToolUse', { additionalContext: noticeText(st.probes, st.deniedSinceDispatch) })
  }
}

try {
  main()
} catch (e) {
  // fail-open：记账挂了绝不阻断工具调用
}

module.exports = {
  PROBE_TOOLS,
  DISPATCH_TOOLS,
  NOTICE_AT,
  DENY_AT,
  MAX_DENIES,
  BATCH_WINDOW_MS,
  denyReason,
  noticeText,
}
