#!/usr/bin/env bash
#
# task-keeper · PreToolUse hook（sdlc 文档正文编写者守卫）
#
# 【作用】主会话（payload 无 agent_id）直接写 sdlc 流程文档正文（sdlc/specs/ 或
#   sdlc/deliveries/ 下、非 _index.md）时返回 permissionDecision=deny，逼它改道派
#   sdlc-writer subagent。sdlc-writer 自己写（payload 带 agent_id）放行；_index.md
#   放行（承载 gate 状态 frontmatter，是主会话/Human 的门禁动作）。
#   判据、四条出路与为什么用 deny 的完整说明见 lib/sdlc_writer_guard.py 模块文档。
#
# 【为什么是 deny 而不是 ask】同 pre-tool-use-debug-evidence.sh：deny 是「AI 自己改正
#   后重试」、用户无感；ask 会弹框打断人，且 permissionDecision 独立于权限模式、配了
#   bypassPermissions 也拦不住。本机 defaultMode 常 bypassPermissions，deny 是唯一可靠
#   档。拦的是「该派没派」的疏忽，不是「需人决策」。
#
# 【为什么独立成脚本】本 hook 输出 JSON；同一 matcher 下并挂多个独立 hook 条目、各自
#   独立 stdout 才安全，混在同一次 stdout 会让 JSON 解析失败（与 evidence 壳同一条
#   理由）。
#
# 【失败即放行】拿不到事件 / 解析异常一律 exit 0。守卫用来拦疏忽，不是在基础设施抖动
#   时把人锁在门外。
#
# 【改完要重启】cc hook 在会话启动时加载。

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/python3 "$DIR/lib/sdlc_writer_guard.py" 2>/dev/null || true

exit 0
