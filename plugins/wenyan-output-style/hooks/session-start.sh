#!/usr/bin/env bash
#
# wenyan-output-style · SessionStart hook（文言极简输出风格注入）
#
# 【作用】把文言极简规则集 + 本仓补充条款作为 additionalContext 注入会话
#   （matcher * 覆盖 compact，auto-compact 后自动重注）。与 plain-talk / adhd
#   同构——风格 = 一个只做注入的插件，/plugin 里启停即切换。
#
# 【两层注入】静态规则全文在这里（SessionStart，每会话一次）；对抗「默认现代白话」
#   的一行短锚在 hooks/user-prompt-submit.sh（每轮）。文言与模型默认语体对抗强，
#   长对话只靠会话头一次注入会漂回白话，故留每轮一行。
#
# 【出处】档位定义与例句取自 caveman 插件 skills/caveman/SKILL.md 的 wenyan-ultra 档，
#   例句由繁体逐句改为简体（working-discipline 3.5 禁繁体），并补齐上游没有的
#   压缩法、禁忌、降级与产出物边界。
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
    "文言极简模式已启用。以下规则约束本会话每一次回复，包含上下文压缩之后；"
    "话题变更不失效，长对话不衰减。关闭方式：/plugin 里停用 wenyan-output-style 插件。"
)

body = "\n\n".join([HEADER, read("wenyan-ultra-rules.md"), read("project-overrides.md")])

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": body,
    }
}, ensure_ascii=False))
PYEOF

exit 0
