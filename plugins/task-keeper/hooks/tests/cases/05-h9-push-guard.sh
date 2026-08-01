# H9 · debug worktree 禁止 push 守卫（fixer 不许 push）。
# 依赖 harness.sh 的 ok/bad；HOOK_DIR 由 run-tests.sh 提供。
# 本节自己定义 PUSHG / run_pushg / pushg_deny / pushg_pass（只在本文件内使用）。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件全部用例都是硬编码的 /repo 路径字面量，不依赖任何
# 真实文件系统现场，也不依赖其他 case 文件留下的变量或函数。

echo
echo "== H9 · debug worktree 禁止 push 守卫（fixer 不许 push）=="
PUSHG="$HOOK_DIR/pre-tool-use-debug-worktree-push.sh"
run_pushg() {   # $1=command  $2=cwd（可省略）
  /usr/bin/python3 -c '
import json,sys
ev = {"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":sys.argv[1]}}
if len(sys.argv) > 2 and sys.argv[2]:
    ev["cwd"] = sys.argv[2]
print(json.dumps(ev))
' "$1" "${2:-}" | bash "$PUSHG"
}
pushg_deny() {   # $1=用例名  $2=command  $3=cwd（可省略）—— 断言 deny
  case "$(run_pushg "$2" "${3:-}")" in
    *'"permissionDecision": "deny"'*) ok "$1" ;;
    *) bad "$1" "deny" "$(run_pushg "$2" "${3:-}")" ;;
  esac
}
pushg_pass() {  # $1=用例名  $2=command  $3=cwd（可省略）—— 断言静默放行
  out="$(run_pushg "$2" "${3:-}")"
  if [ -z "$out" ]; then ok "$1"; else bad "$1" "空（放行）" "$out"; fi
}

echo "[40] -C 落在 fixer worktree 里的 git push 一律 deny（v4 布局：.keeper/<交付id>/debug/<DBG-id>/worktree/，含 _main 兜底桶）"
pushg_deny "git -C <fixer worktree> push（有交付）" 'git -C /repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-017/worktree push origin fix/DBG-017'
pushg_deny "git -C <fixer worktree> push（_main 兜底桶）" 'git -C /repo/.keeper/_main/debug/DBG-001/worktree push origin fix/DBG-001'
pushg_deny "--git-dir 落在 fixer worktree 里"     'git --git-dir=/repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-020/worktree/.git push'
pushg_deny "无 -C，靠 cwd 落在 fixer worktree"    'git push origin fix/DBG-021' '/repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-021/worktree'

echo "[41] -C 落在非 fixer worktree（主仓 / 交付 worktree / 已废弃的 v3 布局）一律放行"
pushg_pass "-C 落在交付 worktree（.sdlc/worktrees）" 'git -C /repo/.sdlc/worktrees/D-001-feat push origin D-001-feat'
pushg_pass "-C 落在主仓根"                          'git -C /repo push origin master'
pushg_pass "无 -C 无 cwd，抠不到路径信息"           'git push origin master'
pushg_pass "旧 v3 布局字面量（.keeper/worktrees/）不再命中——迁移是排他式的" 'git -C /repo/.keeper/worktrees/DBG-017 push origin fix/DBG-017'

echo "[42] 非 push 命令、或压根不是 git 命令，不误伤"
pushg_pass "git status 不误伤"                     'git -C /repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-017/worktree status'
pushg_pass "非 git 文本含 push 字样不误伤"          'echo please push this button'
pushg_pass "非 Bash 无 command 字段"                ''
