# omp Plugin

Oh my pi (omp) CLI 工具集成插件 - 在 Claude Code/Codex 中通过 CLI 调用 omp 实现编码任务。

## 简介

本插件封装了 [Oh my pi (omp)](https://github.com/can1357/oh-my-pi) 的功能，使其可以在 Claude Code 或 Codex 会话中通过命令行直接调用，实现编码、代码审查、Git 提交、Web 搜索、子代理管理等任务。

## 安装

### 前置条件

确保已安装 omp CLI：

```bash
# 通过 Bun (推荐)
bun install -g @oh-my-pi/pi-coding-agent

# 通过安装脚本 (Linux/macOS)
curl -fsSL https://raw.githubusercontent.com/can1357/oh-my-pi/main/scripts/install.sh | sh

# Windows (PowerShell)
irm https://raw.githubusercontent.com/can1357/oh-my-pi/main/scripts/install.ps1 | iex
```

### 安装插件

将此插件放到 Claude Code 的插件目录中，或者通过插件市场安装。

## 启用编排协议（可选，默认关闭）

本插件包含两个 hook 会在会话/消息层面向 Claude 注入「Orchestrator + omp 子代理」编排协议（`hooks/orchestrator-protocol-init.js` 走 `SessionStart`，`hooks/orchestrator-protocol-remind.js` 走 `UserPromptSubmit`）。**从 2.3.0 起，hook 默认不注入**，避免对未使用 omp 工作流的会话造成侵入。

需要启用时，设置环境变量 `OMP_PROTOCOL_ENABLED` 为以下任一值（大小写不敏感）：`1` / `true` / `on` / `yes`。其他值或未设置 = 静默放行。

| 平台 | 命令 |
| --- | --- |
| Windows PowerShell（持久） | `[Environment]::SetEnvironmentVariable("OMP_PROTOCOL_ENABLED","1","User")`，重启 Claude Code |
| Windows PowerShell（临时） | `$env:OMP_PROTOCOL_ENABLED="1"` 后在同一 shell 启动 `claude` |
| Windows CMD（持久） | `setx OMP_PROTOCOL_ENABLED 1`，重开终端 |
| Bash / Zsh | 在 `~/.bashrc` 或 `~/.zshrc` 加 `export OMP_PROTOCOL_ENABLED=1` |

启用后：会话开始时注入完整编排协议（决策树、子代理调用规范、prompt 5 要素），用户每次发消息时注入精简提醒；若当前消息含豁免词（如 `你直接 X`、`不用 omp`、`no omp`），仍会跳过提醒注入。

## 技能列表

| 技能 | 描述 | 触发词 |
| --- | --- | --- |
| `omp` | 将 omp 作为执行代理（Worker），你作为指挥者（Orchestrator）管理任务：代码编写、审查、搜索、重构等 | 调用 omp、使用 omp CLI、omp 命令、omp 编码、omp 代码审查、omp 提交 |

## 子代理列表

| 子代理 | 描述 | 触发词 |
| --- | --- | --- |
| `omp-task` | 执行通用编码任务：功能实现、代码重构、文件操作、测试编写 | 实现功能、编写代码、重构代码、执行任务 |
| `omp-explore` | 进行代码库探索、架构分析和模块调查 | 探索项目、分析代码库、理解架构、代码调查、模块分析 |
| `omp-plan` | 进行架构设计、技术方案制定和任务规划 | 设计方案、架构规划、制定计划、技术方案、任务拆解 |

## 使用示例

### 基本调用

在 Claude Code/Codex 会话中，使用 `!` 前缀执行 omp 命令：

```bash
# 直接执行提示并获取输出
!omp -p "你的问题或任务"

# 使用特定工具限制
!omp -p --tools "read,write,edit,bash" "任务描述"
```

### 代码审查

```bash
!omp -p --tools "read,grep,lsp,report_finding" "审查当前未提交的代码变更，检查 bugs、安全问题和代码质量"
```

### Git 提交

```bash
# 生成提交
!omp commit --dry-run

# 提交并推送
!omp commit --push
```

### Web 搜索

```bash
# 搜索技术文档
!omp search "TypeScript 5.8 新特性"

# 详细搜索
!omp -p --tools "web_search,fetch" "搜索 React 19 新特性并总结"
```

### 子代理任务

```bash
# 使用子代理探索项目
!omp -p --tools "task,read,find,grep" "使用子代理探索项目架构并生成文档"
```

## 配置

### API 密钥

omp 需要配置相应的 API 密钥：

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export GEMINI_API_KEY="..."
```

### 模型选择

```bash
# 使用快速模型
!omp -p --model "anthropic/claude-sonnet-4-6" "任务描述"

# 使用深度推理模型
!omp -p --model "anthropic/claude-opus-4-6:high" "复杂任务"
```

## 工具限制

通过 `--tools` 参数限制 omp 可用的工具：

| 工具集 | 用途 |
| --- | --- |
| `--tools "read,write,edit,bash"` | 基础文件编辑 |
| `--tools "read,grep,ast_grep,lsp"` | 代码搜索分析 |
| `--tools "web_search,fetch"` | 信息研究 |
| `--no-tools` | 纯对话模式 |

## 相关链接

- [Oh my pi GitHub](https://github.com/can1357/oh-my-pi)
- [Oh my pi 官网](https://pi.dev/)
- [npm 包](https://www.npmjs.com/package/@oh-my-pi/pi-coding-agent)
- [Claude Code 文档](https://docs.anthropic.com/claude-code)

## 版本历史

- `2.3.0` - 两个编排协议 hook（`orchestrator-protocol-init.js` / `orchestrator-protocol-remind.js`）改为按 `OMP_PROTOCOL_ENABLED` 环境变量显式启用，默认不注入；降低对未使用 omp 工作流会话的侵入性
- `2.0.0` - 重构版本：合并为 1 个综合技能 `omp`，新增 3 个子代理（omp-task, omp-explore, omp-plan）
- `1.0.0` - 初始版本，包含 5 个技能：using-omp, omp-commit, omp-search, omp-review, omp-subagent
