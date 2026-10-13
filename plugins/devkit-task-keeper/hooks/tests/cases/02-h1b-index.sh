# H1b · index.md（v3 取代 STATUS.md，人机共用同一份；v4 起 index.md 入库、
# 链接指向 <id>/issue.md）。依赖 harness.sh 的 mtime/mkissue/run_hook/
# ok/bad/has/hasnt。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】[9]-[11] 直接复用上一个文件 01-h1-debug-snapshot.sh 结尾留下的
# $T（队列所在 worktree 根）与 $Q（"$T/.keeper/_main/debug"）——这两个变量
# 在那个文件里故意没有清理。[11] 用完后 `rm -rf "$T"`，[12]/[13] 各自重新
# newtmpdir，彼此独立。因此本文件必须紧跟在 01-h1-debug-snapshot.sh 之后
# source，不能单独运行或调换顺序。

echo
echo "== H1b · index.md（v3 取代 STATUS.md，人机共用同一份；v4 起 index.md 入库、链接指向 <id>/issue.md）=="

echo "[9] index.md 自动生成，且内容与注入体同源"
run_hook "$T" '继续' > /dev/null
IDX="$Q/index.md"
if [ -f "$IDX" ]; then ok "index.md 生成"
else bad "index.md 应生成" "文件存在" "缺失"; fi
IDXC="$(cat "$IDX" 2>/dev/null)"
has "open 分组标题"     "$IDXC" "## open 4"
has "done 分组标题"     "$IDXC" "## done 2"
has "open 条目带链接（v4：链接指向 <id>/issue.md，不再是 issues/<id>.md）"   "$IDXC" "[DBG-004](DBG-004/issue.md)"
has "done 条目也可点开" "$IDXC" "[DBG-001](DBG-001/issue.md)"
has "标明是派生视图"    "$IDXC" "派生视图"

echo "[10] 幂等：状态没变时不重写（入库后不制造假 diff）"
hasnt "index.md 不含时间戳（年份）" "$IDXC" "2026-"
M1="$(mtime "$IDX")"
sleep 1
run_hook "$T" '继续' > /dev/null
M2="$(mtime "$IDX")"
if [ "$M1" = "$M2" ]; then ok "二次运行不重写文件（mtime 未变）"
else bad "应幂等" "mtime 不变" "$M1 → $M2"; fi

echo "[11] 状态真变了就要刷新"
mkissue "$Q" DBG-010 open P0 "新报的阻断问题"
run_hook "$T" '继续' > /dev/null
IDXC2="$(cat "$IDX")"
has "新 issue 进入索引" "$IDXC2" "DBG-010"
rm -rf "$T"

echo "[12] fixer 的 DBG-* worktree 里只读不写 index.md（并行 fixer 不互相冲突）"
# 判据是「路径含 DBG-\d+ 且是 linked worktree」——本用例的 worktree 目录名带
# DBG-001，命中跳过条件。不带 id 的交付级 worktree 见 [13]。T 与 WT 的 basename
# 都不匹配交付前缀，两者解析出的交付 id 都是兜底桶 _main（同一个队列目录）。
T="$(newtmpdir)"
git -C "$T" init -q 2>/dev/null
git -C "$T" config user.email t@t.t; git -C "$T" config user.name t
Q="$T/.keeper/_main/debug"
mkissue "$Q" DBG-001 open P1 "主工作区里的问题"
git -C "$T" add -A >/dev/null 2>&1
git -C "$T" commit -qm init >/dev/null 2>&1
run_hook "$T" '继续' > /dev/null
if [ -f "$Q/index.md" ]; then ok "主工作区生成 index.md"
else bad "主工作区应生成" "存在" "缺失"; fi
WT="$T/../$(basename "$T")-wt-DBG-001"
git -C "$T" worktree add -q "$WT" -b fix/DBG-001 >/dev/null 2>&1
if [ -d "$WT" ]; then
  WTQ="$WT/.keeper/_main/debug"
  rm -f "$WTQ/index.md"
  OUT="$(run_hook "$WT" '继续')"
  has "worktree 里仍注入队列快照" "$OUT" "open 1"
  if [ ! -f "$WTQ/index.md" ]; then ok "worktree 里不写 index.md"
  else bad "worktree 不应写 index.md" "文件不存在" "被创建了"; fi
  has "在飞标记由 worktree 路径派生" "$OUT" "DBG-001(P1)⚙在飞"
  git -C "$T" worktree remove --force "$WT" >/dev/null 2>&1
else
  echo "  (跳过 worktree 用例：git worktree add 失败)"
fi
rm -rf "$T"

echo "[13] 交付级 worktree（basename 带交付 slug，不带 DBG-id）必须照常重算 index.md，"
echo "     且它自己那份队列是该交付独立的一份（v4：队列跟随交付，不是从主仓继承的视图）"
T="$(newtmpdir)"
git -C "$T" init -q 2>/dev/null
git -C "$T" config user.email t@t.t; git -C "$T" config user.name t
echo placeholder > "$T/f.txt"
git -C "$T" add -A >/dev/null 2>&1
git -C "$T" commit -qm init >/dev/null 2>&1

# worktree 目录的 basename 本身必须以 D-\d+- 打头才能命中 keeper_paths 的
# DELIVERY_RE（^(?:D-\d+-|hotfix-)）——套 $(basename "$T") 前缀会把它挤到中间、
# 匹配不上锚定正则，那样解析出的交付 id 仍会退回 _main 桶，测不出本用例要测的
# 「队列跟随交付」行为。
DWT="$(dirname "$T")/D-001-feat-job-sequence-model"
rm -rf "$DWT" 2>/dev/null   # 清掉可能残留的上次异常退出现场，保证本用例可重入
git -C "$T" worktree add -q "$DWT" -b delivery/D-001 >/dev/null 2>&1
if [ -d "$DWT" ]; then
  # DWT 的 basename 匹配 D-\d+- 前缀，keeper_paths.resolve_delivery_id 解析出的
  # 交付 id 是完整 slug "D-001-feat-job-sequence-model"，与 T 的 _main 桶是两个
  #互不相干的队列目录——这正是 v4「队列跟随交付」要验证的行为。
  DQ="$DWT/.keeper/D-001-feat-job-sequence-model/debug"
  mkissue "$DQ" DBG-001 open P1 "交付 worktree 自己队列里的问题"
  mkissue "$DQ" DBG-002 open P0 "交付 worktree 里新报的阻断问题"
  OUT="$(run_hook "$DWT" '继续')"
  if [ -f "$DQ/index.md" ]; then ok "交付 worktree 里重算了 index.md"
  else bad "交付 worktree 应重算 index.md" "文件存在" "缺失（旧判据的缺陷）"; fi
  DIDX="$(cat "$DQ/index.md" 2>/dev/null)"
  has "新 issue 进入交付 worktree 的索引" "$DIDX" "DBG-002"
  has "注入体与索引同源（都算出 2 条 open）" "$OUT" "open 2"
  hasnt "该 worktree 不带 DBG-id 故不应被判在飞" "$OUT" "⚙在飞"
  git -C "$T" worktree remove --force "$DWT" >/dev/null 2>&1
else
  echo "  (跳过交付 worktree 用例：git worktree add 失败)"
fi
rm -rf "$T"
