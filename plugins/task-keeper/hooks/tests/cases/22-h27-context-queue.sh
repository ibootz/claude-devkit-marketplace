# H27 · Context 队列（第三条队列接线 + 销账表填写进度）。
# 锁三组东西：
#   (a) queue_files.CONTEXT 这个新 QueueSpec 的 fm_order 固定位置与 index_cols
#       三列——失效形态与 H26 同源（键名拼错时静默排到末尾、不报错）。
#   (b) context_snapshot.ledger_progress 的两侧：能数对已填/总行数；格式一变就
#       fail-soft 返回 None。**返回 None 必须走「不报」而不是「报 0 行已填」**，
#       否则实现者换个表格写法就会被诬告成没填。
#   (c) 端到端注入：open 行带 stage/三方降级/不一致标记，销账表全空时出告警、
#       填了就不出。这条是本队列唯一超出「列清单」的机械信号，值得两侧都锁。
# 依赖 harness.sh 的 newtmpdir/ok/bad/has。context hook 不走 run_hook（那个跑的是
# debug 队列），本节自己拼 JSON 喂 stdin。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——自成一体，不依赖也不留现场。

echo
echo "== H27 · Context 队列接线与销账表填写进度 =="

CTX_HOOK="$HOOK_DIR/user-prompt-submit-context-queue.sh"

# 造一个带 CTX 条目的临时仓。$1=目录 $2=sources $3=inconsistent $4=ledger 已填行数
mkctx() {
  local T="$1" SRC="$2" INC="$3" FILLED="$4" i
  : > "$T/.git"
  local Q="$T/.keeper/_main/context"
  mkdir -p "$Q/CTX-001"
  {
    echo "---"
    echo "id: CTX-001"
    echo "summary: 导入模板的错误提示"
    echo "status: open"
    echo "stage: debug"
    echo "about: DBG-017"
    echo "sources: $SRC"
    echo "assertions: 5"
    echo "inconsistent: $INC"
    echo "created_at: 2026-08-10"
    echo "---"
    echo
    echo "# CTX-001 · 导入模板的错误提示"
  } > "$Q/CTX-001/context.md"
  {
    echo "# CTX-001 销账表"
    echo
    echo "| # | 约束 | 判据 | 实现位置 | 状态 | 备注 |"
    echo "|---|---|---|---|---|---|"
    for i in 1 2 3 4 5; do
      if [ "$i" -le "$FILLED" ]; then
        echo "| $i | 错误提示 E00$i | 与 req.md 逐字一致 | Svc.java:2$i | 已实现 | |"
      else
        echo "| $i | 错误提示 E00$i | 与 req.md 逐字一致 | | | |"
      fi
    done
  } > "$Q/CTX-001/ledger.md"
}

echo "[114] CONTEXT.fm_order 按固定位置渲染 sources/assertions/inconsistent，"
echo "      不是按传入 dict 顺序、也不是被当未知键排到末尾"
OUT="$(/usr/bin/python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
import queue_files as f
fm = {
    "inconsistent": 4, "created_at": "2026-08-10", "id": "CTX-001",
    "sources": 3, "status": "open", "assertions": 31,
    "summary": "测渲染位置", "stage": "debug", "about": "DBG-017",
}
print(f.render_frontmatter(fm, f.CONTEXT))
' "$LIBDIR")"
has "sources 取值原样渲染" "$OUT" "sources: 3"
has "inconsistent 取值原样渲染" "$OUT" "inconsistent: 4"
S_LINE="$(printf '%s\n' "$OUT" | grep -n '^sources:' | head -1 | cut -d: -f1)"
A_LINE="$(printf '%s\n' "$OUT" | grep -n '^assertions:' | head -1 | cut -d: -f1)"
I_LINE="$(printf '%s\n' "$OUT" | grep -n '^inconsistent:' | head -1 | cut -d: -f1)"
C_LINE="$(printf '%s\n' "$OUT" | grep -n '^created_at:' | head -1 | cut -d: -f1)"
if [ -n "$S_LINE" ] && [ -n "$A_LINE" ] && [ -n "$I_LINE" ] && [ -n "$C_LINE" ] \
   && [ "$S_LINE" -lt "$A_LINE" ] && [ "$A_LINE" -lt "$I_LINE" ] && [ "$I_LINE" -lt "$C_LINE" ]; then
  ok "键序 sources(第${S_LINE}行) < assertions < inconsistent < created_at(第${C_LINE}行)"
else
  bad "sources/assertions/inconsistent 应按 fm_order 依次排在 created_at 之前" \
      "行号严格递增" \
      "sources=${S_LINE:-缺失} assertions=${A_LINE:-缺失} inconsistent=${I_LINE:-缺失} created_at=${C_LINE:-缺失}"
fi

echo "[115] context/index.md 的 open 表头列序 = index_cols 声明顺序（阶段/信源/不一致），"
echo "      链接指向 <id>/context.md 而不是 issue.md"
T="$(newtmpdir)"; mkctx "$T" 5 0 0
printf '{"cwd":"%s","prompt":"继续"}' "$T" | bash "$CTX_HOOK" > /dev/null 2>&1
IDX="$T/.keeper/_main/context/index.md"
if [ -f "$IDX" ]; then ok "index.md 生成"
else bad "index.md 应生成" "文件存在" "缺失"; fi
IDXC="$(cat "$IDX" 2>/dev/null)"
has "表头列序正确（阶段/信源/不一致）" "$IDXC" "| ID | 阶段 | 信源 | 不一致 | 摘要 |"
has "数据行取值与链接落 context.md" "$IDXC" \
    "| [CTX-001](CTX-001/context.md) | debug | 5 | 0 | 导入模板的错误提示 |"
rm -rf "$T"

echo "[116] ledger_progress 数对 (已填, 总行数)：表头与分隔行不计入，"
echo "      判据是「第一个 cell 是纯数字」而不是「跳过前两行」"
T="$(newtmpdir)"; mkctx "$T" 5 0 3
PROG="$(/usr/bin/python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
import context_snapshot as cs
print(cs.ledger_progress(sys.argv[2]))
' "$LIBDIR" "$T/.keeper/_main/context/CTX-001")"
# 变量名后紧跟全角括号必须写 ${PROG}：macOS 自带 bash 3.2 会把非 ASCII 字节当成
# 标识符字符吃进变量名，实测报 `PROG?: unbound variable`。
if [ "$PROG" = "(3, 5)" ]; then ok "5 行里数出 3 行已填（${PROG}）"
else bad "ledger_progress 应返回 (3, 5)" "(3, 5)" "$PROG"; fi
rm -rf "$T"

echo "[117] ledger_progress fail-soft：列数被改 / 文件缺失 → None（走「不报」），"
echo "      **不能**退化成「0 行已填」——那会把格式变化诬告成没人填"
T="$(newtmpdir)"; mkctx "$T" 5 0 0
D="$T/.keeper/_main/context/CTX-001"
{
  echo "| # | 约束 | 状态 |"
  echo "|---|---|---|"
  echo "| 1 | 错误提示 | 已实现 |"
} > "$D/ledger.md"
P1="$(/usr/bin/python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
import context_snapshot as cs
print(cs.ledger_progress(sys.argv[2]))
' "$LIBDIR" "$D")"
if [ "$P1" = "None" ]; then ok "列数 3≠6 时返回 None"
else bad "列数不匹配应返回 None" "None" "$P1"; fi
rm -f "$D/ledger.md"
P2="$(/usr/bin/python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
import context_snapshot as cs
print(cs.ledger_progress(sys.argv[2]))
' "$LIBDIR" "$D")"
if [ "$P2" = "None" ]; then ok "ledger.md 不存在时返回 None"
else bad "文件缺失应返回 None" "None" "$P2"; fi
rm -rf "$T"

echo "[118] 注入体：sources=3 打「·三方」降级标记、inconsistent 非 0 打条数，"
echo "      销账表一行没填时出告警"
T="$(newtmpdir)"; mkctx "$T" 3 4 0
OUT="$(printf '{"cwd":"%s","prompt":"继续"}' "$T" | bash "$CTX_HOOK" 2>/dev/null)"
has "open 行带 stage 与三方降级标记" "$OUT" "CTX-001(debug)·三方·不一致4"
has "销账表无人填出告警" "$OUT" "销账表无人填"
has "告警带上未填行数" "$OUT" "CTX-001(5 行未填)"
rm -rf "$T"

echo "[119] 同一条件下只要有一行填了就不再出「无人填」告警（告警判据是 filled==0，"
echo "      不是 filled<total——填一半属于进行中，不该每轮刷屏）"
T="$(newtmpdir)"; mkctx "$T" 5 0 1
OUT="$(printf '{"cwd":"%s","prompt":"继续"}' "$T" | bash "$CTX_HOOK" 2>/dev/null)"
case "$OUT" in
  *销账表无人填*) bad "已填 1 行不应再出无人填告警" "不含「销账表无人填」" "$OUT" ;;
  *) ok "已填 1 行时无告警" ;;
esac
has "sources=5 时不打三方标记" "$OUT" "CTX-001(debug)"
case "$OUT" in
  *·三方*) bad "sources=5 不应打三方降级标记" "不含「·三方」" "$OUT" ;;
  *) ok "sources=5 不打三方标记" ;;
esac
rm -rf "$T"

echo "[120] 未启用 task-keeper（无 .keeper/）→ 零字节输出，exit 0"
T="$(newtmpdir)"; : > "$T/.git"
OUT="$(printf '{"cwd":"%s","prompt":"继续"}' "$T" | bash "$CTX_HOOK" 2>/dev/null)"
RC=$?
if [ -z "$OUT" ] && [ "$RC" -eq 0 ]; then ok "未启用时零输出，exit 0"
else bad "未启用应零输出且 exit 0" "空输出 rc=0" "rc=$RC out=[$OUT]"; fi
rm -rf "$T"
