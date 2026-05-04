# OMP Plugin

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

## 技能列表

| 技能 | 描述 | 触发词 |
| --- | --- | --- |
| `using-omp` | 在 Claude Code/Codex 中调用 omp CLI 的基本用法和常见场景 | 调用 omp、使用 omp CLI、omp 命令 |
| `omp-search` | 通过 omp 进行 Web 搜索和代码搜索 | 调用 omp 搜索、omp web_search、搜索资料 |
| `omp-review` | 通过 omp 进行代码审查 | 调用 omp 审查、omp review、代码审查 |
| `omp-subagent` | 通过 omp 使用子代理执行并行任务 | 调用 omp 子代理、omp task、并行执行 |

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

## Hooks

本插件包含以下 hooks 来强制 Claude Code 使用 omp：

| Hook 事件 | 触发条件 | 行为 |
| --- | --- | --- |
| `SessionStart` | 会话开始 | 注入 omp 使用指南和约定 |
| `PreToolUse` | 使用 Read/Edit/Write/Grep/Bash 前 | 注入提醒，建议改用 omp -p 委托 |

Hooks 在插件启用时自动加载，无需额外配置。如需禁用，可在 `.claude/settings.local.json` 中设置 `"disableAllHooks": true`。

## 版本历史

- `1.1.0` - 添加 hooks 强制使用 omp，精简 using-omp 技能
- `1.0.0` - 初始版本，包含 5 个技能：using-omp, omp-commit, omp-search, omp-review, omp-subagent
