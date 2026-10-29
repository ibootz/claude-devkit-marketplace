---
name: orphan-process-cleaner
description: "查找并清理 Claude Code 拉起、仍在后台跑的进程（macOS 与 Linux/WSL；不支持 Windows）。分两类列：逃逸——会话退出、compact、清屏丢了任务句柄，或 nohup/& 后被 launchd/init 收养，父进程链上已没有活着的 claude；长驻——claude 还在，但 run_in_background / Monitor 拉起的 dev server、watch、监听端口的服务已跑很久。自带只读探测脚本，默认只列不杀，用户逐个点名后才 kill。用户说「后台还有什么在跑」「端口被占了是谁」「清理游离进程」「孤儿进程」「会话关了服务还在」「TaskList 找不到但进程还在」「之前起的 dev server 还在吗」时使用。"
---

# 后台进程排查与清理

脚本把当前用户的进程分成三类，后文一律用这三个词：

| 类别 | 判据 | 默认处置 |
|---|---|---|
| **逃逸** | 带 Claude 拉起的标记，但父进程链上已没有活着的 Claude 进程 | 清理候选，逐个问用户 |
| **长驻** | 父进程链上有活着的 Claude，经 Bash / Monitor 工具的包装 shell 拉起，已跑满 `--min-age`（默认 10 分钟） | 本会话的走 `TaskStop`；别的会话的问用户 |
| **组件** | 父进程链上有活着的 Claude，但不经包装 shell（MCP server、状态栏、hook 子进程） | 不动 |

「Claude 拉起的标记」指三者任一：进程环境里的 `CLAUDECODE=1` / `CLAUDE_CODE_SESSION_ID`；自身或祖先命令行含 `shell-snapshots/snapshot-`（工具的包装 shell）；与带标记的进程同属一个组长已退出的进程组。用户终端手动起的服务、brew services / launchctl / Docker / IDE 这类系统级 daemon 不带这些标记，脚本不列——它们不归本 skill 管。

## 步骤

### 1. 跑探测脚本（只读）

脚本路径是本 skill 加载时显示的 Base directory 拼上 `scripts/find_bg_procs.py`：

```bash
python3 <Base directory>/scripts/find_bg_procs.py            # 逃逸全列，长驻只列跑满 10 分钟的
python3 <Base directory>/scripts/find_bg_procs.py --min-age 1h
python3 <Base directory>/scripts/find_bg_procs.py --all      # 另列组件
python3 <Base directory>/scripts/find_bg_procs.py --json     # 结构化输出
python3 <Base directory>/scripts/find_bg_procs.py --full     # 命令行不截断
```

脚本只调 `ps`、`lsof`（Linux 缺 lsof 时用 `ss`）与 `/proc`，不发任何信号。Windows 上直接退出码 2，告诉用户到 WSL 里跑。

用户问的是「端口 X 被谁占」：先跑脚本看各组的「监听」字段。端口不在清单里，就是非 Claude 拉起的进程，用 `lsof -nP -iTCP:<port> -sTCP:LISTEN`（Linux：`ss -ltnp 'sport = :<port>'`）报出是谁，处置交用户，本 skill 不清理它。

本步完成的标志：三类各几组已知，每组的组根 pid 已拿到。

### 2. 逐组定处置建议

每组一行 `■ 组根 pid … · <kind 标签> · 已运行 …`，下面依次是判定依据、源 Claude 或所属 Claude、启动时刻与 cwd、会话记录（`~/.claude/projects/` 下的 jsonl 及其最后活动时刻）、启动它的工具调用（仅长驻）、组内成员。按 kind 标签定建议：

| kind 标签 | 建议 |
|---|---|
| 脱离后仍在跑的进程（逃逸）+ 源 Claude 进程已退出 | 清理候选。会话记录的「最后活动」早于今天、cwd 是临时目录或已删的 worktree，更倾向清理 |
| 脱离后仍在跑的进程（逃逸）+ 源 Claude 进程仍在 | 多半是那个会话有意 `nohup` 起的服务，正在用。列给用户，默认不清 |
| 插件 hook 拉起的常驻进程（`CLAUDE_PLUGIN_ROOT`） | 插件有意常驻（如某插件的 web daemon）。告诉用户是哪个插件的，按该插件自己的停止方式处理；源会话已退出且端口无人用时才作清理候选 |
| agent-browser / Chrome for Testing | 不 kill：`agent-browser close --all` 后跑 `agent-browser doctor`。直接 kill Chrome 会留下 daemon 与 sidecar 文件；CLI 已卸载时才按 pid 清，且只清命令行含 `chrome-for-testing` 或 `agent-browser` 路径的进程 |
| GUI 应用（.app） | 不清。这是在 Claude 里用 `code .` 一类命令拉起的应用，用户多半正在用 |
| Bash/Monitor 工具拉起的任务（长驻） | 会话标「本会话」：先 `TaskList`，句柄还在就 `TaskStop`，不走 kill。别的会话的：「启动它的工具调用」一行写明是 `Bash` 加 `run_in_background`、前台 `Bash` 还是 `Monitor`，前台 Bash 跑满门槛多半是那个会话正等着的长命令，默认不清 |

判定依据里带「弱信号」或「推断」字样的组，向用户转述时原样带上这两个字。

### 3. 把清单给用户，等逐个点名

每组给：组根 pid、包装 shell 里的用户命令（没有包装 shell 就给组根命令行）、已运行时长、启动时刻（带时区）、cwd、监听端口、判定依据、上一步的建议。让用户按 pid 逐个点名要清理的组。「全清」「都杀了」这类不点名的答复，回一句列出将清理的 pid 请用户确认，再执行。

命令行可能带 token、cookie、内部地址，清单只给本地用户看，不贴到工单、群消息等外部系统。

### 4. 清理（仅限用户当轮点名的 pid）

以子代理身份运行时，到第 3 步为止：清单写进回执交父代理，kill 由主会话在用户点名后执行。

```bash
# ① 核对身份：pid 在列清单与点名之间可能已被复用，命令行与已运行时长要对得上清单
ps -o pid=,etime=,args= -p <pid,...>

# ② 先 SIGTERM，给服务优雅退出的机会；组内成员一起点名时，从组根开始一并发
kill -TERM <pid> ...
sleep 5

# ③ 还在的才 SIGKILL
ps -o pid= -p <pid,...> && kill -KILL <仍在的 pid> ...

# ④ 复扫，确认这些组已不在、端口已释放
python3 <Base directory>/scripts/find_bg_procs.py
```

逃逸组的成员共享一个组长已退出的进程组时，按 pid 逐个发信号，不用 `kill -- -<pgid>`：进程组里可能有清单外的进程。

Java 服务常不理 SIGTERM，等满 5 秒仍在就进入第 ③ 步。

## 不动的进程

- Claude 进程本身（`claude`、`claude daemon`、`bg-pty-host`、`bg-spare`、`~/.local/share/claude/versions/*`），以及组件类。
- 用户终端手动起的服务、系统级 daemon（brew services、launchctl 加载的、Docker、IDE 后台进程）、别的用户与 root 的进程。用户点名清单外的进程时，先确认那是他自己的、知道后果，再按第 4 步执行。

## 已知盲区

- macOS 上 Apple 自带的二进制（`/bin`、`/usr/bin` 下的 `zsh`、`sleep`、`tail` 等）用 `ps -E` 读不到环境变量。这类进程单独逃逸、又没有带标记的祖先或同进程组成员时，脚本漏检。用户怀疑有漏网的，用 `ps -A -o pid,ppid,pgid,etime,args | awk '$2==1'` 手查，结论标「推断」。
- Linux / WSL 分支（`/proc/<pid>/environ`、`ss`）按 procps 语法写成，未在真机实测；首次在 Linux 上用时，先拿 `--json` 的输出与 `ps -ef --forest` 对一遍。
- 每条判据的本机实测命令与输出摘要见 [references/signals.md](references/signals.md)。脚本结果与 `ps` 手查对不上，或要在新平台、新版 Claude Code 上判断脚本是否还可信时读它。
