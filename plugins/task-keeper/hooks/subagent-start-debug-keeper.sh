#!/usr/bin/env bash
#
# task-keeper · SubagentStart hook（debug-keeper 漏派清单注入）
#
# 【作用】debug-keeper 每次启动或被 SendMessage 唤醒时，把「已 triage、但既不在飞也不在
#   等拍板」的那批 issue 现算一行递给它。判据与理由全部写在 lib/debug_keeper_inject.py
#   的文件头，本壳只负责调它。
#
# 【为什么是 SubagentStart 而不是 UserPromptSubmit】
#   UserPromptSubmit 的注入**不进子代理**——同目录那三个 user-prompt-submit-*.sh 伺候的
#   全是主会话，一行都到不了 keeper 手里。给子代理注入开场上下文只有这一个事件。
#   且 2026-08-05 实测确认它在**每次 SendMessage 唤醒时都会重新触发**（探针连做三轮，
#   同一段注入分别出现 1/2/3 次），不是只在首次 Agent 派出时触发一次——这正是本 hook
#   能治「登记完被新需求挤掉、忘了捡回来派」那个症状的前提。
#
# 【matcher】plugin.json 里按 agent_type 精确匹配 `task-keeper:debug-keeper`。
#   **不要写 `*`**——那会把 debug 队列的漏派清单灌给本机每一个子代理（同插件的
#   chore-keeper、sdlc-writer，以及其他插件的、以及主会话派出的所有 Explore/general-purpose），
#   纯噪音。python 侧还会再查一次 agent_type 做双保险。
#
# 【零成本保证】无漏派时 python 侧直接 return、stdout 全空，等价于本 hook 不存在。
#   项目未启用 task-keeper（没有 .keeper/）时同样零输出——pending_dispatch.py 对
#   「自动探测落空」的处理是打印提示后退出码 0，而本 hook 只在 --oneline 输出非空时注入，
#   那个模式下未启用场景给的是空串。
#
# 【失败策略】注入类 hook 一律静默降级，绝不阻断子代理启动：不带 set -e，python 异常在
#   其 main 外层被吞，stderr 丢弃，恒 exit 0。算不出漏派的代价是 keeper 少看到一行提示，
#   而拦住 keeper 启动的代价是整条 bug 流水线停摆——两者不对等，所以这里只能 fail-open。
#
# 【改完要重启】cc hook 在会话启动时加载。

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/python3 "$DIR/lib/debug_keeper_inject.py" 2>/dev/null || true

exit 0
