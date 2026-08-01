#!/usr/bin/env bash
#
# task-keeper · PreToolUse hook · Bash matcher（DBG fixer worktree 强制删除 → 弹框确认）
#
# 【作用】拦截「针对 `.keeper/worktrees/` 目录执行强制删除类命令」（`git worktree
#   remove --force` / `rm -rf` / `git clean -fdx` 等），防止 fixer 尚未 commit 的
#   修复产物被不可逆删掉。命中时输出 permissionDecision=ask，弹框交给 Human
#   拍板——不是 deny，因为 `rm -rf` 这类命令在 `isolated-objdir` / `unreachable`
#   状态的恢复流程里是文档记载的合法手段（见
#   skills/tk-worktree/SKILL.md 状态判据表），一律 deny 会堵死这条恢复路径。
#
# 【为什么独立成脚本】与同目录 pre-tool-use-debug-worktree-push.sh 同理：本 hook
#   输出 JSON，同一个 Bash matcher 下并挂多个独立 hook 条目，各自独立 stdout
#   才安全。
#
# 【判定细则】见 lib/debug_worktree_destroy_guard.py 模块头注释。
# 【怎么关闭】删掉 plugin.json hooks 里本脚本对应的条目，或让本脚本无条件 exit 0。改完需重启 cc。

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/python3 "$DIR/lib/debug_worktree_destroy_guard.py" 2>/dev/null || true

exit 0
