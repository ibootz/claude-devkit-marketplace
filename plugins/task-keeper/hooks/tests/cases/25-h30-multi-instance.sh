# H30 · v7 多实例（一条 issue 一个 keeper 实例，同一档并存多个）。
# 依赖 harness.sh 的 newtmpdir/mkrealrepo/mkissue/run_keeper_agent/run_keeper_instance/
# run_triage_sess/ki_field/ki_count/ok/bad/has/hasnt。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件自成一体。
#
# 【这一节锁的是什么】v7 把「一档一个常驻 keeper 顺序跑完整条队列」拆成「一条 issue
# 一个实例并行跑」。拆开之后新增了四件必须原子或必须现算的事，它们的共同点是
# **坏掉的时候不报错**：
#
#   · 编号认领（`queue_files.claim_id`）——两个实例扫出同一个 DBG-208 再各自写
#     `issue.md`，后写的整份覆盖先写的。表现是「有一条 bug 从来没被报过」。
#   · 合并锁（`keeper_paths.acquire/release/read_merge_lock`）——两个实例同时
#     `git merge` 动同一个主仓，撞出半完成的 merge 状态。
#   · issue 归属（`keeper_instance_register.extract_issue`）——抽错编号会让主会话
#     把 DBG-208 的补充信息发给管 DBG-207 的那个实例。
#   · 实例状态（`keeper_generation.instance_state`）——判早了会让主会话重派一个去抢
#     同一条 issue 的写权。
#
# 【两侧都要有用例】本节每一组都配了「该拦的」与「不该误杀的」：并发不撞号配单进程
# 正常认领、超时抢占配未超时不抢、抽得到编号配抽不到时返回 None（绝不编造）、
# 判 retirable 配 done 但 worktree 未清时仍判 live。只写正例的用例发现不了误杀。

echo
echo "== H30 · v7 多实例（一 issue 一实例并行，认领/锁/归属/状态四组原语）=="

# 直接调 hooks/lib 里的函数，不经 hook 外壳——本节大半判据是函数自己的行为。
# 模式与 16-h21 的 py_kp() 一致。$1=worktree 根，$2=python 表达式（root 已绑好）。
mi_py() {
  /usr/bin/python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
import keeper_paths as kp
import queue_files as qf
from keeper_generation import instance_state
from keeper_instance_register import extract_issue
root = sys.argv[2]
print(eval(sys.argv[3]))
' "$LIBDIR" "$1" "$2"
}

# 从注入体里取 additionalContext 正文，与 17-h22 的 triage_text 同一手法。
mi_text() {
  printf '%s' "$1" | /usr/bin/python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])
except Exception:
    print("")
'
}

# 直接写一条实例登记（绕开 hook 外壳，因为这里要控 issue 与 session_id 两个值）。
# $1=根 $2=kind $3=name $4=session_id $5=issue（可省，省则不写这个键）
# 走 argv 传参而不是往 mi_py 的表达式里拼字符串——拼字符串要嵌三层引号，改一次错一次。
mi_bind() {
  /usr/bin/python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
import keeper_paths as kp
kp.write_keeper_instance(sys.argv[2], "_main", sys.argv[3], sys.argv[4],
                         session_id=sys.argv[5] or None,
                         issue=(sys.argv[6] or None))
' "$LIBDIR" "$1" "$2" "$3" "$4" "${5:-}" >/dev/null
}

# SubagentStart 注入（带 session_id——`debug_keeper_inject.peers` 要靠它过滤同会话实例，
# harness 的 run_subagent_start 不带这个字段，这里单独造）。$1=cwd $2=session_id
mi_sub() {
  /usr/bin/python3 -c '
import json,sys
print(json.dumps({"hook_event_name": "SubagentStart", "cwd": sys.argv[1],
                  "agent_type": "task-keeper:debug-keeper", "session_id": sys.argv[2]}))
' "$1" "$2" | bash "$SUBAGENT_START_HOOK"
}

# 造一条最小 debug 条目（只控 id 与 status，不写 priority——本节不测 triage 判据）。
# $1=根 $2=id $3=status
mi_item() {
  mkdir -p "$1/.keeper/_main/debug/$2"
  printf -- '---\nid: %s\nsummary: H30 用例造的条目\nstatus: %s\n---\n\n## 现象\n\n正文不参与判定。\n' \
    "$2" "$3" >"$1/.keeper/_main/debug/$2/issue.md"
}

# ─────────────────── A · claim_id 原子认领编号（[142]-[146]）───────────────────

echo "[142] claim_id 单进程认领：拿到 DBG-001，目录被建出，占位正文可解析且 status=open"
T="$(newtmpdir)"; mkrealrepo "$T"
Q="$T/.keeper/_main/debug"
IID="$(mi_py "$T" 'qf.claim_id("'"$Q"'", qf.DEBUG, summary="登录页白屏")[0]')"
if [ "$IID" = "DBG-001" ]; then ok "首次认领拿到 DBG-001"
else bad "首次认领应为 DBG-001" "DBG-001" "$IID"; fi
if [ -d "$Q/DBG-001" ]; then ok "认领即建出条目目录（占位先于内容）"
else bad "应建出 DBG-001 目录" "存在" "不存在"; fi
ST="$(mi_py "$T" 'str(qf.parse_item_file("'"$Q"'/DBG-001/issue.md")[0].get("status"))')"
if [ "$ST" = "open" ]; then ok "占位正文 frontmatter 可解析且 status=open"
else bad "占位正文 status 应为 open" "open" "$ST"; fi
SUM="$(mi_py "$T" 'str(qf.parse_item_file("'"$Q"'/DBG-001/issue.md")[0].get("summary"))')"
if [ "$SUM" = "登录页白屏" ]; then ok "传入的 summary 写进占位 frontmatter"
else bad "summary 应写进占位 frontmatter" "登录页白屏" "$SUM"; fi
# 日期一律现算，不写死字面量——写死日期正是 [63] 那条时间炸弹的成因。
TODAY="$(/usr/bin/python3 -c 'import datetime;print(datetime.date.today().isoformat())')"
RAT="$(mi_py "$T" 'str(qf.parse_item_file("'"$Q"'/DBG-001/issue.md")[0].get("reported_at"))')"
if [ "$RAT" = "$TODAY" ]; then ok "reported_at 取当天（现算比对，非写死字面量）"
else bad "reported_at 应为今天" "$TODAY" "$RAT"; fi
rm -rf "$T"

echo "[143] 已有 DBG-001..003 时认领接着排 DBG-004（与 next_id 的扫描口径一致）"
T="$(newtmpdir)"; mkrealrepo "$T"
Q="$T/.keeper/_main/debug"
mkissue "$Q" DBG-001 done P1 "旧条目一"
mkissue "$Q" DBG-002 open P2 "旧条目二"
mkissue "$Q" DBG-003 open P3 "旧条目三"
IID="$(mi_py "$T" 'qf.claim_id("'"$Q"'", qf.DEBUG)[0]')"
if [ "$IID" = "DBG-004" ]; then ok "接着已有最大号排 DBG-004"
else bad "应认领 DBG-004" "DBG-004" "$IID"; fi
rm -rf "$T"

echo "[144] 并发认领不撞号：8 个真实进程同时 claim_id → 8 个互不相同的编号、8 个目录"
# 【为什么是真实进程 + 起跑线文件】见 tests/lib/claim_race.py 的模块头：线程测不出
# `os.mkdir` 的内核级互斥，而不同步起跑的话竞态窗口根本打不开，用例会假绿。
T="$(newtmpdir)"; mkrealrepo "$T"
Q="$T/.keeper/_main/debug"
RACE="$(/usr/bin/python3 "$TESTS_DIR/lib/claim_race.py" "$LIBDIR" "$Q" 8)"
GOT_N="$(printf '%s\n' "$RACE" | grep -c '^DBG-')"
UNIQ_N="$(printf '%s\n' "$RACE" | sort -u | grep -c '^DBG-')"
DIR_N="$(ls -1 "$Q" | grep -c '^DBG-')"
if [ "$GOT_N" -eq 8 ]; then ok "8 个进程都认领成功（无 NONE / MISSING）"
else bad "应有 8 个成功认领" "8" "$GOT_N（原始输出：$(printf '%s' "$RACE" | tr '\n' ' ')）"; fi
if [ "$UNIQ_N" -eq 8 ]; then ok "8 个编号互不相同（os.mkdir 的 CAS 生效）"
else bad "8 个编号应互不相同" "8" "$UNIQ_N（原始输出：$(printf '%s' "$RACE" | tr '\n' ' ')）"; fi
if [ "$DIR_N" -eq 8 ]; then ok "落盘目录数等于进程数（没有两个进程共用一个目录）"
else bad "落盘目录数应为 8" "8" "$DIR_N"; fi
rm -rf "$T" "$Q.race-out"

echo "[145] 目标目录已被别人占住 → 跳过该号取下一个，**不覆盖**别人的目录"
T="$(newtmpdir)"; mkrealrepo "$T"
Q="$T/.keeper/_main/debug"
mkdir -p "$Q/DBG-001"
printf 'squatter\n' > "$Q/DBG-001/MARK"
IID="$(mi_py "$T" 'qf.claim_id("'"$Q"'", qf.DEBUG)[0]')"
if [ "$IID" = "DBG-002" ]; then ok "撞到已占用的 DBG-001 后顺延到 DBG-002"
else bad "应顺延到 DBG-002" "DBG-002" "$IID"; fi
if [ -f "$Q/DBG-001/MARK" ]; then ok "别人的目录内容原样保留（没被占位正文覆盖）"
else bad "不应动别人的目录" "MARK 仍在" "MARK 已丢"; fi
rm -rf "$T"

echo "[146] 反面对照：next_id 只扫描不占位，连叫两次返回同一个号（这正是 claim_id 存在的理由）"
# 【这条用例是防回退的】有人把登记路径从 claim_id 换回 next_id 时，功能测试全绿——
# 覆盖只发生在两个实例恰好并发的那一瞬。所以把「next_id 不占位」这个事实本身钉死，
# 让任何人在改之前先看见它。
T="$(newtmpdir)"; mkrealrepo "$T"
Q="$T/.keeper/_main/debug"
mkdir -p "$Q"
N1="$(mi_py "$T" 'qf.next_id("'"$Q"'", qf.DEBUG)')"
N2="$(mi_py "$T" 'qf.next_id("'"$Q"'", qf.DEBUG)')"
if [ "$N1" = "$N2" ] && [ "$N1" = "DBG-001" ]; then ok "next_id 两次返回同一个 DBG-001（不占位，多实例下会撞号）"
else bad "next_id 两次应返回同一个 DBG-001" "DBG-001/DBG-001" "$N1/$N2"; fi
if [ ! -d "$Q/DBG-001" ]; then ok "next_id 不建目录（与 claim_id 的差别就在这里）"
else bad "next_id 不应建目录" "不存在" "存在"; fi
rm -rf "$T"

# ─────────────────── B · 合并锁（[147]-[154]）───────────────────

echo "[147] 正常获取：acquire 返回 ok=True，锁目录与 owner.json 落盘，status 读得出持有者"
T="$(newtmpdir)"; mkrealrepo "$T"
OK1="$(mi_py "$T" 'kp.acquire_merge_lock(root, "_main", "opus-debug-keeper-aaaa", issue="DBG-201")[0]')"
if [ "$OK1" = "True" ]; then ok "干净取到锁"
else bad "应取到锁" "True" "$OK1"; fi
if [ -d "$T/.keeper/_main/.merge.lock" ]; then ok "锁目录落盘（os.mkdir 即互斥点）"
else bad "锁目录应存在" "存在" "不存在"; fi
HN="$(mi_py "$T" 'str(kp.read_merge_lock(root, "_main").get("name"))')"
if [ "$HN" = "opus-debug-keeper-aaaa" ]; then ok "read_merge_lock 读出持有者 name"
else bad "持有者 name 读取错误" "opus-debug-keeper-aaaa" "$HN"; fi
HI="$(mi_py "$T" 'str(kp.read_merge_lock(root, "_main").get("issue"))')"
if [ "$HI" = "DBG-201" ]; then ok "锁元数据带 issue（便于归因是谁在合哪条）"
else bad "锁元数据 issue 错误" "DBG-201" "$HI"; fi
rm -rf "$T"

echo "[148] 被别人持有且未超时 → 拿不到，返回的是当前持有者元数据（不是空壳）"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_py "$T" 'kp.acquire_merge_lock(root, "_main", "opus-debug-keeper-aaaa", issue="DBG-201")[0]' >/dev/null
OK2="$(mi_py "$T" 'kp.acquire_merge_lock(root, "_main", "opus-debug-keeper-bbbb")[0]')"
if [ "$OK2" = "False" ]; then ok "第二个实例拿不到锁"
else bad "第二个实例不应拿到锁" "False" "$OK2"; fi
WHO="$(mi_py "$T" 'str(kp.acquire_merge_lock(root, "_main", "opus-debug-keeper-bbbb")[1].get("name"))')"
if [ "$WHO" = "opus-debug-keeper-aaaa" ]; then ok "失败时带回当前持有者 name（可写进回执归因）"
else bad "失败时应带回持有者 name" "opus-debug-keeper-aaaa" "$WHO"; fi
rm -rf "$T"

echo "[149] 同一 owner 重入 → 判 True，不算失败（keeper 中途重试自己的合并不该被自己挡住）"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_py "$T" 'kp.acquire_merge_lock(root, "_main", "opus-debug-keeper-aaaa")[0]' >/dev/null
OK3="$(mi_py "$T" 'kp.acquire_merge_lock(root, "_main", "opus-debug-keeper-aaaa")[0]')"
if [ "$OK3" = "True" ]; then ok "本来就是自己持有时重入判 True"
else bad "同 owner 重入应判 True" "True" "$OK3"; fi
rm -rf "$T"

echo "[150] 超时可抢占：owner.json 的 ts 改成 now-3600 秒（>TTL 900）→ 新实例抢到，且带回被抢者信息"
# 【时间一律现算】用 `now - timedelta(3600s)` 而不是写死一个日期字面量——写死日期
# 会在若干天后变成永远超时（或永远不超时）的时间炸弹，[63] 就是这么坏掉的。
T="$(newtmpdir)"; mkrealrepo "$T"
mi_py "$T" 'kp.acquire_merge_lock(root, "_main", "dead-one", issue="DBG-009")[0]' >/dev/null
/usr/bin/python3 -c '
import sys, os, json, datetime
sys.path.insert(0, sys.argv[1])
import keeper_paths as kp
ld = kp.merge_lock_path(sys.argv[2], "_main")
old = (datetime.datetime.now().astimezone()
       - datetime.timedelta(seconds=3600)).isoformat(timespec="seconds")
with open(os.path.join(ld, "owner.json"), "w") as f:
    json.dump({"name": "dead-one", "ts": old, "issue": "DBG-009"}, f)
' "$LIBDIR" "$T"
OK4="$(mi_py "$T" 'kp.acquire_merge_lock(root, "_main", "newcomer")[0]')"
if [ "$OK4" = "True" ]; then ok "超过 TTL 的死锁被抢占"
else bad "超时锁应可抢占" "True" "$OK4"; fi
NOWHOLD="$(mi_py "$T" 'str(kp.read_merge_lock(root, "_main").get("name"))')"
if [ "$NOWHOLD" = "newcomer" ]; then ok "抢占后持有者换成抢占者"
else bad "抢占后持有者应为 newcomer" "newcomer" "$NOWHOLD"; fi
rm -rf "$T"

echo "[151] 未超时不抢占（误杀侧）：ts 改成 now-60 秒（<TTL）→ 仍然拿不到"
# 抢一把别人正在用的锁 = 两个 git merge 同时动主仓，比多等一会儿严重得多。
T="$(newtmpdir)"; mkrealrepo "$T"
mi_py "$T" 'kp.acquire_merge_lock(root, "_main", "busy-one", issue="DBG-010")[0]' >/dev/null
/usr/bin/python3 -c '
import sys, os, json, datetime
sys.path.insert(0, sys.argv[1])
import keeper_paths as kp
ld = kp.merge_lock_path(sys.argv[2], "_main")
recent = (datetime.datetime.now().astimezone()
          - datetime.timedelta(seconds=60)).isoformat(timespec="seconds")
with open(os.path.join(ld, "owner.json"), "w") as f:
    json.dump({"name": "busy-one", "ts": recent, "issue": "DBG-010"}, f)
' "$LIBDIR" "$T"
OK5="$(mi_py "$T" 'kp.acquire_merge_lock(root, "_main", "newcomer")[0]')"
if [ "$OK5" = "False" ]; then ok "持有 60 秒（未超时）的锁不被抢走"
else bad "未超时的锁不应被抢占" "False" "$OK5"; fi
STILL="$(mi_py "$T" 'str(kp.read_merge_lock(root, "_main").get("name"))')"
if [ "$STILL" = "busy-one" ]; then ok "持有者未变"
else bad "持有者不应变" "busy-one" "$STILL"; fi
rm -rf "$T"

echo "[152] 时间戳解析不了 → 年龄不可知，按「仍然有效」处理，拿不到（不是当成已超时）"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_py "$T" 'kp.acquire_merge_lock(root, "_main", "weird-ts")[0]' >/dev/null
/usr/bin/python3 -c '
import sys, os, json
sys.path.insert(0, sys.argv[1])
import keeper_paths as kp
ld = kp.merge_lock_path(sys.argv[2], "_main")
with open(os.path.join(ld, "owner.json"), "w") as f:
    json.dump({"name": "weird-ts", "ts": "not-a-timestamp"}, f)
' "$LIBDIR" "$T"
OK6="$(mi_py "$T" 'kp.acquire_merge_lock(root, "_main", "newcomer")[0]')"
if [ "$OK6" = "False" ]; then ok "ts 读不懂时保守判「锁仍有效」，不抢"
else bad "ts 读不懂时不应抢锁" "False" "$OK6"; fi
rm -rf "$T"

echo "[153] release 由持有者发起 → 删掉锁，read 回落到无人持锁"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_py "$T" 'kp.acquire_merge_lock(root, "_main", "opus-debug-keeper-aaaa")[0]' >/dev/null
REL="$(mi_py "$T" 'kp.release_merge_lock(root, "_main", "opus-debug-keeper-aaaa")')"
if [ "$REL" = "True" ]; then ok "持有者释放成功"
else bad "持有者释放应成功" "True" "$REL"; fi
AFTER="$(mi_py "$T" 'str(kp.read_merge_lock(root, "_main"))')"
if [ "$AFTER" = "None" ]; then ok "释放后 read_merge_lock 返回 None（无人持锁）"
else bad "释放后应无人持锁" "None" "$AFTER"; fi
rm -rf "$T"

echo "[154] release 时 owner 不匹配 → 拒绝删，锁原样保留（误删=把两个实例同时放进合并环节）"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_py "$T" 'kp.acquire_merge_lock(root, "_main", "opus-debug-keeper-aaaa")[0]' >/dev/null
REL2="$(mi_py "$T" 'kp.release_merge_lock(root, "_main", "opus-debug-keeper-bbbb")')"
if [ "$REL2" = "False" ]; then ok "非持有者释放被拒（返回 False）"
else bad "非持有者释放应被拒" "False" "$REL2"; fi
KEEP="$(mi_py "$T" 'str(kp.read_merge_lock(root, "_main").get("name"))')"
if [ "$KEEP" = "opus-debug-keeper-aaaa" ]; then ok "被拒后锁仍在原持有者名下"
else bad "被拒后锁应原样保留" "opus-debug-keeper-aaaa" "$KEEP"; fi
rm -rf "$T"

# ─────────────────── C · extract_issue 归属抽取（[155]-[160]）───────────────────

echo "[155] prompt 里有编号 → 抽到；有多个时只取第一个（派发模板要求认领目标写在开头）"
T="$(newtmpdir)"; mkrealrepo "$T"
E1="$(mi_py "$T" 'str(extract_issue({"prompt": "你认领 DBG-207，注意它与 DBG-100 现象相似"}, "debug"))')"
if [ "$E1" = "DBG-207" ]; then ok "取第一个匹配 DBG-207（不被后面的 DBG-100 带偏）"
else bad "应取第一个匹配" "DBG-207" "$E1"; fi
rm -rf "$T"

echo "[156] prompt 里没有、description 里有 → 从 description 兜底抽"
# 这条的 description 有意超出「简体中文 ≤15 字」那条规约（21 字），因为它测的是 hook 行为
# 而不是文档样例：`\bDBG-\d{3,}\b` 要求编号两侧有词边界，而汉字在 Python 的 Unicode 模式下
# 属于 `\w`——把编号紧贴中文写成 `debug 队列DBG-042`（正好 15 字）会让这里抽到 None。
# 所以规约那侧的结论是「编号写进 prompt、不写进 description」，兜底通道只覆盖历史与例外形态。
T="$(newtmpdir)"; mkrealrepo "$T"
E2="$(mi_py "$T" 'str(extract_issue({"prompt": "照队列纪律处理", "description": "debug 队列 · DBG-042 白屏"}, "debug"))')"
if [ "$E2" = "DBG-042" ]; then ok "description 兜底通道生效"
else bad "应从 description 抽到 DBG-042" "DBG-042" "$E2"; fi
rm -rf "$T"

echo "[157] 两个字段都没有编号 → 返回 None，**绝不编造**（错的 issue 键比缺键更糟）"
T="$(newtmpdir)"; mkrealrepo "$T"
E3="$(mi_py "$T" 'str(extract_issue({"prompt": "去把队列里的活干了", "description": "debug 队列·收尾"}, "debug"))')"
if [ "$E3" = "None" ]; then ok "抽不到时返回 None"
else bad "抽不到时应返回 None" "None" "$E3"; fi
rm -rf "$T"

echo "[158] 档位隔离：chore 档不认 DBG- 前缀，debug 档不认 CHR- 前缀（跨档串号会把补充信息发错实例）"
T="$(newtmpdir)"; mkrealrepo "$T"
E4="$(mi_py "$T" 'str(extract_issue({"prompt": "DBG-207 复现了"}, "chore"))')"
if [ "$E4" = "None" ]; then ok "chore 档不认 DBG- 编号"
else bad "chore 档不应认 DBG- 编号" "None" "$E4"; fi
E5="$(mi_py "$T" 'str(extract_issue({"prompt": "CHR-042 归档台账"}, "chore"))')"
if [ "$E5" = "CHR-042" ]; then ok "chore 档认自己的 CHR- 编号"
else bad "chore 档应认 CHR-042" "CHR-042" "$E5"; fi
E6="$(mi_py "$T" 'str(extract_issue({"prompt": "CHR-042 归档台账"}, "debug"))')"
if [ "$E6" = "None" ]; then ok "debug 档不认 CHR- 编号"
else bad "debug 档不应认 CHR- 编号" "None" "$E6"; fi
rm -rf "$T"

echo "[159] 位数不足的形近串（DBG-20，只有两位）不算命中——正则要求至少三位数字"
T="$(newtmpdir)"; mkrealrepo "$T"
E7="$(mi_py "$T" 'str(extract_issue({"prompt": "参考 DBG-20 那次"}, "debug"))')"
if [ "$E7" = "None" ]; then ok "两位数字不构成合法编号，返回 None"
else bad "两位数字不应命中" "None" "$E7"; fi
rm -rf "$T"

echo "[160] 端到端走 hook 外壳：派发 prompt 带 DBG-207 → 登记里写进 issue 键；不带则不写这个键"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_agent "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "sess-A" \
  "你是 DBG-207 的负责实例，name 是 opus-debug-keeper-4bb6" >/dev/null
REG="$T/.keeper/_main/.keeper-instance.json"
GOTI="$(ki_field "$REG" debug issue DBG-207)"
if [ "$GOTI" = "DBG-207" ]; then ok "hook 把 prompt 里的 DBG-207 登记进 issue 键"
else bad "登记应带 issue=DBG-207" "DBG-207" "$GOTI"; fi
rm -rf "$T"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_agent "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "sess-A" \
  "去把队列里的活干了" >/dev/null
REG="$T/.keeper/_main/.keeper-instance.json"
NOI="$(ki_field "$REG" debug issue)"
if [ -z "$NOI" ]; then ok "prompt 里没有编号时不写 issue 键（不是写空串或占位值）"
else bad "抽不到编号时不应写 issue 键" "空" "$NOI"; fi
NM="$(ki_field "$REG" debug name)"
if [ "$NM" = "opus-debug-keeper-4bb6" ]; then ok "抽不到编号不影响登记本身，name 照常写入"
else bad "name 应照常写入" "opus-debug-keeper-4bb6" "$NM"; fi
rm -rf "$T"

# ─────────────────── D · instance_state 按实例判状态（[161]-[166]）───────────────────

echo "[161] issue 为空（登记时没抽到编号）→ unknown，按 live 对待"
T="$(newtmpdir)"; mkrealrepo "$T"
S="$(mi_py "$T" 'instance_state(root + "/.keeper/_main", "debug", None)')"
if [ "$S" = "unknown" ]; then ok "issue 缺失判 unknown"
else bad "issue 缺失应判 unknown" "unknown" "$S"; fi
rm -rf "$T"

echo "[162] 条目目录还不存在（刚派出、keeper 尚未认领编号）→ unknown，不能判成收工"
# 判成收工的后果是主会话立刻重派一个，两个实例抢同一条 issue 的写权。
T="$(newtmpdir)"; mkrealrepo "$T"
S="$(mi_py "$T" 'instance_state(root + "/.keeper/_main", "debug", "DBG-999")')"
if [ "$S" = "unknown" ]; then ok "条目目录不存在判 unknown"
else bad "条目目录不存在应判 unknown" "unknown" "$S"; fi
rm -rf "$T"

echo "[163] 条目 status=open → live"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_item "$T" DBG-301 open
S="$(mi_py "$T" 'instance_state(root + "/.keeper/_main", "debug", "DBG-301")')"
if [ "$S" = "live" ]; then ok "open 条目判 live"
else bad "open 条目应判 live" "live" "$S"; fi
rm -rf "$T"

echo "[164] 条目 status=done 且无 worktree 残留 → retirable"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_item "$T" DBG-301 done
S="$(mi_py "$T" 'instance_state(root + "/.keeper/_main", "debug", "DBG-301")')"
if [ "$S" = "retirable" ]; then ok "done 且工作区已清判 retirable"
else bad "done 且无 worktree 应判 retirable" "retirable" "$S"; fi
rm -rf "$T"

echo "[165] 条目 done 但 worktree 还在（误杀侧）→ 仍判 live，它还欠一步收尾"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_item "$T" DBG-301 done
mkdir -p "$T/.keeper/_main/debug/DBG-301/worktree"
S="$(mi_py "$T" 'instance_state(root + "/.keeper/_main", "debug", "DBG-301")')"
if [ "$S" = "live" ]; then ok "done 但工作区未清仍判 live"
else bad "done 但有 worktree 应判 live" "live" "$S"; fi
rm -rf "$T"

echo "[166] 正文解析失败（没有 frontmatter）→ unknown，不是 live 也不是 retirable"
T="$(newtmpdir)"; mkrealrepo "$T"
mkdir -p "$T/.keeper/_main/debug/DBG-301"
printf '这份文件没有 frontmatter，解析不出 dict。\n' > "$T/.keeper/_main/debug/DBG-301/issue.md"
S="$(mi_py "$T" 'instance_state(root + "/.keeper/_main", "debug", "DBG-301")')"
if [ "$S" = "unknown" ]; then ok "解析失败判 unknown"
else bad "解析失败应判 unknown" "unknown" "$S"; fi
rm -rf "$T"

# ─────────────────── E · triage_wake_line 多实例措辞（[167]-[171]）───────────────────

echo "[167] 三个实例（两 debug 一 chore）→ 注入给出 issue→name 映射，且明说新 bug 一律新派"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_bind "$T" debug opus-debug-keeper-aaaa sess-A DBG-201
mi_bind "$T" debug opus-debug-keeper-bbbb sess-A DBG-202
mi_bind "$T" chore opus-chore-keeper-cccc sess-A CHR-001
TEXT="$(mi_text "$(run_triage_sess "$T" "sess-A")")"
has "映射带出 DBG-201 及其 name" "$TEXT" "DBG-201→\`opus-debug-keeper-aaaa\`"
has "映射带出 DBG-202 及其 name" "$TEXT" "DBG-202→\`opus-debug-keeper-bbbb\`"
has "映射带出 chore 档的 CHR-001" "$TEXT" "CHR-001→\`opus-chore-keeper-cccc\`"
has "明说新 bug 一律新派实例" "$TEXT" "新 bug 一律新派实例"
hasnt "不得出现 v6 那句「不要重派」" "$TEXT" "不要重派"
# 【4.2.0 分叉判据】CHR-001 必须落进 chore 那一句，而不是跟 DBG-201/202 挤在 debug 句里。
# 只断言 name 出现是不够的——4.0.0 那版把三个实例合成一句，CHR-001 同样"出现"了，
# 但它头顶挂着的是「新 bug 一律新派实例」。
has "chore 档单独成句" "$TEXT" "chore 在跑：CHR-001→\`opus-chore-keeper-cccc\`"
has "debug 档单独成句" "$TEXT" "debug 在跑：DBG-"
# 【为什么抽片段而不是写整句】句内条目的排列顺序取自登记表的写入次序，断言整句等于把
# 顺序也钉死，登记侧改一次追加位置这条就假红。真正要验的是分桶：debug 那句里不许出现
# CHR-，chore 那句里不许出现 DBG-。
# 【形态照抄同文件已验证过的那种】单行 python -c + 参数走 argv。
#
# 【全角括号紧贴变量名必须写 ${}】`（$DSEG）` 在本机 bash 3.2 + UTF-8 locale 下被解析成
# 变量名 `DSEG` 加上全角右括号的字节，`set -u` 当场报 `DSEG?: unbound variable` 整个
# 用例文件中断（实测撞过两次）。中文括号、书名号一类全角标点紧跟 `$NAME` 时一律写
# `${NAME}` 把边界划出来。
DSEG="$(/usr/bin/python3 -c 'import re,sys; m=re.search(r"debug 在跑：(.*?)。", sys.argv[1]); print(m.group(1) if m else "")' "$TEXT")"
case "$DSEG" in
  *CHR-*) bad "debug 句混入了 chore 条目" "只含 DBG-" "$DSEG" ;;
  "")     bad "取不到 debug 句" "非空片段" "(空)" ;;
  *)      ok "debug 句只装 debug 实例（${DSEG}）" ;;
esac
CSEG="$(/usr/bin/python3 -c 'import re,sys; m=re.search(r"chore 在跑：(.*?)。", sys.argv[1]); print(m.group(1) if m else "")' "$TEXT")"
case "$CSEG" in
  *DBG-*) bad "chore 句混入了 debug 条目" "只含 CHR-" "$CSEG" ;;
  "")     bad "取不到 chore 句" "非空片段" "(空)" ;;
  *)      ok "chore 句只装 chore 实例（${CSEG}）" ;;
esac
CHARS="$(/usr/bin/python3 -c 'import sys; print(len(sys.argv[1]))' "$TEXT")"
if [ "$CHARS" -le 800 ]; then ok "三实例分支 ${CHARS} 字符 ≤800"
else bad "三实例分支应 ≤800 字符" "<=800" "$CHARS"; fi
rm -rf "$T"

echo "[168] 实例数超过 MAX_LISTED（6 个）→ 只列 4 个 + 收敛成「等 N 个」，仍守 800 字符预算"
# 【为什么必须收敛】每轮注入有 800 字符硬上限（H19 断言），十几个实例的完整清单会把
# 三岔口本体挤掉——那是本注入真正对抗 system prompt 的部分，丢了它整段就白注。
T="$(newtmpdir)"; mkrealrepo "$T"
for i in 1 2 3 4 5 6; do mi_bind "$T" debug "opus-debug-keeper-x$i" sess-A "DBG-20$i"; done
TEXT="$(mi_text "$(run_triage_sess "$T" "sess-A")")"
has "超出部分收敛成「等 2 个」" "$TEXT" "等 2 个"
LISTED="$(printf '%s' "$TEXT" | grep -o 'opus-debug-keeper-x[1-6]' | sort -u | wc -l | tr -d ' ')"
if [ "$LISTED" -eq 4 ]; then ok "只逐条列出 4 个（MAX_LISTED），其余收敛"
else bad "应只列出 4 个实例" "4" "$LISTED"; fi
CHARS="$(/usr/bin/python3 -c 'import sys; print(len(sys.argv[1]))' "$TEXT")"
if [ "$CHARS" -le 800 ]; then ok "6 实例收敛后 ${CHARS} 字符 ≤800"
else bad "6 实例分支应 ≤800 字符" "<=800" "$CHARS"; fi
rm -rf "$T"

echo "[169] 一个实例已收工、一个还在跑 → 两段并存，收工那个进「别再唤醒」清单"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_bind "$T" debug opus-debug-keeper-done sess-A DBG-301
mi_bind "$T" debug opus-debug-keeper-live sess-A DBG-302
mi_item "$T" DBG-301 done
mi_item "$T" DBG-302 open
TEXT="$(mi_text "$(run_triage_sess "$T" "sess-A")")"
has "收工实例进「已收工，别再唤醒」清单" "$TEXT" "已收工，别再唤醒：DBG-301→\`opus-debug-keeper-done\`"
has "在跑实例仍在「debug 在跑」清单" "$TEXT" "debug 在跑：DBG-302→\`opus-debug-keeper-live\`"
rm -rf "$T"

echo "[170] 误杀侧：done 但 worktree 未清 → 不得进「已收工」清单，仍算在跑"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_bind "$T" debug opus-debug-keeper-done sess-A DBG-301
mi_item "$T" DBG-301 done
mkdir -p "$T/.keeper/_main/debug/DBG-301/worktree"
TEXT="$(mi_text "$(run_triage_sess "$T" "sess-A")")"
hasnt "worktree 未清时不提示已收工" "$TEXT" "已收工"
has "worktree 未清时仍列在「debug 在跑」" "$TEXT" "debug 在跑：DBG-301→\`opus-debug-keeper-done\`"
rm -rf "$T"

echo "[171] 误杀侧：登记有 issue 但条目还没落盘（unknown）→ 按 live 对待，不提示已收工"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_bind "$T" debug opus-debug-keeper-fresh sess-A DBG-777
TEXT="$(mi_text "$(run_triage_sess "$T" "sess-A")")"
hasnt "条目未落盘时不提示已收工" "$TEXT" "已收工"
has "条目未落盘时仍算在跑" "$TEXT" "DBG-777→\`opus-debug-keeper-fresh\`"
rm -rf "$T"

# 【为什么编号带 b】这条是 4.2.0 补的阴性对照，语义上属于 E 段（triage_wake_line 措辞），
# 挤进 [172] 会把后面 7 条全部重排、让历史 finding 里的编号引用全部错位。
echo "[171b] 只有 chore 实例在跑（无 debug）→ 只出 chore 那一句，不得出现 debug 的新派口径"
# 【这条就是 4.0.0 的缺陷本体】那版 WAKE_LINE_LIVE 只有一个 debug 口径，chore 独自在跑时
# 主会话读到的是「新 bug 一律新派实例」——照它做就会给 chore 再派一个实例，而 chore 的
# 全部价值在攒批打包拍板，拆成两个实例等于给 Human 发两份互不相干的决策请求。
T="$(newtmpdir)"; mkrealrepo "$T"
mi_bind "$T" chore opus-chore-keeper-only sess-A CHR-001
TEXT="$(mi_text "$(run_triage_sess "$T" "sess-A")")"
has "chore 独自在跑时给出 chore 句" "$TEXT" "chore 在跑：CHR-001→\`opus-chore-keeper-only\`"
hasnt "chore 独自在跑时不出现 debug 句头" "$TEXT" "debug 在跑"
hasnt "chore 独自在跑时不出现 debug 的新派口径" "$TEXT" "新 bug 一律新派实例"
rm -rf "$T"

# ─────────────────── F · SubagentStart 注入两份事实（[172]-[175]）───────────────────

echo "[172] 无漏派但同档 ≥2 个实例 → 仍然注入（v6 是零注入），并给出同档认领表"
# 【为什么放宽门槛】只给漏派清单会**制造**它要防的问题：每个实例都以为那几条没人管。
# 即使一条都没掉队，一个实例也需要知道旁边还有谁在跑。
T="$(newtmpdir)"; mkrealrepo "$T"
mi_bind "$T" debug opus-debug-keeper-aaaa sess-A DBG-401
mi_bind "$T" debug opus-debug-keeper-bbbb sess-A DBG-402
OUT="$(mi_sub "$T" "sess-A")"
has "无漏派但多实例时仍注入" "$OUT" "漏派体检 + 同档实例"
has "漏派位显示「（无漏派条目）」" "$OUT" "（无漏派条目）"
has "给出同档实例认领表" "$OUT" "同档在跑的实例"
has "表里带 DBG-401 的认领人" "$OUT" "DBG-401→\`opus-debug-keeper-aaaa\`"
has "表里带 DBG-402 的认领人" "$OUT" "DBG-402→\`opus-debug-keeper-bbbb\`"
has "提示别碰已被认领的条目" "$OUT" "别碰它"
rm -rf "$T"

echo "[173] 零成本一侧：无漏派且只有 1 个实例 → 零字节输出，exit 0"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_bind "$T" debug opus-debug-keeper-aaaa sess-A DBG-401
OUT="$(mi_sub "$T" "sess-A")"; RC=$?
if [ -z "$OUT" ] && [ "$RC" -eq 0 ]; then ok "单实例无漏派保持零注入（常态不占 keeper 一个字）"
else bad "单实例无漏派应零输出且 exit 0" "空/0" "OUT=[$OUT] RC=$RC"; fi
rm -rf "$T"

echo "[174] 会话隔离：两条登记属于别的会话 → 不计入 peers，退回零注入"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_bind "$T" debug opus-debug-keeper-aaaa sess-OLD DBG-401
mi_bind "$T" debug opus-debug-keeper-bbbb sess-OLD DBG-402
OUT="$(mi_sub "$T" "sess-A")"
if [ -z "$OUT" ]; then ok "跨会话的死登记不计入同档实例表"
else bad "跨会话登记不应计入 peers" "空" "$(printf '%s' "$OUT" | head -c 200)"; fi
rm -rf "$T"

echo "[175] 有漏派 + 多实例 → 两份事实同时给出（漏派条目与认领表都在）"
T="$(newtmpdir)"; mkrealrepo "$T"
Q="$T/.keeper/_main/debug"
mkissue "$Q" DBG-401 open P1 "已 triage 未派的问题" "" medium
mi_bind "$T" debug opus-debug-keeper-aaaa sess-A DBG-402
mi_bind "$T" debug opus-debug-keeper-bbbb sess-A DBG-403
OUT="$(mi_sub "$T" "sess-A")"
has "漏派清单里有 DBG-401" "$OUT" "DBG-401"
has "同档认领表同时给出" "$OUT" "同档在跑的实例"
hasnt "漏派位不再显示「无漏派条目」" "$OUT" "（无漏派条目）"
rm -rf "$T"

# ─────────────────── G · 登记表本身的多实例读写（[176]-[178]）───────────────────

echo "[176] 同一档写两个不同 name → 两条并存（v6 的覆盖式写入会让先派的那个从登记里消失）"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_bind "$T" debug opus-debug-keeper-aaaa sess-A DBG-201
mi_bind "$T" debug opus-debug-keeper-bbbb sess-A DBG-202
REG="$T/.keeper/_main/.keeper-instance.json"
CNT="$(ki_count "$REG" debug)"
if [ "$CNT" -eq 2 ]; then ok "同档登记两条实例"
else bad "同档应登记 2 条" "2" "$CNT"; fi
N1="$(ki_field "$REG" debug name DBG-201)"
N2="$(ki_field "$REG" debug name DBG-202)"
if [ "$N1" = "opus-debug-keeper-aaaa" ] && [ "$N2" = "opus-debug-keeper-bbbb" ]; then ok "按 issue 取到各自的 name（寻址按编号，不按时间猜）"
else bad "按 issue 取 name 错误" "aaaa/bbbb" "$N1/$N2"; fi
rm -rf "$T"

echo "[177] 同名重复登记是幂等更新（不产生第二条），换绑 issue 走同一条路径"
T="$(newtmpdir)"; mkrealrepo "$T"
mi_bind "$T" debug opus-debug-keeper-aaaa sess-A DBG-201
mi_bind "$T" debug opus-debug-keeper-aaaa sess-A DBG-209
REG="$T/.keeper/_main/.keeper-instance.json"
CNT="$(ki_count "$REG" debug)"
if [ "$CNT" -eq 1 ]; then ok "同名重复登记不产生第二条"
else bad "同名重复登记应仍是 1 条" "1" "$CNT"; fi
CUR="$(ki_field "$REG" debug issue)"
if [ "$CUR" = "DBG-209" ]; then ok "issue 被更新成最新认领的那条"
else bad "issue 应更新为 DBG-209" "DBG-209" "$CUR"; fi
rm -rf "$T"

echo "[178] v6 单条格式（kind 直接是 dict）在读侧被吸收成单元素列表——升级插件不重写既有登记文件"
T="$(newtmpdir)"; mkrealrepo "$T"
mkdir -p "$T/.keeper/_main"
# ts 现算，不写死字面量——`_prune_instances` 按 14 天 TTL 剔旧记录，写死日期的 fixture
# 会在某天之后静默变成「这条已过期」，表现成本用例莫名其妙变红（[63] 就是这么坏的）。
NOW_TS="$(/usr/bin/python3 -c 'import datetime;print(datetime.datetime.now().astimezone().isoformat(timespec="seconds"))')"
/usr/bin/python3 -c '
import json, sys
with open(sys.argv[1], "w") as f:
    json.dump({"debug": {"name": "opus-debug-keeper-v6", "ts": sys.argv[2],
                         "session_id": "sess-A"}}, f)
' "$T/.keeper/_main/.keeper-instance.json" "$NOW_TS"
CNT="$(mi_py "$T" 'len(kp.live_instances(root, "_main", "debug", current_session_id="sess-A"))')"
if [ "$CNT" = "1" ]; then ok "v6 单条格式被读成 1 条实例"
else bad "v6 单条格式应读成 1 条" "1" "$CNT"; fi
NM="$(mi_py "$T" 'str(kp.live_instances(root, "_main", "debug", current_session_id="sess-A")[0].get("name"))')"
if [ "$NM" = "opus-debug-keeper-v6" ]; then ok "v6 记录的 name 读得出来"
else bad "v6 记录 name 读取错误" "opus-debug-keeper-v6" "$NM"; fi
rm -rf "$T"
