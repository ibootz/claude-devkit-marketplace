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
| 这个 hook 为什么没触发？ | `matcher` 缺 `*`，故 compact 后不重注。改 [plugin.json:11](file:///abs/path/plugins/x/.claude-plugin/plugin.json#11)。 |

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
| `SessionStart`（`matcher: "*"`） | `hooks/session-start.js` | 规则全文 + 本仓补充条款 | 每会话一次，compact 后自动重注 |
| `UserPromptSubmit` | `hooks/user-prompt-submit.js` | 一行短锚，上限 300 字符 | 每轮 |

`adhd-output-style` 与 `plain-talk-output-style` 都是纯 `SessionStart`，本插件多一层每轮短锚。原因：文言与模型默认语体（现代白话）正面对抗，属于「对抗 system prompt 的段落」，只放 SessionStart 会在长对话里衰减漂回白话。caveman 上游同样是两层设计。

代价是每轮多一行短锚（上限 300 字符，测试钉住）。往短锚里加内容前先问「不加会不会漂」——不会漂的写进 `style/wenyan-ultra-rules.md`，不要往每轮堆。

## 文件职责

| 文件 | 内容 | 能不能改 |
|---|---|---|
| `style/wenyan-ultra-rules.md` | 压缩法、禁忌、原样清单、例句、降级、产出物边界 | 调整风格行为改这里 |
| `style/project-overrides.md` | 与 `working-discipline` 的接缝：正文拍板与答后闭环、md 受众判定声明、并存说明 | 调整与本仓纪律的关系改这里 |
| `hooks/session-start.js` | 拼上面两份 + 常驻声明，输出 `additionalContext` | 改拼接逻辑 |
| `hooks/user-prompt-submit.js` | 每轮一行短锚 | 慎改，每轮成本 |
| `hooks/tests/wenyan-output-style.test.js` | 协议、注入预算、golden 回归 | 改规则后刷新 golden |
| `hooks/tests/golden/*.json` | 注入文本基准 | 只由下面的刷新命令生成 |

**注入预算由测试钉住**：SessionStart 正文 ≤ 6400 字符，每轮短锚 ≤ 300 字符（字符不是
字节）。超了就把内容挪到指针后面，不是调大这两个数。当前实测值不再抄进本 README——
这处数字历史上漂过三次（写过 2912 / 102、2785 / 169、3862 / 4327），一律以测试输出为准。

跑测试：`node plugins/wenyan-output-style/hooks/tests/wenyan-output-style.test.js`。

### 改规则后刷新 golden

改了两份 style 文件或短锚之后，golden 用例会红。确认改动是有意的，再从仓库根执行：

```bash
node plugins/wenyan-output-style/hooks/session-start.js < /dev/null > plugins/wenyan-output-style/hooks/tests/golden/session-start.json
node plugins/wenyan-output-style/hooks/user-prompt-submit.js < /dev/null > plugins/wenyan-output-style/hooks/tests/golden/user-prompt-submit.json
```

（Windows 的 cmd 把 `< /dev/null` 换成 `< NUL`。）commit message 里写明 golden 为什么变。

## 1.8.0：篇章连贯、正文拍板、hook 由 bash 迁 JS

**篇章连贯。** 症状是「每句都懂、整段难懂」——压缩把句间的因果、条件、转折删掉，读者只能
自己补桥。压缩法前加了一条总则：关系词不算冗词，八条压缩法与它冲突时让位；每轮短锚同步加了
「压缩不删关系」，否则每轮都在反向强化压缩。新增「篇章连贯」一节：先立情境、关系可读、
断言分层、结论前置与渐进披露、承重概念首现给定义、链接带信息气味（形态仍归
`clickable-paths` / `readable-citations`）。其中断言分层、承重概念、链接信息气味三条是纪律
不是形状，判据已迁到 `working-discipline`（3.4 / 3.9，该插件 3.32.0 起），本节只留指针与
压缩相关的补充——停用本插件后它们照样生效。

**正文拍板。** 见下文「与 working-discipline 的接缝」一节。

**hook 迁 JS。**

旧版两个 hook 是 bash + 内联 Python heredoc，有四个静默失效点：`hookEventName` 写死；
heredoc 占了 stdin，hook 读不到入参；`command -v python3` 会被 Windows Store 的零字节桩
骗过；报错全被 `2>/dev/null || true` 吞成空输出。改成 `node` 调 JS，事件名按入参回声，
空 stdin 或畸形 JSON 照常注入。迁移前先抓了 bash 版的输出存成 golden，JS 版逐字一致。

## 2026-08-05 压缩改写

`style/wenyan-ultra-rules.md`、`style/project-overrides.md`、`hooks/session-start.sh`（1.8.0 起为 `.js`）
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

**拍板四要素不豁免。** 起源、现状与期望之差、影响范围、带行号的现场证据——四条约束的是**信息**，文言约束的是**形状**。定义只在 `working-discipline` 3.3 一处，本插件不复制，只给形状：四个具名小标题依序排，证据代码块贴在论断正下方。

**拍板在正文里问，不调 `AskUserQuestion`。** 弹框会盖住前文的研判上下文，用户看不见证据就答不准。问句用白话、只圈一个决策边界，选项用小写字母编号并写代价。答后闭环（回收选定项、范围、未选项、下一步、残余不确定与重开条件，决定当轮落盘）的判据在 `working-discipline` 3.8，本插件只留指针。

**正文回答不是机械授权。** 判据同在 `working-discipline` 3.8：`worktree-flow` 的直写授权只认 `AskUserQuestion` 界面的回答，正文答复解不开，撞到它时默认引导进 worktree。本插件只补形状：要不要走弹框按用户自己的规则办，仍用弹框时四个字段用白话。

**「本次 md 受众判定」声明句照写。** 判定词原样，理由部分可文言。「禁自指」不覆盖 harness 要求的声明。

## 1.7.0：链接形态改成裸链接（两处反引号示范下线）

两份 style 文件里各有一条「文件路径写成链接」的规定，原文把模板用反引号包成 inline code。这与
`clickable-paths` 要的形态正好相反：反引号一包，markdown 只生成 code span、**不生成 link
节点**，Claude Code 拿不到 URL、不发 OSC 8，iTerm2 上点不动——而它看起来完全像一条链接。

同批改掉三处反向示范：

| 位置 | 改前 | 改后 |
|---|---|---|
| `wenyan-ultra-rules.md` 回复结构第 4 条 | 反引号包住整条链接模板 | [decisions.md:130](file:///abs/path/decisions.md#130) |
| 同文件「例」一节 | 改 `plugins/x/.claude-plugin/plugin.json:11`（真实路径写成 inline code） | 改 [plugin.json:11](file:///abs/path/plugins/x/.claude-plugin/plugin.json#11) |
| `project-overrides.md` 文件链接与提要 | 反引号包住整条链接模板 | 裸链接 + 「整条外面不套反引号」的硬要求与后果 |

另在「原样不动」一节补了一句：那一节管「不译不压」，不管「写成什么形态」——正文里提到本机文件
仍要套链接，裸 `path:行号` 只留给代码块、commit message、派给子代理的 prompt。不补这句，
`path/to/file.ext:行号` 与 `path:行号` 列在「原样不动」清单里，读起来像是「正文里就这么写」。

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
