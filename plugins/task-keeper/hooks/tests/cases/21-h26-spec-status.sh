# H26 · spec_status frontmatter 键位与 index.md 规格列（新增字段回归）。
# 锁的是 queue_files.py 里 DEBUG 这个 QueueSpec 的两处改动：fm_order 在
# "type" 与 "reported_at" 之间插入了 "spec_status"；index_cols 追加了
# ("spec_status", "规格")。docstring 明确写着「按 spec.fm_order 固定顺序输出，
# 未知键排在后面按字母序」——如果 fm_order 里的键名被拼错（比如手滑写成
# spec_staus），失效形态是静默把 spec_status 排到末尾，不会报错、不会被
# has() 类的存在性断言抓到（值还在，只是位置错了），所以本节用行号比较锁住
# 「顺序」本身，不只是「存在」。
# 依赖 harness.sh 的 newtmpdir/run_hook/ok/bad/has。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件自成一体，不依赖其他 case 文件留下的变量或函数，
# 也不给后面的文件留任何现场。

echo
echo "== H26 · spec_status frontmatter 键位与 index.md 规格列 =="

echo "[112] render_frontmatter 按 fm_order 固定位置输出 spec_status（type 之后、"
echo "      reported_at 之前），不是按 dict 插入顺序也不是按字母序"
# fm dict 的键故意打乱顺序（spec_status 排在最前、reported_at 排在中间偏后），
# 用来证明输出顺序只由 spec.fm_order 决定，与传入顺序无关。
OUT="$(/usr/bin/python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
import queue_files as f
fm = {
    "spec_status": "violation",
    "reported_at": "2026-07-29",
    "id": "DBG-020",
    "type": "bug",
    "status": "open",
    "summary": "测 spec_status 渲染位置",
    "priority": "P1",
}
print(f.render_frontmatter(fm, f.DEBUG))
' "$LIBDIR")"
has "spec_status 取值原样渲染" "$OUT" "spec_status: violation"
TYPE_LINE="$(printf '%s\n' "$OUT" | grep -n '^type:' | head -1 | cut -d: -f1)"
SPEC_LINE="$(printf '%s\n' "$OUT" | grep -n '^spec_status:' | head -1 | cut -d: -f1)"
REPORTED_LINE="$(printf '%s\n' "$OUT" | grep -n '^reported_at:' | head -1 | cut -d: -f1)"
if [ -n "$TYPE_LINE" ] && [ -n "$SPEC_LINE" ] && [ -n "$REPORTED_LINE" ] \
   && [ "$TYPE_LINE" -lt "$SPEC_LINE" ] && [ "$SPEC_LINE" -lt "$REPORTED_LINE" ]; then
  ok "spec_status 渲染位置在 type(第${TYPE_LINE}行) 与 reported_at(第${REPORTED_LINE}行) 之间（第${SPEC_LINE}行）"
else
  bad "spec_status 应严格夹在 type 与 reported_at 之间（fm_order 固定位置，非未知键排到末尾）" \
      "行号满足 type < spec_status < reported_at" \
      "type=${TYPE_LINE:-缺失} spec_status=${SPEC_LINE:-缺失} reported_at=${REPORTED_LINE:-缺失}"
fi

echo "[113] index.md open 表格新增「规格」列，且取值取自 issue 的 spec_status；"
echo "      表头列序按 index_cols 声明顺序（优先级→难度→类型→规格）"
T="$(newtmpdir)"; : > "$T/.git"
Q="$T/.keeper/_main/debug"
mkdir -p "$Q/DBG-001"
{
  echo "---"
  echo "id: DBG-001"
  echo "summary: 规格列回归用例"
  echo "status: open"
  echo "priority: P1"
  echo "difficulty: medium"
  echo "type: bug"
  echo "spec_status: gap"
  echo "reported_at: 2026-07-29"
  echo "---"
  echo
  echo "# DBG-001 · 规格列回归用例"
} > "$Q/DBG-001/issue.md"
run_hook "$T" '继续' > /dev/null
IDX="$Q/index.md"
if [ -f "$IDX" ]; then ok "index.md 生成"
else bad "index.md 应生成" "文件存在" "缺失"; fi
IDXC="$(cat "$IDX" 2>/dev/null)"
has "表头含规格列，且列序正确（优先级/难度/类型/规格）" "$IDXC" \
    "| ID | 优先级 | 难度 | 类型 | 规格 | 摘要 |"
has "DBG-001 一行的规格列取值 = frontmatter 的 spec_status（gap）" "$IDXC" \
    "| [DBG-001](DBG-001/issue.md) | P1 | medium | bug | gap | 规格列回归用例 |"
rm -rf "$T"
