---
name: omp-search
description: 在 Claude Code/Codex 中调用 omp 进行 Web 搜索和代码搜索。触发词：调用 omp 搜索、omp web_search、omp search、搜索资料、查找文档
---

# 在 Claude Code/Codex 中调用 omp 搜索

本文档说明如何在 Claude Code 或 Codex 会话中，通过 CLI 调用 `omp` 进行 Web 搜索和代码搜索。

## 基本调用方式

### 使用 omp search 子命令

```bash
# 搜索 Web 内容
omp search "TypeScript 5.8 新特性"

# 使用别名 q
omp q "Rust 异步编程最佳实践"
```

### 使用 omp -p 调用 web_search 工具

```bash
# 在 Claude Code 中执行
!omp -p --tools "web_search,fetch" "搜索最新的 React 19 新特性并总结"
```

## 在 Claude Code 会话中的使用场景

### 场景 1：技术调研

```bash
# Claude Code 中执行搜索
!omp -p --tools "web_search,fetch" "搜索微服务架构的最佳实践，并给出关键要点"

# 输出会包含在 Claude Code 的上下文中
```

### 场景 2：查找文档和 API

```bash
# 搜索特定技术文档
!omp search "Next.js 15 App Router 文档"

# 或使用 -p 模式获取更详细的分析
!omp -p --tools "web_search,fetch,read" "查找 PyTorc 2.5 的 API 文档，并总结主要变更"
```

### 场景 3：包和库调研

```bash
# 搜索 npm 包
!omp search "npm 上最流行的 GraphQL 客户端 2026"

# 搜索并比较
!omp -p --tools "web_search,fetch" "比较 Apollo Client 和 urql 的优缺点，给出选择建议"
```

### 场景 4：安全漏洞查询

```bash
# 搜索 CVE 信息
!omp search "CVE-2024-1234 Node.js"

# 搜索安全最佳实践
!omp -p --tools "web_search,fetch" "2026 年 Node.js 应用安全最佳实践"
```

### 场景 5：代码搜索（使用 code_search）

```bash
# 搜索代码示例
!omp -p --tools "code_search,fetch" "搜索 React useEffect 清理函数的代码示例"
```

## 搜索提供商选择

通过环境变量或参数指定搜索提供商：

```bash
# 使用 Exa（需要 EXA_API_KEY）
!omp -p --tools "web_search" "搜索内容"

# 使用 Perplexity（需要 PERPLEXITY_API_KEY）
# omp 会根据配置的提供商自动选择
```

## 常用搜索提供商

| 提供商 | 环境变量 | 用途 |
| --- | --- | --- |
| `exa` | `EXA_API_KEY` | AI 驱动的深度搜索 |
| `brave` | `BRAVE_API_KEY` | Brave Search API |
| `perplexity` | `PERPLEXITY_API_KEY` | Perplexity AI 搜索 |
| `jina` | `JINA_API_KEY` | Jina Reader + 搜索 |
| `anthropic` | `ANTHROPIC_API_KEY` | Anthropic 内置搜索 |
| `gemini` | `GEMINI_API_KEY` | Google Gemini 搜索 |

## 与 Claude Code 工具配合

```bash
# 1. Claude Code 读取项目文件
read package.json

# 2. 发现需要调研的技术
# 例如：项目使用了某个不熟悉的库

# 3. 使用 omp 搜索文档
!omp -p --tools "web_search,fetch" "搜索 lodash merge 的安全问题和替代方案"

# 4. Claude Code 根据搜索结果修改代码
edit src/utils/merge.ts ...
```

## 输出处理

omp 搜索输出为 Markdown 格式，包含：
- 搜索结果摘要
- 关键要点
- 相关链接

```bash
# 获取 JSON 格式输出（如果需要结构化数据）
!omp -p --mode json --tools "web_search" "搜索内容"
```

## 实际工作流示例

### 示例 1：技术选型

```bash
# 在 Claude Code 会话中
# 需要选择 HTTP 客户端库

!omp -p --tools "web_search,fetch" "比较 axios、fetch、got、ky 的优缺点，给出 2026 年的选择建议"

# Claude Code 根据搜索结果给出建议
# 然后执行安装和代码修改
```

### 示例 2：调试问题

```bash
# 遇到奇怪的错误
!omp search "Node.js ERR_HTTP_HEADERS_SENT 错误原因和解决方案"

# 根据搜索结果
# Claude Code 可以分析代码并修复问题
```

### 示例 3：学习新技术

```bash
# 项目需要引入新的技术栈
!omp -p --tools "web_search,fetch,code_search" "搜索 Rust tokio 异步运行时的最佳实践和常见模式"

# Claude Code 根据搜索结果
# 编写示例代码或重构现有代码
```

### 示例 4：查找代码示例

```bash
# 需要特定的代码实现参考
!omp -p --tools "code_search,fetch" "搜索 TypeScript 中实现防抖函数的多种方法"

# Claude Code 可以参考这些示例
# 在项目中使用合适的实现
```

## 站点特定搜索

omp 对以下类型站点有优化：
- **代码托管**：GitHub, GitLab, Bitbucket
- **包注册表**：npm, PyPI, crates.io, Maven
- **研究来源**：arXiv, PubMed
- **论坛**：Stack Overflow, Reddit
- **文档站点**：官方文档、技术博客

```bash
# 搜索 npm 包信息
!omp search "npm package react 最新版本 2026"

# 搜索 GitHub 仓库
!omp search "github repository fastapi vs django rest framework"
```

## 注意事项

1. **API 密钥**：确保配置了搜索提供商的 API 密钥
2. **搜索成本**：每次搜索会消耗 API 配额
3. **结果准确性**：AI 搜索结果需要人工验证
4. **上下文限制**：长搜索结果可能被截断
5. **网络访问**：确保运行环境可以访问外部网络

## 快捷参考

```bash
# 快速搜索
!omp search "搜索内容"

# 详细分析
!omp -p --tools "web_search,fetch" "搜索内容并详细分析"

# 代码搜索
!omp -p --tools "code_search" "搜索代码示例"

# 技术调研
!omp -p --tools "web_search,fetch,code_search" "调研主题"
```
