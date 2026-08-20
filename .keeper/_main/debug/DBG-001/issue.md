---
id: DBG-001
summary: Agent description 未强制简体中文
status: open
priority: P1
difficulty: medium
type: bug
spec_status: violation
reported_at: '2026-08-20'
reopen_count: 0
---

# DBG-001 · Agent description 未强制简体中文

## 问题

派发 subagent 时向 `Agent` 传入英文 `description`，在飞 agent 面板直接展示英文任务描述，而 `agent-dispatch.js` 只校验非空、角色设定句和 60 字符上限，未校验简体中文，因而英文描述被放行。

证据：`plugins/working-discipline/hooks/guards/agent-dispatch.js:652-728` 对 `description` 仅执行正文、角色设定句、长度和 keeper 前缀检查；其中普通 subagent 不进入 keeper 分支。截图显示 “Confirming T2 snapshot matches T1”“Reading DBG-207/CHR-135 archived headers”“Grepping SeqModelTemplateBuilder.java for msg() calls”。

## 用户原话

```text
ai创建subagent 添加描述的地方总是喜欢使用英文，这里改成强制使用简体中文
```

## 证据

- `01-agent-description-english.png`
  - origin_path：`/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.keeper/_main/debug/_inbox/20260820-153543-01-agent-description-english.png`
  - 转录：Claude Code 的 agent 列表将任务描述展示为英文，包括 “Confirming T2 snapshot matches T1”“Reading DBG-207/CHR-135 archived headers”“Grepping SeqModelTemplateBuilder.java for msg() calls”；用户期望派发 description 强制使用简体中文。
- `plugins/working-discipline/hooks/guards/agent-dispatch.js:652-728`
  - 当前 description 校验未检查文字语言，英文 description 可通过。
- `plugins/working-discipline/.claude-plugin/plugin.json:9-16`
  - Agent 的 PreToolUse 入口已挂载 `agent-dispatch.js`，该 guard 的 deny 会在派发前阻断调用。

## 规格依据

- 结论：`violation`（用户明确要求 description 强制使用简体中文，当前实现未执行该要求）。
- 查过的来源：

| 来源 | 结果 | 备注 |
|---|---|---|
| 用户原话 | 命中 | 明确要求“改成强制使用简体中文” |
| 项目级工作纪律 | 命中 | `CLAUDE.md` 与 `plugins/working-discipline/hooks/working-discipline.js` 均要求 description 使用简体中文，但当前 guard 未机械执行 |
| view spec | 未找到 | 项目无 `sdlc/specs/features/*/ui/views/` 规格目录 |
| 原型 html | 未找到 | 项目无对应原型产物；本条是 CLI hook 行为 |
| 交付级决策 / ADR | 未找到 | 仓根无本条对应的交付决策或 ADR |
| i18n 文案 / DB 列注释 | 不适用 | 不涉及页面文案、数据库字段 |
| API 契约 / 错误码文案 | 不适用 | 不涉及 API 或错误码 |

- 规格原文摘录：

```text
ai创建subagent 添加描述的地方总是喜欢使用英文，这里改成强制使用简体中文
```

- 期望 vs 实际：期望在 `Agent` 派发前拒绝不符合简体中文要求的 `description`；实际普通 subagent 的英文 description 未命中任何语言校验而被放行，随后在 agent 面板显示英文。
- 本条的修复判据：对普通 subagent，纯英文 description 必须被 `agent-dispatch.js` 拒绝；符合现有描述格式且以简体中文写出的 description 必须继续放行；保留现有 keeper 的队列前缀、模型、名称与长度校验。

## 生效机制与落点

- `plugins/working-discipline/.claude-plugin/plugin.json:9-16` 把 `Agent` 的 PreToolUse 事件挂到 `agent-dispatch.js`。
- `plugins/working-discipline/hooks/guards/agent-dispatch.js:652-728` 从 `tool_input.description` 取值并决定是否生成 deny；应在该函数的 description 校验链中加入可复核的简体中文格式判定。
- `plugins/working-discipline/test/guard-verify.js:372-390` 以 JSON stdin 执行真实 guard 并将输出归一为 `DENY` / `ALLOW` / `AUTONAME`；应在现有 agent-dispatch 回归段加入英文拒绝与简体中文放行两侧用例。

## Triage

- `priority: P1`：所有派发的 subagent 都可能在用户可见的在飞面板显示英文，影响主要工作流的可读性，但不会阻断派发或破坏数据。
- `difficulty: medium`：需要在 hook 判据、回归测试以及版本/发布元数据之间保持一致，并需界定“简体中文”可机械验证的边界。
- `type: bug`：已有明确用户期望，当前行为与该期望相反。
- 依赖假设：假设可以用对 `description` 字段的确定、可复核字符规则表达“禁止英文任务描述”，并且不改变用户允许的标识符例外（例如 `DBG-024`）；该假设须由 collector 的规格与实现证据核实。
- 相关性：未发现与现有其他 DBG 条目同根因的证据；不合并。

## 验证

- 场景 A：向真实 guard 输入普通 `general-purpose` subagent 的纯英文 description，预期 `DENY`，finding 明确要求简体中文。
- 场景 B：输入简体中文 description，预期 `ALLOW` 或既有的 `AUTONAME`，不得因新增规则被拒绝。
- 场景 C：输入含必要 ASCII 标识符（如 `DBG-024`）的简体中文 description，预期保持放行，避免把可读任务编号误判为英文描述。
- 场景 D：运行完整 `guard-verify.js`，预期所有既有 agent-dispatch 回归用例仍通过。
- 场景 E：合并后派发一个普通 subagent，预期在面板中 description 为简体中文；该运行时验证在统一实测阶段执行。

## 修订记录

### 登记（2026-08-20）

通过 `keeper_cli.py claim` 原子认领 DBG-001，并将截图从 `_inbox/` 移入本条目录。初步定位到 `agent-dispatch.js` 的 description 校验链；尚未确定“简体中文”的机械判据与可接受标识符边界，未派 fixer。
