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

**参考：** [spec](../../plugin-eval/spec.md) 的「2.8 发版闸门（gate）」；[12](../../plugin-eval/issues/12-release-gate-coverage.md) 第 2 条及覆盖说明；[20](../../plugin-eval/issues/20-clause-list-lifecycle.md) 第 4 条；[09](../../plugin-eval/issues/09-build-vs-extend.md)（超 7 天提醒）

## Comments

### 2026-10-15 A 批（09/10/12/14）集成留下的输入（本批不实现）

1. **注入文本指纹变了 → 建议跑对照**：可复用 `clauses.capture_injection` 取当前注入文字与指纹，与 `plugin-evals/<插件>/clauses.json` 的 `injection_fingerprint` 比；提示加在 `gate.evaluate` 的 `notes` 里。
2. **规则判分子集复用 `compare.run_compare` 时**：必须 `use_judge=False`，且不调条款 AI。`run_compare` 现在总会调 `clauses.check_for_run`，需要新增开关跳过它，或传一个不调模型的桩。
3. **前置检查**：gate 跑规则子集、真跑模型时再接前置检查（`preflight.check_compare`）。来源：票 14 已定口径 6（spec 2.6 字面要求 `gate` 开跑前跑前置检查，票 14 的 gate 只读记录、用不上）。
4. 规则子集的 run.json 至少要有 `kind=gate`、`plugin.version`、`plugin.fingerprint`、`complete`、`passed`、`claude_code_versions`，以及 `preflight.dirty` 或 `arms.current.dirty`，闸门才认（票 14 Comments）。gate 跳过 `kind=clauses`（`gate.SKIPPED_KINDS`）。
5. 超 7 天复盘提醒：`reviews/<日期>.json` 现按本机本地日期命名（结果里另记 `tz_offset`）；`preflight.py` 判「上次复盘」仍按 UTC 零点解析，算天数时留意。
