# H19 · UserPromptSubmit 三岔口分诊注入（keeper_routing.py --event
# user-prompt-submit）。依赖 harness.sh 的 newtmpdir/mkissue/run_triage/
# ok/bad/has。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件自成一体，不依赖其他 case 文件留下的变量或函数。
# 2026-08-03 前是全部用例文件里的最后一个；之后补了 15-h20-queue-autocreate.sh，
# 收尾与汇总现在交给它之后的 run-tests.sh。

echo
echo "== H19 · UserPromptSubmit 三岔口分诊注入（keeper_routing.py --event user-prompt-submit）=="

echo "[67] 项目未启用 .keeper/：stdout 全空，等价于本 hook 不存在（零成本保证）"
# 与 SessionStart 那份的分档不同：未启用时这里**不注入任何引导文案**。理由是本 hook
# 每轮触发、随插件装进所有项目，未启用项目一个字符都不该付；引导只在 SessionStart
# 出一次就够。
T="$(newtmpdir)"; : > "$T/.git"
OUT="$(run_triage "$T")"
BYTES="$(/usr/bin/python3 -c 'import sys; print(len(sys.argv[1]))' "$OUT")"
if [ "$BYTES" -eq 0 ]; then ok "未启用时 stdout 全空（0 字节）"
else bad "未启用时应零输出" "0" "$BYTES"; fi

echo "[68] 项目已启用 .keeper/：注入三岔口本体，hookEventName 正确，长度 ≤800 字符"
mkissue "$T/.keeper/_main/debug" DBG-001 open P1 "占位问题，仅用于触发 triage 已启用分支"
OUT="$(run_triage "$T")"
# 【为什么断言 hookEventName】harness 用它匹配事件；写成 SessionStart 会被**静默
# 丢弃且不报错**，注入等于没发生而测试仍能靠正文断言通过。必须单独测这个字段。
EV="$(printf '%s' "$OUT" | /usr/bin/python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["hookSpecificOutput"]["hookEventName"])
except Exception:
    print("")
')"
if [ "$EV" = "UserPromptSubmit" ]; then ok "hookEventName 为 UserPromptSubmit"
else bad "hookEventName 必须与真实事件一致" "UserPromptSubmit" "$EV"; fi
TEXT="$(printf '%s' "$OUT" | /usr/bin/python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])
except Exception:
    print("")
')"
CHARS="$(/usr/bin/python3 -c 'import sys; print(len(sys.argv[1]))' "$TEXT")"
# 每轮注入，成本乘以轮数，上限压得比 SessionStart 那份紧得多。
if [ "$CHARS" -le 800 ]; then ok "分诊文案 ${CHARS} 字符 ≤800（每轮成本硬上限）"
else bad "分诊文案应 ≤800 字符" "<=800" "$CHARS"; fi
has "含三条岔路中的 debug 分支" "$TEXT" "转 debug-keeper"
has "含三条岔路中的 chore 分支" "$TEXT" "转 chore-keeper"
has "含转发三原则" "$TEXT" "逐字"
has "含反合理化那句（这条是遵循度的实际着力点）" "$TEXT" "顺手做了更快"
rm -rf "$T"
