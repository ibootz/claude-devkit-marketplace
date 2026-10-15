# 14 — 闸门判定

Status: resolved

**What to build:**

`gate` 子命令（入参为插件目录）判当前版本能否发布：

- **插件内容指纹**：算整个插件目录、排除 `evals/`。
- **判据**：扫 `runs/*/run.json`；过闸 = 存在同版本、指纹一致、不是 dirty / 不完整的记录，且为二者之一：已审的离线对照，或通过的规则子集。major 升版与提交信息 trailer 写了 `eval-required:` 的版本只认前者。指纹不一致视为未过闸。
- **单测声明**：Python 实现读 `unit-tests.json` 逐条跑，任一失败判失败；未声明只提示「未声明单测」；声明不合法判失败；解释器解析不到判失败。用 02 的共用样例集与 JS 实现对齐。
- **跳过与漏检**：`eval-skip:` 的版本放行并列出全部跳过记录；闸门内版本推到 main 时既无已审报告、也无 `eval-skip:` 的，列为漏检。
- 本仓不接 git hook，用户发版前手动跑。

**Blocked by:** 02, 03


- [x] 对一个有已审对照、指纹一致的版本，`gate` 判通过
- [x] 审后改一个文件（`evals/` 外）不升版，`gate` 判未过闸；只补 `evals/` 用例不影响判定
- [x] dirty 或不完整的 `run.json` 不被采信
- [x] 提交信息带 `eval-skip:` 时放行，并在输出里列出全部跳过版本
- [x] 构造一个闸门内版本无报告、无跳过标记地出现在 main，输出列为漏检
- [x] 02 的共用声明样例在本票 Python 实现下判定结果与 JS 实现一致
- [x] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的「2.8 发版闸门（gate）」「2.7 确定性单测」；[12](../../plugin-eval/issues/12-release-gate-coverage.md)、[13](../../plugin-eval/issues/13-result-layout.md) 第 7 条、[18](../../plugin-eval/issues/18-unit-test-declaration.md)

## Comments

- 2026-10-15，票 03 审查遗留（主会话定、jev 同意）：run.json 的 `dirty` 现按插件目录 `git status` 计，含 `evals/`，也含 compare 自己往插件目录写的那行 `.gitignore`（仓根插件首次对照必为 dirty）。本票实现闸门时统一 dirty 口径：dirty 排除 `evals/`（与插件内容指纹的排除范围一致），并排除 compare 自写的 `.gitignore` 行。票 03 不改。
- 2026-10-15，票 04 集成口径②（主会话定）：插件不在 git 仓、取不到 git 状态时 run.json 记 `dirty=null`。闸门判据必须写成 `dirty is False`；写成 `not dirty` 会把 null 放行。上一版臂的 `head_sha` / `dirty` 恒为 null（快照来自 git 历史，没有 dirty 一说），不能拿它套这条判据。
- 2026-10-15，集成审查 N4（未修，待本票定）：续跑过的运行，dirty 有两个来源。run.json 的 `preflight.dirty` 取自最后一次续跑时，`arms.current.dirty` 沿用首跑。两者可能不一致，闸门判据须写明读哪一个；也可以要求两者都是 `False`。见票 07 Comments「集成审查修订」一节。
- 2026-10-15，用户拍板 05-1（原话「按照推荐来」）：新插件首评或从未升过版本号时，上一版臂仍标退化（`previous_arm.degraded=true`、`reason_kind=no-different-version`），不新设状态。闸门按 `reason_kind` 区别对待：`no-different-version` 的退化报告是「按基线规则比不装」，与 `not-git` / `no-history` / `snapshot-failed` 这类取不到上一版的退化分开处理，具体放行规则本票定。
- 2026-10-15，用户拍板 06-3.2：注入未到达不改 `complete`。闸门读 run.json 的 `injection_check.ok`，为 false 时拒绝把这次运行作依据。
- 2026-10-15，用户拍板 07-1：续跑时 Claude Code 版本不同照常合并。闸门须检查 run.json 顶层的 `claude_code_versions`：多于一个即版本混用（续跑时版本变了，或各臂不同），按混用处理。主力模型不同已在运行侧判为不完整（`complete=false`），闸门照「不完整不作依据」排除即可。

### 2026-10-15 实现摘要（devkit-plugin-eval 0.2.0 内，不升版本号）

**结论**：`gate <插件目录>` 已落地，验收 7 项全部满足。退出码 0 过闸、1 未过闸、2 用法错误（如目录里没有 `plugin.json`）。入参是插件目录，不要求已登记，不读用户级数据目录，不调 `claude`。

**新增模块**

- `scripts/plugin_eval_lib/gate.py`：闸门判定。三块全过才过闸：
  - 单测声明：任一条失败、超时、声明不合法、解释器解析不到，都判失败；未声明只提示。
  - 评测依据：逐份 run.json 过 `assess_run`。
  - 跳过：当前版本的升版提交带 `eval-skip:` 时，评测依据这一块放行。
  - 另外每次都输出两样：历史里全部 `eval-skip:` 记录，以及 main 上的漏检。
- `scripts/plugin_eval_lib/unittests.py`：单测声明的 Python 实现，声明校验的错误码、解释器解析、逐条状态都与仓根 `scripts/run-unit-tests.js` 一致。闸门口径与 pre-commit 口径分别是 `gate_verdict` 与 `precommit_verdict` 两个函数。
- `scripts/plugin_eval_lib/gitstate.py`：统一 dirty 口径，见下文「dirty 口径」。

**采信判据**（`gate.assess_run`）：以下各条都满足才采信，任一条不满足就列出原因。

- `plugin.version` 等于当前版本（plugin.json 没写 version 时记作 `noversion`，与 compare 一致）。
- `plugin.fingerprint` 等于当前插件内容指纹。指纹排除 `evals/`，仓根插件另排除 `.git`、`plugin-evals`。
- `completeness.gate_exclusion_reason` 为 None，即 `complete` 严格为 true。
- dirty `is False`，读哪个来源见「暂定口径 1」。
- `injection_check.ok` 不为 false。离线对照没有 `injection_check` 时只提示，不拒绝。
- 依据种类二者之一：
  - `kind=compare`：要求 `review.status=已审`。
  - `kind=gate`：要求 `passed is True`，且 Claude Code 版本没有混用。

**覆盖范围**

- 闸门内的版本只认已审离线对照。闸门内 = major 升版，或当前版本那一段 plugin.json 提交里写了 `eval-required:`。
- major 的判法：当前版本号的首段数字大于上一个不同版本号的首段数字。上一个不同版本号沿 HEAD 追 plugin.json 取得，跨改名，与上一版臂的认定相同。

**trailer 归属**

- 沿 HEAD 追 plugin.json 的提交历史（`git log --follow`），版本号为 V 的那一段连续提交上写的 trailer 都算 V 的声明。这一段含升版提交。
- trailer 用 `%(trailers:only,unfold)` 取，键名不分大小写。

**漏检**

- 对象：main 上闸门内的版本，既没有 `eval-skip:`，也没有可采信的已审离线对照。
- 内容指纹：该版本推到 main 的内容，即下一个版本引入前的那个提交；最新的版本取 main 的头。用 `git archive` 解出后算指纹。
- 已审报告评的内容与推到 main 的内容不一致时，同样列为漏检。

**dirty 口径（本票统一，改了共享代码）**

- `compare.git_state` 改为调 `gitstate.git_state`，compare、resume、check 三处都按新口径取 dirty。新口径：
  - 排除插件根下 `evals/`；
  - 仓根插件的 `.gitignore` 相对 HEAD 只差 compare 自写的那一行时，不算改动；
  - 仓根插件另排除 `plugin-evals/`。
- `ensure_gitignore` 写的那一行改由 `gitstate.gitignore_line` 给出，与 dirty 判断共用一个来源。
- 已有 run.json 是按旧口径记的，不回写。

**证据**

- 单测：`tests/test_gate.py` 33 条、`tests/test_gitstate.py` 13 条、`tests/test_unittests.py` 12 条。插件全量 344 条通过，`node scripts/tests/run-unit-tests.test.js` 通过，`node scripts/check-versions.js` 通过。
- 反证做了两处，改坏后对应单测失败，复原后通过：
  - 把 dirty 判据从 `is not False` 改成真值判断：`test_dirty_null_not_clean` 失败。
  - 去掉 `:(exclude)<插件>/evals`：`test_evals_changes_do_not_count` 失败。
- 共用样例：`SharedFixturesTest` 逐个比对 23 个样例与各自的 `expected.json`。另外在 linux、darwin、win32 三个平台假定下，对同一批样例直接比对 `node scripts/run-unit-tests.js --json` 与 Python 结果，0 处不一致。
- `test_compare.py` 的 `test_repo_root_plugin_fingerprint_matches_tree_after_run` 原本断言「仓根插件首次对照必 dirty」，这正是旧口径要改掉的行为，已改为断言 `dirty is False`。
- 对仓里已入库的 9 份演示 run.json 跑 `assess_run`：全部因「待审」不采信。demo-06 broken 另报 `injection_check.ok=false`，demo-04 另报 dirty，demo-05 outside-repo 另报 `dirty=null` 与 not-git 退化提示。说明真实字段形状下判据可用。
- 本票没有跑真实 eval：闸门只读已有记录，不调模型。

**已定（2026-10-15 主会话复核）**

审查八条都判合理，照现状保留。第 6 条与 spec 2.6 的字面冲突交票 15：已写进票 15 Comments「gate 跑规则子集时再接前置检查」。

1. **续跑后 dirty 读哪个来源**
   - 选了：读 `preflight.dirty`，即最后一次续跑时的值；没有 `preflight` 段的旧记录退回读 `arms.current.dirty`。首跑时不是 false 而续跑时是 false，照常采信，并提示一句。
   - 备选：所有来源都要是 false（AI 原推荐），或只读首跑的值。
   - 理由：续跑在插件内容指纹变了时会拒绝续跑。所以最后一次续跑时干净，就说明整次运行评的内容等于那时已提交的内容，能追溯到提交。要求全部为 false，会把「首跑时没提交、续跑前提交了」的合法运行拦下。Jev 选这个，置信 0.66，AI 改从 Jev。
   - 用户可见：是。
2. **上一版臂退化的已审报告**
   - 选了：一律采信。`no-different-version` 记普通提示「新插件首评……按基线规则比不装」；其它退化原因记醒目提示「取不到上一版，报告只比了不装、没比版本回归」。
   - 备选：其它退化原因在闸门内版本不采信，或一律不采信。
   - 理由：spec 2.2 原文「退化报告能否作闸门已审依据，由用户审报告时判断」，闸门不替审阅者推翻。重开条件「退化报告被当作闸门依据后漏判回归」留作兜底。Jev 同选，置信 0.33。
   - 用户可见：是。
3. **Claude Code 版本混用**
   - 选了：已审离线对照照常采信并提示；规则子集（`kind=gate`）不采信。
   - 备选：一律不采信，或一律采信。
   - 理由：用户已定续跑时版本不同照常合并，报告也照旧告警，审阅者审过即已知情；规则子集没人看，混用就没人兜底。Jev 同选，置信 0.30。
   - 用户可见：是。
4. **`eval-skip:` 不豁免单测声明**
   - 理由：单测便宜、结果确定，跳过只为省评测成本。Jev 同选，置信 0.80。
   - 用户可见：是。
5. **漏检的起算点**
   - 选了：缺省从 main 上首次入库 `plugin-evals/<插件名>/` 的提交起算，`--since <提交>` 可覆盖。main 依次试 `origin/main`、`main`、`origin/master`、`master`，`--main-ref` 可指定。不 fetch，`origin/main` 可能过时。
   - 理由：评测机制启用前的 major 版本（如 devkit-discipline 4.0.0）若也算，会永久报漏检、淹没真信号。Jev 同选，置信 0.56。
   - 用户可见：是。
6. **闸门不跑前置检查**
   - 理由：spec 2.6 列的前置检查项全是「离线对照前」的（claude 可执行、登录、validate、冒烟），本票的闸门只读记录、跑单测，用不上。规则子集真跑模型时（票 15）再接 `check_compare`。
   - 用户可见：否。
7. **离线对照只要求已审，不要求「是否通过」**：照 spec 2.8 原文。输出不显示 `passed`，审阅者在报告里看。
   - 用户可见：否。
8. **漏检的「已审报告」从工作区读**：读工作区的 `plugin-evals/<插件名>/runs/`，不读 main 上入库的版本。审完但还没推到 main 的报告也算。
   - 用户可见：否。

**已知缺口**

- trailer 只认 plugin.json 提交历史上的提交。只改了其它文件、却写了 trailer 的提交不算；merge 提交不带文件名，也被跳过。
- 漏检里「推到 main 的内容」取下一个版本引入提交的第一父提交。main 上有非线性合并时，这可能不是真正上线的那一刻。
- Windows 上 `.cmd` 解释器经 `subprocess.Popen` 直接起，没有像 JS 那样走 `shell`。未实测。
- 输出里的插件目录是绝对路径，只打印到终端、不落盘。
- 给票 15：
  - 规则子集的 run.json 至少要有 `kind=gate`、`plugin.version`、`plugin.fingerprint`、`complete`、`passed`、`claude_code_versions`，以及 `preflight.dirty` 或 `arms.current.dirty`，闸门才认。
  - 「建议跑对照」与「超 7 天提醒」两类提示加在 `gate.evaluate` 的 `notes` 里即可。

### 2026-10-15 A 批（09/10/12/14）集成定稿（集成分支 worktree-agent-aa78acdaffe679a6d，devkit-plugin-eval 0.3.0）

**主会话定稿口径**

- AI 判分不采信的已审报告（口径 4）：照采信，输出醒目提示「本报告 AI 判分不采信，已审时由用户判断」（`gate.JUDGE_UNTRUSTED_NOTE`，输出字段 `judge_untrusted` 列出这些运行）。单测 `test_untrusted_judge_report_still_accepted_with_prominent_note`。
- 新插件首个版本（口径 5）：不按 major 升版判闸门内，输出一条说明「新插件首个版本（历史上没有更早的版本号）：不按 major 升版判闸门内」；升版提交显式声明了 `eval-required:` 时仍按声明判闸门内，说明里一并写明。单测 `test_first_version_of_new_plugin_noted_and_not_gated`。
- 扫运行记录时跳过 `kind=clauses`（`gate.SKIPPED_KINDS`）。单测 `test_clauses_runs_are_skipped`。

**审查应修落地**

1. 工作区 dirty 不为 False 时直接判未过闸，原因写「插件目录有未提交改动（不含 evals/），先提交再跑 gate」（`gate.DIRTY_BLOCKER`，输出字段 `blockers`，报告节「未过闸原因（与评测依据无关）」）。单测 `DirtyWorkspaceTest.test_worktree_equals_reviewed_content_but_head_differs`、`test_uncommitted_change_blocks_even_with_matching_report`、`test_evals_only_change_does_not_block`。
2. `eval-required:` 除 trailer 外，再按提交信息全文逐行 `^eval-required:` 宽松识别；正文出现 `eval-skip:` / `eval-required:` 而 trailer 没取到时输出警告。单测 `test_eval_required_followed_by_blank_line_and_signature`、`test_eval_skip_outside_trailer_warns_and_does_not_pass`。
- 顺手修：非 UTF-8 的单测声明归为「声明不合法」（`test_non_utf8_declaration_is_invalid`）；`HEAD:.gitignore` 改为 `HEAD:./.gitignore`。

**已知缺口（审查「可留后续」其余各条）**

- 漏检往严的方向误报：漏检用 `git archive` 算指纹，不含被 gitignore 的文件，而 run.json 的指纹按工作区算、含这些文件；插件里有被忽略的文件时，合格的已审报告会被判成漏检，提示原因归错。本仓 `plugins/` 下目前除 `__pycache__` 外没有被忽略的文件。
- 插件目录不是 git 仓根的子路径时，`plugin-evals/<名>` 按顶层取，漏检检查会被跳过（给说明）。
- 带路径的解释器名会 `resolve()` 掉符号链接，JS 的 `path.resolve` 不会；只在解释器路径本身是符号链接时有差异。

**暂定口径（待主会话复核）**

1. 插件目录不在 git 仓里时不触发 dirty 未过闸（无提交可比），沿用原「不在 git 仓里」说明。备选：一律判未过闸。用户可见。
2. git status 失败（dirty 为 null）同样判未过闸，原因写「读不到插件目录的 git 状态（git status 失败），无法确认工作区与提交一致」。用户可见。
3. 正文出现 `eval-skip:` 而 trailer 没取到时只警告、不放行（`eval-skip` 是放行条件，宽松识别会让误写也放行）；`eval-required:` 则按正文宽松识别（往严的方向）。用户可见。

**给票 15**

- 「注入文本指纹变了 → 建议跑对照」本批不实现，见票 15 Comments。

### 2026-10-15 A 批集成审查修订（集成审查结论「修后合并」，同一集成分支）

**已修**

- 漏检检查不认宽松识别的 `eval-required:`（审查 B）。当前版本的闸门判定用 `Commit.required()`：声明后面跟了空行和署名段时，git 不认它是 trailer，`required()` 也按提交信息全文逐行识别。漏检检查原先只认 trailer，同一版本在当前版本判定里进了闸门，推到 main 时却不报漏检。已改为 `c.required()`，与当前版本判定同口径。单测 `test_eval_required_followed_by_blank_line_and_signature_without_report_is_leak`。
