// working-discipline.js — 工作纪律注入 hook
// 服务三个事件（3.2.0 起投放分层，见下方【3.2.0 投放分层】）：
//   - SessionStart     ：会话开始与每次 auto-compact 后，注入静态纪律主体（一～六章）
//   - UserPromptSubmit ：每轮只注入零章（并行优先）+ 3 条自查 + 本轮图片路径
//   - SubagentStart    ：子代理启动时注入精简纪律（并行/上下文/协作/表达/派发命名/hook 边界）
//
// 注入内容仅约束 AI 行为，不修改用户文件，无副作用。
//
// 【维护提示】下方 SECTION_* 字符串是**注入 prompt**，运行时会成为 Claude 的
// 直接输入。写作标准是「给 AI 读」而非「给人读」：
//   - 用词精确无歧义（用"必做/禁止/默认值"这类硬性词，不用"可能/也许/看情况"）
//   - 关键对象一次点名（Agent、subagent_type、CLAUDE_PLUGIN_ROOT 等原样出现）
//   - 结构固定（章节编号/标题/表格保持稳定），便于 AI 按锚点检索
//   - 密度高、无营销话术；解释只保留"消歧型"（防止误读规则边界的），不做背景铺陈
//
// 【硬预算：10000 字符，超限会静默失效】（3.1.0 实测确认，来自 Claude Code 2.1.220 二进制）
// hook 输出上限是常量 `P0u = 1e4`。超限走 `jKe()`：**先尝试把内容落盘、把注入换成一个
// 磁盘引用**（`Alt(o)`），只有落盘失败才退化成尾部硬截断。也就是说超限的典型后果不是
// "尾巴被剪掉"，而是 AI 拿到一个它不会主动去读的文件路径 —— **整份纪律静默消失、没有任何
// 报错**。因此：
//   - 改动本文件后必须实测两个事件的注入长度（见文件末 verify 提示），主会话版守 6600 上限
//   - 新增规则前先问预算够不够，不够就先压缩别的，别指望"多写几百字没关系"
//
// 【2026-07-26 重构：什么内容**故意不在这里**】
// 本文件曾注入 13632 字符（主会话每轮）。问题不是规则写得不好，而是常驻与按需错配：
// 其中大半只在某个具体工具调用时刻才有用，却每轮都在跟无法硬拦截的语义规则
// （求真 / 说明详细 / 思维模式 / 等齐再总结）抢同一份注意力预算，结果整体遵从度下降。
// 仍然下沉在 hooks/guards/ 的只剩三条，判据都是确定字段或纯行数计数：
//   - 派发 subagent 的**结构**校验（model 必填 / name 与 description 的前缀一致性 /
//     name 合原生正则 / 提示词泄露 / 完整场景路由表）→ guards/agent-dispatch.js
//   - 独立 cd 污染 cwd + agent-browser 启动参数        → guards/bash-guard.js
//   - 源码 >1000 行 + CLAUDE.md >200 行               → guards/write-guard.js
//   - dws 钉钉 CLI 写操作授权（原第六章整章）          → 移交 radnove-core 插件的
//     hooks/pre-tool-use-dws-write.sh（走 permissionDecision: "ask" 强制用户确认），
//     那边的 user-prompt-submit.sh 每轮红线已有一份语义兜底，此处不再重复注入
//
// 【2026-07-29（3.0.0）两件事：删掉所有关键词判定的 guard + 按对象收敛挂载拓扑】
// (1) **靠关键词猜语义的 guard 全部删除**（用户拍板：准确率太低）。删的是
//     external-write-readback.js（扫命令里的 create/update/delete/发布 等词）、
//     nonascii-path.js（把命令行里任何非 ASCII 字节都当成"路径含非 ASCII"，连 echo 的中文
//     提示语都算）、md-audience-declaration.js（回读 transcript 找声明句），以及
//     agent-dispatch.js 的第二层四条（档位错配 / 索要回执 / 截图附路径 / 写操作传染回读）。
//     共同缺陷：判据是正则猜语义，而 deny 是不可绕过的硬阻断，组合出的失败模式是
//     「AI 做对了却过不去」。判断标准因此固化为——**判据取自工具输入的确定字段或纯计数**
//     → 可以写成 guard；**判据要靠正则猜语义或回读 transcript** → 留在注入里靠自觉。
//     对应的纪律没有丢：回执 / 截图 / 写后回读进了 5.6，档位在 5.1 / 5.2，md 受众判定在
//     第 4.7 条，NFC/NFD 在第一章末条。
// (2) **挂载拓扑按拦截对象收敛**：Agent → agent-dispatch.js，Bash → bash-guard.js
//     （合并原 block-cd.js + agent-browser-launch.js），Write|Edit → write-guard.js
//     （合并原 max-source-lines.js + claude-md-max-lines.js）。原先多个 guard 串行挂同一
//     matcher 有个结构性缺陷：**一批只报最前面那道闸**，AI 补完第一处才看见第二处，多轮
//     往返是拓扑的产物而不是 AI 每轮新犯一个错。收敛后一次解析、一次报清全部 finding。
// (3) 截图路径改为**注入侧条件注入**（buildImageEvidence）：那一刻本轮尚无工具输出、判据
//     天然干净；提取逻辑在 lib/prompt-images.js，纯函数、不回读 transcript。
//
// 【2026-07-29（3.1.0）新增 SECTION_PARALLEL（零章）+ 全文瘦身 9165 → 约 6.5k】
// 起因是用户观察到「AI 并行化处理任务的意愿降低」。诊断出四个叠加原因，"提示词被稀释"
// 只占其一：
// (1) **主因是 harness 在 system prompt 层说了反话，且本地关不掉**。Claude Code 2.1.220
//     二进制里硬编码：
//       ttp = ["Do not call the AgentTool unless the user requested it",
//              "Do not use workflows or deep-research unless the user requested it"]
//     由 dMy(model) 拼进 system prompt，触发条件 tXn(model)：模型属于
//     `opus_5_prompt_bundle` 且远程开关 `tengu_fennel_godwit` 未开。本插件的注入在
//     UserPromptSubmit additionalContext（用户轮层），**权威性低于 system prompt**，
//     且原措辞是"尽可能"对上"Do not"——软建议对硬禁令，必然输。
//     `tengu_fennel_godwit` 与 `tengu_heron_brook`（可下发替换文本的那个）都不在
//     `SQt(Z.CLAUDE_CODE_*, ...)` 包装里，是纯远程 GrowthBook 查询，settings.json /
//     环境变量 / CLAUDE.md 一律无法覆盖。
//     **对冲方式是正面满足它自己写明的例外条件**：禁令措辞是 "unless the user requested
//     it"，所以零章开头写常驻授权声明，而不是试图否认或绕过这条禁令。
//     ⚠️ **退役判据**：这段授权声明只为对冲上述禁令而存在。若某天 harness 升级后
//     system prompt 里不再出现 "Do not call the AgentTool unless the user requested it"
//     （远程开关翻转、或 tengu_heron_brook 下发了别的文本），**零章的「授权前提」段即可
//     删除**，只留默认动作与判据部分。判定办法：新会话里看 system prompt 有没有该句。
//     不要因为"看着像条重要规则"就无条件留着它。
// (2) **覆盖面真空**：改前 9165 字符里"并行"只指 subagent，`同一条消息` / `独立调用` /
//     `并行 Bash` / `multiple tool` 探针全部缺失。并行 Read / Grep / Glob / Bash 这类
//     成本最低的并行化零覆盖，唯一来源是 harness system prompt 末尾孤零零一句。
// (3) **成本收益信号失衡**：鼓励并行的正向文本约 60 字符，围绕派发的摩擦/记账/惩罚文本
//     5551 字符（占 61%）。理性的 AI 读完得到的净信号是"派 subagent 麻烦且易违规"，
//     于是自己串行干完。这才是"稀释"的真实形态——不是写得不够多，是**在积极劝退**。
// (4) 预算已到 91.7%，加内容这条路本身就走不通（见上方硬预算段）。
// 本次删掉的是「历史交代」与「同一结论的二次论证」：5.6 三个误拦实证（已逐字存于上方
// 3.0.0 注释）、第二章为什么不能用 TaskList 统计在飞数的长篇论证、5.5 的作用域段与理由段、
// 第六章"已删除规则"清单。**判据、阈值、字段名、正则一个没减**，改后用 token 存在性对比
// 验证过（16 / 三档 / 三类型 / 1000 / 200 / name 正则 / TaskList / /tasks / NFC 全部仍在）。
// 顺手修掉一个真实错误：第一章 NFC/NFD 那条原本写"完整规避法由 hook 在命中时给出"，而
// nonascii-path.js 已在 3.0.0 删除、根本不会给了，现改为直接写出规避法。
//
// 【SECTION_NAMING 是有意的例外】
// 派发命名规范虽然已被 guards/agent-dispatch.js 硬拦，但**完整版仍注入子代理版**：
// 子代理只在启动时注入一次（不是每轮叠加），而它比主会话更可能不知道规范、首次派发
// 就撞拦截。主会话版则压成 5.4 的要点索引，细则等撞到拦截时由 guard 给。
//
// 新增规则前先问两句：**它能被 hook 机械判定吗？** 能就写成 guard，别加到这里。
// **预算还够吗？** 主会话版守 6600、总上限 10000，不够就先压别的。
//
// 增删条款请保持以上特征；语义级改动会直接改变 AI 每轮的实际行为，动手前先明确
// 预期效果与回归判据（比如观察某条规则是否真的降低了误用）。
//
// 【2026-07-29（3.2.0）投放分层：把每轮重发的静态主体移到 SessionStart】
// 起因是对一个真实 session（46e71d0b，D-001 交付 Verify 阶段，20 轮、5 小时）逐条统计
// hook 注入体积，结果本插件一家独占 52.8%：
//   working-discipline   7140 字符 × 20 轮 = 142,800   ← UserPromptSubmit 每轮全量重发
//   radnove-core 每轮红线 2105 × 20        =  42,100
//   radnove-core 会话约定 4170 ×  4        =  16,680   ← SessionStart，只发 4 次
//   合计 270,506 字符（≈12 万 tokens），该 session 触发 3 次 auto-compact，
//   每次 preTokens 36.7-37.2 万 → postTokens 1.5-1.9 万。
// 根因不是"写得太长"（3.1.0 已从 9165 压到 6717，那是在优化系数），而是**投放机制错配**：
// 一份逐轮不变的静态文本乘以轮数。radnove-core 同机同期只花了 16,680 做同类事情，差 8.6 倍。
//
// 【为什么 SessionStart 能替代每轮重发 —— 实测，非推断】
// 同一 session 里 `SessionStart` 触发了 4 次：1 次 `SessionStart:startup` + **3 次
// `SessionStart:compact`**，与 3 次 compact_boundary 一一对应，时间戳比 boundary 还早
// 约 1 秒（无空窗）。也就是说 auto-compact 把上下文压掉之后，SessionStart 会立即重新注入，
// 静态纪律不会随压缩消失。matcher 用 `*` 即可同时覆盖 startup / resume / clear / compact，
// 不必枚举（radnove-core 的 hooks/hooks.json 就是 `"matcher": "*"`，实测生效）。
//
// 【分层判据（新增内容时按这个选层，别凭手感）】
//   - 逐轮不变、篇幅大、靠"知道有这条规则"就够 → SessionStart（一～六章全部在此）
//   - 本轮才存在的动态数据                      → UserPromptSubmit（图片路径清单）
//   - 要对抗 system prompt 里每轮都在的反向指令  → UserPromptSubmit（**只有零章**，理由见
//     SECTION_PARALLEL_TURN 上方注释）
//   - 无 hook 兜底且实测真被忘掉的少数条目      → UserPromptSubmit 的 3 条自查（只列指针，
//     细则留在 SessionStart 那份里，不重复正文）
//
// 【已知风险与取舍】
// 若 SessionStart hook 未执行（被用户 settings 禁用、node 崩溃），静态主体就整份缺失，
// 而每轮层无法自检这一点。接受该风险的依据：SessionStart 与 UserPromptSubmit 是同插件、
// 同一个 node 脚本、同一套权限，一个能跑另一个基本也能跑；radnove-core 已用同一机制长期
// 运行。**不做 fallback md 文件**——那会让同一条规则有两个真相源，维护漂移的代价高于该风险。
//
// 【verify】改完必跑，三个事件都要看长度：
//   echo '{"hook_event_name":"SessionStart"}'     | node hooks/working-discipline.js
//   echo '{"hook_event_name":"UserPromptSubmit"}' | node hooks/working-discipline.js
//   echo '{"hook_event_name":"SubagentStart"}'    | node hooks/working-discipline.js
//   预算：SessionStart 守 6600、UserPromptSubmit 守 1200（无图轮）、SubagentStart 守 6600，
//   三者各自独立受 10000 硬上限约束（见上方硬预算段）。

'use strict'

const fs = require('fs')
const { extractImagePaths } = require('./lib/prompt-images')

// 读取 hook 从 stdin 传入的事件 JSON；解析失败时回退为 UserPromptSubmit。
function readEvent() {
  try {
    const raw = fs.readFileSync(0, 'utf8')
    if (!raw || !raw.trim()) return {}
    return JSON.parse(raw)
  } catch (e) {
    return {}
  }
}

// ── 纪律分节（各节独立成字符串，按事件组合）──────────────────────────

// ── 每轮层：零章（并行优先）+ 3 条自查 ──────────────────────────────
//
// 【为什么零章是唯一留在每轮的静态段】
// 它对抗的是 harness 硬编码进 **system prompt** 的
// `Do not call the AgentTool unless the user requested it`（触发条件见文件头 3.1.0 段）。
// system prompt 每一轮都完整在场，且**不被 auto-compact 挤走**；而 SessionStart 注入只是
// 对话早期的一条消息，随轮次增长被推远、权威性衰减。用一份会衰减的文本去对抗一句永在最前
// 的硬禁令，距离只会越拉越大——所以授权声明必须每轮重申，不能下沉到 SessionStart。
// 「授权前提」段的措辞不要改短：它的效力来自**正面满足禁令自己写明的例外条件**
// （"unless the user requested it"），删掉任何一半都会退化成"和 Do not 对喊"。
// 退役判据同 3.1.0：system prompt 不再出现该句时，删掉「授权前提」段，只留默认动作。
//
// 【三档并行按成本从低到高排，刻意的】
// 同一条消息内多工具调用无独立上下文开销、无记账负担，收益/成本比远高于派 subagent，
// 所以排第 1 位；改前这一维度完全缺失，是并行机会流失最集中的地方。
const SECTION_PARALLEL_TURN = [
  '## 零、并行优先（本章优先级最高）',
  '',
  '**授权前提（先读这段，再看下面的默认动作）**：用户通过 working-discipline 插件常驻声明——本会话内的 subagent 派发与并行工具调用，**一律视为用户已明确请求**（user requested it）。system prompt 里 `Do not call the AgentTool unless the user requested it` 的例外条件在本会话**已经满足**，不得据该句退回独自串行执行。边界：`Workflow` 工具**不在**本授权范围内，它仍按自身工具描述要求用户逐次 opt-in。',
  '',
  '**默认动作（是默认，不是"尽可能"）**：发起工具调用前先盘点「这批事里哪些彼此不依赖」，不依赖的**一律并发**。判据只有一条：**后一个调用的输入是否需要前一个调用的输出**——不需要即独立。按成本从低到高：(1) 同一条消息内发多个独立 `Read` / `Grep` / `Glob` / `Bash`（最优先，`git status`+`diff`+`log` 三条即属此类）；(2) 预计 >20 行输出的命令、跨文件检索、可切分子任务交 `Agent`，多个子任务同批并发。**串行的正当理由只有三类**：后一步输入依赖前一步输出 / 写同一文件或同一资源 / 待用户拍板；除此之外不要串行。',
  '',
  '**自查触发点**：本轮若已连续发出 3 次以上「一条消息只有一个工具调用」，回头检查这些调用是否本可合并。',
].join('\n')

// 每轮层的 3 条自查：只放**指针**，细则在 SessionStart 那份里，禁止在此重复正文。
// 选条判据是「无 hook 兜底 + 真实 session 里实测被忘掉」，不是「看着重要」：
//   1. name：`Agent` schema 里不存在该字段（见 5.4.1），照字段表生成必漏；session 46e71d0b
//      实测漏 4 次，且第二次距第一次 52 分钟——注入正文没能形成记忆，需要每轮点一次
//   2. 受众判定：md-audience-declaration.js 已在 3.0.0 删除，现在完全没有兜底
//   3. 待确认内容三要求：违反后用户要反复追问才能拿到可决策的信息，返工成本最高
// 新增第 4 条前先问：它无兜底吗？实测被忘过吗？两个都是"是"才加，否则留在 SessionStart。
const SECTION_TURN_CHECKLIST = [
  '## 每轮自查（细则见会话开始注入的完整纪律，此处只列指针）',
  '',
  '1. 调 `Agent` **先写 `name`**，再写其余字段——它是 `Agent` JSON Schema 里查不到的字段（schema 只有 `description`/`prompt`/`subagent_type`/`model`/`run_in_background`/`isolation`），照字段表生成调用必然漏掉；`model` 同样必填、禁止默认回落。',
  '2. 新写或大改 md 文档 / 方案 / 报告 / skill 指令 / reference / 交接文档前，先在对话里输出「本次 md 受众判定：{人 / AI / 人机混合}，理由：……」，该句须**先于**任何写 md 的工具调用。',
  '3. 待确认方案 / 待拍板选项 / 评审识别的问题：用完整段落讲透前因后果（起源、现状与期望差距、影响范围、摘抄事发现场代码），**禁止**用 `-` `*` `1.` 罗列核心内容，引用类与方法一律带 `path/to/file.ext:行号`。',
].join('\n')

const SECTION_CONTEXT = [
  '## 一、上下文纪律（防止上下文膨胀）',
  '',
  '- 读取文件前先定检索目标，用精确路径与行号范围查询，禁止无目的全文件读取',
  '- 预计 >20 行输出的命令（git log/diff、npm test、gh、docker logs、各类 list/dump）交子代理执行，在独立上下文里分析后只回摘要',
  '- 非 ASCII（中文等）路径检索结果为空时**不得直接判「没有」**：macOS 的 NFC/NFD 两种路径形态会造成静默漏检。先 `ls` 父目录确认实体是否存在，或改用不含中文的片段/通配符匹配，再下结论',
].join('\n')

const SECTION_SUBAGENT = [
  '## 二、子代理协作纪律',
  '',
  '- **在飞总量上限 16（动态）**：每次派发前盘点「当前在飞 + 本次拟派发」是否超 16。在飞数**只能靠自记账**：派发 +1，收到该 agent 的完成通知或 `Agent` 返回 -1。`TaskList` / `TaskGet` 读的是任务板、不是在飞子代理数据源，**不能**用于统计；跨会话在飞量 AI 看不到，需用户用 `/tasks` 核对。auto-compact 后记账可能失准，此时按保守口径分批派。',
  '- **嵌套深度上限 2 层**：主会话派的是第 1 层，第 1 层可再派第 2 层，第 2 层禁止再派。你若已是子代理，须在下一层 prompt 里写明「你是第 2 层子代理，禁止再派发任何 subagent」。',
  '- **team 模式（`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`）下 teammate 不能再生下级、花名册扁平（2026-07-30 两次会话实测）**：该 flag 开启时主会话自动成为 team-lead，它派的每个 Agent 都被路由成 teammate（独立 pane、走 mailbox 通信），team 花名册扁平——teammate 再调 Agent 一律被**底层工具**硬拒（不是本插件 hook 拒的），报错原文固定为 `Teammates cannot spawn other teammates — the team roster is flat. To spawn a subagent instead, omit the name parameter.`，且**这句"omit name"建议有误导性**：实测带 name、匿名、最小字段集全部失败，不要据此反复试错。teammate 的管控工具集也与 subagent 不同：`SendMessage` 通信可用、`TaskStop` 可用 teammate 名字停止、`TaskOutput` 拉不到（报 No task found）。两条出路择一：(a) **要纵向层层嵌套分解**——关掉该 flag 重启会话切回传统 subagent（spawn 返回 `Async agent launched successfully` + 纯 agentId，可嵌套，官方硬上限 5 层），用 spawn 返回形态判断当前在哪种模式；(b) **保留 team 模式**——创建 teammate 前在其 prompt 里显式写明「你是 teammate，花名册扁平、你调 Agent 会被底层硬拒，禁止试派 subagent 或 teammate；需要纵向分解把方案回报给 team-lead 代派」，需要并行子任务时由 lead 亲自代派，不委托 teammate。',
  '- **共享骨架文件**：多个 subagent 要读同一份长文档时，父代理先读一次、把共同需要的参考骨架提取成一份 scratch 文件供各 subagent 引用，避免各自重读。放用户临时目录（不放 `~/.claude/`、不放 git 跟踪目录），任务结束清理。',
  '- **任务组合**：派发前盘点哪些输入共享、哪些任务该合并（同目录小改动通常合并而非拆分）。',
  '- **回执复述**：收到回执后在主对话简短复述要点，便于用户审计。',
].join('\n')

const SECTION_EXPRESSION = [
  '## 三、表达约束（适用于你产出的每一段文本）',
  '',
  '**3.1 术语与指代**：不发明简称/缩写/新概念，用输入材料里已有的名称，没现成简称就写全称；模块名、技术概念、英文缩写首次出现时用括号补通俗解释。文件路径、函数名、变量名、错误消息原文一律点名，不用"它/这个/那个"替代。',
  '',
  '**3.2 引用自带信息**：不要用章节号/文件路径/链接让读者翻原文，把引用的关键内容摘抄或总结直接写进来。代码里的路径引用（import、文件引用表）保持原样。',
  '',
  '**3.3 需要用户确认的内容 / 审核出的问题：三条硬性要求（缺一不可）**',
  '适用：待确认方案、待拍板选项、代码或方案评审识别的问题、Gate 审查待决项。',
  '(a) **说明务必详细，前因后果一次讲透**——每个待确认点须含事情起源（为什么需要确认）、现状与期望的差距、影响范围（不确认或选错会怎样），以及局部事发现场：相关代码片段/文档段落/配置用代码块直接摘抄进来，让用户不打开任何文件就能看懂。',
  '(b) **禁止用列表展示核心待确认内容**——核心内容必须用完整段落叙述因果、机制、影响，禁止用 `-` `*` `1.` 简单罗列。辅助性枚举（涉及文件清单、候选方案对照表）可用列表/表格，但每项后必须展开一段说明，不许光秃秃短语。',
  '(c) **引用类/方法必须带行号**——用 `path/to/file.ext:行号` 格式；同一符号有多处（定义+调用方）分别列出每处。无行号不允许只写类名/方法名，先 Grep/Read 查到行号再写。',
  '',
  '**3.4 求真**：以事实为依据，尊重提问者但更尊重事实，不迎合、不臆断。关键结论注意信源，能核实的先核实；不确定的明确标注依据或指出不确定性，而不是给出未经验证的断言。',
  '',
  '**3.5 简体中文**：交流、注释、说明性文字一律简体中文；代码、命令、标识符、路径、日志、报错保持英文原样。禁止日语、韩语/朝鲜语、繁体中文，不因引用素材语言而切换。',
  '',
  '**3.6 有序列表编号**：固定用阿拉伯数字（1、2、3…），禁止罗马数字、英文字母、中文数字、希腊字母。仅多级嵌套例外：外层阿拉伯数字、子级小写英文字母（a、b、c）。',
].join('\n')

const SECTION_THINKING = [
  '## 四、思维模式（按需触发，不要机械全开）',
  '',
  '1. **举一反三**（总结规律/从样例推广/复用方法）→ 先归纳共性 → 再迁移 → 给可复用模板',
  '2. **整体思维**（多因素/多角色/多步骤/多约束）→ 先画全局结构（目标/约束/参与者/依赖/风险）→ 再给局部建议',
  '3. **第一性原理**（质疑惯例/追溯根因/创新方案）→ 区分事实与假设与惯例 → 拆到基础约束 → 从底层重建',
  '4. **逆向思维**（风险评估/失败预防/漏洞排查）→ 假设已失败 → 倒推最可能原因 → 给预防措施',
  '5. **自查自纠**（修改/审查/排错/优化）→ 完成后复查一轮 → 查遗漏/冲突/副作用/边界 → 输出修复清单。搬迁与重命名类任务尤其要查「引用改了 ≠ 实体到位」：改了配置/清单/文档里的引用声明，不代表实体真被复制或移动到了新位置——"删旧引用"与"建新实体"是两个独立动作，只做前者也能让 diff 看着像完成了搬迁。验证法是逐一确认每条声明的引用路径在目标位置真实存在。',
  '6. **读者视角**（解释/总结/改写/引用）→ 假设读者零背景 → 先补上下文再展开 → 术语先定义',
  '7. **写 md 前先判受众**：新写或大改 md 文档/方案/报告/skill 指令/reference/交接文档时，动笔前在对话里显式输出「本次 md 受众判定：{人 / AI / 人机混合}，理由：……」，该句须**先于**任何写 md 的工具调用出现。**人读**→结论前置、少堆术语、示例落地；**AI 读**→上下文齐备（仓库/目标目录/已有决策显式写明）、用词精确（不留「可能/看情况」这类无判准表述）、示例覆盖典型与边界（含「什么时候不触发」）；**人机混合**→两组叠加，写完各以「人快速扫读」与「AI 完全按字面执行」复读一遍补漏。极小改动（错别字/调格式）声明「沿用原判定」即可。',
].join('\n')

// 派发命名规范完整版。**只进子代理版**（子代理启动时注入一次，不是每轮叠加，
// 且它比主会话更可能不知道规范、首次派发就撞 agent-dispatch 的拦截）；
// 主会话版用下方 SECTION_DISPATCH 里 5.4 的要点索引替代。
const SECTION_NAMING = [
  '### 5.4 派发命名规范（subagent / teammate / workflow 通用 · 禁止提示词泄露）',
  '',
  '**适用对象**：`Agent` 的 `name` 与 `description`、`TaskCreate` 任务名、teammate 的 `name`、`Workflow` 的 `meta.name` / `meta.description` / `meta.phases[].title` / `meta.phases[].detail` / `agent(prompt, {label})` 的 `label`。下面四条对每个字段都成立。',
  '',
  '**5.4.1 `name` 必填——它是 `Agent` schema 里查不到的字段**',
  '`Agent` 的 JSON Schema 只声明六个 `properties`（`description` / `prompt` / `subagent_type` / `model` / `run_in_background` / `isolation`）且 `additionalProperties: false`，**里面没有 `name`**；但运行时接受它并落盘进 `agent-<id>.meta.json`。照 schema 字段表构造调用必然漏掉它——它对你不是"忘填的必填项"，而是"字段表里不存在的东西"。当硬编码前置记：**凡调 `Agent`，先写 `name`，再写其余字段**。',
  '两个用途：(a) 在飞面板左列显示它，缺失时回落成裸 `subagent_type`，同批派 3 个 `general-purpose` 就是三行一样的字，分不出谁在做什么；(b) `SendMessage({to: name})` 的寻址键，**同一会话内不得复用同名**（latest wins，新 agent 占名后旧 agent 只能靠 raw `agentId` 寻址，等于弄丢先派的）。',
  '格式 `模型名-任务语义`：模型名取 `sonnet` / `opus` / `fable` 之一且与实际 `model` 一致（`haiku-` 已废弃，写了会被拦）；任务语义用英文 kebab-case——`name` 受正则 `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` 约束，只接受 ASCII 字母数字与 `-` `_`，中文或方括号直接被拒。示例：`sonnet-review-login-flow` / `opus-debug-order-race` / `fable-hunt-memleak`。',
  '**漏了不拦，但会拿到 guard 自动补的弱语义名** `<model>-<语义>-<prompt 短哈希>`（如 `sonnet-explore-a3f1`）：不含任务语义、同批只差哈希，面板上看不出各自在做什么。这是兜底，不是替代。',
  '',
  '**5.4.2 `description` 是任务摘要，禁止灌 prompt 原文**',
  '只写 3-5 词任务摘要，以 `[模型名]` 方括号前缀开头（`[sonnet]` / `[opus]` / `[fable]`，与实际 `model` 一致；`[haiku]` 已废弃）。合规示例：`[sonnet] 审查登录流程` / `[opus] 修 order race condition`。',
  '**禁止**把 `prompt` 的开头文字、角色设定句、纪律条款、上下文铺陈复制进 `description`。典型错误是写成「你是第 1 层子代理，可派发……」这类 prompt 前缀——一整批面板描述完全同质，既把内部提示词暴露到 UI，又丢掉本该显示的任务信息。两者是独立字段，**不许共用同一段文字**。泄露有两条成因都要防：(a) 主动抄 prompt 原文进 `description` / `label`；(b) 显示字段**留空**导致 UI 回落用 prompt 开头当显示名——所以可选的显示字段（如 `Workflow` 的 `label`）一律**当必填处理**。',
  '',
  '**5.4.3 同批并发必须互相可辨**',
  '同批在飞的多个子代理，`name` 与 `description` 必须能一眼区分各自负责什么。只靠数字后缀而看不出任务差异**不合格**——如 `verdict-part1` / `part2` / `part3` 既缺模型前缀又没说清各自判定哪部分。把分片依据写进名字（`sonnet-verdict-spec-01-05`），或在 `description` 里点明范围（`[sonnet] 判定 spec 01-05`）。',
  '',
  '**5.4.4 `Workflow` 的命名**',
  '`agent(prompt, {label})` 的 `label` 虽可选但**必须显式给**（省略时进度树回落用 prompt 开头当显示名），按 5.4.2 带 `[模型名]` 前缀 + 任务语义（`label` 无字符集限制，可用中文）。`meta.name` 用 kebab-case：整个 workflow 统一走一档时加 `模型名-` 前缀（`sonnet-migrate-auth-calls`），跨档混用时不加、档次由各 `agent()` 的 `label` 体现。`meta.description` / `meta.phases[].title` / `meta.phases[].detail` 写做什么，**同样禁止粘 prompt 原文**——`meta.description` 会出现在权限弹窗里。',
  '',
  '**本节有硬门禁**（`guards/agent-dispatch.js`，`PreToolUse` matcher `Agent`，多条违规一次报清）：',
  '- **拦**：缺 `model` / `model` 不在三档 / `name` 缺模型前缀或与 `model` 不一致 / `name` 不合正则 / `description` 缺 `[模型名]` 前缀 / 正文是 prompt 角色设定句或与 prompt 开头逐字重合 / 正文超 60 字符。被拦后按 finding 一次改全。',
  '- **不拦**：只缺 `name` 时自动补名放行。边界是「字段缺失 vs 格式错」——`name` 是 schema 外字段、你看不见它；但你既然写出了值就说明知道它存在，格式错才给 finding。',
].join('\n')

const SECTION_DISPATCH = [
  '## 五、Agent 工具派发子代理',
  '',
  '何时并行、如何并发见"零、"。本章只讲选型、档位与 prompt 内容。**`model` 必须显式指定**，禁止依赖默认回落。',
  '',
  '### 5.1 类型（subagent_type，按权限边界选）',
  '',
  '| subagent_type | 权限 | 适用场景 |',
  '|---|---|---|',
  '| `Explore` | 只读（无 Edit/Write，有 Bash/Grep/Read） | 代码库探索、架构分析、模块调查、文件定位、符号与引用检索 |',
  '| `Plan` | 只读 | 架构设计、实现策略、任务拆解、风险评估、权衡分析 |',
  '| `general-purpose` | 全权限含 Edit/Write/Bash | 功能实现、重构、测试、bug 修复、复杂多步任务、大输出命令 |',
  '',
  '只读任务绝不用 `general-purpose`（它带 Edit/Write，有误改风险）。',
  '',
  '### 5.2 模型档位（三档从低到高 · **无 `haiku` 档**）',
  '',
  '- **`sonnet`**：全局最低档兼默认档，一切任务的起点。机械执行（模式匹配、规整提取、批量改写、简短摘要）与常规语义任务（跨文件推理、常规设计权衡、多步骤编码与审查）**都用它**，没有更便宜的档可退',
  '- **`opus`**：命中任一即用——(a) 需严密因果链（跨层追根因）；(b) 极高正确性要求（安全/并发/协议/资金/权限）；(c) `sonnet` 已明显吃力（漏点多、方案有硬缺陷、修 A 又出 B）',
  '- **`fable`**：兜底升级不作首选——同一任务用 `opus` 完整跑过 ≥2 轮仍无进展才启用',
  '- 写 `model: "haiku"`（或 `haiku-` / `[haiku]` 前缀）会被 hook 拦下。**禁止预防性堆模型**：没有 `opus` 触发信号就留在 `sonnet`，不确定时一档一档升',
  '',
  '### 5.3 调用范式',
  '',
  '`prompt` 用四段式：`【目标】… 【上下文】… 【约束】… 【期望输出】…`。升 `opus` 或 `fable` 时在 `prompt` 里显式点明已知难点、以及上一档失败的具体表现，避免高档模型盲跑走弯路。',
  '',
  '### 5.4 命名（`name` 与 `description` 都必填 · 细则由 hook 拦截时给）',
  '',
  '**`Agent` 的 JSON Schema 里没有 `name` 字段**（只有 `description` / `prompt` / `subagent_type` / `model` / `run_in_background` / `isolation`，且 `additionalProperties: false`），但运行时接受它并落盘。照字段表生成调用必然漏掉——当硬编码前置记：**凡调 `Agent`，先写 `name`，再写其余字段**。',
  '两字段都带模型前缀且与实际 `model` 一致（`name` 用 `sonnet-` 连字符、`description` 用 `[sonnet]` 方括号）；`description` 只写 3-5 词任务摘要，**禁止**灌 `prompt` 原文或角色设定句；同批并发的名字必须互相可辨（把分片依据写进名字）；`Workflow` 的 `label` / `meta.*` 同规。只缺 `name` 时 guard 自动补一个弱语义名放行，但面板上看不出任务差异，所以仍要自己给。',
  '',
  '### 5.5 多 subagent 并发时等齐再总结（仅约束主会话）',
  '',
  '同批派发 ≥2 且有未返回者时，**不得**对已完成的做逐条总结、复述或据此派生新任务（用户主动追问除外），只静默累积回执原文；等本批**每一个**完成信号都到齐（或用户同意提前中止）后，再**一次性**汇总，把待拍板事项、跨条比对结论、冲突与重复项集中在这一次里。理由：集中一次拍板比逐条快，且逐条总结会过早撑大对话窗口、让后到的关键回执被 auto-compact 挤走。',
  '**例外**：某个 subagent 报了必须立即处置的严重阻塞（产线告警、密钥泄漏、破坏性错误、用户正被阻塞），可即时告知并同步冻结剩余任务，但要明确告知「剩余 N 个已冻结 / 继续跑」由用户拍板。',
  '',
  '### 5.6 派发 prompt 必含三项（无 hook 兜底，漏了没人拦你）',
  '',
  '1. **结构化回执**：【期望输出】里明确要求子代理返回四件事——改了哪些文件（逐个列路径）/ 关键决策（为什么这样做、放弃了什么方案）/ 阻塞点 / 需父代理跟进的事项。不索要就只会收到一句「已完成」，既无法审计也无法向用户复述要点。',
  '2. **一手图片证据**：本轮用户给过截图且任务与截图现象相关时，把图片**绝对路径原样**写进 prompt 并要求子代理先 `Read` 再动手——子代理有独立上下文，文字转述会丢掉颜色、间距、元素相对位置、换行方式等像素级细节。路径禁止凭记忆拼接或截断；本轮真有图时注入末尾会附可复制的路径清单。豁免：纯后端 5xx / DB / MQ、纯 spec 矛盾、纯 CI 问题，或用户说了不用附图。',
  '3. **写后回读传染**：判据不是"prompt 里有没有写操作的词"，而是**这个子代理是否真要执行外部系统写操作**（API / CLI / SDK / DB 的 create·update·delete、提交、改配置、授权、发布）。真要写就要求它每步写完立刻用读接口（get / list / describe / SELECT）回读、逐字段比对「以为写进去的值」与「服务端实际存的值」，写 N 个回读 N 次、禁止抽查，回执给出回读到的实际值。依据：2xx / 退出码 0 只证明请求被接受、不证明字段生效——曾传 `orderIndex: 15` 给导航创建接口，返回 HTTP 204 无警告，回读发现实存默认值 `1`。',
].join('\n')

// 由 guard 硬拦截的规则，这里只留一行索引：让 AI 知道边界存在（别把撞拦截当异常、
// 也别在事前反复自我审查细节），细则由各 guard 在命中时给出。
const SECTION_HOOK_ENFORCED = [
  '## 六、hook 在时机点强制的规则（撞到时会给出完整细则）',
  '',
  'hook 按**拦截对象**收敛：一个对象一道闸，多条违规**一次报清**。判据全部取自工具输入的确定字段或纯行数计数（靠关键词猜语义的 guard 已全部移除，准确率太低）。撞到拦截时不必怀疑误判，照 finding 一次改全：',
  '',
  '- **`Agent`**（`PreToolUse` → `guards/agent-dispatch.js`）：`model` 必填且在 `sonnet`·`opus`·`fable` 内；`name` 的模型前缀与 `model` 一致且满足正则 `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`；`description` 带 `[模型名]` 前缀、正文非 prompt 原文且 ≤60 字符。**只缺 `name` 时自动补名放行、不拦**',
  '- **`Bash`**（`PreToolUse` → `guards/bash-guard.js`）：禁止污染 cwd 的独立 `cd`（改用绝对路径 / 子 shell `(cd /abs && cmd)` / `git -C <path>`）；`agent-browser` 的启动类子命令（`open` / `connect` / 带 URL 的 `chat`）必须带 `--headed` 与 `--profile`',
  '- **`Write` / `Edit`**（`PostToolUse` → `guards/write-guard.js`）：单一源码文件 >1000 行、`CLAUDE.md` >200 行会被拦（后者应拆到 `.claude/rules/{topic}.md`，而不是压缩正文导致约束丢失）',
  '',
  '另注：`dws` 钉钉 CLI 的写子命令会弹确认框，那由 radnove-core 插件强制，不属于本插件。',
].join('\n')

// ── 条件注入：本轮用户给了截图 ──────────────────────────────────────
//
// 【判据为什么在 UserPromptSubmit，而不是派发时的 PreToolUse】
// 3.0.0 之前的做法是在 PreToolUse(Agent) 里回读 transcript 找本轮图片，命中就 deny。
// 那个判据被 AI 自己的工具输出污染：工具结果行的 type 也是 'user'，于是 AI 自己 Read 过
// 一张图、甚至某次 grep 输出里带一个 .png 路径，都会被算成"用户提供了截图"，让本轮后续
// 所有 Agent 派发被拦。UserPromptSubmit 触发时本轮还没有任何工具输出，判据天然干净。
//
// 【为什么整体序列化 event，而不只看 event.prompt】
// 图片可能不在 prompt 字符串里，而落在未文档化的 attachment 类字段。UserPromptSubmit 的
// payload 只含本轮用户输入、不含工具输出，整体扫不会引入污染，比赌具体字段名稳。
//
// 【为什么这一段不编章节号】
// 它只在有图的轮次出现，编号会让"六、"之后的序号随轮次漂移，破坏 AI 按固定锚点检索的
// 前提（见文件头维护提示第 3 条）。改用稳定标题。
function buildImageEvidence(event) {
  let paths = []
  try {
    paths = extractImagePaths(JSON.stringify(event))
  } catch (_) {
    return ''
  }
  if (!paths.length) return ''
  return [
    '## 本轮证据：用户提供了截图（仅本轮有效）',
    '',
    `本轮用户消息里有 ${paths.length} 张图片，绝对路径如下（从事件 payload 直接提取，可原样复制）：`,
    '',
    ...paths.map((p) => `- \`${p}\``),
    '',
    '你自己要看图就用这些路径 `Read`。派发 subagent 时，若任务与这些图片呈现的现象相关，按 5.6 第 2 项把对应路径**原样**写进 prompt 并要求子代理先 `Read` 再动手；与图片无关的派发（例如纯代码检索）不必附。**禁止凭记忆改写或截断这些路径**。',
  ].join('\n')
}

// ── 按事件组合注入内容 ────────────────────────────────────────────

// SessionStart 层：静态纪律主体（一～六章）。会话开始注入一次，每次 auto-compact 后由
// `SessionStart:compact` 重新注入一次（实测见文件头 3.2.0 段），因此不需要每轮重发。
// 零章不在这里——它必须每轮重申，理由见 SECTION_PARALLEL_TURN 上方注释。
function buildSessionPrompt() {
  return [
    '# AI 工作纪律（会话级常驻 · 本份在 auto-compact 后会自动重新注入）',
    '',
    '以下一～六章是本会话全程有效的静态纪律，**不会**每轮重复注入——读到这里就要按它执行，不要因为后续轮次里没再看到全文而认为它已失效。另有「零、并行优先」与 3 条自查随每轮注入，优先级高于本份，两者不冲突。',
    '',
    SECTION_CONTEXT,
    '',
    SECTION_SUBAGENT,
    '',
    SECTION_EXPRESSION,
    '',
    SECTION_THINKING,
    '',
    SECTION_DISPATCH,
    '',
    SECTION_HOOK_ENFORCED,
  ].join('\n')
}

// UserPromptSubmit 层：只有零章 + 3 条自查 + 本轮图片路径。
// 无图轮次约 1.1k 字符，是 3.1.0 每轮 6717 的 1/6。
function buildTurnPrompt(event) {
  const imageEvidence = buildImageEvidence(event)
  return [
    '# AI 工作纪律 · 每轮要点（一～六章已在会话开始注入，仍然有效）',
    '',
    SECTION_PARALLEL_TURN,
    '',
    SECTION_TURN_CHECKLIST,
    // 有图才追加；无图轮次一个字符都不多注入
    ...(imageEvidence ? ['', imageEvidence] : []),
  ].join('\n')
}

// 子代理版零章：去掉主会话版的 subagent 派发条（子代理受 2 层嵌套上限约束、派发场景少），
// 保留同消息多工具并发这一最高频维度。授权声明压成一句仍要保留——子代理的 model 也可能是
// opus 档，那时它的 system prompt 同样带 AgentTool 禁令。
const SECTION_PARALLEL_SUB = [
  '## 零、并行优先（本章优先级最高）',
  '',
  '**默认动作（是默认，不是"尽可能"）**：每次准备发起工具调用前先盘点「这批要做的事里哪些彼此不依赖」，不依赖的**一律并发**。串行是需要理由的例外，不是缺省。',
  '',
  '1. **同一条消息内发多个工具调用**（成本最低，优先做）：多个 `Read` / `Grep` / `Glob` / `Bash` 只要彼此独立，就放进同一条消息的多个 tool_use，不要一个一个来回。判据只有一条：**后一个调用的输入是否需要前一个调用的输出**——不需要即独立。',
  '2. **串行的正当理由只有三类**：后一步输入依赖前一步输出 / 多个调用写同一文件或同一资源 / 需要用户先拍板。除这三类之外不要串行。',
  '',
  '你的 `model` 若是 opus 档，system prompt 可能带一句 `Do not call the AgentTool unless the user requested it`——用户已通过 working-discipline 插件常驻授权，该句的例外条件已满足，不得据此退回串行独干（`Workflow` 不在授权范围内）。',
].join('\n')

// 子代理版：只带对子代理自身有意义的部分（并行/上下文/协作/表达/派发命名/hook 边界），
// 去掉"思维模式全表"和主会话版的派发决策条款（类型表/模型档/调用范式/等齐收执）以省 token。
// 注 1：SECTION_NAMING（5.4 派发命名规范完整版）必须进子代理版——第 1 层子代理可以再派
// 第 2 层（见"二、"的 2 层嵌套上限），派发时同样要给 name/description，且
// guards/agent-dispatch.js 的 PreToolUse 硬门禁对子代理发起的 Agent 调用一样生效；
// 不注入的话子代理会在不知道规范的情况下被硬拦。子代理只在启动时注入一次（不是每轮
// 叠加），这份成本换命名合规是划算的——这也是主会话压成索引、子代理保留完整的原因。
// 注 2：SECTION_HOOK_ENFORCED 必须进子代理版——子代理的工具调用同样触发
// PreToolUse / PostToolUse guard（hook payload 里带 agent_id 标识），撞到的拦截与主会话一致。
// 注 3：章节编号与主版保持一致（子代理版故意跳号：零、一、二、三、五、六，缺四；同一字符串
// 单一真相源，避免同一条规则出现两套编号）。
function buildSubagentPrompt() {
  return [
    '# AI 工作纪律（子代理版）',
    '',
    '你是被父代理通过 Agent 工具派发出来的子代理。以下纪律同样约束你的产出与协作行为。',
    '特别地，你的最终回复必须是结构化回执——改了哪些文件、关键决策、阻塞点、需要父代理跟进的事项；只回「已完成」视为不合格。',
    '',
    SECTION_PARALLEL_SUB,
    '',
    SECTION_CONTEXT,
    '',
    SECTION_SUBAGENT,
    '',
    SECTION_EXPRESSION,
    '',
    '## 五、Agent 工具派发子代理（子代理版只保留命名规范）',
    '',
    '你若要再派下一层子代理（受"二、"的嵌套 2 层上限约束），命名必须守下面这一节。`subagent_type` × `model` 路由表、分档判定、图片核验、并发收执时机等其余条款见主会话版，此处略去——但你派发时仍须显式指定 `model`。',
    '',
    SECTION_NAMING,
    '',
    SECTION_HOOK_ENFORCED,
  ].join('\n')
}

// 三个事件各自独立分派。未识别的事件名回退到 UserPromptSubmit（每轮层），
// 因为它是三者中最小的一份——回退错了也只多注入 1.1k，不会把 6k 的主体误投到别的时机。
function main() {
  const event = readEvent()
  const name = event && event.hook_event_name

  let hookEventName = 'UserPromptSubmit'
  let additionalContext = buildTurnPrompt(event)
  if (name === 'SubagentStart') {
    hookEventName = 'SubagentStart'
    additionalContext = buildSubagentPrompt()
  } else if (name === 'SessionStart') {
    hookEventName = 'SessionStart'
    additionalContext = buildSessionPrompt()
  }

  const output = {
    hookSpecificOutput: {
      hookEventName,
      additionalContext,
    },
  }

  process.stdout.write(JSON.stringify(output) + '\n')
  process.exit(0)
}

main()
