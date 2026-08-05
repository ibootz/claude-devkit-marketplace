# insight-addon

教学洞察附加件：在真正做了技术判断的地方给一个 ★ Insight 框。

**它可以和任何输出风格插件同时开着。** 这是它与官方 `explanatory-output-style` 的唯一区别，也是它存在的理由。

## 为什么不直接用 explanatory-output-style

官方那个插件注入的是一整套风格，其中一句是 `When providing insights, you may exceed typical length constraints`——它同时授权了「给洞察」和「可以写长」。所以它跟 `plain-talk-output-style` 的「一语中的、简单问题一两句答完」直接对撞，两个开着会打架，只能二选一。

本插件把「给洞察」这一件事单独摘出来，不带任何长度授权、不规定用段落还是列表。于是：

| 组合 | 效果 |
|---|---|
| 只开 `insight-addon` | 默认风格 + 洞察框 |
| `plain-talk` + `insight-addon` | 说人话 + 洞察框（干练答案，技术判断处补一个框） |
| `adhd-output-style` + `insight-addon` | ADHD 风格 + 洞察框 |
| `explanatory-output-style` + 本插件 | **不要这么用**，两份洞察规则重复 |

## 什么时候会给洞察框

注入文本要求两条同时满足：本轮真的做了非平凡的技术判断，且其中有**这个代码库特有**的门道。纯问答、状态汇报、执行命令、调格式一律不给。

这条触发条件是本仓补充的。官方原文写的是 `before and after writing code, always provide brief educational explanations`——`always` 在问答类轮次里会塞出无意义的洞察框，所以这里收窄了。

## 与 working-discipline 的关系

不冲突。`working-discipline` 管的是纪律（拍板材料要含哪些信息要素、引用要带行号、求真、简体中文），本插件只加一种额外输出形态，不碰那些要求。

## 维护约定

- 规则文本在 `hooks/session-start.sh` 的 `STYLE` 字符串里，改完新会话生效。
- 注入走 `additionalContext`，纯注入零拦截，不受 `.claude/rules/project/hook-restraint.md` 的判据要求约束（见该文件「适用边界」节）。
- ★ Insight 的格式与「聚焦本代码库特有门道」两点取自官方 `explanatory-output-style`，出处见 `hooks/session-start.sh` 文件头注释。
- 版本登记三处：本目录 `plugin.json` + 仓库两份 marketplace 清单，改完跑 `node scripts/check-versions.js`。
