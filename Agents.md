# Claude DevKit Marketplace - Agents 规则

## 目标
- 本仓库为 Claude Code / Codex 插件市场仓库，核心目标是：稳定、可移植、可发布。
- 任何改动必须以 `.claude-plugin/marketplace.json` 与各插件自身 `.claude-plugin/plugin.json` 为事实来源，避免文档/配置漂移。

## 仓库结构约束
- 市场根：`.claude-plugin/marketplace.json`
- 插件根：`plugins/<plugin-name>/`
- 插件清单/真实插件名以 `marketplace.json.plugins[].name` 为准。

## 通用开发规范（对齐 plugin-dev）
### 可移植性
- 所有插件内脚本、hooks、commands 里引用文件路径时必须使用 `${CLAUDE_PLUGIN_ROOT}`，禁止硬编码绝对路径。
- 插件目录布局遵循 Claude Code auto-discovery：
  - `.claude-plugin/plugin.json`
  - `commands/`（markdown + YAML frontmatter）
  - `skills/`（SKILL.md + resources/examples/scripts 等）
  - `agents/`（如有）
  - `hooks/`（hooks.json + scripts/）

### Commands
- `commands/*.md` 必须包含 YAML frontmatter，描述清晰、参数提示明确。
- Command 内容避免写死仓库路径；需要引用文件时使用相对路径或 `${CLAUDE_PLUGIN_ROOT}`。

### Skills
- `skills/<name>/SKILL.md` 必须：
  - frontmatter 包含 `name`、`description`
  - description 需要包含可触发的短语（trigger phrases），便于自动加载
  - 内容遵循“渐进披露”：先给核心用法，再给 references/examples/scripts

### Agents（如存在）
- `agents/*.md` 使用 YAML frontmatter + system prompt 结构。
- agent description 需要具备可靠触发的示例（参考 plugin-dev 的 agent-development 规范）。

### Hooks
- 优先使用 prompt-based hooks；如需 command hooks，必须明确输入/输出 JSON schema。
- 所有 hooks 脚本必须做到：
  - 失败可解释（明确 deny/block 的原因）
  - 不泄露敏感信息
  - 不依赖本机固定路径

## MCP 插件规范
- MCP 配置必须采用 `.mcp.json` 或 `plugin.json` 约定之一（保持一致），并在 README 里说明“需要哪些环境变量”。
- 对于需要本地/远端服务的 MCP 插件：
  - 禁止在仓库内提交真实密钥
  - 必须提供示例配置文件（如 `.claude-skills.env.example`）

## 敏感信息与配置
- `.claude-skills.env` 视为敏感文件：
  - 不允许提交
  - 必须提供 `.claude-skills.env.example` 作为模板
- 所有 token/cookie/key 必须通过环境变量读取。

## 版本与发布
- 任何插件功能变更都必须同步修改：
  - 插件自身 `plugins/<name>/.claude-plugin/plugin.json` 的 `version`
  - 市场根 `.claude-plugin/marketplace.json` 对应条目的 `version`
- README 中的插件列表/命令数量等信息必须来自真实目录与配置；如果难以保证一致，优先减少“数量声明”，改为“以 marketplace.json 为准”。
