---
id: DBG-002
summary: 文档生成的 Markdown 文件链接失效不可点击
status: open
priority: P2
difficulty: medium
type: bug
spec_status: violation
reported_at: '2026-08-20'
reopen_count: 0
---

# DBG-002 · 文档生成的 Markdown 文件链接失效不可点击

## 问题

生成文档后，正文中的 Markdown 文件链接在渲染结果中显示为普通文本、无法点击。截图证实已把终端对话专用的 `[DBG-207](file:///Users/zhangq/Workspace/xx/domain/sp/xxstar-ai-spsd-work/.sdlc/worktrees/D-006-fix-seqmodel-ui-style-selfcheck/.keeper/D-006-fix-seqmodel-ui-style-selfcheck/debug/archive/auto-20260819/DBG-207/issue.md#1)` 写入落盘 Markdown；其链接目标使用本机 `file://` 绝对路径。`plugins/readable-citations/hooks/readable-citations.js:53-62` 已规定落盘 Markdown 引用另一份 Markdown 时使用相对路径与标题锚点，故现有生成形态违反该约定。

## 用户原话

```text
文档中生成的md可点击链接有问题，目前是失效不可点击状态
```

## 证据

- `/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.keeper/_main/debug/DBG-002/01-markdown-file-link-broken.png`
  - origin_path：`/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.keeper/_main/debug/_inbox/20260820-153543-02-markdown-file-link-broken.png`
  - 转录：标题为“来源”的文档段落中，`[DBG-207](file:///Users/.../issue.md#1)` 原样显示，未形成可点击链接；其后文本为“（导入模板五条说明的多语种译文修复）”。

## 规格依据

- 结论：`violation`。持久化 Markdown 引用另一份 Markdown 的现行格式约定是“相对路径 + 标题锚点”，截图中的 `file:///Users/...` 是终端对话专用绝对路径格式，写入文档后成为不可移植死链。

| 来源 | 结果 | 备注 |
|---|---|---|
| 项目需求文字规格 | 未找到 | 已用 `readable-citations` 这个已知插件名验证仓内检索有效；本仓未找到本条关联的 `sdlc/` 或等价需求文档。 |
| view spec | 未找到 | 本仓未找到本条关联 UI view spec。 |
| 原型 HTML | 未找到 | 本仓未找到本条关联原型。 |
| 交付决策 / ADR | 未找到 | 本仓未找到独立 ADR；`readable-citations` README 与 hook 是现行格式契约。 |
| i18n 文案与 key 注释 | 不适用 | 本条是 Markdown 引用格式。 |
| DB 列注释与数据字典 | 不适用 | 本条不涉及持久化数据字段。 |
| API 契约 / 错误码 | 不适用 | 本条不涉及 API。 |
| 用户直接期望 | 命中 | 用户报告“文档中生成的md可点击链接有问题，目前是失效不可点击状态”。 |
| `plugins/readable-citations/hooks/readable-citations.js:53-62` | 命中 | 落盘 Markdown 使用相对路径与标题锚点；`file:///Users/...` 对其他机器和 GitLab 网页是死链。 |
| `plugins/clickable-paths/hooks/clickable-paths.js:43-46,161-163` | 命中 | `file://` 绝对路径仅适用于对话正文，写进文件的 md 被明确排除。 |

- 规格原文摘录：

```text
- **落盘 md**（写进文件的文档）——相对路径 + 标题锚点，VS Code 预览与 GitLab 网页都能跳：
  `[working-discipline · §5.2 模型档位](../working-discipline/SKILL.md#52-模型档位)`

落盘 md 走相对路径的理由：文档 commit 之后会被别人、别的机器、GitLab 网页读到，
`file:///Users/...` 在那些地方是死链，而死链不报错——点了没反应而已。
```

- 期望 vs 实际：落盘 Markdown 中指向另一份 Markdown 的链接应使用从当前文档到目标文档的相对路径，并在引用章节时使用标题锚点；实际写入了只适合当前机器终端对话渲染的 `file:///` 绝对链接。
- 本条修复判据：生成或改写落盘 Markdown 时，不再输出 `file:///` 本机绝对链接；跨 Markdown 文档的引用使用从落盘文档计算出的相对 `.md` 路径和正确标题锚点。终端对话正文保留 `file:///绝对路径#行号`，不被本条改动。

## 影响面与责任边界

- 代码落点：`plugins/readable-citations/hooks/readable-citations.js:53-72` 是落盘 Markdown 格式规约的注入来源；`plugins/clickable-paths/hooks/clickable-paths.js:43-46,133-163` 定义终端对话 `file://` 形态及其“写进文件的 md”豁免；`plugins/task-keeper/skills/tk-board/scripts/board.py:159-181` 仅为终端看板输出队列编号生成 `file://`，不应被用于落盘文档。
- 截图对应的实际 Markdown 生成者与消费端源码不在本仓，未找到，故本条修复范围是仓内对 agent 的落盘格式约束与回归测试；不得臆测或修改外部 Markdown 渲染器。
- `vscode://file/<绝对路径>:<行号>` 不替换落盘 Markdown 格式：本机仅证实 VS Code CLI 支持 `--goto <file:line[:character]>`，未证实截图消费端将该 URI 渲染为可点击链接或精确定位。终端 `file://` 跳转行号配置归 DBG-003；对话正文跨项目链接覆盖归 DBG-004。

## Triage

- `priority: P2`：链接失效降低文档追溯效率，但不阻断业务主流程、不产生数据错误。
- `difficulty: medium`：需要同步落盘引用规则的注入、README 说明与回归测试，并保持与终端 `file://` 格式的边界一致。
- `type: bug`：现有生成结果直接违反持久化 Markdown 的既有格式约定。
- 处置：派一个 `sonnet` fixer，仅修改 readable-citations 的落盘 Markdown 规则与其测试、README；不得改 clickable-paths、task-keeper 看板或终端/iTerm2 配置。
- 依赖假设：**假设** 落盘 Markdown 的生成者会消费 readable-citations 注入；若外部生成器没有该注入通道，本条仓内修复不足以消除截图来源，需以外部生成器的实际源码另行处理。
- 相关性：DBG-003 是终端 `file://` 到 VS Code 的行号定位，DBG-004 是终端对话输出覆盖面；与本条格式对象、消费端和改动面不同，不合并。

## 验证

- 场景 A：在持久化 Markdown 中引用另一份 Markdown 的某个章节，输出相对 `.md` 路径与由真实标题计算的锚点，不含 `file:///`。
- 场景 B：持久化 Markdown 随仓库移动或由另一台机器阅读时，链接文本不携带 `/Users/` 等本机绝对路径。
- 场景 C：终端对话正文仍明确使用 `file:///绝对路径#行号`，未被落盘规则替换；该行为由 DBG-003/DBG-004 验证。
- 场景 D：运行 readable-citations 现有回归测试，并新增或强化断言：落盘示例含相对路径与标题锚点、`file:///` 仅属于对话轨示例。

## 修订记录

### 登记（2026-08-20）

已原子认领 `DBG-002`、绑定实例 `opus-debugger-r4n8` 并把截图移动到本条目录。

### Triage（2026-08-20）

- 已核实终端对话与落盘 Markdown 有两套不同格式契约：`file:///绝对路径#行号` 属于终端对话；落盘 Markdown 引用另一份 Markdown 必须使用相对路径与标题锚点。
- 截图中的断链形态违反现行落盘规则，`spec_status` 从 `unchecked` 更新为 `violation`；本仓未找到截图所属外部 Markdown 消费端或实际生成器源码，故不把外部渲染行为作为已验证事实。
- 两次 collector 因 `402 Insufficient Balance` 未产生回执；本条依据仓内可读的一手规则与用户截图完成 triage，未因系统失败升级模型。
- 已与 DBG-003、DBG-004 划清责任边界：前者处理 iTerm2 到 VS Code 的行号定位，后者处理终端对话链接覆盖面；本条只处理落盘 Markdown 引用格式。
