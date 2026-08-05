# plain-talk-output-style

说人话输出风格：一语中的、几句话讲明白、能表格不成段；不专业化、不掉书袋、不自造词（新词只用权威来源里已有的名称）。

## 怎么切换风格

原生 output style 功能已废弃，官方 `explanatory-output-style` 插件的实现方式就是「SessionStart 注入一段风格指令」。本插件同理。切换 = `/plugin` 里启停：

| 想要的风格 | 操作 |
|---|---|
| 说人话（干练） | 开 `plain-talk-output-style`，关其他风格插件 |
| ADHD 友好 | 开 `adhd-output-style`，关本插件 |
| 教学讲解（带 ★ Insight） | 开 `explanatory-output-style@claude-plugins-official`，关本插件 |
| 默认 | 全关 |

同时开多个风格插件不会报错，但两段风格指令会互相打架，效果不可预期——一次只开一个。改动后新会话生效（hook 在会话启动时加载）。

`insight-addon` 是**附加件不是风格**（只加一条「何时给 ★ Insight 框」的规则，不规定句子长短和段落形态），可以和本插件同时开着。

## 与 working-discipline 的分工（3.9.0 拆分 + 3.10.0 重构）

风格与纪律分开管，判据是「换一个读者，这条还成立吗」：

| 条款 | 归属 | 原因 |
|---|---|---|
| 术语与指代、引用自带信息、列表编号（原 3.1/3.2/3.6） | 本插件 | 行文风格，应随所选风格切换 |
| 拍板材料的四要素：起源 / 现状与期望的差距 / 影响范围 / 带行号的现场证据（3.3） | working-discipline | **信息**要求，任何读者都需要，风格无权豁免 |
| 这四要素用什么**形状**呈现 | 本插件第 9 条（完整段落） | **形态**要求，换个读者最优解就变 |
| 求真（3.4）、简体中文（3.5） | working-discipline | 纪律与正确性，不能随风格切换丢失 |

第三行是 3.10.0 新增的分界。此前 3.3 直接写着「核心内容必须用完整段落、禁止短语罗列」，这在引入 `adhd-output-style` 时撞车了——上游 ADHD 规则要求「列表封顶 5 条」。重构后纪律只管四要素齐不齐，形状由风格插件各自定义：本插件用完整段落，ADHD 插件用「推荐项在前 + 选项排序 + 每项一行代价」，信息量相同、形状不同。

本插件第 9 条完整承接了这件事：拍板材料四要素一条不少，且**详尽优先于简短**——第 1 条到第 3 条的简短要求在这里让位。

## 2026-08-05 压缩改写

风格正文（`hooks/session-start.sh` 的 `STYLE` 字符串）从 1003 字符压到 **717 字符**，压缩
手法是合并「不过于专业化」与「不掉书袋」为一条、收紧各条例句，未删除任何一条规则的
信息——四要素、8 类命名权威来源等清单原样保留。条款从 10 条降为 9 条，本文件里所有
「第 N 条」引用已同步更新。8 类命名权威来源的枚举措辞与 `wenyan-output-style` /
`adhd-output-style` 两份对齐一致（「类名/方法名/字段名/枚举值/常量/路由」「需求与设计
产物（PRD/spec/原型/view spec）」），三份此前各写各的，现在统一。measured 方式：
`echo '{"hook_event_name":"SessionStart"}' | bash hooks/session-start.sh`，取输出 JSON
的 `hookSpecificOutput.additionalContext` 字段用 Python `len()` 计数（字符不是字节）。

子代理不受本插件影响（SessionStart 注入不进子代理），它们仍从 working-discipline 的 SubagentStart 注入拿到完整表达约束——子代理是产出 md 文档的主力，文档质量条款对它们保持全量。

## 维护约定

- 风格文本在 `hooks/session-start.sh` 的 `STYLE` 字符串里，改完直接生效于新会话，无需改版本外的其他文件。
- 注入走 `additionalContext`，纯注入零拦截，不受 hook 克制原则的判据要求约束（见仓库 `.claude/rules/project/hook-restraint.md` 的适用边界节）。
- 版本登记三处：本目录 `plugin.json` + 仓库两份 marketplace 清单，改版本跑 `node scripts/check-versions.js`。
