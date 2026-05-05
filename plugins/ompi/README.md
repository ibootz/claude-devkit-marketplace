# OMPI Plugin

Oh my pi (ompi) CLI 工具集成插件 - 在 Claude Code/Codex 中通过 CLI 调用 omp 实现编码任务。

## 简介

本插件封装了 [Oh my pi (ompi)](https://github.com/can1357/oh-my-pi) 的功能，使其可以在 Claude Code 或 Codex 会话中通过命令行直接调用，实现编码、代码审查、Git 提交、Web 搜索、子代理管理等任务。

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
| `ompi` | 将 ompi 作为执行代理（Worker），你作为指挥者（Orchestrator）管理任务：代码编写、审查、搜索、重构等 | 调用 ompi、使用 ompi CLI、ompi 命令、ompi 编码、ompi 代码审查、ompi 提交 |

## 子代理列表

| 子代理 | 描述 | 触发词 |
| --- | --- | --- |
| `ompi-task` | 执行通用编码任务：功能实现、代码重构、文件操作、测试编写 | 实现功能、编写代码、重构代码、执行任务 |
| `ompi-explore` | 进行代码库探索、架构分析和模块调查 | 探索项目、分析代码库、理解架构、代码调查、模块分析 |
| `ompi-plan` | 进行架构设计、技术方案制定和任务规划 | 设计方案、架构规划、制定计划、技术方案、任务拆解 |

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

- `2.0.0` - 重构版本：合并为 1 个综合技能 `ompi`，新增 3 个子代理（ompi-task, ompi-explore, ompi-plan）
- `1.0.0` - 初始版本，包含 5 个技能：using-omp, omp-commit, omp-search, omp-review, omp-subagent
