# 01 — 实测「不装」臂的跑法与三项 eval 未知行为

Status: ready-for-agent

**What to build:**

spec 定了每个臂各跑一次 `claude plugin eval --ablation none`，但「不装被测插件」那一臂具体怎么跑没有实测。本票用真实 eval 跑出结论，让 03 的设计有据可依；顺带实测 spec「实施待定」里另外三项未知行为。

实测完把结论写回 spec 的「实施待定」节：对应条目改为「已实测：…」，并附证据位置。证据（命令、`--json` 输出、退出码）放进本目录旁的 `probe/` 下，**不入库含账号邮箱的子会话转录**（同 plugin-eval 的处理）。

**Blocked by:** None — can start immediately


- [ ] 只含 `.claude-plugin/plugin.json` 的空桩插件跑 `--ablation none`：eval 接受与否、分数是否等同「不装」，给出实测结论
- [ ] 若空桩不可行：确认改用当前版臂 `--ablation with-without` 取 `W/OUT` 列作「不装」的做法可行，并写明回放用例必须显式带该参数
- [ ] 用例目录里放 eval 不认识的附加文件（如条款归属说明）是否报错，有实测结论
- [ ] 从 skill 里调起的 Python 进程能否拿到 `CLAUDE_PLUGIN_DATA`，有实测结论；拿不到时给出按缓存路径推出 marketplace 名的做法
- [ ] `cleanupPeriodDays` 未设置时的默认值，查官方文档或实测得出，写明出处
- [ ] spec「实施待定」第 1、3、4、6 条已更新

**参考：** [spec](../../plugin-eval/spec.md) 的spec「一、直接用 claude plugin eval 的部分」与「实施待定」第 1、3、4、6 条；[19 history_file 回放实测](../../plugin-eval/issues/19-probe-history-file-replay.md)（auto ablation 会把回放用例降为只跑 with 臂）

## Comments
