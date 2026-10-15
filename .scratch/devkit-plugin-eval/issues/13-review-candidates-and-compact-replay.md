# 13 — 复盘候选转草稿与 compact 后回放用例

Status: resolved

**What to build:**

把会话复盘发现的问题变成可跑的用例：

- **候选转草稿**：用户勾选的复盘候选，由 AI 现读本机 jsonl，改写成合成 prompt：保留触发违规的结构，换掉项目名、路径与业务内容；上下文裁到触发轮之前 ≤ 2 轮作 `context.history_file`，需要的文件用 `context.scaffold_script` 生成合成桩。产物进草稿区，走 11 的勾选流程。原文已过本机保留期的候选标作废。
- **compact 后回放用例**：每个注入插件挑 ≤ 3 条高风险条款，合成回放会话（`compact_boundary` + 模板化摘要 + 1～2 轮尾巴 + 被测 prompt）。合成历史**不放被测插件的注入文本**；回放子会话写进用例目录的转录在臂组装目录里清理掉。

**Blocked by:** 11, 12


- [x] 一条勾选的复盘候选被改写成草稿，草稿里不含原会话的项目名、路径与业务内容
- [x] 过了保留期的候选被标作废、不生成草稿
- [x] 为 devkit-discipline 生成 ≤ 3 个 compact 后回放用例，在不装与当前版两臂都能跑出分数
- [x] 合成历史里搜不到被测插件注入文本
- [x] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的「2.3 用例从哪来」复盘候选与 compact 段；[17](../../plugin-eval/issues/17-case-sourcing.md) 第 3、4 条；[19](../../plugin-eval/issues/19-probe-history-file-replay.md)（history_file 格式与约束）

## Comments

### 2026-10-15 来自 A 批集成审查（审查 C）：别依赖复盘候选的 `clause_ids`

票 12 的复盘候选几乎全部是「未映射」，`clause_ids=[]`，原因见票 12 的 Comments「A 批集成审查修订」一节。条款的 `events` 只有三个常驻注入事件，拦截类候选的脚本多半挂在 PreToolUse 上；就算挂在常驻事件上，也会同时撞上几十条条款。

约束（集成审查结论）：本票的实现不能依赖复盘候选的 `clause_ids`。

建议（未拍板，实现本票时再定）：

- 「候选转草稿」时，草稿要挂哪条条款，由改写时的 AI 按触发内容判断，或在用户勾选时指定。
- 「compact 后回放用例」挑高风险条款时，直接从 `clauses.json` 的未退役条款里挑，不经过复盘候选的映射。

### 2026-10-16 实现完成（C 批，第 1 层子代理）

#### 实现摘要

新增两个模块，都挂在 `drafts` 子命令下，产物进草稿区，走票 11 的待审页：

- [replay.py](../../../plugins/devkit-plugin-eval/scripts/plugin_eval_lib/replay.py)：`drafts compact <插件> [--clauses C001,…] [--limit N] [--model M] [--no-page]`。
  - 从 `clauses.json` 的未退役条款里挑高风险条款，每插件合计 ≤ 3 个。不经复盘候选的 `clause_ids`。
  - 有底本时，把底本用例原样拷过来：evals/ 优先，其次未打回的草稿，文件桩与 judge 照带。
  - 没有底本时，由 AI 起草被测 prompt 与 grader，复用 drafter 的提示词与校验。
  - 两种做法都会套一份合成历史，写成 `history.jsonl` 与 `case.yaml` 的 `context.history_file`。合成历史 = `compact_boundary` + 模板化摘要（虚构项目 pagelint）+ 两轮固定尾巴，uuid 用 uuid5，可复现，不带 cwd。
  - 写盘前与被测插件当前注入文字比对，去空白后逐字重合 ≥ 20 字即整条不写。注入文字取不到时拒绝生成。
- [candidate_drafts.py](../../../plugins/devkit-plugin-eval/scripts/plugin_eval_lib/candidate_drafts.py)：`drafts from-review <插件> [--date YYYY-MM-DD] [--model M] [--no-page]`。
  - 处理对象：复盘结果里 `selection=draft` 且还没转过的候选。
  - 定位会话：按指针（新到旧）现读本机会话 jsonl，指针字段先过票 12 的白名单，防路径穿越。
  - 片段：触发记录沿 parentUuid 往回，到凑够 2 轮用户发言为止，只在内存里交给 AI 改写。默认模型 Fable，`--model` 可改。
  - 改写结果：被测 prompt + ≤ 2 轮合成历史，compact 之后的候选另带合成摘要；需要的文件用 `scaffold_files` 生成文件桩。条款由 AI 从有效条款里判（≤ 2 个），判不出就不挂。
  - 写盘前跑隐私自检（见暂定口径 9），不过就整条不写。
  - 结果写回该候选的 `conversion`，与待审页写回、review 重跑用同一把锁。
- 回放转录：`compare._run_arm` 跑完每臂，就把回放用例目录里的 `<历史 sessionId>.jsonl` 与同名目录移出组装目录，存进本臂的 trace 目录 `replay-transcripts/<用例>/`。trace 目录在用户级数据目录里，不进被测仓。gate、baseline、续跑都走 `_run_arm`，一并覆盖。

#### 共享文件改动（只做接线）

- `casefiles.py`：spec 新增 `history_file` + `history_text` 两个键，`render_case` 写进 `case.yaml` 的 context。`check_case_dir` 查三件事：history_file 是否为用例目录内的普通文件、是否有 prompt.md、`..` 路径与软链接一律不过。
- `drafts.py`：
  - `SOURCES` 加 `compact-replay`。
  - `CATEGORIES` 加 `compact-replay`、`review-replay`；其中只有 `compact-replay` 进 `CLAUSE_CATEGORIES`，`review-replay` 不挂条款也能上页。
  - 子命令 action 加 `compact`、`from-review`，并加 `--date` 选项。
  - 待审页事实栏加「compact 回放」「复盘候选」两行。
- `compare.py`：`_run_arm` 里调一行 `replay.purge_transcripts`，打一行日志。
- `review.py`：同一天重跑时带上 `conversion`；跨日期只带 `drafted`，防止重复改写。
- `review_clauses.py`：**修了票 12 的一个缺陷**，是本票真跑撞到的。多条条款同挂一个事件时，未映射原因会把条款 id 全列出来。99 条时超过 `LONG_TEXT_LIMIT`（300 字），复盘自检整批拒写，`review` 对 devkit-discipline 完全跑不出结果。现在改为只列前 8 个加「等」，并补了回归单测。

#### 新增字段登记（spec 第四节由集成者补）

- `draft.json` 新增字段：
  - `replay`：`base_case`、`summary_template`、`tail_turns`、`history_file`、`history_session_id`、`injection_overlap_chars`、`injection_hits`、`selection_reasons`。复盘改写的草稿取其中的子集，另有 `history_turns`、`compact`。
  - `review_candidate`：`review_date`、`candidate_id`、`kind`、`rule`、`after_compact`。
  - `clause_reason`：改写 AI 给的挂条款理由。
  - `clause_hint`、`exported_from`：只出现在本仓入库的 3 个演示草稿里，见暂定口径 7。
- `source` 新值：`compact-replay`。复盘改写用已有的 `review-candidate`。
- `category` 新值：`compact-replay`、`review-replay`。
- 复盘结果 `candidates[].conversion`，形态 `{status, code?, draft?, clauses?, findings?, problems?, at}`：
  - `status` 取 `drafted`、`void`、`skipped`、`privacy-rejected`、`invalid`、`error`。
  - 前三种是终态，不再处理；后三种下次 `from-review` 会重试。
  - `void` 的 code 取 `past-retention`、`file-gone`、`record-gone`、`no-pointer`。
  - `skipped` 只记枚举码，不记 AI 的自由文字（复盘结果会入库）。
  - `findings` 只记命中类别与个数，不记原文。
- 环境变量 `PLUGIN_EVAL_PRIVATE_TERMS`：逗号分隔的用户私有词，不区分大小写，只在隐私自检里用。

#### 验收证据

演示摘要见 [demo-13](../demo-13/README.md)。命令都在临时克隆里跑，数据目录是临时目录。

1. **候选改写成草稿、不含原会话内容**：
   - 真跑：`drafts from-review devkit-discipline --date 2026-10-16`，候选 `c-a3c987f89a77` 改写成 1 个草稿，花费 $0.6004。
   - 隐私：自检通过；另对草稿目录按派发简报规定的隐私检索词（公司与项目名、家目录路径、邮箱形态）检索，0 命中。草稿不入库。
   - 单测：`ConvertTest.test_draft_and_void` 断言原会话的用户原话、项目名、分支、主机名、命令里的路径都不在盘上。`PrivacyTest` 覆盖八类拒写：项目名、分支、主机名、路径、邮箱、逐字重合、用户自配私有词、findings 不带原文。
2. **过保留期作废**：
   - 真跑：候选 `c-0b91af60cf02` 的指针被人为改成不存在的会话 id，结果 `void/file-gone`，不调 AI、不出草稿。
   - 单测：另覆盖 `past-retention`（时间早于 cleanupPeriodDays）与 `record-gone`。
3. **≤ 3 个 compact 用例、两臂出分**：
   - `drafts compact` 生成 3 个，花费 $0.8985。待审页（AI 代答）通过后跑了两次 compare：
     - `20261015T171854Z-4.1.0-compare`：不装 0.78 / 当前版 1.00，花费 $2.2123，条款增量重抽另 $0.2920；
     - `20261015T172640Z-4.1.0-compare`：单用例，不装 0.33 / 当前版 1.00，花费 $0.7410。
   - 3 个用例拷回本仓 `plugin-evals/devkit-discipline/drafts/compact-*`。
4. **合成历史里没有注入文本**：入库的 3 份 history.jsonl 与 devkit-discipline 当前注入文字（11551 字）比对，三项都是 0：
   - 逐字重合 ≥ 20 字：0；
   - 逐字重合 ≥ 10 字：0；
   - 注入行原样出现：0。

   第二次 compare 移出的回放转录中，SessionStart 记录数：不装 0 条，上一版 3 条，当前版 3 条。注入是 hook 在回放时现注入的，不来自历史。
5. **读技能**：已用 Skill 工具真实调用 `mattpocock-skills:writing-for-agents` 与 `skill-creator:skill-creator`。本票只改 `scripts/`、`tests/`，不涉及 plugin-dev 的组件规格。

单测：`python3 -m unittest discover -s tests` 全过。新增 `tests/test_replay.py`（19 个）与 `tests/test_candidate_drafts.py`（23 个），夹具全部是合成数据。

#### 已定（2026-10-16 主会话复核）

第 2、10 条按 C 批集成定稿第 4、3 条改写过（见下方「C 批集成」一节）；其余照实现时的原样保留。

1. **高风险条款排序**（用户可见：`compact` 输出逐条打印选中理由）
   - 选了：已证明有差 → 复盘命中 → 事件含 SessionStart → 有现成底本 → 条款号。
   - 备选：只看 SessionStart；或复盘命中优先。
   - 理由：已证明有差的条款最值得回归。SessionStart 在真实长会话里只在开头与 compact/resume 时注入，之后不再重注，最易被稀释。有底本的不花钱。
2. **≤ 3 的计数**（可见）
   - 选了：evals/ 与草稿区里已有的 compact 回放用例都算，含已打回的。不点名时，已覆盖的条款（含已打回的）不重做；`--clauses` 点名时，挂着点名条款、已打回的回放草稿不算覆盖，会重写（C 批定稿 4，与 B 批定稿第 3 条一致）。配额满时提示写明「删除已打回的回放草稿目录可腾出名额」。
   - 备选：只算 evals/。
   - 理由：防止反复生成后被打回、再生成；点名是用户明确要重写。
3. **生成方式**（可见：草稿名与 `replay.base_case`）
   - 选了：有底本就拷，没有才 AI 起草；草稿名为 `compact-<底本名>` 或 `compact-<条款 id 小写>`。
   - 备选：一律 AI 重写。
   - 理由：底本已经审过，可比性好，也省钱。
4. **合成历史只用一份固定模板**（虚构项目 pagelint + 两轮尾巴，不按条款定制）
   - 可见：草稿内容。
   - 备选：让 AI 按用例场景写摘要。
   - 理由：模板可审、可复现，确定不含注入。代价见已知缺口 2。
5. **注入文本核对门槛**（不可见）
   - 选了：去空白后逐字重合 ≥ 20 字。注入文字取当前 hook 输出，取不到用条款清单快照，都没有则拒绝生成。
   - 备选：按行比对。
   - 理由：模板是中文散文，20 字窗口能挡住注入句子，又不会误伤常用词。
6. **回放转录的去向**（不可见）
   - 选了：从组装目录移到本臂 trace 目录，不删。
   - 备选：直接删。
   - 理由：保留排查依据，也是本票「转录确实写在用例目录、并已清出」的唯一证据。trace 目录本来就存转录，且不进仓。
7. **入库的 3 个演示草稿去掉条款 id**（可见）
   - 选了：tags 只留 `compact-replay`，judge 里的 `clause:` 行去掉，另记 `clause_hint`，写明 demo-10 清单里的哪条。
   - 备选：保留 demo-10 的 id。
   - 理由：本仓没有 `clauses.json`，id 只在 demo-10 那份清单里有意义，重新抽取后同号可能指别的条款。与仓里 history 草稿 `clauses: []` 的做法一致；生成正式清单后，`drafts write` 的挂条款步骤会重挂。
8. **复盘改写草稿的类别**（可见）
   - 选了：`review-replay`，不要求挂条款也能上页，优先档沿用票 11 的「复盘」档。
   - 备选：归入 discipline 并强制挂条款。
   - 理由：拦截类候选多半挂在 PreToolUse 上，未必对应注入条款（见上一节审查 C）。
9. **隐私自检的私有词来源**（可见：环境变量）
   - 选了：
     - 从这次会话本身取出的词：cwd 的项目名、家目录用户名、git 分支、片段里主机名与包名的非通用段；
     - 用户自配的私有词，两个入口取并集（C 批定稿 2）：环境变量 `PLUGIN_EVAL_PRIVATE_TERMS`，与数据目录下的 `private-terms.txt`；都为空时 stderr 与摘要各提示一行；
     - 固定形态：路径、邮箱（`example.invalid` 除外）；
     - 与原文去空白后逐字重合 ≥ 24 字；C 批起比对除 compact 边界标记外的全部片段（含工具输出、hook 报错、compact 摘要）。
   - 备选：把公司词硬编码进代码。
   - 理由：仓库公开，把词写进代码本身就是泄露，也过不了提交前的隐私检索。
10. **保留期判定**（可见：作废原因码）
    - 选了（C 批定稿 3）：按指针新到旧，先试读会话，读得到就照常改写，不论时间多早。读不到时才判作废：指针时间早于 `cleanupPeriodDays`（settings，缺省 30）记 `past-retention`；否则文件不在记 `file-gone`、记录不在记 `record-gone`。全部不可用时，用最新指针的原因码。
    - 备选：先按时间判，过期即作废。
    - 理由：用户可能调大过 `cleanupPeriodDays`，或旧会话被别处保留；读得到就有原文可改写，按时间先判会白丢候选。
11. **片段裁剪**（不可见）
    - 选了：每段截 1200 字，总长 12000，超出时丢最早的。
    - 理由：够还原触发情境，又控制送给 AI 的原文量。

#### 已知缺口

1. **回放用例的注入核验报「找不到子会话转录」**。
   - 原因：回放子会话的转录写在用例目录里，不在沙箱的 `projects/` 下。同一用例的多次 run 共用 `<历史 sessionId>.jsonl`，按 run 拆不开。
   - 现状：注入是否到达，目前只能人工数 `replay-transcripts/` 里的记录（演示已数）。要接进 `injection_check`，得按分支（parentUuid）拆 run，留给后续。
2. **固定摘要与被测 prompt 话题不连贯**：摘要讲 pagelint，被测 prompt 讲别的项目。它仍然算长历史稀释，但不像真实的同一会话。
3. **隐私自检是启发式的**：换了说法的业务内容查不出来。演示产出的那份草稿里有一套文档核对场景，像是从原会话的任务结构改写来的；没有逐字重合，但人审时要留意。真正的闸门是待审页上的人工审阅。
4. ~~**README 没写两个新子命令**~~：C 批集成已补 README 与 spec 第四节。
5. **L2 注入核对只覆盖三个常驻事件**（C 批集成审查）：PreToolUse 拦截时输出的文案不在比对范围内，换了说法的规矩也查不出。拦截类候选改写出的历史可能带上这些文字，「不装」臂也会读到。现状：靠待审页人审。
6. **L4 `from-review` 每次处理的候选数没有上限**：选了多少就改写多少。后续可加 `--limit`。
7. **L6 直接在仓里跑 eval 会留下转录**：用例通过移进 `plugins/<p>/evals/` 后，有人直接对仓跑 `claude plugin eval`，`<历史 sessionId>.jsonl` 会作为未跟踪文件落在仓里。后续可在被测仓 `.gitignore` 加一条模式兜住；本插件经 compare 跑时已移走，不受影响。

#### 留给票 17 的接口

- 合成历史：`replay.build_history(seed, turns, compact=True, summary=…)` 返回 `(sessionId, records)`；另有 `replay.history_text(records)`、`replay.message_texts(records)`。
- 注入核对：`replay.injection_hits(texts, injection_text, min_chars=20)`；注入文字用 `replay.default_injection_text(plugin_dir, repo, name)` 取。
- 选条款与生成：`replay.select_clauses(repo, name, plugin_dir, only=, limit=)`、`replay.generate(data_dir, name, …)`。
- 转录清理：`replay.purge_transcripts(arm_dir, keep_dir=None)`。
- 用例文件：casefiles 的 spec 键 `history_file` / `history_text`。
- 复盘候选转草稿：
  - 主流程：`candidate_drafts.run(data_dir, name, date=, ai=, model=, env=, injection_text=)`；
  - 定位与片段：`candidate_drafts.resolve(cfg, cand, now=, retention_days=)` 返回 `(片段, 作废码)`；
  - 隐私自检：`candidate_drafts.privacy_findings(texts, private_terms=, source_texts=)`。
- 状态：复盘候选的 `conversion` 字段；草稿的 `replay`、`review_candidate` 字段。

### 2026-10-16 C 批集成（集成分支 `worktree-agent-a8d415191cb4959db`，devkit-plugin-eval 0.5.0）

与票 16 一起合入，审查原文结论「修后合并」。下面逐条写修法，括号里是单测名：`test_candidate_drafts.py` 的 `BatchCFixTest`，`test_replay.py` 的 `GenerateTest` 与 `CompareCleansTranscriptsTest`。

**审查问题**

- **B1** 逐字重合检查改为比对除 compact 边界标记外的全部片段：工具调用参数、工具输出、hook 报错、compact 摘要都比（`test_copy_from_tool_result_rejected`）。
- **S1** 以下几处的取词门槛从 4 字降到 3 字：cwd 末段、`.claude` 前一段、家目录名、主机名与包名的标签。分支名仍是 ≥ 4 字。通用词表补了 api、app、web、cdn、svc、lib 等。≤ 3 字的私有词按整词匹配（`test_three_letter_terms`）。
- **S2 / 定稿 2** 私有词有两个入口，取并集：环境变量 `PLUGIN_EVAL_PRIVATE_TERMS`，与数据目录下的 `private-terms.txt`（每行一个或逗号分隔，`#` 起注释）。两处都为空时，stderr 与摘要各打一行「未配置私有词，只能靠会话推断与形态检测」（`test_private_terms_file_and_env_union`、`test_no_terms_warns_on_stderr_and_summary`）。
- **S3 / 定稿 1** 改写出的草稿目录里放内容为 `*` 的 `.gitignore`。草稿待审页通过时，`draft.json` 与这个文件只删不搬。`drafts` 认标记的规则：草稿目录顶层、内容恰为 `*` 的 `.gitignore`，这个文件也不算进用例正文。输出与待审页都写「由本机真实会话改写，通过前逐字审隐私」（`test_draft_dir_gitignored_and_mark_dropped_on_approve`，单测里 `git init` 后查 `git status`）。
- **S4** 跨日期沿用的 conversion 从只认 `drafted` 改为认 `drafted` 与 `skipped`，`void` 不沿用（`test_skipped_carried_across_dates_void_not`）。
- **S5 / 定稿 4** `drafts compact --clauses` 点名时，已打回的回放草稿不算覆盖，会重写。点名条款已有未打回的回放用例时，说明里写「不重做」（`test_named_clause_rewrites_rejected`、`test_named_clause_already_covered_says_so`）。
- **S7 / 定稿 3** 先试读会话，读得到就改写，不论时间早晚；读不到时，早于 `cleanupPeriodDays` 记 `past-retention`，否则文件不在记 `file-gone`、记录不在记 `record-gone`（`test_readable_even_if_older_than_retention`；原 `test_past_retention_and_record_gone` 改为指向不存在的记录）。输出里「作废（过了保留期）」改为「作废（原文读不到）」，复盘待审页的说明同步改。
- **S6** 见票 16「C 批集成」一节：run-eval、README 补 `drafts from-review` / `drafts compact` / `--date`、私有词入口与隐私提醒。
- **L1** 拿不到注入文字时，draft.json 记 `injection_checked: false`，待审页事实栏加「未做注入核对」，stderr 打一行（`test_no_injection_text_marks_unchecked`）。
- **L3** `compare._run_arm` 移回放转录时包了 try/except，出错只记一行日志，不中止这一臂（`test_purge_error_does_not_abort_arm`）。
- **L5** compact 配额满时，提示写「删除已打回的回放草稿目录可腾出名额」，并列出已打回的有几个、是哪些；也可以用 `--clauses` 点名重写（`test_quota_full_tells_how_to_free`）。
- **L7** spec 第四节已登记，见「devkit-plugin-eval 0.5.0 起」一条。
- **L2、L4、L6** 已写进上面的「已知缺口」第 5～7 条。

**集成时另定（暂定口径，待主会话复核）**

1. **逐字重合的豁免语料**（用户可见：拒写的少了）
   - 现象：真跑时 13 次改写有 8 次因逐字重合被拒（见 [demo-integ-C](../demo-integ-C/README.md)）。按片段类型排查，有两类是误拒：
     - AI 写合成 compact 摘要时，照抄了 Claude Code 摘要的固定开头；
     - hook 报错里有被测插件自己的脚本路径。
   - 选了：重合窗口出现在豁免语料里就不算。豁免语料是 Claude Code 固定文案 `CC_BOILERPLATE`（目前只有 compact 摘要开头那一句），加被测插件目录下除 `evals/` 外的文本文件，上限 200 万字。只对命中的窗口查豁免语料，不影响速度（`test_public_text_exempt_from_overlap`）。
   - 备选：不豁免，靠改写提示词劝 AI 别抄。
   - 理由：这些文字本来就在被测仓或 Claude Code 里，照抄不泄露。工具输出里别的内容照旧拒写。
   - 这项改动之后没有再真跑 from-review，避免再次读取真实会话。
2. **3 字私有词按整词匹配**（不可见）：前后都不是字母或数字才算命中，`abc` 不误中 `abcd`。更长的词仍按子串匹配。
3. **私有词表文件名与格式**（可见）：`<数据目录>/private-terms.txt`，UTF-8 编码，每行一个或逗号分隔，`#` 起注释，不区分大小写。读不了时按空表处理。
4. **compare 只在完整时打印下一步**（可见，票 16 CLI 缺口 1）：不完整时只给续跑命令，续跑成功后会自动出页。

**已知缺口（集成后新增）**

8. `invalid spec` 只记问题个数。真跑时同一候选两次结构不合格，用户和 AI 都看不到是哪条不合格。后续可以把 `validate_spec` 的结构问题打到 stderr，这些问题只涉及字段名和 grader 名。
9. drafts 运行目录的 `run.json` 与 `report.md` 会记改写草稿的目录名。目录名由 AI 起，已过隐私自检，但会随被测仓入库。

**真实验证**：见 [demo-integ-C](../demo-integ-C/README.md) 第 2、3 节，from-review 与 compact 回放 compare 各真跑过。

**留给票 17 的接口（集成后变化）**

- `candidate_drafts.privacy_findings(texts, private_terms=, source_texts=, public=)`：新增 `public`，即豁免语料，由 `candidate_drafts.public_text(plugin_dir)` 取得。
- `candidate_drafts.configured_terms(env, data_dir)`：返回两个入口取并集后的私有词。
- `candidate_drafts.run(...)` 的摘要新增 `private_terms_configured`、`injection_checked`。
- `replay.existing_compact(..., skip_rejected_for=)`：传点名的条款时，跳过挂着这些条款且已打回的回放草稿。
- `resume.pending_hint(data_dir, name, run_id)`：返回 compare 收尾那行下一步命令。
