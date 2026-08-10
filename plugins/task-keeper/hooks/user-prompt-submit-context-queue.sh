#!/usr/bin/env bash
#
# task-keeper · UserPromptSubmit hook（Context 队列实时快照注入）
#
# 【作用】每轮把 `.keeper/<交付id>/context/` 的实时快照注入本轮上下文——open 各条的
#   id + 阶段 + 是否降级为三方印证 + 不一致条数、销账表无人填的告警、done 计数。
#   顺带重算 `context/index.md`。
#
# 【为什么与另两个快照分开】三个队列启用状态、失败影响面、可测试性彼此独立；各自
#   独立 stdout，一个故障不拖累另外两个。
#
# 【它刻意不做的三件事】不报待拍板计数、不报 gitignore 告警（这两项由 debug/chore
#   二元分工，加第三方只会重复注入同样的文案）、不做特征词提醒（「这次算不算一个
#   功能单元」是语义判断，做成关键词会大面积误报）。判据见 lib/context_snapshot.py
#   模块头。
#
# 【零成本保证】worktree 根下没有 .keeper/ 时 python 侧直接 return，stdout 全空。
# 【启用方式】`.keeper/` 顶层存在即由 find_queue 每轮自动补建 context/，无需手工 mkdir。
# 【失败策略】注入类 hook 静默降级，绝不阻断用户提交。
# 【改完要重启】cc hook 在会话启动时加载。

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/python3 "$DIR/lib/context_snapshot.py" 2>/dev/null || true

exit 0
