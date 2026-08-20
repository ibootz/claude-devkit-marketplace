---
id: DBG-005
summary: AskUserQuestion 题面缺少可判定上下文
status: open
priority: P1
difficulty: medium
type: ux
spec_status: violation
reported_at: '2026-08-20'
reopen_count: 0
---

# DBG-005 · AskUserQuestion 题面缺少可判定上下文

## 问题

用户在 AskUserQuestion 弹窗中看到“塞尔维亚语用户下载模板看到的是英文，且有 6 处句子重复”以及 `config.instruction.full.106`、`step4.104` 等关键结论或符号时，题面没有提供可点击出处，且这些引用未附定义、差距、影响和可独立判断的现场摘录，因而无法可靠选择选项。两张截图显示题面仅展示裸符号与结论；用户必须另找前因后果才能理解选项。

## 用户原话

```text
AskUserQuestion工具中的问题题面里面如果涉及到文件/符号引用/关键表述/业务概念/主题的时候  有办法让它也可以点击跳转到相关文件位置或者多个文件，不然看不懂问题描述中到底说的啥意思，比如下面截图中的红框中的内容，如果没有链接去详细查看前因后果上下文 很难给出好的答复， 或者有无更加友好的问题提问方式，而不是没头没脑的 难以精准把控 进而做出正确答复
```

## 证据

- `.keeper/_main/debug/DBG-005/01-ask-user-question-bare-symbols.png`
  - origin_path：`/Users/zhangq/.claude/image-cache/f6289240-a2fa-4a5e-af6a-0493b213bbae/5.png`
  - 转录：一条 AskUserQuestion 题面把 `config.instruction.full.106` 与 `step4.104` 作为“具体”段的裸符号；题面没有给出这两个符号的文件、定义或可点击出处。
- `.keeper/_main/debug/DBG-005/02-ask-user-question-bare-conclusion.png`
  - origin_path：`/Users/zhangq/.claude/image-cache/f6289240-a2fa-4a5e-af6a-0493b213bbae/6.png`
  - 转录：一条 AskUserQuestion 题面把“塞尔维亚语用户下载模板看到的是英文，且有 6 处句子重复”作为影响结论；题面没有给出数据来源、范围或复现现场。
- `plugins/working-discipline/hooks/working-discipline.js:507-514`：现行规则已要求待确认内容带起源、差距、影响和可直接摘抄的现场证据，并明确应让用户“不打开任何文件就能判断”。实际题面未稳定遵守。
- `plugins/worktree-flow/hooks/lib/round-approval.js:26-55`：本仓唯一可直接追到的 AskUserQuestion 生成器使用结构化 `questions[].header/question/options[].label/description` 协议；其固定授权卡用五行纯文本并经 `evidenceFromQuestion()` 做逐字校验，不能随意插入链接或附加段落。
- `~/.claude/cache/changelog.md:1223,3570`：当前本机 Claude Code 2.1.237 的变更记录仅能证明 AskUserQuestion “preview”存在 Markdown 渲染路径和换行修复；未找到 question、option label、option description 是否分别渲染 Markdown 链接、`file:` URI 或 OSC 8 的字段级契约。

## 规格依据

- 结论：`violation`。现有工作纪律把“用户不打开任何文件就能判断”的自足题面列为待拍板内容的硬信息要求；截图中的题面只有裸符号或裸结论，未达到该要求。

| 来源 | 结果 | 备注 |
|---|---|---|
| 项目需求文字规格 | 未找到 | 本仓没有与 AskUserQuestion 题面体验对应的独立需求规格；已正面检索本仓插件目录。 |
| view spec | 未找到 | 本仓未找到 AskUserQuestion 弹窗的 UI view spec。 |
| 原型 HTML | 未找到 | 本仓未找到 AskUserQuestion 弹窗原型。 |
| 交付决策 / ADR | 命中 | `plugins/working-discipline/hooks/working-discipline.js:507-514` 是当前由 hook 注入的题面信息契约。 |
| i18n 文案与 key 注释 | 不适用 | 本条不涉及应用 i18n。 |
| DB 列注释与数据字典 | 不适用 | 本条不涉及持久化数据字段。 |
| API 契约 / 错误码 | 命中 | `plugins/worktree-flow/hooks/lib/round-approval.js:41-55` 确认本仓题面供给使用 `questions`、`question`、`options`、`label`、`description` 的结构化工具输入。 |
| 用户直接期望 | 命中 | 用户明确要求可跳转到一个或多个相关位置，或提供更友好的自足提问方式。 |
| AskUserQuestion 实际渲染字段边界 | 未找到 | 只追到本机 changelog 的 preview Markdown 线索，未找到 question、label、description、preview 对 Markdown / `file:` URI / OSC 8 的逐字段正式契约；禁止将任何字段“可点击”当作已证实事实。 |

- 规格原文摘录：

```text
(d) 现场证据——相关代码片段 / 文档段落 / 配置用代码块直接摘抄进来，让用户不打开任何文件就能判断；引用类与方法一律用 `path/to/file.ext:行号` 格式，同一符号有多处（定义 + 调用方）各列一处。只写类名 / 方法名不带行号不算，先 Grep/Read 查到行号再写。
```

- 期望 vs 实际：需要 Human 决定的问题，应在 `question` 中解释引用的业务含义、现状与期望差距、影响和最小现场证据，选项的 `label` 只表达选择，`description` 解释该选项的后果；实际题面把关键事实压缩成裸符号或结论，要求用户自行补足上下文。
- 本条的修复判据：所有由本仓规则指导产生的 AskUserQuestion 题面，遇到文件、符号、关键表述、业务概念或主题时，先在题面内给出其白话定义、事实来源与最小可判定摘录；不得把链接可点击性作为唯一获取上下文的前提。若未来获得字段级渲染证据，允许将被证实支持的链接形态作为“延伸阅读”，但不替代自足内容。

## 渲染边界与落点

- 可修改落点：`plugins/working-discipline/hooks/working-discipline.js:507-549`。该文件将待确认内容的四要素注入主会话和子代理；现有措辞要求四要素，却没有把 AskUserQuestion 的 `question`、`label`、`description` 分工和“裸引用不得充当现场证据”写成显式规则。
- 可修改落点：`plugins/task-keeper/skills/tk-decisions/SKILL.md:72-74`。该规则指示主会话把决策文件“正文要点”压入 `question`，却未要求保留定义、差距、影响和最小摘录；这是截图中“没头没脑”题面的直接生成边界。
- 不修改：`plugins/worktree-flow/hooks/lib/round-approval.js:26-140` 及其固定授权卡回归测试。它依赖题面五行逐字稳定性来 fail-closed 地记录 main/master 授权；把一般性链接或长题面规则混入该固定协议，会改变安全边界。
- 不修改：`plugins/clickable-paths/hooks/clickable-paths.js:34-46,133-163`。它仅证实普通终端对话 Markdown 的 `file:` 链接会转为 OSC 8；该证据不能外推到 AskUserQuestion 字段。
- 依赖假设：**假设** AskUserQuestion 题面由主会话遵循注入规则生成；本仓不能直接改 Claude Code 的原生弹窗渲染器。

## Triage

- `priority: P1`：题面缺上下文会直接降低 Human 拍板准确性，可能让主分支授权、外部写入、架构取舍等高影响决策基于错误理解作出；虽有补问和自由文本作为绕行，但不应依赖。
- `difficulty: medium`：需同步主会话通用拍板规则与 keeper 决策转问规则，保留 worktree-flow 固定授权卡的逐字协议和现有测试边界。
- `type: ux`：工具本体可继续正常弹出选项，缺陷是 Human 理解题面与选择选项的体验和信息完整性。
- 处置：派一个 `sonnet` fixer，只修改通用题面生成指引与 tk-decisions 的转问指引，并增加能机械检查注入文本包含“自足题面、字段分工、链接非前提”的回归断言；不得宣称或实现未证实的 AskUserQuestion 原生链接渲染能力。
- 相关性：与 DBG-001、DBG-002、DBG-003 和 DBG-004 的对象不同；本条只处理 AskUserQuestion 的题面信息设计和未验证的字段渲染边界，不合并。

## 验证

- 场景 A：生成包含文件或符号引用的普通拍板题面时，`question` 自带引用对象的白话定义、起源、现状与期望的差距、影响范围及最小现场摘录；用户不点击任何链接仍能选择。
- 场景 B：选项 `label` 仅保留短决策动作；每个 `description` 写清选该项后会发生什么、放弃什么以及适用边界，不重复塞裸符号。
- 场景 C：由 keeper 决策文件转成 AskUserQuestion 时，主会话须将正文中的四要素压缩进 `question`，不能只取“正文要点”或 `options`。
- 场景 D：worktree-flow 固定 main/master 授权卡的 question、选项、metadata 和 fail-closed 回归不改变；运行 `node plugins/worktree-flow/tests/round-approval.test.js`。
- 场景 E：对 `working-discipline` 与 `tk-decisions` 的文本回归测试或精确断言，确认规则明确禁止以未证实的链接可点击性替代题面本身的证据。
- 场景 F：Markdown / `file:` URI / OSC 8 能否在 AskUserQuestion 的 question、option label、option description、preview 中点击，当前均标为“未找到字段级证据”；本条不把任何一种当作验收前提。

## 修订记录

### 登记（2026-08-20）

已通过 `keeper_cli.py claim` 原子认领 `DBG-005`。用户提供两张 AskUserQuestion 截图，证实题面内的裸符号和结论难以脱离上下文理解。

### Triage（2026-08-20）

- 已追到本仓的结构化题面供给边界（worktree-flow 固定授权卡）和通用题面规则边界（working-discipline、tk-decisions）。
- 已确认普通终端对话的 `file:` Markdown 链接机制只适用于普通对话输出；未找到 Claude Code 原生 AskUserQuestion 的 question、option `label`、option `description`、preview 分别支持 Markdown、`file:` URI 或 OSC 8 的字段级证据，因此不外推。
- 两个只读定位 subagent 都因 `402 Insufficient Balance` 在交付前终止；triage 仅使用已读取的一手仓内规则、用户截图与本机 Claude Code changelog，未将失败的子代理输出当事实。
