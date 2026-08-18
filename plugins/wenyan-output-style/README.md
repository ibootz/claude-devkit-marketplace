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

**二、上游只有 1 行档位定义 + 2 个例句，这里补齐成可执行规则集。** 上游 `wenyan-ultra` 的全部定义是「Extreme abbreviation while keeping classical Chinese feel」，落到实操没有判准。本插件补了 8 条压缩法（省主语、去系词、单字动词、虚词白名单……）、5 条禁忌（禁繁体、禁日韩、禁自指、**禁伪古**、**禁生造名词**）、原样不动清单、降级条款、产出物边界。

其中**禁伪古**、**禁生造名词**与**产出物边界**是上游没有的：**禁伪古**防「回调 → 反召之术」这类为古而古的术语替换；**禁生造名词**规定名词只能取自权威来源——代码标识符（类名/方法名/字段名/枚举值/常量/路由）、前端页面上的可见文案、需求文档与设计产物、测试用例名与断言文案、数据库表名列名与字典值、API 接口路径与参数名与错误码文案、日志报错原文、用户自己的说法这 8 类，同一概念多处叫法不一致时按场景分——对人描述用页面或文档的叫法，指代实现用代码标识符原文，不挑赢家、不折中出第四个名字；后者（产出物边界）划死「会落盘或发出去的用白话，只在终端里给用户看的用文言」，避免文言污染 commit message、md 文档和子代理 prompt。

**三、触发方式拉平成纯注入。** 上游靠 `/caveman wenyan-ultra` 在对话里切档，档位状态由 `caveman-mode-tracker.js` 跟踪。本仓改成 `/plugin` 单一开关，与其余风格插件同构。

## 两层注入（与 adhd / plain-talk 的唯一结构差异）

| 层 | 文件 | 内容 | 频率 |
|---|---|---|---|
| `SessionStart`（`matcher: "*"`） | `hooks/session-start.sh` | 规则全文 + 本仓补充条款 | 每会话一次，compact 后自动重注 |
| `UserPromptSubmit` | `hooks/user-prompt-submit.sh` | 一行短锚，实测 169 字符 | 每轮 |

`adhd-output-style` 与 `plain-talk-output-style` 都是纯 `SessionStart`，本插件多一层每轮短锚。原因：文言与模型默认语体（现代白话）正面对抗，属于「对抗 system prompt 的段落」，只放 SessionStart 会在长对话里衰减漂回白话。caveman 上游同样是两层设计。

代价是每轮多实测 169 字符。往短锚里加内容前先问「不加会不会漂」——不会漂的写进 `style/wenyan-ultra-rules.md`，不要往每轮堆。

## 文件职责

| 文件 | 内容 | 能不能改 |
|---|---|---|
| `style/wenyan-ultra-rules.md` | 压缩法、禁忌、原样清单、例句、降级、产出物边界 | 调整风格行为改这里 |
| `style/project-overrides.md` | 与 `working-discipline` 的接缝：四要素、AskUserQuestion 白话、md 受众判定声明、并存说明 | 调整与本仓纪律的关系改这里 |
| `hooks/session-start.sh` | 拼上面两份 + 常驻声明，输出 `additionalContext` | 改拼接逻辑 |
| `hooks/user-prompt-submit.sh` | 每轮一行短锚 | 慎改，每轮成本 |

SessionStart 注入实测 **2785 字符**，每轮短锚实测 **169 字符**，均远低于 hook 输出上限
（10000 字符）。measured 方式：`echo '{"hook_event_name":"SessionStart"}' | bash
hooks/session-start.sh` 与 `echo '{"hook_event_name":"UserPromptSubmit"}' | bash
hooks/user-prompt-submit.sh`，各取输出 JSON 的 `hookSpecificOutput.additionalContext`
字段用 Python `len()` 计数（字符不是字节）。此前本节写的「2912 / 102」已过期失真，
本次核对时一并更正——过期数字与本次实测（改写前 3837 / 169）都对不上，说明这处记述
早已漂移，不是本轮改写才产生的偏差。

## 2026-08-05 压缩改写

`style/wenyan-ultra-rules.md`、`style/project-overrides.md`、`hooks/session-start.sh`
的 `HEADER` 三处逐句压缩，SessionStart 注入总长从 3837 字符降到 2785 字符，未删除任何
一条规则的信息——8 条压缩法、5 条禁忌（含禁生造名词的 8 类权威来源）、原样不动清单、
降级条款、产出物边界、四要素承接、AskUserQuestion 白话要求全部保留，仅收紧措辞与举例
数量（例句从 4 组减到 3 组，各禁忌条目的示例词从 2-3 个减到 1 个）。

**移出一条历史事故记录，非删除**：`wenyan-ultra-rules.md` 原「与 skill 输出模板并存」节
末尾有一段 2026-08-03 会话 `8477c246` 的实测漂移记录（AI 满足模板骨架却把骨架内叙述文字
一并写成白话）。这条记录属于「出事才查」的历史复盘，不是每次判断都要用的可执行规则，
按压缩口径挪到这里而非留在每会话都会重新读一遍的注入正文里：2026-08-03 会话
`8477c246` 首轮走 `/sdlc:resume`，AI 满足了模板骨架，却把骨架内的全部叙述一并写成现代
白话长句——教训是「模板只要求结构，语体是它自己漏掉的」，命中该节时不要连语体一起
退回白话。

## 与 working-discipline 的接缝

**拍板四要素不豁免。** 起源、现状与期望之差、影响范围、带行号的现场证据——四条约束的是**信息**，文言约束的是**形状**。压缩不得丢任何一条，不适用就显式写「无」。`project-overrides.md` 给了四要素的文言版形状（每条一句 + 证据代码块贴在论断正下方）。

**AskUserQuestion 四处用白话。** `question` / `header` / `label` / `description` 会渲染到 Human 手机上，只扫一眼，文言会让人误判。对话正文仍用文言。

**「本次 md 受众判定」声明句照写。** 判定词原样，理由部分可文言。「禁自指」不覆盖 harness 要求的声明。

## 1.6.0：自适应结构与 TUI 排版优化

补齐自适应结构次序（状态行 → 已定结论 → 待拍板事项 → 改动清单/证据 → 下一步）与 TUI 排版规范：
- **改动文件清单按需输出**：仅当本轮实际修改/写文件时列出清单，纯探查、只读、问答轮次不输出文件清单。
- **禁正文重复粘贴 diff**：已配合 `/tui fullscreen` 与 `/focus` 消除 diff 噪声，正文仅留可点击链接 + 简要说明，查看细节通过链接跳 VS Code 或输入 `/diff` 查看。
- **视觉层级**：分级标题、`---` 分隔线、`> **注意**` 引用块加强关键信息识别。

## 1.5.0：禁生造名词补注释通道

八类权威来源默认标识符本身就是可读的名字，真实代码里大量标识符不是（`tech_level`、拼音缩写、纯编号列）。1.5.0 在这一条里补了四条注释通道——entity 类字段注释、数据库表/列注释、i18n 文案与其 key 注释、代码行内注释与 javadoc，并写死它们是八类的**取值通道**而非第九类来源：注释只把八类里读不出的名字翻译出来，不是独立的命名权威。

同批改的还有 `working-discipline` 3.27.0 的 3.1 与 `plain-talk-output-style` 1.5.0 的第 5 条——同一条规则的三份表达，改一处必须改三处。

## 维护约定

- 注入走 `additionalContext`，纯注入零拦截，不受 `.claude/rules/project/hook-restraint.md` 的判据要求约束（见该文件「适用边界」节）。
- 子代理不受本插件影响（SessionStart 注入不进子代理，`UserPromptSubmit` 同样不进），它们仍从 `working-discipline` 的 SubagentStart 注入拿到表达约束。派子代理的 prompt 本身也不要用文言。
- 版本登记三处：本目录 `plugin.json` + 仓库两份 marketplace 清单，改完跑 `node scripts/check-versions.js`。
