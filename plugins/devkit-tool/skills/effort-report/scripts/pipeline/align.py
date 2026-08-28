# -*- coding: utf-8 -*-
"""把「下发完成到开工」那段请假加周末从全局总量里一并扣掉，使全报告只有一个总量口径。

背景：该段（08-06 14:08 → 08-10 14:01）原是时间轴上的一个阶段（P5），
折算后有效工时 0.01 小时（4 个零散动作）。按要求从时间轴移除后，
阶段层合计 = 94.16，而早先算出的全局总量仍含那 0.01 小时 = 94.17。

若不处理，报告会同时出现 94.16 与 94.17 两个数。这里按同一个差额把全局
总量与理想场景三档一并下调，使全部数字对齐到 94.16。
差额不写死，由「全局总量 − 阶段层合计」现算，阶段划分再变也不会失准。
"""


def apply_drop(TT, ID, TL):
    drop = round(TT["eff_h"] - TL["total_eff"], 2)
    if drop <= 0:
        return 0.0

    # 那 0.01 小时是实际动作（机器在跑），故只从 busy 侧扣，等人时长不动。
    TT["eff_h"] = round(TT["eff_h"] - drop, 2)
    TT["busy_h"] = round(TT["busy_h"] - drop, 2)
    TT["eff_d"] = round(TT["eff_h"] / 8, 2)

    # 该段不含异常等待，压缩情景对它无影响，故三档同额下调。
    for k in ("eff_cur", "eff_new", "eff_cons"):
        ID[k] = round(ID[k] - drop, 2)
    ID["day_cur"] = round(ID["eff_cur"] / 8, 2)
    ID["day_new"] = round(ID["eff_new"] / 8, 2)
    ID["day_cons"] = round(ID["eff_cons"] / 8, 2)
    ID["saved_h"] = round(ID["eff_cur"] - ID["eff_new"], 2)
    ID["saved_pct"] = round(ID["saved_h"] / ID["eff_cur"] * 100, 1)
    ID["saved_cons_h"] = round(ID["eff_cur"] - ID["eff_cons"], 2)
    ID["saved_cons_pct"] = round(ID["saved_cons_h"] / ID["eff_cur"] * 100, 1)

    # 三档各自的「机器在跑 + 等人回话」要仍然等于该档有效工时，故同样只扣 busy 侧。
    sp = ID.get("split") or {}
    for k in ("b_cur", "b_new", "b_cons"):
        if k in sp:
            sp[k] = round(sp[k] - drop, 2)
    return drop
