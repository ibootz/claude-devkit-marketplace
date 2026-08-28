# -*- coding: utf-8 -*-
"""移植到新项目时的配置改点清单（D-003 值为实例，非默认值）。

本文件不被执行——流水线脚本按「参考实现原样入仓」原则不抽参，
移植时按本清单逐文件改字面量。每项标注：文件 / D-003 原值 / 语义。
"""

CONFIG = {

    # ---------- lib.py（口径微积分：会话、时间窗、日历） ----------
    "lib.DIRS": {
        "原值": [
            "-Users-zhangq-Workspace-xx-domain-sp-xxstar-ai-spbk-work",            # 主会话目录名
            "-Users-zhangq-Workspace-xx-domain-sp-xxstar-ai-spbk-work--sdlc-worktrees-D-003-fix-succession-map-dept-headcount",  # delivery worktree 会话
            # + fusion 侧目录（需求转换发生地）
        ],
        "语义": "scan/calc 只认这些目录（目录名 = projects 下项目路径的 / 换 -）。漏一个就少一段工时",
    },
    "lib.START": {"原值": "datetime(2026, 8, 5, 14, 24)", "语义": "scope 起点（fusion conversion 时刻）"},
    "lib.END":   {"原值": "datetime(2026, 8, 26, 18, 44)", "语义": "scope 终点（G4 验收放行时刻）"},
    "lib.WORK_H": {"原值": "(8, 19)", "语义": "工作时段 08:00–19:00"},
    "lib.DAY_CAP": {"原值": "8", "语义": "每日有效工时封顶"},
    "lib.OFF_DAYS": {"原值": "周末 + 2026-08-07（请假）", "语义": "不计工时的日子；改这里必须重验守恒"},

    # ---------- phases.py（阶段窗口：门禁事件切窗） ----------
    "phases.PHASES": {
        "原值": "11 个阶段 dict（P1..P12，P5 空窗已移除），每段 a/b/gate/ev/stages/track/side",
        "语义": "全量重写。a/b = 窗口起止（由 gate decided_at + git commit 时刻对齐）；"
                "stages = 本阶段包含的步骤组 key；track = 四条轨归属；side = domain/fusion 匹配池。"
                "窗口必须互不重叠且连续覆盖，否则守恒必炸",
    },

    # ---------- steps_def.py（96 步锚点） ----------
    "steps_def.DOMAIN / FUSION": {
        "原值": "每步 (stage_key, 说明, 必做, src, {f/a/b/q 锚点})",
        "语义": "全量重写。src 必须逐条可指到插件 SKILL/rules 的 file:line；"
                "f=写文件路径片段、a=agent/命令文本关键词、b=命令特征、q=拍板问题关键词。"
                "锚点决定 named 归属——锚太宽抢别阶段事件，太窄 named 偏低",
    },

    # ---------- build_timeline.py（匹配与分桶） ----------
    "build_timeline.ALL": {"原值": "domain 步骤先于 fusion 步骤", "语义": "顺序即匹配优先级，勿动"},
    "build_timeline.BUCKETS": {"原值": "7 桶关键词表", "语义": "按新项目命令形态重写；桶名只描述内容不描述机制推断（见 bucket-audit）"},
    "build_timeline.classify": {"原值": "十四类别优先级链", "语义": "write 按路径、bash 按首词+关键词；顺序即优先级"},

    # ---------- gen_timeline.py / gen_md.py（叙事与裁剪） ----------
    "gen_timeline.OUT": {"原值": "docs/2026-08-26-短需求全流程耗时与ROI分析.html", "语义": "HTML 产物路径（直写，覆盖即生效）"},
    "gen_md.OUT": {"原值": "docs/…-数据底稿.md", "语义": "底稿产物路径"},
    "gen_md.OLD": {"原值": "docs/2026-08-26-短需求交付耗时分析（需求下发起）.md", "语义": "先行报告路径，存在则其结论被本底稿取代"},
    "gen_timeline.CUTS": {"原值": "C1-C6 + R1/R2 红线", "语义": "裁剪清单全重写；折扣须逐类实证加权（见 calibers.md §7）"},
    "patch_section.PATCH_ENTRY": {"原值": "A1-A4 注入方案", "语义": "只写「如果」，不落仓"},

    # ---------- scan.py ----------
    "scan.OUT": {"原值": "工作区目录", "语义": "events.jsonl 输出目录（回归时 sed 成独立验证目录）"},

    # ---------- align.py ----------
    "align.apply_drop": {"原值": "drop P5（0.01h）", "语义": "移除某阶段时的总量对齐清单；清空则不 drop"},
}

# 回归门：改任何脚本后全链重跑，diff 底稿 md vs 冻结基准。
# D-003 基准：/Users/zhangq/.claude/jobs/recovered/md_fixture.md（627 行）
# 已知残差（活 jsonl 漂移所致，见 references/pitfalls.md §5）：
#   需求开发轨真人指令 105→108、P1 unnamed 1.57→1.58、FC3/FD2/FG2/FS2/FS3/FG3
#   六步骤的窗口内 ask/bash 计数、42.49→42.48 —— 共 9 事件归属 + 2 处 0.01 传播
