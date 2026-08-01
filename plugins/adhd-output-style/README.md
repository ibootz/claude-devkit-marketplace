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

补充条款还处理了另外两件事：Rule 10 禁止 `"I'll..."` 这类开场白与 harness 要求「调工具前说明」的冲突（上游例外 6 已覆盖，这里提到显眼位置），以及「规则用英文但对话仍用简体中文」的边界说明。

## 文件职责

| 文件 | 内容 | 能不能改 |
|---|---|---|
| `style/upstream-rules.md` | 上游 SKILL.md 剥掉 YAML frontmatter 的正文，131 行，逐字未改 | **不要改**，改了就没法与上游比对 |
| `style/project-overrides.md` | 本仓补充：拍板材料呈现、harness 冲突、语言边界 | 要调整行为改这里 |
| `hooks/session-start.sh` | 把上面两份拼起来，加一句常驻声明，输出 `additionalContext` | 改拼接逻辑 |

注入总长约 8500 字符，低于 hook 输出上限（10000 字符）。往 `project-overrides.md` 加内容前先估算，超限会被截断落盘。

## 出处与许可

上游仓库 [ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd)，作者 Ayoub Ghriss，MIT License。许可原文保存在 `style/LICENSE.upstream`。

## 维护约定

- 注入走 `additionalContext`，纯注入零拦截，不受 `.claude/rules/hook-restraint.md` 的判据要求约束（见该文件「适用边界」节）。
- 子代理不受本插件影响（SessionStart 注入不进子代理），它们仍从 `working-discipline` 的 SubagentStart 注入拿到表达约束。
- 版本登记三处：本目录 `plugin.json` + 仓库两份 marketplace 清单，改完跑 `node scripts/check-versions.js`。
