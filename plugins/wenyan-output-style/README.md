# wenyan-output-style

文言极简输出风格：以文言语法压缩对话回复，**字形一律简体**；代码、命令、报错、行号原样不动；安全告警与不可逆操作确认逐段退回白话；落盘产出物（代码、commit、md、子代理 prompt）不用文言。

取自 [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) 插件 `skills/caveman/SKILL.md` 的 `wenyan-ultra` 档位，改写而非复刻——见下方「与上游的三点差异」。

## 怎么切换风格

与本仓其他风格插件同构，切换 = `/plugin` 里启停：

| 想要的风格 | 操作 |
|---|---|
| 文言极简 | 开 `wenyan-output-style`，关其他风格插件 |
| ADHD 友好 | 开 `adhd-output-style` |
| 说人话（干练） | 开 `plain-talk-output-style` |
| 教学讲解 | 开 `explanatory-output-style@claude-plugins-official` |
| 默认 | 全关 |

`insight-addon` 是**附加件不是风格**，可以和上面任意一个同时开。

同时开多个**风格**插件不会报错，但两段风格指令会互相打架——一次只开一个。改动后新会话生效。

**与 caveman 插件的关系**：`caveman@caveman` 自己也注入风格规则，`/caveman wenyan-ultra` 是本插件的出处。两者同开会有两套指令并行，建议只留一个。区别是开关位置——caveman 靠对话里说 `/caveman <档位>`，本插件靠 `/plugin` 常驻。

## 效果示例

| 问题 | 输出 |
|---|---|
| React 组件为何频繁重绘？ | 新参照则重绘。`useMemo` 包之。 |
| 解释数据库连接池。 | 池蓄连，免逐请新开，省握手。 |
| 这个 hook 为什么没触发？ | `matcher` 缺 `*`，故 compact 后不重注。改 `plugins/x/.claude-plugin/plugin.json:11`。 |

不可逆操作不套文言：

> **警告**：`DROP TABLE users` 会永久删除表内全部行，无法撤销。先确认备份存在再执行。

## 与上游的三点差异

**一、繁体改简体。** 上游 wenyan 例句全是繁体（`新參照則重繪。useMemo 包之。`），与本仓 `working-discipline` 3.5「禁止繁体中文」正面冲突。本插件保留文言语法与虚词，字形逐句改简，并把「禁繁体」写成硬约束——遇到繁体素材照样输出简体。

**二、上游只有 1 行档位定义 + 2 个例句，这里补齐成可执行规则集。** 上游 `wenyan-ultra` 的全部定义是「Extreme abbreviation while keeping classical Chinese feel」，落到实操没有判准。本插件补了 8 条压缩法（省主语、去系词、单字动词、虚词白名单……）、4 条禁忌（禁繁体、禁日韩、禁自指、**禁伪古**）、原样不动清单、降级条款、产出物边界。

其中**禁伪古**与**产出物边界**是上游没有的：前者防「回调 → 反召之术」这类为古而古的术语替换；后者划死「会落盘或发出去的用白话，只在终端里给用户看的用文言」，避免文言污染 commit message、md 文档和子代理 prompt。

**三、触发方式拉平成纯注入。** 上游靠 `/caveman wenyan-ultra` 在对话里切档，档位状态由 `caveman-mode-tracker.js` 跟踪。本仓改成 `/plugin` 单一开关，与其余风格插件同构。

## 两层注入（与 adhd / plain-talk 的唯一结构差异）

| 层 | 文件 | 内容 | 频率 |
|---|---|---|---|
| `SessionStart`（`matcher: "*"`） | `hooks/session-start.sh` | 规则全文 + 本仓补充条款 | 每会话一次，compact 后自动重注 |
| `UserPromptSubmit` | `hooks/user-prompt-submit.sh` | 一行短锚，约 110 字符 | 每轮 |

`adhd-output-style` 与 `plain-talk-output-style` 都是纯 `SessionStart`，本插件多一层每轮短锚。原因：文言与模型默认语体（现代白话）正面对抗，属于「对抗 system prompt 的段落」，只放 SessionStart 会在长对话里衰减漂回白话。caveman 上游同样是两层设计。

代价是每轮多约 110 字符。往短锚里加内容前先问「不加会不会漂」——不会漂的写进 `style/wenyan-ultra-rules.md`，不要往每轮堆。

## 文件职责

| 文件 | 内容 | 能不能改 |
|---|---|---|
| `style/wenyan-ultra-rules.md` | 压缩法、禁忌、原样清单、例句、降级、产出物边界 | 调整风格行为改这里 |
| `style/project-overrides.md` | 与 `working-discipline` 的接缝：四要素、AskUserQuestion 白话、md 受众判定声明、并存说明 | 调整与本仓纪律的关系改这里 |
| `hooks/session-start.sh` | 拼上面两份 + 常驻声明，输出 `additionalContext` | 改拼接逻辑 |
| `hooks/user-prompt-submit.sh` | 每轮一行短锚 | 慎改，每轮成本 |

SessionStart 注入实测 2912 字符，每轮短锚 102 字符，均远低于 hook 输出上限（10000 字符）。

## 与 working-discipline 的接缝

**拍板四要素不豁免。** 起源、现状与期望之差、影响范围、带行号的现场证据——四条约束的是**信息**，文言约束的是**形状**。压缩不得丢任何一条，不适用就显式写「无」。`project-overrides.md` 给了四要素的文言版形状（每条一句 + 证据代码块贴在论断正下方）。

**AskUserQuestion 四处用白话。** `question` / `header` / `label` / `description` 会渲染到 Human 手机上，只扫一眼，文言会让人误判。对话正文仍用文言。

**「本次 md 受众判定」声明句照写。** 判定词原样，理由部分可文言。「禁自指」不覆盖 harness 要求的声明。

## 维护约定

- 注入走 `additionalContext`，纯注入零拦截，不受 `.claude/rules/hook-restraint.md` 的判据要求约束（见该文件「适用边界」节）。
- 子代理不受本插件影响（SessionStart 注入不进子代理，`UserPromptSubmit` 同样不进），它们仍从 `working-discipline` 的 SubagentStart 注入拿到表达约束。派子代理的 prompt 本身也不要用文言。
- 版本登记三处：本目录 `plugin.json` + 仓库两份 marketplace 清单，改完跑 `node scripts/check-versions.js`。
