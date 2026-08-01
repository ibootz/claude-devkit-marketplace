#!/usr/bin/env bash
#
# task-keeper · PreToolUse hook（截图证据路径守卫）
#
# 【作用】写 .keeper/debug/issues/<DBG-id>.md 时，若正文里出现指向
#   ~/.claude/image-cache/ 的图片路径（会话级临时资源，实测只保留当前活跃会话
#   目录），返回 permissionDecision=deny，让 AI 自己改成 .keeper/debug/attachments/
#   下的副本路径，或干脆不写路径只做文字转录。同一行标注了 origin_path 的豁免
#   （那是刻意保留的来源留档，不是给人后续去读的指针）。
#   判据与两条出路的完整说明见 lib/evidence_guard.py 的模块文档。
#
# 【为什么是 deny 而不是 ask】deny 是「AI 自己改正后重试」，用户无感；ask 会弹框打断
#   人，且 permissionDecision 独立于权限模式、配了 bypassPermissions 也拦不住。
#   拦疏忽用 deny，交决策才用 ask。
#
# 【为什么独立成脚本】本 hook 输出 JSON；同一 matcher 下并挂多个独立 hook 条目、
#   各自独立 stdout 才安全，混在同一次 stdout 会让 JSON 解析失败。
#
# 【失败即放行】拿不到事件 / 解析异常一律 exit 0。守卫用来拦疏忽，不是在基础设施
#   抖动时把人锁在门外。

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/python3 "$DIR/lib/evidence_guard.py" 2>/dev/null || true

exit 0
