# 04 — 前置检查

Status: resolved

**What to build:**

`check` 子命令单跑前置检查；对照、复盘、闸门检查开跑前也自动执行。失败分两级：**硬项失败即中止，不提供绕过开关；软项照跑**，在报告与待审页标注。

离线对照前的硬项：hook 解释器可达（临时空 HOME 加同一 PATH，把被测插件、上一版快照、环境插件 `hooks.json` 的每条 command 真执行一次，exit 126 / 127 判不可达，其它非零码只提示）；`claude` 可执行且 eval 参数齐（读 `--help` 做特性探测，不比版本号）；已登录（`claude auth status --json` 的 `loggedIn`）；`claude plugin validate` 通过；有环境插件时它们在 containment root 内；被测插件已登记。
软项：工作区有未提交改动（照跑，`run.json` 记 dirty，结果不计入发版闸门）；Claude Code 版本或主力模型与上次对照不同（标注不可直接比）。
会话复盘前另有一组：会话目录可定位可读非空（尊重 `CLAUDE_CONFIG_DIR`）、登记清单非空且各仓路径可写、距上次复盘天数超过 `cleanupPeriodDays`（软）、要调 AI 评委时查登录态。

**Blocked by:** 03


- [x] 故意让某条 hook 的解释器经 asdf shim 解析（或写一个 exit 126 的 hook），`check` 报硬项失败并中止对照，指明是哪条 command
- [x] 每个硬项各有一个失败用例能触发中止；软项触发时对照照跑，报告首段有标注
- [x] dirty 工作区跑出的 `run.json` 带 dirty 标记
- [x] 检查逻辑不维护 shim 名单，平台差异只在配置目录定位、Python 解析、`claude` 可执行路径三处
- [x] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的「2.6 前置检查」；[15](../../plugin-eval/issues/15-preflight-checks.md)；[05](../../plugin-eval/issues/05-probe-plugin-eval-on-hook-injection.md)（asdf shim 在临时 HOME 下 exit 126，eval 不报错）

## Comments

### 2026-10-15 实现完成

在 worktree 分支上提交，未合并 main、未推送，等主会话审后合并。动 `plugins/**` 前已用 Skill 读过 `mattpocock-skills:writing-for-agents`、`skill-creator:skill-creator`（本票只写 `scripts/`、`tests/`，不命中 plugin-dev 追加项）。版本号未动，仍为 0.1.0。

**实现摘要**

- 新模块 `scripts/plugin_eval_lib/preflight.py`：`check_compare`（离线对照前）、`check_review`（会话复盘前），各项结果是 `Item(id, label, level=hard|soft, status=ok|fail|skip|warn, detail)`，汇总成 `Report`；硬项任一 `fail` 即 `passed=False`。
- `check` 子命令：`check <插件名> [--model M]` 跑离线对照前的硬项加软项；`check --review [--judge]` 跑复盘前各项。硬项失败退出码 2，没有绕过开关。
- `compare` 开跑前自动执行：硬项在任何写入（`.gitignore`、运行目录、traces）之前查，失败抛 `PreflightFailed`，命令行打印全部检查项后退出码 2。软项照跑：dirty 用 compare 自己取的 git 状态（写 `.gitignore` 之后），版本与主力模型在跑完后用实际值与上一次对照比——主力模型只有跑完才知道。结果写进 `run.json` 的 `preflight`（`passed`、`dirty`、`warnings`、`items`、`hook_smoke`），`warnings` 渲染在 `report.md` 首段；hook 冒烟的非 126/127 非零码单列「前置检查提示」一节。
- hook 冒烟：读 `hooks/hooks.json` 加 `plugin.json` 的 `hooks`（内联对象、路径字符串、路径数组），只收 `type: command`，按 command 字符串去重。临时空 HOME（同时设 `USERPROFILE`）、空临时 cwd、与 eval 子进程相同的 PATH（`evalrun.child_env`），替换 `${CLAUDE_PLUGIN_ROOT}` / `${CLAUDE_PLUGIN_DATA}`，经 shell 执行，stdin 给一份按事件拼的样例 JSON。126 / 127 判硬项失败并列出 `[插件标签] 命令原文（事件）退出码：stderr 首行`；其它非零码与超时只记提示。
- eval 参数特性探测要求的是 compare 实际会传的全部参数：`--ablation --keep-temp --no-publish --trust-plugin --scaffold --runs --concurrency --output-dir --report`，传了 `--model` 时再加 `--model`。
- 登录态只读 `loggedIn` 一个字段；`auth status` 输出里的账号邮箱、组织不进任何产物。
- 复盘前：配置目录取 `CLAUDE_CONFIG_DIR`，缺省 `~/.claude`；`projects/` 下至少一个 `*.jsonl` 算非空；`cleanupPeriodDays` 读 `<配置目录>/settings.json`，缺省 30；上次复盘取各仓 `plugin-evals/<plugin>/reviews/` 下文件名以 `YYYY-MM-DD` 开头的最大日期。
- 单测 `tests/test_preflight.py` 共 42 个，全量 126 个通过。`test_compare.py` 两处调用补了一个直接放行的前置检查替身。

**验收证据**

1. asdf shim：演示仓里把 devkit-discipline 一条 hook 的 `node` 换成 asdf shim 绝对路径。`check` 退出码 2，失败项原文为「[当前版] `<家目录>/.asdf/shims/node ${CLAUDE_PLUGIN_ROOT}/hooks/dispatch-ledger.js`（UserPromptSubmit）退出码 126：No version is set for command node」；同一仓跑 `compare` 也是退出码 2，仓里没写 `.gitignore`，也没建运行目录。单测另有 `exit 126`、仿 shim（真实 HOME 下有版本配置就能跑、空 HOME 下 exit 126）、`exit 127` 三例。
2. 每个硬项各有失败用例：已登记、claude 可执行、eval 参数齐、已登录（含输出不是 JSON）、validate、containment root、hook 冒烟，见 `HookSmokeTest` / `ClaudeItemsTest`；`CompareWiringTest.test_each_hard_item_aborts` 确认 compare 在其中三项失败时一个臂都不跑。软项：dirty 与版本变化两种都照跑，`report.md` 在第一个 `##` 之前有标注（`test_dirty_runs_and_is_marked`、`test_version_change_vs_previous_compare_marked`）。
3. dirty 真跑：[demo-04](../demo-04/plugin-evals/devkit-discipline/runs/20261015T093637Z-4.1.0-compare/report.md)，devkit-discipline 4.1.0 加 probe 三例，每例每臂 1 次，改了插件 README 未提交。`run.json` 的 `arms.current.dirty=true`、`preflight.dirty=true`，`preflight.warnings` 与 `report.md` 首段都写了「这份结果不计入发版闸门」。不装 0.61、当前版 1.00、差 +0.39，标价估算 $0.90。只入库 run.json 与 report.md。run.json 里 `registered` 项的 detail 原来带演示仓的绝对路径，修正代码后按新口径就地改成仓内相对路径，未重跑。
4. 不维护 shim 名单：`preflight.py` 里检索 `asdf|mise|volta|nvm|shims|sys.platform|os.name|win32|darwin`，0 命中。平台差异只在三处：`config_dir`；Python 一律 `sys.executable`，本模块不另行解析解释器；`evalrun.resolve_claude`。
5. 技能：见上。

**待拍板**

1. `evalrun.child_env` 会把 PATH 里的 `~/.asdf/shims` 去掉（票 03 实现），这等于一份只有一项的 shim 名单。冒烟用的是同一份 PATH，所以冒烟与 eval 子进程一致，本票没动它。如果拿掉这条剔除、改由冒烟兜底：本机 PATH 里 asdf 排在前面，每次对照都会被硬项拦下，要用户自己调好 PATH。保留还是拿掉，请用户定。
2. 插件不在 git 仓、或取不到 git 状态时，软项 dirty 记为 `warn`（「无法确认结果对应哪个提交，不计入发版闸门」），`preflight.dirty=null`。spec 只写了「有未提交改动」一种情形。
3. 「上次对照」取 `runs/` 下目录名最大的那个 `kind=compare` 记录，不管它是否完整、是否已审。

**已知缺口与扩展点**

- 上一版快照、环境插件（票 05）：`check_compare` 已有 `others=[(标签, 目录)]`（validate 与冒烟一并覆盖）和 `env_plugins` / `containment_root` 两个参数，compare 里还没传。环境插件要拷进臂组装目录之后才能查 containment，票 05 需要在任何臂开跑前先把各臂组装好，或者单独做一次预检。
- 闸门（票 14 / 15）、会话复盘（票 12）开跑前的自动执行没有接线：前者可复用 `check_compare`，后者直接调 `check_review(need_judge=...)`。待审页（票 08）读 `run.json` 的 `preflight.warnings` 即可。
- 单跑 `check` 时 dirty 在写 `.gitignore` 之前取；compare 在写之后取。插件在仓根、第一次对照时两者可能不一致。dirty 口径由票 14 统一。
- hook 命令的枚举与票 06 的 `injection.load_hook_specs` 功能重叠，合并后可收敛为一份。
- 冒烟的 stdin 是样例，对输入敏感的 hook 可能给出非零码，所以非零码只作提示，见 spec 残余风险第 3 条。Windows 上 `shell=True` 走 cmd.exe，Windows / Linux 未实测。

### 2026-10-15 集成（票 04–08 合入集成分支，devkit-plugin-eval 0.2.0）

**集成审查应修项（已修）**

- 冒烟改在插件副本里跑：拷贝时跳过顶层 `.git`、`evals`、`plugin-evals` 与各级 `__pycache__`，`${CLAUDE_PLUGIN_ROOT}` 指向副本，并设 `PYTHONDONTWRITEBYTECODE=1`。冒烟不再往用户工作树写文件，也不再让 dirty 被误判。单测：`test_python_hook_leaves_no_pycache_in_plugin_dir`。
- 版本与模型软项：任一方取不到值时判 skip 并写明是哪个字段、哪一方缺；`check` 子命令只比版本，不拿 `--model` 别名去比完整模型 id，同时固定提示「主力模型要跑完才知道」。
- 冒烟失败提示里的副本路径换回 `${CLAUDE_PLUGIN_ROOT}`，原审查可留项 7 一并修了。
- hook 枚举与票 06 合并：`collect_hook_commands` 改用 `injection.load_hook_specs`，冒烟复用 `injection.run_hook`。缺省 `type` 按 command 收（Claude Code 同此）；PreToolUse / PostToolUse / PermissionRequest 的样例输入带 `tool_name`、`tool_input`。
- 原「已知缺口」第一条已接线：compare 与 `check` 共用 `compare.load_target` / `plan_for`，上一版快照（`--base` 或自动认定）与 `--env-plugin` 一并冒烟、validate、查 containment。

**主会话口径（集成简报第六节）**

- ①：`evalrun.child_env` 仍去掉 `~/.asdf/shims`；找 claude 改用本进程的完整 PATH，与 compare、resume 一致。这是 spec 的一处例外，由主会话在 spec Comments 补记。单测：`test_claude_resolved_from_full_path_not_child_env`。
- ②：不在 git 仓时 `dirty=null`，记 warn，维持现状。票 14 的判据须写 `dirty is False`，已追加到票 14 Comments。
- ③：「上次对照」优先取最近一次 `complete=true` 的记录，一条完整的都没有才取最新一条。单测：`test_previous_compare_prefers_latest_complete_run`。

**已知缺口（来自集成审查，未修）**

- Windows 上 cmd.exe「命令找不到」的退出码是 9009，不是 127，只会落成提示。这是规格空白，等首次 Windows 实测时补。
- 超时只杀 shell，孙进程会成孤儿。冒烟与票 06 的静态执行共用 `injection.run_hook`，这一条与票 06 F 是同一处。
- 通过时「N 条 command 已执行」把超时未判定的条目也算进去了。
- 参数特性探测只查 `--help` 文本里有没有出现参数名：参数被移除、说明文字仍提到它时会漏判。
