#!/usr/bin/env bash
# preview-gitlink-bump.sh — 模式 B 只读预览：submodule gitlink bump（不做任何写操作）
#
# 用途：在父仓根目录执行，对指定（或全部直接）submodule fetch 后，列出
#       "当前绑定提交 vs 将要绑定提交" 的 commit message、跨越提交清单，
#       以及 behind/ahead/远端可达性 三量健康诊断，供用户确认后再更新 gitlink。
#
# 与 diagnose-sync.sh 的分工：先跑 diagnose-sync.sh 看三方差异定模式；
#       选了模式 B 之后再跑本脚本生成逐条确认清单（铁律二）。
#
# 「当前绑定」取自**父仓索引里的 gitlink**（git ls-files -s），不是子模块工作树 HEAD——
#       两者可能不等（G≠W），拿工作树当基线会把本地漂移误报成"要跨越的提交"。
#
# 铁律：只处理本仓 .gitmodules 直接声明的 submodule，绝不递归进嵌套子模块。
#
# 用法：
#   ./preview-gitlink-bump.sh                 # 预览全部直接 submodule
#   ./preview-gitlink-bump.sh domains/spsd    # 只预览指定的（可多个）
#
# 注意：本脚本会对目标 submodule 执行 `git fetch`（更新本地 remote-tracking），
#       这是唯一的副作用；不改工作树、不改 gitlink、不 checkout、不 commit。
# 兼容：bash 3.2（macOS 自带），未使用 mapfile 等 4.x 内建。

set -euo pipefail

if [ ! -f .gitmodules ]; then
  echo "错误：当前目录没有 .gitmodules，请在父仓根目录执行。" >&2
  exit 1
fi

# 本层直接声明的 submodule 路径清单（不递归）
# 注：不用 mapfile —— 它是 bash 4+ 内建，macOS 自带 /bin/bash 是 3.2
ALL=$(git config --file .gitmodules --get-regexp '^submodule\..*\.path$' | awk '{print $2}')

if [ "$#" -eq 0 ]; then
  targets="$ALL"
else
  targets="$*"
fi

for sm in $targets; do
  # 只允许本仓直接声明的 submodule（铁律一）
  if ! printf '%s\n' "$ALL" | grep -qx "$sm"; then
    echo "跳过 $sm：不是本仓直接声明的 submodule（拒绝越权 / 递归处理）"
    echo
    continue
  fi

  branch=$(git config --file .gitmodules --get "submodule.${sm}.branch" 2>/dev/null || echo master)
  echo "=== ${sm} (跟踪分支: ${branch}) ==="

  if ! git -C "$sm" rev-parse HEAD >/dev/null 2>&1; then
    echo "⚠️ 子模块未初始化，请先 git submodule update --init -- ${sm}"
    echo
    continue
  fi

  # --no-recurse-submodules：git fetch 默认 recurseSubmodules=on-demand 会递归进嵌套层
  # （违反铁律一，且嵌套层未初始化时刷一串报错噪音）
  git -C "$sm" fetch origin --prune --quiet --no-recurse-submodules

  # 当前绑定 = 父仓索引里的 gitlink（G），不是子模块工作树 HEAD（W）
  cur=$(git ls-files -s -- "$sm" | awk '{print $2}')
  if [ -z "$cur" ]; then
    echo "⚠️ 父仓索引里没有 ${sm} 的 gitlink 条目，跳过"
    echo
    continue
  fi
  wt=$(git -C "$sm" rev-parse HEAD)
  if [ "$cur" != "$wt" ]; then
    echo "⚠️ G≠W：gitlink=${cur:0:7} 但工作树 HEAD=${wt:0:7}"
    echo "   先走模式 A 对齐（./sync-to-gitlink.sh ${sm}）再考虑 bump，否则容易把本地漂移带进 gitlink"
  fi

  if ! tgt=$(git -C "$sm" rev-parse --verify -q "origin/${branch}"); then
    echo "🔴 子模块远端不存在 origin/${branch}，无法确定目标，跳过"
    echo
    continue
  fi

  echo "当前绑定: $(git -C "$sm" log -1 --format='%h %s (%ci)' "$cur")"
  echo "将要绑定: $(git -C "$sm" log -1 --format='%h %s (%ci)' "$tgt")"

  if [ "$cur" = "$tgt" ]; then
    echo "→ 🟢 已是 origin/${branch} tip，无需更新"
    echo
    continue
  fi

  behind=$(git -C "$sm" rev-list --count "${cur}..origin/${branch}")
  ahead=$(git -C "$sm" rev-list --count "origin/${branch}..${cur}")
  reachable=$(git -C "$sm" branch -r --contains "$cur" 2>/dev/null | awk 'NR==1' || true)

  echo "跨越提交（behind=${behind} ahead=${ahead}，最多列 30 条）:"
  # 不接 `| head -30`：head 取满即关管道，git log 收 SIGPIPE 非零退出，
  # 在 set -o pipefail 下整条管道非零 → set -e 让脚本在此自杀（跨越 >30 条时必挂）
  git -C "$sm" log --format='  %h %s' -n 30 "${cur}..${tgt}"

  if [ "$ahead" -gt 0 ]; then
    echo "⚠️ ahead=${ahead}：当前 gitlink 领先跟踪分支，可能钉在未合并分支，确认是否要切回 origin/${branch}"
    echo "   bump 前按 SKILL.md「Gitlink 回退的判读」逐条看 ${tgt:0:7}..${cur:0:7} 是不是 merge 壳"
  fi
  if [ -z "$reachable" ]; then
    echo "🔴 当前 gitlink 在远端不可达（疑似悬空），更新前请核实"
  fi
  echo
done

echo "以上为只读预览，未做任何 gitlink 更改。确认无误后再执行更新。"
