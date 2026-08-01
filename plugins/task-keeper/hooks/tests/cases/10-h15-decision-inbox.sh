# H15 · 决策信箱（decision_inbox：pending/blocking 计数 + debug↔chore 去重注入）。
# 依赖 harness.sh 的 newtmpdir/mkissue/mkchore/run_hook/run_chore/ok/bad/
# has/hasnt；LIBDIR 由 run-tests.sh 提供。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件自成一体，不依赖其他 case 文件留下的变量或函数。

echo
echo "== H15 · 决策信箱（decision_inbox：pending/blocking 计数 + debug↔chore 去重注入）=="

echo "[59] pending 计数排除已答复、blocking 计数按 frontmatter 累加；chore 启用时改由它承接摘要"
# decisions/ 与 debug/、chore/ 是同一个交付目录下的兄弟（v4：<worktree根>/.keeper/
# <交付id>/{debug,chore,decisions}/），queue_snapshot/chore_snapshot 传给
# summary_line() 的是「交付目录」这一层，不是 .keeper 本身——测试直接调
# decision_inbox 时必须传同一层，否则测的就不是真实调用路径。
T="$(newtmpdir)"; : > "$T/.git"
mkdir -p "$T/.keeper/_main/decisions/answers"
printf -- '---\nblocking: true\n---\n\n需要拍板 A\n' > "$T/.keeper/_main/decisions/2026-07-30-1200-debug-keeper.md"
printf -- '---\nblocking: false\n---\n\n需要拍板 B\n' > "$T/.keeper/_main/decisions/2026-07-30-1300-debug-keeper.md"
printf -- '---\nblocking: true\n---\n\n已经回复过的\n' > "$T/.keeper/_main/decisions/2026-07-30-1100-debug-keeper.md"
printf -- '答复：已确认\n' > "$T/.keeper/_main/decisions/answers/2026-07-30-1100-debug-keeper.md"
CNT="$(/usr/bin/python3 -c '
import sys; sys.path.insert(0, sys.argv[1])
import decision_inbox as d
items = d.pending_decisions(sys.argv[2])
print(len(items))
print(sum(1 for _n, b in items if b))
' "$LIBDIR" "$T/.keeper/_main")"
PEND_COUNT="$(printf '%s\n' "$CNT" | sed -n '1p')"
BLOCK_COUNT="$(printf '%s\n' "$CNT" | sed -n '2p')"
if [ "$PEND_COUNT" = "2" ]; then ok "pending 计数=2（已答复的第三条不计入 answers/ 也不算决策文件）"
else bad "pending 应为 2" "2" "$PEND_COUNT"; fi
if [ "$BLOCK_COUNT" = "1" ]; then ok "blocking 计数=1（宽松匹配 frontmatter 布尔真值，缺失/写错按非 blocking 计）"
else bad "blocking 应为 1" "1" "$BLOCK_COUNT"; fi

mkissue "$T/.keeper/_main/debug" DBG-001 open P1 "占位问题，仅用于触发 debug 快照"
OUT="$(run_hook "$T" '继续')"
has "chore 未启用时由 debug 快照代注待拍板摘要" "$OUT" "待拍板 2 条"
has "摘要点出 blocking 计数"                   "$OUT" "blocking 1"

mkchore "$T/.keeper/_main/chore" CHR-001 open ledger "占位杂务，仅用于触发 chore 快照"
OUT_DEBUG2="$(run_hook "$T" '继续')"
hasnt "chore 队列一旦启用，debug 快照不再重复代注待拍板（去重判据：<交付>/chore 目录存在性）" \
  "$OUT_DEBUG2" "待拍板"
OUT_CHORE="$(run_chore "$T" '继续')"
has "chore 快照改为承接待拍板摘要" "$OUT_CHORE" "待拍板 2 条"
rm -rf "$T"
