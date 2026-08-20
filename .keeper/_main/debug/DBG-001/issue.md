---
id: DBG-001
summary: keeper 与二层 fixer 档位命名描述规则未硬化
status: open
priority: P1
difficulty: hard
type: bug
spec_status: violation
reported_at: '2026-08-20'
reopen_count: 0
---

# DBG-001 · keeper 与二层 fixer 档位命名描述规则未硬化

## 问题

`tk-debug` 的第二层 fixer 先前使用 `general-purpose`，其 `Agent` 输入与普通子代理没有可机械区分的字段，因而不能仅对 fixer 强制档位路由、`<model>-debug-<4位>` 名称与全串简体中文且不超过 15 字的 description。第一层 `debug-keeper` / `chore-keeper` 则仍由固定 `KEEPER_SPECS` 强制分别使用 opus / sonnet；这与用户随后明确的「第一层 keeper 也要按难易度切换模型」相反。

证据：`plugins/task-keeper/skills/tk-debug/references/queue.md:680-685`、`:753-759` 的旧 fixer 模板名称不符合用户指定格式；`:885-893` 的旧模型表将 hard 修复固定为 opus；`plugins/working-discipline/hooks/guards/agent-dispatch.js:178-192` 的 `KEEPER_SPECS` 固定第一层模型，`:599-614` 对该固定值做硬拒绝。截图显示 “Confirming T2 snapshot matches T1”“Reading DBG-207/CHR-135 archived headers”“Grepping SeqModelTemplateBuilder.java for msg() calls”。

## 用户原话

```text
ai创建subagent 添加描述的地方总是喜欢使用英文，这里改成强制使用简体中文
```

```text
目前的 tk-debug 在派发debuger-agent的时候有些地方需要优化：
1-subagent 不需要指定死使用opus，一些简单的bug可以使用sonnet，复杂的bug可以使用fable，目前看ai仍然倾向于都使用opus，
2-另外subagent的名字模型前缀也要跟着上面选择的实际模型拼接，如 fable-debug-a1b2 sonnet-debug-1234 等， 注意中间是debug 不是 debugger
3-生成的subagent描述无比使用简体中文，不超过15个字，前面也不要拼上固定的 debugger队列的字样
```

```text
第一层keeper比如（debug-keeper chore-keeper）也要受上面的难易度进行模型的切换啊 而不是默认都是opus
```

## 证据

- `01-agent-description-english.png`
  - origin_path：`/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.keeper/_main/debug/DBG-001/01-agent-description-english.png`
  - 转录：Claude Code 的 agent 列表将任务描述展示为英文，包括 “Confirming T2 snapshot matches T1”“Reading DBG-207/CHR-135 archived headers”“Grepping SeqModelTemplateBuilder.java for msg() calls”。
- `plugins/task-keeper/skills/tk-debug/references/queue.md:388-393`
  - 仅为第二层 debug 修复定义了 `difficulty`：easy 为单文件明确锚点，medium 为跨 2–3 文件或需定位，hard 为跨模块、数据结构或集成缺失。
- `plugins/task-keeper/agents/debug-keeper.md:35-50`
  - 第一层 debug-keeper 仍自称固定 opus；其首次派出发生在登记和 triage 之前，故其使用的 issue 此时尚不存在 `difficulty` 字段。
- `plugins/task-keeper/agents/chore-keeper.md:47-58`、`:94-105`
  - 第一层 chore-keeper 固定 sonnet；`CHR-NNN/item.md` 的 schema 没有 `difficulty` 字段。
- `plugins/task-keeper/hooks/lib/keeper_instance_register.py:77-100`、`plugins/task-keeper/.claude-plugin/plugin.json:43-53`
  - 登记白名单和 SubagentStart matcher 都只认精确 `debug-keeper` / `chore-keeper` slug；新增第一层精确档位 type 时必须同步，否则会静默漏登记或漏注入。
- `plugins/working-discipline/hooks/guards/agent-dispatch.js:178-207`、`:599-704`
  - guard 可只依精确 `subagent_type`、`model`、`name`、`description` 做等值与锚定正则校验；不能从 prompt、description 或任务关键词推测难易度。
- `plugins/working-discipline/test/guard-verify.js:399-439`、`:476-565`
  - 普通 Agent 的 ASCII description 是正向回归，故中文/15 字规则不能错误泛化；现有 keeper 回归则证明第一层目前被固定档位拦截。

## 规格依据

- 结论：`violation`。用户先明确第二层 fixer 的三档、名称和 description 约束，后明确追加第一层 `debug-keeper`、`chore-keeper` 也必须按难易度切模型。当前固定 `KEEPER_SPECS` 违反后者。
- 查过的来源：

| 来源 | 结果 | 备注 |
|---|---|---|
| 用户原话 | 命中 | 明确 easy 可用 sonnet、复杂可用 fable、名称模型前缀联动；追加明确第一层 keeper 亦按难易度切模型 |
| 项目级工作纪律 | 命中 | 现有全局三档和 task-keeper 第二层特例均要求模型选择来自明确规则；`hook-restraint.md` 禁止用 prompt 语义做 hard guard |
| task-keeper queue schema 与生命周期 | 命中 | debug 的 `difficulty` 是第一层 keeper triage 后才写入；chore schema 完全没有该字段，首次派发前没有可传入的结构化难度来源 |
| view spec | 未找到 | 项目无 `sdlc/specs/features/*/ui/views/` 规格目录；本条是 CLI agent 派发行为 |
| 原型 html | 未找到 | 项目无对应原型产物；本条不是 UI 原型行为 |
| 交付级决策 / ADR | 未找到 | 仓根未找到可定义第一层首次派发难度来源的决策或 ADR |

- 生效的规格断言：
  1. 第二层 `easy → sonnet`、`medium → opus`、`hard → fable`，并以三个精确 fixer type 编码；name 必须为实际模型加 `-debug-<4位>`。
  2. 第一层 `debug-keeper`、`chore-keeper` 不得再按 kind 固定模型；其实际模型与 name 的模型前缀必须等值联动。
  3. 第一层模型路由若做 hard guard，必须由 `Agent.tool_input` 中的确定结构字段表达，不能扫描 prompt、description、用户原话、`DBG-` / `CHR-` 或任务关键词推测难易度。
  4. 第一层 description 的队列前缀和常驻面板语义未被本次追加原话推翻；本轮不把第二层的「无队列前缀、≤15 字」规则外推给第一层。

- 未决规格空白（blocking）：首次派发第一层时，debug 尚未 triage 从而没有 `difficulty`，chore 条目也尚未创建且 schema 无 `difficulty`。现有 Agent 调用没有专用难度字段。用 tiered `subagent_type` 能让 guard 机械校验已经选定的档位，却不能自行定义主会话如何在不猜 prompt 的前提下选该 type。此处不能由实现自行补行为；已按待拍板协议提出来源选项。

## 生效机制与落点

- 已实现、待本条整体接受的第二层基础：`plugins/task-keeper/agents/debug-fixer-easy.md`、`debug-fixer-medium.md`、`debug-fixer-hard.md` 和相应 queue 模板、guard、注入、回归及 OpenCC 简繁差异表。
- 第一层的候选机械实现必须新增精确 type 以承载已确定的 tier，并同步 `plugins/task-keeper/agents/`、`hooks/lib/keeper_instance_register.py` 的白名单、`plugin.json` 的 SubagentStart matcher、`agent-dispatch.js` 映射/自动名、注入文字与回归。具体 type 名和首次 tier 来源等待裁决，不能先猜定。
- `KEEPER_SPECS` 固定 model 逻辑、`debug-keeper.md` / `chore-keeper.md` 的固定档位叙述、两份 SKILL 派发模板、`keeper-dispatch.md`、`working-discipline.js`、README 与测试均须在确定来源后同步。

## Triage

- `priority: P1`：在飞面板信息、模型成本与可追踪性受影响；不阻断派发或破坏用户数据。
- `difficulty: hard`：在已完成第二层跨插件实现上扩展第一层，会同时变更 agent discovery、实例登记、SubagentStart 注入、guard、派发模板和回归；更重要的是首次派发难度字段存在生命周期闭环，不能凭默认值掩盖。
- `type: bug`：已有明确用户期望，当前第一层固定档位与期望相反。
- 依赖假设：假设新增 `plugins/task-keeper/agents/*.md` 会暴露对应精确 `task-keeper:<agent-name>` type；第二层已按同一机制实现。此假设不替代首次 tier 的业务来源。
- 相关性：未发现与其他 DBG 条目同根因的证据；不合并。
- 规格收集：collector 与本轮只读 tier 审计均因 API 402 系统失败而未完成；已用源码和现有 schema 人工复核。系统失败不构成模型升级依据。

## 验证

- 场景 A：第二层 easy/medium/hard 的精确 type 仅分别接受 sonnet/opus/fable，且 name 为对应 `<model>-debug-<4位>`；错档、`debugger` 中段、非四位后缀均 DENY。
- 场景 B：第二层纯英文、超 15 code point、队列前缀、模型标签与明确繁体差异字形均 DENY；`修DBG-024分类归属` 与简体样例 ALLOW；普通 Agent 不受误伤。
- 场景 C：第一层最终 type 的 tier 与 model、name 模型前缀等值；无论 sonnet / opus / fable，均由精确 `subagent_type` 映射验证，不读取 prompt 文字。
- 场景 D：第一层 debug 与 chore 的登记 hook 和 SubagentStart 注入均命中新 type；其 instance name、issue 绑定和漏派清单保持可用。
- 场景 E：分别覆盖 debug 与 chore 的首次派发来源：给定裁决定义的结构化 tier，派发模板能生成相应 type；缺失或非法 tier 必须不能静默退回固定 opus / sonnet。
- 场景 F：运行完整 `node plugins/working-discipline/test/guard-verify.js`、task-keeper hook 回归、`node scripts/check-versions.js` 与 `git diff --check main...HEAD`。
- 场景 G：合并后在加载本地新插件版本的会话最小真实派发每种第一层及第二层 type，确认面板 name / description、实例登记和 debug 注入；不把静态 payload 当运行时证据。

## 修订记录

### 登记（2026-08-20）

通过 `keeper_cli.py claim` 原子认领 DBG-001，并将截图从 `_inbox/` 移入本条目录。登记提交已由协调方在临时 worktree 完成并以 merge commit `041c554` 合回主分支。

### 第二层范围扩展（2026-08-20）

用户追加第二层 fixer 的模型、名称与 description 联动要求。普通 Agent 有 ASCII description 正向回归，且 `general-purpose` 不含父级 / 层级确定字段；按 prompt 关键词识别 fixer 会违反 hook 克制原则。因此采用精确第二层 `subagent_type` 建立可机械校验边界。

### 接受裁决被覆盖并重新 triage（2026-08-20）

Human 在原 `fix-acceptance` 决策答复中明确说：“第一层keeper比如（debug-keeper chore-keeper）也要受上面的难易度进行模型的切换啊 而不是默认都是opus”。据此撤销旧正文和旧接受材料中「第一层固定 debug=opus / chore=sonnet、保持不改」的结论；既有第二层实现保留为未合并基础，不得据旧 accept 建议合并或 push。源码复核发现第一层首次派发时没有可机械取得的 `difficulty`：debug 的字段由派发后的 keeper triage 产生，chore schema 没有该字段。已另发 blocking 决策，仅请求确定该字段的权威来源。
