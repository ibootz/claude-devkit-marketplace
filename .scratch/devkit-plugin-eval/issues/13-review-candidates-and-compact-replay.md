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

#### 暂定口径（待主会话复核）

1. **高风险条款排序**（用户可见：`compact` 输出逐条打印选中理由）
   - 选了：已证明有差 → 复盘命中 → 事件含 SessionStart → 有现成底本 → 条款号。
   - 备选：只看 SessionStart；或复盘命中优先。
   - 理由：已证明有差的条款最值得回归。SessionStart 在真实长会话里只在开头与 compact/resume 时注入，之后不再重注，最易被稀释。有底本的不花钱。
2. **≤ 3 的计数**（可见）
   - 选了：evals/ 与草稿区里已有的 compact 回放用例都算，含已打回的；已覆盖的条款不重做。
   - 备选：只算 evals/。
   - 理由：防止反复生成后被打回、再生成。
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
     - 用户自配的 `PLUGIN_EVAL_PRIVATE_TERMS`；
     - 固定形态：路径、邮箱（`example.invalid` 除外）；
     - 与原文（用户话、助手话、工具参数）去空白后逐字重合 ≥ 24 字。
   - 备选：把公司词硬编码进代码。
   - 理由：仓库公开，把词写进代码本身就是泄露，也过不了提交前的隐私检索。
10. **保留期判定**（可见：作废原因码）
    - 选了：按指针新到旧，取第一个可用的。指针时间早于 `cleanupPeriodDays`（settings，缺省 30）记 `past-retention`；文件不在记 `file-gone`；记录不在记 `record-gone`。全部不可用时，用最新指针的原因码。
    - 备选：只看文件在不在。
    - 理由：票面写的是「过了保留期」，文件只是保留期的一种落地表现。
11. **片段裁剪**（不可见）
    - 选了：每段截 1200 字，总长 12000，超出时丢最早的。
    - 理由：够还原触发情境，又控制送给 AI 的原文量。

#### 已知缺口

1. **回放用例的注入核验报「找不到子会话转录」**。
   - 原因：回放子会话的转录写在用例目录里，不在沙箱的 `projects/` 下。同一用例的多次 run 共用 `<历史 sessionId>.jsonl`，按 run 拆不开。
   - 现状：注入是否到达，目前只能人工数 `replay-transcripts/` 里的记录（演示已数）。要接进 `injection_check`，得按分支（parentUuid）拆 run，留给后续。
2. **固定摘要与被测 prompt 话题不连贯**：摘要讲 pagelint，被测 prompt 讲别的项目。它仍然算长历史稀释，但不像真实的同一会话。
3. **隐私自检是启发式的**：换了说法的业务内容查不出来。演示产出的那份草稿里有一套文档核对场景，像是从原会话的任务结构改写来的；没有逐字重合，但人审时要留意。真正的闸门是待审页上的人工审阅。
4. **README 没写两个新子命令**：票 16 在并行，由集成者补。spec 第四节的字段也由集成者登记。

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
