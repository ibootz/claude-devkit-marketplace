#!/usr/bin/env bash
# diagnose-sync.sh — 只读诊断父仓 + 各直接 submodule 的三方差异（S0，永远第一步）
#
# 三方差异模型：
#   G = gitlink   父仓索引记录的"子模块应停在哪"   git ls-files -s <sm>
#   W = 工作树    子模块目录里实际 checkout 的 commit  git -C <sm> rev-parse HEAD
#   R = 远端 tip  子仓跟踪分支最新                     git -C <sm> rev-parse origin/<branch>
#
#   G≠W        → 模式 A（父仓 pull + 对齐工作树），不动 gitlink
#   G=W 且 W≠R → 模式 B（bump gitlink 到 R），会产生父仓提交
#   两者兼有   → 先 A 后 B
#
# 铁律：只处理本仓 .gitmodules 直接声明的 submodule，绝不递归进嵌套子模块。
#
# 用法（在父仓根目录执行）：
#   ./diagnose-sync.sh                 # 诊断全部直接 submodule
#   ./diagnose-sync.sh domains/spsd    # 只诊断指定的（可多个）
#
# 副作用：仅 `git fetch`（父仓 + 目标子模块的 remote-tracking）。
#         不改工作树、不改 gitlink、不 checkout、不 commit、不 pull。
# 兼容：bash 3.2（macOS 自带），未使用 mapfile 等 4.x 内建。

set -euo pipefail

if [ ! -f .gitmodules ]; then
  echo "错误：当前目录没有 .gitmodules，请在父仓根目录执行。" >&2
  exit 1
fi

# ---------- 父仓 ----------
echo "########## 父仓 ##########"
echo "分支: $(git rev-parse --abbrev-ref HEAD)"
git fetch --no-recurse-submodules --prune --quiet || echo "⚠️ 父仓 fetch 失败，下面的 behind/ahead 可能过期"

upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)
if [ -n "$upstream" ]; then
  p_behind=$(git rev-list --count "HEAD..${upstream}")
  p_ahead=$(git rev-list --count "${upstream}..HEAD")
  echo "上游: ${upstream}  behind=${p_behind} ahead=${p_ahead}"
  if [ "$p_behind" -gt 0 ]; then
    echo "  待拉取的提交（最多 10 条）:"
    # 不用 `| head -10`：head 取满即关闭管道，git log 收到 SIGPIPE 非零退出，
    # 在 set -o pipefail 下整条管道非零 → set -e 让脚本在此自杀（凡 behind>0 必挂）。
    # git 自带 -n 的一律用 -n，不接 head。
    git log --format='    %h %s' -n 10 "HEAD..${upstream}"
  fi
else
  echo "上游: 无（当前分支未设置 tracking branch）"
fi

# 父仓未提交改动：子模块条目单列，其它文件另列——前者可能只是 W≠G，后者是真在制品
# 同上：不接 head。git status 无限行参数，故先收进变量，再用 awk 限行
# （awk 读完全部输入才结束，不提前关闭管道，无 SIGPIPE）。
dirty_other_list=$(git status --porcelain --ignore-submodules=all)
if [ -n "$dirty_other_list" ]; then
  dirty_other=$(printf '%s\n' "$dirty_other_list" | wc -l | tr -d ' ')
  echo "⚠️ 父仓有 ${dirty_other} 处未提交改动（不含子模块条目），拉取前先与用户确认 stash / commit / 放弃："
  printf '%s\n' "$dirty_other_list" | awk 'NR<=20'
fi
echo

# ---------- 子模块 ----------
# 本层直接声明的 submodule 路径清单（不递归）
ALL=$(git config --file .gitmodules --get-regexp '^submodule\..*\.path$' | awk '{print $2}')

if [ "$#" -eq 0 ]; then
  targets="$ALL"
else
  targets="$*"
fi

need_a=0
need_b=0

for sm in $targets; do
  # 只允许本仓直接声明的 submodule（铁律一）
  if ! printf '%s\n' "$ALL" | grep -qx "$sm"; then
    echo "跳过 $sm：不是本仓直接声明的 submodule（拒绝越权 / 递归处理）"
    echo
    continue
  fi

  branch=$(git config --file .gitmodules --get "submodule.${sm}.branch" 2>/dev/null || echo master)
  echo "########## ${sm} (跟踪分支: ${branch}) ##########"

  # G：父仓索引里的 gitlink（父仓将提交的值，不是工作树的值）
  G=$(git ls-files -s -- "$sm" | awk '{print $2}')
  if [ -z "$G" ]; then
    echo "⚠️ 父仓索引里没有 ${sm} 的 gitlink 条目，跳过"
    echo
    continue
  fi

  if ! git -C "$sm" rev-parse HEAD >/dev/null 2>&1; then
    echo "G(gitlink) = ${G:0:7}"
    echo "⚠️ 子模块未初始化 / 未 clone → 属于模式 A：git submodule update --init -- ${sm}"
    need_a=1
    echo
    continue
  fi

  W=$(git -C "$sm" rev-parse HEAD)
  # --no-recurse-submodules 不是可选项：git fetch 默认 recurseSubmodules=on-demand，
  # 会顺着子仓自己的 .gitmodules 递归进嵌套层（违反铁律一，且嵌套层未初始化时刷一串报错噪音）。
  git -C "$sm" fetch origin --prune --quiet --no-recurse-submodules || echo "⚠️ ${sm} fetch 失败，R 可能过期"
  R=$(git -C "$sm" rev-parse --verify -q "origin/${branch}" || true)

  echo "G(gitlink)  = ${G:0:7}  $(git -C "$sm" log -1 --format='%s (%ci)' "$G" 2>/dev/null || echo '（本地没有该对象，需 fetch 子仓）')"
  echo "W(工作树)   = ${W:0:7}  $(git -C "$sm" log -1 --format='%s (%ci)' "$W")"
  if [ -n "$R" ]; then
    echo "R(远端tip)  = ${R:0:7}  $(git -C "$sm" log -1 --format='%s (%ci)' "$R")"
  else
    echo "R(远端tip)  = 🔴 远端不存在 origin/${branch}"
  fi

  # 判级
  if [ "$G" != "$W" ]; then
    echo "→ 【模式 A】G≠W：工作树代码与父仓声明不一致，子模块目录里是过期 / 漂移的代码"
    # 「非祖先」有两种成因，必须先分辨：真分叉 vs 本地缺对象。
    # 父仓 pull 只搬 gitlink 数值、不搬子仓 commit，故新 pin 的对象在子仓本地常常还不存在，
    # --is-ancestor 此时同样返回非零。不先 cat-file -e 判存在性就会把纯落后误报成有独立提交。
    if ! git -C "$sm" cat-file -e "${G}^{commit}" 2>/dev/null; then
      echo "   ℹ️ gitlink 对象 ${G:0:7} 子仓本地不存在（fetch 未取到），祖先关系无法判定"
      echo "      这不等于分叉；对齐时 sync-to-gitlink.sh 会先 fetch 取对象再判"
    elif git -C "$sm" merge-base --is-ancestor "$W" "$G"; then
      echo "   工作树落后 gitlink $(git -C "$sm" rev-list --count "${W}..${G}") 个提交，对齐即可，无风险"
    else
      echo "   ⚠️ 工作树不是 gitlink 的祖先（本地有独立提交 / 停在别的分支），对齐前确认这些提交是否要保留"
    fi
    need_a=1
  fi

  if [ -n "$R" ] && [ "$G" != "$R" ]; then
    behind=$(git -C "$sm" rev-list --count "${G}..${R}" 2>/dev/null || echo '?')
    ahead=$(git -C "$sm" rev-list --count "${R}..${G}" 2>/dev/null || echo '?')
    echo "→ 【模式 B 可选】G≠R：gitlink 落后远端 tip（behind=${behind} ahead=${ahead}），bump 后父仓会产生提交"
    [ "$ahead" != "0" ] && echo "   ⚠️ ahead=${ahead}：gitlink 领先跟踪分支，可能钉在未合并分支，bump 前先判读是否回退"
    need_b=1
  fi

  # 对象缺失时 branch --contains 会报错并返回空 → 与「真悬空」同形，故分开判
  if git -C "$sm" cat-file -e "${G}^{commit}" 2>/dev/null; then
    reachable=$(git -C "$sm" branch -r --contains "$G" 2>/dev/null | awk 'NR==1' || true)
    [ -z "$reachable" ] && echo "🔴 当前 gitlink 在子仓远端不可达（疑似悬空），别人 clone 会断，需子仓 owner push"
  fi

  # 子模块内部的未提交改动（真在制品，跟 G/W/R 无关）
  sm_dirty=$(git -C "$sm" status --porcelain --ignore-submodules=all | wc -l | tr -d ' ')
  [ "$sm_dirty" != "0" ] && echo "⚠️ 子模块内有 ${sm_dirty} 处未提交改动，对齐 / checkout 前先与用户确认（禁止 -f / reset --hard 覆盖）"

  [ "$G" = "$W" ] && { [ -z "$R" ] || [ "$G" = "$R" ]; } && echo "→ 🟢 G=W=R，无需动作"
  echo
done

echo "########## 结论 ##########"
[ "$need_a" = "1" ] && echo "存在 G≠W → 需要模式 A（git pull --no-recurse-submodules && ./sync-to-gitlink.sh），不动 gitlink、无父仓提交"
[ "$need_b" = "1" ] && echo "存在 G≠R → 可选模式 B（./preview-gitlink-bump.sh 预览确认后 bump），会产生父仓提交"
[ "$need_a" = "1" ] && [ "$need_b" = "1" ] && echo "两者兼有 → 必须先 A 再判断要不要 B，否则 bump 会把本地漂移带进 gitlink"
[ "$need_a" = "0" ] && [ "$need_b" = "0" ] && echo "🟢 全部对齐，无需动作"
echo
echo "以上为只读诊断（唯一副作用是 fetch）。走 A 还是 B 由用户决定，不要替用户默认选。"
