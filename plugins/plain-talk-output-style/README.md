# plain-talk-output-style

说人话输出风格：一语中的、几句话讲明白、能表格不成段；不专业化、不掉书袋、不自造词。

## 怎么切换风格

原生 output style 功能已废弃，官方 `explanatory-output-style` 插件的实现方式就是「SessionStart 注入一段风格指令」。本插件同理。切换 = `/plugin` 里启停：

| 想要的风格 | 操作 |
|---|---|
| 说人话（干练） | 开 `plain-talk-output-style`，关其他风格插件 |
| 教学讲解（带 ★ Insight） | 开 `explanatory-output-style@claude-plugins-official`，关本插件 |
| 默认 | 两个都关 |

同时开多个风格插件不会报错，但两段风格指令会互相打架，效果不可预期——一次只开一个。改动后新会话生效（hook 在会话启动时加载）。

## 与 working-discipline 的分工（3.9.0 拆分）

风格与纪律分开管：

| 条款 | 归属 | 原因 |
|---|---|---|
| 术语与指代、引用自带信息、列表编号（原 3.1/3.2/3.6） | 本插件 | 行文风格，应随用户选的风格切换 |
| 拍板内容讲透（3.3）、求真（3.4）、简体中文（3.5） | working-discipline | 纪律与正确性，不能随风格切换丢失 |

注意本插件第 10 条明确让位：需要用户拍板的内容仍按 working-discipline 3.3 讲透前因后果，简短不适用于拍板材料。

子代理不受本插件影响（SessionStart 注入不进子代理），它们仍从 working-discipline 的 SubagentStart 注入拿到完整表达约束——子代理是产出 md 文档的主力，文档质量条款对它们保持全量。

## 维护约定

- 风格文本在 `hooks/session-start.sh` 的 `STYLE` 字符串里，改完直接生效于新会话，无需改版本外的其他文件。
- 注入走 `additionalContext`，纯注入零拦截，不受 hook 克制原则的判据要求约束（见仓库 `.claude/rules/hook-restraint.md` 的适用边界节）。
- 版本登记三处：本目录 `plugin.json` + 仓库两份 marketplace 清单，改版本跑 `node scripts/check-versions.js`。
