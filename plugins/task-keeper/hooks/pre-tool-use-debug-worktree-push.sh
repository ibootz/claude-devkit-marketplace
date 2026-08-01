#!/usr/bin/env bash
#
# task-keeper · PreToolUse hook · Bash matcher（DBG fixer worktree 禁止 push → 强制拦截）
#
# 【作用】把「debug 流程派出去的 fixer 不允许执行 git push」（2026-07-30 Human
#   立规）从纯文档描述升级为 harness 强制拦截：命中「push 目标路径落在某个
#   `.keeper/worktrees/DBG-*/` 下」时输出 permissionDecision=deny。走 deny 不走
#   ask——fixer 结构上从不需要 push，没有需要用户点头放行的合法场景，直接让 AI
#   自己收手即可。
#
# 【只覆盖 fixer 这一半】debug-keeper 自己做对账/merge-back 收尾时，通常跑在
#   主工作区/交付 worktree，cwd 与它是不是在做 debug 收尾无法机械区分，本 hook
#   覆盖不到；keeper 的「不许未经同意 push」约束靠 `agents/debug-keeper.md` 与
#   `skills/tk-debug/references/queue.md` §6 的显式指令自觉遵守。两条防线合起来
#   才是完整范围，细节见 lib/debug_worktree_push_guard.py 模块头注释。
#
# 【为什么独立成脚本】本 hook 输出 JSON；同一个 Bash matcher 下并挂多个独立
#   hook 条目，各自独立 stdout 才安全，混在同一次 stdout 会让 JSON 解析失败。
#
# 【判定细则】见 lib/debug_worktree_push_guard.py 模块头注释。
# 【怎么关闭】删掉 plugin.json hooks 里本脚本对应的条目，或让本脚本无条件 exit 0。改完需重启 cc。

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/python3 "$DIR/lib/debug_worktree_push_guard.py" 2>/dev/null || true

exit 0
