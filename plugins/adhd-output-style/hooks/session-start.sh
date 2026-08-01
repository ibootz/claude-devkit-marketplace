#!/usr/bin/env bash
#
# adhd-output-style · SessionStart hook（ADHD 友好输出风格注入）
#
# 【作用】把上游 i-have-adhd 的完整规则集 + 本仓补充条款作为 additionalContext
#   注入会话（matcher * 覆盖 compact，auto-compact 后自动重注）。与 plain-talk /
#   explanatory 一样，风格 = 一个只做 SessionStart 注入的插件，/plugin 里启停即切换。
#
# 【与上游的两点差异】
#   1. 上游是「skill 手动触发 /i-have-adhd + 手工创建 ~/.claude/.i-have-adhd-always
#      标记文件才常驻」的双通道设计。本仓拉平成纯 SessionStart 注入，与其余风格插件
#      同构——开关只有 /plugin 一个地方，不引入界面上看不见的隐藏开关。
#   2. 追加 style/project-overrides.md，解决上游 Rule 9（列表封顶 5 条）与本仓
#      working-discipline「拍板材料必须含起源/差距/影响/现场证据四要素」的冲突。
#      解法不是让 ADHD 风格让位，而是明确「四要素约束的是信息，不是形状」。
#
# 【规则原文】style/upstream-rules.md 是上游 SKILL.md 剥掉 YAML frontmatter 后的
#   正文，逐字未改，便于与上游比对。要改行为请改 project-overrides.md，不要改它。
#
# 【失败策略】注入类 hook 静默降级，绝不阻断会话启动。

set -uo pipefail

STYLE_DIR="$(dirname -- "$0")/../style" /usr/bin/python3 - <<'PYEOF' 2>/dev/null || true
import json
import os

style_dir = os.environ["STYLE_DIR"]

def read(name):
    with open(os.path.join(style_dir, name), encoding="utf-8") as f:
        return f.read().strip()

HEADER = (
    "ADHD MODE ACTIVE. The ruleset below shapes every response for the rest of "
    "this session, including after context compaction. It does not lapse when "
    "the topic changes. Turn it off by disabling the adhd-output-style plugin."
)

body = "\n\n".join([HEADER, read("upstream-rules.md"), read("project-overrides.md")])

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": body,
    }
}, ensure_ascii=False))
PYEOF

exit 0
