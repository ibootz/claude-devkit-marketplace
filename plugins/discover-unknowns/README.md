# discover-unknowns — 发现你的未知

一套与 Claude 协作**挖掘未知**的方法论：把提示词/上下文当"地图"、真实代码库/约束当"疆域"，两者的差距就是**未知（unknowns）**；动手前用盲点扫描/头脑风暴/访谈/参考暴露未知，合并前用测验确认理解，从而减少返工与踩坑。

源自 Anthropic 官方博客 [*A field guide to Claude Fable 5: Finding your unknowns*](https://claude.com/blog/a-field-guide-to-claude-fable-finding-your-unknowns)（Thariq Shihipar）。

## 四类未知

| 类型 | 含义 | 对应手法 |
|------|------|----------|
| 已知的已知 | 我清楚要什么 | 直接写清楚 |
| 已知的未知 | 我知道自己没想清的点 | 访谈 / 头脑风暴（`/brainstorm`） |
| 未知的已知 | 显而易见到不会写、但看到就认得 | 原型（`/brainstorm`）/ 参考（统领内嵌） |
| 未知的未知 | 完全没考虑过 | 盲点扫描（统领内嵌） |

## 组成：3 个 Skill + 1 个 Hook

拆分粒度对齐**用户真实会停下来的决策时刻**（探索/收敛/合并），而不是原文的章节结构：

| 组件 | 时刻 | 作用 |
|------|------|------|
| `discover-unknowns` | 任务开局含糊/陌生 | 统领：心智模型 + 路由；内嵌盲点扫描、参考两个手法 |
| `/brainstorm` | 需求模糊需探索或收敛 | 头脑风暴与访谈：发散（多方向假数据原型）+ 收敛（一次一问，优先会改架构的问题）※ |
| `/quiz` | 长会话后要合并 | 测验：报告 + 必须通过的测验，通过才 merge |
| `unknowns-radar` hook | 每轮注入 | UserPromptSubmit 注入 4 条路标级提醒（约 150 token）：模糊任务先挖未知、参考复刻语义、实现偏离选保守并上报、合并前建议 /quiz。设 `DISCOVER_UNKNOWNS_RADAR=off` 可关闭 |

※ **superpowers 集成**：`brainstorm` 会先检查可用技能列表中是否存在 `superpowers:brainstorming`（[obra/superpowers](https://github.com/obra/superpowers)，其 brainstorming 本身融合了方案探索与一问一答）。已安装则优先委派并叠加本方法论约束（假数据多方向原型、优先问会改架构的问题）；未安装则使用内置指令，功能不受影响。

> **边界**：未知收敛后的实施规划与执行（实现计划、任务拆解、按计划编码）不属于本插件，交给规范驱动工作流（如本市场的 devkit-spec）。

## 安装

- **Claude Code**：安装本插件后 3 个 skill 自动可用（支持 `/名称` 直调与语义触发），hook 随插件自动注册。
- **Codex CLI**：`node scripts/install-codex.js --plugins=discover-unknowns`，skills 复制到 `~/.agents/skills/`，hook 合并进 `~/.codex/hooks.json`，两侧能力一致。

## 一句话用法

> 开始下一个项目时，先请 Claude 帮你找出你的未知。
