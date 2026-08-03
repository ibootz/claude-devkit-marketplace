#!/usr/bin/env bash
#
# task-keeper · UserPromptSubmit hook（Chore 队列实时快照注入）
#
# 【作用】每轮把 `.keeper/<交付id>/chore/` 的实时快照注入本轮上下文——open 各条的
#   id + 类别 + 是否涉外部写、done 计数、待拍板（决策信箱）计数。顺带重算
#   `.keeper/chore/index.md`。注入体刻意压薄（目标 ≤900 字符，H14 有预算断言）：
#   杂务是低频背景事务，不配吃掉主会话更多注意力预算。
#
# 【为什么与 debug 快照分开】两个队列启用状态、失败影响面、可测试性彼此独立；
#   两个 hook 各自独立 stdout，一个故障不拖累另一个。
#
# 【零成本保证】当前 worktree 根下没有 .keeper/ 目录时（= 项目未启用 task-keeper），
#   python 侧直接 return，stdout 全空，等价于本 hook 不存在。
#
# 【启用方式】只要 .keeper/ 顶层存在（哪怕只建过 debug/），`.keeper/<交付id>/chore/`
#   由 find_queue 每轮**自动补建**，不需要手工 mkdir——判据见 lib/queue_snapshot.py
#   的 find_queue docstring「为什么自动补建」。整个项目要启用 task-keeper 仍需先手工
#   建一次 .keeper/<交付id>/（交付 id = worktree 根 basename，非交付用 _main）。
#   **停用方式不再是「删掉 chore 目录」**——下一轮就会被补建回来；要停用整个插件请
#   在设置里禁用它，或删掉整个 .keeper/。
# 【失败策略】注入类 hook 静默降级，绝不阻断用户提交。
# 【改完要重启】cc hook 在会话启动时加载。

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/python3 "$DIR/lib/chore_snapshot.py" 2>/dev/null || true

exit 0
