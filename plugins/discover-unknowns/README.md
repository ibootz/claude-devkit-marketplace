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

## 九个 Skill（模式 skill 均可 `/斜杠` 直接调用）

| 阶段 | Skill | 作用 |
|------|------|------|
| 统领 | `discover-unknowns` | 心智模型 + 编排逻辑：何时主动进入哪个模式 |
| 前 | `/blind-spot-pass` | 盲点扫描：挖未知的未知并讲解 |
| 前 | `/brainstorm` | 头脑风暴与原型：多方向 + 假数据原型 ※ |
| 前 | `/interview` | 访谈：一次一问，优先会改架构的问题 ※ |
| 前 | `/reference` | 参考：用源代码复刻语义（优于截图） |
| 前 | `/impl-plan` | 实现计划：易变决策置顶、机械重构沉底 |
| 中 | `/impl-notes` | 实现笔记：记录偏离，选保守方案继续 |
| 后 | `/pitch` | 提案讲解：打包成可争取批准的文档 |
| 后 | `/quiz` | 测验：通过才 merge |

※ **superpowers 集成**：`brainstorm` 与 `interview` 会先检查可用技能列表中是否存在 `superpowers:brainstorming`（[obra/superpowers](https://github.com/obra/superpowers)）。已安装则优先委派该 skill（访谈场景叠加"优先问会改架构的问题"约束）；未安装则使用本插件内置指令，功能不受影响。

## 安装

- **Claude Code**：安装本插件后 9 个 skill 自动可用，模式 skill 支持 `/名称` 直接调用，也会按语义自动触发。
- **Codex CLI**：`node scripts/install-codex.js --plugins=discover-unknowns`，9 个 skill 全部复制到 `~/.agents/skills/`（skill 化后 Codex 侧与 Claude 侧能力一致）。

## 一句话用法

> 开始下一个项目时，先请 Claude 帮你找出你的未知。
