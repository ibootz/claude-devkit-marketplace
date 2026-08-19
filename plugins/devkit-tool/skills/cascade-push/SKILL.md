---
name: cascade-push
description: 嵌套 git submodule（多层子模块）项目从最内层向外逐层提交推送，链式更新每一层父仓的 gitlink。push 前必出「推送简报」——逐层调查未提交改动（含 untracked）与待推送 commit（每条列 subject + 文件清单 + gitlink 标注），交 Human 批准后才带 --approved 推远端。自带 cascade-push.py：默认只出简报，--apply 才提交，--push --approved 才推送，push 后逐层写后回读远端 SHA。
when_to_use: |
  用户说"提交推送 submodule"、"嵌套子模块怎么提交"、"submodule 改了怎么 push 上去"、"多层子模块一层层往外提交"、"submodule 提交顺序"、"gitlink 没更新"、"父仓没记录子模块的改动"、"submodule push 了别人拉不到"、"submodule detached HEAD 怎么提交"、"用 foreach --recursive 提交 submodule 顺序错了"。
  **也覆盖「推之前先讲清楚要推什么」这类诉求**："push 前给我个清单"、"这次要推哪些 commit"、"本地还有哪些没提交/没推上去的"、"每个提交改了什么给我看看"、"我批准了再推"、"别直接推、先给简报"。
  **核心触发判据**：当前项目是真正的 git submodule 嵌套结构（有 `.gitmodules`、父仓 index 里有 mode 160000 的 gitlink 条目、子模块各自是独立 git 仓），且本轮要把改动从最内层一路提交推送到最外层。单仓 monorepo（没有 submodule）直接用 `git commit` / `git push` 即可，不需要本 skill。
---

# Nested Submodule Commit-Push（嵌套 submodule 由内向外逐层提交推送）

把"嵌套 submodule 项目的提交推送"做成**简报 → 批准 → 提交 → 推送**四段流程，靠脚本按正确拓扑序逐层执行，不靠人工记顺序——人工逐层是这类项目最高频的事故来源。

**两个不可跳的闸**：push 前必须出一份逐层简报并取得 Human 当轮批准（脚本层的机械闸是 `--approved`）；push 后必须逐层写后回读远端 SHA。

**设计基础**：机制依据来自 git submodule 的标准行为与社区共识——`git submodule foreach --recursive` 是「父先于子」（tail-recursive），方向与「由内向外提交」相反（[SO](https://stackoverflow.com/q/14846967)、[r/bash](https://www.reddit.com/r/bash/comments/1bz6lb9/)）；父仓 commit 的 gitlink 指向子 SHA，该 SHA 必须先存在于远端，否则 dangling（[Git Book](https://git-scm.com/book/en/v2/Git-Tools-Submodules)）。本 skill 的脚本据此自采嵌套树、按路径深度降序逐层处理，不依赖 foreach 的遍历顺序。

## 背景：两层以上嵌套，人工逐层必踩四个坑

git submodule 嵌套项目里，每个 submodule 自己是独立 git 仓，父仓通过 **gitlink**（index 里 mode 160000 的条目）指向子的某个具体 commit SHA。改了最内层代码后，要把它一路提交推送到最外层，**顺序只有一个正确方向：最内 → 最外**。人工逐层极易踩：

1. **顺序错**（先提交外层）→ 父仓 gitlink 指向一个还没 push、甚至远端不存在的子 SHA，别人 clone 父仓时拉不到子的那个 commit（dangling reference）。
2. **gitlink 漏更新**（提交了子，忘了在父仓 `git add <子>`）→ 父仓 commit 不含 gitlink 变化，子的新提交没被父记录，等于白提交。
3. **`git submodule foreach --recursive` 方向陷阱** → 它是「父先子后」，照搬来做提交直接制造第 1 个坑。
4. **推送范围盲区** → `git status` 只显示未提交改动，**看不见「已 commit 但未 push」的历史 commit**。那些 commit 会在这次 `--push` 时一并上远端，而调用方以为只推了本轮这点改动。多层嵌套把这个盲区乘以层数：每一层都可能各自压着几条陈年未推 commit。

前三个坑坏的是仓库状态，第 4 个坑坏的是**知情同意**——推上去的内容超出了 Human 批准的范围，而 push 到共享远端后没有干净的撤销路径。所以简报要调查的不只是"改了什么还没提交"，而是**"这次 push 会让远端多出哪些 commit"**。

这四个坑的共同点：**失败了不报错**。git 不会告诉你"顺序错了"、"gitlink 没更新"、"你顺带推了 11 条别的 commit"，提交看起来成功了，问题要到别人 clone、或下游拉取时才暴露。

## 机制（脚本据此实现，须理解）

- **拓扑序 = 路径深度降序**。最内层 submodule 路径最深，先处理；顶层 superproject 深度 0，最后处理。子的路径必然比父深，故深度降序天然满足「子先于父」的偏序；平级 submodule 之间顺序无关。
- **每层 `git add -A && git commit`（有 staged 才提交）**。子模块在父仓 index 里是 gitlink 条目；子 HEAD 变化后，父仓 `git add -A` 会把 gitlink 更新到子的新 SHA。于是「处理完子 → 处理父时 add -A」天然链式更新整条 gitlink 链。
- **待推送范围 = `<远端实际 SHA>..HEAD`**。基线取 `git ls-remote` 当场问到的远端 SHA，**不用本地的 `refs/remotes/...` 跟踪引用**——后者是上次 fetch 时的快照，可能已经过期，用它算出的待推送清单会漏或多。脚本默认在简报阶段先 `git fetch <remote> <branch>` 刷新对象库（只读远端、不动工作区），`--no-fetch` 可关但简报会标注"可能不准"。
- **push 必须子先于父**。父 commit 引用子 SHA，该 SHA 须先在远端存在。脚本按深度降序逐层 push（子先），每层 push 完立刻 `git ls-remote` 回读远端 SHA，与本地 HEAD 比对一致才算该层成功。
- **detached HEAD 必须拦截**。superproject checkout 出来的 submodule 常处于 detached HEAD；在上面 commit 会产生不在任何分支上的游离 commit，push 会丢。脚本检测到 detached HEAD 直接中止并报该层，不自动切分支（切错不可逆）。
- **未 init 的 submodule 必须剔除**。判据是 `git -C <该层> rev-parse --show-toplevel` 归一化后是否等于该层自身；不等说明 git 沿目录树向上命中了**上级仓**。脚本在发现阶段就把这类层剔掉并在简报里列名——在它们上面跑 `git add -A` 会把上级仓的全部改动裹进一个无关提交。

## 执行工作流

脚本随本 skill 提供。先定位它：

```bash
SP="$CLAUDE_PLUGIN_ROOT/skills/cascade-push/scripts/cascade-push.py"
ls -l "$SP"   # 必须存在再往下走
```

拿不到 `$CLAUDE_PLUGIN_ROOT` 时（如直接在源仓里跑），改用绝对路径 `plugins/devkit-tool/skills/cascade-push/scripts/cascade-push.py`。

### 第一步：简报（默认动作，不带任何 flag）

```bash
python3 "$SP"                              # 出简报
python3 "$SP" --root /path/to/superproject # 指定 superproject 根，缺省取 git toplevel
python3 "$SP" --no-fetch                   # 离线时用，简报会标注远端信息可能过期
```

它递归发现全部嵌套层级、剔除未 init 层，按深度降序逐层打印。**简报的完成判据是下面每一项都在输出里有着落**，缺项说明脚本跑挂了或该层被剔了，先查清再往下走：

- **每层的分支与 push 目标**（`<branch> → <remote>/<branch>`）以及远端当前 SHA。
- **每层的未提交改动全量清单**，分 staged / unstaged / untracked 三组，**不截断**——这就是 `--apply` 时 `add -A` 的实际范围。子模块目录那一行标 `(gitlink)`，代表指针移动而非文件内容改动。untracked 里命中可疑形态的（`.env` / `*.key` / `*.log` / `id_rsa` / `node_modules` 等）标"疑似不该提交"。
- **每层的待推送 commit 逐条**：短 SHA、日期、作者、subject，以及该 commit 的文件清单（gitlink 行标 `← gitlink 指针移动`）。这是第 4 个坑的解药。
- **本地其它分支未推送的 commit 计数**（提示性，本次只推当前分支，它们不会被推）。
- **阻塞清单**：detached HEAD 层（红，硬拦）、远端领先本地的层（红，push 会被拒）、无 upstream 的层（黄，`--push` 会失败）。有硬阻塞时脚本 exit 2。

### 第二步：取 Human 批准（不可跳过）

push 是不可逆的外部写，**批准必须走 `AskUserQuestion` 工具**——Human 常把会话投到手机上远程操作，只有这个工具名会触发推送通知；用 `<options>` 文本块问等于让他在外面完全不知道有事等他拍板。

转述简报时把这几样原样带上，让 Human 不打开终端就能判断：

- **逐层的待推送 commit subject**，不是只给"共 N 条"。汇总数字看不出里面有没有别人的 commit、有没有半年前忘推的东西。
- **被标"疑似不该提交"的 untracked 项**，逐个点名。`add -A` 对它们一视同仁。
- **待推送 commit 里的 gitlink 行**，说明这次推送会让哪一层的指针移到哪里。
- **阻塞项与你打算怎么处理**（先 pull 再重跑 / 先设 upstream / 先切分支）。

批准是**逐次的，不跨轮延续**。简报出完之后工作区又变了（自己改了文件、别人推了东西、你自己刚跑了 `--apply`），**重出简报重新取批准**——`--approved` 这个 flag 代表的是"Human 看过**这一份**简报"，不是一张通用许可证。

### 第三步：提交（--apply，本地、可逆）

```bash
python3 "$SP" --apply --message '本次改动说明'
```

- **`--message` 在 `--apply` 时必传**。脚本不自动编 message（避免 garbage commit）。每层实际 commit message 写成 `[<层路径>] <message>`，便于在 git log 里区分是哪一层；顶层仓前缀是 `(root)`。message 内容据简报里那一层的实际改动写，不要写"更新代码"这类看不出改了什么的话。
- 按深度降序逐层 `git add -A` → `git diff --cached --quiet` 判有无 staged → 有才 `git commit`，无改动的层跳过（不产生空提交）。
- 每层 commit 后脚本自动回读该次提交的 gitlink 变化行（`gitlink 已更新  M  <子模块路径>`）。**这是"gitlink 关系处理好"的判据**：有子模块的层，若子模块本轮有新提交而这里没打出 gitlink 行，就是漏更新，停下来查。
- 任一层 detached HEAD 立即整体中止，打印已提交层与中止层。

### 第四步：推送（--push --approved，不可逆）

```bash
python3 "$SP" --push --approved
```

- **缺 `--approved` 脚本直接 exit 2 拒绝执行**并提示先出简报。这道闸是给"忘了问就推"兜底的，不是给你跳过第二步的理由——先拿批准，再加 flag。
- 按深度降序逐层 `git push <remote> HEAD:<branch>`（子先于父）。
- 每层 push 完立刻**写后回读**：本地 `git rev-parse HEAD` 与 `git ls-remote <remote> refs/heads/<branch>` 取远端 SHA，两者一致才算该层成功；不一致或 push 失败立即整体中止，打印已成功层与中止层，不让后续层继续（避免半途状态）。
- 结尾打印每层 local / remote SHA 对照表。

`--apply` 与 `--push --approved` 可合用一次性走完。但**首次在一个嵌套仓用本 skill 时分开走**（简报 → 批准 → apply → 再出一次简报 → push），因为 `--apply` 之后待推送清单会变，再出一次简报能让 Human 看到"实际要推的最终形态"。

### 何时本 skill 不适用

- **单仓 monorepo**（无 `.gitmodules`、无 gitlink）→ 脚本会报告「未发现 submodule，仅顶层仓」，此时直接用 `git commit` / `git push` 即可。
- **只改了顶层仓自身、没动任何 submodule** → 同上，直接提交推送顶层。
- **拉取/同步方向**（父仓升级对 submodule 的引用，即 `git submodule update --remote`）→ 那是 pull 方向，走 `cascade-pull`；本 skill 只管 push 方向（子改动向外传播）。

## 已验证的坑

| 现象 | 真实原因 | 怎么核实 / 处置 |
|------|----------|----------------|
| push 完才发现远端多了一堆本轮之外的 commit | 那些是各层"已 commit 未 push"的历史 commit，`git status` 看不见它们，简报若只看未提交改动就会漏报 | 简报按 `<ls-remote 远端 SHA>..HEAD` 逐条列出，取批准时把 subject 逐条给 Human，不给汇总数字 |
| 简报里的待推送条数与实际 push 的对不上 | 用本地 `refs/remotes/...` 跟踪引用算范围——那是上次 fetch 的快照 | 基线取 `git ls-remote` 当场问的远端 SHA；脚本默认先 fetch，`--no-fetch` 时输出会标注"可能不准" |
| 父仓 push 后别人 clone 拿不到 submodule 的新提交 | 提交/推送顺序反了（先父后子），父 gitlink 指向尚未 push 的子 SHA → dangling | 严格最内→最外（脚本按深度降序保证）；push 后写后回读 `git ls-remote` 确认子 SHA 已在远端 |
| 子模块提交了，父仓 commit 却没记录它 | 父仓漏 `git add <子>`，gitlink 未更新 | 每层 `git add -A` 捕获该层 gitlink 变化；`--apply` 后脚本自动打印 `gitlink 已更新` 行，没有它 = 漏更新 |
| 用 `git submodule foreach --recursive` 提交，顺序全错 | 它是「父先子后」（tail-recursive），方向与「由内向外」相反 | 脚本自采嵌套树按深度降序，不用 foreach 做提交 |
| submodule commit 后 push 报错或改动丢失 | 处于 detached HEAD，commit 是游离 commit | 脚本 detached HEAD 预检中止；先 `git -C <该层> checkout <branch>` 再重跑简报 |
| push 被远端拒（non-fast-forward） | 该层远端领先本地（别人先推了） | 简报把"远端领先"列为**硬阻塞**并 exit 2；先在该层 `git pull --rebase`（或走 `cascade-pull`），再重跑简报 |
| `.env` / `*.key` / 一堆日志被提交上去 | `git add -A` 对 untracked 一视同仁 | 简报对可疑形态标"疑似不该提交"并全量列出 untracked；取批准时逐个点名，该 ignore 的先进 `.gitignore` |
| 某一层报告的改动清单与它的上级层**逐字相同**，或空目录层也报出一堆改动 | 该层是**未 init 的 submodule**（空目录，没有自己的 `.git`），在其中跑 git 会沿目录树向上找到**上级仓**并返回上级仓的状态，exit 0、无任何警告 | 脚本在发现阶段比对 `git -C <该层> rev-parse --show-toplevel` 与该层自身路径，不等即剔除并在简报里列名。注意 linked worktree 里的 `.git` 是**文件**不是目录，不能用"是不是目录"来判 |
| 解析 `git status --porcelain` 时 unstaged 被读成 staged，且路径少了首字符 | porcelain v1 每行前两列 XY 状态码**列首字符有语义**，unstaged-only 的行形如 ` M path`；对整份 stdout 做 `.strip()` 会吃掉首行那个前导空格 | 读这类输出不做整体 strip（脚本的 `run_git(..., strip_out=False)`）；自己写 git 解析代码时同理 |
| 某层没改动却产生了空 commit | 无差别 commit | `git diff --cached --quiet` 为真（无 staged）则跳过该层 |
| 多层嵌套时漏了中间某层 | 人工逐层易漏，或只递归了一层 | 脚本发现阶段递归读各级 `.gitmodules` 采全嵌套树，深度降序无遗漏 |
| push 半途失败，前面层已 push、后面没推 | 网络 / 认证 / 远端拒绝 / 写后回读不一致 | 任一层失败立即中止，打印「已成功 push 的层」与「中止层」，据此决定补推还是回滚 |
| 跑 `git ls-remote` / `fetch` 探测远端时 SSH 弹密码卡住 | 没禁交互 | 脚本已设 `GIT_TERMINAL_PROMPT=0` + `GIT_SSH_COMMAND="ssh -o BatchMode=yes"`，无凭证直接失败不挂起 |
| 用 shell 的 `timeout` 包命令，结果瞬间"全部失败" | macOS 默认没有 `timeout` 二进制（GNU coreutils 才有，Homebrew 的叫 `gtimeout`） | 脚本用 `subprocess.run(timeout=)`，不依赖 `timeout` 命令 |

## 验证清单

- [ ] 动手前先跑过**简报**（不带 `--apply` / `--push`），且简报里每层的未提交改动与待推送 commit 都有着落
- [ ] 简报里**每层的待推送 commit 逐条**（subject + 文件清单）已呈给 Human，不是只给了"共 N 条"
- [ ] untracked 里被标"疑似不该提交"的项已逐个点名，该 ignore 的已进 `.gitignore`
- [ ] Human 的批准通过 **`AskUserQuestion`** 拿到，且是**本轮**这一份简报的批准（工作区变过就重出简报重新取）
- [ ] 计划里**没有硬阻塞**：无 detached HEAD 层、无远端领先本地的层；无 upstream 的层已先 `push -u` 设置
- [ ] `--apply` 时传了 `--message`，且 message 写得出这一层实际改了什么
- [ ] 每个有子模块的父仓，`--apply` 输出里能看到该子模块的 **`gitlink 已更新`** 行（子模块本轮有新提交时）
- [ ] `--push` 带了 `--approved`，且这个 flag 对应一次真实发生过的批准
- [ ] push 后每层的**写后回读** SHA 一致（local == remote），对照表里没有 MISMATCH
- [ ] push 顺序是**子先于父**（深度降序），最内层最先 push、顶层最后 push
- [ ] 若发生中途中止：已按脚本打印的「已成功层 / 中止层」决定补推或回滚，没有在不知情的情况下重跑整条链
