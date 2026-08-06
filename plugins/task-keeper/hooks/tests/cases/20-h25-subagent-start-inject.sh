# H25 · SubagentStart 漏派体检注入（subagent-start-debug-keeper.sh 薄壳 +
# lib/debug_keeper_inject.py 实作，调 tk-board/scripts/pending_dispatch.py
# --oneline 现算漏派集合）。依赖 harness.sh 的
# newtmpdir/mkissue/mkrealrepo/run_subagent_start/ok/bad/has/hasnt。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件自成一体，不依赖其他 case 文件留下的变量或函数。

echo
echo "== H25 · SubagentStart 漏派体检注入（debug-keeper 专属，agent_type/event 双重白名单 + fail-open）=="

echo "[107] 正确 event + 正确 agent_type + 本仓未启用 task-keeper（无漏派）→ 零字节输出，exit 0"
T="$(newtmpdir)"; : > "$T/.git"
OUT="$(run_subagent_start "$T")"; RC=$?
if [ -z "$OUT" ] && [ "$RC" -eq 0 ]; then ok "无漏派零输出，exit 0"
else bad "无漏派应零输出且 exit 0" "空/0" "OUT=[$OUT] RC=$RC"; fi
rm -rf "$T"

echo "[108] agent_type 换成 task-keeper:chore-keeper（非目标 agent）→ 零字节输出，exit 0"
T="$(newtmpdir)"; : > "$T/.git"
OUT="$(run_subagent_start "$T" "" "task-keeper:chore-keeper")"; RC=$?
if [ -z "$OUT" ] && [ "$RC" -eq 0 ]; then ok "非 debug-keeper 的 agent_type 零输出，exit 0"
else bad "非目标 agent_type 应零输出且 exit 0" "空/0" "OUT=[$OUT] RC=$RC"; fi
rm -rf "$T"

echo "[109] hook_event_name 换成 UserPromptSubmit（非 SubagentStart）→ 零字节输出，exit 0"
T="$(newtmpdir)"; : > "$T/.git"
OUT="$(run_subagent_start "$T" "UserPromptSubmit")"; RC=$?
if [ -z "$OUT" ] && [ "$RC" -eq 0 ]; then ok "非 SubagentStart 事件零输出，exit 0"
else bad "非 SubagentStart 事件应零输出且 exit 0" "空/0" "OUT=[$OUT] RC=$RC"; fi
rm -rf "$T"

echo "[110] stdin 喂坏 JSON（not json）→ 零字节输出，exit 0（注入类 hook fail-open，不阻断子代理启动）"
OUT="$(printf 'not json' | bash "$SUBAGENT_START_HOOK")"; RC=$?
if [ -z "$OUT" ] && [ "$RC" -eq 0 ]; then ok "坏 JSON 零输出，exit 0"
else bad "坏 JSON 应零输出且 exit 0" "空/0" "OUT=[$OUT] RC=$RC"; fi

echo "[111] 真实 git 仓 + DBG-001(open/P1/medium，已 triage 未派) + DBG-002(open 但无 priority/difficulty，未 triage) → 有漏派，只带 DBG-001"
T="$(newtmpdir)"; mkrealrepo "$T"
Q="$T/.keeper/_main/debug"
mkissue "$Q" DBG-001 open P1 "已 triage 未派的问题" "" medium
mkissue "$Q" DBG-002 open ""  "还没 triage 的问题"
OUT="$(run_subagent_start "$T")"; RC=$?
has "含漏派体检开场白" "$OUT" "# 漏派体检（harness 每次唤醒现算，非你的记忆）"
has "带出已 triage 未派的 DBG-001" "$OUT" "DBG-001"
hasnt "不带未 triage 的 DBG-002（触发漏派前提是 priority 与 difficulty 都非空）" "$OUT" "DBG-002"
if [ "$RC" -eq 0 ]; then ok "有漏派场景 exit 0"
else bad "有漏派场景应 exit 0" "0" "$RC"; fi
# 字节数按本测试套件的既有惯例计（$(...) 会剥掉 hook stdout 末尾那个换行符，
# 见 09-h14-chore-snapshot.sh:19、15-h20-queue-autocreate.sh:17 同一手法）——
# 因此这里量到的字节数比"贴着原始管道输出跑 wc -c"少 1。人工用原始管道实测过
# 一次是 905 字节（含末尾换行符），本条断言的 904 与之一致，差的正是那 1 个换行
# 字节，不是两次结果不一致。这是回归判据，锁定的是 render() 模板文案本身没有
# 漂移——模板文案一旦被改动，这条会先红，提醒去 debug_keeper_inject.py 复核。
BYTES="$(printf '%s' "$OUT" | wc -c | tr -d ' ')"
if [ "$BYTES" -eq 904 ]; then ok "漏派注入体 ${BYTES} 字节（=904，人工实测原始字节数 905 差的是被剥掉的那个换行符）"
else bad "漏派注入体应为 904 字节（模板文案回归锁定）" "904" "$BYTES"; fi
rm -rf "$T"
