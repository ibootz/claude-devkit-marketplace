---
id: DBG-006
summary: AskUserQuestion 批准本轮后授权未落盘，写入仍被拦截
status: open
priority: P1
difficulty: medium
type: bug
spec_status: violation
reported_at: '2026-08-20'
reopen_count: 0
---

# DBG-006 AskUserQuestion 批准本轮后授权未落盘

## 问题

Human 在授权卡里选「批准本轮」→ `round-approval-state.js` 的 PostToolUse 判定恒为 false →
`grantRound()` 从不被调用 → 状态文件不产生 → 下一步 main/master 写入照旧被拦，且全程无任何报错。

**根因（已实证，非推断）**：[round-approval.js:142](vscode://file/C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/worktree-flow/hooks/lib/round-approval.js:142)
用**顺序敏感**的 `JSON.stringify` 比对 `tool_response.questions` 与 `tool_input.questions`：

```js
if (JSON.stringify(response.questions) !== JSON.stringify(payload.tool_input.questions)) return false
```

而 harness 回执里 `questions[0]` 的键顺序被**归一化**成 `["question","header","options","multiSelect"]`，
与工具输入侧的顺序**从不相同**。`JSON.stringify` 保留插入顺序，于是这个条件**永远为真**，
恒 `return false`。这不是偶发，是 100% 确定性失败——与用户说的「经常出现」一致（实为「每次」）。

## 证据（实证，取自本机 Claude Code transcript 真实落盘数据）

数据源：`C:\Users\momog\.claude\projects\**\*.jsonl`，取 `tool_use(AskUserQuestion)` 与其
`toolUseResult`（即 hook 收到的 `tool_response`）配对。

**全量统计（27 对，覆盖多个项目与多种客户端）**：

| 观测项 | 结果 |
|---|---|
| `JSON.stringify(questions)` 两侧相等的对数 | **0 / 27** |
| 回执侧 `questions[0]` 键顺序 | `["question","header","options","multiSelect"]` —— 27/27 全部一致 |
| 输入侧 `questions[0]` 键顺序 | 3 种：`[header,question,multiSelect,options]`×17、`[question,header,multiSelect,options]`×5、`[header,multiSelect,options,question]`×5 |

输入侧三种顺序**没有一种**等于回执侧的归一化顺序（即使 `question,header` 开头的那 5 条，
其 `multiSelect` / `options` 后两位仍是反的）。故该比对在任何客户端上都无法通过。

**worktree-flow 授权卡的 6 对真实配对**，逐项拆解（用真实数据跑当前 `isApprovalResponse()`）：

| 项 | 结果 |
|---|---|
| Human 实选「批准本轮」的 | 3 对 |
| `isApprovalRequest(tool_input)` | 6/6 **true** |
| `answers` 键等于完整问题文本 | 6/6 **true** |
| `annotations` 为空对象或缺席 | 6/6 **true** |
| `JSON.stringify(questions)` 相等 | **0/6** ← 唯一失败项 |
| **`isApprovalResponse()` 最终** | **0/6 通过** |

即：**所有其它检查全部通过，唯独第 142 行这一项失败**，包括 3 次 Human 真的点了「批准本轮」的。

**旁证**：状态目录 `C:\Users\momog\AppData\Local\Temp\worktree-flow-user` 至今不存在
（本轮复核仍为 `No such file or directory`）——与「`grantRound()` 从未成功执行过」完全一致。

**真实回执形态样本**（`toolUseResult`，来自 transcript
`C--Users-momog-workspace-tech-support-tech-support-work/90014b90-...jsonl:458`）：

```json
{ "questions": [ { "question": "...", "header": "主分支写入", "options": [...], "multiSelect": false } ],
  "answers": { "<完整问题文本>": "改走 worktree (Recommended)" },
  "annotations": {} }
```

## 规格依据（spec_status: violation）

被违反的是本插件自己的书面契约，两处：

1. [README.md:31](vscode://file/C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/worktree-flow/README.md:31)
   ——「主会话真实调用 `AskUserQuestion`，PostToolUse 仅在结构化
   `tool_response.answers[完整问题] === "批准本轮"` 时落授权状态。」
   契约只约定按 `answers` 判定；第 142 行是契约之外附加的、且恒不成立的条件。
2. [round-approval-state.js:5](vscode://file/C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/worktree-flow/hooks/round-approval-state.js:5)
   ——「仅当工具输入逐字段匹配本插件的固定问题，且 Human 选择"批准本轮"时，才写入 session-scoped
   临时授权。」两个条件真实成立时仍未写入，即违反。

查证范围声明：第 2 类（view spec）与第 3 类（原型）在本仓不适用（插件仓，无 UI 原型）；
实际命中的是第 1 类（插件自身 README 契约）与第 5 类（代码内注释契约）。

## 与 1.5.1 的关系：同一根因的第二次复发

[README.md:99](vscode://file/C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/worktree-flow/README.md:99)
记录的 1.5.1 修复（`annotations` 按可选键处理）与本条**是同一类缺陷**：对 harness 回执形态做了
过强的结构假设，且 fixture 复制了这个错误假设，导致测试全绿而现实全挂。

1.5.1 只修了「键集合」这一层，**没修「键顺序」这一层**，且 fixture 仍用
[round-approval.test.js:77](vscode://file/C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/worktree-flow/tests/round-approval.test.js:77)
的 `questions: clone(request.questions)` —— `clone` 走 `JSON.parse(JSON.stringify())`，**原样保留输入侧键顺序**，
于是被测的恰好又是唯一能通过的那个形状。README 自己写过的那句「为什么测试全绿却挡不住这个 bug」
在本条上**原样再次成立**。

## 落点

| 文件 | 行 | 要做什么 |
|---|---|---|
| `plugins/worktree-flow/hooks/lib/round-approval.js` | 142 | 顺序敏感比对改为顺序无关的深比较 |
| `plugins/worktree-flow/tests/round-approval.test.js` | 73-90 | fixture 改为复刻真实 harness 键顺序；补键顺序回归用例 |
| `plugins/worktree-flow/README.md` | 105 后 | 新增小节记录本次；版本号相关登记点同步 |

同形状排查结论：`JSON.stringify` 直接比对 harness 回执的写法在本仓
**仅此一处**（已全量 grep `plugins/**/*.js`），无其它副本需要连带修改。

## 验证场景（穷举，缺一不可）

- **场景 A**：回执 `questions[0]` 键顺序为真实 harness 顺序
  `["question","header","options","multiSelect"]`、答案为「批准本轮」→ **必须授权成功**（当前失败）。
- **场景 B**：键顺序同 A、答案为「改走 worktree (Recommended)」→ 必须**不**授权。
- **场景 C**：键顺序同 A、`annotations` 非空 → 必须**不**授权（1.5.1 语义不得回退）。
- **场景 D**：回执 `questions` 的**内容**被篡改（改了 label / 问题文本 / 选项数量）→ 必须**不**授权。
  这是第 142 行原本要防的攻击面，修完不能丢。
- **场景 E**：回执缺 `annotations` 键 → 仍须能授权（1.5.1 语义不得回退）。
- **场景 F**：两个测试脚本全绿（`main-branch-guard.test.js` + `round-approval.test.js`）。

## 依赖假设

- **假设**：transcript 里落盘的 `toolUseResult` 对象，与 hook 经 stdin 收到的 `tool_response`
  是同一对象的序列化，键顺序一致。未能直接捕获一次真实 hook stdin（需 Human 真实点击才能触发，
  本轮无法自行制造）。**但该假设不影响根因成立**：状态目录从未被创建，而其余所有检查项经实测
  全部通过，失败点只可能落在第 142 行。
- **假设**：修复后 harness 不会再对回执做内容层面（而非顺序层面）的改写。

## 用户原话（2026-09-19，逐字）

> 经常出现 请求在worktree中修改 但是批准了之后不生效的情况

（附截图一张，已随件落盘为本条目目录下 `01-approval-not-persisted.png`）

origin_path: C:\Users\momog\AppData\Local\Temp\claude\C--Users-momog-workspace-personal-claude-devkit-marketplace\6e5aadfd-c7cd-47c9-a674-c53977a2d94e\images\1.png

## 修订记录

- 2026-09-19 triage（opus-debugger-4bb6）：根因定位并实证，补 `difficulty: medium`、
  `spec_status: violation`。
- 2026-09-19：**推翻**登记时截图转录里的两条推断，原文保留于此备查：
  - 旧推断①「卡在 `annotations` 逐字段比对」——**不成立**。该项已在 1.5.1 修好，当前源码
    [round-approval.js:140](vscode://file/C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/worktree-flow/hooks/lib/round-approval.js:140)
    按可选键处理，6/6 真实回执在此项上均通过。截图引用的 `round-approval.js:127` 那两行代码
    与当前源码不符（127 行实为 `isApprovalRequest` 调用）。
  - 旧推断②「这很可能又是一条 VSCode 扩展差异，扩展侧回执结构和终端不一致」——**不成立**。
    实测 27/27 对回执的键顺序归一化结果完全一致，跨多个项目、跨 `toolu_` 与 `call_` 两种
    工具调用 id 形态（即不同客户端）均相同。**与 VSCode 扩展无关**，是 harness 通用行为。
- 2026-09-19：登记时截图转录中「未逐字段验证回执实际长什么样」的待查项，本轮已用 transcript
  真实数据补齐，见「证据」章节。
- 2026-09-19：注册表里一度出现第二条 DBG-006 实例 `sonnet-debug-keeper-a7f3`。经主会话确认，
  该实例**从未真正启动**（派发被 working-discipline 的 agent-dispatch 守卫拒绝，Agent 未创建），
  但注册条目仍被写入 —— 属 keeper 实例注册跑在 PreToolUse 且不回滚 deny 结果的**独立新 bug**，
  已由主会话另派实例处理，不在本条范围内。主会话已手工清理注册表，本条由 opus-debugger-4bb6 独家认领。
