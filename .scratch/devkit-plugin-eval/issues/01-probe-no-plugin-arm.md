# 01 — 实测「不装」臂的跑法与三项 eval 未知行为

Status: resolved

**What to build:**

spec 定了每个臂各跑一次 `claude plugin eval --ablation none`，但「不装被测插件」那一臂具体怎么跑没有实测。本票用真实 eval 跑出结论，让 03 的设计有据可依；顺带实测 spec「实施待定」里另外三项未知行为。

实测完把结论写回 spec 的「实施待定」节：对应条目改为「已实测：…」，并附证据位置。证据（命令、`--json` 输出、退出码）放进本目录旁的 `probe/` 下，**不入库含账号邮箱的子会话转录**（同 plugin-eval 的处理）。

**Blocked by:** None — can start immediately


- [x] 只含 `.claude-plugin/plugin.json` 的空桩插件跑 `--ablation none`：eval 接受与否、分数是否等同「不装」，给出实测结论
- [x] 若空桩不可行：确认改用当前版臂 `--ablation with-without` 取 `W/OUT` 列作「不装」的做法可行，并写明回放用例必须显式带该参数（前提不成立：空桩可行；备选仍顺带实测可用）
- [x] 用例目录里放 eval 不认识的附加文件（如条款归属说明）是否报错，有实测结论
- [x] 从 skill 里调起的 Python 进程能否拿到 `CLAUDE_PLUGIN_DATA`，有实测结论；拿不到时给出按缓存路径推出 marketplace 名的做法
- [x] `cleanupPeriodDays` 未设置时的默认值，查官方文档或实测得出，写明出处
- [x] spec「实施待定」第 1、3、4、6 条已更新

**参考：** [spec](../../plugin-eval/spec.md) 的「一、直接用 claude plugin eval 的部分」与「实施待定」第 1、3、4、6 条；[19 history_file 回放实测](../../plugin-eval/issues/19-probe-history-file-replay.md)（auto ablation 会把回放用例降为只跑 with 臂）

## Comments

- 2026-10-15 实测完成（Claude Code 2.1.300，7 次 eval 合计 $2.75 标价估算；code-review 后补跑 extras-mixed 1 次，8 次合计 $2.83，未撞订阅用量限制）。完整报告：[probe/REPORT.md](../probe/REPORT.md)。结论摘要：
  1. **空桩可行**：eval 接受只含 `plugin.json` 的插件；空桩臂与 without 臂的模型可见面（工具、skill、slash 命令、agent、MCP）逐项相同，计分 grader 结果相同，同一 eval 里装空桩与不装 Δ=0。03 照原设计每臂一次 `--ablation none`，「不装」臂用空桩目录。`with-without` 取 `W/OUT` 也可用，留作备选。
  2. **新发现，03 必须处理**：`--ablation none` 下 `arm: with-only` grader 计入分数（空桩臂因此 0.2 而非 0.33）。外围脚本算臂分时只取计分 grader，或用例不写这类标记。已加进 spec「一」已实测第 6 条。
  3. **附加文件**：用例目录与 `evals/` 根目录可放任意附加文件，静默忽略；`graders/` 下带 frontmatter 却无 `type:` 的 md、`prompt.md` frontmatter 里的未知键，都会让该用例加载失败（退出码 1，与「低于阈值」同码，脚本要看 `casesTotal` 与 stderr）。
  4. **`CLAUDE_PLUGIN_DATA`**：Bash 调起的 Python 进程环境里没有（eval 沙箱与真实会话都实测为 unset）；SKILL.md 正文里写 `${CLAUDE_PLUGIN_DATA}` 会被替换成绝对路径。做法：SKILL.md 传参；兜底按 `plugins/cache/<marketplace>/<plugin>/` 推出 `plugins/data/<plugin>-<marketplace>/`。
  5. **`cleanupPeriodDays` 默认 30 天**，最小 1，设 0 校验失败；出处为官方文档 settings-reference 与 2.1.300 settings schema。本机 `~/.claude/settings.json` 设的是 90。
- 证据位置：`probe/cases/`（三组探针插件与用例）、`probe/out/`（`--json`、stdout、stderr、退出码、结构比对）、`probe/excerpts/`（文档原文、可执行文件字符串）、`probe/tools/`。子会话转录与 trace 在 `probe/traces/`，含账号邮箱，已加进仓根 `.gitignore`，未入库。
- 2026-10-15 `/code-review low` 后的修订（报告与 spec 已同步改）：
  1. 「空桩臂与 without 臂逐项相同」改为「排除两条随机出现的用量类 slash 命令后逐项相同」：real-ww 的 without#3 多出 `extra-usage`、`usage-credits`，首请求 token 10412。
  2. 补跑 extras-mixed（入库的 4 例整目录，$0.0824）：坏用例只跳过自己，但**不进 `--json`、`casesTotal` 不计它**，只有 stderr 与退出码 1 能看出来。已加进 spec「一」已实测第 7 条，03 必须处理。
  3. with-only 的剔除依据查实为 `--json` 里用例级的 `cases[].graders[].config.arm`；逐 run 的 `withOnly`/`scored` 在 none 模式下分不出。已写进 spec「一」第 6 条。
  4. `run.sh`、`realsession.sh` 改为先把插件目录转成绝对路径再 `cd`；`compare-init.js` 在沙箱清掉后改读 `traces/` 本地副本（两种路径实测输出一致）。
  5. 未采纳两条：`Status: resolved` 是派票时用户指定的值，保留；报告里非 md 文件的 `vscode://file/` 绝对路径链接是本仓落盘 md 的约定（plugin-eval 两份报告同样写法），合并后即可打开，保留。
