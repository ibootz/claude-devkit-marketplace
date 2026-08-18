---
name: worktree-flow
description: 在 main/master 分支改文件或 git commit 时，默认走「开 worktree 临时分支 → 提交 → --no-ff 合回 → 清理」；确需直接写时，用 AskUserQuestion 取得 Human 本轮授权。被 `[L1-BLOCKER] check=worktree-flow` 拦下、用户说“开 worktree”“别在 main 上改”“本轮允许直接改 main/master”“合并回主分支”“清理 worktree”时使用。
---

# 主分支保护流程（worktree-flow）

## 判据与两条路径

当前仓分支逐字等于 `main` 或 `master`，且要改仓内文件或执行 `git commit` 时触发。默认选
worktree；只有 Human 明确批准本轮直写，才留在主分支操作。

不触发：非 git 目录；detached HEAD；已在其他分支；merge / rebase / cherry-pick 进行中；
目标落在 `.claude/`、`.keeper/`、`.git/`、`WORKTREE_GUARD_EXEMPT` 目录，或启用
`WORKTREE_GUARD_EXEMPT_DOTDIRS=1` 后的顶层点目录。

## 默认路径：worktree

### 1. 开工作区

先比 base ref：

```bash
git -C <仓根> rev-parse HEAD origin/$(git -C <仓根> symbolic-ref --short HEAD)
```

一致则调：

```json
{"name":"<任务语义-kebab>"}
```

`EnterWorktree` 建 `worktree-<name>` 并切入 `.claude/worktrees/<name>/`。若本地主分支领先远端，
默认 `worktree.baseRef = fresh` 会漏本地提交；改设 `head`，或从本地 `HEAD` 手动建 worktree。

### 2. 在临时分支改与提交

```bash
git -C <worktree 路径> add -A
git -C <worktree 路径> commit -m "feat(xxx): ..."
```

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
