# -*- coding: utf-8 -*-
"""四条时间轴版报告：顶层四轨 → fusion 下发 → domain 开发 → fusion 收尾。

每个阶段可点击，弹出该阶段的步骤级时间轴（对照 AI-SDLC 流程定义的明细步骤），
每个步骤可再展开，看 AI 与人各自做了什么、改了哪些文件、ROI 如何。
既有的深度分析（额外产出 / ROI 措施 / 理想场景 / 等待分桶）全部下沉进弹层。
"""
import json, os, sys, html
sys.path.insert(0, "/Users/zhangq/.claude/jobs/01ddd053/tmp")

T = "/Users/zhangq/.claude/jobs/01ddd053/tmp"
OUT = "/Users/zhangq/Workspace/xx/domain/sp/xxstar-ai-spbk-work/docs/2026-08-26-短需求全流程耗时与ROI分析.html"

TL = json.load(open(os.path.join(T, "timeline.json"), encoding="utf-8"))
D = json.load(open(os.path.join(T, "report-data.json"), encoding="utf-8"))
TT, ID, RO, WD, MA, ME = D["totals"], D["ideal"], D["roi"], D["waitdetail"], D["machine"], D["meta"]

sys.path.insert(0, T)
from align import apply_drop

DROP = apply_drop(TT, ID, TL)


def e(s):
    return html.escape(str(s), quote=False)


def n(v, d=1):
    return f"{v:,.{d}f}"


# ---------- 额外产出按发生阶段归位（下沉进弹层） ----------
EXTRA = [
 ("E1", "P10", "继任地图「继任者」筛选的选人抽屉把权限码传成空串，候选人列表只剩当前登录人自己",
  "产品缺陷", "测试提单", "提交 b4ec6ba（前端 userFilter.vue）"),
 ("E2", "P10", "画布把授权部门无条件展开为「该部门及全部后代」，越权显示未授权的兄弟部门",
  "健壮性", "测试提单", "提交 3d9e79d15 + d66090717（后端）"),
 ("E3", "P9", "守护测试结构性假绿：断言落在整份 XML 上，被文件里的注释文本满足即通过，删掉真正的 SQL 也不判红",
  "工程质量", "AI 主动发现", "提交 bf2abc3f6（审查条目 CR-001）"),
 ("E4", "P9", "授权部门集合展开后仍用列表线性查找做节点级权限标记，复杂度由 O(n) 变 O(n×m)",
  "工程质量", "AI 主动发现", "提交 bf2abc3f6（审查条目 CR-003）"),
 ("E5", "P9", "部门/岗位类型入参缺越界校验——规格写明非法值应拒绝，实现里越界值被默默当「非部门」处理",
  "健壮性", "AI 主动发现", "提交 bf2abc3f6（新增校验 + 专项测试）"),
 ("E6", "P9", "卡片展开后的继任者名单未过滤已禁用/已删除账号，与卡片上的人数字段口径分家（写 1 人、点开列 2 人）",
  "产品缺陷", "来源不明", "提交 78cd3fdf3（后端两个端点）"),
 ("E7", "P9", "顶部汇总端点长期使用第三套判据、与画布和学员端口径不一致；核实发现它已无任何前端消费方",
  "工程质量", "AI 主动发现", "提交 b4188f6dd + c3aaeb903（TASK-23）"),
 ("E8", "P10", "继任者列表「状态」列把已删除账号误显示为「启用」，新增「已删除」文案分支并把弱断言升级为精确断言",
  "产品缺陷", "本人实测发现", "提交 2e88953 + 规格仓 6c1ffe8（TASK-13/22）"),
 ("E9", "P8", "学员端继任部门列表的机构隔离缺测试证明（防护已存在），补行为场景与测试点，并补上架构文档缺失的多租户标记",
  "规格补齐", "产品答复引发", "规格仓 6c1ffe8（TASK-20）"),
 ("E10", "P10", "前端初始化用 Promise.all，任一子任务失败即整条链 reject、Vue 不挂载、页面白屏；改为 allSettled",
  "产品缺陷", "来源不明", "提交 7cf9ef6（前端 main.js）"),
 ("E11", "P10", "验证阶段撞上浏览器自动化内核下载阻塞，绕法沉淀为仓内可执行配置 + 说明文档，避免下一个人重撞",
  "工程质量", "AI 主动发现", "提交 4489bdb（父仓 tests/browser/）"),
]

# ---------- ROI 措施按阶段归位 ----------
ROIS = [
 ("R1", "P6", "下发产物直接进需求定义，取消域仓二次整理", RO["r1_h"], "待实施",
  "08-10 14:01–15:06 实测：域仓把已下发的需求又 triage / refine 了一遍"),
 ("R2", "P8", "人工实测前移到首轮需求定义之前", RO["r2_h"], "待实施",
  f"08-14~16 门禁联审重过实测 {n(RO['r2_h'],2)} 小时（08-13 新报三条问题触发 G2/G3 双回退）"),
 ("R3", "*", "拍板批量化：逐条「继续下一个任务」→ 攒批一次问", round(WD["gap_over30_h"] / 2, 2), "部分已实施",
  f"机器等人回话超 30 分钟的 {WD['gap_over30_n']} 次共 {n(WD['gap_over30_h'],2)} 小时，按可压缩一半计"),
 ("R4", "P4", "下发流程加进度可见性，消掉「走到哪一步了」的空转询问", 1.5, "待实施",
  "环节 1 长挂起里有 3 次为纯进度询问"),
 ("R5", "*", "后台助手并行执行", RO["r5_h"], "已实现",
  f"累加 {n(MA['sub_sum_h'],1)} → 并集 {n(MA['sub_union_h'],1)} 小时"),
 ("R6", "*", "后台一致性检查无人值守", RO["r4_h"], "已实现",
  f"{RO['r4_n']} 次自动执行共 {n(RO['r4_h'],2)} 小时，全落在无人时段"),
]

TRACK_C = {"gen": "var(--s-spec)", "disp": "var(--s-fusion)", "dev": "var(--s-sdlc)", "wrap": "var(--muted)"}

# ---------- 组装给前端的数据 ----------
PH = {}
for p in TL["phases"]:
    q = dict(p)
    q["extras"] = [dict(k=k, s=s, c=c, src=src, ev=ev) for k, ph, s, c, src, ev in EXTRA if ph == p["id"]]
    q["rois"] = [dict(k=k, s=s, h=h, st=st, ev=ev) for k, ph, s, h, st, ev in ROIS if ph == p["id"]]
    PH[p["id"]] = q
W = dict(TL["wrap"])
W["extras"], W["rois"] = [], []
W["eff_h"] = W["busy_h"] = W["wait_h"] = W["named_h"] = W["unnamed_h"] = 0.0
W["none_n"] = 0
W["n_write"] = W["n_bash"] = W["n_agent"] = W["n_ask"] = W["n_human"] = W["n_files"] = 0
W["top_files"], W["humans"], W["breakdown"] = [], [], []
W["nonebuckets"], W["nb_h"], W["nb_n"] = [], 0.0, 0
W["a"] = W["b"] = "—"
W["cal_h"] = 0.0
PH["P13"] = W

GLOBAL_ROI = [dict(k=k, s=s, h=h, st=st, ev=ev) for k, ph, s, h, st, ev in ROIS if ph == "*"]

AG = TL["agg"]
_BH = {b["name"]: b["eff_h"] for b in AG["buckets"]}
_SH = {s["id"]: s for s in AG["steps"]}


def _sh(sid):
    return _SH.get(sid, dict(eff_h=0.0, n_write=0, n_bash=0, phases=[], src="—", name=sid))


# 可裁剪清单。每条：现耗时取自实测，「怎么改」与「保守可省」是判断，红线两条固定不碰。
# 保守可省一律取实测耗时的一个折扣，折扣理由写在 why 里，不给拍脑袋的绝对数。
CUTS = [
 dict(no="C1", cls="机制", name="在几千行规格里反复定位条款、复算条数",
      src="无单一出处。规格账本自身几千行、编号散落其间，而工具链不提供「编号 → 行号」索引，"
          "每次引用某条都得全文重搜一遍",
      cur=_BH.get("在自己写的账本与规格里定位与复核", 0),
      save=round(_BH.get("在自己写的账本与规格里定位与复核", 0) * .49, 2),
      how="产物写入时增量维护一张「编号 → 文件:行号」索引（SC / TASK / BR / ADR / 端点），"
          "引用时查表而不是全文搜；条数、场景数、哈希这类计数由一条校验脚本一次算全，"
          "不再逐项现敲。两者都是工具层改造，不改任何流程定义、不削弱校验强度。",
      why="按 49% 计，是对该桶 351 条命令全量归类后的加权结果，不是拍的："
          "定位条款 56.1% × 可省 60%（查表替代全文搜，仍要读那一段）＋"
          "复算条数与哈希 23.1% × 可省 50%（脚本能算，期望值对不对仍要判断）＋"
          "跨文件一致性核对 7.4% × 0%（属修复闭环，一条不能省）＋零散 11.7% × 30%。",
      risk="不碰红线"),
 dict(no="C2", cls="机制", name="worktree 与嵌套子模块的手工对齐",
      src="knowledge/worktree-operations.md ＋ 本仓 14 个 submodule 的嵌套拓扑",
      cur=_BH.get("管 git / worktree / 子模块", 0), save=round(_BH.get("管 git / worktree / 子模块", 0) * .6, 2),
      how="把「建 worktree → 对齐 gitlink → 逐层提交子模块」这套固定动作封成一条命令，不再每次现敲。",
      why="按六成计：固定动作可脚本化，冲突处置与分支决策仍要现场判断。",
      risk="不碰红线"),
 dict(no="C3", cls="步骤", name="三个测试子工作流串行三轮（明写「不可跳」）",
      src="skills/design/SKILL.md:221 / :228 / :236 —— 2T1 test-points、2T2 test-review、2T3 test-case",
      cur=round(_sh("XT1")["eff_h"] + _sh("XT2")["eff_h"] + _sh("XT3")["eff_h"], 2),
      save=round((_sh("XT1")["eff_h"] + _sh("XT2")["eff_h"] + _sh("XT3")["eff_h"]) * .55, 2),
      how="给 fix 类、且影响面 ≤ 若干端点的交付定一档合并规则：三轮并作一轮，评审内嵌不单开。",
      why="按 55% 计：合并省掉两次上下文重载与两次产物落盘，用例设计本身的思考量不省。",
      risk="不碰红线（不属 G1-G5，是 Design 内部子流程）"),
 dict(no="C4", cls="步骤", name="上下文加载·四层产物扫描跑了两遍",
      src="skills/define/SKILL.md:109 —— 本次在首过与回退重过各跑一次，0 写文件、%d 条命令"
          % _sh("D1")["n_bash"],
      cur=_sh("D1")["eff_h"], save=round(_sh("D1")["eff_h"] * .6, 2),
      how="扫描结果落进交付目录做快照，回退重过时只增量核对变化部分，不整树重扫。",
      why="按六成计：重过那次的扫描绝大部分是重复劳动，但变更点仍需重新确认。",
      risk="不碰红线"),
 dict(no="C5", cls="步骤", name="交付账本 frontmatter 由 AI 手写",
      src="skills/define/SKILL.md:600 —— 步骤 9 · 更新 deliveries/_index.md frontmatter",
      cur=_sh("D9")["eff_h"], save=round(_sh("D9")["eff_h"] * .7, 2),
      how="frontmatter 的字段值全部可从账本与 git 机械派生，改由脚本生成 + AI 只审一遍。",
      why="按七成计：机械字段可全自动，少数判断型字段（lifecycle / spec_level）仍要人定。",
      risk="不碰红线"),
 dict(no="C6", cls="返工", name="需求变更后 Define／Design 整段重跑",
      src="G2/G3 回退重过机制 —— 08-12~13 三条数据问题触发，P8 整段 17.71 小时",
      cur=round(sum(_sh(k)["eff_h"] for k in ("D3", "D4", "D6", "D35", "D9")), 2),
      save=round(sum(_sh(k)["eff_h"] for k in ("D3", "D4", "D6", "D35", "D9")) * .35, 2),
      how="回退时按受影响的行为契约做定向重跑，不把 Define 五个步骤整体推倒重来。",
      why="按 35% 计：本次新增 SC-82~86 确实要重写一部分契约，但 scope／contracts 大部分未变仍被重写。",
      risk="不碰红线（G2/G3 仍然照过，只改重跑范围）"),
 dict(no="R1", cls="红线", name="G1-G5 五道门禁", src="rules/flow-lifecycle.md 门禁体系明细",
      cur=round(sum(_sh(k)["eff_h"] for k in ("G1", "G2", "G3", "G4")), 2), save=0.0,
      how="保留。", why="你已定的红线，不进裁剪范围。", risk="红线，不裁"),
 dict(no="R2", cls="红线", name="本体知识库回填", src="/sdlc:ontology 产出，供后续需求取准确知识",
      cur=0.0, save=0.0,
      how="保留。", why="你已定的红线，不进裁剪范围。本次窗口内未单独计时。", risk="红线，不裁"),
]
CUT_SAVE = round(sum(c["save"] for c in CUTS), 2)

AXES = [
 dict(key="top", no="轴 一", title="需求全生命周期 · 四段主轨",
      note="从 fusion 侧把原始需求转成结构化条目开始，到 domain 侧 G4 验收放行为止。"
           "点任一段进入该段的阶段轴；四段合计即全程有效工时 "
           f"{n(TL['total_eff'],2)} 小时。",
      nodes=[dict(kind="track", **t) for t in TL["tracks"]]),
 dict(key="disp", no="轴 二", title="fusion 侧 · 需求生成与下发（G1 → G3 → dispatch）",
      note="fusion 是需求的总装线：把原始需求判域、拆解、产出规格骨架，再切片下发给具体业务域。"
           "这一段走完 G1／G2／G3 三道门禁。点任一阶段看它内部的明细步骤。",
      nodes=[dict(kind="phase", **PH[i]) for i in ("P1", "P2", "P3", "P4")]),
 dict(key="dev", no="轴 三", title="domain 侧 · 需求开发（Supply → G1 → Define/Design → G2/G3 → Implement → Verify → G4 → G5）",
      note="业务域接到切片后的完整交付流水线。这条轴占全程 "
           f"{n(TL['tracks'][2]['eff_h']/TL['total_eff']*100,0)}% 的工时，"
           "也是可裁剪空间的主要所在。点任一阶段进入它的明细步骤轴。",
      nodes=[dict(kind="phase", **PH[i]) for i in ("P6", "P7", "P8", "P9", "P10", "P11", "P12")]),
 dict(key="wrap", no="轴 四", title="fusion 侧 · 需求收尾（G4 / G5，未完成）",
      note="域侧 G4 放行后，fusion 侧还要跑一次跨域实测、过 G4／G5、回填版本矩阵、发出交付通知。"
           "本需求这一段已启动但未收口，草稿停在未提交的工作区。",
      nodes=[dict(kind="phase", **PH["P13"])]),
]

DATA = json.dumps(dict(phases=PH, axes=[{k: v for k, v in a.items() if k != "nodes"} for a in AXES],
                       groi=GLOBAL_ROI,
                       ideal=ID, tot=TT, wd=WD, ma=MA,
                       total_eff=TL["total_eff"], n_steps=TL["n_steps"], n_steps_hit=TL["n_steps_hit"]),
                  ensure_ascii=False)
# 命令原文里可能出现 </ 或 <!--，直接嵌进 <script> 会提前闭合标签、把整个 body 吞掉。
# JSON 允许 \/ 转义，解析回来仍是 /，故这里只改字节形态、不改语义。
DATA = DATA.replace("</", "<\\/").replace("<!--", "<\\u0021--")

CSS = """
:root{
  --s-fusion:#eb6834; --s-sdlc:#1baf7a; --s-roi:#2a78d6; --s-spec:#7a5af0;
  --neutral-idle:#dcdad2; --surface-1:#ffffff; --surface-2:#f7f6f3; --surface-3:#efeee9;
  --ink:#1f1e1c; --ink-2:#4a4843; --muted:#8a8781; --line:#e3e1db;
  --ok:#1baf7a; --warn:#d99000; --bad:#d64545;
}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-2);color:var(--ink);
  font:15px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1280px;margin:0 auto;padding:36px 24px 80px}
header{margin-bottom:28px}
h1{font-size:29px;line-height:1.35;margin:0 0 8px;letter-spacing:-.01em}
.sub{color:var(--ink-2);font-size:15px;max-width:900px}
.meta{color:var(--muted);font-size:12.5px;margin-top:10px}

/* 顶部指标 */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px;margin:22px 0 8px}
.kpi{background:var(--surface-1);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kpi .v{font-size:26px;font-weight:650;letter-spacing:-.02em;line-height:1.2}
.kpi .v small{font-size:13px;font-weight:500;color:var(--muted);margin-left:3px}
.kpi .k{font-size:12.5px;color:var(--muted);margin-top:3px}
.kpi.hi .v{color:var(--s-sdlc)}

.caliber{background:var(--surface-1);border:1px solid var(--line);border-left:3px solid var(--s-roi);
  border-radius:8px;padding:12px 16px;margin:14px 0 30px;font-size:13.5px;color:var(--ink-2)}
.caliber b{color:var(--ink)}

/* 时间轴 */
.axis{margin:0 0 42px}
.axis-h{display:flex;align-items:baseline;gap:12px;margin-bottom:6px}
.axis-no{font-size:12px;font-weight:650;color:var(--surface-1);background:var(--ink);
  border-radius:4px;padding:2px 8px;letter-spacing:.04em;flex:none}
.axis-t{font-size:19px;font-weight:640;letter-spacing:-.01em}
.axis-note{color:var(--ink-2);font-size:13.5px;margin:0 0 16px;max-width:980px}

.rail{position:relative;background:var(--surface-1);border:1px solid var(--line);border-radius:12px;
  padding:20px 18px 16px;overflow-x:auto}
.rail-line{position:absolute;left:18px;right:18px;top:56px;height:2px;background:var(--line);border-radius:1px}
.nodes{position:relative;display:flex;gap:10px;min-width:min-content}
.node{flex:1 1 0;min-width:132px;background:var(--surface-1);border:1px solid var(--line);
  border-radius:10px;padding:0;cursor:pointer;text-align:left;font:inherit;color:inherit;
  transition:border-color .13s,box-shadow .13s,transform .13s;position:relative}
.node:hover{border-color:var(--s-roi);box-shadow:0 3px 14px rgba(42,120,214,.13);transform:translateY(-2px)}
.node:focus-visible{outline:2px solid var(--s-roi);outline-offset:2px}
.node .dot{position:absolute;left:50%;top:-24px;width:11px;height:11px;border-radius:50%;
  transform:translateX(-50%);border:2.5px solid var(--surface-1);box-shadow:0 0 0 1px var(--line)}
.node .body{padding:14px 13px 12px}
.node .no{font-size:11px;font-weight:700;letter-spacing:.06em;color:var(--muted)}
.node .nm{font-size:13.5px;font-weight:640;line-height:1.4;margin:3px 0 8px;min-height:2.6em}
.node .h{font-size:22px;font-weight:660;letter-spacing:-.02em;line-height:1.1}
.node .h small{font-size:12px;font-weight:500;color:var(--muted);margin-left:2px}
.node .when{font-size:11.5px;color:var(--muted);margin-top:2px;font-variant-numeric:tabular-nums}
.node .prop{height:5px;border-radius:3px;background:var(--surface-3);margin-top:9px;overflow:hidden}
.node .prop i{display:block;height:100%;border-radius:3px}
.node .mini{display:flex;gap:9px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin-top:8px}
.node .mini b{color:var(--ink-2);font-weight:600}
.node .cta{border-top:1px solid var(--line);padding:7px 13px;font-size:11.5px;color:var(--s-roi);font-weight:600}
.node.void{background:repeating-linear-gradient(135deg,var(--surface-2),var(--surface-2) 5px,transparent 5px,transparent 10px);
  border-style:dashed}
.node.void .h{color:var(--muted)}
.badge{display:inline-block;font-size:10.5px;font-weight:650;padding:1px 6px;border-radius:4px;
  background:var(--surface-3);color:var(--ink-2);vertical-align:2px;margin-left:5px}
.badge.gate{background:rgba(27,175,122,.14);color:#127a55}
.badge.pend{background:rgba(217,144,0,.16);color:#8a5c00}

/* 弹层 */
.mask{position:fixed;inset:0;background:rgba(24,23,21,.5);backdrop-filter:blur(2px);
  display:none;z-index:60;padding:26px}
.mask.on{display:block}
.modal{background:var(--surface-2);border-radius:14px;max-width:1120px;margin:0 auto;height:100%;
  display:flex;flex-direction:column;overflow:hidden;box-shadow:0 24px 70px rgba(0,0,0,.3)}
.m-head{background:var(--surface-1);border-bottom:1px solid var(--line);padding:16px 22px;flex:none}
.m-top{display:flex;align-items:flex-start;gap:14px}
.m-title{flex:1;min-width:0}
.m-title h3{margin:0;font-size:19px;font-weight:650;letter-spacing:-.01em}
.m-title .s{color:var(--ink-2);font-size:13px;margin-top:4px}
.m-tools{display:flex;gap:6px;flex:none;align-items:center}
.btn{border:1px solid var(--line);background:var(--surface-1);border-radius:7px;padding:5px 11px;
  font:inherit;font-size:12.5px;cursor:pointer;color:var(--ink-2)}
.btn:hover{border-color:var(--s-roi);color:var(--s-roi)}
.btn.x{font-size:16px;line-height:1;padding:6px 10px}
.m-kpis{display:flex;gap:9px;flex-wrap:wrap;margin-top:13px}
.mk{background:var(--surface-2);border:1px solid var(--line);border-radius:7px;padding:7px 11px;min-width:96px}
.mk .v{font-size:17px;font-weight:650;letter-spacing:-.01em;line-height:1.2}
.mk .k{font-size:11px;color:var(--muted)}
.m-body{overflow-y:auto;padding:20px 22px 30px;flex:1;font-size:calc(14px * var(--mz,1))}

.mnote{background:var(--surface-1);border:1px solid var(--line);border-radius:9px;padding:12px 15px;
  font-size:13px;color:var(--ink-2);margin-bottom:16px}
.mnote b{color:var(--ink)}
.mnote.warn{border-left:3px solid var(--warn)}
.mnote.ok{border-left:3px solid var(--ok)}

.mh{font-size:14.5px;font-weight:650;margin:22px 0 10px;display:flex;align-items:center;gap:8px}
.mh:first-child{margin-top:0}
.mh .c{font-size:11.5px;font-weight:500;color:var(--muted)}

/* 步骤时间轴（弹层内） */
.steps{position:relative;padding-left:22px}
.steps:before{content:"";position:absolute;left:6px;top:6px;bottom:6px;width:2px;background:var(--line)}
.step{position:relative;background:var(--surface-1);border:1px solid var(--line);border-radius:9px;
  margin-bottom:8px;overflow:hidden}
.step:before{content:"";position:absolute;left:-21px;top:17px;width:9px;height:9px;border-radius:50%;
  background:var(--neutral-idle);border:2px solid var(--surface-2);box-shadow:0 0 0 1px var(--line)}
.step.hit:before{background:var(--s-sdlc)}
.step-h{display:flex;align-items:center;gap:11px;padding:11px 13px;cursor:pointer;user-select:none}
.step-h:hover{background:var(--surface-2)}
.step-id{font-size:11px;font-weight:700;letter-spacing:.04em;color:var(--surface-1);background:var(--ink-2);
  border-radius:4px;padding:2px 6px;flex:none;font-variant-numeric:tabular-nums}
.step.hit .step-id{background:var(--s-sdlc)}
.step-nm{flex:1;min-width:0;font-size:13.5px;font-weight:600;line-height:1.45}
.step-nm .src{display:block;font-size:11px;font-weight:400;color:var(--muted);margin-top:2px;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.step-bar{flex:none;width:132px}
.step-bar .t{height:6px;border-radius:3px;background:var(--surface-3);overflow:hidden}
.step-bar .t i{display:block;height:100%;background:var(--s-sdlc);border-radius:3px}
.step-bar .v{font-size:11.5px;color:var(--ink-2);text-align:right;margin-top:3px;font-variant-numeric:tabular-nums}
.step-tags{flex:none;display:flex;gap:5px;align-items:center}
.tg{font-size:10.5px;font-weight:650;padding:2px 7px;border-radius:4px;white-space:nowrap}
.tg.must{background:rgba(214,69,69,.12);color:#a83333}
.tg.opt{background:var(--surface-3);color:var(--ink-2)}
.tg.skip{background:rgba(138,135,129,.16);color:var(--muted)}
.tg.cut{background:rgba(217,144,0,.16);color:#8a5c00}
.step-more{font-size:15px;color:var(--muted);flex:none;transition:transform .15s}
.step.open .step-more{transform:rotate(90deg)}
.step-d{display:none;border-top:1px solid var(--line);padding:13px;background:var(--surface-2)}
.step.open .step-d{display:block}

.roi{display:grid;grid-template-columns:repeat(auto-fit,minmax(88px,1fr));gap:7px;margin-bottom:12px}
.roi div{background:var(--surface-1);border:1px solid var(--line);border-radius:7px;padding:7px 9px}
.roi .v{font-size:16px;font-weight:650;line-height:1.2}
.roi .k{font-size:10.5px;color:var(--muted)}

.flow{border-left:2px solid var(--line);margin-left:5px;padding-left:13px}
.ev{display:flex;gap:9px;padding:3px 0;font-size:12.5px;line-height:1.5;position:relative}
.ev:before{content:"";position:absolute;left:-17px;top:11px;width:6px;height:6px;border-radius:50%;background:var(--line)}
.ev.human:before{background:var(--s-fusion)}
.ev .t{flex:none;color:var(--muted);font-size:11px;font-variant-numeric:tabular-nums;width:74px;padding-top:1px}
.ev .w{flex:none;font-size:10.5px;font-weight:650;border-radius:3px;padding:1px 5px;height:fit-content;margin-top:1px}
.ev .w.ai{background:rgba(42,120,214,.12);color:#1c5ea8}
.ev .w.human{background:rgba(235,104,52,.14);color:#a8441a}
.ev .s{flex:1;min-width:0;word-break:break-word;color:var(--ink-2)}
.ev .s code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;
  background:var(--surface-3);border-radius:3px;padding:1px 4px}

.files{display:flex;flex-wrap:wrap;gap:5px;margin-top:4px}
.fl{font-size:11px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--surface-1);
  border:1px solid var(--line);border-radius:5px;padding:2px 7px;color:var(--ink-2)}
.fl b{color:var(--ink);font-weight:600}

table{width:100%;border-collapse:collapse;font-size:12.5px;background:var(--surface-1);
  border:1px solid var(--line);border-radius:8px;overflow:hidden}
th{text-align:left;font-weight:640;font-size:11.5px;color:var(--muted);padding:8px 11px;
  border-bottom:1px solid var(--line);background:var(--surface-2)}
td{padding:8px 11px;border-bottom:1px solid var(--line);vertical-align:top;line-height:1.55}
tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.nowrap{white-space:nowrap}

.hum{background:var(--surface-1);border:1px solid var(--line);border-radius:8px;padding:11px 13px}
.hum .l{display:flex;gap:10px;padding:5px 0;border-bottom:1px dashed var(--line);font-size:12.5px}
.hum .l:last-child{border-bottom:none}
.hum .l .t{flex:none;color:var(--muted);font-size:11px;width:80px;font-variant-numeric:tabular-nums;padding-top:2px}
.hum .l .s{flex:1;color:var(--ink-2);white-space:pre-wrap;word-break:break-word}

.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:12px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}

footer{margin-top:34px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}
@media (max-width:820px){
  .wrap{padding:22px 14px 60px}
  h1{font-size:23px}
  .rail{padding:20px 14px 14px}
  .node{min-width:158px;flex:none}
  .mask{padding:0}
  .modal{border-radius:0}
  .step-bar{width:78px}
  .step-h{flex-wrap:wrap}
}
@media print{.mask{display:none!important}.node{break-inside:avoid}}
"""

JS = r"""
const DATA = __DATA__;
const $ = (s, r) => (r || document).querySelector(s);
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const nn = (v, d) => (v == null ? "—" : Number(v).toLocaleString("zh-CN", {minimumFractionDigits: d, maximumFractionDigits: d}));

const KIND = {write:["写文件","ai"], bash:["跑命令","ai"], agent:["派后台助手","ai"], ask:["向人拍板","human"]};

function verdict(s){
  const hit = s.n_write + s.n_bash + s.n_agent + s.n_ask;
  if (!hit) return s.must ? ["skip","本次无留痕"] : ["skip","本次未执行"];
  if (s.must) return ["must","流程必做"];
  if (s.eff_h >= 0.5) return ["cut","可裁剪候选"];
  return ["opt","可选步骤"];
}

function evLine(x){
  const k = KIND[x.k] || ["动作","ai"];
  let s = esc(x.s);
  if (x.k === "write") s = "<code>" + s + "</code>" + (x.x ? " <span style='color:var(--muted)'>" + esc(x.x) + "</span>" : "");
  if (x.k === "ask")  s = "<b>" + s + "</b>";
  return `<div class="ev ${k[1]}"><span class="t">${esc(x.t)}</span>`
       + `<span class="w ${k[1]}">${k[0]}</span><span class="s">${s}</span></div>`;
}

function stepHTML(s, mx){
  const [cls, lab] = verdict(s);
  const hit = s.n_write + s.n_bash + s.n_agent + s.n_ask;
  const pct = mx > 0 ? Math.max(s.eff_h / mx * 100, s.eff_h > 0 ? 3 : 0) : 0;
  const dens = s.eff_h > 0 ? (s.n_write + s.n_bash) / s.eff_h : 0;
  let d = `<div class="roi">
     <div><div class="v">${nn(s.eff_h,2)}<small style="font-size:11px;color:var(--muted)"> h</small></div><div class="k">投入工时</div></div>
     <div><div class="v">${s.n_ask}</div><div class="k">向人拍板</div></div>
     <div><div class="v">${s.n_write}</div><div class="k">写文件次数</div></div>
     <div><div class="v">${s.n_files}</div><div class="k">触及文件</div></div>
     <div><div class="v">${s.n_agent}</div><div class="k">派后台助手</div></div>
     <div><div class="v">${s.n_bash}</div><div class="k">跑命令</div></div>
     <div><div class="v">${s.eff_h > 0 ? nn(dens,0) : "—"}</div><div class="k">每小时动作数</div></div>
     <div><div class="v">${s.days.length}</div><div class="k">跨天数</div></div>
   </div>`;
  if (s.days.length) d += `<div style="font-size:12px;color:var(--muted);margin-bottom:9px">发生于 ${s.days.join("、")}｜首个动作 ${esc(s.a||"—")}｜末个动作 ${esc(s.b||"—")}</div>`;
  if (s.files && s.files.length)
    d += `<div style="font-size:12px;font-weight:600;margin:10px 0 5px">改了哪些文件</div><div class="files">`
       + s.files.map(f => `<span class="fl">${esc(f)}</span>`).join("") + `</div>`;
  if (s.events && s.events.length){
    d += `<div style="font-size:12px;font-weight:600;margin:13px 0 6px">AI 与人各自做了什么<span style="font-weight:400;color:var(--muted)">（按时间序，最多列 70 条）</span></div>`
       + `<div class="flow">` + s.events.map(evLine).join("") + `</div>`;
  } else {
    d += `<div style="font-size:12px;color:var(--muted);margin-top:10px">`
       + (hit ? "本步骤有动作计数但无可展示的明细条目。" : "会话记录里没有可归属到本步骤的动作 —— 要么本次实际跳过了它，要么它的产出并入了相邻步骤、没留下独立痕迹。")
       + `</div>`;
  }
  return `<div class="step ${hit ? "hit" : ""}">
    <div class="step-h" onclick="this.parentNode.classList.toggle('open')">
      <span class="step-id">${esc(s.id)}</span>
      <span class="step-nm">${esc(s.name)}<span class="src">${esc(s.src)}</span></span>
      <span class="step-bar"><span class="t"><i style="width:${pct.toFixed(1)}%"></i></span>
        <span class="v">${s.eff_h > 0 ? nn(s.eff_h,2) + " h" : "无留痕"}</span></span>
      <span class="step-tags"><span class="tg ${cls}">${lab}</span></span>
      <span class="step-more">›</span>
    </div><div class="step-d">${d}</div></div>`;
}

function open(id){
  const p = DATA.phases[id];
  if (!p) return;
  const mx = Math.max(0.01, ...p.steps.map(s => s.eff_h));
  const hitN = p.steps.filter(s => s.n_write + s.n_bash + s.n_agent + s.n_ask).length;
  const cutN = p.steps.filter(s => verdict(s)[0] === "cut").length;
  const skipN = p.steps.filter(s => verdict(s)[0] === "skip").length;

  let b = "";
  // 阶段自身的口径说明
  b += `<div class="mnote"><b>阶段窗口</b>：${esc(p.a)} → ${esc(p.b)}，
    日历跨度 ${nn(p.cal_h,1)} 小时，按八小时工作制折算有效工时 <b>${nn(p.eff_h,2)} 小时</b>
    （其中机器在跑 ${nn(p.busy_h,2)}、等人回话 ${nn(p.wait_h,2)}）。<br>
    <b>边界依据</b>：${esc(p.gate)}｜证据 ${esc(p.ev)}</div>`;

  if (p.eff_h > 0 && p.unnamed_h > 0){
    const r = p.named_h / p.eff_h * 100;
    b += `<div class="mnote warn"><b>两层口径，先说清楚再看数</b>：本阶段 ${nn(p.eff_h,2)} 小时里，
      能归到下面某个具名步骤的是 <b>${nn(p.named_h,2)} 小时（${r.toFixed(0)}%）</b>，
      其余 <b>${nn(p.unnamed_h,2)} 小时</b>是跨步骤的协调、读码、讨论与重跑 —— 它们真实发生，
      但没留下能指向某一个流程步骤的痕迹，因此<b>不摊派到步骤上、也不隐藏</b>。
      所以下面每个步骤的时长相加会小于阶段总量，这是设计如此，不是漏算。</div>`;
  }

  // 步骤时间轴
  if (p.steps.length){
    b += `<div class="mh">流程明细步骤时间轴<span class="c">共 ${p.steps.length} 步，${hitN} 步有实测痕迹`
       + (cutN ? `，${cutN} 步为可裁剪候选` : "") + (skipN ? `，${skipN} 步本次无留痕` : "") + `</span></div>`;
    b += `<div class="mnote" style="font-size:12.5px">步骤清单不是我列的，是从 AI-SDLC 插件自身的
      SKILL / rules 文件里逐条抄出来的，每步后面的灰色小字就是它在插件里的出处行号。
      时长来自会话记录（账本只到天粒度，切不到步骤层）。点任一步骤展开它的明细。</div>`;
    b += `<div class="steps">` + p.steps.map(s => stepHTML(s, mx)).join("") + `</div>`;
  }

  // 本阶段顺手修掉的问题
  if (p.extras.length){
    b += `<div class="mh">本阶段顺手修掉的额外问题<span class="c">${p.extras.length} 条，不在原始需求范围内</span></div>`;
    b += `<table><thead><tr><th>编号</th><th>问题</th><th class="nowrap">性质</th><th class="nowrap">谁发现的</th><th>证据</th></tr></thead><tbody>`
       + p.extras.map(x => `<tr><td><b>${esc(x.k)}</b></td><td>${esc(x.s)}</td>`
       + `<td class="nowrap">${esc(x.c)}</td><td class="nowrap">${esc(x.src)}</td>`
       + `<td style="color:var(--muted);font-size:11.5px">${esc(x.ev)}</td></tr>`).join("")
       + `</tbody></table>`;
  }

  // 本阶段的 ROI 措施
  if (p.rois.length){
    b += `<div class="mh">本阶段可省的时间<span class="c">不触碰门禁与本体回填两条红线</span></div>`;
    b += `<table><thead><tr><th>编号</th><th>措施</th><th class="num">可省</th><th class="nowrap">状态</th><th>实测依据</th></tr></thead><tbody>`
       + p.rois.map(x => `<tr><td><b>${esc(x.k)}</b></td><td>${esc(x.s)}</td>`
       + `<td class="num"><b>${nn(x.h,2)}</b> h</td><td class="nowrap">${esc(x.st)}</td>`
       + `<td style="color:var(--muted);font-size:11.5px">${esc(x.ev)}</td></tr>`).join("")
       + `</tbody></table>`;
  }

  // 人在本阶段说了什么
  if (p.humans && p.humans.length){
    b += `<div class="mh">人在本阶段说了什么<span class="c">去重后的决策指令原文，共 ${p.n_human} 条</span></div>`;
    b += `<div class="hum">` + p.humans.map(h =>
      `<div class="l"><span class="t">${esc(h.t)}</span><span class="s">${esc(h.s)}</span></div>`).join("") + `</div>`;
  }

  // 高频文件
  if (p.top_files && p.top_files.length){
    b += `<div class="mh">本阶段改得最多的文件<span class="c">共触及 ${p.n_files} 个文件</span></div><div class="files">`
       + p.top_files.map(f => `<span class="fl">${esc(f.f)} <b>×${f.n}</b></span>`).join("") + `</div>`;
  }

  $("#m-title").innerHTML = esc(p.name) + (p.gate && p.gate !== "—" ? ` <span class="badge gate">${esc(p.gate)}</span>` : "");
  $("#m-sub").textContent = p.sub;
  $("#m-kpis").innerHTML = [
    ["有效工时", nn(p.eff_h,2) + " h", p.eff_h > 0 ? "var(--s-sdlc)" : "var(--muted)"],
    ["日历跨度", nn(p.cal_h/24,1) + " 天", ""],
    ["机器在跑", nn(p.busy_h,2) + " h", ""],
    ["等人回话", nn(p.wait_h,2) + " h", p.wait_h > p.busy_h ? "var(--s-fusion)" : ""],
    ["向人拍板", p.n_ask + " 次", ""],
    ["派后台助手", p.n_agent + " 个", ""],
    ["写文件", p.n_write + " 次", ""],
    ["跑命令", p.n_bash + " 次", ""],
  ].map(([k,v,c]) => `<div class="mk"><div class="v"${c?` style="color:${c}"`:""}>${v}</div><div class="k">${k}</div></div>`).join("");
  $("#m-body").innerHTML = b;
  $("#m-body").scrollTop = 0;
  $("#mask").classList.add("on");
  document.body.style.overflow = "hidden";
}

function shut(){ $("#mask").classList.remove("on"); document.body.style.overflow = ""; }
let MZ = 1;
function zoom(d){ MZ = Math.min(1.6, Math.max(.8, MZ + d)); $("#m-body").style.setProperty("--mz", MZ); }

document.addEventListener("click", ev => {
  const nb = ev.target.closest(".nbrow");
  if (nb) {
    const r = $("#nb" + nb.dataset.nb);
    if (r) r.style.display = r.style.display === "none" ? "table-row" : "none";
    return;
  }
  const n = ev.target.closest("[data-phase]");
  if (n) { open(n.dataset.phase); return; }
  if (ev.target.id === "mask") shut();
});
document.addEventListener("keydown", ev => {
  if (ev.key === "Escape") shut();
  if ($("#mask").classList.contains("on")){
    if (ev.key === "+" || ev.key === "=") zoom(.1);
    if (ev.key === "-") zoom(-.1);
  }
});
"""


def node_html(x, mx, kind):
    if kind == "track":
        c = TRACK_C[x["key"]]
        pid = {"gen": "P1", "disp": "P2", "dev": "P9", "wrap": "P13"}[x["key"]]
        pct = x["eff_h"] / mx * 100 if mx else 0
        return f"""
      <a class="node" href="#ax-{'disp' if x['key'] in ('gen','disp') else ('dev' if x['key']=='dev' else 'wrap')}">
        <span class="dot" style="background:{c}"></span>
        <span class="body">
          <span class="no">{e(x['name'])}</span>
          <span class="nm" style="display:block">{e(x['sub'])}</span>
          <span class="h" style="display:block">{n(x['eff_h'],2)}<small> 小时</small></span>
          <span class="when">{e(x['a'] or '—')} → {e(x['b'] or '—')}</span>
          <span class="prop"><i style="width:{pct:.1f}%;background:{c}"></i></span>
          <span class="mini"><span>机器在跑 <b>{n(x['busy_h'],1)}h</b></span><span>等人 <b>{n(x['wait_h'],1)}h</b></span>
            <span>拍板 <b>{x['n_ask']}</b></span><span>助手 <b>{x['n_agent']}</b></span></span>
        </span>
        <span class="cta">跳到这一段的阶段轴 ↓</span>
      </a>"""
    p = x
    c = TRACK_C[p["track"]]
    void = p["eff_h"] <= 0.02
    pct = p["eff_h"] / mx * 100 if mx else 0
    gate = p.get("gate") or "—"
    bd = ""
    if "pending" in gate or "未完成" in p["name"]:
        bd = '<span class="badge pend">未收口</span>'
    elif gate != "—" and "passed" in gate or "放行" in gate or "重过" in gate:
        bd = '<span class="badge gate">门禁</span>'
    return f"""
      <button class="node{' void' if void else ''}" data-phase="{p['id']}" type="button">
        <span class="dot" style="background:{'var(--neutral-idle)' if void else c}"></span>
        <span class="body">
          <span class="no">{p['id']}{bd}</span>
          <span class="nm" style="display:block">{e(p['name'])}</span>
          <span class="h" style="display:block">{n(p['eff_h'],2)}<small> 小时</small></span>
          <span class="when">{e(p['a'])} → {e(p['b'])}</span>
          <span class="prop"><i style="width:{pct:.1f}%;background:{'var(--neutral-idle)' if void else c}"></i></span>
          <span class="mini"><span>步骤 <b>{len(p['steps'])}</b></span><span>拍板 <b>{p['n_ask']}</b></span>
            <span>助手 <b>{p['n_agent']}</b></span><span>写 <b>{p['n_write']}</b></span></span>
        </span>
        <span class="cta">点开看这一段的明细步骤轴 →</span>
      </button>"""


def axis_html(ax):
    kinds = ax["nodes"][0]["kind"]
    mx = max([x["eff_h"] for x in ax["nodes"]] + [0.01])
    nodes = "".join(node_html(x, mx, x["kind"]) for x in ax["nodes"])
    return f"""
  <section class="axis" id="ax-{ax['key']}">
    <div class="axis-h"><span class="axis-no">{e(ax['no'])}</span><span class="axis-t">{e(ax['title'])}</span></div>
    <p class="axis-note">{ax['note']}</p>
    <div class="rail"><div class="rail-line"></div><div class="nodes">{nodes}</div></div>
  </section>"""


sp = ID["split"]
KPI = [
 ("全程有效工时", f"{n(TT['eff_h'],2)}<small> 小时</small>", f"折合 {n(TT['eff_d'],2)} 个工作日当量", 1),
 ("对照传统估时", f"{n(TT['eff_d']/1.5,1)}<small> 倍</small>", "基准 1.5 人天（仅开发段）", 0),
 ("挤掉异常等待后", f"{n(ID['eff_cons']/8,2)}<small> 天当量</small>", f"即 {n(ID['x_cons'],1)} 倍，见轴内说明", 1),
 ("流程明细步骤", f"{TL['n_steps_hit']}<small> / {TL['n_steps']}</small>", "有实测痕迹 / 流程共定义", 0),
 ("向人拍板", f"{sum(p['n_ask'] for p in TL['phases'])}<small> 次</small>", f"机器等人合计 {n(TT['wait_h'],1)} 小时", 0),
 ("后台助手", f"{TT['sub_n']}<small> 个</small>", f"并集耗时 {n(MA['sub_union_h'],1)} 小时", 0),
]
kpis = "".join(
    f'<div class="kpi{" hi" if h else ""}"><div class="v">{v}</div><div class="k">{e(k)}<br>'
    f'<span style="font-size:11.5px">{e(s)}</span></div></div>' for k, v, s, h in KPI)

groi = "".join(
    f"<tr><td><b>{e(x['k'])}</b></td><td>{e(x['s'])}</td><td class='num'><b>{n(x['h'],2)}</b> h</td>"
    f"<td class='nowrap'>{e(x['st'])}</td><td style='color:var(--muted);font-size:11.5px'>{e(x['ev'])}</td></tr>"
    for x in GLOBAL_ROI)

from patch_section import build as _build_patch
PATCH_ENTRY, PATCH_FIELD, PATCH_CEIL, PATCH_HTML = _build_patch(dict(
    e=e, n=n, sh=_sh, BH=_BH, CUT_SAVE=CUT_SAVE, TL=TL, AG=AG))

HTML = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>短需求全流程耗时与 ROI · 四条时间轴</title>
<style>{CSS}</style></head>
<body data-palette="#eb6834,#1baf7a,#2a78d6,#7a5af0">
<div class="wrap">
<header>
  <h1>一个「改两个数字」的需求，走完 AI-SDLC 全流程花了多久</h1>
  <p class="sub">需求：继任地图部门人数统计口径订正（<code>fix-succession-map-dept-headcount</code>）。
  本页不分章节，只给四条<b>可下钻的时间轴</b>：点任一阶段，弹出该阶段内部按 AI-SDLC 流程定义逐步拆开的明细时间轴；
  再点任一步骤，看这一步里 AI 做了什么、人做了什么、改了哪些文件、ROI 如何。</p>
  <p class="meta">统计口径：工作日 {ME['work_from']}–{ME['work_to']} 之间的实际活动窗口，每日封顶 {ME['day_cap_h']} 小时；
  周末只计实际活跃段；零活动日整日剔除；08-07（周五，请假）整日剔除。
  含后台助手执行时间（按并集，非线性相加）。起点 {ME['start']}（fusion 侧需求转换），终点 {ME['end']}（域侧 G4 验收放行）。
  快照 {ME['snapshot']}。</p>
</header>

<div class="kpis">{kpis}</div>

<div class="caliber"><b>两层口径，先讲清楚再看数。</b>
阶段层是<b>守恒</b>的：四条轴上所有阶段的有效工时相加 = {n(TL['total_eff'],2)} 小时 = 全程总量，一分不多一分不少，
因为阶段边界由门禁事件（gate 决策时刻 + 提交时刻）切定，互不重叠。
（下发完成到开工之间那段请假加周末已整段移除，折算后仅 {n(DROP,2)} 小时，不构成流程耗时，也已从总量中扣除。）
步骤层是<b>可归因子集</b>：只统计能明确指向某一个流程步骤的动作，
剩下的跨步骤协调、读码、讨论与重跑在弹层里单列为「未留具名痕迹」，<b>不摊派、不隐藏</b>。
另需说明：<b>账本切不到步骤层</b>（一次提交可跨两个子步骤、账本文字是天粒度），
所以阶段边界取自账本门禁事件，步骤时长取自会话记录 —— 两个信源，各管各的。</div>

{"".join(axis_html(a) for a in AXES)}

<section class="axis">
  <div class="axis-h"><span class="axis-no">全局</span><span class="axis-t">不落在单一阶段的三项已实现优化</span></div>
  <p class="axis-note">下面三项贯穿全程、无法归到某一个阶段，因此单列。分阶段的可省项已下沉到对应阶段的弹层里。</p>
  <table><thead><tr><th>编号</th><th>措施</th><th class="num">影响</th><th>状态</th><th>实测依据</th></tr></thead>
  <tbody>{groi}</tbody></table>
  <div class="caliber" style="margin-top:14px">
  <b>理想场景对照</b>：把「机器等人超过 20 分钟」视为异常，统一压到 10 分钟，全程 {n(ID['eff_cur'],2)} → {n(ID['eff_new'],2)} 小时。
  但其中 {sp.get('lunch_n', ID['kind_n'].get('lunch', 0))} 段压在午休上、{ID['kind_n'].get('pre',0)} 段贴着开工前，这两类压不动 ——
  <b>只压在岗时段那 {ID['kind_n'].get('onduty',0)} 段</b>才是流程真能改的，得到<b>保守可达 {n(ID['eff_cons'],2)} 小时
  ＝ {n(ID['eff_cons']/8,2)} 个工作日当量 ＝ {n(ID['x_cons'],1)} 倍</b>，省 {n(ID['saved_cons_h'],2)} 小时（{n(ID['saved_cons_pct'],1)}%）。
  对外引用请用这个保守数，不要用理想值。</div>
</section>

<section class="axis">
  <div class="axis-h"><span class="axis-no">收尾</span><span class="axis-t">哪个阶段、哪一步可以裁 —— 逐条对到 AI-SDLC 的出处</span></div>
  <p class="axis-note">前面四条轴回答「时间花在哪」，这一段回答「哪些能省」。每条都指向 AI-SDLC 里一处具体要求或一个具体机制，
  现耗时来自实测，「保守可省」一律是对实测值打折后的数，折扣理由写在表里 —— 不给拍脑袋的绝对数。
  两条红线按你定的原则原样保留：<b>G1-G5 五道门禁</b>与<b>本体知识库回填</b>不进裁剪范围。</p>

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin:4px 0 16px">
    {"".join(f'<div class="kpi"><div class="v">{n(v,2)}<small> 小时</small></div><div class="k">{e(k)}<br><span style="font-size:11.5px">{e(s)}</span></div></div>' for k, v, s in [
      ("归不到步骤的机制性开销", AG["bucket_h"], f"{sum(b['n'] for b in AG['buckets'])} 条命令，占全程 {n(AG['bucket_h']/TL['total_eff']*100,1)}%"),
      ("账本记录的返工", AG["rework_h"], f"唯一一次门禁回退（G2＋G3 同时回退），占全程 {n(AG['rework_h']/TL['total_eff']*100,1)}%"),
      ("流程步骤本身", AG["step_h"], f"{len(AG['steps'])} 个步骤有实测留痕"),
      ("按下表保守可省", CUT_SAVE, f"占全程 {n(CUT_SAVE/TL['total_eff']*100,1)}%，红线两项不计"),
    ])}
  </div>

  <table><thead><tr><th>编号</th><th>类别</th><th>裁什么</th><th class="num">现耗时</th><th class="num">保守可省</th><th>怎么改 · 折扣理由</th></tr></thead>
  <tbody>
  {"".join(
    f'<tr><td><b>{e(c["no"])}</b></td>'
    f'<td><span style="font-size:11px;padding:2px 7px;border-radius:9px;background:'
    + ("var(--s-roi)" if c["cls"] == "机制" else "var(--s-sdlc)" if c["cls"] == "步骤" else "var(--s-fusion)" if c["cls"] == "返工" else "var(--muted)")
    + f';color:#fff">{e(c["cls"])}</span></td>'
    f'<td><b>{e(c["name"])}</b><div style="font-size:11px;color:var(--muted);margin-top:3px">出处：{e(c["src"])}</div></td>'
    f'<td class="num">{n(c["cur"],2)} h</td>'
    f'<td class="num">' + (f'<b style="color:var(--s-sdlc)">{n(c["save"],2)} h</b>' if c["save"] > 0 else '<span style="color:var(--muted)">—</span>') + '</td>'
    f'<td style="font-size:12px">{e(c["how"])}<div style="color:var(--muted);margin-top:3px">{e(c["why"])} · <b>{e(c["risk"])}</b></div></td></tr>'
    for c in CUTS)}
  </tbody></table>

  <div class="caliber" style="margin-top:14px">
  <b>这几个数不能直接相加。</b>机制性开销 {n(AG['bucket_h'],2)} 小时与流程步骤 {n(AG['step_h'],2)} 小时是
  <b>同一段时间的两种切法</b>（各自按活跃段并集计时，彼此在时间上重叠），相加会超过全程 {n(TL['total_eff'],2)} 小时。
  账本返工 {n(AG['rework_h'],2)} 小时是<b>另一个维度</b>——它是阶段层的一整段，已经含在守恒的 {n(TL['total_eff'],2)} 小时里，
  不要再叠加到前两者上。要看守恒的那一层，回上面四条轴的阶段合计。<br>
  <b>最大的单一发现：</b>全程 {n(AG['rework_h'],2)} 小时（{n(AG['rework_h']/TL['total_eff']*100,1)}%）耗在
  <b>唯一一次门禁回退重过</b>上 —— 2026-08-13 需求侧改口径，G2 与 G3 同时回退，08-16 才重新过闸。
  这一段里 {PH['P8']['n_write']} 次写文件、{PH['P8']['n_bash']} 条命令，重写的是
  scope 103 行、coverage 1457 行、decisions 131 行、tasks 504 行 ——
  <b>产品意图只改了两个数，四份规格产物整份重做</b>。证据在 <code>{AG['rework_ledger']}</code>，不是估的。
  它指向的不是某条 SKILL 写错了，是<b>规格产物的体量与需求体量脱钩</b>：改两个数与改一个模块，
  要重写的 spec 行数几乎一样多。裁单个步骤最多省下表里那 {n(CUT_SAVE,2)} 小时；
  这一层要动的是「回退时哪些产物必须整份重写」的粒度判据。</div>
</section>

{PATCH_HTML}

<footer>
  数据来源：本机 Claude Code 会话记录（{ME['sessions_req']} 个会话，含 {TT['sub_n']} 个后台助手的独立记录）
  + fusion／domain 两侧 sdlc 账本的门禁事件与 git 提交时刻。
  流程步骤清单逐条抄自 AI-SDLC 插件自身的 SKILL／rules 文件，弹层里每步都带出处行号。<br>
  已知需在下一版对齐的三处：fusion 转换回写实际发生在 08-05 14:46（14:24 是本人首条指令，两者不冲突但应并列写明）；
  下发落地时刻应为 08-06 11:12~11:15；fusion 侧验证报告的文件时间 08-26 12:19 早于域侧 G4 的 18:44，此处时序待核。
</footer>
</div>

<div class="mask" id="mask">
  <div class="modal" role="dialog" aria-modal="true">
    <div class="m-head">
      <div class="m-top">
        <div class="m-title"><h3 id="m-title"></h3><div class="s" id="m-sub"></div></div>
        <div class="m-tools">
          <button class="btn" onclick="zoom(-.1)" title="缩小（-）">A−</button>
          <button class="btn" onclick="zoom(.1)" title="放大（+）">A＋</button>
          <button class="btn x" onclick="shut()" title="关闭（Esc）">✕</button>
        </div>
      </div>
      <div class="m-kpis" id="m-kpis"></div>
    </div>
    <div class="m-body" id="m-body"></div>
  </div>
</div>

<script>{JS.replace("__DATA__", DATA)}</script>
</body></html>
"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w", encoding="utf-8").write(HTML)
print("写出 %s ｜ %d 字节" % (OUT, len(HTML.encode("utf-8"))))
print("四条轴：%s" % " / ".join(a["no"] + " " + str(len(a["nodes"])) + " 节点" for a in AXES))
print("阶段合计 %.2fh ｜ 主报告 %.2fh" % (TL["total_eff"], TT["eff_h"]))
