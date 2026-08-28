# -*- coding: utf-8 -*-
"""生成四条时间轴的完整数据：阶段层（守恒）+ 步骤层（可归因子集）+ 逐步骤事件流。

口径与主报告严格一致：工作日 08:00–19:00、每日封顶 8 小时、周末只计实际活跃段。
阶段窗口由门禁事件切定（见 phases.py），互不重叠、连续覆盖，故 Σ阶段 = 全程有效工时。
步骤层只算锚点命中的动作，Σ步骤 ≤ 阶段总量，差额显式标为「跨步骤协调 / 未留具名痕迹」。
"""
import json, os, sys
sys.path.insert(0, "/Users/zhangq/.claude/jobs/01ddd053/tmp")
from lib import *
from steps_def import FUSION, DOMAIN
from phases import PHASES, FUSION_WRAP, TRACKS
from collections import defaultdict, Counter

H = 3600.0
A = json.load(open(os.path.join(T, "acts.json")))
MAIN = json.load(open(os.path.join(T, "report-data.json")))
ALL = [("domain", r) for r in DOMAIN] + [("fusion", r) for r in FUSION]

WTP = "/Users/zhangq/Workspace/xx/domain/sp/xxstar-ai-spbk-work/.sdlc/worktrees/D-003-fix-succession-map-dept-headcount/"
MAINP = "/Users/zhangq/Workspace/xx/domain/sp/xxstar-ai-spbk-work/"
FUSP = "/Users/zhangq/Workspace/xx/fusion/xxstar-ai-fusion-work/"

ev = load_events()
req = [o for o in ev if scope_of(o["f"]) == "req" and START <= o["t"] <= END]
req_ts = [o["t"] for o in req]
cal = Calendar(req_ts)
req_busy = merge(busy_segments(req_ts))
req_idle = merge(idle_segments(req_ts))


def inter(Aa, Bb):
    return merge([(max(a, c), min(b, d)) for a, b in Aa for c, d in Bb if min(b, d) > max(a, c)])


def norm(f):
    for pre, tag in ((WTP, "wt:"), (MAINP, "main:"), (FUSP, "fusion:")):
        if f.startswith(pre):
            return tag + f[len(pre):]
    return "other:" + f


# 事件按时间落在哪个阶段 → 决定它属于 fusion 侧还是 domain 侧。
# 不加这层约束，关键词锚点（storyline / behaviors / 契约 …）会跨侧误命中：
# fusion 侧写 storyline 骨架的动作被匹配到 domain 的 storyline 步骤上。
_SIDE_IDX = {}
for _sd in ("fusion", "domain"):
    _SIDE_IDX[_sd] = [i for i, (sd, _) in enumerate(ALL) if sd == _sd]
_SIDE_IDX["gap"] = []


def side_at(t):
    for ph in PHASES:
        if ph["a"] <= t < ph["b"]:
            return ph["side"]
    return "domain"


def short(t):
    """把三个仓库的绝对路径前缀压成短标记，让事件流里真正有信息的那截露出来。"""
    t = str(t)
    for pre, tag in ((WTP, "工作区/"), (MAINP, "主仓/"), (FUSP, "fusion仓/")):
        t = t.replace(pre, tag)
    return t


def match_file(path, sd="both"):
    best, blen = None, 0
    pool = range(len(ALL)) if sd == "both" else _SIDE_IDX.get(sd, [])
    for i in pool:
        for frag in ALL[i][1][6].get("f", []):
            if frag in path and len(frag) > blen:
                best, blen = i, len(frag)
    return best


def match_kw(text, key, sd="both"):
    t = (text or "").lower()
    pool = range(len(ALL)) if sd == "both" else _SIDE_IDX.get(sd, [])
    for i in pool:
        for kw in ALL[i][1][6].get(key, []):
            if kw.lower() in t:
                return i
    return None


# ---------- 归属：每个动作 → (步骤idx | None) ----------
EVT = []      # (t, step_idx|None, who, kind, text, extra)
for w in A["writes"]:
    p = norm(w["f"])
    EVT.append((w["t"], match_file(p), "ai", "write", p, w["op"]))
for d in A["dispatch"]:
    EVT.append((d["t"], match_kw(d["d"] + " " + d.get("nm", ""), "a"), "ai", "agent", d["d"], d["st"]))
for a in A["asks"]:
    EVT.append((a["t"], match_kw(a["h"] + " " + a["q"], "q"), "human", "ask", a["q"],
                dict(h=a["h"], opts=a["opts"])))
for b in A["bash"]:
    _sd = side_at(b["t"])
    i = match_file(b["cmd"], _sd)
    if i is None:
        i = match_kw(b["cmd"] + " " + b["d"], "b", _sd)
    if i is None:
        i = match_kw(b["cmd"] + " " + b["d"], "a", _sd)
    EVT.append((b["t"], i, "ai", "bash", b["d"] or short(b["cmd"])[:110], b["cmd"]))
# 真人指令原文（来自主报告已去重的决策指令流）
for st in MAIN["stages"]:
    for m in st.get("msgs", []):
        pass   # 主报告里只存了格式化时间，原文另取
HUM = []
for st in MAIN["stages"]:
    for m in st.get("msgs", []):
        # 主报告里存的是 "MM-DD HH:MM"，解析回时间戳（全程都在 2026 年内）
        try:
            d = datetime.strptime("2026-" + m["t"], "%Y-%m-%d %H:%M").replace(tzinfo=BJ)
        except ValueError:
            continue
        HUM.append((d.timestamp(), m["s"]))

EVT.sort(key=lambda x: x[0])
ts_of = defaultdict(list)
for t, i, *_ in EVT:
    if i is not None:
        ts_of[i].append(t)

STEP_META = {i: r for i, (_, r) in enumerate(ALL)}


def classify(ev):
    """把一个未归属到本阶段步骤的动作，归到一个「实际在干什么」的类别上。"""
    _, _, _, k, sx, x = ev
    if k == "ask":
        return "向人拍板"
    if k == "agent":
        return "派后台助手"
    if k == "write":
        p = sx
        if "tests/" in p:
            return "改测试代码"
        if "/src/" in p:
            return "改产品源码"
        if ".keeper" in p:
            return "改缺陷与杂务台账"
        if "sdlc/" in p or "backlog" in p or "deliveries" in p or "specs/" in p:
            return "改规格与交付账本"
        if "/docs/" in p or p.endswith(".md"):
            return "改文档"
        return "改其他文件"
    c = (x or sx or "").strip().lower()
    if c.startswith("git ") or " git " in c[:40] or c.startswith("gh "):
        return "git 操作"
    for w in ("mvn", "gradle", "javac", "yarn", "npm", "npx", "playwright", "pytest", "agent-browser", "curl "):
        if w in c:
            return "跑测试与构建"
    for w in ("dbops", "ymcas", "cred ", "preflight", "fe_deploy"):
        if w in c:
            return "环境与部署运维"
    for w in ("grep", "rg ", "find ", "ls ", "cat ", "head ", "tail ", "wc ", "jq ", "sed ", "awk "):
        if c.startswith(w) or "| " + w in c or "(cd" in c and w in c:
            return "检索与查看"
    if c.startswith("python") or c.startswith("node "):
        return "跑脚本"
    return "其他命令"



# 二次分桶：一个动作归不到流程步骤，不代表它跟需求无关。这里按「命令碰的是什么东西」
# 再分一层，用来回答「它到底在干什么、能不能算进流程里」。判据全是命令文本的路径形态。
BUCKETS = [
    ("查流程本身怎么规定的",
     "读 AI-SDLC 插件自己的 skill 说明、门禁校验脚本与知识库，弄清这一步该产什么、闸怎么过",
     ("/plugins/cache/ai-sdlc/", "/plugins/marketplaces/ai-sdlc/", "/plugins/cache/curatedskills-dev/",
      "/skills/define/", "/skills/design/", "/skills/verify/", "/knowledge/", "write-guard",
      "validate-blocker", "gate-dossier", "inject-dossier", "audit-dossier", "qualify")),
    ("在自己写的账本与规格里定位与复核",
     "在自己刚写过的那几份规格/账本里找某个编号、字段、条款具体在第几行，或复算条数与哈希。"
     "已对 P9 阶段该桶 351 条命令做过全量归类实证：定位 197 条（56.1%）、"
     "复算条数与哈希 81 条（23.1%）、跨文件一致性核对 26 条（7.4%）、零散 41 条（11.7%）；"
     "字面意义的「写完 grep 一遍确认落盘」按最宽口径也只占 18.2%、紧口径 10.5%，不是主体",
     ("sdlc/deliveries/", "sdlc/specs/", "sdlc/backlog/", "coverage.md", "behaviors",
      "contracts.md", "entities.md", "scope.md", "tasks.md", "product-questions",
      "gate-review", "platform-deps", "_index.md")),
    ("管 git / worktree / 子模块",
     "交付跑在独立 worktree 上、仓内还套多层 submodule，状态确认与 gitlink 对齐都要人工敲命令",
     ("git ", "worktree", "submodule", "gitlink", "rev-parse", "git-inner")),
    ("查产品源码与前端",
     "读继任相关的 Java / Vue / Mapper，判断改动落点与影响面",
     ("src/sptalentbkapi", "src/sptalentbankpc", "src/spgwnlh5", "src/talent-pc",
      ".java", ".vue", ".xml", "--include=")),
    ("查别的域的本体与外部依赖",
     "读 udp / fusion 侧的本体与契约，确认跨域字段口径",
     ("ontologies/", "ontology", "-udp-work", "-fusion-work")),
    ("跑临时脚本与探针",
     "为查证某个判断临时写的一次性脚本",
     ("/tmp/d003", "python3 -c", "node -e", ".claude/jobs/")),
]


def bucket_of(cmd):
    c = cmd or ""
    for name, _, kws in BUCKETS:
        if any(w in c for w in kws):
            return name
    return "其他零散命令"


# 每个类别「为什么会耗这么久」的机制性解释。回答的是听报告的人第一个会问的问题：
# 这些动作单看每一条都很短，为什么加起来这么多。答案统一是「次数」而不是「单次慢」，
# 所以每行同时给平均每次耗时，让人自己对上。
CAT_WHY = {
    "检索与查看":
        "影响面枚举与条款定位全靠 grep：一次改动要在 14 个前端仓加后端里枚举受影响的调用点；"
        "而规格账本自身有几千行、编号（SC-xx / TASK-xx / BR-xx）散落其间，"
        "每次要引用某一条都得先全文搜出它在第几行。没有编号到行号的索引，只能逐次重搜。",
    "其他命令":
        "兜底桶 —— 命令文本里不含 git／构建／运维／检索这些关键词的都落这里。"
        "实际主体是 sed -n 读文件片段、python3 -c 现算、以及 (cd … && …) 包起来的复合命令。"
        "点开看二级构成就知道它们碰的是什么。",
    "git 操作":
        "交付跑在独立 worktree 上、仓内还套多层 submodule：改一处要确认父仓与子仓两侧状态、"
        "对齐 gitlink、核 worktree 是否落后主线。这些没有一步能省，且每步都要单独敲。",
    "派后台助手":
        "长任务交给后台助手做，主会话只留摘要。这里记的是派发与收回执的那段时间，"
        "助手自己的执行时间已按并集算进阶段总量，不重复计。",
    "向人拍板":
        "门禁决策、方案选型、口径确认。这里只计发问与收到答复之间机器侧的活跃时间；"
        "人真正在想的那些长间隙已按「机器等人」单独计，不落在这一栏，所以这一栏的平均每次很短。",
    "改规格与交付账本":
        "AI-SDLC 要求每一步都落盘：behaviors／contracts／entities／coverage／tasks／decisions "
        "各自成文，且相互引用要对得上。改一个字段口径，牵动的是好几份产物。",
    "改产品源码":
        "本次真正的代码改动面很小（两处统计口径），但落点分散在后端 Mapper 与前端多个仓，"
        "每处都要单独定位与验证。",
    "改测试代码": "补测试与调用例，随产品源码改动同步。",
    "改缺陷与杂务台账": "验证期发现的缺陷与顺手记下的杂务，逐条登记与归档。",
    "改文档": "报告、说明、交接文档。",
    "跑测试与构建": "编译、跑单测、跑前端构建与浏览器用例。等构建本身的时间占大头。",
    "环境与部署运维": "查环境状态、刷鉴权、看部署与日志。",
    "跑脚本": "为查证某个判断临时写的一次性脚本，用完即弃。",
    "改其他文件": "配置、临时产物等不属上面任何一类的文件。",
}


def _nopfx(s):
    """剥掉内部标记前缀（worktree / 仓外文件），呈现里不该出现这些。"""
    s = s or ""
    for pfx in ("wt:", "other:"):
        if s.startswith(pfx):
            return s[len(pfx):]
    return s


def samp_of(x):
    """抽样行显示什么：命令给原文，写文件给路径，派助手给派发描述，拍板给问题原文。"""
    k = x[3]
    if k == "bash":
        return short(x[5] or x[4] or "")
    if k == "agent":
        d = short(x[4] or "")
        return (d + ("（" + str(x[5]) + "）" if x[5] and str(x[5]) not in d else "")) or "派后台助手"
    return _nopfx(short(x[4] or x[5] or ""))


def sub_of(x):
    """给一个动作再分一层「碰的是什么东西」，用来把兜底桶拆开。"""
    k = x[3]
    if k == "bash":
        return bucket_of(x[5] or x[4] or "")
    if k == "write":
        p = _nopfx(x[4] or "")
        parts = [s for s in p.split("/") if s]
        for i, s in enumerate(parts):
            if s in ("sdlc", "src", "docs", ".keeper", ".sdlc", "specs", "deliveries"):
                return "/".join(parts[i:i + 3])
        return "/".join(parts[:2]) or "（路径未知）"
    if k == "agent":
        return "派后台助手"
    if k == "ask":
        return "向人拍板"
    return "其他"


def _u(xs):
    """一组动作的有效工时（活跃段并集），分项相加会重复计时，总量必须走这里。"""
    if not xs:
        return 0.0
    sg = merge(busy_segments(sorted(x[0] for x in xs)))
    return cal.eff(sg)[0] if sg else 0.0


def build_phase(ph):
    span = [(ph["a"], ph["b"])]
    eff, per = cal.eff(span)
    ebusy, _ = cal.eff(inter(req_busy, span))
    ewait, _ = cal.eff(inter(req_idle, span))
    ine = [e for e in EVT if ph["a"] <= e[0] < ph["b"]]
    hum = [h for h in HUM if ph["a"] <= h[0] < ph["b"]]
    n = Counter(e[3] for e in ine)
    files = Counter(e[4] for e in ine if e[3] == "write")

    # 步骤层：只取本阶段声明的 stage key，且动作落在窗口内
    steps = []
    for i, r in STEP_META.items():
        if r[0] not in ph["stages"]:
            continue
        mine = [e for e in ine if e[1] == i]
        tss = sorted(e[0] for e in mine)
        segs = merge(busy_segments(tss)) if tss else []
        eff_s, _ = cal.eff(segs) if segs else (0.0, {})
        cnt = Counter(e[3] for e in mine)
        fl = Counter(e[4] for e in mine if e[3] == "write")
        steps.append(dict(
            id=r[2], name=r[3], must=bool(r[4]), src=r[5],
            eff_h=round(eff_s / H, 2), raw_h=round(total(segs) / H, 2),
            n_write=cnt["write"], n_bash=cnt["bash"], n_agent=cnt["agent"], n_ask=cnt["ask"],
            n_files=len(fl), files=[f for f, _ in fl.most_common(10)],
            a=hhmm(tss[0]) if tss else None, b=hhmm(tss[-1]) if tss else None,
            days=sorted({datetime.fromtimestamp(t, BJ).strftime("%m-%d") for t in tss}),
            events=[dict(t=hm(e[0]), who=e[2], k=e[3], s=short(e[4])[:120],
                         x=e[5] if isinstance(e[5], (str, dict)) else None)
                    for e in mine[:70]],
        ))
    mine_idx = {i for i, r in STEP_META.items() if r[0] in ph["stages"]}
    named = merge(busy_segments(sorted(e[0] for e in ine if e[1] in mine_idx)))
    eff_named, _ = cal.eff(named) if named else (0.0, {})

    # 落在本阶段窗口、但归不到本阶段某个具名子步骤的动作。
    # 它们仍然算本阶段的（流程线性，过了上道门禁就进入本阶段），这里只按
    # 「实际在干什么」分解，不摊派也不只给一个总数。
    rest_none = [x for x in ine if x[1] not in mine_idx]
    cat = defaultdict(list)
    for x in rest_none:
        cat[classify(x)].append(x)
    breakdown = []
    for cn, xs in cat.items():
        tss2 = sorted(x[0] for x in xs)
        sg = merge(busy_segments(tss2))
        eh, _ = cal.eff(sg) if sg else (0.0, {})
        ff = Counter(x[4] for x in xs if x[3] == "write")
        # 二级构成：把类别（尤其兜底桶「其他命令」）拆到「碰的是什么东西」这一层
        sc = defaultdict(list)
        for x in xs:
            sc[sub_of(x)].append(x)
        sub = []
        for sn, sxs in sorted(sc.items(), key=lambda kv: -_u(kv[1])):
            sub.append(dict(name=sn, n=len(sxs), eff_h=round(_u(sxs) / H, 2)))
        st = max(1, len(xs) // 20)
        breakdown.append(dict(
            name=cn, n=len(xs), eff_h=round(eh / H, 2),
            avg_s=round(eh / len(xs)) if xs else 0,
            why=CAT_WHY.get(cn, ""),
            files=[f for f, _ in ff.most_common(6)],
            sub=sub[:8],
            samples=[dict(t=hm(x[0]), s=samp_of(x).replace("\n", " ")[:170])
                     for x in sorted(xs, key=lambda y: y[0])[::st][:20]]))
    breakdown.sort(key=lambda r: -r["eff_h"])
    # 二次分桶：把未归因的命令按「碰的是什么东西」再分一层，并留原文抽样供逐条判断。
    # 桶各自按并集算工时，故各桶相加 > 未归因总量（时间上有重叠），呈现时须写明。
    _BD = dict((b[0], b[1]) for b in BUCKETS)
    bcat = defaultdict(list)
    for x in rest_none:
        if x[3] == "bash":
            bcat[bucket_of(x[5] or x[4] or "")].append(x)
    nb_tot = _u([x for x in rest_none if x[3] == "bash"])
    nonebuckets = []
    for bn, xs in sorted(bcat.items(), key=lambda kv: -_u(kv[1])):
        bh = _u(xs)
        st = max(1, len(xs) // 24)
        nonebuckets.append(dict(
            name=bn, why=_BD.get(bn, "既不碰流程定义、也不碰本需求产物的零散命令"),
            n=len(xs), eff_h=round(bh / H, 2),
            pct=round(bh / nb_tot * 100, 1) if nb_tot else 0.0,
            samples=[dict(t=hm(x[0]), s=short(x[5] or x[4] or "").replace("\n", " ")[:170])
                     for x in xs[::st][:24]]))

    # 口径：流程线性，窗口内的动作一律算本阶段的。只有账本明确记录了回退某道门禁，
    # 那一段重做才另计返工（见 AGG["rework_*"]，信源 gate-rollbacks.md）。
    # 故此处不再按「产物锚点」把窗口内动作判给别的阶段 —— 那会把正常的跨阶段微调
    # 与真正的门禁回退返工混进同一个桶，把返工量放大一倍以上。
    return dict(
        id=ph["id"], track=ph["track"], side=ph["side"], name=ph["name"], sub=ph["sub"],
        gate=ph["gate"], ev=ph["ev"],
        a=hm(ph["a"]), b=hm(ph["b"]), ts_a=ph["a"], ts_b=ph["b"],
        cal_h=round((ph["b"] - ph["a"]) / H, 2), cal_d=round((ph["b"] - ph["a"]) / 86400, 2),
        eff_h=round(eff / H, 2), eff_d=round(eff / H / 8, 2),
        busy_h=round(ebusy / H, 2), wait_h=round(ewait / H, 2),
        named_h=round(eff_named / H, 2), unnamed_h=round(max(0.0, eff / H - eff_named / H), 2),
        n_write=n["write"], n_bash=n["bash"], n_agent=n["agent"], n_ask=n["ask"],
        n_human=len(hum), n_files=len(files),
        top_files=[dict(f=f, n=c) for f, c in files.most_common(12)],
        steps=steps, breakdown=breakdown,
        nonebuckets=nonebuckets, nb_h=round(nb_tot / H, 2),
        nb_n=sum(b["n"] for b in nonebuckets),
        none_n=len(rest_none),
        humans=[dict(t=hm(t), s=s[:400]) for t, s in hum[:60]],
    )


phases = [build_phase(p) for p in PHASES]

# fusion 收尾：无独立工时窗口（其动作落在 domain Verify 期间并行），单独给证据
wrap = dict(FUSION_WRAP)
wrap.update(a=None, b=None, eff_h=0.0, cal_h=0.0, steps=[
    dict(id=r[2], name=r[3], must=bool(r[4]), src=r[5], eff_h=0.0, raw_h=0.0,
         n_write=0, n_bash=0, n_agent=0, n_ask=0, n_files=0, files=[], a=None, b=None,
         days=[], events=[], done=False)
    for i, r in STEP_META.items() if r[0] == "f-wrap"])

tot_eff = sum(p["eff_h"] for p in phases)
ref = MAIN["totals"]["eff_h"]

# ---------- 跨阶段聚合：给「可裁剪清单」当底数 ----------
# 各阶段窗口互不重叠，故同名项跨阶段相加成立（阶段内部各项重叠已在阶段层说明）。
_bk = defaultdict(lambda: [0, 0.0])
for p in phases:
    for b in p.get("nonebuckets", []):
        _bk[b["name"]][0] += b["n"]
        _bk[b["name"]][1] += b["eff_h"]
# 同一个步骤可能在两个阶段各跑一遍（首过 + 回退重过），这里按步骤 id 合并并记跑了几段
_st = {}
for p in phases:
    for s in p["steps"]:
        if s["eff_h"] <= 0:
            continue
        r = _st.setdefault(s["id"], dict(id=s["id"], name=s["name"], src=s["src"],
                                         eff_h=0.0, n_write=0, n_bash=0, n_ask=0, phases=[]))
        r["eff_h"] = round(r["eff_h"] + s["eff_h"], 2)
        r["n_write"] += s["n_write"]
        r["n_bash"] += s["n_bash"]
        r["n_ask"] += s["n_ask"]
        r["phases"].append(p["id"])

AGG = dict(
    buckets=[dict(name=k, n=v[0], eff_h=round(v[1], 2)) for k, v in
             sorted(_bk.items(), key=lambda kv: -kv[1][1])],
    steps=sorted(_st.values(), key=lambda r: -r["eff_h"]),
)
AGG["bucket_h"] = round(sum(b["eff_h"] for b in AGG["buckets"]), 2)
AGG["step_h"] = round(sum(s["eff_h"] for s in AGG["steps"]), 2)

# ---------- 返工口径：唯一信源 = 交付账本 gate-rollbacks.md ----------
# 流程是线性的：过了 Gx 就进入 Gx→Gy 这一段，窗口内的动作一律算该阶段的。
# 只有账本明确记录了「回退某道门禁」，那一段重做才另计返工。
# 该账本全文只有两行数据行，均为 2026-08-13、human-directive / requirement-change，
# 均于 2026-08-16 重过闭环：
#   ① 回退 G2 —— 重开 SC-82~SC-86 与覆盖面 B10/F5/F6（scope 103 行 / coverage 1457 行）
#   ② 回退 G3 —— 重开 TASK-12~TASK-15、ADR-008、两个契约字段
#      （HeirPosNodeBean.heirValidQty / PosUserListResp.userDeleted）
# 除这两行外，对话历史中没有任何其他回退门禁的记录。这两行圈出的返工区间，
# 就是时间轴上按门禁事件单独切出来的那一段（阶段名即「需求变更 → G2/G3 回退重过」）。
REWORK_PHASE_ID = "P8"
REWORK_LEDGER = "sdlc/deliveries/D-003-fix-succession-map-dept-headcount/gate-rollbacks.md"
REWORK_ROWS = [
    ("2026-08-13", "回退 G2（Spec 展开门禁）",
     "重开 SC-82~SC-86 与覆盖面 B10/F5/F6；scope.md 103 行、coverage.md 1457 行重写",
     "2026-08-16"),
    ("2026-08-13", "回退 G3（方案可行门禁）",
     "重开 TASK-12~TASK-15、ADR-008，补两个契约字段 heirValidQty / userDeleted；"
     "decisions.md 131 行、tasks.md 504 行重写",
     "2026-08-16"),
]
_rw = next((p for p in phases if p["id"] == REWORK_PHASE_ID), None)
AGG["rework_h"] = _rw["eff_h"] if _rw else 0.0
AGG["rework_n"] = (_rw["n_write"] + _rw["n_bash"] + _rw["n_agent"] + _rw["n_ask"]) if _rw else 0
AGG["rework_name"] = _rw["name"] if _rw else ""
AGG["rework_win"] = f'{_rw["a"]} → {_rw["b"]}' if _rw else ""
AGG["rework_ledger"] = REWORK_LEDGER
AGG["rework_rows"] = [dict(d=a, g=b, what=c, repass=d) for a, b, c, d in REWORK_ROWS]

# ---------- 跨阶段聚合：给「可裁剪清单」当底数 ----------
# 各阶段窗口互不重叠，故同名项跨阶段相加成立（阶段内部各项重叠已在阶段层说明）。
_bk = defaultdict(lambda: [0, 0.0])
for p in phases:
    for b in p.get("nonebuckets", []):
        _bk[b["name"]][0] += b["n"]
        _bk[b["name"]][1] += b["eff_h"]
# 同一个步骤可能在两个阶段各跑一遍（首过 + 回退重过），这里按步骤 id 合并并记跑了几段
_st = {}
for p in phases:
    for s in p["steps"]:
        if s["eff_h"] <= 0:
            continue
        r = _st.setdefault(s["id"], dict(id=s["id"], name=s["name"], src=s["src"],
                                         eff_h=0.0, n_write=0, n_bash=0, n_ask=0, phases=[]))
        r["eff_h"] = round(r["eff_h"] + s["eff_h"], 2)
        r["n_write"] += s["n_write"]
        r["n_bash"] += s["n_bash"]
        r["n_ask"] += s["n_ask"]
        r["phases"].append(p["id"])

AGG = dict(
    buckets=[dict(name=k, n=v[0], eff_h=round(v[1], 2)) for k, v in
             sorted(_bk.items(), key=lambda kv: -kv[1][1])],
    steps=sorted(_st.values(), key=lambda r: -r["eff_h"]),
)
AGG["bucket_h"] = round(sum(b["eff_h"] for b in AGG["buckets"]), 2)
AGG["step_h"] = round(sum(s["eff_h"] for s in AGG["steps"]), 2)

# ---------- 返工口径：唯一信源 = 交付账本 gate-rollbacks.md ----------
# 流程是线性的：过了 Gx 就进入 Gx→Gy 这一段，窗口内的动作一律算该阶段的。
# 只有账本明确记录了「回退某道门禁」，那一段重做才另计返工。
# 该账本全文只有两行数据行，均为 2026-08-13、human-directive / requirement-change，
# 均于 2026-08-16 重过闭环：
#   ① 回退 G2 —— 重开 SC-82~SC-86 与覆盖面 B10/F5/F6（scope 103 行 / coverage 1457 行）
#   ② 回退 G3 —— 重开 TASK-12~TASK-15、ADR-008、两个契约字段
#      （HeirPosNodeBean.heirValidQty / PosUserListResp.userDeleted）
# 除这两行外，对话历史中没有任何其他回退门禁的记录。这两行圈出的返工区间，
# 就是时间轴上按门禁事件单独切出来的那一段（阶段名即「需求变更 → G2/G3 回退重过」）。
REWORK_PHASE_ID = "P8"
REWORK_LEDGER = "sdlc/deliveries/D-003-fix-succession-map-dept-headcount/gate-rollbacks.md"
REWORK_ROWS = [
    ("2026-08-13", "回退 G2（Spec 展开门禁）",
     "重开 SC-82~SC-86 与覆盖面 B10/F5/F6；scope.md 103 行、coverage.md 1457 行重写",
     "2026-08-16"),
    ("2026-08-13", "回退 G3（方案可行门禁）",
     "重开 TASK-12~TASK-15、ADR-008，补两个契约字段 heirValidQty / userDeleted；"
     "decisions.md 131 行、tasks.md 504 行重写",
     "2026-08-16"),
]
_rw = next((p for p in phases if p["id"] == REWORK_PHASE_ID), None)
AGG["rework_h"] = _rw["eff_h"] if _rw else 0.0
AGG["rework_n"] = (_rw["n_write"] + _rw["n_bash"] + _rw["n_agent"] + _rw["n_ask"]) if _rw else 0
AGG["rework_name"] = _rw["name"] if _rw else ""
AGG["rework_win"] = f'{_rw["a"]} → {_rw["b"]}' if _rw else ""
AGG["rework_ledger"] = REWORK_LEDGER
AGG["rework_rows"] = [dict(d=a, g=b, what=c, repass=d) for a, b, c, d in REWORK_ROWS]
tracks = []
for k, nm, sub in TRACKS:
    mine = [p for p in phases if p["track"] == k]
    tracks.append(dict(key=k, name=nm, sub=sub,
                       eff_h=round(sum(p["eff_h"] for p in mine), 2),
                       cal_h=round(sum(p["cal_h"] for p in mine), 2),
                       busy_h=round(sum(p["busy_h"] for p in mine), 2),
                       wait_h=round(sum(p["wait_h"] for p in mine), 2),
                       n_ask=sum(p["n_ask"] for p in mine), n_human=sum(p["n_human"] for p in mine),
                       n_agent=sum(p["n_agent"] for p in mine), n_write=sum(p["n_write"] for p in mine),
                       a=mine[0]["a"] if mine else None, b=mine[-1]["b"] if mine else None,
                       phases=[p["id"] for p in mine]))

json.dump(dict(tracks=tracks, phases=phases, wrap=wrap,
               total_eff=round(tot_eff, 2), ref_eff=ref, agg=AGG,
               n_steps=len(ALL),
               n_steps_hit=sum(1 for p in phases for s in p["steps"]
                               if s["n_write"] or s["n_bash"] or s["n_agent"] or s["n_ask"])),
          open(os.path.join(T, "timeline.json"), "w"), ensure_ascii=False)

print("阶段合计有效工时 %.2fh ｜ 主报告 %.2fh ｜ 差 %.2fh" % (tot_eff, ref, tot_eff - ref))
print("\n顶层四条轨：")
for t in tracks:
    print("  %-8s %6.2fh（干活 %5.2f / 等人 %5.2f）拍板 %3d 真人指令 %3d 派发 %3d"
          % (t["name"], t["eff_h"], t["busy_h"], t["wait_h"], t["n_ask"], t["n_human"], t["n_agent"]))
print("\n阶段明细：")
for p in phases:
    print("  %-4s %-26s %6.2fh ｜ 具名步骤 %5.2fh ｜ 未具名 %5.2fh ｜ 步骤 %d ｜ 拍板 %2d 派发 %3d 写 %4d 命令 %4d"
          % (p["id"], p["name"], p["eff_h"], p["named_h"], p["unnamed_h"],
             len(p["steps"]), p["n_ask"], p["n_agent"], p["n_write"], p["n_bash"]))
