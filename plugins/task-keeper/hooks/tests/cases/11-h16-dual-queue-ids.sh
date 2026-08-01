# H16 · 双队列互不串号（debug 与 chore 各自独立的 next_id / 归档不互相影响）。
# 依赖 harness.sh 的 newtmpdir/mkissue/mkchore/ok/bad；LIBDIR 由 run-tests.sh
# 提供。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合 · 重要】[61] 直接引用 $ARCH（archive_done.py 的路径），这个变量
# 定义在 07-h11-archive.sh 里，靠 source 在同一个 shell 里持续生效，本文件
# 不重新定义。因此本文件必须排在 07-h11-archive.sh 之后 source。

echo
echo "== H16 · 双队列互不串号（debug 与 chore 各自独立的 next_id / 归档不互相影响）=="

echo "[60] 同项目 debug 与 chore 各自独立编号"
T="$(newtmpdir)"
mkissue "$T/.keeper/_main/debug" DBG-003 open P1 "已有的问题"
mkchore "$T/.keeper/_main/chore" CHR-001 open ledger "已有的杂务"
DBG_NEXT="$(/usr/bin/python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import queue_files as f; print(f.next_id(sys.argv[2], f.DEBUG))' "$LIBDIR" "$T/.keeper/_main/debug")"
CHR_NEXT="$(/usr/bin/python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import queue_files as f; print(f.next_id(sys.argv[2], f.CHORE))' "$LIBDIR" "$T/.keeper/_main/chore")"
if [ "$DBG_NEXT" = "DBG-004" ]; then ok "debug next_id = DBG-004"
else bad "应为 DBG-004" "DBG-004" "$DBG_NEXT"; fi
if [ "$CHR_NEXT" = "CHR-002" ]; then ok "chore next_id = CHR-002（不受 debug 编号影响）"
else bad "应为 CHR-002" "CHR-002" "$CHR_NEXT"; fi

echo "[61] debug 队列归档进 archive/ 后，chore 队列编号仍不受影响"
mkissue "$T/.keeper/_main/debug" DBG-004 done P1 "已完成待归档"
/usr/bin/python3 "$ARCH" --queue debug --queue-dir "$T/.keeper/_main/debug" --batch H16-test --apply >/dev/null 2>&1
DBG_NEXT2="$(/usr/bin/python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import queue_files as f; print(f.next_id(sys.argv[2], f.DEBUG))' "$LIBDIR" "$T/.keeper/_main/debug")"
CHR_NEXT2="$(/usr/bin/python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import queue_files as f; print(f.next_id(sys.argv[2], f.CHORE))' "$LIBDIR" "$T/.keeper/_main/chore")"
if [ "$DBG_NEXT2" = "DBG-005" ]; then ok "debug 归档后 next_id 前进到 DBG-005（archive/ 也计入历史，不回收编号）"
else bad "应为 DBG-005" "DBG-005" "$DBG_NEXT2"; fi
if [ "$CHR_NEXT2" = "CHR-002" ]; then ok "chore 队列 next_id 不受 debug 归档动作影响，仍为 CHR-002"
else bad "应仍为 CHR-002" "CHR-002" "$CHR_NEXT2"; fi
rm -rf "$T"
