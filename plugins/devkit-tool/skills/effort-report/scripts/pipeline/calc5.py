#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""理想情景重算：把「超过 20 分钟没回应」的等待段统一压到 10 分钟，重算全流程耗时。

口径与主报告严格一致，只改一件事：等待段的长度。
  · 判定与压缩都按「有效工时窗内长度」——与主报告等待三分桶同一把尺
  · 压缩后重新套用每日 8 小时封顶（封顶规则不变，两侧同规则才可比）
  · 干活时长一秒不动（这不是「让 AI 跑更快」的假设）
落 report-data.json 的 ideal 段。
"""
import json, os, sys
from collections import defaultdict
sys.path.insert(0, "/Users/zhangq/.claude/jobs/01ddd053/tmp")
from lib import *
H = 3600.0

THRESH = 20 * 60      # 超过 20 分钟没回应 = 不正常等待
TARGET = 10 * 60      # 统一压缩到 10 分钟
LUNCH_A, LUNCH_B = 12 * 3600, 13 * 3600 + 30 * 60   # 午休窗（判「这段等待人本来就不在工位」）
LUNCH_A, LUNCH_B = 12 * 3600, 13 * 3600 + 30 * 60   # 午休窗（判「这段等待人本来就不在工位」）
LUNCH_A, LUNCH_B = 12 * 3600, 13 * 3600 + 30 * 60   # 午休窗（判「这段等待人本来就不在工位」）

data = json.load(open(os.path.join(T, "report-data.json")))
ev = load_events()
req = [o for o in ev if scope_of(o["f"]) == "req" and START <= o["t"] <= END]
req_ts = [o["t"] for o in req]
cal = Calendar(req_ts)
req_busy = merge(busy_segments(req_ts))
req_idle = merge(idle_segments(req_ts))

STAGES = data["stages"]


def inter(A, B):
    return merge([(max(a, c), min(b, d)) for a, b in A for c, d in B if min(b, d) > max(a, c)])


def stage_of(t):
    for s in STAGES:
        if s["ts_a"] <= t < s["ts_b"]:
            return s["id"]
    return STAGES[-1]["id"]


# ---------------- 逐日重算 ----------------
daily, cut_by_stage, cut_cons_stage, seg_rows = [], defaultdict(float), defaultdict(float), []
kind_n, kind_cut = defaultdict(int), defaultdict(float)
kind_n, kind_cut = defaultdict(int), defaultdict(float)
tot_cur = tot_new = tot_cons = 0.0
acc = defaultdict(float)
n_abnormal = 0

for d in cal.all_days():
    ts = cal.by_day[d]
    d0 = day_start(d)
    # 未封顶窗口（封顶留到压缩之后再套，两侧同规则）
    if is_weekend(d):
        w_raw = merge(busy_segments(ts))
    else:
        w_raw = clip([(min(ts), max(ts))], d0 + WORK_FROM, d0 + WORK_TO)
    busy_d = total(inter(req_busy, w_raw))
    idle_d = inter(req_idle, w_raw)

    wait_raw = wait_new = wait_cons = 0.0
    cut_d, cut_cons_d = defaultdict(float), defaultdict(float)
    for a, b in idle_d:
        L = b - a
        wait_raw += L
        if L <= THRESH:
            wait_new += L
            wait_cons += L
            continue
        # 不正常段再分三类——决定「保守情景」里哪些真能压
        if not is_weekend(d) and b > d0 + LUNCH_A and a < d0 + LUNCH_B:
            kind = "lunch"          # 跨午休：人本来就不在工位
        elif a <= d0 + WORK_FROM + 120 and not is_weekend(d):
            kind = "pre"            # 贴着窗口起点：前夜溢出到早晨，开工前
        else:
            kind = "onduty"         # 在岗时段人没及时回 —— 唯一真正可压的
        sid = stage_of(a)
        wait_new += TARGET
        cut_d[sid] += L - TARGET
        if kind == "onduty":
            wait_cons += TARGET
            cut_cons_d[sid] += L - TARGET
        else:
            wait_cons += L
        n_abnormal += 1
        kind_n[kind] += 1
        kind_cut[kind] += L - TARGET
        seg_rows.append(dict(day=d, a=hhmm(a), b=hhmm(b),
                             min=round(L / 60, 1), stage=sid, kind=kind))

    raw = busy_d + wait_raw
    new = busy_d + wait_new
    cons = busy_d + wait_cons
    cur_eff = min(DAY_CAP, raw)
    new_eff = min(DAY_CAP, new)
    cons_eff = min(DAY_CAP, cons)
    saved = cur_eff - new_eff
    saved_cons = cur_eff - cons_eff
    tot_cur += cur_eff
    tot_new += new_eff
    tot_cons += cons_eff

    # 三档各自封顶后计入的干活/等人（触顶日按当日 干活:等人 比例分摊截断量）
    def split(busy, wait, eff):
        tot_ = busy + wait
        if tot_ <= 0:
            return 0.0, 0.0
        k = eff / tot_
        return busy * k, wait * k
    b_cur, w_cur = split(busy_d, wait_raw, cur_eff)
    b_new, w_new = split(busy_d, wait_new, new_eff)
    b_cons, w_cons = split(busy_d, wait_cons, cons_eff)
    acc["b_cur"] += b_cur; acc["w_cur"] += w_cur
    acc["b_new"] += b_new; acc["w_new"] += w_new
    acc["b_cons"] += b_cons; acc["w_cons"] += w_cons

    # 环节分摊：该日节省按各环节的削减量占比分配（封顶会让节省 < 削减量）
    cut_sum = sum(cut_d.values())
    for sid, c in cut_d.items():
        cut_by_stage[sid] += saved * (c / cut_sum) if cut_sum else 0.0
    cs = sum(cut_cons_d.values())
    for sid, c in cut_cons_d.items():
        cut_cons_stage[sid] += saved_cons * (c / cs) if cs else 0.0

    daily.append(dict(
        day=d, wd=WD[wd_of(d)],
        busy=round(busy_d / H, 2),
        wait_cur=round(wait_raw / H, 2), wait_new=round(wait_new / H, 2),
        eff_cur=round(cur_eff / H, 2), eff_new=round(new_eff / H, 2),
        saved=round(saved / H, 2),
        capped_cur=raw > DAY_CAP, capped_new=new > DAY_CAP,
    ))

# ---------------- 环节对照 ----------------
stages_out = []
for s in STAGES:
    cut = cut_by_stage.get(s["id"], 0.0) / H
    stages_out.append(dict(
        id=s["id"], name=s["name"], seg=s["seg"],
        eff_cur=s["eff_h"], eff_new=round(max(0.0, s["eff_h"] - cut), 2),
        saved=round(cut, 2),
        eff_cons=round(max(0.0, s["eff_h"] - cut_cons_stage.get(s["id"], 0.0) / H), 2),
    ))

# ---------------- 校验：现状必须复现主报告总量 ----------------
cur_h, new_h = tot_cur / H, tot_new / H
ref = data["totals"]["eff_h"]
assert abs(cur_h - ref) < 0.02, "口径不自洽：重算现状 %.2f ≠ 主报告 %.2f" % (cur_h, ref)

wait_cur = sum(x["wait_cur"] for x in daily)
wait_new = sum(x["wait_new"] for x in daily)

data["ideal"] = dict(
    thresh_min=THRESH // 60, target_min=TARGET // 60,
    eff_cur=round(cur_h, 2), eff_new=round(new_h, 2), eff_cons=round(tot_cons / H, 2),
    day_cons=round(tot_cons / H / 8, 2), x_cons=round(tot_cons / H / 8 / 1.5, 1),
    saved_cons_h=round((tot_cur - tot_cons) / H, 2),
    saved_cons_pct=round((tot_cur - tot_cons) / tot_cur * 100, 1),
    kind_n=dict(kind_n), kind_cut={k: round(v / H, 2) for k, v in kind_cut.items()},
    split={k: round(v / H, 2) for k, v in acc.items()},
    saved_h=round(cur_h - new_h, 2), saved_pct=round((cur_h - new_h) / cur_h * 100, 1),
    day_cur=round(cur_h / 8, 2), day_new=round(new_h / 8, 2),
    x_cur=round(cur_h / 8 / 1.5, 1), x_new=round(new_h / 8 / 1.5, 1),
    busy_h=round(sum(x["busy"] for x in daily), 2),
    wait_cur=round(wait_cur, 2), wait_new=round(wait_new, 2),
    n_abnormal=n_abnormal,
    capped_cur=sum(1 for x in daily if x["capped_cur"]),
    capped_new=sum(1 for x in daily if x["capped_new"]),
    stages=stages_out, daily=daily,
    top_segs=sorted(seg_rows, key=lambda r: -r["min"])[:10],
)
json.dump(data, open(os.path.join(T, "report-data.json"), "w"), ensure_ascii=False, indent=1)

print("校验通过：重算现状 %.2fh ＝ 主报告 %.2fh" % (cur_h, ref))
print("不正常等待段（窗内 >%d 分钟）%d 段" % (THRESH // 60, n_abnormal))
print("等人：%.2f → %.2f 小时（封顶前削减 %.2f）" % (wait_cur, wait_new, wait_cur - wait_new))
print("有效工时：%.2f → %.2f 小时（省 %.2f，%.1f%%）"
      % (cur_h, new_h, cur_h - new_h, (cur_h - new_h) / cur_h * 100))
print("工作日当量：%.2f → %.2f 个 ｜ 对照 1.5 人天：%.1f 倍 → %.1f 倍"
      % (cur_h / 8, new_h / 8, cur_h / 8 / 1.5, new_h / 8 / 1.5))
print("触顶天数：%d → %d" % (data["ideal"]["capped_cur"], data["ideal"]["capped_new"]))
print("不正常段分类：", dict(kind_n), "各类削减(h)：", {k: round(v/H,2) for k,v in kind_cut.items()})
print("保守档（只压在岗段）：%.2fh = %.2f 人天 = %.1f 倍，省 %.2fh"
      % (tot_cons/H, tot_cons/H/8, tot_cons/H/8/1.5, (tot_cur-tot_cons)/H))
print("\n环节对照：")
for s in stages_out:
    print("  %-22s %6.2f → %6.2f  省 %5.2f" % (s["name"], s["eff_cur"], s["eff_new"], s["saved"]))
print("\n最长的 5 段不正常等待：")
for r in data["ideal"]["top_segs"][:5]:
    print("  %s %s→%s  %.0f 分钟  (%s)" % (r["day"], r["a"], r["b"], r["min"], r["stage"]))

sp = data["ideal"]["split"]
print("\n三档拆分（封顶后计入）：")
for lbl, b, w, e in (("现状", sp["b_cur"], sp["w_cur"], cur_h),
                     ("保守可达", sp["b_cons"], sp["w_cons"], tot_cons / H),
                     ("理想上界", sp["b_new"], sp["w_new"], new_h)):
    print("  %-6s 干活 %5.2f + 等人 %5.2f = %6.2f （校验 %.2f）" % (lbl, b, w, b + w, e))
print("主报告现状拆分 干活 %.2f + 等人 %.2f" % (data["totals"]["busy_h"], data["totals"]["wait_h"]))
