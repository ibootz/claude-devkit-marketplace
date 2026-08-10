#!/usr/bin/env bash
# sync-to-gitlink.sh — 模式 A 执行：把各直接 submodule 的工作树对齐到父仓记录的 gitlink
#
# 做什么：对每个直接 submodule 执行 `git submodule update --init -- <path>`（逐个、非递归），
#         然后逐个断言 `git -C <sm> rev-parse HEAD` == 父仓索引里的 gitlink 值。
# 不做什么：不改 gitlink、不 git add、不 commit、不 push、不进嵌套子模块（铁律一）。
#
# 前置：父仓已 `git pull --no-recurse-submodules`（本脚本不替你 pull 父仓，
#       因为父仓 pull 可能有冲突 / 需要 rebase 决策，必须由人经手）。
#
# 用法（在父仓根目录执行）：
#   ./sync-to-gitlink.sh                 # 对齐全部直接 submodule
#   ./sync-to-gitlink.sh domains/spsd    # 只对齐指定的（可多个）
#
# 安全：子模块内有未提交改动时**跳过并告警**，绝不 -f / reset --hard 覆盖在制品。
# 兼容：bash 3.2（macOS 自带），未使用 mapfile 等 4.x 内建。

set -euo pipefail

if [ ! -f .gitmodules ]; then
  echo "错误：当前目录没有 .gitmodules，请在父仓根目录执行。" >&2
  exit 1
fi

ALL=$(git config --file .gitmodules --get-regexp '^submodule\..*\.path$' | awk '{print $2}')

if [ "$#" -eq 0 ]; then
  targets="$ALL"
else
  targets="$*"
fi

failed=0
skipped=0
synced=0

for sm in $targets; do
  # 只允许本仓直接声明的 submodule（铁律一）
  if ! printf '%s\n' "$ALL" | grep -qx "$sm"; then
    echo "跳过 $sm：不是本仓直接声明的 submodule（拒绝越权 / 递归处理）"
    skipped=$((skipped + 1))
    continue
  fi

  G=$(git ls-files -s -- "$sm" | awk '{print $2}')
  if [ -z "$G" ]; then
    echo "跳过 $sm：父仓索引里没有它的 gitlink 条目"
    skipped=$((skipped + 1))
    continue
  fi

  # 已初始化且有在制品 → 跳过，不覆盖
  if git -C "$sm" rev-parse HEAD >/dev/null 2>&1; then
    W=$(git -C "$sm" rev-parse HEAD)
    if [ "$W" = "$G" ]; then
      echo "🟢 ${sm} 已对齐 ${G:0:7}"
      synced=$((synced + 1))
      continue
    fi
    dirty=$(git -C "$sm" status --porcelain --ignore-submodules=all | wc -l | tr -d ' ')
    if [ "$dirty" != "0" ]; then
      echo "⚠️ 跳过 ${sm}：子模块内有 ${dirty} 处未提交改动，先与用户确认 stash / commit 再对齐"
      skipped=$((skipped + 1))
      continue
    fi
    # 「工作树不是 gitlink 的祖先」有两种成因，混为一谈会把纯落后的子仓全数误拦：
    #   (a) 真分叉——子仓本地有独立提交 / 停在别的分支，对齐会让它们脱离分支，必须跳过；
    #   (b) 本地缺对象——父仓 pull 只搬 gitlink 数值、不搬子仓 commit，新 pin 的对象要靠
    #       后面的 submodule update 才 fetch 下来。此时 --is-ancestor 因对象不存在返回非零，
    #       与 (a) 同形。fresh clone / 未 fetch 的子仓里这是常态而非例外。
    # 故先 cat-file -e 判对象存在性，缺则先 fetch 取对象，再判祖先；仍取不到才放行给 update。
    if ! git -C "$sm" cat-file -e "${G}^{commit}" 2>/dev/null; then
      echo "   ℹ️ ${sm}: gitlink ${G:0:7} 对象本地缺失，先 fetch 子仓取对象再判祖先"
      # --no-recurse-submodules：git fetch 默认 on-demand 会递归进嵌套层（违反铁律一 + 噪音报错）
      git -C "$sm" fetch origin --prune --quiet --no-recurse-submodules \
        || echo "   ⚠️ ${sm} fetch 失败"
    fi
    if git -C "$sm" cat-file -e "${G}^{commit}" 2>/dev/null; then
      if ! git -C "$sm" merge-base --is-ancestor "$W" "$G"; then
        echo "⚠️ 跳过 ${sm}：工作树 ${W:0:7} 不是 gitlink ${G:0:7} 的祖先（本地有独立提交 / 停在别的分支）"
        echo "   先确认这些提交是否要保留：git -C ${sm} log --oneline ${G}..${W}"
        skipped=$((skipped + 1))
        continue
      fi
    else
      echo "   ⚠️ ${sm}: fetch 后仍取不到 gitlink 对象，跳过祖先判定，交由 update 处理（下面仍逐个验证 HEAD）"
    fi
  fi

  echo "→ 对齐 ${sm} 到 ${G:0:7}"
  # 逐个、非递归；不吞报错（--recursive 会半途而废且静默）。
  # -c fetch.recurseSubmodules=no：update 内部若需 fetch，同样不许递归进嵌套层（铁律一）
  if ! git -c fetch.recurseSubmodules=no submodule update --init -- "$sm"; then
    echo "🔴 ${sm} update 失败"
    failed=$((failed + 1))
    continue
  fi

  # 逐个验证到位（不假设 update 成功就一定对齐）
  now=$(git -C "$sm" rev-parse HEAD)
  if [ "$now" = "$G" ]; then
    echo "   ✅ 验证通过：HEAD = gitlink = ${G:0:7}"
    synced=$((synced + 1))
  else
    echo "   🔴 验证失败：HEAD=${now:0:7} ≠ gitlink=${G:0:7}"
    failed=$((failed + 1))
  fi
done

echo
echo "对齐完成：成功 ${synced}，跳过 ${skipped}，失败 ${failed}"
echo "本脚本未改 gitlink、未 git add、未 commit。父仓此刻应当没有因本脚本新增的暂存内容。"
[ "$failed" -gt 0 ] && exit 1
exit 0
