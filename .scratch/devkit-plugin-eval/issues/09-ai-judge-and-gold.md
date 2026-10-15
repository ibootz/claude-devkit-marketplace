# 09 — AI 评委、分歧样本与金标

Status: ready-for-agent

**What to build:**

规则判不了的问题交 AI 评委：在 eval 之外读 `--keep-temp` 完整转录判分，**每条判两遍**；评委模型默认最贵一档（如 Fable），可配置，`run.json` 记评委模型。判分写 `judge.json`。

- **分歧样本**（两遍判法不同，或评委与规则冲突）全部进待审页；另从两遍一致的样本里随机抽 3 条进待审页。
- 用户在待审页的裁定写回 `judge.json`，裁定过的样本存为**金标样本**（`gold/`）。
- 每次评测先让评委判一遍金标，算一致率写进 `judge.json`；一致率不够时本次 AI 判分标为不采信。阈值与启用所需条数先做成配置项，留空即不启用校准。
- 用户看过的样本 trace 压缩存进本次运行的 `samples/` 入库；其余全量 trace 只留本机。

**Blocked by:** 08


- [ ] 对含一条 AI 评委判分用例的对照，`judge.json` 有两遍判分；故意构造一条分歧样本，它出现在待审页
- [ ] 两遍一致样本中随机抽 3 条进待审页（少于 3 条时全进）
- [ ] 用户裁定后该样本存为金标；下次对照先判金标并记一致率
- [ ] 一致率低于配置阈值时报告标「AI 判分不采信」
- [ ] 评委模型可通过配置改，`run.json` 记实际所用模型
- [ ] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的spec「2.4 判分与人工介入」；[11](../../plugin-eval/issues/11-judging-and-human-checkpoints.md)；[08](../../plugin-eval/issues/08-cadence-and-budget.md) 覆盖说明（评委默认最贵一档）

## Comments
