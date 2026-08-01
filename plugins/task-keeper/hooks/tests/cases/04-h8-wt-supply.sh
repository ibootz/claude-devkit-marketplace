# H8 · wt_supply.py（worktree submodule 供给：跨对象库共享 / gitlink 精确读取 /
# 幂等）。依赖 harness.sh 的 newtmpdir/mkissue/ok/bad/has/hasnt；HOOK_DIR 由
# run-tests.sh 提供。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合 · 重要】本文件定义的 `run_supply()`（连同 $WT_SUPPLY）、
# `mksmrepo()`、`mkmainwithsm()` 三个 helper 不止本文件用——它们之后被
# 08-h12-mergeback.sh 的 mkmbfixture 直接调用，靠的是 source 在同一个 shell
# 里持续生效这一点。删除或改名这三者、或把 04 挪到 08 之后 source，都会让
# 08-h12-mergeback.sh 直接报 "command not found"。

echo
echo "== H8 · wt_supply.py（worktree submodule 供给：跨对象库共享 / gitlink 精确读取 / 幂等）=="
# 落点固定 <source>/.keeper/<交付id>/debug/<id>/worktree/（v4：收进它所属那条
# issue 自己的目录，不再是与 debug/ 平级的 .keeper/worktrees/<id>/）——见
# wt_supply.py cmd_init docstring。本节全部用 `git init -b master` 造裸临时目录，
# basename 恒不匹配 keeper_paths.DELIVERY_RE，交付 id 因此恒为兜底桶 _main。

WT_SUPPLY="$HOOK_DIR/../skills/tk-worktree/scripts/wt_supply.py"
run_supply() { /usr/bin/python3 "$WT_SUPPLY" "$@"; }

# 造一个 submodule 源仓（供 `git submodule add` 用）。$1=路径
mksmrepo() {
  git init -q -b master "$1"
  git -C "$1" config user.email t@t.t; git -C "$1" config user.name t
  echo "v1" > "$1/a.txt"
  git -C "$1" add -A >/dev/null 2>&1
  git -C "$1" commit -qm "init" >/dev/null 2>&1
}

# 造一个带一个 submodule 的主仓（固定 -b master）。
# $1=主仓路径 $2=submodule 源路径 $3=submodule 相对路径
# 【为什么 .gitignore 忽略 .keeper/】init 的落点固定是
# `<source>/.keeper/_main/debug/<id>/worktree/`，落在源仓内部。不忽略的话它会以
# `?? .keeper/` 出现在 `git status --porcelain` 里，让源仓变 dirty，撞上
# merge-back 的「源 worktree 父仓不干净」前置校验。本节测的是 wt_supply.py 自身
# 的供给/回流机制，不是 hooks/lib 的 gitignore_findings 三行精确规则，两者判据
# 互不相关，故仍用整树忽略。
mkmainwithsm() {
  git init -q -b master "$1"
  git -C "$1" config user.email t@t.t; git -C "$1" config user.name t
  printf '.keeper/\n' > "$1/.gitignore"
  git -C "$1" -c protocol.file.allow=always submodule add -q "$2" "$3" >/dev/null 2>&1
  git -C "$1" add -A >/dev/null 2>&1
  git -C "$1" commit -qm "add submodule $3" >/dev/null 2>&1
}

echo "[31] 无 submodule 的仓：init 成功建出落点，supply 明确报无需供给（exit 0）"
T="$(newtmpdir)"
git init -q -b master "$T" >/dev/null 2>&1
git -C "$T" config user.email t@t.t; git -C "$T" config user.name t
printf '.keeper/\n' > "$T/.gitignore"
echo hi > "$T/f.txt"; git -C "$T" add -A >/dev/null 2>&1; git -C "$T" commit -qm init >/dev/null 2>&1
OUT="$(run_supply init --source "$T" --id WT31 2>&1)"; RC=$?
if [ "$RC" -eq 0 ]; then ok "无 submodule 仓 init exit 0"
else bad "应 exit 0" "0" "$RC"; fi
WT="$T/.keeper/_main/debug/WT31/worktree"
if [ -d "$WT" ]; then ok "父仓工作区落在 <source>/.keeper/<交付id>/debug/<id>/worktree/（落点固定，不接受路径参数）"
else bad "落点目录应存在" "$WT" "缺失"; fi
OUT2="$(run_supply supply --worktree "$WT" 2>&1)"; RC2=$?
if [ "$RC2" -eq 0 ]; then ok "supply 优雅跳过 exit 0"
else bad "应 exit 0" "0" "$RC2"; fi
has "明确输出跳过信息" "$OUT2" "没有 .gitmodules，无 submodule 需要供给"
rm -rf "$T" 2>/dev/null

echo "[32] init 供给后 <worktree>/<sm>/.git 是文件，gitdir 指向源仓共享对象库"
T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
mkmainwithsm "$T" "$SM_SRC" "libs/sm"
run_supply init --source "$T" --id WT32 >/dev/null 2>&1
WT="$T/.keeper/_main/debug/WT32/worktree"
DOTGIT="$WT/libs/sm/.git"
if [ -f "$DOTGIT" ]; then ok "子模块 .git 是文件（是目录就说明建成了独立对象库）"
else bad "应为文件" "文件" "$([ -d "$DOTGIT" ] && echo 目录 || echo 缺失)"; fi
CONTENT="$(cat "$DOTGIT" 2>/dev/null)"
has ".git 文件内容含 gitdir:" "$CONTENT" "gitdir:"
SRC_GITDIR="$(git -C "$T" rev-parse --path-format=absolute --git-common-dir)"
has "gitdir 指向源仓 .git/modules/<sm>/worktrees/（对象库共享）" "$CONTENT" "$SRC_GITDIR/modules/libs/sm/worktrees/"
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[33] gitlink 取自**源侧**父仓 index，不是主 checkout 当前分支（回归重点）"
T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
mkmainwithsm "$T" "$SM_SRC" "libs/sm"
SHA1="$(git -C "$T" rev-parse ":libs/sm")"        # 主 checkout(master) 记的 gitlink
run_supply init --source "$T" --id SRC33 >/dev/null 2>&1
SRC="$T/.keeper/_main/debug/SRC33/worktree"         # 这一份本身是 linked worktree，当"源"用
echo "v2" > "$SRC/libs/sm/a.txt"
git -C "$SRC/libs/sm" add -A >/dev/null 2>&1
git -C "$SRC/libs/sm" commit -qm "v2" >/dev/null 2>&1
SHA2="$(git -C "$SRC/libs/sm" rev-parse HEAD)"
git -C "$SRC" add libs/sm >/dev/null 2>&1
git -C "$SRC" commit -qm "bump libs/sm to v2" >/dev/null 2>&1
if [ "$(git -C "$SRC" rev-parse ":libs/sm")" = "$SHA2" ] && [ "$SHA1" != "$SHA2" ]; then
  ok "前置构造成立：源侧记 v2 的 gitlink，主 checkout 仍记 v1"
else
  bad "前置构造应让两侧 gitlink 不同" "src=$SHA2 / main=$SHA1" "src=$(git -C "$SRC" rev-parse ":libs/sm")"
fi
run_supply init --source "$SRC" --id WT33 >/dev/null 2>&1
GOT="$(git -C "$SRC/.keeper/_main/debug/WT33/worktree/libs/sm" rev-parse HEAD 2>/dev/null)"
if [ "$GOT" = "$SHA2" ] && [ "$GOT" != "$SHA1" ]; then
  ok "供给出的子模块 HEAD 等于源侧记录的 gitlink，不是主 checkout(master) 的旧值"
else
  bad "应等于源侧 gitlink ${SHA2}（主 checkout 记的是 ${SHA1}）" "$SHA2" "$GOT"
fi
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[34] 幂等：init 连跑两次，第二次跳过父仓创建、submodule 层报已 ok，exit 0"
T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
mkmainwithsm "$T" "$SM_SRC" "libs/sm"
run_supply init --source "$T" --id WT34 >/dev/null 2>&1
OUT2="$(run_supply init --source "$T" --id WT34 2>&1)"; RC2=$?
if [ "$RC2" -eq 0 ]; then ok "第二次 init exit 0（不重建、不报错）"
else bad "应 exit 0" "0" "$RC2"; fi
has "第二次跳过父仓工作区创建" "$OUT2" "父仓工作区已存在且分支一致"
has "submodule 层报已 ok 跳过" "$OUT2" "已 ok，跳过"
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[35] status 区分 empty(未供给)与 ok(已供给)，exit code 分别为 2 与 0"
T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
mkmainwithsm "$T" "$SM_SRC" "libs/sm"
WT="$T/.keeper/_main/debug/WT35/worktree"
git -C "$T" worktree add -q "$WT" -b b35 >/dev/null 2>&1
OUT="$(run_supply status --worktree "$WT" --source "$T" 2>&1)"; RC=$?
has "未供给时状态为 empty" "$OUT" "empty"
if [ "$RC" -eq 2 ]; then ok "有非 ok 层时 status exit 2"
else bad "应 exit 2" "2" "$RC"; fi
run_supply supply --worktree "$WT" --source "$T" >/dev/null 2>&1
OUT="$(run_supply status --worktree "$WT" 2>&1)"; RC=$?    # 刻意不给 --source
has "供给后状态为 ok" "$OUT" "ok"
if [ "$RC" -eq 0 ]; then ok "全 ok 时 status exit 0，且 --source 可省（supply 已把源记进 gitdir）"
else bad "应 exit 0" "0" "$RC"; fi
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[36] supply 缺 --source 且 gitdir 无源记录 → fail-loud，不猜、不默认用主 checkout"
T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
mkmainwithsm "$T" "$SM_SRC" "libs/sm"
WT="$T/.keeper/_main/debug/WT36/worktree"
git -C "$T" worktree add -q "$WT" -b b36 >/dev/null 2>&1
OUT="$(run_supply supply --worktree "$WT" 2>&1)"; RC=$?
if [ "$RC" -ne 0 ]; then ok "缺源信息时非零退出"
else bad "应非零退出" "非 0" "$RC"; fi
has "报错点明缺的是源记录" "$OUT" "wt-supply-source"
has "给出可操作的下一步" "$OUT" "建议下一步"
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[37] explain-scope 只读反推 submodule 集合，且**不**裁剪 init 的全量供给"
T="$(newtmpdir)"; SM_SRC1="$(newtmpdir)"; mksmrepo "$SM_SRC1"; SM_SRC2="$(newtmpdir)"; mksmrepo "$SM_SRC2"
git init -q -b master "$T" >/dev/null 2>&1
git -C "$T" config user.email t@t.t; git -C "$T" config user.name t
printf '.keeper/\n' > "$T/.gitignore"
git -C "$T" -c protocol.file.allow=always submodule add -q "$SM_SRC1" "libs/sm1" >/dev/null 2>&1
git -C "$T" -c protocol.file.allow=always submodule add -q "$SM_SRC2" "libs/sm2" >/dev/null 2>&1
git -C "$T" add -A >/dev/null 2>&1
git -C "$T" commit -qm "add two submodules" >/dev/null 2>&1
run_supply init --source "$T" --id WT37 >/dev/null 2>&1
WT="$T/.keeper/_main/debug/WT37/worktree"
mkissue "$T/.keeper/_main/debug" DBG-100 open "" "只涉及 sm1"
printf -- '---\nid: DBG-100\nsummary: 只涉及 sm1\nstatus: open\n---\n\n# DBG-100\n\n出错文件是 `libs/sm1/a.txt:3`\n' > "$T/.keeper/_main/debug/DBG-100/issue.md"
OUT="$(run_supply explain-scope --worktree "$WT" --from-triage "$T/.keeper/_main/debug/DBG-100/issue.md" 2>&1)"; RC=$?
if [ "$RC" -eq 0 ]; then ok "explain-scope exit 0"
else bad "应 exit 0" "0" "$RC"; fi
has "反推命中 libs/sm1" "$OUT" "libs/sm1"
hasnt "未把无关的 libs/sm2 算进命中集合" "$OUT" "libs/sm2"
if [ -f "$WT/libs/sm1/.git" ] && [ -f "$WT/libs/sm2/.git" ]; then
  ok "两个 submodule 都已供给（explain-scope 的结果不裁剪供给范围）"
else
  bad "两层都应已供给" "sm1 与 sm2 的 .git 都是文件" \
      "sm1=$([ -f "$WT/libs/sm1/.git" ] && echo 有 || echo 无) sm2=$([ -f "$WT/libs/sm2/.git" ] && echo 有 || echo 无)"
fi
rm -rf "$T" "$SM_SRC1" "$SM_SRC2" 2>/dev/null

echo "[38] remove 深度优先清干净，且不污染源侧 submodule 初始化状态（前缀不得从空格变 -）"
T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
mkmainwithsm "$T" "$SM_SRC" "libs/sm"
run_supply init --source "$T" --id WT38 >/dev/null 2>&1
WT="$T/.keeper/_main/debug/WT38/worktree"
BEFORE="$(git -C "$T" submodule status libs/sm)"
OUT="$(run_supply remove --worktree "$WT" --yes 2>&1)"; RC=$?
if [ "$RC" -eq 0 ]; then ok "remove --yes 正常退出"
else bad "应 exit 0" "0" "$RC"; fi
if [ ! -e "$WT" ]; then ok "目标 worktree 整体清除（缺省连父仓工作区一起删）"
else bad "目标目录应已删除" "不存在" "仍存在"; fi
AFTER="$(git -C "$T" submodule status libs/sm)"
if [ "${BEFORE:0:1}" = "${AFTER:0:1}" ]; then
  ok "源侧 submodule status 前缀未被污染（证明没跑 submodule deinit -f）"
else
  bad "源侧前缀不应变化" "${BEFORE:0:1}" "${AFTER:0:1}"
fi
CLEAN="$(git -C "$T" status --short 2>&1)"
if [ -z "$CLEAN" ]; then ok "源 worktree 清理后仍干净"
else bad "源 worktree 应干净" "空" "$CLEAN"; fi
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[39] merge-back 默认 dry-run 零副作用（源侧 submodule HEAD 未变、源仓 index 未 stage）"
T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
mkmainwithsm "$T" "$SM_SRC" "libs/sm"
run_supply init --source "$T" --id WT39 >/dev/null 2>&1
WT="$T/.keeper/_main/debug/WT39/worktree"
echo "from-wt" > "$WT/libs/sm/b.txt"
git -C "$WT/libs/sm" add -A >/dev/null 2>&1
git -C "$WT/libs/sm" commit -qm "wt side change" >/dev/null 2>&1
git -C "$WT" add libs/sm >/dev/null 2>&1
git -C "$WT" commit -qm "bump gitlink" >/dev/null 2>&1
SRC_SM_HEAD_BEFORE="$(git -C "$T/libs/sm" rev-parse HEAD)"
OUT="$(run_supply merge-back --worktree "$WT" 2>&1)"; RC=$?
if [ "$RC" -eq 0 ]; then ok "前置校验通过、dry-run exit 0"
else bad "应 exit 0（前置校验应通过）" "0" "$RC"; fi
has "输出标明 dry-run" "$OUT" "dry-run"
has "逐层打印旧 gitlink 供 Human 核对（gitlink 红线要求的形态）" "$OUT" "旧 gitlink"
SRC_SM_HEAD_AFTER="$(git -C "$T/libs/sm" rev-parse HEAD)"
if [ "$SRC_SM_HEAD_BEFORE" = "$SRC_SM_HEAD_AFTER" ]; then ok "源侧 submodule HEAD 未变"
else bad "HEAD 不应变化" "$SRC_SM_HEAD_BEFORE" "$SRC_SM_HEAD_AFTER"; fi
STAGED="$(git -C "$T" diff --cached --name-only)"
if [ -z "$STAGED" ]; then ok "源仓 index 未 stage 任何东西"
else bad "index 应为空" "空" "$STAGED"; fi
rm -rf "$T" "$SM_SRC" 2>/dev/null
