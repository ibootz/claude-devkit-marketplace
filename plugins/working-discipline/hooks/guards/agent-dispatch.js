// agent-dispatch.js — PreToolUse 门控钩子（matcher: Agent）
//
// 【用途】
// 派发 subagent 时**结构层面**机械可判定的要求在这里处理：model 是否显式给了且在三档内、
// name / description 是否齐备、name 前缀是否与 model 一致、name 是否体现插件专用 agent 的
// 身份（check 8）、keeper 类常驻 agent 是否落在固定的 opus 档（check 9）、keeper 的 name 是否
// 满足「固定前缀 + 4 位小写字母数字短哈希」的形态（check 10）、description 是否
// 超长。判据取自 tool_input 的确定字段，不回读 transcript。
//
// 【判据精度的如实说明（不要再写成"零误判"）】
// 本文件里绝大多数判据是**确定字段比较**：`model` 是否在闭合枚举 MODELS 内、`name` 是否
// 匹配完整锚定正则 NAME_PATTERN、`name` 是否以 `<model>-` / `<model>_` 开头、`description`
// 是否为空、`description` 字符数是否 > DESC_BODY_MAX。这几条同一输入必得同一结论、可人工
// 复核，符合 .claude/rules/hook-restraint.md 里"可以做成 hook"的分级。
//
// **唯一的例外是 PROMPT_LEAK_PREFIXES**：它靠"正文以某个句式开头"近似判断"这是 prompt
// 角色设定句而不是任务摘要"，本质是猜语义，不是零误判。已知覆盖边界：
//   - 不覆盖（假阴性）：角色设定句不在开头（"本次请你扮演审计员…"）、换用未列举的句式
//     （"扮演"/"担任"/"Pretend you are"）、把 prompt 中段而非开头抄进 description。
//   - 可能误伤（假阳性）：任务摘要本身合法地以列表里的词开头。为压低这一面，2026-07-31
//     移除了三个高误杀项 `'#'` / `'【'` / `'Your task'`——前两个会命中任何以 markdown 标题
//     或中文书名号开头的正常摘要，第三个与 `'You are'` 的角色设定语义并不等价（"Your task
//     summary…"是合法摘要）。留下的都是"第二人称+角色设定"这一类明确句式。
// 因此这条判据是**近似**的；若日后再出现真实误杀，正确处置是继续收窄词表或整条降级为
// 注入提醒，而不是加更复杂的正则去猜。
//
// 同日一并移除的还有 prompt-prefix-overlap 检查（原 LEAK_MATCH_MIN = 20：description 正文
// 与 prompt 开头 ≥20 字符逐字重合就判抄袭）。移除原因不是"阈值不合适"，而是**判据前提
// 不成立**：合法的 description 本来就写任务目标，而本仓派发 prompt 的第一段恰是`【目标】`
// 且写的是同一件事，两者开头天然重合——它命中的是"写得规范"而不是"抄了 prompt"。
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
// {"agentType":"Explore","description":"翻译 dimId/nodeId 并核权重","name":"sonnet-dbops-translate-weight-ids",
// "model":"sonnet"}）。AI 构造工具调用时照 schema 的字段表生成，字段表里不存在的字段不会
// 被"想起来"，所以「缺 name」是结构性必然、不是偶发疏忽；用 deny 打回只是把这次必然的
// 返工固化下来。现在改为用 `hookSpecificOutput.updatedInput` 补一个合规名并放行。
//
// 边界（为什么不是"所有命名问题都自动修"）：
//   - **字段缺失**（name 压根没给）→ 自动补。AI 看不见这个字段，罚它没有教育意义。
//   - **字段存在但格式错**（前缀与 model 不符 / 含中文 / description 超长或是角色设定句）→ 仍 deny。
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
// 本文件自身并未 100% 做到这一条：PROMPT_LEAK_PREFIXES 仍是句式近似判定（边界见上文
// 【判据精度的如实说明】），它是留在 deny 里的唯一一条近似判据，词表只减不增。
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

// name 的模型档次前缀与任务语义之间允许的分隔符。**必须同时含 '-' 和 '_'**：
// NAME_PATTERN 本身允许下划线，只认连字符会造成"照文档正则写却被拦"。
const NAME_PREFIX_SEPARATORS = ['-', '_']

// 系统内建 subagent_type：model 覆盖被忽略或命名语义不适用，一律放行。
const EXEMPT_SUBAGENT_TYPES = new Set(['fork', 'statusline-setup', 'output-style-setup'])

// 档位被钉死在 opus 的常驻 agent（check 9，2026-08-03 用户拍板加）。
//
// 【为什么需要这道闸】task-keeper 的两个 keeper 在自己的定义文件里已经写了
// `model: opus`（agents/debug-keeper.md:5 / agents/chore-keeper.md:5），但 `Agent` 工具的
// `model` 参数**优先级高于 agent 定义的 frontmatter**（工具描述原文："Takes precedence
// over the agent definition's model frontmatter"）——主会话显式传 `sonnet` 就把 frontmatter
// 的 opus 顶掉了。而「keeper 固定 opus」这条规则只写在 tk-debug/tk-chore 两个 SKILL.md 正文
// 里，task-keeper 每轮注入的 TRIAGE 文本（hooks/lib/keeper_routing.py:73）压根没提 model；
// 于是主会话没先调那个 skill 时读不到该规则，只读到本插件注入的三档标尺「没 opus 触发信号
// 就留在 sonnet」，遂选 sonnet。实测事故：2026-08-03 会话 8477c246 派
// `{"name":"sonnet-debug-keeper-085","model":"sonnet","subagent_type":"task-keeper:debug-keeper"}`,
// 八条 check 全过（name 前缀与 model 一致、含身份词 keeper），档位静默落在 sonnet。
// keeper 是第一层调度者，triage / 去重 / 合并前对账错一次，整条队列跟着错。
//
// 【判据形态】完整锚定正则匹配 subagent_type 小写化后的串 + model 与 'opus' 的等值比较，
// 二者都是确定字段，同一输入必得同一结论（符合 .claude/rules/hook-restraint.md 的
// "可以做成 hook"分级）。**不是**靠扫 prompt 猜"这活难不难"——3.0.0 删掉的那条档位判据
// 才是那种（见上文【3.0.0 之三】的 (c)），两者性质不同，别混为一谈。
//
// 【覆盖边界（如实记录，勿删）】
//   - **假阳性**：故意降档跑 keeper 的场景会被硬拦，且本 guard 不给逃生舱。真要降档只能
//     `AGENT_DISPATCH_GUARD=off`。用户 2026-08-03 拍板时明确选了 deny 而非 ask，口径是
//     "keeper 降档没有正当理由"；日后若出现真实需求，正确处置是整条降级为 ask，不是加咒语。
//   - **假阴性**：只覆盖名字正好是 `debug-keeper` / `chore-keeper` 的 slug。别的插件自建的
//     keeper-like 常驻 agent（`foo:queue-keeper` / `foo:keeper-v2`）不在表内——这张表是**白
//     名单式枚举**，加新成员要显式改这里，不做"含 keeper 就算"的模糊匹配（那会把无档位要求
//     的第三方 agent 一并拦下）。
const FIXED_OPUS_PATTERN = /(^|:)(debug|chore)-keeper$/
const FIXED_OPUS_MODEL = 'opus'

// 身份词校验（check 8）的通用词黑名单：这些词出现在 subagent_type 的 slug 里不携带
// 可辨识身份，不能拿来当 name 的必含词。例如 `fpf:fpf-agent` 的 'agent'、
// `foo:use` 的 'use'——要求 name 含 'use' 既荒谬又制造误杀。slug 的词被这张表
// 滤空时（如 `foo:use`）整条 check 跳过，fail-open。
const GENERIC_IDENTITY_WORDS = new Set([
  'agent', 'use', 'main', 'default', 'general', 'purpose', 'task', 'claude', 'sub',
])

// 从 subagent_type 抽出「身份词候选集」。只处理**含冒号**的插件专用 agent
// （`task-keeper:debug-keeper` / `caveman:cavecrew-builder`）：它们带常驻语义
// （keeper 会持久接管队列、reviewer 只出审查结论），而面板只渲染 name 不渲染
// subagent_type，name 不带身份词就无法反推派的是谁。内建三档
// （Explore / Plan / general-purpose）返回空数组、不参与校验——它们只是权限差别。
function identityWords(subagentType) {
  const st = String(subagentType || '')
  if (st.indexOf(':') === -1) return []
  const slug = st.slice(st.indexOf(':') + 1)
  return (slug.match(/[A-Za-z0-9]+/g) || [])
    .map((w) => w.toLowerCase())
    .filter((w) => w.length >= 3 && !GENERIC_IDENTITY_WORDS.has(w))
}

// description 正文若以这些句式开头，判定为把 prompt 的角色设定句抄进了 description。
// 这是本文件唯一的近似判据（覆盖边界见文件头【判据精度的如实说明】），词表只减不增。
// 2026-07-31 移除 '#' / '【' / 'Your task' 三项：前两个命中任何以 markdown 标题或中文
// 书名号开头的合法摘要，第三个不等价于角色设定（"Your task summary…"是合法摘要）。
const PROMPT_LEAK_PREFIXES = [
  '你是', '您是', '你將', '你将', '请你', '請你',
  '作为一个', '作為一個', '作为一名', '作為一名',
  'You are', 'you are', 'Act as', 'act as',
]

// description 最大长度（纪律要求 3-5 词摘要；超此长度说明塞了 prompt 内容）。
// **按 description 原始字符串计长**，不减去 [模型名] 前缀——见 checkNaming 第 5 条。
const DESC_BODY_MAX = 60

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

function guardDisabled() {
  const off = (v) => String(v || '').toLowerCase() === 'off'
  return off(process.env.AGENT_DISPATCH_GUARD) || off(process.env.AGENT_NAMING_GUARD)
}

// ── 自动补名 ────────────────────────────────────────────────────────
//
// 语义来源优先级：description 正文里的 ASCII 词 > subagent_type。
// description 常是中文（纪律要求它写中文任务摘要），抽不出 ASCII 词时退回
// subagent_type——中文转写（拼音/翻译）在 hook 里不可靠，宁可给个语义弱但绝不出错的名。

// 从 description 正文抽 ASCII 语义片段：'grep auth refs' → 'grep-auth-refs'
// （description 按新规不带 [模型名] 前缀；若仍带了旧写法,下面 replace 会先 strip 掉）
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

// 把任意字符串压成合法的 name 片段（只留 ASCII 字母数字，用 '-' 连接）。
// **hint 文案里凡是要拼进 name 的用户输入都必须过这个函数**：name 受 NAME_PATTERN 约束、
// 不接受中文与空格，直接把原值回显进"改成 xxx"的建议里，AI 照抄会再撞一次拦截。
function toAsciiKebab(s) {
  return (String(s == null ? '' : s).match(/[A-Za-z0-9]+/g) || [])
    .map((w) => w.toLowerCase())
    .join('-')
}

// 同批并发的多个 subagent 必须拿到不同的 name（同名会让 SendMessage 的 latest-wins
// 寻址把先派的那个弄丢）。用短哈希做区分符：纯函数、无需持久状态。
// **哈希输入必须含 description**：本仓常见的并发分片是"同一段 prompt + 不同中文
// description"（如"判定 spec 01-05"/"判定 spec 06-10"），description 又多为中文、
// 抽不出 ASCII 词，deriveSlug 会一齐回落到 subagent_type——若哈希只吃 prompt + slug，
// 这批分片会拿到**完全相同**的自动名，SendMessage 按名寻址直接失效。
function shortHash(s) {
  return crypto.createHash('sha1').update(s).digest('hex').slice(0, 4)
}

// keeper 类常驻 agent 的 name 固定前缀（check 10 用）。`stLower` 传小写化后的
// subagent_type，命中 FIXED_OPUS_PATTERN 时才有意义。前缀之后必须再接 4 位小写
// 字母数字短哈希——2026-08-04 用户拍板：同一会话里前一个 keeper 实例结束后，
// 若下一个又派成逐字相同的固定名，`SendMessage` 的 latest-wins 寻址会让唤醒方
// 分不清召唤的是哪一个实例；强制带哈希后缀，把"名字不可预测"这个事实摆出来，
// 逼唤醒方必须去读登记文件（task-keeper 的 PreToolUse(Agent) hook 会把实际用的
// name 写进 `.keeper/<交付id>/.keeper-instance.json`），而不是心存"记得住固定名"
// 的幻觉。
function keeperNamePrefix(stLower) {
  return `${FIXED_OPUS_MODEL}-${stLower.split(':').pop()}-`
}

// keeper name 的完整锚定正则：固定前缀 + 恰好 4 位小写字母或数字，无更多无更少。
function keeperNamePattern(stLower) {
  return new RegExp('^' + keeperNamePrefix(stLower) + '[0-9a-z]{4}$')
}

function autoName(ti, model) {
  // keeper 类常驻 agent 的 name 被 check 10 要求「固定前缀 + 4 位短哈希」，自动补名
  // 直接按这个形态生成，复用与非 keeper 分支相同的 shortHash 输入口径
  // （prompt + description + slug），确保自己补的名自己能通过 check 10。
  const stLowerForKeeper = String(ti.subagent_type || '').toLowerCase()
  if (FIXED_OPUS_PATTERN.test(stLowerForKeeper)) {
    const keeperHash = shortHash(
      String(ti.prompt || '') + '|' + String(ti.description || '') + '|' + stLowerForKeeper
    )
    return keeperNamePrefix(stLowerForKeeper) + keeperHash
  }

  let slug = deriveSlug(ti)
  // check 8 要求 name 体现插件专用 agent 的身份；自动补名同样要满足，否则会补出一个
  // guard 自己都不放行的形态（description 全是 ASCII 时 deriveSlug 压根不看 subagent_type）。
  const idWords = identityWords(ti.subagent_type)
  if (idWords.length && !idWords.some((w) => slug.indexOf(w) !== -1)) {
    slug = `${idWords[0]}-${slug}`
  }
  const hash = shortHash(
    String(ti.prompt || '') + '|' + String(ti.description || '') + '|' + slug
  )
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
    // 前缀分隔符 '-' 与 '_' 等价：NAME_PATTERN 允许下划线，只认连字符会把
    // "sonnet_review_login" 这类照正则写出来的合法名误拦。
    const startsWithPrefix = (m) => NAME_PREFIX_SEPARATORS.some((sep) => name.startsWith(m + sep))
    const namePrefix = MODELS.find(startsWithPrefix)
    if (startsWithPrefix('haiku')) {
      // 单独识别旧档前缀，避免回落到「缺前缀」分支后给出 "sonnet-haiku-xxx" 这种
      // 把旧档次名留在任务语义里的错误改法。
      findings.push(`name="${name}" 用了已移除的 haiku 档前缀;本插件无 haiku 档,最低档是 sonnet`)
      hints.push(`name 改成 "${modelOk ? model : 'sonnet'}-${toAsciiKebab(name.slice(6)) || '<任务语义-kebab>'}"`)
    } else if (!namePrefix) {
      findings.push(`name="${name}" 缺模型档次前缀;用户无法从在飞 agent 面板判断这批任务烧的是哪一档模型`)
      hints.push(`name 改成 "${modelOk ? model : '<模型名>'}-${toAsciiKebab(name) || '<任务语义-kebab>'}"（任务语义只能用 ASCII 字母数字与 - _）`)
    } else if (modelOk && namePrefix !== model) {
      // 回显实际用的分隔符（可能是 '_'），避免 finding 里写 "sonnet-" 而 name 里其实是
      // "sonnet_"，让人以为 guard 看错了字段。
      const usedPrefix = name.slice(0, namePrefix.length + 1)
      findings.push(`name 前缀 "${usedPrefix}" 与实际 model="${model}" 不一致;面板会显示错误的模型档次`)
      hints.push(`name 前缀改成 "${model}${usedPrefix.slice(-1)}"`)
    }
  }

  // 8. name 必须体现插件专用 agent 的身份（2026-08-03 新增）
  //    起因：在飞面板只渲染 name、**不渲染 subagent_type**，于是
  //    name="sonnet-dbg-open-audit" + subagent_type="task-keeper:debug-keeper" 这组派发
  //    在面板上完全看不出派的是 keeper，用户找不到自己刚被托管的那条队列。
  //
  //    判据是**纯子串包含**、不猜语义：subagent_type 含 ':' → 取冒号后 slug → 拆 ASCII 词
  //    → 滤掉通用词 → 要求 name 小写化后包含其中**任意一个**。
  //
  //    覆盖边界（如实记录，勿删）：
  //    - **假阴性成本为零**：`sonnet-x-keeper` 这类随便塞词即可过闸，且只查"任一词"，
  //      分不出 debug-keeper 与 chore-keeper。这条判据只防**遗忘**，不防绕过——而遗忘
  //      正是它唯一的失败模式（没人有动机故意隐藏 subagent 身份）。
  //    - **只覆盖含冒号的插件专用 agent**。内建 Explore / Plan / general-purpose 不校验：
  //      它们是权限差别不是常驻身份，强制带词只会让每个名字多背一个无信息的前缀。
  //    - slug 的词全落通用词黑名单时整条跳过（`foo:use`），fail-open。
  if (!nameMissing) {
    const idWords = identityWords(ti.subagent_type)
    const lowerName = name.toLowerCase()
    if (idWords.length && !idWords.some((w) => lowerName.indexOf(w) !== -1)) {
      findings.push(
        `name="${name}" 不含 subagent_type="${ti.subagent_type}" 的身份词(${idWords.join('/')});` +
          `在飞面板只渲染 name 不渲染 subagent_type,用户无法从面板判断这是哪种专用 agent`
      )
      hints.push(
        `name 改成 "${modelOk ? model : '<模型名>'}-${idWords.join('-')}-<任务语义-kebab>"` +
          `(身份词 ${idWords.join(' 或 ')} 任含其一即可,位置不限)`
      )
    }
  }

  // 9. keeper 类常驻 agent 的档位钉死在 opus（2026-08-03 新增，判据与边界见 FIXED_OPUS_PATTERN）
  //    与 check 1 并列而非合并：check 1 管"三档枚举内"，这条管"这个 subagent_type 只允许一档"。
  //    model 缺失时两条会同时报，hint 各给一半，AI 一次改全。
  const stLower = String(ti.subagent_type || '').toLowerCase()
  if (FIXED_OPUS_PATTERN.test(stLower) && model !== FIXED_OPUS_MODEL) {
    findings.push(
      `subagent_type="${ti.subagent_type}" 是固定 ${FIXED_OPUS_MODEL} 档的常驻 keeper,` +
        `本次 model=${model ? `"${model}"` : '(缺失)'};` +
        `agent 定义 frontmatter 的 model:${FIXED_OPUS_MODEL} 会被这里显式传的 model 顶掉` +
        `(Agent 工具的 model 参数优先级高于 frontmatter),所以档位只能在这里给对`
    )
    // 建议名：剥掉 name 已有的模型前缀，换成 opus-。name 缺失时给出带身份词的完整模板。
    const strippedName = name.replace(/^(sonnet|opus|fable|haiku)[-_]/i, '')
    const suggestSlug = toAsciiKebab(strippedName) || `${stLower.split(':').pop()}-<任务语义-kebab>`
    hints.push(
      `model 改 "${FIXED_OPUS_MODEL}",name 前缀同改 "${FIXED_OPUS_MODEL}-"(即 "${FIXED_OPUS_MODEL}-${suggestSlug}");` +
        `keeper 是第一层调度者,triage/去重/对账错一次整条队列跟着错,故不按任务看起来难不难下调,` +
        `也不受三档标尺那句"没 ${FIXED_OPUS_MODEL} 触发信号就留在 sonnet"约束`
    )
  }

  // 10. keeper 类常驻 agent 的 name 必须带 4 位短哈希后缀（2026-08-04 用户拍板改）
  //     起因是一次真实事故（session 8477c246，2026-08-03）：keeper 被派成
  //     `sonnet-debug-keeper-085`；38 分钟后主会话想唤醒它，按 agent 定义里写的固定名
  //     `debug-keeper` 寻址，`SendMessage` 返回
  //     "No agent named 'debug-keeper' is reachable."，随后它直接又派了**第二个**
  //     debug-keeper 实例。两个实例先后持有同一 `.keeper/<交付id>/debug/` 的独占写权限，
  //     单一写者模式失效、队列一致性无保障。
  //
  //     旧判据（3.14.0）曾把 name 钉死成逐字相等的固定三段名（`opus-debug-keeper`），
  //     但这条本身埋了新的坑：同一会话内前一个 keeper 实例结束后，若后来者又派成逐字
  //     相同的固定名，`SendMessage` 的 latest-wins 寻址规则会让"占名"这件事本身变得
  //     不可靠——旧实例的名字被新实例顶掉，唤醒方分不清这次唤到的是哪一个。
  //     2026-08-04 改法：name 必须再带 4 位小写字母数字短哈希，逼「名字不可预测」这个
  //     事实被强制暴露出来，让唤醒方**必须**先去读登记文件才能拿到当前有效的 name，
  //     机制不会退化成"记得住就不读、记不住才读"的可选项。登记文件由 task-keeper 插件
  //     的 `PreToolUse(Agent)` hook 写：命中 keeper 类 subagent_type 时把本次实际用的
  //     name 落进 `.keeper/<交付id>/.keeper-instance.json`
  //     （形如 `{"debug":{"name":"opus-debug-keeper-4bb6","ts":"<ISO8601>"}}`），
  //     主会话唤醒前先读它，读不到才首次派发。
  //
  //     判据形态：完整锚定正则 `^opus-<slug>-[0-9a-z]{4}$`（`keeperNamePattern()`），
  //     `<slug>` 取自 subagent_type 冒号后的部分（`debug-keeper` / `chore-keeper`）。
  //     前缀部分仍是确定字段比较，只有后 4 位是「形态匹配」而非「值校验」——
  //     它与 check 8（name 须含身份词）不是一回事：check 8 只防遗忘、随便塞词即可过闸；
  //     这条同样不校验后 4 位是不是真的取自哈希，只校验形态（4 个小写字母或数字）。
  //
  //     覆盖边界（如实记录，勿删）：
  //     - **假阴性**：AI 可以随便编 4 个字符交上来，而不是真的调用 shortHash——判据
  //       只能校验形态，校验不了随机性。这是可以接受的：本 guard 真正要防的是「同名
  //       撞车导致 SendMessage 寻址混乱」，任意 4 位后缀（哪怕是编的）都能防住这一点；
  //       防不住的是「AI 故意每次编同一个后缀」，但那属于蓄意绕过纪律，不是本 guard
  //       该拦的范畴（本仓 hook 只对"忘记"负责，不对"故意"负责）。
  //     - **假阳性**：合法的 4 位小写字母数字后缀不会被拒绝，无已知误杀面。
  //     - name 缺失时不在这里报：`autoName` 已直接补成同一形态的名字（见 keeper 分支，
  //       复用 shortHash，输出的十六进制字符天然落在 [0-9a-z] 内）。
  //     - 与 check 9 的叠加：model 不是 opus 时两条会同时报，期望名恒以 `opus-` 开头
  //       （档位本身也被钉死），两条 hint 方向一致、AI 一次改全。
  if (!nameMissing && FIXED_OPUS_PATTERN.test(stLower)) {
    const pattern = keeperNamePattern(stLower)
    if (!pattern.test(name)) {
      const prefix = keeperNamePrefix(stLower)
      findings.push(
        `subagent_type="${ti.subagent_type}" 是常驻 keeper,name 必须形如 "${prefix}xxxx"` +
          `(固定前缀 + 恰好 4 位小写字母数字短哈希),本次 name="${name}" 不满足;` +
          `强制带哈希后缀是为了防同一会话内前一个 keeper 实例关闭后新派的同名撞车` +
          `(SendMessage 的 name 寻址是 latest wins),名字因此不可预测,` +
          `唤醒前必须先读 .keeper/<交付id>/.keeper-instance.json 里登记的实际 name`
      )
      hints.push(
        `name 改成 "${prefix}4bb6" 这种形态(如 "${prefix}4bb6",后 4 位随便挑 4 个小写字母` +
          `或数字即可,不要求真的是哈希值,只要求形态和大概率唯一);` +
          `keeper 是第一层调度者,它的 name 现在既不固定也不可预测,` +
          `唤醒前先读 .keeper/<交付id>/.keeper-instance.json 拿当前实际 name,读不到才首次派发`
      )
    }
  }

  // 5. description 必填且有正文（description 是 schema 里的必填字段，缺失基本由工具层
  //    拦掉，这里仍留判定以防 harness 放宽）。**不再要求 [模型名] 前缀**：name 的模型
  //    前缀已是强制校验（见上 check 3~4），在飞面板 name 与 description 并排显示，
  //    模型档次由 name 一处表达即可，description 再带 [模型名] 前缀是冗余（每行模型名
  //    出现两次）。AI 仍带了前缀（旧习惯）也不拦——这是**软放宽**口径：strip 掉再做
  //    正文检测，避免「[sonnet] xxx」整体被当正文触发误判。模型档次一致性由 name 侧独担。
  //
  //    **strip 只服务于正文检测，不减免字符预算**：DESC_BODY_MAX 一律按 description 的
  //    原始长度比较（见下 check 9）。否则「[sonnet] 」这类前缀等于白送 9 个字符额度，
  //    带前缀的 description 能比不带前缀的多写一截，前缀反而变成收益。
  //
  //    `[haiku]` 是例外，不 strip 而是报错：本插件已无 haiku 档（MODELS 只有
  //    sonnet/opus/fable），静默吞掉会让人以为 haiku 仍合法。注意与另两处 haiku 判定
  //    区分：`model:"haiku"`（上 check 1）与 name 的 `haiku-`/`haiku_` 前缀（上 check 3~4）
  //    本来就各有拦截，这里补的是 description 里的 `[haiku]`。
  let descBody = ''
  if (!description) {
    findings.push('缺 description')
    hints.push('description 填 "<3-5 词任务摘要>"（模型档次由 name 前缀体现,description 不带 [模型名] 前缀）')
  } else {
    const modelTag = description.match(/^\[(sonnet|opus|fable|haiku)\]\s*/)
    descBody = modelTag ? description.slice(modelTag[0].length).trim() : description
    if (modelTag && modelTag[1] === 'haiku') {
      findings.push('description 前缀 "[haiku]" 用了已移除的档次;本插件无 haiku 档,最低档是 sonnet')
      hints.push('删掉 description 的 [haiku] 前缀(3.4.0 起 description 本就不要求 [模型名] 前缀,档次由 name 前缀表达),并确认 model 与 name 前缀落在 sonnet')
    }
    if (!descBody) {
      findings.push('description 没有任务摘要正文')
      hints.push('description 填 3-5 词任务摘要（不带 [模型名] 前缀）')
    }
  }

  // 6. 角色设定句检测（近似判据，覆盖边界见文件头）。原先并列的
  //    prompt-prefix-overlap 检查（description 正文与 prompt 开头 ≥20 字符逐字重合）
  //    已于 2026-07-31 整条移除：合法 description 写任务目标、prompt 的【目标】段写
  //    同一件事，两者开头天然重合，它命中的是"写得规范"而非"抄了 prompt"。
  if (descBody) {
    const leakPrefix = PROMPT_LEAK_PREFIXES.find((p) => descBody.startsWith(p))
    if (leakPrefix) {
      findings.push(`description 正文以 "${leakPrefix}" 开头,是 prompt 角色设定/元指令句式而非任务摘要;提示词会暴露到在飞 agent 面板`)
      hints.push('description 只写"这个子代理在做什么",prompt 与 description 禁止共用同一段文字')
    }
  }

  // 7. 字符预算：按 description **原始长度**比较，不减去 [模型名] 前缀（前缀是容错接受
  //    的旧写法，不该换来更多字符额度）。
  if (description && description.length > DESC_BODY_MAX) {
    findings.push(`description ${description.length} 字符超过 ${DESC_BODY_MAX};纪律要求 3-5 词摘要,超长说明塞了 prompt 内容`)
    hints.push(`description 压到 ${DESC_BODY_MAX} 字符以内(带 [模型名] 前缀的话前缀也算在内,直接删掉前缀最省)`)
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
    // keeper 类补的是 check 10 要求的那种形态（固定前缀 + 4 位短哈希），文案要讲清楚
    // 这个名字不可预测、唤醒前要先读登记文件——否则又是一处"效力与描述各自漂移"
    // （见 .claude/rules/hook-restraint.md 实证 5）。
    const isFixedKeeper = FIXED_OPUS_PATTERN.test(String(ti.subagent_type || '').toLowerCase())
    allowWithName(
      ti,
      generated,
      isFixedKeeper
        ? `[agent-dispatch] 本次派发没给 name（Agent 工具的 JSON Schema 未声明该字段，` +
            `但运行时接受并会存进 subagent 元数据）。这是常驻 keeper，name 必须形如` +
            ` "opus-<debug|chore>-keeper-<4位小写字母数字短哈希>"，已补为 "${generated}" 并放行——` +
            `后 4 位短哈希是为了防同一会话内前一个 keeper 实例关闭后新派的同名撞车` +
            `（SendMessage 的 name 寻址是 latest wins），这个名字因此不可预测。` +
            `唤醒它前先读 .keeper/<交付id>/.keeper-instance.json 里登记的实际 name，` +
            `读不到才首次派发。下次派发请自己写上这种形态的 name。`
        : `[agent-dispatch] 本次派发没给 name（Agent 工具的 JSON Schema 未声明该字段，` +
            `但运行时接受并会存进 subagent 元数据），已自动补为 "${generated}" 并放行。` +
            `自动名只有 description/subagent_type 里抽出的弱语义 + prompt·description 的短哈希，` +
            `在飞面板上看不出任务差异——` +
            `下次派发请自己给 "${model}-<任务语义-kebab>"（如 ${model}-review-login-flow），` +
            `同批并发时把分片依据写进名字。`
    )
  }

  process.exit(0)
}

main()
