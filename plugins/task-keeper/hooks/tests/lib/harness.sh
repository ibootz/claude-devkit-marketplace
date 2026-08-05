# task-keeper hook 回归测试 · 共享测试骨架（harness）。
#
# 本文件由 run-tests.sh 在同一个 shell 里用 `source` 执行，定义全部用例共用的
# helper 函数与 pass/fail 计数器初始化；cases/ 下每个用例文件直接调用这里的
# 函数，不重新定义。不要单独 `bash` 执行本文件——它没有入口逻辑，也不产出任何
# 输出。HOOK_DIR / HOOK / HOOK_CHORE / ROUTING / TRIAGE_HOOK / LIBDIR 等路径
# 变量由 run-tests.sh 用 `${BASH_SOURCE[0]}` 算出（算法依赖调用者自身的路径，
# 挪到本文件会指向 harness.sh 自己的位置，路径就错一层），本文件只读取、不
# 重新计算这些变量。
#
# 【可移植性】本仓库要求脚本同时兼容 Linux 与 macOS，故：mktemp 一律带
#   XXXXXX 模板（BSD 不接受省略）；不使用 sed -i 原地编辑（GNU 与 BSD 的
#   -i 语义冲突）；python 解释器统一写死 `/usr/bin/python3`（避免 PATH 上
#   装了别的 python3 导致依赖版本漂移）；日期计算一律用 python 现算
#   （`datetime.date.today()`），不写死具体年份/日期字面量。
#   （本节原文位于拆分前 run-tests.sh 文件头 57-61 行，随 helper 实现一起
#   搬到这里；run-tests.sh 头部留了指回本文件的指针，不再重复这段文字。）

pass=0; fail=0

newtmpdir() { mktemp -d "${TMPDIR:-/tmp}/tk-dbgq.XXXXXX"; }

# 取文件 mtime。不用 stat——它的格式参数在两个平台互不兼容（BSD/macOS 是 -f、
# GNU/Linux 是 -c），而 `stat -f … || stat -c …` 那种兜法会把「命令失败」变成
# 正常控制流，出真错时也被吞掉。本脚本本来就依赖 /usr/bin/python3，用它最干净。
mtime() {
  /usr/bin/python3 -c 'import os,sys;print(int(os.stat(sys.argv[1]).st_mtime))' "$1"
}

# 造一条 debug 队列 issue 文件（v4：一条目一目录）。$1=队列目录
# （形如 <worktree根>/.keeper/<交付id>/debug，调用方自己按 keeper_paths 的解析
# 规则拼好这个路径——裸临时目录一律落 _main 兜底桶）$2=id $3=status $4=priority
# $5=summary $6=reported_at（可省略，默认 2026-07-29；H17 的超龄归档用例需要
# 显式传一个 >14 天前的日期）
mkissue() {
  mkdir -p "$1/$2"
  {
    echo "---"
    echo "id: $2"
    echo "summary: $5"
    echo "status: $3"
    [ -n "$4" ] && echo "priority: $4"
    echo "reported_at: ${6:-2026-07-29}"
    echo "---"
    echo
    echo "# $2 · $5"
    echo
    echo "## 用户原话"
    echo
    echo '```text'
    echo "这里是原话"
    echo '```'
  } > "$1/$2/issue.md"
}

# 造一条 chore 队列条目文件（v4：一条目一目录）。$1=队列目录
# （形如 <worktree根>/.keeper/<交付id>/chore）$2=id $3=status $4=kind $5=summary
# $6=reported_at（可省略，默认 2026-07-29）
mkchore() {
  mkdir -p "$1/$2"
  {
    echo "---"
    echo "id: $2"
    echo "summary: $5"
    echo "status: $3"
    [ -n "$4" ] && echo "kind: $4"
    echo "reported_at: ${6:-2026-07-29}"
    echo "---"
    echo
    echo "# $2 · $5"
  } > "$1/$2/item.md"
}

run_hook() {         # $1 = cwd, $2 = prompt —— debug 队列快照 hook
  /usr/bin/python3 -c '
import json,sys
print(json.dumps({"hook_event_name":"UserPromptSubmit","cwd":sys.argv[1],"prompt":sys.argv[2]}))
' "$1" "$2" | bash "$HOOK"
}

run_chore() {         # $1 = cwd, $2 = prompt —— chore 队列快照 hook
  /usr/bin/python3 -c '
import json,sys
print(json.dumps({"hook_event_name":"UserPromptSubmit","cwd":sys.argv[1],"prompt":sys.argv[2]}))
' "$1" "$2" | bash "$HOOK_CHORE"
}

run_routing() {       # $1 = cwd —— SessionStart 路由注入 hook
  # 【回归点】薄壳曾有 heredoc-stdin bug：若用 `python3 - <<EOF` 内联生成事件 JSON，
  # heredoc 会占用 python 自己的 stdin，事件 JSON 反而读不到、cwd 拿不到。本 helper
  # 必须走「独立进程生成 JSON → 管道喂给薄壳」这条路径，不能改写成 heredoc 形态，
  # 否则这条测试就不再是它的回归。
  /usr/bin/python3 -c '
import json,sys
print(json.dumps({"hook_event_name":"SessionStart","cwd":sys.argv[1]}))
' "$1" | bash "$ROUTING"
}

run_triage() {        # $1 = cwd —— UserPromptSubmit 三岔口分诊注入 hook
  # 与 run_routing 同一条 heredoc-stdin 回归约束，不要改写成 heredoc 形态。
  /usr/bin/python3 -c '
import json,sys
print(json.dumps({"hook_event_name":"UserPromptSubmit","cwd":sys.argv[1]}))
' "$1" | bash "$TRIAGE_HOOK"
}

run_triage_sess() {   # $1=cwd $2=session_id(可省，省则 payload 不带 session_id 键)
  # 与 run_triage 的差异只是多带 session_id——H22 用它构造"本会话匹配/不匹配"两侧。
  /usr/bin/python3 -c '
import json,sys
ev = {"hook_event_name": "UserPromptSubmit", "cwd": sys.argv[1]}
if len(sys.argv) > 2 and sys.argv[2]:
    ev["session_id"] = sys.argv[2]
print(json.dumps(ev))
' "$1" "${2:-}" | bash "$TRIAGE_HOOK"
}

run_keeper_instance() {   # $1=cwd $2=subagent_type(可省) $3=name(可省) $4=tool_name(可省，默认 Agent) $5=session_id(可省)
  # PreToolUse(Agent) keeper 实例登记 hook。$2/$3/$5 省略时 tool_input/顶层对应键就
  # 不写，用来构造「缺 subagent_type」「缺 name」「缺 session_id」这类假阴性输入。
  /usr/bin/python3 -c '
import json,sys
ti = {}
if len(sys.argv) > 2 and sys.argv[2]:
    ti["subagent_type"] = sys.argv[2]
if len(sys.argv) > 3 and sys.argv[3]:
    ti["name"] = sys.argv[3]
ev = {
    "hook_event_name": "PreToolUse",
    "tool_name": sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else "Agent",
    "cwd": sys.argv[1],
    "tool_input": ti,
}
if len(sys.argv) > 5 and sys.argv[5]:
    ev["session_id"] = sys.argv[5]
print(json.dumps(ev))
' "$1" "${2:-}" "${3:-}" "${4:-Agent}" "${5:-}" | bash "$KEEPER_INSTANCE_HOOK"
}

# 造一个真实 git 仓库（keeper_paths.find_worktree_root 需要真实 git 命令能跑通，
# 假 `.git` 占位文件在这里不适用——find_worktree_root 会因为 git 命令全部失败而
# 返回 None，本 hook 遇到 None 就直接放弃，测不出任何写入行为）。$1=目标目录
mkrealrepo() {
  git init -q -b master "$1" >/dev/null 2>&1
  git -C "$1" config user.email t@t.t
  git -C "$1" config user.name t
  echo hi > "$1/f.txt"
  git -C "$1" add -A >/dev/null 2>&1
  git -C "$1" commit -qm init >/dev/null 2>&1
}

# 读 `.keeper-instance.json` 某一档的某个字段。$1=json 文件绝对路径 $2=kind(debug/chore)
# $3=字段名(name/ts)。文件不存在/损坏/键缺失都返回空串，不报错——断言侧用空串与
# 期望值比较即可，不需要先判断文件是否存在。
ki_field() {
  /usr/bin/python3 -c '
import json,sys
try:
    d = json.load(open(sys.argv[1]))
    print(d.get(sys.argv[2], {}).get(sys.argv[3], ""))
except Exception:
    print("")
' "$1" "$2" "$3"
}

ok()   { pass=$((pass+1)); printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf '  \033[31m✗\033[0m %s\n' "$1"; printf '      期望: %s\n      实际: %s\n' "$2" "$3"; }

has()  { # $1 名称  $2 输出  $3 期望子串
  case "$2" in *"$3"*) ok "$1";; *) bad "$1" "包含 [$3]" "$(printf '%s' "$2" | head -c 300)";; esac
}
hasnt() {
  case "$2" in *"$3"*) bad "$1" "不含 [$3]" "$(printf '%s' "$2" | head -c 300)";; *) ok "$1";; esac
}
