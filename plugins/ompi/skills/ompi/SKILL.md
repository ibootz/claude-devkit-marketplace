---
name: ompi
description: >
  触发词：调用 ompi、使用 ompi CLI、ompi 命令、ompi 编码、ompi 代码审查、ompi 提交。
  将 ompi 作为执行代理（Worker），你作为指挥者（Orchestrator）只负责理解需求、制定策略、审阅结果。
  所有读文件、写代码、搜索、分析等执行工作必须委托给 ompi。
---

# 在 Claude Code/Codex 中调用 ompi

**你 = Orchestrator**：理解需求、拆解任务、制定策略、审阅结果、做决策。
**ompi = Worker**：执行所有实际操作——读文件、搜索、编辑、运行命令、抓取网页等。

**核心原则：不要自己操作文件或执行命令，让 ompi 去做。**

## 协作流程

```
用户需求 → 你拆解任务 → 调用 ompi 执行 → 审阅结果 → 通过/修正/补充
```

**你的职责**：需求澄清、策略制定、撰写 ompi 指令、审阅结果、迭代决策。
**禁止事项**：❌ 自己 read/write/edit/grep/bash/web_search，✅ 全部通过 `ompi -p` 委托。

## 调用范式

```bash
ompi -p --tools "<工具集>" "
【目标】...
【上下文】...
【约束】...
【期望输出】...
"
```

**工具集选择**：

| 场景          | 工具集                                    | 说明      |
| ------------- | ----------------------------------------- | --------- |
| 代码审查      | `read,grep,lsp,bash`                      | 只读分析  |
| 代码编写/重构 | `read,write,edit,bash,grep,lsp`           | 需改文件  |
| 技术调研      | `web_search,fetch,read`                   | 查文档    |
| 项目探索      | `read,find,grep`                          | 了解结构  |
| 复杂任务      | `read,write,edit,bash,grep,find,lsp,task` | 含子代理  |
| Git 操作      | `bash,git-overview,git-file-diff`         | 提交/diff |
| 纯对话        | `--no-tools`                              | 不碰文件  |

## 典型场景

**代码审查**：

```bash
ompi -p --tools "read,grep,bash,lsp" "
【目标】审查未提交变更
【约束】不修改文件
【期望输出】按 P0/P1/P2/P3 分级列出问题，含文件和行号
"
```

**代码重构**：

```bash
# 步骤1：探索（ompi 执行）
omp -p --tools "read,find,grep" "【目标】分析 src/services/auth.ts【约束】不改文件【期望输出】函数列表、依赖、代码异味"

# 步骤2：你决策重构方案

# 步骤3：执行（ompi 执行）
ompi -p --tools "read,write,edit,bash,grep,lsp" "
【目标】重构 src/services/auth.ts
【上下文】提取重复逻辑到 utils，添加错误处理
【约束】保持 API 签名不变；不引入新依赖
【期望输出】变更文件列表和摘要
"
```

**Bug 修复**：

```bash
ompi -p --tools "read,grep,bash,lsp,edit" "
【目标】诊断并修复 <问题描述>
【上下文】<相关目录/文件>
【期望输出】根因分析、修复方案、diff 摘要、测试点
"
```

**生成 Git 提交**：

```bash
ompi -p --tools "bash,git-overview,git-file-diff" "
【目标】为暂存变更生成 conventional commit 消息
【约束】遵循项目规范；暂存区为空则报错
【期望输出】完整的 commit message
"
```

## 复杂任务管理

拆为 3-5 个独立子任务，逐一派发，中间验收：

1. 你拆解任务 → 2. 派发子任务给 ompi → 3. 验收结果 → 4. 继续下一子任务

## 结果审阅

检查：完整性（是否回答所有要求）、准确性（逻辑/路径/引用）、副作用（是否误改文件）、遗漏（边界情况）。

不满意时给 ompi 发修正指令，不要自己改。

## 注意事项

- ompi 上下文独立，prompt 需自带足够上下文
- 通过 `--tools` 遵循最小权限原则
- 复杂任务用 `ompi -p --model "<强模型>"`
- ompi 失败时分析错误原因，调整指令重试
