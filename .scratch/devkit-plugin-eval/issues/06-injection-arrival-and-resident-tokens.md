# 06 — 注入到达核验与常驻 token

Status: resolved

**What to build:**

两项不计分、但决定结果可不可信的核验：

- **注入到达核验**：UserPromptSubmit / PreToolUse / SubagentStart 注入不进 eval 的 trace，只能读 `--keep-temp` 的子会话转录确认它们确实到达了模型。另查 trace 里 hook 的 `exit_code`，作前置检查冒烟之外的第二道防线。结果写 `injection-check.json`，未到达的臂在报告首段醒目标出。
- **常驻 token 静态算**：直接执行被测插件会输出注入文字的 hook，按输出计 token，不调模型，写进 `run.json` 与报告。

**Blocked by:** 03


- [x] 对一个注入插件跑对照，`injection-check.json` 列出每个 with 类臂每个 run 收到的注入事件与条数；不装臂为零
- [x] 人为让某条注入 hook 失败（如退出码非零），核验把它标为未到达，报告首段有醒目提示
- [x] 报告列出被测插件每类注入的常驻 token 数，前后两版可对比
- [x] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的「2.2 离线对照（compare）」第 5、7 步；[05](../../plugin-eval/issues/05-probe-plugin-eval-on-hook-injection.md)（哪些注入进 trace）、[09](../../plugin-eval/issues/09-build-vs-extend.md)

## Comments

### 2026-10-15 实现完成

在 worktree 分支 `worktree-agent-a9de8eb31a3fede96` 上提交，未合并 main、未推送、未改版本号（仍 0.1.0），等主会话审后合并。动 `plugins/**` 前已用 Skill 读过 `mattpocock-skills:writing-for-agents`、`skill-creator:skill-creator`（本票只写 Python 与测试，无路径追加技能）。

**实现摘要**

- 新模块 `scripts/plugin_eval_lib/injection.py`：读被测插件的 hook 声明（plugin.json 内联 / 路径 / 默认 `hooks/hooks.json`，去重，只取 `type: command`）；直接执行常驻注入 hook（SessionStart / UserPromptSubmit / SubagentStart）取输出、估 token。执行环境：真实 HOME、空临时 cwd、`CLAUDE_PLUGIN_DATA` 指临时目录、PATH 用 eval 同款；stdin 按事件给最小 payload。PreToolUse 等条件注入只登记条数，不执行、不计常驻。
- 新模块 `scripts/plugin_eval_lib/injection_check.py`：读 harvest 后的子会话转录（含 `subagents/agent-*.jsonl`）与 trace，逐 run 统计各事件 `hook_additional_context` 条数、hook 失败记录、首请求输入 token；按「静态执行得到的正文首行」作标签，逐条判 hook 到达（arrived / failed / missing / not_triggered / unverified）。写 `injection-check.json`，`run.json` 增 `injection_check`（摘要）与 `resident_tokens`；报告首段在有问题时加醒目提示，正文加「注入到达核验」「常驻 token（静态估算）」两节。
- 共享文件只做接线：`compare.py` 在组臂时算静态画像、harvest 时记每个 run 的目录、判分后调核验并写文件；`record.py` 渲染首段提示与两节。`cli.py`、`scoring.py` 未改。核验不计分，不改 `complete` / `passed`。
- 单测新增 40 个（`test_injection.py` 22、`test_injection_check.py` 16、`test_compare_injection.py` 2），全量 122 个通过。

**真实对照（演示，devkit-discipline 4.1.0 + probe 用例，`--runs 2`）**，产物在 [demo-06](../demo-06/)，只入库 run.json、report.md、injection-check.json、两臂 aggregate-result.json：

- 正常版（dispatch-model + parallel-lookup）：不装 0.67 / 当前版 1.00，$1.1146。当前版 4/4 run 全部到达，各事件条数 SessionStart 4、UserPromptSubmit 8、SubagentStart 4、PreToolUse 2；不装臂全部为 0。常驻估算 SessionStart 4512、UserPromptSubmit 1803、SubagentStart 4026；首请求实测中位数 不装 10316 / 当前版 17001。
- 弄坏版（UserPromptSubmit 的脚本路径改成不存在的 `working-discipline-missing.js`，node 退出码 1、无输出）：不装 0.33 / 当前版 0.83，$0.8236。核验报「当前版臂：2/2 个 run 有注入未到达（UserPromptSubmit …：退出码 1 ×2）」，报告首段有提示；常驻表 UserPromptSubmit 为 0。两次的常驻表并排即「前后两版可对比」；票 05 接入上一版臂后同一张表自动多一列（单测已覆盖）。

**实测发现**

1. Claude Code 2.1.300 下，hook 照常输出 JSON 后以非 2 的码退出（试了 `&& exit 3`），注入照样到达，转录也不记失败；`claude -p --include-hook-events` 旁证 hook_response 记 exit 3、但注入仍进会话。所以核验以「正文到没到」为准，退出码只作佐证；静态执行也只把超时和退出码 2 当作没有注入。第一版演示就是用 `exit 3` 弄坏，结果核验报全部到达，后改成脚本路径不存在。
2. 后台子代理完成时的 `<task-notification>` 也是一轮用户输入，会再触发 UserPromptSubmit，所以 dispatch-model 每个 run 有 3 条 UPS 注入（1 条用户原话 + 2 条通知）。条数如实计入。
3. SubagentStart 注入在子代理自己的转录 `subagents/agent-*.jsonl` 里，不在主会话转录里。

**待用户拍板**

1. 常驻 token 用字符估算：`round(宽字符数 × 1.33 + 其余字符数 × 0.29)`，宽字符 = 码位 ≥ U+2E80；只计注入正文，不含 system-reminder 包装。系数是本票自定，用 devkit-discipline 与 clickable-paths 的首请求实测差校准，误差约 ±5%。报告另附首请求实测中位数作对照。是否沿用这个口径，或改成调 count_tokens 接口（要联网、要 key）。
2. 注入未到达只进报告首段与 `injection_check.ok=false`，不改 `complete` / `passed`。未到达的运行要不要算不完整、挡住发版闸门（票 14）。
3. 静态执行在真实 HOME 下跑被测 hook（spec 口径如此）；有副作用的 hook 可能写真实 HOME（`CLAUDE_PLUGIN_DATA` 已重定向到临时目录）。

**已知缺口**

- 环境插件臂（票 05）里，若环境插件的 hook command 原文与被测插件完全相同，到达会误归因。
- SubagentStart 的 matcher 限定了 agent_type 时，没有对应子代理只判 not_triggered，不判丢失。
- trace 的失败记录只有事件名没有 command，同一事件多条 hook 时只能整事件判失败。
- 条件注入（PreToolUse 等）不计常驻、不核验到达，只报非零退出（退出码 2 是拦截，不报）。
- 宽字符系数对日文、韩文未校准；Windows / Linux 未实测（hook 用 shell 执行，`${CLAUDE_PLUGIN_ROOT}` 做文字替换）。

**扩展点**：票 04 的 hook 冒烟、票 10 的注入文本指纹可复用 `injection.load_hook_specs` / `injection.run_hook`。
