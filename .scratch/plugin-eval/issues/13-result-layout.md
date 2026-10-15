# 13: 评测产物与状态落在哪、什么格式

Type: grilling
Status: resolved
Blocked by: 无

## Question

[缺口里哪些自建、以什么形态](09-build-vs-extend.md) 定了 `devkit-plugin-eval` 的产物种类，[评测范围](06-scope.md) 定了用例与结果放在被测插件所在仓、会话原文不入库。还要定目录约定与文件格式，才能事后复核：

1. **被测插件仓内**：用例（含 AI 起草、待勾选的草稿区）、每次离线对照的运行结果（各臂 `aggregate-result.json`、注入到达核验、AI 评委两遍判分）、会话复盘的抽取结果、本地 HTML 待审页、报告与它的「待审 / 已审」状态，各放哪个目录、什么格式、哪些入库。
2. **用户级**：花费账本、被测插件登记清单、上次复盘时间、上次对照时的 Claude Code 版本与主力模型，放在 `~/.claude` 下哪里。
3. **金标样本**归被测插件仓还是用户级——它来自用户裁定过的分歧样本，用来校准 AI 评委。
4. 闸门检查命令要靠什么记录判断「某版本有已审报告 / 规则子集通过 / `eval-skip:`」。

## Answer

> **2026-10-15 部分覆盖**：用户 2026-10-15 撤销美元花费上限（原话「由于我使用的是订阅 测评额度不适用 可以去掉 避免因为额度干扰了测评的质量」），随后拍板四项连带决定（原话「Q17 用最贵那一档 比如Fable模型 其他按照建议」），记录见 [08](08-cadence-and-budget.md) Comments。作废：用户级目录里的花费账本 `ledger.jsonl`。现行：用户级只放登记清单与 trace 缓存；`run.json` 的花费字段保留，只作信息。

2026-10-15 用户一轮拍板，原话「全部按推荐来」，七问全按推荐。Jev（jev-1.13.0）七题与推荐一致。

**目录总图**（`<repo>` 是被测插件所在仓的根，`<plugin>` 是被测插件名）：

```
<repo>/plugins/<plugin>/evals/<case>/        # 已通过的用例，eval 原生位置，随插件分发
<repo>/plugin-evals/<plugin>/                # 插件目录外，入库，不分发给安装者
  drafts/<case>/                             # AI 起草、待勾选的用例草稿
  runs/<时间>-<版本>-<compare|gate>/          # 一次运行一个目录
    run.json                                 # 唯一真源
    arms/<臂>/aggregate-result.json
    injection-check.json                     # 注入到达核验
    judge.json                               # AI 评委两遍判分、金标一致率、用户裁定
    samples/<id>.jsonl.gz                    # 用户看过的样本 trace
    report.md
  reviews/<日期>.json                         # 会话复盘抽取结果，不含原文
  gold/<id>.json                             # 金标样本
~/.claude/plugins/data/devkit-plugin-eval-<marketplace>/
  ledger.jsonl                               # 花费账本
  registry.json                              # 被测插件登记清单
  traces/                                    # 全量 trace 本机缓存，留 90 天
```

1. **用例**：通过的用例放 `<plugin>/evals/<case>/`，用 eval 原生格式（`prompt.md` / `case.yaml` + `graders/`），可直接裸跑 `claude plugin eval`，随插件分发。草稿放插件目录外的 `plugin-evals/<plugin>/drafts/`——eval 递归扫描 `<eval dir>/**`，草稿放在 `evals/` 下会被当正式用例跑掉。条款归属、规则子集成员用 `tags` 标（frontmatter 只有 `tags` 能挂自定义标记，未知 key 报错）。
2. **结果根目录**：`<repo>/plugin-evals/<plugin>/`，入库、不分发。外围脚本跑完把 eval 写进 `<plugin>/evals/results/` 的产物搬过去；`<plugin>/evals/results/` 加进 `.gitignore`。插件目录就是仓根时，产物仍会分发，接受这个例外。
3. **trace 入库范围**：入库结构化结果（各臂 `aggregate-result.json`、两遍判分、注入到达核验、报告），加上用户看过的样本 trace（分歧、抽检、金标），压缩存放。全量 trace 只留本机用户级目录 90 天（与本机 `cleanupPeriodDays` 一致）。这放宽了地图常设偏好「原始运行数据要入库」，已在地图 Notes 标注。
4. **运行记录与审阅状态**：每次运行一个目录，`run.json` 是唯一真源，字段含插件名、版本、插件内容指纹、各臂、Claude Code 版本、主力模型、花费、`kind`（`compare` 离线对照 / `gate` 规则子集）、是否通过、审阅状态（待审 / 已审）与审阅时间。`report.md` 给人读，状态改动由 CLI 改写。HTML 待审页在本机生成、不入库；用户贴回的回复码裁定写回 `run.json` 与 `judge.json`。
5. **用户级**：放 `~/.claude/plugins/data/devkit-plugin-eval-<marketplace>/`，只存三样——花费账本 `ledger.jsonl`、登记清单 `registry.json`（插件名 + 所在仓路径）、全量 trace 缓存。上次复盘时间、上次对照时的 Claude Code 版本与主力模型**不另存**，从各仓 `reviews/` 与 `run.json` 现算；为此会话复盘对每个登记的插件都写一份 `reviews/<日期>.json`，零计数也写。卸载插件时账本可能被清，只影响当月预算统计，接受。
6. **金标样本**：归被测插件仓 `plugin-evals/<plugin>/gold/`，入库。内网插件的金标留内网仓。代价是各插件各攒各的，启用门槛（见 [判分分工与人工介入点](11-judging-and-human-checkpoints.md)，未定）更晚达到。
7. **闸门判据**：闸门检查命令扫 `runs/*/run.json`。某版本过闸 = 存在同版本、且**插件内容指纹**与当前一致的记录，二者之一：已审的离线对照，或通过的规则子集。指纹算整个插件目录、排除 `evals/`（补用例不让已审报告失效）。指纹不一致视为未过闸——堵住并行会话撞版本号、审后改内容不升版两种误放行。「本次需评测」的声明与紧急跳过都写在升版提交的提交信息 trailer 里（`eval-required: <理由>` / `eval-skip: <理由>`），命令读 git log。不另设 `gate.jsonl`，不往 `plugin.json` 加字段。

**对其它票的约束**：

- [「上一版」臂的插件目录怎么产出](14-previous-version-arm.md)：用例在 `<plugin>/evals/` 里，上一版快照里的是旧用例或没有用例；外围脚本要把**当前**用例放进每个臂的插件目录，各臂跑同一批用例。14 已于同日关闭，其 Answer「用例一律取当前版」与此一致。
- 地图 fog「用例从哪来」：草稿的落点已定为 `drafts/`，来源与构造方式仍在 fog。

**未选**：用例与草稿都放插件目录外、草稿打 `tags: draft` 留在 `evals/`；结果留 eval 默认位置；全量 trace 入库、trace 一律不入库；状态写进 `report.md` frontmatter、每插件一份 `index.jsonl`；用户级放 `~/.claude/devkit-plugin-eval/`、另存 `state.json`；金标放用户级；闸门只比版本号、另维护 `gate.jsonl` 并把声明写进 `plugin.json`。

**残余不确定**：

- 用例目录里放 eval 不认识的附加文件会不会报错，未实测；条款归属先只用 `tags`。
- 外围 Python 命令行从技能里调用时能否拿到 `CLAUDE_PLUGIN_DATA` 环境变量，未查；拿不到时由脚本按自身缓存路径推出 marketplace 名再拼目录。
- 内容指纹的具体算法（文件清单排序、换行归一）留给实施。

**重开条件**：

- 入库的样本 trace 让被测插件仓体积每月增长超过约 2MB，重议第 3 条的样本范围。
- 用户事后需要重看一条未入库、且已过 90 天的 trace，重议第 3 条。
- 「审后改一字就要重跑」的成本让闸门被频繁 `eval-skip:` 绕过，重议第 7 条的指纹范围。

## Comments

### 2026-10-15 第一轮提问（待答）

已认领。补查事实：

- `claude plugin eval --help`（本机）：用例目录默认 `<plugin>/evals/`，`--eval-dir` 或 `plugin.json` 的 `experimental.evals` 可改，但必须在插件目录之下；递归扫描 `<eval dir>/**/case.yaml|prompt.md`；结果写 `<plugin>/<dir>/results/<时间戳>/`。
- 插件安装时整个插件目录进用户缓存（`devkit-discipline/4.1.0/` 缓存里有 `test/`），放在插件目录内的文件会分发给每个安装者。市场仓克隆是浅克隆（`--is-shallow-repository` 为 true），HEAD 里累积的文件每个用户都要下载。
- 05 那轮完整对照（3 例 × 3 次 × 2 臂 = 18 run）的 trace 原文 2.6MB，`tar.gz` 后约 0.66MB。
- 本机有 `~/.claude/plugins/data/<plugin>-<marketplace>/` 插件数据目录。

第一轮问七件，Jev（jev-1.13.0）七题均与 AI 推荐一致：用例与草稿位置（Jev 0.73）、结果根目录（0.55）、trace 入库范围（0.43）、运行记录与审阅状态（0.97）、用户级目录（0.66）、金标归属（0.94）、闸门判据记录（0.80）。

### 2026-10-15 第一轮答复

用户原话「全部按推荐来」，七问照推荐定，见 Answer。同轮改写：地图 Decisions so far 追加一行、Notes 常设偏好补 trace 入库例外；`CONTEXT.md` 新增「用例草稿」词条、「发版闸门」补「内容未变」。
