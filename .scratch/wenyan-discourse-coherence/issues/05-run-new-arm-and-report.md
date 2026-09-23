# 05: 跑 new 组并出对比报告

Status: done
Type: task
Blocked by: 01, 04

## What to build

用 01 号票的装置，按与 baseline 组完全相同的场景、运行次数与 rubric 跑 new 组。采集输出前，同样先证明 new 组的注入状态符合预期。然后给三组评分并出报告。

报告内容：

- 每个场景下三组的得分，以及各组内部的方差。
- 按 spec 测试决策 6c 给出结论：通过或不通过，逐条对照。
- 硬负例在每次运行中的通过情况。
- 长度只作为观察项列出，不参与判定。
- 如果 no-style 组在「关系回忆」上不低于 new 组，明写一句：「触发层级决策的重开条件」（见 spec 的 Comments）。

如果使用自动 judge，保留 judge 的 prompt、模型与版本、原始的成对输出和打分依据。

另外准备一份给 06 号票用的盲评材料包：同场景的输出成对放置、顺序随机、去掉组标签，并单独存一份揭盲对照表。

## Scope boundaries

不改规则。结论不达标时照实记录，不为了过线去调整 rubric 或通过线。

## Acceptance criteria

- [ ] new 组采集前的注入证明已落盘。
- [ ] 三组的运行条件一致，只有启用的插件集合不同。
- [ ] 报告对 6c 的每一条都给出「成立 / 不成立」，并附证据。
- [ ] 硬负例逐次记录。
- [ ] 重开条件是否触发已经明写。
- [ ] 盲评材料包与揭盲对照表分开存放；材料包本身读不出组别。

## Comments

### 2026-09-23 · 已完成：判定为不通过，并触发重开条件

- new 组：用工作区插件的快照跑（与工作区逐字节一致，哈希见 `eval/proof/new-arm-snapshot.sha256`），22 次运行零失败。原先各场景 `meta.json` 里 `runs.new` 为 0，已补成与 baseline 相同的次数。
- 注入证明（采集前）：SessionStart 注入的是新版全文，每轮短锚是新版那句，旧版的 AskUserQuestion 一节没有出现。记录在 `eval/proof/`。
- 评分：`eval/judge/`。judge 为 `claude-opus-5-5`，隔离上下文，看不到组别；每条评两遍。判定口径在看到结果之前写进 `judge/README.md`。
- 报告：`eval/report.md`；数据：`eval/report-data.md`、`eval/scores.json`。
- 6c 逐条：
  - 至少五个核心场景 new ≥ baseline：不成立（4 / 6，02 为 −0.15，03 为 −0.33）。
  - 没有明显落败：成立。
  - 每次运行都通过全部硬负例：不成立。22 次运行里 14 次 fail，全部是 `inference_not_fact`；baseline 与 no-style 在同一项上各 fail 18 次。
- **触发层级决策的重开条件**：六个核心场景合并的 relation_recall，no-style 为 3.81，new 为 3.56（baseline 3.53）。
- 盲评材料：`eval/blind/packet.md`（10 对）与 `eval/blind-key/unblind.json`，分开存放。
- 未改规则，也未调整 rubric 与通过线。
