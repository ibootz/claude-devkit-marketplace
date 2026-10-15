# 09 — AI 评委、分歧样本与金标

Status: resolved

**What to build:**

规则判不了的问题交 AI 评委：在 eval 之外读 `--keep-temp` 完整转录判分，**每条判两遍**；评委模型默认最贵一档（如 Fable），可配置，`run.json` 记评委模型。判分写 `judge.json`。

- **分歧样本**（两遍判法不同，或评委与规则冲突）全部进待审页；另从两遍一致的样本里随机抽 3 条进待审页。
- 用户在待审页的裁定写回 `judge.json`，裁定过的样本存为**金标样本**（`gold/`）。
- 每次评测先让评委判一遍金标，算一致率写进 `judge.json`；一致率不够时本次 AI 判分标为不采信。阈值与启用所需条数先做成配置项，留空即不启用校准。
- 用户看过的样本 trace 压缩存进本次运行的 `samples/` 入库；其余全量 trace 只留本机。

**Blocked by:** 08


- [x] 对含一条 AI 评委判分用例的对照，`judge.json` 有两遍判分；故意构造一条分歧样本，它出现在待审页
- [x] 两遍一致样本中随机抽 3 条进待审页（少于 3 条时全进）
- [x] 用户裁定后该样本存为金标；下次对照先判金标并记一致率
- [x] 一致率低于配置阈值时报告标「AI 判分不采信」
- [x] 评委模型可通过配置改，`run.json` 记实际所用模型
- [x] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的「2.4 判分与人工介入」；[11](../../plugin-eval/issues/11-judging-and-human-checkpoints.md)；[08](../../plugin-eval/issues/08-cadence-and-budget.md) 覆盖说明（评委默认最贵一档）

## Comments

### 2026-10-15 实现完成

在 worktree 分支 `worktree-agent-a12edb2b7fa5a2fd6` 上提交，基线 `6decae3`，未合并 main、未推送、未改版本号（仍 0.2.0）。动 `plugins/**` 前已用 Skill 读过 `mattpocock-skills:writing-for-agents`、`skill-creator:skill-creator`（本票只写 `scripts/` 与 `tests/`，不碰 skills / hooks / plugin.json，无追加技能）。

**实现摘要**

- 新模块三个：`judge.py`（判定标准发现、转录渲染、调评委、两遍判分、分类、抽检、样本入库、金标校准、配置）、`judgepending.py`（待审页的「分歧样本」「抽检」两类项与写回，import 即注册）、`judgereport.py`（report.md 的首段提示与「## AI 评委判分」一节）。
- 用例怎么交 AI 评委：用例目录下放 `judge/<判定标准 id>.md`，正文是判定标准；可选 frontmatter `rule: <grader 名>`（与之对照，判法相反即「评委与规则冲突」）、`arms: [current, none]`（只判这些臂）。真跑实测 eval 静默忽略该子目录，用例照常加载、运行完整。
- 样本 = 臂 × 用例 × 第几次 run × 判定标准；error 非空的 run 不交评委。每个样本独立调两次评委。评委调用：`claude -p --safe-mode --model <评委模型> --output-format json --tools "" --no-session-persistence --system-prompt …`，空临时目录、PATH 剔除 asdf shim。`--safe-mode` 不加载评测者自己的 CLAUDE.md、插件与 hook，`--bare` 不可用（只认 API key，订阅用户登录态读不到）。
- 喂给评委的转录只含助手文字、工具调用、工具结果与最终回复；hook 输出、init 里的插件清单、thinking 都不进，评委看不出样本来自哪一臂。超过 80000 字保留头 1/4、尾 3/4。
- 分类：任一遍出错 → `error`；两遍判法不同 → 分歧 `two-pass`；两遍都判「判不了」→ 分歧 `unclear`；两遍一致却与 rule grader 相反 → 分歧 `rule-conflict`；其余 `agreed`。从 `agreed` 里以 run_id 为种子随机抽 3 条作抽检，不足全抽。
- 分歧与抽检样本的 trace 去掉家目录、邮箱（换成 `<email>`）、thinking 签名后 gzip（mtime=0，同内容同字节）存 `runs/<run_id>/samples/<臂>--<用例>-<第几次>.jsonl.gz`；其余 trace 只留本机 `traces/`。
- 金标：待审页上用户判「通过 / 不通过」的样本写 `plugin-evals/<插件>/gold/g-<12 位>.json`，自带判定标准原文、用例 prompt、样本 trace 相对路径、用户判法、评委两遍判法；「判不了」不存金标。每次对照先把 `active` 不为 false 的全部金标判一遍（一遍），一致率写进 judge.json 的 `gold`。
- 配置 `plugin-evals/<插件>/judge-config.json`：`model`、`gold_agreement_threshold`（0～1）、`gold_min_samples`（≥1 整数），都可缺省；不认识的键或非法值在对照开跑前报错（不白跑各臂）。阈值或条数留空：只记一致率、不校准；判成的金标不足条数：同样不校准；启用且一致率低于阈值：`judge.trusted=false`，report.md 首段标「**AI 判分不采信**」。
- 评委模型优先级：`compare --judge-model` > 配置 `model` > 续跑时首跑 judge.json 记下的 `requested_model` > 默认 `claude-fable-5-1`。`run.json` 的 `judge_model` 记**实际所用**模型（取评委回报的 `modelUsage`），judge.json 另记 `requested_model`、`models_used`、`model_source`。`compare --no-judge` 本次不调评委。
- 判分出错的样本让运行判不完整（`incomplete_reasons` 加一条），续跑走同一入口 `finalize_run`：同一样本、同一 trace、同一判定标准指纹且两遍都没出错的沿用首跑判分与用户裁定，只重判出错的。
- 共享文件只做接线：`compare.py`（import、`run_compare` 新增 `judge_model / use_judge / judge_runner` 三个参数并在开跑前读配置、`finalize_run` 新增 `judge_opts` 并在 `_score_arms` 之前调 `judge.run`、写 judge.json、补 `judge_model / judge` 字段）；`record.py`（首段加 `judgereport.report_banner`，原「本报告未覆盖：AI 评委尚未接入」一节换成 `judgereport.report_sections`）；`cli.py`（`--judge-model`、`--no-judge`、打印一行评委摘要、捕获 `JudgeConfigError`）。`pending.py`、`resume.py`、`scoring.py` 未改。
- 单测 23 个（`tests/test_judge.py`），全量 309 个通过（python 3.9.6 与 3.14.7 各跑一遍）；pre-commit 的版本检查与单测声明也通过。

**真跑（本机，devkit-discipline 4.1.0，用例 `decision-no-ask` 加两条判定标准）**

演示仓在 `/tmp`（非 git 仓：worktree 隔离不允许本代理对外部仓跑 git，上一版臂因此按「不在 git 仓」退化）。两条判定标准：`asked-via-tool`（「发起过 AskUserQuestion 工具调用」，`rule: no-ask-user-question`，与规则含义相反，**故意构造评委与规则冲突**）、`leaves-decision-to-user`（无对照规则）。摘要入库在 `.scratch/devkit-plugin-eval/demo-09/run{1,2,3}/`（run.json、judge.json、report.md；样本 trace、金标、待审页不入库）。

| 运行 | 做了什么 | 结果 |
|---|---|---|
| run1 `20261015T123502Z` | `--runs 2`，默认评委 | 样本 8、调评委 16 次，每个样本两遍；`asked-via-tool` 4 个样本全是「评委与规则冲突」分歧，`leaves-decision-to-user` 4 个两遍一致、抽检 3 个；待审页 8 项 = 报告审阅 1 + 分歧 4 + 抽检 3；`run.json` `judge_model=claude-fable-5-1` |
| （写回） | AI 演示贴回 `2B 3B 4B 5B 6A 7A 8A`（未勾报告审阅） | `gold/` 生成 7 个金标，judge.json 各样本带 `user` 与 `gold_id` |
| run2 `20261015T123753Z` | 配置阈值 0.8、启用 3 条；`--runs 1` | 先判 7 条金标，一致 7 条、一致率 1.00、已启用校准、采信；一致样本只有 2 个，抽检 2 个（不足 3 条全进） |
| run3 `20261015T124005Z` | 配置 `model: claude-opus-5-5`；**手工改了 2 条金标的用户判法**模拟用户与评委不一致 | `judge_model=claude-opus-5-5`（来源「配置 judge-config.json」）；一致 5/7=0.71 < 0.8，report.md 首段标「AI 判分不采信」 |

花费（标价估算，订阅只作信息）：eval 三次合计 $1.08，评委三次合计 $1.49（46 次调用），另有 1 次探针调用 $0.02。没撞限流。run3 里被改的金标与 run1 的裁定都是 AI 演示，不是用户审阅，所以金标与「已审」都不入库。

**已定（2026-10-15 主会话复核）**

审查判合理的照现状保留；第 4、7、12 条被下方「A 批集成定稿」改写，以那里为准。

1. 用例怎么声明交 AI 评委：`<用例>/judge/<id>.md`，frontmatter `rule` / `arms`。备选：用 eval 原生 `type: llm` grader（eval 会自己调模型判，spec「不用 eval 内置 llm 评委」排除）、写进 `prompt.md` frontmatter（未知键会让用例加载失败，票 01 实测）。用户可见：是（写用例的人要照这个格式）。
2. 判哪些臂：默认全部臂（不装、上一版、当前版、+环境插件），可用 `arms` 收窄。备选：只判当前版（省一半调用，但算不出 AI 判分的臂间差）。用户可见：是（调用次数）。
3. 两遍都判「判不了」算分歧（交用户）；任一遍出错算 error（不进待审页，运行判不完整，续跑重判）。备选：判不了算一致、出错样本也交用户。用户可见：是。
4. 抽检样本也进金标（`source: spot-check`），与分歧样本（`source: disagreement`）同库。spec 原文「金标来自用户裁定过的分歧样本」，CONTEXT.md「金标样本」定义是「用户亲自裁定过的样本」；抽检同样是用户在同一页上判过的，不算「另外标注」。备选：只收分歧样本。可回退：按 `source` 过滤即可。用户可见：是（金标条数与一致率）。
5. 样本 trace 在**判分时**就把分歧与抽检样本存进 `samples/`（即交给用户看的那批），而不是等用户在页上看过之后再存。原因：待审页正文要从仓里读这份 trace 渲染转录，且写回事务（`Subject`）只支持文本、不支持二进制。代价：页上装不下（>10 项被抽样掉）的样本也会入库。用户可见：仓体积。
6. 每次对照判金标只判一遍；未配置阈值或条数时照样判金标、记一致率，只是不校准（验收第 3 条「下次对照先判金标并记一致率」不依赖配置）。备选：未配置时连金标也不判（省调用）。用户可见：是（调用次数）。
7. 判成的金标不足启用条数时**采信**、报告写「不足启用所需 N 条，不启用校准」。备选：不足即不采信。用户可见：是。
8. AI 判分只作信息：不改规则分、不进 `passed`（「是否通过」仍按票 03 口径）；报告与 judge.json 另列各臂 AI 判分与差（当前版 − 不装）。用户裁定后的样本按用户判法计入。备选：把 AI 判分并进用例分。用户可见：是。
9. 待审页上不显示样本来自哪一臂（盲判），也不显示评委理由以外的臂信息；报告与 judge.json 照记臂。备选：页上显示臂（审得快但带预期）。用户可见：是。
10. 优先级：分歧样本 10、抽检 20（票 08 集成口径「分歧样本 > 抽检 > 用例草稿 > 复盘候选」，票 11、12 往后排）。
11. 评委调用用 `--safe-mode`；评委的系统提示要求只输出 `{"verdict": "pass|fail|unclear", "reason": "…"}`。用户可见：否。
12. 续跑时没有 judge.json（首跑在评委之前就断了），评委模型回落到配置或默认，首跑命令行的 `--judge-model` 记不下来（检查点不记评委参数）。备选：检查点加字段（要动 resume.py）。用户可见：是，但只在「首跑传了 --judge-model 又断在评委之前」时。

**需主会话在 spec 登记（本票未改 spec，免得与同批票冲突；集成时已登记进 spec 第四节）**：`judge.json` 结构、`judge-config.json`、`gold/<id>.json` 字段、用例 `judge/` 子目录、`run.json` 的 `judge` 字段（summary）与 `judge_model` 取实际所用模型；实施待定第 7 条「金标一致率阈值与启用条数」现为配置项、默认留空。

**已知缺口与扩展点**

- 金标判一遍、样本判两遍都是串行于各臂之后；评委并发数沿用 `-j`（上限 8）。
- ~~样本 id（`s-<10 位>`）只由「臂/用例/第几次/判定标准」算出~~：集成时改为按 `trace_dir` 哈希（见下方应修 B）。
- 金标的 `active` 字段留给票 10 条款退役时置 false；本票不处理条款 id 与金标的关联（判定标准还没挂条款 id）。
- 闸门（票 14）可读 `run.json` 的 `judge.trusted` 与 `judge.complete`；本票没有改闸门判据。
- 待审页的 HTML 渲染沿用票 08 框架，本票只在单测里检查页上文字，没有用浏览器打开 judge 项。
- Windows / Linux 未实测。

### 2026-10-15 A 批（09/10/12/14）集成定稿（集成分支 worktree-agent-aa78acdaffe679a6d，devkit-plugin-eval 0.3.0）

**主会话定稿口径（覆盖上面第 4、7、12 条）**

- 金标来源：分歧样本与抽检样本裁定后都存金标，`gold/<id>.json` 记 `source`（`disagreement` / `spot-check`）。一致率按来源分开记（judge.json 的 `gold.by_source`），判采信与否只用分歧来源的一致率。spec 2.4 已同步修订。单测 `test_spot_check_gold_does_not_count_toward_calibration`。
- 采信三态：`judge.trusted` 取 `true` / `false` / `null`。金标不足启用条数时为 `null`，报告写「采信（未校准）」。配置了校准、但因评委调用出错导致判成条数不足时，`gold.state=insufficient-errors`，运行判不完整（`complete=false`，原因进 `reasons`），可续跑。
- 闸门对 AI 判分不采信的已审报告照采信，并输出醒目提示「本报告 AI 判分不采信，已审时由用户判断」（`gate.JUDGE_UNTRUSTED_NOTE`）。
- 续跑：`--no-judge` 与 `--judge-model` 写进检查点 `environment.judge = {enabled, model}`，续跑时由 `resume.judge_opts_from` 读回。

**报告节顺序（集成定的）**：record.py 首段提示依次为注入核验 → 条款清单（票 10）→ AI 评委（本票）；report.md 末尾先放条款节，再放评委节。

**审查应修落地**

- A 续跑丢 `--no-judge` / `--judge-model`：见上。单测 `ResumeOptionsTest.test_no_judge_first_run_resume_does_not_judge`、`test_judge_model_from_first_run_kept_on_resume`。
- B 样本文件名改为 `samples/<臂>--<用例>--<trace_dir 哈希>.jsonl.gz`，金标 id 由 run_id 与 trace_dir 哈希算出；续跑按（trace_dir, 判定标准）匹配，沿用样本与裁定。单测 `test_gold_keeps_pointing_at_original_trace_after_resume`（改回按位置匹配后该单测失败，已反证）。
- C 见上面三态。单测 `test_calibration_short_because_of_call_errors_is_incomplete`。
- D 入库样本只保留 `assistant`（去掉 thinking 块）、`user` 的 tool_result、`result` 三类行，`system/init` 整行不入库。单测 `test_stored_sample_scrubbed_and_deterministic`。
- 顺手修：`--no-judge` 时 run.json 记 `judge={"skipped": "no-judge"}`、报告写「按 --no-judge 跳过」、不读 judge-config.json；首段「判分：」一行按实际改写；续跑后 usage 合并首跑沿用样本的数据。单测 `test_no_judge_flag_and_no_criteria_skip_judge`。
- 集成真跑发现：compare 收尾的终端行在 `trusted=null` 时打印「AI 判分不采信：None」，`--no-judge` 时会抛 KeyError；改由 `judgereport.console_line` 按三态与跳过打印。单测 `test_console_line_covers_three_trust_states_and_no_judge`。

**接票 10 的条款清单**：判定标准 frontmatter 加可选键 `clause: C001`，金标记下 `clause`。条款退役被确认时，该条款的金标置 `active=false`（`clauses._deactivate_gold`）；校准时也按 `clauses.retired_ids()` 排除。frontmatter 未知键、`arms` 里的未知臂名：compare 开跑前报错（`judge.check_criteria`）。`rule` 指向的 grader 不存在、条款不在清单里或已退役：记进 judge.json 的 `warnings`，报告「### 判定标准告警」逐条列出。单测 `CriteriaAndClauseTest`、`test_bad_frontmatter_aborts_before_any_eval`。

**集成真跑（2026-10-15）**：devkit-discipline 4.1.0 副本（放在 /tmp 下、不受版本控制的目录，上一版臂因此按「不在 git 仓」退化），用例 `decision-no-ask`、`dispatch-model`，`--runs 1`，`decision-no-ask` 加两条判定标准（`asked-via-tool` 带 `rule` 与 `arms`、`leaves-decision-to-user` 带 `clause: C001`）。运行 `20261015T143739Z-4.1.0-compare`：评委 4 个样本各两遍（8 次调用），分歧 2、抽检 2、出错 0，`trusted=null`（未配置校准）、`warnings` 1 条（C001 尚无清单可核对）；条款清单首次抽取 99 条待确认；待审页 6 项（报告审阅 1、分歧 2、抽检 2、条款清单 1，无复盘类型）。AI 构造回复码 `2B 3B 4A 5A 6B`（不勾报告审阅）写回后读回：4 个金标（`source` 分歧 2、抽检 2，抽检那两条 `clause=C001`），`clause-check.json` 与 run.json 的 `status=rejected`，报告改写为「条款清单变更已打回」。摘要 run.json、report.md 在 `.scratch/devkit-plugin-eval/demo-integ-A/`（写回后的版本；裁定是 AI 演示，不是用户审阅；金标与样本未入库）。花费（标价估算）：eval $0.77、评委 $0.47、条款抽取 $0.86。

**暂定口径（待主会话复核）**

1. 没配置校准（阈值或条数留空）时同样 `trusted=null`、报告写「采信（未校准）」，与「不足启用条数」同态。备选：未配置时记 `true`。理由：没校准就不该声称已采信。可回退：改 `judge.run` 里 `trusted` 的取值一处。用户可见。
2. frontmatter 未知键、未知臂名直接拒绝开跑；grader 名不存在只告警。理由：前两者是格式写错，跑了也白跑；grader 名要等各臂跑完才知道存不存在。备选：都只告警。用户可见。
3. 两遍都判「判不了」算分歧（上面第 3 条），已登记进 spec Comments。
