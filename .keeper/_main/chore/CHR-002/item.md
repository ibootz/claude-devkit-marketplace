---
id: CHR-002
summary: gitignore缺两条keeper精确排除
status: done
kind: cleanup
external_write: false
reported_at: '2026-08-21'
external_ref: null
---

## 用户原话

标题：本仓 .gitignore 缺两条 keeper 精确排除

内容：/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.gitignore 缺 `.keeper/.keeper-active`（本机状态，跨机器无意义）与 `.keeper/**/.merge.lock*`（被 git 看见则 merge-back 判脏树）两条精确排除。补法见 keeper 冷启动第 2 步，文案须逐字照抄，否则各分支追加内容不同会冲突。这条你自己就能做，做完在条目里记下实际写进去的两行原文。

## 处置方案

按 §5 共享工作区纪律先声明清单：本条只碰仓根 `.gitignore` 一个文件。动手前查占用：
`git status --short -- .gitignore` 输出为空，无人占用，可以动手。

拟追加的两行（逐字取自 `task-keeper` 4.4.0 版
`skills/tk-debug/references/cold-start.md` 第 44 行给出的四行模板中缺失的那
两行，chore 与 debug 冷启动共用同一份文案）：

```
.keeper/.keeper-active
.keeper/**/.merge.lock*
```

## 执行记录

`Edit` 工具在写入仓根 `.gitignore` 时被 `main-branch-guard.js` 的
`PreToolUse` 钩子拦下：

```
[L1-BLOCKER] tool=Edit check=worktree-flow
finding="仓 /Users/zhangq/Workspace/mine/claude-devkit-marketplace 当前在受保护
分支 main，本轮尚无 Human 直接写入授权（目标：.gitignore）"
```

`.gitignore` 不落在 `.keeper/`、`.claude/`、`.git/` 等既有豁免目录内，不满足
自动豁免条件。按父代理给的约束「撞到 [L1-BLOCKER] check=worktree-flow，把仓、
分支、目标与原因回报给我，不要自己申请授权、也不要改写命令绕过」，本实例已
停手，未做任何绕过尝试（未试 `sed -i`、未试 heredoc 重定向、未试
`EnterWorktree`）。回读确认文件未被部分写入：`git status --short -- .gitignore`
仍为空，`.gitignore` 末尾八行与改动前完全一致。

## 结局

2026-08-21 由**主会话**走 worktree 流程执行完毕（`worktree-keeper-ledger` 分支，
worktree 在 `.claude/worktrees/keeper-ledger`），随后 `--no-ff` 合回 `main`。

**执行者不是本 keeper 实例，原因是结构性的**：`main-branch-guard.js` 对 Bash 侧
`git commit` 调用 `evaluate(dir, null)`，`filePath` 传 `null` 使
`if (canonicalFile && isExemptPath(canonicalFile, root)) return null` 这一支被短路，
于是**受保护分支上的 `git commit` 无论 pathspec 收窄到哪里都会被拦**，与目标是否
落在 `.keeper/` 豁免前缀无关。而子代理不能调用 `AskUserQuestion`、按协议也不该自行
`EnterWorktree`，所以 keeper 在 `main` 上永远走不完「改 + 提交」这一步。这一点已作为
判据口径分歧上报，**未改动 guard 判据**（改硬阻断判据须 Human 拍板）。

实际写进 `.gitignore` 的两条规则（各自的说明写在规则**上方**，遵守本文件既有约定
「gitignore 的 `#` 只在行首才是注释」）：

```
# 本机激活状态，跨机器无意义
.keeper/.keeper-active
# 合并互斥锁，被 git 看见则 merge-back 判脏树
.keeper/**/.merge.lock*
```

同时把该段落说明里的「只精确排除四类」改为「五类」——原文写四类而实际只列了三组，
补上这两条后是五组。

**规则生效已用行为回读核实**（不是只回读文件内容——本文件自己记着 2026-08-06
那次「四条里三条静默失效」的事故）：

```
$ git check-ignore -v .keeper/.keeper-active .keeper/_main/.merge.lock/foo .keeper/_main/.merge.lock
.gitignore:59:.keeper/.keeper-active	.keeper/.keeper-active
.gitignore:61:.keeper/**/.merge.lock*	.keeper/_main/.merge.lock/foo
.gitignore:61:.keeper/**/.merge.lock*	.keeper/_main/.merge.lock
exit=0
```

三条路径全部命中、且命中的正是新加的那两行，规则真生效。
