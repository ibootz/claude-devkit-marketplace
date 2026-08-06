---
name: nested-submodule-commit-push
description: 嵌套 git submodule（多层子模块）项目从最内层向外逐层提交推送，链式更新每一层父仓的 gitlink，push 后逐层写后回读核验远端 SHA。自带 cascade-push.py 探测脚本，默认 dry-run 只打印计划，--apply 才提交、--push 才推送，把不可逆的 push 永远隔成独立显式动作。
when_to_use: |
  用户说"提交推送 submodule"、"嵌套子模块怎么提交"、"submodule 改了怎么 push 上去"、"多层子模块一层层往外提交"、"submodule 提交顺序"、"gitlink 没更新"、"父仓没记录子模块的改动"、"submodule push 了别人拉不到"、"submodule detached HEAD 怎么提交"、"用 foreach --recursive 提交 submodule 顺序错了"。
  **核心触发判据**：当前项目是真正的 git submodule 嵌套结构（有 `.gitmodules`、父仓 index 里有 mode 160000 的 gitlink 条目、子模块各自是独立 git 仓），且本轮要把改动从最内层一路提交推送到最外层。单仓 monorepo（没有 submodule）直接用 `git commit` / `git push` 即可，不需要本 skill。
---

# Nested Submodule Commit-Push（嵌套 submodule 由内向外逐层提交推送）

把"嵌套 submodule 项目的提交推送"做成**由内向外、链式更新 gitlink、写后回读**的一条龙流程，靠脚本按正确拓扑序逐层执行，不靠人工记顺序——人工逐层是这类项目最高频的事故来源。

**设计基础**：机制依据来自 git submodule 的标准行为与社区共识——`git submodule foreach --recursive` 是「父先于子」（tail-recursive），方向与「由内向外提交」相反（[SO](https://stackoverflow.com/q/14846967)、[r/bash](https://www.reddit.com/r/bash/comments/1bz6lb9/)）；父仓 commit 的 gitlink 指向子 SHA，该 SHA 必须先存在于远端，否则 dangling（[Git Book](https://git-scm.com/book/en/v2/Git-Tools-Submodules)）。本 skill 的脚本据此自采嵌套树、按路径深度降序逐层处理，不依赖 foreach 的遍历顺序。

## 背景：两层以上嵌套，人工逐层必踩三个坑

git submodule 嵌套项目里，每个 submodule 自己是独立 git 仓，父仓通过 **gitlink**（index 里 mode 160000 的条目）指向子的某个具体 commit SHA。改了最内层代码后，要把它一路提交推送到最外层，**顺序只有一个正确方向：最内 → 最外**。人工逐层极易踩：

1. **顺序错**（先提交外层）→ 父仓 gitlink 指向一个还没 push、甚至远端不存在的子 SHA，别人 clone 父仓时拉不到子的那个 commit（dangling reference）。
2. **gitlink 漏更新**（提交了子，忘了在父仓 `git add <子>`）→ 父仓 commit 不含 gitlink 变化，子的新提交没被父记录，等于白提交。
3. **`git submodule foreach --recursive` 方向陷阱** → 它是「父先子后」，照搬来做提交直接制造第 1 个坑。

这三个坑的共同点：**失败了不报错**。git 不会告诉你"顺序错了"或"gitlink 没更新"，提交看起来成功了，问题要到别人 clone、或下游拉取时才暴露。所以这类流程必须脚本化、按确定的拓扑序执行、并在每层写后回读核验。

## 机制（脚本据此实现，须理解）

- **拓扑序 = 路径深度降序**。最内层 submodule 路径最深，先处理；顶层 superproject 深度 0，最后处理。子的路径必然比父深，故深度降序天然满足「子先于父」的偏序；平级 submodule 之间顺序无关。脚本发现阶段递归采全嵌套树后按深度降序排序。
- **每层 `git add -A && git commit`（有 staged 才提交）**。子模块在父仓 index 里是 gitlink 条目；子 HEAD 变化后，父仓 `git add -A` 会把 gitlink 更新到子的新 SHA。于是「处理完子 → 处理父时 add -A」天然链式更新整条 gitlink 链。
- **push 必须子先于父**。父 commit 引用子 SHA，该 SHA 须先在远端存在。脚本按深度降序逐层 push（子先），每层 push 完立刻 `git ls-remote` 回读远端 SHA，与本地 HEAD 比对一致才算该层成功。
- **detached HEAD 必须拦截**。superproject checkout 出来的 submodule 常处于 detached HEAD；在上面 commit 会产生不在任何分支上的游离 commit，push 会丢。脚本检测到 detached HEAD 直接中止并报该层，不自动切分支（切错不可逆）。

## 执行工作流

脚本随本 skill 提供。先定位它：

```bash
SP="$CLAUDE_PLUGIN_ROOT/skills/nested-submodule-commit-push/scripts/cascade-push.py"
ls -l "$SP"   # 必须存在再往下走
```

拿不到 `$CLAUDE_PLUGIN_ROOT` 时（如直接在源仓里跑），改用绝对路径 `plugins/devkit-tool/skills/nested-submodule-commit-push/scripts/cascade-push.py`。

### 第一步：dry-run，先看计划再决定

**这一步是硬约束，不可跳过**——push 是不可逆外部写，动手前必须看清有哪些层、什么顺序、哪些层会受阻。

```bash
python3 "$SP"                              # 默认 dry-run
python3 "$SP" --root /path/to/superproject # 指定 superproject 根，缺省取 git toplevel
```

它会递归发现全部嵌套层级，按深度降序逐层打印：层路径、深度、是否 detached HEAD、将 stage 的改动清单（截断到前 15 项）、push 目标（remote/branch）。结尾汇总「共 N 层 / M 层需 commit」，并报告两类阻塞：

- **detached HEAD 层**：标红列出，须先在各层 `git checkout <branch>`（或 `git checkout -b <new-branch>`）再重跑。不修就硬拦。
- **无 upstream 分支层**：标黄列出，`--push` 会失败，须先 `git -C <该层> push -u <remote> <branch>` 设置上游。

### 第二步：提交（--apply，本地、可逆）

dry-run 无阻塞、改动清单已与用户确认后：

```bash
python3 "$SP" --apply --message '本次改动说明'
```

- **`--message` 在 `--apply` 时必传**。脚本不自动编 message（避免 garbage commit）。每层实际 commit message 写成 `[<层路径>] <message>`，便于在 git log 里区分是哪一层。顶层仓前缀是 `(root)`。
- 按深度降序逐层 `git add -A` → `git diff --cached --quiet` 判有无 staged → 有才 `git commit`，无改动的层跳过（不产生空提交）。
- 任一层 detached HEAD 立即整体中止，打印已提交层与中止层。

提交后可以逐层核验 gitlink 是否真的更新了（这是「处理好 gitlink 关系」的判据）：

```bash
# 父仓最近一次 commit 应能看到对应 submodule 的 gitlink 变化行
git -C <父仓> show --stat HEAD
# 形如： plugins/<子模块> | 2 +-
# 这一行就是 gitlink 指针更新；没有它 = 该层 gitlink 没更新 = 失败
```

### 第三步：推送（--push，不可逆、独立动作）

确认所有层 commit 完成、gitlink 链已更新后：

```bash
python3 "$SP" --push
```

- 按深度降序逐层 `git push <remote> HEAD:<branch>`（子先于父）。
- 每层 push 完立刻**写后回读**：本地 `git rev-parse HEAD` 与 `git ls-remote <remote> refs/heads/<branch>` 取远端 SHA，两者一致才算该层成功；不一致或 push 失败立即整体中止，打印已成功层与中止层，不让后续层继续（避免半途状态）。
- 结尾打印每层 local / remote SHA 对照表。

`--apply` 与 `--push` 可合用一次性走完：`python3 "$SP" --apply -m '<msg>' --push`。但**首次在一个嵌套仓用本 skill 时，强烈建议分开走**（先 dry-run、再 apply、再 push），确认每段行为符合预期后再合并。

### 何时本 skill 不适用

- **单仓 monorepo**（无 `.gitmodules`、无 gitlink）→ 脚本会报告「未发现 submodule，仅顶层仓」，此时直接用 `git commit` / `git push` 即可。
- **只改了顶层仓自身、没动任何 submodule** → 同上，直接提交推送顶层。
- **拉取/同步方向**（父仓升级对 submodule 的引用，即 `git submodule update --remote`）→ 那是 pull 方向，本 skill 只管 push 方向（子改动向外传播）。

## 已验证的坑

| 现象 | 真实原因 | 怎么核实 / 处置 |
|------|----------|----------------|
| 父仓 push 后别人 clone 拿不到 submodule 的新提交 | 提交/推送顺序反了（先父后子），父 gitlink 指向尚未 push 的子 SHA → dangling | 严格最内→最外（脚本按深度降序保证）；push 后写后回读 `git ls-remote` 确认子 SHA 已在远端 |
| 子模块提交了，父仓 commit 却没记录它 | 父仓漏 `git add <子>`，gitlink 未更新 | 每层 `git add -A` 捕获该层 gitlink 变化；commit 后 `git -C <父仓> show --stat HEAD` 看到对应 gitlink 变化行才算成功 |
| 用 `git submodule foreach --recursive` 提交，顺序全错 | 它是「父先子后」（tail-recursive），方向与「由内向外」相反 | 脚本自采嵌套树按深度降序，不用 foreach 做提交 |
| submodule commit 后 push 报错或改动丢失 | 处于 detached HEAD，commit 是游离 commit | 脚本 detached HEAD 预检中止；用户先 `git -C <该层> checkout <branch>` 再重跑 |
| 某层没改动却产生了空 commit | 无差别 commit | `git diff --cached --quiet` 为真（无 staged）则跳过该层 |
| `git add -A` 把不想提交的改动也带上了 | `-A` stage 该层全部改动 | dry-run 已明示每层将 stage的全部文件供用户审；确认后再 apply |
| 多层嵌套时漏了中间某层 | 人工逐层易漏，或只递归了一层 | 脚本发现阶段递归读各级 `.gitmodules` 采全嵌套树，深度降序无遗漏 |
| push 半途失败，前面层已 push、后面没推 | 网络 / 认证 / 远端拒绝 / 写后回读不一致 | 任一层失败立即中止，打印「已成功 push 的层」与「中止层」，据此决定补推还是回滚 |
| 跑 `git ls-remote` 探测远端时 SSH 弹密码卡住 | 没禁交互 | 脚本已设 `GIT_TERMINAL_PROMPT=0` + `GIT_SSH_COMMAND="ssh -o BatchMode=yes"`，无凭证直接失败不挂起 |
| 用 shell 的 `timeout` 包命令，结果瞬间"全部失败" | macOS 默认没有 `timeout` 二进制（GNU coreutils 才有，Homebrew 的叫 `gtimeout`） | 脚本用 `subprocess.run(timeout=)`，不依赖 `timeout` 命令 |

## 验证清单

- [ ] 动手前先跑过 **dry-run**（不带 `--apply` / `--push`），改动清单已出示给用户并确认
- [ ] 计划里**没有 detached HEAD 层**（若有，已先在各层 `git checkout <branch>` 修复并重跑 dry-run）
- [ ] 需 push 的层都有 upstream 分支（无 upstream 的已先 `push -u` 设置）
- [ ] `--apply` 时**传了 `--message`**，且 dry-run 显示的层数与实际提交层数一致（无改动层被跳过是正常的，不是漏）
- [ ] 每个有子模块的父仓，commit 后 `git show --stat HEAD` 能看到对应 submodule 的 **gitlink 变化行**（这是"gitlink 关系处理好"的判据，缺了就是漏更新）
- [ ] `--push` 后每层的**写后回读** SHA 一致（local == remote），对照表里没有 MISMATCH
- [ ] push 顺序是**子先于父**（深度降序），最内层最先 push、顶层最后 push
- [ ] 若发生中途中止：已按脚本打印的「已成功层 / 中止层」决定补推或回滚，没有在不知情的情况下重跑整条链
