# 票 15 演示：规则判分子集与闸门提示（2026-10-15，devkit-plugin-eval 0.3.0 未升版本号）

读者：复核票 15 的主会话与用户。这里只放摘要，eval 子会话转录、trace、report.html 不入库。
被测插件：`devkit-discipline` 4.1.0（闸门外：非 major、未声明 `eval-required:`）。
用例：把 [probe 用例](../../plugin-eval/probe/cases/devkit-discipline/evals) 临时复制进插件目录 `evals/`，演示后已删除。
输出里的 worktree 绝对路径已替换成 `<worktree>`。

## 规则判分子集（真跑模型）

| 演示 | 命令 | 结果 | 花费（标价估算） |
|---|---|---|---|
| [A](gate-outputs/A-run-subset-3x-failed.txt) | `gate plugins/devkit-discipline --run-subset`（每例 3 次） | 规则分 0.75～0.80，`passed=false`，gate 判未过闸，原因「规则子集未通过（passed=False）」 | $1.6542 |
| [B](gate-outputs/B-run-subset-1x-passed.txt) | 同上加 `--runs 1`，用例删去 `marker-userpromptsubmit` grader | 规则分 1.00，`passed=true`，gate 采信该运行、判过闸 | $0.5326 |

- A 未通过的唯一原因是 `marker-userpromptsubmit` grader：eval 的 trace 不收 UserPromptSubmit 注入，这个 grader 在任何版本都判不过。属于 probe 用例的缺陷，不是插件问题；同一运行的注入到达核验显示 UserPromptSubmit 注入 13 条全部到达。
- 两次运行的 run.json 与 report.md：[A run.json](run-3x-failed/run.json)、[A report.md](run-3x-failed/report.md)、[B run.json](run-1x-passed/run.json)、[B report.md](run-1x-passed/report.md)。`kind=gate`，`review=null`，`judge.skipped=gate-rule-subset`。
- 跑完后执行 `pending devkit-discipline`，输出「没有待审项」：规则子集运行不进待审页。

## 闸门提示（不跑模型）

基线：演示前按 `clauses.capture_injection` 现取注入文本指纹，写进 `plugin-evals/devkit-discipline/clauses.json`（只含 `injection_fingerprint` 与 `normalization`）。演示 B 的 gate 输出里没有「建议跑对照」，说明注入文本未变时不提示。

| 演示 | 构造 | gate 输出 |
|---|---|---|
| [C](gate-outputs/C-injection-sentence-changed.txt) | `hooks/working-discipline.js` 第 880 行改一句注入文字 | 恰好一条「建议跑对照（会先更新条款清单）：注入文本指纹相对条款清单 clauses.json 变了」 |
| [D](gate-outputs/D-skill-description-changed.json) | `skills/zh-disambiguate/SKILL.md` 的 description 加四个字 | `compare_suggestion.line` 为「建议跑对照（会先更新条款清单）：相对上一版 4.0.0：skill `zh-disambiguate` 的 description 改了」，notes 里恰好一条 |
| [E gate](gate-outputs/E-gate-review-8-days.txt) / [E compare](gate-outputs/E-compare-review-8-days.txt) | `reviews/2026-10-07.json`（距今 8 天） | gate 与 compare 都输出「距上次会话复盘（2026-10-07）已 8 天，超过 7 天：建议先跑会话复盘（review）」 |
| [E 对照组](gate-outputs/E-gate-review-7-days.txt) | 改成 `reviews/2026-10-08.json`（距今 7 天） | 不提示 |

- C、D 改的是未提交改动，所以 gate 同时判未过闸，原因是 dirty；提示本身不影响过闸判定。两处改动演示后都已还原。
- E 的 compare 用 `--base no-such-ref-pe15` 让它在提醒之后、开跑之前中止（退出码 2），不花钱。
