---
name: commit-push
description: 提交推送一步做完，不反问「要不要提交推送」。用户说「提交推送」「推上去」「push 一下」「commit and push」，或你刚完成一批改动、正要问用户「要不要提交/推送」时使用。先 rebase 拉远端最新再推；在 worktree 里则只提交、合回主分支、清理临时分支、不推远端；submodule 嵌套仓转介 cascade-pull/cascade-push；改的是 Claude Code 插件源时收尾刷本机缓存并提示 /reload-plugins。
when_to_use: |
  触发词：提交推送 / 推上去 / push 一下 / commit push / 提交并推送 / commit-push。
  **判据式触发（比触发词更常命中，别漏）**：你刚完成一批改动，正要问用户「要不要提交推送」——此时直接走本 skill，把问句换成动作。调用即当轮提交与推送的授权，不再反问。
---

# Commit-Push（提交推送一步做完）

调用本 skill 即当轮提交与推送的授权——把「要不要提交推送」这个问句换成动作，不再反问。

## 先判场景，再动手

三条判据按序过一遍，命中几条叠加几条：

1. **在 worktree 里？** `git rev-parse --git-dir` 与 `git rev-parse --git-common-dir` 输出不一致，即在 worktree。命中 → 主流程走「worktree：只提交合回」。
2. **submodule 嵌套仓？** 仓根有 `.gitmodules` 即命中。命中 → 走「submodule 嵌套仓：转介 cascade-*」，不走本 skill 主流程。
3. **改的是 Claude Code 插件源？** 仓根有 `.claude-plugin/marketplace.json` 且本轮改动落在 `plugins/**` 下即命中。命中 → 提交推送后追加「插件收尾」。

三条都不命中 → 普通仓主流程。

## 普通仓：commit → pull --rebase → push

先提交再变基，不是先拉再提交——`git pull --rebase` 拒绝带着未暂存变更运行，先提交既满足「推送前合入远端最新（rebase 合并、无 merge commit）」，又免掉 stash 往返：

```bash
git add -A                      # 多会话共用同一 checkout 时改用窄 pathspec，见下方注
git commit -m "<按仓内惯例>"     # 动手前 git log --oneline -5 对齐格式与语言
git pull --rebase
git push                        # 无 upstream 时 git push -u origin <当前分支>
```

- **rebase 撞冲突**：常规冲突自己解，解完 `git rebase --continue`；解不动则 `git rebase --abort` 回到拉取前状态，报告用户，不硬推。
- **多会话共用同一 checkout**：git 索引全仓共享，谁先 commit 谁带走全部暂存——此时 `git add` 与 `git commit` 都带窄 pathspec（`git commit -m "..." -- <pathspec>`，`-m` 放 `--` 之前），免卷入他人暂存。
- **push 回执**：输出里的 `<分支> -> <分支>` 即成功；要核远端，`git status` 显示 up to date with origin 即一致。

## worktree：只提交，合回主分支，不推远端

临时分支的价值在隔离，不在远端——合回即完成交付：

1. 在 worktree 里提交（message 同上按仓惯例）。
2. 回主仓：worktree 会话用 `ExitWorktree {"action":"keep"}`；只是站在 worktree 目录里则直接 `git -C <主仓路径>` 操作。
3. 主分支落后远端时先 `git -C <主仓> pull --rebase`，再合：

   ```bash
   git -C <主仓> merge --no-ff <临时分支> -m "merge: <本批说明>"
   ```

4. 清理：

   ```bash
   git -C <主仓> worktree remove <worktree 路径>
   git -C <主仓> branch -d <临时分支>
   ```

   `branch -d` 拒删说明没合干净，回头查 merge，不得改用 `-D`。

**不推远端**——临时分支与合回的主分支都留在本地。若本批改动同时命中插件判据，缓存刷新依赖远端新提交，此时提示用户「待推送后再刷」。

## submodule 嵌套仓：转介 cascade-*

`.gitmodules` 存在时本 skill 主流程不适用（普通 pull/push 只动父仓一层，gitlink 会脱节）：

- 拉取对齐 → `cascade-pull`（模式 A/B 的选择判据在其自身文档）
- 由内向外提交推送 → `cascade-push`（简报→批准→提交→推送四段，push 后逐层回读远端 SHA）

本 skill 到此转介，不重复其流程。

## 插件收尾：改的是 Claude Code 插件源

命中插件判据时，提交推送只是半程——本机装着的还是旧缓存。收尾两步：

1. **升版本号再提交**。CLI 判「有无新版」比的是 version，不升则 update 永远 no-op、回执还绿。版本在插件 manifest 与市场清单多处登记，以仓内规约为准（本仓形态：plugin.json ×2 + marketplace.json ×2 四处同步，pre-commit 的 check-versions.js 强制校验）。
2. **push 完成后刷两层缓存**：`claude plugin marketplace update <marketplace>` 与 `claude plugin update <插件名>@<marketplace>`。判据、url 源坑、project scope 陷阱见 `marketplace-cache-sync` skill，按其流程走。

刷完提示用户：**运行 `/reload-plugins` 刷新当前会话**（skill/hook/agent 热载；仅 SessionStart/SessionEnd/PreCompact 生命周期挂载点变动才需重启会话）。

## 什么时候不触发

- 用户当轮说了「先别提交」「只提交不推」——按字面截断流程，不追问。
- `git status` 干净无改动——报一句「无改动」即止，不造空提交。
- 推送目标是他人在用的共享分支且仓内有发布规约——照仓规约走，本 skill 的调用授权不覆盖仓级发布纪律。
