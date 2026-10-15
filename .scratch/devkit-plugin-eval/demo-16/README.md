# 票 16 触发测试：run-eval 与 handle-pending 的 description

结论：两轮共 66 次 run，有效 56 次，**每一次有效 run 的触发与不触发都符合预期**。第二轮 33/33 有效且全对。

## 做法

- 用例：[trigger-cases/](trigger-cases/) 下 11 个，eval 原生格式。每例挂两个 `tool_used: Skill` grader，分别管 `run-eval` 与 `handle-pending`：应触发的写 `min: 1`，不应触发的写 `min: 0` 加 `max: 0`。
  - 应触发 `run-eval`：r1～r4（这 4 例同时是 `handle-pending` 的不应触发例）。
  - 应触发 `handle-pending`：h1～h3（同时是 `run-eval` 的不应触发例）。
  - 两个都不应触发：n1～n4，取相邻易混场景（skill-creator 的触发率评测、插件单测失败、代码审查、`claude plugin validate` 报错）。
- 运行：把插件拷到临时目录、`evals/` 换成这 11 例，跑
  `claude plugin eval <临时插件目录> --ablation none --runs 3 -j 4 --no-publish --trust-plugin --json <out.json>`。
  只装被测插件一个（eval 的隔离 HOME 不加载用户配置与其它插件），PATH 剔除 asdf shims、直接命中真实 node。
- 用例的 `allowed_tools` 只给 `Skill, Read, Glob, Grep`，不给 Bash：只测会不会加载 skill，不让子会话真去跑命令行。
- 环境：Claude Code 2.1.300，子会话模型 claude-opus-5-5（eval 缺省模型）。
- 原始 `out.json`、trace 与 eval 的 HTML 报告未入库（含子会话转录），本机临时目录已清理。

## 结果

第一轮 `max_turns: 4`：10 次 run 因「Reached maximum number of turns (4)」判无效（eval 不给无效 run 算 grader）。有效的 23 次全对。
第二轮 `max_turns: 10`、加 `--keep-temp` 从 trace 核对实际加载的 skill 名：33 次全部有效、全对。

| 用例 | 提问（摘要） | 期望 | 第一轮 有效/对 | 第二轮 有效/对 | 第二轮实际加载 |
|---|---|---|---|---|---|
| r1-upgrade-compare | 升到 4.1.0 改了注入，跑离线对照比上一版 | run-eval | 2/2 | 3/3 | `devkit-plugin-eval:run-eval` ×3 |
| r2-new-plugin | 自写插件，评测装与不装的差 | run-eval | 3/3 | 3/3 | `run-eval` ×3 |
| r3-suggested-compare | 闸门说「建议跑对照」，按它说的跑 | run-eval | 3/3 | 3/3 | `run-eval` ×3 |
| r4-release-gate | 推 main 前过发版闸门 | run-eval | 2/2 | 3/3 | `run-eval` ×3 |
| h1-bare-code | 只贴一串 `PE1 …` 回复码 | handle-pending | 1/1 | 3/3 | `devkit-plugin-eval:handle-pending` ×3 |
| h2-code-writeback | 待审页勾完了，回复码是 `PE1 …`，写回 | handle-pending | 2/2 | 3/3 | `handle-pending` ×3 |
| h3-list-pending | 还有哪些待审项，打开待审页 | handle-pending | 1/1 | 3/3 | `handle-pending` ×3 |
| n1-skill-creator | 用 skill-creator 的 evals.json 测某 skill 触发率 | 都不触发 | 2/2 | 3/3 | 无 |
| n2-unit-test-fail | 某插件的 hook 单测报 AssertionError | 都不触发 | 1/1 | 3/3 | 无 |
| n3-code-review | review 当前分支改动找 bug | 都不触发 | 3/3 | 3/3 | 内置 `code-review` ×3 |
| n4-plugin-validate | `claude plugin validate` 报 name 不合法 | 都不触发 | 3/3 | 3/3 | 无 |

「有效/对」：有效 run 数 / 两个 grader 都通过的 run 数。花费（eval 报的标价估算）：第一轮 $5.06，第二轮 $5.33。

## C 批集成补例（2026-10-16）

补两例应触发 `run-eval` 的提问（同时是 `handle-pending` 的不应触发例），跑法同第二轮（`max_turns: 10`、每例 3 次、`--keep-temp` 核对实际加载的 skill）：

| 用例 | 提问（摘要） | 期望 | 有效/对 | 实际加载 |
|---|---|---|---|---|
| r5-session-review | 扫本机最近会话，看某插件实际触发、拦截与 hook 报错（不出现「复盘」二字） | run-eval | 3/3 | `devkit-plugin-eval:run-eval` ×3 |
| r6-draft-cases | 条款清单已确认、还没有用例，让 AI 起草用例草稿 | run-eval | 3/3 | `run-eval` ×3 |

花费 $1.2906。明细见 [../demo-integ-C/README.md](../demo-integ-C/README.md)。

## 局限

- 隔离环境里没有 skill-creator、plugin-dev 等相邻插件，n1、n4 测的是本插件 description 不过度触发，测不到与那些 skill 抢触发时谁赢。
- 每例只测了第一跳是否加载 skill，加载后是否照 skill 做事不在本测试内（需要 Bash 与真实登记环境，归票 17 的真评）。
