# 离线对照报告：devkit-discipline 4.1.0

> 上一版：`devkit-discipline` 4.0.0，快照取自提交 `8ea2db2099ff`，自动认定为版本号与当前不同的最近一个版本的引入提交；插件路径 `plugins/devkit-discipline`。

> 状态：**待审**。待审报告不能作为改插件或发版的依据；用户审过后改为「已审」。

> 信任范围：登记即声明信任该插件：之后每次对照都给 eval 加 --trust-plugin 与 --scaffold，以你的身份运行插件代码与用例声明的 scaffold_script（作者写的 bash 脚本）。

- 运行：`20261015T105936Z-4.1.0-compare`，2026-10-15T10:59:36Z 至 2026-10-15T11:05:22Z（UTC）
- 插件内容指纹：`sha256:c06cf79180afb51c6a65152eb28ff0f1d4177a9ea324c5b8871341770e1d9524`
- Claude Code：2.1.300；主力模型：claude-opus-5-5
- 判分：只用规则 grader；每例每臂 3 次
- 是否完整：是
- 是否通过：是（口径：运行完整，且当前版臂每个有分用例的规则分都 ≥ threshold，threshold=1.0）
- 花费：$4.2990（按标价（list price）估算，订阅用户只作信息）；token：输入 196、输出 64119、缓存读 963171、缓存写 437222

## 各臂总分

| 臂 | 总分 | 有效 run | 无效 run | 花费 |
|---|---|---|---|---|
| 不装 | 0.61 | 9 | 0 | $0.8985 |
| 当前版 | 1.00 | 9 | 0 | $1.7612 |
| 上一版 | 1.00 | 9 | 0 | $2.0380 |
| 差（当前版 − 不装） | +0.39 | | | |

## 逐用例

| 用例 | 不装 | 当前版 | 差 | 不装逐次 | 当前版逐次 |
|---|---|---|---|---|---|
| decision-no-ask | 0.50 | 1.00 | +0.50 | 0.50 / 0.50 / 0.50 | 1.00 / 1.00 / 1.00 |
| dispatch-model | 0.33 | 1.00 | +0.67 | 0.33 / 0.33 / 0.33 | 1.00 / 1.00 / 1.00 |
| parallel-lookup | 1.00 | 1.00 | +0.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |

## 未计分的 grader

with-only 的 grader 在 `--ablation none` 下会被 eval 计入分数，本报告照 eval 在 with-without 模式下的判据剔除：显式 `arm: with-only`、未写 arm 的 `tool_used: Skill`、mock 全为插件 server 替身时未写 arm 的 mock_calls grader；`llm` / `baseline` 等付费 grader 不在规则判分范围内，也剔除。

- decision-no-ask：`marker-sessionstart`（with-only）、`marker-userpromptsubmit`（with-only）
- dispatch-model：`marker-sessionstart`（with-only）、`marker-userpromptsubmit`（with-only）
- parallel-lookup：`marker-sessionstart`（with-only）、`marker-userpromptsubmit`（with-only）

## 上一版与当前版

| 用例 | 上一版 | 当前版 | 差（当前版 − 上一版） | 上一版逐次 | 当前版逐次 | 备注 |
|---|---|---|---|---|---|---|
| decision-no-ask | 1.00 | 1.00 | +0.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |  |
| dispatch-model | 1.00 | 1.00 | +0.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |  |
| parallel-lookup | 1.00 | 1.00 | +0.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |  |
| 差（当前版 − 上一版） | +0.00 | | | | |  |

## 注入到达核验

只作前置核验、不计分。读 `--keep-temp` 子会话转录：注入条数含全部来源；「被测插件注入」按内容标签认领。

| 臂 | run 数 | 全部到达 | 未到达 | 无法逐条确认 | 无转录 | 被测插件注入条数 | 各事件注入条数 |
|---|---|---|---|---|---|---|---|
| 不装 | 9 | — | 0 | 0 | 0 | 0 | 0 |
| 上一版 | 9 | 9 | 0 | 0 | 0 | 28 | PreToolUse 2、SessionStart 9、SubagentStart 6、UserPromptSubmit 13 |
| 当前版 | 9 | 9 | 0 | 0 | 0 | 30 | SessionStart 9、SubagentStart 6、UserPromptSubmit 15 |

## 常驻 token（静态估算）

直接执行被测插件的常驻注入 hook，按输出估 token，不调模型。口径：round(宽字符数 × 1.33 + 其余字符数 × 0.29)，宽字符 = 码位 ≥ U+2E80；只计注入正文，不含 Claude Code 包装的 system-reminder 前缀；不调模型。SessionStart 每次会话一次，UserPromptSubmit 每轮一次，SubagentStart 每个子代理一次。

| 事件 | 当前版 | 上一版 |
|---|---|---|
| SessionStart | 4510 | 4549 |
| UserPromptSubmit | 1802 | 1823 |
| SubagentStart | 4025 | 4066 |
| 合计（各事件各触发一次） | 10337 | 10438 |

条件注入 hook（PreToolUse 等，按工具入参才注入）不计常驻：当前版 4 条、上一版 4 条。

对照：各臂首请求输入 token 实测中位数 不装 10398、上一版 17005、当前版 17006；相对不装 上一版 +6607、当前版 +6608（含 skill 列表等全部差异，不只注入）。

## 本报告未覆盖

AI 评委尚未接入，run.json 里对应字段为 null。

## 续跑记录

已完成的 run 不重跑，只补跑判无效与未跑的 run；分数按合并后的有效 run 计，口径与一次跑完相同。花费与 token 含首跑里出错的 run。

- 第 1 次（2026-10-15T11:04:32Z 至 2026-10-15T11:05:22Z，UTC）：补跑 上一版臂 decision-no-ask × 1、dispatch-model × 1、parallel-lookup × 1；替换掉的无效 run 3 个，其中撞订阅用量限制 0 个
