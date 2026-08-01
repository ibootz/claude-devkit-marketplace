#!/usr/bin/env bash
#
# task-keeper · UserPromptSubmit hook（Debug 队列实时快照注入）
#
# 【作用】每轮把项目 `.keeper/debug/issues/` 的**实时快照**注入本轮上下文——open
#   各条的 id + 优先级 + 是否在飞、done 计数、reopen 告警、.gitignore 缺行提醒。
#   顺带重算 `.keeper/debug/index.md`（只在 fixer 的 `DBG-*` worktree 里跳过重算,
#   避免几份并行副本互相冒充真身；交付级 worktree 照常重算——那里的队列若是唯一
#   真身，不刷会让索引永久过期）。
#
# 【为什么是 hook 而不是一段 CLAUDE.md 纪律】
#   CLAUDE.md 是静态文本，hook 是**可执行程序**——它能读文件、算状态。
#   一步之差，注入内容从「规则」变成「规则 + 当前状态」，并且解决了纯纪律型
#   约束的固有缺陷：「队列文件是恢复锚点，但恢复动作依赖主会话记得 Read」。
#   现在由 harness 每轮强制注入，与 AI 是否记得、上下文有没有被压缩无关。
#   ——**监督者与被监督者由此分离**。
#
# 【为什么独立成脚本，不与 chore 快照合并】
#   同目录 user-prompt-submit-chore-queue.sh 伺候的是另一个队列（CHR），两者
#   启用状态、失败影响面、可测试性彼此独立；且两个 hook 各自独立 stdout，
#   一个故障不拖累另一个。核心逻辑都有回归测试（hooks/tests/run-tests.sh）。
#
# 【零成本保证（重要）】
#   本 hook 随插件装到**所有**项目、**每轮**触发。因此：从 cwd 向上（到 .git
#   为止）找不到 .keeper/debug/issues/ 目录时，python 侧直接 return，stdout
#   全空，等价于本 hook 不存在。唯一例外是检测到旧版 .debug/issues/（radnove
#   布局）时注入一句迁移提示——否则升级用户会看到「队列消失」且无从归因。
#
# 【启用方式】在项目根 `mkdir -p .keeper/debug/issues`（文件格式见
#   skills/tk-debug/references/queue.md §2）。删掉该目录即自动停用。
#
# 【失败策略】注入类 hook 一律静默降级，绝不阻断用户提交：脚本不带 set -e，
#   python 异常在其 main 外层被吞。唯一例外是 issue 文件读不懂（frontmatter
#   损坏、status 不是 open/done）——那会在注入体里列出来，因为静默跳过会让
#   这几条从队列视图消失、被误读成「已经修完了」，比报错更危险。
#
# 【改完要重启】cc hook 在会话启动时加载。

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/python3 "$DIR/lib/queue_snapshot.py" 2>/dev/null || true

exit 0
