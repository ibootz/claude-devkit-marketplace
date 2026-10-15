# 规则判分子集：devkit-discipline 4.1.0

> 闸门外版本的发版依据（spec 2.8）：只跑当前版一臂、只用规则判分；不调 AI 评委、不跑条款清单检查、不进待审页、无需审阅。闸门内版本（major 升版、声明 eval-required:）不认这份结果。

- 运行：`20261015T152828Z-4.1.0-gate`，2026-10-15T15:28:28Z 至 2026-10-15T15:29:05Z（UTC）
- 插件内容指纹：`sha256:c06cf79180afb51c6a65152eb28ff0f1d4177a9ea324c5b8871341770e1d9524`
- Claude Code：2.1.301；主力模型：claude-opus-5-5
- 每例 1 次
- 是否完整：是
- 是否通过：是（口径：运行完整，且当前版每个有分用例的规则分都 ≥ threshold（规则子集：只跑当前版一臂，with-only grader 照计分，付费 grader 不计），threshold=1.0）
- 花费：$0.5326（按标价（list price）估算，订阅用户只作信息）

## 逐用例

| 用例 | 规则分 | 逐次 | 未计分的 grader |
|---|---|---|---|
| decision-no-ask | 1.00 | 1.00 | — |
| dispatch-model | 1.00 | 1.00 | — |
| parallel-lookup | 1.00 | 1.00 | — |

## 注入到达核验

只作前置核验、不计分。读 `--keep-temp` 子会话转录：注入条数含全部来源；「被测插件注入」按内容标签认领。

| 臂 | run 数 | 全部到达 | 未到达 | 无法逐条确认 | 无转录 | 被测插件注入条数 | 各事件注入条数 |
|---|---|---|---|---|---|---|---|
| 当前版 | 3 | 3 | 0 | 0 | 0 | 10 | PreToolUse 2、SessionStart 3、SubagentStart 2、UserPromptSubmit 5 |

## 常驻 token（静态估算）

直接执行被测插件的常驻注入 hook，按输出估 token，不调模型。口径：round(宽字符数 × 1.33 + 其余字符数 × 0.29)，宽字符 = 码位 ≥ U+2E80；只计注入正文，不含 Claude Code 包装的 system-reminder 前缀；不调模型。SessionStart 每次会话一次，UserPromptSubmit 每轮一次，SubagentStart 每个子代理一次。

| 事件 | 当前版 |
|---|---|
| SessionStart | 4548 |
| UserPromptSubmit | 1815 |
| SubagentStart | 4051 |
| 合计（各事件各触发一次） | 10414 |

条件注入 hook（PreToolUse 等，按工具入参才注入）不计常驻：当前版 4 条。

对照：各臂首请求输入 token 实测中位数 当前版 17022。
