#!/usr/bin/env python3
"""find_bg_procs.py 的纯函数回归用例（纯离线，不读本机进程表、不发任何信号）。

覆盖解析（ps / lsof / ss / 环境变量）与分类判据（逃逸 / 未逃逸长驻 / Claude 组件 / 不归本 skill 管）。
进程表全部手工构造，形状照 2026-10-29 本机 macOS 实测的进程树取样。

跑法：python3 plugins/devkit-tool/skills/orphan-process-cleaner/tests/find_bg_procs.test.py
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "..", "scripts", "find_bg_procs.py")
spec = importlib.util.spec_from_file_location("find_bg_procs", os.path.abspath(TARGET))
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)

FAILED = []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n          期望 {want!r}\n          实得 {got!r}")
        FAILED.append(label)


print("\n[1] 时长解析")
check("mm:ss", fb.parse_etime("05:03"), 303)
check("hh:mm:ss", fb.parse_etime("12:00:00"), 43200)
check("dd-hh:mm:ss", fb.parse_etime("1-02:03:04"), 93784)
check("--min-age 10m", fb.parse_age_arg("10m"), 600)
check("--min-age 纯数字按秒", fb.parse_age_arg("600"), 600)
check("--min-age 2h", fb.parse_age_arg("2h"), 7200)
try:
    fb.parse_age_arg("10 分钟")
    check("--min-age 非法值报错", "未报错", "ValueError")
except ValueError:
    check("--min-age 非法值报错", "ValueError", "ValueError")

print("\n[2] ps 行解析")
check("args 含空格保留原样",
      fb.parse_ps_line("  67697 67694 67694   501   24:01 /usr/bin/python3 /a b/listen.py --x 1"),
      {"pid": 67697, "ppid": 67694, "pgid": 67694, "uid": 501, "age": 1441, "args": "/usr/bin/python3 /a b/listen.py --x 1"})
check("字段不足返回 None", fb.parse_ps_line("123 1"), None)

print("\n[3] 环境变量解析：只留白名单，token 类不出现")
env = fb.parse_env_suffix("CLAUDECODE=1 FOO=bar CLAUDE_PROJECT_DIR=/a b/c CLAUDE_CODE_MESSAGING_TOKEN=secret CLAUDE_PID=24922")
check("macOS ps -E 后缀", env, {"CLAUDECODE": "1", "CLAUDE_PROJECT_DIR": "/a b/c", "CLAUDE_PID": "24922"})
check("Linux /proc/<pid>/environ",
      fb.parse_environ_bytes(b"PATH=/bin\0CLAUDECODE=1\0CLAUDE_CODE_SESSION_ID=abc\0CLAUDE_CODE_MESSAGING_TOKEN=x\0"),
      {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "abc"})
check("源 Claude pid：CLAUDE_PID 优先", fb.claude_pid_from_env({"CLAUDE_PID": "7", "CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/cc-socks/8.sock"}), 7)
check("源 Claude pid：退回 messaging socket", fb.claude_pid_from_env({"CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/cc-socks/40190.sock"}), 40190)
check("源 Claude pid：都没有", fb.claude_pid_from_env({}), None)

print("\n[4] lsof / ss 解析")
check("lsof -Fpn 监听端口（同端口 v4/v6 去重）",
      fb.parse_lsof_fields("p98678\nf20\nn127.0.0.1:8765\np704\nf9\nn*:7000\nf10\nn*:7000\n"),
      {98678: ["127.0.0.1:8765"], 704: ["*:7000"]})
check("lsof -d cwd -Fpn", fb.parse_lsof_fields("p40429\nfcwd\nn/Users/u/w\n"), {40429: ["/Users/u/w"]})
check("ss -ltnpH",
      fb.parse_ss_listen('LISTEN 0 511 0.0.0.0:5173 0.0.0.0:* users:(("node",pid=4242,fd=21))\n'),
      {4242: ["0.0.0.0:5173"]})

print("\n[5] 是不是 Claude 进程")
for args, want in [
    ("claude --dangerously-skip-permissions", True),
    ("claude bg-spare --bg-spare /tmp/cc-daemon-501/x/spare/a.claim.sock", True),
    ("/Users/u/.local/bin/claude daemon run --json-path /Users/u/.claude/daemon.json", True),
    ("/Users/u/.local/share/claude/versions/2.1.312 --session-id ddc0", True),
    ("/Users/u/.local/share/claude/ClaudeCode.app/Contents/MacOS/claude --bg-pty-host /tmp/x.sock", True),
    ("node /usr/lib/node_modules/@anthropic-ai/claude-code/cli.js", True),
    ("node server.js --name claude-proxy", False),
    ("python3 /x/claude_helper.py", False),
    ("", False),
]:
    check(f"{args[:50]!r} → {want}", fb.is_claude_process(args), want)

print("\n[6] 包装 shell 里取用户命令")
W = ("/bin/zsh -c source /Users/u/.claude/shell-snapshots/snapshot-zsh-1-a.sh 2>/dev/null || true && "
     "eval 'npm run dev -- --port 5173 && echo '\\''ok'\\''' < /dev/null && pwd -P >| /tmp/claude-94ff-cwd")
check("还原 '\\'' 转义", fb.wrapper_command(W), "npm run dev -- --port 5173 && echo 'ok'")
check("非包装 shell 返回 None", fb.wrapper_command("node server.js"), None)


# ------------------------------------------------------------------ 分类
def P(pid, ppid, args, age=3600, uid=501, pgid=None, env=None, cwd=None):
    return {"pid": pid, "ppid": ppid, "pgid": pgid if pgid is not None else pid, "uid": uid, "age": age,
            "args": args, "env": env or {}, "cwd": cwd, "ports": []}


SNAP = "/bin/zsh -c source /Users/u/.claude/shell-snapshots/snapshot-zsh-1-a.sh && eval '{}' < /dev/null"
CC = {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "3b7d804c-40ae-48a7-9be0-647f038aae68"}
rows = [
    P(1, 0, "/sbin/launchd", uid=0, age=10**6),
    P(40, 1, "login -pf u", uid=0, age=10**5),
    P(50, 40, "-zsh", age=10**5),                                                   # 用户终端
    P(100, 50, "claude --dangerously-skip-permissions", age=50000),                  # 活着的 Claude
    P(200, 100, SNAP.format("npm run dev"), age=3600, env=CC),                       # 未逃逸长驻：包装 shell
    P(201, 200, "node node_modules/.bin/vite", age=3600, pgid=200, env=CC),
    P(210, 100, SNAP.format("pytest -x"), age=30, env=CC),                           # 包装 shell，未满门槛
    P(220, 100, "node /Users/u/.claude/plugins/cache/x/mcp/index.mjs", env=CC),      # Claude 组件：MCP
    P(300, 1, "java -jar app.jar", age=7200, env=dict(CC, CLAUDE_PID="999")),        # 逃逸，源 Claude 已退出
    P(301, 300, "/bin/zsh -c ./watch.sh", age=7200, pgid=300),                       # 系统二进制读不到环境，靠祖先
    P(400, 1, "node server.js", age=900, pgid=390, env=dict(CC, CLAUDE_PID="100")),  # 逃逸，源 Claude 仍在
    P(401, 1, "tail -f /tmp/x.log", age=900, pgid=390),                              # 同进程组兄弟，读不到环境
    P(500, 1, "python3 -m http.server", age=4000, env=dict(CC, CLAUDE_PID="60")),    # 源 pid 被复用
    P(60, 1, "/System/Library/CoreServices/Finder.app/Contents/MacOS/Finder", age=100),
    P(600, 1, "/opt/homebrew/opt/redis/bin/redis-server 127.0.0.1:6379", age=10**5),  # brew services，无标记
    P(700, 50, "node my-own-server.js", age=10**4),                                  # 用户终端手动起的
    P(800, 1, "/Applications/Visual Studio Code.app/Contents/MacOS/Code", env=CC),   # Claude 里 `code .` 拉起的 GUI
    P(900, 1, "node root-thing.js", uid=0, env=CC),                                  # 别的用户，跳过
    P(1000, 1, "node dev.js", pgid=995, cwd="/r/.claude/worktrees/feat-x"),          # 弱信号
    P(1100, 100, SNAP.format("python3 find_bg_procs.py"), age=5000, env=CC),         # 脚本自身祖先，排除
    P(1200, 1, "node /Users/u/.claude/plugins/cache/some-market/some-plugin/1.2.3/scripts/web-daemon/launcher.js",
      env=dict(CC, CLAUDE_PLUGIN_ROOT="/Users/u/.claude/plugins/cache/some-market/some-plugin/1.2.3")),
    P(1300, 1, "node /Users/u/.agent-browser/daemon.js", env=CC),
    P(1400, 1, "sleep 600", pgid=1395),                                              # 孤零零的系统二进制：已知漏检
    P(1500, 1500, "weird", age=10),                                                  # ppid 指向自己，防死循环
]
procs = {r["pid"]: r for r in rows}
res = fb.classify(procs, 501, exclude={1100}, min_age=600)
by_root = {g["root"]: g for cat in res.values() for g in cat}

print("\n[7] 分类：未逃逸长驻")
check("包装 shell 归组，含其子进程", [(g["root"], g["members"]) for g in res["resident"]], [(200, [200, 201])])
check("未满 --min-age 的不列", 210 in by_root, False)
check("脚本自身祖先被排除", 1100 in by_root, False)
check("所属 Claude 是父链上的 100", by_root[200]["live_claude"], 100)
check("会话 id 取自环境", by_root[200]["session_id"], CC["CLAUDE_CODE_SESSION_ID"])

print("\n[8] 分类：Claude 组件")
check("MCP server 归组件", [g["root"] for g in res["component"]], [220])
check("组件 kind", by_root[220]["kind"], "component")

print("\n[9] 分类：逃逸")
esc = {g["root"]: g for g in res["escaped"]}
check("逃逸组集合", sorted(esc), [300, 400, 500, 800, 1000, 1200, 1300])
check("祖先已逃逸的子进程并入同组", esc[300]["members"], [300, 301])
check("源 Claude 已退出", esc[300]["origin_claude"], {"pid": 999, "state": "dead"})
check("同进程组（组长已死）合并", esc[400]["members"], [400, 401])
check("源 Claude 仍在", esc[400]["origin_claude"], {"pid": 100, "state": "alive"})
check("非组根成员的依据单列（同进程组）", any("同属进程组 390" in x for x in esc[400]["member_basis"].get(401, [])), True)
check("非组根成员的依据单列（祖先）", any("祖先 pid 300" in x for x in esc[300]["member_basis"].get(301, [])), True)
check("源 pid 被非 Claude 进程复用", esc[500]["origin_claude"], {"pid": 60, "state": "reused"})
check("GUI 应用单独标注", esc[800]["kind"], "gui-app")
check("cwd 在 worktree 下是弱信号", any("弱信号" in b for b in esc[1000]["basis"]), True)
check("插件 hook 拉起的常驻进程", esc[1200]["kind"], "plugin-daemon")
check("agent-browser 单独标注", esc[1300]["kind"], "agent-browser")
check("普通逃逸进程 kind", esc[300]["kind"], "detached")

print("\n[10] 不归本 skill 管的进程一个都不列")
for pid, why in [(600, "brew services 起的 daemon"), (700, "用户终端手动起的服务"), (900, "别的用户的进程"),
                 (1400, "无任何标记的孤立系统二进制"), (60, "Finder"), (100, "Claude 自身"), (1500, "自指 ppid")]:
    check(f"{why}（pid {pid}）不出现", pid in {m for cat in res.values() for g in cat for m in g["members"]}, False)

print("\n[11] 源 pid 指向更年轻的 Claude 也算复用")
procs2 = {r["pid"]: r for r in [P(1, 0, "/sbin/launchd", uid=0), P(70, 1, "claude", age=10),
                                P(71, 1, "node a.js", age=5000, env=dict(CC, CLAUDE_PID="70"))]}
check("Claude 比被追溯进程晚启动 → reused",
      fb.classify(procs2, 501, set(), 600)["escaped"][0]["origin_claude"], {"pid": 70, "state": "reused"})

if FAILED:
    print(f"\n共 {len(FAILED)} 条失败")
    sys.exit(1)
print("\n全部通过")
