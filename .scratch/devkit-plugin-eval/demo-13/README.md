# demo-13：票 13 复盘候选转草稿与 compact 后回放用例的演示摘要

**本目录的裁定是 AI 演示，不是用户审阅。**

两次待审页的回复码都是 AI 代给的，用来演示写回流程：
- 草稿页 `2A 3A 5A`：只通过 3 个 compact 回放用例。
- 复盘页 `1A 10A`：两个候选选「转草稿」。

演示在临时克隆里跑，被测仓是本仓 70f92b9 的克隆，数据目录是临时目录，跑完已删。

克隆里另外做了两件事：
- 放进 demo-10 的条款清单：[../demo-10/clauses.json](../demo-10/clauses.json)，带快照。
- 先跑 `drafts write --limit 0`，给仓里两条 history 草稿挂上条款，花费 $0.1639。

## compact 后回放（devkit-discipline）

- `drafts compact devkit-discipline` 选中 3 条条款，写进 3 个草稿，AI 调用 2 次，花费 $0.8985：
  - C093：已证明有差，底本是 `drafts/dispatch-with-model`，直接拷底本，不调 AI。
  - C001、C002：都是 SessionStart 注入，没有底本，由 AI 起草。
- 3 份合成历史与被测插件当前注入文字比对，三项都是 0：
  - 逐字重合 ≥20 字：0；
  - 逐字重合 ≥10 字：0；
  - 注入里的行原样出现：0。
- 入库副本在 [../../../plugin-evals/devkit-discipline/drafts/](../../../plugin-evals/devkit-discipline/drafts/) 的 `compact-*`，与克隆里的有两处不同：
  - 去掉了 demo-10 清单的条款 id（仓库没有条款清单），改记 `clause_hint`；
  - `draft.json` 的 `created_at` 是拷回时刻，另加 `exported_from` 说明出处。
- 两次离线对照，每次只留 run.json 与 report.md：

| run_id | 用例 | 不装 | 上一版 4.0.0 | 当前版 4.1.0 | 花费（标价估算） |
|---|---|---|---|---|---|
| `20261015T171854Z-4.1.0-compare` | 3 个 × 1 次 | 0.78 | 1.00 | 1.00 | $2.2123；条款增量重抽另 $0.2920 |
| `20261015T172640Z-4.1.0-compare` | 只留 compact-dispatch-with-model × 1 次 | 0.33 | 1.00 | 1.00 | $0.7410 |

- 第一次对照里各用例的分数：

  | 用例 | 不装 | 当前版 |
  |---|---|---|
  | compact-c001 | 1.0 | 1.0 |
  | compact-c002 | 1.0 | 1.0 |
  | compact-dispatch-with-model | 0.33 | 1.0 |

  compact-c001 与 compact-c002 不装也满分，属于基线已满足，要靠票 15 的 baseline 判。

- 第二次对照用来取回放转录的去向证据。三臂日志各有一行「回放用例的子会话转录 2 项移出组装目录」。
  - 移出去的转录按臂计数，只数不看内容：

    | 臂 | 回放转录里的 SessionStart 记录 |
    |---|---|
    | 不装 | 0 条 |
    | 上一版 | 3 条 |
    | 当前版 | 3 条 |

  - 注入核验仍报「找不到子会话转录」，见票 13 的已知缺口。

## 复盘候选转草稿

- 真实 `review` 扫的是本机 90 天会话，devkit-discipline 有 18 个候选。
  这次跑撞到一个票 12 的缺陷：99 条条款同挂一个事件时，未映射原因超长，被自检整批拒写。已修，见票 13 Comments。
- 两个候选选了「转草稿」，然后跑 `drafts from-review devkit-discipline --date 2026-10-16`。AI 调用 1 次，花费 $0.6004，结果：
  - `c-a3c987f89a77`（拦截 `?#check=agent-dispatch` ×29，compact 之后）：改写成 1 个草稿。
    - 草稿内容：带 1 轮合成历史与合成摘要，加文件桩，被测 prompt 要求派子代理核对文档；
    - 挂的条款：AI 判为 demo-10 的 C092、C093；
    - 隐私：自检通过；对草稿目录按派发简报规定的隐私检索词（公司与项目名、家目录路径、邮箱形态）检索，0 命中。
    - 这份草稿由真实会话改写而来，**不入库**，留在临时克隆里，已随克隆删除。
  - `c-0b91af60cf02`：演示里**人为把它的指针会话 id 改成一个不存在的随机 uuid**，模拟原文已过保留期被清掉。
    - 结果标作废，`conversion = {status: void, code: file-gone}`，不生成草稿、不调 AI。
- 复盘结果文件不入库：指针来自真实会话。conversion 写回后，结果文件仍过票 12 的自检。
