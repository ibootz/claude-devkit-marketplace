---
name: worktree-boundary
description: 已经在 worktree 会话里、要动手写文件或要退出时的隔离边界纪律。动手前先定位自己在哪一份 checkout（同名相对路径在父仓与 worktree 里指向两个不同文件，且这个歧义不报错），退出前先确认改动已提交、合回与清理的顺序。撞到 `isolated in the worktree`、`Shell cwd was reset to`、「在 worktree 里改不了父仓的文件」、「cd 出去被弹回」、「worktree 里的 test 和父仓的 test 不是同一个文件」、「改完要不要提交才能合回」、`ExitWorktree`、「合并回主分支」、「清理 worktree」、「让另一个会话帮我改被拦的那一步」时使用。**准备操作 worktree 之前与准备退出 worktree 之前都要读**，别等撞了闸才来。「我在 main 上要落笔、该不该开 worktree」是另一个时刻，走 worktree-flow skill。
---

# worktree 隔离边界与退出

worktree 会话的隔离**只拦写、不拦读**。这个形状决定了本 skill 的两个时刻：动手前要知道自己
落笔在哪一份 checkout，退出前要知道改动能不能合回去。

与 [worktree-flow · 主分支保护流程](../worktree-flow/SKILL.md#判据与两条路径)（讲「main 上要落笔时
该不该开 worktree、怎么申请本轮直写授权」，含正路四步与 submodule 边界）的分工：那份管**进入
之前**的决策，本份管**进入之后到退出之前**。四步流程是那份的正文，这里不重复。

---

## 时刻一 · 动手前定位自己在哪一份 checkout

**同名相对路径在父仓与 worktree 里是两个不同文件，且这个歧义不会报错。** 实测踩过：Human 说
「@test 添加一行」，会话 cwd 在 worktree，AI 用相对路径 `test` 追加，落在
`<仓根>/.claude/worktrees/<名>/test`，而 Human 心里想的是父仓那一份 `<仓根>/test`。两份文件
同名、内容一开始也相同，diff 出来都「看着对」。

动笔前把这四条命令**放在同一条消息里并发发出**（它们互不依赖，逐条单发既慢又会累积串行检索计数）：

```bash
pwd
git rev-parse --show-toplevel
git rev-parse --abbrev-ref HEAD
git worktree list
```

前三条回答「我在哪一份 checkout、它的仓根与分支是什么」，第四条回答「盘上还有哪些 worktree 可进」。

**回复给 Human 时把落点写成绝对路径**，让他一眼看出改的是哪一份。写文件名或相对路径时，这个
歧义会一路静默传到他眼前。

---

## 报错原文 → 拦截者对照表

两层闸的形态相似——都在写操作那一刻拦下——但成因与解法完全不同。**先看报错原文里有没有
`isolated in the worktree` 这句**，有就是隔离，没有再往主分支保护上想。

| 报错里的判据句 | 拦截者 | 真正的判据 | 解法 |
|---|---|---|---|
| `isolated in the worktree` | worktree 会话隔离（harness 工具层） | 目标路径落在父仓共享 checkout 内 | 改 worktree 副本，或 `ExitWorktree {"action":"keep"}` 退出后再写 |
| `[L1-BLOCKER] check=worktree-flow` | 主分支保护（worktree-flow 插件的 PreToolUse） | 目标仓当前分支逐字等于 `main` / `master` | 走 worktree 流程，或由 Human 当轮授权直写 |

隔离那条的完整原文（一字不改，实测抄录）：

```
This session is isolated in the worktree /path/to/repo/.claude/worktrees/<名>. Edit the worktree copy of this file instead of the shared-checkout path.
```

**归因错了的两种后果**：把隔离误报成主分支保护，会让你去申请一个根本用不上的授权；把主分支
保护误报成隔离，会让你以为「换个目录就行」而漏掉授权环节。

同一路径的 `Read` 全程不受隔离约束——**读父仓、写 worktree** 就是这个隔离的实际形状。

---

## 想在 worktree 期间写父仓：三条不通，一条通，一条不许走

| 路 | 结果 |
|---|---|
| 先 `cd` 到父仓再用相对路径写 | **不通**。Bash 的 cwd 被钉在 worktree 内，`cd` 出去即刻复位，stderr 给出 `Shell cwd was reset to <worktree 绝对路径>`。裸 `cd` 另会被 cd-blocker 硬拦 |
| `git -C <父仓>` 改文件内容 | **不通**。`git -C` 只切换 git 命令的操作目录，不落笔文件内容；只读查询（`status` / `log` / `worktree list` / `rev-parse`）已实测可用，而 `git -C <父仓> commit` 会撞主分支保护 |
| 让另一个会话代做 | **明禁**，见下节 |
| `ExitWorktree {"action":"keep"}` 退出后再写 | **通**。隔离即解，worktree 目录与分支留在盘上，随时 `EnterWorktree {"path": ...}` 再进。若父仓在 main/master 上，此时另需向 Human 申请本轮直写授权 |

**这一条是敞口，不是出路**：`printf ... >> /绝对路径`、`sed -i`、`tee`、heredoc、解释器内部
写文件都不依赖 cwd，两道闸都够不着。worktree-flow 自己的注入里就写明了这个漏报。**技术上能
穿透、机制拦不住，靠的是你自己守规**——未获 Human 当轮授权，不得走这条路。（把它写在这里是
为了让你在被问到时能如实回答自己的能力边界，不是给你一条绕闸的捷径。）

**为什么这类敞口存在**：这个隔离拦的是「会话进程的 cwd 与写工具的目标路径」，不是文件系统本身，
所以任何不经 cwd、不经 Write/Edit 的写法天然在它的判据之外。官方 changelog 记载 2.1.210 起连续
四轮修的都是同一类逃逸——子代理借 `isolation: worktree` 对主仓跑 git 变更命令、借 `git -C` /
`--git-dir` / `GIT_DIR` / `GIT_WORK_TREE` 把 git 重定向回共享检出——**说明这类穿透被当作缺陷在
逐版本补，不是留给你用的通道**。（版本沿革属文档转述，未实测；本机 2.1.237 上只实测了 `git -C`
的只读查询可用。）

**遇到「A 与 B 不能并存」时，先检查 A 是不是可以先退掉，再断言做不到。** 实测反例：AI 一度把
结论说成「worktree 期间要写父仓只能人自己搞」——判断偏软，正路是自己调 `ExitWorktree` 把 A
退掉。

---

## 跨会话代做被拦的动作：明禁，一个例外

**判据两条，第二条更严**（原文在 `SendMessage` 工具描述的 "Permission boundaries are
per-session" 段，随版本变化，需要原文时去读那里，不要凭这里的转述）：

1. 本会话**已被拦过**的动作，不得托付他人；
2. **你预计自己的权限设置会拦**的动作，同样不得托付——不需要真撞过闸，凭预判即成立。

要害不在「规矩被违反」，而在 **Human 失去了那个决定点**：本该他看到的确认框跑到了另一个会话
里（或压根没弹），他以为拦住了，实际照做了。

**唯一例外**：Human 在当轮明确重申要发。此时决定点回到了他手上，禁令要防的失效点（他不知情）
不再成立。此时仍要在消息里写清三件事——任务是什么、**我这条消息不构成授权**、边界（只改哪些
文件、能不能提交、不碰什么）。实测有效：对端撞到自己的主分支保护后没把消息当授权，而是自调
`AskUserQuestion` 向 Human 申请，Human 亲自批了才动手。

**对端回执是现象，不是证据。** 它说改好了，自己 `Read` 一遍逐字核对再向 Human 报完成。

---

## 时刻二 · 退出前的四件事

### 1. 先确认改动已提交——合回主分支的前提

`git -C <仓根> merge --no-ff <临时分支>` 合的是**提交**。若任务约束是「只改不提交」，合回这条
路就走不通。

此时**不要自己选一条然后不说**，把冲突端给 Human：要么放弃「不提交」这个约束，要么改走「退出
worktree 后直写主分支（需 Human 当轮授权）」。这个冲突本身就该写进 `AskUserQuestion` 的选项
描述里——端给 Human 的选项必须把真实影响面写明。

### 2. `ExitWorktree` 的两个 action，别混

| 参数 | 效果 |
|---|---|
| `{"action":"keep"}` | 回原目录，worktree 目录与分支留在盘上。**要合回、或还想再进来，用这个** |
| `{"action":"remove"}` | 删目录与分支。**不可逆** |

`remove` 在有未提交改动或未合并 commit 时会拒绝，除非传 `discard_changes: true`。
**这一条未实测，来自工具描述**；而 `discard_changes: true` 是不可逆动作，须 Human 明确确认后
再传，不要因为它「只是个参数」就顺手加上。

**`ExitWorktree` 的作用域是会话级白名单，不是目录级**：它只处理**本会话由 `EnterWorktree` 亲手
建的**那一个 worktree。以 `path` 方式进来的、手工 `git worktree add` 建的、上一个会话建的，一概
不碰——`action: "remove"` 对它们是 no-op，只报「无活动 worktree 会话」。**所以手工建 + `path` 进入
的 worktree，清理必须自己跑 `git worktree remove` 与 `git branch -d`，别指望 `remove` 帮你收尾。**
（依据 `ExitWorktree` 工具描述的 Scope 段。）

### 3. 合回与清理的顺序

先 `ExitWorktree {"action":"keep"}` 回主目录，再在仓根 merge，最后清理。顺序颠倒会在隔离
未解时去动父仓。完整命令见 worktree-flow skill 的四步流程。

### 4. 临时分支不 push remote

### 5. 别把「会话退出时自动清」当成清理手段

交互式会话结束时的自动清理只在**干净且未命名**（无改动、无未跟踪文件、无新提交）的会话上发生；
已命名会话或有工作内容时会先问 Human 保留还是删除。**非交互 `-p` 运行不自动清理**，要自己
`git worktree remove`（若被锁先 `git worktree unlock`）。

删除侧另有一层安全阀：多会话监控里 `Ctrl+X` 两次删会话会连 worktree 一起删（**含未提交改动**），
`claude rm` 在有未提交改动时保留 worktree；但两者都**永不删除有未推送提交、或被其它会话锁住的**
worktree。（本节两段来自官方文档转述，未实测。）

---

## 进入一个已存在的 worktree

`EnterWorktree` 传 `path` 而不是 `name`，进既有 worktree、不新建（已实测成功）。已经在一个
worktree 会话里时不能再用 `name` 建新的，但可以用 `path` 切到另一个已存在的。候选靠
`git -C <仓根> worktree list` 列。

**切换是单向门**：从 worktree A 切到 worktree B 之后，A 留在盘上不动，但**A 不再可写**——要回去
写，得再 `EnterWorktree {"path": A}` 一次。所以在一个会话里来回改两个 worktree，每次换手都要
显式切一次，别以为「刚才能写、现在也能写」。

`path` 落在 `<仓根>/.claude/worktrees/` 之外时会先向 Human 弹一次权限确认（它移动的是会话的
工作目录与写权限）；落在里面或新建 worktree 时不弹。**这两条来自 `EnterWorktree` 工具描述与官方
tools-reference，本轮未实测**——`path` 只实测过 `.claude/worktrees/` 内部这一种。

**这条组合解掉一个实际问题**：`EnterWorktree` 的默认 `worktree.baseRef = fresh` 从
`origin/<默认分支>` 分叉，本地主分支领先远端时会漏掉那些本地提交。已实测的做法是绕过 `name`：

```bash
git -C <仓根> rev-list --left-right --count origin/main...HEAD   # 右边非 0 = 本地领先，fresh 会漏
git -C <仓根> worktree add -b <临时分支名> <仓根>/.claude/worktrees/<名> HEAD
```

再 `EnterWorktree {"path":"<仓根>/.claude/worktrees/<名>"}` 进去。**注意 `ExitWorktree` 不会
删除以 `path` 方式进入的 worktree**，清理要自己跑 `git worktree remove` 与 `git branch -d`。

另一条路是把 `worktree.baseRef` 配成 `head`，但要知道它在 linked worktree 内部取的是**该 worktree
自己的 HEAD**，不是主仓 HEAD（文档转述，未实测）——所以从一个 worktree 里再建 worktree 时，
`head` 的基线未必是你以为的那个。手动 `git worktree add ... HEAD` 把基线写死更不容易搞错。

---

## 什么时候不触发

- **只读操作**——读父仓文件不受隔离约束，不必先定位 checkout。
- **会话不在 worktree 内**——没有隔离这一层，撞到的写拦截一律是主分支保护，走 worktree-flow。
- **目标路径本来就在当前 checkout 内**——同名歧义不成立，直接写。
- **仓库里没有 worktree**，或本轮不打算开——「该不该开」是 worktree-flow 的时刻。
- **worktree 目录内的写操作不会被主分支保护拦**：worktree 建在 `<仓根>/.claude/worktrees/<名>`，
  而 `.claude/` 是主分支保护的自动豁免目录之一。拦它的只有会话隔离那一层。
