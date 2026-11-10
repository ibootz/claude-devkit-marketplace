# H32 · Codex 宿主下四个注入 hook 整段静默（keeper_routing.py 两个事件、
# queue_snapshot.py、chore_snapshot.py）。依赖 harness.sh 的 newtmpdir/mkissue/
# mkchore/ok/bad 与 run-tests.sh 的 HOOK/HOOK_CHORE/ROUTING/TRIAGE_HOOK。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件自成一体。
# 【为什么静默】keeper 体系靠 `Agent` 派发插件 agents/ 里的 debug-keeper /
# chore-keeper、靠 `SendMessage` 续派；Codex 既没有这两个工具也不加载 agents/，
# 注入的分诊、快照与路由全是做不到的指令。宿主判别与 H10 [46] 同一条：
# 环境变量 PLUGIN_ROOT 非空，或事件 JSON 含 turn_id。

echo
echo "== H32 · Codex 宿主：keeper 注入 hook 整段静默（PLUGIN_ROOT 非空 或 输入含 turn_id）=="

# $1=hook 脚本 $2=事件名 $3=cwd $4=判别方式 claude|env|turn_id
run_host() {
  local payload
  payload="$(python3 -c '
import json, sys
ev = {"hook_event_name": sys.argv[1], "cwd": sys.argv[2], "prompt": "继续"}
if sys.argv[3] == "turn_id":
    ev["turn_id"] = "turn-1"
print(json.dumps(ev))
' "$2" "$3" "$4")"
  if [ "$4" = env ]; then
    printf '%s' "$payload" | PLUGIN_ROOT=/fake/plugin/root bash "$1"
  else
    printf '%s' "$payload" | env -u PLUGIN_ROOT bash "$1"
  fi
}

T="$(newtmpdir)"; : > "$T/.git"
mkissue "$T/.keeper/_main/debug" DBG-001 open P1 "占位问题，触发 debug 快照"
mkchore "$T/.keeper/_main/chore" CHR-001 open ledger "占位杂务，触发 chore 快照"

echo "[205] Claude 宿主（无 PLUGIN_ROOT、无 turn_id）：四个 hook 照常注入"
for pair in "$ROUTING:SessionStart" "$TRIAGE_HOOK:UserPromptSubmit" "$HOOK:UserPromptSubmit" "$HOOK_CHORE:UserPromptSubmit"; do
  h="${pair%:*}"; ev="${pair##*:}"
  OUT="$(run_host "$h" "$ev" "$T" claude)"
  if [ -n "$OUT" ]; then ok "$(basename "$h") 有输出"
  else bad "$(basename "$h") Claude 宿主应注入" "非空" "空"; fi
done

for via in env turn_id; do
  echo "[206/${via}] Codex 宿主（判别=${via}）：四个 hook stdout 全空"
  for pair in "$ROUTING:SessionStart" "$TRIAGE_HOOK:UserPromptSubmit" "$HOOK:UserPromptSubmit" "$HOOK_CHORE:UserPromptSubmit"; do
    h="${pair%:*}"; ev="${pair##*:}"
    OUT="$(run_host "$h" "$ev" "$T" "$via")"
    if [ -z "$OUT" ]; then ok "$(basename "$h") 静默"
    else bad "$(basename "$h") Codex 宿主应静默" "空" "$(printf '%s' "$OUT" | head -c 120)"; fi
  done
done

echo "[207] 只设 CLAUDE_PLUGIN_ROOT 不算 Codex（Codex 也设它，不能拿它判宿主）"
OUT="$(printf '{"hook_event_name":"UserPromptSubmit","cwd":"%s"}' "$T" | env -u PLUGIN_ROOT CLAUDE_PLUGIN_ROOT=/fake bash "$TRIAGE_HOOK")"
if [ -n "$OUT" ]; then ok "CLAUDE_PLUGIN_ROOT 单独存在时照常注入"
else bad "CLAUDE_PLUGIN_ROOT 不应触发 Codex 静默" "非空" "空"; fi

echo "[208] tk-board 的 board.py --link-style code：编号列出 inline code 相对路径（Codex 用）；默认仍是 file:// 链接"
BOARD_PY="$HOOK_DIR/../skills/tk-board/scripts/board.py"
CODE_OUT="$(cd "$T" && python3 "$BOARD_PY" --link-style code)"
FILE_OUT="$(cd "$T" && python3 "$BOARD_PY")"
has "code 形态给相对 cwd 的 inline code 路径" "$CODE_OUT" 'DBG-001 `.keeper/_main/debug/DBG-001/issue.md:1`'
hasnt "code 形态不再出 file:// 链接" "$CODE_OUT" 'file://'
has "默认形态仍是 file:// 链接（Claude 侧不变）" "$FILE_OUT" '[DBG-001](file://'
rm -rf "$T"
