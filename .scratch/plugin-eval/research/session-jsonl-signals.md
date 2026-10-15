# 会话 jsonl 能给「会话复盘」提供哪些信号

调研时间：2026-10-14。本机 Claude Code 会话文件里的 `version` 字段取值范围是 2.1.263 到 2.1.299（共 23 个版本）。
出处：**本机实测**，没有读官方文档，也没有追源码。jsonl 的字段是 Claude Code 的内部落盘格式，按本机观察写，不保证稳定。
标「未查到」的是样本里没有出现、或没法从字段推断的，没有臆测。
隐私：本文只含字段名、JSON 结构、计数与占位值（`<plugin>`、`<version>` 一类）。不含对话原文、文件内容、工具结果正文、项目目录名、会话 id。

## 方法与样本

- 工具：`python3 -I` 脚本，逐行 `json.loads`，只统计键名、枚举值、布尔与计数。脚本放在本机作业目录，不入仓。
- 范围：`~/.claude/projects/**/*.jsonl`，只取修改时间在近 30 天内的文件。

| 口径 | 项目数 | 主会话文件 | 子代理文件 |
|---|---|---|---|
| 全量扫描（违规与拦截、归因、子代理关联、去重统计用） | 137 | 611 | 1227（挂在 184 个父会话下） |
| 字段结构普查（记录类型、附件类型、字段集合） | 8 | 48 | 52 |
| 专题抽样（skill、Agent 入参、hook 配对用） | 8 到 12 | 每项目最近 6 到 15 个 | 随主会话 |

- 全量扫描里约 100 个项目只有 1 个会话，其中有多少是 `claude -p` 或 eval 沙箱留下的，没有逐个核实。`entrypoint` 取值 `cli` / `sdk-cli` 可用来过滤。
- 同一份历史会被 resume / fork 复制进新文件，见第四节「去重」。

## 五问结论

| # | 问题 | 结论 | 主要字段路径 |
|---|---|---|---|
| 1 | skill 调用，模型自动 vs 用户 `/<skill>` | **能** | 自动：`message.content[].input.skill`（`name=="Skill"` 的 `tool_use`）；手动：user 记录 `message.content` 字符串里的 `<command-name>`；归因：assistant 记录的 `attributionSkill` |
| 2 | hook 输出留痕、能否归到插件 | **部分能** | 留痕：`attachment.type` 取 `hook_success` / `hook_additional_context` / `hook_blocking_error` 等；deny：user 记录 `message.content[].content`（`is_error:true`，开头 `PreToolUse:<Tool> hook error: [<command>]`）与 `permissionDecision`；归插件靠展开后的 cache 路径、`<plugin>@<marketplace>` 尾注或脚本指纹，不是每条都有 |
| 3 | 环境插件清单与版本 | **部分能** | 会话内：`attachment.skill_listing.names[]`；会话外：`~/.claude/plugins/installed_plugins.json`（只有当前态）。历史版本还原不了 |
| 4 | 子代理关联、compact 留痕 | **能** | 子代理：`subagents/agent-<id>.meta.json` 的 `toolUseId` 对父会话 `tool_use.id`；compact：`system` 记录 `subtype:"compact_boundary"` 的 `compactMetadata` |
| 5 | 违规模式机械检出 | **部分能** | `Agent` 缺 `model`：`tool_use.input` 无 `model` 键；`cd-guard` 拦截：tool_result 文本含 `check=cd-guard`。语义类违规与「该触发没触发」不能 |

## 一、skill 调用

**模型自动调用**：assistant 记录 `message.content[]` 里 `type=="tool_use"` 且 `name=="Skill"` 的块。
- 入参 `input.skill`，可选 `input.args`。样本 139 次，键集合只有 `{skill}`（80）与 `{skill,args}`（59）两种。
- `input.skill` 的形态：带冒号的 `<plugin>:<skill>` 131 次，不带冒号的裸名 8 次（用户级或项目级 skill）。
- 配对结果在随后的 user 记录：顶层 `toolUseResult` 是 `{success:bool, commandName:str}`（137 次），失败时是字符串（2 次）。

**用户输入 `/<skill>`**：user 记录的 `message.content` 是字符串，含 `<command-message>…</command-message>` 与 `<command-name>/<name></command-name>`。
- `<name>` 带冒号（`<plugin>:<skill>`）53 次，裸名 49 次。
- 紧接着常有一条 `isMeta:true` 的 user 记录（样本 55/102），装展开后的 skill 正文；另有 31 次后面跟的是 `system` 记录，属于内置命令一类。
- **内置命令（如清屏）与 skill 共用这种形态**，统计 skill 时要拿 `skill_listing.names[]` 过滤。

**两条路径的区分**：Skill 工具走 assistant 的 `tool_use`；斜杠走 user 记录的 `<command-name>`。两者字段不同，可以机械区分。
- 用户记录上 `promptSource` 取值 `typed`（139）、`system`（78）、`sdk`（11）、`suggestion_accepted`（7）、`queued`（3），可辅助判断是不是人敲的。

**归因字段（更直接的信号）**：assistant 记录上的 `attributionSkill`（`<plugin>:<skill>`）与 `attributionPlugin`（`<plugin>`）。
- 全量扫描里 15289 条 assistant 记录带这两个字段（主会话 11347、子代理 3942）。2.1.263 起就有。
- 每个会话里**首次出现**该字段时，前面已有对应 Skill 工具调用 233 次，已有对应斜杠输入 104 次；主会话里两者都没有 13 次，子代理里 100 次（原因未查到，可能是 agent 类型自带 skill）。
- 它**不是粘性的**：首次出现之后只有约 22% 的 assistant 记录带它。该字段由有变无共 266 次，其中 238 次发生在下一条人类 prompt 之后，所以大致是「本轮 prompt 内处于该 skill 影响下的 assistant 回合」。精确语义未查到。
- `attributionPlugin` 恒等于 `attributionSkill` 冒号前的部分（442 次）。裸名 skill 没有 `attributionPlugin`（8 次）。

**compact 之后**：`attachment.type=="invoked_skills"` 的 `skills[]`，每项 `{name, path, content}`；`path` 的形态是 `plugin:<plugin>:<skill>`，不是文件系统路径。

**局限**：没触发的 skill 没有任何记录。jsonl 只能给分母（会话、`skill_listing` 里有这个 skill）与实际调用，「该触发而没触发」得靠规则或评委判。

## 二、hook 输出

### 2.1 留痕在哪

hook 的执行结果以 `type:"attachment"` 记录落盘，`attachment.type` 取值与样本计数如下（普查口径，8 个项目）：

| attachment.type | 计数 | 字段（除公共字段外） |
|---|---|---|
| `hook_success` | 3109 | `command` `stdout` `stderr` `exitCode` `durationMs` |
| `hook_additional_context` | 3325 | `content[]`（字符串数组） |
| `hook_system_message` | 51 | `content` |
| `hook_blocking_error` | 11 | `blockingError.{blockingError, command}` |
| `hook_non_blocking_error` | 12 | `stderr` `stdout` `exitCode` `command` `durationMs` |
| `async_hook_response` | 9 | `processId` `response` `stdout` `stderr` `exitCode` |

- 公共字段：`hookName`、`hookEvent`、`toolUseID`。
- `hookName` 形态：`<Event>:<matcher>`（如 `PreToolUse:<Tool>`、`SessionStart:startup`），UserPromptSubmit 与 Stop 常是不带冒号的裸名。
- `SessionStart` 的 matcher 取值见到 `startup` 895、`compact` 735、`resume` 123、`clear` 67、`fork` 13。**compact 之后 SessionStart 确实重新执行**，可以直接核对注入是否重放。
- 按事件计数（`hook_success`）：PreToolUse 1882、SessionStart 591、UserPromptSubmit 523、PostToolUse 101、Stop 12。
- `hook_success.stdout` 是 hook 原样输出的字符串。能解析成 JSON 的里面，主要键是 `hookSpecificOutput.{hookEventName, additionalContext, permissionDecision, permissionDecisionReason, updatedInput}` 与 `systemMessage`。
- `Stop` 事件另走 `system` 记录：`subtype:"stop_hook_summary"`，字段 `hookCount`、`hookInfos[{command,durationMs}]`、`hookErrors[]`、`hookAdditionalContext`、`preventedContinuation`、`stopReason`、`hasOutput`。

### 2.2 deny / ask / 报错

- **PreToolUse deny**：落在 user 记录的 `message.content[]`，块 `type:"tool_result"`、`is_error:true`，`content` 字符串开头是 `PreToolUse:<Tool> hook error: [<展开后的 command>]: <hook 的 stderr>`。
  - 同一条 user 记录上 `toolDenialKind:"permission-rule"`（hook deny 也被标成这个，所以**它不能用来区分 hook deny 与权限规则 deny**），顶层 `toolUseResult` 是字符串。
  - 2.1.294 起还有 `permissionDecision:{decision:"reject", reasonType:"hook", source:"hook"}`，全量计数 508。这个才是 hook deny 的干净标记。
  - 子代理文件里同样如此。
- **PreToolUse ask**：`hook_success.stdout` 里 `hookSpecificOutput.permissionDecision:"ask"`（60 次）。用户的答复落在后续 user 记录的 `permissionDecision`：`{accept, source:"user_temporary"}`（21 次）或 `{reject, source:"user_reject"}`（1 次）。
- **JSON 形态的 deny**（`permissionDecision:"deny"`）：样本里一次也没出现，未查到落点。
- **PostToolUse 阻断**：`hook_blocking_error` 附件，`blockingError.command` 是展开后的完整路径（全量 1040 主 + 1742 子代理，全部展开）。
- **hook 脚本自身出错**：`hook_non_blocking_error`，样本 12 条，`exitCode` 全是 1，分布在 UserPromptSubmit、PreToolUse、PostToolUse、Stop。「找不到 node」一类的 exit 126 没有样本，未查到是否同样落这里。
- **改写入参**：`updatedInput` 只出现在 `hook_success.stdout`。assistant 记录里的 `tool_use.input` 是**改写前**的。样本中 `Agent` 被 hook 改写 488 次，改写前后唯一的差别是补了 `name` 键（改写前没有）。

### 2.3 注入内容

- `hook_additional_context.content[]` 就是注入文本本身，按 `hookEvent` 可分 UserPromptSubmit（1512）、PreToolUse（1706）、SessionStart（95）、PostToolUse（7）、Stop（5）。
- **这类附件没有 `command` 字段**。想知道它来自哪个脚本，得和同一 `(toolUseID, hookEvent, hookName)` 的 `hook_success` 配对：普查样本里 3325 条中 1607 条配不上，1585 条一对一，133 条对到多个（同一事件有多个插件都响应）。所以**配对只能当辅助**。
- `toolUseID` 的形态：PreToolUse / PostToolUse 是对应 `tool_use.id`；UserPromptSubmit 是 `hook-<uuid>`；SessionStart 是 `SessionStart:<matcher>` 类字符串。

### 2.4 能否归到具体插件

| 路径 | 给出什么 | 覆盖面 |
|---|---|---|
| `hook_success.command` / `stop_hook_summary.hookInfos[].command` | 未展开的 `${CLAUDE_PLUGIN_ROOT}/hooks/<脚本>`，**不含插件名** | 全部 hook_success 都有，但脚本名会撞（`session-start.js`、`user-prompt-submit.sh` 在多个插件里同名） |
| PreToolUse deny 的 tool_result 文本 | 展开后的 `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/hooks/...`，得到**插件名与版本** | 只覆盖 deny 事件；样本 179 条全可解 |
| 同一文本的尾注 `This hook comes from the <plugin>@<marketplace> plugin` | 直接给插件名 | 2.1.281 起才有，样本 179 条里 59 条带 |
| `hook_blocking_error.blockingError.command` | 展开路径 | 只覆盖 PostToolUse 阻断 |
| `additionalContext` 文本里作者自带的标签 | 如本仓注入的标题含 `devkit-<name>` | 3325 条里 535 条含 `devkit-` 字样，约 16%；依赖作者自觉，别的插件没有 |
| 被测插件的 `hooks.json` 做指纹 | 事件 + matcher + 脚本相对路径 → 对 `hookName` 与 `command` | 脚本名被其它插件共用时有歧义，要加「同事件里输出内容」交叉 |

- **改名陷阱**：cache 路径里的插件目录名是**当时**的名字。样本里 `cd-guard` 的路径有 150 次是改名前的旧目录名，5 次是 `devkit-cd-blocker`。归一要用 `.claude-plugin/marketplace.json` 的 `renames`。
- 结论：**能把 deny 类事件稳定归到 `<plugin>@<version>`；注入类事件只能靠脚本指纹加内容标签，不是 100%**。06 的重开条件「jsonl 无法把现象归到具体插件」对 deny 与 skill 不成立，对「无标签的纯注入」成立一半。

## 三、环境插件清单

**会话内能拿到的**：
- `attachment.type=="skill_listing"`，会话首次（`isInitial:true`）带 `names[]` 与 `skillCount`。`names[]` 里 `<plugin>:<skill>` 形态占绝大多数（样本约 25433 比 3006），去掉冒号后半段即得到**有 skill 的插件名集合**。只含项目、本地、用户三层里实际生效的，所以会比用户级 `enabledPlugins` 多。
- `attachment.type=="agent_listing_delta"` 的 `addedTypes[]`，插件自带 agent 是 `<plugin>:<agent>` 形态。
- 实际触发过的 hook，见 2.4。
- 记录顶层 `version` 是 **Claude Code 的版本，不是插件版本**。

**会话内拿不到的**：插件版本；纯 hook 插件（没有 skill 与 agent）的存在，只能从它的 hook 记录反推。

**会话外的本地文件**（都只有**当前态**）：
- `~/.claude/settings.json` 的 `enabledPlugins`（用户层；项目层与本地层在各项目的 `.claude/settings*.json`）。
- `~/.claude/plugins/installed_plugins.json`：`plugins.<name>@<marketplace>[]`，每项 `{scope, projectPath, installPath, version, installedAt, lastUpdated, gitCommitSha}`。`scope` 取值 `user` / `project` / `local`；`projectPath` 含项目目录名，**抽取结果里不能带**。
- `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`：50 个插件里 49 个只留 1 个版本，**历史版本还原不了**。
- `installed_plugins.json` 有零星的 `.bak.<日期>` 快照，不构成连续记录。

**结论：部分能**。能还原「有 skill 的插件名集合」和「当前装的版本」；还原不了「该会话当时每个插件是哪个版本」。可行做法是复盘脚本**在跑的时刻**读一次 `installed_plugins.json` 并把 `<plugin>@<version>` 写进抽取结果，同时承认离会话发生时间越远越不准。deny 事件的路径带版本，可作为这一条的校验。

## 四、会话关联

### 子代理

- 文件布局：`<project>/<sessionId>.jsonl`（主）、`<project>/<sessionId>/subagents/agent-<agentId>.jsonl` 与同名 `.meta.json`。
- `.meta.json` 的键：`agentType`、`description`、`model`、`name`、`requestNonInteractive`、`requestShape`、`spawnDepth`、`toolUseId`。
  - `toolUseId` 对应父会话里派发它的那个 `Agent` 的 `tool_use.id`，**这是关联的主键**。
  - `spawnDepth` 给嵌套层数。
- 父会话的配对 tool_result：顶层 `toolUseResult` 键集合 `{agentId, status, isAsync, resolvedModel, description, prompt, outputFile, canReadOutputFile}`，部分多一个 `canContinueAgent`（336 次里 31 次）。`agentId` 对子代理文件名，`resolvedModel` 是实际用的模型。
- 子代理文件每行 `isSidechain:true`、带 `agentId`；`sessionId` 与父会话 id 一致（59 个里 57 个，另 2 个不一致，原因未查到）。首行是 user（派发的 prompt）。
- **子代理里 hook 与 skill 信号都在**：子代理文件含 `hook_success`、`hook_additional_context`、`hook_blocking_error`、`attributionSkill`。普查口径下子代理文件里 `hook_blocking_error` 有 178 条，`hook_success` 有 376 条。所以复盘必须把子代理文件并入统计，否则漏掉近半数拦截（全量 `check=cd-guard` 拦截：主会话 810 条 tool_result，子代理 1041 条）。

### compact 与会话续接

- compact：`type:"system"`、`subtype:"compact_boundary"`，带 `compactMetadata.{trigger, preTokens, postTokens, cumulativeDroppedTokens, durationMs, preservedSegment, preservedMessages}` 与 `logicalParentUuid`。样本 116 次，`trigger` 全是 `auto`，手动触发未见到。
- 紧随其后：user 记录 `isCompactSummary:true`（摘要，原文不要抄）、`SessionStart:compact` 的 hook 附件、`invoked_skills` 附件。
- 续接类事件：`SessionStart:resume` / `fork` / `clear`；顶层记录 `continued-in`（`{sessionId, continuedInSessionId}`）。
- **去重**：42 个有多文件的项目里，user 与 assistant 记录的 `uuid` 约 11%（8001/71007）出现在不止一个文件里，是 resume / fork 复制了历史。**按 `uuid` 去重后再数**，否则同一次 skill 调用或违规会被重复计数。
- 其它会话级记录：`ai-title`、`custom-title`、`last-prompt`、`agent-name`、`permission-mode`、`cost-state`（含 `totalCostUSD`、`modelUsage`，可给成本估算用）。

## 五、违规模式机械检出

| 违规 | 检出方式 | 结论 |
|---|---|---|
| 派发 `Agent` 不带 `model` | assistant `message.content[]` 中 `name=="Agent"` 的 `tool_use`，`input` 无 `model` 键。样本 326 次里 1 次缺（该次入参键是 `{description, prompt, run_in_background, subagent_type}`），其余 325 次 `model` 取值 `sonnet`（300）或 `opus`（25） | 能 |
| `Agent` 不带 `name` | 同上判 `input.name`。**要读 `tool_use.input`（hook 改写前），不要读 hook 改写后的值**，否则被自动补名遮住 | 能 |
| `cd-guard` 拦截 | user 记录 tool_result，`is_error:true` 且文本含 `check=cd-guard`；2.1.294 起再加 `permissionDecision.reasonType=="hook"` | 能 |
| Bash 命令内容违规（如以 `cd` 开头） | `tool_use.input.command` 正则 | 能，见下方注意 |
| 注入是否在场（作 treatment 证据） | `hook_additional_context` 中是否有该插件的标签文本；`SessionStart:compact` 是否重放 | 部分能，靠内容标签 |
| 被 hook 拦下的违规 vs 没被拦的违规 | 前者有 deny 记录；后者只有 `tool_use`，没有任何 hook 记录，只能靠入参规则 | 部分能 |
| 语义与文风类违规（排版、措辞、是否「先问再做」） | 需读 assistant 文本，jsonl 不提供判据 | 不能，交 AI 评委或人评 |
| 「该触发没触发」（漏调 skill） | 没有记录可查 | 不能 |

**注意**：
- `wireToolInputs` 是 assistant 记录上的另一份入参副本（2.1.272 起，样本 7737 条）。`Bash` 的 `command` 上有 492 条与 `message.content[].input` 不一致，`input` 是 `wireToolInputs` 里那条的子串；`Edit` 上少一个 `replace_all` 键 385 次。两者差异的原因未查到，**规则判分先以 `message.content[].input` 为准**，并用 `wireToolInputs` 做交叉。
- 一次 deny 之后模型是否改正，要看后续 `tool_use`，属于序列判断，不是单条记录能给的。

## 六、给下游工单的输入

- **字段随版本变**：`permissionDecision` 2.1.294 起、`wireToolInputs` 2.1.272 起、deny 尾注 2.1.281 起，其它早期字段 2.1.263 就有。抽取脚本要对缺字段容错，并把 `version` 一起写进抽取结果。
- **抽取结果入库的建议形状**（不含原文）：会话 id、时间、`version`、`entrypoint`、命中的规则名或 `<plugin>:<skill>`、次数、插件 `<plugin>@<version>`、是否子代理。
- **按 `uuid` 去重**，主会话与子代理文件一并扫。
- **过滤非人类会话**：`entrypoint=="sdk-cli"`、`sessionKind=="bg"`、`origin.kind` 非 `human`。
- **私有内容雷区**：`prompt_snapshot.systemPrompt`、`session_context.context`、`nested_memory.content`、`tool_result.content`、`toolUseResult` 都含私有正文，脚本一律不落盘。`installed_plugins.json` 的 `projectPath` 也别带。
- **本文没做的**：没有对任何会话做模型调用；没有追 Claude Code 源码，所以 `attributionSkill` 的精确边界、`wireToolInputs` 与 `input` 的差异、子代理 `sessionId` 不一致的 2 个例外都只是观察到的现象。
