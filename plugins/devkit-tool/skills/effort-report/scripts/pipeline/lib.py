#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared model: scope definition + 8h-workday effective-time calculus."""
import json, os
from datetime import datetime, timezone, timedelta

T = "/Users/zhangq/.claude/jobs/01ddd053/tmp"
BJ = timezone(timedelta(hours=8))

DIR_FUSION = "-Users-zhangq-Workspace-xx-fusion-xxstar-ai-fusion-work"
DIR_SPBK = "-Users-zhangq-Workspace-xx-domain-sp-xxstar-ai-spbk-work"
DIR_WT = "-Users-zhangq-Workspace-xx-domain-sp-xxstar-ai-spbk-work--sdlc-worktrees-D-003-fix-succession-map-dept-headcount"

# --- in-scope sessions of THIS requirement -------------------------------
# 已核实剔除：218e464c = 另一需求（feat-aiqb-flow-guidance）下发；ef0b4e5d = fusion 插件自身修复
FUSION_SESSIONS = {
    "c89c0a42-6574-4ae1-a4da-c1d121bed29e",   # /fusion:req fix-succession-map-dept-headcount 主线
    "9ec36128-d9ba-4b21-81ba-54fb18b5a69b",   # 08-12 下发补漏（短）
    "fb914172-ec8d-4e99-8fee-83ad9f4fabee",   # 08-12 下发补漏（主）
}
SPBK_SESSIONS = {
    "52035015-d12b-4444-aedf-7b0456ee1646",   # 继任域知识理解
    "6011b1ed-2bb4-4051-a09c-7ce5a8d0ce9e",   # 后台漂移检查 BackgroundValidator ×8
    "5bd32e93-71c9-445f-bdc4-1a548b807995",
    "daff5373-5ac4-4e99-a285-8f19b1a9d451",
    "f76cc809-44d9-4cf3-be9e-f8c518067287",
    "8232a2a3-09a8-4aa2-a6b0-b0e711dfb7f0",
    "4a8dd599-6f07-44b6-ae95-b3d2419533b8",
    "3b5c6861-2ba1-4b86-ad7c-1a14ec47defe",
}
EXCLUDE_SESSIONS = {   # 本次盘点/分析会话自身
    "375f1420-023e-44ee-9de8-5351c7a391d3",
    "845a0e15-ffee-411f-ad34-7dff31ace373",
    "01ddd053-34de-4948-8abd-bacf396ec56e",
    "77e2be7d-7d0c-47ed-8c3a-94640337ba28",
    "d42c0a06-1179-4ad5-9d4e-64af74b0d439",
}

START = datetime(2026, 8, 5, 14, 24, tzinfo=BJ).timestamp()
END = datetime(2026, 8, 26, 18, 44, tzinfo=BJ).timestamp()

WORK_FROM = 8 * 3600
WORK_TO = 19 * 3600
DAY_CAP = 8 * 3600
IDLE_GAP = 600

WD = "一二三四五六日"


def parts(rel):
    ps = rel.split("/")
    proj = ps[0]
    if len(ps) == 2:
        return proj, ps[1][:-6], False
    return proj, ps[1], True


def scope_of(rel):
    proj, sid, _ = parts(rel)
    if sid in EXCLUDE_SESSIONS:
        return "self"
    if proj == DIR_WT:
        return "req"
    if proj == DIR_FUSION and sid in FUSION_SESSIONS:
        return "req"
    if proj == DIR_SPBK and sid in SPBK_SESSIONS:
        return "req"
    return None


def seg_of(rel):
    proj, _, _ = parts(rel)
    return "fusion" if proj == DIR_FUSION else "sdlc"


def load_events():
    out = []
    with open(os.path.join(T, "events.jsonl")) as f:
        for line in f:
            out.append(json.loads(line))
    out.sort(key=lambda x: x["t"])
    return out


def dstr(ts):
    return datetime.fromtimestamp(ts, BJ).strftime("%Y-%m-%d")


def hm(ts):
    return datetime.fromtimestamp(ts, BJ).strftime("%m-%d %H:%M")


def hhmm(ts):
    return datetime.fromtimestamp(ts, BJ).strftime("%H:%M")


def day_start(dayiso):
    y, m, d = (int(x) for x in dayiso.split("-"))
    return datetime(y, m, d, tzinfo=BJ).timestamp()


def wd_of(dayiso):
    return datetime.fromisoformat(dayiso).weekday()


def is_weekend(dayiso):
    return wd_of(dayiso) >= 5


def merge(ivs):
    if not ivs:
        return []
    ivs = sorted(tuple(x) for x in ivs)
    out = [list(ivs[0])]
    for a, b in ivs[1:]:
        if a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [tuple(x) for x in out]


def clip(ivs, lo, hi):
    r = []
    for a, b in ivs:
        a2, b2 = max(a, lo), min(b, hi)
        if b2 > a2:
            r.append((a2, b2))
    return r


def total(ivs):
    return sum(b - a for a, b in ivs)


def busy_segments(ts_list, gap=IDLE_GAP):
    ts = sorted(set(ts_list))
    if not ts:
        return []
    segs = []
    s = prev = ts[0]
    for t in ts[1:]:
        if t - prev > gap:
            segs.append((s, prev)); s = t
        prev = t
    segs.append((s, prev))
    return segs


def idle_segments(ts_list, gap=IDLE_GAP):
    ts = sorted(set(ts_list))
    return [(ts[i - 1], ts[i]) for i in range(1, len(ts)) if ts[i] - ts[i - 1] > gap]


class Calendar:
    """8 小时工作制口径（口径 A · 有效工时）。

    每日可计入窗口 W(d)：
      · 本需求零活动日            → ∅（自然涵盖 08-07 请假日与 08-08/09、08-22/23 周末）
      · 工作日                    → [08:00,19:00] ∩ [当日首事件, 当日末事件]
      · 周末（有活动）            → 当日实际忙段并集（≤10min 聚簇），不摊满整窗
    日封顶 8 小时。
    """

    def __init__(self, req_ts):
        self.by_day = {}
        for t in req_ts:
            self.by_day.setdefault(dstr(t), []).append(t)
        self.win = {}
        for d, ts in self.by_day.items():
            d0 = day_start(d)
            if is_weekend(d):
                w = merge(busy_segments(ts))
            else:
                lo, hi = min(ts), max(ts)
                w = clip([(lo, hi)], d0 + WORK_FROM, d0 + WORK_TO)
            # 日封顶 8h（从窗口起点起截）
            w = merge(w)
            if total(w) > DAY_CAP:
                acc, out = 0.0, []
                for a, b in w:
                    take = min(b - a, DAY_CAP - acc)
                    if take <= 0:
                        break
                    out.append((a, a + take)); acc += take
                w = out
            self.win[d] = w

    def window(self, dayiso):
        return self.win.get(dayiso, [])

    def all_days(self):
        return sorted(self.win)

    def eff(self, ivs):
        """有效工时（秒）+ 逐日分布"""
        ivs = merge(ivs)
        per = {}
        for d, w in self.win.items():
            if not w:
                continue
            v = total(merge(clip(
                [(max(a, wa), min(b, wb)) for a, b in ivs for wa, wb in w
                 if min(b, wb) > max(a, wa)], -1e18, 1e18)))
            if v > 0:
                per[d] = v
        return sum(per.values()), per
