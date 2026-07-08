# discover-unknowns — 发现你的未知

一套与 Claude 协作的**任务生命周期方法论**：把提示词/上下文当"地图"、真实代码库/约束当"疆域"，两者的差距就是**未知（unknowns）**；用八个实践模式在**实现前 / 中 / 后**系统性地挖掘并澄清未知，从而减少返工与踩坑。

源自 Anthropic 官方博客 [*A field guide to Claude Fable 5: Finding your unknowns*](https://claude.com/blog/a-field-guide-to-claude-fable-finding-your-unknowns)（Thariq Shihipar）。

## 四类未知

| 类型 | 含义 | 对应动作 |
|------|------|----------|
| 已知的已知 | 我清楚要什么 | 直接写清楚 |
| 已知的未知 | 我知道自己没想清的点 | 访谈 / 头脑风暴 |
| 未知的已知 | 显而易见到不会写、但看到就认得 | 原型 / 参考 |
| 未知的未知 | 完全没考虑过 | 盲点扫描 |

## 八个模式（= 八个 slash 命令）

| 阶段 | 命令 | 作用 |
|------|------|------|
| 前 | `/blind-spot-pass` | 盲点扫描：挖未知的未知并讲解 |
| 前 | `/brainstorm` | 头脑风暴与原型：多方向 + 假数据原型 |
| 前 | `/interview` | 访谈：一次一问，优先会改架构的问题 |
| 前 | `/reference` | 参考：用源代码复刻语义（优于截图） |
| 前 | `/impl-plan` | 实现计划：易变决策置顶、机械重构沉底 |
| 中 | `/impl-notes` | 实现笔记：记录偏离，选保守方案继续 |
| 后 | `/pitch` | 提案讲解：打包成可争取批准的文档 |
| 后 | `/quiz` | 测验：通过才 merge |

## 组成

- **SKILL `discover-unknowns`**：统领方法论与编排逻辑（何时该主动进入哪个模式），内嵌全部八个模式与原文示例 prompt。Claude 会在陌生/含糊/大颗粒度任务上主动应用。
- **8 个 slash 命令**（Claude Code）：每个模式的快捷入口，接受任务上下文作为参数。

## 安装与平台差异

- **Claude Code**：安装本插件后，SKILL 与 8 个 slash 命令均自动可用。
- **Codex CLI**：本 marketplace 的 codex 安装器（`scripts/install-codex.js`）支持 skills，会把 `skills/discover-unknowns` 复制到 `~/.agents/skills/`。方法论与八个模式**通过 SKILL 提供**（模式内容已内嵌在 SKILL 中）；由于安装器暂无 slash 命令通道，Codex 侧**不提供独立的 8 个 `/命令`**，直接按 SKILL 描述执行即可。

## 一句话用法

> 开始下一个项目时，先请 Claude 帮你找出你的未知。
