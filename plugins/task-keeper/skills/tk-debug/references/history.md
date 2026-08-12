# 入库策略与字段演变史（debug-keeper）

> 本文件收纳 debug-keeper.md 瘦身时从正文移出的、**有溯源价值**的历史演变叙事。
> 正文只留「当前生效做法 + 一句理由」；想了解「为什么 v6 是这个判据、它推翻了什么」时查本文件。
> **无溯源价值的纯 sediment（v2 字段名、删除日期）不收录于此，已直接删除。**

## 目录

1. [入库策略：v4 → v5 → v6 的来回](#1-入库策略v4--v5--v6-的来回)
2. [被删除的 v2 机制](#2-被删除的-v2-机制)
3. [被删除的 v2 frontmatter 字段](#3-被删除的-v2-frontmatter-字段)
4. [上限调整记录](#4-上限调整记录)

---

## 1. 入库策略：v4 → v5 → v6 的来回

`.keeper/` 下文件的入库策略经历过三次反转，当前生效的是 **v6（2026-08-10 用户拍板）**。

### v4（最早）：队列文本被跟踪

- `.keeper/` 下的 `issue.md` / `receipts.md` / `index.md` / `decisions/` / 截图都是被跟踪文件。
- `receipts.md` 读取用 `git show HEAD:<路径>`，对账基于 commit。
- 两个 worktree 看到的队列一致（随分支合并回主仓）。
- `check_staged_gitlink.py` 是主线校验。

### v5（中间）：整树忽略

用户原话（2026-08-06）曾拍板「`.keeper/` 整树不入库」。成因是当时对「bug 细节与截图进 git 历史」的顾虑。

带来的连带判据（**全部已被 v6 反转，不要再按这些做**）：

- `.gitignore` 写 `.keeper/` 整树忽略 → 队列文本不入库
- 读 `receipts.md` 改用 `cat`（`git show HEAD:` 报 `does not exist`）
- `receipts.md` 不随 `merge-back` 回来，需手工 `cp` 回 delivery
- 「各层 status 为空才允许删 worktree」那道闸对 receipts 失效（它压根不在 status 里）
- 两个 worktree 看到的队列不一样
- `check_staged_gitlink.py` 沦为存量仓专用（整树忽略让幽灵 gitlink 这条路暂时关闭）

### v6（当前生效，2026-08-10）：正文入库，精确排除三类本机产物

用户原话（2026-08-10）：

> 「`.keeper` 之前把它从整个项目中忽略了，现在看来还是需要提交到远端纳入版本控制，
> 除了少数内容比如里面的 worktree 之外，其他都可以（包括当时的问题附件/图片/文件等）
> 纳入版本控制」

v6 三条精确排除规则（逐字照抄，**注释也要照抄**——实测两个分支各自追加内容不同的注释会产生合并冲突）：

```gitignore
# task-keeper 队列：正文与附件入库，只排除三类本机产物
.keeper/**/worktree/
.keeper/**/.keeper-instance.json
.keeper/.keeper-active
```

v6 推翻 v5 的四条：

1. 队列改动要正常提交（按路径 `git add .keeper/<交付id>/`，不要 `git add -A`）。
2. `check_staged_gitlink.py` 恢复为主线校验，每次提交队列前都跑。
3. 读 `receipts.md` 用 `git show HEAD:`，不要 `cat`。
4. `receipts.md` 随 `merge-back` 正常带回来，不要手工 `cp`。

### `.gitignore` 写法坑（v6 连带）

- `.keeper-active` 那条**不带 `**`**（它是 `.keeper/` 顶层的单文件，不是每交付一份；写成 `.keeper/**/.keeper-active` 匹配不到它）。
- 另两条**必须用 `**`**（`.keeper/**/worktree/` / `.keeper/**/.keeper-instance.json`），写死中间层（如 `.keeper/*/debug/*/worktree/`）在嵌套变化时会漏网。
- 理想情况是这四行一次性提交到主分支，各交付分支的 `grep -qxF` 直接命中、什么都不写。
- v5 的整树忽略行（`.keeper/`）若残留，它会覆盖三条精确规则、让队列继续不入库，且**不会有任何报错**——冷启动时检出要按 §12 上报请用户拍板删除，不要自己删（会让存量队列一次性变成待提交、把历史 bug 细节与截图一次推上远端）。

### 代价（v6 带来的）

bug 细节、内部系统坐标、决策原文、截图现在都会随 push 公开。所以：

- 截图脱敏是红线（`references/screenshot.md` §4）。
- 决策原文里的敏感值同样要替换。
- 你没有图像编辑能力、打不了码，所以「不落盘」是唯一那道机械闸。

---

## 2. 被删除的 v2 机制

以下机制在 v3/v4 重构中删除，正文不再保留叙事，此处仅留溯源。

### 攒批 triage（2026-07-29 删除）

v2 要求「攒够一批派一个 triage subagent」，理由是同一批里能顺手去重。删除理由：去重的真正前提是 keeper 的上下文跨唤醒完整保留（§0），而不是「几条 issue 在同一次 triage 调用里」——登记第 5 条时照样记得第 2 条讲的是什么。攒批只带来两样东西：等下一条 bug 的延迟，以及「几条算一批」这个无判准的判断。

用户一次甩来 3 条时仍可合成一个 triage subagent 去核（省 token），但**这是顺手合并，不是等**——手上只有 1 条就 triage 那 1 条。

### 登记与调度两步（v3 删除）

v2 有「先记 pending 行、triage 完再补写」的两阶段登记，以及独立的调度算法（算在飞集合、文件冲突）。v3 里接收即登记（同一个文件），调度算法的输入由 worktree 物理隔离取代，没有可调度的东西了。

### journal.md（2026-07-29 删除）

v2 有个 `journal.md` 装「跨 issue 的批次记录」，它是 v2 `issues.yaml` 的 `meta` 段原样搬来的，没做过「这条到底属于谁」的重新归属。实测 5 个章节里 1 个纯冗余（`delivery` 就是 worktree 目录名）、1 个是配置常量（`parallel_cap: 4`）、3 个装的其实是单条 issue 的决策与对账。加上没有任何 hook 读它写它校验它，它正在长成第二个 `issues.yaml`。

替代：批次级信息按归属分流——属于某条 issue 的写进那条 issue 的「修订记录」；真正跨 issue 的交付级事实属于项目自己的交付文档体系（如 `.sdlc/`）。

### subagent-stop-debug-reconcile.sh（v3 删除）

v2 有一个对账 hook，介入门槛是 `status == "in_progress"`，而那个值从未被写入过，实测在跑了 14 个 subagent 的会话里零命中。现在没有任何 hook 替 keeper 对账，全部由 keeper 在合并前手工做。

### 「两条 issue 是否同根因需要确认」第三种拍板（2026-07-29 删除）

v2 有第三种需要打断用户的情况。删除理由：worktree 隔离后判错的代价（合并时一个 git 冲突）低于打断用户一次的代价，改由 keeper 自己判并在回执里留痕。

---

## 3. 被删除的 v2 frontmatter 字段

v2 的 `issue.md` frontmatter 存过这些字段，**当前一律不写**（它们要么从未被写对过、要么写完立刻失同步）：

- `stage` / `status: in_progress`：在飞状态——`git worktree list` 已知道
- `affected_files`：改了哪些文件——`git diff --stat` 已知道
- `blocked` / `stale`：阻塞与陈旧——`git merge-base --is-ancestor` 已知道

判据：**不要把能从 git 算出来的东西写进 frontmatter**。

---

## 4. 上限调整记录

- **同时在飞 fixer 上限**：原 v2 是 5（2026-07-30 Human 立规），后上调至 **8**。理由是 keeper 自己的审阅带宽——8 个回执同时回来时逐个核对 diff 的负担是真的，超过就会开始「看着像对的就 accept」。等 Human 回复的交互式 subagent 不占这个额度。
- **headless `agent-browser` 并发上限**：固定 3（来自 working-discipline 插件 `bash-guard.js` 的 `INSTANCE_LIMIT = 4`，留 1 个余量给主会话）。与「同时在飞 8 个」正交，是两个独立的额度。
