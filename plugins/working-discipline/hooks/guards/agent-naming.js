// agent-naming.js — PreToolUse 门控钩子
//
// 【用途】
// 硬拦截命名不规范的 subagent / teammate 派发，落地注入纪律 5.5 节「派发命名规范」。
// 解决的真实问题（2026-07-25 事故）：在飞 agent 面板上出现 4 个子代理，name 全无模型
// 档次前缀（ontology-drain / verdict-part1 / verdict-part2 / verdict-part3），
// description 全被写成 prompt 原文开头「你是第 1 层子代理，可派…」——既把内部提示词
// 暴露到 UI 上，又让 4 行描述完全同质、无法分辨谁在做什么；另一个合规的
// 「[sonnet] 映射 16 个 spec」反而没给 name，面板左列回落成裸的 general-purpose。
// 纯注入纪律靠 AI 自觉，命中率不足，故补一道 exit 2 硬门禁。
//
// 【触发条件】
// - 工具：Agent（当前 Claude Code 的子代理派发工具名；旧名 Task 不匹配，避免在旧
//   工具名环境里因缺 name/model 字段而永久误拦——fail-open 优于误伤）
// - tool_input 可解析，且 subagent_type 不在 EXEMPT_SUBAGENT_TYPES 豁免名单内
//
// 【校验项】命中任意一条即拦截，多条时 finding 里全部列出
// 1. model 缺失或不在 haiku/sonnet/opus/fable —— 纪律要求显式指定，禁止默认回落
// 2. name 缺失 —— 省略后面板左列只能回落显示裸 subagent_type，同批多个无法分辨
// 3. name 不以 `{model}-` 开头（前缀必须与实际 model 一致，不许写不符的档次）
// 4. name 不满足 Agent 工具正则 ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$（提前拦并给清楚提示）
// 5. description 缺失，或不以 `[{model}] ` 方括号前缀开头（同样要求与 model 一致）
// 6. description 正文以角色设定/元指令句式开头（你是 / You are / 【目标】/ # 等）
//    —— 这是把 prompt 原文抄进 description 的高置信特征
// 7. description 正文长度 >= 20 且正好是 prompt 的开头 —— 抄袭特征
// 8. description 正文长度 > 60 —— 纪律要求 3-5 词摘要，超长说明塞了 prompt 内容
//
// 【放行场景】
// - 环境变量 AGENT_NAMING_GUARD=off（大小写不敏感）—— 总开关，便于临时关闭
// - tool_name 不是 Agent
// - subagent_type 属于 EXEMPT_SUBAGENT_TYPES（系统内建类型，model/命名语义不适用）
// - stdin 读取失败 / JSON 解析失败 / tool_input 缺失 —— 基础设施异常不误拦
// - 全部校验项通过
//
// 【阻塞行为】
// 命中即 exit 2 阻断，stderr 输出：
//   [L1-BLOCKER] tool=Agent check=agent-naming finding="..." hint="..."
// AI 收到 stderr 后应修正 name / description / model 再重新派发，而不是绕过。
//
// 【已知局限】
// 本 hook 只覆盖 Agent 工具的直接派发。Workflow 脚本内部 `agent(prompt, {label})`
// 的 label 不经过 PreToolUse，无法在此拦截，只能靠注入纪律 5.5.4 约束。
//
// Input: JSON on stdin with tool_name / tool_input
// Exit 0 = 放行; Exit 2 = 阻断

'use strict'

const fs = require('fs')

const MODELS = ['haiku', 'sonnet', 'opus', 'fable']

// Agent 工具 name 字段的原生正则约束（只接受 ASCII 字母数字与 - _）
const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/

// 系统内建 subagent_type：model 覆盖被忽略或命名语义不适用，一律放行。
// fork 明确「always inherit the parent model」，强制 model 前缀会自相矛盾。
const EXEMPT_SUBAGENT_TYPES = new Set([
  'fork',
  'statusline-setup',
  'output-style-setup',
])

// description 正文若以这些句式开头，判定为把 prompt 原文抄进了 description
const PROMPT_LEAK_PREFIXES = [
  '你是', '您是', '你將', '你将', '请你', '請你',
  '作为一个', '作為一個', '作为一名', '作為一名',
  'You are', 'you are', 'Your task', 'Act as', 'act as',
  '【', '#',
]

// description 正文最大长度（纪律要求 3-5 词摘要；超此长度说明塞了 prompt 内容）
const DESC_BODY_MAX = 60

// description 正文与 prompt 开头比对的最小长度门槛。低于此值不判抄袭——
// 短摘要与 prompt 开头偶然重合的概率高，会误报。
const LEAK_MATCH_MIN = 20

function main() {
  if (String(process.env.AGENT_NAMING_GUARD || '').toLowerCase() === 'off') {
    process.exit(0)
  }

  let input = ''
  try {
    input = fs.readFileSync(0, 'utf8')
  } catch (_) {
    process.exit(0)
  }

  let payload
  try {
    payload = JSON.parse(input)
  } catch (_) {
    process.exit(0)
  }

  if (payload.tool_name !== 'Agent') process.exit(0)

  const ti = payload.tool_input
  if (!ti || typeof ti !== 'object') process.exit(0)

  const subagentType = typeof ti.subagent_type === 'string' ? ti.subagent_type : ''
  if (EXEMPT_SUBAGENT_TYPES.has(subagentType)) process.exit(0)

  const model = typeof ti.model === 'string' ? ti.model.trim() : ''
  const name = typeof ti.name === 'string' ? ti.name.trim() : ''
  const description = typeof ti.description === 'string' ? ti.description.trim() : ''
  const prompt = typeof ti.prompt === 'string' ? ti.prompt : ''

  const findings = []
  const hints = []

  // ── 1. model 必须显式指定且在四档之内 ──
  const modelOk = MODELS.indexOf(model) !== -1
  if (!model) {
    findings.push('缺 model;禁止依赖默认模型回落')
    hints.push('显式加 model:"haiku"|"sonnet"|"opus"|"fable"')
  } else if (!modelOk) {
    findings.push(`model="${model}" 不在四档 haiku/sonnet/opus/fable 之内`)
    hints.push('model 只能填 haiku|sonnet|opus|fable')
  }

  // ── 2~4. name 必填 + 模型前缀 + 字符集合法 ──
  if (!name) {
    findings.push('缺 name;省略后面板左列只能回落显示裸 subagent_type,同批并发无法分辨各自任务')
    hints.push(`name 填 "${modelOk ? model : '<模型名>'}-<任务语义-kebab-case>"(如 sonnet-review-login-flow)`)
  } else {
    if (!NAME_PATTERN.test(name)) {
      findings.push(`name="${name}" 不满足 Agent 工具正则 ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$;只接受 ASCII 字母数字与 - _`)
      hints.push('name 用英文 kebab-case,不能含中文/空格/方括号')
    }
    const namePrefix = MODELS.find((m) => name.startsWith(m + '-'))
    if (!namePrefix) {
      findings.push(`name="${name}" 缺模型档次前缀;用户无法从面板判断在飞任务烧的是哪一档模型`)
      hints.push(`name 改成 "${modelOk ? model : '<模型名>'}-${name.replace(/^[^A-Za-z0-9]+/, '') || '<任务语义>'}"`)
    } else if (modelOk && namePrefix !== model) {
      findings.push(`name 前缀 "${namePrefix}-" 与实际 model="${model}" 不一致;面板会显示错误的模型档次`)
      hints.push(`name 前缀改成 "${model}-"`)
    }
  }

  // ── 5. description 必填 + 方括号模型前缀 ──
  let descBody = ''
  if (!description) {
    findings.push('缺 description')
    hints.push(`description 填 "[${modelOk ? model : '<模型名>'}] <3-5 词任务摘要>"`)
  } else {
    const m = description.match(/^\[(haiku|sonnet|opus|fable)\]\s*/)
    if (!m) {
      findings.push(`description="${truncate(description, 40)}" 缺 [模型名] 方括号前缀`)
      hints.push(`description 改成 "[${modelOk ? model : '<模型名>'}] <3-5 词任务摘要>"`)
    } else {
      if (modelOk && m[1] !== model) {
        findings.push(`description 前缀 "[${m[1]}]" 与实际 model="${model}" 不一致`)
        hints.push(`description 前缀改成 "[${model}]"`)
      }
      descBody = description.slice(m[0].length).trim()
      if (!descBody) {
        findings.push('description 只有 [模型名] 前缀,没有任务摘要正文')
        hints.push('前缀后补 3-5 词任务摘要')
      }
    }
  }

  // ── 6~8. 提示词泄露检测（只在拿到 description 正文时进行）──
  if (descBody) {
    const leakPrefix = PROMPT_LEAK_PREFIXES.find((p) => descBody.startsWith(p))
    if (leakPrefix) {
      findings.push(`description 正文以 "${leakPrefix}" 开头,是 prompt 角色设定/元指令句式而非任务摘要;提示词会暴露到在飞 agent 面板`)
      hints.push('description 只写"这个子代理在做什么",prompt 与 description 禁止共用同一段文字')
    } else if (descBody.length >= LEAK_MATCH_MIN && prompt.trimStart().startsWith(descBody)) {
      findings.push(`description 正文与 prompt 开头逐字重合(前 ${descBody.length} 字符);这是把 prompt 原文抄进 description 的特征`)
      hints.push('description 换成独立撰写的 3-5 词任务摘要,不要从 prompt 复制')
    }

    if (descBody.length > DESC_BODY_MAX) {
      findings.push(`description 正文 ${descBody.length} 字符超过 ${DESC_BODY_MAX};纪律要求 3-5 词摘要,超长说明塞了 prompt 内容`)
      hints.push(`description 正文压到 ${DESC_BODY_MAX} 字符以内`)
    }
  }

  if (findings.length === 0) process.exit(0)

  const msg =
    `[L1-BLOCKER] tool=Agent check=agent-naming ` +
    `finding="${findings.join(';')}" ` +
    `hint="${hints.join(';')};完整规范见注入纪律 5.5 节;确需临时关闭本门禁用 AGENT_NAMING_GUARD=off"`

  process.stderr.write(msg + '\n')
  process.exit(2)
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n) + '…' : s
}

main()
