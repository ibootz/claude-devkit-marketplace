#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主计算：三口径耗时 / 环节明细 / 等待三分桶 / 子代理 / token。落 report-data.json"""
import json, os, sys, io, re
from collections import defaultdict
sys.path.insert(0, "/Users/zhangq/.claude/jobs/01ddd053/tmp")
from lib import *

ROOT = "/Users/zhangq/.claude/projects"
H = 3600.0

# ---------------- 环节定义 ----------------
def ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=BJ).timestamp()

STAGES = [
    dict(id="s1", name="需求下发", sub="产品需求 → 结构化规格 → 立项 → 分发到域仓",
         a=ts("2026-08-05 14:24"), b=ts("2026-08-06 14:08"), seg="fusion"),
    dict(id="s2", name="空窗：下发完成到开工", sub="请假(08-07 周五) + 周末(08-08/09) + 周一开工",
         a=ts("2026-08-06 14:08"), b=ts("2026-08-10 14:01"), seg="gap"),
    dict(id="s3", name="立项 + G1 + 需求定义", sub="Backlog triage/refine → G1 → Define → G2 首次放行",
         a=ts("2026-08-10 14:01"), b=ts("2026-08-12 12:42"), seg="sdlc"),
    dict(id="s4", name="需求变更与门禁回退", sub="新增 5 条行为契约 → G2/G3 双回退 → 联审重过",
         a=ts("2026-08-12 12:42"), b=ts("2026-08-16 19:41"), seg="sdlc"),
    dict(id="s5", name="编码实现", sub="TASK-01~23 逐条实现 + 单测 + 契约同步",
         a=ts("2026-08-16 19:41"), b=ts("2026-08-21 15:28"), seg="sdlc"),
    dict(id="s6", name="联调验证与缺陷修复", sub="di/tf 发布 → 人工实测 → QA 提单 → 修复回归",
         a=ts("2026-08-21 15:28"), b=ts("2026-08-26 14:06"), seg="sdlc"),
    dict(id="s7", name="G4 验收放行", sub="验证报告 + 审计 + Human 拍板",
         a=ts("2026-08-26 14:06"), b=ts("2026-08-26 18:44"), seg="sdlc"),
]

# ---------------- 事件分流 ----------------
ev = load_events()
req, oth = [], []
for o in ev:
    s = scope_of(o["f"])
    if s == "req":
        if START <= o["t"] <= END:
            req.append(o)
    elif s is None:
        oth.append(o)

req_ts = [o["t"] for o in req]
cal = Calendar(req_ts)

# 本需求忙 / 等待（全需求事件流）
req_busy = merge(busy_segments(req_ts))
req_idle = idle_segments(req_ts)

# 其他项目：真人活跃段 / AI 活跃段（按项目分别聚簇再并集）
oh_by_p, oa_by_p = defaultdict(list), defaultdict(list)
for o in oth:
    if not (START - 86400 <= o["t"] <= END + 86400):
        continue
    (oh_by_p if o["k"] == "H" else oa_by_p)[o["p"]].append(o["t"])
other_human = merge([s for p, l in oh_by_p.items() for s in busy_segments(l)])
other_ai = merge([s for p, l in oa_by_p.items() for s in busy_segments(l)])

def inter(A, B):
    out = []
    for a, b in A:
        for c, d in B:
            x, y = max(a, c), min(b, d)
            if y > x:
                out.append((x, y))
    return merge(out)


def sub(A, B):
    """A 减 B"""
    out = []
    for a, b in A:
        segs = [(a, b)]
        for c, d in B:
            ns = []
            for x, y in segs:
                if d <= x or c >= y:
                    ns.append((x, y))
                else:
                    if x < c:
                        ns.append((x, c))
                    if d < y:
                        ns.append((d, y))
            segs = ns
        out += segs
    return merge(out)


LONG_HOLD = 30 * 60   # 等待段 >30min 记为长挂起


def buckets(idle_raw, span, win_all):
    """等待三分桶（窗内）：
       B 并行占用 = 与其他需求真人活跃段重叠部分（人被别的需求占住）
       A 短交互间隔 = 余下部分，且所属等待段窗内长度 ≤30min（人在场的正常协作节奏）
       C 长挂起    = 余下部分，且所属等待段窗内长度 >30min（人离席 / 等外部答复）
    """
    tA = tB = tC = 0.0
    for a, b in idle_raw:
        seg = inter([(a, b)], span)
        seg = inter(seg, win_all)
        if not seg:
            continue
        L = total(seg)
        ov = inter(seg, other_human)
        tB += total(ov)
        rest = total(sub(seg, ov))
        if L > LONG_HOLD:
            tC += rest
        else:
            tA += rest
    return dict(par=round(tB / H, 2), quick=round(tA / H, 2), hold=round(tC / H, 2),
                tot=round((tA + tB + tC) / H, 2))

# ---------------- 子代理 ----------------
files = json.load(open(os.path.join(T, "files.json")))
sub_ivs, sub_n, sub_by_stage = [], 0, defaultdict(int)
main_tok = dict(ti=0, to=0, tc=0)
for rel, m in files.items():
    if scope_of(rel) != "req":
        continue
    if m["first"] > END or m["last"] < START:
        continue
    if m["a"]:
        sub_n += 1
        sub_ivs.append((max(m["first"], START), min(m["last"], END)))
        for st in STAGES:
            if st["a"] <= m["first"] < st["b"]:
                sub_by_stage[st["id"]] += 1
sub_ivs = [(a, b) for a, b in sub_ivs if b > a]
sub_sum = sum(b - a for a, b in sub_ivs)
sub_union = total(merge(sub_ivs))

# token 按事件裁剪（只算落在报告范围内的 assistant 事件）
for o in req:
    if o["k"] == "A":
        main_tok["ti"] += o.get("ti", 0)
        main_tok["to"] += o.get("to", 0)
        main_tok["tc"] += o.get("tc", 0)

# ---------------- 真人消息（含文本，供弹层） ----------------
NP = ("<system-reminder>", "Caveat: The messages below were generated",
      "<local-command-stdout>", "<task-notification>", "<bash-input>",
      "<bash-stdout>", "<bash-stderr>")
ENV_CMDS = {"reload-plugins", "plugin", "model", "compact", "clear", "tui", "focus", "diff"}
NS = ("This session is being continued from a previous conversation",
      "Your task is to create a detailed summary of the conversation",
      "[Request interrupted by user", "API Error")

def text_of(msg):
    c = msg.get("content")
    if isinstance(c, str):
        return c, False
    if isinstance(c, list):
        tr = False; ps = []
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_result":
                tr = True
            elif b.get("type") == "text":
                ps.append(b.get("text") or "")
        return "\n".join(ps), tr
    return "", False

def clean_cmd(s):
    m = re.match(r"<command-(?:message|name)>([^<]*)</command-[a-z]+>", s)
    if s.startswith("<command-"):
        names = re.findall(r"<command-name>([^<]*)</command-name>", s)
        args = re.findall(r"<command-args>([^<]*)</command-args>", s)
        n = (names[0] if names else "?").lstrip("/")
        a = (args[0] if args else "").strip()
        return ("斜杠命令 /%s %s" % (n, a)).strip()
    return s

humans = []
for rel in files:
    if scope_of(rel) != "req" or files[rel]["a"]:
        continue
    with io.open(os.path.join(ROOT, rel), "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.startswith("{"):
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") != "user" or o.get("userType") != "external":
                continue
            if o.get("isMeta") or o.get("isSidechain"):
                continue
            txt, tr = text_of(o.get("message") or {})
            if tr:
                continue
            s = (txt or "").lstrip()
            if not s or any(s.startswith(p) for p in NP) or any(p in s[:400] for p in NS):
                continue
            try:
                t = datetime.fromisoformat(o["timestamp"].replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            if not (START <= t <= END):
                continue
            txt2 = re.sub(r"\s+", " ", clean_cmd(s))[:220]
            kind = "real"
            mm = re.match(r"斜杠命令 /([a-z0-9:_-]+)", txt2)
            if mm and mm.group(1) in ENV_CMDS:
                kind = "env"
            humans.append((t, txt2, kind))
humans.sort()
humans_real = [(t, s) for t, s, k in humans if k == "real"]
humans_env = [(t, s) for t, s, k in humans if k == "env"]

# ---------------- 逐日 ----------------
daily = []
for d in cal.all_days():
    w = cal.window(d)
    ts_d = cal.by_day[d]
    dh = [o for o in req if dstr(o["t"]) == d]
    nh = sum(1 for t, _ in humans_real if dstr(t) == d)
    ne = sum(1 for t, _ in humans_env if dstr(t) == d)
    na = sum(1 for o in dh if o["k"] == "A" and not o["a"])
    ns = sum(1 for o in dh if o["k"] == "A" and o["a"])
    busy_d = inter(req_busy, w)
    idle_d = inter(merge(req_idle), w)
    daily.append(dict(
        day=d, wd=WD[wd_of(d)], weekend=is_weekend(d),
        human=nh, env=ne, ai=na, sub=ns,
        first=hhmm(min(ts_d)), last=hhmm(max(ts_d)),
        eff_h=round(total(w) / H, 2),
        busy_h=round(total(busy_d) / H, 2),
        wait_h=round(total(idle_d) / H, 2),
    ))

# 范围内零活动日
zero_days = []
d0 = datetime.fromtimestamp(START, BJ).replace(hour=0, minute=0, second=0, microsecond=0)
while d0.timestamp() <= END:
    di = d0.strftime("%Y-%m-%d")
    if di not in cal.win:
        zero_days.append(dict(day=di, wd=WD[d0.weekday()], weekend=d0.weekday() >= 5))
    d0 += timedelta(days=1)

# ---------------- 环节 ----------------
def stage_calc(st):
    span = [(st["a"], st["b"])]
    eff, per = cal.eff(span)
    busy = inter(req_busy, span)
    idle = inter(merge(req_idle), span)
    eff_busy, _ = cal.eff(busy)
    eff_wait, _ = cal.eff(idle)
    win_all = merge([w for d in cal.all_days() for w in cal.window(d)])
    bk = buckets(req_idle, span, win_all)
    # 逐日明细
    days = []
    for d in sorted(per):
        dw = cal.window(d)
        dspan = inter(span, dw)
        days.append(dict(
            day=d, wd=WD[wd_of(d)],
            eff_h=round(per[d] / H, 2),
            busy_h=round(total(inter(req_busy, dspan)) / H, 2),
            wait_h=round(total(inter(merge(req_idle), dspan)) / H, 2),
            human=sum(1 for t, _ in humans_real if dstr(t) == d and st["a"] <= t < st["b"]),
            env=sum(1 for t, _ in humans_env if dstr(t) == d and st["a"] <= t < st["b"]),
        ))
    msgs = [dict(t=hm(t), s=s) for t, s in humans_real if st["a"] <= t < st["b"]]
    subs = sub_by_stage.get(st["id"], 0)
    return dict(
        id=st["id"], name=st["name"], sub=st["sub"], seg=st["seg"],
        a=hm(st["a"]), b=hm(st["b"]), ts_a=st["a"], ts_b=st["b"],
        cal_h=round((st["b"] - st["a"]) / H, 2),
        cal_d=round((st["b"] - st["a"]) / 86400, 2),
        eff_h=round(eff / H, 2), eff_d=round(eff / H / 8, 2),
        busy_h=round(eff_busy / H, 2), wait_h=round(eff_wait / H, 2),
        raw_busy_h=round(total(busy) / H, 2),
        bucket=bk,
        days=days, msgs=msgs, subagents=subs,
        env_n=sum(1 for t, _ in humans_env if st["a"] <= t < st["b"]),
    )

stages = [stage_calc(s) for s in STAGES]

# ---------------- 总计 ----------------
eff_all, per_all = cal.eff([(START, END)])
busy_eff, _ = cal.eff(req_busy)
wait_eff, _ = cal.eff(merge(req_idle))
win_all = merge([w for d in cal.all_days() for w in cal.window(d)])
BK = buckets(req_idle, [(START, END)], win_all)

# 响应时长（真人消息 → 下一条 AI 事件；及 AI 停 → 真人回话）
resp = []
req_sorted = sorted(req, key=lambda x: x["t"])
for i, o in enumerate(req_sorted):
    if o["k"] != "A":
        continue
    # AI 最后一条后到下一条真人消息的间隔 = 等人
    j = i + 1
    if j < len(req_sorted) and req_sorted[j]["k"] == "H":
        resp.append(req_sorted[j]["t"] - o["t"])
resp.sort()
def pct(l, p):
    if not l:
        return 0
    return l[min(len(l) - 1, int(len(l) * p))]

out = dict(
    meta=dict(
        snapshot=hm(datetime.now(BJ).timestamp()),
        start=hm(START), end=hm(END),
        cal_h=round((END - START) / H, 2), cal_d=round((END - START) / 86400, 2),
        work_from="08:00", work_to="19:00", day_cap_h=8, idle_gap_min=10,
        sessions_req=len(FUSION_SESSIONS) + len(SPBK_SESSIONS) + 5,
        excluded_notes=[
            "218e464c（fusion）= 另一需求 feat-aiqb-flow-guidance 的下发会话，已剔除",
            "ef0b4e5d（fusion）= fusion 插件自身修复，已剔除",
            "375f1420 / 845a0e15 / 01ddd053 = 本次盘点分析会话自身，已剔除",
        ],
    ),
    totals=dict(
        eff_h=round(eff_all / H, 2), eff_d=round(eff_all / H / 8, 2),
        busy_h=round(busy_eff / H, 2), wait_h=round(wait_eff / H, 2),
        raw_busy_h=round(total(req_busy) / H, 2),
        human_msgs=len(humans_real), human_env=len(humans_env),
        ai_main=sum(1 for o in req if o["k"] == "A" and not o["a"]),
        ai_sub=sum(1 for o in req if o["k"] == "A" and o["a"]),
        sub_n=sub_n, sub_sum_h=round(sub_sum / H, 2), sub_union_h=round(sub_union / H, 2),
        tokens=main_tok,
        bucket=BK,
        resp_n=len(resp),
        resp_med_min=round(pct(resp, 0.5) / 60, 1),
        resp_p90_min=round(pct(resp, 0.9) / 60, 1),
    ),
    stages=stages, daily=daily, zero_days=zero_days,
)
json.dump(out, open(os.path.join(T, "report-data.json"), "w"), ensure_ascii=False, indent=1)

# ---------------- 打印摘要 ----------------
m, t = out["meta"], out["totals"]
print("范围 %s → %s ｜ 日历 %.1fh = %.1f 天" % (m["start"], m["end"], m["cal_h"], m["cal_d"]))
print("有效工时(8h制) %.2fh = %.2f 人天 ｜ 其中忙 %.2fh / 等 %.2fh" %
      (t["eff_h"], t["eff_d"], t["busy_h"], t["wait_h"]))
print("原始忙段(不分昼夜) %.2fh ｜ 子代理 %d 个 Σ%.1fh 并集%.1fh" %
      (t["raw_busy_h"], t["sub_n"], t["sub_sum_h"], t["sub_union_h"]))
print("真人消息 %d ｜ 主AI %d ｜ 子AI %d" % (t["human_msgs"], t["ai_main"], t["ai_sub"]))
print("token in=%s out=%s cache_read=%s" % (t["tokens"]["ti"], t["tokens"]["to"], t["tokens"]["tc"]))
print("等待三分桶(窗内 %.2fh)：并行占用 %.2f / 短交互间隔 %.2f / 长挂起 %.2f" %
      (t["bucket"]["tot"], t["bucket"]["par"], t["bucket"]["quick"], t["bucket"]["hold"]))
print("等人响应：中位 %.1f min / P90 %.1f min（%d 样本）" %
      (t["resp_med_min"], t["resp_p90_min"], t["resp_n"]))
print()
print(f"{'环节':26}{'日历h':>8}{'有效h':>8}{'人天':>7}{'忙h':>7}{'等h':>7}{'并行':>7}{'短间隔':>7}{'长挂起':>7}{'子代理':>7}")
for s in stages:
    print(f"{s['name'][:13]:26}{s['cal_h']:>8.1f}{s['eff_h']:>8.2f}{s['eff_d']:>7.2f}"
          f"{s['busy_h']:>7.2f}{s['wait_h']:>7.2f}{s['bucket']['par']:>7.2f}"
          f"{s['bucket']['quick']:>7.2f}{s['bucket']['hold']:>7.2f}{s['subagents']:>7}")
print("\n零活动日：", ", ".join("%s(%s)" % (z["day"][5:], z["wd"]) for z in zero_days))
print("\n逐日：")
print(f"{'日':7}{'周':4}{'H':>4}{'A':>6}{'子':>6}{'首':>7}{'末':>7}{'有效h':>8}{'忙h':>7}{'等h':>7}")
for d in daily:
    print(f"{d['day'][5:]:7}{d['wd']:4}{d['human']:>4}{d['ai']:>6}{d['sub']:>6}"
          f"{d['first']:>7}{d['last']:>7}{d['eff_h']:>8.2f}{d['busy_h']:>7.2f}{d['wait_h']:>7.2f}")
