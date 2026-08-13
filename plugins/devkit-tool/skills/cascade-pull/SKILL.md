---
name: cascade-pull
description: 带 submodule 的 Git 仓库同步拉取——父仓拉最新、子模块 checkout 到位、gitlink 对齐，是 `git pull` 增强版。与 `cascade-push` 配对但作用域相反：**只处理本仓直接声明的一层 submodule，绝不递归嵌套层**。诊断父仓/子模块/远端三方差异后由用户选拉取模式，移动 gitlink 前列新旧提交给用户确认。
when_to_use: |
  用户说"拉一下代码/更新代码/同步仓库"、"pull 完子模块还是旧的/没更新"、"submodule dirty 或 detached HEAD"、"更新/bump submodule 指针"、"把某个 submodule 提升到最新"、"submodule 落后要拉齐"、"更新 gitlink"时使用。
  **核心判据**：仓库有 `.gitmodules` 且要把父仓与子模块同步到一致。单仓无 submodule 直接 `git pull` 即可，不需要本 skill。嵌套递归拉取（多层子模块一路往里 pull）不是本 skill——本 skill 只处理一层、严禁 `--recursive`；递归推送方向（由内向外提交）才用 `cascade-push`。
---

# 带 submodule 的仓库同步拉取（增强版 pull）

## 命名说明：`cascade-` 前缀在本 skill 不表示递归

本 skill 与 `cascade-push` 同属 devkit-tool 的 submodule 能力对，前缀取自配对命名，**不表示本 skill 会级联进嵌套子模块**。两者的作用域恰好相反，动手前先认准：

| skill | 方向 | 作用域 |
|---|---|---|
| `cascade-push` | 提交推送（由内向外） | **递归全嵌套树**，按路径深度降序逐层提交、逐层 push |
| `cascade-pull`（本 skill） | 拉取同步 | **只处理父仓 `.gitmodules` 直接声明的一层**，禁止 `--recursive`，见铁律一 |

把本 skill 当成"递归拉取"来用会直接违反铁律一。需要让嵌套层的 pin 到位时，正确做法是 bump 本层一个指针、让上游替你递归（铁律一正文有展开）。

## 概述

普通 `git pull` 在带 submodule 的仓库里**只完成了一半**：它更新父仓的文件和 **gitlink**（父仓 tree 里一个 `160000` 模式的条目，记录"子模块应该停在哪个 commit"），但**不会**把子模块工作树 checkout 到那个新 commit。结果是拉完之后子模块目录里还是旧代码，`git status` 里显示子模块 dirty（`m` 标记），编译 / 运行用的仍是过期版本。

本 skill 覆盖两件事，都围绕"让子模块代码真正到位"：

1. **模式 A — 父仓 pull + 子模块工作树对齐到父仓记录的 gitlink**（消费上游，不动 gitlink，不产生提交）
2. **模式 B — 子模块拉到远端最新 + 更新父仓 gitlink 并提交**（生产上游，会产生父仓提交）

两者结果完全不同，**不得由 AI 替用户默认选一个**（见铁律三）。

## 三方差异模型（先建立这个模型，后面所有判断都基于它）

任何一个 submodule 在任意时刻有三个互相独立的 commit 值，**它们两两都可能不等**：

| 记号 | 含义 | 怎么读 |
|---|---|---|
| **G** = gitlink | 父仓记录的"应该停在哪" | `git ls-files -s <sm路径>` 取第 2 列（父仓将提交的值）；父仓 HEAD 记录的值用 `git rev-parse HEAD:<sm路径>` |
| **W** = 工作树 HEAD | 子模块目录里实际 checkout 的 commit | `git -C <sm> rev-parse HEAD` |
| **R** = 远端 tip | 子仓跟踪分支最新提交 | `git -C <sm> fetch origin --prune` 后 `git -C <sm> rev-parse origin/<branch>` |

常见组合与含义：

| 状态 | 现象 | 归属 |
|---|---|---|
| G=W=R | 全齐 | 无需动作 |
| G≠W | `git status` 里子模块显示 dirty / `new commits`，编译用的是 W 的代码 | **模式 A** 解决（把工作树 checkout 到 G） |
| G=W，W≠R | 子模块代码与父仓声明一致，但落后子仓主干 | **模式 B** 才需要动（bump G 到 R） |
| G≠W 且 W≠R | 两个问题叠加，**必须先 A 再判断要不要 B**，否则 bump 会把本地漂移一起带进 gitlink | 先 A 后 B |

**这个模型解决的核心误判**：`git status` 显示子模块 dirty ≠ 需要 bump gitlink。绝大多数"子模块怎么是脏的"其实是 G≠W（模式 A，本地没同步），跟 gitlink 该不该前进（模式 B）无关。

## 三条铁律

### 铁律一：只处理本仓直接绑定的 submodule，绝不递归

只处理父仓 `.gitmodules` 里**直接声明**的 submodule，**不要**用 `--recursive`、也不要进入某个 submodule 内部去更新它自己的 submodule。原因：嵌套的子模块（submodule 里的 submodule）通常由**其他人 / 其他团队维护**，递归操作会把不属于你职责范围的绑定一起改掉，造成越权变更、且极难回溯。

- 用 `git config --file .gitmodules --get-regexp '^submodule\..*\.path$'` 列出**本层**声明的 submodule，只在这个清单内操作。
- 禁止 `git submodule update --init --recursive`、禁止 `git pull --recurse-submodules`。
- 逐个显式 `git submodule update --init -- <path>` 并逐个验证，见"模式 A"。

**当用户点名要 bump 的目标其实是嵌套子模块（submodule 的 submodule）时** —— 不要因此破例递归。先查**本层直接子模块的目标 commit** 是否已经用 gitlink **链式带入**了你要的下层 pin：

```bash
git ls-tree <本层目标commit> <本层子模块路径>        # 取本层目标记录的下一层 pin
git -C <本层子模块> ls-tree <上一步的pin> <再下层路径>  # 逐层往下看，直到你要 bump 的那层
```

上游子仓的 owner 提交这个目标 commit 时，通常已自底向上把整条嵌套链 bump 并 push 好。此时只需 bump 本层**一个**指针，整条链（如 `work→sdlc→ontology/requirements`）的 pin 就随之到位 —— 满足需求、不越权、无需替任何子仓 push。这是铁律一的正面形态：**让上游替你递归**，你只动本层。

只有当本层目标 commit **未**记录你要的下层 pin（说明需求要在中间层新建 commit）时才是例外：这会触发"必须替中间层子仓 push，否则本层指针悬空"的两难 —— 停下告知用户，已超出本 skill 单层同步的范畴。

### 铁律二：移动 gitlink 前，列出新旧提交的 commit message 给用户确认

在真正移动 gitlink（模式 B）之前，对每个待更新的 submodule，必须把**当前绑定提交**和**将要绑定提交**的 commit message（连同短 hash、日期）并列出来，并列出两者之间**跨越的提交清单**，交用户确认后再动手。**绝不静默 bump。** 确认清单格式见"模式 B"。

### 铁律三：诊断先行，模式由用户当次选，AI 不预设默认

跑完只读诊断（S0）后，把三方差异摆给用户，**由用户当次决定走模式 A 还是模式 B**（或先 A 后 B）。不得因为"看起来落后了就顺手 bump"，也不得因为"看起来只是没同步就默默只做 A"而隐瞒可 bump 的空间。

**例外（可不问直接执行）**：用户当轮已明确点名模式——如"把 X 子模块 bump 到最新"（=B）、"pull 一下代码让子模块跟父仓一致"（=A）。此时铁律二仍然生效（B 仍要列 commit 确认）。

## 标准流程

### 脚本路径（三个脚本共用，先取一次）

三个脚本随本 skill 分发，路径用插件根变量取，**不要**写成相对当前目录的 `scripts/xxx.sh`——脚本要在被诊断的父仓根目录下执行，那里没有 `scripts/` 这个目录：

```bash
SD="$CLAUDE_PLUGIN_ROOT/skills/cascade-pull/scripts"
```

拿不到 `$CLAUDE_PLUGIN_ROOT` 时（少数宿主不注入该变量），改用插件安装目录下的绝对路径 `plugins/devkit-tool/skills/cascade-pull/scripts/`。

### S0 · 只读诊断（永远第一步）

在**父仓根目录**执行：

```bash
"$SD"/diagnose-sync.sh               # 全部直接 submodule
"$SD"/diagnose-sync.sh domains/spsd  # 只看指定的（可多个）
```

它输出：父仓 behind/ahead + 未提交改动，以及每个直接 submodule 的 G / W / R 三值与差异判级。**唯一副作用是 `git fetch`**（更新 remote-tracking），不改工作树、不改 gitlink、不 commit。

诊断发现父仓或子模块有未提交改动时，先停下问用户（stash / commit / 放弃），**不要**用 `checkout -f` / `reset --hard` 覆盖别人的在制品。

### S1 · 摆差异、由用户选模式（铁律三）

把 S0 结果按 submodule 逐条列出，指明每条属于哪种状态（G≠W / W≠R / 两者兼有），再问走 A 还是 B。

### S2A · 模式 A：父仓 pull + 子模块对齐到 gitlink

```bash
git pull --no-recurse-submodules       # 父仓拉最新；显式禁递归（铁律一）
"$SD"/sync-to-gitlink.sh               # 逐个非递归对齐 + 逐个验证
```

`--no-recurse-submodules` 不是可选项：Git 若配了 `submodule.recurse=true` 或 `fetch.recurseSubmodules`，`git pull` 会自动递归进嵌套层，直接违反铁律一。**不确定当前配置时就显式写这个 flag**。

`sync-to-gitlink.sh` 对每个直接 submodule 做 `git submodule update --init -- <path>`，然后逐个断言 `git -C <sm> rev-parse HEAD` 等于父仓索引里的 gitlink 值。**不允许**用一条 `--recursive` 代替，它常被某个子模块（未初始化 / fetch 失败）中途打断，剩下的静默不同步。

模式 A **不产生任何父仓提交**。做完 `git status` 里父仓应当是干净的（除非用户本来就有在制品）。

### S2B · 模式 B：子模块拉到远端最新 + bump gitlink

1. **圈定范围**：读 `.gitmodules` 取本层直接 submodule 清单，只在清单内选目标（铁律一）。默认只动用户点名的，不擅自全量。
2. **确定目标提交**：是"子模块远端跟踪分支的最新 tip"（最常见），还是用户指定的某个 commit / tag。跟踪分支取自 `.gitmodules` 的 `branch` 字段（缺省按 `master`，勿假设一律 main）。
3. **逐个预览（只读）**：`"$SD"/preview-gitlink-bump.sh [路径...]` 生成确认清单（铁律二）。
4. **用户确认**：展示确认清单，等用户明确同意。有 ⚠️ / 🔴 告警项（见"健康诊断"）逐条说明。
5. **执行更新**：`git -C <sm> checkout <target>`，回父仓 `git add <sm路径>`。**只 add submodule 路径，不 add 其它。**
6. **父仓提交**：全部目标处理完，在父仓一次 commit，message 写清每个 submodule 的 `from→to`（短 hash）与含义。

确认清单格式（铁律二落地）：

```
=== domains/spsd (跟踪分支: master) ===
当前绑定: 28f466e chore: 归并 v2.64 需求包 (2026-07-01 10:22)
将要绑定: a1b2c3d feat: 新增岗位序列模型 US-07 (2026-07-10 15:40)
跨越 2 个提交:
  a1b2c3d feat: 新增岗位序列模型 US-07
  9f8e7d6 fix: 修正序列层级校验
确认更新? (y/n)
```

### S3 · 验证（两种模式都要做）

- **gitlink 值看 `ls-files -s`，不看工作树**：`git ls-files -s <sm路径>` 第 2 列是父仓将提交的 commit id。
- 模式 A：每个 submodule 的 `git -C <sm> rev-parse HEAD` 应等于其 gitlink 值；父仓无新增暂存。
- 模式 B：`git ls-files -s <sm路径>` 应等于目标 commit；`git status` 确认父仓暂存的**只有**目标 submodule 路径。

## Bump 前健康诊断（三量判据）

判断"该不该 bump、目标是否合理"，**不要信** `git submodule status` 的 `+/-`（只比索引 vs checkout）和 `git describe` 的分支名（就近取名，会误导）。fetch 后算三个量：

```bash
git -C <sm> fetch origin --prune          # 必须先 fetch，否则自带假绿灯
behind=$(git -C <sm> rev-list --count HEAD..origin/<branch>)
ahead=$(git -C <sm> rev-list --count origin/<branch>..HEAD)
reachable=$(git -C <sm> branch -r --contains HEAD)   # 空 = 悬空
```

| 判级 | 条件 | 含义 / 动作 |
|---|---|---|
| 🟢 健康 | behind=0 且 ahead=0 | 已在 tip，无需 bump |
| 🟡 陈旧 | behind>0 且 ahead=0 | 落后主干，正常 bump 到 tip |
| 🟠 离题 | ahead>0 | 当前 HEAD 领先 / 停在未合并分支，**bump 前确认**是否要切回跟踪分支 |
| 🔴 悬空 | 远端不可达 | 当前或目标 HEAD 未 push，**禁止 bump 到此**（别人 clone 会断） |

三条判据铁律：`ahead>0` 才是真离题（`describe` 异名 ≠ 离题）；必须先 `fetch`，否则 behind 是下界、🟢 可能假阳性；健康快照有时效性（会持续漂移），批量 bump 要临近执行时重新 fetch。

## Gitlink"回退"的判读：`--is-ancestor` 报非祖先不等于内容真丢失

判断"要不要把 gitlink 从当前值改到某个新值"时，如果新值相对旧值不是祖先关系
（`git merge-base --is-ancestor <旧值> <新值>` 返回非零），不能直接把这当成"内容会丢失"的结论
——**"旧值不可达"与"内容真的丢失"是两件必须分开判断的事**。

### 第 0 步：先分辨"非祖先"的两种成因，再谈内容有没有丢

`--is-ancestor` 返回非零有两个完全不同的原因，混为一谈会把最常见的"纯落后"误判成"有分叉"：

| 成因 | 判据 | 含义 |
|---|---|---|
| **本地缺对象** | `git -C <sm> cat-file -e <commit>^{commit}` 失败 | 子仓本地根本没有这个提交，祖先关系**无法判定**（不是判定为假）。fresh clone / 父仓刚 pull 出新 pin 的子仓里这是**常态而非例外** |
| **真分叉** | 对象存在，`--is-ancestor` 仍返回 1 | 子仓本地确有独立提交，或停在别的分支 |

之所以是常态：**父仓 pull 与子仓取对象是两个独立动作** —— `git pull --no-recurse-submodules`
只搬 gitlink 的**数值**，不搬子仓的 commit **对象**；新 pin 的对象要靠后面的
`git submodule update` 或一次显式 fetch 才下来。所以判祖先之前必须先确认对象在本地：

```bash
if ! git -C <sm> cat-file -e "<G>^{commit}" 2>/dev/null; then
  git -C <sm> fetch origin --prune --no-recurse-submodules    # 缺对象 → 先取，再判
fi
git -C <sm> merge-base --is-ancestor <W> <G>                  # 此时的非零才是真分叉
```

**不要用 `2>/dev/null` 吞掉 `--is-ancestor` 的 stderr** —— 对象缺失时 git 的报错正是区分
两种成因的唯一信号，吞了就只剩一个非零退出码，两者同形。`sync-to-gitlink.sh`
曾因此把 9 个纯落后的子仓全数当作"本地有独立提交"跳过（2026-08-03 实测）。

**示例场景（泛化自一次实战排查，具体仓库/分支名仅作示例）**：某父仓的一个 delivery 分支下，
某 submodule 的 gitlink 曾被外部操作（如另一个发布线分支的回写）指向了一个"发布线"分支的 tip，
而不是这条 delivery 分支自己应该指向的 HEAD。把 gitlink 改回 delivery 分支自己的 HEAD 时，
`--is-ancestor` 检测报"回退"、显示会丢若干个 commit——但逐条查这些 commit 的 subject 后发现，
它们**全部**是"合入发布线"形态的 merge 壳（merge commit），merge 进去的内容正是 delivery 分支
自身已有的工作，已经全部在新 HEAD 的祖先历史里，实际内容丢失为零。

**判读顺序（缺一不可，不能只看 `--is-ancestor` 的返回码就下结论）**：

1. `git log --oneline <新值>..<旧值>` 逐条列出"会丢的" commit。
2. 逐条看它们是 merge 壳（合并另一分支时产生的、不携带独立内容改动的 merge commit）还是携带
   独立改动的原始 commit——merge 壳零风险，可以直接改；若其中含有其它分支的原始改动（不是
   merge 壳），则是真回退，必须停下、不擅自继续，报告用户由其决定。
3. 做一次语义校准：目标分支的 gitlink 本应指向"这条分支自己的" submodule commit；指向了另
   一条线（如发布线、其它 delivery 分支）的 tip 属于错位——错位会导致 worktree 里 checkout
   出来的 submodule 代码与父仓 gitlink 声明的版本不一致，即便这次判读显示内容零丢失，错位本身
   仍应作为问题记录并订正。

这条判读同样适用于上一节"健康诊断"给出 🟠 离题（`ahead>0`）判级时的进一步分析——`ahead>0`
只说明当前 HEAD 领先或停在未合并分支，而是否真的存在"回退风险"要靠上面这三步逐条验证，不能
仅凭判级颜色直接下结论。

## 其它最佳实践

- **禁止 bump 到远端不可达的 commit**：目标提交必须已在子模块远端（`git -C <sm> branch -r --contains <target>` 非空），否则父仓会指向别人拉不到的悬空引用。
- **不替子模块 push**：更新 gitlink 只在父仓提交；子模块内部的提交 / 推送是其 owner 的职责，本 skill 不 push 子模块远端，也不改子模块内容。
- **默认分支逐个读取**：跟踪分支来自 `.gitmodules` 的 `branch` 字段，不同 submodule 可能不同（有的 master 有的 main），不要一刀切。
- **批量也要逐条确认**：多个 submodule 一起 bump 时，逐个列确认清单，不要静默批量 checkout。
- **父仓 commit message 规范**：写明 `bump <sm>: <from>→<to>` 及覆盖的提交范围 / 意图，便于追溯。
- **区分三个命令语义**：`git submodule update`（把子模块拉到父仓已记录的 gitlink，"按父仓走" = 模式 A）vs `git submodule update --remote`（把子模块更新到远端分支最新，"往前走" = 模式 B 的前半段）vs `git pull`（只动父仓）。模式 B 用 `--remote` 语义，但要显式、逐个、经确认，不要无差别对全部子模块跑。
- **`--recursive` 会半途而废**：`git submodule update --init --recursive` 常被某个子模块（未初始化 / fetch 失败）中途打断，剩下的静默不同步；别用 `2>/dev/null` 吞掉它的报错。
- **gitlink 正确性看索引，不看工作树**：下层工作树没 checkout 到位、`git status` 里显示 `m`（dirty），都不改变待提交的 gitlink 值 —— 别因工作树脏就不敢提交，也别拿工作树 `rev-parse HEAD` 当 gitlink 真相源。
- **脚本兼容 bash 3.2**：macOS 自带 `/bin/bash` 是 3.2，本 skill 三个脚本已避开 `mapfile` 等 4.x 内建；若自行改脚本，别引入 4.x 语法。
- **子仓 fetch 一律带 `--no-recurse-submodules`**：`git fetch` 默认 `recurseSubmodules=on-demand`，会顺着子仓自己的 `.gitmodules` 递归进嵌套层——既违反铁律一，又在嵌套层未初始化时刷一串 `Unable to fetch in submodule path` 噪音（如 `kng` 下的 `ontology`）。这些报错**不影响本层结果**，但会误导判读，源头掐掉比事后解释便宜。`git submodule update` 同理，写成 `git -c fetch.recurseSubmodules=no submodule update --init -- <path>`。
- **`set -o pipefail` 下不接 `head`**：`git log … | head -N` 在输出超过 N 行时，head 取满即关闭管道，git 收 SIGPIPE 非零退出（`exit=141`），`pipefail` 把它变成整条管道非零，`set -e` 当即让脚本自杀——`diagnose-sync.sh` 曾因此**凡父仓 behind>0 必挂**，子模块段一行都跑不到。git 自带 `-n` 的一律用 `-n`；`git status` 这类无限行参数的先收进变量再 `awk 'NR<=N'` 限行（awk 读完全部输入才结束，不提前关管道）。

## 边界 / 不做什么

- 不 `--recursive`、不 `--recurse-submodules`、不进嵌套子模块改其 gitlink（铁律一）。
- 不修改子模块内部文件、不代子模块向其远端 push。
- 不在未展示新旧 commit message、未获用户确认的情况下移动任何 gitlink（铁律二）。
- 不替用户预设拉取模式；不擅自全量 bump，只动用户点名的 submodule（铁律三）。
- 不用 `reset --hard` / `checkout -f` / `clean -fdx` 覆盖父仓或子模块里的未提交改动——发现在制品先停下问用户。
