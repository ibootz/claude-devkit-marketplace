---
name: tk-worktree
description: 从一个源 worktree 派生出**结构完整的聚合仓 worktree**（父仓 + 全部 submodule（子模块）层，含嵌套递归），落点固定 `<source>/.keeper/<交付id>/debug/<id>/worktree/`，并能整体合并回源 worktree 的分支。`git worktree add` 只建父仓工作区、submodule 目录全是空的，本 skill 负责把它们按父仓记录的 gitlink（父仓 index 里那条 `160000` 模式条目，值是子仓某次提交的 40 位 SHA）真正 checkout 出来，并提供状态查询 / 清理 / 回流。核心纪律：linked worktree 里永远走 `git worktree add` 供给、绝不用 `git submodule update --init`；gitlink 一律以**源侧同层 index** 为准。
when_to_use: |
  用户或 keeper 说"新 worktree 里 submodule 是空的"、"worktree 里子模块没内容"、"给 worktree 补子模块"、"给这个 issue 开一个带完整子模块的工作区"、"submodule update --init 之后回流失败/not our ref"、"清理 worktree 的子模块工作区"、"把 worktree 里子模块的改动合回源分支"。
---

# worktree 的 submodule 供给

## 概述

`git worktree add` 只建**父仓**的工作区。父仓 index 里每个 submodule 只是一条 **gitlink**（tree 里一个 `160000` 模式的条目，值是子仓某次提交的 40 位 SHA），git 不会顺带把子仓内容 checkout 出来——所以新 worktree 里所有 submodule 目录**存在但为空**，`git -C <wt> submodule status` 每行带 `-` 前缀表示未初始化。

**"供给"**（supply）= 把这些空目录按父仓已记录的 gitlink 填上内容。正确手法是对每个 submodule **也各自 `git worktree add`**，且一律**从源侧那个 submodule 目录**发起，产物 `.git` 是一个**文件**，内容形如：

```
gitdir: /path/to/source/.git/modules/libs/b/worktrees/b
```

这样子模块的对象库与源侧**共享**，源侧那些只存在本地、还没 push 的提交在新 worktree 里可见，回流也不会失败。

脚本：`scripts/wt_supply.py`（Python 3 标准库，无第三方依赖）+ `scripts/wt_git.py`（git 原语）+ `scripts/wt_levels.py`（层级遍历与供给）+ `scripts/wt_par.py`（批量的并发底座）+ `scripts/wt_scope.py`（`explain-scope` 的实现）。

**源 worktree（source）** 是本 skill 的基准概念：它可以是主 checkout，也可以本身就是个 linked worktree（从 worktree 再派生 worktree 完全合法）。所有供给都从源侧发起，因此**主 checkout 的 submodule 初始化状态全程不被触碰**。

## 两条铁律（最重要，先看）

### 铁律一：linked worktree 里绝不跑 `git submodule update --init`

在 linked worktree（`git worktree add` 出来的第二个工作区）里跑 `git submodule update --init <sm>`，产物 `.git` 也是文件，**但指向 `<super>/.git/worktrees/<wt>/modules/<sm>`——那是一个完整独立对象库**：有自己的 `objects/` `refs/` `packed-refs`，**没有** `objects/info/alternates` 链回源仓。后果是源侧的本地未推送提交在这里**永远看不到**，即便 `fetch` 过也是 `fatal: could not get object info`。

实测两种典型爆法：

```
# 供给时：gitlink 指的提交从未 push 到 upstream，独立对象库 fetch 不到
fatal: remote error: upload-pack: not our ref 863f4f414a1a...
fatal: Fetched in submodule path 'libs/b', but it did not contain 863f4f4...

# 回流时：同因，反向报
fatal: git upload-pack: not our ref <sha>
```

所以：**只走 `git worktree add`，一次都不要把 `submodule update --init` 当兜底手段。** 本脚本自己也不跑它——源侧某层未初始化（无 `.git`）时判为 `source-missing` 并 fail-loud，要求你先在**源 worktree 侧**把那层补齐，而不是替你在目标侧硬造一个独立对象库。

配套的一个坑：若源侧该 submodule 未初始化（空目录、无 `.git`），`git -C <那个空目录> <cmd>` 会**静默向上逃逸到父仓执行**（`git -C libs/a rev-parse --git-dir` 解析成 `super/.git`），于是报出语义完全无关的 `fatal: invalid reference: 3d40d5a`。看到这种"引用莫名不存在"先查源侧有没有 `.git`，不要去怀疑 SHA。

### 铁律二：gitlink 一律以**源侧同层 index** 为准

```bash
git -C <源侧父仓> rev-parse :<submodule相对路径>     # ✅ 唯一正确来源
git -C <主checkout> rev-parse :<submodule相对路径>   # ❌ 已知同类工具的真实 bug
```

不同 worktree 在不同分支上，各分支记录的 gitlink 不同。实测：主 checkout 在 `main`（`libs/b` → `d410752`），从 `b1` 派生的 worktree 记录的是 `863f4f4`。从主 checkout 读会**静默检出错误版本**——不报错、内容却是别的分支的，极难发现。

本脚本的做法是把"源"显式化：`init` 从 `--source` 指定的那个 worktree 的 HEAD 派生目标 worktree，此后每一层的 gitlink 都读**源侧父仓的 index**（`supply_level` 里 `gitlink_sha(level.parent_src, level.rel)`）。源侧既是派生基线、也是 gitlink 权威，两者天然一致，不存在"猜该用哪个分支的 gitlink"的空间。

## 六个子命令

### init —— 主入口，一条命令建出完整聚合仓 worktree（支持批量并行）

```bash
# 单个 id
python3 scripts/wt_supply.py init --source <源worktree绝对路径> --id <ID> \
    [--branch <name>] [--dry-run]

# 批量：一条命令并发建多个 id 的 worktree（keeper 派 fixer 前的标准形态）
python3 scripts/wt_supply.py init --source "$ROOT" --ids DBG-017,DBG-018,DBG-019 \
    --jobs 3 --quiet
```

做四件事：建父仓工作区（`git -C <source> worktree add <target> -b <branch> HEAD`）→ 把源路径记进目标 worktree 的 gitdir → 全量递归供给所有 submodule 层 → 自校验（等价 `status`）。批量时每个 id 各自完整走这四件事。

- **落点固定 `<source>/.keeper/<交付id>/debug/<id>/worktree/`，不可配。** 核心原因：很多工具链（hook、状态注入、路径识别）靠 **cwd 的路径字面量**反推"当前处于哪个工作区"——目标 worktree 落在源 worktree **内部**时，它的绝对路径天然包含源 worktree 的完整路径前缀，这类识别全部照常工作；落到外部（比如与源平级的目录）会被静默判成另一个无关工作区，没有任何报错。一个真实例子：某交付框架的路径识别常量是 `MARKER = '/.sdlc/worktrees/'` + slug 白名单（只认 `^D-\d+` / `^hotfix-` 开头），fixer worktree 若直接落到 `.sdlc/worktrees/DBG-021`，MARKER 命中但 slug 校验不认，一整串依赖 cwd 判断的 hook 集体失准；落在源 worktree 内部的 `.keeper/<交付id>/debug/DBG-021/worktree/` 则前缀完整保留、识别不受任何影响。这条约束在"落点必须在源 worktree 内部"之上又收紧一级：**落进它所属那条 issue 自己的目录**——v3 曾放在与队列数据平级的 `.keeper/worktrees/<id>/`，同一条 bug 的 issue / receipts / 截图 / worktree 分散在四棵子树里，删一条要记四处；v4 收进 `debug/<id>/worktree/` 之后，一条 issue 的全部东西就是一个目录。**挪走这个落点会静默破坏宿主工具链的 worktree 识别。**
- `--id` 只接受 `^[A-Za-z0-9][A-Za-z0-9._-]*$`（字母数字开头，由字母数字与 `.` `_` `-` 组成），因为它直接当目录名用，不接受路径分隔符。
- 分支缺省 `fix/<交付id>-<id>`。基线是**源 worktree 的 HEAD**，不是 master。
- **源侧未提交的改动不会进目标 worktree**（`worktree add ... HEAD` 只带走 HEAD 的内容）。有未提交改动时会列出最多 10 项警告你。
- 记源之后，`supply` / `status` / `remove` / `merge-back` 的 `--source` 都**可以省略**。
- **幂等**：目标已登记为 worktree 且分支一致 → 跳过创建、直接续跑供给；分支不一致 → fail-loud，要么先 `remove --yes`，要么用 `--branch` 指定成已有的那个续跑。
- 自校验非全绿 → 退出码 `2`，且**已建出的部分刻意不回滚**，保留现场供排查；修掉根因后重跑同一条 `init` 即可。

#### 批量三参数：`--ids` / `--jobs` / `--quiet`

| 参数 | 语义 |
|---|---|
| `--ids` | 逗号分隔的多个 id。与 `--id` **二者至少给一个**；**同时给报错**（不静默取其一）。`--ids` 里有空元素（多写了逗号）或重复 id 也报错——这三类是整条命令级的错用，什么都不建就退出 `1` |
| `--jobs N` | 并行度，**缺省 3**。`--jobs 1` 等价串行（压根不建线程池，可用它把「并行引入的问题」与「本来就有的问题」切开）。`< 1` 报错。实际并行度取 `min(N, id 个数)` |
| `--quiet` | 不打印逐层供给与自校验清单，只留每个 id 一行结论。**自校验本身照跑**——非全绿仍然退出 `2`，且此时把完整逐层清单打全（省的是成功路径的输出，不是失败路径的信息） |

- **`--branch` 与批量互斥**：`--ids` 给了两个以上 id 时再给 `--branch` 直接报错。多个 id 共用一个分支名不合理，而静默忽略它同样是坑。要自定义分支名就一个一个用 `--id` 跑。
- **一个 id 失败不牵连其他 id**：每个 id 的失败被独立捕获、独立汇报，其余 id 照常建完。退出码汇总规则是 **有任一 id 失败 → `1`；没有失败但有 id 自校验非全绿 → `2`；全绿 → `0`**（单 id 时这套规则与批量化之前逐字等价）。失败详情打到 stderr、每行带 `[<id>] ` 前缀；stdout 末尾恒有一段汇总：

  ```
  [wt_supply] init 汇总：3 个 id → 成功 2 / 自校验非全绿 0 / 失败 1
    ok      DBG-030  新建 3 / 跳过 0 层 → /abs/.../debug/DBG-030/worktree
    fail    BAD/ID  id 只接受字母数字开头、由字母数字与 . _ - 组成的名字，收到：'BAD/ID'
    ok      DBG-031  新建 3 / 跳过 0 层 → /abs/.../debug/DBG-031/worktree
  ```

  失败后**只需重跑失败的那几个 id**（`init` 幂等，已建好的层再跑是 no-op）。**id 的形态校验刻意放在单个 id 的任务里**而不是命令入口，就是为了让一个 id 拼错不把整批打回去。
- **输出按 id 分组，不是实时交错**：多 id 时每个 id 的输出先攒在自己的缓冲区里，跑完整块吐出、每行带 `[<id>] ` 前缀。逐层输出靠缩进表达嵌套深度，实时交错会把树形打散。代价是一个 id 跑完才见到它的输出——批量的调用方是 subagent，不是盯屏的人。
- **并行安全靠三处机制**（改这三处前先读对应函数的注释，它们是踩出来的）：
  1. `wt_git.git()` 的**锁冲突退避重试**（`LOCK_RETRIES=5`、指数退避 `0.1s` 起、上限 `2s`，累计约 3.1s）。判据是 stderr 里的确定字符串，**不是非零退出码**——`index.lock` / `cannot lock ref` / `could not lock config file` / `Unable to create …*.lock` 这四条是写侧；第五条 `failed to read '…/locked'` 是读侧竞态：`worktree list` 撞上并发 `worktree add` 正在建删的 `locked` 标记文件（`--jobs 6` 压测实测踩到）。其他失败一律照原样 fail-loud，不重试。
  2. `wt_levels.reserve_branch()` 的**按源仓 realpath 的进程内互斥锁**，解 `pick_branch()` 的 check-then-act 竞态。它把「定名 + 建分支 ref」放进临界区（毫秒级），耗时的 checkout 留在锁外并行跑——所以 `worktree add` 用的是 `<path> <已存在分支>` 形态而不是 `-b`。若改回 `-b`，临界区就会包含整棵工作树的 checkout，所有 id 在同一个 submodule 上串行、并行度归零。
  3. 每个 id 的落点与分支名天然按 id 隔离（`debug/<id>/worktree/`、`fix/<交付id>-<id>`），不同 id 之间没有共享的目标状态。
- **实测量级**（3 层测试仓：父仓 + 2 个 submodule + 1 个嵌套）：8 个 id × `--jobs 8` 连跑 3 轮共 24 个 worktree、72 层，全绿；6 个 id 的 `--jobs 6` 对 `--jobs 1` 是 0.71s 对 2.56s。`--quiet` 把 3 个 id 的输出从 73 行压到 9 行。

### supply —— 全量递归供给（不改任何 gitlink 指针）

```bash
python3 scripts/wt_supply.py supply --worktree <目标worktree> \
    [--source <源>] [--branch <name>] [--dry-run]
```

正常流程用不到它——`init` 已经包含供给。单独用它的场景是：父仓工作区已经在了（别人建的、或 `init` 半路失败后续跑），只想把 submodule 层补齐。

- **供给范围 = 源侧 `.gitmodules` 声明的全部顶层 + 递归嵌套层，不限层数、不做子集裁剪。** 早先有过"按 issue 落点只供给相关几个"的设计，已被推翻：修一个 bug 常常要顺手改 spec（住在 `sdlc/` 这类 submodule 里）、要查知识库、要翻组件库做 UI 组件溯源，按落点裁剪会在半路卡住。判影响面的需求转由只读的 `explain-scope` 承担。
- `--source` 缺省读 `init` 时记下的那份；既没给又没记录时 fail-loud：
  ```
  [wt_supply] 失败：没给 --source，且 <path> 的 gitdir 里也没有 wt-supply-source 记录
    建议下一步：显式加 --source <源 worktree 绝对路径>
  ```
- `--branch`：submodule 侧新分支名，缺省用目标 worktree 父仓的当前分支名。
- **目标侧形态机械照抄源侧**：源侧该层在分支 → 目标侧 `-b <branch>`；源侧 detached → 目标侧 `--detach`。已 `ok` 但形态与源侧不匹配时只打印提示、**不自动纠正**（要纠正得先 `remove` 这一层再 `supply`）。
- **幂等**：已 `ok` 的层再跑是 no-op，且照样继续下探嵌套层。
- 源侧无 `.gitmodules` → 打印 `[wt_supply] <source> 没有 .gitmodules，无 submodule 需要供给。` 并退出 `0`，不用特意先检测。

供给成功的样子（一级 + 嵌套两层）：

```
  [libs/a] gitlink=7c528417ce3a 状态=empty 源侧=分支 main → 目标侧 -b fix/D-001-DBG-017
    已供给：分支 fix/D-001-DBG-017，.git → /src/super/.git/modules/libs/a/worktrees/a
    [vendor/n] gitlink=ff0eb5e95c42 状态=empty 源侧=分支 main → 目标侧 -b fix/D-001-DBG-017
      已供给：分支 fix/D-001-DBG-017，.git → /src/super/.git/modules/libs/a/modules/vendor/n/worktrees/n
```

嵌套层的存储路径规律是 `<父模块 git-dir>/modules/<子路径>`，例如 `super/.git/modules/libs/a/modules/vendor/n/worktrees/n`。

**分支占用**：复用已被别的 worktree 检出的分支名会报 `fatal: '<branch>' is already used by worktree at '<path>'`。脚本命中这类情况（或同名分支已存在）时自动换派生名 `<基础分支名>-<submodule路径末段>`，例如 `fix/D-001-DBG-017` → `fix/D-001-DBG-017-b`；派生名也不可用则 fail-loud，让你用 `--branch` 显式指定，**不盲目重试**。

### status —— 逐层报状态

```bash
python3 scripts/wt_supply.py status --worktree <目标worktree> [--source <源>]
```

输出每层（含嵌套）的 path、状态、以及源侧/目标侧的形态差异。退出码 `0` = 全 `ok`，`2` = 有非 `ok` 层。

### remove —— 深度优先清理

```bash
python3 scripts/wt_supply.py remove --worktree <目标worktree> \
    [--source <源>] [--keep-parent] [--keep-branches] [--force-delete-branches] [--yes]
```

缺省只打印计划，加 `--yes` 才执行。**缺省会连父仓工作区一起删干净**（最后一步 `git -C <source> worktree remove <target>`）；只想清 submodule 层、保留父仓工作区时加 `--keep-parent`。源 worktree 全程不受影响。

**缺省还会自动清理每一层 `init`/`supply` 建过的分支**（`fix/<交付id>-<id>` 或 `pick_branch` 派生出的同名分支），不需要额外手工删。判据是尝试安全删除（`git branch -d`）：这条分支若已经被 `merge-back --apply` 合入源侧对应分支，或者压根没产生过新提交（这次 issue 没实际碰这个 submodule），`-d` 都能直接删掉；若分支还有未合并的提交（没跑过 `merge-back` 就直接 `remove`，例如 reject 场景），`-d` 会拒绝，脚本此时只打印保留原因、**不阻断 worktree 本身的删除**，也不静默丢内容。理由与实现见 `wt_supply.py` 里 `try_delete_branch` 的函数注释。`--keep-branches` 跳过这整段清理（想保留分支供人工核实时用）；`--force-delete-branches` 对未合并的分支也强删（`-D`），需要显式传，不是默认行为。

**顺序必须深度优先（先子后父）**：先删父会报 `fatal: working trees containing submodules cannot be moved or removed`。

删掉子层 worktree 会把目录物理删除，父层随即出现 `D <path>` 变 dirty，父层自己的 `worktree remove` 就报 `contains modified or untracked files, use --force to delete it`。脚本的解法是**把空目录 `mkdir` 回来**——对未初始化的 submodule，git 认为空目录即干净状态，父层立刻恢复 clean（实测有效，之后 `worktree remove` 直接通过）。

刻意**不用**另两条路，将来也不要加回来：

- `git submodule deinit -f <子路径>`：实测在 linked worktree 里 deinit 会从**与源仓共享的** `.git/config` 里删掉 `submodule.<name>.url`，连主 checkout 的 `git submodule status` 都跟着从 ` `（已初始化）变成 `-`（未初始化）——那是波及主 checkout 的副作用，超出本脚本职责。而本链路的供给全部从源侧发起、从不碰主 checkout 的 submodule 初始化状态，压根没有需要 deinit 收拾的东西。
- `worktree remove --force`：那是掩盖因果，不是消除原因。若报 `contains modified or untracked files`，说明里面真有未提交内容，先人工确认要不要留。

  **这条只管 `contains modified or untracked files` 这一种拒绝。** `git worktree remove` 还有另一种拒绝——`fatal: working trees containing submodules cannot be moved or removed`——它是结构性的、与干净度无关（实测：worktree 完全干净、只要有一个已初始化的 submodule 就照样 exit 128），`--force` 在那里跳过的东西与安全无关。本脚本自己不需要 `--force` 是因为它用「深度优先 + 空目录回填」把那种拒绝从根上消掉了；**没有对应脚本的场景（例如销毁 delivery worktree 本身）必须加 `--force`**，见 `skills/tk-debug/references/queue.md` §6「销毁 delivery worktree」。判据是看报错原文，不是看命令。

### merge-back —— 回流（会改 gitlink 并建 commit，默认 dry-run）

```bash
python3 scripts/wt_supply.py merge-back --worktree <目标worktree> [--source <源>] [--apply]
```

把目标 worktree 各层合回**源 worktree 对应分支**并回写 gitlink。**没有 `--onto` 参数**：合并落点就是源 worktree 当前所在的分支，各层的落点是源侧那一层当前所在的分支。

顺序**自底向上**（最深嵌套层先合），父仓最后。每层做三件事：**先 commit 子层刚回写的 gitlink → `git merge --no-ff <目标侧分支>` → 把本层新 HEAD `git add` 进父层**。

"先 commit"这一步不是可选的。实测（2026-07-29）：若把子层合出的新 HEAD 留在工作树里不 commit 就直接 merge 父层，git **不会**报错，而是把父层 gitlink 直接写成目标侧那个 tip、丢掉源侧刚做出的 merge commit，工作树留下一条 `M <sm>`——源侧该层若本来有自己的提交，那些内容就在这一步被静默丢弃。

**前置校验**（任何一条不过就整体阻断、不做局部执行，退出码 `2`）：目标侧父仓不能 detached HEAD；层状态为 `isolated-objdir` / `unreachable` / `source-missing` / `prunable` 一律阻断；**每层源侧分支必须等于源父仓分支**——聚合仓的各层应与父仓同名分支同步推进，不一致时无法判定该层该合到哪里，故整体阻断（旧实现在这里静悄悄合到错分支，是必须修的缺陷）。

**目标侧与源侧的干净度判据不对称，这是刻意设计（2026-07-30 改）**：

- **目标侧（父仓与每一层，即 fixer 的工作区）沿用全树严格检查**——`git status --porcelain -uall` 只要非空（已剔除登记在案的嵌套 worktree 目录）就阻断。目标侧脏了就说明 fixer 有没提交的产物，必须硬拦，不能收窄。
- **源侧（父仓与每一层，即主会话——人 + AI——日常干活的地方）改用两条收窄判据**，不再要求全树干净：
  1. **index 必须干净（硬拦）**：`git diff --cached --name-only` 非空即阻断。理由是 `--apply` 分支里回写 gitlink 的 `git commit` 不带 pathspec，会把 index 里**所有**已 staged 的内容一并卷进那条"回写 gitlink"的提交里；错误信息会列出具体文件并提示"先 commit 或 `git restore --staged <path>` 撤出暂存区"。
  2. **未 staged 的脏文件（含未跟踪），只在与本次 merge 实际会触碰的路径相交时才阻断**；不相交的一律放行，仅在输出里以"提示"列出（不是 blocker），说明"这些文件与本次合并无关、已放行"，避免静默。相交时才拦，因为这种情况下 `git merge` 自己也会报 `local changes would be overwritten by merge` 而拒绝——提前在这里拦下是等价的，只是把报错时机挪早、给出更明确的定位。"本次 merge 会触碰的路径"用 `git diff --name-only <合并起点>..<目标侧分支tip>`（父仓是 `<源侧当前 HEAD>..<目标侧根分支>`，每层是 `<该层源侧 HEAD>..<该层目标侧分支>`）算出。

  为什么源侧不能像目标侧一样全树严格：源 worktree 是主会话（人 + AI）的日常工作区，任何一点与本次回流无关的半途 WIP（未提交、未跟踪、正在改的文档等）都会被全树检查误伤，导致 debug-keeper 手上**每一条** issue 的回流全部被无关 WIP 挡死——这是 2026-07-30 的真实死锁，收窄判据就是为了消除它，同时仍旧挡住"已 staged 内容被静默卷入 gitlink 提交"这个真正的危险。

两类不阻断的跳过：目标侧 `empty`（那层没供给过，无内容可回流）；源侧 detached 的层照设计不参与回流——但若目标侧在这种层上有了新提交则阻断，因为那些提交没有分支承载、回流没有落点。

**默认 dry-run，零副作用**，逐层打印新旧 gitlink（短 hash + 日期 + message）对照 + 跨越的提交清单（最多 20 条）；只有 `--apply` 才真正执行。`--apply` 会在**源侧各层与父仓上建 commit**（gitlink 回写用 `chore(wt-supply): …`，合并用 `merge(wt-supply): …`），但**不 push**。

merge 冲突若**全部**落在本仓声明的 submodule 路径上（即纯 gitlink 冲突），按"取工作树里已 merge 好的实际 HEAD"自动 `git add` + `commit --no-edit` 收敛——本流程自底向上，子层早已合完并前进到包含双方内容的提交。有任何一条非 gitlink 冲突就整体阻断，且**已成功的层刻意不回滚**（整个流程幂等可重跑）：要么在那一层人工解冲突后 `git commit` 再重跑同一条 `--apply`（已合完的层会显示 Already up to date），要么 `git merge --abort` 放弃这一层——注意比它更深的层已经合完、不会被 abort 撤销。

### explain-scope —— 只读，判影响面

```bash
python3 scripts/wt_supply.py explain-scope --worktree <worktree> --from-triage <issue.md>
```

读该 markdown，把正文里所有 `<path>:<行号>` 形态的文件引用抽出来，用 `.gitmodules` 声明的 path 做前缀匹配（取最长匹配），反推这条 issue 涉及哪些 submodule。macOS 上 `/tmp` 与 `/private/tmp` 是同一处、两种字面都可能出现在 issue 里，脚本对前缀不匹配的引用会退一步按路径段边界找。

**它不决定供给范围**，纯只读、不改任何东西。`supply` 一律全量供给源侧声明的所有层，不按这个结果裁剪。它的用途是排查时判影响面、写 issue 时核对是否漏了某一层。

## 状态判据表

| 状态 | 判据 | 处置 |
|---|---|---|
| `ok` | `.git` 是**文件**，指向的 gitdir 有 `commondir`、**没有**自己的 `objects/`，且该 commondir **等于源侧同层的 git-common-dir** = 对象库与源侧共享 | 无需动作；`supply` 跳过 |
| `empty` | 目录不存在，或存在但没有 `.git` | 跑 `supply` |
| `isolated-objdir` | `.git` 是**目录**，**或** `.git` 文件指向的 gitdir 是一个完整独立对象库（有 `objects/`、无 `commondir`），**或** commondir 与源侧同层不一致 | 典型来源是踩了铁律一。不能原地转成共享 worktree，`rm -rf` 该目录后重跑 `supply`；里面若有未推送提交先 `git bundle create` 或 push 到别处备份 |
| `unreachable` | `.git` 是文件，但指向的 gitdir 已不存在 | `rm -rf` 该目录后重跑 `supply`，并在源侧 `git worktree prune` 清残留登记 |
| `prunable` | 目录被手动 `rm -rf` 掉，但仍登记在 `git worktree list` 里 | `git worktree prune`；`supply` 会自动先 prune 再重建 |
| `source-missing` | **源侧**这一层没有 `.git` | 先在源 worktree 侧把这层补齐再供给目标。源侧缺内容时目标侧无从供给，且没有对象库可比对，其余判据全部无意义，故**优先**返回它 |

`ok` 的判据换过一次，这点值得记住：现在用的是"commondir **等于源侧同层的 git-common-dir**"，取代了早先的"commondir 落在 `<主仓>/.git/modules/` 之下"。后者只认"主 checkout 侧有对象库"这一种拓扑，会把**源侧本身是 worktree 私有克隆的那些层**全部误判成 `isolated-objdir`（实测 18 个层集体误判）。

层的枚举一律从**源侧** `.gitmodules` 递归展开，不从目标侧：目标侧未供给的层是空目录、读不到它自己的 `.gitmodules`，从目标侧枚举会看不见嵌套层的存在（旧实现的已知盲区）。

判"谁是主 checkout"可靠地取 `git worktree list --porcelain` 的**第一个** `worktree ` 行——实测从主 checkout / 任一派生 worktree 三个视角跑，结果完全一致，第一条恒为主 checkout（不是发起命令的那个）。从 worktree 再派生 worktree 也完全合法，这正是本 skill 的常规用法。

## 典型调用链

```bash
S=/abs/path/to/源worktree
DID=_main   # 交付 id：源 worktree 目录名匹配 ^(?:D-\d+-|hotfix-) 才取该名，否则落 _main
W=$S/.keeper/$DID/debug/DBG-017/worktree

# 建：一条命令搞定父仓工作区 + 全部 submodule 层 + 自校验
python3 scripts/wt_supply.py init --source "$S" --id DBG-017

# 建一批（3-8 条 issue 同时开工时用这条，不要 for 循环调 N 次上面那条）
python3 scripts/wt_supply.py init --source "$S" --ids DBG-017,DBG-018,DBG-019 \
    --jobs 3 --quiet

# 查（--source 已被 init 记住，可省）
python3 scripts/wt_supply.py status --worktree "$W"

# 回流：先 dry-run 逐层核对新旧 gitlink，确认后再 --apply
python3 scripts/wt_supply.py merge-back --worktree "$W"
python3 scripts/wt_supply.py merge-back --worktree "$W" --apply

# 清理（缺省只打印计划）
python3 scripts/wt_supply.py remove --worktree "$W" --yes
```

## 什么时候不触发

- **只建一个 worktree 时不要用 `--ids`**：一个 id 就用 `--id <ID>`。判据是 id 个数，不是"要不要快"。`--ids DBG-017` 这种单元素形态虽然能跑，但它不会带来任何并行收益，只会让输出形态与既有文档、既有调用方不一致（单 id 走的是「不加前缀、流式打印」，和批量的「按 id 缓冲 + `[<id>] ` 前缀」是两套）。
- **`--jobs` 不要往大调**：并行度受益的是「等 git 退出」这段 I/O，不是 CPU。id 个数以内取 3（缺省值）足够；调到远大于 id 个数没有意义（实际取 `min(--jobs, id 个数)`），而所有 id 都写同一个源仓，并行度越高撞锁越频繁、越依赖退避重试。
- **失败重跑时只重跑失败的 id**，不要整批重来。`init` 幂等，但整批重跑会让已建好的 N-1 个 id 各自再走一遍全树 `classify()`，纯浪费。
- **仓里没有 submodule**：`.gitmodules` 不存在 / `git submodule status` 空输出（注意它此时 **exit 0**，不报错）。脚本会直接打印"无 submodule 需要供给"并退出 0，不用特意先检测。
- **只是想移动 gitlink 指针**（把父仓记录的子模块提交从旧 commit 改成新 commit，即 bump / 拉齐 / 同步到最新）：那是 `submodule-gitlink-update` skill 的事，不是本 skill。本 skill 的 `supply` 是**按源侧已记录的 gitlink 原样把内容拉出来**，不改指针。
- **目标是主 checkout 而不是 linked worktree**：直接 `git submodule update --init <path>` 即可，脚本会 fail-loud 拒绝。

## 与 gitlink 红线的关系（避免误拦 / 误用）

本插件有一条常驻红线：更新 submodule gitlink 前必须列出新旧 commit 的 message + 短 hash + 日期并列给用户确认。对应到本 skill：

- `init` / `supply` / `status` / `remove` / `explain-scope` **不改任何 gitlink 指针**，属于纯供给与清理，**不触发**该红线，不需要确认流程。
- `merge-back` **会改指针并在源侧建 commit**，所以它默认 dry-run，并在输出里逐层打印新旧 commit 的 message + 短 hash + 日期以及跨越的提交清单，供人确认后才 `--apply`。这正是该红线要求的形态。
