---
name: claude-session-launch
description: 再起一个 Claude Code 会话来干活——后台会话用 `claude --allow-dangerously-skip-permissions --bg -n <名字>`（立即返回 8 位短 id，配 agents/attach/logs/stop 四个管理命令；`-n` 就是 `claude agents` 面板里显示的名字），要人盯着看的前台会话用两条 osascript 在 iTerm2 里弹新 tab。用户说「起一个后台会话/后台 agent」「用 cy 开几个窗口」「给新会话起个名字/指定 claude agents 里显示的名字」「并行开几个 claude 跑」「开个新 tab 跑 claude」「让另一个会话去做 X」「怎么看那个后台会话在干什么」「停掉那个后台会话」「claude --bg / claude agents / claude attach / claude logs / claude stop 怎么用」「claude logs 出来一堆乱码转义」「新开的 tab 跑在错的目录里」「pgrep iTerm2 查不到进程」「后台会话改完没合回主分支 / 没推送 / worktree 没清」时使用。**起会话之前就读**，别等 cwd 落错仓或 logs 刷出满屏 ANSI 才来。派活给一个**已经存在**的会话是另一件事，走 ListAgents + SendMessage；要新会话接手本会话上下文，先走 handoff-to 写交接文档。
---

# 起一个新的 Claude Code 会话

两条路，先按「要不要程序化管控」选，不按「哪条顺手」选。

| 维度 | `claude --bg` 后台会话 | osascript 弹 iTerm2 tab 前台会话 |
|---|---|---|
| 归属 | 被 `claude agents` **托管**：有 8 位短 id、有 logs、有 stop | 普通 TTY 进程，Claude Code 侧**没有任何管控入口** |
| 观察 | `claude logs <id>` / `claude attach <id>` | 只能靠人看那个 tab |
| 停止 | `claude stop <id>` | 出问题只能 `pgrep` / `lsof` 找 pid 再 `kill` |
| 占屏 | 不占 | 占：抢走一个 tab 与焦点 |
| 适用 | 无人值守跑活、并行铺开、要程序化管控 | 人要盯着看、要交互接管、要边跑边打字 |

**要害就是「托管」这一行**：后台会话是个被托管的对象；osascript 起的只是个普通进程，起完就
失联了。**默认选后台**，只有 Human 明确要「弹出来我盯着」时才走前台——它会抢屏。

以下命令行选项来自本机 `claude --help` / `claude agents --help` 的实际输出（Claude Code
v2.1.237，macOS；默认启动参数与起名两节于 v2.1.300 复核）。**引用选项时以当前 `claude --help` 输出为准**，不同版本会增删。

---

## 后台会话（`claude --bg`）

### 启动（已实测）

```bash
claude --allow-dangerously-skip-permissions --bg -n "<会话显示名>" "<初始 prompt>"
```

这条默认命令等于人手敲 `claude --allow-dangerously-skip-permissions`（常被设成 shell 别名，如
`cy`）再加 `--bg`。别名只在交互式 shell 里展开，Bash 工具里写展开后的全称。用户要指定模型或
权限模式时，再追加 `--model <别名或全名>` / `--permission-mode <模式>`。

四件必须知道的事：

1. **必须带初始 prompt**。`--bg` 没有「空转待命」模式，没有任务内容起不来。只想占一个可寻址
   的后台会话时，给个占位 prompt（如「待命，等待后续 SendMessage 指令」），起来之后再用
   `SendMessage` 派活。
2. **会话在当前工作目录下启动**；目录是 git 仓时，会话常在 worktree
   （`<仓>/.claude/worktrees/<名字>/`）里干活，活干完**不会自动合回主分支，也不提交推送**
   （`claude agents --json` 里可见后台会话 cwd 落在这类目录；2026-10-26 实测一例是在主仓 checkout
   启动、会话自己调 `EnterWorktree` 进的 worktree）。改仓库文件的活
   必须在初始 prompt 里写收尾，见下一节「改仓库文件的活：初始 prompt 末尾写收尾」。要它在别的仓干活，用
   `(cd /abs/path && claude --allow-dangerously-skip-permissions --bg ...)` 起——**不要发裸 `cd`**
   （会污染本会话 cwd，且本机 devkit-cd-blocker 插件硬拦）。
3. **每个会话都起一个人一眼认得出的名字**，规则见下一节「起名」。
4. **`--allow-dangerously-skip-permissions` 只是把 bypass 模式设为可切换，不直接开启它**
   （`claude agents --help` 原文：`Make bypass-permissions mode available ... without defaulting to it`）。
   会话的初始权限模式跟随用户 settings 的 `permissions.defaultMode`；Human attach 进去后可以按
   Shift+Tab 切到 bypass。后台会话无人值守，没人点权限确认框，所以默认带上它，Human 接管时不必
   重起会话。直接**开启** bypass 的写法——`--permission-mode bypassPermissions` 或
   `--dangerously-skip-permissions`——会放开全部权限检查，要用先向 Human 取当轮授权。

`--model` 接受别名（`sonnet` / `opus` / `fable`）或全名（如 `claude-opus-5`）。

### 改仓库文件的活：初始 prompt 末尾写收尾

后台会话会改仓库文件（写代码、改文档、改配置）时，把下面这段原样追加到初始 prompt 末尾——经
`handoff-to` 交接起的会话同样追加。尖括号占位由本会话起会话前填好：主仓路径与主分支名本会话
已知，后台会话自己去猜容易猜错仓或分支。

```text
收尾（活干完后按序做完，不等指令）：
1. 提交：在当前分支提交本次全部改动，message 按本仓惯例。
2. 回主仓：当前在 worktree 里（git rev-parse --git-dir 与 --git-common-dir 输出不一致即是）时，先记下当前分支名（即临时分支）与 worktree 绝对路径，再调 ExitWorktree {"action":"keep"} 回到 <主仓绝对路径>。这是本段授权的主动调用，不必再问用户。已在 <主分支名> 上则跳过第 2、3、5 步。
3. 合回：git -C <主仓绝对路径> merge <临时分支>。
4. 推送：git -C <主仓绝对路径> pull --rebase 后 git -C <主仓绝对路径> push。本步覆盖 devkit-tool:commit-push 里「worktree 只合回、不推远端」那一条。
5. 清理：git -C <主仓绝对路径> worktree remove <worktree 绝对路径>，再 git -C <主仓绝对路径> branch -d <临时分支>。
第 3～5 步一律在第 2 步之后跑：会话还处在 worktree 里时，Claude Code 拒绝一切用 -C 指向主仓的 git 命令（报错含 isolated in the worktree）。撞到这条拒绝说明漏了第 2 步，补做第 2 步再重试，它不算下面的停止条件；ExitWorktree 回报没有活动的 worktree 会话、重试仍被拒时，才停下。
任一步遇到合并冲突、rebase 冲突、push 被拒、被守卫拦下，停在那一步，把卡在哪一步和报错原文留在会话里等用户处理；分支删除只用 -d，推送不带 --force。
```

### 教训：worktree 会话里用 `git -C` 回主仓，harness 不放行（2026-10-26 实测）

6.33.x 的收尾模板让后台会话站在 worktree 里直接 `git -C <主仓> merge`。实测改动已提交，合回这一步被
Claude Code 拒绝，原文：

```
This session is isolated in the worktree <worktree 路径>, but this command redirects git to the shared checkout via -C. Refusing to run it — a worktree-isolated session's git operations must target its own worktree.
```

- **谁拦的**：Claude Code harness 内置的 worktree 会话隔离，不是插件 hook；`bypassPermissions` 下照拦，
  停用哪个插件都绕不过。作用范围是会话进了 worktree 之后，所有指向主仓 checkout 的 git 命令。
- **唯一出路是先离开隔离**：`ExitWorktree {"action":"keep"}` 回到主仓，再 merge、push、清理。用
  `action: "remove"` 会连临时分支一起删，此时还没合回，提交就丢了。
- **授权要写进 prompt**：`ExitWorktree` 的工具描述要求「只在用户要求时调用」。初始 prompt 不点名授权，后台会话
  即使想到这条路也会停下来问人；后台无人应答，合回、推送、清理就全部搁置。上面模板第 2 步的「本段授权的主动调用」
  就是为这个写的，改模板时保留。

**什么时候不追加**：

- 只读的活（调研、排查、出报告不改仓库文件）——没有可提交的改动。
- 主分支受发布规约管着（产线分支、只许走 MR / PR 合入）——删掉第 3 步，改成「合回后停下，报告
  待推送」，推送交还 Human。

### 起名：`-n` 就是 `claude agents` 面板里的名字（已实测）

`-n` 一个参数同时决定三处，起会话时就给，不留到事后改：

- `claude agents` 面板与 `claude agents --json` 的 `name` 字段；`--help` 原文另列 prompt 输入框、
  `/resume` 列表与终端标题；
- `SendMessage` 的寻址键；
- 会话 jsonl 里的 `custom-title` 与 `agent-name` 两行。2026-10-15 实测 4 个后台会话从启动到结束
  一直保持 `-n` 给的名字（各 14～16 条记录），装着 devkit-session-auto-title 也没被自动标题覆盖。

名字写成 `<分片依据>-<任务短语>`，如 `票13-产物落盘`、`查配置层-加载顺序`：Human 在面板里扫一眼就
知道哪个会话在干什么。接受中文。**同名 latest wins**——后建的同名会话会顶掉先建那个的可寻址性，
同一批并行起多个时把分片依据写进名字，互相可辨。

### 启动后的返回（已实测，原文照抄）

```
backgrounded · 338e6c99 · 测试启动bg对话
  claude agents             list sessions
  claude attach 338e6c99    open in this terminal
  claude logs 338e6c99      show recent output
  claude stop 338e6c99      stop this session
```

命令**立即返回**，打印 8 位短 id 与显示名。**这个 id 是后续一切管控的钥匙，起完就把它记下来
并在回复里告诉 Human**——丢了它就只能回头去 `claude agents --json` 里按名字捞。

### 观察：结构化走 `--json`，人看走 `attach`

| 命令 | 用途 | 注意 |
|---|---|---|
| `claude agents --json` | **脚本消费的唯一正路**。打印活动会话 JSON 数组，**不需要 TTY** | 加 `--all` 才含已完成的后台会话；`--cwd <path>` 只看某目录下起的后台会话 |
| `claude agents` | 交互式列表 | **需要 TTY**，在工具调用里不可用 |
| `claude attach <id>` | 在当前终端接管 | 会占住当前终端，交给 Human 自己敲 |
| `claude logs <id>` | 看最近输出 | **见下面第 1 个坑** |
| `claude stop <id>` | 停掉 | |

### 两个实测坑

**坑 1 · `claude logs <id>` 是 TTY 快照原文，满屏 ANSI 转义。** 输出里塞满
`[?2026h`、`[38;2;215;119;87m` 这类序列，一次 `tail -30` 就是几千字符的转义噪音——
**不要把它直接贴给 Human，也不要喂给下游程序**。要结构化数据走 `claude agents --json`；
要人看就让 Human 自己 `claude attach <id>`。

**坑 2 · 判断前台/后台看 `kind`，不是 `type` 或 `mode`。** `type` 与 `mode` 这两个键在会话
对象里**根本不存在**（已实测），拿它们判断会静默拿到 `None` 然后走错分支。

### `claude agents --json` 的实测字段（2026-08-20，11 个真实会话，v2.1.237）

字段全集：`cwd`、`id`、`kind`、`name`、`pid`、`sessionId`、`startedAt`、`state`、`status`。

| 字段 | 实测取值 | 说明 |
|---|---|---|
| `kind` | `background` / `interactive` | **这就是区分后台与前台的字段。** `--json` 两类都列（`--help` 原文：`interactive and background`） |
| `id` | 8 位短 id | **只有 `kind: background` 的会话有这个键**；`interactive` 会话没有 `id`。所以 `attach` / `logs` / `stop` 只对后台会话可用 |
| `sessionId` | 完整 UUID | 两类都有 |
| `status` | `idle` / `busy`（另有 `waiting`） | 「它现在忙不忙」 |
| `state` | `working` / `done` | **只有后台会话有**；`interactive` 会话该键缺失 |
| `cwd` / `name` / `pid` / `startedAt` | — | `startedAt` 是毫秒时间戳 |

**取值示例**（照抄这个形状去解析，别凭字段名猜语义）：

```bash
claude agents --json | python3 -c "
import sys, json
for s in json.load(sys.stdin):
    print(s['kind'], s.get('id','-'), s['status'], s['name'], s['cwd'])
"
```

---

## 前台会话（只承诺 iTerm2）

### 两条 osascript（已实测）

```bash
osascript -e 'tell application "iTerm" to tell current window to create tab with default profile' \
          -e 'tell application "iTerm" to tell current session of current window to write text "cd /absolute/target/dir && claude --allow-dangerously-skip-permissions -n 会话名"'
```

`create tab` 之后 `current session of current window` **已经指向新建那个 tab**，不必自己传句柄，
两条 `-e` 就够。

### 显式 `cd` 是默认做法，不是可选项（已实测）

**新 tab 的 cwd 继承 iTerm 的默认目录，不是你执行 osascript 时所在的目录。** 实测：从
`.../demo/.claude/worktrees/elegant-soaring-pancake` 发起，新会话落在
`/Users/zhangq/Workspace/mine/claude-devkit-marketplace`——另一个 tab 的目录。

**这个错误不报错**：会话正常启动，只是在错的仓里干活。所以 `write text` 的内容一律写成
`cd /absolute/target/dir && claude --allow-dangerously-skip-permissions -n <名字> ...`，绝对路径，不省；
命名规则与后台会话相同。

### AppleScript 里的应用名是 `iTerm`，不是 `iTerm2`（已实测）

app bundle 是 `/Applications/iTerm.app`，`tell application "iTerm"` 正常工作。而
**`pgrep -l iTerm2` 查不到进程**（返回 exit 1）——**不要拿它为空去判断 iTerm 没在跑**，那是
一个静默误导的否定结论。要判进程在不在，查 `iTerm` 这个名字。

---

## 派活与交接：走既有能力，别另造一套

- **起完之后追加指令、要它回报**：`ListAgents` 拿确切名字（就是 `-n` 设的那个，不是 8 位 id
  或 sessionId）→ `SendMessage` 按名字发。跳过 `ListAgents` 照记忆里的名字发，会撞
  `No agent named X is reachable`。
- **要新会话接手本会话手上的活**：走 `devkit-tool:handoff-to` 的「新起会话」分支——先写交接
  文档，再把文档路径写进 `--bg` 的初始 prompt 一步起好，不先起占位会话再 `SendMessage`。交接
  文档的骨架、去敏、授权边界都在那个 skill 里，本 skill 只管把会话起出来。

**权限边界按会话算**：初始 prompt 与 `SendMessage` 里都只写本会话自己也能做的事；本会话已被拦下、
或预计会被拦的动作交还 Human。借另一个会话去做是权限洗白，Human 会因此失去他本该看到的那个决定点。

---

## 不要用 shell 把 claude 后台化

`claude --bg` 是 Claude Code 自己的后台会话机制、自带托管，**它不属于「本地测试服务必须走
Bash 工具 `run_in_background`」那条约束的管辖对象**，直接前台调用即可（它自己立即返回）。

但**不要给出任何用 shell 后台化启动 claude 的写法**——`nohup claude ... &`、命令行末尾裸 `&`、
`disown`、`setsid`、`screen -dmS`、`tmux new -d`。那样起出来的会话既不受 `claude agents` 托管，
也不受 harness 托管，Human 和 AI 都失去观察入口，且与本机全局约束冲突。要后台就用 `--bg`。

---

## 本 skill 未覆盖的边界（都是未实测，别当成已知结论写给 Human）

- **其它终端**：Terminal.app、Ghostty、WezTerm、tmux 的 AppleScript / CLI 接口各不相同。
  本 skill 只承诺 iTerm2。
- **iTerm 没在运行时** `tell application "iTerm"` 是否会拉起它（AppleScript 常规行为如此，未实测）。
- **`create window`**（新开窗口而非 tab）。
- **`claude --tmux`**：选项确实存在（`--help` 原文：`Create a tmux session for the worktree
  (requires --worktree). Uses iTerm2 ... --tmux=classic for traditional tmux.`），**依赖
  `--worktree`，单独给无效**。tmux 用户可能有更好的路径，但本机未实测。
- **启动后再改名**：attach 进会话后用 `/rename` 能改标题，但 `claude agents` 面板的名字与 `SendMessage`
  寻址键是否跟着变未实测。需要改名时优先停掉重起一个带新 `-n` 的会话。
- **`defaultMode` 不是 `bypassPermissions` 的机器**上，带 `--allow-dangerously-skip-permissions` 起的
  后台会话初始是什么模式。本机 `defaultMode` 为 `bypassPermissions`，实测 4 个会话都记
  `permissionMode:"bypassPermissions"`，分不出是 flag 还是 settings 的作用。

要用到上面任何一条，先自己验一次再写进回复，不要照抄这一节的措辞当结论。

---

## 什么时候不触发

- **要派活给一个已经存在的会话** → `ListAgents` + `SendMessage`，不必再起一个；要把本会话
  上下文交给它，走 `devkit-tool:handoff-to`。
- **要在本会话内并行干活** → 用 `Agent` 工具派子代理，那是同一会话内的并行，成本远低于起一个
  独立会话，且子代理回执直接回到本会话。**判据是：这活要不要一个独立的、跨轮存活的会话身份。**
  不要用起会话代替派子代理。
- **要起本地测试服务**（后端 / 前端 / mock / DB）→ 走 Bash 工具的 `run_in_background: true`
  由 harness 托管，与本 skill 无关。
- **只想看现在有哪些会话在跑** → 直接 `claude agents --json`，不必读完本 skill。
