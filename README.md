# Claude DevKit Marketplace

Claude DevKit 插件市场，提供精简后的 Claude Code 插件集合。

## 概述

当前市场聚焦 5 个保留插件：

- `devkit-core`：核心开发工具集，聚焦分析、排障、多模型协作与辅助能力，并以统一的 `bugfix` skill 吸收原 `devkit-issue`
- `devkit-spec`：规范驱动开发工作流
- `heal`：技能自修复工具
- `prompt-engineering`：提示词工程插件
- `content-research-writer`：内容研究与写作助手

原 `devkit-git`、`devkit-dev`、`devkit-issue` 已从市场移除，不再作为独立插件提供。

## 可用插件

### 1. devkit-core

核心开发工具集，覆盖代码库分析、依赖排查、缺陷修复、多模型协作与辅助工具。

**包含 Skills (7 个)**:
- `deps-investigator` - 依赖源码读取
- `bugfix` - 统一的缺陷诊断与修复流程
- `init-architect` - 架构初始化
- `key-module-analysis` - 关键模块分析
- `orphan-process-cleaner` - 孤儿进程清理
- `using-codex` - 使用 Codex 模型
- `using-gemini` - 使用 Gemini 模型

### 2. devkit-spec

规范驱动开发工具集，支持完整的 Spec 工作流。

**包含 Skills (4 个)**:
- `spec-analyze` - 需求分析并生成 spec
- `spec-tasks` - 将 spec 拆解为任务清单
- `spec-impl` - 按任务清单实施
- `spec-review` - 审查 spec 与实现一致性

### 3. heal

技能修复工具，在技能执行过程中发现问题时更新 SKILL.md 及相关文件。

- 自动检测正在运行的技能
- 反思出错原因并提出修复方案
- 审批工作流，获得用户批准后应用更改
- 支持可选的 Git 提交

### 4. prompt-engineering

提示词工程专家，优化 LLM 提示词、设计命令/钩子/技能。

- Few-Shot Learning（少样本学习）
- Chain-of-Thought（思维链推理）
- 提示词优化与模板系统
- 系统提示设计
- 基于 Anthropic 官方最佳实践
- 说服原则应用

### 5. content-research-writer

内容研究写作助手，协助研究、写作和内容创作。

- 协作大纲与研究协助
- 钩子改进与分节反馈
- 声音保留与引用管理
- 支持 Web 搜索与内容获取
- 多种写作工作流程（博客、新闻通讯、教程等）

## 安装

### 添加此市场

```bash
/plugin marketplace add ibootz/claude-devkit-marketplace
```

### 安装插件

添加市场后，可以安装市场中的任意插件：

```bash
# 安装核心工具集
/plugin install devkit-core@claude-devkit-marketplace

# 安装 Spec 工作流
/plugin install devkit-spec@claude-devkit-marketplace

# 安装技能修复工具
/plugin install heal@claude-devkit-marketplace

# 安装提示词工程插件
/plugin install prompt-engineering@claude-devkit-marketplace

# 安装内容研究写作助手
/plugin install content-research-writer@claude-devkit-marketplace
```

### Hooks（可选）

DevKit Pro 提供 `SessionStart` / `UserPromptSubmit` hooks，用于会话提示。

- 在 Claude Code 中执行 `/hooks` 应能看到这些 hooks；若未显示，建议重启 Claude Code 后重试。

## 详细功能

### Skills

#### deps-investigator
第三方依赖源码读取（Maven/Node 模块），用于定位依赖行为与版本差异。

#### bugfix
统一的缺陷诊断与修复流程，按需使用 worktree 隔离环境并补齐验证。

### 关键 Skills

- `/bugfix` - 统一的缺陷诊断、隔离修复与验证
- `/init-architect` - 分析代码库并生成 `CLAUDE.md`
- `/key-module-analysis` - 梳理关键模块边界、依赖与风险
- `/spec-analyze` - 需求分析并生成 `spec.md`
- `/spec-tasks` - 将 `spec.md` 拆解为任务清单
- `/spec-impl` - 按任务清单实施改动
- `/spec-review` - 审查规范或实现一致性

详细参数与流程见各插件目录下的 `SKILL.md`，其中 `devkit-core` 汇总说明见 `plugins/devkit-core/README.md`。

## 市场结构

```
claude-devkit-marketplace/
├── .claude-plugin/
│   └── marketplace.json       # 市场配置文件
├── plugins/
│   ├── devkit-core/           # 核心工具集
│   ├── devkit-spec/           # Spec 工作流
│   ├── heal/                  # 技能修复工具
│   ├── prompt-engineering/    # 提示词工程
│   └── content-research-writer/  # 内容研究写作
└── README.md
```

## 开发

### 添加新插件

1. 在 `plugins/` 目录下创建新的插件目录
2. 按照插件规范创建必要的配置文件
   - 对于普通插件：`.claude-plugin/plugin.json`、`skills/`、`commands/` 等
   - 对于 MCP 插件：`.mcp.json`（或 `.claude-plugin/plugin.json` + `.mcp.json`）
3. 在 `.claude-plugin/marketplace.json` 中添加插件条目

### 本地测试

```bash
# 测试核心插件
claude --plugin-dir ./plugins/devkit-core

# 测试 MCP 插件
claude --plugin-dir ./plugins/<plugin-name>
```

## 要求

- Claude Code CLI
- Git（建议安装，用于仓库协作、差异审查与可选的 worktree 隔离修复）

## 许可证

MIT

## 作者

zhangq
