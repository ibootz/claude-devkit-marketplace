---
id: DBG-001
summary: 二层 fixer 模型命名描述规则未硬化
status: open
priority: P1
difficulty: medium
type: bug
spec_status: violation
reported_at: '2026-08-20'
reopen_count: 0
---

# DBG-001 · 二层 fixer 模型命名描述规则未硬化

## 问题

`tk-debug` 的第二层 fixer 目前使用 `general-purpose`，其 `Agent` 输入与其他普通子代理无可机械区分的字段；因此 `agent-dispatch.js` 只能校验通用的模型枚举、模型前缀、60 字符 description 与第一层 keeper 专项，不能仅对第二层 fixer 强制模型路由、`<model>-debug-<4位>` 名称和全串简体中文且不超过 15 字的 description。当前模板还使用 `sonnet-fix-dbg017-step3-style`、`sonnet-DBG-024` 等不合规名称，并把 hard 修复固定为 `opus`。

证据：`plugins/task-keeper/skills/tk-debug/references/queue.md:680-685` 和 `:753-759` 的 fixer 模板名称不符合用户指定格式；`:885-893` 的模型表把 hard 集成缺失路由到 `opus`；`plugins/working-discipline/hooks/guards/agent-dispatch.js:652-728` 对普通子代理仅检查通用 description 规则，未校验简体中文、15 字上限或 fixer 专用名称。截图显示 “Confirming T2 snapshot matches T1”“Reading DBG-207/CHR-135 archived headers”“Grepping SeqModelTemplateBuilder.java for msg() calls”。

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

## 证据

- `01-agent-description-english.png`
  - origin_path：`/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.keeper/_main/debug/_inbox/20260820-153543-01-agent-description-english.png`
  - 转录：Claude Code 的 agent 列表将任务描述展示为英文，包括 “Confirming T2 snapshot matches T1”“Reading DBG-207/CHR-135 archived headers”“Grepping SeqModelTemplateBuilder.java for msg() calls”。
- `plugins/task-keeper/skills/tk-debug/references/queue.md:621-639`
  - 第二层 fixer 当前统一使用内建 `general-purpose`；该类型无法携带 `difficulty`，并与普通修复 agent 同形。
- `plugins/task-keeper/skills/tk-debug/references/queue.md:673-685`、`753-759`
  - 文本已软要求简体中文与 15 字，但模板 name 仍是 `sonnet-fix-dbg017-step3-style`、`sonnet-DBG-024`。
- `plugins/task-keeper/skills/tk-debug/references/queue.md:885-893`
  - 当前 hard 集成缺失 / 跨文件修复固定走 `general-purpose/opus`，与「复杂 bug 可以使用 fable」的新增期望不符。
- `plugins/working-discipline/hooks/guards/agent-dispatch.js:177-188`、`:470-730`
  - guard 可对精确 `subagent_type` 进行确定字段校验；现有第一层 keeper 使用此能力，但普通 `general-purpose` 不进入专项分支。
- `plugins/working-discipline/test/guard-verify.js:452-457`
  - 普通插件 agent 的 ASCII description 目前是正向回归，故不能把「简体中文、15 字」错误泛化到所有 `Agent` 调用。

## 规格依据

- 结论：`violation`。用户明确限定本条适用于 `tk-debug` 派出的第二层 debugger/fixer，不适用于第一层 `task-keeper:debug-keeper`；现有模板、路由与 guard 均未实现这一组约束。
- 查过的来源：

| 来源 | 结果 | 备注 |
|---|---|---|
| 用户原话 | 命中 | 明确指定简单用 sonnet、复杂可用 fable、名称中段为 debug、description 全串简体中文且 ≤15 字且无固定队列前缀 |
| 项目级工作纪律 | 命中 | `plugins/working-discipline/hooks/working-discipline.js:664-669` 规定通用 Agent 字段；其 `:685-689` 的全局 fable 兜底规则须对本条新增受限例外作明确同步 |
| view spec | 未找到 | 项目无 `sdlc/specs/features/*/ui/views/` 规格目录；本条是 CLI agent 派发行为 |
| 原型 html | 未找到 | 项目无对应原型产物；本条不是 UI 原型行为 |
| 交付级决策 / ADR | 未找到 | 仓根未找到本条对应交付决策或 ADR |
| i18n 文案 / DB 列注释 | 不适用 | 不涉及页面文案、数据库字段 |
| API 契约 / 错误码文案 | 不适用 | 不涉及 API 或错误码 |

- 规格断言：
  1. 第二层 `easy` fixer 必须路由 `sonnet`。
  2. 第二层路由以现有 `difficulty` 的机械定义为依据：`easy` 为单文件明确锚点，`medium` 为跨 2–3 文件或需定位，`hard` 为跨模块、数据结构或集成缺失，定义见 `queue.md:388-393`。
  3. 本条采用明确三档映射：`easy → sonnet`、`medium → opus`、`hard → fable`。`opus` 只保留为 medium 的中档，不得按「keeper 自身是 opus」或默认习惯选择；`hard → fable` 是对 working-discipline 全局「fable 仅两轮 opus 无进展」的 task-keeper 第二层 fixer 特例，须在全局文字规范中逐字声明，避免冲突。
  4. 第二层 fixer 的 `name` 必须完整匹配 `^(sonnet|opus|fable)-debug-[0-9a-z]{4}$`，且模型段必须等于实际 `model`；中段只能为 `debug`，不得为 `debugger`。
  5. 第二层 fixer 的 `description` 必须全串简体中文任务摘要、长度不超过 15 个 code point；必要 issue 标识符 `DBG-024` 可保留；不得带 `debug 队列`、`debugger 队列` 或模型标签等固定前缀。
  6. 第一层 keeper 不在本条改动范围：`task-keeper:debug-keeper` 仍固定 `model: opus`、`name: opus-debugger-<4位>`、description 仍以 `debug 队列` 起头。

- 可机械的作用域方案：新增三个精确第二层 `subagent_type`，分别编码 `easy`、`medium`、`hard`；`agent-dispatch.js` 仅对这三个值执行固定模型、严格 name 和 description 规则。此判据只读本次 `Agent.tool_input.subagent_type`、`model`、`name`、`description` 与字符串长度，符合 `.claude/rules/project/hook-restraint.md:19-31`，且不会误伤普通 `general-purpose` 调用。

## 生效机制与落点

- `plugins/task-keeper/agents/debug-fixer-easy.md`、`debug-fixer-medium.md`、`debug-fixer-hard.md`：新增第二层专用 agent 类型，分别声明固定档位，供模板传入精确 `subagent_type`。
- `plugins/task-keeper/agents/debug-keeper.md:42-46`、`:264-297`：保留第一层固定 opus；把第二层派发规则改为使用专用 type、严格 name / description 与三档映射。
- `plugins/task-keeper/skills/tk-debug/references/queue.md:621-639`、`:673-685`、`:751-824`、`:877-900`：替换两套 fixer 模板与模型表，并解释 `difficulty` 到 type / model 的机械映射。
- `plugins/task-keeper/skills/tk-debug/SKILL.md:148-151`、`plugins/task-keeper/README.md:39-49`：明确第一层与第二层边界及新增 type。
- `plugins/working-discipline/hooks/guards/agent-dispatch.js:177-188`、`:470-730`：保留 `KEEPER_SPECS` 不变，新增只匹配 task-keeper 第二层 type 的规则；不收紧普通 Agent description。
- `plugins/working-discipline/hooks/working-discipline.js:664-689`、`:720-721`：同步全局字段说明与 task-keeper 的 fable 特例，不得将第一层 keeper 和第二层 fixer 混为一谈。
- `plugins/working-discipline/test/guard-verify.js:372-390`：经 JSON stdin 执行真实 guard，新增模型、名称、英文 / 超长 / 队列前缀拒绝与合规放行回归；继续保留普通 ASCII description 正向回归。
- `plugins/working-discipline/README.md`：同步 guard 检查表与覆盖范围；版本清单按 `scripts/check-versions.js` 规则同步检查。

## Triage

- `priority: P1`：第二层 fixer 的在飞面板信息、模型成本与可追踪性均受影响；不阻断派发或破坏用户数据。
- `difficulty: medium`：需跨 task-keeper 的派发类型、模板与 working-discipline guard / 注入 / 测试同步，且必须保持第一层 keeper 不变。
- `type: bug`：已有明确用户期望，当前行为与该期望相反。
- 依赖假设：假设 Claude Code 从新增 `plugins/task-keeper/agents/*.md` 暴露精确 `task-keeper:<agent-name>` type；现有 agent 清单已经以此方式暴露 `task-keeper:debug-keeper`，fixer 应按同一机制加载。须由回归 payload 验证 guard 不依赖 prompt 关键词。
- 相关性：未发现与其他 DBG 条目同根因的证据；不合并。
- 规格收集：collector 因 API 402 系统失败而未完成；其已读取的同构范围由本条人工复核补齐。系统失败不构成模型升级依据。

## 验证

- 场景 A：`task-keeper:debug-fixer-easy` + `model: sonnet` + `sonnet-debug-<4位>` + 合规中文 description 放行；模型改为 opus 必须 `DENY`。
- 场景 B：`task-keeper:debug-fixer-medium` 只接受 `model: opus`，`task-keeper:debug-fixer-hard` 只接受 `model: fable`；三个映射均有真实 guard 回归。
- 场景 C：第二层 name 使用 `debugger`、实际模型与 name 前缀不一致、后缀不是恰好 4 位小写字母数字时均 `DENY`。
- 场景 D：第二层纯英文 description、超过 15 字、或带 `debug 队列` / `debugger 队列` 前缀时均 `DENY`；含 `DBG-024` 的合规简体中文 description 放行。
- 场景 E：普通 `general-purpose` ASCII description 既有正向回归仍放行；第一层 `task-keeper:debug-keeper` 的 `opus-debugger-<4位>`、`debug 队列` 前缀与固定 opus 回归仍放行。
- 场景 F：运行完整 `node plugins/working-discipline/test/guard-verify.js` 与 `node scripts/check-versions.js`，预期全部通过；验证改动后各插件 manifest 与两份市场清单版本一致。
- 场景 G：合并后新会话以每个第二层专用 type 派发最小 payload，预期面板显示中文且名称符合模型派生格式；运行时验证须在已加载新插件版本的会话执行。

## 修订记录

### 登记（2026-08-20）

通过 `keeper_cli.py claim` 原子认领 DBG-001，并将截图从 `_inbox/` 移入本条目录。登记提交已由协调方在临时 worktree 完成并以 merge commit `041c554` 合回主分支。

### 范围扩展与重新 triage（2026-08-20）

用户在登记后追加第二层 fixer 的模型、名称与 description 联动要求。旧正文中「对普通 subagent 强制中文」已被本节替换：普通 Agent 有 ASCII description 正向回归，且 `general-purpose` 不含父级 / 层级确定字段；按 prompt 关键词识别 fixer 会违反 hook 克制原则。因此改用精确第二层 `subagent_type` 建立可机械校验边界。第一层 debug-keeper 的固定 opus、`opus-debugger-<4位>` 与 `debug 队列` 前缀明确保留，不纳入修改。
