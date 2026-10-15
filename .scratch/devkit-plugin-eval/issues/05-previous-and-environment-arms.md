# 05 — 上一版臂与环境插件臂

Status: resolved

**What to build:**

对照支持另外两种臂：

- **上一版**：沿 `HEAD` 按改名追踪 `plugin.json`，找版本号与工作目录不同的最近一个版本，取该版本号**被引入的那个提交**；`--base <提交|版本号>` 可覆盖。用 `git archive` 把当时路径下的插件解到臂组装目录。快照与当前版一样要过前置检查的 hook 冒烟与 validate。
- **环境插件**：入参收 `插件名@市场`（按 `installed_plugins.json` 的 `installPath` 取本机当前版）或路径，拷入臂组装目录、排除 `.in_use/`。
- **退化**：不在 git 仓、历史里没有不同版本号、或快照失败时，自动跳过上一版臂，只跑「不装」与「当前版」，报告首段写明原因。
- **跨改名**：上一版与当前版 `name` 不同时快照原样不动，报告标「跨改名」，列出判分规则写了 skill 全名、因而跨臂不可比的用例。

`run.json` 补齐各臂来源：上一版的提交 sha、版本号、取得方式（自动 / `--base`）、是否退化及原因、是否跨改名；当前版 `HEAD` sha；每个环境插件的来源、版本号与 `gitCommitSha`。

**Blocked by:** 03


- [x] 对本仓一个有多个版本的插件跑改版对照，报告给出上一版与当前版之差，上一版提交是该版本号被引入的提交
- [x] 同一版本号跨多个提交时取引入提交；`--base` 指定提交或版本号均生效
- [x] 对不在 git 仓的插件跑对照，自动退化为两臂，报告首段写明原因
- [x] 对一个改过名的插件跑对照，报告标「跨改名」并列出不可比用例
- [x] 加一个环境插件跑对照，两份插件的注入都生效，`run.json` 记下环境插件来源
- [x] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的「2.2 离线对照（compare）」第 3 步；[14](../../plugin-eval/issues/14-previous-version-arm.md)

## Comments

### 2026-10-15 实现完成

在 worktree 分支上提交，未合并 main、未推送、未改版本号。动 `plugins/**` 前已用 Skill 读过 `mattpocock-skills:writing-for-agents`、`skill-creator:skill-creator`（本票不改 plugin.json、skills、hooks，无追加技能）。

**实现摘要**

- 新模块：`previous.py`（认定上一版、`git archive` 快照、跨改名不可比用例）、`envplugins.py`（环境插件入参解析、拷入、改写用例 `plugins` 字段）、`armplan.py`（决定跑哪几个臂、validate、写进 run.json 的来源字段）、`armreport.py`（report.md 首段与两个新段落）。
- 上一版认定：`git log --follow --date-order` 追踪 `plugin.json`（跨改名），第一个版本号与工作目录不同的就是上一版版本号，再取该版本号在序列里**最早**出现的提交。同号跨多个提交、并行分支各自写出同号（本仓 3.27.0 的 `63c2410` 与 `7023a8b`）时都取最早那个，对应 CONTEXT.md「以该版本号首次出现时的内容为准」。
- `--base`：先按版本号匹配（取引入提交），再按提交解析；该提交没改 `plugin.json` 时，插件路径取它最近的、改过 `plugin.json` 的祖先提交当时的路径。**解析不到就中止（退出码 2），不退化**：用户点名的基线找不到时静默只跑两臂，会掩盖输入错误。
- 退化：没有 git、不在 git 仓、仓里没有提交、历史里没有不同版本号、`git archive` 或解包失败，都跳过上一版臂，`run.json` 的 `previous_arm` 记 `degraded` / `reason_kind` / `reason`，report.md 标题下第一段写明原因。
- 快照与环境插件都过 `claude plugin validate`，不过即中止（spec「2.6 前置检查」：插件结构合法是硬项）。hook 冒烟留给票 04：`Plan.source_dirs()` 给出快照与环境插件目录。
- 环境插件臂（2.1.300 二进制实测）：用例写了 `plugins` 就只加载所列目录，不再自动带上被测插件；所列目录必须在 containment root 内，target 本身是插件时 containment root 就是 target 目录。所以环境插件拷进臂组装目录下的 `_plugin_eval_env/<name>/`（排除 `.in_use/`、`evals/`、`.git`），每个用例的 `plugins` 写「臂组装目录本身 + 各环境插件目录」的相对路径。prompt.md frontmatter 的顶层键覆盖 case.yaml 同名键，所以有 prompt.md 就写进它，否则追加到 case.yaml。用例自带 `plugins` 的不改写，列进 `env_not_applied_cases` 与报告。
- `插件名@市场` 取 `installed_plugins.json`（尊重 `CLAUDE_CONFIG_DIR`）：同一 id 多条安装记录时取 user 范围，没有 user 范围取 `lastUpdated` 最新的。
- run.json：`arms.previous` 记 `source=git-snapshot`、`commit`、`version`、`name`、`path_in_repo`、`obtained_by`（auto / --base）、`base`、`cross_rename`、快照的插件内容指纹；`arms.current_with_env` 记当前版的 `head_sha` / `dirty` 与 `env_plugins`；顶层新增 `previous_arm`（含退化与不可比用例）、`env_plugins`、`delta_vs_previous`、`delta_env_vs_current`。环境插件的 `git_commit_sha`：`插件名@市场` 时照抄 `gitCommitSha`（刷新那一刻市场仓的 HEAD），路径时取该目录所在 git 仓的 HEAD。
- 跨改名：快照原样不改 name；只扫判分规则（`graders/*.md` 与 case.yaml 的 `graders:` 段）里的 `<当前名或旧名>:<skill>`，prompt 里提到不算。不可比用例照列逐用例差，但**不进**「当前版 − 上一版」总体差（`excluded_from_overall`）。
- 新增命令行参数：`compare --base <提交|版本号>`、`--env-plugin <插件名@市场|路径>`（可重复，多个环境插件同装在一个臂里）。单测 117 个全过（新增 32 个，用真 git 在临时目录造历史）。

**真实对照**（devkit-discipline 4.1.0，演示仓是本仓克隆，`evals/` 放 probe 三例加两个演示用例：`env-clickable` 改自 probe 多插件用例、去掉 `plugins` 行；`zh-skill` 的 grader 写了 `devkit-discipline:zh-disambiguate`）。产物在 [demo-05](../demo-05/)，只入库 run.json、report.md、各臂 aggregate-result.json：

| 运行 | 臂 | 结果 | 花费（标价估算） |
|---|---|---|---|
| `20261015T094658Z`，自动认定，每例 3 次 | 不装 / 上一版 / 当前版 | 上一版 4.0.0，取自引入提交 `8ea2db2`；不装 0.37、上一版 0.80、当前版 0.80；当前版 − 上一版 +0.00 | $6.01 |
| `20261015T095228Z`，`--base 3.37.0` 加 `--env-plugin devkit-clickable-paths@claude-devkit-marketplace`，每例 1 次 | 四臂 | 上一版 working-discipline 3.37.0（`c9109dc`），报告标「跨改名」、列出 zh-skill；环境插件臂 1.00，env-clickable 用例当前版 0.00、加环境插件 1.00 | $3.00 |
| `20261015T095711Z`，插件拷到 git 仓外，每例 1 次 | 不装 / 当前版 | 首段「上一版臂已退化……被测插件不在 git 仓里」 | $1.23 |

两份注入都生效的证据（转录只在本机，不入库）：环境插件臂 5 个 run 的子会话转录里，devkit-clickable-paths 的注入标题与 devkit-discipline 的「AI 工作纪律」都在；trace 的 `init.plugins` 同时列出两个插件；当前版臂 5 个 run 的转录里没有 devkit-clickable-paths 的注入。本仓 3.27.0 在两条并行分支上各写一次，`--base 3.27.0` 取较早的 `7023a8b`（只跑了认定，没跑 eval）。

**待拍板**

1. 历史里只有当前一个版本号的插件（新插件首次评测）：本票照 spec 与本票正文算「退化」并写原因；设计票 14 第 4 条写「新插件首次评测按 07 本来就比『不装』，不算退化」。两处对同一情形给的说法相反，要定是否另设一种「无上一版、不算退化」的状态。
2. 跨改名不可比的用例不进「当前版 − 上一版」总体差（逐用例差照列）。spec 只要求列出，没说进不进总体差。
3. `--base` 解析不到时中止，而不是退化。
4. 上一版快照没过 `claude plugin validate` 时中止，照 spec 2.6 算硬项；旧版因 manifest 规则变化而校验不过时，只能换 `--base`。

**已知缺口**

- 快照与环境插件的 hook 冒烟没做，归票 04；合并时把 `Plan.source_dirs()` 接进前置检查，并去掉本票在 `armplan` 里的 validate，或改为调票 04 的实现。
- 没有 `--no-previous`：只要取得到上一版就多跑一臂，花费约多一半。
- `git log --follow` 靠内容相似度认改名：plugin.json 改名时内容变动超过一半（如单行 JSON 同时改 name 与 version）就追不过改名，上一版会在新路径的历史里找，可能误判为退化。本仓插件 `plugin.json` 是多行的，实测能追过去。
- `git archive` 不带被 git 忽略的文件，spec 残余风险第 7 条已记。
- Windows / Linux 未实测。
