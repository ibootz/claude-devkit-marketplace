#!/usr/bin/env bash
#
# task-keeper · UserPromptSubmit hook（三岔口分诊每轮注入）
#
# 【作用】每轮把「自己做 / 转 debug-keeper / 转 chore-keeper」三岔口分诊规则注入
#   本轮上下文。**纯注入，零拦截**——分诊是语义判断，按 hook 克制原则不能做成
#   拦截（见仓库 .claude/rules/project/hook-restraint.md）。
#
# 【为什么从 SessionStart 挪到这里（2026-08-01）】
#   分诊规则与 system prompt 的默认行为直接对立：base 指令是「有足够信息就动手」，
#   分诊要求「先别动手、判归属」。只在会话开头注入一次，压不过每轮都在生效的 base
#   指令——实测 AI 在会话中段会跳过分诊直接自己修 bug、自己做杂务。
#   同会话里的静态参考（决策打包协议、v4 布局、指针）仍留 SessionStart，两层文本
#   刻意不重叠。分层判据见 lib/keeper_routing.py 模块头。
#
# 【为什么独立成脚本，不并进 debug/chore 快照那两个】
#   与同目录另两个 UserPromptSubmit hook 同一条理由：三者启用状态、失败影响面、
#   可测试性彼此独立，各自独立 stdout，一个故障不拖累另外两个。
#   注意本 hook 的启用判据比那两个宽——它只要 `.keeper/` 存在即注入，不要求
#   debug 或 chore 任一队列目录已建。
#
# 【零成本保证】未启用项目（找不到 `.keeper/`）python 侧直接 return，stdout 全空，
#   等价于本 hook 不存在。SessionStart 那份的「未启用引导」不会在这里每轮重复。
#
# 【失败策略】注入类 hook 一律静默降级，绝不阻断用户提交。
#
# 【改完要重启】cc hook 在会话启动时加载。

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/python3 "$DIR/lib/keeper_routing.py" --event user-prompt-submit 2>/dev/null || true

exit 0
