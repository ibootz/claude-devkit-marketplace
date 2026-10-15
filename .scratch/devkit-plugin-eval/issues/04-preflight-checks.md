# 04 — 前置检查

Status: ready-for-agent

**What to build:**

`check` 子命令单跑前置检查；对照、复盘、闸门检查开跑前也自动执行。失败分两级：**硬项失败即中止，不提供绕过开关；软项照跑**，在报告与待审页标注。

离线对照前的硬项：hook 解释器可达（临时空 HOME 加同一 PATH，把被测插件、上一版快照、环境插件 `hooks.json` 的每条 command 真执行一次，exit 126 / 127 判不可达，其它非零码只提示）；`claude` 可执行且 eval 参数齐（读 `--help` 做特性探测，不比版本号）；已登录（`claude auth status --json` 的 `loggedIn`）；`claude plugin validate` 通过；有环境插件时它们在 containment root 内；被测插件已登记。
软项：工作区有未提交改动（照跑，`run.json` 记 dirty，结果不计入发版闸门）；Claude Code 版本或主力模型与上次对照不同（标注不可直接比）。
会话复盘前另有一组：会话目录可定位可读非空（尊重 `CLAUDE_CONFIG_DIR`）、登记清单非空且各仓路径可写、距上次复盘天数超过 `cleanupPeriodDays`（软）、要调 AI 评委时查登录态。

**Blocked by:** 03


- [ ] 故意让某条 hook 的解释器经 asdf shim 解析（或写一个 exit 126 的 hook），`check` 报硬项失败并中止对照，指明是哪条 command
- [ ] 每个硬项各有一个失败用例能触发中止；软项触发时对照照跑，报告首段有标注
- [ ] dirty 工作区跑出的 `run.json` 带 dirty 标记
- [ ] 检查逻辑不维护 shim 名单，平台差异只在配置目录定位、Python 解析、`claude` 可执行路径三处
- [ ] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的spec「2.6 前置检查」；[15](../../plugin-eval/issues/15-preflight-checks.md)；[05](../../plugin-eval/issues/05-probe-plugin-eval-on-hook-injection.md)（asdf shim 在临时 HOME 下 exit 126，eval 不报错）

## Comments
