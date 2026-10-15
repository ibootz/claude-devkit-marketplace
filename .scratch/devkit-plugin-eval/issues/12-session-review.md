# 12 — 会话复盘

Status: resolved

**What to build:**

`review` 子命令手动触发，覆盖全部已登记插件，读本机会话 jsonl 抽信号，结果写回各插件所在仓的 `plugin-evals/<plugin>/reviews/<日期>.json`（零计数也写）。**原始 jsonl 不入库、不另存，抽取结果不含对话原文。**

要抽的信号：skill 调用（`Skill` tool_use、`<command-name>`、`attributionSkill` / `attributionPlugin`）；拦截（tool_result 文本、`permissionDecision`、cache 路径里的 `<plugin>/<version>`）；注入（`attachment.type`，按 hooks.json 导出的「事件 + matcher + 脚本相对路径」指纹加内容标签归到插件）；hook 时延（`hook_success.durationMs`）；compact 前后（`compact_boundary`）；环境插件（`skill_listing`，版本在复盘时读一次 `installed_plugins.json`）；Claude Code `version` / `model`，与上次对照比对，变了在待审页列「建议跑对照」。

实现要求：子代理文件并入统计；按 `uuid` 去重；缺字段容错并记 `version`；旧插件名按 marketplace 的 `renames` 归一。

复盘还产出**复盘候选**（只存会话 id、`uuid`、时间、插件版本、命中条款 id、是否在 compact 之后，不存原文），进复盘待审页供用户勾选（转草稿在 13）。

**Blocked by:** 08


- [x] 对本机近 30 天会话跑一次复盘，每个登记插件都有一份 `reviews/<日期>.json`；用全文检索确认文件里没有对话原文
- [x] 同一会话经 resume 复制的记录不重复计数
- [x] 子代理里的拦截被计入
- [x] Claude Code 版本或模型与上次对照不同时，复盘待审页出现「建议跑对照」
- [x] 复盘候选进待审页，用户勾选结果写回
- [x] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的「2.5 会话复盘（review）」；[10](../../plugin-eval/issues/10-session-jsonl-signals.md)；字段路径见 [research/session-jsonl-signals.md](../../plugin-eval/research/session-jsonl-signals.md)

## Comments

### 2026-10-15 实现完成

在 worktree 分支 `worktree-agent-aca00d48441c330e2` 上提交，未合并 main、未推送、未改版本号（仍 0.2.0）。动 `plugins/**` 前已用 Skill 读过 `mattpocock-skills:writing-for-agents`、`skill-creator:skill-creator`（本票只写 `scripts/` 与 `tests/`，不碰 skills / hooks / plugin.json，无追加技能）。

**实现摘要**

- 新子命令 `review [--days N] [--no-hook-labels]`：覆盖登记表里全部插件，每个插件写一份 `<被测仓>/plugin-evals/<插件>/reviews/<UTC 日期>.json`，零计数也写。复盘前先跑 preflight 的 `check_review`，硬失败即中止、不写文件。
- 新模块四个，共享文件只接线：
  - `review_scan.py`：抽取层。读 `projects/<项目>/<会话>.jsonl` 与 `<会话>/subagents/agent-*.jsonl`，按 mtime 从旧到新，全局 `uuid` 集合去重（重复记录仍推进 compact 段号与注入配对表，但不计数）；坏行、读到一半消失的文件都容错并计数。
  - `review.py`：建插件索引（登记插件 + `installed_plugins.json` 里所有已装插件的 hooks 指纹；指纹撞车时用常驻 hook 静态跑一次得到的首行做内容标签），组装结果、写盘、全文自检（超 300 字、含换行、含家目录或 macOS / Linux / Windows 用户目录路径形态的字符串一律报错不写）。
  - `review_pending.py`：两种待审项「建议跑对照」（always，只有「知道了」）与「复盘候选」（A 转用例草稿 / B 不转），挂到票 08 的待审页框架上。
  - `review_clauses.py`：票 10 条款清单的最小读取接口（见暂定口径 9）。
- 抽取的信号：skill 调用（`Skill` tool_use、`<command-name>`、`attributionSkill`，按插件前缀归）；拦截（`<Event>:<Tool> hook error: [<命令>]` 形态的 tool_result 与其中的 cache 路径 `<插件>/<版本>`、尾注 `This hook comes from the <插件>@<市场> plugin`、`permissionDecision`）；hook 报错（`hook_blocking_error` / `hook_non_blocking_error`）；注入（`hook_additional_context` 按同文件 `hook_success` 文本配对到指纹，配不上时按内容标签）；hook 时延；compact 边界与边界后 SessionStart 是否重新注入；同会话加载的插件（`skill_listing`）；Claude Code 版本与主会话模型。旧插件名按两份 marketplace 的 `renames` 链式归一，`null` 视为已删。
- 复盘候选只存定位指针与信号：`kind`、`rule`（脚本相对路径，有 `check=` 时追加 `#check=`）、计数、子代理计数、是否在 compact 之后、命中条款 id、插件版本、最近 3 条指针（会话 id、子代理 id、`uuid`、时间、插件版本、Claude Code 版本）。
- `pending <插件> --review [日期]` 生成复盘待审页（缺省取最新一份）；`--reply` 收到 run_id 以 `review-` 开头的回复码时转给 `review_pending` 写回 `reviews/<日期>.json`（候选的 `selection` = `draft` / `skip` 与 `decided_at`；对照提示的 `acknowledged_at`）。同日重跑覆盖结果但沿用已有勾选与已读，旧页作废（`page_id` 清空并记进 `pending.history`）。
- 单测 24 个（`tests/test_review.py`，全部合成假转录，到处埋 `SECRET` 标记断言结果里一个都没有）；全量 310 个通过。

**验收证据**

1. 本机近 30 天真实复盘：21 个登记插件各得一份 `reviews/2026-10-15.json`（产物在 `/tmp` 的假仓里，未入库）。按派发简报第 8 条的检索词（用户目录路径形态、公司域名与其缩写、邮箱形态）加本机用户名做全文检索，均 0 命中；字符串字段逐个过白名单，剩下的只有脚本相对路径、hook 指纹键、插件 id、模型名、版本与固定提示语；再从真实会话随机抽 53936 个 24 字正文片段反查，16 个命中全是插件名 / skill 全名 / 脚本路径这类标识符，非标识符形态 0 个。计数摘要见 `../demo-12/summary.json`。
2. resume 不重复计：`test_resume_copies_are_counted_once`（S2 复制 S1 的 13 条历史，含 compact 边界与重新注入，只计 S2 新增的 1 次）；真实复盘跳过重复 `uuid` 25481 条。
3. 子代理拦截计入：`test_subagent_blocks_are_counted`；真实复盘 devkit-cd-blocker 1530 次拦截里 1028 次在子代理。
4. 建议跑对照：`test_compare_hint_appears_when_version_or_model_changed` / `test_no_hint_when_same_as_previous_compare`。真实复盘时假仓里没有离线对照记录，各插件都是「没有离线对照记录，无从比较」，不出提示。
5. 候选进页与写回：`test_candidates_on_page_and_selection_written_back_and_kept_on_rerun`、`test_bad_reply_changes_nothing`、`test_more_than_ten_candidates_are_sampled`；真实数据上 devkit-discipline 18 个候选抽样 10 个上页，AI 演示贴回 `1A 2B` 后两项分别写成 `draft` / `skip`（AI 演示，不算用户勾选，未入库）。
6. 读技能：见上。

**已定（2026-10-15 主会话复核）**

审查判合理的照现状保留。第 5 条（UTC 日期）被主会话口径 7 改写，第 9 条（`review_signals`）改为按票 10 的格式推导，第 2 条补了跨日期沿用，第 6 条主力模型改为按插件取，第 15 条的分母已修，均见下方「A 批集成定稿」。

1. 每个插件每次复盘一页，回复码 run_id 为 `review-<日期>`，入口 `pending <插件> --review`。备选：所有插件合一页。理由：票 08 框架按插件出页、回复码绑定单个结果文件。用户可见。
2. 候选按（kind、rule、是否 compact 之后）归组，每组留最近 3 条指针。备选：一次事件一个候选。理由：真实数据单插件上千次同类拦截，逐条上页无法审。用户可见。
3. 候选只取拦截与 hook 报错两类；注入、时延、skill 调用只做计数。理由：只有前两类对应「行为可能有问题、值得转用例」。用户可见。
4. 时间窗缺省取 `cleanupPeriodDays`（未设为 30），按文件 mtime 粗筛再按记录时间戳细筛；`sdk-cli` 等入口不过滤，各入口会话数记进 `scan.entrypoints`。用户可见（`--days`）。
5. 复盘日期取 UTC 日期；同日重跑覆盖，沿用勾选与已读，旧页作废。用户可见。
6. 「当前版本 / 模型」取窗口内时间最新的记录的 `version` 与最新一条主会话 assistant 的 `model`；与 `preflight.previous_compare` 记录的版本、主模型比；没有离线对照记录时不提示。用户可见。
7. 「建议跑对照」做成必上页的待审项，只有「知道了」一个选项。备选：只在命令输出里提示。理由：spec 要求出现在待审页。用户可见。
8. 复盘候选在待审页的优先级 400（排在分歧样本、抽检、用例草稿之后）。用户可见（抽样时谁先上页）。
9. 条款清单读 `plugin-evals/<插件>/clauses.json`：`{"clauses":[{"id","retired","review_signals":[...]}]}`，信号键形如 `block:<脚本>`、`hook_error:<脚本>`、`check=<名>`；退役条款与没有 `review_signals` 的条款跳过。票 10 落地后按它的真实格式改 `review_clauses.py` 一处即可。用户不可见。
10. 内容标签来自静态执行常驻 hook 取首行（`--no-hook-labels` 可关）。理由：UserPromptSubmit 的 JSON 输出型 hook 没有 `hook_success` 记录，只能按首行认。用户可见（开关）。
11. hook 时延只按声明指纹归，不按内容标签归。理由：指纹撞车时把时延记到任一方都会失真。用户不可见。
12. 不带插件前缀的裸 skill 名不计入任何插件。用户不可见。
13. 规则键里的脚本路径只取 hook 命令段里的 ASCII 路径；旧版 Claude Code 的拦截文本方括号里没有命令，脚本记 `?`，插件与版本仍从诊断里的 cache 路径或尾注取。理由：诊断文案里的文档路径后常紧跟全角标点与正文，放宽会把原文带进规则键。用户可见（候选的 rule）。
14. 同会话加载的插件只具名列出同在登记表里的插件，其余（第三方、公司内部插件、项目级 skill 目录）只记个数 `co_loaded_unregistered_count`。理由：复盘结果会进公开仓，未登记插件名可能是内部名字。用户可见。
15. compact 统计只算窗口内、非 resume 复制的边界。用户可见（`signals.compact`）。

**已知缺口**

- 真实复盘里约 1 万次 UserPromptSubmit 注入未归因：多数来自未登记插件（JSON 输出型 UPS hook 没有 `hook_success`，指纹配不上；内容标签只覆盖登记插件），少数是登记插件旧版本的首行与当前版本不同、按标签认不出。
- `plugin.installed` 里带的是本插件的 `<插件>@<市场>` id；登记的插件都在本市场，名字可公开。
- 「距上次对照超过 7 天提醒」不在本票，属于 compare / gate。
- ~~spec 未登记 reviews JSON 的字段表~~：集成时已登记进 spec 第四节。
- Windows / Linux 未实测。

### 2026-10-15 A 批（09/10/12/14）集成定稿（集成分支 worktree-agent-aa78acdaffe679a6d，devkit-plugin-eval 0.3.0）

**主会话定稿口径**

- 复盘候选的裁定跨日期沿用（口径 6）：同一候选 id 在更早日期已裁定过的，不再上页，除非插件版本变了；命中新的规则键时候选 id 本身就不同，自然重新上页。沿用记录写 `carried_from = {date, run_id, decided_at, plugin_version}`（`review.carry_earlier`）。单测 `test_decision_carries_across_dates_unless_version_changed`。
- 复盘日期（口径 7）：用本机本地日期命名 `reviews/<日期>.json`，结果里记 `date_basis=local` 与 `tz_offset`（如 `+08:00`）；`generated_at` 与指针时间仍是 UTC。单测 `test_date_is_local_with_offset`。

**条款映射（对齐票 10 的 clauses.json）**：只认 `status=active` 的条款。候选规则键里的脚本相对路径（`hooks/guard.js#check=x` 取 `hooks/guard.js`）→ 被测插件 hooks.json 里挂这个脚本的事件集合 → 与未退役条款的 `events` 有交集的恰好一条时，记这一条。零条或多条都记 `clause_ids=[]`，`clause_mapping={status: unmapped, reason}` 写明原因；待审页「命中条款 id」显示「未映射（原因）」。不新增要用户手填的字段。单测 `test_clause_ids_derived_from_events_and_hook_rules`、`test_no_clause_list_means_unmapped`。

**审查应修落地**

- ① 自检挪到 `scrub_home` 之前，检测正则加 `~/`；新增指针白名单 `review.check_pointers`：会话 id 必须是 uuid，uuid 与子代理 id 是短标识，时间戳合 ISO 形态，`rule` 与 `signals.blocks` / `signals.hook_errors` 的键必须是脚本相对路径形态或 `?`。单测 `test_self_check_runs_before_scrub_and_rejects_home_paths`、`test_pointer_whitelist`。
- ② 删除全局 `models` 清单；`environment.main_model` 只取加载过本插件（skill 清单列出或有信号）的会话里最新一条主线程回复的模型。单测 `test_main_model_is_per_plugin_and_no_global_model_list`。
- ③ compact 分母只算该插件在本文件这次 compact 之前出现过注入或 hook_success 的边界。单测 `test_compact_denominator_skips_sessions_without_the_plugin`。
- 顺手修：先给全部插件建结果并自检，任一不过整批不写（`test_bad_pointer_in_any_plugin_writes_nothing`）；写盘拿与待审页写回同一把锁 `review-<插件>-<日期>`（`test_write_takes_the_review_lock`）；复盘页抽样提示改指「复盘结果的 pending.sampled_out」，不再指向 report.md。
- 待审项类型加了「适用于哪类结果」（`pending.ItemType.kinds`），复盘页只跑复盘类型，不再调用 09、10 的 collect。单测 `test_review_page_skips_compare_kind_collectors`。

**暂定口径（待主会话复核）**

1. 条款映射只在「恰好一条未退役条款的 events 与脚本挂载事件相交」时记 id；多条相交记「未映射」。备选：多条时全列。理由：全列会把无关条款带进来，误导转用例。可回退：改 `review_clauses.match` 一处。用户可见（待审页「命中条款 id」）。
2. 跨日期沿用只看最近一次出现过该候选裁定的日期；那次的插件版本不同就不再往前找，重新上页。用户在页上重新裁定会清掉 `carried_from`。用户可见。
3. 自检不过时整批插件都不写盘，报错列出前 5 个违规位置。备选：只跳过不过的插件。理由：简报要求「不写出部分结果」。用户可见。

**已知缺口**

- 前置检查判「距上次复盘」时仍把 `reviews/<日期>` 当 UTC 零点（`preflight.py` 的复盘日期解析），与本地日期最多差一个时区偏移；票 15 的「超 7 天提醒」复用时留意。

### 2026-10-15 A 批集成审查修订（集成审查结论「修后合并」，同一集成分支）

**已修**

- 同一天重跑复盘的竞态（审查 D）：同一天的旧结果原先在锁外读取，写盘时才拿锁，中间落一次待审页写回就会被覆盖。现在先对合并后的副本做全部自检（任一插件不过，整批不写）；写盘时在锁 `review-<插件>-<日期>` 内重读旧结果、重新合并、重新自检，再 `scrub_home` 写盘。单测 `test_rerun_rereads_old_result_inside_the_lock`。把读取挪回锁外，这条单测失败，已做变异验证。
- 钉住「自检在脱敏之前」：上面「审查应修落地」① 的单测 `test_self_check_runs_before_scrub_and_rejects_home_paths` 只测了 `assert_no_text` 本身，改回「先脱敏再自检」也照样全过。新增单测 `test_self_check_happens_before_scrub`：家目录不在 /Users 或 /home 下，结果里出现家目录本身时，脱敏后只剩 `~`，检测正则认不出，只有先自检才拦得住。把自检挪到脱敏之后，这条单测失败，已做变异验证。

**记录（审查 C，不修）**

- 复盘候选的条款映射实际几乎映射不出，候选会全部记成「未映射」。原因有两条：
  - 条款的 `events` 只会是三个常驻注入事件：SessionStart、SubagentStart、UserPromptSubmit。审查给的数据是 demo-10 清单里 SessionStart 79 条、SubagentStart 58 条、UserPromptSubmit 22 条。
  - 拦截类候选的脚本多半挂在 PreToolUse 上，与条款事件没有交集；就算挂在常驻事件上，也会同时撞上几十条条款，不可能「恰好一条相交」。
- 这属于如实记录，不算错：映射规则不变（见上面暂定口径 1）。票 13 不能依赖 `clause_ids`，已在票 13 的 Comments 写明。
