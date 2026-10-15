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

### 暂定口径（待主会话复核）

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
