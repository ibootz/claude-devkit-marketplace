# H14 · Chore 队列快照（task-keeper 新增，无 radnove-core 对应实现）。
# 依赖 harness.sh 的 newtmpdir/mkchore/run_chore/ok/bad/has。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件自成一体，不依赖其他 case 文件留下的变量或函数。

echo
echo "== H14 · Chore 队列快照（task-keeper 新增，无 radnove-core 对应实现）=="

echo "[57] 零成本保证：没有 .keeper/<交付id>/chore/ 的项目 stdout 必须全空"
T="$(newtmpdir)"; : > "$T/.git"
OUT="$(run_chore "$T" '记一下这笔支出')"
if [ -z "$OUT" ]; then ok "无 chore 队列项目零输出（含杂务特征词也不注入）"
else bad "无队列应零输出" "空" "$OUT"; fi

echo "[58] 造一条 open 条目后，注入体含 id + kind，且字节数预算 ≤900（H14 硬指标）"
mkchore "$T/.keeper/_main/chore" CHR-001 open ledger "记一笔支出台账"
OUT="$(run_chore "$T" '继续')"
has "open 计数、id 与类别" "$OUT" "open 1: CHR-001(ledger)"
BYTES="$(printf '%s' "$OUT" | wc -c | tr -d ' ')"
if [ "$BYTES" -le 900 ]; then ok "chore 快照输出 ${BYTES} 字节 ≤900（低频背景事务不该吃主会话注意力预算）"
else bad "chore 快照输出应 ≤900 字节" "<=900" "$BYTES"; fi
rm -rf "$T"
