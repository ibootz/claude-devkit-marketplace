#!/usr/bin/env bash
# user-prompt-submit-codegraph.js 的 gating 回归用例。
# 判据两侧都覆盖：该注入的（仓根 / submodule / 已建图 worktree）与该静默的
# （未建图 worktree / 无图仓 / 非仓目录）。两条曾经判错的边界各留一条用例：
#   - submodule 的 gitdir 同时含 modules 与 worktrees（`.git/modules/<sub>/worktrees/<sub>`）
#   - 未建图 worktree 不得认领父仓的图（父仓图里是另一个分支的符号）
# 跑法：bash hooks/tests/codegraph-hint-gating.sh

set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/user-prompt-submit-codegraph.js"
B="$(mktemp -d "${TMPDIR:-/tmp}/codegraph-hint.XXXXXX")"
trap 'rm -rf "$B"' EXIT

mkdir -p "$B/repo/.git" "$B/repo/.codegraph"
mkdir -p "$B/repo/sub/deep"; echo "gitdir: $B/repo/.git/modules/sub" > "$B/repo/sub/.git"
mkdir -p "$B/repo/.wt/W/sub"; echo "gitdir: $B/repo/.git/worktrees/W" > "$B/repo/.wt/W/.git"
echo "gitdir: $B/repo/.git/modules/sub/worktrees/sub" > "$B/repo/.wt/W/sub/.git"
mkdir -p "$B/repo/.wt/G/.codegraph" "$B/repo/.wt/G/sub"
echo "gitdir: $B/repo/.git/worktrees/G" > "$B/repo/.wt/G/.git"
echo "gitdir: $B/repo/.git/modules/sub/worktrees/sub" > "$B/repo/.wt/G/sub/.git"
mkdir -p "$B/repo2/.git"

pass=0; fail=0
t() { # $1=cwd $2=inject|silent $3=label
  n=$(printf '%s' "{\"cwd\":\"$1\"}" | node "$HOOK" 2>/dev/null | wc -c | tr -d ' ')
  got=$([ "$n" -gt 0 ] && echo inject || echo silent)
  if [ "$got" = "$2" ]; then pass=$((pass+1)); printf 'PASS %-8s %s\n' "$got" "$3"
  else fail=$((fail+1)); printf 'FAIL %-8s %s (期望 %s)\n' "$got" "$3" "$2"; fi
}

t "$B/repo"           inject "仓根有图"
t "$B/repo/sub/deep"  inject "submodule 深层 → 穿过 modules 找到父图"
t "$B/repo/.wt/W"     silent "未建图 worktree → 不认父仓的图"
t "$B/repo/.wt/W/sub" silent "未建图 worktree 内 submodule → 停在 worktree 边界"
t "$B/repo/.wt/G"     inject "已建图 worktree"
t "$B/repo/.wt/G/sub" inject "已建图 worktree 内 submodule（gitdir 含 modules+worktrees）"
t "$B/repo2"          silent "无图独立仓"
t "/tmp"              silent "非仓目录"

n=$(printf '%s' "{\"cwd\":\"$B/repo\"}" | CODEGRAPH_HINT=off node "$HOOK" 2>/dev/null | wc -c | tr -d ' ')
if [ "$n" = "0" ]; then pass=$((pass+1)); echo "PASS silent   CODEGRAPH_HINT=off 关闭注入"
else fail=$((fail+1)); echo "FAIL inject   CODEGRAPH_HINT=off 关闭注入 (期望 silent)"; fi

printf 'not-json' | node "$HOOK" >/dev/null 2>&1
if [ $? -eq 0 ]; then pass=$((pass+1)); echo "PASS exit=0   坏 payload 不崩（退回 process.cwd()）"
else fail=$((fail+1)); echo "FAIL          坏 payload 导致非零退出"; fi

echo "=== pass=$pass fail=$fail ==="
[ "$fail" -eq 0 ]
