# H18 · SessionStart 主会话路由注入（keeper_routing.py：opt-in 分档 +
# heredoc-stdin 回归）。依赖 harness.sh 的 newtmpdir/mkissue/run_routing/
# ok/bad/has/hasnt。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】仅在本文件内部：[66] 复用 [65] 建的 $T（未启用 → 启用是同一个
# 项目目录的两个阶段），到本文件末尾才 `rm -rf "$T"`。这一耦合完全在本文件
# 范围内，不涉及其他 case 文件。

echo
echo "== H18 · SessionStart 主会话路由注入（keeper_routing.py：opt-in 分档 + heredoc-stdin 回归）=="

echo "[65] 项目未启用 .keeper/：只注入一句话介绍，长度 ≤300 字符"
# 判据是 keeper_paths.find_keeper_root：.keeper/ 这个目录本身存在与否，不要求
# <交付id>/debug 这一层已建出——所以「未启用」必须连 .keeper/ 都不存在。
T="$(newtmpdir)"; : > "$T/.git"
OUT="$(run_routing "$T")"
TEXT="$(printf '%s' "$OUT" | /usr/bin/python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])
except Exception:
    print("")
')"
CHARS="$(/usr/bin/python3 -c 'import sys; print(len(sys.argv[1]))' "$TEXT")"
if [ "$CHARS" -le 300 ]; then ok "未启用文案 ${CHARS} 字符 ≤300"
else bad "未启用文案应 ≤300 字符" "<=300" "$CHARS"; fi
# 断言子串刻意避开 NOT_ENABLED 原文里的反引号——反引号在 bash 双引号字符串里仍是
# 命令替换语法，写进测试字面量会被当命令执行，而不是原样比较。
has "未启用文案给出启用方式（mkdir 命令）" "$TEXT" "mkdir -p .keeper/"
has "未启用文案点出非交付 worktree 的兜底桶" "$TEXT" "代替 basename"

echo "[66] 项目已启用 .keeper/：只注入静态参考，长度 ≤2000 字符（硬上限）"
mkissue "$T/.keeper/_main/debug" DBG-001 open P1 "占位问题，仅用于触发 routing 已启用分支"
OUT="$(run_routing "$T")"
TEXT="$(printf '%s' "$OUT" | /usr/bin/python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])
except Exception:
    print("")
')"
CHARS="$(/usr/bin/python3 -c 'import sys; print(len(sys.argv[1]))' "$TEXT")"
if [ "$CHARS" -le 2000 ]; then ok "已启用文案 ${CHARS} 字符 ≤2000（硬上限）"
else bad "已启用文案应 ≤2000 字符" "<=2000" "$CHARS"; fi
has "含决策打包主会话侧职责说明" "$TEXT" "决策打包"
has "含 v4 布局说明" "$TEXT" "worktree 根"
# 【为什么断言「不含」】2026-08-01 三岔口挪到 UserPromptSubmit 后，这里原本那条
# `has "含三岔口分诊文案" … "三岔口分诊"` 变成了**假绿**：它命中的是新文案里
# 「三岔口分诊规则每轮随 UserPromptSubmit 注入」这句**指针**，而不是分诊规则本体。
# 两层文本刻意不重叠是这次改动的设计约束，所以正确的断言方向是反的——用分诊规则
# **本体**才有的字串（转发目标名）来断言它不在 SessionStart 这份里。
hasnt "SessionStart 这份不复述分诊规则本体（避免同会话重复两遍）" "$TEXT" "转 chore-keeper"
rm -rf "$T"
