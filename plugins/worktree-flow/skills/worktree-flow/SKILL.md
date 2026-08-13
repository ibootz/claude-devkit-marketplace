---
name: worktree-flow
description: 在 main/master 分支上要改代码时，改走「开 worktree 临时分支 → 在里面改并提交 → --no-ff 合回主分支 → 删 worktree 与临时分支」这条流程，临时分支不 push remote。当你被 `[L1-BLOCKER] check=worktree-flow` 拦下、或用户说"开个 worktree""别在 main 上改""这次改动走分支""合并回主分支""清理 worktree""临时分支删掉"时使用。也适用于动手前发现当前分支是 main/master、需要先把工作区准备好的场合。
---

# 主分支保护流程（worktree-flow）

## 何时触发

**判据只有一条**：当前仓的 `git rev-parse --abbrev-ref HEAD` 逐字等于 `main` 或 `master`，
且本轮要改这个仓里的文件（或要在这个仓 `git commit`）。命中就走下面四步，不要先改了再说。

**不触发**（直接照常做）：

- 当前不在 git 仓里
- detached HEAD（`rev-parse --abbrev-ref HEAD` 返回 `HEAD`）
- 已经在某个 worktree / 别的分支上——分支名不是 main/master 就不受本流程约束
- 仓正处于 merge / rebase / cherry-pick 进行中（解决冲突按设计就发生在主分支上）
- 目标文件落在 `.claude/`、`.keeper/`、`.git/` 之下，或 `WORKTREE_GUARD_EXEMPT` 配置的目录下，或开启 `WORKTREE_GUARD_EXEMPT_DOTDIRS=1` 后任何顶层点开头目录下（会话产物、任务台账、git 元数据，或项目主动豁免的目录）

## 四步流程

### 第 1 步 · 开工作区

调 `EnterWorktree` 工具：

```json
{"name": "fix-login-timeout"}
```

它做三件事：建临时分支 `worktree-<name>`、在 `.claude/worktrees/<name>/` 建工作区、
把会话 cwd 切进去。此后所有相对路径都以 worktree 为根。

**开工前必查 base ref**——这是本流程最容易踩的一脚：

```bash
git -C <仓根> rev-parse HEAD origin/$(git -C <仓根> symbolic-ref --short HEAD)
```

两个 SHA 一致就直接用 `EnterWorktree`。**不一致**（本地 main 领先 origin，有未推送的提交）时
`EnterWorktree` 默认的 `worktree.baseRef = fresh` 会从 `origin/<默认分支>` 拉，**你的本地提交
不在新工作区里**，改完合回来会撞出莫名其妙的冲突。两条出路选一：

- 把 `worktree.baseRef` 设为 `head`（settings.json），让它基于本地 HEAD 分叉；
- 或手动开：`git -C <仓根> worktree add <路径> -b <临时分支> HEAD`。

### 第 2 步 · 在里面改

worktree 的分支不是 main/master，闸自然放行。改完在 **worktree 内**提交：

```bash
git -C <worktree 路径> add -A
git -C <worktree 路径> commit -m "feat(xxx): ..."
```

分几次提交都行——第 3 步用 `--no-ff`，这些提交会原样保留在历史里。

### 第 3 步 · 合回主分支

先回主目录：`ExitWorktree` 传 `{"action": "keep"}`（**不是 `remove`**——现在还没合并，
删了就丢改动）。然后：

```bash
git -C <仓根> merge --no-ff <临时分支> -m "merge: <一句话说明这批改动>"
```

`--no-ff` 是用户拍板选定的策略：主分支上留一个合并提交，日后能看出这批改动同属一次作业，
即使临时分支已被删掉也追溯得到。

**撞冲突时**：解决冲突这一步在主分支上做，本插件的闸会因为检测到 `MERGE_HEAD` 而整仓放行，
所以你能正常改文件、能 `git commit` 收尾。解完跑 `git -C <仓根> commit`（不带 `-m` 时用
git 预填的合并信息）。

### 第 4 步 · 清理

```bash
git -C <仓根> worktree remove <worktree 路径>
git -C <仓根> branch -d <临时分支>
```

`branch -d`（小写 d）只删已合并的分支——**没合并成功它会拒绝删**，这正是要的护栏；
不要因为它报错就改成 `-D`，那会真的丢掉改动。

**临时分支不 push remote**。它是一次性的本地作业空间，推上去只会在远端留一堆需要人工清理
的垃圾分支。要推的是合并之后的主分支。

清理完核验一次：

```bash
git -C <仓根> worktree list      # 应只剩主工作区
git -C <仓根> branch --list 'worktree-*'   # 应为空
```

## 特殊情形

**含 submodule 的聚合仓**：`git worktree add` 只建父仓工作区，submodule 目录全是空的。
`EnterWorktree` 同样不补。这类仓改用 `task-keeper:tk-worktree` skill 派生结构完整的
worktree，提交推送用 `devkit-tool:cascade-push`。

**应急热修 / 改一个错别字**：本闸不按扩展名豁免文档类文件（`.json`、`.yml` 落在代码与文档
的灰区，按扩展名切会切出一条模糊边界）。确实不值得开 worktree 时，用逃生阀：

```bash
WORKTREE_GUARD=off <你的命令>
```

或在 settings.json 的 `env` 里临时设上，用完删掉。**不要把它长期设成 off**——那等于卸载
这个插件，还留着一份「以为受保护」的错觉。

## 拦不住但同样违反本流程的写法

Bash 侧的闸只认 `git commit` 这一种确定形态（判据不猜语义，见插件 README 的设计依据）。
下面这些在 main 上**会被放行**，靠你自觉不用：

`sed -i` / `>` `>>` 重定向 / `tee` / `cp` `mv` `rm` / heredoc 写文件 /
`python - <<EOF` 之类解释器脚本内部的写操作。

判据是「这个动作会不会改动工作区里的文件」，不是「我这条命令有没有被拦下来」。
