# 11 — 用例草稿流与基线已满足

Status: resolved

**What to build:**

用例一律先成为**用例草稿**，用户勾选通过才跑：

- AI 按条款清单（及 skill、agent 定义）起草用例，写进插件目录外的 `drafts/`（放 `evals/` 下会被 eval 当正式用例跑）。每类数量：纪律每条可判条款 1 例；skill 每个应触发 2、不应触发 2；agent 每个该派 1、不该派 1、照定义做事 1；文风可机械判定规则每条 1 例、易读性与信息不丢共用 2～3 个固定场景。用例用 `tags` 挂条款 id。
- 草稿进待审页（每页 ≤ 10 个，按优先级分批：已证明有差、复盘已命中的条款先审）；勾选通过的移到 `<plugin>/evals/`，未审条款在报告列「无用例」、不算失败。
- **基线已满足**：新用例先在不装臂跑 3 次，≥ 2/3 通过的打 `tags` 标记，只作回归守护（只比上一版不退化）；要量差时起草诱导用例（任务压力、诱人捷径、长任务稀释，每条款 ≥ 2 种手法），起草者只看条款意图、不看注入原文。
- 10 产出的退役改挂建议接进草稿区：挂在退役 id 上的用例退回草稿、附建议。
- 迁历史素材进草稿：plugin-eval probe 的「派发带 model」「并发检索」两例；zh-disambiguate 的 3 例改写成 eval 格式。

**Blocked by:** 08, 10


- [x] 对 devkit-discipline 起草第一批草稿，待审页一次出 ≤ 10 个，勾选通过的出现在 `evals/` 且能被 eval 直接裸跑
- [x] 草稿不参与任何对照运行
- [x] 一条新用例在不装臂 ≥ 2/3 通过时被标基线已满足，报告对它只出回归结论、不出相对不装的差
- [x] 历史素材 5 例已进草稿区
- [x] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的「2.3 用例从哪来」；[17](../../plugin-eval/issues/17-case-sourcing.md)；[11](../../plugin-eval/issues/11-judging-and-human-checkpoints.md) 第 4 条

## Comments

### 实现摘要（2026-10-15，worktree-agent-acb55ec5550de5e61）

- 提交：`8252f2a`（功能）、`d859f72`（历史 5 例迁入草稿区）、`7e2c68f`（只写 `max: 0` 的 grader 必须补 `min: 0`）、`bcd1928`（回归守护改为比上一版）。版本号未动（0.3.0）。
- 新模块（`plugins/devkit-plugin-eval/scripts/plugin_eval_lib/`）：
  - `drafts.py`：草稿区 `plugin-evals/<plugin>/drafts/<slug>/`（eval 原生用例目录 + `draft.json` 元数据）、退役改挂同步 `sync_rehang`（消费票 10 的 `clause-rehang.json`）、优先级四档、待审页类型 `case-draft` / `case-draft-delete`（priority 300，`kinds={'drafts'}`）、`drafts write|page|list|sync` 子命令。
  - `drafter.py`：按条款清单与 skill / agent 定义找缺口、调 `claude -p`（默认 `claude-fable-5-1`，`--model` 可改）起草、校验后写进草稿区；判为离线评不了的条款记进 `draft-skips.json`；`--clauses` 指定条款时起草诱导用例。
  - `casefiles.py`：spec → eval 原生用例文件（prompt.md / case.yaml / graders / judge / scaffold.sh）、加载前检查、tags 改写、judge 的 clause 改挂。
  - `baseline.py`：`baseline <plugin>` 子命令在不装臂跑 3 次判基线已满足，记录在 `plugin-evals/<plugin>/baseline.json`，打 `baseline-satisfied` tag；对照时 `apply_to_record` 把这些用例剔出总体差，另出「回归守护」一节。
- 共享文件只做接线：
  - `cli.py`：注册 `drafts`、`baseline` 两个子命令。
  - `pending.py`：`RUN_KINDS` 加 `drafts`，使不带 `--run` 的 `pending` 能选中草稿运行。
  - `gate.py`：`SKIPPED_KINDS` 加 `drafts`、`baseline`，这两类运行不出门禁结论。
  - `compare.py`：import `drafts`（注册待审项类型）与 `baseline`；写 record 字段后调 `baseline.apply_to_record`。
  - `record.py`：差那一行注明「不含 N 个回归守护用例」，逐用例差一列显示「回归守护」，插入回归守护一节。
  - `clause_ai.py`：`claude_caller` 加可选 `system_prompt`。`clauses.py`：`case_tags` 取 case.yaml 与 prompt.md 两处 tags 的并集。
- 全量单测 477 个通过（新增 test_drafts 12、test_baseline 6、test_casefiles 8）；`node scripts/check-versions.js` 通过。

### 验收证据

演示仓是本分支的克隆，按 demo-10 复刻了「在飞上限 16→8」与已确认条款清单；产物摘要在 `../demo-11/`（run.json、report.md、baseline.json、draft-skips.json、clause-rehang.json、通过的用例 `evals-approved/`、演示结束时的草稿区 `drafts-after/`）。待审页的裁定由 AI 代为给出，只演示写回链路，不是用户审阅。

1. 起草与待审页：
   - `drafts sync` 把挂退役 C007 的 `evals/inflight-cap` 退回草稿区并改挂 C100（clause-rehang.json 里该建议标 `moved`）。
   - `drafts write --limit 12`（Fable，3 次调用，$1.4707）：先给历史 2 例挂条款（dispatch-with-model→C093、parallel-lookup→C087），再写出 4 个草稿（C001、C002、C005、C011），8 条记为离线评不了。
   - 第一页 `../demo-11/runs/20261015T153942Z-4.1.0-drafts/report.md` 10 项：第 1 项是已证明有差的 dispatch-with-model（probe Δ=+0.67），第 2 项是退役改挂的 inflight-cap。
   - 回复码 `1A 2B 3A 5A 6B 7A` 后 4 个用例移进 `evals/`，2 个打回。
   - 裸跑 `claude plugin eval <插件目录> --ablation none --runs 1` 4 个用例都加载并跑完（约 $0.65）。
   - 第二页 `../demo-11/runs/20261015T154630Z-4.1.0-drafts/report.md` 3 项，已通过和已打回的不再上页。
   - 单测：`test_page_limit_priority_and_writeback`、`test_unlinked_and_broken_drafts_stay_off_page`、`test_sync_moves_retags_and_marks_suggestions`。
2. 草稿不进对照：演示 compare `20261015T154410Z-4.1.0-compare` 的 run.json `cases` 只有 evals 里的 4 例。eval 只扫插件目录下的 `evals/`，草稿区在插件目录外；单测 `test_drafts_never_reach_any_arm` 覆盖插件在 `plugins/` 下与插件在仓根两种布局。
3. 基线已满足：
   - `baseline devkit-discipline`（$1.1168，`../demo-11/runs/20261015T154243Z-4.1.0-baseline/report.md`）：grep-then-targeted-read、parallel-lookup 3/3 → 打 tag；dispatch-with-model、zero-hit-verify-search 0/3 → 未满足。
   - compare（$1.7306）报告：总体差 +0.33「不含 2 个回归守护用例」，逐用例差一列对这两例显示「回归守护」，回归守护一节两例都是「守住」（当前版 1.00，上一版 4.0.0 1.00）。
   - 单测：`test_two_of_three`、`test_tags_satisfied_case_and_records_verdict`、`test_compare_reports_regression_only_for_satisfied_cases`、`test_compares_with_previous_then_falls_back`。
   - 演示 compare 跑在回归判据修改（`bcd1928`）之前，report.md 是用同一份 run.json 按新判据重算后重新渲染的；两例在新旧判据下都是「守住」。
4. 历史 5 例：`plugin-evals/devkit-discipline/drafts/` 下 dispatch-with-model、parallel-lookup、zh-audit-executor、zh-audit-scope、zh-rewrite-keeps-meaning，单测 `RepoHistoryDraftsTest` 校验全部可被 eval 加载。
5. 本票只改了 `plugins/devkit-plugin-eval/scripts/` 与 `tests/`，动手前已用 Skill 工具读 `mattpocock-skills:writing-for-agents`、`skill-creator:skill-creator`；plugin-dev 追加表不涉及这两个目录。

诱导用例另跑了一次：`drafts write --clauses C001,C087 --no-page`（$1.0020），两条款各 2 例，手法为 task-pressure 与 long-task-dilution。

真实花费合计约 $5.97（起草 1.4707 + 裸跑约 0.65 + 基线 1.1168 + 对照 1.7306 + 诱导 1.0020，均为标价估算）。

演示中查出并修掉的 eval 行为：`tool_used` 的 `min` 缺省为 1，只写 `max: 0` 时显示「expected 1..0」，永远不通过。现在校验、加载前检查、起草三处都要求同时写 `min: 0`。

### 暂定口径（待主会话复核）

1. 用例草稿待审项优先级取 300。备选：与条款清单同档。理由：派发约定。用户可见：待审页排序。
2. 打回的草稿留在草稿区（`draft.json` 标 rejected），它挂的条款视为已有草稿，不再起草、不再上页。备选：打回后重新起草。理由：避免同一条款反复花钱起草同类用例。用户可见：报告里该条款仍列「无用例」。
3. 判为离线评不了的条款记进 `draft-skips.json`，之后不再重试；条款文字变了（换 id）才会重新进缺口。备选：每次都重试。理由：省钱，这类判断与模型无关。用户可见：`drafts list` 能看到。
4. 回归守护判据：有上一版臂时当前版分 ≥ 上一版分算「守住」；没有上一版臂时看当前版是否仍 ≥ 2/3 通过（「低于基线」）。备选：只看当前版是否 ≥ 2/3。理由：票原文「只比上一版不退化」。用户可见：报告回归守护一节。
5. skill 触发类 grader 写 `tool_used: Skill` 时显式加 `arm: both`（不写会被 eval 剔除不计分）。用户可见：用例文件。
6. 文风规则被起草者判为不能机械判定时，不单独起草，归入共用场景（2～3 个）。用户可见：草稿列表。
7. tags 由程序写入：类别 + 条款 id（skill / agent 用例写 skill / agent 名），起草者不自己写 tags。用户可见：用例文件。
8. 草稿运行（kind=drafts）与基线运行（kind=baseline）是独立运行种类，门禁跳过它们。用户可见：`runs/` 目录名后缀。

### 已知缺口

- 文风类场景（style / style-scenario）与 skill、agent 缺口没有在真实演示里跑，只有单测覆盖：缺口排序是条款在前、skill / agent 在后，演示 `--limit 12` 用完在条款上，zh-disambiguate 的应触发 / 不应触发缺口没轮到；devkit-discipline 没有 agent。
- 复盘已命中这一档依赖票 12 / 13 产出带 `clause_ids` 的复盘候选；目前读的是约定字段，没有真实数据。
- 演示待审页的裁定由 AI 代给，草稿内容未经用户审阅；演示仓的改动不入库，仓内 `evals/` 未新增正式用例。
- parallel-lookup 的 grader 用正则匹配 trace 文本，依赖 eval 当前 trace 格式。
- 诱导起草本次只出了两种手法（tempting-shortcut 未被选用），满足每条款 ≥ 2 种，但三种手法的分布未做约束。

### 留给 13 / 16 / 17 的接口

- 13：复盘候选写成草稿时 `draft.json` 的 `source='review-candidate'`、`clause_ids`；`drafts.create_batch(data_dir, name, now, drafting=..., limit=...)` 出待审页。
- 16：README / skill 要写的命令：`drafts write|page|list|sync`、`baseline`；`baseline.json` 记录格式；报告「回归守护」一节的读法。
- 17：首轮正式评测前先 `drafts write` → 审页 → `baseline` → `compare`；run.json 的 `rec['baseline']`（tag、cases、rule、regressed）与 `delta.excluded_baseline_satisfied`；退役改挂走 `drafts sync`。
