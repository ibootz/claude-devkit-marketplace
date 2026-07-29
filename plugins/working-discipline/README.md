# Working Discipline

一个纯 hook 插件，用两种方式把「AI 工作纪律」落到 Claude Code 上：

1. **常驻注入**：每轮往主会话、以及每次子代理启动时的 context 里，塞入一份可审计、可复用的行为准则；本轮用户贴了截图时，额外附一份可原样复制的图片绝对路径清单
2. **硬拦截**：派发 subagent 时 `name` / `description` / `model` 等**结构字段**不合规（`PreToolUse` deny）、污染 cwd 的独立 `cd`、缺 `--headed`/`--profile` 的 `agent-browser` 启动（`PreToolUse` exit 2）；以及写入完成后拦超 1000 行源码文件、超 200 行 CLAUDE.md（`PostToolUse` exit 2）

零 skill、零命令、零子代理，装了就生效。不修改用户文件（拦截类 hook 只阻断"继续往下走"，不撤销已完成的写入），无副作用。唯一一处会改动工具调用的地方是**缺 `name` 时自动补名**，见第二章。

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

## 一、注入：主会话与子代理各注入什么

| 维度 | 关键约束 | 主会话 | 子代理 |
|------|---------|:---:|:---:|
| 一、上下文纪律 | 精确路径读文件、子代理优先、bash 输出限流、macOS 中文路径「空结果不得判无」 | ✅ | ✅ |
| 二、子代理协作 | 在飞≤16（靠自记账盘点，明确禁用 `TaskList` 统计——它是任务板不是在飞 agent 列表）、嵌套≤2、共享骨架文件、结构化回执 | ✅ | ✅ |
| 三、表达约束 | 关键对象点名、待确认四要素、行号引用、简体中文、列表编号 | ✅ | ✅ |
| 四、思维模式 | 举一反三 / 整体 / 第一性 / 逆向 / 自查自纠 / 读者视角 / 写 md 前受众分辨（含三分支要点） | ✅ | — |
| 五、Agent 派发 | 5.1 `subagent_type` 选择、5.2 三档 model 判定标尺（`sonnet` / `opus` / `fable`，**无 `haiku`**）、5.3 调用范式、5.4 派发命名要点索引、5.5 多 subagent 并发时等齐再总结、5.6 派发 prompt 必含三项 | ✅ | 仅 5.4 |
| 六、hook 边界清单 | 一份索引：三个 guard 各拦什么、哪些规则已删除因而没有兜底。**不复述细则** | ✅ | ✅ |
| 本轮证据（条件） | 本轮用户贴了截图时，附图片绝对路径清单；无图轮次一个字符都不注入 | ✅ | — |

子代理版带一~三节、五节的 5.4 派发命名规范（**完整版**）、六节索引。四节与五节其余部分主要是指导父代理如何选 `subagent_type` × `model`，对子代理自身价值低，故省 token 略去。

**5.4 为什么在子代理版保留完整版、主会话只留索引**：这是一处**有意的例外**。第 1 层子代理可以再派第 2 层（受二节的嵌套上限约束），派发时同样要给 `name` / `description`，而 `agent-dispatch` 硬门禁对**子代理发起的** `Agent` 调用一样生效。但两者处境不同——主会话每轮注入，被拦一次就学会了，索引足够；子代理**只在启动时注入一次**、且更可能对规范一无所知，被拦后只能靠 deny reason 反推。所以主会话走「索引 + 硬门禁」，子代理付这 2.5k 字符换「一次就写对」。章节编号与主版严格一致（子代理版为一、二、三、五、六，缺四），同一条规则不出现两套编号。

**外部写操作授权（原 dws 章）已从本插件移出**（2.0.0）：钉钉 dws CLI 的写授权改由 `radnove-core` 插件的 `hooks/pre-tool-use-dws-write.sh` 承担，`PreToolUse` 命中写子命令时输出 `permissionDecision: "ask"`，把「须获用户当次明确许可」这个语义要求变成 harness 强制的确认弹窗——比每轮注入 918 字符的自觉约束强得多。

> 完整注入文本见 `hooks/working-discipline.js` 里的 `SECTION_*` 数组。实测体积：主会话 9165 字符，子代理 8161 字符（3.0.0 把回执 / 截图 / 写后回读三条从 hook 搬回注入后的值）。

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

面板左列显示 `Agent` 工具的 `name`（未指定时回落显示 `subagent_type`），右列显示 `description`。这一屏同时暴露三个问题：四个 `name` 都不带模型档次前缀，用户看不出这批在飞任务烧的是 `sonnet` 还是 `opus`；这四个的右列全是 `prompt` 原文的开头「你是第 1 层子代理，可派…」，既把内部提示词暴露到 UI 上，又让四行描述完全同质、面板彻底失去"谁在做什么"的信息量；唯一合规的 `[sonnet] 映射 16 个 spe…` 那行反过来没给 `name`，左列回落成裸的 `general-purpose`。

对应的注入规则分四条：`name` 必填且同会话内不重名、格式 `模型名-任务语义`；`description` 必填、`[模型名]` 前缀 + 3-5 词任务摘要且**禁止与 `prompt` 共用同一段文字**；同批并发的名字必须互相可辨（`verdict-part1/2/3` 应改成把分片依据写进名字的 `sonnet-verdict-spec-01-05`）；`Workflow` 的 `meta.name` / `meta.description` / `meta.phases[].*` / `agent(prompt, {label})` 的 `label` 同规，其中 `meta.description` 会出现在权限确认弹窗里，粘 prompt 等于让用户在弹窗里读一段内部指令。

#### 为什么 AI「总是忘记传 `name`」：两套约束不同源

这不是注意力问题，是**结构性缺陷**。`Agent` 工具的 JSON Schema 里 `properties` 只声明了六个字段，还写着 `additionalProperties: false`：

| 约束 | 载体 | 关于 `name` |
|---|---|---|
| 调用层能接受什么 | `Agent` 工具 JSON Schema | `description` / `prompt` / `subagent_type` / `model` / `run_in_background` / `isolation` —— **不存在此字段** |
| 本插件要求什么 | `agent-dispatch` hook | 必填，格式 `<model>-<语义-kebab>` |

后者是前者的真子集**加一个额外必填项**，而加的这项 schema 里查不到。AI 构造工具调用时照 `properties` 列表生成参数，一个字段表里不存在的字段不会被"想起来"——所以缺 `name` 是必然，不是疏忽。

但 `name` 确实是运行时的一等公民，只是 schema 声明漏了。实证（2026-07-29）：一次带 `name` 的 `Explore` 派发，其元数据文件 `<项目 transcript 目录>/subagents/agent-a89132b5b2d9d0f67.meta.json` 内容是

```json
{"agentType":"Explore","description":"[sonnet] dbops 翻译 dimId/nodeId 并核权重",
 "name":"sonnet-dbops-translate-weight-ids","toolUseId":"toolu_01LFRkf1uMvs9RwnMpcoU9ca",
 "spawnDepth":1,"model":"sonnet"}
```

`name` 被接受并落盘。此外 `Agent` 工具的说明文字本身也反复提到它存在：「Use SendMessage with the agent's ID or **name** to continue a previously spawned agent」、「Use the raw `agentId` only when the agent **has no name**, or when a newer agent took the name」。一个能"没有 name"也能"被新 agent 抢走 name"的东西，显然是运行时的真实字段。

**3.0.0 的处置：缺 `name` 不再 deny，改用 `updatedInput` 自动补名放行。** 理由是 deny 只是把一次必然的返工固化下来——AI 看不见这个字段，罚它没有教育意义。同时注入侧（5.4 与 5.4.1）把「schema 里查不到它」这个根因和「凡调 `Agent`，先写 `name`，再写别的」这条硬编码前置写进去，让 AI 尽量自己命名，因为自动名的语义很弱（见下一章）。

**`subagent` 与 `teammate` 不必分两套规则**：是同一个 `name` 概念，差别只在用途权重。teammate 场景下 `name` 是 `SendMessage({to})` 的寻址键（没名字就只能用 raw `agentId`）；一次性 subagent 场景下它主要用于面板显示与事后追溯。两种场景的命名格式要求完全一致。

---

## 二、拦截：`agent-dispatch` 守 `Agent` 派发的结构字段

**触发条件**：`tool_name` 是 `Agent`。注意**不匹配旧工具名 `Task`**——旧名环境下的 `tool_input` 可能压根没有 `name` / `model` 字段，强制校验会造成永久性误拦，fail-open 优于误伤。

### 拦什么：8 项结构校验，多条一并列出

这类问题往往同时出现好几个（`name` 前缀不符 + `description` 抄 prompt + 超长），`findings` 聚合成一条 reason 一次报清，才能一次改对：

| # | 校验 | 为什么 |
|---|------|--------|
| 1 | `model` 缺失或不在 `sonnet`/`opus`/`fable` | 纪律要求显式指定，禁止默认回落。**这一条命中时额外附完整路由表**帮助选档。`model: "haiku"` 单独给一条 finding（「已从可选档次中移除，最低档是 sonnet」）而不是泛泛报「不在三档之内」——它是旧纪律下的合法档，是最高频的误填 |
| 2 | `name` 不以 `{model}-` 开头 | 前缀必须与实际 `model` 一致。`haiku-` 开头单独识别并给「改成 `sonnet-<原任务语义>`」的精确改法，避免回落到泛化分支后建议出 `sonnet-haiku-grep-refs` 这种把废弃档次名留在任务语义里的错名 |
| 3 | `name` 不满足 `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` | Agent 工具的原生约束，提前拦下来并给清楚提示（写中文会被工具直接拒） |
| 4 | `description` 缺失或不以 `[{model}] ` 开头 | 方括号内档次要与 `model` 一致。前缀正则里**仍保留 `haiku` 分支专供识别**（`^\[(sonnet\|opus\|fable\|haiku)\]`）：命中即报「用了已移除的档次」，若直接删掉这个分支，`[haiku] xxx` 会掉进「缺前缀」判定，连带解析不出正文、跳过后面三条泄露检测 |
| 5 | `description` 只有前缀没有正文 | 前缀后必须有 3-5 词任务摘要 |
| 6 | `description` 正文以角色设定句开头（`你是` / `You are` / `【` / `#` / `作为一名` 等） | 把 prompt 原文抄进 `description` 的高置信特征 |
| 7 | `description` 正文长度 ≥ 20 且正好是 `prompt` 的开头 | 抄袭特征。20 字符门槛用来避免误报——3-5 词摘要与 prompt 开头偶然重合的概率不低，短文本不判 |
| 8 | `description` 正文超过 60 字符 | 纪律要求 3-5 词摘要，超长说明塞了 prompt 内容 |

判据全部取自 `tool_input` 的确定字段，不猜语义、不回读 transcript，误判空间接近零——这是它在 3.0.0 的清理里被保留的唯一理由。

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

**自动名的构成**：`<model>-<语义>-<prompt 短哈希 4 位>`。语义来源优先级是「`description` 正文里的 ASCII 词（取前 4 个，≥2 字符）」→「`subagent_type` 转 kebab」。`description` 按纪律写的是中文任务摘要时抽不出 ASCII 词，就退回 `subagent_type`（`[opus] 修订单竞态` + `general-purpose` → `opus-general-purpose-7f2c`）——中文转写（拼音 / 翻译）在 hook 里不可靠，宁可给个语义弱但绝不出错的名。哈希以 `prompt` 为输入，保证同批并发的多个 agent 拿到不同的名（同名会让 `SendMessage` 的 latest-wins 寻址把先派的那个弄丢），且是纯函数、不需要持久状态。

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

```text
[L1-BLOCKER] tool=Agent check=agent-dispatch finding="name="verdict-part1" 缺模型档次前缀;description="你是第 1 层子代理..." 缺 [模型名] 方括号前缀" hint="name 改成 "sonnet-verdict-part1";description 改成 "[sonnet] <3-5 词任务摘要>";完整规范见注入纪律 5.4 节;确需临时关闭本门禁用 AGENT_DISPATCH_GUARD=off"
```

这道门禁**默认开启且全局生效**：其他插件或 skill 内部派发 subagent 时（如 `omp` 的强制委派、各类 spec 工作流），若它们不遵守本插件的命名规范，同样会被拦下来。这是**预期行为**——规范要统一才有意义——但如果它挡住了你必须跑的既有工作流：

```bash
AGENT_DISPATCH_GUARD=off   # 大小写不敏感，设为 off 即整条门禁放行
AGENT_NAMING_GUARD=off     # 1.11.0 起沿用的旧名，继续有效
```

想永久关闭就从 `.claude-plugin/plugin.json` 的 `PreToolUse` 里删掉这条 hook 注册；想放宽某类 agent，把它的 `subagent_type` 加进 `EXEMPT_SUBAGENT_TYPES`。

### Known Limitation：`Workflow` 内部的 `label` 拦不到

本 hook 只覆盖 `Agent` 工具的直接派发。`Workflow` 脚本内部 `agent(prompt, {label})` 的调用**不经过 `PreToolUse`**（它发生在 workflow 运行时的脚本执行层），因此 `label` 缺失或抄 prompt 都拦不到，只能靠注入纪律 5.4.4 约束。理论上可以拦 `Workflow` 工具本身、对 `script` 字符串做正则提取来校验 `meta.name` 与各 `agent()` 的 `label`，但正则解析 JS 源码的可靠性太低（易误判模板字符串、嵌套括号、注释里的调用），故未实现。

---

## 三、拦截：`bash-guard` 守 Bash 命令的两条硬边界

`PreToolUse` + matcher `Bash`，合并自原 `block-cd.js` 与 `agent-browser-launch.js`。两者原本各自读一遍 stdin、各自解析一遍命令行，且**串行短路**——第一个 guard 拦下后第二个根本不执行。合并后一次解析、一次把所有问题报清：

```text
[L1-BLOCKER] tool=Bash check=bash-guard finding="独立 `cd` 会污染后续所有 Bash 调用的 cwd(cwd=/x);违规片段：cd /var;agent-browser open 缺 --headed;起 headless CFT 会让用户看不到 AI 操作过程" hint="改用绝对路径,或子 shell `(cd /abs/path && cmd)`,git 命令优先 `git -C <path> <cmd>`;加 --headed(...)"
```

两条判据都是命令行的确定结构：`cd` 是 shell 的确定 token（由 `hooks/lib/shell-parse.js` 逐字符切分后精确定位，引号内的、子 shell 里的、no-op 的都能准确排除）；`agent-browser` 是命令名精确匹配 + 子命令词表精确匹配 + 参数存在性判定。**没有"猜意图"的成分**，这是它们在 3.0.0 的清理里被保留的理由。

### 检查一：独立 `cd` 污染 cwd

Bash 工具的 cwd 在多次调用之间**持久保留**。AI 中间执行一次 `cd /tmp`，后续所有相对路径操作都会失准——排查半天才发现是 cwd 被静默改掉了。

- **阻断**（exit 2）：命令链里存在会真正改动 cwd 的独立 `cd`
- **放行**：子 shell `(cd /path && cmd)`（cwd 不回流父进程）/ 命令替换 `$(cd /path && pwd)` / 字符串内的 `cd`（`echo "cd /tmp"`）/ **no-op cd**（目标解析后等于当前 cwd，如 `cd .`、`cd <当前目录绝对路径>`）

**stderr 控制在 400 字符量级**。2.0.0 之前这里是约 1500 字符的完整事故复盘，每次拦截都灌进上下文——**这本身就是本插件要治的"注意力抢占"的一个实例**，而且是最讽刺的一种：一个用来纠正行为的提示，自己占掉了比被纠正的行为更多的注意力。复盘搬进了源码文件头注释（给维护者读）。

**已知误报**：shell 函数定义 `cd() { ...; }` 会被判成独立 `cd`——tokenizer 只看到段首的 `cd` token，不区分「调用」与「定义」。真实触发过两次（2026-07-26 与 2026-07-29 本插件自身的开发会话）。这类写法本就罕见且没有必要，未做特判：加一条「后跟 `()` 则跳过」的规则会让解析器为一个近乎不存在的场景变复杂，而绕开的成本只是删掉那行。

#### Known Limitation：跨插件 cd 探测差异

`bash-guard` 只保证"AI 自己的 cwd 不被污染"，但它**不能**保证其他插件对同一条命令的 cwd 探测逻辑与 AI 实际使用的语法兼容——遇到时不要去改对方插件的探测逻辑，改 AI 自己发出的命令语法即可规避。

**事故来源（2026-07-20，D-001-feat-job-sequence-model 会话）**：subagent 要把改动 push 到 `claude-devkit-marketplace`（一个与当前项目完全无关的第三方仓库），用的命令是 `(cd /Users/zhangq/Workspace/mine/claude-devkit-marketplace && git push origin main)`——这条命令本身完全合法，本 guard 也正常放行。但推送被同时装着的 **sdlc 插件**拦截，报「BLOCKED: ontology 正向同步未收口 for D-001-feat-job-sequence-model」，一次跨仓库误伤。根因在 sdlc 插件 `hooks/lib/worktree-utils.js` 的 `resolveGitCwd()`：它用正则 `/^cd\s+.../` 匹配命令字符串**开头**的 `cd` 前缀来判定这条 git 命令作用于哪个仓库（同时显式支持 `git -C <path>`）。子 shell 语法 `(cd /path && cmd)` 带括号、不以 `cd` 开头，正则天然匹配不上，`resolveGitCwd()` 就 fall back 到当前会话所在的 worktree，把发往第三方仓库的 push 误认成 D-001 delivery 分支的 push。

**推荐用法**：涉及 git 命令时优先 `git -C <path> <cmd>`，而不是 `(cd /path && git ...)`。`-C` 是 git 官方支持的全局选项，语义等价，但字面上不含 `cd` token、不进子 shell，本 guard 放行，且各类插件的 cwd 探测正则通常会显式支持这种标准写法：

```bash
git -C /Users/zhangq/Workspace/mine/claude-devkit-marketplace push origin main
git -C /abs/path/to/repo status
```

非 git 命令仍然只能走 `(cd /path && cmd)` 子 shell 语法——`-C` 是 git 专有选项，不是通用 shell 机制。

### 检查二：`agent-browser` 启动缺 `--headed` / `--profile`

**`--headed` 的设计理由**：AI 用 agent-browser 时默认走 headless 起 Chrome for Testing（CFT）实例。虽然 CFT 与用户日常 Chrome 是两个不同的 app bundle、profile 可以完全隔离，但 headless 下**用户视角看不到 AI 在操作什么**——点了哪个按钮、填了什么表单、跳到哪个 URL、遇到什么弹窗，全是黑箱，用户会误以为 AI 没启动实例、或在动自己的 Chrome。真实事故：2026-07-20 D-001 verify 期间用户质疑"你现在是创建了一个 headless 的 chrome 浏览器实例吗？为啥我看还是在向我使用的 chrome 实例进行权限申请呢"。

**`--profile` 的设计理由**：同一会话里加了 `--headed` 之后暴露第二个问题——AI 默认用一次性临时 profile 目录起 CFT，目录里没有任何登录态，**每次会话都要在浏览器里重新登录一遍业务系统**。用户拍板方案：硬要求 `--profile`，引导 AI 复用一个专门建立、一次性登录好的 "AI Testing" profile 目录（与用户日常 `Default` profile 物理隔离，不会互相抢 `SingletonLock`），登录态跨会话持久化；纯隔离测试场景仍可用 `--profile "$(mktemp -d)"` 满足硬性要求。

判定顺序：命令里出现 `agent-browser` 或 `npx agent-browser` → 同一顶层片段内匹配到**启动类子命令** → 两条独立检查，命中任意一条即拦（都缺时 finding / hint 各列两条）。

| 启动类子命令 | 说明 |
|--------|------|
| `open` | 打开新页面/新实例 |
| `connect` | 连接并拉起实例 |
| `chat` | 仅当后面接了 URL 位置参数才算启动；纯 REPL 模式不拦 |

**探测/后续操作类子命令一律放行**：只读探测（`skills` `doctor` `install` `upgrade`）、生命周期无关（`close` `mcp` `dashboard` `session` `plugin` `auth` `profiles` `confirm` `deny`）、后续操作类（`snapshot` `click` `fill` `type` `screenshot` `eval` `network` `tab` 等一整套）。子命令识别用的是「第一个与已知词表精确匹配的 token」，不是"第一个非 flag token"——`--profile /tmp/foo` 这类 flag 接值的写法，值本身不在词表里会被自然跳过。

正确调用示例：

```bash
agent-browser --headed --profile "/Users/<user>/Library/Application Support/Google/Chrome/Profile 1" open https://example.com
AGENT_BROWSER_HEADED=true AGENT_BROWSER_PROFILE=/tmp/ab-profile agent-browser open https://example.com   # 环境变量等价
agent-browser --headed false --profile /tmp/ab-profile open https://example.com   # 显式选择 headless，仍需带 --profile
agent-browser --headed --profile "$(mktemp -d)" open https://example.com          # 纯隔离测试场景
```

#### AI Testing profile 创建与使用指南

**一次性设置步骤（用户端操作，AI 不能代做）**：

1. 打开 Google Chrome（用户日常在用的那个，不是 CFT）→ 点右上角头像 → 选"添加"/"Add" → 输入 profile 名字，比如 `AI Testing`（名字随意，只是 UI 显示名，不影响磁盘路径）→ 完成创建
2. 在这个新窗口里手动登录一次目标业务系统
3. 在同一个 `AI Testing` profile 窗口里（**不是** `Default` 窗口）打开 `chrome://version/`，找到 "个人资料路径" / "Profile Path"，复制绝对路径。macOS 上通常形如：

   ```text
   /Users/<user>/Library/Application Support/Google/Chrome/Profile 1
   ```

   注意：`AI Testing` 是 UI 显示名，磁盘上的实际目录名是 `Profile N`（`N` 取决于这是第几个非 Default profile），两者不是同一个字符串
4. 把这个路径记到项目 `CLAUDE.md` 或个人 memory 里，后续所有 `--profile` 都指向它

**关键坑警告**：macOS 上用户日常 Chrome 主实例只要正在运行，它当前打开的那个 profile 目录就会被 `SingletonLock` 独占——如果 CFT 用同一个 profile 目录起，会**强制关掉用户日常 Chrome 或者干脆起不来**。这正是为什么 `AI Testing` **必须是一个与用户日常主力 profile（通常是 `Default`）不同的独立 profile**。相应地，AI 用 CFT 跑 `AI Testing` 期间，用户不要手动把自己的 Chrome 窗口切到 `AI Testing`，否则会跟 CFT 抢锁。

**豁免场景**：任务本身就是"隔离测试、完全不带登录态"（比如测一个匿名可访问的公开页面）时，用 `--profile "$(mktemp -d)"` 起一个全新干净的目录，同样满足硬性要求。不要误以为"任何时候都必须用 `AI Testing` 这一个固定 profile"。

---

## 四、拦截：`write-guard` 守文件行数

`PostToolUse` + matcher `Write|Edit`，合并自原 `max-source-lines.js` 与 `claude-md-max-lines.js`。两条检查互斥（一个文件不可能同时是 `.md` 和源码扩展名），合并的收益不在"一次报两条"，而在消除一次进程启动 + 一次重复的 `readFileSync`——`PostToolUse` 每次写文件都触发，这是热路径。

**注意这是 `PostToolUse`**：文件已经写完，阻断的是"继续往下走"而非撤销这次写入。

### 检查一：单一源码文件 > 1000 行

行数超硬阈值是"职责过大"的信号——该文件大概率在做不止一件事，继续往里堆代码只会让可读性、可测试性、review 成本一起变差。这条只管"行数"这一个维度，语法/风格交给 linter。

- **命中扩展名**（小写比对）：`.java .js .ts .jsx .tsx .vue .py .go .rs .rb .php .cpp .cc .cxx .c .h .hpp .cs .kt .swift .m .mm .css .scss .sass .less .sql`——`.md .json .yaml .yml .toml .env .lock` 等非源码文件不受约束
- **判定**：命中扩展名 AND 落盘后总行数（按 `\n` 分割，空文件计 0 行）> 1000
- **阻断**：`[L1-BLOCKER] file={相对路径} check=write-guard finding="{N} lines exceeds source limit 1000" hint="按职责拆分模块,不要继续在同一文件堆代码"`

### 检查二：CLAUDE.md > 200 行

这条要解决的不是"CLAUDE.md 不许长"，而是**"不许靠压缩正文来规避长"**。真实事故：某项目的 CLAUDE.md 逼近阈值后，AI 把原本 3 段独立的踩坑记录（症状 / 根因 / 解法三段式）硬压成 1 段紧凑文字塞进 200 行以内——压缩过程中丢掉了完整因果链、具体的 `file:行号` 引用、以及未来 AI 需要的典型与边界场景示例，表面"合规"了，但作为纪律文档的可用性被严重削弱。正确做法是拆分结构：CLAUDE.md 只保留"一览目录 + 短标题 + 相对路径引用"，细节各自落成 `.claude/rules/{topic}.md`（不受 200 行限制），CLAUDE.md 里用 markdown 相对链接指过去。

- **命中文件**：`basename` 不区分大小写等于 `claude.md`（`CLAUDE.md` / `claude.md` / `Claude.Md` 均命中），且不限于仓库根——多 CLAUDE.md 项目里子目录下的同名文件同样受约束
- **排除**：路径含 `.claude/rules/` 目录段的文件不受限——这正是拆分后应当落脚的地方
- **阻断**：`hint` 明确指路 `拆到 .claude/rules/{topic}.md 用相对链接引用,禁止压缩正文导致约束丢失`，不是只报一个数字让 AI 自己瞎猜怎么合规

**两条共用的放行场景**：`tool_name` 不是 `Write`/`Edit` / 两条检查都不适用（此时不读盘）/ `file_path` 缺失 / 文件读取失败（竞态删除等基础设施异常不误拦）。

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
| 结构化回执 / 截图附绝对路径 / 写后回读传染 | 注入 5.6「派发 prompt 必须包含的三项内容」，标题里明写「没有 hook 兜底，漏了不会有人拦你」 |
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
UserPromptSubmit（主会话每轮） 或 SubagentStart（子代理启动时）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/working-discipline.js
   ↓  读 stdin 的 hook_event_name 分流：
   ↓    UserPromptSubmit → 一、二、三、四、五（含 5.4 索引、5.6 三项）、六（hook 边界清单）
   ↓                       + 经 lib/prompt-images.js 扫 payload：有图才追加图片路径清单
   ↓    SubagentStart    → 一、二、三、5.4 命名规范完整版、六（缺四；缺 5.1-5.3、5.5-5.6）
   ↓
stdout 输出 { hookSpecificOutput: { hookEventName, additionalContext } }
   ↓
Claude Code 把 additionalContext 拼进对应 context
（SubagentStart 的注入只进子代理自己的 transcript，不入主会话）
```

**拦截 hook**（`hooks/guards/agent-dispatch.js`）

```text
PreToolUse（Agent 工具调用前）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/guards/agent-dispatch.js
   ↓  读 stdin 的 tool_name / tool_input：
   ↓    AGENT_DISPATCH_GUARD=off 或 AGENT_NAMING_GUARD=off → 放行（总开关）
   ↓    tool_name 不是 Agent → 放行（不匹配旧名 Task，避免永久误拦）
   ↓    subagent_type ∈ {fork, statusline-setup, output-style-setup} → 放行
   ↓  8 项结构校验，聚合所有 finding：
   ↓    model 显式且合法 / name 前缀符 model·满足原生正则
   ↓    description [模型名] 前缀符 model·有正文
   ↓    description 正文非角色句 / 非 prompt 开头逐字重合 / ≤60 字符
   ↓    有 finding → deny（model 非法时额外附完整路由表）
   ↓  只缺 name（其余全过）：
   ↓    autoName() = <model>-<description ASCII 词或 subagent_type>-<prompt 哈希 4 位>
   ↓    → 输出 updatedInput 补名 + additionalContext 告知，不带 permissionDecision
   ↓  全过 → 放行
```

**拦截 hook**（`hooks/guards/bash-guard.js`）

```text
PreToolUse（Bash 工具调用前）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/guards/bash-guard.js
   ↓  读 stdin 的 tool_input.command 与 cwd，一次解析、两项检查全跑：
   ↓  【检查一】剥离子 shell / 命令替换 → 切分顶层片段 → 逐个判定 cd
   ↓    存在会改变 cwd 的独立 cd → 记 finding（附违规片段）
   ↓  【检查二】定位 agent-browser（或 npx agent-browser）→ 匹配子命令
   ↓    子命令不属于启动类（open/connect/带 URL 的 chat） → 跳过
   ↓    缺 --headed（非 --headed false / AGENT_BROWSER_HEADED=true）→ 记 finding
   ↓    缺 --profile <值>（非 AGENT_BROWSER_PROFILE=<值>）→ 记 finding
   ↓  有 finding → exit 2 阻断（stderr 一次输出全部 finding + hint）
   ↓  无 finding → exit 0 放行
```

**拦截 hook**（`hooks/guards/write-guard.js`）

```text
PostToolUse（Write / Edit 工具写入完成后）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/guards/write-guard.js
   ↓  读 stdin 的 tool_input.file_path 与 cwd：
   ↓    既不是源码扩展名、也不是 CLAUDE.md → exit 0 放行（不读盘）
   ↓    路径含 .claude/rules/ 目录段的 claude.md → 不按 CLAUDE.md 判（拆分页不受限）
   ↓    读落盘后文件内容，按 \n 分割计数行数
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
- `write-guard.js` 与另一个插件 `quality-lint` 的 md 200 行拦截是同类思路（`PostToolUse` 拦 Write/Edit、`[L1-BLOCKER]` 输出格式）但各自独立实现——两个插件归属不同、不互相依赖。
- `bash-guard.js` 的 agent-browser 检查只管两个启动参数（`--headed` 与 `--profile`），不涉及浏览器自动化能力本身；`--profile` 具体指向哪个目录走各会话的个人 memory / 全局 CLAUDE.md 约定，本插件只在缺参数时硬拦，不管值本身是否合法。
- 钉钉 dws CLI 写授权由 `radnove-core` 插件的 `pre-tool-use-dws-write.sh` 承担（`permissionDecision: "ask"`），本插件不再重复注入。

---

## 目录结构

```text
plugins/working-discipline/
├── .claude-plugin/plugin.json          # hook 注册（1 个注入脚本 + 3 个 guard，共 5 处挂载）
├── hooks/
│   ├── working-discipline.js           # UserPromptSubmit / SubagentStart 常驻注入
│   │                                   #   + 有图轮次条件注入图片路径清单
│   ├── lib/
│   │   ├── shell-parse.js              #   命令切分/分词/剥引号剥子 shell（bash-guard 两项检查共用）
│   │   └── prompt-images.js            #   从 UserPromptSubmit payload 提取图片绝对路径（纯函数，
│   │                                   #   不回读 transcript —— 那是 3.0.0 删掉的误判根源）
│   └── guards/
│       ├── agent-dispatch.js           # PreToolUse:Agent —— 8 项结构校验聚合报错；
│       │                               #   只缺 name 时用 updatedInput 自动补名放行
│       ├── bash-guard.js               # PreToolUse:Bash —— 独立 cd 污染 cwd + agent-browser
│       │                               #   启动缺 --headed/--profile，两项一次报清
│       └── write-guard.js              # PostToolUse:Write|Edit —— 源码 >1000 行 / CLAUDE.md >200 行
└── README.md
```

3.0.0 删除的文件：`guards/external-write-readback.js`、`guards/nonascii-path.js`、`guards/md-audience-declaration.js`、`lib/transcript.js`、`lib/notify-once.js`（判据靠猜或只服务已删 guard）；`guards/block-cd.js`、`guards/agent-browser-launch.js` 合并进 `bash-guard.js`；`guards/max-source-lines.js`、`guards/claude-md-max-lines.js` 合并进 `write-guard.js`。更早的 `agent-naming.js`（1.11.0）已在 2.0.0 并入 `agent-dispatch.js`。

## 自定义

- 增删注入条款 / 切换风格 → 编辑 `hooks/working-discipline.js` 里的 `SECTION_*` 数组，每行是 markdown 一行
- 调整 subagent 派发门禁 → 编辑 `hooks/guards/agent-dispatch.js`：`EXEMPT_SUBAGENT_TYPES` / `DESC_BODY_MAX` / `PROMPT_LEAK_PREFIXES` / `LEAK_MATCH_MIN` / `NAME_PATTERN` / `ROUTING_TABLE`；自动补名的语义来源与长度预算在 `deriveSlug()` / `autoName()`；临时整体关闭用 `AGENT_DISPATCH_GUARD=off`（旧名 `AGENT_NAMING_GUARD=off` 同样有效）
- 调整 `cd` 拦截行为 / agent-browser 启动类与白名单子命令 → 编辑 `hooks/guards/bash-guard.js` 里的 `CD_PATTERN` / `isNoOpCd()` / `LAUNCH_SUBCOMMANDS` / `ALLOWLIST_SUBCOMMANDS`
- 调整行数阈值 / 源码扩展名 / CLAUDE.md 排除目录 → 编辑 `hooks/guards/write-guard.js` 里的 `SOURCE_LINE_LIMIT` / `CLAUDE_MD_LINE_LIMIT` / `SOURCE_EXTENSIONS` / `EXCLUDED_SEGMENT_PATTERN`
- 调整截图路径的提取与条件注入 → 改 `hooks/lib/prompt-images.js` 的 `IMAGE_TAG_PATTERN` / `BARE_IMAGE_PATH_PATTERN`，或 `hooks/working-discipline.js` 的 `buildImageEvidence()`

> 改注入文本时留一句自检：**这条规则能被机械判定吗？** 注意 3.0.0 给这个问题补的下半句——**判据是取自确定字段，还是靠正则猜语义？** 前者做成 guard，后者留在 `SECTION_*` 里靠自觉，否则会造出「AI 做对了却过不去」的门禁。

---

版本 3.0.0 · 作者 zhangq · MIT
