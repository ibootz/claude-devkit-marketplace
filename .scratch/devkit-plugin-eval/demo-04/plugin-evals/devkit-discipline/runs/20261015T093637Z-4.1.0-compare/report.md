# 离线对照报告：devkit-discipline 4.1.0

> 状态：**待审**。待审报告不能作为改插件或发版的依据；用户审过后改为「已审」。

> 信任范围：登记即声明信任该插件：之后每次对照都给 eval 加 --trust-plugin 与 --scaffold，以你的身份运行插件代码与用例声明的 scaffold_script（作者写的 bash 脚本）。

- 运行：`20261015T093637Z-4.1.0-compare`，2026-10-15T09:36:37Z 至 2026-10-15T09:38:32Z（UTC）
- 插件内容指纹：`sha256:da22b3f52b81c797d51d6242ee2440b809a1e660e73d724165929e89d64bdf68`
- Claude Code：2.1.300；主力模型：claude-opus-5-5
- 判分：只用规则 grader；每例每臂 1 次
- 是否完整：是
- 是否通过：是（口径：运行完整，且当前版臂每个有分用例的规则分都 ≥ threshold，threshold=1.0）
- 花费：$0.9023（按标价（list price）估算，订阅用户只作信息）；token：输入 42、输出 15482、缓存读 166088、缓存写 90303

> **前置检查软项**（照跑；审阅时据此判断结果能否采信）：
>
> - 插件目录有未提交改动（HEAD 81bc5b6f401b），照跑；run.json 记 dirty，这份结果不计入发版闸门

## 各臂总分

| 臂 | 总分 | 有效 run | 无效 run | 花费 |
|---|---|---|---|---|
| 不装 | 0.61 | 3 | 0 | $0.3141 |
| 当前版 | 1.00 | 3 | 0 | $0.5882 |
| 差（当前版 − 不装） | +0.39 | | | |

## 逐用例

| 用例 | 不装 | 当前版 | 差 | 不装逐次 | 当前版逐次 |
|---|---|---|---|---|---|
| decision-no-ask | 0.50 | 1.00 | +0.50 | 0.50 | 1.00 |
| dispatch-model | 0.33 | 1.00 | +0.67 | 0.33 | 1.00 |
| parallel-lookup | 1.00 | 1.00 | +0.00 | 1.00 | 1.00 |

## 未计分的 grader

with-only 的 grader 在 `--ablation none` 下会被 eval 计入分数，本报告照 eval 在 with-without 模式下的判据剔除：显式 `arm: with-only`、未写 arm 的 `tool_used: Skill`、mock 全为插件 server 替身时未写 arm 的 mock_calls grader；`llm` / `baseline` 等付费 grader 不在规则判分范围内，也剔除。

- decision-no-ask：`marker-sessionstart`（with-only）、`marker-userpromptsubmit`（with-only）
- dispatch-model：`marker-sessionstart`（with-only）、`marker-userpromptsubmit`（with-only）
- parallel-lookup：`marker-sessionstart`（with-only）、`marker-userpromptsubmit`（with-only）

## 本报告未覆盖

上一版臂、注入到达核验、AI 评委、常驻 token 尚未接入，run.json 里对应字段为 null。
