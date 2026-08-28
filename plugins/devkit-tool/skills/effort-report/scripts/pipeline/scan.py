#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pass 1: scan all session jsonl under ~/.claude/projects, emit compact event stream.
Output: events.jsonl  (one line per kept event)
  {p: proj_dir, f: rel_file, a: 1 if agent-subtranscript, t: epoch_seconds(utc),
   k: kind in {H(human), A(assistant), O(other)}, ti: input_tokens, to: output_tokens, tc: cache_read}
Also: files.json  per-file summary for scope decisions.
"""
import os, json, sys, io
from datetime import datetime, timezone

ROOT = "/Users/zhangq/.claude/projects"
OUT = "/Users/zhangq/.claude/jobs/01ddd053/tmp"

NOISE_PREFIX = (
    "<system-reminder>",
    "Caveat: The messages below were generated",
    "<command-name>",
    "<local-command-stdout>",
    "<task-notification>",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
)
NOISE_SUBSTR = (
    "This session is being continued from a previous conversation",
    "Your task is to create a detailed summary of the conversation",
    "[Request interrupted by user",
    "API Error",
)

def text_of(msg):
    c = msg.get("content")
    if isinstance(c, str):
        return c, False
    if isinstance(c, list):
        has_tr = False
        parts = []
        for b in c:
            if not isinstance(b, dict):
                continue
            ty = b.get("type")
            if ty == "tool_result":
                has_tr = True
            elif ty == "text":
                parts.append(b.get("text") or "")
        return "\n".join(parts), has_tr
    return "", False

def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None

def main():
    ev = open(os.path.join(OUT, "events.jsonl"), "w")
    files = {}
    nfile = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        for fn in filenames:
            if not fn.endswith(".jsonl"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT)
            parts = rel.split(os.sep)
            proj = parts[0]
            is_agent = 1 if fn.startswith("agent-") else 0
            nfile += 1
            n_h = n_a = 0
            ti = to = tc = 0
            first = last = None
            first_human_text = None
            try:
                fh = io.open(full, "r", encoding="utf-8", errors="replace")
            except Exception:
                continue
            with fh:
                for line in fh:
                    line = line.strip()
                    if not line or line[0] != "{":
                        continue
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    t = parse_ts(o.get("timestamp"))
                    if t is None:
                        continue
                    ty = o.get("type")
                    kind = "O"
                    if ty == "assistant":
                        kind = "A"
                        u = (o.get("message") or {}).get("usage") or {}
                        a_ti = u.get("input_tokens") or 0
                        a_to = u.get("output_tokens") or 0
                        a_tc = u.get("cache_read_input_tokens") or 0
                        ti += a_ti; to += a_to; tc += a_tc
                        n_a += 1
                    elif ty == "user":
                        msg = o.get("message") or {}
                        txt, has_tr = text_of(msg)
                        is_ext = (o.get("userType") == "external")
                        meta = bool(o.get("isMeta")) or bool(o.get("isCompactSummary"))
                        side = bool(o.get("isSidechain"))
                        noise = False
                        s = (txt or "").lstrip()
                        if not s:
                            noise = True
                        else:
                            for p in NOISE_PREFIX:
                                if s.startswith(p):
                                    noise = True; break
                            if not noise:
                                for p in NOISE_SUBSTR:
                                    if p in s[:400]:
                                        noise = True; break
                        if is_ext and not meta and not side and not has_tr and not noise:
                            kind = "H"
                            n_h += 1
                            if first_human_text is None:
                                first_human_text = s[:160]
                    if first is None or t < first:
                        first = t
                    if last is None or t > last:
                        last = t
                    if kind in ("H", "A"):
                        rec = {"p": proj, "f": rel, "a": is_agent, "t": round(t), "k": kind}
                        if kind == "A":
                            rec["ti"] = a_ti; rec["to"] = a_to; rec["tc"] = a_tc
                        ev.write(json.dumps(rec, separators=(",", ":")) + "\n")
            if first is not None:
                files[rel] = {
                    "p": proj, "a": is_agent, "first": round(first), "last": round(last),
                    "nh": n_h, "na": n_a, "ti": ti, "to": to, "tc": tc,
                    "q": first_human_text,
                }
    ev.close()
    with open(os.path.join(OUT, "files.json"), "w") as f:
        json.dump(files, f, ensure_ascii=False)
    print("files scanned:", nfile, "with events:", len(files))

main()
