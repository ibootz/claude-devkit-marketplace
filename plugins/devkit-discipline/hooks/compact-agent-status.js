#!/usr/bin/env node
/**
 * devkit-discipline · PreCompact + SessionStart(compact)：后台子代理状态表（纯注入，零拦截）
 *
 * 【要解决什么】
 *   2026-10-19 sptalent 会话（19d19a86…jsonl 第 42566 行那次 auto-compact）：子代理
 *   sonnet-spsd-prod-check 03:29 已完成并投递通知，随后用户中断一次，对话分支回绕，
 *   含通知的第 42507–42535 行整段落进被放弃的分支——既不在压缩保留的消息里，也没进摘要。
 *   摘要照派发时的印象写成「两个子代理都还在运行」，压缩后主会话三次告诉用户「还在跑」。
 *   Claude Code 自己只给「压缩时仍在跑」的 agent 补 task_status 提醒，已投递的不补，
 *   所以压缩后的上下文里没有任何反证。
 *
 *   根因是摘要**看不到**完成事件，在压缩提示词里多写一句「别丢子代理」修不了它。
 *   能修的是：hook 扫整份 JSONL（不顺 parentUuid 链走，被放弃分支里的行照样在文件里），
 *   把每个后台子代理的状态算出来，摆到两处——
 *     · PreCompact：stdout 交给摘要。Claude Code 2.1.303 二进制里 PreCompact 以 exit 0
 *       结束时，stdout 被拼成压缩请求末尾的 `Additional Instructions: <stdout>`，默认
 *       压缩指令不动；手动 / 自动 / reactive / precomputed 四条压缩路径都走这段拼接。
 *       子代理自己压缩时这段被 Claude Code 丢弃，所以只对主会话生效。
 *     · SessionStart(source=compact)：压缩完成后重扫一次，additionalContext 注入最新表。
 *       必须有这一路：precomputed 压缩会提前跑 PreCompact、提前生成摘要，之后才替换上下文，
 *       中间完成的子代理在 PreCompact 那份表里还是「进行中」。
 *
 * 【判据全部机械】
 *   只认四种结构化行，不对整行做字符串搜索（prompt_snapshot / api-request-blob 行里有
 *   工具描述原文，含 `<task-notification>` 字样，整行搜会误中）：
 *     1. 派发：`type==="assistant"` 的 `tool_use`，`name` 为 `Agent`（或旧名 `Task`）；
 *     2. 转后台：对应 `tool_result` 文本含 `Async agent launched successfully` 与
 *        `agentId: <id>`。同步返回的子代理没有这句，不进表——它们没有「在飞」状态；
 *     3. 完成通知：`queue-operation`(enqueue).content / `attachment`(queued_command).prompt /
 *        `user` 消息的字符串或 text 块里的 `<task-notification>` 块。同一条通知通常出现
 *        三次（入队、作为附件投递、作为用户消息投递），按块原文去重，只取第一次——入队
 *        时刻才是真实完成时刻，也避免「完成→被 SendMessage 唤醒→迟到的投递副本」把
 *        已唤醒的子代理又判回已完成；
 *     4. 唤醒：`SendMessage` 的 `tool_result` 带 `"resumedAgentId":"<id>"`，该子代理回到
 *        进行中。
 *   tool_result 里引用的通知原文（比如子代理回执里抄了一段）不算通知。
 *
 * 【「进行中」只写成「未见完成通知」】
 *   会话被 resume 时，旧进程里的后台子代理已经不在，却不会补发通知。表里如果直接写
 *   「运行中」，就是把这次的 bug 反过来再造一遍。所以只陈述可核验的事实：未见完成通知、
 *   派发时刻、输出文件最后写入时刻（输出文件就是子代理的 transcript，停止写入是它
 *   已不活动的直接证据），判断留给模型。
 *
 * 【失效时不谎报】
 *   transcript 读不到、一个后台子代理都没找到 → 什么都不输出。PreCompact 无输出时压缩
 *   请求与不装本插件完全一致。
 *
 * 【成本】
 *   流式按块读，只对含四类标记子串的行做 JSON.parse。175MB / 4.3 万行的 sptalent
 *   transcript 实测见 README。每次压缩跑两次。
 *
 * 【改完要重启】cc hook 在会话启动时加载。
 */

'use strict'

const fs = require('fs')

// 已结束的子代理最多列几个（按结束时刻倒序）。进行中的全列。
// 长会话里已结束的可达上百个，摘要出错的只会是最近结束的那几个。
const MAX_FINISHED = 6
const CHUNK = 4 * 1024 * 1024

// 行级预筛：不含任一标记的行不 parse。
const MARKERS = [
  '"name":"Agent"',
  '"name":"Task"',
  'Async agent launched',
  '<task-notification>',
  'resumedAgentId',
]

const STATUS_LABEL = {
  completed: '已完成',
  failed: '失败',
  killed: '已终止',
  stopped: '已停止',
}

const NOTIFY_RE = /<task-notification>([\s\S]*?)<\/task-notification>/g

function readEvent() {
  try {
    const raw = fs.readFileSync(0, 'utf8')
    if (!raw || !raw.trim()) return {}
    return JSON.parse(raw)
  } catch (e) {
    return {}
  }
}

// 按块流式读行。按字节 0x0A 切行，避免 UTF-8 多字节字符被块边界切断。
function forEachLine(file, fn) {
  const fd = fs.openSync(file, 'r')
  try {
    const buf = Buffer.alloc(CHUNK)
    let rest = Buffer.alloc(0)
    let n
    while ((n = fs.readSync(fd, buf, 0, CHUNK, null)) > 0) {
      const data = rest.length ? Buffer.concat([rest, buf.subarray(0, n)]) : Buffer.from(buf.subarray(0, n))
      let start = 0
      let idx
      while ((idx = data.indexOf(10, start)) !== -1) {
        fn(data.toString('utf8', start, idx))
        start = idx + 1
      }
      rest = data.subarray(start)
    }
    if (rest.length) fn(rest.toString('utf8'))
  } finally {
    fs.closeSync(fd)
  }
}

function tag(block, name) {
  const m = block.match(new RegExp(`<${name}>([\\s\\S]*?)</${name}>`))
  return m ? m[1].trim() : ''
}

function textOf(content) {
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  return content
    .map((b) => (b && b.type === 'text' && typeof b.text === 'string' ? b.text : ''))
    .join('\n')
}

/**
 * 扫描 JSONL 行，返回后台子代理状态。
 * @returns {Map<string, {id, name, description, status, launchedAt, endedAt, outputFile, summary}>}
 *   status：'running' 表示「派发或唤醒之后未见完成通知」，其余取通知里的 <status> 原值。
 */
function scan(lines) {
  const pending = new Map() // tool_use_id -> { name, description, launchedAt }
  const agents = new Map()
  const seenNotices = new Set()

  function applyNotices(text, at) {
    if (!text || text.indexOf('<task-notification>') === -1) return
    NOTIFY_RE.lastIndex = 0
    let m
    while ((m = NOTIFY_RE.exec(text)) !== null) {
      const block = m[1]
      const key = block.replace(/\s+/g, ' ').trim()
      if (seenNotices.has(key)) continue
      seenNotices.add(key)
      const id = tag(block, 'task-id')
      const a = agents.get(id)
      if (!a) continue // Bash 后台任务、Monitor 等，或派发行不在本文件里
      a.status = tag(block, 'status') || 'completed'
      a.endedAt = at || a.endedAt
      a.summary = tag(block, 'summary') || a.summary
      a.outputFile = tag(block, 'output-file') || a.outputFile
    }
  }

  for (const line of lines) {
    if (!line || line.charCodeAt(0) !== 123 /* '{' */) continue
    if (!MARKERS.some((k) => line.indexOf(k) !== -1)) continue
    let row
    try {
      row = JSON.parse(line)
    } catch (e) {
      continue
    }
    if (!row || row.isSidechain === true) continue
    const at = row.timestamp

    if (row.type === 'queue-operation') {
      if (row.operation === 'enqueue' && typeof row.content === 'string') applyNotices(row.content, at)
      continue
    }
    if (row.type === 'attachment') {
      const att = row.attachment
      if (att && att.type === 'queued_command' && typeof att.prompt === 'string') applyNotices(att.prompt, at)
      continue
    }

    const content = row.message && row.message.content
    if (row.type === 'assistant' && Array.isArray(content)) {
      for (const b of content) {
        if (!b || b.type !== 'tool_use') continue
        if (b.name !== 'Agent' && b.name !== 'Task') continue
        const input = b.input || {}
        pending.set(b.id, {
          name: typeof input.name === 'string' ? input.name : '',
          description: typeof input.description === 'string' ? input.description : '',
          launchedAt: at,
        })
      }
      continue
    }
    if (row.type !== 'user') continue

    if (typeof content === 'string') {
      applyNotices(content, at)
      continue
    }
    if (!Array.isArray(content)) continue
    for (const b of content) {
      if (!b) continue
      if (b.type === 'text') {
        applyNotices(b.text, at)
        continue
      }
      if (b.type !== 'tool_result') continue
      const text = textOf(b.content)
      const launch = pending.get(b.tool_use_id)
      if (launch) {
        pending.delete(b.tool_use_id)
        const idm = text.indexOf('Async agent launched') !== -1 && text.match(/agentId:\s*([A-Za-z0-9]+)/)
        if (!idm) continue // 同步子代理，没有在飞状态
        const of = text.match(/output_file:\s*(\S+)/)
        agents.set(idm[1], {
          id: idm[1],
          name: launch.name,
          description: launch.description,
          status: 'running',
          launchedAt: launch.launchedAt,
          endedAt: undefined,
          outputFile: of ? of[1] : '',
          summary: '',
        })
        continue
      }
      const rm = text.match(/"resumedAgentId"\s*:\s*"([A-Za-z0-9]+)"/)
      if (rm && agents.has(rm[1])) {
        const a = agents.get(rm[1])
        a.status = 'running'
        a.launchedAt = at || a.launchedAt
        a.endedAt = undefined
      }
    }
  }
  return agents
}

function pad(n) {
  return String(n).padStart(2, '0')
}

function fmtTime(iso) {
  const d = iso instanceof Date ? iso : new Date(iso)
  if (Number.isNaN(d.getTime())) return '时刻未知'
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function outputMtime(file) {
  if (!file) return '输出文件路径未知'
  try {
    return `输出文件最后写入 ${fmtTime(fs.statSync(file).mtime)}`
  } catch (e) {
    return '输出文件已不存在'
  }
}

function label(a) {
  const who = a.name ? `${a.name}「${a.description}」` : `「${a.description}」`
  return `${who} · agentId ${a.id}`
}

// 输出文件路径很长（约 180 字符）且通常同在一个 tasks 目录下：目录只写一次，行内只写文件名。
function commonDir(files) {
  const dirs = new Set(files.filter(Boolean).map((f) => f.slice(0, f.lastIndexOf('/') + 1)))
  return dirs.size === 1 ? [...dirs][0] : ''
}

/**
 * @returns {{lines: string[], omitted: number, dir: string} | null} 没有任何后台子代理时返回 null。
 */
function buildList(agents) {
  const all = [...agents.values()]
  if (all.length === 0) return null
  const running = all.filter((a) => a.status === 'running')
  const finished = all
    .filter((a) => a.status !== 'running')
    .sort((x, y) => String(y.endedAt || '').localeCompare(String(x.endedAt || '')))
  const shown = finished.slice(0, MAX_FINISHED)
  const dir = commonDir(shown.map((a) => a.outputFile))
  const lines = []
  for (const a of running) {
    lines.push(`- 未见完成通知 · ${label(a)} · 派发于 ${fmtTime(a.launchedAt)} · ${outputMtime(a.outputFile)}`)
  }
  for (const a of shown) {
    const st = STATUS_LABEL[a.status] || a.status
    const file = a.outputFile && dir ? a.outputFile.slice(dir.length) : a.outputFile
    const out = file ? ` · 回执 ${file}` : ''
    lines.push(`- ${st} · ${label(a)} · 结束于 ${fmtTime(a.endedAt)}${out}`)
  }
  return { lines, omitted: finished.length - shown.length, dir }
}

function listBody(list) {
  const parts = [list.lines.join('\n')]
  if (list.omitted > 0) parts.push(`（另有 ${list.omitted} 个更早结束的子代理未列出。）`)
  if (list.dir) parts.push(`回执文件所在目录：${list.dir}`)
  return parts.join('\n')
}

function renderPreCompact(list) {
  return [
    '【后台子代理状态】下表由 devkit-discipline 扫描整份会话记录算出，包括被中断的对话分支里的完成通知，比对话里较早的说法新。',
    listBody(list),
    '写摘要时，Pending Tasks 与 Current Work 里凡提到上表的子代理，状态逐个照上表写，并注明这是压缩时的状态。已结束的写明「已完成（或失败、已停止），回执在输出文件」。未见完成通知的保留 name 与 agentId，压缩后要靠它们对上完成通知。',
  ].join('\n')
}

function renderPostCompact(list) {
  return [
    '# 后台子代理状态（压缩后由 devkit-discipline 扫描会话记录现算）',
    '',
    '压缩摘要是模型写的，可能把已完成的子代理写成还在跑：被中断的对话分支里的完成通知，摘要看不到。子代理状态以本表为准，本表之后到达的 task-notification 再覆盖本表。',
    '',
    listBody(list),
    '',
    '已结束的子代理，回执原文在输出文件里，要用时 Read。说某个子代理「还在跑」之前，先对照本表与之后的通知；「未见完成通知」而输出文件已久未写入的，按可能已停止向用户说明。',
  ].join('\n')
}

function main() {
  const ev = readEvent()
  if (ev.agent_id) return // 子代理自己的压缩：PreCompact 输出会被丢弃，SessionStart 也不归这里管
  const event = ev.hook_event_name
  const isPre = event === 'PreCompact'
  const isPost = event === 'SessionStart' && ev.source === 'compact'
  if (!isPre && !isPost) return
  if (!ev.transcript_path) return

  const lines = []
  try {
    forEachLine(ev.transcript_path, (l) => {
      if (MARKERS.some((k) => l.indexOf(k) !== -1)) lines.push(l)
    })
  } catch (e) {
    return
  }
  const list = buildList(scan(lines))
  if (!list) return

  if (isPre) {
    process.stdout.write(renderPreCompact(list))
    return
  }
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'SessionStart',
      additionalContext: renderPostCompact(list),
    },
  }))
}

if (require.main === module) {
  try {
    main()
  } catch (e) {
    // 注入类 hook 一律静默降级，绝不阻断压缩
  }
}

module.exports = { scan, buildList, renderPreCompact, renderPostCompact, MAX_FINISHED }
