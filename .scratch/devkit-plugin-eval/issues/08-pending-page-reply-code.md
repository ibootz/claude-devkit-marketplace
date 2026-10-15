# 08 — 待审页与回复码

Status: resolved

**What to build:**

所有人工环节集中在一个本机生成的 HTML 待审页：每次对照一页、每次复盘一页。本票先打通「报告审阅」这一环，并把待审项做成可扩展的类型，供 09（分歧样本、抽检）、10（条款清单变更）、11（用例草稿）、12（复盘候选）往里加项。

用户在页上选完，复制回复码贴回对话；CLI 解析回复码，把裁定写回 `run.json`（审阅状态改「已审」、记审阅时间）及相应文件。每页 ≤ 10 个待判项，超出时自动抽样，并在报告里写明抽了哪些。待审页不入库。

**Blocked by:** 03


- [x] 对一次对照生成待审页，页上能看到报告摘要并勾选「已审」；贴回回复码后 `run.json` 变为已审并带审阅时间
- [x] 回复码格式错误或对不上该次运行时，CLI 报错且不改任何文件
- [x] 构造超过 10 个待判项时页上只出 10 项，报告写明抽样规则与被抽中的项
- [x] 新增一种待审项类型只需注册类型与写回逻辑，不改页面框架（以一个示例类型证明）
- [x] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的「2.4 判分与人工介入」后半；[11](../../plugin-eval/issues/11-judging-and-human-checkpoints.md) 第 5、7 条；[13](../../plugin-eval/issues/13-result-layout.md) 第 4 条

## Comments

### 2026-10-15 实现完成

在 worktree 分支 `worktree-agent-a1d5116362e7a7318` 上提交，未合并 main、未推送、未改版本号（仍 0.1.0）。动 `plugins/**` 前已用 Skill 读过 `mattpocock-skills:writing-for-agents`、`skill-creator:skill-creator`（本票只写 `scripts/` 与 `tests/`，不碰 skills / hooks / plugin.json，无追加技能）。

**实现摘要**

- 新模块 `scripts/plugin_eval_lib/pending.py`；CLI 新增子命令 `pending <插件名> [--run <运行 id>] [--reply '<回复码>']`。不带 `--reply` 生成待审页，带 `--reply` 写回。
- 待审页写在用户级数据目录 `<数据目录>/pending/<插件>/<run_id>.html`，不进被测仓，自然不入库。页面自包含（内联 CSS / JS，无外部资源），每项显示类型、标题、摘要表、正文（转义后放 `<pre>`）、选项单选（默认「暂不裁定」，不进回复码）；页底实时拼回复码并提供「复制回复码」。
- 回复码：`PE1 <run_id> <page_id> <序号><选项码> ...`，如 `PE1 20261015T084918Z-4.1.0-compare 6911e07e 1A`。容忍多余空白与大小写。`page_id` 每次生成页时重算（含随机数），记进 `run.json` 的 `pending.page_id`。
- 报错且不改任何文件的情形：格式不对、前缀不是 `PE1`、run_id 在该插件下找不到、`--run` 与回复码的 run_id 不一致、`page_id` 不是最新一页、序号不在页上、选项码不属于该类型、同一序号出现两次、没有任何裁定、这一页已写回过、某一项的写回逻辑抛错。做法是先全部校验，再让各类型把改动暂存在内存（`Subject.stage_*`），全部成功后才统一落盘，`run.json` 最后写。
- 写回「报告审阅」：`run.json` 的 `review` 改为 `{"status": "已审", "reviewed_at": "<UTC>"}`；`report.md` 的状态行改为「状态：**已审**（审阅时间 …，UTC）」；另在 `run.json` 记 `pending.applied_at` 与 `pending.decisions`。
- 抽样：每页最多 10 项（`PAGE_LIMIT`）。规则：`always=True` 的类型（报告审阅）必上页；其余按类型 `priority` 由小到大依次装入，装不下的那一档以 run_id 为种子随机抽取（重复生成结果不变），上页的项保持原顺序。抽样时 `run.json` 的 `pending` 记 `sampled`、`sampling_rule`、`items`、`sampled_out`，`report.md` 追加或替换「## 待审页抽样」一节，列出规则、页上的项与没上页的项；之后再生成不需抽样时删掉这一节。
- 扩展方式：构造 `ItemType(key, label, options, collect, apply, priority, always, hint)` 后 `register_type`，页面框架、回复码、抽样、写回事务都不用改。单测里的示例类型 `demo-note`（读写运行目录下的 `demo-notes.json`）证明了这一点。
- 单测 23 个（`tests/test_pending.py`），全量 107 个通过。

**演示（本机，未入库）**：把 demo-03 的运行目录拷到 `/tmp` 下的假仓，登记后生成待审页；用 agent-browser 无头打开，勾「已审」后页上回复码为 `PE1 20261015T084918Z-4.1.0-compare 6911e07e 1A`，「复制回复码」后提示已复制；先贴错 page_id 的回复码，退出码 2、未改文件；再贴正确回复码，`run.json` 的 review 变为已审并带审阅时间，`report.md` 状态行同步改写；再生成页提示「没有待审项」。因为这次「已审」是 AI 演示，不是用户审阅，所以不建 demo-08 目录，免得仓里留一份没人审过却标「已审」的报告。

**待拍板**

1. 超过 10 项时谁先上页：本票暂定「报告审阅必上页，其余按类型优先级装，最后一档随机抽」。各类型的优先级（分歧样本、抽检、条款清单变更、用例草稿、复盘候选谁先）留给 09–12 注册时定，spec 只说「超出时自动抽样」，没规定类型间的先后。
2. 不带 `--run` 时取最新一次离线对照。如果最新那次已审、较早那次还待审，会提示「没有待审项」，要用 `--run` 指定。要不要改成默认取「最新一次还有待判项的运行」？

**已知缺口与扩展点**

- 「每次复盘一页」（票 12）：`Subject` 现在只指向 `runs/<run_id>/run.json`，复盘页要让它也能指向 `reviews/<日期>.json`。
- 写回 `judge.json` 等文件由 09 起各类型的 `apply` 用 `subject.stage_json` 完成。多文件落盘按文件逐个原子替换，不是跨文件事务。
- 别的票重新渲染 `report.md` 时（如票 07 续跑），「待审页抽样」一节会丢，重新生成待审页即可补回。
- `record.render_report` 的状态行没写审阅时间：审阅时间只在 `pending` 写回 `report.md` 时补上。
- Windows / Linux 未实测。

### 2026-10-15 集成（票 04–08 合入集成分支，devkit-plugin-eval 0.2.0）

**集成审查应修项（已修）**

- M1：落盘仍是 run.json 最后写。中途出 `OSError` 时清掉 `.pending-tmp` 残片，抛 `PendingError` 并列出已写成的文件，提示用同一回复码重试，不再打 traceback。
- M2：不带 `--run` 挑默认运行时，坏的历史 run.json 跳过，并在 stderr 提示；只有用 `--run` 指定它时才报错。
- M3：写进被测仓的 run.json 与 report.md（含 `pending` 字段、「待审页抽样」一节）都过 `record.scrub_home`。
- L2（顺手修）：某类型的 `collect` 抛错、`pending.items` 缺 `type` 或序号时，包成 `PendingError` / `ReplyError`，报错写明类型。
- 与票 07 衔接：生成页与写回都拿该运行的 `RunLock`，锁被占用时报「正在对照或续跑」。未结束的运行（检查点 run.json，或锁被占用）不出页；不带 `--run` 时跳过它们取下一个，用 `--run` 显式指定时报「还没结束」。续跑作废旧页并自动重新生成，见票 07 集成记录。上面「已知缺口」第三条（续跑后抽样一节丢失）因此不再需要手动补。

**主会话口径（集成简报第六节）**：待拍板 1 定为：待审页超过 10 项时，条款清单变更（票 10）也必上页（`always=True`）；其余按「分歧样本 > 抽检 > 用例草稿 > 复盘候选」排优先级（`priority` 依次增大）。09–12 注册类型时照此设值。

**仍待用户拍板（保持现状）**：待拍板 2，不带 `--run` 时是否列出较早仍待审的 run_id。

**已知缺口（来自集成审查，未修）**

- L1：`generate` 直接用 `rec['run_id']` 拼 HTML 路径、写进页内 JSON 脚本块，没过 `_RUN_ID_RE`，脚本块里也只转义了 `</`。run.json 被篡改时可带 `../`，或让页面脚本失效（不会执行注入代码）。run.json 里的 run_id 与目录名不一致时，回复码永远写不回。宜统一用 `run_dir.name`，并把 `<` 转成 `<`。来源是受信的 compare，风险低。
- L3：扩展接口对 09–12 的支撑有限。写回只有逐文件的 `stage_text` / `stage_delete`：没有整目录移动（票 11 草稿转用例要用），`stage_delete` 会留空目录，也不支持二进制文件。新类型只能靠 import 时 `register_type` 登记，没有发现机制。写回前不重新收集、不核对该项是否仍待判，09 起各类型的写回要能重复执行，才接得住 M1 的重试。
- L4：提示命令 `--reply '<回复码>'` 用单引号，Windows cmd 会把回复码拆成多个参数。与 registry 已有写法一致，宜统一处理。

### 2026-10-15 集成审查修订（review-integ，提交 e95fba3、6e02baf）

**已修（波及本票）**

- N1：续跑中途再崩时，检查点原来不带 `pending`：已写回过的页的历史全丢，再续跑成功后也不重新生成待审页。现在检查点里的 `pending` 已作废（`page_id=null`、`superseded_by_resume`、`history` 保留）；再续跑成功后照常重新生成一页。单测见票 07 本节 N1。
