---
name: using-omp
description: 在 Claude Code 或 Codex 中通过 CLI 调用 omp 实现编码任务。触发词：调用 omp、使用 omp CLI、omp 命令、omp 编码、omp 代码审查、omp 提交
---

# 在 Claude Code/Codex 中调用 Oh my pi CLI (omp)

本文档说明如何在 Claude Code 或 Codex 会话中，通过命令行直接调用 `omp` 完成编码任务。

## 核心用法

在 Claude Code/Codex 中，使用 `!` 前缀或 Bash 工具执行 omp 命令：

```bash
# 直接执行提示并获取结果
omp -p "你的问题或任务"

# 使用特定模型（可选，支持模糊匹配）
omp -p --model "<model-name>" "任务描述"

# 使用特定工具限制
omp -p --tools "read,write,bash,grep,edit" "任务描述"
```

## 常见编码任务场景

### 1. 代码审查

```bash
# 审查未提交的变更
omp -p --tools "read,grep,bash,lsp" "审查当前未提交的代码变更，检查 bugs、安全问题和代码质量"

# 审查特定文件
omp -p --tools "read,grep,lsp" "审查 src/auth/login.ts 文件，重点关注错误处理和安全性"
```

### 2. 生成 Git 提交

```bash
# 使用 omp commit 子命令
omp commit --dry-run

# 或者在会话中调用
omp -p "分析暂存的变更并生成符合 conventional commits 的提交消息"
```

### 3. 代码搜索与分析

```bash
# 搜索代码模式
omp -p --tools "grep,ast_grep,read" "在项目中搜索所有使用 useEffect 的地方，并总结使用模式"

# 探索代码库
omp -p --tools "read,find,grep" "分析 src/services/ 目录的架构，总结主要模块和依赖关系"
```

### 4. 代码重构

```bash
# 重构任务
omp -p --tools "read,write,edit,bash,grep,lsp" "重构 src/utils/helpers.ts，改善函数命名和错误处理，确保通过 lsp 诊断"

# 使用 hashline 编辑（omp 的编辑工具）
omp -p --tools "read,edit,bash" "修复 src/api/users.ts 中的类型错误，使用 edit 工具进行精确编辑"
```

### 5. Web 搜索辅助编码

```bash
# 搜索技术文档
omp -p --tools "web_search,fetch,read" "搜索 React 19 新特性，并给出在当前项目中应用的建议"

# 查找包信息
omp -p --tools "web_search,fetch" "查找 npm 上最流行的 GraphQL 客户端，并比较它们的优缺点"
```

### 6. 多步骤任务

```bash
# 复杂任务（omp 会自动使用 task 工具启动子代理）
omp -p --tools "read,write,edit,bash,grep,find,lsp,task" "为项目添加用户认证功能，包括：1) 设计 API 接口 2) 实现服务端逻辑 3) 添加单元测试"
```

## 工具限制参数

通过 `--tools` 参数限制 omp 可用的工具，提高安全性和专注度：

| 工具集 | 用途 |
| --- | --- |
| `--tools "read,write,edit,bash"` | 基础文件编辑 |
| `--tools "read,grep,ast_grep,lsp"` | 代码搜索分析 |
| `--tools "read,write,edit,bash,lsp"` | 重构任务 |
| `--tools "web_search,fetch"` | 信息研究 |
| `--tools "bash,git-overview,git-file-diff"` | Git 操作 |
| `--no-tools` | 纯对话模式 |

## 模型选择

omp 支持通过 `--model` 参数指定模型，或在交互模式通过 `/model` 配置模型角色。

```bash
# 使用默认模型（在 omp config 中配置）
omp -p "任务描述"

# 指定模型（支持模糊匹配，可用 `omp --list-models` 查看）
omp -p --model "<model-name>" "任务描述"
```

模型角色配置参考：
- 通过 `omp` 交互模式输入 `/model` 配置
- 或在 `~/.omp/agent/config.yml` 中设置 `modelRoles`
- 支持多提供商：Anthropic、OpenAI、Gemini、本地模型等
- 使用 `omp --list-models` 列出所有可用模型

## 在 Claude Code 中的集成模式

### 模式 1：直接执行并获取输出

```bash
!omp -p "分析当前目录下的 TypeScript 文件，总结项目结构"
```

输出会自动包含在上下文中。

### 模式 2：排除输出（仅执行）

```bash
!!omp commit --dry-run
```

执行命令但不将输出包含在上下文中。

### 模式 3：条件执行

```bash
# 先检查条件
!git status
# 如果有变更，执行 omp
!omp -p "审查这些变更并生成提交消息"
```

## 输出处理

omp 的输出格式：
- **text 模式**（默认）：人类可读的文本输出
- **json 模式**：结构化 JSON 输出（使用 `--mode json`）

```bash
# 获取 JSON 格式输出
omp -p --mode json "分析 package.json 中的依赖"

# 解析 JSON 输出（在 Claude Code 中）
# 输出会包含结构化的结果，可以直接解析
```

## 与 Claude Code 工具配合

```bash
# 1. Claude Code 读取文件
read src/index.ts

# 2. 使用 omp 分析
!omp -p --tools "grep,lsp" "分析这个文件的代码质量，检查是否有改进空间"

# 3. Claude Code 根据 omp 的输出进行修改
edit src/index.ts ...
```

## 实际示例

### 示例 1：修复 Bug

```bash
# 在 Claude Code 会话中
!omp -p --tools "read,grep,bash,lsp,edit" "用户报告登录失败，请诊断 src/auth/ 目录的问题并修复"
```

### 示例 2：添加功能

```bash
!omp -p --tools "read,write,edit,bash,lsp,task" "添加用户头像上传功能，包括 API 端点、文件验证和存储逻辑"
```

### 示例 3：代码审查

```bash
# 审查 PR 的变更
!omp -p --tools "read,bash,grep,lsp" "审查 main...feature-branch 分支的变更，报告 P0-P3 级别的问题"
```

### 示例 4：技术调研

```bash
!omp -p --tools "web_search,fetch,code_search" "调研微服务架构的最佳实践，并给出在当前项目中实施的建议"
```

## 注意事项

1. **工具权限**：确保 omp 有权限访问项目文件和执行命令
2. **API 密钥**：omp 需要配置相应的 API 密钥（ANTHROPIC_API_KEY 等）
3. **上下文传递**：omp 的上下文独立于 Claude Code，需要通过提示明确任务
4. **输出长度**：对于长输出，omp 可能会截断，使用 `agent://` 资源访问完整输出
5. **模型成本**：选择合适的模型平衡成本和质量

## 快捷命令参考

| 任务 | 命令 |
| --- | --- |
| 快速代码审查 | `omp -p --tools "read,grep,lsp" "审查变更"` |
| 生成提交 | `omp commit` |
| 代码搜索 | `omp -p --tools "grep,ast_grep" "搜索模式"` |
| 重构代码 | `omp -p --tools "read,edit,write,lsp" "重构任务"` |
| Web 搜索 | `omp -p --tools "web_search,fetch" "搜索内容"` |
| 探索代码库 | `omp -p --tools "read,find,grep" "分析项目结构"` |
