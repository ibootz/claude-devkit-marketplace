# 07 — 不完整运行与断点续跑

Status: resolved

**What to build:**

评测不设美元上限，但会撞上订阅用量限制。撞限制而失败的 run 判为无效、不计分；整次运行标「不完整」（`run.json` 的是否完整字段），可从断点续跑：已完成的臂与 run 不重跑，只补跑无效与未跑的部分。不完整的结果不计入发版闸门。`run.json` 照记 token 与标价估算，只作信息。

**Blocked by:** 03


- [x] 模拟某个 run 撞用量限制（可注入一个假失败），整次运行标「不完整」，失败 run 不进分数
- [x] 续跑命令只补跑缺的 run，完成后整次标「完整」，分数与一次跑完的口径一致
- [x] 不完整的 `run.json` 被闸门判据排除（可先用单测断言判据函数，14 接入后再端到端验证）
- [x] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的「2.2 离线对照（compare）」末两段；[09](../../plugin-eval/issues/09-build-vs-extend.md) 与 [08](../../plugin-eval/issues/08-cadence-and-budget.md) 的 2026-10-15 覆盖说明

## Comments

### 2026-10-15 实现完成

在 worktree 分支 `worktree-agent-a5021905780fb8643` 上提交，未合并 main、未推送，未改版本号（仍 0.1.0）。动 `plugins/**` 前已用 Skill 读过 `mattpocock-skills:writing-for-agents`、`skill-creator:skill-creator`（本票只改 `scripts/` 与 `tests/`，不碰 plugin.json、skills、hooks，无追加技能）。

**实现摘要**

- **判无效与归类**：run 的 `error` 非空即判无效、不计分（票 03 已有，未改）。新增 `completeness.classify_run_error` 把错误归为 `usage_limit` / `other`，只用于报告与续跑记录；续跑补跑的是全部无效 run，不依赖归类是否认准。不完整原因写成「当前版臂：1 个 run 出错，判无效不计分（其中 1 个撞订阅用量限制）」。
- **检查点**：compare 开跑前、每跑完一臂，都写一次 run.json（`complete=false`，原因「运行未结束……（已跑完的臂：不装）」）。进程中途退出也留得下 run.json，补上票 03「中途异常留下没有 run.json 的运行目录」的缺口。
- **续跑**：新子命令 `plugin_eval.py --data-dir <数据目录> resume <运行目录>`。逐臂读 `arms/<臂>/aggregate-result.json`：每个用例保留有效 run，缺几个补几个；没有汇总的臂整臂重跑。缺的个数不同的用例分组，每组调一次 eval（只拷要补的用例目录，`--runs` 为缺的个数）。补跑结果合并进同一份汇总（首跑的无效 run 剔除，记进 `run.json` 的 `resume.attempts[].replaced_invalid_runs`），再走与 compare 同一个收尾函数 `compare.finalize_run` 判分落盘，所以分数口径与一次跑完相同。续跑的 trace 放 `traces/<run_id>/resume-<n>/<臂>/`，不覆盖首跑。
- **续跑的前提**：插件版本与内容指纹都与首跑相同，否则拒绝并提示重新对照；用例集合沿用首跑 run.json 的 `cases`，首跑之后新增的用例不并入；首跑的用例目录已删则拒绝。
- **锁**：同一运行目录同一时刻只许一个进程写。锁文件放 `<数据目录>/locks/<run_id>.lock`，不进被测仓；持有者进程已不在（同主机）就接管。防止 AI 对一个仍在后台跑、检查点显示「不完整」的对照又发起续跑。
- **闸门判据**：`completeness.gate_exclusion_reason(rec)` 只判「完整性」一条：`complete` 严格为 `true` 才不排除；缺字段、非布尔、检查点都排除。票 14 在此之上再判同版本、指纹、dirty、已审 / 规则子集通过。
- **花费与 token**：照记，含首跑里出错的 run（它们真花了钱），报告「续跑记录」一节写明。
- 顺带补了票 03 审查列的三项缺口：eval 没产出汇总、或 run 缺 tracePath 时，按 trace 首条 `system/init` 的 `plugins[].path` 认领本臂组装目录下的残留 `/tmp/e-*` 沙箱并搬走（`sandbox_sweep.py`，别的会话的沙箱不动）；`claude plugin eval` 子进程可选超时 `--eval-timeout <分钟>`（默认不限时；超时整组终止、记退出码 124，该臂不完整、可续跑）；断开的符号链接在组装时跳过，不再让 copytree 抛 `shutil.Error`。
- 单测新增 21 个（`tests/test_resume.py`、`tests/test_robustness.py`），全量 105 个通过。

**真实演示（devkit-discipline 4.1.0 + probe 三例，每例每臂 3 次）**：首跑后在当前版臂 `decision-no-ask` 第 2 个 run 注入假失败「API Error: Claude AI usage limit reached|…」，run.json 标不完整、该 run 不计分（[run.before-resume.json](../demo-07/plugin-evals/devkit-discipline/runs/20261015T094250Z-4.1.0-compare/run.before-resume.json)）；随后真跑 `resume`，只补跑「当前版臂 decision-no-ask × 1」，整次标完整、通过：不装 0.61、当前版 1.00、差 +0.39，标价估算 $2.86（首跑 $2.66 + 续跑约 $0.19）。产物在 [demo-07](../demo-07/plugin-evals/devkit-discipline/runs/20261015T094250Z-4.1.0-compare/report.md)，只入库 run.json、report.md、两臂 aggregate-result.json 与续跑前快照；trace、report.html、转录不入库，已清理。演示的 report.md 是修正报告里臂名标签后按 run.json 重渲的，内容与 finalize_run 现写的一致。

**待用户拍板**

1. **续跑时 Claude Code 版本或主力模型与首跑不同**：现做法是照常合并、标完整，只在报告「续跑记录」里写一条注意。撞限后隔几小时续跑，Claude Code 很可能已自动升级；若改为「版本不同即保持不完整」，续跑会常常白跑。spec 未写。
2. **`--eval-timeout` 默认值**：现默认 0（不限时），与票 03 行为一致。设默认值会让大套件或慢模型被误杀（整臂丢、要续跑）；不设则 eval 挂死时 compare 永远不返回。
3. **撞限后是否自动停跑后续臂**：现做法是照跑（撞限的 run 很快失败，不花钱），留给续跑补。若要「检测到撞限就停、直接提示续跑」，属用户可见行为，未做。

**已知缺口**

- 撞限错误的真实文案没有实测样本（本机订阅未撞限），`USAGE_LIMIT_RE` 按 2.1.300 二进制里的字样写；认不准只影响报告里的归类计数，不影响判无效与续跑。
- 首跑的 eval 退出码不在 0 / 1、但汇总里各用例 run 数都齐的臂，续跑无 run 可补，记录会一直不完整；只能重新对照。实测未遇到（我们不传 `--max-cost-usd`）。
- 用例内容（`evals/`）不在插件内容指纹内：首跑后改了某个用例的 grader 再续跑，合并结果会混两版判据。未做用例指纹。
- 续跑在检查点之间被杀：合并后的汇总先写、run.json 后写，最坏情况是该次续跑的 token 与花费没记进 run.json，分数不受影响。
- Windows / Linux 未实测（超时整组终止在 Windows 走 `taskkill /T /F`，锁的存活判断走 `OpenProcess`）。
- **给并行票的接线点**：续跑复用 `compare._arm_specs(plugin_dir)`、`compare._run_arm(spec, ctx=...)` 与 `compare.finalize_run(...)`。票 05 改 `_arm_specs` 签名、票 06 往 `_run_arm` 的 ctx 加键时，`resume.py` 的 `base_ctx`（`resume_run` 里）与 `_arm_specs` 调用要同步；上一版臂的快照目录续跑时要能重建。票 14 实现闸门时调 `completeness.gate_exclusion_reason`。

### 2026-10-15 集成（票 04–08 合入集成分支，devkit-plugin-eval 0.2.0）

**集成审查应修项（已修）**

- B1：运行锁改用 `fcntl.flock`（Windows 走 `msvcrt.locking`），进程死了锁由系统释放，空锁文件被当成死锁接管、两进程同时接管的两个竞态都消失。锁文件不再删除，释放时清空内容。C3（Windows 存活判断）随之消失。单测：空锁文件仍被持有、`kill -9` 后自动释放。
- B2：上面「已知缺口」第三条已修。`fingerprint.evals_fingerprint` 分「共享部分」与「逐用例」两层，记在 run.json 的 `plugin.evals_fingerprint`。续跑前重算，改过首跑用例就拒绝续跑；新增用例不影响。首跑没有这条记录的老运行，续跑时在 attempt 里记 warning。
- B3：限时模式下主线程把 SIGTERM / SIGHUP 转成退出，`finally` 里按进程组杀掉 eval。单测：SIGTERM 后子进程被杀。去掉修复时这条单测失败，已反证。
- C4：run.json 与检查点一律原子写（`resume.write_json_atomic`）；坏 JSON、缺字段转成 `ResumeError`。
- 与票 05 衔接：上面「给并行票的接线点」已落地。`_arm_specs` 删除，臂清单取 `plan.specs`。续跑用 `armplan.rebuild_plan` 重建上一版快照，环境插件的版本与指纹、上一版重新认定的提交、快照指纹任一与首跑不同就拒绝续跑。首跑没有 `previous_arm` 键的老运行，按两臂续跑。
- 与票 04 衔接：续跑拿锁前先重跑前置检查硬项，不过就中止。首跑的软项提示去重后排在前面，整份首跑结果另存在 run.json 的 `preflight.first_run`。
- 与票 06 衔接：续跑后注入核验与常驻 token 照常产出，不会因 `_` 开头的键被剔除而静默跳过。
- 与票 08 衔接：首跑生成过待审页的，续跑重写 run.json 时旧页作废（`pending.superseded_by_resume` 记第几次续跑，`history` 保留旧页），锁释放后自动重新生成一页。审阅状态随结果重算，回到「待审」。

**主会话口径（集成简报第六节）**

- 待拍板 2：`--eval-timeout` 默认 0（不限时），维持。前提是 B3 已修。
- 待拍板 3：撞限后照跑后续臂，维持。

**仍待用户拍板（保持现状）**：待拍板 1，续跑时 Claude Code 版本或主力模型与首跑不同怎么处理。现状只记 warning、照常合并。

**已知缺口（来自集成审查，未修）**

- C1：发 SIGTERM 后只要组长进程退出就返回，组里忽略 SIGTERM 的子进程不会再收到 SIGKILL。宜在宽限期过后无条件补一次 `killpg(SIGKILL)`。
- C2：Windows 上 `taskkill /T /F` 失败时没有退回 `proc.kill()`，随后的 `proc.wait()` 可能一直等下去。
- C5：`replaced_invalid_runs` 在补跑之前就登记。补跑一个汇总都没产出时，首跑出错的 run 仍会从磁盘汇总里删掉，报告却写「替换掉的无效 run N 个」。整次仍判不完整，但证据丢了、措辞也不实。
- C6：`finalize_run` 不核对「每个用例的有效 run 数等于 `runs_per_case`」，完整与否靠退出码与 `partial` 间接保证。宜加成续跑完整性的硬判据。
