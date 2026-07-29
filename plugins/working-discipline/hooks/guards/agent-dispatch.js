// agent-dispatch.js — PreToolUse 门控钩子（matcher: Agent）
//
// 【用途】
// 派发 subagent 时**结构层面**机械可判定的要求在这里处理：model 是否显式给了且在三档内、
// name / description 是否齐备、前缀是否与 model 一致、description 是否把 prompt 原文灌了
// 进去。判据全部取自 tool_input 的确定字段，不猜语义、不回读 transcript。
//
// 【本文件是「针对 Agent 这一个对象的唯一 hook」】
// 3.0.0 起本插件的挂载拓扑按**拦截对象**收敛：Agent → 本文件，Bash → bash-guard.js，
// Write|Edit → write-guard.js。同一对象只过一道闸，一次报清所有问题。原先"多个 guard
// 分层串行挂同一个 matcher"的拓扑有个结构性缺陷：**一批只报最前面那道闸**，AI 补完
// 第一道才看见第二道，多轮往返是拓扑的产物而不是 AI 每轮新犯一个错。
//
// 【3.0.0 之二：缺 name 改为自动补全，不再 deny】
// 根因不是 AI 注意力不够，而是**两套约束不同源**：`Agent` 工具的 JSON Schema 里
// `properties` 只声明了 description / prompt / subagent_type / model / run_in_background /
// isolation 六项，还写着 `additionalProperties: false`——`name` 是 schema 外但运行时真实
// 消费的字段（实证：<project>/subagents/agent-<id>.meta.json 里存着
// {"agentType":"Explore","description":"[sonnet] …","name":"sonnet-dbops-translate-weight-ids",
// "model":"sonnet"}）。AI 构造工具调用时照 schema 的字段表生成，字段表里不存在的字段不会
// 被"想起来"，所以「缺 name」是结构性必然、不是偶发疏忽；用 deny 打回只是把这次必然的
// 返工固化下来。现在改为用 `hookSpecificOutput.updatedInput` 补一个合规名并放行。
//
// 边界（为什么不是"所有命名问题都自动修"）：
//   - **字段缺失**（name 压根没给）→ 自动补。AI 看不见这个字段，罚它没有教育意义。
//   - **字段存在但格式错**（前缀与 model 不符 / 含中文 / description 抄 prompt）→ 仍 deny。
//     AI 既然产出了这个值，就说明它知道字段存在，此时 finding 能真正教会它规则。
//   - **model 缺失/非法** → 仍 deny，且不顺手补 name。档位是语义决策（这个任务值不值得
//     上高档模型），自动填一个默认值等于把决策悄悄替 AI 做了，还会让 name 前缀跟着错。
//
// 【3.0.0 之三：所有靠关键词猜语义的校验已删除】
// 2.0.0 曾有第二层「派发质量」四条（档位错配 / 索要回执 / 截图附路径 / 写操作传染回读），
// 判据是**正则扫 prompt 词表**，配上不可绕过的 deny 后失败模式变成「AI 做对了却过不去」。
// 实证三条：
//   (a) 写后回读那条扫 create/update/delete/发布/提交 等词。排查一个「点发布按钮报错」的
//       bug 时，`发布`/`publish` 在 prompt 里出现十几次全是**被排查对象的业务语义**，不是
//       要执行的动作；而 Explore 类型物理上没有 Edit/Write 工具、改不了任何文件，守卫却
//       只读 prompt 文本、没把 subagent_type 的权限面纳入判据。
//   (b) 截图那条回读 transcript 取图片路径，而工具结果行的 type 也是 'user'——AI 自己
//       Read 过一张图、grep 输出里带一个 .png 路径，本轮后续**所有** Agent 派发全被拦。
//       它读自己的源码就会自我触发：源码里的正则字面量完全符合旧路径正则的形状。
//   (c) 档位那条因 prompt 里出现「不变量」「根因」就要求升 opus，而那里的"不变量"只是
//       spec 里名为 INV-xx 的条目字段名。
// 逃生舱（`档位已确认：` / `豁免图片：`）不算解法：它要求 AI 先撞一次 deny、再回头往
// prompt 里塞一句咒语，而 deny 不给用户"点一下就过"的入口。这四条已改为 working-discipline.js
// 在 UserPromptSubmit 侧的软约束注入（5.6 与 buildImageEvidence）。
//
// 判断标准因此固化为一条：**判据取自 tool_input 的确定字段** → 可以写成 guard；
// **判据要靠正则猜语义或回读 transcript** → 留在注入里靠自觉，别做成 deny。
//
// 【触发条件】
// - 工具名为 Agent。**不匹配旧名 Task**：旧工具名的 tool_input 可能没有 name / model
//   字段，强行校验会永久误拦——fail-open 优于误伤。
// - subagent_type 不在 EXEMPT_SUBAGENT_TYPES 内
//
// 【放行场景】
// - 环境变量 AGENT_DISPATCH_GUARD=off 或 AGENT_NAMING_GUARD=off（大小写不敏感）。
//   保留旧名 AGENT_NAMING_GUARD 是为了不破坏 1.11.0 起已在用的关闭方式。
// - tool_name 不是 Agent
// - subagent_type 属于 EXEMPT_SUBAGENT_TYPES（系统内建类型，model / 命名语义不适用；
//   fork 明确「always inherit the parent model」，强制 model 前缀会自相矛盾）
// - stdin 读取失败 / JSON 解析失败 / tool_input 缺失 —— 基础设施异常不误拦
// - 只缺 name（其余全过）→ 自动补名后放行，不是拦截
// - 校验全过
//
// 【阻塞行为】
// 格式错时输出 JSON permissionDecision: "deny"，reason 沿用本仓库 guard 的
// [L1-BLOCKER] ... finding= hint= 格式。缺 name 时输出 updatedInput（不带
// permissionDecision，让正常权限流继续走），并用 additionalContext 告知已自动补名。
//
// 【已知局限】
// 只覆盖 Agent 工具的直接派发。Workflow 脚本内部 agent(prompt, {label}) 不经 PreToolUse，
// label 缺失或抄 prompt 拦不到，只能靠注入纪律 5.4.4 约束。
//
// Input: JSON on stdin with tool_name / tool_input
// Exit 0（始终）——放行、补名、deny 都走 exit 0，靠 stdout 的 JSON 表达决定

'use strict'

const fs = require('fs')
const crypto = require('crypto')

// 可选模型三档。**不含 haiku**（2026-07-27 起）：haiku 在机械任务上省下的那点
// 成本，抵不过它读错文件结构、漏掉边界条件后父代理返工重派的开销——最低档一律
// 从 sonnet 起步。写了 haiku 会被拦下并回灌路由表。
const MODELS = ['sonnet', 'opus', 'fable']

// Agent 工具 name 字段的原生正则约束（只接受 ASCII 字母数字与 - _）
const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/
const NAME_MAX = 64

// 系统内建 subagent_type：model 覆盖被忽略或命名语义不适用，一律放行。
const EXEMPT_SUBAGENT_TYPES = new Set(['fork', 'statusline-setup', 'output-style-setup'])

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

// 完整场景路由表：只在「model 缺失/非法」时才注入（档位错配的语义判定已删除，
// 这张表现在只用于"你没给 model，这是选档依据"这一个场景）
const ROUTING_TABLE = [
  '## subagent_type × model 场景路由表',
  '',
  '| subagent_type | 权限 | 适用场景 |',
  '|---|---|---|',
  '| `Explore` | 只读（无 Edit/Write，但有 Bash/Grep/Read） | 代码库探索、架构分析、模块调查、文件定位、符号/引用检索 |',
  '| `Plan` | 只读 | 架构设计、实现策略规划、任务拆解、风险评估、权衡分析 |',
  '| `general-purpose` | 全权限含 Edit/Write/Bash | 功能实现、重构、测试、bug 修复、复杂多步任务、大输出命令执行 |',
  '',
  '只读任务绝不用 `general-purpose`（默认带 Edit/Write 权限，存在误改风险）。',
  '',
  '| 场景 | subagent_type | model |',
  '|---|---|---|',
  '| 只读检索与分析：grep / 文件定位 / 找定义引用 / 单文件字段提取（日志·CSV·JSON） | `Explore` | `sonnet` |',
  '| 代码库架构调查 / 多文件交叉理解 / 依赖追踪 / 常规代码审查 | `Explore` | `sonnet` |',
  '| **深度代码审查**（安全审计 / 并发正确性 / 边界条件 / 协议一致性 / 数据一致性） | `Explore` | `opus` |',
  '| 常规架构设计 / 技术方案 / 任务拆解 / 风险评估 | `Plan` | `sonnet` |',
  '| **重大架构设计**（系统级取舍 / 破坏性变更 / 跨模块不变量迁移 / 长期演进） | `Plan` | `opus` |',
  '| 机械执行类：大输出命令 + 摘要（npm test / docker logs / dump）、git log·diff 摘要、提交消息生成 | `general-purpose` | `sonnet` |',
  '| 机械文件改写（重命名、格式化、模板填充、批量替换） | `general-purpose` | `sonnet` |',
  '| Web 文档检索 / 多源调研 + 综合分析 | `general-purpose` | `sonnet` |',
  '| 常规多步骤编码 / 重构 / 普通 bug 修复 / 测试编写 | `general-purpose` | `sonnet` |',
  '| **复杂 bug 排查**：跨模块 / 难复现 / 并发·竞态·死锁 / 内存泄漏 / 时序 / 性能回退 / 长链根因 | `general-purpose` | `opus` |',
  '| **性能诊断与优化**：找真正瓶颈 / 判断优化方向 / 基准设计 / 复杂度分析 | `general-purpose` | `opus` |',
  '| **安全漏洞分析与修复**：认证 / 授权 / 注入 / SSRF / 反序列化 / 信息泄漏 | `general-purpose` | `opus` |',
  '| **复杂算法设计与选型**：数据结构与复杂度取舍 / 边界与不变量证明 | `general-purpose` | `opus` |',
  '| **深度技术调研**：对抗性验证 / 多源交叉核对 / 可信度评估 | `general-purpose` | `opus` |',
  '| **兜底升级**：同一任务在 opus 下已完整跑过 ≥2 轮仍无进展 | 沿用原类型 | `fable` |',
  '',
  '模型三档判定标尺（**无 haiku 档，最低从 sonnet 起**）：',
  '- `sonnet`：**全局最低档兼默认档**。机械执行（模式匹配、规整提取、批量改写、简短摘要）',
  '  与常规语义任务（跨文件推理、常规设计权衡、多步骤编码与审查）**都从这一档起步**',
  '- `opus`：命中任一即用——(a) 需严密因果链（跨层追根因）；(b) 极高正确性要求',
  '  （安全/并发/协议/资金/权限）；(c) sonnet 已明显吃力（漏点多、方案有硬缺陷、修 A 出 B）',
  '- `fable`：兜底升级不作首选——同一任务用 opus 完整跑过 ≥2 轮仍无进展才启用',
  '- 禁止预防性堆模型：没有 opus 触发信号就留在 sonnet，不确定时一档一档升，别一步跳顶',
].join('\n')

function deny(reason) {
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: reason,
      },
    }) + '\n'
  )
  process.exit(0)
}

// 补全 name 后放行。**不带 permissionDecision**：本 hook 只负责改参数，权限判定交回
// 正常流程（给 "allow" 会连带跳过其他权限检查，越权）。additionalContext 告知 AI
// 已自动补名，让它下次自己起有语义的名字——自动名只有 subagent_type 和哈希，
// 可辨性弱于 AI 自己写的任务语义。
function allowWithName(ti, name, note) {
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        updatedInput: Object.assign({}, ti, { name: name }),
        additionalContext: note,
      },
    }) + '\n'
  )
  process.exit(0)
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n) + '…' : s
}

function guardDisabled() {
  const off = (v) => String(v || '').toLowerCase() === 'off'
  return off(process.env.AGENT_DISPATCH_GUARD) || off(process.env.AGENT_NAMING_GUARD)
}

// ── 自动补名 ────────────────────────────────────────────────────────
//
// 语义来源优先级：description 正文里的 ASCII 词 > subagent_type。
// description 常是中文（纪律要求它写中文任务摘要），抽不出 ASCII 词时退回
// subagent_type——中文转写（拼音/翻译）在 hook 里不可靠，宁可给个语义弱但绝不出错的名。

// 从 description 正文抽 ASCII 语义片段：'[sonnet] grep auth refs' → 'grep-auth-refs'
function deriveSlug(ti) {
  const desc = typeof ti.description === 'string' ? ti.description : ''
  const body = desc.replace(/^\[(sonnet|opus|fable|haiku)\]\s*/, '')
  const words = (body.match(/[A-Za-z0-9]+/g) || [])
    .map((w) => w.toLowerCase())
    .filter((w) => w.length >= 2)
    .slice(0, 4)
  if (words.length) return words.join('-')

  const st = typeof ti.subagent_type === 'string' ? ti.subagent_type : ''
  const fromType = st.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  return fromType || 'agent'
}

// 同批并发的多个 subagent 必须拿到不同的 name（同名会让 SendMessage 的 latest-wins
// 寻址把先派的那个弄丢）。用 prompt 的短哈希做区分符：纯函数、无需持久状态，
// 同一会话里两个 prompt 不同的派发几乎不可能撞。
function shortHash(s) {
  return crypto.createHash('sha1').update(s).digest('hex').slice(0, 4)
}

function autoName(ti, model) {
  const slug = deriveSlug(ti)
  const hash = shortHash(String(ti.prompt || '') + '|' + slug)
  const budget = NAME_MAX - model.length - 1 - 1 - hash.length // model + '-' + slug + '-' + hash
  const safeSlug = slug.slice(0, Math.max(1, budget))
  const name = `${model}-${safeSlug}-${hash}`
  // 兜底：任何原因导致不合正则时，退回一个必然合法的形态
  return NAME_PATTERN.test(name) ? name : `${model}-agent-${hash}`
}

// ── 命名与 model 的结构校验（多条一并列出）──────────────────────────
// 返回 { findings, hints, modelOk, nameMissing }
function checkNaming(ti) {
  const model = typeof ti.model === 'string' ? ti.model.trim() : ''
  const name = typeof ti.name === 'string' ? ti.name.trim() : ''
  const description = typeof ti.description === 'string' ? ti.description.trim() : ''
  const prompt = typeof ti.prompt === 'string' ? ti.prompt : ''

  const findings = []
  const hints = []
  const modelOk = MODELS.indexOf(model) !== -1
  const nameMissing = !name

  // 1. model 必须显式指定且在三档之内
  if (!model) {
    findings.push('缺 model;禁止依赖默认模型回落')
    hints.push('显式加 model:"sonnet"|"opus"|"fable"')
  } else if (model === 'haiku') {
    // haiku 单独给 finding：它是最常见的误填（旧纪律里曾是合法档），
    // 泛泛报「不在三档之内」不足以让人知道该换成哪一档。
    findings.push('model="haiku" 已从可选档次中移除;最低档是 sonnet')
    hints.push('机械执行/规整提取类任务同样用 model:"sonnet",并把 name / description 前缀一并改成 sonnet')
  } else if (!modelOk) {
    findings.push(`model="${model}" 不在三档 sonnet/opus/fable 之内`)
    hints.push('model 只能填 sonnet|opus|fable')
  }

  // 2. name 缺失**不进 findings**——它是 schema 外字段、AI 看不见，由 main() 自动补。
  //    但 model 也有问题时要顺带提醒：那种情况会走 deny，补名的时机已经错过，
  //    且补名需要合法的 model 做前缀。
  if (nameMissing && !modelOk) {
    hints.push('重派时顺带给 name:"<model>-<任务语义-kebab>"(schema 里查不到这个字段,但运行时接受并会存进 subagent 元数据)')
  }

  // 3~4. name 存在时校验字符集与模型前缀（存在即说明 AI 知道这个字段，格式错要教）
  if (!nameMissing) {
    if (!NAME_PATTERN.test(name)) {
      findings.push(`name="${name}" 不满足 Agent 工具正则 ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$;只接受 ASCII 字母数字与 - _`)
      hints.push('name 用英文 kebab-case,不能含中文/空格/方括号')
    }
    const namePrefix = MODELS.find((m) => name.startsWith(m + '-'))
    if (name.startsWith('haiku-')) {
      // 单独识别旧档前缀，避免回落到「缺前缀」分支后给出 "sonnet-haiku-xxx" 这种
      // 把旧档次名留在任务语义里的错误改法。
      findings.push(`name="${name}" 用了已移除的 haiku 档前缀`)
      hints.push(`name 改成 "${modelOk ? model : 'sonnet'}-${name.slice(6) || '<任务语义>'}"`)
    } else if (!namePrefix) {
      findings.push(`name="${name}" 缺模型档次前缀;用户无法从在飞 agent 面板判断这批任务烧的是哪一档模型`)
      hints.push(`name 改成 "${modelOk ? model : '<模型名>'}-${name.replace(/^[^A-Za-z0-9]+/, '') || '<任务语义>'}"`)
    } else if (modelOk && namePrefix !== model) {
      findings.push(`name 前缀 "${namePrefix}-" 与实际 model="${model}" 不一致;面板会显示错误的模型档次`)
      hints.push(`name 前缀改成 "${model}-"`)
    }
  }

  // 5. description 必填 + 方括号模型前缀（description 是 schema 里的必填字段，
  //    缺失基本由工具层拦掉，这里仍留判定以防 harness 放宽）
  let descBody = ''
  if (!description) {
    findings.push('缺 description')
    hints.push(`description 填 "[${modelOk ? model : '<模型名>'}] <3-5 词任务摘要>"`)
  } else {
    // 正则里保留 haiku 只为**识别**旧档前缀并给出精确改法（否则会掉进「缺前缀」
    // 分支，descBody 解析不出来，连带跳过后面的提示词泄露检测）；它已不是合法
    // 档次，命中即报错，不会放行。
    const m = description.match(/^\[(sonnet|opus|fable|haiku)\]\s*/)
    if (!m) {
      findings.push(`description="${truncate(description, 40)}" 缺 [模型名] 方括号前缀`)
      hints.push(`description 改成 "[${modelOk ? model : '<模型名>'}] <3-5 词任务摘要>"`)
    } else {
      if (m[1] === 'haiku') {
        findings.push('description 前缀 "[haiku]" 用了已移除的档次')
        hints.push(`description 前缀改成 "[${modelOk ? model : 'sonnet'}]"`)
      } else if (modelOk && m[1] !== model) {
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

  // 6~8. 提示词泄露检测（只在拿到 description 正文时进行）
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

  return { findings, hints, modelOk, nameMissing }
}

function main() {
  if (guardDisabled()) process.exit(0)

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

  // 只匹配当前工具名 Agent；旧名 Task 的 tool_input 可能无 name / model 字段，
  // 强行校验会永久误拦 —— fail-open 优于误伤。
  if (payload.tool_name !== 'Agent') process.exit(0)

  const ti = payload.tool_input
  if (!ti || typeof ti !== 'object') process.exit(0)

  const subagentType = typeof ti.subagent_type === 'string' ? ti.subagent_type : ''
  if (EXEMPT_SUBAGENT_TYPES.has(subagentType)) process.exit(0)

  const { findings, hints, modelOk, nameMissing } = checkNaming(ti)

  // 格式错 → deny（一次报清全部）
  if (findings.length) {
    let reason =
      `[L1-BLOCKER] tool=Agent check=agent-dispatch ` +
      `finding="${findings.join(';')}" ` +
      `hint="${hints.join(';')};完整规范见注入纪律 5.4 节;确需临时关闭本门禁用 AGENT_DISPATCH_GUARD=off"`
    // model 本身有问题时附完整路由表，帮助选对档次（命名问题不附，避免长文本淹没重点）
    if (!modelOk) reason += `\n\n${ROUTING_TABLE}`
    deny(reason)
  }

  // 只缺 name（其余全过）→ 自动补名放行
  if (nameMissing) {
    const model = ti.model.trim()
    const generated = autoName(ti, model)
    allowWithName(
      ti,
      generated,
      `[agent-dispatch] 本次派发没给 name（Agent 工具的 JSON Schema 未声明该字段，` +
        `但运行时接受并会存进 subagent 元数据），已自动补为 "${generated}" 并放行。` +
        `自动名只有 subagent_type + prompt 哈希，在飞面板上看不出任务差异——` +
        `下次派发请自己给 "${model}-<任务语义-kebab>"（如 ${model}-review-login-flow），` +
        `同批并发时把分片依据写进名字。`
    )
  }

  process.exit(0)
}

main()
