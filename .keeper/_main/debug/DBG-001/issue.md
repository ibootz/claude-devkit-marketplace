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

`tk-debug` 的第二层 fixer 先前使用 `general-purpose`，其 `Agent` 输入与普通子代理没有可机械区分的字段，因而不能仅对 fixer 强制档位路由、`<model>-debug-<4位>` 名称与全串简体中文且不超过 15 字的 description。当前模板还存在不合规名称，并曾将 hard 修复固定为 `opus`。

第一层 keeper 不在最终改动范围：Human 对档位来源决策选择“保持固定档”，故 `debug-keeper` 继续固定 `opus`，`chore-keeper` 继续固定 `sonnet`。

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

后续就第一层首次派发前没有结构化难度来源一事，Human 在 AskUserQuestion 中最终选择：

```text
保持固定档
```

## 证据

- `01-agent-description-english.png`
  - origin_path：`/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.keeper/_main/debug/DBG-001/01-agent-description-english.png`
  - 转录：Claude Code 的 agent 列表将任务描述展示为英文，包括 “Confirming T2 snapshot matches T1”“Reading DBG-207/CHR-135 archived headers”“Grepping SeqModelTemplateBuilder.java for msg() calls”。
- `plugins/task-keeper/skills/tk-debug/references/queue.md`
  - 旧第二层 fixer 模板名称不符合用户指定格式，旧模型表将 hard 修复固定为 opus。
- `plugins/working-discipline/hooks/guards/agent-dispatch.js`
  - 通用 Agent 规则不能仅凭 prompt 判定某次调用是 task-keeper 第二层 fixer；需用精确 `subagent_type` 建立机械作用域。
- `plugins/working-discipline/test/guard-verify.js`
  - 普通 Agent 的 ASCII description 是正向回归，故中文与 15 字规则不能错误泛化。

## 规格依据

- 结论：`violation`。第二层 fixer 的当前派发模板、模型路由与 guard 未实现用户明确规则。
- 生效断言：
  1. 第二层 `easy → sonnet`、`medium → opus`、`hard → fable`。
  2. 第二层以三个精确 fixer type 编码难度，guard 只读 `subagent_type`、`model`、`name`、`description` 与 code point 长度，不扫描 prompt。
  3. 第二层 name 必须完整匹配 `^(sonnet|opus|fable)-debug-[0-9a-z]{4}$`，且模型段等于实际 `model`；中段只能为 `debug`。
  4. 第二层 description 必须为简体中文任务摘要，最多 15 个 code point；可保留必要 issue 标识符（如 `DBG-024`）；不得带 `debug 队列`、`debugger 队列` 或模型标签等固定前缀。
  5. 第一层保持固定档：`debug-keeper` 固定 `opus`，name 为 `opus-debugger-<4位>`，description 以 `debug 队列` 起头；`chore-keeper` 固定 `sonnet`，沿用其现有 name 与 description 规则。

## 生效机制与落点

- 新增 `plugins/task-keeper/agents/debug-fixer-easy.md`、`debug-fixer-medium.md`、`debug-fixer-hard.md`，分别声明第二层固定档位。
- 更新 task-keeper 的 debug-keeper 派发说明、tk-debug 模板与 README，明确第一层/第二层边界。
- 更新 working-discipline 的 `agent-dispatch`、注入、README 与测试，仅对三个精确第二层 fixer type 增加 hard gate。
- 第一层 agent type、实例登记、SubagentStart matcher 与固定档规则均不扩展。

## Triage

- `priority: P1`：在飞面板信息、模型成本与可追踪性受影响；不阻断派发或破坏用户数据。
- `difficulty: medium`：需跨 task-keeper 派发模板与 working-discipline guard、注入、测试同步，但第一层保持现状。
- `type: bug`：已有明确用户期望，当前第二层行为与其相反。
- 相关性：未发现与其他 DBG 条目同根因的证据；不合并。

## 验证

- 场景 A：`task-keeper:debug-fixer-easy` 仅接受 `sonnet`，medium 仅接受 `opus`，hard 仅接受 `fable`。
- 场景 B：第二层 name 使用 `debugger`、错误模型前缀或非四位小写字母数字后缀时均 DENY。
- 场景 C：第二层英文、明确繁体差异字形、超过 15 code point、队列前缀或模型标签均 DENY；简体中文摘要及含 `DBG-024` 的摘要 ALLOW。
- 场景 D：普通 `general-purpose` 的 ASCII description 继续 ALLOW；第一层 debug-keeper/chore-keeper 固定档与原 name/description 规则继续 ALLOW。
- 场景 E：运行 working-discipline guard 全回归、task-keeper 相关测试、版本四方一致检查与 `git diff --check`。
- 场景 F：合并与缓存刷新后，在新会话对三个第二层 type 做最小真实派发，确认面板 name 与 description；静态 guard payload 不替代运行时证据。

## 修订记录

### 登记（2026-08-20）

通过 `keeper_cli.py claim` 原子认领 DBG-001，并将截图从 `_inbox/` 移入本条目录。登记提交由协调方通过临时 worktree 合回主分支。

### 第二层范围扩展（2026-08-20）

用户追加第二层 fixer 的模型、名称与 description 联动要求。因普通 `general-purpose` 不含父级或层级确定字段，按 prompt 关键词识别 fixer 会违反 hook 克制原则，故采用精确第二层 `subagent_type` 建立机械校验边界。

### 第一层范围裁决（2026-08-20）

Human 一度要求第一层 keeper 也按难度切档。源码复核发现首次派发前没有结构化难度来源：debug 的 `difficulty` 由第一层 keeper triage 后产生，chore schema 没有该字段。主会话通过 AskUserQuestion 提供三种来源方案后，Human 最终选择“保持固定档”。因此现行依据为：第一层 `debug-keeper` 固定 `opus`、`chore-keeper` 固定 `sonnet`；仅推进第二层三档修复。该裁决覆盖此前“第一层也必须分档”的中间要求。
