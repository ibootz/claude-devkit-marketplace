# Working Discipline

一个纯 hook 插件，用两种方式把「AI 工作纪律」落到 Claude Code 上：

1. **常驻注入**：每轮往主会话、以及每次子代理启动时的 context 里，塞入一份可审计、可复用的行为准则；本轮用户贴了截图时，额外附一份可原样复制的图片绝对路径清单
2. **硬拦截**：派发 subagent 时 `name` / `description` / `model` 等**结构字段**不合规（`PreToolUse` deny）、以裸 `cd` 开头污染 cwd 的独立命令、缺鉴权或实例超限的 `agent-browser` 启动（`PreToolUse` exit 2）
3. **事后提醒**：写入完成后，超 1000 行的源码文件、当前项目内超 200 行的 `CLAUDE.md` 会拿到一条 stderr 提示（`PostToolUse` exit 2）。**它不是拦截**——触发时文件已经落盘，既不回滚也不停住本轮，见第四章

零 skill、零命令、零子代理，装了就生效。不修改用户文件：两道 `PreToolUse` 闸只阻断工具调用本身，`PostToolUse` 的 `write-guard` 连"继续往下走"都不阻断。唯一一处会改动工具调用的地方是**缺 `name` 时自动补名**，见第二章。

### 核心设计原则：判据必须真的机械，否则别做成 deny

2.0.0 做过一次大幅瘦身，起因是一个反直觉的观察——**注入的规则越多，AI 的整体遵从度反而越低**，连那些写得很清楚的规则也开始被跳过。根因是**常驻与按需错配**：原注入里有一大半属于「只在某个具体工具调用时刻才有用」的细则，它们每一轮都在跟真正只能靠自觉的语义规则（求真、思维模式、等齐再总结）抢同一份注意力预算。于是判据定为：**一条规则若能被机械判定，就不该常驻**，下沉成 hook 在命中时才付细则的 token。

**3.0.0 补上了那条判据里被忽略的前提：判据必须真的机械可判定。** 2.0.0 下沉的规则里有一批判据其实是「用正则猜 prompt / 命令的语义」，配上不可绕过的 `deny` 之后，失败模式不是"AI 被纠正"，而是**"AI 做对了却过不去"**。三个实证：

- 排查一个「点发布按钮报错」的 bug 时，`发布` / `publish` 在派发 prompt 里出现十几次，**全部是被排查对象的业务语义**，不是 AI 要执行的动作；而 `Explore` 类型物理上没有 `Edit` / `Write` 工具、改不了任何文件，守卫却只读 prompt 文本、没把 `subagent_type` 的权限面纳入判据，于是把两个纯 `Read` / `git grep` 的任务判成了写操作
- 截图检查回读 transcript 找本轮图片，而**工具结果行的 `type` 也是 `'user'`**——AI 自己 `Read` 过一张图、甚至某次 grep 输出里带一个 `.png` 路径，都会让本轮后续**所有** `Agent` 派发被拦；它读自己的源码就会自我触发，因为源码里的正则字面量完全符合那条路径正则的形状
- 非 ASCII 路径守卫把命令行里**任何**非 ASCII 字节都当成"路径含非 ASCII"，于是 `echo '=== 已安装缓存版本 ==='; ls -d /tmp/foo 2>/dev/null` 被拦——中文来自 `echo` 的提示语，路径全是 ASCII

所以 3.0.0 删掉了所有这类 guard（清单见第五章），判据固化为一句话：

| 判据性质 | 去处 |
|---|---|
| 取自 `tool_input` 的确定字段（存在性、前缀一致性、字符集、长度）或纯行数计数 | 可以做成 `deny` / `exit 2` |
| 要靠正则猜命令 / prompt 的语义，或回读 transcript 推断状态 | 留在常驻注入里靠自觉，**别做成拦截** |

**3.6.0 用这条标准回过头审判它自己，结论是三条判据里只有一条真的达标。** 起因是用户先在仓库根立了 `.claude/rules/hook-restraint.md`（"默认不加 hook，能 100% 机械判定才可以"），随即要求用它复核本插件已有的三个 guard。两个 opus 只读审计构造真实 payload 跑真 guard（`bash-guard` 103 条、`write-guard` 27 条、`agent-dispatch` 28 条），发现：**只有 `write-guard` 的行数计数是纯计数**；独立 `cd` 与 `agent-browser` 启动参数都是「对命令字符串做近似 shell 解析后的形态匹配」，与 3.0.0 删掉的关键词 guard 差别是**程度而非性质**（那批猜的是意图，这两条猜的是语法结构）；`agent-dispatch` 里的 `PROMPT_LEAK_PREFIXES`（`description` 正文以 `你是` / `You are` 等句式开头即判为抄了 prompt）也是句式近似判定，不是确定字段比较。

这不意味着这三条该删——用户逐条拍板的结论是"修误杀 + 收窄，不删"（详见本文档「3.6.0 审计」一节）。它意味着**原表格那一行"取自确定字段"当初被读得太宽**：判据取自 `tool_input.command` 这个确定字段，不等于**判据本身**是确定的，因为中间隔着一层近似解析。仓库级规则 `.claude/rules/hook-restraint.md` 现在承担更严格的那份判据分级（能做 / 不能做各自的清单、强度阶梯 `什么都不做 → 注入提醒 → ask → deny`、新增 hook 前必须回答的五个问题、以及"判据改动必须用户拍板、AI 只报不改"），本插件是它的第一批实证来源。

同时**挂载拓扑按拦截对象收敛**：一个对象只有一道闸。3.0.0 之前 `Bash` 上串行挂着三个 guard、`Write|Edit` 上挂着两个，其结构性缺陷是**一批只报最前面那道闸**——AI 补完第一处才看见第二处，多轮往返是拓扑的产物，而不是 AI 每轮新犯一个错。

| 拦截对象 | 事件 | guard | 合并自 |
|---|---|---|---|
| `Agent` | `PreToolUse` | `guards/agent-dispatch.js` | （2.0.0 已合并 `agent-naming.js`） |
| `Bash` | `PreToolUse` | `guards/bash-guard.js` | `block-cd.js` + `agent-browser-launch.js` |
| `Write` / `Edit` | `PostToolUse` | `guards/write-guard.js` | `max-source-lines.js` + `claude-md-max-lines.js` |

---

## 什么时候用

- 想让 Claude 的行为在长会话、多 agent 协作里更规整、更可预测
- 被 AI 独立 `cd /tmp` 之后所有相对路径失准坑过
- 团队或个人想固化一套「工作纪律基线」，任何项目都能开着

## 什么时候不用

- 项目里已有更严格的 `CLAUDE.md`，且不希望被通用纪律覆盖
- 只是短会话、单文件微改，不想付出每轮注入的 token 成本

---

## 一、注入：三层各注入什么

3.2.0 起按**投放时机**分三层。「会话级」是 `SessionStart`（会话开始 + 每次 auto-compact 后各一次），「每轮」是 `UserPromptSubmit`，「子代理」是 `SubagentStart`。

| 维度 | 关键约束 | 会话级 | 每轮 | 子代理 |
|------|---------|:---:|:---:|:---:|
| 零、并行优先 | 常驻授权声明（对冲 system prompt 的 AgentTool 禁令）、独立性盘点、三档并行按成本排序（第 3 档 3.11.0 加：**同一类改动落在 ≥3 个文件**的机械改写交 `general-purpose`，判据是文件数不是难度，附三条不触发情形）、三类正当串行理由 | — | ✅ | ✅(精简) |
| 一、上下文纪律 | 精确路径读文件、子代理优先、bash 输出限流、macOS 中文路径「空结果不得判无」 | ✅ | — | ✅ |
| 二、子代理协作 | 在飞≤16（靠自记账盘点，明确禁用 `TaskList` 统计——它是任务板不是在飞 agent 列表）、嵌套≤2、共享骨架文件、结构化回执 | ✅ | — | ✅ |
| 三、表达约束 | 主会话版只保留纪律条款（3.3 拍板内容讲透 / 3.4 求真 / 3.5 简体中文）；行文风格条款（3.1 术语与指代 / 3.2 引用自带信息 / 3.6 列表编号）3.9.0 起移交 `plain-talk-output-style` 插件随风格切换。子代理版仍是**全量六条**——SessionStart 不进子代理、风格插件对它们无效，而它们是产出 md 的主力 | ✅(纪律) | — | ✅(全量) |
| 四、思维模式 | 举一反三 / 整体 / 第一性 / 逆向 / 自查自纠 / 读者视角 / 写 md 前受众分辨（含三分支要点） | ✅ | — | — |
| 五、Agent 派发 | 5.1 `subagent_type` 选择、5.2 三档 model 判定标尺（`sonnet` / `opus` / `fable`，**无 `haiku`**）、5.3 调用范式、5.4 命名索引（3.16.0 起压成三条补充，正文移到「完整调用形态」）、5.5 多 subagent 并发时等齐再总结、5.6 派发 prompt 必含四项（回执 / 图片证据 / 写后回读 / **核实类任务的追踪停止条件**）、5.7 subagent 因系统/网络原因（529 / 限额 / 限流 / 超时 / 断流）失败后的即时评估与一致性验证 | ✅ | — | 仅 5.4（增量部分） |
| 派发 `Agent` 的完整调用形态 | **3.16.0 加**。可整体照抄的调用 JSON（`name` 排第一）+ `prompt` 四段式模板 + 六字段硬要求表 + 三条不适用情形，并显式声明**本段优先级高于 `Agent` 工具自带的 JSON Schema** | — | ✅ | ✅ |
| 六、hook 边界清单 | 一份索引：三个 guard 各管什么、判据是文本形态匹配因而都有误杀面（撞到明显误判就报告用户拍板）、`write-guard` 挂 `PostToolUse` 指望不上它兜底、哪些规则已删除因而没有兜底。**不复述细则** | ✅ | — | ✅ |
| 每轮自查 4 条 | 只列指针不复述细则：`Agent` 先写 `name` / 写 md 前输出受众判定句 / 待确认内容用完整段落 + 行号引用 / 核实类任务先定追踪停止条件、结论写明追到哪一层 | — | ✅ | — |
| 本轮证据（条件） | 本轮用户贴了截图时，附图片绝对路径清单；无图轮次一个字符都不注入 | — | ✅ | — |

**每轮层的选条判据**（新增前先过这两问，两个都"是"才加，否则放会话级）：这条**无 hook 兜底**吗？在真实 session 里**实测被忘过**吗？现有 4 条的依据分别是——`name` 在 `Agent` 的 JSON Schema 里根本不存在（照字段表生成必漏，某 session 实测漏 4 次且第二次距第一次 52 分钟）；受众判定的 `md-audience-declaration.js` 已在 3.0.0 删除、现在毫无兜底；待确认内容三要求违反后用户要反复追问才能拿到可决策信息，返工成本最高；核实类任务的停止条件判据只能猜语义因而不做成 guard（见下方「核实类任务」一节），2026-07-31 实测漏写后两个代理对同一处注释给出相反结论，且它**同时约束主会话自己做的核实**——5.6 只管派出去的那部分，留在会话级会漏掉主会话亲自核实的场景。

子代理版带一~三节、五节的 5.4 派发命名规范（**完整版**）、六节索引。四节与五节其余部分主要是指导父代理如何选 `subagent_type` × `model`，对子代理自身价值低，故省 token 略去。

**5.4 为什么在子代理版保留完整版、主会话只留索引**：这是一处**有意的例外**。第 1 层子代理可以再派第 2 层（受二节的嵌套上限约束），派发时同样要给 `name` / `description`，而 `agent-dispatch` 硬门禁对**子代理发起的** `Agent` 调用一样生效。但两者处境不同——主会话每轮注入，被拦一次就学会了，索引足够；子代理**只在启动时注入一次**、且更可能对规范一无所知，被拦后只能靠 deny reason 反推。所以主会话走「索引 + 硬门禁」，子代理付这 2.5k 字符换「一次就写对」。章节编号与主版严格一致（子代理版为一、二、三、五、六，缺四），同一条规则不出现两套编号。

**外部写操作授权（原 dws 章）已从本插件移出**（2.0.0）：钉钉 dws CLI 的写授权改由 `radnove-core` 插件的 `hooks/pre-tool-use-dws-write.sh` 承担，`PreToolUse` 命中写子命令时输出 `permissionDecision: "ask"`，把「须获用户当次明确许可」这个语义要求变成 harness 强制的确认弹窗——比每轮注入 918 字符的自觉约束强得多。

> 完整注入文本见 `hooks/working-discipline.js` 里的 `SECTION_*` 数组。实测体积（3.6.0 guard 审计后）：`SessionStart` 7142 字符、`UserPromptSubmit` 1342（无图轮）、`SubagentStart` 7174。三者各自独立受 hook 输出硬上限 10000 约束。历史值：3.5.0 6886 / 1342 / 6918、3.5.0 改造前 7353 / 1401 / 7345、3.3.1 `SessionStart` 6832 / `UserPromptSubmit` 1163 / `SubagentStart` 6865、3.3.0 6328 / — / 6361、3.2.0 5985 / — / 6018、3.1.0 主会话每轮 6717、3.0.0 每轮 9165。
>
> 3.16.0 实测：`SessionStart` 8749、`UserPromptSubmit` 4085（无图轮）、`SubagentStart` 9050。每轮层净增 **+2051**，来自新增的「派发 `Agent` 的完整调用形态」整节——这一笔是用户当面要求付的，理由见下方「3.16.0 完整调用形态」。会话级反降 **−649**（5.4 正文压成索引）。**中途一度把 `SubagentStart` 推到 10758、越过 10000 硬上限**：新段与既有 5.4.1~5.4.3 逐句重合，两份一起注入；删去重合段后回落。教训——加新段前先想清楚它和哪一节重复，别只看新段自身多大。
>
> 3.12.0 实测：`SessionStart` 8304、`UserPromptSubmit` 2034、`SubagentStart` 7503，另加 `dispatch-ledger.js` 每轮 108–231 字符（3.15.0 实测：常态 108、0 派发追加时 125、检索过线追加时 231）。每轮层净增 **+428**，来自零章自查触发点拆成两个检查点、以及检查点②里那个可照抄的 `Agent` 调用骨架。涨这一笔的理由见下方「3.12.0 委派强化」。三个事件均在 10000 硬上限内。
>
> 3.11.0 实测：`SessionStart` 8304、`UserPromptSubmit` 1606、`SubagentStart` 7503。净增 **+6 / +264 / +80**，主要来自零章新增的第 3 档（≥3 文件同类改写交 `general-purpose`）——每轮层涨得最多是刻意的：该档的失效场景（15 连 `Edit` 撑爆上下文）恰好发生在长会话中段，只在 `SessionStart` 说一次接不住。三个事件均在 10000 硬上限内。
>
> 3.9.0 实测：`SessionStart` 8298、`UserPromptSubmit` 1342、`SubagentStart` 7423——主会话版摘除 3.1/3.2/3.6 三条后仍高于 3.6.0 的历史值，差额来自 3.7/3.8 期间六章与五章的净增；三个事件均在 10000 硬上限内。
>
> 3.6.0 的净增是 **+256 / 0 / +256**，全部来自六章（hook 边界清单）的三处如实改写——总述加了「判据是文本形态匹配而非语义判定，撞到明显误判就报告用户拍板」、`cd` 条目点明「只认裸 `cd` 开头一种形态，`pushd` / `source` / `eval "cd …"` 同样污染却拦不住」、`Write`/`Edit` 条目点明「挂 `PostToolUse`，触发时文件已经写完了，指望不上它兜底」。用字符换准确性，不是没压到。
>
> **数的是字符（JS 的 `.length`），不是字节**——本文件正文以中文为主，UTF-8 下 `wc -c` 得到的数约为字符数的 2.1 倍。2026-07-31 曾据 `wc -c` 的 15138 误判"已超 10000 硬上限"，实际字符数只有 7167。下面的 verify 命令解析 JSON 后取 `len()`，别退回用 `wc -c` 估。
>
> 改完必跑三条 verify（长度不达标就别提交）：
> ```bash
> for E in SessionStart UserPromptSubmit SubagentStart; do
>   echo "{\"hook_event_name\":\"$E\"}" | node hooks/working-discipline.js \
>     | python3 -c "import sys,json;d=json.load(sys.stdin)['hookSpecificOutput'];print(d['hookEventName'],len(d['additionalContext']))"
> done
> ```

### 派发命名规范：`name` 是 schema 里查不到的字段（注入文本 5.4 节）

**事故来源（2026-07-25）**：用户截图的在飞 agent 面板上，5 个子代理是这样显示的——

```text
> ● main
  ○ ontology-drain      你是第 1 层子代理（orch...
  ○ verdict-part1       你是第 1 层子代理，可派...
  ○ verdict-part2       你是第 1 层子代理，可派...
  ○ general-purpose   [sonnet] 映射 16 个 spe...
  ○ verdict-part3      你是第 1 层子代理，可派...
```

面板左列显示 `Agent` 工具的 `name`（未指定时回落显示 `subagent_type`），右列显示 `description`。这一屏同时暴露三个问题：四个 `name` 都不带模型档次前缀，用户看不出这批在飞任务烧的是 `sonnet` 还是 `opus`；这四个的右列全是 `prompt` 原文的开头「你是第 1 层子代理，可派…」，既把内部提示词暴露到 UI 上，又让四行描述完全同质、面板彻底失去"谁在做什么"的信息量；唯一 `description` 没抄 prompt 的那行（`[sonnet] 映射 16 个 spe…`——前缀在 3.4.0 前是硬要求、现已软放宽不要求）反过来没给 `name`，左列回落成裸的 `general-purpose`。

对应的注入规则分四条：`name` 必填且同会话内不重名、格式 `模型名-任务语义`；`description` 必填、3-5 词任务摘要（3.4.0 起不带 `[模型名]` 前缀，模型档次由 `name` 体现）且**禁止与 `prompt` 共用同一段文字**；同批并发的名字必须互相可辨（`verdict-part1/2/3` 应改成把分片依据写进名字的 `sonnet-verdict-spec-01-05`）；`Workflow` 的 `meta.name` / `meta.description` / `meta.phases[].*` / `agent(prompt, {label})` 的 `label` 同规，其中 `meta.description` 会出现在权限确认弹窗里，粘 prompt 等于让用户在弹窗里读一段内部指令。

#### 为什么 AI「总是忘记传 `name`」：两套约束不同源

这不是注意力问题，是**结构性缺陷**。`Agent` 工具的 JSON Schema 里 `properties` 只声明了六个字段，还写着 `additionalProperties: false`：

| 约束 | 载体 | 关于 `name` |
|---|---|---|
| 调用层能接受什么 | `Agent` 工具 JSON Schema | `description` / `prompt` / `subagent_type` / `model` / `run_in_background` / `isolation` —— **不存在此字段** |
| 本插件要求什么 | `agent-dispatch` hook | 必填，格式 `<model>-<语义-kebab>` |

后者是前者的真子集**加一个额外必填项**，而加的这项 schema 里查不到。AI 构造工具调用时照 `properties` 列表生成参数，一个字段表里不存在的字段不会被"想起来"——所以缺 `name` 是必然，不是疏忽。

但 `name` 确实是运行时的一等公民，只是 schema 声明漏了。实证（2026-07-29）：一次带 `name` 的 `Explore` 派发，其元数据文件 `<项目 transcript 目录>/subagents/agent-a89132b5b2d9d0f67.meta.json` 内容是

```json
{"agentType":"Explore","description":"dbops 翻译 dimId/nodeId 并核权重",
 "name":"sonnet-dbops-translate-weight-ids","toolUseId":"toolu_01LFRkf1uMvs9RwnMpcoU9ca",
 "spawnDepth":1,"model":"sonnet"}
```

`name` 被接受并落盘。此外 `Agent` 工具的说明文字本身也反复提到它存在：「Use SendMessage with the agent's ID or **name** to continue a previously spawned agent」、「Use the raw `agentId` only when the agent **has no name**, or when a newer agent took the name」。一个能"没有 name"也能"被新 agent 抢走 name"的东西，显然是运行时的真实字段。

**3.0.0 的处置：缺 `name` 不再 deny，改用 `updatedInput` 自动补名放行。** 理由是 deny 只是把一次必然的返工固化下来——AI 看不见这个字段，罚它没有教育意义。同时注入侧（5.4 与 5.4.1）把「schema 里查不到它」这个根因和「凡调 `Agent`，先写 `name`，再写别的」这条硬编码前置写进去，让 AI 尽量自己命名，因为自动名的语义很弱（见下一章）。

**`subagent` 与 `teammate` 不必分两套规则**：是同一个 `name` 概念，差别只在用途权重。teammate 场景下 `name` 是 `SendMessage({to})` 的寻址键（没名字就只能用 raw `agentId`）；一次性 subagent 场景下它主要用于面板显示与事后追溯。两种场景的命名格式要求完全一致。

### 核实类任务必须写明追踪停止条件（注入文本 5.6 第 4 项，3.5.0 加）

**观察来源（2026-07-31）**：主会话派两个子代理核实**同一处注释**是否准确，拿回相反结论。前者 `grep` 到注释里提及的方法名不在本文件，报「疑点」；后者读了跨类调用链，确认「无碍」。

复盘结论是**两者的停止条件不同，不是能力差异**。派发 prompt 只写了核实目标（"确认这处注释是否准确"），没写追到哪一层为止，于是两个代理各按自身成本感觉停下：一个的隐含停止条件是「符号在本文件内是否可解析」，另一个是「跨类调用链上是否仍然成立」。两个条件各自自洽，都能产出一份看起来完整的回执，而**两份回执都没交代自己停在哪一层**——所以"结论相反"这件事无法归因，只能重跑一遍才知道分歧出在深度而非事实。

这类损失有个特征：它不出现在任何 diff 里。代码没改错、回执没写错、没有任何 guard 会命中，只是白烧了一轮 token 且一度以为共用发布线上真有问题。因此它以前从未被记录过。

还有一半成因在被核实的对象上：那条注释把**跨类的语义写成了本地语义**。读者（人或 AI）在本文件内找不到闭环，就会把"找不到"当成"有问题"。这类注释的危害不是信息错误，而是把验证成本转嫁给每一个后来读它的人，且每次都以「疑点」形态冒出来——它正是决定大多数读者停在第一层的原因。所以注入文本把它写成**触发信号**：被核实的注释 / 文档 / 命名描述的是跨文件或跨类行为时，本文件内验证必然不闭环，停止条件至少要给到被调方。

**为什么落三处而不是只加一段**（用户当轮的要求是"保证指令遵循度"）：

| 落点 | 注入时机 | 约束谁 | 单独失效的场景 |
|---|---|---|---|
| 5.6 第 4 项 | `SessionStart` | **派发侧**：停止条件写进【约束】、交代深度写进【期望输出】 | 根治位置，但只在会话早期注入一次，随轮次被推远 |
| 每轮自查第 4 条 | `UserPromptSubmit` | 派发侧 + **主会话自己做的核实**（5.6 只管派出去的那部分） | 每轮重申不会衰减，但仍是软约束，AI 可以读到而不执行 |
| 子代理版开头 | `SubagentStart` | **执行侧**：不论父代理有没有给停止条件，都必须在回执里交代实际停在哪层、哪些边界没追 | — |

第三处是遵循度的关键。前两处都作用在派发侧，一旦漏写就同时失效；而第三处让层级差异**暴露在回执里**——即使派发时忘了给停止条件，两份结论相反的回执也会各自带着"我追到哪层"，分歧当场可归因，不必重跑。它和已有的「回执只回『已完成』视为不合格」并列，放在子代理版正文第二、三句，位置刻意靠前。

**为什么不做成 guard**：判据是"这个任务是不是核实类""prompt 里有没有给停止条件"，两者都只能靠正则猜语义，正撞本文档开头那条核心设计原则（判据靠猜 → 别做成 `deny`）。硬拦会复现 3.0.0 已经付过学费的失败模式——AI 做对了却过不去。漏提醒的代价远低于此。

### 3.5.0 遵循度改造：为什么"加强措辞"没用，改结构才有用

做法是派两个只读代理独立诊断同一份注入文本——一个查遵循度失效机制，一个做字符级冗余量化。两份结论互补、无冲突。

**最有价值的证据是诊断代理自己违反了它正在分析的规则**。它整读了 518 行文件（违反当时的"禁止无目的全文件读取"）、三次超 20 行输出没派子代理、并写了独立 `cd` 被 `bash-guard.js` 当场拦回。它明确写道违反时"没有犹豫"——因为那两条规则**既没写违反后果、也没写例外条款**，而任务收益是明确的。所以纯禁令的真实后果不是引发权衡，是引发**无声跳过**。

同一份报告里还有一个正向对照：同一条 `cd` 规则，以软文本注入时它读过却违反，被 `PreToolUse` 硬拦后**一次就改对了**——因为 finding 文案里给了 `(cd /abs && cmd)` 这个可照抄的模板。判据准 + 文案给模板 = 一次改对；这是 hook 值得存在的样子（另见仓库根 `.claude/rules/hook-restraint.md`）。

本批改动按四类归因，不是逐句润色：

**一是删掉"哪些违规不会被拦"的执行状态披露。** 同一份注入里"`name` 必填"被"漏了会自动补名放行"抵消了三次（5.4.1 末句、5.4 硬门禁的"不拦"bullet、5.4 索引末句、六章 Agent 条目末句）。按成本最小化行动的读者读完得到的净结论是"可以省"。这是整份纪律里最直接的自我削弱形态，改法统一为把"是否会被拦"换成"违反后你会拿到什么"。

**二是删版本史。** `3.4.0 起软放宽`（4 处）、`[haiku] 前缀 3.4.0 起不再拦`、`靠关键词猜语义的 guard 已全部移除`、`2026-07-30 两次会话实测`、dws 归属交代，全部清掉。判据是：讲"规则从哪版变过"→ 删；讲"规则为什么成立"→ 留。所以 `orderIndex: 15` / HTTP 204 那个反例保留了——它是"2xx 不等于字段生效"唯一的说服力来源，删了那条规则就退回成无理由禁令。

**三是给纯禁令补判据与边界。** 一章两条全改：`禁止无目的全文件读取` 补上"核对整份规范时直接整读、分片会漏跨段冲突"（原写法与 `Read` 工具自身"recommended to read the whole file"的建议正面冲突且没有压制）；`>20 行输出交子代理` 改为"先收窄再跑，>200 行且需逐条分析才派"——原阈值 20 行几乎任何 `grep` 都越线，与零章"同消息多调用最优先"的成本排序矛盾，而且对第 2 层子代理**根本不可执行**（它受嵌套上限约束不能再派），无法执行的指令会连带降低整章可信度。另外 3.3(b) 加了裁决句（用户或父代理明确要求清单时按其要求，禁止的是"用短语替代因果"而不是禁止编号本身），并删掉 `上限 16（动态）` 里那个凭两个字就取消阈值硬度的括号。

**四是修三处自相矛盾或不可执行。** 5.1 表格把"大输出命令"从 `general-purpose` 移到 `Explore`（原表格指向 `general-purpose`，下一行却禁止只读任务用它，读者的低成本出路是干脆不派，正好抵消第一章的委派要求）；子代理版零章的授权声明**移到首段并去掉"可能"**（原来沉在章末且措辞软化，而主会话版明确标注"先读这段，再看下面的默认动作"，说明作者知道位置是关键变量）；子代理版"其余条款见主会话版"改为**自带信息**（子代理拿不到主会话版，原写法违反了同一份注入里 3.2 的"引用自带信息"）。

另补两处子代理版的覆盖缺口：**无用户通道的转译总则**（本份凡要求"问用户 / 让用户核对 / 在主对话复述"的条款，改为写进回执交父代理转达——子代理遇到这类条款只能跳过，而"跳过一部分条款"一旦开始就没有边界规定跳到哪为止），以及 **md 受众判定要求**（子代理版不注入四章，这条此前对子代理完全缺失，而子代理正是产出 md 报告的主力）。

压缩侧最大单笔是 `SECTION_NAMING` 的"本节有硬门禁"小节压成一句指针（它整段复述了六章的 `Agent` 条目，-395 字符），其次是 team 模式那条 846 → 约 380（该常量被 `SessionStart` 与 `SubagentStart` 共享，省下的字符按两份算）。

净变化是 SessionStart -467、UserPromptSubmit -59、SubagentStart -427，**远小于冗余审计估算的可压空间**。差额是同批新增的判据、后果句与那两处覆盖缺口——属于"遵循度优先于压缩"的取舍，不是没压到。改后用双向核对验证：25 项应保留的规则锚点全部仍在，8 项应删除的旧表述全部清除。

### 3.6.0 审计：用新立的仓库规则回过头审判本插件自己的三个 guard

**方法本身是这次的主要产出**：先在仓库根立下 `.claude/rules/hook-restraint.md`（"默认不加 hook，能 100% 机械判定才可以"，含判据分级、强度阶梯、新增 hook 前必答的五个问题），然后**立刻拿它回溯审判已经上线的东西**，而不是只用来把关新增。派了两个 opus 只读审计构造真实 payload 打真 guard：`bash-guard` 103 条、`write-guard` 27 条、`agent-dispatch` 28 条。三份结论指向同一个方向——**写 guard 的人会系统性高估自己判据的精度**。

**三个 guard 的自述全部被真 payload 证伪**，而且每一处自述当初写下时都是真诚的：`write-guard.js` 写着"误判空间为零"，实测三类误判（扩展名不能区分源码与数据/产物/依赖、行数带 `+1` 偏移、`basename` 不能区分本项目与第三方）；`bash-guard.js` 写着 `cd` 由 shell-parse "精确定位"，实测 19 类真污染写法放行、heredoc 正文被误杀且 hint 无解、`echo "(start" && cd /tmp && echo "end)"` 一个假括号配对就让真 `cd` 隐形，`--headed` 因全局字符串扫描退化成一个 `echo --headed;` 就能满足的口令；`agent-dispatch.js` 写着"判据全部取自确定字段、误判空间接近零"，而 `PROMPT_LEAK_PREFIXES` 是句式近似判定、`LEAK_MATCH_MIN` 那条 prompt 重合检查的前提根本不成立（合法 description 与 prompt 的 `【目标】` 段天然写同一件事）。

**最值得记住的一条与判据精度无关，而与"文案漂移"有关。** `write-guard` 的**效力等级**在注入文本第六章里被错误升级成了"会被拦"——而它挂 `PostToolUse`，文件已落盘、不回滚、本轮继续（三条证据见第四章）。后果不是抽象的：**主代理据此以为"写出超长文件有机械兜底"，整整一轮都在这个错误前提下工作**。这里真正的教训是——hook 的**实际效力**（代码里挂哪个事件、走 stderr 还是 JSON、有没有输出 `continue: false`）与**描述它的文案**（源码注释、注入文本、README）会各自独立漂移，而**没有任何环节会自动核对两者**。判据可以靠测试用例守住，效力等级只能靠人定期回读代码确认。这也是本次同时改了源码注释、注入文本、本 README 三处的原因：三份都是"文案"，漏改任何一份都会重现同一类事故。

**处置口径由用户逐条拍板，四项全选"修误杀 + 收窄，不删"**（依据 `hook-restraint.md` 第 4 条：判据影响硬阻断行为，AI 只报不改）。已落地的改动：`stripHeredocs()` 剥离 heredoc 正文、no-op `cd` 的 `realpath` 与 `$PWD` 识别、后台化片段放行、finding 违规片段截断 120 字符、`agent-browser` 判定收窄到单次调用的 tail、`--help` 放行、命令名位置判定、行数 `+1` 偏移修复、依赖与产物路径排除、源码扩展名补齐、CLAUDE.md 限定当前项目树内、`prompt-prefix-overlap` 检查整条移除、`autoName()` 哈希补 `description`。**43 条回归用例全绿**，两侧都覆盖——既验旧版误杀现在放行，也验旧版正确拦截的仍然拦得住。

注入文本同步改了三处（六章总述、`cd` 条目、`Write`/`Edit` 条目），净增 `+256 / 0 / +256` 字符。这是**用字符换准确性**：一份把自己效力说大了的纪律文本，比一份短一点的更贵。

---

### 3.12.0 委派强化：检查点拆分 + 派发账本

**问题**：注入天天在，派发率照样是 0。2026-08-02 在本仓一次跨插件排查里，主代理连续多轮做多文件调查、`Agent` 调用 **0 次**，而它每轮都读到了零章。逐条查下来是四件事叠加：

1. **写好的强化没生效**。源码与 marketplace clone 都是 3.11.0（含第 3 档「≥3 文件同类改写」），但 `installed_plugins.json` 的 `installPath` 仍指向 3.10.0——cache 里两份目录都在，指针没切。同期 `task-keeper`（1.0.0 vs 2.1.0）、`radnove-core`（5.0.1 vs 5.2.x）撞的是同一个根因。**改注入文本前先确认线上跑的是哪一版**，否则改了个寂寞。
2. **检查点自带逃生舱**。旧版唯一的自查触发点是「连续 3 次单工具调用 → 第 4 次合并进同一条消息」，补救动作是**合并**——而合并永远不需要派 subagent。满足它的最省力路径正好绕开它想推动的行为。事故现场就是这么走的：反复「一条消息两个 Bash」，检查点从不触发，派发 0。
3. **读侧扇出没有可数触发**。(2) 档写的是「跨文件检索、**可切分**子任务」，"可切分"是语义判断；(3) 档虽可数但只覆盖写侧。而读侧（本轮要查 N 个互不相关的问题）才是最常见的可派场景。
4. **摩擦只加不减**。四段式 prompt、5.6 的四项必含、核实类停止条件、`agent-dispatch` 对 `model`/`description` 的 deny——派发的边际成本被系统性抬高，而"自己做"的成本是零。抬门槛与推行为方向相反，会互相抵消。

**改法**：

- 自查触发点拆成**两个相互独立**的检查点，明写「满足①不等于满足②」堵掉互相顶替。①管合并；②专管派发，判据是纯计数：**本轮已自己发起 ≥6 次只读检索，且仍有 ≥2 个互不依赖的待查项 → 必须派 `Explore`**。
- ②里直接给**字段顺序正确、可照抄的 `Agent` 调用骨架**（多付约 250 字符）。依据是 `bash-guard` 的实证：finding 里给可照抄模板时 AI 一次改对，只写"禁止 X"则反复试错。
- 新增 `hooks/dispatch-ledger.js`（`UserPromptSubmit`，纯注入零拦截），从 `transcript_path` 现算「主会话工具调用 N 次 / `Agent` 派发 M 次」，每轮一行。**这是本次唯一的新反馈回路**——`task-keeper` 的队列快照之所以有效，靠的正是把磁盘现算的状态摆在眼前，而不是重复一遍规则。

**账本的三条设计约束**（都有回归用例钉住）：

| 约束 | 为什么 |
|---|---|
| 判据失灵时**不注入**，不注「0 派发」 | 注 0 会把"我没数到"说成"你没派过"，比不注入更糟 |
| 主会话调用数 < 12 不注入 | 会话刚起步谈不上派发率，每轮注一行是噪音 |
| `isSidechain === true` 整行不计 | 子代理内部的工具调用不属于主会话的派发决策 |

它读 transcript 但**不构成实证 3 的反例**：那条讲的是「靠回读 transcript 做**门控判定**」不可靠，失败模式是 deny 把 AI 卡死；本 hook 是纯注入，读不到就沉默，最坏结果是数字偏小。

首次上线即自证：拿事故现场那个会话跑出「239 次调用 / 24 次派发」，拿写下这段文字的会话跑出「118 次调用 / **0 次派发**」。

### 3.15.0 账本升级：从「报数」到「报越界」

3.12.0 的账本报的是**全会话累计**（"73 次调用 / 3 次派发"），而检查点②的判据是**自上次派发以来 ≥6 次只读检索**。两个数不是一回事——累计值再大也答不了"这一段连查了几次"。

2026-08-04 实证（本仓会话）：主代理连发 **9 次**只读检索才派出第一个 `Explore`，这 9 次分散在三轮里。它每轮都读到了账本，也每轮都读到了检查点②，但账本给的数字和判据要的数字对不上，而检查点②原文写着「**你自己数得出来**」——它数不出来，那要求回溯自己的调用历史。

改法是把这个数补上，并把注入文本的口径改齐：

| 位置 | 3.12.0 | 3.15.0 |
|---|---|---|
| `dispatch-ledger.js` 的 `count()` | 两个累计数 | 加第三个：顺序扫描，遇 `Agent`/`Task` 清零、遇 `Read`/`Grep`/`Glob`/`Bash` 加一 |
| `dispatch-ledger.js` 的 `render()` | 报数（0 派发时追加一句） | 报数 + 过线时点名，并说清"另一半判据只有你知道" |
| 零章检查点②的措辞 | 「**本轮**已发起 ≥6 次……**你自己数得出来**」 | 「**自上次派发以来** ≥6 次……**次数那一半不用你数**，账本会点出来」 |

范围从"本轮"改成"自上次派发以来"是必要的：每轮重置会让上面那种跨三轮的连查永远不过线。

**两处已知不精确，都朝高估方向，如实记在源码文件头**：(a) `Bash` 一律计入，不区分只读与写——要区分就得解析命令语义，那正是 `bash-guard` 实测 19 类漏报的老路，宁可多提示一次；(b) `MAX_BYTES`（8MB）尾部截断时，若真正的上一次派发落在被截掉的头部，计数从截断点重新起算，偏大。两者都只影响提示时机，不影响任何操作。

**为什么仍然不做成硬拦截**：检查点②是合取判据，另一半"手上是否仍有 ≥2 个互不依赖的待查项"是 AI 脑内状态，transcript 里没有任何字段能提取。只对可算的那一半 deny，会误杀"次数够了但待查项只剩 1 个"的正当情形。所以账本只把数字和判据摆出来，答不答仍靠自觉——**这正是仓库规则里「判据要猜语义就退回注入」的正常结果**。

通用教训：**能机械算的那一半，就不该写进注入文本让 AI 自己数。**注入文本擅长的是"告诉它该做什么"，不擅长"让它记住自己做过什么"。

### 3.16.0 完整调用形态：用一个可照抄的 JSON 去对抗一张字段表

**问题**：`name` 漏填这件事，从 3.5.0 提醒到 3.12.0 给骨架，一直没治好。2026-08-04 本仓一次会话里，主代理 7 次 `Agent` 派发**漏 `name` 7 次**，全靠 `agent-dispatch` 的自动补名兜底——而漏的那几次它刚读过检查点②里的紧凑骨架。

**根因不是提醒不够响，是提醒与构造动作不在同一个形态上。** 模型构造工具调用时照的是工具的 JSON Schema 字段表，而 `Agent` 的 schema 声明了六个 `properties` 且 `additionalProperties: false`，`name` **不在表内**。它对构造过程不是"忘填的必填项"，是"不存在的字段"。用散文提醒去对抗一张结构化字段表，形态上就不对等。

更麻烦的是 `additionalProperties: false` 这一句会让「遵守 schema」与「遵守本纪律」看起来互相冲突，而 schema 是工具层权威、更容易赢。

**改法两条**：

1. **给一个可整体照抄的完整 JSON**，`name` 排第一位——把照抄的对象从 schema 换成它。附 `prompt` 四段式模板、六字段硬要求表、三条不适用情形（`SendMessage` 唤醒 / `Workflow` 的 `label` / 第 2 层子代理不许再派）。
2. **显式写出优先级**：「schema 描述的是工具层能接受什么，本段规定的是本会话必须传什么；两者不一致时一律以本段为准。」不写这句，那个表面冲突就一直在。

**落点是每轮层 + 子代理层，不进会话级**——它要对抗的东西（schema 字段表）每轮都在，同零章的理由。子代理层也要，因为第 1 层子代理可以再派第 2 层，面对的是同一张 schema。

**代价与一次越界**：每轮层 2034 → 4085。中途 `SubagentStart` 一度到 10758、**越过 10000 硬上限**——新段与既有 `SECTION_NAMING` 的 5.4.1~5.4.3 逐句重合。删去重合段（只留 `SendMessage` 寻址键复用禁令、提示词泄露第二条成因、`Workflow` 命名、keeper 固定名四件新段没讲的）后回落到 9050，同时会话级的 5.4 也压成索引、反降 649。

这条教训值得单独记：**注入文本的体积风险不在新段自身多大，在它和哪一节重复。**加段前先找重复，别只量新段。

## 二、拦截：`agent-dispatch` 守 `Agent` 派发的结构字段

**触发条件**：`tool_name` 是 `Agent`。注意**不匹配旧工具名 `Task`**——旧名环境下的 `tool_input` 可能压根没有 `name` / `model` 字段，强制校验会造成永久性误拦，fail-open 优于误伤。

### 拦什么：8 项结构校验，多条一并列出

这类问题往往同时出现好几个（`name` 前缀不符 + `description` 抄 prompt + 超长），`findings` 聚合成一条 reason 一次报清，才能一次改对：

| # | 校验 | 为什么 |
|---|------|--------|
| 1 | `model` 缺失或不在 `sonnet`/`opus`/`fable` | 纪律要求显式指定，禁止默认回落。**这一条命中时额外附完整路由表**帮助选档。`model: "haiku"` 单独给一条 finding（「已从可选档次中移除，最低档是 sonnet」）而不是泛泛报「不在三档之内」——它是旧纪律下的合法档，是最高频的误填 |
| 2 | `name` 不以 `{model}-` 或 `{model}_` 开头 | 前缀必须与实际 `model` 一致。**分隔符 `-` 与 `_` 等价**（`NAME_PREFIX_SEPARATORS`，3.6.0 加）：第 3 项那条原生正则本来就允许下划线，只认连字符会把 `sonnet_review_login` 这种「照文档正则写出来的合法名」误拦。`haiku-` / `haiku_` 开头单独识别并给「改成 `sonnet-<原任务语义>`」的精确改法，避免回落到泛化分支后建议出 `sonnet-haiku-grep-refs` 这种把废弃档次名留在任务语义里的错名 |
| 3 | `name` 不满足 `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` | Agent 工具的原生约束，提前拦下来并给清楚提示（写中文会被工具直接拒）。3.6.0 起改法建议里的任务语义先过 `toAsciiKebab()`——旧实现把含中文的原 `name` 原样回显进「改成 xxx」，AI 照抄会再撞一次同一道闸 |
| 4 | `description` 缺失，或 strip 掉可选的 `[模型名]` 前缀后没有正文 | 必填且必须有 3-5 词任务摘要正文。**3.4.0 起不再要求 `[模型名]` 前缀**（软放宽）：name 的模型前缀已是第 2 项强制校验、在飞面板与 description 并排显示，模型档次由 name 一处表达即可，description 再带前缀是冗余（每行模型名出现两次）。仍带了前缀不拦，先 strip 再做正文/句式检测。**但 `[haiku]` 是例外**：3.6.0 起不再静默剥离，而是单独给一条 finding（`description 前缀 "[haiku]" 用了已移除的档次;本插件无 haiku 档`）——静默吞掉会让人以为 haiku 仍是合法档 |
| 5 | `description` 正文以角色设定句开头（`你是` / `您是` / `请你` / `作为一名` / `You are` / `Act as` 等 14 项） | 把 prompt 原文抄进 `description` 的高置信特征。**这是本 guard 唯一一条近似判据**（详见下方「判据精度」）。3.6.0 从词表里移除了 `#`、`【`、`Your task` 三项：前两个会命中任何以 markdown 标题或中文书名号开头的**合法**摘要，第三个与 `You are` 的角色设定语义不等价（`Your task summary…` 是合法摘要） |
| 6 | `description` **原始串**超过 60 字符 | 纪律要求 3-5 词摘要，超长说明塞了 prompt 内容。**按原始串计长、不减去 `[模型名]` 前缀**（3.6.0 改）：旧实现拿 strip 后的正文比，等于给带前缀的写法白送 7-9 个字符额度，「容错接受的旧写法」反而变成收益 |

| 7 | `subagent_type` 含冒号（插件专用 agent）而 `name` 不含它的任一身份词 | **3.12.1 加**。在飞面板只渲染 `name`、**不渲染 `subagent_type`**，于是 `name="sonnet-dbg-open-audit"` + `subagent_type="task-keeper:debug-keeper"` 这组派发在面板上完全看不出派的是 keeper，用户找不到自己刚被托管的那条队列（2026-08-03 真实事故）。判据是纯子串包含：取冒号后 slug → 拆 ASCII 词 → 滤掉 `GENERIC_IDENTITY_WORDS`（`agent`/`use`/`main`/… 这些不携带身份的通用词）→ 要求 `name` 小写化后含**任意一个**。内建 `Explore`/`Plan`/`general-purpose` 不校验（权限差别不是常驻身份）；slug 的词被黑名单滤空时整条跳过（`foo:use`），fail-open。`autoName()` 同步加了身份词前置，避免自动补出一个 guard 自己不放行的名字 |

| 8 | `subagent_type` 的 slug 是 `debug-keeper` / `chore-keeper` 而 `model` 不是 `opus` | **3.13.0 加**。这两个 keeper 在自己的定义文件里已写 `model: opus`（`task-keeper/agents/debug-keeper.md:5`），但 `Agent` 工具的 `model` 参数**优先级高于 agent frontmatter**（工具描述原文 "Takes precedence over the agent definition's model frontmatter"），主会话显式传 `sonnet` 就把它顶掉了；而「keeper 固定 opus」这条规则只写在 `tk-debug` / `tk-chore` 两个 SKILL.md 正文里，task-keeper 每轮注入的 TRIAGE 文本（`hooks/lib/keeper_routing.py:73`）压根没提 `model`——主会话没先调那个 skill 就读不到它，只读到本插件的三档标尺「没 `opus` 触发信号就留在 `sonnet`」。2026-08-03 事故：会话 `8477c246` 派出 `{"name":"sonnet-debug-keeper-085","model":"sonnet","subagent_type":"task-keeper:debug-keeper"}`，前七项 check 全过（前缀与 `model` 一致、含身份词 `keeper`），档位静默落在 `sonnet`。判据是完整锚定正则 `/(^|:)(debug|chore)-keeper$/` + `model` 与 `'opus'` 的等值比较，两个都是确定字段。**这不是 3.0.0 删掉的那条档位判据**——那条扫 prompt 里的「不变量」「根因」猜任务难度，这条只看 `subagent_type` 是不是那两个固定档类型。**白名单式枚举**：第三方 keeper-like agent（`foo:queue-keeper`）不在表内、不牵连，加成员要显式改 `FIXED_OPUS_PATTERN`，不做"含 keeper 就算"的模糊匹配。假阳性面是「故意降档跑 keeper」，本 guard 不给逃生舱（只能 `AGENT_DISPATCH_GUARD=off`）——用户拍板时明确选 deny 而非 ask，口径是"keeper 降档没有正当理由"；日后若出现真实需求，正确处置是整条降级为 ask，不是加咒语 |
| 9 | `subagent_type` 的 slug 是 `debug-keeper` / `chore-keeper` 而 `name` 不满足 `^opus-<slug>-[0-9a-z]{4}$` | **3.14.0 加，2026-08-04 用户拍板改判据**。与第 7 项不是一回事：第 7 项只防遗忘、随便塞个身份词即可过闸；这条要求 name 落在固定前缀 + 4 位小写字母数字短哈希的形态里，因为唤醒方是**照文档拼名字**而不是照面板抄名字。2026-08-03 事故（会话 `8477c246`）：keeper 被派成 `sonnet-debug-keeper-085`，38 分钟后主会话按 `agents/debug-keeper.md:31` 写的固定名 `debug-keeper` 唤醒，`SendMessage` 返回 `No agent named 'debug-keeper' is reachable.`，随后它直接又派了**第二个** debug-keeper 实例——同一会话里两个实例先后持有 `.keeper/<交付id>/debug/` 的独占写权限，单一写者模式失效。3.14.0 最初的判据是把 name 钉死成逐字相等的固定三段名 `opus-debug-keeper`，但这条本身埋了新坑：同一会话内前一个 keeper 实例结束后，若后来者又派成逐字相同的固定名，`SendMessage` 的 latest-wins 寻址规则会让"占名"本身变得不可靠——旧实例的名字被新实例顶掉，唤醒方无法分辨这次唤到的是哪一个。2026-08-04 改为要求 name 带 4 位短哈希后缀（如 `opus-debug-keeper-4bb6`），逼"名字不可预测"这个事实被强制暴露出来：唤醒方**必须**先读登记文件才能拿到当前有效的 name，机制不会退化成"记得住固定名就不用读"的可选项。登记文件由 `task-keeper` 插件新增的 `PreToolUse(Agent)` hook 写：命中 keeper 类 `subagent_type` 时把本次实际用的 name 落进 `.keeper/<交付id>/.keeper-instance.json`（形如 `{"debug":{"name":"opus-debug-keeper-4bb6","ts":"<ISO8601>"}}`），主会话唤醒前先读它，读不到才首次派发。判据是完整锚定正则 `^opus-<slug>-[0-9a-z]{4}$`，前缀部分仍是确定字段比较，只有后 4 位是形态匹配。**覆盖边界（如实记录，不再写"零误判"）**：假阴性面是"AI 可以随便编 4 个字符而不是真的取哈希"——判据只能校验形态、校验不了随机性，但这是可以接受的：本 guard 真正要防的是"同名撞车导致 `SendMessage` 寻址混乱"，任意 4 位后缀（哪怕是编的）都能防住这一点；防不住的是"AI 故意每次编同一个后缀"，但那属于蓄意绕过纪律，不是本 guard 该拦的范畴。假阳性面是合法的 4 位小写字母数字后缀，无已知误杀。`autoName()` 同步改为对 keeper 补出带哈希的名字（复用与非 keeper 分支相同的 `shortHash()` 输入口径），`allowWithName()` 的提示文案也同步改写——避免又一处「效力与描述各自漂移」 |

**判据精度：不要再写成"零误判"。** 3.6.0 前这里写的是「判据全部取自确定字段，误判空间接近零」，审计用 28 条真实 payload 证伪了后半句。八条里有七条确实是确定字段比较（`model` 在闭合枚举 `MODELS` 内、`name` 匹配完整锚定正则 `NAME_PATTERN`、`name` 以 `<model>-`/`<model>_` 开头、`description` 是否为空、`description.length > DESC_BODY_MAX`、第 7 条的身份词子串包含、第 8 条的 `FIXED_OPUS_PATTERN` 锚定匹配 + `model` 等值比较）——同一输入必得同一结论、可人工复核。**第 5 条不是**：它靠"正文以某个句式开头"近似判断"这是角色设定句而不是任务摘要"，本质在猜语义。已知边界写在 `hooks/guards/agent-dispatch.js:14-23`——假阴性是角色设定句不在开头（`本次请你扮演审计员…`）或换用未列举句式（`扮演` / `担任` / `Pretend you are`）；假阳性是任务摘要本身合法地以词表里的词开头。处置口径是**词表只减不增**：再出现真实误杀就继续收窄或整条降级为注入提醒，不是加更复杂的正则去猜。

**3.6.0 整条移除的 prompt-prefix-overlap 检查**（原第 6 项，常量 `LEAK_MATCH_MIN = 20`：`description` 正文与 `prompt` 开头逐字重合 ≥20 字符即判抄袭）：移除原因不是"阈值不合适"，而是**判据前提不成立**。合法的 `description` 本来就写任务目标，而本仓派发 prompt 的第一段恰是 `【目标】` 且写的是同一件事，两者开头天然重合——它命中的是"写得规范"，不是"抄了 prompt"。真正要防的提示词泄露由第 5 项承担。

### 不拦什么：只缺 `name` 时自动补名放行

判定"只缺 `name`、其余全过"时，guard 不输出 `permissionDecision`，而是输出 `hookSpecificOutput.updatedInput` 替换工具参数，并用 `additionalContext` 告知 AI 已自动补名：

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": { "...原参数": "...", "name": "sonnet-grep-auth-refs-a3f1" },
    "additionalContext": "[agent-dispatch] 本次派发没给 name（Agent 工具的 JSON Schema 未声明该字段，但运行时接受并会存进 subagent 元数据），已自动补为 … 下次派发请自己给 …"
  }
}
```

**自动名的构成**：`<model>-<语义>-<短哈希 4 位>`。语义来源优先级是「`description` 正文里的 ASCII 词（取前 4 个，≥2 字符）」→「`subagent_type` 转 kebab」。`description` 按纪律写的是中文任务摘要时抽不出 ASCII 词，就退回 `subagent_type`（`修订单竞态` + `general-purpose` → `opus-general-purpose-7f2c`；description 按新规不带 `[模型名]` 前缀，仍带前缀的旧写法会被 `deriveSlug()` 先 strip）——中文转写（拼音 / 翻译）在 hook 里不可靠，宁可给个语义弱但绝不出错的名。哈希是纯函数、不需要持久状态。

**3.6.0 修掉的哈希碰撞 bug：同批并发分片曾拿到完全相同的自动名。** 旧实现的哈希输入是 `prompt + '|' + slug`（`agent-dispatch.js:220`，3.4.0 版本），漏了 `description`。而本仓最常见的并发形态恰是**同一段 prompt + 不同的中文 description**（如「判定第一批规范」/「判定第二批规范」/「判定第三批规范」），中文 description 抽不出 ASCII 词、三个分片的 `slug` 一齐回落到同一个 `subagent_type`——于是哈希输入三者逐字相同，三个名字也逐字相同。用新旧两版对同一组 payload 实跑复现：

```text
旧版（HEAD:agent-dispatch.js）  判定第一批规范 → sonnet-explore-ebbd
                                判定第二批规范 → sonnet-explore-ebbd   ← 三个一模一样
                                判定第三批规范 → sonnet-explore-ebbd
现版（3.6.0）                   判定第一批规范 → sonnet-explore-7449
                                判定第二批规范 → sonnet-explore-3b76
                                判定第三批规范 → sonnet-explore-2ced
```

后果正是自动补名本来要避免的那一个：`SendMessage({to: name})` 走 latest-wins 寻址，同名时先派的两个 agent 只能靠 raw `agentId` 找回，等于弄丢。现在哈希输入改为 `prompt + '|' + description + '|' + slug`（`agent-dispatch.js:257-267`）。注意哈希值本身依赖 prompt 原文，换一段 prompt 得到的四位十六进制数不同，上表只用于对照"三个是否相同"。

**为什么不带 `permissionDecision`**：只改参数、不做权限判定。给 `"allow"` 会连带跳过用户自己的权限确认，等于 hook 替用户批准了一次工具调用，属于越权。

**边界：为什么不是"所有命名问题都自动修"**——`name` 前缀与 `model` 不符、含中文这类"字段存在但格式错"的情况仍然 deny：

| 情况 | 处置 | 理由 |
|---|---|---|
| 字段缺失（`name` 压根没给） | 自动补 | AI 看不见这个字段（schema 未声明），罚它没有教育意义 |
| 字段存在但格式错（前缀不符 / 含中文 / `description` 抄 prompt） | deny | AI 既然产出了这个值，就说明它知道字段存在，此时 finding 能真正教会它规则 |
| `model` 缺失或非法 | deny，且**不顺手补 `name`** | 档位是语义决策（这个任务值不值得上高档模型），自动填默认值等于把决策悄悄替 AI 做了，还会让 `name` 前缀跟着错 |

### 放行、豁免与总开关

**放行场景**：`tool_name` 不是 `Agent` / `subagent_type` 属于豁免名单 / stdin 读取或 JSON 解析失败 / `tool_input` 缺失 / 只缺 `name`（自动补名后放行）/ 校验全过。

**豁免名单**（`EXEMPT_SUBAGENT_TYPES`）：`fork`、`statusline-setup`、`output-style-setup`。其中 `fork` 是必须豁免的——Agent 工具文档明确写它「always inherit the parent model」，`model` 覆盖会被忽略，强制模型前缀自相矛盾。

**输出通道**：deny 走 JSON `permissionDecision: "deny"`（不是 exit 2）。官方文档明确 `permissionDecisionReason` 是展示给 Claude 的，语义比 exit code 约定更明确。reason 沿用本仓库 guard 的 `[L1-BLOCKER] ... finding= hint=` 格式便于统一识别：

下面这条是拿 `{"model":"sonnet","name":"verdict-part1","description":"你是第 1 层子代理，可派发第 2 层","subagent_type":"general-purpose"}` 实跑 `hooks/guards/agent-dispatch.js` 得到的原样输出（两条 finding 一次报清）：

```text
[L1-BLOCKER] tool=Agent check=agent-dispatch finding="name="verdict-part1" 缺模型档次前缀;用户无法从在飞 agent 面板判断这批任务烧的是哪一档模型;description 正文以 "你是" 开头,是 prompt 角色设定/元指令句式而非任务摘要;提示词会暴露到在飞 agent 面板" hint="name 改成 "sonnet-verdict-part1"（任务语义只能用 ASCII 字母数字与 - _）;description 只写"这个子代理在做什么",prompt 与 description 禁止共用同一段文字;完整规范见注入纪律 5.4 节;确需临时关闭本门禁用 AGENT_DISPATCH_GUARD=off"
```

注意 `description` 那条 hint 现在写的是「只写"这个子代理在做什么"」，**不再出现"不带 `[模型名]` 前缀"的措辞**（`agent-dispatch.js:369`）——3.4.0 起前缀是软放宽的：省略是推荐写法，写了也不拦，但会一并算进第 6 项那 60 字符的预算里。

这道门禁**默认开启且全局生效**：其他插件或 skill 内部派发 subagent 时（如 `omp` 的强制委派、各类 spec 工作流），若它们不遵守本插件的命名规范，同样会被拦下来。这是**预期行为**——规范要统一才有意义——但如果它挡住了你必须跑的既有工作流：

```bash
AGENT_DISPATCH_GUARD=off   # 大小写不敏感，设为 off 即整条门禁放行
AGENT_NAMING_GUARD=off     # 1.11.0 起沿用的旧名，继续有效
```

想永久关闭就从 `.claude-plugin/plugin.json` 的 `PreToolUse` 里删掉这条 hook 注册；想放宽某类 agent，把它的 `subagent_type` 加进 `EXEMPT_SUBAGENT_TYPES`。

### Known Limitation：`Workflow` 内部的 `label` 拦不到

本 hook 只覆盖 `Agent` 工具的直接派发。`Workflow` 脚本内部 `agent(prompt, {label})` 的调用**不经过 `PreToolUse`**（它发生在 workflow 运行时的脚本执行层），因此 `label` 缺失或抄 prompt 都拦不到，只能靠注入纪律 5.4.4 约束。理论上可以拦 `Workflow` 工具本身、对 `script` 字符串做正则提取来校验 `meta.name` 与各 `agent()` 的 `label`，但正则解析 JS 源码的可靠性太低（易误判模板字符串、嵌套括号、注释里的调用），故未实现。

---

## 三、拦截：`bash-guard` 守 Bash 命令的两条边界

`PreToolUse` + matcher `Bash`，合并自原 `block-cd.js` 与 `agent-browser-launch.js`。两者原本各自读一遍 stdin、各自解析一遍命令行，且**串行短路**——第一个 guard 拦下后第二个根本不执行。合并后一次解析、一次把所有问题报清：

```text
[L1-BLOCKER] tool=Bash check=bash-guard finding="独立 `cd` 会污染后续所有 Bash 调用的 cwd(cwd=/x);违规片段：cd /var;agent-browser open 缺 --headed;起 headless CFT 会让用户看不到 AI 操作过程" hint="改用绝对路径,或子 shell `(cd /abs/path && cmd)`,git 命令优先 `git -C <path> <cmd>`;加 --headed(...)"
```

### 两条判据的真实覆盖面（3.6.0 按 103 条实测 payload 如实改写）

3.6.0 前这里写的是「`cd` 由 `hooks/lib/shell-parse.js` 逐字符切分后**精确定位**……没有"猜意图"的成分」。2026-07-31 的审计跑了 103 条真实 payload 打真 guard，**"精确"二字被证伪**。如实表述是：

**独立 `cd` 的实际判据**是「剥掉 heredoc 正文与子 shell 后，由 `; && || | 换行` 切出的顶层片段、`trim()` 后以 `cd` 开头」（`bash-guard.js:125` 的 `CD_PATTERN` 与 `:193-207` 的 `checkCd()`）。它抓的是**文本形态**，不是"这条命令是否改变父 shell 的 cwd"这个语义。

**`agent-browser` 的实际判据**是命令名按 basename 匹配（跳过 `VAR=值` 前缀，接受 `npx` / `bunx` / `pnpm dlx` 与 `/usr/local/bin/agent-browser` 这类绝对路径）、子命令取 tail 里第一个位置参数并在已知词表内匹配、`--headed` / `--profile` 在**该次调用自己的 tail 内**判定（`bash-guard.js:249-342`）。词表命中与参数存在性确实是确定判定，但"这条命令是不是在调 agent-browser"仍是形态推断。

两条都是**提醒**，不是**保证**。它们仍然值得存在的理由不是判据完美，而是拦截文案里给了可照抄的模板（见下方 §3.5.0 那处正向对照）；未覆盖清单逐条列在下面两个 Known Limitation 里，别把"没被拦"读成"没问题"。

### 检查一：独立 `cd` 污染 cwd

Bash 工具的 cwd 在多次调用之间**持久保留**。AI 中间执行一次 `cd /tmp`，后续所有相对路径操作都会失准——排查半天才发现是 cwd 被静默改掉了。

- **阻断**（exit 2）：顶层片段以裸 `cd` 开头，且目标不是 no-op
- **放行**：子 shell `(cd /path && cmd)` / 命令替换 `$(cd /path && pwd)` / 字符串内的 `cd`（`echo "cd /tmp"`）/ **heredoc 正文里的 `cd`**（3.6.0 加）/ **以单个 `&` 后台化的片段**（3.6.0 加）/ **no-op cd**（目标解析后等于当前 cwd：`cd .`、`cd $PWD`、`cd ${PWD}`、`cd <当前目录绝对路径>`，3.6.0 起还包括符号链接等价与大小写等价路径）

#### 3.6.0 修掉的四类误杀（均为审计实测的真实 BLOCK）

1. **heredoc 正文，最严重的一类**。`ssh prod bash -s <<'EOF' / cd /srv/app / git pull / EOF` 被判成本地 cwd 污染，而那个 `cd` 在**远程主机**执行；`python3 - <<'EOF' / print(1) / cd /tmp / EOF` 里的 `cd` 甚至根本不是 shell 命令。根因是 heredoc 正文里的换行被 `splitSegments()` 当成命令分隔符，于是正文每一行都被当作独立的本地命令判定。更糟的是 hint 给的两个模板（改绝对路径 / 套子 shell）对 heredoc 正文**完全无从下手**——AI 撞上去改不动。修法是 `checkCd()` 先调新增的 `stripHeredocs()` 剥离正文（`shell-parse.js:195-214`，只保留声明行本身，覆盖 `<<DELIM` / `<<-DELIM` / `<<'DELIM'` / `<<"DELIM"`，显式排除 here-string `<<<`）。
2. **`cd /tmp &`**：`&` 结尾的命令在子 shell 异步执行，父 shell 的 cwd 不变（`isBackgrounded()`，`bash-guard.js:187-190`）。
3. **符号链接等价**：macOS 上 cwd 为 `/private/tmp` 时 `cd /tmp` 实际是 no-op，而旧实现只做 `path.resolve` 的字符串归一、不 `realpath`。
4. **`cd $PWD` 与大小写等价路径**（APFS 默认大小写不敏感），同上，旧实现按字面串比对判成"真的换目录"。

**stderr 控制在 400 字符量级**。3.6.0 顺带修了一处反噬：违规片段原样回灌进 finding，曾把 20 多行测试数据整段塞回上下文（实测单条 900+ 字符）。现在片段截断到 `SEGMENT_ECHO_LIMIT`（120 字符）。2.0.0 之前这里是约 1500 字符的完整事故复盘，每次拦截都灌进上下文——**这本身就是本插件要治的"注意力抢占"的一个实例**，而且是最讽刺的一种：一个用来纠正行为的提示，自己占掉了比被纠正的行为更多的注意力。复盘搬进了源码文件头注释（给维护者读）。

**已知误报**：shell 函数定义 `cd() { ...; }` 会被判成独立 `cd`——tokenizer 只看到段首的 `cd` token，不区分「调用」与「定义」。真实触发过两次（2026-07-26 与 2026-07-29 本插件自身的开发会话）。这类写法本就罕见且没有必要，未做特判：加一条「后跟 `()` 则跳过」的规则会让解析器为一个近乎不存在的场景变复杂，而绕开的成本只是删掉那行。

#### Known Limitation：只认「裸 `cd` 开头」一种形态，19 类真污染写法放行

审计清点出 **19 类同样污染父 shell cwd、但本 guard 实测全部放行**的写法，完整清单在 `hooks/guards/bash-guard.js:18-22`。分四组看：

同义或改写过的调用——`pushd /tmp`、`source ./setup.sh` 或 `. ./setup.sh`（脚本正文里有 `cd`）、`eval 'cd /tmp'`、`\cd /tmp`、`builtin cd /tmp`、`command cd /tmp`、`"cd" /tmp`（引号让首 token 不再字面等于 `cd`）。前缀挡住了段首——`CDPATH=/ cd tmp`（环境变量赋值前缀）、`time cd /tmp`。分隔符不被识别——`git status & cd /tmp`：单个 `&` 在 `splitSegments()` 里没有语义（只切 `&&`），整段被当成一个片段，而它以 `git` 开头。复合结构里的分支标签排在 `cd` 之前——`if ...; then cd /tmp; fi`、`{ cd /tmp; }`、`for d in *; do cd $d; done`、`case $x in a) cd /tmp;; esac`，以及函数体内的 `cd`。

对照之下，本 guard 拦得住的其实只有 `cd /x`、`foo && cd /x`、`foo; cd /x` 这一族。这正是仓库规则 `.claude/rules/hook-restraint.md` 里「判据抓的是文本形态而非真实风险」那条的实证来源，注入文本六章的 `cd` 条目因此改成了「要守的是 cwd 干净，不是躲过这道闸」。

#### Known Limitation：`stripSubshells` 的括号匹配不感知引号，一个假括号就能让真 `cd` 隐形

`hooks/lib/shell-parse.js:135` 剥子 shell 用的是 `/\([^()]*\)/g` 这个纯字符匹配，**不判断括号在不在引号里**。于是引号内一个不成对的 `(` 会跟后面某个 `)` 配对，把中间的真实命令一起吃掉。2026-07-31 的对照实测：

```text
echo "(start" && cd /tmp && echo "end)"   → exit 0 放行（cd 被整段剥离，checkCd 根本看不到它）
echo "a)" && cd /tmp                      → exit 2 拦下（只有 ) 没有 (，剥不掉）
(cd /tmp && ls) && cd /var                → exit 2 拦下（对照组：括号外的真 cd 仍在）
```

这条同时改写了一个此前的**因果误述**：README 与源码原本都说 `(cd /abs && cmd)` 放行是因为"cwd 不回流父进程"。实际机制是**括号里的文本被删掉了**，guard 压根没做那个语义判断——第三行那个对照组就是旁证。结论对同一件事仍然成立（子 shell 确实不污染父 shell），但**理由不同**，而理由决定了边界：既然靠的是字符剥离，第一行那种"假括号"就能让真 `cd` 一起消失。

方向是**放行**（少看到东西 → 少拦），符合 `shell-parse.js` 文件头写明的"宁可放行也不误拦"取向；代价是调用方不能据此声称自己"精确"覆盖了某类语义。

#### Known Limitation：跨插件 cd 探测差异

`bash-guard` 只保证"AI 自己的 cwd 不被污染"，但它**不能**保证其他插件对同一条命令的 cwd 探测逻辑与 AI 实际使用的语法兼容——遇到时不要去改对方插件的探测逻辑，改 AI 自己发出的命令语法即可规避。

**事故来源（2026-07-20，D-001-feat-job-sequence-model 会话）**：subagent 要把改动 push 到 `claude-devkit-marketplace`（一个与当前项目完全无关的第三方仓库），用的命令是 `(cd /Users/zhangq/Workspace/mine/claude-devkit-marketplace && git push origin main)`——这条命令本身完全合法，本 guard 也正常放行。但推送被同时装着的 **sdlc 插件**拦截，报「BLOCKED: ontology 正向同步未收口 for D-001-feat-job-sequence-model」，一次跨仓库误伤。根因在 sdlc 插件 `hooks/lib/worktree-utils.js` 的 `resolveGitCwd()`：它用正则 `/^cd\s+.../` 匹配命令字符串**开头**的 `cd` 前缀来判定这条 git 命令作用于哪个仓库（同时显式支持 `git -C <path>`）。子 shell 语法 `(cd /path && cmd)` 带括号、不以 `cd` 开头，正则天然匹配不上，`resolveGitCwd()` 就 fall back 到当前会话所在的 worktree，把发往第三方仓库的 push 误认成 D-001 delivery 分支的 push。

**推荐用法**：涉及 git 命令时优先 `git -C <path> <cmd>`，而不是 `(cd /path && git ...)`。`-C` 是 git 官方支持的全局选项，语义等价，但字面上不含 `cd` token、不进子 shell，本 guard 放行，且各类插件的 cwd 探测正则通常会显式支持这种标准写法：

```bash
git -C /Users/zhangq/Workspace/mine/claude-devkit-marketplace push origin main
git -C /abs/path/to/repo status
```

非 git 命令仍然只能走 `(cd /path && cmd)` 子 shell 语法——`-C` 是 git 专有选项，不是通用 shell 机制。

### 检查二：`agent-browser` 启动——headless 默认下的新四护栏

**沿革**：3.6.0 前本检查强制 `--headed` + `--profile`，起因是 2026-07-20 D-001 verify 事故——AI 用 headless 起 Chrome for Testing 复现前端问题，用户看不到窗口、只看到权限申请弹窗，质疑"你现在是创建了一个 headless 的 chrome 实例吗？"。**3.7.0 应产品要求改为默认 headless**：用户接受 headless 作为常态，但要求用四道新机制替代"看到窗口"提供的监督。

| 护栏 | 判据 | 处置 |
|------|------|------|
| ①鉴权前置 | 启动类子命令且 tail/env 无 `--profile`/`--state`/`--headers`/`--restore` 任一持久化鉴权方式 | **阻断**（headless 下人类无法中途授权） |
| ②实例上限 4 | 启动类子命令时同步 `agent-browser session list`，活动实例 ≥4 | **阻断**（agent-browser 无内置并发上限，须外部节制） |
| ③登录态复用 | 并入①——缺鉴权判据已覆盖"无 --profile"情形 | 同① |
| ④安全边界 | tail 无 `--allowed-domains` 且无 `--content-boundaries` | **仅提醒**（不阻断，避免过度拦截纯公开页任务） |

> 完整使用指南（鉴权注入四法、AI Testing profile 创建、snapshot 工作流、反检测）见本市场独立插件 `agent-browser` 的 SKILL.md。本节只讲 guard 判据。

判定顺序（沿用 3.6.0 的逐片段独立判定）：切出顶层片段 → 在片段的**命令名位置**认出 `agent-browser`（跳过 `VAR=值` 前缀，接受 `npx` / `bunx` / `pnpm dlx` 转发，命令名按 basename 比对因而 `/usr/local/bin/agent-browser` 也算）→ tail 里含 `--help` / `-h` / `--version` / `-V` 直接放行 → 取 tail 第一个位置参数当子命令，属于**启动类**才继续 → 四护栏逐一判定（①②阻断、④提醒）。

| 启动类子命令 | 说明 |
|--------|------|
| `open` | 打开新页面/新实例 |
| `connect` | 连接并拉起实例 |
| `chat` | 仅当后面接了 URL 位置参数才算启动；纯 REPL 模式不拦 |

**探测/后续操作类子命令一律放行**：只读探测（`skills` `doctor` `install` `upgrade`）、生命周期无关（`close` `mcp` `dashboard` `session` `plugin` `auth` `profiles` `confirm` `deny`）、后续操作类（`snapshot` `click` `fill` `type` `screenshot` `eval` `network` `tab` 等一整套）。

正确调用示例（3.7.0：默认 headless，无需 `--headed`）：

```bash
# 带持久化 profile（满足①③），默认 headless
agent-browser --profile "/Users/<user>/Library/Application Support/Google/Chrome/Profile 1" open https://example.com
# token 注入（满足①，origin 作用域）
agent-browser open https://api.example.com --headers '{"Authorization":"Bearer <token>"}'
# 环境变量等价
AGENT_BROWSER_PROFILE=/tmp/ab-profile agent-browser open https://example.com
# 纯隔离测试场景（临时 profile 满足硬要求）
agent-browser --profile "$(mktemp -d)" open https://example.com
# 推荐再带安全边界（满足④，消除提醒）
agent-browser --profile /p --allowed-domains "example.com" --content-boundaries open https://example.com
```

#### 护栏②的实现：`session list` 计数

agent-browser **无内置并发上限**（官方已确认），`--session` 只做隔离不做计数。guard 在每次启动类子命令时同步 run `agent-browser session list`，正则数顶层条目（`->` 开头的行），≥4 即拦。CLI 未装 / daemon 未起 / 超时 / 输出无法解析 → 返回 -1 → **放行**（不因工具未装而误拦，沿用"未知即放行"方向）。测试用环境变量 `WD_AB_INSTANCE_COUNT=<整数>` 桩注入确定值。

#### 沿用 3.6.0 的工程改进

3.7.0 未改这些（仍生效，仅记要点）：

- **逐片段独立判定**，不跨片段共用结果——修掉了"口令退化"（`echo --profile /p; agent-browser open https://x` 不再被另一片段的 `--profile` 满足）。
- **命令名按 basename 匹配**，认 `npx`/`bunx`/`pnpm dlx` 前缀与绝对路径 `/usr/local/bin/agent-browser`。
- tail 含 `--help`/`-h`/`--version`/`-V` 直接放行；`--profile=""` 视为空值（tokenize 后首字符是 `-`，需再剥一次引号）。
- 环境变量前缀 `AGENT_BROWSER_PROFILE=<非空值>` 等可替代对应 flag（3.7.0 扩展为 `AGENT_BROWSER_PROFILE`/`HEADERS`/`STATE` 三者任一非空即满足①）。

#### Known Limitation：间接调用与未知子命令一律放行

三类已知不覆盖，写在 `hooks/guards/bash-guard.js:29-34`：

命令替换与变量间接调用——`$(which agent-browser) open https://x.com`、`AB=agent-browser; $AB open https://x.com`，命令名位置上的 token 不字面等于 `agent-browser`，认不出来。**不在词表里的子命令一律放行**——这是有意选择的方向（未知即放行，避免把 CLI 新增的普通子命令误拦），代价是 agent-browser 日后新增启动类子命令时，本判据会**静默失效**、没有任何报错。白名单里的 `read <URL>` 等子命令在 daemon 不存在时会**自行拉起一个 headless 实例**，3.7.0 后这不再是问题（默认就是 headless），但它仍绕过①②④三道护栏。

---

## 四、事后提醒：`write-guard` 守文件行数（**它不是拦截器**）

`PostToolUse` + matcher `Write|Edit`，合并自原 `max-source-lines.js` 与 `claude-md-max-lines.js`。两条检查互斥（一个文件不可能同时是 `.md` 和源码扩展名），合并的收益不在"一次报两条"，而在消除一次进程启动 + 一次重复的 `readFileSync`——`PostToolUse` 每次写文件都触发，这是热路径。

### 先修正一条被广泛误读的断言：它不拦，也不停

3.6.0 之前，本章标题、注入文本六章、以及 `write-guard.js` 自己的注释都写着"会被拦"。**这是错的**，而且错得有代价（见本文档「3.6.0 审计」一节）。真实行为是：hook 挂在 `PostToolUse`，触发时**文件已经落盘**，本 guard 既不回滚这次写入、也不停住本轮，只是把一句 stderr 喂回给 Claude 当附加上下文，**这一轮继续往下走**。

三条实测证据（`write-guard.js:11-22`）：

1. **它没有、也无法做回滚**。整份 `hooks/guards/write-guard.js` 只有两处 `readFileSync`（读 stdin、读目标文件），零个 `fs` 写操作。审计连续 6 次拦同一个 12436 行文件后复核该文件的 md5 与 mtime——**未变**。顺带说明 `finding` 里那个行数本身就是证据：它是**读落盘后的文件**数出来的（`write-guard.js:217`），能数出来就说明已经写进去了。
2. **Claude Code 2.1.220 二进制里的明文**：`On PostToolUse, the reason is fed back to Claude and the turn continues.`
3. **真能停住回合的是 JSON 顶层 `continue: false`**（配 `stopReason`），而本文件走的是 `process.stderr.write` + `process.exit(2)`，压根不输出 JSON。

所以正确的心智模型是：`Agent` 与 `Bash` 那两道是**闸**（`PreToolUse`，工具调用没发生），`Write`/`Edit` 这道是**回执单**（`PostToolUse`，事情已经做完了）。任何形如「反正超长了会被拦下所以不用提前判断」的推理都建立在错误前提上——动笔前就要判断该不该拆。注入文本六章的对应条目已在 3.6.0 改成「它挂 `PostToolUse`，触发时文件已经写完了……指望不上它兜底」。

### 检查一：单一源码文件 > 1000 行

行数超硬阈值是"职责过大"的信号——该文件大概率在做不止一件事，继续往里堆代码只会让可读性、可测试性、review 成本一起变差。这条只管"行数"这一个维度，语法/风格交给 linter。

- **命中扩展名**（小写比对，`SOURCE_EXTENSIONS`）：`.java .kt .kts .scala .groovy .gradle .js .mjs .cjs .ts .mts .cts .jsx .tsx .vue .svelte .astro .py .go .rs .rb .php .pl .lua .dart .cpp .cc .cxx .c .h .hpp .cs .swift .m .mm .hs .ex .exs .erl .clj .cljs .sh .bash .zsh`——`.md .json .yaml .yml .toml .env .lock` 等非源码文件不受约束
- **排除路径**（3.6.0 加）：`GENERATED_PATH_PATTERN` 命中依赖 / 产物 / 虚拟环境目录段（`node_modules` `bower_components` `vendor` `third_party` `Pods` `dist` `build` `target` `out` `.next` `.nuxt` `.output` `coverage` `__pycache__` `.venv` `venv` `site-packages`），或 `GENERATED_NAME_PATTERN` 命中生成物命名约定（`.min.` `.generated.` `.g.` `.bundle.` `_pb2.` `.pb.`）
- **判定**：命中扩展名 AND 未命中排除路径 AND 落盘后总行数 > 1000
- **提醒**（exit 2 走 stderr，文件已落盘）：`[L1-BLOCKER] file={相对路径} check=write-guard finding="{N} lines exceeds source limit 1000" hint="按职责拆分模块,不要继续在同一文件堆代码"`

#### 3.6.0 的三处收窄：扩展名不能区分"源码"，行数还差一

3.6.0 前这里的注释写着"误判空间为零"。审计用 27 条真实文件跑真 guard 证伪了它——**扩展名不能区分源码与数据 / 产物 / 第三方依赖，`basename` 不能区分本项目与别人的项目，行数计数还带 `+1` 偏移**。三处已收窄，但**没有归零**：

**一是 `.sql` 与样式表（`.css` / `.scss` / `.sass` / `.less`）整体移出源码集合。** 一个 3539 行的全库建表 DDL 被判"按职责拆分模块"毫无意义——拆成 4 个文件只会破坏可执行性；vendored 的 `animate.css`（4073 行）同理。行数与"职责过大"这个信号在这类文件上根本不成立。代价是**手写的超长样式表与 SQL 现在不再有任何约束**，这是换掉那批误判的自觉取舍。

**二是依赖与产物路径排除。** 审计实测被误拦的真实样本：`node_modules/animate.css/animate.css`、`target/classes/db/schema.mysql.sql`、`dist/hooks/bridge.js`（2511 行的打包产物）。这些都不是"我们正在写的源码"，提示拆分毫无意义。

**三是补齐扩展名黑洞——这处方向原本刚好是反的。** `.mjs` / `.cjs` / `.sh` 等**原本不在**集合里，审计实测 1710 行的 `keyword-detector.mjs` 与 2657 行的 `setup.sh` 全部放行。也就是说"AI 把 3000 行堆进一个文件"这件事，**换个扩展名就完全不受约束**，而真正该放行的 SQL / CSS 反倒被拦。

**外加行数 `+1` 偏移修复。** 旧实现 `content.split('\n').length` 在文件以换行结尾时（POSIX 文本文件的常态）多算一行。审计两组实测：`wc -l` 得 12436、guard 报 12437；`wc -l` 得 685、guard 报 686；`tail -c 1 | xxd` 确认结尾就是 `0a`。后果是**阈值文案与实际行为差一**——正好 1000 行且以换行结尾的文件被算成 1001 行报出来，而 finding 告诉 Claude 的是 `limit 1000`，照 1000 行去卡会反复撞同一条提醒。现在 `countLines()`（`write-guard.js:143-147`）先去掉末尾那个换行再分割，空文件仍显式计 0 行。

**仍然未覆盖**：`.ipynb` / `.tf` / `.json` 等按行数衡量无意义的类型没有纳入；手写超长 SQL 与样式表如上所述已无约束。

### 检查二：CLAUDE.md > 200 行

这条要解决的不是"CLAUDE.md 不许长"，而是**"不许靠压缩正文来规避长"**。真实事故：某项目的 CLAUDE.md 逼近阈值后，AI 把原本 3 段独立的踩坑记录（症状 / 根因 / 解法三段式）硬压成 1 段紧凑文字塞进 200 行以内——压缩过程中丢掉了完整因果链、具体的 `file:行号` 引用、以及未来 AI 需要的典型与边界场景示例，表面"合规"了，但作为纪律文档的可用性被严重削弱。正确做法是拆分结构：细节各自落成 `.claude/rules/{topic}.md`（不受 200 行限制），CLAUDE.md 只留全局必知的部分。

**拆过去的文件不需要在 CLAUDE.md 里引用。** 3.1.0 之前这里写的是"CLAUDE.md 里用 markdown 相对链接指过去"，那句话基于「不引用就读不到」的错误前提。实证（Claude Code 2.1.220 二进制）：memory 装配链上 `.claude/rules/` 的加载调用 `ZPt({rulesDir: <cwd>/.claude/rules, type:"Project", conditionalRule})` 与 CLAUDE.md 自身的 `Lpe()` 并列，用户级 `~/.claude/rules/` 走 `gfo(){return join(fn(),"rules")}`；内置 `/init` 指令的原文同样写明「These are loaded automatically alongside CLAUDE.md and can be scoped to specific file paths using `paths` frontmatter」。冗余之外还有实害——AI 读到"引用"会倾向改用 Claude Code 真正的 import 语法 `@.claude/rules/x.md`，那会让同一份内容被「目录自动加载 + import」注入两次（官方未声明两者之间会去重）。

拆分真正的额外收益是 `paths` frontmatter：rules 文件可声明只在改动匹配某些路径时才加载，比无条件常驻的 CLAUDE.md 更省上下文。

- **命中文件**：`basename` 不区分大小写等于 `claude.md`（`CLAUDE.md` / `claude.md` / `Claude.Md` 均命中），且不限于仓库根——多 CLAUDE.md 项目里子目录下的同名文件同样受约束
- **限定当前项目树内**（3.6.0 加）：`path.relative(cwd, filePath)` 不以 `..` 开头、也不是绝对路径（win32 跨盘符），否则放行
- **排除**：项目内相对路径**以 `.claude/rules/` 开头**（`RULES_DIR_PREFIX`）的文件不受限——这正是拆分后应当落脚的地方
- **提醒**（exit 2 走 stderr，文件已落盘）：`hint` 明确指路 `拆到 .claude/rules/{topic}.md(自动加载,不要在 CLAUDE.md 里 @import 或加链接引用;可用 paths frontmatter 限定生效路径),禁止压缩正文导致约束丢失`，不是只报一个数字让 AI 自己瞎猜怎么合规

#### 3.6.0 的两处收窄：别人的 CLAUDE.md 不归你管，以及一个被实测出来的绕过点

**一是必须落在当前项目树内。** 这条约束的**依据**是"该文件常驻当前会话上下文、吃上下文预算"，而那取决于它在不在当前 `cwd` 树里——`basename` 单独判定做不到这件事。审计实测被误拦的真实样本是两个插件市场缓存里**别人写的** CLAUDE.md：`~/.claude/plugins/marketplaces/context-engineering-kit/CLAUDE.md`（257 行）与同目录下 `xxstar-prod-ai/CLAUDE.md`（217 行）。维护插件市场缓存时改到它们，会被按"本项目上下文预算"这个根本不适用的理由拦下。

**二是 `.claude/rules/` 排除从"路径任意位置包含"改为"项目内相对路径以此开头"。** 旧实现 `/(^|\/)\.claude\/rules\//` 是个**实测可用的绕过点**——只要让路径里出现这个目录段，任意位置都算：

```text
BLOCK | <别处>/ccg-workflow/CLAUDE.md                                （686 行）
PASS  | <本仓>/.claude/rules/../../../../<别处>/ccg-workflow/CLAUDE.md（同一个文件，绕过）
BLOCK | <本仓>/docs/research/../../../../<别处>/ccg-workflow/CLAUDE.md（对照组）
```

第三行那个对照组是关键：它证明放行是**那个特定路径段**导致的，不是 `..` 导致的。改用 `path.relative()` 归一化后再判断（`projectRelative()`，`write-guard.js:157-168`），`..` 爬出项目的场景先被"项目树内"那条挡掉，绕过点随之消失。

**两条共用的放行场景**：`tool_name` 不是 `Write`/`Edit` / `file_path` 缺失 / 路径命中依赖·产物·生成物模式 / 两条检查都不适用（此时不读盘）/ 文件读取失败（竞态删除等基础设施异常不误拦）。

---

## 五、3.0.0 删掉了什么，纪律去哪了

删掉的四组判据，共同缺陷是**判据靠正则猜语义或回读 transcript 推断状态，而拦截是不可绕过的硬阻断**。

| 删除的 guard / 校验 | 原判据 | 失败模式 |
|---|---|---|
| `external-write-readback.js`（`PostToolUse` Bash 条件注入） | 扫命令里的 `create` / `update` / `delete` / `发布` / `提交` 等词，命中即注入回读要求 | 只跑了 `ls -l` 和 `cat` 也会被注入「刚才这条命令用 Bash 改了本地文件」 |
| `nonascii-path.js`（`PreToolUse` Bash） | 命令含非 ASCII 字节 + 挂 `2>/dev/null` + 探测类命令词表 | 非 ASCII 来自 `echo '=== 已安装缓存版本 ==='` 的提示语、路径全是 ASCII，照样 deny |
| `md-audience-declaration.js`（`PreToolUse` Write\|Edit） | 回读 transcript 找本轮 assistant 文本里的「受众判定」字样 | 2.3.0 已摘挂载：子代理不知道这条规则时必然先撞 deny，撞满熔断阈值后转 `ask`，于是每次让子代理写 md 都要打断用户点一次确认框；而 hook 的 `permissionDecision` 独立于权限模式，用户配了 `bypassPermissions` 也拦不住，表现为「subagent 莫名其妙丢了 bypass 权限」 |
| `agent-dispatch.js` 第二层四条（档位错配 / 索要回执 / 截图附路径 / 写操作传染回读） | 扫 prompt 词表 + 回读 transcript 取图片 | 见第一章开头三个实证 |

**两个逃生舱也一并删除**（原先 prompt 里写 `档位已确认：<理由>` / `豁免图片：<理由>` 即放行）。它们是中间态而非解法：要求 AI 先撞一次 deny、再回头往 prompt 里塞一句咒语，而 `deny` 不给用户"点一下就过"的入口。真正的选择只有两个——要么判据够硬就硬拦，要么判据靠猜就别做成拦截。需要中间档时用 `permissionDecision: "ask"`（参见 radnove-core 的 `pre-tool-use-dws-write.sh`），而不是 deny + 咒语。

**纪律一条都没丢，全部回到常驻注入**：

| 原 hook 强制的规则 | 现在在哪 |
|---|---|
| 结构化回执 / 截图附绝对路径 / 写后回读传染 | 注入 5.6「派发 prompt 必含四项」的前三项（第 4 项是 3.5.0 新加的核实类停止条件），标题里明写「没有 hook 兜底，漏了没人拦你」 |
| 派发档位选择 | 注入 5.1（`subagent_type` 权限边界）与 5.2（三档 model 判定标尺） |
| 写 md 前的受众判定 | 注入四、第 7 项，含完整三分支要点 |
| 非 ASCII 路径 NFC/NFD 漏检 | 注入一、末条「空结果不得直接判『没有』」 |
| 外部写操作后的逐字段回读 | 注入 5.6 第 3 项，判据换成「这个任务是否真的要执行写操作」而不是「prompt 里有没有出现写操作的词」 |

**截图路径改为注入侧条件注入**。判据从 `PreToolUse` 回读 transcript 挪到 `UserPromptSubmit` 直接读事件 payload——那一刻本轮还没有任何工具输出，payload 里只有用户输入，判据天然干净。提取逻辑在 `hooks/lib/prompt-images.js`，纯函数、不碰文件系统。正则收紧为两条：`[Image: source: <path>]` 标记优先（harness 渲染用户贴图的固定形态，2026-07-28 与 07-29 两次实测确认），裸绝对路径要求**至少两级路径段**且不含 `|` 与反斜杠。前者杜绝残片（真实截图路径必然多级，旧版贪婪切分曾切出 `/1.png` 这类假路径），后者杜绝把源码里的正则字面量当成路径。已知取舍：含空格的手写路径（`/Users/me/Desktop/shot 2.png`）扫不到——软约束下漏一条提醒无所谓，误报却会让 AI 把假路径写进 prompt 让子代理 `Read` 到不存在的文件，故**宁漏不误**。

**顺带删掉的两个 lib**：`transcript.js`（按 `prompt_id` 回读本轮 assistant 文本与图片，是上述两处误判的共同根源）与 `notify-once.js`（同轮去重计数，只服务已删除的 guard）。

### 这次留下的工程教训

判据依赖外部数据结构（transcript 行格式）的门控 hook，必须做两件事——把判据本身写进 deny 文案（否则 AI 只能猜，猜错就是绕过），以及给一个次数熔断（否则格式一变就是永久拒绝）。2.2.0 在 `md-audience-declaration.js` 上补齐了这两件，但 2.3.0 仍然摘除了它：**补齐可观测性只能让失灵可诊断，不能让不可靠的判据变可靠**。真正的结论是这类判据压根不该做成拦截。

那次事故值得留档，因为它示范了「用历史行的最终排列去推实时可读性」这个方法论错误。旧实现有两条错误结论叠加成永久拒绝：(a) 轮起点算法「从后往前找最后一个 `promptId` 匹配的 user 行」必然命中**最近一次工具结果**（`tool_result` 行的 `type` 也是 `'user'` 且带相同 `promptId`），起点被推到它之后，AI 之前说过的话全被切掉；(b) 一条 assistant message（thinking + text + tool_use）在 API 响应结束后才整体写盘，而 `PreToolUse` 发生在那之前，**同一条 message 里的 text 块在该 message 的 tool_use 触发 hook 时读不到**。(a) 决定「重试时旧声明又被新 tool_result 切出窗口」，(b) 决定「首次必然读不到」，合起来就是死局——每次重新声明都会再造一个 `tool_result` 把声明推走。事故现场的 AI 在两次被 deny 后判断"这是个失灵的时机检查"，转而用 heredoc 绕开 `Write` 工具直接写文件。

---

## 安装

**Claude Code**

```bash
/plugin install working-discipline@claude-devkit-marketplace
```

**Codex CLI**（用户级安装，对所有项目生效）

```bash
node scripts/install-codex.js --plugins=working-discipline --scope=user
```

---

## 工作机制速览

**注入 hook**（`hooks/working-discipline.js`）

```text
SessionStart（会话开始 + 每次 auto-compact 后） / UserPromptSubmit（每轮） / SubagentStart（子代理启动）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/working-discipline.js
   ↓  读 stdin 的 hook_event_name 分流（3.2.0 起三层）：
   ↓    SessionStart     → 一、二、三、四、五（含 5.4 索引、5.6 四项、5.7）、六        实测 8538 字符
   ↓    UserPromptSubmit → 零（并行优先）+ 每轮自查 4 条                          实测 1342 字符
   ↓                       + 经 lib/prompt-images.js 扫 payload：有图才追加路径清单
   ↓    SubagentStart    → 零(精简)、一、二、三、5.4 命名规范完整版、六（缺四）    实测 7174 字符
   ↓                       + 开头的执行侧要求：结构化回执 + 核实类任务交代追踪深度
   ↓    未识别事件        → 回退 UserPromptSubmit（三者中最小的一份，回退错了只多注入 1.1k）
   ↓
stdout 输出 { hookSpecificOutput: { hookEventName, additionalContext } }
   ↓
Claude Code 把 additionalContext 拼进对应 context
（SubagentStart 的注入只进子代理自己的 transcript，不入主会话）
```

**为什么静态主体能只在 SessionStart 投放一次**：`matcher: "*"` 同时覆盖 `startup` / `resume` / `clear` / `compact` 四种触发。实测一个 20 轮 session 里 `SessionStart` 共触发 4 次——1 次 `SessionStart:startup` 加 **3 次 `SessionStart:compact`**，与 3 次 `compact_boundary` 一一对应、时间戳还早约 1 秒，没有空窗。也就是说 auto-compact 把上下文压掉之后静态纪律会立即重新注入，不需要每轮重发来"续命"。

**为什么零章偏偏留在每轮**：它对抗的是 harness 硬编码进 **system prompt** 的 `Do not call the AgentTool unless the user requested it`。system prompt 每轮完整在场、且不被 auto-compact 挤走；而 SessionStart 注入只是对话早期的一条消息，随轮次增长被推远。用一份会衰减的文本去对抗一句永在最前的硬禁令，距离只会越拉越大，所以授权声明必须每轮重申。

**分层收益**：改前每轮全量重发 6717 字符，在那个 20 轮 session 里累计 142,800 字符、占全部 hook 注入（270,506）的 52.8%，期间触发 3 次 auto-compact。分层后同形态为 `5985 × 4 + 1163 × 20 = 47,200`，降幅 65%（该核算用 3.2.0 当时的体积；按 3.6.0 实测的 7142 / 1342 重算是 `7142 × 4 + 1342 × 20 = 55,408`，占改前的 38.8%、即降幅 61%——注入文本从 3.2.0 到 3.6.0 长了近 1200 字符，分层的收益仍在，只是被吃掉了一部分）。作为对照，同机 `radnove-core` 把会话约定放 SessionStart，同类内容只花了 `4170 × 4 = 16,680`。

**拦截 hook**（`hooks/guards/agent-dispatch.js`）

```text
PreToolUse（Agent 工具调用前）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/guards/agent-dispatch.js
   ↓  读 stdin 的 tool_name / tool_input：
   ↓    AGENT_DISPATCH_GUARD=off 或 AGENT_NAMING_GUARD=off → 放行（总开关）
   ↓    tool_name 不是 Agent → 放行（不匹配旧名 Task，避免永久误拦）
   ↓    subagent_type ∈ {fork, statusline-setup, output-style-setup} → 放行
   ↓  6 项结构校验，聚合所有 finding：
   ↓    model 显式且合法 / name 前缀符 model（分隔符 - 或 _）·满足原生正则
   ↓    description 必填且有正文（不要求 [模型名] 前缀，3.4.0 起软放宽；[haiku] 报错）
   ↓    description 正文非角色设定句 / 原始串 ≤60 字符（前缀也算进去）
   ↓    有 finding → deny（model 非法时额外附完整路由表）
   ↓  只缺 name（其余全过）：
   ↓    autoName() = <model>-<description ASCII 词或 subagent_type>-<短哈希 4 位>
   ↓      短哈希输入 = prompt + '|' + description + '|' + slug（3.6.0 补 description）
   ↓    → 输出 updatedInput 补名 + additionalContext 告知，不带 permissionDecision
   ↓  全过 → 放行
```

**拦截 hook**（`hooks/guards/bash-guard.js`）

```text
PreToolUse（Bash 工具调用前）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/guards/bash-guard.js
   ↓  读 stdin 的 tool_input.command 与 cwd，一次解析、两项检查全跑：
   ↓  【检查一】剥 heredoc 正文 → 剥子 shell / 命令替换 → 切顶层片段 → 逐个判定 cd
   ↓    片段以裸 cd 开头、非后台化(&)、目标非 no-op → 记 finding（片段截断 120 字符）
   ↓  【检查二】逐片段在命令名位置定位 agent-browser（跳 VAR=值；npx/bunx/pnpm dlx；
   ↓            按 basename 比对）→ tail 含 --help/-h/--version/-V 则跳过
   ↓    tail 第一个位置参数不属于启动类（open/connect/带 URL 的 chat） → 跳过
   ↓    护栏①缺鉴权（tail/env 无 --profile/--state/--headers/--restore 任一）→ 记 finding
   ↓    护栏②实例超限（agent-browser session list 数 ≥4；CLI 不可用则跳过）→ 记 finding
   ↓    护栏④缺安全边界（无 --allowed-domains/--content-boundaries）→ 仅记 hint，不阻断
   ↓  有阻断类 finding → exit 2 阻断（stderr 一次输出全部 finding + hint）
   ↓  无 finding → exit 0 放行
```

**事后提醒 hook**（`hooks/guards/write-guard.js`）——注意 exit 2 在 `PostToolUse` 上**不回滚、不停轮**，只把 stderr 喂回给 Claude

```text
PostToolUse（Write / Edit 工具写入完成后 —— 文件已经在盘上了）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/guards/write-guard.js
   ↓  读 stdin 的 tool_input.file_path 与 cwd：
   ↓    路径命中依赖/产物/生成物模式（node_modules、dist、target、.min. …）→ exit 0
   ↓    既不是源码扩展名、也不是当前项目树内的 CLAUDE.md → exit 0 放行（不读盘）
   ↓    项目内相对路径以 .claude/rules/ 开头的 claude.md → 不按 CLAUDE.md 判（拆分页不受限）
   ↓    读落盘后文件内容计数行数（末尾换行不多算一行）
   ↓    源码 > 1000 行 → exit 2（hint：按职责拆分模块）
   ↓    CLAUDE.md > 200 行 → exit 2（hint：拆到 .claude/rules/{topic}.md）
   ↓    未超限 / 文件读取失败 → exit 0 放行
```

---

## 深入话题

### 「在飞≤16」和「嵌套≤2」是纪律软约束

这两条不是 Claude Code 的硬限制，是靠注入文本让 AI 自觉遵守：

- **在飞≤16**：Claude Code 没有并发数的原生配置，也**没有任何工具能枚举在飞子代理**。规则要求 AI 每次派发前靠**自记账**盘点本会话在飞数（派发时 +1，收到某 agent 的 `<task-notification>` 完成通知或其 `Agent` 工具返回时 -1）。

  这里曾有一处错误，1.10.1 修掉：旧版规则文本写的是「用 `TaskList` 统计当前 `status=running` 的在飞子代理数量」，两处都不成立——`TaskList` 读的是**任务板**（字段 `id` / `subject` / `status` / `owner` / `blockedBy`），跟在飞子代理不是同一个数据源；而它的 `status` 枚举只有 `pending` / `in_progress` / `completed` / `deleted`，**根本没有 `running` 这个值**，照字面执行只会拿到一个恒为空的过滤结果。同批修正的还有「等齐再总结」的判据：旧文本写「等 `TaskList` 显示本批次全部到 `completed`」，同样查错了数据源，现改为「本批次每个 agent 各自的完成通知/工具返回都已到齐」。

  另外两点边界：`TaskOutput` 虽能按 `task_id` 查后台任务状态，但已标记 DEPRECATED 且只接受**单个已知的** `task_id`，无法枚举；能列出全系统在飞任务的入口是用户侧的 `/tasks` 斜杠命令，**AI 无法自行调用**。所以规则同时收窄口径——自查范围只限本会话自己派发的子代理，禁止 AI 声称统计过"全系统在飞总量"；长会话 auto-compact 压掉早期派发记录导致记账失准时，按保守口径分批派或请用户报数。
- **嵌套≤2**：Claude Code 原生嵌套硬上限是 **5 层且不可配置**，`SubagentStart` 也无法拦截派发行为。所以 2 层限制只能由各层自觉传递——第 1 层子代理在给第 2 层写 prompt 时，须明确写「你是第 2 层子代理，禁止再派任何 subagent」。

### 为什么有四项机械规则从未下沉

设计时评估过、最终**决定不实现**的四项，它们的注入文本因此仍然常驻：

| 候选 | 本可以怎么做 | 为什么不做 |
|---|---|---|
| 在飞 subagent ≤16 的计数拦截 | `PreToolUse` 拦 `Agent`，用状态文件记账，超 16 则 deny | 状态文件的崩溃残留会造成**永久性误拦**——会话异常退出时计数不归零，下次开会话直接被拦死，而用户很难猜到原因 |
| `Stop` hook 校验输出语言与列表编号 | `Stop` 的 exit 2 可以「阻止停止、让对话继续」，读 transcript 校验 AI 自己的输出 | 误报的代价是**强行多跑一轮**（比 deny 一次工具调用贵得多）；且繁简判定极易误伤引用的繁体原文 |
| 大输出命令 `PreToolUse` 拦截 | 识别 `cat` 大文件、无 `head` 的 `find /` 等 | 误报多，且用户明确要求看全量输出时会碍事——这条本来就有合理的例外 |
| 嵌套深度 ≤2 的记账拦截 | 派发时按父子链累加深度 | **官方 payload 里没有 parent 信息**，父子链只能靠时序推断，并发派发时有竞态；判据本身不可靠就不该做成硬拦截 |

共同的取舍是：**硬拦截的误报成本远高于漏报**。3.0.0 把这条原则推到了它的结论——不只是"新规则要满足判据机械"，而是"已经上线的规则若判据不机械，该删"。

### 与其他插件的关系

- 与 `omp` 插件互补：`omp` 的 `orchestrator-protocol-remind.js` 注入 omp 编排协议（强制委派 omp 子代理），本插件注入通用工作纪律（覆盖 Claude 原生 Agent 工具）——二者可并行启用。
- `bash-guard.js` 的 cd 检查原本在 `devkit-core`（现已更名 `devkit-tool`）的 `block-cd.js`，本插件 1.3.0 起迁入；`devkit-tool` 自 5.1.0 起不再内置任何 hook。同批删除的 `guard-full-read.js`（大文件全文读取拦截）因与「精确读文件」注入纪律重复，未一并迁入。
- `write-guard.js` 与另一个插件 `quality-lint` 的 md 200 行检查是同类思路（`PostToolUse` 上挂 Write/Edit、`[L1-BLOCKER]` 输出格式）但各自独立实现——两个插件归属不同、不互相依赖。**关于两者效力等级是否相同，本仓无法核实**：2026-07-31 全盘检索时本机未安装 `quality-lint` 插件本体（只在若干项目里留下 `.quality-lint-state.json` 状态文件），既读不到它的源码也读不到它的 README。若那边的文案写的是"拦截"而实现同样挂在 `PostToolUse`，就与本插件 3.6.0 修掉的是同一类效力虚高，值得那边自己核一次——但这句只是推断，不是本仓验证过的结论。
- `bash-guard.js` 的 agent-browser 检查管四道护栏（①鉴权 ②实例上限 ④安全边界提醒），不涉及浏览器自动化能力本身；怎么用对见独立插件 `agent-browser` 的 SKILL.md。本插件只在缺鉴权 / 实例超限时硬拦，不管值本身是否合法（如 `--profile` 指向哪个目录走各会话 memory / CLAUDE.md 约定）。
- 钉钉 dws CLI 写授权由 `radnove-core` 插件的 `pre-tool-use-dws-write.sh` 承担（`permissionDecision: "ask"`），本插件不再重复注入。

---

## 目录结构

```text
plugins/working-discipline/
├── .claude-plugin/plugin.json          # hook 注册（1 个注入脚本 + 3 个 guard，共 6 处挂载：
│                                       #   PreToolUse×2 + PostToolUse×1 + 三个注入时机×1）
├── hooks/
│   ├── working-discipline.js           # SessionStart / UserPromptSubmit / SubagentStart 注入
│   │                                   #   + 有图轮次条件注入图片路径清单
│   ├── lib/
│   │   ├── shell-parse.js              #   命令切分/分词/剥引号/剥子 shell/剥 heredoc 正文
│   │   │                               #   （bash-guard 两项检查共用；stripHeredocs 3.6.0 新增，
│   │   │                               #   括号匹配不感知引号的已知边界写在文件头）
│   │   └── prompt-images.js            #   从 UserPromptSubmit payload 提取图片绝对路径（纯函数，
│   │                                   #   不回读 transcript —— 那是 3.0.0 删掉的误判根源）
│   └── guards/
│       ├── agent-dispatch.js           # PreToolUse:Agent —— 7 项结构校验聚合报错；
│       │                               #   只缺 name 时用 updatedInput 自动补名放行
│       ├── bash-guard.js               # PreToolUse:Bash —— 裸 cd 开头污染 cwd + agent-browser
│       │                               #   启动四护栏（①鉴权 ②实例上限 ④安全边界），一次报清
│       └── write-guard.js              # PostToolUse:Write|Edit —— 源码 >1000 行 / 本项目内
│                                       #   CLAUDE.md >200 行；事后提醒，不回滚也不停轮
└── README.md
```

3.0.0 删除的文件：`guards/external-write-readback.js`、`guards/nonascii-path.js`、`guards/md-audience-declaration.js`、`lib/transcript.js`、`lib/notify-once.js`（判据靠猜或只服务已删 guard）；`guards/block-cd.js`、`guards/agent-browser-launch.js` 合并进 `bash-guard.js`；`guards/max-source-lines.js`、`guards/claude-md-max-lines.js` 合并进 `write-guard.js`。更早的 `agent-naming.js`（1.11.0）已在 2.0.0 并入 `agent-dispatch.js`。

## 自定义

- 增删注入条款 / 切换风格 → 编辑 `hooks/working-discipline.js` 里的 `SECTION_*` 数组，每行是 markdown 一行
- 调整 subagent 派发门禁 → 编辑 `hooks/guards/agent-dispatch.js`：`MODELS` / `EXEMPT_SUBAGENT_TYPES` / `NAME_PATTERN` / `NAME_MAX` / `NAME_PREFIX_SEPARATORS` / `PROMPT_LEAK_PREFIXES` / `DESC_BODY_MAX` / `ROUTING_TABLE`；自动补名的语义来源、哈希输入与长度预算在 `deriveSlug()` / `shortHash()` / `autoName()`，hint 里回显用户输入前先过 `toAsciiKebab()`；临时整体关闭用 `AGENT_DISPATCH_GUARD=off`（旧名 `AGENT_NAMING_GUARD=off` 同样有效）。**`LEAK_MATCH_MIN` 已在 3.6.0 随 prompt-prefix-overlap 检查整条删除**，不要再去找它
- 调整 `cd` 判定 → 编辑 `hooks/guards/bash-guard.js` 里的 `CD_PATTERN` / `parseCdTarget()` / `isNoOpCd()`（含 `PWD_TARGETS`）/ `isBackgrounded()` / `SEGMENT_ECHO_LIMIT`（finding 里回灌的违规片段长度）；heredoc 与子 shell 的剥离在 `hooks/lib/shell-parse.js` 的 `stripHeredocs()` / `stripSubshells()`
- 调整 agent-browser 启动类与白名单子命令 → 同文件的 `LAUNCH_SUBCOMMANDS` / `ALLOWLIST_SUBCOMMANDS`（两者并成 `ALL_KNOWN_SUBCOMMANDS`）/ `HELP_FLAGS` / `URL_PATTERN` / `ENV_ASSIGN_PATTERN`；四护栏判据在 `AUTH_FLAGS` / `AUTH_ENV_PATTERNS`（①鉴权）、`INSTANCE_LIMIT` / `countActiveInstances()`（②实例上限，测试桩 `WD_AB_INSTANCE_COUNT`）、`hasSafetyBoundary()`（④安全边界）
- 调整行数阈值 / 源码扩展名 / 排除路径 → 编辑 `hooks/guards/write-guard.js` 里的 `SOURCE_LINE_LIMIT` / `CLAUDE_MD_LINE_LIMIT` / `SOURCE_EXTENSIONS` / `GENERATED_PATH_PATTERN` / `GENERATED_NAME_PATTERN` / `RULES_DIR_PREFIX`（3.6.0 起 CLAUDE.md 的排除判据由旧常量 `EXCLUDED_SEGMENT_PATTERN` 那种"路径任意位置包含"改成了这个"项目内相对路径前缀"，旧常量已不存在）
- 调整截图路径的提取与条件注入 → 改 `hooks/lib/prompt-images.js` 的 `IMAGE_TAG_PATTERN` / `BARE_IMAGE_PATH_PATTERN`，或 `hooks/working-discipline.js` 的 `buildImageEvidence()`

> **判据是硬阻断行为的一部分，AI 不得自行修改。** 按仓库规则 `.claude/rules/hook-restraint.md` 第 4 条：发现判据有问题**只报不改**，把可复现的输入与实际输出交给用户拍板。
>
> 改注入文本时留一句自检：**这条规则能被机械判定吗？** 注意 3.0.0 给这个问题补的下半句——**判据是取自确定字段，还是靠正则猜语义？** 再注意 3.6.0 补的第三句——**取自确定字段不等于判据本身确定**，中间隔一层近似解析（切 shell 片段、匹配句式）就已经在猜了。前者做成 guard，后者留在 `SECTION_*` 里靠自觉，否则会造出「AI 做对了却过不去」的门禁。新增前先读 `.claude/rules/hook-restraint.md` 的强度阶梯：多数规则的正确落点是「注入提醒」而不是 `deny`。

---

版本 3.8.0 · 作者 zhangq · MIT
