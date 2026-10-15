# demo-integ-B：B 批（11 / 15）集成真跑的摘要

**本目录的裁定是 AI 演示，不是用户审阅。**

离线对照待审页上只有第 2 项（当前版 parallel-lookup 的评委分歧样本）有裁定，回复码 `2A` 是 AI 代给的，用来验证「裁定后重算评委差时剔除回归守护用例」。
`compare-after-2A.*` 里该样本的 `user` / `final_verdict`、对应金标，都来自这次 AI 代给的回复。
其余 5 项（报告审阅、3 个抽检、条款清单变更）没有裁定，报告状态仍是「待审」，不能作为改插件或发版的依据。

被测插件是 devkit-discipline 4.1.0 的副本，用例取 `.scratch/plugin-eval/probe/cases/devkit-discipline/evals/` 的 3 个 probe 用例（已删 `marker-userpromptsubmit` grader），另在 `evals/mocks/` 下放了一个共用文件 `shared-note.txt`。
副本放在 /tmp 下的临时 git 仓里，文中路径一律写成 `<sandbox>`。
2026-10-16 跑，eval 子进程的 PATH 直接命中真实 node（不经 asdf shim）。

| 步骤 | 命令 | 运行 | 结果 | 花费（标价估算） |
|---|---|---|---|---|
| (a) 规则子集过闸 | `gate <sandbox>/repo/plugins/devkit-discipline --run-subset` | `20261015T162209Z-4.1.0-gate` | 3 例 × 3 次，规则分全 1.00，完整、通过；gate 重判后采信，「过闸」，退出码 0；输出写了「threshold=1.0：每例全部 run 都过」 | $1.7122 |
| (b) 单测声明失败不开跑 | 同上，另一份副本把 `unit-tests.json` 改成 `node -e process.exit(1)` 并提交 | 无 | 退出码 1，stderr「不跑规则子集：单测声明未通过……」；没有生成 `plugin-evals/` | $0 |
| (c) 基线判定 | `baseline devkit-discipline` | `20261015T162411Z-4.1.0-baseline` | parallel-lookup 3/3「基线已满足」并打上 `baseline-satisfied`；另两例 0/3「基线未满足」。运行期间抓到的子集与「不装」臂目录里都有 `evals/mocks/shared-note.txt` | $0.9226 |
| (d) 离线对照（带评委） | `compare devkit-discipline --runs 1` | `20261015T162621Z-4.1.0-compare` | 完整，待审；规则差 +0.58，报告写「不含 1 个回归守护用例」；回归守护一节有「每臂 1 次，单次波动也会标退化」；无上一版臂（新插件首评），parallel-lookup 记「无上一版」 | 两臂 $0.8556 + 评委 $0.4545 + 条款清单首次抽取 $0.9262 = $2.2363 |

(d) 之前在副本里给两个用例加了评委判定标准 `judge/<id>.md`：parallel-lookup（回归守护用例）与 decision-no-ask（普通用例）各一条，并提交。

(d) 的评委差分两步看：

1. 刚跑完时（`compare.*`），当前版 parallel-lookup 的评委样本是分歧、待裁定，当前版这一例没有评委分，所以评委差 +1.00 本来就只算 decision-no-ask，`excluded_baseline_satisfied` 为空，报告不写「不含」。
2. 写回 `2A` 后（`compare-after-2A.*`），parallel-lookup 两臂都有评委分，重算时被剔除：`judge.scores.excluded_baseline_satisfied=["parallel-lookup"]`，报告写「差（当前版 − 不装，不含 1 个回归守护用例）：+1.00」。不剔除的话这一行会是 +0.50。

文件：

- `gate-subset.run.json`、`gate-subset.report.md`：(a) 的运行记录与报告。`a-gate.out.txt`、`a-gate.err.txt`：(a) 的 gate 输出。
- `b-gate.out.txt`、`b-gate.err.txt`：(b) 的 gate 输出。
- `baseline.run.json`、`baseline.report.md`：(c) 的运行记录与报告。`c-baseline.out.txt`、`c-baseline.err.txt`：命令输出。`c-baseline-subset-files.txt`：运行期间基线工作目录里的文件清单（`evals/` 是拷出的用例子集，`arms/none/` 是组装好的「不装」臂）。
- `compare.run.json`、`compare.report.md`：(d) 刚跑完时的运行记录与报告。`d-compare.out.txt`、`d-compare.err.txt`：命令输出。
- `compare-after-2A.run.json`、`compare-after-2A.report.md`：写回 AI 代给的 `2A` 之后的同一次运行。

转录、全量 trace、report.html、样本 gz、金标都没有入库。
过程与修订见票 [11](../issues/11-case-drafts-flow.md)、[15](../issues/15-gate-rule-subset-and-prompts.md) 的「2026-10-16 B 批（11/15）集成修订」一节。
