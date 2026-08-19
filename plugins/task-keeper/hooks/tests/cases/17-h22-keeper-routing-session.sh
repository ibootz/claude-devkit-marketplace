# H22 · 三岔口分诊注入的会话隔离（keeper_routing.py 的 triage_wake_line：登记
# 存在且 session_id 匹配 / 存在但不匹配（含旧格式无 session_id 键）/ 不存在，
# 三选一，只注入其中一支）。依赖 harness.sh 的
# newtmpdir/mkrealrepo/run_keeper_instance/run_triage_sess/ok/bad/has/hasnt。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件自成一体，不依赖其他 case 文件留下的变量或函数。
# 【为什么用真实 git 仓库】同 16-h21：keeper_paths.find_worktree_root 靠真实
# git 命令定位工作区根，假 `.git` 占位文件在这里不适用。

echo
echo "== H22 · 三岔口分诊注入的会话隔离（keeper_routing.py：triage_wake_line 三选一）=="

# 从注入体里取出 additionalContext 正文，与 14-h19-userprompt-triage.sh 的抽取方式一致。
triage_text() {
  printf '%s' "$1" | /usr/bin/python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])
except Exception:
    print("")
'
}

echo "[87] 没有任何登记 → 三岔口注入「本会话还没有实例」这一支，且总长度 ≤800"
T="$(newtmpdir)"; mkrealrepo "$T"
mkdir -p "$T/.keeper"   # 只需 .keeper/ 顶层存在即 enabled，不要求已建出具体队列目录
OUT="$(run_triage_sess "$T" "sess-A")"
TEXT="$(triage_text "$OUT")"
has "无登记时提示本会话还没有实例" "$TEXT" "本会话还没有实例"
hasnt "无登记时不误报已失效" "$TEXT" "已失效"
CHARS="$(/usr/bin/python3 -c 'import sys; print(len(sys.argv[1]))' "$TEXT")"
if [ "$CHARS" -le 800 ]; then ok "无登记分支 ${CHARS} 字符 ≤800"
else bad "无登记分支应 ≤800 字符" "<=800" "$CHARS"; fi
rm -rf "$T"

echo "[88] 登记存在且 session_id 与当前一致 → 注入「debug 在跑：…」，直接带出真实 name"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "Agent" "sess-A" >/dev/null
OUT="$(run_triage_sess "$T" "sess-A")"
TEXT="$(triage_text "$OUT")"
has "session 匹配时提示 debug 有实例在跑" "$TEXT" "debug 在跑"
has "session 匹配时直接带出真实 name" "$TEXT" "opus-debug-keeper-4bb6"
has "session 匹配时仍给出 SendMessage 这条唤醒通道（只对补充既有 issue 成立）" "$TEXT" "SendMessage"
has "session 匹配时提示新 bug 一律新派实例（v7 该分支专属短语）" "$TEXT" "新 bug 一律新派实例"
# 【v7 反向断言，别删】v6 那句「用 SendMessage 唤醒它，不要重派」在一档一实例下是对的，
# 在 v7 下会把并行压回串行：主会话看到有实例在跑，就把第二条、第三条 bug 全塞给同一个。
# 表面上一切正常、没有任何报错，只是并行收益归零——所以这句话的**缺席**本身就是判据。
hasnt "session 匹配时不得再劝「不要重派」（v6 措辞会把并行压回串行）" "$TEXT" "不要重派"
# 【不测"不含首次"】"首次" 这个词本身也出现在 TRIAGE_HEAD 固定骨架里（第 2 条
# 岔路"首次用 Agent 派出，之后 SendMessage 唤醒"），三个分支都恒定含有它，不是
# 动态行专属词——最初写成 hasnt 断言是假阳性，已改为上面这条更精确的正向断言。
CHARS="$(/usr/bin/python3 -c 'import sys; print(len(sys.argv[1]))' "$TEXT")"
if [ "$CHARS" -le 800 ]; then ok "session 匹配分支 ${CHARS} 字符 ≤800"
else bad "session 匹配分支应 ≤800 字符" "<=800" "$CHARS"; fi
rm -rf "$T"

echo "[89] 登记存在但 session_id 不一致（换了新会话）→ 注入「登记来自上一个会话已失效」"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "Agent" "sess-A" >/dev/null
OUT="$(run_triage_sess "$T" "sess-B")"
TEXT="$(triage_text "$OUT")"
has "session 不匹配时提示登记已失效" "$TEXT" "已失效"
has "session 不匹配时提示这是首次派发" "$TEXT" "首次"
hasnt "session 不匹配时不应带出旧会话的 name（避免被凭这个 name 误唤醒）" "$TEXT" "opus-debug-keeper-4bb6"
rm -rf "$T"

echo "[90] 登记是旧格式（没有 session_id 键，会话隔离机制落地之前写入）→ 同样走「已失效、首次派发」这一支"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" >/dev/null   # 不传 $5，模拟旧格式
OUT="$(run_triage_sess "$T" "sess-A")"
TEXT="$(triage_text "$OUT")"
has "旧格式登记也当陈旧处理" "$TEXT" "已失效"
rm -rf "$T"

echo "[91] debug/chore 两档都命中同一个 session_id → 两个 name 各自落进本档那一句（4.2.0 起分两句）"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "Agent" "sess-A" >/dev/null
run_keeper_instance "$T" "task-keeper:chore-keeper" "opus-chore-keeper-9f2a" "Agent" "sess-A" >/dev/null
OUT="$(run_triage_sess "$T" "sess-A")"
TEXT="$(triage_text "$OUT")"
has "两档都匹配时 debug 的 name 出现" "$TEXT" "opus-debug-keeper-4bb6"
has "两档都匹配时 chore 的 name 出现" "$TEXT" "opus-chore-keeper-9f2a"
# 【为什么两句都要断言】两档处置方向相反（debug 新派 / chore 唤醒），4.0.0～4.1.0
# 这里只有 debug 一句，chore 实例在场时读到的是反的口径。两句同时在场是本次修复的判据。
has "两档都匹配时 debug 句在场" "$TEXT" "debug 在跑"
has "两档都匹配时 chore 句在场" "$TEXT" "chore 在跑"
has "chore 句给的是唤醒方向（攒批打包拍板）" "$TEXT" "新杂务一律 \`SendMessage\` 交给它"
CHARS="$(/usr/bin/python3 -c 'import sys; print(len(sys.argv[1]))' "$TEXT")"
if [ "$CHARS" -le 800 ]; then ok "两档都匹配分支 ${CHARS} 字符 ≤800（预算仍留有余量）"
else bad "两档都匹配分支应 ≤800 字符" "<=800" "$CHARS"; fi
rm -rf "$T"

echo "[92] payload 不带 session_id（旧版 harness 调用形态）→ 任何登记都判不出匹配，一律走陈旧/无登记那一支，不会误当匹配"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "Agent" "sess-A" >/dev/null
OUT="$(run_triage "$T")"   # 不带 session_id 的旧版调用方式
TEXT="$(triage_text "$OUT")"
has "当前 session_id 缺失时把已有登记当陈旧处理" "$TEXT" "已失效"
hasnt "当前 session_id 缺失时不应误判成本会话匹配" "$TEXT" "debug 在跑"
rm -rf "$T"