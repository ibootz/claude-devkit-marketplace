---
name: tk-board
description: 出一张 debug / chore 队列的进度看板：每条一行（编号 + 20 字问题说明 + 已解决/未解决/进行中/待拍板），外加四态计数与占比、陈旧 worktree 与悬空拍板项告警。纯只读，跑多少次都不改队列、不唤醒 keeper。
when_to_use: |
  用户问「现在进度怎么样」「还有多少没修完」「队列里剩什么」「给我一张表看看」「哪些在等我拍板」「哪些还在跑」，或任何需要**一眼看到整体进度**的场合。也适用于交付收尾前的自检（还有没有 open 条目、有没有忘删的 worktree 卡住归档）。
  **不适用**：用户报新 bug / 新杂务（那是 tk-debug / tk-chore 的转发流程）；用户问某一条 issue 的细节（直接读那条 `issue.md`，看板只给 20 字摘要）；要改队列状态（看板是只读的，改状态得让 keeper 去做）。
---

# tk-board：队列进度看板

## 一条命令，把输出原样给用户

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/tk-board/scripts/board.py"
```

脚本从当前工作目录往上找队列（与两个 hook 用同一份 `keeper_paths` 判据），输出一份
完整的 markdown。**把它原样贴给用户，不要复述、不要挑几条讲、不要自己重新排版**——
用户要的就是一眼扫完那张表，你转述一遍只会更慢且会丢条目。

常用变体：

```bash
# chore 队列 / 两个队列各出一份
python3 .../board.py --queue chore
python3 .../board.py --queue both

# 只看需要人动作的两态
python3 .../board.py --status 待拍板,进行中

# 连已归档条目一起列（真实交付可能有一百多条，会很长，用户明确要才加）
python3 .../board.py --all

# 说明列放宽（默认 20 个汉字宽）
python3 .../board.py --summary-width 30

# 不在队列所在目录时显式指定
python3 .../board.py --queue-dir <worktree根>/.keeper/<交付id>/debug
```

## 四种状态是怎么算出来的（用户追问时照这个答）

`issue.md` 的 `status` 字段**只有 `open` / `done` 两个值**——v2 曾经有过
`in_progress`，v3 砍掉了，理由是「AI 手写的业务字段当机械判据不可靠」（原话在
`hooks/lib/queue_snapshot.py` 模块头）。所以另外两态是从**文件系统事实**反推的，
不是从 frontmatter 读的：

| 状态 | 判据 | 为什么可信 |
|---|---|---|
| 已解决 | `status: done` | frontmatter 唯一的终态 |
| 待拍板 | `decisions/` 里有未答复的 `.md`，其 `about:` 指向这条 | 「未答复」= 文件名在 `decisions/` 而不在 `decisions/answers/`，纯文件名差集 |
| 进行中 | 条目目录下有 `worktree/` 子目录 | fixer 派出去时才会有这个目录 |
| 未解决 | 以上都不是的 `open` | 兜底 |

**判定自上而下短路，四态互斥。** 两处顺序是有意的：`done` 排最前，所以「已修完但
`worktree/` 忘了删」不会冒充「进行中」（它单独进告警段）；「待拍板」优先于「进行中」，
因为一条 issue 可以既派了 fixer 又卡在等人答复，此时该突出的是**需要人动作**的那一面。

## 告警段比表格更该看

表格下方的「告警」段列三类东西，都是**表格本身表达不了、但会咬人**的：

- **陈旧 worktree**——条目已 `done` 但 `worktree/` 没清理。归档脚本撞到它会跳过该条
  （`shutil.move` 一个活着的 git worktree 会让主仓 gitlink 失效），于是队列看着清完了
  却归不了档。
- **未答复的拍板项指向的条目不在「待拍板」态**——该条已经 `done` 收尾了，人却还欠一个
  答复；或者 `about:` 写了个不存在的 id。两种都要人看一眼。
- **待拍板但归属不明**——`decisions/` 里未答复、但没写 `about:` 或抽不出条目 id，
  它没算进表里任何一条。

看到告警时**在贴完表格后用一句话点出来**，别指望用户自己往下滚。

## 三条纪律

1. **不要为了出这张表去唤醒 keeper。** 看板读的是磁盘上的队列文件，keeper 在不在跑、
   在忙什么都不影响结果；唤醒它反而会打断它手上的活，还要多等一轮。
2. **不要自己 grep 队列凑数字。** 手工数会漏归档目录（真实交付里归档条目常是未归档的
   五六倍）、会把陈旧 worktree 当成在飞、会漏掉待拍板归属——这三件事脚本都处理了，
   手工做一遍只会给出一个看起来对、实际错的数。
3. **看板是只读的，看到问题不要顺手改。** 想改 issue 状态、清理 worktree、推进归档，
   都走 keeper（`tk-debug` / `tk-chore` 的转发流程）——`.keeper/` 队列的写权限归 keeper
   独占，主会话直接改会破坏单一写者模式。

## 队列还没启用时

脚本会打印「找不到 debug 队列目录」而不是报错。这说明本项目还没启用 task-keeper，
按每轮注入里那句启用命令建目录即可，不要用 `--queue-dir` 指到别的项目的队列上去。

## `pending_dispatch.py`：漏派体检（`board.py` 看不出来的那一层）

`board.py` 的「未解决」桶混着两种性质完全不同的条目——**还没 triage**（keeper 的正常
待办，不该催）与**triage 完了却没派 fixer、也没在等拍板**（漏派：keeper 登记完一条 bug
后被后来的条目挤掉了注意力，纯粹忘了捡）。`pending_dispatch.py` 只挑后一种，纯只读，
判据全机械：

```
漏派 = status == open 且 priority/difficulty 都非空（triage 已完成）
       且不在 `git worktree list` 的 DBG-* 集合里（没派 fixer）
       且不在「未答复 decisions」的 about 字段集合里（不是在等拍板）
```

```bash
# 人/AI 读：每条一行，无漏派时输出「无漏派」
python3 "${CLAUDE_PLUGIN_ROOT}/skills/tk-board/scripts/pending_dispatch.py"

# 机器读：JSON，含 id/priority/difficulty/summary 与总数
python3 .../pending_dispatch.py --json

# 塞进 hook additionalContext：压成一行，无漏派时是空字符串，可直接拿「输出非空」当判据
python3 .../pending_dispatch.py --oneline

# 多交付场景（.keeper/*/debug 有多个）：默认只算当前交付（.keeper-active 指向的那个），
# 要全扫加这个 flag
python3 .../pending_dispatch.py --all-deliveries
```

退出码：`0` = 正常执行完（不管有没有漏派——「有漏派」是正常产出）；非 `0` 只在真正执行
不下去时出现（依赖模块导入失败、显式给的 `--queue-dir` 不存在）。**不要**靠退出码判断
有没有漏派，靠输出内容判断。

**什么时候不该用它**：它不判断「这条 issue 该不该派」，只判断「已经 triage 的有没有被
派出去」——未 triage 的条目一律不算漏派，那是 keeper 排队里的正常待办，`pending_dispatch.py`
对它保持沉默，催的话应该催 triage 本身，不是催这个脚本。它也不是 `board.py` 的替代品：
要看整体进度、四态分布、陈旧 worktree 告警仍然用 `board.py`；`pending_dispatch.py` 只回答
一个更窄的问题。
