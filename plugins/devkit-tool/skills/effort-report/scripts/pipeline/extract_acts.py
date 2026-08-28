# -*- coding: utf-8 -*-
"""提取下钻弹层素材：子代理派发（带时长）、拍板事件、工具动作、文件改动。落 acts.json。"""
import json, os, re, sys
sys.path.insert(0, "/Users/zhangq/.claude/jobs/01ddd053/tmp")
from lib import *
from collections import Counter, defaultdict

ROOT = os.path.expanduser("~/.claude/projects")
BJT = lambda t: datetime.fromtimestamp(t, BJ).strftime("%m-%d %H:%M")

dispatch = []      # 主会话里的 Agent 调用
asks = []          # AskUserQuestion
subspan = {}       # agent-<id>.jsonl 的生命期
tool_by_day = defaultdict(Counter)
writes = []        # Write/Edit 目标文件

for proj in (DIR_FUSION, DIR_SPBK, DIR_WT):
    base = os.path.join(ROOT, proj)
    if not os.path.isdir(base): continue
    for dirpath, _, files in os.walk(base):
        for fn in files:
            if not fn.endswith(".jsonl"): continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT)
            if scope_of(rel) != "req": continue
            _, sid, is_sub = parts(rel)
            ts_all = []
            for line in open(full, errors="ignore"):
                try: o = json.loads(line)
                except Exception: continue
                ts = o.get("timestamp")
                if not ts: continue
                t = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                if not (START <= t <= END): continue
                ts_all.append(t)
                c = o.get("message", {}).get("content")
                if not isinstance(c, list): continue
                for b in c:
                    if not isinstance(b, dict) or b.get("type") != "tool_use": continue
                    nm = b.get("name", "?"); inp = b.get("input", {}) or {}
                    d = datetime.fromtimestamp(t, BJ).strftime("%Y-%m-%d")
                    tool_by_day[d][nm] += 1
                    if nm in ("Task", "Agent"):
                        dispatch.append(dict(t=t, st=inp.get("subagent_type", "?"),
                                             d=(inp.get("description") or "")[:60],
                                             nm=(inp.get("name") or "")[:40], sub=is_sub))
                    elif nm == "AskUserQuestion":
                        qs = inp.get("questions") or []
                        for q in qs:
                            asks.append(dict(t=t, h=(q.get("header") or "")[:20],
                                             q=(q.get("question") or "")[:120],
                                             opts=[(o2.get("label") or "")[:30] for o2 in (q.get("options") or [])]))
                    elif nm in ("Write", "Edit", "MultiEdit"):
                        fp = inp.get("file_path") or ""
                        if fp: writes.append(dict(t=t, f=fp, op=nm))
            if is_sub and ts_all:
                subspan[fn[:-6]] = (min(ts_all), max(ts_all))

dispatch.sort(key=lambda x: x["t"]); asks.sort(key=lambda x: x["t"]); writes.sort(key=lambda x: x["t"])
out = dict(
    dispatch=[dict(x, ts=BJT(x["t"])) for x in dispatch],
    asks=[dict(x, ts=BJT(x["t"])) for x in asks],
    writes=[dict(x, ts=BJT(x["t"])) for x in writes],
    tool_by_day={k: dict(v) for k, v in sorted(tool_by_day.items())},
    subspan={k: [v[0], v[1], round((v[1]-v[0])/60, 1)] for k, v in subspan.items()},
)
json.dump(out, open(os.path.join(T, "acts.json"), "w"), ensure_ascii=False)
print("派发 %d ｜ 拍板问题 %d ｜ 写文件动作 %d ｜ 子代理 transcript %d"
      % (len(dispatch), len(asks), len(writes), len(subspan)))
O=out["asks"]
print("\n拍板事件（前 40）：")
for a in O[:40]:
    print("  %s [%s] %s → %s" % (a["ts"], a["h"], a["q"][:60], "/".join(a["opts"])[:60]))
print("\n改动文件 top25（按次数）：")
cw = Counter(os.path.relpath(w["f"], "/Users/zhangq/Workspace/xx") if w["f"].startswith("/Users/zhangq/Workspace/xx") else w["f"] for w in writes)
for f, n in cw.most_common(25): print("  %4d  %s" % (n, f))
