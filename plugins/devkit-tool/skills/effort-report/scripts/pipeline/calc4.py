#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补算：机器口径并集 / 等人回话量 / ROI 支撑量。追加进 report-data.json"""
import json, os, sys
from collections import defaultdict
sys.path.insert(0, "/Users/zhangq/.claude/jobs/01ddd053/tmp")
from lib import *
H = 3600.0

data = json.load(open(os.path.join(T, "report-data.json")))
ev = load_events()
req = [o for o in ev if scope_of(o["f"]) == "req" and START <= o["t"] <= END]
oth = [o for o in ev if scope_of(o["f"]) is None and START - 86400 <= o["t"] <= END + 86400]
req_ts = [o["t"] for o in req]
cal = Calendar(req_ts)
req_busy = merge(busy_segments(req_ts))
req_idle = idle_segments(req_ts)
win_all = merge([w for d in cal.all_days() for w in cal.window(d)])

def inter(A, B):
    return merge([(max(a, c), min(b, d)) for a, b in A for c, d in B if min(b, d) > max(a, c)])

# --- 机器口径（不分昼夜，主会话忙段 ∪ 子代理生命周期） ---
files = json.load(open(os.path.join(T, "files.json")))
sub_ivs = []
for rel, m in files.items():
    if scope_of(rel) != "req" or not m["a"]:
        continue
    a, b = max(m["first"], START), min(m["last"], END)
    if b > a:
        sub_ivs.append((a, b))
machine_union = total(merge(req_busy + sub_ivs))
sub_union = total(merge(sub_ivs))
sub_sum = sum(b - a for a, b in sub_ivs)

# --- 等人回话：AI 末条 → 真人下一条 的间隔 ---
rs = sorted(req, key=lambda x: x["t"])
gaps = []
for i in range(len(rs) - 1):
    if rs[i]["k"] == "A" and rs[i + 1]["k"] == "H":
        gaps.append((rs[i]["t"], rs[i + 1]["t"]))
gaps = [(a, b) for a, b in gaps if b - a > 60]
g_in = inter(gaps, win_all)
g30 = inter([(a, b) for a, b in gaps if b - a > 1800], win_all)
g30_n = len([1 for a, b in gaps if b - a > 1800])

# --- ROI 支撑量 ---
def ts_(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=BJ).timestamp()

def eff_of(a, b):
    v, per = cal.eff([(a, b)])
    return round(v / H, 2), {k: round(x / H, 2) for k, x in per.items()}

# R1: 域仓内重复 triage / refine（08-10 14:01 → 15:06「提交 推送 然后进入下一阶段」）
r1, r1p = eff_of(ts_("2026-08-10 14:01"), ts_("2026-08-10 15:06"))
# R2: 08-13 回退后的联审重过（08-14 全天 → 08-16 19:41 放行）
r2, r2p = eff_of(ts_("2026-08-14 00:00"), ts_("2026-08-16 19:41"))
# R2b: 回退当日（08-13）新增契约产出 —— 必要工作，不算可省
r2b, _ = eff_of(ts_("2026-08-13 00:00"), ts_("2026-08-14 00:00"))
# R3: 等人回话 >30min 的窗内总量（可批量化压缩的上界）
r3 = round(total(g30) / H, 2)
# R4: 后台漂移检查（BackgroundValidator）8 次，无人值守
bg = [rel for rel in files if scope_of(rel) == "req"
      and parts(rel)[1] in SPBK_SESSIONS and parts(rel)[1] != "52035015-d12b-4444-aedf-7b0456ee1646"
      and not files[rel]["a"]]
bg_iv = [(files[r]["first"], files[r]["last"]) for r in bg]
r4 = round(total(merge(bg_iv)) / H, 2)
# R5: 子代理并行收益（Σ - 并集）
r5 = round((sub_sum - sub_union) / H, 2)

# --- 逐日：其他需求真人活跃（并行度证据） ---
oh_by_p = defaultdict(list)
for o in oth:
    if o["k"] == "H":
        oh_by_p[o["p"]].append(o["t"])
other_human = merge([s for p, l in oh_by_p.items() for s in busy_segments(l)])
par_by_day = {}
for d in cal.all_days():
    w = cal.window(d)
    par_by_day[d] = round(total(inter(inter(merge(req_idle), w), other_human)) / H, 2)

# 并行项目数（范围内有真人消息的其他项目目录数）
par_projects = len([p for p, l in oh_by_p.items() if any(START <= x <= END for x in l)])

data["machine"] = dict(
    talk_h=round(total(req_busy) / H, 2),
    sub_sum_h=round(sub_sum / H, 2),
    sub_union_h=round(sub_union / H, 2),
    union_h=round(machine_union / H, 2),
    naive_sum_h=round((total(req_busy) + sub_union) / H, 2),
)
data["waitdetail"] = dict(
    gap_all_h=round(total(g_in) / H, 2),
    gap_over30_h=r3, gap_over30_n=g30_n, gap_n=len(gaps),
)
data["roi"] = dict(
    r1_h=r1, r1_per=r1p,
    r2_h=r2, r2_per=r2p, r2b_h=r2b,
    r3_h=r3,
    r4_h=r4, r4_n=len(bg),
    r5_h=r5,
)
data["parallel"] = dict(by_day=par_by_day, projects=par_projects)
json.dump(data, open(os.path.join(T, "report-data.json"), "w"), ensure_ascii=False, indent=1)

print("机器口径：对话推进 %.2fh ｜ 子代理 Σ%.2fh 并集 %.2fh ｜ 二者并集 %.2fh ｜ 线性相加(高估) %.2fh"
      % (data["machine"]["talk_h"], data["machine"]["sub_sum_h"], data["machine"]["sub_union_h"],
         data["machine"]["union_h"], data["machine"]["naive_sum_h"]))
print("等人回话：%d 次 窗内合计 %.2fh ｜ 其中 >30min 的 %d 次合计 %.2fh"
      % (data["waitdetail"]["gap_n"], data["waitdetail"]["gap_all_h"],
         g30_n, r3))
print("ROI 支撑：R1 域仓重复 triage/refine %.2fh ｜ R2 联审重过 %.2fh（回退当日新增契约产出 %.2fh 属必要）"
      % (r1, r2, r2b))
print("          R3 等人>30min %.2fh ｜ R4 后台漂移检查 %d 次 %.2fh（无人值守）｜ R5 子代理并行已省 %.2fh"
      % (r3, len(bg), r4, r5))
print("R2 逐日：", r2p)
print("并行：范围内另有 %d 个项目目录有真人消息" % par_projects)
print("并行占用逐日：", {k: v for k, v in par_by_day.items() if v > 0})
