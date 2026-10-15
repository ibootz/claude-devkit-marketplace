# 15 — 规则判分子集与闸门提示

Status: ready-for-agent

**What to build:**

补齐闸门剩下的两块：

- **规则判分子集**：闸门外的版本（非 major、未声明需评测）发布前，跑全部能用规则判分的用例，只跑当前版一臂、不调 AI 评委、不进待审页，但真跑模型；结果写 `runs/<时间>-<版本>-gate/`，`kind=gate`，供 14 的判据采信。
- **闸门提示**：`gate` 每次运行时额外输出——升版改动碰到 skill description 或 agent 定义，或注入文本指纹相对上次对照变了，合成一条「建议跑对照（会先更新条款清单）」；距上次复盘超过 7 天（从各仓 `reviews/` 现算），提醒先复盘。离线对照开跑时同样给出超 7 天提醒。

**Blocked by:** 10, 12, 14


- [ ] 对一个闸门外版本跑规则子集，`run.json` 为 `kind=gate`，通过后 `gate` 判过闸
- [ ] 规则子集运行不调 AI 评委、不产生待审页
- [ ] 改一句注入文本后跑 `gate`，输出恰好一条「建议跑对照（会先更新条款清单）」
- [ ] 改某 skill 的 description 后跑 `gate`，同样输出该提示
- [ ] 构造距上次复盘 8 天，`gate` 与对照都提示先复盘
- [ ] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的spec「2.8 发版闸门（gate）」；[12](../../plugin-eval/issues/12-release-gate-coverage.md) 第 2 条及覆盖说明；[20](../../plugin-eval/issues/20-clause-list-lifecycle.md) 第 4 条；[09](../../plugin-eval/issues/09-build-vs-extend.md)（超 7 天提醒）

## Comments
