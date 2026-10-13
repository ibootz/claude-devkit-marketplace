# H20 · find_queue 自动补建（debug/chore 队列子目录缺失时自动 mkdir，出自
# 2026-08-03 修的自锁死循环，见 hooks/lib/queue_snapshot.py 的 find_queue
# docstring「为什么自动补建」）。依赖 harness.sh 的
# newtmpdir/run_hook/run_chore/ok/bad/has/hasnt。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件自成一体，不依赖其他 case 文件留下的变量或函数。

echo
echo "== H20 · find_queue 自动补建（.keeper/<交付id>/{debug,chore} 缺失子目录自动补建）=="

echo "[69] debug/ 已存在、chore/ 缺失 → 跑 chore 快照后 chore/ 被建出来，且有非零字节输出"
T="$(newtmpdir)"; : > "$T/.git"
mkdir -p "$T/.keeper/_main/debug"
OUT="$(run_chore "$T" '继续')"
if [ -d "$T/.keeper/_main/chore" ]; then ok "chore/ 被自动补建"
else bad "chore/ 应被补建" "存在" "缺失"; fi
BYTES="$(printf '%s' "$OUT" | wc -c | tr -d ' ')"
if [ "$BYTES" -gt 0 ]; then ok "补建当轮 chore 快照有非零字节输出（含队列标题行）"
else bad "chore 快照应有输出" ">0 字节" "$BYTES"; fi
rm -rf "$T"

echo "[70] 反向对称：chore/ 已存在、debug/ 缺失 → 跑 debug 快照后 debug/ 被建出来"
T="$(newtmpdir)"; : > "$T/.git"
mkdir -p "$T/.keeper/_main/chore"
OUT="$(run_hook "$T" '继续')"
if [ -d "$T/.keeper/_main/debug" ]; then ok "debug/ 被自动补建"
else bad "debug/ 应被补建" "存在" "缺失"; fi
BYTES="$(printf '%s' "$OUT" | wc -c | tr -d ' ')"
if [ "$BYTES" -gt 0 ]; then ok "补建当轮 debug 快照有非零字节输出"
else bad "debug 快照应有输出" ">0 字节" "$BYTES"; fi
rm -rf "$T"

echo "[71] .keeper/ 顶层完全不存在 → 两个 hook 都零输出，且不会凭空造出任何 debug/chore 目录（零成本保证的守门断言）"
T="$(newtmpdir)"; : > "$T/.git"
OUT_D="$(run_hook "$T" '继续')"
OUT_C="$(run_chore "$T" '继续')"
if [ -z "$OUT_D" ] && [ -z "$OUT_C" ]; then ok "未启用项目两个 hook 均零输出"
else bad "未启用项目应零输出" "空/空" "debug=[$OUT_D] chore=[$OUT_C]"; fi
FOUND="$(find "$T" -type d \( -name debug -o -name chore \) 2>/dev/null)"
if [ -z "$FOUND" ]; then ok "未启用项目未被凭空造出任何 debug/chore 目录"
else bad "不应存在任何 debug/chore 目录" "空" "$FOUND"; fi
rm -rf "$T"

echo "[72] fixer worktree 场景：delivery 侧 chore/ 缺失，但 fixer 里跑快照不补建、零输出"
# 用确定信息构造——<git-dir>/wt-supply-source 标记文件（wt_supply.py 的
# record_source 写入的同名文件）。keeper_paths.in_fixer_worktree 优先读这个标记，
# 命中即直接判定 fixer、不必再靠「路径含 DBG-\d+ 且是 linked worktree」兜底判据。
# 需要真实 git 仓库——_read_source_mark 靠 `git rev-parse --absolute-git-dir` 定位
# 标记文件该落在哪，假 `.git` 文件（其他用例常用的零成本占位写法）在这里不适用。
DELIVERY="$(newtmpdir)"
git init -q -b master "$DELIVERY" >/dev/null 2>&1
git -C "$DELIVERY" config user.email t@t.t; git -C "$DELIVERY" config user.name t
echo hi > "$DELIVERY/f.txt"
git -C "$DELIVERY" add -A >/dev/null 2>&1
git -C "$DELIVERY" commit -qm init >/dev/null 2>&1
mkdir -p "$DELIVERY/.keeper/_main/debug"     # debug 已存在，chore 缺失
FIXER="$(newtmpdir)"; rmdir "$FIXER"
git -C "$DELIVERY" worktree add -q "$FIXER" -b fixer-branch >/dev/null 2>&1
GITDIR="$(git -C "$FIXER" rev-parse --absolute-git-dir)"
printf '%s' "$DELIVERY" > "$GITDIR/wt-supply-source"
OUT="$(run_chore "$FIXER" '继续')"
if [ -z "$OUT" ]; then ok "fixer worktree 里跑 chore 快照零输出（wt-supply-source 标记命中）"
else bad "fixer worktree 应零输出" "空" "$OUT"; fi
if [ ! -d "$DELIVERY/.keeper/_main/chore" ]; then ok "delivery 侧 chore/ 未被 fixer 补建（fixer 只读不写）"
else bad "delivery 侧 chore/ 不应被 fixer 补建" "不存在" "存在"; fi
rm -rf "$DELIVERY" "$FIXER" 2>/dev/null

echo "[73] 补建当轮不重复注入待拍板计数：debug 与 chore 都缺失，按 plugin.json 真实顺序先跑 debug 快照再跑 chore 快照"
T="$(newtmpdir)"; : > "$T/.git"
mkdir -p "$T/.keeper/_main/decisions"
printf -- '---\nblocking: true\n---\n\n需要拍板 X\n' > "$T/.keeper/_main/decisions/2026-08-03-1000-debug-keeper.md"
OUT_DEBUG="$(run_hook "$T" '继续')"
OUT_CHORE="$(run_chore "$T" '继续')"
if [ -d "$T/.keeper/_main/debug" ] && [ -d "$T/.keeper/_main/chore" ]; then
  ok "debug/chore 两个队列目录均已补建（_sibling_queue_names 生效的前提）"
else
  bad "debug/chore 都应已补建" "均存在" \
    "debug=$([ -d "$T/.keeper/_main/debug" ] && echo 有 || echo 无) chore=$([ -d "$T/.keeper/_main/chore" ] && echo 有 || echo 无)"
fi
COMBINED="$OUT_DEBUG
$OUT_CHORE"
COUNT="$(printf '%s' "$COMBINED" | grep -o '待拍板' | wc -l | tr -d ' ')"
if [ "$COUNT" -eq 1 ]; then
  ok "待拍板计数合计只出现一次（debug 补建 chore 后自认 chore 已启用不再代注，改由 chore 自己注入）"
else
  bad "待拍板计数应合计出现 1 次" "1" "$COUNT"
fi
rm -rf "$T"
