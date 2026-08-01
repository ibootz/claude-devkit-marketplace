#!/usr/bin/env bash
#
# task-keeper · UserPromptSubmit hook（Chore 队列实时快照注入）
#
# 【作用】每轮把项目 `.keeper/chore/items/` 的实时快照注入本轮上下文——open 各条的
#   id + 类别 + 是否涉外部写、done 计数、待拍板（决策信箱）计数。顺带重算
#   `.keeper/chore/index.md`。注入体刻意压薄（目标 ≤900 字符，H14 有预算断言）：
#   杂务是低频背景事务，不配吃掉主会话更多注意力预算。
#
# 【为什么与 debug 快照分开】两个队列启用状态、失败影响面、可测试性彼此独立；
#   两个 hook 各自独立 stdout，一个故障不拖累另一个。
#
# 【零成本保证】从 cwd 向上（到 .git 为止）找不到 .keeper/chore/items/ 目录时，
#   python 侧直接 return，stdout 全空，等价于本 hook 不存在。
#
# 【启用方式】在项目根 `mkdir -p .keeper/chore/items`。删掉该目录即自动停用。
# 【失败策略】注入类 hook 静默降级，绝不阻断用户提交。
# 【改完要重启】cc hook 在会话启动时加载。

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/python3 "$DIR/lib/chore_snapshot.py" 2>/dev/null || true

exit 0
