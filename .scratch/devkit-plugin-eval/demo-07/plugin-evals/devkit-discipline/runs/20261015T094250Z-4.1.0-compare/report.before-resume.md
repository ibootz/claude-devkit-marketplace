# 离线对照报告：devkit-discipline 4.1.0

> 状态：**待审**。待审报告不能作为改插件或发版的依据；用户审过后改为「已审」。

> 信任范围：登记即声明信任该插件：之后每次对照都给 eval 加 --trust-plugin 与 --scaffold，以你的身份运行插件代码与用例声明的 scaffold_script（作者写的 bash 脚本）。

- 运行：`20261015T094250Z-4.1.0-compare`，2026-10-15T09:42:50Z 至 2026-10-15T09:45:47Z（UTC）
- 插件内容指纹：`sha256:c06cf79180afb51c6a65152eb28ff0f1d4177a9ea324c5b8871341770e1d9524`
- Claude Code：2.1.300；主力模型：claude-opus-5-5
- 判分：只用规则 grader；每例每臂 3 次
- 是否完整：**不完整**
- 是否通过：否（口径：运行完整，且当前版臂每个有分用例的规则分都 ≥ threshold，threshold=1.0）
- 花费：$2.6635（按标价（list price）估算，订阅用户只作信息）；token：输入 134、输出 43288、缓存读 625536、缓存写 252507

## 不完整的原因

- 当前版臂：1 个 run 出错，判无效不计分（其中 1 个撞订阅用量限制）

## 各臂总分

| 臂 | 总分 | 有效 run | 无效 run | 花费 |
|---|---|---|---|---|
| 不装 | 0.61 | 9 | 0 | $0.8603 |
| 当前版 | 1.00 | 8 | 1 | $1.8032 |
| 差（当前版 − 不装） | +0.39 | | | |

## 逐用例

| 用例 | 不装 | 当前版 | 差 | 不装逐次 | 当前版逐次 |
|---|---|---|---|---|---|
| decision-no-ask | 0.50 | 1.00 | +0.50 | 0.50 / 0.50 / 0.50 | 1.00 / 1.00 |
| dispatch-model | 0.33 | 1.00 | +0.67 | 0.33 / 0.33 / 0.33 | 1.00 / 1.00 / 1.00 |
| parallel-lookup | 1.00 | 1.00 | +0.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |

## 未计分的 grader

with-only 的 grader 在 `--ablation none` 下会被 eval 计入分数，本报告照 eval 在 with-without 模式下的判据剔除：显式 `arm: with-only`、未写 arm 的 `tool_used: Skill`、mock 全为插件 server 替身时未写 arm 的 mock_calls grader；`llm` / `baseline` 等付费 grader 不在规则判分范围内，也剔除。

- decision-no-ask：`marker-sessionstart`（with-only）、`marker-userpromptsubmit`（with-only）
- dispatch-model：`marker-sessionstart`（with-only）、`marker-userpromptsubmit`（with-only）
- parallel-lookup：`marker-sessionstart`（with-only）、`marker-userpromptsubmit`（with-only）

## 本报告未覆盖

前置检查、上一版臂、注入到达核验、AI 评委、常驻 token 尚未接入，run.json 里对应字段为 null。

## 续跑

本次运行不完整，不计入发版闸门。撞订阅用量限制的，等额度恢复后在被测插件所在仓根执行：

```
python3 <devkit-plugin-eval 插件目录>/scripts/plugin_eval.py --data-dir <数据目录> resume plugin-evals/devkit-discipline/runs/20261015T094250Z-4.1.0-compare
```

已完成的 run 不重跑，只补跑判无效与未跑的 run。插件内容指纹与首跑不同时不能续跑，要重新对照。
