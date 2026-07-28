// agent-dispatch.js — PreToolUse 门控钩子（matcher: Agent）
//
// 【用途】
// 派发 subagent 的所有机械可判定要求都在这里硬拦。这些要求常驻注入的话，只会跟
// 「求真」「说明详细」这类无法硬拦截的语义规则抢注意力预算；改成命中时拦截并在
// reason 里给对应细则，选对时零开销、选错时才付细则成本。
//
// 【本文件是两个 guard 合并的产物（2026-07-26）】
// 原 hooks/guards/agent-naming.js（1.11.0 引入）负责命名与 model 的 8 项校验，
// 原 agent-dispatch.js（本次引入）负责派发质量的 4 项校验，两者都挂 PreToolUse(Agent)、
// 有三项重叠（model 必填 / description 的 [模型名] 前缀 / name 的 模型名- 前缀），
// 不合并会重复拦截并输出两份 finding。合并后 agent-naming.js 删除。
//
// 【两层校验，形态不同是有意的】
// 第一层「命名与 model」：多条违规**一并列出**（findings 聚合），因为这类问题往往
//   同时出现好几个（缺 name + description 抄 prompt + 超长），一次报清才能一次改对。
// 第二层「派发质量」：**取第一个命中**，每条给一段长细则（路由表 / 回执模板 / 回读要求）。
//   这类问题一次一个就够，同时倒出多段长文本会重演常驻注入的老问题。
//   只有第一层全过才进第二层——命名都没写对时，谈档位选择为时过早。
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
// - 两层校验全过
// - 逃生舱：档位与截图两类允许 prompt 里显式声明理由后放行（正则无法覆盖全部合法场景）
//
// 【阻塞行为】
// 输出 JSON permissionDecision: "deny"。按官方文档，Claude Code 读取该 JSON 后阻断
// 工具调用并把 permissionDecisionReason 展示给 Claude。命名类 reason 沿用本仓库
// guard 的 [L1-BLOCKER] ... finding= hint= 格式，便于与其他 guard 的输出统一识别。
//
// 【已知局限】
// 只覆盖 Agent 工具的直接派发。Workflow 脚本内部 agent(prompt, {label}) 不经 PreToolUse，
// label 缺失或抄 prompt 拦不到，只能靠注入纪律 5.4.4 约束。
//
// Input: JSON on stdin with tool_name / tool_input / transcript_path / prompt_id
// Exit 0（始终）——放行与 deny 都走 exit 0，靠 stdout 的 JSON 表达决定

'use strict'

const fs = require('fs')
const { currentTurnImagePaths } = require('../lib/transcript')

// 可选模型三档。**不含 haiku**（2026-07-27 起）：haiku 在机械任务上省下的那点
// 成本，抵不过它读错文件结构、漏掉边界条件后父代理返工重派的开销——最低档一律
// 从 sonnet 起步。写了 haiku 会在第一层被拦并回灌路由表。
const MODELS = ['sonnet', 'opus', 'fable']

// Agent 工具 name 字段的原生正则约束（只接受 ASCII 字母数字与 - _）
const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/

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

// 完整场景路由表：只在「model 缺失/非法」与「档位错配」两类命中时才注入
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

const RECEIPT_TEMPLATE = [
  '派发 prompt 必须明确索要结构化回执，否则子代理只回「已完成」，父代理无法审计、',
  '也无法在主对话向用户复述要点。在 prompt 的【期望输出】里写明要求返回：',
  '  1. 改了哪些文件（逐个列出路径）',
  '  2. 关键决策（为什么这样做，放弃了什么方案）',
  '  3. 阻塞点（没做完的、卡住的）',
  '  4. 需要父代理跟进的事项',
].join('\n')

const READBACK_REQUIREMENT = [
  '这个 prompt 含外部系统写操作（API / CLI / SDK / DB 的 create / update / delete /',
  '提交 / 改配置 / 授权 / 发布），但没有要求子代理做写后回读核验。',
  '',
  '写操作返回成功（HTTP 2xx / 退出码 0 / 无 error 字段）**只证明请求被接受，不证明',
  '意图被实现**。服务端有三类静默失败，响应里没有任何消极信号：(a) 静默忽略字段——',
  '字段服务端不认，既不报错也不警告直接丢弃，落默认值；(b) 静默降级——值超范围被截断',
  '或替换为默认值；(c) 部分成功——批量写入个别条目失败，整体仍返回成功。',
  '真实事故（2026-07-26）：向平台导航创建接口传 orderIndex: 15，返回 HTTP 204 无警告，',
  '回读发现实际存储值是默认的 1，字段被静默丢弃，菜单排到错误位置。',
  '',
  '父代理看不见子代理的写调用细节，回读要求写不进 prompt 就等于没有。请在 prompt 里',
  '显式写入：',
  '  - 每步写操作后立即用**读接口**（get / list / describe / SELECT）回读，逐字段比对',
  '    「以为写进去的值」与「服务端实际存储的值」；禁止把写接口自己的响应体当回读结果',
  '  - 写 N 个对象就回读 N 次，禁止抽查、禁止只查列表看总数',
  '  - 涉及层级/归属（parentId / 外键 / 所属分组）要额外从父对象侧确认能看到新成员',
  '  - 回执中必须给出**回读到的实际值**；只报「N 个全部创建成功」的回执一律不接受',
  '  - 确实没有读接口的项，明确标注「此项无法回读验证」，不得默认成功',
].join('\n')

const IMAGE_REQUIREMENT = [
  '本轮用户提供了截图，但派发 prompt 里没有任何图片路径。',
  '',
  '子代理有独立上下文，没有主会话的截图记忆。文字转述会丢失颜色、间距、UI 元素相对',
  '位置、文本换行方式等像素级细节——不附路径等于让子代理盲跑。一手证据（图片）优先于',
  '二手描述（文字转述）。',
  '',
  '把下列路径原样写进 prompt，让子代理用 Read 工具直接读取图片：',
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

function truncate(s, n) {
  return s.length > n ? s.slice(0, n) + '…' : s
}

function guardDisabled() {
  const off = (v) => String(v || '').toLowerCase() === 'off'
  return off(process.env.AGENT_DISPATCH_GUARD) || off(process.env.AGENT_NAMING_GUARD)
}

// ── 第一层：命名与 model 的机械校验（多条一并列出）────────────────────
// 返回 { findings: [], hints: [], modelOk: bool }
function checkNaming(ti) {
  const model = typeof ti.model === 'string' ? ti.model.trim() : ''
  const name = typeof ti.name === 'string' ? ti.name.trim() : ''
  const description = typeof ti.description === 'string' ? ti.description.trim() : ''
  const prompt = typeof ti.prompt === 'string' ? ti.prompt : ''

  const findings = []
  const hints = []
  const modelOk = MODELS.indexOf(model) !== -1

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

  // 2~4. name 必填 + 模型前缀 + 字符集合法
  if (!name) {
    findings.push('缺 name;省略后面板左列只能回落显示裸 subagent_type,同批并发无法分辨各自任务')
    hints.push(`name 填 "${modelOk ? model : '<模型名>'}-<任务语义-kebab-case>"(如 sonnet-review-login-flow)`)
  } else {
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
      findings.push(`name="${name}" 缺模型档次前缀;用户无法从面板判断在飞任务烧的是哪一档模型`)
      hints.push(`name 改成 "${modelOk ? model : '<模型名>'}-${name.replace(/^[^A-Za-z0-9]+/, '') || '<任务语义>'}"`)
    } else if (modelOk && namePrefix !== model) {
      findings.push(`name 前缀 "${namePrefix}-" 与实际 model="${model}" 不一致;面板会显示错误的模型档次`)
      hints.push(`name 前缀改成 "${model}-"`)
    }
  }

  // 5. description 必填 + 方括号模型前缀
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

  return { findings, hints, modelOk }
}

// ── 第二层：派发质量校验（取第一个命中，各给长细则）──────────────────
function checkDispatchQuality(ti, payload) {
  const model = typeof ti.model === 'string' ? ti.model.trim() : ''
  const prompt = typeof ti.prompt === 'string' ? ti.prompt : ''
  const subagentType = typeof ti.subagent_type === 'string' ? ti.subagent_type : ''

  // 逃生舱：prompt 里显式写「档位已确认」即跳过档位检查——正则无法覆盖全部
  // 合法场景（例如只读措辞但确实需要写权限），硬拦死会挡住真实需求。
  const routingConfirmed = /档位已确认/.test(prompt)
  const READ_ONLY_INTENT = /分析|调查|查找|定位|梳理|检索|阅读|审查|评估|理解|探索|统计|列出|盘点/
  const WRITE_INTENT = /修改|新增|删除|重构|实现|修复|写入|创建|编辑|提交|安装|生成|补充|更新|执行|运行|跑一?下|测试|构建|npm |mvn |yarn |git commit/
  // 「最低档别干必须 opus 的活」。haiku 移除后最低档变成 sonnet，这条由原来的
  // 「haiku + 高复杂度」平移而来，但词表**必须同步收窄**，原因有二：
  //   (a) sonnet 是默认档，绝大多数派发都走它，宽词表的误拦面比作用于 haiku 时大得多；
  //   (b) 旧词表里「架构设计」「一致性」与路由表自相矛盾——路由表明写「常规架构设计
  //       → sonnet / 重大架构设计 → opus」，留着就会把常规设计任务拦死。
  // 同理「安全」「注入」这类单字词也换成限定写法：本仓库语境里「注入」几乎都指
  // 依赖注入 / 上下文注入，裸词会天天误拦。
  const OPUS_REQUIRED =
    /安全审计|安全漏洞|安全风险|安全加固|越权|提权|SQL\s*注入|注入漏洞|注入攻击|反序列化|SSRF|并发|竞态|死锁|内存泄漏|资源泄漏|性能瓶颈|性能回退|根因|深度审查|深度调研|数据一致性|协议一致性|不变量|时序问题/

  if (!routingConfirmed) {
    if (subagentType === 'general-purpose' && READ_ONLY_INTENT.test(prompt) && !WRITE_INTENT.test(prompt)) {
      return [
        '这是只读任务（prompt 只含检索/分析类意图，无修改类意图），却用了 `general-purpose`——',
        '它默认携带 Edit / Write / Bash 全权限，存在误改文件的风险。',
        '改用 `Explore`（只读，但仍有 Bash / Grep / Read，足够做检索与分析）。',
        '若这个任务确实需要写权限，在 prompt 里写明「档位已确认：<理由>」再派发。',
        '',
        ROUTING_TABLE,
      ].join('\n')
    }
    if (model === 'sonnet' && OPUS_REQUIRED.test(prompt)) {
      return [
        'prompt 命中必须起 `opus` 的信号（安全审计·漏洞 / 越权·提权 / 并发·竞态·死锁 /',
        '内存·资源泄漏 / 性能瓶颈·回退 / 根因 / 深度审查·调研 / 数据·协议一致性 / 不变量 /',
        '时序问题 等）。这类任务要么需要跨层因果链推理，要么对正确性要求极高，`sonnet`',
        '作为**最低档**不足以胜任（haiku 已从档次表移除，sonnet 就是地板，不能再往下让）。',
        '请升到 `opus`，并同步改 name / description 的模型前缀。',
        '',
        '若判断这其实是常规任务、只是 prompt 里恰好出现了这些词（例如「依赖注入」「上下文',
        '注入」这类与安全无关的用法），在 prompt 里写明「档位已确认：<理由>」再派发。',
        '',
        ROUTING_TABLE,
      ].join('\n')
    }
    // 原「`Plan` + haiku」检查已删除：haiku 不再是合法档次，第一层就会拦下，
    // 这条在第二层永远不可能命中。Plan 最低 sonnet 现由 MODELS 的地板天然保证。
  }

  // prompt 必须索要结构化回执
  if (!/回执|改了哪些文件|阻塞点/.test(prompt)) {
    return RECEIPT_TEMPLATE
  }

  // 本轮有截图则必须附路径。豁免（原纪律明列）：纯后端 5xx / DB / MQ 问题、
  // 纯 spec 矛盾 / 纯 CI 问题、用户明确说不用附图片——这些无法用正则可靠区分，
  // 故给逃生舱：prompt 里写「豁免图片：<理由>」即放行。
  if (!/豁免图片/.test(prompt)) {
    // 字段名两种写法都接受（详见 md-audience-declaration.js 同处理）
    const images = currentTurnImagePaths(payload.transcript_path, payload.prompt_id || payload.promptId)
    if (images.length && !/image-cache|\.png|\.jpg|\.jpeg|\.webp|\.gif/i.test(prompt)) {
      return [IMAGE_REQUIREMENT, ...images.map((p) => `  ${p}`)].join('\n')
    }
  }

  // 含外部写操作则必须传染回读要求
  const EXTERNAL_WRITE_INTENT =
    /curl\s+[^|]*-X\s*(POST|PUT|PATCH|DELETE)|发布|publish|上线|授权|开通|建对象|建实体|提工单|发消息|推送|下发|入库|导入|批量创建|批量更新|INSERT\s+INTO|UPDATE\s+\S+\s+SET|DELETE\s+FROM/i
  if (EXTERNAL_WRITE_INTENT.test(prompt) && !/回读/.test(prompt)) {
    return READBACK_REQUIREMENT
  }

  return null
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

  // 第一层：命名与 model（多条一并列出）
  const { findings, hints, modelOk } = checkNaming(ti)
  if (findings.length) {
    let reason =
      `[L1-BLOCKER] tool=Agent check=agent-dispatch ` +
      `finding="${findings.join(';')}" ` +
      `hint="${hints.join(';')};完整规范见注入纪律 5.4 节;确需临时关闭本门禁用 AGENT_DISPATCH_GUARD=off"`
    // model 本身有问题时附完整路由表，帮助选对档次（命名问题不附，避免长文本淹没重点）
    if (!modelOk) reason += `\n\n${ROUTING_TABLE}`
    deny(reason)
  }

  // 第二层：派发质量（取第一个命中）
  const qualityReason = checkDispatchQuality(ti, payload)
  if (qualityReason) deny(qualityReason)

  process.exit(0)
}

main()
