# 07 — 不完整运行与断点续跑

Status: ready-for-agent

**What to build:**

评测不设美元上限，但会撞上订阅用量限制。撞限制而失败的 run 判为无效、不计分；整次运行标「不完整」（`run.json` 的是否完整字段），可从断点续跑：已完成的臂与 run 不重跑，只补跑无效与未跑的部分。不完整的结果不计入发版闸门。`run.json` 照记 token 与标价估算，只作信息。

**Blocked by:** 03


- [ ] 模拟某个 run 撞用量限制（可注入一个假失败），整次运行标「不完整」，失败 run 不进分数
- [ ] 续跑命令只补跑缺的 run，完成后整次标「完整」，分数与一次跑完的口径一致
- [ ] 不完整的 `run.json` 被闸门判据排除（可先用单测断言判据函数，14 接入后再端到端验证）
- [ ] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的spec「2.2 离线对照（compare）」末两段；[09](../../plugin-eval/issues/09-build-vs-extend.md) 与 [08](../../plugin-eval/issues/08-cadence-and-budget.md) 的 2026-10-15 覆盖说明

## Comments
