# -*- coding: utf-8 -*-
"""门禁事件切出的阶段窗口（互不重叠、连续覆盖全程），与主报告 7 段口径兼容。

时间戳依据：fusion / domain 两侧账本的 gate decided_at + git commit 时刻（由账本盘点核出），
落在会话记录里的最近一次动作上对齐。每段都可回溯到一个门禁事件或一次下发动作。
"""
import sys
sys.path.insert(0, "/Users/zhangq/.claude/jobs/01ddd053/tmp")
from lib import *


def ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=BJ).timestamp()


# track: 顶层时间轴归属；side: 第二/三/四条时间轴归属
PHASES = [
 dict(id="P1", track="gen",  side="fusion", name="需求转换 → G1 放行",
      sub="把原始需求文档转成结构化条目，跨域判定，G1 值不值得做",
      a=ts("2026-08-05 14:24"), b=ts("2026-08-05 17:10"),
      gate="G1 passed（fusion backlog → ready）", ev="git 856542f @08-05 17:09:47",
      stages=["f-convert", "f-g1"]),
 dict(id="P2", track="disp", side="fusion", name="fusion Define → G2 放行",
      sub="建 D-040 交付、写 scope、产 storyline 骨架",
      a=ts("2026-08-05 17:10"), b=ts("2026-08-05 20:26"),
      gate="G2 passed", ev="git 9bfbb1d @08-05 20:25:41",
      stages=["f-define", "f-g2"]),
 dict(id="P3", track="disp", side="fusion", name="fusion Design → G3 放行",
      sub="平台能力依赖识别、manual-cases、breakdown 与版本规划",
      a=ts("2026-08-05 20:26"), b=ts("2026-08-06 11:13"),
      gate="G3 passed", ev="git e98fcc1 @08-06 11:12:55",
      stages=["f-design", "f-g3"]),
 dict(id="P4", track="disp", side="fusion", name="下发 dispatch 到 domain",
      sub="写 domain backlog + upstream 物料、cascade 推主仓、通知",
      a=ts("2026-08-06 11:13"), b=ts("2026-08-06 14:08"),
      gate="dispatch 完成", ev="fusion 主仓 5a3eb84 @08-06 11:15:20",
      stages=["f-dispatch"]),
 # 原 P5「空窗 · 下发完成到开工」（08-06 14:08 → 08-10 14:01）已按要求移除：
 # 该段是请假 + 周末，按 8 小时工作制折算后有效工时仅 0.01 小时（4 个零散动作），
 # 既不构成流程耗时，也无分析价值。窗口不再参与归属，故其 0.01 小时不计入总量。
 dict(id="P6", track="dev",  side="domain", name="Supply 接收 → G1 放行",
      sub="接 upstream、写 stories、粒度校准、DoD 九项自检、建 worktree",
      a=ts("2026-08-10 14:01"), b=ts("2026-08-10 15:18"),
      gate="G1 passed（backlog → ready）", ev="git 6b09a91 @08-10 15:07:37",
      stages=["d-supply", "d-g1"]),
 dict(id="P7", track="dev",  side="domain", name="Define + Design → G2/G3 首过",
      sub="行为契约、影响面、契约与实体、任务拆分、四套测试子工作流",
      a=ts("2026-08-10 15:18"), b=ts("2026-08-12 12:42"),
      gate="G2 + G3 同批 passed", ev="git 28f9066 @08-12 12:44:00",
      stages=["d-define", "d-g2", "d-design", "d-g3"]),
 dict(id="P8", track="dev",  side="domain", name="需求变更 → G2/G3 回退重过",
      sub="08-12~13 连报三条数据问题，新增 SC-82~86 与 TASK-12~15，两道门禁翻回 pending",
      a=ts("2026-08-12 12:42"), b=ts("2026-08-16 19:41"),
      gate="G2 重过 @08-16 21:11、G3 重过 @08-16 21:43",
      ev="gate-rollbacks.md 两行 + git 95ae345 / ba2d5b5",
      stages=["d-define", "d-g2", "d-design", "d-g3"]),
 dict(id="P9", track="dev",  side="domain", name="Implement 编码实现",
      sub="按 DAG 跑 TDD、跨 task code-review、QA fan-out 生成自动化脚本",
      a=ts("2026-08-16 19:41"), b=ts("2026-08-21 15:28"),
      gate="G2/G3 两次 delta 放行（不改 decided_at）",
      ev="git 8b00648 / b6cc8b1 / 9bfc307 @08-18",
      stages=["d-impl"]),
 dict(id="P10", track="dev", side="domain", name="Verify 联调验证与缺陷修复",
      sub="环境选择、回归、UI 交互层验证、失败 TC 回环分流",
      a=ts("2026-08-21 15:28"), b=ts("2026-08-26 14:06"),
      gate="—（G4 尚未开）", ev="validation-report.md 首现 @08-26 16:42:52",
      stages=["d-verify"]),
 dict(id="P11", track="dev", side="domain", name="G4 验收放行",
      sub="追溯矩阵、validation-report、Human 验收决策",
      a=ts("2026-08-26 14:06"), b=ts("2026-08-26 18:44"),
      gate="G4 passed", ev="git c2dc40b @08-26 18:44:47",
      stages=["d-g4"]),
 dict(id="P12", track="wrap", side="domain", name="Deliver → G5（在飞，未完成）",
      sub="release-plan 草拟、G5 评审物料；G5 状态仍 pending",
      a=ts("2026-08-26 18:44"), b=END,
      gate="G5 pending", ev="deliveries/_index.md frontmatter g5.status=pending",
      stages=["d-deliver"]),
]

# fusion 侧收尾：已启动未完成，且草稿未提交。不占主时间轴的工时窗口，单列。
FUSION_WRAP = dict(
    id="P13", track="wrap", side="fusion", name="fusion 收尾 → G4/G5（未完成）",
    sub="TF 实测已跑且 verdict=pass，但 G4 Review 段未写、G5 未开、release-plan 不存在。"
        "本段在快照时点未收口，故工时计 0、不计入总量",
    gate="G4 pending / G5 pending",
    ev="fusion 侧 deliveries 账本：g4.status / g5.status 均为 pending",
    stages=["f-wrap"],
)

TRACKS = [
    ("gen",  "需求生成", "把原始需求转成结构化条目并过 G1"),
    ("disp", "需求下发", "fusion 侧走完 Define/Design/G2/G3 并分发到域"),
    ("dev",  "需求开发", "domain 侧从接收到 G4 验收放行"),
    ("wrap", "需求收尾", "两侧的 Deliver 与 G5，均未完成"),
]
