#!/usr/bin/env bash
#
# task-keeper · SessionStart hook（主会话三岔口路由注入）
#
# 【作用】会话开始（含每次 auto-compact 后，matcher * 覆盖 compact 来源）给主会话
#   注入「任务分诊三岔口」与「决策打包主会话侧职责」。**纯注入，零拦截**——分诊是
#   语义判断，按 hook 克制原则只能做软约束（见仓库 .claude/rules/project/hook-restraint.md）。
#
# 【opt-in 分档】判据是项目里 `.keeper/` 目录的存在性（从 cwd 向上找，到 .git 止）：
#   · 未启用：只注入 ≤300 字符的一句话介绍 + 启用方式，不铺开细节。
#   · 已启用：注入完整三岔口 + 决策打包摘要 + 指针，目标 ≤1600 字符、硬上限 2000
#     （回归测试 H18 断言）。
#
# 【为什么不用 python3 - <<'EOF' 内联】heredoc 会占用 python 的 stdin，SessionStart
#   事件 JSON（含 cwd）就读不到了——实测踩过。逻辑在 lib/keeper_routing.py。
#
# 【失败策略】注入类 hook 静默降级，绝不阻断会话启动。

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/python3 "$DIR/lib/keeper_routing.py" 2>/dev/null || true

exit 0
