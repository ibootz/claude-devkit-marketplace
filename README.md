# Claude DevKit Marketplace

Claude Code / Codex 插件市场，提供精选的开发工具集与生产力插件。

## 概述

本市场包含 10 个插件，覆盖核心开发、规范驱动工作流、技能生态、多模型协作、AI 工作纪律、协作方法论等场景。

原 `devkit-git`、`devkit-dev`、`devkit-issue` 已从市场移除，不再作为独立插件提供。

## 可用插件

### 1. devkit-core

核心开发工具集，覆盖代码库分析、依赖排查与架构辅助。

**Skills**:
- `deps-investigator` - 依赖源码读取
- `init-architect` - 架构初始化，生成 CLAUDE.md
- `key-module-analysis` - 关键模块分析
- `orphan-process-cleaner` - 孤儿进程清理

### 2. devkit-spec

规范驱动开发工具集，支持完整的 Spec 工作流。

**Skills**:
- `spec-analyze` - 需求分析并生成 spec
- `spec-bugfix` - 缺陷修复流程
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

### 5. content-research-writer

内容研究写作助手，协助研究、写作和内容创作。

- 协作大纲与研究协助
- 钩子改进与分节反馈
- 声音保留与引用管理
- 支持 Web 搜索与内容获取
- 多种写作工作流程（博客、新闻通讯、教程等）

### 6. matt-pocock-skills

Matt Pocock 工程技能集，包含调试诊断、TDD、架构改进等实战工具。

**Skills**:
- `diagnose` - 系统化诊断流程
- `tdd` - 测试驱动开发
- `improve-codebase-architecture` - 架构改进
- `triage` - 问题分类与处理
- `to-issues` - 生成任务清单
- `to-prd` - 生成产品需求文档
- `zoom-out` - 高层视角分析
- `grill-me` - 方案压力测试
- `grill-with-docs` - 结合文档的方案验证
- `write-a-skill` - 技能创建指南
- `caveman` - 精简沟通模式
- 更多技能见插件目录

### 7. omp (Oh My Pi)

CLI 工具集成，在 Claude Code/Codex 中调用 omp 实现编码、审查、搜索等任务。

**Skills**:
- `using-omp` - OMP 基础使用
- `omp-search` - 代码搜索
- `omp-review` - 代码审查
- `omp-subagent` - 子代理任务

### 8. find-skills

帮助发现和安装 agent 技能 - 基于 skills.sh 生态系统，使用 npx skills CLI 搜索和安装技能。

- 搜索技能库
- 安装指定技能
- 列出已安装技能
- 基于 vercel-labs/skills 生态

### 9. working-discipline

AI 工作纪律每轮注入，一个 `UserPromptSubmit` hook，零 skill、零命令，适合作为全局基线长期开启。

- 上下文纪律：精确读取、子代理优先、bash 输出限流
- 子代理协作：并发上限 4、共享骨架文件、结构化回执
- 表达约束：不自造术语、关键对象点名、引用自带信息、四要素待确认、行号引用
- 思维模式：举一反三 / 整体 / 第一性 / 逆向 / 自查自纠 / 读者视角，按需触发
- Agent 工具派发：subagent_type × model 路由表、显式 model 指定、成本意识

### 10. discover-unknowns（发现你的未知）

与 Claude 协作挖掘未知的方法论：把提示词/上下文当"地图"、真实代码库/约束当"疆域"，两者差距即"未知"，动手前暴露未知、合并前确认理解。源自 Anthropic 官方博客 *A field guide to Claude Fable 5: Finding your unknowns*。

**组成**（3 个 Skill + 1 个 Hook，按"探索/收敛/合并"三个决策时刻拆分）：
- `discover-unknowns` - 统领：心智模型 + 路由，内嵌盲点扫描与参考两个手法
- `/brainstorm` - 头脑风暴与访谈：发散（多方向假数据原型）+ 收敛（一次一问，优先会改架构的问题）※
- `/quiz` - 测验：报告 + 必须通过的测验，通过才 merge
- `unknowns-radar` hook - UserPromptSubmit 每轮注入 4 条路标级提醒（`DISCOVER_UNKNOWNS_RADAR=off` 可关闭）

> ※ `brainstorm` 在本地已安装 superpowers 插件时优先委派 `superpowers:brainstorming`，未安装时用内置指令。实施规划与执行不属于本插件，交给 devkit-spec。Claude Code 与 Codex 两侧能力一致。

## 安装

### Claude Code

#### 添加此市场

```bash
/plugin marketplace add ibootz/claude-devkit-marketplace
```

#### 安装插件

添加市场后，可以安装市场中的任意插件：

```bash
# 核心开发工具集
/plugin install devkit-core@claude-devkit-marketplace

# 规范驱动开发
/plugin install devkit-spec@claude-devkit-marketplace

# 技能自修复
/plugin install heal@claude-devkit-marketplace

# 提示词工程
/plugin install prompt-engineering@claude-devkit-marketplace

# 内容研究写作
/plugin install content-research-writer@claude-devkit-marketplace

# Matt Pocock 工程技能集
/plugin install matt-pocock-skills@claude-devkit-marketplace

# OMP 工具集成
/plugin install omp@claude-devkit-marketplace

# 技能发现与安装
/plugin install find-skills@claude-devkit-marketplace

# AI 工作纪律（推荐全局开启）
/plugin install working-discipline@claude-devkit-marketplace

# 发现你的未知（协作方法论）
/plugin install discover-unknowns@claude-devkit-marketplace
```

### Codex CLI

#### 添加此市场

```bash
codex plugin marketplace add ibootz/claude-devkit-marketplace
```

#### 通过插件目录安装

在 Codex CLI 中打开插件目录，浏览并安装：

```
codex                          # 启动 Codex CLI
/plugins                       # 打开插件目录
```

在插件目录中：
1. 切换到 "claude-devkit-marketplace" 市场标签
2. 浏览或搜索插件
3. 选择插件并点击安装

#### 通过脚本安装（推荐 — 含 hooks/agents 自动注入）

Codex CLI 通过插件目录安装时，skills 能正常加载，但 hooks 和 agents 不会自动注入到活跃配置。
本市场提供安装脚本解决这个问题，同时安装 skills、hooks 和 agents 到 Codex 的目标路径。

**前提条件**：Node.js >= 14

```bash
# 进入市场目录
cd path/to/claude-devkit-marketplace

# 安装所有插件到当前项目（项目级）
node scripts/install-codex.js --all

# 安装所有插件到用户目录（用户级，全局生效）
node scripts/install-codex.js --all --scope=user

# 交互式选择要安装的插件
node scripts/install-codex.js

# 只安装指定插件
node scripts/install-codex.js --plugins=devkit-core,omp

# 预览模式（不实际修改文件）
node scripts/install-codex.js --all --dry-run
```

**安装范围**：
- 项目级（默认）：写入当前项目目录的 `.codex/`、`.agents/skills/`
- 用户级（`--scope=user`）：写入用户主目录的 `~/.codex/`、`~/.agents/skills/`

**安装内容**：
- **Skills**：所有 8 个插件的技能目录
- **Hooks**：devkit-core 的 PreToolUse 守卫钩子、omp 的 SessionStart/UserPromptSubmit 钩子、working-discipline 与 discover-unknowns 的 UserPromptSubmit 注入钩子
- **Agents**：omp 的 3 个子代理（omp-explore、omp-plan、omp-task）

#### 卸载

```bash
# 卸载所有已安装的插件
node scripts/uninstall-codex.js --all

# 卸载指定插件
node scripts/uninstall-codex.js --plugins=omp

# 预览卸载内容
node scripts/uninstall-codex.js --all --dry-run
```

## 关键 Skills 快速参考

- `/init-architect` - 分析代码库并生成 `CLAUDE.md`
- `/key-module-analysis` - 梳理关键模块边界、依赖与风险
- `/spec-analyze` - 需求分析并生成 `spec.md`
- `/spec-tasks` - 将 `spec.md` 拆解为任务清单
- `/spec-impl` - 按任务清单实施改动
- `/spec-review` - 审查规范或实现一致性
- `/diagnose` - 系统化诊断问题
- `/tdd` - 测试驱动开发

详细参数与流程见各插件目录下的 `SKILL.md`。

## 市场结构

```
claude-devkit-marketplace/
├── .claude-plugin/
│   └── marketplace.json       # 市场配置文件
├── plugins/
│   ├── devkit-core/
│   ├── devkit-spec/
│   ├── heal/
│   ├── prompt-engineering/
│   ├── content-research-writer/
│   ├── matt-pocock-skills/
│   ├── omp/
│   ├── find-skills/
│   ├── working-discipline/
│   └── discover-unknowns/
├── README.md
└── AGENTS.md
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

# 测试其他插件
claude --plugin-dir ./plugins/<plugin-name>
```

## 要求

- Claude Code CLI
- Git（建议安装，用于仓库协作、差异审查与可选的 worktree 隔离修复）

## 许可证

MIT

## 作者

zhangq
