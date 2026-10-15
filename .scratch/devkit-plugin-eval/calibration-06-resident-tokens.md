# 常驻 token 估算系数的校准数据（票 06）

估算式：`round(宽字符数 × 1.33 + 其余字符数 × 0.29)`，宽字符 = 码位 ≥ U+2E80。
代码在 `plugins/devkit-plugin-eval/scripts/plugin_eval_lib/injection.py`（`WIDE_RATE`、`NARROW_RATE`、`METHOD`）。

本文件补齐票 06 集成审查 A 项要的原始数据：各校准点的宽 / 窄字符数、首请求实测值、skill 列表修正量的来源。
数字取自票 06 实现会话里的命令输出（实现方当时没落盘，集成时从会话记录里抄出）；能在仓里核对的，注明了文件。

## 结论先说

- 两个系数由**两个校准点**拟合，两点都是同一作者、以中文为主的插件，拟合残差 ≤3%。
- 窄字符系数 0.29 几乎没被约束：两点的宽字符都占六成以上。**英文或代码为主的注入文本没有验证过**，误差未知。
- 常驻 token 一节只作信息，不进分数与闸门。

## 校准点 1：devkit-discipline 4.1.0（SessionStart + 一次 UserPromptSubmit）

| 注入 | 宽字符 | 其余字符 | 按式估算 |
|---|---|---|---|
| SessionStart 正文 | 2972 | 1904 | 4505 |
| UserPromptSubmit 正文 | 1119 | 1077 | 1801 |
| 合计 | | | 6306 |

字符数取自子会话转录里 `hook_additional_context` 附件的正文（不含 Claude Code 包的 `<system-reminder>` 前缀）。

首请求输入 token 实测（Claude Code 2.1.300、claude-opus-5-5，用例 dispatch-model，各 3 次）：

- 装（real-ww / with）：16887 / 16893 / 16893，中位数 16893；
- 不装（real-ww / without）：10319 / 10316 / 10412，中位数 10319；
- 差 6574。

仓内可核对：`.scratch/devkit-plugin-eval/probe/REPORT.md` 第 68–69 行。

差值除两段注入外还含 devkit-discipline 的一条 skill 列表（`devkit-discipline:zh-disambiguate`）。实现方取约 215：

- **215 的推算过程没有留存**，会话记录里只有结论。
- 集成时按同一估算式重算这条列表行（`- devkit-discipline:zh-disambiguate: <description>`，description 取当前 SKILL.md）：宽字符 129、其余 73，估 193，不含包装。215 与它同量级，差额可能来自包装文字，属推断。
- 取 215：估算 6306 + 215 = 6521，实测 6574，残差 −0.8%。

## 校准点 2：devkit-clickable-paths 2.0.0（一次 UserPromptSubmit）

| 注入 | 宽字符 | 其余字符 | 按式估算 |
|---|---|---|---|
| UserPromptSubmit 正文 | 892 | 743 | 1402 |

实测约 1369～1370，是**推算值，不是直接测量**：

- multi-plugin 用例同时装 devkit-discipline 与 devkit-clickable-paths；
- 装两者的首请求 18094 / 18187 / 18184，中位数 18184；不装 10240 / 10240 / 10243，中位数 10240；差 7944；
- 减去校准点 1 的 6574，得 1370（原注释写 1369）；
- 两组数来自不同轮次的 eval，Claude Code 版本是否一致没有核对。

残差：估算 1402 对 1370，+2.3%。

## 同一插件的复测（不是独立样本）

票 06 的两次演示与集成端到端又对 devkit-discipline 4.1.0 跑了三遍。注入文字与校准点 1 相同，只能说明复测稳定，不能当样本外验证。

| 演示 | 估算 | 实测首请求差（中位数） | 残差 |
|---|---|---|---|
| ok：SessionStart 4512 + UserPromptSubmit 1803 + skill 列表 215 | 6530 | 17001 − 10316 = 6685 | −2.3% |
| broken：UserPromptSubmit 已弄坏，SessionStart 4515 + skill 列表 215 | 4730 | 15094 − 10410.5 = 4683.5 | +1.0% |
| 集成端到端（当前版臂）：SessionStart 4510 + UserPromptSubmit 1802 + skill 列表 215 | 6527 | 17006 − 10398 = 6608 | −1.2% |

仓内可核对：

- `.scratch/devkit-plugin-eval/demo-06/ok/plugin-evals/devkit-discipline/runs/20261015T094409Z-4.1.0-compare/run.json` 的 `resident_tokens`；
- `.scratch/devkit-plugin-eval/demo-06/broken/plugin-evals/devkit-discipline/runs/20261015T094410Z-4.1.0-compare/run.json` 的 `resident_tokens`；
- `.scratch/devkit-plugin-eval/demo-integ/run.json` 的 `resident_tokens`。

## 没覆盖的

- 英文为主、代码为主的注入文本：没有校准点。
- 其他模型的分词器：只测了 claude-opus-5-5。
- 估算 / 改用 count_tokens 接口：待拍板（票 06 待拍板 3.1）。
