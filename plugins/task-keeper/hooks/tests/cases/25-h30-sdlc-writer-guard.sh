# H30 · sdlc 文档正文编写者守卫（主会话写 sdlc 正文 → deny，逼派 sdlc-writer）。
# 依赖 harness.sh 的 ok/bad/has/hasnt；HOOK_DIR 由 run-tests.sh 提供。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件不依赖任何其他 case 文件留下的变量或函数。

echo
echo "== H30 · sdlc 文档正文编写者守卫（主会话写 sdlc 正文 → deny 逼派 sdlc-writer）=="
# 【判据】主会话（payload 无 agent_id）写 sdlc/specs/ 或 sdlc/deliveries/ 下非 _index.md
# 文件 → deny，文案给派 sdlc-writer 的照抄形态 + why + 四条出路；子代理（带 agent_id）
# 写同路径放行（sdlc-writer 写自己的产物不拦）；_index.md 放行（gate 翻转合法）。
SDLC="$HOOK_DIR/pre-tool-use-sdlc-writer-guard.sh"
run_sdlc() {   # $1=tool_name $2=file_path $3=agent_id(可省，省/空则不带键=主会话) $4=session_id(可省)
  /usr/bin/python3 -c '
import json,sys
tn,fp = sys.argv[1],sys.argv[2]
ev = {"tool_name":tn,"tool_input":{"file_path":fp}}
if len(sys.argv) > 3 and sys.argv[3]:
    ev["agent_id"] = sys.argv[3]
if len(sys.argv) > 4 and sys.argv[4]:
    ev["session_id"] = sys.argv[4]
print(json.dumps(ev, ensure_ascii=False))
' "$1" "$2" "${3:-}" "${4:-}" | bash "$SDLC"
}
CNT_DIR3="$(/usr/bin/python3 -c 'import tempfile;print(tempfile.gettempdir())')"
# 前缀 tk-（task-keeper）与 radnove-core 的 rn- 区分，见 hook_counter.py 模块头注释
find "$CNT_DIR3" -maxdepth 1 -name 'tk-sdlc-writer-SDLC*.json' -delete

F_CONTRACTS="/repo/sdlc/specs/features/order-export/contracts.md"
F_SCOPE="/repo/sdlc/deliveries/D-001-feat-x/scope.md"
F_INDEX="/repo/sdlc/specs/features/order-export/_index.md"
F_INDEX_D="/repo/sdlc/deliveries/D-001-feat-x/_index.md"
F_BEHAVIOR="/repo/sdlc/specs/features/order-export/behaviors/export-list.gherkin"
F_CONCEPT="/repo/sdlc/specs/concepts/Member.md"
F_SRC="/repo/src/Foo.java"
F_OTHER_MD="/repo/docs/note.md"
F_SCRATCH="/repo/sdlc/scratch/notes.md"

echo "[135] 范围窄：非 sdlc 文件一律零成本放行（即使主会话发起）"
OUT="$(run_sdlc Write "$F_SRC" "" SDLC1)"
if [ -z "$OUT" ]; then ok "写源码不介入"; else bad "源码应放行" "空" "$OUT"; fi
OUT="$(run_sdlc Write "$F_OTHER_MD" "" SDLC1)"
if [ -z "$OUT" ]; then ok "写 sdlc 外的 md 不介入"; else bad "非 sdlc md 应放行" "空" "$OUT"; fi

echo "[136] 关键豁免：_index.md 放行（gate 状态 frontmatter 是主会话/Human 的门禁动作）"
OUT="$(run_sdlc Write "$F_INDEX" "" SDLC2)"
if [ -z "$OUT" ]; then ok "写 feature _index.md 放行（翻 gate）"; else bad "_index.md 应放行" "空" "$OUT"; fi
OUT="$(run_sdlc Write "$F_INDEX_D" "" SDLC2)"
if [ -z "$OUT" ]; then ok "写 delivery _index.md 放行"; else bad "delivery _index 应放行" "空" "$OUT"; fi

echo "[137] 判据：主会话写 sdlc 正文 → deny，文案给派 sdlc-writer 照抄形态 + why + 四条出路"
OUT="$(run_sdlc Write "$F_CONTRACTS" "" SDLC3)"
has "返回 deny 而非 ask"        "$OUT" '"permissionDecision": "deny"'
has "指出该派 sdlc-writer"      "$OUT" "派 sdlc-writer"
has "给派发形态模板"            "$OUT" "task-keeper:sdlc-writer"
has "解释 why（auto-compact）"  "$OUT" "auto-compact"
has "出路含 _index.md"          "$OUT" "_index.md"
has "出路含 decisions/answers"  "$OUT" "decisions/answers"
has "说明只拦主会话"            "$OUT" "主会话"
# 子路径覆盖：交付级 / behaviors / concepts 都在 sdlc 正文区
OUT="$(run_sdlc Write "$F_SCOPE" "" SDLC3)"
has "交付级 scope.md 命中 deny" "$OUT" '"permissionDecision": "deny"'
OUT="$(run_sdlc Write "$F_BEHAVIOR" "" SDLC3)"
has "behaviors/*.gherkin 命中 deny" "$OUT" '"permissionDecision": "deny"'
OUT="$(run_sdlc Write "$F_CONCEPT" "" SDLC3)"
has "concepts/*.md 命中 deny"   "$OUT" '"permissionDecision": "deny"'

echo "[138] 关键判据：子代理发起（带 agent_id）写 sdlc 正文 → 放行（sdlc-writer 不被拦）"
OUT="$(run_sdlc Write "$F_CONTRACTS" "agent-abc-123" SDLC4)"
if [ -z "$OUT" ]; then ok "子代理写 contracts.md 放行（writer 写自己的产物）"; else bad "子代理应放行" "空" "$OUT"; fi
OUT="$(run_sdlc Write "$F_SCOPE" "agent-xyz-456" SDLC4)"
if [ -z "$OUT" ]; then ok "子代理写 scope.md 放行"; else bad "子代理应放行" "空" "$OUT"; fi

echo "[139] Edit 同样命中（主会话 Edit sdlc 正文也 deny）"
OUT="$(run_sdlc Edit "$F_CONTRACTS" "" SDLC5)"
has "Edit 主会话写 sdlc 正文 → deny" "$OUT" '"permissionDecision": "deny"'

echo "[140] 熔断：撞 DENY_LIMIT 次后降级放行并附警告，不无限 deny"
for i in 1 2 3; do
  OUT="$(run_sdlc Write "$F_CONTRACTS" "" SDLC6)"
  has "第 $i 次仍 deny" "$OUT" '"permissionDecision": "deny"'
done
OUT="$(run_sdlc Write "$F_CONTRACTS" "" SDLC6)"
hasnt "第 4 次不再 deny"     "$OUT" '"permissionDecision": "deny"'
has   "降级时说明达到上限"    "$OUT" "达到上限"
has   "降级时仍点出派 writer" "$OUT" "派 sdlc-writer"

echo "[141] 边界：sdlc/ 下非 specs|deliveries 路径不命中（判据保守，只锁正文区两前缀）"
OUT="$(run_sdlc Write "$F_SCRATCH" "" SDLC7)"
if [ -z "$OUT" ]; then ok "sdlc/scratch/ 不命中（非 specs|deliveries）"; else bad "应放行" "空" "$OUT"; fi
