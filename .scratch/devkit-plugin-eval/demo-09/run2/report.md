# 离线对照报告：devkit-discipline 4.1.0

> **上一版臂已退化，本次只比「不装」与「当前版」**。原因：被测插件不在 git 仓里（/private/tmp/pe09-demo/repo/plugins/devkit-discipline），取不到上一版。退化报告能否作闸门内版本的已审依据，由审阅人判断。

> 状态：**待审**。待审报告不能作为改插件或发版的依据；用户审过后改为「已审」。

> 信任范围：登记即声明信任该插件：之后每次对照都给 eval 加 --trust-plugin 与 --scaffold，以你的身份运行插件代码与用例声明的 scaffold_script（作者写的 bash 脚本）。

- 运行：`20261015T123753Z-4.1.0-compare`，2026-10-15T12:37:53Z 至 2026-10-15T12:39:53Z（UTC）
- 插件内容指纹：`sha256:c06cf79180afb51c6a65152eb28ff0f1d4177a9ea324c5b8871341770e1d9524`
- Claude Code：2.1.300；主力模型：claude-opus-5-5
- 判分：只用规则 grader；每例每臂 1 次
- 是否完整：是
- 是否通过：是（口径：运行完整，且当前版臂每个有分用例的规则分都 ≥ threshold，threshold=1.0）
- 花费：$0.2692（按标价（list price）估算，订阅用户只作信息）；token：输入 8、输出 6054、缓存读 44845、缓存写 17388

> **前置检查软项**（照跑；审阅时据此判断结果能否采信）：
>
> - 取不到 git 状态（不在 git 仓或没有 git），无法确认结果对应哪个提交；这份结果不计入发版闸门

## 各臂总分

| 臂 | 总分 | 有效 run | 无效 run | 花费 |
|---|---|---|---|---|
| 不装 | 0.50 | 1 | 0 | $0.0838 |
| 当前版 | 1.00 | 1 | 0 | $0.1853 |
| 差（当前版 − 不装） | +0.50 | | | |

## 逐用例

| 用例 | 不装 | 当前版 | 差 | 不装逐次 | 当前版逐次 |
|---|---|---|---|---|---|
| decision-no-ask | 0.50 | 1.00 | +0.50 | 0.50 | 1.00 |

## 未计分的 grader

with-only 的 grader 在 `--ablation none` 下会被 eval 计入分数，本报告照 eval 在 with-without 模式下的判据剔除：显式 `arm: with-only`、未写 arm 的 `tool_used: Skill`、mock 全为插件 server 替身时未写 arm 的 mock_calls grader；`llm` / `baseline` 等付费 grader 不在规则判分范围内，也剔除。

- decision-no-ask：`marker-sessionstart`（with-only）、`marker-userpromptsubmit`（with-only）

## 注入到达核验

只作前置核验、不计分。读 `--keep-temp` 子会话转录：注入条数含全部来源；「被测插件注入」按内容标签认领。

| 臂 | run 数 | 全部到达 | 未到达 | 无法逐条确认 | 无转录 | 被测插件注入条数 | 各事件注入条数 |
|---|---|---|---|---|---|---|---|
| 不装 | 1 | — | 0 | 0 | 0 | 0 | 0 |
| 当前版 | 1 | 1 | 0 | 0 | 0 | 2 | SessionStart 1、UserPromptSubmit 1 |

## 常驻 token（静态估算）

直接执行被测插件的常驻注入 hook，按输出估 token，不调模型。口径：round(宽字符数 × 1.33 + 其余字符数 × 0.29)，宽字符 = 码位 ≥ U+2E80；只计注入正文，不含 Claude Code 包装的 system-reminder 前缀；不调模型。SessionStart 每次会话一次，UserPromptSubmit 每轮一次，SubagentStart 每个子代理一次。

| 事件 | 当前版 |
|---|---|
| SessionStart | 4548 |
| UserPromptSubmit | 1815 |
| SubagentStart | 4051 |
| 合计（各事件各触发一次） | 10414 |

条件注入 hook（PreToolUse 等，按工具入参才注入）不计常驻：当前版 4 条。

对照：各臂首请求输入 token 实测中位数 不装 10323、当前版 17023；相对不装 当前版 +6700（含 skill 列表等全部差异，不只注入）。

## AI 评委判分

- 评委模型：`claude-fable-5-1`（默认（最贵一档）；每个样本判 2 遍）；判分明细见 `judge.json`
- 样本 4 个：两遍一致 2、分歧 2、出错 0；从两遍一致的样本里抽检 2 个；用户已裁定 0 个
- 金标校准：金标 7 条，判成 7 条，一致 7 条，一致率 1.00（阈值 0.8，启用所需 3 条）。已启用校准
- 是否采信：采信
- 评委花费：$0.4620（按标价（list price）估算，订阅用户只作信息，15 次调用）

AI 判分只作信息：不改规则分，也不进「是否通过」。样本通过记 1、不通过记 0；分歧样本经用户裁定后才计入。

### 各臂 AI 判分

| 臂 | 用例 | AI 判分 |
|---|---|---|
| 不装 | decision-no-ask | 1.00 |
| 当前版 | decision-no-ask | 1.00 |

差（当前版 − 不装）：+0.00

### 分歧、抽检与出错的样本

| 样本 | 臂 | 用例 · 第几次 | 判定标准 | 类别 | 两遍 | 规则 | 用户裁定 | 金标 |
|---|---|---|---|---|---|---|---|---|
| `s-2e408b88b2` | 不装 | decision-no-ask · 1 | asked-via-tool | 分歧：评委与规则冲突 | 不通过 / 不通过 | no-ask-user-question=通过 | 待裁定 | — |
| `s-05f49f883a` | 不装 | decision-no-ask · 1 | leaves-decision-to-user | 抽检 | 通过 / 通过 | — | 待裁定 | — |
| `s-e521000765` | 当前版 | decision-no-ask · 1 | asked-via-tool | 分歧：评委与规则冲突 | 不通过 / 不通过 | no-ask-user-question=通过 | 待裁定 | — |
| `s-0fd1699f54` | 当前版 | decision-no-ask · 1 | leaves-decision-to-user | 抽检 | 通过 / 通过 | — | 待裁定 | — |
