#!/usr/bin/env bash
#
# wenyan-output-style · UserPromptSubmit hook（每轮短锚）
#
# 【作用】每轮注一行，对抗「回落现代白话」的漂移。静态规则全文不在这里——它在
#   SessionStart 注入里（hooks/session-start.sh），每轮重复注入全文只会白烧上下文。
#
# 【为什么需要每轮】文言与模型默认语体正面对抗，属于「对抗 system prompt 的段落」，
#   实测这类约束只放 SessionStart 会在长对话里衰减。参照 caveman 上游同样的两层设计。
#
# 【改动纪律】这一行是每轮成本，加内容前先问「不加会不会漂」。不会漂的写进
#   style/wenyan-ultra-rules.md，不要往这里堆。
#
# 【失败策略】注入类 hook 静默降级，绝不阻断本轮。

set -uo pipefail

/usr/bin/python3 - <<'PYEOF' 2>/dev/null || true
import json

LINE = (
    "文言极简模式生效中：文言语法、字形简体、省主语去系词用单字动词；"
    "代码/命令/报错/标识符/行号原样；安全告警与不可逆确认逐段退回白话；"
    "落盘产出物（代码、commit、md、子代理 prompt）一律白话。"
)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": LINE,
    }
}, ensure_ascii=False))
PYEOF

exit 0
