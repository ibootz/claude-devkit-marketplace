"""报告附录：可能的改动方案（未实施）。

与时间轴主体分离——主体讲「时间花在哪」，本模块讲「哪些能靠注入省掉」。
build() 接收主体模块的依赖，返回三份数据与渲染好的 HTML 片段。
"""


def build(ctx):
    e, n, _sh = ctx["e"], ctx["n"], ctx["sh"]
    _BH, CUT_SAVE, TL, AG = ctx["BH"], ctx["CUT_SAVE"], ctx["TL"], ctx["AG"]
    _BN = {b["name"]: b["n"] for b in AG["buckets"]}
    _PB = lambda k: round(_BH.get(k, 0), 2)
    _PN = lambda k: _BN.get(k, 0)

    # ---------- 附录数据：不改 SDLC 插件、只靠注入上下文的补丁方案 ----------
    # 本节全部是「方案」，未实施。现耗时取自实测；「可触及」与「怎么做」是判断。
    # 分界线：注入能改由 AI 执行的软性散文纪律，改不了 hook 读取的字段。


    PATCH_ENTRY = [
     dict(no="A1", name="查「流程本身怎么规定的」",
          cur=_PB("查流程本身怎么规定的"),
          ev="%d 条命令，产出 0 个交付物" % _PN("查流程本身怎么规定的"),
          reach="近全额", reach_cls="hi",
          how="把「各阶段该产什么文件、哪几步明写不可跳、两个减法字段怎么用」一次查清，"
              "固化成项目内一份查阅材料。此后遇到同类问题读这份，不再翻插件源码。",
          gate="无 hook 参与，纯 AI 自主检索行为",
          note="这段耗时全部花在读 <code>~/.claude/plugins/cache/ai-sdlc/</code> 下的 SKILL 与 rules。"
               "它不产出任何交付物，是纯粹的「为了知道该怎么做」而付的学习成本，每个新需求都要重付一次。"),
     dict(no="A2", name="Define 首步·四层产物扫描（跑了两遍）",
          cur=_sh("D1")["eff_h"], ev="%d 条命令，写文件 0 次" % _sh("D1")["n_bash"],
          reach="近全额", reach_cls="hi",
          how="把 <code>sdlc/</code> 现状（多少 Feature／行为契约／端点／实体表，各在哪）"
              "固化成一份带生成命令与计数口径的快照；回退重过时只增量核对变化部分，不整树重扫。",
          gate="<code>skills/define/SKILL.md:109</code> 是散文要求「扫描」，无 hook 校验扫描过程",
          note="注入能改的是<b>「怎么扫」</b>，改不了<b>「要不要扫」</b>——后者是 SKILL 明文步骤。"
               "但本次两遍扫描零文件产出，说明它的全部价值就是把数字装进上下文，而这正是注入能替代的。"),
     dict(no="A3", name="管 git／worktree／嵌套子模块",
          cur=_PB("管 git / worktree / 子模块"),
          ev="%d 条命令" % _PN("管 git / worktree / 子模块"),
          reach="大半", reach_cls="mid",
          how="把三层仓库拓扑与四类决策（拉最新／提子仓代码／真相流合入受保护 master／worktree 内干活）"
              "的结论固化成决策树，遇到对应场景直接照做，不每次现场重新推演。",
          gate="个别动作有硬闸（裸 <code>cd</code> 被 cd-blocker 拦），但<b>推演成本本身没有闸</b>",
          note="耗时主因不是命令慢，是每次都重新推演「此刻该动哪个仓、gitlink 提不提、"
               "worktree 里的子模块要不要恢复」。推演结论是可缓存的，冲突处置与分支决策不可缓存。"),
     dict(no="A4", name="在自己写的账本与规格里定位与复核",
          cur=_PB("在自己写的账本与规格里定位与复核"),
          ev="%d 条命令，已做全量归类实证" % _PN("在自己写的账本与规格里定位与复核"),
          reach="约半（49%）", reach_cls="mid",
          how="随产物写入增量维护一张「编号 → 文件:行号」索引（SC / TASK / BR / ADR / 端点），"
              "要引用某条时查表，不再全文搜；条数、场景数、哈希这类计数交一条校验脚本一次算全。"
              "都是工具层改造，<b>不改流程定义、不削弱任何校验</b>。",
          gate="无闸。这不是哪条纪律要求的动作，是「规格没有索引」逼出来的重复劳动",
          note="这一条的定性曾经是错的，已按实证改正。原先按桶名把它当成「写完 grep 一遍确认落盘」，"
               "据此论证「本机文件写不需回读、这段是纯开销」。对该桶 351 条命令全量归类后："
               "定位条款 197 条（56.1%）、复算条数与哈希 81 条（23.1%）、跨文件一致性核对 26 条"
               "（7.4%）、零散 41 条（11.7%）；字面的「确认落盘」按最宽口径只占 18.2%。"
               "可省比例巧合仍是约半，但解法从「放宽一条纪律」变成「加一张索引表」—— 后者不必说服"
               "任何人接受校验强度下降。"),
     dict(no="A5", name="Define·展开行为契约（跑了两遍）",
          cur=_sh("D4")["eff_h"], ev="%d 次文件写入，全程最贵的单个步骤" % _sh("D4")["n_write"],
          reach="靠顺序重排避免", reach_cls="mid",
          how="需求含统计口径（计数／聚合／去重／人数／占比）时，写行为契约<b>之前</b>先对着真实数据"
              "核一遍事实基线：该口径当前实际算出什么、边界数据现在怎么表现。核完再写契约。",
          gate="这是<b>加法</b>——多做一步前置核验，不豁免任何既有步骤、不碰任何门禁",
          note="本次第二遍是全量重做，成因是 08-12／13 才发现三条新的数据问题，而那时行为契约"
               "已按错误的数据认知写完。<b>数据事实是行为契约的地基，地基后到则上层全部重砌。</b>"),
    ]

    # 两个真正存在的减法字段。注意：都<b>不适用于本需求</b>，列出是为了说明它们能省什么、什么时候能用。
    PATCH_FIELD = [
     dict(no="F1", field="test_surface: none", need="配非空 <code>test_surface_reason</code>",
          effect="G3 豁免测试四件套（测试点／评审／用例／脚本），<b>并连带豁免另三处</b>："
                 "测试用例闭合、UI 用例下限、单测覆盖 —— 合计七处",
          src="hooks/lib/test-verification.js:110-132 判定豁免（三轴优先级 test_surface &gt; spec_level "
              "&gt; grandfathered，出处同文件 :102）；真正执行拦截的是 hooks/delivery-guard.js:401，"
              "其注释原文写明「连带豁免七处」",
          fit="不适用", fit_why="本需求改后端统计口径，有 API surface，测试面客观存在",
          use="适用于真无测试面的小需求：纯配置项调整、纯文案改动"),
     dict(no="F2", field="spec_level: L2", need="配非空 <code>downgrade_reason</code>",
          effect="横跨 G3／G4／G5 豁免七处测试类检查",
          src="hooks/lib/spec-level.js:108-117 —— 只接受 <code>L2</code> 或缺省（缺省即默认 L3）",
          fit="不适用", fit_why="限纯文档同步／配置微调；本需求 <code>feature_type: fix</code>、改产品行为",
          use="适用于纯文档同步与配置微调；<b>不要拿它当针对性解闸开关</b>——它一次扫掉七处检查，"
              "面太宽。真无测试面的诉求走 F1 更精确"),
    ]

    # 三层上限，故意不相加：口径不同、时间上重叠。
    PATCH_CEIL = [
     ("高置信可省", round(_PB("查流程本身怎么规定的") + _sh("D1")["eff_h"], 2),
      "A1＋A2 两项纯读、零产出，注入后可整段免掉", "hi"),
     ("部分可触及", round(_PB("管 git / worktree / 子模块") + _PB("在自己写的账本与规格里定位与复核"), 2),
      "A3＋A4 的上界。实际可省是其中一部分，无法给出可信折扣，故给上界", "mid"),
     ("靠顺序重排避免", round(_sh("D4")["eff_h"], 2),
      "A5。不是删掉这一步，是把它挪到数据事实核验之后，避免整段重做", "mid"),
    ]

    _RC = {"hi": "var(--s-sdlc)", "mid": "var(--s-roi)"}

    _pe = "".join(
        '<tr>'
        '<td><b>%s</b></td>'
        '<td><b>%s</b></td>'
        '<td class="num"><b>%s</b> h<div style="font-size:11px;color:var(--muted);font-weight:400;margin-top:2px">%s</div></td>'
        '<td class="nowrap"><span style="font-size:11px;padding:2px 8px;border-radius:9px;background:%s;color:#fff">%s</span></td>'
        '<td style="font-size:12px">%s'
        '<div style="color:var(--muted);margin-top:5px">机械闸：%s</div>'
        '<div style="margin-top:5px;padding-left:8px;border-left:2px solid var(--s-roi)">%s</div></td>'
        '</tr>' % (e(x["no"]), e(x["name"]), n(x["cur"], 2), e(x["ev"]),
                   _RC.get(x["reach_cls"], "var(--muted)"), e(x["reach"]),
                   x["how"], x["gate"], x["note"])
        for x in PATCH_ENTRY)

    _pf = "".join(
        '<tr>'
        '<td><b>%s</b></td>'
        '<td><code>%s</code><div style="font-size:11px;color:var(--muted);margin-top:3px">%s</div></td>'
        '<td style="font-size:12px">%s</td>'
        '<td class="nowrap"><span style="font-size:11px;padding:2px 8px;border-radius:9px;'
        'background:var(--s-fusion);color:#fff">%s</span>'
        '<div style="font-size:11px;color:var(--muted);margin-top:3px">%s</div></td>'
        '<td style="font-size:12px">%s</td>'
        '<td style="font-size:11px;color:var(--muted)">%s</td>'
        '</tr>' % (e(x["no"]), e(x["field"]), x["need"], x["effect"],
                   e(x["fit"]), x["fit_why"], x["use"], x["src"])
        for x in PATCH_FIELD)

    _pc = "".join(
        '<div class="kpi%s"><div class="v">%s<small> 小时</small></div>'
        '<div class="k">%s<br><span style="font-size:11.5px">%s</span></div></div>'
        % (" hi" if c == "hi" else "", n(v, 2), e(k), e(s))
        for k, v, s, c in PATCH_CEIL)

    PATCH_HTML = """
    <section class="axis" id="ax-patch">
      <div class="axis-h"><span class="axis-no">附</span>
        <span class="axis-t">可能的改动方案 —— 不改 SDLC 流程本身，只靠注入上下文</span></div>

      <div style="margin:2px 0 15px;padding:12px 15px;border-radius:8px;
           border:1.5px dashed #7a5af0;background:rgba(122,90,240,.07)">
        <b style="color:#7a5af0;font-size:14px">本节全部是方案，未实施。</b>
        下面每一条都<b>没有</b>落到任何文件上 —— 既不改 SDLC 插件源码，也不改本仓的规则与配置。
        列出来是为了把两件事讲清楚：<b>哪些成本靠「打补丁」真能拿到手</b>，以及<b>这条路的天花板在哪</b>。
        真要做，逐条另行拍板。
      </div>

      <p class="axis-note"><b>先讲这个方案想解决什么。</b>
      本次需求在 backlog 里带着「小 Feature」的标签，但机械层照最高完备度全量跑完了：
      账本 23 个文件约 1.38 万行、10 份审计档、22 个任务项，声明的改动落点是 20 个文件
      —— 而「小 Feature」判据写的是 1–5 个文件，差了 4 倍。
      查过之后发现原因很直接：<b>「小 Feature」是纸面上的档，机械层没有这一档。</b>三条各自独立的证据：<br>
      <b>其一，粒度这件事只活在文档层。</b>粒度标记是需求条目模板正文里的一个中文标签
      （取值「Feature／小 Feature／微改动」，写在正文而非结构化字段里），
      流程另有一份七个维度的粒度判定规范供 Define 阶段参考 ——
      <b>但门禁脚本目录下对这两者都是零命中</b>：有判定规范，无机械消费。<br>
      <b>其二，两个阶段明文写着不可跳。</b>Define 阶段所有步骤标「对 Feature 和小 Feature 均执行，无跳过」；
      Design 阶段的架构基线、任务拆分、三个测试子流程也都标「不可跳过」。<br>
      <b>其三，完备度字段只有两档。</b>它只接受「显式降一档」或「缺省即最高档」，
      <b>文档上有三档，机械层只有两档，中间那档写进去会被直接拦下</b>。<br>
      所以本次交付并不是「没按小需求做」，是<b>机械层没有小需求这个概念</b>。</p>

      <div class="caliber"><b>还有两道闸，比上面三条更直接地决定「小需求能不能走捷径」——答案是不能。</b><br>
      <b>一是流程总闸</b>（<code>delivery-guard.js</code>，挂在技能调用前）：任何交付类技能启动前先查门禁状态与工作树落点，
      门禁没过就不放行。<b>它是前面那些完备度字段的落点</b> —— 没有这道闸，字段层面的豁免逻辑根本没有执行的地方。
      报告前面只讨论了它内部读的那几个字段，没提这道闸本身，这里补上。<br>
      <b>二是源码守卫</b>（<code>business-source-guard.js</code>）：项目一旦声明了受保护的源码路径，
      不走流程直接改产品源码会被硬拦。<b>这是「小需求抄近道」最直接的那条路，机械层是封着的。</b>
      说明一句：本项目<b>当前尚未</b>声明受保护路径（会话启动时有提示：「本项目尚未武装源码守护」），
      所以这道闸此刻不生效 —— 但它的存在意味着「绕流程」不是一个可长期依赖的省时方案。</div>

      <div class="caliber"><b>这条路的边界，一句话就能划清：</b>
      注入上下文能改的是<b>由 AI 自己执行的软性纪律</b>（怎么查、查几遍、按什么顺序做、要不要回头核），
      改不了的是<b>门禁脚本读取的字段</b>（写文件前后触发的机械校验）。
      前者是「AI 读到什么就照什么做」，后者是「脚本读到什么值就给什么结论」，注入进不了后者的输入。<br>
      <b>这条边界本次当场被验证过一次：</b>试着往仓内规则目录写一份材料，
      在文件落盘之前就被一个门禁脚本拦下 —— 理由是正文里出现了交付编号，而规则类文件不允许引用交付编号。
      它判的是<b>文本形态</b>，不是语义，也不看这份材料想干什么。
      这恰好说明：机械闸不参与讨论，注入改不动它。<br>
      <b>还有一个容量上限：</b>常驻加载的规则区有硬预算（约束类文件 800 行、全部规则 1800 行），
      超预算的写入会在落盘前被拦。所以注入材料不能无限堆 ——
      <b>「每次都要遵守的约束」放常驻区，「需要时才查的材料」必须外置</b>，否则前者会被后者挤掉。</div>

      <h3 style="font-size:14px;margin:20px 0 6px">一、五个可以入手的地方（按实测耗时排）</h3>
      <table><thead><tr><th>编号</th><th>成本源</th><th class="num">实测耗时</th><th>可触及</th>
        <th>怎么做 · 为什么能／不能</th></tr></thead>
      <tbody>%s</tbody></table>

      <h3 style="font-size:14px;margin:22px 0 6px">二、流程里真正存在的两个减法开关（本需求都用不上）</h3>
      <p class="axis-note">这两个是<b>机械层认的</b>字段，不是注入 —— 写对了门禁真的会少查几项。
      列在这里是因为它们常被误解：一是以为还有个「中间档」（没有，写了会被拦），
      二是以为可以拿来给任意小需求解闸（不行，各有适用范围）。<b>本次需求两个都不适用。</b></p>
      <table><thead><tr><th>编号</th><th>字段</th><th>省掉什么</th><th>本需求</th>
        <th>什么时候能用</th><th>出处</th></tr></thead>
      <tbody>%s</tbody></table>

      <h3 style="font-size:14px;margin:22px 0 6px">三、比纯注入更硬一档：自己加一个校验钩子（仍不改插件）</h3>
      <div class="caliber">
      上面第一节那五条都靠 AI 自觉执行 —— <b>AI 忘了就没人拦</b>。想要机械保障、又不改插件，还剩一条路：
      在本仓自己的配置里挂一个项目级的<b>写后校验钩子</b>，读交付账本里声明的改动落点数量，
      与需求条目上标的粒度阈值比对，超出就给一条提醒。<br>
      <b>可行性已核过：</b>本仓配置文件当前<b>没有</b>钩子配置段，加一段不会与现有配置冲突。<br>
      <b>它能解决的正是本次那个 4 倍偏差</b>：粒度是 2026-08-10 评估一次之后再没重估过，
      而落点从 5 个以内涨到 20 个的过程中，没有任何一处会提醒「这个需求已经不是小需求了」。
      提醒不是阻断 —— 该往上走就往上走，只是要求这件事被看见一次。</div>

      <h3 style="font-size:14px;margin:22px 0 6px">四、天花板：三层数，故意不相加</h3>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:4px 0 14px">
        %s
      </div>
      <div class="caliber">
      <b>为什么不给一个合计数：</b>三层的口径不同 —— 第一层是可整段免掉的，第二层是上界（实际能省其中一部分，
      但拿不出可信折扣），第三层不是省掉而是避免重做。相加会得到一个看着精确、实际站不住的数。<br>
      <b>更要紧的是天花板本身：</b>前面裁剪清单逐步打折后的上限是 %s 小时（占全程 %s%%），
      <b>注入这条路不可能超过它</b> —— 因为注入<b>不删掉任何一个产物、不跳过任何一个步骤</b>，
      它只能让「做同一件事时少走弯路」。<br>
      <b>而全程最大的那一块，这条路只能碰到一半：</b>账本记录的那次门禁回退重过 %s 小时（占全程 %s%%）
      —— 2026-08-13 需求侧改口径，G2 与 G3 同时回退，四份规格产物整份重做。
      注入上下文能减少<b>重做时的弯路</b>（少读几遍规范、少纠几次口径），但改不了<b>「回退就得整份重写」这条粒度假设</b>本身：
      产品意图只变了两个数，scope／coverage／decisions／tasks 仍是整份重写。
      要真正吃掉这一块，动的是「回退时哪些产物必须整份重写、哪些可以只改差异」的判据，不是注入能覆盖的范围。</div>
    </section>
    """ % (_pe, _pf, _pc, n(CUT_SAVE, 2), n(CUT_SAVE / TL["total_eff"] * 100, 1),
           n(AG["rework_h"], 2), n(AG["rework_h"] / TL["total_eff"] * 100, 1))
    return PATCH_ENTRY, PATCH_FIELD, PATCH_CEIL, PATCH_HTML
