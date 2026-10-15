# 16 — 两个 skill 与插件说明

Status: ready-for-agent

**What to build:**

插件只拆两个 skill，对应两个决策时刻，不加常驻 hook：

- **跑离线对照**：用户想评某插件、或被提示「建议跑对照」时触发；引导 AI 先确认被测插件已登记、选臂（默认按 spec 的基线规则：新插件比不装、改版比上一版）、长任务放后台，跑完给出待审页位置。
- **处理待审**：用户贴回回复码、或要看待审项时触发；引导 AI 调 CLI 写回裁定，并提醒「待审报告不能作为改插件或发版的依据」。

另写插件 README：命令行各子命令、登记、目录布局、单测声明格式、发版闸门用法，以及 Windows / Linux 未实测的说明。

**Blocked by:** 04, 05, 07, 09, 11


- [ ] 两个 skill 的 description 能在对应场景被自动加载：各准备 ≥ 3 条应触发与 ≥ 3 条不应触发的提问做触发测试并记录结果
- [ ] skill 正文只描述决策与调用方式，具体参数以 CLI `--help` 为准，不重复 CLI 细节
- [ ] description 长度符合本仓规则（marketplace.json 80 字符、plugin.json 120 字符）
- [ ] README 覆盖 spec「三、谁跑、何时跑、占用户多少时间」的内容
- [ ] 改插件文件前按仓根 CLAUDE.md 先读规定的技能（含 skill-creator 与 writing-for-agents）

**参考：** [spec](../../plugin-eval/spec.md) 的「2.1 交付形态」「三、谁跑、何时跑、占用户多少时间」；[09](../../plugin-eval/issues/09-build-vs-extend.md)（交付形态）

## Comments
