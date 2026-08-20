---
id: DBG-004
summary: 本机文件对话链接现有规则已覆盖
status: done
priority: P2
difficulty: easy
type: ux
spec_status: conformant
reported_at: 2026-08-20
reopen_count: 0
---

# DBG-004 · 本机文件对话链接现有规则已覆盖

> `done` 在本条语义是“核实后无需代码修复”，不是新增实现；如后续给出已确认本机文件未被链接化的实际对话输出，应 reopen 并附原文与文件存在性证据。

## 问题

用户希望 AI 对话正文中所有可确定绝对路径的本机文件均为可点击链接，覆盖当前项目、其他本机项目、插件 skill 与 `DBG-NNN` / `CHR-NNN` 队列条目。核实结果显示，已安装的 clickable-paths 1.5.0 已对主会话和子代理注入该通用规则：已由 `Read`、`Edit`、`Grep`、`ls` 或工具结果确认存在的“本机文件”均应使用 `file:///绝对路径#行号` Markdown 链接，未将范围限制为当前项目：`plugins/clickable-paths/hooks/clickable-paths.js:132-164`。

该能力是输出格式的软规约而非文本重写器；hook 只输出 `additionalContext`，不拦截或改写已生成的回复：`plugins/clickable-paths/hooks/clickable-paths.js:6-10,177-186`。本报告没有提供任何已确认存在的文件在实际对话正文中未被链接化的原文，故不能据此断言现有实现失效或以新增样例冒充修复。

## 用户原话

```text
我希望万物皆链接，ai输出的文本中 任何可以添加绝对路径的文件（不限于当前项目中，插件中的skill等文件 其他某个项目等等… …）都添加上链接，就像维基百科一样，这样我可以跳转查看 全面了解
```

```text
方法一：改用 VSCode 专属的 vscode://file/ 协议（最推荐）
这是最简单且不需要安装任何插件的方法。将原来的 file:// 替换为 vscode://file/，点击后会直接在 VSCode 编辑器中打开该文件，并支持跳转行号：
```

```text
文档中路径在vscode中跳转不了的问题的可以考虑使用上面的方案，同时思考在终端中输出的文件附带的绝对路径，比如DBG-xx这些文件路径是不是也可以这么改造 从而解决跳到vscode之后无法定位到具体行号的问题
```

## 证据

- clickable-paths 同时注册 `UserPromptSubmit`（主会话）与 `SubagentStart`（子代理），覆盖对话正文的两个生产方：`plugins/clickable-paths/.claude-plugin/plugin.json:8-31`。
- 注入正文明确要求“对话正文每提到一个本机文件，就给一个链接”，并以“Read/Edit/Grep/ls 见过、或工具结果里出现过的文件”为存在性判据；该判断不依赖文件属于当前项目：`plugins/clickable-paths/hooks/clickable-paths.js:132-164`。
- `DBG-NNN` / `CHR-NNN` 已被明定为队列条目文件，hook 从实际 `.keeper/` 路径现算样例以避免坏链接：`plugins/clickable-paths/hooks/clickable-paths.js:68-110,147-175`。
- 现有回归套件在源工作区实测通过 14/14，覆盖两个注入事件、三种漏套形态、队列前缀与关闭开关：`plugins/clickable-paths/hooks/tests/clickable-paths.test.js:44-205`。
- 本机 VS Code 1.134.0 注册 `vscode` URL scheme；对 percent-encoded 的中文和空格路径使用 `open -g` 可打开目标文件。但本条没有取得编辑器光标坐标，不能把该候选 URI 认定为行列精确定位方案。

## 规格依据

- 结论：`conformant`。用户的唯一明确规格是“任何可以添加绝对路径的文件”均在 AI 输出中添加链接；现有规约已经以“本机文件 + 已确认存在”覆盖该范围，未限定项目根。

| 来源 | 结果 | 备注 |
|---|---|---|
| 项目需求文字规格 | 本项目不存在 | 未找到 `sdlc/` 或等价需求规格产物。 |
| view spec | 本项目不存在 | 未找到本条关联 view spec。 |
| 原型 HTML | 本项目不存在 | 未找到本条关联原型。 |
| 交付决策 / ADR | 未找到 | 未找到规定此输出范围的独立决策。 |
| i18n 文案与 key 注释 | 不适用 | 本条是 Claude Code 输出格式规约。 |
| DB 列注释与数据字典 | 不适用 | 本条不涉及持久化数据。 |
| API 契约 / 错误码 | 不适用 | 本条不涉及项目 API。 |
| 用户直接期望 | 命中且符合 | 见“用户原话”第一段与现有注入规则。 |

- 规格原文摘录：

```text
ai输出的文本中 任何可以添加绝对路径的文件（不限于当前项目中，插件中的skill等文件 其他某个项目等等… …）都添加上链接
```

- 期望 vs 实际：期望为已确定的本机绝对路径生成可点击链接；实际规则同样要求已确认存在的本机文件以绝对 `file:` 链接输出。没有实际漏链样本，故不存在可核实的偏差。
- 本条的收口判据：保留现有 `file:///绝对路径#行号` 对话链接规约与其主会话/子代理双挂；不在无复现证据时改写措辞、扩展 hook 判据或迁移协议。

## 范围与边界

- 本条核实的范围仅为 Claude Code 终端**对话正文的格式规约**；已确认存在的其他项目文件和插件缓存中的 `SKILL.md` 适用同一“本机文件”判据。
- 软规约不等于可机械保证模型每次都遵循。未来若出现实际漏链，reopen 时必须提供：原始对话文本、应被链接的绝对路径、该文件已通过工具结果确认存在的证据，以及该路径不属于代码块、命令、落盘文档、子代理 prompt、外部系统内容或非本机引用的证据。
- `vscode://file/<绝对路径>:<行号>` 不在本条替换。现有插件和 Claude Code 的终端超链接链路以 `file:` 为基础；iTerm2 Semantic History 是否消费 `#行号`、以及 VS Code `--goto` 配置归 DBG-003 核实。
- 落盘 Markdown 的消费端能否渲染链接归 DBG-002，不在本条改动。

## Triage

- `priority: P2`：是体验与排查效率诉求，不阻断业务流程或造成数据错误。
- `difficulty: easy`：核实范围后确认无业务代码、hook 或文档改动需要实施。
- `type: ux`：主题是文件跳转体验。
- 处置：关闭不修；不派 fixer，不新建 worktree 提交，不改变输出协议。
- 依赖假设：**假设** Claude Code 继续将 `file:` Markdown 链接交给终端超链接能力渲染；这不是本插件可机械控制的行为。
- 相关性：DBG-002 是落盘 Markdown 的消费端渲染，DBG-003 是 iTerm2 → VS Code 行号消费；同属链接体验但根因与改动面不同，不合并。

## 验证

- 场景 A：主会话已由工具确认的当前项目文件，现有注入规则要求其使用 `file:///绝对路径#行号`。
- 场景 B：其他本机项目的已确认文件，规则不含项目根限制，适用与场景 A 相同的链接形态。
- 场景 C：已安装插件目录中已确认存在的 `SKILL.md`，属于本机文件，适用同一链接形态。
- 场景 D：`DBG-NNN` / `CHR-NNN` 由注入规则显式作为 `issue.md` / `item.md` 的别名处理。
- 场景 E：尚未创建的落点、代码块、落盘 Markdown、外部系统消息与非本机路径维持既有豁免，不能为满足格式编造绝对路径。
- 场景 F：在源工作区运行 `node plugins/clickable-paths/hooks/tests/clickable-paths.test.js`，实测 14/14 通过。

## 修订记录

### 登记（2026-08-20）

- 已用 `keeper_cli.py claim` 原子认领并用 `bind` 登记实例 `opus-debugger-t6v3`。
- 用户提出 `vscode://file/<绝对路径>:<行号>` 候选；不将其视为已确认修法。

### Triage（2026-08-20）

- 已核实本机安装的 clickable-paths 1.5.0 同时注册 `UserPromptSubmit` 与 `SubagentStart`，并在主会话、子代理侧注入同一条软规约；其 14 条现有回归测试通过。
- 初步曾考虑将“其他项目”与“插件 skill”加入更多显式正例；复核后撤销：通用规则已覆盖二者，且没有用户提供的实际漏链样本。仅扩写文案不能被称为修复。
- 与 DBG-002、DBG-003 协调后保持边界：本条只核实对话输出规约，落盘 Markdown 与 iTerm2 行号跳转各由对应条目处理。
