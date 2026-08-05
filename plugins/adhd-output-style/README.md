# adhd-output-style

ADHD 友好输出风格：首行给可执行动作、多步骤编号、每轮重述进度、给具体时间估算、错误用陈述句而非「糟糕」。

复刻自 [ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd)（MIT），规则原文逐字保留。

## 怎么切换风格

与本仓其他风格插件同构，切换 = `/plugin` 里启停：

| 想要的风格 | 操作 |
|---|---|
| ADHD 友好 | 开 `adhd-output-style`，关其他风格插件 |
| 说人话（干练） | 开 `plain-talk-output-style` |
| 教学讲解 | 开 `explanatory-output-style@claude-plugins-official` |
| 默认 | 全关 |

`insight-addon` 是**附加件不是风格**，可以和上面任意一个同时开。

同时开多个**风格**插件不会报错，但两段风格指令会互相打架——一次只开一个。改动后新会话生效。

## 与上游的两点差异

**触发方式拉平成纯注入。** 上游是双通道：默认要手动 `/i-have-adhd` 触发，只有手工创建 `~/.claude/.i-have-adhd-always` 标记文件后才在 SessionStart 常驻。本仓改成只有 SessionStart 注入一条路径，因为「`/plugin` 界面看得见的开关」比「藏在家目录里的标记文件」更好维护——两个开关并存时，你会遇到「插件明明关了风格还在」这种排查不出来的情况。

**追加了 `style/project-overrides.md`。** 上游 Rule 9 要求「列表封顶 5 条，五条排过序胜过十条没排序」，而本仓 `working-discipline` 要求拍板材料必须含起源、现状与期望的差距、影响范围、带行号的现场证据四要素。两者看起来对撞。

补充条款给的解法不是让 ADHD 风格让位，而是点明**四要素约束的是信息，不是形状**：推荐项一行在前、选项排序每项配一行代价、证据用代码块贴在对应论断正下方并标 `file:line`、超过五项时拆「现在决定」与「稍后」并说明有几项挪走了。信息一条不少，形状仍是 ADHD 的。

补充条款还处理了另外三件事：Rule 10 禁止 `"I'll..."` 这类开场白与 harness 要求「调工具前说明」的冲突（上游例外 6 已覆盖，这里提到显眼位置）、「规则用英文但对话仍用简体中文」的边界说明，以及命名来源——新词只能取自 8 类权威来源（代码标识符、可见 UI 文案、需求与设计产物、测试用例名与断言文案、表名列名与字典值、API 参数与错误码文案、日志报错原文、用户自己的说法），Rule 9「列表封顶 5 条」对这份清单不适用——它是查表，不是排序论证；同一概念在多个来源里叫法不一致时按场景分，不挑赢家。

## 文件职责

| 文件 | 内容 | 能不能改 |
|---|---|---|
| `style/upstream-rules.md` | 上游 SKILL.md 剥掉 YAML frontmatter 的正文，131 行，逐字未改 | **不要改**，改了就没法与上游比对 |
| `style/project-overrides.md` | 本仓补充：拍板材料呈现、harness 冲突、语言边界 | 要调整行为改这里 |
| `hooks/session-start.sh` | 把上面两份拼起来，加一句常驻声明，输出 `additionalContext` | 改拼接逻辑 |

## 2026-08-05 压缩改写

`project-overrides.md` 四节（拍板材料四要素 / 命名来源 / harness note / language）逐句
压缩，不删除任何一条规则的信息；`hooks/session-start.sh` 的 `HEADER` 常驻声明句同步收紧。
`style/upstream-rules.md` **未改动**——它是上游 SKILL.md 逐字保留，改行为要经 project-overrides.md，
本轮压缩尊重这条既有约定，未去动它。

压缩结果：注入总长从实测 9844 字符降到 **8892 字符**，距 hook 输出上限（10000 字符）
余量从约 156 字符扩到约 1108 字符。measured 方式：`echo '{"hook_event_name":"SessionStart"}' |
bash hooks/session-start.sh`，取输出 JSON 的 `hookSpecificOutput.additionalContext` 字段
用 Python `len()` 计数（字符不是字节）。

**未达成的压缩目标**：本轮口径给的目标是 ≤7000 字符，未能达到。原因是 `upstream-rules.md`
单独测得 6391 字符且按既有约定不可改，留给 `HEADER` + `project-overrides.md` + 两处
段落分隔符的预算只剩 `7000 - 6391 = 609` 字符；而 `project-overrides.md` 的四节内容
（拍板材料四要素、命名来源 8 类、harness note、language）经压缩后最短也要 2330 字符左右，
无法塞进 609 字符而不删除信息。要达到 ≤7000 只有两条路：(a) 打破「upstream-rules.md 逐字
保留」这条既有约定去压缩它本身，或 (b) 删除 `project-overrides.md` 里的某些条款。这两条
本轮都未执行——(a) 会破坏与上游可比对性这个明确写在三处的设计约定，(b) 属于删除规则，
按口径需要拍板，故只做到 8892 字符，未到 ≤7000，留给拍板决定怎么处理。

往 `project-overrides.md` 加内容前必须先用上面的 hook 实跑测量实际字符数再加——8892 距
10000 上限还有约 1108 字符余量，但也不能靠估算，要用命令实测。

## 出处与许可

上游仓库 [ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd)，作者 Ayoub Ghriss，MIT License。许可原文保存在 `style/LICENSE.upstream`。

## 维护约定

- 注入走 `additionalContext`，纯注入零拦截，不受 `.claude/rules/project/hook-restraint.md` 的判据要求约束（见该文件「适用边界」节）。
- 子代理不受本插件影响（SessionStart 注入不进子代理），它们仍从 `working-discipline` 的 SubagentStart 注入拿到表达约束。
- 版本登记三处：本目录 `plugin.json` + 仓库两份 marketplace 清单，改完跑 `node scripts/check-versions.js`。
