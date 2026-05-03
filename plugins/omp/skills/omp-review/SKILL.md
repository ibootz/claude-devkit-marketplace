---
name: omp-review
description: 在 Claude Code/Codex 中调用 omp 进行代码审查。触发词：调用 omp 审查、omp review、代码审查、检查代码质量
---

# 在 Claude Code/Codex 中调用 omp 代码审查

本文档说明如何在 Claude Code 或 Codex 会话中，通过 CLI 调用 `omp` 进行代码审查。

## 基本调用方式

### 使用 omp -p 调用审查功能

```bash
# 审查未提交的变更
!omp -p --tools "read,grep,lsp,report_finding" "审查当前未提交的代码变更，检查 bugs、安全问题和代码质量，使用 report_finding 工具报告发现"

# 审查特定文件
!omp -p --tools "read,grep,lsp,report_finding" "审查 src/auth/login.ts 文件，重点关注错误处理、安全性和性能"
```

### 在 omp 交互模式中调用 /review

```bash
# 启动 omp 交互模式（在 Claude Code 中可执行，但交互性受限）
!omp
# 然后在 omp 中输入 /review
```

推荐在 Claude Code 中直接使用 `-p` 模式调用审查。

## 在 Claude Code 会话中的使用场景

### 场景 1：审查未提交的变更

```bash
# 1. 查看变更
!git diff

# 2. 使用 omp 进行深度审查
!omp -p --tools "read,grep,lsp,git-file-diff,report_finding" "审查当前所有未提交的变更，按 P0-P3 优先级报告发现的问题"
```

### 场景 2：审查特定文件

```bash
# 审查单个文件
!omp -p --tools "read,grep,lsp,report_finding" "审查 src/api/users.ts，检查：1) 类型安全 2) 错误处理 3) 性能问题 4) 安全漏洞"
```

### 场景 3：审查分支差异

```bash
# 比较分支差异
!git diff main...feature-branch

# 使用 omp 审查
!omp -p --tools "read,grep,lsp,git-file-diff,report_finding" "审查 main...feature-branch 分支差异，重点关注架构变更和潜在回归"
```

### 场景 4：审查特定提交

```bash
# 查看提交
!git show <commit-hash>

# 使用 omp 审查
!omp -p --tools "read,grep,lsp,report_finding" "审查提交 <commit-hash> 的变更，评估代码质量和潜在风险"
```

### 场景 5：批量审查多个文件

```bash
# 审查整个目录
!omp -p --tools "read,grep,lsp,find,report_finding" "审查 src/services/ 目录下的所有文件，检查代码质量和一致性"
```

## 审查检查项

在提示中明确指定审查重点：

```bash
!omp -p --tools "read,grep,lsp,report_finding" "审查代码，检查以下方面：
- 正确性：Bugs、逻辑错误、边界情况
- 安全性：SQL 注入、XSS、认证/授权、敏感信息泄露
- 代码质量：命名规范、函数复杂度、代码重复
- 性能：不必要的计算、内存泄漏、N+1 查询
- 测试：测试覆盖率、边界情况测试"
```

## 使用 report_finding 工具

omp 的 `report_finding` 工具支持优先级分级：

| 优先级 | 说明 | 处理建议 |
| --- | --- | --- |
| P0 | 严重 (critical) | 必须立即修复 |
| P1 | 高 (high) | 重要问题，优先修复 |
| P2 | 中 (medium) | 一般问题，计划修复 |
| P3 | 低 (nit) | 小问题/建议 |

```bash
# 调用时明确要求使用 report_finding
!omp -p --tools "read,grep,lsp,report_finding" "审查 src/auth/，使用 report_finding 工具报告发现的问题，包含 P0-P3 优先级"
```

## 与 Claude Code 工具配合

```bash
# 1. Claude Code 读取待审查文件
read src/auth/login.ts

# 2. 使用 omp 进行深度审查
!omp -p --tools "read,grep,lsp,report_finding" "审查该文件，报告所有问题"

# 3. omp 输出审查结果（包含发现的问题）

# 4. Claude Code 根据审查结果修复问题
edit src/auth/login.ts ...
```

## 审查裁决

omp 审查完成后会生成裁决：
- **approve** - 批准变更
- **request-changes** - 请求变更
- **comment** - 仅评论

```bash
# 获取完整审查结果
!omp -p --tools "read,grep,lsp,report_finding" "审查变更并给出明确的 approve/request-changes/comment 裁决"
```

## 实际工作流示例

### 示例 1：Pull Request 审查

```bash
# 在 Claude Code 会话中审查 PR
# 1. 获取 PR 变更
!git fetch origin pull/123/head:pr-123
!git diff main...pr-123

# 2. 使用 omp 深度审查
!omp -p --tools "read,grep,lsp,git-file-diff,report_finding" "审查 PR #123 的所有变更，按优先级报告问题，给出 approve 或 request-changes 裁决"

# 3. Claude Code 可以根据审查结果
# - 如果 approve：合并 PR
# - 如果 request-changes：通知作者修改
```

### 示例 2：重构后的审查

```bash
# 重构完成后审查
!git add .
!omp -p --tools "read,grep,lsp,report_finding" "审查重构后的代码，重点检查：1) 功能是否保持一致 2) 是否有引入新 bug 3) 代码质量是否提升"
```

### 示例 3：安全检查

```bash
# 专门进行安全审查
!omp -p --tools "read,grep,lsp,report_finding" "安全审查：检查 src/ 目录下所有代码是否存在：1) SQL 注入风险 2) XSS 漏洞 3) 认证绕过 4) 敏感信息泄露。使用 report_finding 报告 P0-P2 问题"
```

### 示例 4：性能审查

```bash
# 性能焦点审查
!omp -p --tools "read,grep,lsp,report_finding" "性能审查：分析 src/services/ 目录，检查：1) N+1 查询 2) 不必要的计算 3) 内存泄漏风险 4) 低效的算法"
```

## 自定义审查标准

可以在提示中指定项目的特定审查标准：

```bash
!omp -p --tools "read,grep,lsp,report_finding" "根据以下标准审查代码：

### 项目特定规则
- 所有 API 调用必须有错误处理
- 禁止使用 var，使用 const/let
- 异步函数必须有 try-catch
- 敏感信息不得硬编码

### 通用检查
- 代码质量
- 安全性
- 性能

使用 report_finding 报告发现。"
```

## 输出格式

omp 审查输出包含：
- **裁决**：approve / request-changes / comment
- **发现列表**：按优先级 (P0-P3) 分组的问题
- **结果树**：完整的审查结果结构

## 注意事项

1. **工具权限**：确保 omp 有 `read`、`grep`、`lsp` 等工具的访问权限
2. **API 密钥**：审查功能需要配置 LLM API 密钥
3. **LSP 配置**：`lsp` 工具需要项目中配置相应的语言服务器
4. **上下文**：对于大型变更，可能需要分批审查
5. **人工复核**：AI 审查结果需要人工最终确认

## 快捷参考

```bash
# 快速审查未提交变更
!omp -p --tools "read,grep,lsp,report_finding" "审查未提交变更"

# 审查特定文件
!omp -p --tools "read,grep,lsp,report_finding" "审查 <文件路径>"

# 分支差异审查
!omp -p --tools "read,grep,lsp,git-file-diff,report_finding" "审查 <branch1>...<branch2>"

# 深度审查（包含裁决）
!omp -p --tools "read,grep,lsp,report_finding" "深度审查并给出 approve/request-changes 裁决"
```
