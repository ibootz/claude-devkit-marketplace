# 16 — 两个 skill 与插件说明

Status: resolved

**What to build:**

插件只拆两个 skill，对应两个决策时刻，不加常驻 hook：

- **跑离线对照**：用户想评某插件、或被提示「建议跑对照」时触发；引导 AI 先确认被测插件已登记、选臂（默认按 spec 的基线规则：新插件比不装、改版比上一版）、长任务放后台，跑完给出待审页位置。
- **处理待审**：用户贴回回复码、或要看待审项时触发；引导 AI 调 CLI 写回裁定，并提醒「待审报告不能作为改插件或发版的依据」。

另写插件 README：命令行各子命令、登记、目录布局、单测声明格式、发版闸门用法，以及 Windows / Linux 未实测的说明。

**Blocked by:** 04, 05, 07, 09, 11


- [x] 两个 skill 的 description 能在对应场景被自动加载：各准备 ≥ 3 条应触发与 ≥ 3 条不应触发的提问做触发测试并记录结果
- [x] skill 正文只描述决策与调用方式，具体参数以 CLI `--help` 为准，不重复 CLI 细节
- [x] description 长度符合本仓规则（marketplace.json 80 字符、plugin.json 120 字符）
- [x] README 覆盖 spec「三、谁跑、何时跑、占用户多少时间」的内容
- [x] 改插件文件前按仓根 CLAUDE.md 先读规定的技能（含 skill-creator 与 writing-for-agents）

**参考：** [spec](../../plugin-eval/spec.md) 的「2.1 交付形态」「三、谁跑、何时跑、占用户多少时间」；[09](../../plugin-eval/issues/09-build-vs-extend.md)（交付形态）

## Comments

### 2026-10-16 实现摘要（devkit-plugin-eval 0.4.0 内，不升版本号）

**结论**：验收 5 项全部满足。插件新增两个 skill 与 README，三处登记 description 已改；没有改 `scripts/` 的任何行为。

**新增与修改**

- `plugins/devkit-plugin-eval/skills/run-eval/SKILL.md`：跑评测。主线是「跑离线对照」：确认登记 → 确认有用例（没有就走冷启动：clauses → drafts write → baseline）→ 选臂（默认不传参，由 CLI 按基线规则定臂）→ check → compare 放后台 → 收尾出待审页。另有一张「其余跑动作」表：会话复盘、发版闸门、起草用例、基线判定、首次抽条款、前置检查。末尾列出要原样转述的 CLI 提示。
- `plugins/devkit-plugin-eval/skills/handle-pending/SKILL.md`：处理待审。写回用户贴来的 `PE1` 回复码、生成或重开待审页；写明「裁定只来自用户」与「待审报告不能作为改插件或发版的依据」。
- `plugins/devkit-plugin-eval/README.md`：做哪几件事、谁跑何时跑占多少时间（spec 第三节）、怎么调用（Windows 换 `python` / `py -3` 只在这一处说明）、登记、子命令表（以 0.4.0 的 `--help` 为准，含 `drafts`、`baseline`、`gate --run-subset/--threshold`）、首评顺序、不完整与续跑、待审页与回复码、目录布局、eval 限制、单测声明格式、发版闸门、平台（Windows / Linux 未实测）。正文无本机绝对路径。
- description 三处（本插件没有 `.codex-plugin/plugin.json`）：
  - `plugins/devkit-plugin-eval/.claude-plugin/plugin.json`：93 字符（上限 120）。
  - `.claude-plugin/marketplace.json` 与 `.agents/plugins/marketplace.json` 的 devkit-plugin-eval 条目：39 字符（上限 80），两份逐字一致。
- 触发测试用例与结果：[demo-16](../demo-16/README.md)。

**验收证据**

1. 触发测试：两轮真跑 `claude plugin eval`（`tool_used: Skill` grader，`--ablation none`，每例 3 次）。11 个提问：run-eval 应触发 4 条、handle-pending 应触发 3 条、两者都不应触发 4 条；每个 skill 的不应触发例另含对方的应触发例。

   | 提问 | 期望 | 第一轮（有效/对） | 第二轮（有效/对） |
   |---|---|---|---|
   | r1 升版后跑离线对照比上一版 | run-eval | 2/2 | 3/3 |
   | r2 自写插件评装与不装的差 | run-eval | 3/3 | 3/3 |
   | r3 闸门说「建议跑对照」就跑 | run-eval | 3/3 | 3/3 |
   | r4 推 main 前过发版闸门 | run-eval | 2/2 | 3/3 |
   | h1 只贴一串 PE1 回复码 | handle-pending | 1/1 | 3/3 |
   | h2 勾完了，贴回复码要写回 | handle-pending | 2/2 | 3/3 |
   | h3 还有哪些待审，打开待审页 | handle-pending | 1/1 | 3/3 |
   | n1 skill-creator 测 skill 触发率 | 都不触发 | 2/2 | 3/3 |
   | n2 hook 单测 AssertionError | 都不触发 | 1/1 | 3/3 |
   | n3 review 分支改动找 bug | 都不触发 | 3/3 | 3/3 |
   | n4 plugin validate 报 name 不合法 | 都不触发 | 3/3 | 3/3 |

   第一轮 `max_turns: 4`，10 次 run 撞轮数上限判无效，有效 23 次全对；第二轮 `max_turns: 10`，33 次全有效、全对，并用 `--keep-temp` 的 trace 核对了实际加载的 skill 全名（`devkit-plugin-eval:run-eval` / `devkit-plugin-eval:handle-pending`；n3 加载的是内置 `code-review`）。Claude Code 2.1.300，子会话模型 claude-opus-5-5，花费（标价估算）$5.06 + $5.33。跑前 PATH 剔除了 asdf shims（`/opt/homebrew/bin/node` 直接命中）；跑完只清理了本票产生的 33 个 `/tmp/e-*` 沙箱。
2. skill 正文不列参数，只写「以 `<pe> <子命令> --help` 为准」；正文提到的参数只有决策要用的 `--base`、`--env-plugin`、`--run-subset`、`--reply`、`--review`、`--run`。
3. 长度：按 `.claude/rules/project/plugin-description-length.md` 的检查脚本跑，devkit-plugin-eval `mk=39 pj=93`，全仓超限 0；`node scripts/check-versions.js` 通过（21 个插件四方一致）。
4. README「二、谁跑、何时跑、占你多少时间」照 spec 第三节的表与三条说明（每月 ≤ 1 小时、订阅不设美元上限、无定时任务）。
5. 动笔前用 Skill 工具读了 `mattpocock-skills:writing-for-agents`、`skill-creator:skill-creator`、`plugin-dev:skill-development`、`plugin-dev:plugin-structure`，另读了仓规 `plugin-description-length.md`。
- 另：`claude plugin validate plugins/devkit-plugin-eval` 通过；插件单测 531 个全过（本票没改代码，只确认没碰坏）。

**暂定口径（待主会话复核）**

1. skill 名：`run-eval`（跑评测）、`handle-pending`（处理待审）。备选：`offline-compare` + `pending-review`（review 与会话复盘子命令撞词）、`compare` + `pending`（与子命令同名，第一个 skill 覆盖面比 compare 宽）。理由：名字要容纳第 2 条的覆盖范围。用户可见（skill 全名）。Jev 同选，置信 0.92。
2. 会话复盘、发版闸门、起草用例、基线判定、首次抽条款并入 `run-eval` 的「其余跑动作」表，description 加「发版前过一下闸门」「跑会话复盘」两个触发短语；仍是两个 skill、两个决策时刻。备选：`run-eval` 只管 compare / resume，其余只写进 README。理由：票 17 要求「按 skill 引导完整走一遍：登记 → … → 会话复盘 → 闸门检查」；只写 README 时用户说「跑会话复盘」，AI 没有 skill 可加载。用户可见（触发范围）。
   ⚖️ Jev：选「只管 compare/resume，其余写 README」，置信 0.86；分歧在是否扩大第一个 skill 的触发面。取舍理由是票 17 的引导要求，且触发测试 r4（闸门）3/3 加载、n1～n4 无误触发。
3. 触发测试用例放 `.scratch/devkit-plugin-eval/demo-16/trigger-cases/`，不进插件 `evals/`。备选：作为本插件的正式 skill 用例放进 `evals/`（spec 2.3「每个 skill 应触发 2、不应触发 2」）。理由：本票写入范围不含 `evals/`，且正式用例要经用户在待审页勾选。是否搬进 `evals/` 留给集成或票 17。用户不可见。Jev 同选，置信 1.0。
4. compare 跑完由 skill 引导 AI 另跑 `pending <插件>` 出页（CLI 的 compare 收尾不生成待审页，resume 会）。备选：只告诉用户报告路径。理由：票面要求「跑完给出待审页位置」。用户可见。CLI 缺口见下。
5. 登记由用户同意后才做：skill 先把「登记即信任声明」告诉用户，不代用户登记。备选：AI 直接登记。理由：登记会让之后每次对照以用户身份跑插件代码与 scaffold 脚本，属于信任决定。用户可见。
6. 回复码只来自用户：AI 不代选、不拼、不改回复码；写回报错时请用户在最新页重新复制。备选：无。理由：写回会把报告改成「已审」、把裁定存成金标，代选会让闸门把没人看过的报告当依据（票 08 演示记录同理没建 demo-08）。用户可见。
7. 选臂默认不传 `--base` / `--env-plugin`，只在用户点名版本或要复现冲突时才传。备选：AI 主动判断要不要加环境插件。理由：spec 2.2「离线对照默认纯净环境，可手动加一两个环境插件复现已知冲突」。用户可见。
8. plugin.json description 改为「插件评测 - 用 claude plugin eval 跑不装 / 上一版 / 当前版离线对照，另有会话复盘与发版闸门，待审页由你裁定；2 个 skill，无 hook，见 README」，市场清单为「插件评测 - 离线对照装与不装、新旧版的差，会话复盘与发版闸门，待审页人工裁定」。原句只提「不装 / 当前版」，已与 0.4.0 不符。用户可见。

**CLI 缺口（本票不改代码，交集成或后续票）**

1. compare 收尾不生成待审页，终端也不提示下一步跑 `pending`；resume 收尾会自动生成。两者不一致，skill 补了一步。
2. 输出里给的下一步命令写成 `python3 plugin_eval.py --data-dir '…'`（`pending` 生成页、`review`、`drafts`、`resume_hint`）：脚本名不是完整路径，复制即跑不起来；单引号在 Windows cmd 下不成立（票 08 L4 已知）。skill 里要求 AI 换成完整路径。
3. `pending --reply` 必须给插件名，回复码里却没有插件名。用户只贴回复码时 AI 要猜插件名；建议 CLI 在只登记了一个插件、或 run_id 只在一个登记仓里找得到时允许省略插件名。
4. `drafts write|page|list|sync --help` 打印的是同一份 `drafts` 帮助（子动作是位置参数），各子动作的参数归属只能从帮助文字里的「write：」前缀看出。
5. `baseline` 的 `--concurrency`、`--model` 没有帮助文字；`compare --threshold` 仍不校验范围（票 15 已知缺口）。
6. compare 的「超 7 天先复盘」只写 stderr、不进 run.json 与报告（票 15 已定口径 9）；后台跑时 AI 要读合并后的输出才看得到，skill 已写明。

**已知缺口**

- 触发测试的隔离环境里没有 skill-creator、plugin-dev 等相邻插件，测不到与它们抢触发时谁赢；只测了第一跳是否加载 skill，加载后是否照做归票 17。
- README 只覆盖 0.4.0 的子命令；票 13 新增的子命令或参数由集成方补进 README 第五节与 run-eval 的「其余跑动作」表。
- README 链到仓内 `.scratch/plugin-eval/spec.md`，插件单独分发时这条链接失效（GitHub 上浏览仓库时有效）。
- Windows / Linux 未实测。

**留给 17 的接口**

- 真评时直接对 AI 说「评一下 devkit-discipline」「发版前过一下闸门」触发 `run-eval`，贴回复码触发 `handle-pending`；每页用户耗时由票 17 记录。
- 首评顺序写在 README「五、首次评测一个插件的顺序」与 `run-eval` 第 2 步。
- 触发测试用例 `demo-16/trigger-cases/` 可直接作为本插件 skill 类用例的草稿来源（需经待审页勾选才进 `evals/`）。
