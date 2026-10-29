# 「是不是 Claude Code 拉起的」各判据的实测记录

实测环境：macOS 26（Darwin 25.5.0），Claude Code 2.1.311 / 2.1.312，原生安装（`~/.local/share/claude/versions/`），2026-10-29。
Linux / WSL 一条都未实测。

| 判据 | 结论 | 脚本里的用法 |
|---|---|---|
| 父进程链上有 Claude 可执行文件 | 可靠（已实测） | 区分逃逸与长驻、组件 |
| 环境变量 `CLAUDECODE=1` / `CLAUDE_CODE_SESSION_ID` / `CLAUDE_PID` | 第三方二进制可靠；Apple 平台二进制读不到（已实测） | 主判据 |
| 包装 shell 命令行含 `shell-snapshots/snapshot-` | 可靠，Bash 与 Monitor 工具都用它（已实测） | 区分长驻与组件；取出用户命令 |
| 同进程组且组长已退出 | 单独用噪声大；与带标记的同组成员合用可靠（已实测） | 补 Apple 二进制读不到环境的缺口 |
| 会话 jsonl 里能对上启动它的工具调用 | 可靠，含子代理的 `subagents/*.jsonl`（已实测） | 报告是哪次工具调用、何时、是否 `run_in_background` |
| cwd 在 `.claude/worktrees/` 下 | 本机没遇到命中实例（未实测命中） | 只作弱信号，限 PPID=1 且无其它标记的进程 |

## 1. Claude 进程长什么样

```bash
LC_ALL=C ps -axo pid=,ppid=,args= | grep -i claude
```

本机见到的形态，脚本 `is_claude_process` 全部覆盖：

- `claude --dangerously-skip-permissions`：终端里的交互会话，argv[0] 的 basename 是 `claude`。
- `/Users/<u>/.local/bin/claude daemon run --json-path ~/.claude/daemon.json ...`：`claude --bg` 的常驻 daemon，PPID=1，属正常形态。
- `claude bg-pty-host ...`、`claude bg-spare ...`：daemon 派生的进程，进程标题被改写，argv[0] 仍是 `claude`。
- `/Users/<u>/.local/share/claude/ClaudeCode.app/Contents/MacOS/claude --bg-pty-host ...`：同上，部分为 PPID=1。
- `/Users/<u>/.local/share/claude/versions/2.1.312 --session-id <id> --fork-session --resume ...`：后台会话本体。

npm 全局安装形态（`node .../@anthropic-ai/claude-code/cli.js`）本机未装，未实测，脚本按路径片段匹配。

## 2. 环境变量

```bash
ps -E -ww -o command= -p <pid> | tr ' ' '\n' | grep '^CLAUDE'
```

- node、python3（asdf 安装与 CommandLineTools 自带的都算）拉起的进程：能读到。Bash 工具拉起的进程带 `CLAUDECODE=1`、`CLAUDE_CODE_SESSION_ID`、`CLAUDE_PID`（等于父链上那个 Claude 进程的 pid，对过 3 例），以及 `CLAUDE_CODE_MESSAGING_SOCKET=/tmp/cc-socks/<claude pid>.sock`。
- 插件 hook 拉起的进程另带 `CLAUDE_PLUGIN_ROOT`、`CLAUDE_PROJECT_DIR`、`CLAUDE_ENV_FILE`（实测 2 个插件 web daemon，PPID=1，`CLAUDE_PID` 指向的进程已不存在）。
- `/bin/zsh`、`/bin/sleep`：输出里只有命令行、没有环境变量。在同一批测试里，同一个父 shell 拉起的 node 与 python 都能读到。推断是 macOS 对 Apple 平台二进制的限制，具体机制没查。
- 环境里还有 `CLAUDE_CODE_MESSAGING_TOKEN`。脚本只按白名单取键，不输出这个值。

Linux 分支读 `/proc/<pid>/environ`（同用户可读，NUL 分隔），未实测。

## 3. 包装 shell

```text
/bin/zsh -c source ~/.claude/shell-snapshots/snapshot-zsh-<ts>-<rand>.sh 2>/dev/null || true && setopt ... && eval '<用户命令>' < /dev/null && pwd -P >| /tmp/claude-<hex>-cwd
```

Bash 工具（前台与 `run_in_background`）和 Monitor 工具的进程都挂在这个 shell 下。它是进程组组长，子孙进程的 pgid 等于它的 pid。用户命令里的单引号写成 `'\''`，脚本取出后还原。

`nohup cmd &` 一类命令执行完后包装 shell 退出，子进程被 launchd 收养（PPID=1），这条标记随之消失，只能靠环境变量或进程组。

## 4. 进程组

在一次 Bash 调用里 `nohup` 起 node、python、`/bin/zsh -c 'sleep …'` 各一个，包装 shell 退出后三者 PPID 都变成 1，pgid 都还是那个已退出的包装 shell 的 pid。其中 zsh 和 sleep 读不到环境，靠同组的 node 带的标记判为逃逸，并归进同一组。

单看「PPID=1 且进程组组长已退出」不行：本机这样的同用户进程有 11 个，大多是 VS Code、Chrome、微信的 `crashpad_handler`，以及 Clash Verge、`op` 这些和 Claude 无关的进程。

同一测试里单独 `nohup sleep 170 &`，没有带标记的同组成员，漏检。这就是 SKILL.md「已知盲区」第一条。

## 5. 会话 jsonl

- `~/.claude/projects/*/<CLAUDE_CODE_SESSION_ID>.jsonl` 按会话 id 用 glob 能找到，文件 mtime 就是会话最后活动时刻。
- 主会话的工具调用记在这个文件里；子代理的记在 `<会话 id>/subagents/agent-*.jsonl`。
- `tool_use.input.command` 与包装 shell 里 `eval '…'` 那段逐字相同。实测 Monitor 1 例，子代理里的 Bash `run_in_background` 1 例。
- 包装 shell 是 `/bin/zsh`，读不到环境，长驻组可能拿不到会话 id。这时取同一 Claude 进程其它子进程（MCP server 等）环境里最晚的那个 `CLAUDE_CODE_SESSION_ID`，输出标「推断」。`/clear` 之后 MCP server 环境里的 id 会不会跟着换，未实测。

## 6. 本机一次实跑（2026-10-29 23:43 +0800）

- 逃逸 3 组，都是某插件 hook 拉起的 web daemon：node `.../scripts/web-daemon/launcher.js`，分别监听 127.0.0.1:8765、8766、8767。其中 2 组的源 Claude 进程已退出（已跑 7 天 13 小时、1 天 8 小时），1 组的源 Claude 进程仍在（才跑 3 分钟）。
- 长驻 1 组：Monitor 工具拉起的某插件监听脚本 `python3 .../listen.py`，带 9 个 CLI 长连接子进程，已跑 24 分钟。会话 jsonl 里对上了那次 Monitor 调用。
- 组件 23 组：MCP server（`npm exec ... mcp`、插件运行时 `index.mjs`）、状态栏 `ccline`、`caffeinate -i -t 300`、状态栏或 hook 发起的 `git`。
- 当前用户有 506 个 PPID=1 的进程，包括 VS Code、ZCode、XPC 服务、Clash Verge 等，除上面 3 组外都没有被列出，没有系统 daemon 被误判。
