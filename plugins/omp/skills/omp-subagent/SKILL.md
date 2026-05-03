---
name: omp-subagent
description: 在 Claude Code/Codex 中利用 omp 的子代理能力执行并行任务。触发词：调用 omp 子代理、omp task、并行执行、spawn 子任务
---

# 在 Claude Code/Codex 中调用 omp 子代理

本文档说明如何在 Claude Code 或 Codex 会话中，通过 CLI 调用 `omp` 使用子代理（task 工具）执行复杂任务。

## 基本调用方式

### 使用 omp -p 自动触发 task 工具

```bash
# omp 会根据任务复杂度自动使用 task 工具启动子代理
!omp -p --tools "read,write,edit,bash,grep,find,lsp,task" "探索这个项目的架构并总结主要模块"

# 明确指定使用 task 工具
!omp -p --tools "task,read,grep,find" "使用子代理探索 src/ 目录，分析代码质量"
```

### 在提示中明确要求使用子代理

```bash
!omp -p --tools "task,read,write,edit,bash,lsp" "使用 task 工具启动子代理，并行完成：1) 分析现有代码 2) 设计重构方案 3) 执行重构"
```

## 在 Claude Code 会话中的使用场景

### 场景 1：大型代码库探索

```bash
# Claude Code 中启动 omp 子代理探索项目
!omp -p --tools "task,read,find,grep,lsp" "使用子代理探索整个项目，生成架构文档，包括：主要模块、依赖关系、技术栈"
```

omp 会自动使用 `task` 工具启动 explore 代理进行探索。

### 场景 2：并行代码审查

```bash
# 使用子代理并行审查多个模块
!omp -p --tools "task,read,grep,lsp,report_finding" "使用子代理并行审查：1) src/auth/ 模块 2) src/api/ 模块 3) src/utils/ 模块，汇总所有发现"
```

### 场景 3：复杂重构任务

```bash
# 使用子代理执行多阶段重构
!omp -p --tools "task,read,write,edit,bash,grep,lsp" "使用子代理完成重构：1) explore 代理分析现有代码 2) plan 代理设计重构方案 3) task 代理执行重构"
```

### 场景 4：多任务并行执行

```bash
# 并行执行多个独立任务
!omp -p --tools "task,read,write,bash" "启动多个子代理并行执行：1) 更新依赖 2) 运行测试 3) 生成文档 4) 检查代码质量"
```

### 场景 5：后台任务执行

```bash
# 启动长时间运行的任务
!omp -p --tools "task,bash" "使用子代理在后台运行完整的测试套件，并生成测试报告"
```

## 内置子代理类型

omp 支持以下内置代理：

| 代理 | 用途 | 适用场景 |
| --- | --- | --- |
| `explore` | 代码库探索和调查 | 理解新项目、分析架构 |
| `plan` | 计划和架构设计 | 设计重构方案、规划功能 |
| `designer` | UI/UX 设计 | 界面设计、组件规划 |
| `reviewer` | 代码审查 | 深度代码审查、质量检查 |
| `task` | 通用任务执行 | 执行具体操作、文件修改 |
| `quick_task` | 快速轻量级任务 | 简单查询、快速修改 |

```bash
# 指定使用特定类型的子代理
!omp -p --tools "task" "使用 explore 代理分析 src/services/ 目录的架构"
```

## 隔离模式

对于需要隔离环境的任务，可以指定隔离模式：

```bash
# 注意：隔离模式目前主要通过 omp 交互模式配置
# 在 CLI -p 模式下，可以通过提示说明隔离需求

!omp -p --tools "task,read,write,edit,bash" "使用隔离模式（worktree）执行重构任务，避免影响当前工作目录"
```

## 与 Claude Code 工具配合

```bash
# 1. Claude Code 分析任务复杂度
# 判断是否需要子代理

# 2. 调用 omp 使用子代理
!omp -p --tools "task,read,write,edit,bash,grep,lsp" "任务描述"

# 3. omp 启动子代理执行
# 子代理会实时流式输出进度

# 4. Claude Code 可以读取子代理的完整输出
# 通过 omp 输出的 agent://<id> 引用

# 5. 根据子代理结果继续操作
edit ...
```

## 实时输出和进度跟踪

omp 子代理支持实时流式输出：

```bash
# 子代理的输出会实时显示
!omp -p --tools "task,read,write,bash" "执行长时间任务，实时报告进度"
```

## 访问子代理完整输出

当输出被截断时，可以通过 `agent://` 资源访问完整输出：

```bash
# omp 输出可能会包含类似这样的引用
# agent://task-abc123

# 在 Claude Code 中可以读取完整输出（如果 omp 支持导出）
# 或者通过后续提示获取
!omp -p "读取 task-abc123 的完整输出并总结"
```

## 实际工作流示例

### 示例 1：新项目上手

```bash
# 在 Claude Code 中快速理解新项目
!omp -p --tools "task,read,find,grep,lsp" "使用 explore 子代理全面分析这个项目的：1) 技术栈 2) 目录结构 3) 核心模块 4) 依赖关系 5) 构建流程，生成项目概述文档"
```

### 示例 2：功能开发

```bash
# 使用子代理协作开发新功能
!omp -p --tools "task,read,write,edit,bash,grep,lsp" "使用子代理协作开发用户认证功能：
- explore 代理：分析现有代码，确定集成点
- plan 代理：设计 API 接口和数据模型
- task 代理：实现服务端和客户端代码
- reviewer 代理：审查实现的质量和安全性"
```

### 示例 3：代码质量改进

```bash
# 并行改进多个方面的代码质量
!omp -p --tools "task,read,grep,lsp,report_finding" "启动多个子代理并行改进代码质量：
1) reviewer 代理：审查 src/ 所有代码，报告问题
2) explore 代理：分析重复代码，提出重构建议
3) task 代理：修复所有 P0 和 P1 级别的问题"
```

### 示例 4：技术债务清理

```bash
# 使用子代理系统性清理技术债务
!omp -p --tools "task,read,write,edit,grep,bash" "使用子代理清理技术债务：
- 识别并移除未使用的代码
- 更新过时的依赖
- 改进错误处理
- 增加缺失的测试覆盖率
- 重构复杂函数"
```

### 示例 5：文档生成

```bash
# 并行生成多种文档
!omp -p --tools "task,read,grep,find" "使用子代理并行生成文档：
1) API 文档：扫描所有 API 端点
2) 架构文档：分析模块依赖
3) README：更新项目说明
4) CHANGELOG：整理历史变更"
```

## 异步后台任务

对于耗时较长的任务，可以使用异步模式：

```bash
# omp 支持通过配置启用异步任务
# 在 CLI 中可以通过提示说明

!omp -p --tools "task,bash" "在后台运行完整的测试套件（包括集成测试和 e2e 测试），生成详细的测试报告"
```

## 配置子代理行为

虽然主要通过 CLI 调用，但了解 omp 的子代理配置有助于更好使用：

```yaml
# 在 ~/.omp/agent/config.yml 中配置
task:
  eager: false  # 是否立即启动任务
  isolation:
    mode: none  # none | worktree | fuse-overlay | fuse-projfs
    merge: patch  # patch | branch

async:
  enabled: false
  maxJobs: 100  # 最大并发任务数
```

## 注意事项

1. **工具权限**：确保 omp 有 `task` 工具和其他必要工具的权限
2. **API 成本**：子代理会消耗更多 API 调用，注意成本
3. **上下文隔离**：子代理有独立的上下文，可能需要重新读取文件
4. **合并策略**：隔离模式下的变更需要合并回主分支/工作目录
5. **并发限制**：注意系统资源和 API 速率限制

## 快捷参考

```bash
# 使用子代理探索项目
!omp -p --tools "task,read,find,grep" "使用 explore 代理探索项目"

# 使用子代理执行重构
!omp -p --tools "task,read,write,edit,lsp" "使用子代理重构 <模块>"

# 并行代码审查
!omp -p --tools "task,read,grep,lsp,report_finding" "使用多个子代理并行审查"

# 复杂多阶段任务
!omp -p --tools "task,read,write,edit,bash" "阶段1:分析 阶段2:设计 阶段3:实现"

# 后台长时间任务
!omp -p --tools "task,bash" "后台执行 <任务描述>"
```
