# worktree-flow · 主分支保护

`main` / `master` 默认不直接落笔：改动走临时 worktree，再以 `--no-ff` 合回。确需留在主分支时，
主会话可用 `AskUserQuestion` 取得 Human **本轮**授权，不再只能撞无条件硬拒。

## 构成

| 组件 | 挂载点 | 作用 |
|---|---|---|
| `hooks/guards/main-branch-guard.js` | `PreToolUse(Write\|Edit\|MultiEdit\|NotebookEdit\|Bash)` | 无本轮授权时拒绝主分支写入；finding 给 worktree 与授权两条路径 |
| `hooks/approval-question-guard.js` | `PreToolUse(AskUserQuestion)` | 固定授权卡须逐字段匹配，拒绝 AI 预填回答 |
| `hooks/round-approval-state.js` | `PostToolUse(AskUserQuestion)` + `SessionStart` + `UserPromptSubmit` + `Stop` + `SessionEnd` | Human 明确批准后记本轮状态，并在边界事件撤销 |
| `hooks/worktree-flow-inject.js` | `SessionStart` + `UserPromptSubmit` + `SubagentStart` | 事前注入流程与授权边界 |
| `skills/worktree-flow/SKILL.md` | skill | worktree 四步、授权路径、submodule 边界 |
| `skills/worktree-boundary/SKILL.md` | skill | 已在 worktree 会话内的隔离边界与退出纪律 |

两个 skill 按**决策时刻**分工，不是按主题分工：`worktree-flow` 管「我在 main 上要落笔，该不该开
worktree / 要不要申请直写授权」——进入之前；`worktree-boundary` 管「我已经在 worktree 会话里了，
该写哪一份副本、撞的是哪一层闸、怎么安全退出与合回」——进入之后到退出之前。两份 description 各自
点明了这条界限，并互相指路。

`UserPromptSubmit` 只触达主会话，`SubagentStart` 单独触达子代理；二者都可能写文件，故双挂。
`SessionStart` 覆盖启动与 compact 后重注。

## 为什么不用 `permissionDecision: "ask"`

本机 `defaultMode = bypassPermissions` 时，PreToolUse 返回 `permissionDecision: "ask"` 实测不弹框、
直接放行，不能承载主分支授权。本插件改用两段式：

1. guard 首次命中仍 `exit 2`，只阻止尚未获批的调用；
2. 主会话真实调用 `AskUserQuestion`，PostToolUse 仅在结构化
   `tool_response.answers[完整问题] === "批准本轮"` 时落授权状态。

Claude Code 2.1.234 的二进制传递链确认：AskUserQuestion 的 `call().data` 原样进入
`PostToolUse.tool_response`，回答在 `answers`，自由文本在 `response`，备注在 `annotations`，
AFK 自动继续带 `afkTimeoutMs`。后面三类一律 fail-closed，不解析模型可见的 UI 文本，也不回读
transcript。

## 本轮授权契约

授权卡的 `metadata.source` 固定为 `worktree-flow`。触发时实际的仓绝对路径、`main` / `master`
分支与目标编码在完整问题正文的“现场证据”行；其余正文同时呈现：

- 起源：哪个仓、分支、目标命中保护；
- 差距：默认应走 worktree，当前想直接写；
- 影响：批准放行当前会话本轮所有主分支写入；
- 现场证据：仓、分支、目标的实值。

PreToolUse 要求问题、选项、metadata 逐字段匹配，且输入不能带 `answers` / `annotations`。PostToolUse
还要求 `tool_response` 只含原问题、单一 `answers` 映射，以及一个**空的** `annotations`（该键可缺席，
见下方 1.5.1）；自由文本、非空备注、AFK、未知字段、跳过、非批准标签皆不落授权。

授权状态按 `session_id` 的 SHA-256 命名，存系统临时目录，目录权限 `0700`、文件权限 `0600`；
下一次 `UserPromptSubmit`、`Stop`、`SessionEnd` 或新 `SessionStart` 删除。另设 24 小时 fail-safe，防异常退出遗留。
状态文件不含对话、仓内容或用户回答原文。

**批准粒度**：当前会话本轮所有 `main` / `master` 写入与 `git commit`。这是 Human 选择的粒度，
并非每次工具调用重问。授权不会跨下一条用户消息，也不会成为以后会话的常驻许可。

子代理没有 `AskUserQuestion`，撞闸后只能回主会话申请；同一 session 的本轮状态可供本轮动作继续。

## 主分支判据

| 步骤 | 取值方式 | 比较 |
|---|---|---|
| 目标仓 |文件工具取目标路径；Bash 取 `cwd` 或 `git -C` | `git rev-parse --show-toplevel` 失败则放行 |
| 分支 | `git rev-parse --abbrev-ref HEAD` | 逐字等于 `main` 或 `master` |
| 豁免路径 | 文件相对仓根路径 | `.claude/`、`.keeper/`、`.git/` 或显式配置前缀 |
| 提交范围 | `git diff --cached --name-only` + 命令里的 pathspec | 非空且**每一条**都豁免则放行；判不定则拦 |
| 合流进行中 | git 目录标记 | merge / cherry-pick / revert / rebase 标记存在则放行 |
| 本轮授权 | session-scoped 临时状态 | 有效则放行；缺失、过期、损坏则拒绝 |

Bash 侧仍只认命令位上的 `git commit`。正则无法可靠判断 `sed -i`、重定向、heredoc 或解释器
内部写入，故这些保持已知漏报，由注入纪律兜住。

### `git commit` 的提交范围豁免（1.4.0）

1.3.0 之前 Bash 侧一律 `evaluate(dir, null)`，`filePath` 为 `null` 时豁免判定整段被短路：
**路径豁免对 `Write` / `Edit` 生效，对 `git commit` 不生效**。后果是 keeper 在 `main` 上写
`.keeper/` 台账一路放行，到提交那一步被拦——而它无路可走（子代理不能调 `AskUserQuestion`）。

1.4.0 起，命中受保护分支后再判这次提交能不能**证明**只动豁免路径，三条同时成立才放行：

1. **flag 全在白名单内**。`-a` / `-A` / `--all` / `-i` / `--include` / `--amend` / `--patch` /
   `--pathspec-from-file` 出局——它们在提交那一刻才扩大暂存范围或改写既有提交，事先读到的
   索引不再是这次提交内容的权威快照。**未列入白名单的 flag 一律出局**，包括 git 日后新增的。
2. **显式 pathspec 逐条豁免**（`--` 之后与裸路径形态都算）。通配符与 `:` 开头的 magic
   pathspec 不展开，直接判不定。pathspec 带走的是工作区内容、绕开索引，故必须单独校验。
3. **索引非空且逐条豁免**。读法钉死了三个配置（`diff.relative=false` /
   `core.quotePath=false` / `--no-renames`），使输出不受本机 git 配置影响、重命名摊成
   delete + add 两条而不是只看到新名字。

**白名单不是黑名单，这是有意的。** 黑名单漏一个新 flag 会静默放行；白名单最坏只是多拦一次
本来安全的写法，而出口一直都在（先窄 `git add` 再不带 `-a` 提交，或走 worktree）。判不定
一律维持阻断，方向与本机制存在以来一致。

### `tool_response.annotations` 按可选键处理（1.5.1）

1.5.0 及之前，PostToolUse 侧要求 `tool_response` 的键集**恰好**是 `{questions, answers}`
（`hooks/lib/round-approval.js` 的 `isApprovalResponse()`）。而 harness 实际回执**恒带第三个键
`annotations`**——Human 没写备注时它是空对象，键本身始终在。两者一撞，结果是**每一次结构完全
合规的 Human 批准都被丢弃**：`grantRound()` 压根不被调用，状态文件不出现，下一次写入照旧被拦，
且全程无任何报错或提示。Human 反复点“批准本轮”，看起来像插件是硬拦截、没有授权通道。

1.5.1 起 `annotations` 按可选键处理：缺席或为空对象都放行，**非空仍然拒绝**——Human 写了备注即
说明这次批准是附条件的，不能当无条件放行（`expectRejected('Human 备注存在', ...)` 那条用例语义
不变）。`annotations` 存在但不是对象（`null`、数组、字符串）同样拒绝。

**为什么测试全绿却挡不住这个 bug**：`tests/round-approval.test.js` 的 `approvalPayload()` fixture
造的回执只有两个键，与真实 harness 形态不一致，于是被测的恰好是唯一能通过的那个形状。1.5.1 把
fixture 的默认回执改成带 `annotations: {}`，让测试基线等于真实形态，并补了“回执无 annotations
键时仍批准”与“annotations 不是对象”两侧用例。

## 回归用例

```bash
node plugins/worktree-flow/tests/main-branch-guard.test.js
node plugins/worktree-flow/tests/round-approval.test.js
```

覆盖：无授权拒绝；固定授权卡放行调用；预填回答拒绝；批准后整轮多次放行；下一条用户消息、Stop、
SessionEnd 撤销；非批准、自由文本、备注、AFK、问题篡改、损坏与过期状态皆 fail-closed；以及 feature
分支、detached HEAD、豁免目录、合流进行中和 Bash 已知漏报不回归。`git commit` 提交范围豁免的
判据两侧各有用例：全豁免暂存区 / 豁免 pathspec / `git -C` / 粘连值 `-m"msg"` 应放行；空索引 /
混了源码 / `-a`·`-A`·`--all`·`-i`·`--include`·`--amend`·`--patch` / 源码 pathspec / glob /
`--pathspec-from-file` / 未知 flag 应仍拦。

## worktree 与 submodule 边界

`EnterWorktree` 的 `name` 使用 `<仓名短名>-<功能词1>-<功能词2>-<功能词3>`：仓名取仓根目录名并转为 lowercase `kebab-case`，功能最多 3 个词，不足不补；同名冲突时仅追加 4 位短 hash。这样目录与分支可直接识别来源仓和任务，例如 `claude-devkit-fix-hook`。`EnterWorktree` 默认 `worktree.baseRef = fresh`，本地主分支领先远端时会漏本地提交；先比
`HEAD` 与 `origin/<branch>`，不一致则用 `head` 或从本地 `HEAD` 手动建。

普通 worktree 不初始化 submodule。完整聚合仓 worktree 用 `task-keeper:tk-worktree`；嵌套提交推送
用 `devkit-tool:cascade-push`。若现有 checkout 才持有脏改动，可向 Human 申请本轮直写，勿开空
worktree 后再跨隔离边界操作原仓。

## 三道闸，别混（1.6.0 起从两道扩到三道）

三道闸都在写操作那一刻拦下，成因与解法完全不同。归因错了的代价是实测过的：把隔离误报成主分支
保护，会去申请一个根本用不上的授权；反过来会以为「换个目录就行」而漏掉授权环节。

| 报错里的判据句 | 拦截者 | 判据 | 解法 |
|---|---|---|---|
| `isolated in the worktree` | worktree 会话隔离（harness 工具层，非本插件） | 目标路径落在父仓共享 checkout 内 | 改 worktree 副本，或 `ExitWorktree {"action":"keep"}` 后再写 |
| `[L1-BLOCKER] check=worktree-flow` | 本插件的 `main-branch-guard.js` | 目标仓当前分支逐字等于 `main` / `master` | 走 worktree 流程，或 Human 当轮授权 |
| `Refusing to run it — a worktree-isolated session's git operations must target its own worktree` | 会话隔离管 Bash 命令的那一半（harness 工具层，非本插件） | 两种成因共用一条报错：①`git -C <父仓>` / `--git-dir` / `GIT_DIR` 把 git 指回共享检出且这次是写；②命令复杂到它无法静态判定落点（`python3 - <<EOF` 之类内联脚本、多段串联），此时保守拒绝，**哪怕目标就在 worktree 内** | ①退出后再跑；②拆成平铺命令，或改用 `Read` / `Edit` / `Write` 文件工具——它们不过这道闸 |

第三道是 2026-09-10 实测补入的：一条落点完全在 worktree 内的 `python3 - <<'PYEOF'` 改文件脚本
被它拒绝，报错却与「把 git 指回父仓」那种情形逐字相同。**两种成因共用一条报错**，是这道闸最容易
误判归因的地方。

worktree 建在 `<仓根>/.claude/worktrees/<名>`，而 `.claude/` 是本插件的自动豁免目录之一——所以
worktree 内的写操作**不会**被主分支保护拦，拦它的只有会话隔离那两半。

**三道闸都有自救路，没有一道的正解是把命令交给 Human 敲**（1.6.0 新增的纪律，起因见下）。完整
判据、`ExitWorktree` 两个 action 的取舍、退—改—回三步往返、跨会话代做的明禁与例外，见
`skills/worktree-boundary/SKILL.md`。

### 撞闸不甩锅（1.6.0）

用户级 `CLAUDE.md` 第 4 条「没有阻断，就不许把命令抄给用户敲」的闭集第 1 项旧文是「已经真撞上
守卫……拿到了 L1-BLOCKER」。字面读下来撞了闸就获准把命令交出去，2026-09-09 至 09-10 的历史会话
里**实测被这么用了三次**——其中一次 AI 逐字引用了那条规则的标题，而它当时只要 `ExitWorktree` →
改 → `EnterWorktree {"path":...}` 三步就能自己做完；另一次 Human 不得不亲口说「授权你通过
exitworktree 退出到主 checkout 修改 然后再回来」，AI 才动。三次里 `ExitWorktree` 没有一次是 AI
自己想起来的。

该规则已于 2026-09-10 修订，第 1 项现在要求拿到 L1-BLOCKER 之后先问「这道闸自带申请通道或自解
手段吗」。本插件在 `hooks/worktree-flow-inject.js` 的注入文本里同步压了一句，因为要对抗的那条
规则同样是每轮在场的——软注入对软注入，权重才对得上。

### 第二个触发时刻：同仓并发会话（1.6.0）

`skills/worktree-flow/SKILL.md` 新增一节：分支判据之外，「同一个仓正有别的会话在工作」也是开
worktree 的理由——git 索引全仓共享，两个会话各自 `git add` 之后谁先 `git commit` 谁就带走当时
索引里的全部暂存。

**判据交给 Human，不自动探测。** 五类探测手段已逐条实测（`git worktree list`、
`.claude/worktrees/` 目录、`ps` 配 `lsof` 查 claude 进程 cwd、`~/.claude/projects/` 下 session
文件 mtime、`~/.claude/` 下的 socket 与 lock），**没有一种是单条命令、秒级且可靠的**——
`~/.claude/` 下不存在仓库级活跃标记，`daemon.lock` 是全局单例且 cwd 会漂到 `$HOME`。最接近的
`ps` + `lsof` 组合既漏报（对方走 IDE 插件启动、或 cwd 落在某个 worktree 子目录）也误报（残留
spare 进程），且必须先排掉自己那条进程链。错报代价不对称：漏报只是回到默认行为，误报是每次
落笔都打断人一次，而噪音会让整条纪律被关掉。

## 目录豁免与全局关闭

细粒度目录豁免：

```json
{ "env": { "WORKTREE_GUARD_EXEMPT": "docs/,config/" } }
```

`WORKTREE_GUARD_EXEMPT_DOTDIRS=1` 放行所有顶层点目录，亦会放开 `.github/workflows/`、`.githooks/`
等高影响脚本目录，默认关闭。

`WORKTREE_GUARD=off` 保留为独立全局关闭开关，**不是 Human 本轮授权**。AI 不得自行启用；长期写进
settings 等于卸载保护，却会制造“仍受保护”的错觉。

## Codex 侧

`.codex-plugin/plugin.json` 已登记，但 hooks 为 Claude Code 专有。Codex 侧只有 skill 指引，
没有机械门控或 AskUserQuestion 授权状态机。
