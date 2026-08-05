#!/usr/bin/env bash
#
# insight-addon · SessionStart hook（教学洞察附加件）
#
# 【作用】给会话追加一条「何时给 ★ Insight 框」的规则，不定义整体行文风格。
#   设计目标是**可叠加**：它只增加一种额外输出，不规定句子长短、不规定用段落还是
#   列表，因此与 plain-talk-output-style / adhd-output-style 等完整风格插件同时
#   开启不会互相打架。这与官方 explanatory-output-style 不同——后者是一整套风格
#   （含"可超出通常长度限制"的授权），开着它再开别的风格就会冲突。
#
# 【内容来源】★ Insight 的格式与"聚焦本代码库特有门道、不讲通用编程概念"这两点，
#   取自官方 explanatory-output-style 插件的注入原文
#   （~/.claude/plugins/marketplaces/claude-plugins-official/plugins/
#     explanatory-output-style/hooks-handlers/session-start.sh 第 10 行）。
#   触发条件（何时该给、何时不该给）是本仓补充的——官方原文只说"before and after
#   writing code, always provide"，在问答类轮次里会塞出无意义的洞察框。
#
# 【失败策略】注入类 hook 静默降级，绝不阻断会话启动。

set -uo pipefail

/usr/bin/python3 - <<'PYEOF' 2>/dev/null || true
import json

STYLE = """本会话附加"教学洞察"：特定时刻多输出一个洞察框，不改变当前输出风格的句长/段落/列表要求。

触发（两条都满足才给，宁缺毋滥）：
1. 本轮做了非平凡技术判断——写/改代码、定位根因、做架构或方案取舍、读懂不直观的实现。
2. 存在这个代码库或这次改动特有的门道（通用编程知识不算）。

纯问答、状态汇报、执行命令、调格式、复述用户已知的事，一律不给。

格式（三行原样照抄，分隔线长度不变）：
`★ Insight ─────────────────────────────────────`
[2-3 条洞察，每条一行，一句话说完]
`─────────────────────────────────────────────────`

做完判断/写完代码后当场给，不攒到末尾。一轮最多一个框；框内每条一句话，不展开成段落——叠加简短类风格（plain-talk/adhd 等）时不受其约束。"""

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": STYLE,
    }
}, ensure_ascii=False))
PYEOF

exit 0
