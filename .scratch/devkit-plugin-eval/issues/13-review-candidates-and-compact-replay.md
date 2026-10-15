# 13 — 复盘候选转草稿与 compact 后回放用例

Status: ready-for-agent

**What to build:**

把会话复盘发现的问题变成可跑的用例：

- **候选转草稿**：用户勾选的复盘候选，由 AI 现读本机 jsonl，改写成合成 prompt：保留触发违规的结构，换掉项目名、路径与业务内容；上下文裁到触发轮之前 ≤ 2 轮作 `context.history_file`，需要的文件用 `context.scaffold_script` 生成合成桩。产物进草稿区，走 11 的勾选流程。原文已过本机保留期的候选标作废。
- **compact 后回放用例**：每个注入插件挑 ≤ 3 条高风险条款，合成回放会话（`compact_boundary` + 模板化摘要 + 1～2 轮尾巴 + 被测 prompt）。合成历史**不放被测插件的注入文本**；回放子会话写进用例目录的转录在臂组装目录里清理掉。

**Blocked by:** 11, 12


- [ ] 一条勾选的复盘候选被改写成草稿，草稿里不含原会话的项目名、路径与业务内容
- [ ] 过了保留期的候选被标作废、不生成草稿
- [ ] 为 devkit-discipline 生成 ≤ 3 个 compact 后回放用例，在不装与当前版两臂都能跑出分数
- [ ] 合成历史里搜不到被测插件注入文本
- [ ] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的「2.3 用例从哪来」复盘候选与 compact 段；[17](../../plugin-eval/issues/17-case-sourcing.md) 第 3、4 条；[19](../../plugin-eval/issues/19-probe-history-file-replay.md)（history_file 格式与约束）

## Comments
