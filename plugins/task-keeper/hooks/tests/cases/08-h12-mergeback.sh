# H12 · merge-back 源侧判据收窄（主会话无关 WIP 不该阻断回流）。
# 依赖 harness.sh 的 newtmpdir/ok/bad/has；HOOK_DIR 由 run-tests.sh 提供。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合 · 重要】本文件的 mkmbfixture() 直接调用 04-h8-wt-supply.sh 里
# 定义的 run_supply()、mksmrepo()、mkmainwithsm()（同一个 shell 里靠 source
# 持续生效，本文件不重新定义）。因此本文件必须排在 04-h8-wt-supply.sh 之后
# source，且两者之间不能有别的文件重新定义/清空同名函数。

echo
echo "== H12 · merge-back 源侧判据收窄（主会话无关 WIP 不该阻断回流）=="

echo "[49] dirty_lines 切片精确：porcelain 首行的前导空格不得被 .strip() 吃掉"
T="$(newtmpdir)"
git init -q -b master "$T" >/dev/null 2>&1
git -C "$T" config user.email t@t.t; git -C "$T" config user.name t
echo v1 > "$T/zz.txt"; git -C "$T" add -A >/dev/null 2>&1
git -C "$T" commit -qm init >/dev/null 2>&1
echo v2 > "$T/zz.txt"     # 唯一一项改动，未 staged ⇒ porcelain 首行就是 " M zz.txt"
DP="$(/usr/bin/python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import wt_git as g; print(sorted(g.dirty_paths(sys.argv[2])))' \
  "$HOOK_DIR/../skills/tk-worktree/scripts" "$T" 2>&1)"
has "dirty_paths 取到完整路径 zz.txt（错位会得到 z.txt）" "$DP" "'zz.txt'"
rm -rf "$T" 2>/dev/null

# 造一份「fixer 已在 submodule 层提交、目标父仓已回写 gitlink」的可回流现场（同 [39]）。
# 结果放全局 T / SM_SRC / WT，调用方自己清理。
mkmbfixture() {
  T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
  mkmainwithsm "$T" "$SM_SRC" "libs/sm"
  run_supply init --source "$T" --id "$1" >/dev/null 2>&1
  WT="$T/.keeper/_main/debug/$1/worktree"
  echo "from-wt" > "$WT/libs/sm/b.txt"
  git -C "$WT/libs/sm" add -A >/dev/null 2>&1
  git -C "$WT/libs/sm" commit -qm "wt side change" >/dev/null 2>&1
  git -C "$WT" add libs/sm >/dev/null 2>&1
  git -C "$WT" commit -qm "bump gitlink" >/dev/null 2>&1
}

echo "[50] 源侧无关未跟踪文件不再阻断（死锁修复本体：放行并降级为提示）"
mkmbfixture WT50
echo "主会话手上的活" > "$T/unrelated.md"   # 未跟踪、未 staged、与 libs/sm 无交集
OUT="$(run_supply merge-back --worktree "$WT" 2>&1)"; RC=$?
if [ "$RC" -eq 0 ]; then ok "无关 WIP 挂着也能过前置校验（exit 0）"
else bad "应 exit 0（这正是死锁场景）" "0" "$RC"; fi
has "无关改动降级为提示而不是 blocker" "$OUT" "提示"
has "提示里点名了具体路径"             "$OUT" "unrelated.md"
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[51] 源侧 index 有 staged 内容仍必须阻断（回写 gitlink 的 commit 不带 pathspec，会卷走它）"
mkmbfixture WT51
echo "主会话手上的活" > "$T/unrelated.md"
git -C "$T" add unrelated.md >/dev/null 2>&1     # 同一个文件，只多了一步 git add
OUT="$(run_supply merge-back --worktree "$WT" 2>&1)"; RC=$?
if [ "$RC" -eq 2 ]; then ok "staged 内容阻断（exit 2）"
else bad "应 exit 2" "2" "$RC"; fi
has "报清是 staged 惹的祸、不是笼统的不干净" "$OUT" "staged"
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[52] 源侧未 staged 改动与本次合并路径相交时仍必须阻断（git merge 会覆盖它）"
mkmbfixture WT52
echo "源侧也在改同一个子模块" > "$T/libs/sm/a.txt"   # 使源父仓出现 ` M libs/sm`，与合并路径相交
OUT="$(run_supply merge-back --worktree "$WT" 2>&1)"; RC=$?
if [ "$RC" -eq 2 ]; then ok "相交的未 staged 改动阻断（exit 2）"
else bad "应 exit 2" "2" "$RC"; fi
has "报清阻断理由是与合并路径相交" "$OUT" "相交"
rm -rf "$T" "$SM_SRC" 2>/dev/null
