# H21 · keeper 实例落盘登记（pre-tool-use-keeper-instance.sh：PreToolUse(Agent)
# 命中 keeper 类 subagent_type 时把 tool_input.name 写进
# `.keeper/<交付id>/.keeper-instance.json`）。依赖 harness.sh 的
# newtmpdir/mkrealrepo/run_keeper_instance/ki_field/ok/bad/has/hasnt。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件自成一体，不依赖其他 case 文件留下的变量或函数。
#
# 【为什么要真实 git 仓库】keeper_paths.find_worktree_root 靠真实 `git rev-parse`
# 系列命令定位工作区根；其他 case 常用的假 `.git` 占位文件（`: > "$T/.git"`）在
# 这里不适用——那条路径会让 git 命令全部失败、`find_worktree_root` 返回 None，
# 本 hook 遇到 None 就直接放弃，测不出任何写入行为。所以本节统一用 mkrealrepo
# 造一个可以真正跑 git 命令的仓库；basename 不匹配 `D-\d+-*`/`hotfix-*`，落
# `_main` 兜底桶。
# 【2026-08-05 追加 [81]-[86]】会话隔离——[81]-[82] 测本文件对应的 hook 外壳
# （payload 带/不带 session_id 两侧）；[83]-[86] 直接调用 `keeper_paths.py` 的
# `write_keeper_instance`/`read_keeper_instance_name`，测函数级的会话比对与
# 旧格式（无 session_id 键）陈旧判据，走 py_kp() 这个新 helper，模式与
# 04-h8-wt-supply.sh 的 py_nextid() 一致。三岔口注入文案的三选一（要用到
# `keeper_routing.py` 的 `triage_wake_line`）另开一节，见 17-h22。

echo
echo "== H21 · keeper 实例落盘登记（pre-tool-use-keeper-instance.sh：PreToolUse(Agent)）=="

echo "[74] 命中 debug-keeper 白名单 + 有效 name → 写入 .keeper/_main/.keeper-instance.json 的 debug 键"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" >/dev/null
REG="$T/.keeper/_main/.keeper-instance.json"
if [ -f "$REG" ]; then ok "登记文件被建出来"
else bad "登记文件应存在" "存在" "不存在"; fi
NAME="$(ki_field "$REG" debug name)"
if [ "$NAME" = "opus-debug-keeper-4bb6" ]; then ok "debug 键的 name 写入正确"
else bad "debug.name 应为 opus-debug-keeper-4bb6" "opus-debug-keeper-4bb6" "$NAME"; fi
TS="$(ki_field "$REG" debug ts)"
case "$TS" in *T*) ok "debug 键带 ts 时间戳（含 T 分隔符）";; *) bad "debug.ts 应是 ISO 时间戳" "含 T" "$TS";; esac

echo "[75] 命中 chore-keeper + 有效 name → 写 chore 键，且不覆盖已有的 debug 键（合并写，不整份覆盖）"
run_keeper_instance "$T" "task-keeper:chore-keeper" "opus-chore-keeper-9f2a" >/dev/null
NAME_CHORE="$(ki_field "$REG" chore name)"
if [ "$NAME_CHORE" = "opus-chore-keeper-9f2a" ]; then ok "chore 键的 name 写入正确"
else bad "chore.name 应为 opus-chore-keeper-9f2a" "opus-chore-keeper-9f2a" "$NAME_CHORE"; fi
NAME_DEBUG_STILL="$(ki_field "$REG" debug name)"
if [ "$NAME_DEBUG_STILL" = "opus-debug-keeper-4bb6" ]; then ok "写 chore 键之后 debug 键原样保留（没被整份覆盖）"
else bad "debug.name 应仍是 opus-debug-keeper-4bb6" "opus-debug-keeper-4bb6" "$NAME_DEBUG_STILL"; fi
rm -rf "$T"

echo "[76] subagent_type 不在白名单内（如 general-purpose）→ 不登记（不写任何文件）"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "general-purpose" "sonnet-some-task-a1b2" >/dev/null
if [ ! -f "$T/.keeper/_main/.keeper-instance.json" ]; then ok "非白名单 subagent_type 不产生登记文件"
else bad "不应产生登记文件" "不存在" "存在"; fi
rm -rf "$T"

echo "[77] tool_name 不是 Agent（即便 subagent_type/name 都命中）→ 不登记（假阳性防线）"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "Bash" >/dev/null
if [ ! -f "$T/.keeper/_main/.keeper-instance.json" ]; then ok "tool_name!=Agent 时不登记，即便字段形态命中"
else bad "tool_name 不是 Agent 时不应登记" "不存在" "存在"; fi
rm -rf "$T"

echo "[78] tool_input 缺 name → 不登记（没有可登记的东西，不用占位值顶替）"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" >/dev/null
if [ ! -f "$T/.keeper/_main/.keeper-instance.json" ]; then ok "name 缺失时不登记"
else bad "name 缺失时不应登记" "不存在" "存在"; fi
rm -rf "$T"

echo "[79] .keeper/<交付id>/ 目录事先不存在 → hook 自动 mkdir -p 建出并写入（不要求 .keeper/ 顶层预先 opt-in）"
T="$(newtmpdir)"; mkrealrepo "$T"
if [ ! -d "$T/.keeper" ]; then ok "登记前 .keeper/ 确实不存在（前提成立）"
else bad "登记前 .keeper/ 应不存在" "不存在" "存在"; fi
run_keeper_instance "$T" "task-keeper:chore-keeper" "opus-chore-keeper-0001" >/dev/null
if [ -f "$T/.keeper/_main/.keeper-instance.json" ]; then ok "目录被自动建出，登记文件写入成功（冷启动场景）"
else bad "应自动建出目录并写入登记文件" "存在" "不存在"; fi
rm -rf "$T"

echo "[80] subagent_type 不带插件前缀的裸值（debug-keeper，无冒号）同样命中白名单"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "debug-keeper" "opus-debug-keeper-cafe" >/dev/null
NAME_BARE="$(ki_field "$T/.keeper/_main/.keeper-instance.json" debug name)"
if [ "$NAME_BARE" = "opus-debug-keeper-cafe" ]; then ok "裸 subagent_type（无冒号）同样命中并登记"
else bad "裸 subagent_type 应同样命中" "opus-debug-keeper-cafe" "$NAME_BARE"; fi
rm -rf "$T"

# ────────────────────────── 会话隔离（2026-08-05 补，keeper_instance_register.py 侧）──────────────────────────
# 判据在 keeper_paths.py：write_keeper_instance 新增 session_id 参数、
# read_keeper_instance_name 新增 current_session_id 参数。本节先测
# pre-tool-use-keeper-instance.sh 这一层（payload 带/不带 session_id 两侧），
# keeper_paths.py 函数级别的读写/旧格式判据放到下面单独一段直接调用 python。

echo "[81] payload 带 session_id → 登记文件的 session_id 键写入正确"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "Agent" "sess-AAA" >/dev/null
REG="$T/.keeper/_main/.keeper-instance.json"
SID="$(ki_field "$REG" debug session_id)"
if [ "$SID" = "sess-AAA" ]; then ok "debug 键的 session_id 写入正确"
else bad "debug.session_id 应为 sess-AAA" "sess-AAA" "$SID"; fi
rm -rf "$T"

echo "[82] payload 缺 session_id → 仍然登记 name，且不写出坏文件（JSON 仍合法，没有 session_id 键）"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" >/dev/null
REG="$T/.keeper/_main/.keeper-instance.json"
NAME_NOSID="$(ki_field "$REG" debug name)"
if [ "$NAME_NOSID" = "opus-debug-keeper-4bb6" ]; then ok "缺 session_id 时 name 仍正常登记"
else bad "缺 session_id 时 name 应仍登记" "opus-debug-keeper-4bb6" "$NAME_NOSID"; fi
# 【v7 起必须下钻到 instances 那一层】登记从「kind 直接是一条 record」变成
# 「kind 是 {"instances": [record, ...]}」。原先这里写的是
# `"session_id" in d.get("debug", {})`——它在 v7 下**恒为 False**，因为 v7 的
# `d["debug"]` 只有 `instances` 一个键。也就是说这条断言即使 hook 真的错写了
# session_id 也照样绿，是一条失去检测力的假绿。改成读第一条 record 本身。
HAS_KEY="$(/usr/bin/python3 -c '
import json
try:
    d = json.load(open("'"$REG"'"))
    e = d.get("debug") or {}
    rec = (e.get("instances") or [e])[0]
    print("session_id" in rec)
except Exception:
    print("ERROR")
')"
if [ "$HAS_KEY" = "False" ]; then ok "缺 session_id 时登记记录里不写出这个键（不是写 null）"
else bad "缺 session_id 时不应写出 session_id 键" "False" "$HAS_KEY"; fi
rm -rf "$T"

# ────────────────────────── 会话隔离（keeper_paths.py 函数级） ──────────────────────────
# 直接调用 write_keeper_instance/read_keeper_instance_name，不经过 hook 外壳——
# 判据是这两个函数自己的行为，用 py_kp() 直接跑，模式与 04-h8-wt-supply.sh 的
# py_nextid() 一致。

py_kp() {   # $1=worktree_root，其余转给 python 表达式，import 好 keeper_paths 后 eval
  /usr/bin/python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
import keeper_paths as kp
root = sys.argv[2]
print(eval(sys.argv[3]))
' "$LIBDIR" "$1" "$2"
}

echo "[83] write_keeper_instance 带 session_id，read_keeper_instance_name 传相同 session_id → 读得到 name"
T="$(newtmpdir)"; mkrealrepo "$T"
py_kp "$T" 'kp.write_keeper_instance(root, "_main", "debug", "opus-debug-keeper-1111", session_id="sess-A")' >/dev/null
GOT="$(py_kp "$T" 'kp.read_keeper_instance_name(root, "_main", "debug", current_session_id="sess-A")')"
if [ "$GOT" = "opus-debug-keeper-1111" ]; then ok "同 session_id 比对通过，读得到 name"
else bad "同 session_id 应读得到 name" "opus-debug-keeper-1111" "$GOT"; fi
rm -rf "$T"

echo "[84] 同一条登记，传不同的 current_session_id → 读不到（返回 None）"
T="$(newtmpdir)"; mkrealrepo "$T"
py_kp "$T" 'kp.write_keeper_instance(root, "_main", "debug", "opus-debug-keeper-1111", session_id="sess-A")' >/dev/null
GOT="$(py_kp "$T" 'kp.read_keeper_instance_name(root, "_main", "debug", current_session_id="sess-B")')"
if [ "$GOT" = "None" ]; then ok "不同 session_id 比对失败，返回 None"
else bad "不同 session_id 应返回 None" "None" "$GOT"; fi
rm -rf "$T"

echo "[85] 登记是旧格式（没有 session_id 键）→ 传 current_session_id 比对时当陈旧处理，返回 None"
T="$(newtmpdir)"; mkrealrepo "$T"
# 不传 session_id 参数，模拟会话隔离机制落地之前写入的旧格式记录。
py_kp "$T" 'kp.write_keeper_instance(root, "_main", "debug", "opus-debug-keeper-1111")' >/dev/null
GOT="$(py_kp "$T" 'kp.read_keeper_instance_name(root, "_main", "debug", current_session_id="sess-A")')"
if [ "$GOT" = "None" ]; then ok "旧格式（无 session_id 键）在会话比对下当陈旧处理，返回 None"
else bad "旧格式登记在会话比对下应返回 None" "None" "$GOT"; fi
rm -rf "$T"

echo "[86] 不传 current_session_id（缺省）→ 维持旧行为，不比较会话，只看 name 有没有"
T="$(newtmpdir)"; mkrealrepo "$T"
py_kp "$T" 'kp.write_keeper_instance(root, "_main", "debug", "opus-debug-keeper-1111", session_id="sess-A")' >/dev/null
GOT="$(py_kp "$T" 'kp.read_keeper_instance_name(root, "_main", "debug")')"
if [ "$GOT" = "opus-debug-keeper-1111" ]; then ok "不传 current_session_id 时忽略会话比对，读到 name"
else bad "不传 current_session_id 时应读到 name（旧行为）" "opus-debug-keeper-1111" "$GOT"; fi
rm -rf "$T"
