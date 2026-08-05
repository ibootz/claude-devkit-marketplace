# H23 · 三岔口第 4 支路（sdlc-writer）的条件注入（keeper_routing.py 的
# sdlc_present + build_triage 的 sdlc_line 参数）。判据是纯目录存在性：worktree
# 根本身 + 往上 4 层里任一层存在 `sdlc/specs` 或 `sdlc/deliveries`。
# 依赖 harness.sh 的 newtmpdir/mkrealrepo/run_triage_sess/ok/bad/has/hasnt。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件自成一体，不依赖其他 case 文件留下的变量或函数。
# 【为什么用真实 git 仓库】同 16-h21 / 17-h22：keeper_paths 靠真实 git 命令定位
# 工作区根，假 `.git` 占位文件测不出任何路径解析行为。
# 【为什么不担心 symlink】mktemp 目录在 macOS 上可能带 /private 前缀差异，但
# sdlc/ 是建在同一个文件系统实体下的，realpath 与原路径都能看见它，不影响判定。

echo
echo "== H23 · 三岔口第 4 支路 sdlc-writer 的条件注入（keeper_routing.py：sdlc_present）=="

# 与 14-h19 / 17-h22 同一套抽取方式。
triage_text_h23() {
  printf '%s' "$1" | /usr/bin/python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])
except Exception:
    print("")
'
}

echo "[93] 工作区没有 sdlc 流程目录 → 不注入第 4 支路（未跑 sdlc 的项目一个字符都不付）"
T="$(newtmpdir)"; mkrealrepo "$T"
mkdir -p "$T/.keeper"
TEXT="$(triage_text_h23 "$(run_triage_sess "$T" "sess-A")")"
hasnt "无 sdlc 目录时不出现 sdlc-writer" "$TEXT" "sdlc-writer"
hasnt "无 sdlc 目录时不出现 tk-sdlc" "$TEXT" "tk-sdlc"
has "无 sdlc 目录时三支路本体仍在" "$TEXT" "转 chore-keeper"
rm -rf "$T"

echo "[94] worktree 根下有 sdlc/specs → 注入第 4 支路，且总长度仍 ≤800"
T="$(newtmpdir)"; mkrealrepo "$T"
mkdir -p "$T/.keeper" "$T/sdlc/specs"
TEXT="$(triage_text_h23 "$(run_triage_sess "$T" "sess-A")")"
has "sdlc/specs 命中时出现第 4 支路" "$TEXT" "转 sdlc-writer"
has "第 4 支路指向 tk-sdlc skill" "$TEXT" "tk-sdlc"
has "第 4 支路声明 Gate 交互仍归主会话" "$TEXT" "Gate 交互与拍板仍你自己做"
has "第 4 支路不挤掉原有三支" "$TEXT" "转 debug-keeper"
CHARS="$(/usr/bin/python3 -c 'import sys; print(len(sys.argv[1]))' "$TEXT")"
if [ "$CHARS" -le 800 ]; then ok "命中 sdlc 后 ${CHARS} 字符 ≤800（每轮成本硬上限）"
else bad "命中 sdlc 后应 ≤800 字符" "<=800" "$CHARS"; fi
rm -rf "$T"

echo "[95] 只有 sdlc/deliveries（另一个判据子目录）→ 同样命中"
T="$(newtmpdir)"; mkrealrepo "$T"
mkdir -p "$T/.keeper" "$T/sdlc/deliveries"
TEXT="$(triage_text_h23 "$(run_triage_sess "$T" "sess-A")")"
has "sdlc/deliveries 命中时出现第 4 支路" "$TEXT" "转 sdlc-writer"
rm -rf "$T"

echo "[96] 交付跑在 .sdlc/worktrees/D-NNN-<slug>/ 里、sdlc/ 在三层之上 → 仍命中（这正是最需要它的场景）"
T="$(newtmpdir)"
mkrealrepo "$T/.sdlc/worktrees/D-001-demo"
mkdir -p "$T/.sdlc/worktrees/D-001-demo/.keeper" "$T/sdlc/specs"
TEXT="$(triage_text_h23 "$(run_triage_sess "$T/.sdlc/worktrees/D-001-demo" "sess-A")")"
has "交付 worktree 内向上找到 sdlc/ 时出现第 4 支路" "$TEXT" "转 sdlc-writer"
rm -rf "$T"

echo "[97] 有同名 sdlc/ 目录但里面既无 specs 也无 deliveries → 不命中（避免误命中重名目录）"
T="$(newtmpdir)"; mkrealrepo "$T"
mkdir -p "$T/.keeper" "$T/sdlc/somethingelse"
TEXT="$(triage_text_h23 "$(run_triage_sess "$T" "sess-A")")"
hasnt "空 sdlc/ 目录不应命中" "$TEXT" "sdlc-writer"
rm -rf "$T"

echo "[98] sdlc/ 在查找深度之外（隔 6 层）→ 不命中，判 False 是安全方向"
T="$(newtmpdir)"
mkrealrepo "$T/a/b/c/d/e"
mkdir -p "$T/a/b/c/d/e/.keeper" "$T/sdlc/specs"
TEXT="$(triage_text_h23 "$(run_triage_sess "$T/a/b/c/d/e" "sess-A")")"
hasnt "超出 SDLC_LOOKUP_DEPTH 时不命中" "$TEXT" "sdlc-writer"
rm -rf "$T"
