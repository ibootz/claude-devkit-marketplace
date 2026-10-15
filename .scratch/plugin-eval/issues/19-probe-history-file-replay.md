# 19: 实测 history_file 回放能否测出「长历史之后」的遵守差

Type: task
Status: resolved
Blocked by: 无

## Question

[离线对照的用例从哪来、怎么构造](17-case-sourcing.md) 第一轮 Q4 定了：「compact 之后」的离线用例用合成的 `context.history_file` 回放（模板化 compact 摘要 + 1～2 轮尾巴 + 被测 prompt），但前提未实测。用 `claude plugin eval` 跑一次最小实测，回答：

1. `context.history_file` 接受什么格式：Claude Code 会话转录 jsonl 原样可用，还是另有字段要求；能否含 `isCompactSummary` 摘要记录；大小上限。
2. 回放后被测插件的 SessionStart / UserPromptSubmit 注入是否照常到达（读 `--keep-temp` 转录核验）。
3. 挑 1～2 条 devkit-discipline 里 probe 已证明有差的条款（如派发带 `model`），比较「无历史」与「合成长历史」两种用例的 with / without 遵守率，看长历史是否拉低遵守率、Δ 是否仍可测。

## 约束

- `--max-cost-usd 5`、`--no-publish`；用例与结果放 `.scratch/plugin-eval/probe/history-file/`，不写进 `plugins/**`。
- 合成历史里不放真实会话原文与内网项目名。
- 跑前确认 PATH 直达真实 node（asdf shim 致 hook 静默 exit 126，见 [05](05-probe-plugin-eval-on-hook-injection.md)）。

## 完成判据

三问各给「能 / 部分能 / 不能」加证据；第 3 问不成立时，按 [09](09-build-vs-extend.md) 重开条件「回放测不出 compact 后差异」交回地图。

## Answer

2026-10-15 实测完成（Claude Code 2.1.300），详见 [probe/history-file/REPORT.md](../probe/history-file/REPORT.md)。5 次 eval 合计 $4.86（上限 $5），墙钟约 5 分钟。主会话已对照 `logs/*.json` 的 `costUsd` 与 `aggregates.meanDelta` 复核。

1. **格式：能。** `history_file` 就是 Claude Code 会话转录 jsonl，eval 不解析内容，原样作 `--resume <绝对路径>` 传给子会话。最小可用字段：`type`、`uuid`、`parentUuid`（首条 null）、`sessionId`、`timestamp`、`isSidechain:false`、`message`。可以用 `system/compact_boundary` 开头、再接一条 `isCompactSummary:true` 的 user 摘要，摘要确实作为第一条 user 消息发给模型。约束（来自可执行文件字符串）：配了 `history_file` 必须有被测 prompt；路径须在用例目录或被测插件目录内、且是普通单链接文件；`.json` 形态上限 256 MB，jsonl 实测到 78 KB。回放历史不进 eval 的 trace，`tool_used` 不会把历史算进去。
2. **注入到达：能。** with 臂 9 个回放 run 的 SessionStart（`SessionStart:resume`）全部 exit 0；子会话转录里每个 with run 有 1 条 SessionStart 注入、3 条每轮注入，without 臂零注入。
3. **长历史后的差：能测，本条款未被拉低。**

   | 用例 | 历史量 | with | without | Δ | 臂内波动 |
   |---|---|---|---|---|---|
   | 无历史 | 0 | 1.00 ×3 | 0.33 ×3 | +0.67 | 0 |
   | 合成 compact 摘要 | 约 3k token | 1.00 ×3 | 0.33 ×3 | +0.67 | 0 |
   | 合成长历史 | 约 20k token | 1.00 ×2 | 0.33 ×2 | +0.67 | 0 |

**对 [离线对照的用例从哪来、怎么构造](17-case-sourcing.md) 第 4 条的影响：可行，需调整三处。**

- 回放用例必须显式带 `--ablation with-without`：默认 auto 会把回放用例降为只跑 with 臂、不出 Δ（提示原文「a replay case whose history carries the plugin into both arms」）。
- 回放子会话的转录写进**用例目录**的 `<历史 sessionId>.jsonl` 与同名目录，同一用例所有 run 往同一文件追加。按 [「上一版」臂的插件目录怎么产出](14-previous-version-arm.md)，用例拷进臂组装目录再跑，污染落在临时副本而不是仓内 `evals/`；外围脚本每批跑完要清理或搬走。
- 合成历史只放模板化摘要与尾巴，**不放被测插件的注入文本**，否则 without 臂也读得到。由此「注入只在很远的历史里、之后不再重注」的状态造不出来：with 臂每次 resume 都会新注入一次。

**对 [缺口里哪些自建、以什么形态](09-build-vs-extend.md) 重开条件「回放测不出 compact 后差异」：本轮不触发。** 但所选条款在三种历史下都没退化，「回放能否复现真实会话里 compact 后的退化」仍未验证，记入地图「Not yet specified」。

**未核实**：150k token 以上历史；历史里含工具调用；历史里带 cost-state 时 eval 会读 `restoredCostUsd` 抵扣花费（合成历史不带，不受影响）；API 请求里有 3 条消息在转录里找不到；回放与真实 compact 只差注入与尾巴的先后，是否等价未对照。

**产物**：`probe/history-file/` 下 `cases/`（5 个用例含 `history.jsonl`）、`logs/`、`results/`、`excerpts/`（7 份证据摘录）、`tools/`，共约 660 KB。合成历史是虚构的记账命令行工具「tally」开发过程，不含真实会话原文与内网项目名。

## Comments

### 2026-10-15 执行记录

已认领后派一个子代理实测，主会话复核 `logs/*.json`（5 份 `costUsd` 合计 4.8557；三份正式对照 `meanDelta` 均 0.667）与 `excerpts/binary-strings.txt`。清理了本轮 22 个 keep-temp 沙箱（`/private/tmp/e-*`，沙箱内 `sealed` 等目录权限为 000，需先 `chmod -R u+rwx` 才删得掉）与 `/tmp/h-*.jsonl` 等临时文件；05 那轮及其它会话的沙箱未动。落盘沿用票 17 的方式（`Bash` 定点写入）。
