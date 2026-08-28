# -*- coding: utf-8 -*-
"""补提 Bash / Read / Grep 动作（Verify、Implement 的主要活跃形态是跑命令而非写文件）。"""
import json, os, sys
sys.path.insert(0, "/Users/zhangq/.claude/jobs/01ddd053/tmp")
from lib import *
ROOT = os.path.expanduser("~/.claude/projects")
A = json.load(open(os.path.join(T, "acts.json")))
bash, reads = [], []
for proj in (DIR_FUSION, DIR_SPBK, DIR_WT):
    base = os.path.join(ROOT, proj)
    if not os.path.isdir(base):
        continue
    for dp, _, fs in os.walk(base):
        for fn in fs:
            if not fn.endswith(".jsonl"):
                continue
            rel = os.path.relpath(os.path.join(dp, fn), ROOT)
            if scope_of(rel) != "req":
                continue
            for line in open(os.path.join(dp, fn), errors="ignore"):
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                ts = o.get("timestamp")
                if not ts:
                    continue
                t = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                if not (START <= t <= END):
                    continue
                c = o.get("message", {}).get("content")
                if not isinstance(c, list):
                    continue
                for b in c:
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    inp = b.get("input", {}) or {}
                    if b.get("name") == "Bash":
                        bash.append(dict(t=t, cmd=(inp.get("command") or "")[:200],
                                         d=(inp.get("description") or "")[:60]))
                    elif b.get("name") in ("Read", "Grep", "Glob"):
                        reads.append(dict(t=t, f=(inp.get("file_path") or inp.get("pattern") or "")[:160]))
bash.sort(key=lambda x: x["t"])
reads.sort(key=lambda x: x["t"])
A["bash"] = bash
A["reads"] = reads
json.dump(A, open(os.path.join(T, "acts.json"), "w"), ensure_ascii=False)
print("Bash %d 条 ｜ 只读检索 %d 条" % (len(bash), len(reads)))
