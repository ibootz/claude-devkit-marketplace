# H10 · debug worktree 强制删除守卫（fixer 未提交产物防误删，ask 而非 deny）。
# 依赖 harness.sh 的 ok/bad；HOOK_DIR 由 run-tests.sh 提供。
# 本节自己定义 DESTROYG / run_destroyg / destroyg_ask / destroyg_pass /
# run_destroyg_codex（只在本文件内使用）。
# run_destroyg 一律 `env -u PLUGIN_ROOT` 跑，模拟 Claude 宿主——即使测试本身在
# Codex 会话里执行，[43]～[45] 断言的 ask 也不会被宿主判别翻成 deny。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——同 H9，全部用例都是硬编码路径字面量，不依赖其他 case 文件。
# 【格式说明】原文件里 H9 与 H10 的标题之间没有空行分隔（其余相邻 H 节之间都有
# 一行空输出），本文件因此不像其他 case 文件那样在开头加空 `echo`——这是对原始
# 输出的逐字保留，不是遗漏。

echo "== H10 · debug worktree 强制删除守卫（fixer 未提交产物防误删，ask 而非 deny）=="
DESTROYG="$HOOK_DIR/pre-tool-use-debug-worktree-destroy.sh"
run_destroyg() {   # $1=command  $2=cwd（可省略）
  python3 -c '
import json,sys
ev = {"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":sys.argv[1]}}
if len(sys.argv) > 2 and sys.argv[2]:
    ev["cwd"] = sys.argv[2]
print(json.dumps(ev))
' "$1" "${2:-}" | env -u PLUGIN_ROOT bash "$DESTROYG"
}
destroyg_ask() {   # $1=用例名  $2=command  $3=cwd（可省略）—— 断言 ask
  case "$(run_destroyg "$2" "${3:-}")" in
    *'"permissionDecision": "ask"'*) ok "$1" ;;
    *) bad "$1" "ask" "$(run_destroyg "$2" "${3:-}")" ;;
  esac
}
destroyg_pass() {  # $1=用例名  $2=command  $3=cwd（可省略）—— 断言静默放行
  out="$(run_destroyg "$2" "${3:-}")"
  if [ -z "$out" ]; then ok "$1"; else bad "$1" "空（放行）" "$out"; fi
}

echo "[43] 三种强制删除形态命中 DBG worktree 路径 → ask（v4 布局：.keeper/<交付id>/debug/<DBG-id>/worktree/，含 _main 兜底桶）"
destroyg_ask "git worktree remove --force（有交付）" 'git worktree remove --force /repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-017/worktree'
destroyg_ask "git worktree remove --force（_main 兜底桶）" 'git worktree remove --force /repo/.keeper/_main/debug/DBG-001/worktree'
destroyg_ask "git -C 带 -f 的 worktree remove"    'git -C /repo worktree remove -f /repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-017/worktree'
destroyg_ask "rm -rf 裸位置参数路径"              'rm -rf /repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-020/worktree'
destroyg_ask "rm -fr 合并短选项换序"              'rm -fr /repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-020/worktree/sm'
destroyg_ask "无路径字面量，靠 cwd 兜底"          'rm -rf sm' '/repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-021/worktree'
destroyg_ask "git clean -fdx，靠 cwd 兜底"        'git clean -fdx' '/repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-022/worktree'

echo "[44] 路径落在 .keeper/<交付id>/debug/<DBG-id>/worktree/，但命令本身没构成强制删除形态 → 放行"
destroyg_pass "worktree remove 不带 --force"     'git worktree remove /repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-017/worktree'
destroyg_pass "rm 不带递归标志，删单个文件"      'rm /repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-017/worktree/a.txt'
destroyg_pass "非删除命令不误伤"                 'git -C /repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-017/worktree status'
destroyg_pass "git clean dry-run 没有 -f"         'git clean -n'

echo "[45] 命令构成强制删除形态，但路径不在管辖范围内（交付 worktree / 已废弃的 v3 布局）→ 放行"
destroyg_pass "交付 worktree 不是本守卫管辖范围" 'rm -rf /repo/.sdlc/worktrees/D-001-feat'
destroyg_pass "旧 v3 布局字面量（.keeper/worktrees/）不再命中——迁移是排他式的" 'rm -rf /repo/.keeper/worktrees/DBG-017'
destroyg_pass "非 Bash 无 command 字段"           ''

echo "[46] Codex 宿主：ask 改 deny + 确认标记 DEVKIT_CONFIRMED=1（宿主判别 = env PLUGIN_ROOT 非空 或 输入含 turn_id）"
DESTROY_CMD='rm -rf /repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-020/worktree'
run_destroyg_codex() {   # $1=command  $2=判别方式 env|turn_id
  if [ "$2" = env ]; then
    python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":sys.argv[1]}}))' "$1" \
      | PLUGIN_ROOT=/fake/plugin/root bash "$DESTROYG"
  else
    python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Bash","turn_id":"turn-1","tool_input":{"command":sys.argv[1]}}))' "$1" \
      | env -u PLUGIN_ROOT bash "$DESTROYG"
  fi
}
destroyg_ask "Claude 宿主（无 PLUGIN_ROOT、无 turn_id）仍 ask" "$DESTROY_CMD"
destroyg_ask "Claude 宿主带了标记也照旧 ask（标记只在 Codex 生效）" "DEVKIT_CONFIRMED=1 $DESTROY_CMD"
for via in env turn_id; do
  out="$(run_destroyg_codex "$DESTROY_CMD" "$via")"
  has "Codex（$via 判别）无标记 → deny" "$out" '"permissionDecision": "deny"'
  has "Codex（$via 判别）deny 理由保留原 ask 文案" "$out" '需要 Human 确认后再继续'
  has "Codex（$via 判别）deny 理由带确认标记尾注" "$out" 'Codex 不支持确认弹框'
  out="$(run_destroyg_codex "DEVKIT_CONFIRMED=1 $DESTROY_CMD" "$via")"
  case "$out" in
    *permissionDecision*) bad "Codex（$via 判别）带标记 → 无 permissionDecision" "无 permissionDecision" "$out" ;;
    *) ok "Codex（$via 判别）带标记 → 无 permissionDecision" ;;
  esac
done
out="$(run_destroyg_codex "XDEVKIT_CONFIRMED=1 $DESTROY_CMD" turn_id)"
has "Codex 标记须是独立 token（XDEVKIT_CONFIRMED=1 不算）→ 仍 deny" "$out" '"permissionDecision": "deny"'
out="$(run_destroyg_codex 'git status' turn_id)"
if [ -z "$out" ]; then ok "Codex 下未命中的命令照旧静默放行"; else bad "Codex 下未命中的命令照旧静默放行" "空" "$out"; fi
