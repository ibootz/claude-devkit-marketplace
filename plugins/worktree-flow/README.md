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
还要求 `tool_response` 只含原问题与单一 `answers` 映射；自由文本、备注、AFK、未知字段、跳过、
非批准标签皆不落授权。

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
| 合流进行中 | git 目录标记 | merge / cherry-pick / revert / rebase 标记存在则放行 |
| 本轮授权 | session-scoped 临时状态 | 有效则放行；缺失、过期、损坏则拒绝 |

Bash 侧仍只认命令位上的 `git commit`。正则无法可靠判断 `sed -i`、重定向、heredoc 或解释器
内部写入，故这些保持已知漏报，由注入纪律兜住。

## 回归用例

```bash
node plugins/worktree-flow/tests/main-branch-guard.test.js
node plugins/worktree-flow/tests/round-approval.test.js
```

覆盖：无授权拒绝；固定授权卡放行调用；预填回答拒绝；批准后整轮多次放行；下一条用户消息、Stop、
SessionEnd 撤销；非批准、自由文本、备注、AFK、问题篡改、损坏与过期状态皆 fail-closed；以及 feature
分支、detached HEAD、豁免目录、合流进行中和 Bash 已知漏报不回归。

## worktree 与 submodule 边界

`EnterWorktree` 默认 `worktree.baseRef = fresh`，本地主分支领先远端时会漏本地提交；先比
`HEAD` 与 `origin/<branch>`，不一致则用 `head` 或从本地 `HEAD` 手动建。

普通 worktree 不初始化 submodule。完整聚合仓 worktree 用 `task-keeper:tk-worktree`；嵌套提交推送
用 `devkit-tool:cascade-push`。若现有 checkout 才持有脏改动，可向 Human 申请本轮直写，勿开空
worktree 后再跨隔离边界操作原仓。

## 隔离边界与主分支保护是两层，别混

两层闸都在写操作那一刻拦下，成因与解法完全不同。归因错了的代价是实测过的：把隔离误报成主分支
保护，会去申请一个根本用不上的授权；反过来会以为「换个目录就行」而漏掉授权环节。

| 报错里的判据句 | 拦截者 | 判据 | 解法 |
|---|---|---|---|
| `isolated in the worktree` | worktree 会话隔离（harness 工具层，非本插件） | 目标路径落在父仓共享 checkout 内 | 改 worktree 副本，或 `ExitWorktree {"action":"keep"}` 后再写 |
| `[L1-BLOCKER] check=worktree-flow` | 本插件的 `main-branch-guard.js` | 目标仓当前分支逐字等于 `main` / `master` | 走 worktree 流程，或 Human 当轮授权 |

worktree 建在 `<仓根>/.claude/worktrees/<名>`，而 `.claude/` 是本插件的自动豁免目录之一——所以
worktree 内的写操作**不会**被主分支保护拦，拦它的只有会话隔离那一层。完整判据、`ExitWorktree`
两个 action 的取舍、跨会话代做的明禁与例外，见 `skills/worktree-boundary/SKILL.md`。

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
