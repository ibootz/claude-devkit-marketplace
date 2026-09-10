---
name: worktree-flow
description: 在 main/master 分支改文件或 git commit 时，默认走「开 worktree 临时分支 → 提交 → --no-ff 合回 → 清理」；确需直接写时，用 AskUserQuestion 取得 Human 本轮授权。被 `[L1-BLOCKER] check=worktree-flow` 拦下、用户说“开 worktree”“别在 main 上改”“本轮允许直接改 main/master”“合并回主分支”“清理 worktree”“还有别的会话在跑这个仓”“另开一个隔离空间做”时使用。管的是**进入 worktree 之前**那个决策；已经在 worktree 会话里、要落笔或要退出时的隔离边界纪律走 worktree-boundary skill。
---

# 主分支保护流程（worktree-flow）

## 判据与两条路径

当前仓分支逐字等于 `main` 或 `master`，且要改仓内文件或执行 `git commit` 时触发。默认选
worktree；只有 Human 明确批准本轮直写，才留在主分支操作。

不触发：非 git 目录；detached HEAD；已在其他分支；merge / rebase / cherry-pick 进行中；
目标落在 `.claude/`、`.keeper/`、`.git/`、`WORKTREE_GUARD_EXEMPT` 目录，或启用
`WORKTREE_GUARD_EXEMPT_DOTDIRS=1` 后的顶层点目录。

## 第二个触发时刻：同仓有别的会话在动

上面那条判据看的是**分支**。还有一个更早的时刻看的是**并发**——会话刚接到一个要改文件的
需求，而同一个仓可能正有别的会话在工作。此时开 worktree 的理由与主分支保护无关：`git` 的
索引是**全仓共享**的，两个会话各自 `git add` 之后谁先 `git commit`，谁就带走当时索引里的
全部暂存，与「是谁 add 的」无关。受害方会看到 `no changes added to commit`——一个字面说得通、
但完全不指向真因的报错。

**判据交给 Human，不要自己探测。** 五类探测手段已逐条实测（`git worktree list`、
`.claude/worktrees/` 目录、`ps` 配 `lsof -a -p <pid> -d cwd -Fn` 查 claude 进程 cwd、
`~/.claude/projects/` 下 session 文件的 mtime、`~/.claude/` 下的 socket 与 lock 文件），
**没有一种是单条命令、秒级、且可靠的**：`~/.claude/` 下不存在任何仓库级的活跃标记，
`daemon.lock` 是全局单例且 cwd 会漂到 `$HOME`，`$CLAUDE_CODE_MESSAGING_SOCKET` 按 pid 命名。
最接近的是 `ps` 抓带 `--resume` 的主进程再用 `lsof` 核 cwd 这个组合，但它**漏报**（对方走
IDE 插件启动，或 cwd 落在某个 worktree 子目录——每个 worktree 有自己独立的 projects 转义
目录，要逐个枚举）也**误报**（残留的 spare 进程），且必须先排掉自己那条进程链——实测中
险些把本会话自己 fork 的源 session 当成「另一个会话」。

所以：**Human 说了「还有别的会话在跑这个仓」才走隔离流程**，不主动探测、不主动弹选择框。
理由是错报的代价不对称——漏报只是回到默认行为（他会说），误报却是每次落笔都打断他一次，
而这种噪音会让整条纪律被他亲手关掉。

**允许的弱提示，仅此一种**：`git worktree list` 里除主仓外还挂着别的条目时，可以在回复里
附**一句话**——「盘上还挂着 N 个 worktree，要隔离就说一声」。不要把它升格成选择框，也不要
把「盘上有 worktree」当成硬触发——一个长期使用 worktree 的仓里这个条件恒真，硬触发会立刻
退化成每轮噪音。

## 默认路径：worktree

### 1. 开工作区

先比 base ref：

```bash
git -C <仓根> rev-parse HEAD origin/$(git -C <仓根> symbolic-ref --short HEAD)
```

一致则调：

```json
{"name":"<仓名短名>-<功能词1>-<功能词2>-<功能词3>"}
```

命名规则：

- 先取仓根目录名，转为合法的 lowercase `kebab-case`；仓名过长时保留能识别项目的短名。
- 仓名后追加功能词，功能最多 3 个；删除 `fix`、`feat`、`task`、`worktree` 等无辨识度前缀。
- 无需凑满 3 个功能词；优先使用 `hook`、`auth`、`config` 等能表达任务核心的词。
- 同名冲突时，仅追加 4 位短 hash；目录名与临时分支名保持一致。

例如：`claude-devkit-fix-hook`、`claude-devkit-review-auth`、`devkit-market-add-guard`。

`EnterWorktree` 建 `worktree-<name>` 并切入 `.claude/worktrees/<name>/`。若本地主分支领先远端，
默认 `worktree.baseRef = fresh` 会漏本地提交；改设 `head`，或从本地 `HEAD` 手动建 worktree。

### 2. 在临时分支改与提交

```bash
git -C <worktree 路径> add -A
git -C <worktree 路径> commit -m "feat(xxx): ..."
```

切进 worktree 之后本 skill 的职责就结束了。**落笔前先定位自己在哪一份 checkout、撞到写拦截时
先分清是三道闸里的哪一道、退出前先确认改动已提交**，这三件事见
[worktree-boundary · worktree 隔离边界与退出](../worktree-boundary/SKILL.md#时刻一--动手前定位自己在哪一份-checkout)
（同名相对路径在父仓与 worktree 里指向两个不同文件且不报错；三道闸的归因对照表；
`ExitWorktree` 两个 action 的取舍）。

**其中一节现在就要记住：撞闸不是终点。** 三道闸各自的解都在你手上，没有一道的正解是把命令
交给 Human 敲——会话隔离用 `ExitWorktree {"action":"keep"}` 纯自解，主分支保护用 finding 里
那份 `AskUserQuestion` 就地申请（他点一下选项，不是替你敲命令）。展开与三次实测反例见
[worktree-boundary · 撞闸不是终点——三道闸的解都在你手上](../worktree-boundary/SKILL.md#撞闸不是终点三道闸的解都在你手上)
（含退—改—回三步往返，与「唯一真的退不出去」那种情形该怎么办）。

### 3. 合回主分支

先以 `ExitWorktree {"action":"keep"}` 回主目录，再执行：

```bash
git -C <仓根> merge --no-ff <临时分支> -m "merge: <本批说明>"
```

撞冲突时，guard 因 `MERGE_HEAD` 存在而放行解决与收尾 commit。

### 4. 清理

```bash
git -C <仓根> worktree remove <worktree 路径>
git -C <仓根> branch -d <临时分支>
```

临时分支不 push remote。`branch -d` 拒删未合并分支时，不得改用 `-D`。

## 例外路径：Human 批准本轮直写

guard 首次命中会拒绝操作，并在 finding 中给一份完整 `AskUserQuestion` 输入，含实际仓、分支、
目标及影响。主会话原样调用它；不得自填 `answers` 或 `annotations`。Human 选择“批准本轮”后，
重试原操作。

授权边界：

- 覆盖当前会话**本轮**所有 `main` / `master` 写入与 `git commit`，不是只放首个文件。
- 下一次用户消息、Stop 或 SessionEnd 即撤销；临时状态另有 24 小时 fail-safe 过期。
- Human 选择 worktree、跳过、写自由文本、加备注、发生 AFK 自动继续、回执结构未知时，均不授权。
- 子代理不能调用 `AskUserQuestion`；撞闸后须把仓、分支、目标与直写原因交回主会话申请。
- 本机制不靠 `permissionDecision: "ask"`；本机 `bypassPermissions` 下该档实测不弹框而直接放行。

## 含 submodule 的聚合仓

普通 `EnterWorktree` 只建父仓，submodule 目录为空。需完整结构时用 `task-keeper:tk-worktree`；
由内向外提交推送用 `devkit-tool:cascade-push`。若因此确需留在现有 checkout 直写，走上节 Human
本轮授权，不要私开空 worktree 再跨隔离边界操作原仓。

更新 gitlink 前仍须列每个**直接 submodule** 新旧 commit 的 message、短 hash、日期给 Human
确认；本轮直写授权不替代 gitlink 变更确认。

## 全局关闭与已知漏报

`WORKTREE_GUARD=off` 是独立全局关闭开关，不是 Human 本轮授权。AI 不得自行启用；写进
settings 长期开启等于卸载保护，却留下“仍受保护”的错觉。

Bash 侧只机械识别 `git commit`。`sed -i`、重定向、`tee`、`cp`、`mv`、`rm`、heredoc、
解释器内部写文件可能过闸；未经 Human 本轮授权，仍不得在 `main` / `master` 使用。判据看动作
是否写工作区，不看 hook 是否抓到。

## `git commit` 只动豁免目录时不必开 worktree

暂存区里每一条都落在 `.claude/` / `.keeper/` / `.git/` 或显式配置的豁免前缀下时，`main` /
`master` 上的 `git commit` 直接放行——台账、会话产物这类提交不需要为它开一个 worktree。

放行有三个前提，缺一即拦：暂存区**非空**；显式 pathspec（`--` 之后或裸路径）也逐条豁免，
且不含通配符；不带 `-a` / `-A` / `--all` / `-i` / `--include` / `--amend` / `--patch`。后者
在提交那一刻才扩大暂存范围或改写既有提交，守卫事先读到的索引不再作数。白名单外的 flag 同样
维持阻断。

被拦时的改法：`git add -- <豁免路径>` 收窄暂存区，再 `git commit -m "..." -- <同一批路径>`，
不要加 `-a`。仍被拦说明这次提交确实带了别的东西，走 worktree。
