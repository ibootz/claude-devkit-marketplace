#!/usr/bin/env python3
"""列出 Claude Code 拉起、仍在跑的后台进程，分「逃逸」与「未逃逸长驻」两类。只读，不发任何信号。

用法：
    python3 find_bg_procs.py                 # 默认：逃逸全列，未逃逸只列已跑满 10 分钟的
    python3 find_bg_procs.py --min-age 30m   # 未逃逸的时长门槛（s/m/h/d 后缀，纯数字按秒）
    python3 find_bg_procs.py --all           # 另列 Claude 组件（MCP server、插件运行时等）
    python3 find_bg_procs.py --json          # 结构化输出
    python3 find_bg_procs.py --full          # 命令行不截断
    python3 find_bg_procs.py --no-transcript # 不去会话 jsonl 里反查启动它的工具调用

平台：macOS、Linux（含 WSL）。Windows 不支持（没有 ps / lsof / /proc），直接退出码 2。

判据（每条在 SKILL.md「判据与实测」一节有本机实测记录）：
  - Claude 进程：argv[0] 的 basename 是 claude，或路径含 /claude/versions/、ClaudeCode.app/、
    @anthropic-ai/claude-code。
  - Claude 拉起的标记：进程环境含 CLAUDECODE=1 / CLAUDE_CODE_SESSION_ID / CLAUDE_PID；或自身/祖先
    的命令行含 shell-snapshots/snapshot-（Bash 工具与 Monitor 工具的包装 shell）。
  - 逃逸：带上述标记，但父进程链上已没有活着的 Claude 进程。
  - 未逃逸长驻：父进程链上有活着的 Claude 进程，且经由包装 shell 拉起，包装 shell 已跑满 --min-age。
  - Claude 组件：父链上有活着的 Claude，但不经包装 shell（MCP server、hook 拉起的常驻进程等）。
只看当前用户的进程；root 进程读不到环境，也不归本脚本管。
"""

import argparse
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys

SNAPSHOT_MARK = "shell-snapshots/snapshot-"
ENV_KEYS = (
    "CLAUDECODE",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_PID",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_PLUGIN_ROOT",
)
CLAUDE_PATH_MARKS = ("/claude/versions/", "ClaudeCode.app/", "@anthropic-ai/claude-code")
BROWSER_RE = re.compile(r"agent-browser|chrome-for-testing|Chrome for Testing", re.I)


# ---------------------------------------------------------------- 纯函数（单测覆盖）


def parse_etime(s):
    """ps 的 etime（[[dd-]hh:]mm:ss）→ 秒。macOS 与 Linux 格式相同。"""
    s = s.strip()
    days = 0
    if "-" in s:
        d, s = s.split("-", 1)
        days = int(d)
    parts = [int(x) for x in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, sec = parts
    return days * 86400 + h * 3600 + m * 60 + sec


def parse_age_arg(s):
    """'10m' / '2h' / '1d' / '600' → 秒。"""
    m = re.fullmatch(r"(\d+)([smhd]?)", s.strip())
    if not m:
        raise ValueError(f"时长格式不对：{s!r}，应形如 600、10m、2h、1d")
    n, unit = int(m.group(1)), m.group(2) or "s"
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def fmt_age(sec):
    d, rem = divmod(int(sec), 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}天{h}小时"
    if h:
        return f"{h}小时{m}分"
    return f"{m}分"


def parse_ps_line(line):
    """`ps -A -ww -o pid=,ppid=,pgid=,uid=,etime=,args=` 的一行 → dict；空行或格式不对返回 None。"""
    parts = line.strip().split(None, 5)
    if len(parts) < 5:
        return None
    try:
        pid, ppid, pgid, uid = (int(x) for x in parts[:4])
        age = parse_etime(parts[4])
    except ValueError:
        return None
    return {"pid": pid, "ppid": ppid, "pgid": pgid, "uid": uid, "age": age,
            "args": parts[5] if len(parts) > 5 else ""}


def parse_env_suffix(suffix, keys=ENV_KEYS):
    """macOS `ps -E` 把环境变量用空格接在命令行后面；拆成 dict，只留 keys 里的键（不碰 token 类变量）。"""
    out = {}
    for tok in re.split(r" (?=[A-Za-z_][A-Za-z0-9_]*=)", " " + suffix):
        if "=" not in tok:
            continue
        k, v = tok.strip().split("=", 1)
        if k in keys:
            out[k] = v.strip()
    return out


def parse_environ_bytes(data, keys=ENV_KEYS):
    """Linux /proc/<pid>/environ（NUL 分隔）→ dict，只留 keys。"""
    out = {}
    for item in data.split(b"\0"):
        if b"=" not in item:
            continue
        k, v = item.split(b"=", 1)
        k = k.decode("utf-8", "replace")
        if k in keys:
            out[k] = v.decode("utf-8", "replace")
    return out


def parse_lsof_fields(text):
    """`lsof -F pn` 的输出 → {pid: [name, ...]}。cwd 与监听端口两处共用。"""
    out, pid = {}, None
    for line in text.splitlines():
        if not line:
            continue
        tag, val = line[0], line[1:]
        if tag == "p":
            pid = int(val)
            out.setdefault(pid, [])
        elif tag == "n" and pid is not None and val not in out[pid]:
            out[pid].append(val)
    return out


def parse_ss_listen(text):
    """Linux `ss -ltnpH` → {pid: [addr:port, ...]}（lsof 不在时的后备）。"""
    out = {}
    for line in text.splitlines():
        cols = line.split()
        if len(cols) < 5:
            continue
        local = cols[3]
        for pid in re.findall(r"pid=(\d+)", line):
            lst = out.setdefault(int(pid), [])
            if local not in lst:
                lst.append(local)
    return out


def is_claude_process(args):
    if not args:
        return False
    argv0 = args.split(None, 1)[0]
    if os.path.basename(argv0) == "claude":
        return True
    head = args[:300]
    return any(mark in head for mark in CLAUDE_PATH_MARKS)


def wrapper_command(args):
    """从 Bash / Monitor 工具的包装 shell 命令行里取出用户命令（`eval '...'` 里那段）。"""
    m = re.search(r"\beval '(.*)' < /dev/null", args, re.S)
    if not m:
        return None
    return m.group(1).replace("'\\''", "'")


def claude_pid_from_env(env):
    if env.get("CLAUDE_PID", "").isdigit():
        return int(env["CLAUDE_PID"])
    m = re.search(r"/(\d+)\.sock$", env.get("CLAUDE_CODE_MESSAGING_SOCKET", ""))
    return int(m.group(1)) if m else None


def ancestors(procs, pid):
    """pid 的父进程链（不含自身），自下而上，到 pid 1 或断链为止。"""
    chain, seen = [], {pid}
    cur = procs.get(pid)
    while cur and cur["ppid"] not in (0, 1) and cur["ppid"] not in seen:
        seen.add(cur["ppid"])
        cur = procs.get(cur["ppid"])
        if cur is None:
            break
        chain.append(cur["pid"])
    return chain


def classify(procs, my_uid, exclude, min_age):
    """把进程表分成 escaped / resident / component 三类，每类按「组」给出。

    procs: {pid: {pid, ppid, pgid, uid, age, args, env(dict), cwd(str|None)}}，必须含全部进程（父链要用）
    exclude: 不参与判定的 pid 集合（脚本自身及其祖先）
    返回 {"escaped": [group], "resident": [group], "component": [group]}；
    group = {cat, root, members, basis, session_id, project_dir, live_claude, origin_claude, kind}
    """
    marks, pending = {}, []
    for pid, p in procs.items():
        if p["uid"] != my_uid or pid in exclude or pid == 1 or is_claude_process(p["args"]):
            continue
        chain = ancestors(procs, pid)
        live_claude = next((a for a in chain if is_claude_process(procs[a]["args"])), None)
        upto = chain[: chain.index(live_claude)] if live_claude else chain
        wrapper = pid if SNAPSHOT_MARK in p["args"] else next(
            (a for a in upto if SNAPSHOT_MARK in procs[a]["args"]), None
        )
        if wrapper is not None and wrapper in exclude:
            continue  # 与本脚本同一次工具调用里的兄弟进程（管道下游等）
        env = p.get("env") or {}
        basis = []
        if env.get("CLAUDECODE") == "1":
            basis.append("环境变量 CLAUDECODE=1")
        if env.get("CLAUDE_CODE_SESSION_ID"):
            basis.append("环境变量 CLAUDE_CODE_SESSION_ID")
        if wrapper is not None:
            basis.append(f"经由 Claude 包装 shell（pid {wrapper}，命令行含 {SNAPSHOT_MARK}）")
        if live_claude:
            cat = "resident" if wrapper is not None else "component"
            basis.insert(0, f"父进程链上有活着的 Claude（pid {live_claude}）")
        elif basis:
            cat = "escaped"
            basis.insert(0, "父进程链上已没有活着的 Claude 进程")
        else:
            pending.append((len(chain), pid, chain))
            continue
        marks[pid] = {"cat": cat, "wrapper": wrapper, "live_claude": live_claude, "basis": basis}

    # 第二轮：自身读不到 Claude 标记的进程（macOS 上 /bin、/usr/bin 的系统二进制 ps -E 读不到环境），
    # 借祖先或同进程组成员的标记判定。按父链深度从浅到深处理，祖先先定。
    escaped_pgids = {}
    for pid, m in marks.items():
        if m["cat"] == "escaped":
            escaped_pgids.setdefault(procs[pid]["pgid"], pid)
    for _, pid, chain in sorted(pending):
        p = procs[pid]
        anc = next((a for a in chain if marks.get(a, {}).get("cat") == "escaped"), None)
        if anc is not None:
            basis = ["父进程链上已没有活着的 Claude 进程", f"祖先 pid {anc} 已判为逃逸（自身环境读不到 Claude 标记）"]
        elif p["ppid"] == 1 and p["pgid"] != pid and p["pgid"] in escaped_pgids:
            basis = ["父进程链上已没有活着的 Claude 进程",
                     f"与带 Claude 标记的 pid {escaped_pgids[p['pgid']]} 同属进程组 {p['pgid']}（自身环境读不到 Claude 标记）"]
        elif p["ppid"] == 1 and "/.claude/worktrees/" in (p.get("cwd") or ""):
            basis = ["父进程链上已没有活着的 Claude 进程",
                     "弱信号：已被 init/launchd 收养且 cwd 在 .claude/worktrees/ 下，环境里无 Claude 标记"]
        else:
            continue
        marks[pid] = {"cat": "escaped", "wrapper": None, "live_claude": None, "basis": basis}
        escaped_pgids.setdefault(p["pgid"], pid)

    # 分组：未逃逸与组件按包装 shell / 顶层进程归组；逃逸的先沿父链归到顶，组长已死的同进程组再合并
    # （同一次 Bash 调用里 & 出去的几个进程共享包装 shell 的 pgid，包装 shell 退出后各自被收养）。
    groups = {}
    for pid, m in marks.items():
        top = pid
        while procs[top]["ppid"] in marks and marks[procs[top]["ppid"]]["cat"] == m["cat"]:
            top = procs[top]["ppid"]
        if m["cat"] == "resident":
            key = m["wrapper"]
        elif m["cat"] == "escaped" and procs[top]["pgid"] != top and procs[top]["pgid"] not in procs:
            key = ("pgid", procs[top]["pgid"])
        else:
            key = top
        g = groups.setdefault((m["cat"], key), {"cat": m["cat"], "members": []})
        g["members"].append(pid)

    # 包装 shell 是 /bin/zsh，macOS 上读不到它的环境；会话 id 退而取同一 Claude 进程其它子进程（MCP server 等）
    # 环境里记的，取最晚启动的那个（/clear 后会话 id 会换，越晚启动越接近当前会话）。
    sid_by_claude = {}
    for q in sorted(procs.values(), key=lambda q: -q["age"]):
        e = q.get("env") or {}
        cp = claude_pid_from_env(e)
        if cp and e.get("CLAUDE_CODE_SESSION_ID"):
            sid_by_claude[cp] = e["CLAUDE_CODE_SESSION_ID"]

    out = {"escaped": [], "resident": [], "component": []}
    for (cat, _), g in groups.items():
        mem = set(g["members"])
        g["members"].sort()
        tops = [m for m in g["members"] if procs[m]["ppid"] not in mem]
        g["root"] = max(tops, key=lambda m: (procs[m]["age"], -m))
        rp = procs[g["root"]]
        if cat == "resident" and rp["age"] < min_age:
            continue
        g["basis"] = marks[g["root"]]["basis"]
        g["member_basis"] = {m: marks[m]["basis"] for m in g["members"]
                             if m != g["root"] and marks[m]["basis"][1:] != g["basis"][1:]
                             and not marks[m]["basis"][-1].startswith("经由")}
        envs = [procs[m].get("env") or {} for m in g["members"]]
        g["session_id"] = next((e["CLAUDE_CODE_SESSION_ID"] for e in envs if e.get("CLAUDE_CODE_SESSION_ID")), None)
        g["session_inferred"] = False
        lc = marks[g["root"]]["live_claude"]
        if g["session_id"] is None and lc in sid_by_claude:
            g["session_id"], g["session_inferred"] = sid_by_claude[lc], True
        g["project_dir"] = next((e["CLAUDE_PROJECT_DIR"] for e in envs if e.get("CLAUDE_PROJECT_DIR")), None)
        g["live_claude"] = marks[g["root"]]["live_claude"]
        cpid = next((claude_pid_from_env(e) for e in envs if claude_pid_from_env(e)), None)
        g["origin_claude"] = origin_status(procs, rp, cpid)
        g["kind"] = kind_of(procs, g)
        out[cat].append(g)
    for cat in out:
        out[cat].sort(key=lambda g: -procs[g["root"]]["age"])
    return out


def origin_status(procs, root_proc, cpid):
    """环境里记的源 Claude pid 现在的状态：dead / alive / reused（pid 被别的进程复用）/ unknown。"""
    if cpid is None:
        return {"pid": None, "state": "unknown"}
    cp = procs.get(cpid)
    if cp is None:
        return {"pid": cpid, "state": "dead"}
    if not is_claude_process(cp["args"]) or cp["age"] < root_proc["age"]:
        return {"pid": cpid, "state": "reused"}
    return {"pid": cpid, "state": "alive"}


def kind_of(procs, g):
    members = [procs[m] for m in g["members"]]
    root = procs[g["root"]]
    if g["cat"] == "component":
        return "component"
    if any(BROWSER_RE.search(m["args"]) for m in members):
        return "agent-browser"
    if any((m.get("env") or {}).get("CLAUDE_PLUGIN_ROOT") and "/.claude/plugins/" in m["args"] for m in members):
        return "plugin-daemon"
    if ".app/Contents/" in root["args"]:
        return "gui-app"
    if g["cat"] == "resident":
        return "tool-task"
    return "detached"


# ---------------------------------------------------------------- 采集（读本机）


def run(argv):
    exe = shutil.which(argv[0])
    if not exe:
        return None
    try:
        r = subprocess.run([exe] + argv[1:], capture_output=True, text=True, errors="replace", timeout=30,
                           env=dict(os.environ, LC_ALL="C"))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout


def collect():
    text = run(["ps", "-A", "-ww", "-o", "pid=,ppid=,pgid=,uid=,etime=,args="])
    if text is None:
        sys.exit("找不到 ps 命令")
    procs = {}
    for line in text.splitlines():
        p = parse_ps_line(line)
        if p:
            p["env"], p["cwd"], p["ports"] = {}, None, []
            procs[p["pid"]] = p
    my_uid = os.getuid()
    if sys.platform == "darwin":
        etext = run(["ps", "-E", "-ww", "-U", str(my_uid), "-o", "pid=,command="]) or ""
        for line in etext.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) < 2 or not parts[0].isdigit():
                continue
            p = procs.get(int(parts[0]))
            if not p:
                continue
            full = parts[1]
            suffix = full[len(p["args"]):] if full.startswith(p["args"]) else full
            p["env"] = parse_env_suffix(suffix)
    else:
        for pid, p in procs.items():
            if p["uid"] != my_uid:
                continue
            try:
                with open(f"/proc/{pid}/environ", "rb") as f:
                    p["env"] = parse_environ_bytes(f.read())
            except OSError:
                pass
    return procs, my_uid


def fill_cwd(procs, pids):
    pids = sorted(set(pids))
    if not pids:
        return
    if sys.platform.startswith("linux"):
        for pid in pids:
            try:
                procs[pid]["cwd"] = os.readlink(f"/proc/{pid}/cwd")
            except OSError:
                pass
        return
    text = run(["lsof", "-a", "-d", "cwd", "-Fpn", "-p", ",".join(map(str, pids))]) or ""
    for pid, names in parse_lsof_fields(text).items():
        if pid in procs and names:
            procs[pid]["cwd"] = names[0]


def fill_ports(procs):
    text = run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"])
    table = parse_lsof_fields(text) if text else parse_ss_listen(run(["ss", "-ltnpH"]) or "")
    for pid, ports in table.items():
        if pid in procs:
            procs[pid]["ports"] = ports


def transcript_of(session_id):
    if not session_id or not re.fullmatch(r"[0-9a-fA-F-]{8,}", session_id):
        return None
    hits = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{session_id}.jsonl"))
    if not hits:
        return None
    path = hits[0]
    return {"path": path, "last_active": dt.datetime.fromtimestamp(os.path.getmtime(path)).astimezone()}


def match_tool_call(path, command):
    """在会话 jsonl（含 <会话>/subagents/*.jsonl，子代理的工具调用记在那里）里找 input.command
    与包装 shell 里的命令完全相同的那次工具调用，取最后一次。"""
    if not path or not command:
        return None
    found = None
    for f in [path] + sorted(glob.glob(os.path.join(path[: -len(".jsonl")], "subagents", "*.jsonl"))):
        hit = _match_in_file(f, command)
        if hit:
            hit["file"] = f
            found = hit
    return found


def _match_in_file(path, command):
    needle = json.dumps(command.strip()[:30], ensure_ascii=False)[1:-1]
    found = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"tool_use"' not in line or needle not in line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                for c in (obj.get("message") or {}).get("content") or []:
                    if not isinstance(c, dict) or c.get("type") != "tool_use":
                        continue
                    inp = c.get("input") or {}
                    if (inp.get("command") or "").strip() == command.strip():
                        found = {"tool": c.get("name"), "run_in_background": bool(inp.get("run_in_background")),
                                 "description": inp.get("description"), "timestamp": local_time(obj.get("timestamp"))}
    except OSError:
        return None
    return found


def local_time(iso):
    """jsonl 里的 UTC 时间戳（...Z）→ 本地时区带偏移的可读时刻；解析不了原样返回。"""
    if not iso:
        return None
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return t.astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def self_chain(procs):
    me = os.getpid()
    return {me} | set(ancestors(procs, me))


# ---------------------------------------------------------------- 输出


def start_at(age):
    return (dt.datetime.now().astimezone() - dt.timedelta(seconds=age)).strftime("%Y-%m-%d %H:%M:%S %z")


KIND_LABEL = {
    "tool-task": "Bash/Monitor 工具拉起的任务",
    "detached": "脱离后仍在跑的进程",
    "plugin-daemon": "插件 hook 拉起的常驻进程（CLAUDE_PLUGIN_ROOT）",
    "agent-browser": "agent-browser / Chrome for Testing",
    "gui-app": "GUI 应用（.app）",
    "component": "Claude 组件（MCP server、状态栏、hook 子进程等）",
}
ORIGIN_LABEL = {
    "dead": "源 Claude 进程已退出",
    "alive": "源 Claude 进程仍在，但本进程已脱离它的父链（nohup / setsid / & 后包装 shell 退出一类）",
    "reused": "源 Claude pid 已被别的进程复用，按已退出处理",
    "unknown": "环境里没有源 Claude pid",
}


def render_group(procs, g, full, my_session):
    lines = []
    root = procs[g["root"]]
    sess = g["session_id"] or "未知"
    if g.get("session_inferred"):
        sess += "（推断：取自同一 Claude 进程的其它子进程）"
    if g["session_id"] and g["session_id"] == my_session:
        sess += "（本会话）"
    lines.append(f"■ 组根 pid {root['pid']} · {KIND_LABEL[g['kind']]} · 已运行 {fmt_age(root['age'])}")
    lines.append(f"  判定依据：{'；'.join(g['basis'])}")
    o = g["origin_claude"]
    if g["cat"] == "escaped":
        lines.append(f"  源 Claude：{'pid ' + str(o['pid']) if o['pid'] else '—'} · {ORIGIN_LABEL[o['state']]} · 会话 {sess}")
    else:
        lines.append(f"  所属 Claude：pid {g['live_claude']}（父链上，存活） · 会话 {sess}")
    lines.append(f"  启动：{start_at(root['age'])} · cwd：{root.get('cwd') or '未取到'}")
    if g.get("transcript"):
        t = g["transcript"]
        lines.append(f"  会话记录：{t['path']}（最后活动 {t['last_active'].strftime('%Y-%m-%d %H:%M:%S %z')}）")
    if g.get("tool_call"):
        tc = g["tool_call"]
        bg = "，run_in_background" if tc["run_in_background"] else ""
        sub = "（子代理）" if "/subagents/" in tc.get("file", "") else ""
        lines.append(f"  启动它的工具调用{sub}：{tc['tool']}{bg} · {tc.get('description') or ''} · {tc.get('timestamp') or ''}")
    for pid in g["members"]:
        p = procs[pid]
        args = p["args"]
        if pid == g["root"] and wrapper_command(args) is not None:
            args = "[Claude 包装 shell] " + wrapper_command(args)
        cmd = args if full else (args[:200] + ("…" if len(args) > 200 else ""))
        extra = []
        if abs(p["age"] - root["age"]) > 60:
            extra.append(f"启动 {start_at(p['age'])}")
        if p.get("cwd") and p.get("cwd") != root.get("cwd"):
            extra.append(f"cwd {p['cwd']}")
        if p.get("ports"):
            extra.append(f"监听 {', '.join(p['ports'])}")
        lines.append(f"  - pid {pid} ppid {p['ppid']}" + "".join(f" · {e}" for e in extra))
        if pid in g.get("member_basis", {}):
            lines.append(f"    依据：{g['member_basis'][pid][-1]}")
        lines.append(f"    {cmd}")
    return "\n".join(lines)


def to_json(procs, g):
    def proc(pid):
        p = procs[pid]
        return {"pid": pid, "ppid": p["ppid"], "start": start_at(p["age"]), "age_sec": p["age"],
                "cwd": p.get("cwd"), "ports": p.get("ports") or [], "args": p["args"]}
    t = g.get("transcript")
    return {"category": g["cat"], "kind": g["kind"], "root": g["root"], "basis": g["basis"],
            "origin_claude": g["origin_claude"], "live_claude": g["live_claude"], "session_id": g["session_id"],
            "session_inferred": g.get("session_inferred", False),
            "project_dir": g["project_dir"],
            "transcript": {"path": t["path"], "last_active": t["last_active"].isoformat()} if t else None,
            "tool_call": g.get("tool_call"), "members": [proc(m) for m in g["members"]],
            "member_basis": {str(k): v for k, v in g.get("member_basis", {}).items()}}


def main():
    if sys.platform.startswith("win"):
        print("不支持 Windows：本脚本依赖 ps / lsof 或 /proc。WSL 里跑即可。", file=sys.stderr)
        return 2
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="列出 Claude Code 拉起的后台进程（只读）")
    ap.add_argument("--min-age", default="10m", help="未逃逸长驻的时长门槛，默认 10m")
    ap.add_argument("--all", action="store_true", help="另列 Claude 组件（MCP server 等）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--full", action="store_true", help="命令行不截断")
    ap.add_argument("--no-transcript", action="store_true", help="不读会话 jsonl")
    a = ap.parse_args()
    min_age = parse_age_arg(a.min_age)

    procs, my_uid = collect()
    exclude = self_chain(procs)
    orphan_unmarked = [pid for pid, p in procs.items()
                       if p["uid"] == my_uid and p["ppid"] == 1 and not p["env"] and pid not in exclude]
    fill_cwd(procs, orphan_unmarked)
    res = classify(procs, my_uid, exclude, min_age)
    shown = res["escaped"] + res["resident"] + (res["component"] if a.all else [])
    fill_cwd(procs, [m for g in shown for m in g["members"]])
    fill_ports(procs)
    for g in shown:
        if a.no_transcript:
            continue
        g["transcript"] = transcript_of(g["session_id"])
        if g["cat"] == "resident" and g["transcript"]:
            g["tool_call"] = match_tool_call(g["transcript"]["path"], wrapper_command(procs[g["root"]]["args"]))

    my_session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if a.json:
        print(json.dumps({"min_age_sec": min_age,
                          "escaped": [to_json(procs, g) for g in res["escaped"]],
                          "resident": [to_json(procs, g) for g in res["resident"]],
                          "component": [to_json(procs, g) for g in res["component"]] if a.all else len(res["component"])},
                         ensure_ascii=False, indent=2, default=str))
        return 0

    print(f"扫描时刻 {dt.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %z')} · 平台 {sys.platform} · 只读，未发任何信号")
    print(f"\n== 一、逃逸（父链上已没有活着的 Claude）：{len(res['escaped'])} 组")
    for g in res["escaped"]:
        print(render_group(procs, g, a.full, my_session))
    print(f"\n== 二、未逃逸但长驻（Claude 仍在，任务已跑满 {fmt_age(min_age)}）：{len(res['resident'])} 组")
    for g in res["resident"]:
        print(render_group(procs, g, a.full, my_session))
    print(f"\n== 三、Claude 组件（MCP server、hook 常驻进程等，不建议清理）：{len(res['component'])} 组"
          + ("" if a.all else "，加 --all 列出"))
    if a.all:
        for g in res["component"]:
            print(render_group(procs, g, a.full, my_session))
    return 0


if __name__ == "__main__":
    sys.exit(main())
