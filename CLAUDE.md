# claude-devkit-marketplace 项目指令

本仓是 Claude Code / Codex 插件市场仓：市场清单在 `.claude-plugin/marketplace.json`，
各插件在 `plugins/<plugin-name>/`。

## 硬约束：改插件前必须先读两个技能

**动手改任何插件内容之前**，先用 `Skill` 工具读完这两个技能，读完再动笔：

| 调用 | 管什么 |
|---|---|
| `skill: "mattpocock-skills:writing-for-agents"` | 写给 agent 看的文字怎么写：指令密度、歧义消除、什么该显式写死、什么算废话 |
| `skill: "skill-creator:skill-creator"` | skill 本身的结构与触发率：frontmatter、`description` 的触发短语、渐进披露、eval 与基准测试 |

**两个都要读，不是二选一。** 前者管**文字质量**（对 SKILL.md、agent 系统提示词、command 正文、
hook 的 deny/hint 文案、reference 文档一律作用）；后者管**结构与触发**（frontmatter 字段、
目录布局、description 怎么写才会被自动加载）。只读其一会漏掉另一半的判据。

### 触发判据（机械，按文件路径判，不按改动大小判）

本轮将要 `Write` 或 `Edit` 任何位于 `plugins/**` 下的文件即触发，含：

- `plugins/*/skills/**/SKILL.md` 及其 `references/` `examples/` `scripts/`
- `plugins/*/agents/*.md`
- `plugins/*/commands/*.md`
- `plugins/*/hooks/**`（含 `hooks.json` 与 hook 脚本里的 deny / ask / hint 文案）
- `plugins/*/.claude-plugin/plugin.json`、`plugins/*/.codex-plugin/plugin.json`
- `plugins/*/README.md` 及插件内其它 md
- 新建一个插件（此时按「改插件」处理，判据同上）

「这次只改一行」「只是调个措辞」「只是改 description」**都不豁免**——description 的触发率
恰好是 `skill-creator` 的核心内容，措辞恰好是 `writing-for-agents` 的核心内容，这两类小改动
是本约束最该覆盖的场景。

### 什么时候不触发

- **只读操作**：读代码、回答关于某插件的提问、查版本号、跑检查脚本。
- **`plugins/**` 之外的改动**：仓根 `README.md`、`Agents.md`、`scripts/`、`.githooks/`、
  `.claude/rules/`、本文件自身。
- **纯机械对齐**：同步 version 号、跑 `node scripts/check-versions.js --fix`、批量改路径常量
  这类不涉及任何面向 agent 的表述的改动。
- **用户在当轮明确说了不用读**：以他当轮的话为准，且只对当次有效。

### 执行要求

读技能的动作必须是**真实的两次 `Skill` 工具调用**，不接受「我已了解这两个技能的内容」这类
声明代替。同一会话内已经读过则不必重读。

## 其余仓库规约

- 通用开发规范（可移植性、commands / skills / agents / hooks 各自的结构要求、MCP、敏感信息、
  版本与发布）见 `Agents.md`。
- 按路径生效的项目规则见 `.claude/rules/project/`，其中 `plugin-description-length.md` 给出了
  `description` 的字符硬上限与四处登记点，改 description 时与上面两个技能一起用。
