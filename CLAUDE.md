# claude-devkit-marketplace 项目指令

本仓是 Claude Code / Codex 插件市场仓：市场清单在 `.claude-plugin/marketplace.json`，
各插件在 `plugins/<plugin-name>/`。

## 硬约束：改插件前必须先读技能

**动手改任何插件内容之前**，先用 `Skill` 工具读完下面两组技能，读完再动笔：通用的两个必读，
再按将要写的文件路径追加 `plugin-dev` 对应技能。

### 通用：两个必读

| 调用 | 管什么 |
|---|---|
| `skill: "mattpocock-skills:writing-for-agents"` | 写给 agent 看的文字怎么写：指令密度、歧义消除、什么该显式写死、什么算废话 |
| `skill: "skill-creator:skill-creator"` | skill 本身的结构与触发率：frontmatter、`description` 的触发短语、渐进披露、eval 与基准测试 |

**两个都要读，不是二选一。** 前者管**文字质量**（对 SKILL.md、agent 系统提示词、command 正文、
hook 的 deny/hint 文案、reference 文档一律作用）；后者管**结构与触发**（frontmatter 字段、
目录布局、description 怎么写才会被自动加载）。只读其一会漏掉另一半的判据。

### 按路径追加：plugin-dev 技能

`plugin-dev` 管**各组件的格式规格**（字段、事件、目录约定）。本轮要写的路径命中下表哪几行，
就把那几行的技能都读掉（取并集）；命中多行的同一技能只读一次。

| 本轮要写的路径 | 追加读 |
|---|---|
| 新建插件（`plugins/<name>/` 目录尚不存在） | `plugin-dev:create-plugin`、`plugin-dev:plugin-structure` |
| `plugins/*/.claude-plugin/plugin.json`、`plugins/*/.codex-plugin/plugin.json`；插件目录改名、组件目录增删 | `plugin-dev:plugin-structure` |
| `plugins/*/skills/**` | `plugin-dev:skill-development` |
| `plugins/*/agents/*.md` | `plugin-dev:agent-development` |
| `plugins/*/commands/*.md` | `plugin-dev:command-development` |
| `plugins/*/hooks/**` | `plugin-dev:hook-development` |
| `plugins/*/.mcp.json`，或 plugin.json 里的 `mcpServers` | `plugin-dev:mcp-integration` |
| 插件读写用户侧配置或状态文件（`.claude/<plugin>.local.md` 一类） | `plugin-dev:plugin-settings` |
| `plugins/*/README.md` 及插件内其它说明性 md | 无追加，只读通用两个 |

例：给某插件加一个 hook 并同步升版本号 → 写 `hooks/**` 与 `plugin.json`，追加
`plugin-dev:hook-development` + `plugin-dev:plugin-structure`。

`plugin-dev` 的示例与本仓规约冲突时以本仓为准——如 hook 脚本按 `devkit-portable-shell` 约定写成 node
调起的 JS（`plugin-dev` 示例是 `.sh`），commands 已废弃、新能力做成 skill。

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

读技能的动作必须是**每个技能一次真实的 `Skill` 工具调用**，不接受「我已了解这些技能的内容」这类
声明代替。同一会话内已经读过则不必重读。

## Agent skills

### Issue tracker

Issues and specs are tracked as local Markdown under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default five-role triage vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

Use the single-context layout: root `CONTEXT.md` plus `docs/adr/`. See `docs/agents/domain.md`.

## 其余仓库规约

- 通用开发规范（可移植性、commands / skills / agents / hooks 各自的结构要求、MCP、敏感信息、
  版本与发布）见 `Agents.md`。
- 按路径生效的项目规则见 `.claude/rules/project/`，其中 `plugin-description-length.md` 给出了
  `description` 的字符硬上限与四处登记点，改 description 时与上面的技能一起用。
