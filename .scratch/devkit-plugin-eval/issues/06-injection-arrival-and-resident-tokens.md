# 06 — 注入到达核验与常驻 token

Status: ready-for-agent

**What to build:**

两项不计分、但决定结果可不可信的核验：

- **注入到达核验**：UserPromptSubmit / PreToolUse / SubagentStart 注入不进 eval 的 trace，只能读 `--keep-temp` 的子会话转录确认它们确实到达了模型。另查 trace 里 hook 的 `exit_code`，作前置检查冒烟之外的第二道防线。结果写 `injection-check.json`，未到达的臂在报告首段醒目标出。
- **常驻 token 静态算**：直接执行被测插件会输出注入文字的 hook，按输出计 token，不调模型，写进 `run.json` 与报告。

**Blocked by:** 03


- [ ] 对一个注入插件跑对照，`injection-check.json` 列出每个 with 类臂每个 run 收到的注入事件与条数；不装臂为零
- [ ] 人为让某条注入 hook 失败（如退出码非零），核验把它标为未到达，报告首段有醒目提示
- [ ] 报告列出被测插件每类注入的常驻 token 数，前后两版可对比
- [ ] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的spec「2.2 离线对照（compare）」第 5、7 步；[05](../../plugin-eval/issues/05-probe-plugin-eval-on-hook-injection.md)（哪些注入进 trace）、[09](../../plugin-eval/issues/09-build-vs-extend.md)

## Comments
