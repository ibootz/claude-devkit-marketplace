# 离线对照报告：devkit-discipline 4.1.0

> 上一版：`working-discipline` 3.37.0，快照取自提交 `c9109dc2ed79`，由 --base 3.37.0 指定；插件路径 `plugins/working-discipline`。

> **跨改名**：上一版名为 `working-discipline`，当前版名为 `devkit-discipline`，快照原样未改名。判分规则写了 skill 全名、因而跨臂不可比的用例：zh-skill（`devkit-discipline:zh-disambiguate`）。

> 环境插件：`devkit-clickable-paths` 2.0.0（devkit-clickable-paths@claude-devkit-marketplace，gitCommitSha `8ea2db2099ff`）。

> 状态：**待审**。待审报告不能作为改插件或发版的依据；用户审过后改为「已审」。

> 信任范围：登记即声明信任该插件：之后每次对照都给 eval 加 --trust-plugin 与 --scaffold，以你的身份运行插件代码与用例声明的 scaffold_script（作者写的 bash 脚本）。

- 运行：`20261015T095228Z-4.1.0-compare`，2026-10-15T09:52:28Z 至 2026-10-15T09:56:43Z（UTC）
- 插件内容指纹：`sha256:c06cf79180afb51c6a65152eb28ff0f1d4177a9ea324c5b8871341770e1d9524`
- Claude Code：2.1.300；主力模型：claude-opus-5-5
- 判分：只用规则 grader；每例每臂 1 次
- 是否完整：是
- 是否通过：否（口径：运行完整，且当前版臂每个有分用例的规则分都 ≥ threshold，threshold=1.0）
- 花费：$2.9993（按标价（list price）估算，订阅用户只作信息）；token：输入 120、输出 38617、缓存读 648140、缓存写 299292

## 各臂总分

| 臂 | 总分 | 有效 run | 无效 run | 花费 |
|---|---|---|---|---|
| 不装 | 0.37 | 5 | 0 | $0.3903 |
| 当前版 | 0.80 | 5 | 0 | $0.8396 |
| 上一版 | 0.60 | 5 | 0 | $0.8668 |
| 当前版+环境插件 | 1.00 | 5 | 0 | $0.9025 |
| 差（当前版 − 不装） | +0.43 | | | |

## 逐用例

| 用例 | 不装 | 当前版 | 差 | 不装逐次 | 当前版逐次 |
|---|---|---|---|---|---|
| decision-no-ask | 0.50 | 1.00 | +0.50 | 0.50 | 1.00 |
| dispatch-model | 0.33 | 1.00 | +0.67 | 0.33 | 1.00 |
| env-clickable | 0.00 | 0.00 | +0.00 | 0.00 | 0.00 |
| parallel-lookup | 1.00 | 1.00 | +0.00 | 1.00 | 1.00 |
| zh-skill | 0.00 | 1.00 | +1.00 | 0.00 | 1.00 |

## 当前版未达 threshold 的用例

「是否通过」要求当前版每个有分用例 ≥ threshold（1.0）；下列用例没达到：

- env-clickable：0.00

## 未计分的 grader

with-only 的 grader 在 `--ablation none` 下会被 eval 计入分数，本报告照 eval 在 with-without 模式下的判据剔除：显式 `arm: with-only`、未写 arm 的 `tool_used: Skill`、mock 全为插件 server 替身时未写 arm 的 mock_calls grader；`llm` / `baseline` 等付费 grader 不在规则判分范围内，也剔除。

- decision-no-ask：`marker-sessionstart`（with-only）、`marker-userpromptsubmit`（with-only）
- dispatch-model：`marker-sessionstart`（with-only）、`marker-userpromptsubmit`（with-only）
- env-clickable：`marker-clickable`（with-only）、`marker-sessionstart`（with-only）、`marker-userpromptsubmit`（with-only）
- parallel-lookup：`marker-sessionstart`（with-only）、`marker-userpromptsubmit`（with-only）

## 上一版与当前版

| 用例 | 上一版 | 当前版 | 差（当前版 − 上一版） | 上一版逐次 | 当前版逐次 | 备注 |
|---|---|---|---|---|---|---|
| decision-no-ask | 1.00 | 1.00 | +0.00 | 1.00 | 1.00 |  |
| dispatch-model | 1.00 | 1.00 | +0.00 | 1.00 | 1.00 |  |
| env-clickable | 0.00 | 0.00 | +0.00 | 0.00 | 0.00 |  |
| parallel-lookup | 1.00 | 1.00 | +0.00 | 1.00 | 1.00 |  |
| zh-skill | 0.00 | 1.00 | +1.00 | 0.00 | 1.00 | 跨改名不可比 |
| 差（当前版 − 上一版） | +0.00 | | | | | 不含跨改名不可比的用例 |

## 环境插件臂

同装环境插件只用来看有没有冲突迹象，不量化「打几折」。各环境插件：

- `devkit-clickable-paths` 2.0.0（devkit-clickable-paths@claude-devkit-marketplace，gitCommitSha `8ea2db2099ff`）

| 用例 | 当前版 | 当前版+环境插件 | 差 | 当前版+环境插件逐次 |
|---|---|---|---|---|
| decision-no-ask | 1.00 | 1.00 | +0.00 | 1.00 |
| dispatch-model | 1.00 | 1.00 | +0.00 | 1.00 |
| env-clickable | 0.00 | 1.00 | +1.00 | 1.00 |
| parallel-lookup | 1.00 | 1.00 | +0.00 | 1.00 |
| zh-skill | 1.00 | 1.00 | +0.00 | 1.00 |

## 本报告未覆盖

前置检查、注入到达核验、AI 评委、常驻 token 尚未接入，run.json 里对应字段为 null。
