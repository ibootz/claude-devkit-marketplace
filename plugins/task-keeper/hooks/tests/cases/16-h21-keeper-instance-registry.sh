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
