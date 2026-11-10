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
- hook 一律注册在 `plugins/<name>/hooks/hooks.json`（`{"description": "...", "hooks": {...}}`），Claude Code 与 Codex 都按这个默认路径加载。`.claude-plugin/plugin.json` 与 `.codex-plugin/plugin.json` 都不写 `hooks` 字段：写内联对象 Codex 不识别；写 `"hooks": "./hooks/hooks.json"` 会让 Claude Code 报重复加载。
- 不要建插件根目录 `plugin.json`、不要把 hooks 内联进清单——Codex 0.167 实测两者都会让 hook 不被识别。
- 宿主是 Codex 时 `PreToolUse` 的 `permissionDecision: "ask"` 不生效（视为 hook 失败、工具照常执行）。需要用户确认的闸，在 Codex 下改输出 `deny` 并要求用户同意后带 `DEVKIT_CONFIRMED=1` 重跑；宿主判别：环境变量 `PLUGIN_ROOT` 非空或输入 JSON 含 `turn_id` → Codex。参照 `plugins/devkit-task-keeper/hooks/lib/debug_worktree_destroy_guard.py`。
- 注入类 hook（SessionStart / UserPromptSubmit / SubagentStart）按同一宿主判别分流，Claude 侧输出逐字不变、用 golden 快照测试钉住（形态见 `plugins/devkit-discipline/test/codex-host-verify.js`）。Codex 侧：点名 Claude 专属工具（`Agent` 字段与 model 档位、Explore / Plan、`SendMessage` / `ListAgents`、`AskUserQuestion`、`TaskList`、`EnterWorktree`、Skill 工具）的段落省略或换成不点名工具的表述；整段依赖这些工具的注入（devkit-tool 跨会话通信、devkit-omp、task-keeper 的 keeper 路由与队列快照）在 Codex 下整段不注入。
- 文件引用形态（2026-11-10 拍板）：Codex 下写 inline code，仓内路径相对仓库根、仓外写绝对路径，后接 `:行号`，不写行号范围，禁用 `file://` / `vscode://`——Codex 系统提示只认 inline code 路径为可点击，TUI 把 `[x](file:///…)` 渲染成「标签 (路径)」纯文本（转述主会话对 openai/codex 源码的核查）。落盘 md 那一轨不随宿主变。
- skill 正文不写 `${CLAUDE_PLUGIN_ROOT}`：Codex 不替换 SKILL.md 正文、也不把这个变量注入模型执行命令的 shell（只注入 hook 进程）。写相对本 SKILL.md 所在目录的路径，并在用到命令处写明一次「先拼上本 skill 目录再执行」。只对 Claude Code 有意义的 skill 在 description 末尾加「仅适用于 Claude Code。」，正文标题下一行写 Codex 下的替代做法。
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
