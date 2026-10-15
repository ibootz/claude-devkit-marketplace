# 15 — 规则判分子集与闸门提示

Status: resolved

**What to build:**

补齐闸门剩下的两块：

- **规则判分子集**：闸门外的版本（非 major、未声明需评测）发布前，跑全部能用规则判分的用例，只跑当前版一臂、不调 AI 评委、不进待审页，但真跑模型；结果写 `runs/<时间>-<版本>-gate/`，`kind=gate`，供 14 的判据采信。
- **闸门提示**：`gate` 每次运行时额外输出——升版改动碰到 skill description 或 agent 定义，或注入文本指纹相对上次对照变了，合成一条「建议跑对照（会先更新条款清单）」；距上次复盘超过 7 天（从各仓 `reviews/` 现算），提醒先复盘。离线对照开跑时同样给出超 7 天提醒。

**Blocked by:** 10, 12, 14


- [x] 对一个闸门外版本跑规则子集，`run.json` 为 `kind=gate`，通过后 `gate` 判过闸
- [x] 规则子集运行不调 AI 评委、不产生待审页
- [x] 改一句注入文本后跑 `gate`，输出恰好一条「建议跑对照（会先更新条款清单）」
- [x] 改某 skill 的 description 后跑 `gate`，同样输出该提示
- [x] 构造距上次复盘 8 天，`gate` 与对照都提示先复盘
- [x] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的「2.8 发版闸门（gate）」；[12](../../plugin-eval/issues/12-release-gate-coverage.md) 第 2 条及覆盖说明；[20](../../plugin-eval/issues/20-clause-list-lifecycle.md) 第 4 条；[09](../../plugin-eval/issues/09-build-vs-extend.md)（超 7 天提醒）

## Comments

### 2026-10-15 A 批（09/10/12/14）集成留下的输入（本批不实现）

1. **注入文本指纹变了 → 建议跑对照**：可复用 `clauses.capture_injection` 取当前注入文字与指纹，与 `plugin-evals/<插件>/clauses.json` 的 `injection_fingerprint` 比；提示加在 `gate.evaluate` 的 `notes` 里。
2. **规则判分子集复用 `compare.run_compare` 时**：必须 `use_judge=False`，且不调条款 AI。`run_compare` 现在总会调 `clauses.check_for_run`，需要新增开关跳过它，或传一个不调模型的桩。
3. **前置检查**：gate 跑规则子集、真跑模型时再接前置检查（`preflight.check_compare`）。来源：票 14 已定口径 6（spec 2.6 字面要求 `gate` 开跑前跑前置检查，票 14 的 gate 只读记录、用不上）。
4. 规则子集的 run.json 至少要有 `kind=gate`、`plugin.version`、`plugin.fingerprint`、`complete`、`passed`、`claude_code_versions`，以及 `preflight.dirty` 或 `arms.current.dirty`，闸门才认（票 14 Comments）。gate 跳过 `kind=clauses`（`gate.SKIPPED_KINDS`）。
5. 超 7 天复盘提醒：`reviews/<日期>.json` 现按本机本地日期命名（结果里另记 `tz_offset`）；`preflight.py` 判「上次复盘」仍按 UTC 零点解析，算天数时留意。

### 2026-10-15 实现摘要（devkit-plugin-eval 0.3.0 内，不升版本号；分支 worktree-agent-a345eb448ba66065f，代码提交 557c166）

**结论**：验收 6 项全部满足。规则判分子集由 `gate <插件目录> --run-subset` 触发，跑完自动重判；两条提示每次跑 `gate` 都现算，提示不改变过闸判定。

**新增模块**（均在 `plugins/devkit-plugin-eval/scripts/plugin_eval_lib/`）

- `gaterun.py`：规则子集编排 `run_subset`。另起编排、不往 `compare.run_compare` 加开关：`run_compare` 写死了三臂计划、条款清单检查、AI 评委、相对不装的差值与多臂报告，规则子集一样都不要。流程：前置检查 `preflight.check_compare`（硬项失败抛 `PreflightFailed`、不建运行目录）→ 选例 → 只跑当前版一臂 → 打分 → 注入到达核验 → 写 `runs/<UTC>-<版本>-gate/` 的 `run.json`、`report.md`、`injection-check.json`。
- `gatehints.py`：「建议跑对照（会先更新条款清单）」的三个来源合成一条（`compare_suggestion`）。
- `reviewgap.py`：超 7 天复盘提醒（`reminder`），gate、compare、preflight 共用同一套日期解析。

**run.json（kind=gate）与 gate --json 新增字段**（spec 第四节待集成方登记）

- run.json：`kind=gate`、`review=null`、`judge={"skipped": "gate-rule-subset"}`、`delta=null`、`rule_subset={cases, excluded_cases, count_with_only: true}`；`plugin`、`complete`、`passed`、`claude_code_versions`、`preflight.dirty`、`injection_check` 与 compare 同口径，满足票 14 Comments 第 4 条的采信要求。
- gate --json：`compare_suggestion`（`{line, reasons, previous_version}` 或 null）、`review_reminder`（字符串或 null）、`rule_subset_needed`（null 表示该跑；否则是不跑的原因）。两条提示同时排在 `notes` 最前面。

**共享文件改动**

- `gate.py`：`evaluate` 末尾算两条提示并写进 `notes`；新增 `subset_needed_reason`；`main` 接 `--run-subset`（`_run_subset`）。
- `cli.py`：gate 子命令加 `--run-subset`、`--runs`、`-j/--concurrency`、`--model`、`--eval-timeout`。
- `compare.py`：`run_compare` 登记查完即 `log('[提示] …')` 超 7 天提醒，不中止。
- `preflight.py`：`_last_review` 改用 `reviewgap.last_review_date`；`check_review` 的「今天」改取本机本地日期（原按 UTC 零点解析，与按本地日期命名的 `reviews/<日期>.json` 差一天，本票 Comments 第 5 条）。
- `scoring.py`：`score_case` / `score_arm` 加 `count_with_only` 参数，见暂定口径 1。

**证据**

- 单测 `tests/test_gate_rule_subset.py` 28 条；全量 478 条通过；`node scripts/check-versions.js` 通过。验收对应：
  - 1：`test_gate_kind_record_one_arm_rule_cases_only`、`test_outside_gate_subset_passes_gate`、`test_cli_run_subset_then_regate`。
  - 2：`test_gate_kind_record_one_arm_rule_cases_only`（AI 评委与条款 AI 打桩成抛异常）、`test_no_pending_page`。
  - 3：`test_injection_text_changed_exactly_one_line`、`test_agent_and_injection_and_description_merge_into_one`。
  - 4：`test_skill_description_changed`、`test_skill_body_only_change_no_suggestion`。
  - 5：`test_gate_reminds_after_8_days_not_7`、`test_compare_logs_reminder`、`test_local_date_not_utc_midnight`。
- 真跑演示见 [demo-15](../demo-15/README.md)：对 `devkit-discipline` 4.1.0 跑规则子集两次，共花费 $2.1868（标价估算）。每例 3 次那次规则分 0.75～0.80、gate 判未过闸，失败全来自 probe 用例的 `marker-userpromptsubmit` grader（eval 的 trace 不收 UserPromptSubmit 注入）；去掉这个 grader、每例 1 次那次规则分 1.00，gate 采信并判过闸。改一句注入文字、改一个 skill 的 description、构造 8 天前的复盘，gate 输出都符合验收，compare 也输出了超 7 天提醒。

**已定（2026-10-16 主会话复核）**

审查判「合理」的照现状保留；第 2、6 条按 B 批集成定稿补了内容，见下一节。

1. 规则子集里 with-only 的规则 grader 照计分（只剔除付费类型）。备选：照对照的口径剔除。理由：只有一臂，没有「不装」臂可比，剔除后注入标记类 grader 全部失效。用户可见（影响规则分）。
2. `gate --run-subset` 默认每例 3 次（`--runs` 可改），threshold=1.0，即每例全部 run 都过（B 批集成定稿第 1 条；`--threshold` 可改，报告与 gate 输出写明这一点）。备选：默认 1 次，更省钱。理由：与 compare 默认一致，单次结果偶然性大。用户可见（影响花费）。Jev 选 1 次，置信度 0（两边持平）。
3. description 与 agent 定义的比较基线 = 上一版本号的最后一个提交；同版本、同插件内容指纹已跑过离线对照时不再提示，只在说明里记一句。备选：基线取上次离线对照评的那个提交。理由：「升版改动」字面就是相对上一版；上次对照可能早于上一版，会把已发布过的改动重复算进来。用户可见。Jev 选「上次对照的提交」，置信度 0.54。
4. 注入文本指纹的基线：先取最近一次 kind=compare 的 `clause_check.injection_fingerprint`（状态为 unreliable / error 的跳过），再退回 `clauses.json` 的 `injection_fingerprint`；两者都没有就不比，只记一句说明；归一化规则名不同也不比。用户可见。
5. 复盘提醒只看本插件的 `plugin-evals/<插件>/reviews/`；从未复盘也提醒。备选：从未复盘不提醒。用户可见。
6. `--run-subset` 只在闸门外、缺可采信依据、未声明 `eval-skip:`、没有其它未过闸原因（如 dirty）、单测声明通过、在 git 仓里时才真跑（后两条是 B 批集成补的，审查应修 2）；不满足时 stderr 输出「不跑规则子集：<原因>」后照常判定。用户可见。
7. 规则子集不可续跑（`resume` 只认 kind=compare），不完整就整个重跑。用户可见。
8. 选例：用例的 `graders/*.md` 里有任一规则类型就跑；一个可识别的 grader 都没有、或 `case.yaml` 里写了 `graders:` 的，也照跑（读不准就不排除）；grader 全是非规则类型（如付费类型）的排除，原因记在 `rule_subset.excluded_cases`。用户可见。
9. compare 的超 7 天提醒只写进运行日志（stderr），不写进 run.json 与报告。用户可见。

### 2026-10-16 B 批（11/15）集成修订（集成分支 worktree-agent-a8eba54acc263c023，devkit-plugin-eval 0.4.0）

**审查应修（都已修）**

- 应修 1：提示计算出错不再让 gate 崩溃。`gate.evaluate` 里 `gatehints.compare_suggestion` 与 `reviewgap.reminder` 各包一层 `try/except Exception`。出错时 `compare_suggestion` / `review_reminder` 记 null，notes 里记「提示计算出错：…（异常类型: 信息）」，过闸判定不受影响。单测 `HintErrorsDoNotBreakGateTest`：clauses.json 损坏时照常给结论，`cli gate` 退出码仍是 1（未过闸）而不是崩溃；复盘提醒抛错只记一句。
- 应修 2：`subset_needed_reason` 加 `tests_ok`、`in_git` 两个参数。单测声明未通过时返回「单测声明未通过：先修单测（修完插件内容指纹会变，现在跑的规则子集会作废）」；不在 git 仓时返回「不在 git 仓里（或没有提交）：读不到工作区是否有未提交改动，规则子集的结果闸门不采信」。单测 `SubsetNeededReasonTest`。

**可留后续里本批做掉的（B 批集成定稿）**

- 可留后续 1 → 定稿第 6 条：全部选中用例都没有可计分的规则 grader 时，规则子集记不完整（`complete=false`），`incomplete_reasons` 写「没有可计分的规则 grader」。`gate.assess_run` 对不完整的规则子集只报完整性那一条，不再报「规则子集未通过」。单测 `NoScorableGraderTest`。
- 可留后续 2 → 定稿第 1 条：gate 加 `--threshold`（默认 1.0），传给 `gaterun.run_subset`；`gate --json` 多一个字段 `rule_subset_threshold`。以下几处都写「threshold=1.0：每例全部 run 都过」（取自 `gate.threshold_text`）：规则子集 report.md 的「是否通过」一行、`console_lines`、gate 采信规则子集时的提示行、「跑规则子集」建议行。单测 `ThresholdTest`。
- 可留后续 3：从未复盘时的提醒补一句「复盘只扫登记清单里的插件，未登记需先登记（register）」。单测 `test_never_reviewed_mentions_registry`。

**probe 用例**：`.scratch/plugin-eval/probe/cases/` 下 4 个 `marker-userpromptsubmit` grader（devkit-discipline 3 个、multi 1 个）已删。eval 的 trace 不收 UserPromptSubmit 注入，这类 grader 在任何版本都判不过；注入是否到达由 `injection_check` 核验。历史草稿区 `plugin-evals/devkit-discipline/drafts/` 与仓内其它 `evals/` 下没有同类 grader：按内容 `git grep`、按文件名查找都是 0 命中。

**集成真跑**：见 [demo-integ-B](../demo-integ-B/README.md)。

**已知缺口**

- plugin.json 自定义的 skills / agents 路径不认，只比 `skills/**/SKILL.md` 与 `agents/*.md`；commands 不比。
- 注入指纹在每次跑 gate 时现取，会真执行一遍被测插件的常驻注入 hook（与 compare 第 2 步同一取法）。
- Windows 未实测。
- description 提示可能重复出现：对照跑完后又改了一个无关文件，比较基线仍是上一版，description 那条会再提示一次。B 批集成定稿第 2 条定为已知噪音，不修。
- 规则子集无人审阅，偶发失败只能重跑；threshold=1.0 下每例 3 次要求全对，偶发失败的概率比 1 次高（`--threshold`、`--runs` 可调）。

**留给 13 / 16 / 17 的接口**

- `gaterun.run_subset(data_dir, name, …)` 返回 `compare.CompareResult`（退出码 0 / 3）；`gaterun.console_lines(res)` 给控制台摘要。
- `gatehints.compare_suggestion(target=…, runs=…, plugin_fp=…, git=…, top=…, segs=…)` → `(提示 dict 或 None, 说明行)`。
- `reviewgap.reminder(reviews_dir, now=…)` → 提醒文字或 None。
- CLI：`gate <插件目录> --run-subset [--runs N] [-j N] [--model M] [--eval-timeout 分钟] [--threshold T]`。
- `gate.subset_needed_reason(gated, eval_ok, skipped, blockers, *, tests_ok, in_git)`、`gate.threshold_text(t)`。
- 票 16 的 skill：转述 gate 输出时，两条提示（`compare_suggestion.line`、`review_reminder`）要原样交给用户。
