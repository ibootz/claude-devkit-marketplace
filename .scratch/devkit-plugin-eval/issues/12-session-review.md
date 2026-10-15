# 12 — 会话复盘

Status: ready-for-agent

**What to build:**

`review` 子命令手动触发，覆盖全部已登记插件，读本机会话 jsonl 抽信号，结果写回各插件所在仓的 `plugin-evals/<plugin>/reviews/<日期>.json`（零计数也写）。**原始 jsonl 不入库、不另存，抽取结果不含对话原文。**

要抽的信号：skill 调用（`Skill` tool_use、`<command-name>`、`attributionSkill` / `attributionPlugin`）；拦截（tool_result 文本、`permissionDecision`、cache 路径里的 `<plugin>/<version>`）；注入（`attachment.type`，按 hooks.json 导出的「事件 + matcher + 脚本相对路径」指纹加内容标签归到插件）；hook 时延（`hook_success.durationMs`）；compact 前后（`compact_boundary`）；环境插件（`skill_listing`，版本在复盘时读一次 `installed_plugins.json`）；Claude Code `version` / `model`，与上次对照比对，变了在待审页列「建议跑对照」。

实现要求：子代理文件并入统计；按 `uuid` 去重；缺字段容错并记 `version`；旧插件名按 marketplace 的 `renames` 归一。

复盘还产出**复盘候选**（只存会话 id、`uuid`、时间、插件版本、命中条款 id、是否在 compact 之后，不存原文），进复盘待审页供用户勾选（转草稿在 13）。

**Blocked by:** 08


- [ ] 对本机近 30 天会话跑一次复盘，每个登记插件都有一份 `reviews/<日期>.json`；用全文检索确认文件里没有对话原文
- [ ] 同一会话经 resume 复制的记录不重复计数
- [ ] 子代理里的拦截被计入
- [ ] Claude Code 版本或模型与上次对照不同时，复盘待审页出现「建议跑对照」
- [ ] 复盘候选进待审页，用户勾选结果写回
- [ ] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的spec「2.5 会话复盘（review）」；[10](../../plugin-eval/issues/10-session-jsonl-signals.md)；字段路径见 [research/session-jsonl-signals.md](../../plugin-eval/research/session-jsonl-signals.md)

## Comments
