# H17 · archive_done.py --auto 自动归档（done 数量阈值 / 超龄阈值）。
# 依赖 harness.sh 的 newtmpdir/mkissue/ok/bad/has。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合 · 重要】本文件引用 $ARCH 与 py_nextid()，两者都定义在
# 07-h11-archive.sh 里，靠 source 在同一个 shell 里持续生效，本文件不重新
# 定义。因此本文件必须排在 07-h11-archive.sh 之后 source。

echo
echo "== H17 · archive_done.py --auto 自动归档（done 数量阈值 / 超龄阈值）=="

echo "[62] done ≥ AUTO_DONE_THRESHOLD（10）条即触发，批次名固定 auto-<今日>，next_id 不回收"
T="$(newtmpdir)"
for i in 1 2 3 4 5 6 7 8 9 10; do
  mkissue "$T/.keeper/_main/debug" "DBG-$(printf '%03d' "$i")" done P2 "第 $i 条已完成"
done
before="$(py_nextid "$T/.keeper/_main/debug")"
TODAY_STAMP="$(/usr/bin/python3 -c 'import datetime; print(datetime.date.today().strftime("%Y%m%d"))')"
out="$(/usr/bin/python3 "$ARCH" --queue-dir "$T/.keeper/_main/debug" --auto --apply 2>&1)"
has "达到数量阈值触发" "$out" "触发自动归档"
has "触发理由点明 done 10 条 ≥ 阈值 10" "$out" "done 10 条 ≥ 阈值 10"
has "批次名固定 auto-<今日>" "$out" "auto-$TODAY_STAMP"
for i in 1 2 3 4 5 6 7 8 9 10; do
  f="$T/.keeper/_main/debug/archive/auto-$TODAY_STAMP/DBG-$(printf '%03d' "$i")/issue.md"
  if [ ! -f "$f" ]; then bad "DBG-$(printf '%03d' "$i") 应归档进 auto-$TODAY_STAMP" "存在" "缺失：$f"; fi
done
ok "10 条 done 全部归档进 archive/auto-$TODAY_STAMP/"
after="$(py_nextid "$T/.keeper/_main/debug")"
if [ "$after" = "$before" ]; then ok "自动归档不回收 next_id（仍为 ${before}）"
else bad "next_id 不应变化" "$before" "$after"; fi
rm -rf "$T"

echo "[63] done 未达数量阈值（9 条）且都不超龄时不触发，不建 archive/ 目录"
T="$(newtmpdir)"
for i in 1 2 3 4 5 6 7 8 9; do
  mkissue "$T/.keeper/_main/debug" "DBG-$(printf '%03d' "$i")" done P2 "第 $i 条已完成"
done
out="$(/usr/bin/python3 "$ARCH" --queue-dir "$T/.keeper/_main/debug" --auto --apply 2>&1)"
has "未达阈值时明确说明判据" "$out" "未达自动归档阈值"
if [ ! -d "$T/.keeper/_main/debug/archive" ]; then ok "未触发时不创建 archive/ 目录"
else bad "不应创建 archive/ 目录" "不存在" "已创建"; fi
rm -rf "$T"

echo "[64] done 数量不足阈值，但存在 reported_at 超龄（>14 天）条目仍触发"
T="$(newtmpdir)"
OLD_DATE="$(/usr/bin/python3 -c 'import datetime; print((datetime.date.today()-datetime.timedelta(days=15)).isoformat())')"
mkissue "$T/.keeper/_main/debug" DBG-001 done P2 "很久以前修完但一直没归档" "$OLD_DATE"
TODAY_STAMP="$(/usr/bin/python3 -c 'import datetime; print(datetime.date.today().strftime("%Y%m%d"))')"
out="$(/usr/bin/python3 "$ARCH" --queue-dir "$T/.keeper/_main/debug" --auto --apply 2>&1)"
has "超龄触发，报出实际天数与阈值对比" "$out" "距今 15 天 > 阈值 14 天"
if [ -f "$T/.keeper/_main/debug/archive/auto-$TODAY_STAMP/DBG-001/issue.md" ]; then
  ok "超龄条目被归档进 auto-<今日> 批次（批次名不取该条目自己的日期）"
else
  bad "应归档进 auto-$TODAY_STAMP" "存在" "缺失"
fi
rm -rf "$T"
