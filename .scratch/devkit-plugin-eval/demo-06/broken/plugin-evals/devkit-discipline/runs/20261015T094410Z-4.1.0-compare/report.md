# 离线对照报告：devkit-discipline 4.1.0

> 状态：**待审**。待审报告不能作为改插件或发版的依据；用户审过后改为「已审」。

> 信任范围：登记即声明信任该插件：之后每次对照都给 eval 加 --trust-plugin 与 --scaffold，以你的身份运行插件代码与用例声明的 scaffold_script（作者写的 bash 脚本）。

> **注入未到达或无法核验**：下列臂的分数不能直接当作插件效果，先排查 hook 再看结果（注入到达核验只作前置核验、不计分，明细见 `injection-check.json`）。
>
> - 当前版臂：2/2 个 run 有注入未到达（UserPromptSubmit `node ${CLAUDE_PLUGIN_ROOT}/hooks/working-discipline-missing.js`：退出码 1 ×2）
> - 当前版臂：常驻注入 hook 静态执行出错（UserPromptSubmit|*|node ${CLAUDE_PLUGIN_ROOT}/hooks/working-discipline-missing.js：退出码 1），这些 hook 的常驻 token 可能不准

- 运行：`20261015T094410Z-4.1.0-compare`，2026-10-15T09:44:10Z 至 2026-10-15T09:45:20Z（UTC）
- 插件内容指纹：`sha256:da22d42741ba53952cc411a5673b5eff28615630c3d0689034ee4deca805f9e0`
- Claude Code：2.1.300；主力模型：claude-opus-5-5
- 判分：只用规则 grader；每例每臂 2 次
- 是否完整：是
- 是否通过：否（口径：运行完整，且当前版臂每个有分用例的规则分都 ≥ threshold，threshold=1.0）
- 花费：$0.8236（按标价（list price）估算，订阅用户只作信息）；token：输入 58、输出 12909、缓存读 240164、缓存写 93747

## 各臂总分

| 臂 | 总分 | 有效 run | 无效 run | 花费 |
|---|---|---|---|---|
| 不装 | 0.33 | 2 | 0 | $0.2864 |
| 当前版 | 0.83 | 2 | 0 | $0.5372 |
| 差（当前版 − 不装） | +0.50 | | | |

## 逐用例

| 用例 | 不装 | 当前版 | 差 | 不装逐次 | 当前版逐次 |
|---|---|---|---|---|---|
| dispatch-model | 0.33 | 0.83 | +0.50 | 0.33 / 0.33 | 0.67 / 1.00 |

## 当前版未达 threshold 的用例

「是否通过」要求当前版每个有分用例 ≥ threshold（1.0）；下列用例没达到：

- dispatch-model：0.83

## 未计分的 grader

with-only 的 grader 在 `--ablation none` 下会被 eval 计入分数，本报告照 eval 在 with-without 模式下的判据剔除：显式 `arm: with-only`、未写 arm 的 `tool_used: Skill`、mock 全为插件 server 替身时未写 arm 的 mock_calls grader；`llm` / `baseline` 等付费 grader 不在规则判分范围内，也剔除。

- dispatch-model：`marker-sessionstart`（with-only）、`marker-userpromptsubmit`（with-only）

## 注入到达核验

只作前置核验、不计分。读 `--keep-temp` 子会话转录：注入条数含全部来源；「被测插件注入」按内容标签认领。

| 臂 | run 数 | 全部到达 | 未到达 | 无法逐条确认 | 无转录 | 被测插件注入条数 | 各事件注入条数 |
|---|---|---|---|---|---|---|---|
| 不装 | 2 | — | 0 | 0 | 0 | 0 | 0 |
| 当前版 | 2 | 0 | 2 | 0 | 0 | 6 | PreToolUse 2、SessionStart 2、SubagentStart 4 |

## 常驻 token（静态估算）

直接执行被测插件的常驻注入 hook，按输出估 token，不调模型。口径：round(宽字符数 × 1.33 + 其余字符数 × 0.29)，宽字符 = 码位 ≥ U+2E80；只计注入正文，不含 Claude Code 包装的 system-reminder 前缀；不调模型。SessionStart 每次会话一次，UserPromptSubmit 每轮一次，SubagentStart 每个子代理一次。

| 事件 | 当前版 |
|---|---|
| SessionStart | 4515 |
| UserPromptSubmit | 0 |
| SubagentStart | 4029 |
| 合计（各事件各触发一次） | 8544 |

条件注入 hook（PreToolUse 等，按工具入参才注入）不计常驻：当前版 4 条。

对照：各臂首请求输入 token 实测中位数 不装 10410.5、当前版 15094；相对不装 当前版 +4683（含 skill 列表等全部差异，不只注入）。

## 本报告未覆盖

前置检查、上一版臂、AI 评委尚未接入，run.json 里对应字段为 null。
