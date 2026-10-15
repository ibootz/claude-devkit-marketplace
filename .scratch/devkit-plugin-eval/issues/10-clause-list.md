# 10 — 条款清单：抽取、过期判定与退役

Status: resolved

**What to build:**

注入类插件按**条款**评。本票交付条款清单的整个生命周期：

- **抽取**：AI 从被测插件的注入文本拆出可单独判定的条款，每条一个稳定 id、一句判定标准；清单存被测插件仓的 `plugin-evals/<plugin>/` 下，记下抽取时的**注入文本指纹**；整份清单在待审页作 1 项确认。
- **注入文本指纹**：在真实 HOME、空临时 cwd 下执行全部注入 hook，取输出文字算指纹（不复用前置检查的空 HOME 冒烟）。
- **过期与增量重抽**：对照第一步比指纹；变了则 AI 只读旧清单加新旧注入文本差异，产出清单变更（新增、改写、退役），进待审页算 1 项；未确认前对照照跑，新条款列「无用例」，报告标「条款清单待确认」。
- **退役**：id 绑判定标准不绑措辞、永不复用；拆分、合并按「旧 id 退役 + 新 id」；退役条款留在清单里并写替代 id；挂在退役 id 上的用例退回草稿区附改挂建议（草稿区由 11 提供，本票先产出改挂建议清单）；金标停用不删。
- `run.json` 记本次所用条款清单指纹。

**Blocked by:** 08


- [x] 对 devkit-discipline 抽出条款清单，待审页确认后落盘，清单含 id、判定标准与注入文本指纹
- [x] 不改注入文本再跑对照，不重抽、不产生待审项
- [x] 改一句注入文本再跑对照，只产出增量变更 1 项；未确认时报告标「条款清单待确认」
- [x] 构造一次拆分，旧 id 标退役并写替代 id，旧 id 不再被分配
- [x] 注入文字含时间等每次都变的内容时有归一化处理，不会恒判过期（以一个构造用例证明）
- [x] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的「2.2 离线对照（compare）」第 2 步、「2.3 用例从哪来」条款清单段；[20](../../plugin-eval/issues/20-clause-list-lifecycle.md)；[17](../../plugin-eval/issues/17-case-sourcing.md) 第 2 条

## Comments

### 实现摘要（2026-10-15，worktree-agent-aa79f3de4e2d06ff9）

- 新模块：`scripts/plugin_eval_lib/clauses.py`（指纹、清单读写、id 分配、提案、待审页类型 `clause-list`、`clauses` 子命令）、`clause_ai.py`（`claude -p` 调用、两份 JSON schema、结果校验）、`clausereport.py`（报告首段提示与「## 条款清单」一节）；测试 `tests/test_clauses.py` 21 个。
- 共享文件只做接线：`compare.py` 在第一次写检查点之后调 `clauses.check_for_run`，`finalize_run` 补 `clauses.record_fields`；`record.py` 渲染两处调用 `clausereport`；`cli.py` 加 `compare --clause-model` 与 `clauses` 子命令。pending.py、resume.py、scoring.py 未改。
- 注入文本指纹复用 `injection.load_hook_specs` / `run_hook` 与 `preflight._plugin_copy`：真实 HOME、空临时 cwd、插件副本，SessionStart / UserPromptSubmit / SubagentStart 各执行两次，归一化后按（事件, 文字）去重排序算 sha256。
- 全量单测 307 个通过；`node scripts/check-versions.js` 通过；版本号未动（0.2.0）。

### 验收证据

1. 抽取并落盘：真实演示 `clauses devkit-discipline`（Fable）抽出 99 条，待审页回 `1A` 后写入 `clauses.json`（每条 id、criterion、events，顶层 injection_fingerprint）。摘要见 `../demo-10/20261015T123610Z-4.1.0-clauses/` 与 `../demo-10/clauses.json`。单测 `LifecycleTest.test_extract_confirm_writes_list_with_ids_criteria_fingerprint`、`test_no_list_compare_extracts_and_report_lists_new_clauses_without_cases`。
2. 不改文字再跑：真跑 compare `20261015T123838Z-4.1.0-compare`，clause_check.status=up-to-date，未调 AI，待审页只有报告审阅 1 项。单测 `test_unchanged_text_compare_does_not_reextract_or_add_pending_item`；续跑不重抽见 `test_resume_keeps_clause_check_without_reextracting`。
3. 改一句再跑：把演示副本里「在飞上限 16」改成 8，真跑 compare `20261015T123944Z-4.1.0-compare`：增量变更 1 项（C007 以 criterion-changed 退役，新增 C100），报告首段有「条款清单待确认」，C100 列「无用例（新条款，清单待确认）」；回 `2A` 后清单 100 条、C007 为 retired。单测 `test_one_sentence_change_yields_one_incremental_item_and_banner`、`test_unconfirmed_proposal_is_reused_not_reextracted`。
4. 拆分：真实 AI 两次都没产出 split（第二次改成「前台 8、后台 4」仍判 criterion-changed，已打回），本条靠单测构造：`test_split_retires_old_id_with_replacements_and_never_reallocates` 断言旧 id 状态 retired、retire_reason=split、replaced_by 为两个新 id，`allocate_ids` 不再分配旧号，改挂提示里的临时引用 N1 映射为 C003；`test_reject_keeps_list_and_next_run_reextracts_with_fresh_ids` 断言打回后新提案用全新 id。
5. 归一化：`NormalizationTest.test_volatile_content_does_not_change_fingerprint` 用 hook 输出附带时间戳、UUID、日期构造，两次执行指纹相同、与清单一致不判过期；输出不可归一的随机数时判 unreliable、不判过期（`test_unnormalizable_randomness_marks_unreliable`）。
6. 技能：动笔前已用 Skill 工具读 `mattpocock-skills:writing-for-agents`、`skill-creator:skill-creator`；本票写的路径是 `scripts/**`、`tests/**`，不命中 plugin-dev 追加表。

### 已知缺口

- 「挂在退役 id 上的用例退回草稿区」只产出改挂建议 `plugin-evals/<p>/clause-rehang.json`，真正挪进 drafts/ 由票 11 实现。
- 「金标停用不删」只提供 `clauses.retired_ids()`，由票 09（AI 评委）消费。
- 闸门对「条款清单已过期」的提示（建议跑对照）留给票 14。
- 条件注入（空 cwd 下没有输出的 hook）的文字改了不会判过期，报告里列出这些 hook。
- 演示里的「确认 / 打回」由 AI 代回复码，不是用户本人裁定。
- 第 3 步演示的提案生成于 ref 映射修复之前，其 rehang_hint 文字里仍有「N1」；修复后由单测覆盖。

### 已定（2026-10-15 主会话复核）

审查判合理的照现状保留。第 3 条被下方「A 批集成定稿」改写；第 8、9、14 条的缺陷（审查应修 1、3）已修。

1. 清单文件 `plugin-evals/<p>/clauses.json`，id 格式 `C%03d`（超过 999 自然变长），取历史最大号加一，扫描清单与所有 `runs/*/clause-proposal.json`，打回的提案用过的号也不复用。备选：UUID 短码。理由：人读、报告列宽小。用户可见。
2. 抽取模型默认 Fable（`claude-fable-5-1`），`compare --clause-model` / `clauses --model` 可改。备选：Sonnet。理由：简报「AI 评委默认最贵档」同口径。用户可见。
3. 新增单跑子命令 `clauses <name>`，只有出了变更才建 `runs/<ts>-<version>-clauses/`（kind=clauses）并生成待审页。`pending` 不带 `--run` 时找不到这类运行，要带 `--run`。备选：只在 compare 里抽。理由：首次抽取不必陪跑整轮对照。用户可见。
4. 指纹只认（事件, 文字），不含命令行与 matcher。备选：连 hooks.json 一起算。理由：spec 写「取输出文字算指纹」。用户不可见。
5. 每条 hook 执行两次，失败或两次不一致判 unreliable，本次不判过期、不重抽，报告首段提示。备选：只跑一次。理由：防易变内容恒判过期。用户可见。
6. 归一化规则 `injection-text-v1`：UUID、日期时间、中文日期、日期、时刻、以 1 开头的 10/13 位时间戳、16 位以上小写十六进制换占位符；插件副本路径换 `${CLAUDE_PLUGIN_ROOT}`，临时目录换 `<HOOK_TMP>` / `<TMP>`，HOME 走 `record.scrub_home`。用户不可见。
7. AI 调用失败（含限额）不中止对照，status=ai-error，报告首段写「已过期，重抽失败」，下次对照再试。用户可见。
8. 未裁定的提案若基于同一份清单、指向同一新指纹，下次对照直接复用，不重抽。用户可见（报告写「沿用运行 …」）。
9. 打回后清单不改，下次对照重新抽，新条款用全新 id。用户可见。
10. AI 判「无条款变更」但指纹变了时也出 1 项待审（确认后只更新清单记录的指纹与快照）。备选：自动静默更新指纹。理由：清单变更一律过人。用户可见。
11. run.json 新增 `clause_check`（clause-check.json 原样搬入），与 `clause_list_fingerprint` 并列。需登记进 spec 的 run.json 字段表。用户不可见。
12. 清单旁存注入文本快照 `clauses-injection.txt`，增量重抽靠它做差异；运行目录另存本次快照 `clause-injection.txt`。用户不可见。
13. 单跑 `clauses` 不做全量前置检查。理由：只执行注入 hook、不起 eval。用户不可见。
14. 报告首段「条款清单待确认」放在注入核验提示之后；确认 / 打回后改写为「条款清单变更已确认（时间，UTC）」/「已打回」。用户可见。

### 2026-10-15 A 批（09/10/12/14）集成定稿（集成分支 worktree-agent-aa78acdaffe679a6d，devkit-plugin-eval 0.3.0）

**主会话定稿口径（覆盖上面第 3 条）**

- `clauses` 子命令保留，只在该插件尚无 `clauses.json` 时执行；已有清单时拒绝，提示「已有条款清单，重抽是跑对照的第一步，请改跑 compare」（`clauses.EXISTING_LIST_MSG`）。spec 第四节已登记运行目录 `-clauses` 后缀与 `kind=clauses`。
- `pending` 不带 `--run` 时也会选中 `kind=clauses` 的运行，并在「更早运行」里列出（`pending.RUN_KINDS`）；第 3 条里「要带 `--run`」不再成立。单测 `test_pending_without_run_picks_clauses_run_and_lists_it_as_earlier`。
- gate 扫运行记录时跳过 `kind=clauses`（`gate.SKIPPED_KINDS`）。单测 `GateIntegrationTest.test_clauses_runs_are_skipped`。

**审查应修落地**

1. （已被下方「A 批集成审查修订」覆盖，此条口径作废）被打回的提案不再复用：任一运行对同一组（基线清单指纹、新指纹）记过 `rejected`，`find_reusable` 就返回空。单测 `test_rejected_pair_is_never_reused_even_if_another_run_has_it_pending`。
2. 清单 JSON 损坏不中止对照：`check_for_run` 的异常分支不再读清单，`list_fingerprint` 记 None；`used_ids` 同样容错。单测 `test_corrupt_list_does_not_abort_compare`。
3. 裁定时同步改 `clause-check.json` 的 `status`（`confirmed` / `rejected`），报告渲染也看 `decision`，重渲染不再退回「待确认」。单测 `test_extract_confirm_writes_list_with_ids_criteria_fingerprint` 的 status 断言。
- 顺手修：判 hook 失败的口径与 `injection.run_hook` 一致，只有超时或退出码 2 算失败，非 0 退出码但有输出仍算注入。单测 `test_nonzero_exit_with_output_still_counts_as_injection`。

**与 09、12 的接线**：条款退役被确认时，把挂在该条款上的金标置 `active=false`；票 12 的复盘只认 `status=active` 的条款，按 `events` 推映射。

**给票 15**：「注入文本指纹变了 → 建议跑对照」可复用 `clauses.capture_injection` 取当前注入文字与指纹，与 `clauses.json` 的 `injection_fingerprint` 比。

本票集成时没有新增暂定口径。

### 2026-10-15 A 批集成审查修订（集成审查结论「修后合并」，同一集成分支）

**覆盖上面「审查应修落地」第 1 条**：原写法「任一运行对同一组（基线清单指纹、新指纹）记过 `rejected`，`find_reusable` 就返回空」已作废，原单测 `test_rejected_pair_is_never_reused_even_if_another_run_has_it_pending` 已删除。原写法的问题：打回一次之后，连重抽出的新提案也不再复用；用户确认之前每跑一次 compare 都会重调 AI（首次整份抽取每次约 $0.86）、多耗一批条款 id、多出一个待审项。

**现行口径**：打回只作废被打回的那一份提案。按提案的 `created_in_run` 认份：沿用某份提案的运行会把它抄进自己的目录，`created_in_run` 不变。`find_reusable` 先收集所有被打回提案的 `created_in_run`，跳过 `created_in_run` 落在这个集合里的运行（沿用了被打回提案的运行也一并跳过），其余照常返回最新的待确认提案。单测：

- `test_rejected_proposal_is_not_reused_via_a_run_that_copied_it`：A 抽出提案 → B 沿用 A → 在 B 的页上打回 → C 不再从 A 沿用，重新抽（原审查的 A/B/C 场景，`find_reusable` 返回 None）。
- `test_reextracted_proposal_after_reject_is_reused`：R1 打回 → R2 重抽出新提案 → R3 沿用 R2，不调 AI。

**已知缺口（新增，记录不修）**

- 重复建运行（审查 H）。首次抽取还没裁定时，再跑一次 `clauses` 子命令，会另建一个 `-clauses` 运行目录，并沿用同一份提案，待审页上因此出现两份相同的条款清单项。在其中一页确认后，另一页的条款项会因清单已变而作废，不会写错清单，只是多一页要看。后续修法：`clauses` 子命令发现有可沿用的待确认提案时，直接提示去哪一页裁定，不新建运行。
