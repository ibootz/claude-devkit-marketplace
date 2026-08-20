---
name: claude-session-launch
description: 再起一个 Claude Code 会话来干活——后台会话用 `claude --bg`（立即返回 8 位短 id，配 agents/attach/logs/stop 四个管理命令），要人盯着看的前台会话用两条 osascript 在 iTerm2 里弹新 tab。用户说「起一个后台会话/后台 agent」「并行开几个 claude 跑」「开个新 tab 跑 claude」「让另一个会话去做 X」「怎么看那个后台会话在干什么」「停掉那个后台会话」「claude --bg / claude agents / claude attach / claude logs / claude stop 怎么用」「claude logs 出来一堆乱码转义」「新开的 tab 跑在错的目录里」「pgrep iTerm2 查不到进程」时使用。**起会话之前就读**，别等 cwd 落错仓或 logs 刷出满屏 ANSI 才来。派活给一个**已经存在**的会话是另一件事，走 ListAgents + SendMessage。
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
v2.1.237，macOS）。**引用选项时以当前 `claude --help` 输出为准**，不同版本会增删。

---

## 后台会话（`claude --bg`）

### 启动（已实测）

```bash
claude --bg -n "<会话显示名>" --model sonnet --permission-mode acceptEdits "<初始 prompt>"
```

四件必须知道的事：

1. **必须带初始 prompt**。`--bg` 没有「空转待命」模式，没有任务内容起不来。只想占一个可寻址
   的后台会话时，给个占位 prompt（如「待命，等待后续 SendMessage 指令」），起来之后再用
   `SendMessage` 派活。
2. **会话在当前工作目录下启动**，cwd 与执行命令时一致。要它在别的仓干活，用
   `(cd /abs/path && claude --bg ...)` 起——**不要发裸 `cd`**（会污染本会话 cwd，且本机
   cd-blocker 插件硬拦）。
3. **`-n` 是显示名，同时是 `SendMessage` 的寻址键**。接受中文（已实测）。**同名 latest wins**
   ——后建的同名会话会顶掉先建那个的可寻址性，所以同一批并行起多个时名字必须互相可辨（把分片
   依据写进名字，别都叫 `probe-x`）。
4. **`--permission-mode` 要按任务实际需要的写域先给够**。后台会话无人值守，没人点权限确认框，
   给窄了它会卡在那里。可选值：`acceptEdits` / `auto` / `bypassPermissions` / `manual` /
   `dontAsk` / `plan`。`bypassPermissions` 需配合 `--dangerously-skip-permissions` 或
   `--allow-dangerously-skip-permissions`（**这一组的实际行为未实测**；它放开全部权限检查，
   要用先向 Human 取当轮授权，不要自己顺手加上）。

`--model` 接受别名（`sonnet` / `opus` / `fable`）或全名（如 `claude-opus-5`）。

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
          -e 'tell application "iTerm" to tell current session of current window to write text "cd /absolute/target/dir && claude -n 会话名"'
```

`create tab` 之后 `current session of current window` **已经指向新建那个 tab**，不必自己传句柄，
两条 `-e` 就够。

### 显式 `cd` 是默认做法，不是可选项（已实测）

**新 tab 的 cwd 继承 iTerm 的默认目录，不是你执行 osascript 时所在的目录。** 实测：从
`.../demo/.claude/worktrees/elegant-soaring-pancake` 发起，新会话落在
`/Users/zhangq/Workspace/mine/claude-devkit-marketplace`——另一个 tab 的目录。

**这个错误不报错**：会话正常启动，只是在错的仓里干活。所以 `write text` 的内容一律写成
`cd /absolute/target/dir && claude ...`，绝对路径，不省。

### AppleScript 里的应用名是 `iTerm`，不是 `iTerm2`（已实测）

app bundle 是 `/Applications/iTerm.app`，`tell application "iTerm"` 正常工作。而
**`pgrep -l iTerm2` 查不到进程**（返回 exit 1）——**不要拿它为空去判断 iTerm 没在跑**，那是
一个静默误导的否定结论。要判进程在不在，查 `iTerm` 这个名字。

---

## 起完之后怎么派活：走既有能力，别另造一套

会话起来之后，给它派活、追加指令、要它回报，一律走 **`ListAgents` 先拿确切名字 →
`SendMessage` 按名字发**。寻址键是会话名（`-n` 设的那个），不是 session id；**跳过
`ListAgents` 直接照记忆里的名字发，会撞 `No agent named X is reachable`**。

`SendMessage` 只传一段纯文本，不带对话历史与文件。要把整个上下文交出去，落盘一份自足文档、
在消息里给绝对路径，不要试图用消息搬运上下文。

**权限边界是按会话算的**：不要请另一个会话去做本会话已被拦下、或你预计自己权限会拦的动作——
那是权限洗白，Human 会因此失去他本该看到的那个决定点。

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
- **`--bg` 配 `bypassPermissions`** 的实际行为。

要用到上面任何一条，先自己验一次再写进回复，不要照抄这一节的措辞当结论。

---

## 什么时候不触发

- **要派活给一个已经存在的会话** → `ListAgents` + `SendMessage`，不必再起一个。
- **要在本会话内并行干活** → 用 `Agent` 工具派子代理，那是同一会话内的并行，成本远低于起一个
  独立会话，且子代理回执直接回到本会话。**判据是：这活要不要一个独立的、跨轮存活的会话身份。**
  不要用起会话代替派子代理。
- **要起本地测试服务**（后端 / 前端 / mock / DB）→ 走 Bash 工具的 `run_in_background: true`
  由 harness 托管，与本 skill 无关。
- **只想看现在有哪些会话在跑** → 直接 `claude agents --json`，不必读完本 skill。
