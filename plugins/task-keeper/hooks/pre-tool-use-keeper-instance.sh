#!/usr/bin/env bash
#
# task-keeper · PreToolUse hook · Agent matcher（keeper 实例落盘登记）
#
# 【作用】命中 keeper 类 `subagent_type`（`debug-keeper` / `chore-keeper`）的
#   `Agent` 派发时，把这次派发用的 `tool_input.name`（keeper 的 name 现在强制带
#   4 位随机短哈希，如 `opus-debugger-4bb6`）写进
#   `<worktree 根>/.keeper/<交付id>/.keeper-instance.json`，供主会话下次唤醒 keeper
#   前读取真实 name——短哈希是随机的，主会话没法靠记忆或文档拼出来。
#
# 【纯写文件，不拦截任何操作】本脚本不输出 permissionDecision，不 exit 2，任何异常
#   都在 python 侧静默降级。写得进就写，写不进就算了，绝不阻断这次 Agent 派发。
#   本仓 `.claude/rules/project/hook-restraint.md` 的严格判据表约束的是拦截类 hook；本 hook
#   是纯副作用 hook，不受那张表约束，但代价是必须保证自己不会误伤——判据与异常处理
#   细节见 `lib/keeper_instance_register.py` 模块头。
#
# 【判据】只用确定字段：`tool_name === "Agent"` 且 `tool_input.subagent_type` 的
#   冒号后 slug 属于 `{debug-keeper, chore-keeper}` 白名单，`tool_input.name` 必须
#   是非空字符串。三条都不涉及语义猜测。
#
# 【为什么独立成脚本】本 hook 挂在 `PreToolUse` 的 `Agent` matcher 下，与其他插件
#   （working-discipline 的 `agent-dispatch.js`）各自独立注册、各自独立 stdout，
#   互不干扰。
#
# 【怎么关闭】删掉 plugin.json hooks 里本脚本对应的条目，或让本脚本无条件 exit 0。
#   改完需重启 cc。

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/python3 "$DIR/lib/keeper_instance_register.py" 2>/dev/null || true

exit 0
