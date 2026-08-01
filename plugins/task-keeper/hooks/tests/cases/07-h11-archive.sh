# H11 · 按交付批次归档（archive_done.py + next_id 归档感知 + index.md 统计）。
# 依赖 harness.sh 的 newtmpdir/ok/bad/has/hasnt；LIBDIR/HOOK_DIR 由
# run-tests.sh 提供。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合 · 重要】本文件定义的 $ARCH（archive_done.py 的路径）与
# py_nextid() 之后被两个文件复用：11-h16-dual-queue-ids.sh 直接引用 $ARCH，
# 12-h17-auto-archive.sh 同时引用 $ARCH 与 py_nextid()——都是靠 source 在
# 同一个 shell 里持续生效。这三个文件必须保持 07→…→11→12 的相对顺序（07 在
# 11、12 之前 source），否则那两个文件会因为变量/函数未定义而报错或取到空值。

echo
echo "== H11 · 按交付批次归档（archive_done.py + next_id 归档感知 + index.md 统计）=="
ARCH="$HOOK_DIR/../skills/tk-debug/scripts/archive_done.py"

# 造一个最小的 git 跟踪的假 .keeper/_main/debug/：3 条 done（其中 DBG-003 故意留着
# worktree/ 子目录，v4 落点是条目目录自己里面的 worktree/）+ 1 条 open；DBG-002 带
# receipts.md 与一张截图（v4 平铺在条目目录里，没有独立 attachments 子树），用来
# 验证成组搬迁——v4 一条目一目录，归档退化成一次 shutil.move，三份东西随目录一起搬。
mkarchfixture() {
  local d; d="$(newtmpdir)"
  local q="$d/.keeper/_main/debug"
  mkdir -p "$q/DBG-001" "$q/DBG-002" "$q/DBG-003/worktree" "$q/DBG-004"
  git -C "$d" init -q -b main
  for spec in "DBG-001 done" "DBG-002 done" "DBG-003 done" "DBG-004 open"; do
    set -- $spec
    printf -- '---\nid: %s\nsummary: %s 摘要\nstatus: %s\npriority: P1\ndifficulty: easy\ntype: bug\nreported_at: 2026-07-30\nreopen_count: 0\n---\n\n# %s\n' \
      "$1" "$1" "$2" "$1" > "$q/$1/issue.md"
  done
  echo "回执" > "$q/DBG-002/receipts.md"
  echo "png" > "$q/DBG-002/01.png"
  # worktree/ 在真实项目里被 .gitignore 排除，这里用 -f 强制纳入不影响判定
  git -C "$d" add -A -f .keeper >/dev/null 2>&1
  git -C "$d" -c user.email=t@t.com -c user.name=t commit -q -m "fixture"
  echo "$d"
}
py_nextid() {   # $1=queue_dir(.keeper/_main/debug) —— 打印 DEBUG spec 下的 next_id()
  /usr/bin/python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import queue_files as f; print(f.next_id(sys.argv[2], f.DEBUG))' \
    "$LIBDIR" "$1"
}

echo "[46] dry-run 零副作用：列出计划但不动任何文件，next_id 不变"
D="$(mkarchfixture)"
DQ="$D/.keeper/_main/debug"
before="$(py_nextid "$DQ")"
out="$(/usr/bin/python3 "$ARCH" --queue-dir "$DQ" --batch D-999-test 2>&1)"
has "dry-run 列出 DBG-001 的搬迁计划" "$out" "DBG-001"
has "dry-run 明确标注未移动"          "$out" "未移动任何文件"
if [ -z "$(git -C "$D" status --short)" ]; then ok "dry-run 后工作区仍干净"
else bad "dry-run 后工作区仍干净" "空" "$(git -C "$D" status --short)"; fi
has "dry-run 后 next_id 不变（${before}）" "$(py_nextid "$DQ")" "$before"

echo "[47] --apply 整目录搬迁（issue.md/receipts.md/截图一起走），open 与带 worktree 的 done 不动"
out="$(/usr/bin/python3 "$ARCH" --queue-dir "$DQ" --batch D-999-test --apply 2>&1)"
has "汇总报成功 2 条" "$out" "成功 2 条"
for f in DBG-001/issue.md DBG-002/issue.md DBG-002/receipts.md DBG-002/01.png; do
  if [ -e "$DQ/archive/D-999-test/$f" ]; then ok "已归档 archive/D-999-test/$f"
  else bad "已归档 archive/D-999-test/$f" "存在" "缺失"; fi
done
if [ -f "$DQ/DBG-004/issue.md" ]; then ok "open 条目 DBG-004 留在原地"
else bad "open 条目 DBG-004 留在原地" "存在" "被误搬"; fi
if [ -f "$DQ/DBG-003/issue.md" ]; then ok "done 但 worktree 未清的 DBG-003 未被搬走"
else bad "done 但 worktree 未清的 DBG-003 未被搬走" "存在" "被误搬"; fi
has "DBG-003 给出跳过警告" "$out" "DBG-003"

echo "[48] 归档不得造成 id 复用（最关键的不变量）+ index.md 只统计不逐条 + 幂等"
has "归档后 next_id 未回退（仍为 ${before}）" "$(py_nextid "$DQ")" "$before"
idx="$(/usr/bin/python3 -c '
import sys; sys.path.insert(0, sys.argv[1]); import queue_files as f
a = f.render_index(sys.argv[2], f.DEBUG); b = f.render_index(sys.argv[2], f.DEBUG)
print("IDEMPOTENT" if a == b else "DIFFERS")
print(a)' "$LIBDIR" "$DQ")"
has "render_index 两次调用逐字节相同" "$idx" "IDEMPOTENT"
has "index.md 含 archived 计数节"     "$idx" "## archived 2"
hasnt "archived 节不逐条列归档 id"     "$idx" "archive/D-999-test/DBG-001/issue.md"
out="$(/usr/bin/python3 "$ARCH" --queue-dir "$DQ" --batch D-999-test --apply 2>&1)"
has "重跑幂等（已归档的不再重复搬）" "$out" "0 条"
rm -rf "$D" 2>/dev/null
