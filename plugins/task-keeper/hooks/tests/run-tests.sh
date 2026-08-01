#!/usr/bin/env bash
#
# task-keeper · hook 回归测试（Debug/Chore 双队列 schema v3 · worktree 供给 ·
# 截图证据守卫 · push/destroy 守卫 · 归档 · 决策信箱 · 主会话路由注入）
#
# 用法： bash plugins/task-keeper/hooks/tests/run-tests.sh
# 退出码：0 全过 / 1 有失败
#
# 【来源】本文件搬迁自 radnove-core 插件的
#   plugins/radnove-core/hooks/tests/run-tests.sh（922 行，schema v3 版本）。
#   task-keeper 是 radnove debug 体系的通用化搬迁版：产物布局从 `.debug/` 改成
#   `.keeper/`（debug 队列在 `.keeper/debug/`，chore 队列在 `.keeper/chore/`，
#   worktree 落点 `.keeper/worktrees/<id>/` 与 `debug/`、`chore/` **平级**，
#   不在 debug/ 目录内部）；存储层从 `issue_files.py` 单队列实现改成
#   `queue_files.py` 的 QueueSpec 参数化实现，一份代码同时伺候 debug（DBG-）与
#   chore（CHR-）两个队列；skill 目录从 `debug-triage/` / `worktree-supply/`
#   改名 `tk-debug/` / `tk-worktree/`；hook_counter 的临时状态文件前缀从
#   `rn-` 改成 `tk-`。下面每一节的用例编号、断言意图与旧版逐条对应，只按上述
#   差异改写了路径字面量、模块导入方式与函数签名，判断逻辑本身未改动。
#
# 【搬了旧版哪 8 节，为什么另外两节不搬】
#   搬：H1（1-8，debug 队列快照）/ H1b（9-13，index.md）/ H7（25-30，截图证据
#   守卫）/ H8（31-39，wt_supply.py）/ H9（40-42，push 守卫）/ H10（43-45，
#   destroy 守卫）/ H11（46-48，归档）/ H12（49-52，merge-back 源侧判据）。
#   不搬：H5（tf 发布守卫）与 H13/[53]-[56]（dbops 提单守卫）——这两节测的是
#   `ymcas` / `fe_deploy.py` / `dbops` 这类云学堂内部工具链，是 radnove-core
#   插件的公司专属能力，task-keeper 里既没有对应的被测脚本，也不该有；这两节
#   继续留在 radnove-core 仓自己的回归测试里。
#
# 【编号沿用旧坐标、故意留空档】
#   旧文件本身的用例编号就不连续（[17] 跳到 [25]，是 v3 摘除派发/回执对账/前端
#   组件溯源三节后留下的空档，旧文件头注释解释过原因）。本文件继续沿用这个
#   历史坐标：H1/H1b 用 [1]-[13]，跳过 H5 原占的 [13]-[17]（旧 tf 守卫用例，
#   本文件不搬），H7-H12 用 [25]-[52]（与旧文件完全一致的编号），跳过 H13 原占
#   的 [53]-[56]（旧 dbops 用例，本文件不搬），新增的 5 节从 [57] 起接着编号。
#   编号是历史坐标而不是行号——保持它不变，是为了让「第 N 个用例」这种指代在
#   跨文件/跨版本的讨论里仍然对得上。
#
# 【新增 5 节，编号 [57]-[66]】
#   H14（[57]-[58]，chore 快照）/ H15（[59]，决策信箱计数与 debug↔chore 去重）/
#   H16（[60]-[61]，双队列互不串号）/ H17（[62]-[64]，archive_done.py --auto
#   自动归档）/ H18（[65]-[66]，SessionStart 路由注入分档）。这 5 节测的是
#   task-keeper 相对 radnove-core 新增的能力（chore 队列、决策信箱、主会话
#   路由注入、自动归档），radnove-core 里没有对应实现，故不是「搬迁」而是
#   新写。
#
# 【测试用真实进程跑，不 mock】直接把 JSON 喂给 hook 脚本的 stdin、断言 stdout，
#   与 harness 的调用方式完全一致，因此能覆盖 bash 外壳、python 定位、编码等
#   全链路，而不只是 python 函数。
#
# 【可移植性】本仓库要求脚本同时兼容 Linux 与 macOS，故：mktemp 一律带
#   XXXXXX 模板（BSD 不接受省略）；不使用 sed -i 原地编辑（GNU 与 BSD 的
#   -i 语义冲突）；python 解释器统一写死 `/usr/bin/python3`（避免 PATH 上
#   装了别的 python3 导致依赖版本漂移）；日期计算一律用 python 现算
#   （`datetime.date.today()`），不写死具体年份/日期字面量。

set -uo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$HOOK_DIR/user-prompt-submit-debug-queue.sh"
HOOK_CHORE="$HOOK_DIR/user-prompt-submit-chore-queue.sh"
ROUTING="$HOOK_DIR/session-start-keeper-routing.sh"
LIBDIR="$HOOK_DIR/lib"

pass=0; fail=0

newtmpdir() { mktemp -d "${TMPDIR:-/tmp}/tk-dbgq.XXXXXX"; }

# 取文件 mtime。不用 stat——它的格式参数在两个平台互不兼容（BSD/macOS 是 -f、
# GNU/Linux 是 -c），而 `stat -f … || stat -c …` 那种兜法会把「命令失败」变成
# 正常控制流，出真错时也被吞掉。本脚本本来就依赖 /usr/bin/python3，用它最干净。
mtime() {
  /usr/bin/python3 -c 'import os,sys;print(int(os.stat(sys.argv[1]).st_mtime))' "$1"
}

# 造一条 debug 队列 issue 文件。$1=队列目录(.keeper/debug) $2=id $3=status
# $4=priority $5=summary $6=reported_at（可省略，默认 2026-07-29；H17 的超龄
# 归档用例需要显式传一个 >14 天前的日期）
mkissue() {
  mkdir -p "$1/issues"
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
  } > "$1/issues/$2.md"
}

# 造一条 chore 队列条目文件。$1=队列目录(.keeper/chore) $2=id $3=status
# $4=kind $5=summary $6=reported_at（可省略，默认 2026-07-29）
mkchore() {
  mkdir -p "$1/items"
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
  } > "$1/items/$2.md"
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

ok()   { pass=$((pass+1)); printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf '  \033[31m✗\033[0m %s\n' "$1"; printf '      期望: %s\n      实际: %s\n' "$2" "$3"; }

has()  { # $1 名称  $2 输出  $3 期望子串
  case "$2" in *"$3"*) ok "$1";; *) bad "$1" "包含 [$3]" "$(printf '%s' "$2" | head -c 300)";; esac
}
hasnt() {
  case "$2" in *"$3"*) bad "$1" "不含 [$3]" "$(printf '%s' "$2" | head -c 300)";; *) ok "$1";; esac
}

echo "== H1 · Debug 队列快照（schema v3：一 issue 一文件，落点 .keeper/debug/）=="

echo "[1] 零成本保证：没有 .keeper/debug/issues/ 的项目 stdout 必须全空"
T="$(newtmpdir)"; : > "$T/.git"
OUT="$(run_hook "$T" '报错了，白屏')"
if [ -z "$OUT" ]; then ok "无队列项目零输出（含 bug 特征词也不注入）"
else bad "无队列应零输出" "空" "$OUT"; fi
# 只有 .keeper/debug/ 没有 issues/ 也算未启用——冷启动入口是 mkdir -p .keeper/debug/issues
mkdir -p "$T/.keeper/debug"
OUT="$(run_hook "$T" '继续')"
if [ -z "$OUT" ]; then ok "有 .keeper/debug/ 但无 issues/ 仍视为未启用"
else bad "应零输出" "空" "$OUT"; fi
rm -rf "$T"

echo "[2] 分桶：open 列出、done 只给计数"
T="$(newtmpdir)"; : > "$T/.git"
mkissue "$T/.keeper/debug" DBG-001 done ""   "已修好的历史问题"
mkissue "$T/.keeper/debug" DBG-002 done ""   "另一条历史问题"
mkissue "$T/.keeper/debug" DBG-003 open P2   "待办的体验问题"
OUT="$(run_hook "$T" '继续')"
has "open 计数与 id"      "$OUT" "open 1: DBG-003(P2)"
has "done 只给计数"       "$OUT" "done 2"
hasnt "done 的 id 不进注入体" "$OUT" "DBG-001"
has "指向薄索引"          "$OUT" ".keeper/debug/index.md"
has "强调按需打开单条"    "$OUT" "按需打开单条"

echo "[3] open 排序：P0 最前，无优先级最后"
mkissue "$T/.keeper/debug" DBG-004 open P0 "阻断问题"
mkissue "$T/.keeper/debug" DBG-005 open ""  "没打分的问题"
mkissue "$T/.keeper/debug" DBG-006 open P1 "主流程问题"
OUT="$(run_hook "$T" '继续')"
has "P0→P1→P2→无分 的顺序" "$OUT" "DBG-004(P0) DBG-006(P1) DBG-003(P2) DBG-005"

echo "[4] 未知 status 必须显式告警（v2 回归：曾被 if/elif 链静默丢弃）"
mkissue "$T/.keeper/debug" DBG-007 fixed "" "status 用了枚举外的值"
OUT="$(run_hook "$T" '继续')"
has "读不懂桶把它捞出来" "$OUT" "读不懂 1: DBG-007"
has "说明后果"           "$OUT" "已从队列视图消失"
rm -f "$T/.keeper/debug/issues/DBG-007.md"

echo "[5] frontmatter 损坏的文件同样进读不懂桶，不静默跳过"
printf 'id: DBG-008\n没有 frontmatter 分隔符\n' > "$T/.keeper/debug/issues/DBG-008.md"
OUT="$(run_hook "$T" '继续')"
has "损坏文件被显式列出" "$OUT" "DBG-008"
rm -f "$T/.keeper/debug/issues/DBG-008.md"

echo "[6] bug 特征词 → register-first 提示，并直接给出下一个可用 id"
OUT="$(run_hook "$T" '这个页面点了没反应')"
has "提示先登记"       "$OUT" "不要直接派 subagent 修"
has "给出具体 id"      "$OUT" "DBG-007.md"
has "要求原话逐字"     "$OUT" "逐字照抄"
OUT="$(run_hook "$T" '继续推进')"
hasnt "无特征词时不提示" "$OUT" "不要直接派 subagent 修"

echo "[7] reopen 升级阶梯"
mkissue "$T/.keeper/debug" DBG-009 open P1 "反复修不好的问题"
printf -- '---\nid: DBG-009\nsummary: 反复修不好\nstatus: open\npriority: P1\nreopen_count: 2\n---\n\n正文\n' > "$T/.keeper/debug/issues/DBG-009.md"
OUT="$(run_hook "$T" '继续')"
has "reopen 2 次要升档"  "$OUT" "已 reopen 2 次"
has "给出具体动作"       "$OUT" "强制升档 opus"
rm -f "$T/.keeper/debug/issues/DBG-009.md"

echo "[8] 向上查找：子目录启动能找到队列，但不越过仓库根"
mkdir -p "$T/src/deep/deeper"
OUT="$(run_hook "$T/src/deep/deeper" '继续')"
has "从深层子目录仍找到队列" "$OUT" "open 4"
OUTSIDE="$(newtmpdir)"; : > "$OUTSIDE/.git"; mkdir -p "$OUTSIDE/sub"
OUT="$(run_hook "$OUTSIDE/sub" '继续')"
if [ -z "$OUT" ]; then ok "另一个仓库不会串到本队列（.git 是上界）"
else bad "不应串队列" "空" "$OUT"; fi
rm -rf "$OUTSIDE"

echo
echo "== H1b · index.md（v3 取代 STATUS.md，人机共用同一份）=="

echo "[9] index.md 自动生成，且内容与注入体同源"
run_hook "$T" '继续' > /dev/null
IDX="$T/.keeper/debug/index.md"
if [ -f "$IDX" ]; then ok "index.md 生成"
else bad "index.md 应生成" "文件存在" "缺失"; fi
IDXC="$(cat "$IDX" 2>/dev/null)"
has "open 分组标题"     "$IDXC" "## open 4"
has "done 分组标题"     "$IDXC" "## done 2"
has "open 条目带链接"   "$IDXC" "[DBG-004](issues/DBG-004.md)"
has "done 条目也可点开" "$IDXC" "[DBG-001](issues/DBG-001.md)"
has "标明是派生视图"    "$IDXC" "派生视图"

echo "[10] 幂等：状态没变时不重写（入库后不制造假 diff）"
hasnt "index.md 不含时间戳（年份）" "$IDXC" "2026-"
M1="$(mtime "$IDX")"
sleep 1
run_hook "$T" '继续' > /dev/null
M2="$(mtime "$IDX")"
if [ "$M1" = "$M2" ]; then ok "二次运行不重写文件（mtime 未变）"
else bad "应幂等" "mtime 不变" "$M1 → $M2"; fi

echo "[11] 状态真变了就要刷新"
mkissue "$T/.keeper/debug" DBG-010 open P0 "新报的阻断问题"
run_hook "$T" '继续' > /dev/null
IDXC2="$(cat "$IDX")"
has "新 issue 进入索引" "$IDXC2" "DBG-010"
rm -rf "$T"

echo "[12] fixer 的 DBG-* worktree 里只读不写 index.md（并行 fixer 不互相冲突）"
# 判据是「路径含 DBG-\d+ 且是 linked worktree」——本用例的 worktree 目录名带
# DBG-001，命中跳过条件。不带 id 的交付级 worktree 见 [13]。
T="$(newtmpdir)"
git -C "$T" init -q 2>/dev/null
git -C "$T" config user.email t@t.t; git -C "$T" config user.name t
mkissue "$T/.keeper/debug" DBG-001 open P1 "主工作区里的问题"
git -C "$T" add -A >/dev/null 2>&1
git -C "$T" commit -qm init >/dev/null 2>&1
run_hook "$T" '继续' > /dev/null
if [ -f "$T/.keeper/debug/index.md" ]; then ok "主工作区生成 index.md"
else bad "主工作区应生成" "存在" "缺失"; fi
WT="$T/../$(basename "$T")-wt-DBG-001"
git -C "$T" worktree add -q "$WT" -b fix/DBG-001 >/dev/null 2>&1
if [ -d "$WT" ]; then
  rm -f "$WT/.keeper/debug/index.md"
  OUT="$(run_hook "$WT" '继续')"
  has "worktree 里仍注入队列快照" "$OUT" "open 1"
  if [ ! -f "$WT/.keeper/debug/index.md" ]; then ok "worktree 里不写 index.md"
  else bad "worktree 不应写 index.md" "文件不存在" "被创建了"; fi
  has "在飞标记由 worktree 路径派生" "$OUT" "DBG-001(P1)⚙在飞"
  git -C "$T" worktree remove --force "$WT" >/dev/null 2>&1
else
  echo "  (跳过 worktree 用例：git worktree add 失败)"
fi
rm -rf "$T"

echo "[13] 交付级 worktree（路径不带 DBG-id）必须照常重算 index.md"
T="$(newtmpdir)"
git -C "$T" init -q 2>/dev/null
git -C "$T" config user.email t@t.t; git -C "$T" config user.name t
mkissue "$T/.keeper/debug" DBG-001 open P1 "主仓里的问题"
git -C "$T" add -A >/dev/null 2>&1
git -C "$T" commit -qm init >/dev/null 2>&1
DWT="$T/../$(basename "$T")-wt-D-001-feat-job-sequence-model"
git -C "$T" worktree add -q "$DWT" -b delivery/D-001 >/dev/null 2>&1
if [ -d "$DWT" ]; then
  mkissue "$DWT/.keeper/debug" DBG-002 open P0 "交付 worktree 里新报的阻断问题"
  rm -f "$DWT/.keeper/debug/index.md"
  OUT="$(run_hook "$DWT" '继续')"
  if [ -f "$DWT/.keeper/debug/index.md" ]; then ok "交付 worktree 里重算了 index.md"
  else bad "交付 worktree 应重算 index.md" "文件存在" "缺失（旧判据的缺陷）"; fi
  DIDX="$(cat "$DWT/.keeper/debug/index.md" 2>/dev/null)"
  has "新 issue 进入交付 worktree 的索引" "$DIDX" "DBG-002"
  has "注入体与索引同源（都算出 2 条 open）" "$OUT" "open 2"
  hasnt "该 worktree 不带 DBG-id 故不应被判在飞" "$OUT" "⚙在飞"
  git -C "$T" worktree remove --force "$DWT" >/dev/null 2>&1
else
  echo "  (跳过交付 worktree 用例：git worktree add 失败)"
fi
rm -rf "$T"

echo
echo "== H7 · 截图证据路径守卫（写 issue 文件时拦 image-cache 路径）=="
# 【判据】写入目标从 .keeper/debug/issues.yaml（v2）变成 .keeper/debug/issues/<DBG-id>.md（v3）；
# 检出方式是行级扫描，豁免同行标注 origin_path 的留档。
EVD="$HOOK_DIR/pre-tool-use-debug-evidence.sh"
run_evd() {   # $1=tool_name $2=file_path $3=输入字段名 $4=值 $5=session_id
  /usr/bin/python3 -c '
import json,sys
tn,fp,key,val,sid = sys.argv[1:6]
print(json.dumps({"tool_name":tn,"tool_input":{"file_path":fp,key:val},"session_id":sid},
                 ensure_ascii=False))
' "$1" "$2" "$3" "$4" "$5" | bash "$EVD"
}
CNT_DIR2="$(/usr/bin/python3 -c 'import tempfile;print(tempfile.gettempdir())')"
# 前缀 tk-（task-keeper）与 radnove-core 的 rn- 区分，见 hook_counter.py 模块头注释
find "$CNT_DIR2" -maxdepth 1 -name 'tk-evidence-EVDTEST*.json' -delete

Q_MD="/repo/.keeper/debug/issues/DBG-001.md"
P_BAD="- \`/Users/me/.claude/image-cache/abc-123/1.png\`"
P_OK="- \`/repo/.keeper/debug/attachments/DBG-001/01-header.png\`"

echo "[25] 范围极窄：非 issue 文件的写入一律零成本放行"
OUT="$(run_evd Write /repo/src/Foo.java content "$P_BAD" EVDTEST1)"
if [ -z "$OUT" ]; then ok "写源码文件不介入（即使内容含 image-cache 字样）"
else bad "非队列文件应放行" "空" "$OUT"; fi
OUT="$(run_evd Write /repo/docs/note.md content "$P_BAD" EVDTEST1)"
if [ -z "$OUT" ]; then ok "写其他 md 不介入"
else bad "非队列文件应放行" "空" "$OUT"; fi
OUT="$(run_evd Write /repo/.keeper/debug/index.md content "$P_BAD" EVDTEST1)"
if [ -z "$OUT" ]; then ok "写 index.md 不介入（它是派生物，不承载证据）"
else bad "index.md 应放行" "空" "$OUT"; fi

echo "[26] 判据：issue 文件里的 image-cache 路径 → deny，并给出两条可达出路"
OUT="$(run_evd Write "$Q_MD" content "$P_BAD" EVDTEST2)"
has "返回 deny 而非 ask" "$OUT" '"permissionDecision": "deny"'
has "指出会 404"         "$OUT" "404"
has "出路1：cp 到 attachments" "$OUT" "attachments"
has "出路2：不写路径只转录"    "$OUT" "不要写任何图片路径"
has "提示必须回读验证"   "$OUT" "回读验证"

echo "[27] 合规写法与出路二都必须放行（判据存在可达的通过态 · DBG-007 教训）"
OUT="$(run_evd Write "$Q_MD" content "$P_OK" EVDTEST3)"
if [ -z "$OUT" ]; then ok "attachments 下的副本路径放行"
else bad "合规路径应放行" "空" "$OUT"; fi
OUT="$(run_evd Write "$Q_MD" content "原图未落盘，原因：源文件已被清理" EVDTEST3)"
if [ -z "$OUT" ]; then ok "只写文字说明放行（出路二可达）"
else bad "出路二应放行" "空" "$OUT"; fi

echo "[28] 边界：只看新内容，正在**删除** image-cache 路径的 Edit 不该被拦"
OUT="$(run_evd Edit "$Q_MD" new_string "$P_BAD" EVDTEST4)"
has "new_string 含 image-cache → deny" "$OUT" '"permissionDecision": "deny"'
OUT="$(run_evd Edit "$Q_MD" old_string "$P_BAD" EVDTEST4)"
if [ -z "$OUT" ]; then ok "old_string 含 image-cache 不拦（这次修改正是在删掉它）"
else bad "old_string 不应触发" "空" "$OUT"; fi

echo "[29] 熔断：撞 DENY_LIMIT 次后降级放行并附警告，不无限 deny"
for i in 1 2 3; do
  OUT="$(run_evd Write "$Q_MD" content "$P_BAD" EVDTEST5)"
  has "第 $i 次仍 deny" "$OUT" '"permissionDecision": "deny"'
done
OUT="$(run_evd Write "$Q_MD" content "$P_BAD" EVDTEST5)"
hasnt "第 4 次不再 deny" "$OUT" '"permissionDecision": "deny"'
has   "降级时说明达到上限" "$OUT" "达到上限"
has   "降级时仍点出风险"   "$OUT" "404"

echo "[30] 关键豁免：origin_path 留档 image-cache 原路径是**规定动作**，不得被拦"
COMPLIANT='## 证据

- `/repo/.keeper/debug/attachments/DBG-001/01-x.png`
  - origin_path：/Users/me/.claude/image-cache/abc-123/1.png
  - 转录：表头被合并成一列'
OUT="$(run_evd Write "$Q_MD" content "$COMPLIANT" EVDTEST6)"
if [ -z "$OUT" ]; then ok "规定写法放行（正文路径合规 + origin_path 留档 image-cache）"
else bad "规定写法应放行" "空" "$OUT"; fi
OUT="$(run_evd Write "$Q_MD" content "  - origin_path：/Users/me/.claude/image-cache/abc/1.png" EVDTEST6)"
if [ -z "$OUT" ]; then ok "仅 origin_path 含 image-cache 不触发"
else bad "origin_path 不应触发" "空" "$OUT"; fi
OUT="$(run_evd Write "$Q_MD" content "表格里的路径 | ~/.claude/image-cache/abc/1.png |" EVDTEST6)"
has "表格等自由格式也能拦住（v2 的 path: 正则会漏）" "$OUT" '"permissionDecision": "deny"'

echo
echo "== H8 · wt_supply.py（worktree submodule 供给：跨对象库共享 / gitlink 精确读取 / 幂等）=="
# 落点固定 <source>/.keeper/worktrees/<id>/，与 .keeper/debug/ 的队列数据平级
# （不在 debug/ 目录内部）——见 wt_supply.py cmd_init docstring。

WT_SUPPLY="$HOOK_DIR/../skills/tk-worktree/scripts/wt_supply.py"
run_supply() { /usr/bin/python3 "$WT_SUPPLY" "$@"; }

# 造一个 submodule 源仓（供 `git submodule add` 用）。$1=路径
mksmrepo() {
  git init -q -b master "$1"
  git -C "$1" config user.email t@t.t; git -C "$1" config user.name t
  echo "v1" > "$1/a.txt"
  git -C "$1" add -A >/dev/null 2>&1
  git -C "$1" commit -qm "init" >/dev/null 2>&1
}

# 造一个带一个 submodule 的主仓（固定 -b master）。
# $1=主仓路径 $2=submodule 源路径 $3=submodule 相对路径
# 【为什么 .gitignore 忽略 .keeper/】init 的落点固定是 `<source>/.keeper/worktrees/<id>/`，
# 落在源仓内部。不忽略的话它会以 `?? .keeper/` 出现在 `git status --porcelain` 里，
# 让源仓变 dirty，撞上 merge-back 的「源 worktree 父仓不干净」前置校验。
mkmainwithsm() {
  git init -q -b master "$1"
  git -C "$1" config user.email t@t.t; git -C "$1" config user.name t
  printf '.keeper/\n' > "$1/.gitignore"
  git -C "$1" -c protocol.file.allow=always submodule add -q "$2" "$3" >/dev/null 2>&1
  git -C "$1" add -A >/dev/null 2>&1
  git -C "$1" commit -qm "add submodule $3" >/dev/null 2>&1
}

echo "[31] 无 submodule 的仓：init 成功建出落点，supply 明确报无需供给（exit 0）"
T="$(newtmpdir)"
git init -q -b master "$T" >/dev/null 2>&1
git -C "$T" config user.email t@t.t; git -C "$T" config user.name t
printf '.keeper/\n' > "$T/.gitignore"
echo hi > "$T/f.txt"; git -C "$T" add -A >/dev/null 2>&1; git -C "$T" commit -qm init >/dev/null 2>&1
OUT="$(run_supply init --source "$T" --id WT31 2>&1)"; RC=$?
if [ "$RC" -eq 0 ]; then ok "无 submodule 仓 init exit 0"
else bad "应 exit 0" "0" "$RC"; fi
WT="$T/.keeper/worktrees/WT31"
if [ -d "$WT" ]; then ok "父仓工作区落在 <source>/.keeper/worktrees/<id>/（落点固定，不接受路径参数）"
else bad "落点目录应存在" "$WT" "缺失"; fi
OUT2="$(run_supply supply --worktree "$WT" 2>&1)"; RC2=$?
if [ "$RC2" -eq 0 ]; then ok "supply 优雅跳过 exit 0"
else bad "应 exit 0" "0" "$RC2"; fi
has "明确输出跳过信息" "$OUT2" "没有 .gitmodules，无 submodule 需要供给"
rm -rf "$T" 2>/dev/null

echo "[32] init 供给后 <worktree>/<sm>/.git 是文件，gitdir 指向源仓共享对象库"
T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
mkmainwithsm "$T" "$SM_SRC" "libs/sm"
run_supply init --source "$T" --id WT32 >/dev/null 2>&1
WT="$T/.keeper/worktrees/WT32"
DOTGIT="$WT/libs/sm/.git"
if [ -f "$DOTGIT" ]; then ok "子模块 .git 是文件（是目录就说明建成了独立对象库）"
else bad "应为文件" "文件" "$([ -d "$DOTGIT" ] && echo 目录 || echo 缺失)"; fi
CONTENT="$(cat "$DOTGIT" 2>/dev/null)"
has ".git 文件内容含 gitdir:" "$CONTENT" "gitdir:"
SRC_GITDIR="$(git -C "$T" rev-parse --path-format=absolute --git-common-dir)"
has "gitdir 指向源仓 .git/modules/<sm>/worktrees/（对象库共享）" "$CONTENT" "$SRC_GITDIR/modules/libs/sm/worktrees/"
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[33] gitlink 取自**源侧**父仓 index，不是主 checkout 当前分支（回归重点）"
T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
mkmainwithsm "$T" "$SM_SRC" "libs/sm"
SHA1="$(git -C "$T" rev-parse ":libs/sm")"        # 主 checkout(master) 记的 gitlink
run_supply init --source "$T" --id SRC33 >/dev/null 2>&1
SRC="$T/.keeper/worktrees/SRC33"                    # 这一份本身是 linked worktree，当"源"用
echo "v2" > "$SRC/libs/sm/a.txt"
git -C "$SRC/libs/sm" add -A >/dev/null 2>&1
git -C "$SRC/libs/sm" commit -qm "v2" >/dev/null 2>&1
SHA2="$(git -C "$SRC/libs/sm" rev-parse HEAD)"
git -C "$SRC" add libs/sm >/dev/null 2>&1
git -C "$SRC" commit -qm "bump libs/sm to v2" >/dev/null 2>&1
if [ "$(git -C "$SRC" rev-parse ":libs/sm")" = "$SHA2" ] && [ "$SHA1" != "$SHA2" ]; then
  ok "前置构造成立：源侧记 v2 的 gitlink，主 checkout 仍记 v1"
else
  bad "前置构造应让两侧 gitlink 不同" "src=$SHA2 / main=$SHA1" "src=$(git -C "$SRC" rev-parse ":libs/sm")"
fi
run_supply init --source "$SRC" --id WT33 >/dev/null 2>&1
GOT="$(git -C "$SRC/.keeper/worktrees/WT33/libs/sm" rev-parse HEAD 2>/dev/null)"
if [ "$GOT" = "$SHA2" ] && [ "$GOT" != "$SHA1" ]; then
  ok "供给出的子模块 HEAD 等于源侧记录的 gitlink，不是主 checkout(master) 的旧值"
else
  bad "应等于源侧 gitlink ${SHA2}（主 checkout 记的是 ${SHA1}）" "$SHA2" "$GOT"
fi
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[34] 幂等：init 连跑两次，第二次跳过父仓创建、submodule 层报已 ok，exit 0"
T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
mkmainwithsm "$T" "$SM_SRC" "libs/sm"
run_supply init --source "$T" --id WT34 >/dev/null 2>&1
OUT2="$(run_supply init --source "$T" --id WT34 2>&1)"; RC2=$?
if [ "$RC2" -eq 0 ]; then ok "第二次 init exit 0（不重建、不报错）"
else bad "应 exit 0" "0" "$RC2"; fi
has "第二次跳过父仓工作区创建" "$OUT2" "父仓工作区已存在且分支一致"
has "submodule 层报已 ok 跳过" "$OUT2" "已 ok，跳过"
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[35] status 区分 empty(未供给)与 ok(已供给)，exit code 分别为 2 与 0"
T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
mkmainwithsm "$T" "$SM_SRC" "libs/sm"
WT="$T/.keeper/worktrees/WT35"
git -C "$T" worktree add -q "$WT" -b b35 >/dev/null 2>&1
OUT="$(run_supply status --worktree "$WT" --source "$T" 2>&1)"; RC=$?
has "未供给时状态为 empty" "$OUT" "empty"
if [ "$RC" -eq 2 ]; then ok "有非 ok 层时 status exit 2"
else bad "应 exit 2" "2" "$RC"; fi
run_supply supply --worktree "$WT" --source "$T" >/dev/null 2>&1
OUT="$(run_supply status --worktree "$WT" 2>&1)"; RC=$?    # 刻意不给 --source
has "供给后状态为 ok" "$OUT" "ok"
if [ "$RC" -eq 0 ]; then ok "全 ok 时 status exit 0，且 --source 可省（supply 已把源记进 gitdir）"
else bad "应 exit 0" "0" "$RC"; fi
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[36] supply 缺 --source 且 gitdir 无源记录 → fail-loud，不猜、不默认用主 checkout"
T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
mkmainwithsm "$T" "$SM_SRC" "libs/sm"
WT="$T/.keeper/worktrees/WT36"
git -C "$T" worktree add -q "$WT" -b b36 >/dev/null 2>&1
OUT="$(run_supply supply --worktree "$WT" 2>&1)"; RC=$?
if [ "$RC" -ne 0 ]; then ok "缺源信息时非零退出"
else bad "应非零退出" "非 0" "$RC"; fi
has "报错点明缺的是源记录" "$OUT" "wt-supply-source"
has "给出可操作的下一步" "$OUT" "建议下一步"
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[37] explain-scope 只读反推 submodule 集合，且**不**裁剪 init 的全量供给"
T="$(newtmpdir)"; SM_SRC1="$(newtmpdir)"; mksmrepo "$SM_SRC1"; SM_SRC2="$(newtmpdir)"; mksmrepo "$SM_SRC2"
git init -q -b master "$T" >/dev/null 2>&1
git -C "$T" config user.email t@t.t; git -C "$T" config user.name t
printf '.keeper/\n' > "$T/.gitignore"
git -C "$T" -c protocol.file.allow=always submodule add -q "$SM_SRC1" "libs/sm1" >/dev/null 2>&1
git -C "$T" -c protocol.file.allow=always submodule add -q "$SM_SRC2" "libs/sm2" >/dev/null 2>&1
git -C "$T" add -A >/dev/null 2>&1
git -C "$T" commit -qm "add two submodules" >/dev/null 2>&1
run_supply init --source "$T" --id WT37 >/dev/null 2>&1
WT="$T/.keeper/worktrees/WT37"
mkdir -p "$T/.keeper/debug/issues"
printf -- '---\nid: DBG-100\nsummary: 只涉及 sm1\nstatus: open\n---\n\n# DBG-100\n\n出错文件是 `libs/sm1/a.txt:3`\n' > "$T/.keeper/debug/issues/DBG-100.md"
OUT="$(run_supply explain-scope --worktree "$WT" --from-triage "$T/.keeper/debug/issues/DBG-100.md" 2>&1)"; RC=$?
if [ "$RC" -eq 0 ]; then ok "explain-scope exit 0"
else bad "应 exit 0" "0" "$RC"; fi
has "反推命中 libs/sm1" "$OUT" "libs/sm1"
hasnt "未把无关的 libs/sm2 算进命中集合" "$OUT" "libs/sm2"
if [ -f "$WT/libs/sm1/.git" ] && [ -f "$WT/libs/sm2/.git" ]; then
  ok "两个 submodule 都已供给（explain-scope 的结果不裁剪供给范围）"
else
  bad "两层都应已供给" "sm1 与 sm2 的 .git 都是文件" \
      "sm1=$([ -f "$WT/libs/sm1/.git" ] && echo 有 || echo 无) sm2=$([ -f "$WT/libs/sm2/.git" ] && echo 有 || echo 无)"
fi
rm -rf "$T" "$SM_SRC1" "$SM_SRC2" 2>/dev/null

echo "[38] remove 深度优先清干净，且不污染源侧 submodule 初始化状态（前缀不得从空格变 -）"
T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
mkmainwithsm "$T" "$SM_SRC" "libs/sm"
run_supply init --source "$T" --id WT38 >/dev/null 2>&1
WT="$T/.keeper/worktrees/WT38"
BEFORE="$(git -C "$T" submodule status libs/sm)"
OUT="$(run_supply remove --worktree "$WT" --yes 2>&1)"; RC=$?
if [ "$RC" -eq 0 ]; then ok "remove --yes 正常退出"
else bad "应 exit 0" "0" "$RC"; fi
if [ ! -e "$WT" ]; then ok "目标 worktree 整体清除（缺省连父仓工作区一起删）"
else bad "目标目录应已删除" "不存在" "仍存在"; fi
AFTER="$(git -C "$T" submodule status libs/sm)"
if [ "${BEFORE:0:1}" = "${AFTER:0:1}" ]; then
  ok "源侧 submodule status 前缀未被污染（证明没跑 submodule deinit -f）"
else
  bad "源侧前缀不应变化" "${BEFORE:0:1}" "${AFTER:0:1}"
fi
CLEAN="$(git -C "$T" status --short 2>&1)"
if [ -z "$CLEAN" ]; then ok "源 worktree 清理后仍干净"
else bad "源 worktree 应干净" "空" "$CLEAN"; fi
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[39] merge-back 默认 dry-run 零副作用（源侧 submodule HEAD 未变、源仓 index 未 stage）"
T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
mkmainwithsm "$T" "$SM_SRC" "libs/sm"
run_supply init --source "$T" --id WT39 >/dev/null 2>&1
WT="$T/.keeper/worktrees/WT39"
echo "from-wt" > "$WT/libs/sm/b.txt"
git -C "$WT/libs/sm" add -A >/dev/null 2>&1
git -C "$WT/libs/sm" commit -qm "wt side change" >/dev/null 2>&1
git -C "$WT" add libs/sm >/dev/null 2>&1
git -C "$WT" commit -qm "bump gitlink" >/dev/null 2>&1
SRC_SM_HEAD_BEFORE="$(git -C "$T/libs/sm" rev-parse HEAD)"
OUT="$(run_supply merge-back --worktree "$WT" 2>&1)"; RC=$?
if [ "$RC" -eq 0 ]; then ok "前置校验通过、dry-run exit 0"
else bad "应 exit 0（前置校验应通过）" "0" "$RC"; fi
has "输出标明 dry-run" "$OUT" "dry-run"
has "逐层打印旧 gitlink 供 Human 核对（gitlink 红线要求的形态）" "$OUT" "旧 gitlink"
SRC_SM_HEAD_AFTER="$(git -C "$T/libs/sm" rev-parse HEAD)"
if [ "$SRC_SM_HEAD_BEFORE" = "$SRC_SM_HEAD_AFTER" ]; then ok "源侧 submodule HEAD 未变"
else bad "HEAD 不应变化" "$SRC_SM_HEAD_BEFORE" "$SRC_SM_HEAD_AFTER"; fi
STAGED="$(git -C "$T" diff --cached --name-only)"
if [ -z "$STAGED" ]; then ok "源仓 index 未 stage 任何东西"
else bad "index 应为空" "空" "$STAGED"; fi
rm -rf "$T" "$SM_SRC" 2>/dev/null

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

echo "[40] -C 落在 fixer worktree 里的 git push 一律 deny"
pushg_deny "git -C <fixer worktree> push"        'git -C /repo/.keeper/worktrees/DBG-017 push origin fix/DBG-017'
pushg_deny "--git-dir 落在 fixer worktree 里"     'git --git-dir=/repo/.keeper/worktrees/DBG-020/.git push'
pushg_deny "无 -C，靠 cwd 落在 fixer worktree"    'git push origin fix/DBG-021' '/repo/.keeper/worktrees/DBG-021'

echo "[41] -C 落在非 fixer worktree（主仓 / 交付 worktree）一律放行"
pushg_pass "-C 落在交付 worktree（.sdlc/worktrees）" 'git -C /repo/.sdlc/worktrees/D-001-feat push origin D-001-feat'
pushg_pass "-C 落在主仓根"                          'git -C /repo push origin master'
pushg_pass "无 -C 无 cwd，抠不到路径信息"           'git push origin master'

echo "[42] 非 push 命令、或压根不是 git 命令，不误伤"
pushg_pass "git status 不误伤"                     'git -C /repo/.keeper/worktrees/DBG-017 status'
pushg_pass "非 git 文本含 push 字样不误伤"          'echo please push this button'
pushg_pass "非 Bash 无 command 字段"                ''

echo "== H10 · debug worktree 强制删除守卫（fixer 未提交产物防误删，ask 而非 deny）=="
DESTROYG="$HOOK_DIR/pre-tool-use-debug-worktree-destroy.sh"
run_destroyg() {   # $1=command  $2=cwd（可省略）
  /usr/bin/python3 -c '
import json,sys
ev = {"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":sys.argv[1]}}
if len(sys.argv) > 2 and sys.argv[2]:
    ev["cwd"] = sys.argv[2]
print(json.dumps(ev))
' "$1" "${2:-}" | bash "$DESTROYG"
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

echo "[43] 三种强制删除形态命中 DBG worktree 路径 → ask"
destroyg_ask "git worktree remove --force"        'git worktree remove --force /repo/.keeper/worktrees/DBG-017'
destroyg_ask "git -C 带 -f 的 worktree remove"    'git -C /repo worktree remove -f /repo/.keeper/worktrees/DBG-017'
destroyg_ask "rm -rf 裸位置参数路径"              'rm -rf /repo/.keeper/worktrees/DBG-020'
destroyg_ask "rm -fr 合并短选项换序"              'rm -fr /repo/.keeper/worktrees/DBG-020/sm'
destroyg_ask "无路径字面量，靠 cwd 兜底"          'rm -rf sm' '/repo/.keeper/worktrees/DBG-021'
destroyg_ask "git clean -fdx，靠 cwd 兜底"        'git clean -fdx' '/repo/.keeper/worktrees/DBG-022'

echo "[44] 路径落在 .keeper/worktrees/，但命令本身没构成强制删除形态 → 放行"
destroyg_pass "worktree remove 不带 --force"     'git worktree remove /repo/.keeper/worktrees/DBG-017'
destroyg_pass "rm 不带递归标志，删单个文件"      'rm /repo/.keeper/worktrees/DBG-017/a.txt'
destroyg_pass "非删除命令不误伤"                 'git -C /repo/.keeper/worktrees/DBG-017 status'
destroyg_pass "git clean dry-run 没有 -f"         'git clean -n'

echo "[45] 命令构成强制删除形态，但路径不在 .keeper/worktrees/ 管辖范围内 → 放行"
destroyg_pass "交付 worktree 不是本守卫管辖范围" 'rm -rf /repo/.sdlc/worktrees/D-001-feat'
destroyg_pass "非 Bash 无 command 字段"           ''

echo
echo "== H11 · 按交付批次归档（archive_done.py + next_id 归档感知 + index.md 统计）=="
ARCH="$HOOK_DIR/../skills/tk-debug/scripts/archive_done.py"

# 造一个最小的 git 跟踪的假 .keeper/debug/：3 条 done（其中 DBG-003 故意留着 worktree
# 目录，worktree 落点与 debug/ 平级即 .keeper/worktrees/）+ 1 条 open；DBG-002 带
# receipts 与 attachments，用来验证成组搬迁。
mkarchfixture() {
  local d; d="$(newtmpdir)"
  mkdir -p "$d/.keeper/debug/issues" "$d/.keeper/debug/receipts" \
           "$d/.keeper/debug/attachments/DBG-002" "$d/.keeper/worktrees/DBG-003"
  git -C "$d" init -q -b main
  for spec in "DBG-001 done" "DBG-002 done" "DBG-003 done" "DBG-004 open"; do
    set -- $spec
    printf -- '---\nid: %s\nsummary: %s 摘要\nstatus: %s\npriority: P1\ndifficulty: easy\ntype: bug\nreported_at: 2026-07-30\nreopen_count: 0\n---\n\n# %s\n' \
      "$1" "$1" "$2" "$1" > "$d/.keeper/debug/issues/$1.md"
  done
  echo "回执" > "$d/.keeper/debug/receipts/DBG-002.md"
  echo "png" > "$d/.keeper/debug/attachments/DBG-002/01.png"
  # worktrees/ 在真实项目里被 .gitignore 排除，这里用 -f 强制纳入不影响判定
  git -C "$d" add -A -f .keeper >/dev/null 2>&1
  git -C "$d" -c user.email=t@t.com -c user.name=t commit -q -m "fixture"
  echo "$d"
}
py_nextid() {   # $1=queue_dir(.keeper/debug) —— 打印 DEBUG spec 下的 next_id()
  /usr/bin/python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import queue_files as f; print(f.next_id(sys.argv[2], f.DEBUG))' \
    "$LIBDIR" "$1"
}

echo "[46] dry-run 零副作用：列出计划但不动任何文件，next_id 不变"
D="$(mkarchfixture)"
before="$(py_nextid "$D/.keeper/debug")"
out="$(/usr/bin/python3 "$ARCH" --queue-dir "$D/.keeper/debug" --batch D-999-test 2>&1)"
has "dry-run 列出 DBG-001 的搬迁计划" "$out" "DBG-001"
has "dry-run 明确标注未移动"          "$out" "未移动任何文件"
if [ -z "$(git -C "$D" status --short)" ]; then ok "dry-run 后工作区仍干净"
else bad "dry-run 后工作区仍干净" "空" "$(git -C "$D" status --short)"; fi
has "dry-run 后 next_id 不变（${before}）" "$(py_nextid "$D/.keeper/debug")" "$before"

echo "[47] --apply 成组搬迁 issue + receipts + attachments，open 与带 worktree 的 done 不动"
out="$(/usr/bin/python3 "$ARCH" --queue-dir "$D/.keeper/debug" --batch D-999-test --apply 2>&1)"
has "汇总报成功 2 条" "$out" "成功 2 条"
for f in issues/DBG-001.md issues/DBG-002.md receipts/DBG-002.md attachments/DBG-002/01.png; do
  if [ -e "$D/.keeper/debug/archive/D-999-test/$f" ]; then ok "已归档 archive/D-999-test/$f"
  else bad "已归档 archive/D-999-test/$f" "存在" "缺失"; fi
done
if [ -f "$D/.keeper/debug/issues/DBG-004.md" ]; then ok "open 条目 DBG-004 留在 issues/"
else bad "open 条目 DBG-004 留在 issues/" "存在" "被误搬"; fi
if [ -f "$D/.keeper/debug/issues/DBG-003.md" ]; then ok "done 但 worktree 未清的 DBG-003 未被搬走"
else bad "done 但 worktree 未清的 DBG-003 未被搬走" "存在" "被误搬"; fi
has "DBG-003 给出跳过警告" "$out" "DBG-003"

echo "[48] 归档不得造成 id 复用（最关键的不变量）+ index.md 只统计不逐条 + 幂等"
has "归档后 next_id 未回退（仍为 ${before}）" "$(py_nextid "$D/.keeper/debug")" "$before"
idx="$(/usr/bin/python3 -c '
import sys; sys.path.insert(0, sys.argv[1]); import queue_files as f
a = f.render_index(sys.argv[2], f.DEBUG); b = f.render_index(sys.argv[2], f.DEBUG)
print("IDEMPOTENT" if a == b else "DIFFERS")
print(a)' "$LIBDIR" "$D/.keeper/debug")"
has "render_index 两次调用逐字节相同" "$idx" "IDEMPOTENT"
has "index.md 含 archived 计数节"     "$idx" "## archived 2"
hasnt "archived 节不逐条列归档 id"     "$idx" "archive/D-999-test/issues/DBG-001.md"
out="$(/usr/bin/python3 "$ARCH" --queue-dir "$D/.keeper/debug" --batch D-999-test --apply 2>&1)"
has "重跑幂等（已归档的不再重复搬）" "$out" "0 条"
rm -rf "$D" 2>/dev/null

echo
echo "== H12 · merge-back 源侧判据收窄（主会话无关 WIP 不该阻断回流）=="

echo "[49] dirty_lines 切片精确：porcelain 首行的前导空格不得被 .strip() 吃掉"
T="$(newtmpdir)"
git init -q -b master "$T" >/dev/null 2>&1
git -C "$T" config user.email t@t.t; git -C "$T" config user.name t
echo v1 > "$T/zz.txt"; git -C "$T" add -A >/dev/null 2>&1
git -C "$T" commit -qm init >/dev/null 2>&1
echo v2 > "$T/zz.txt"     # 唯一一项改动，未 staged ⇒ porcelain 首行就是 " M zz.txt"
DP="$(/usr/bin/python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import wt_git as g; print(sorted(g.dirty_paths(sys.argv[2])))' \
  "$HOOK_DIR/../skills/tk-worktree/scripts" "$T" 2>&1)"
has "dirty_paths 取到完整路径 zz.txt（错位会得到 z.txt）" "$DP" "'zz.txt'"
rm -rf "$T" 2>/dev/null

# 造一份「fixer 已在 submodule 层提交、目标父仓已回写 gitlink」的可回流现场（同 [39]）。
# 结果放全局 T / SM_SRC / WT，调用方自己清理。
mkmbfixture() {
  T="$(newtmpdir)"; SM_SRC="$(newtmpdir)"; mksmrepo "$SM_SRC"
  mkmainwithsm "$T" "$SM_SRC" "libs/sm"
  run_supply init --source "$T" --id "$1" >/dev/null 2>&1
  WT="$T/.keeper/worktrees/$1"
  echo "from-wt" > "$WT/libs/sm/b.txt"
  git -C "$WT/libs/sm" add -A >/dev/null 2>&1
  git -C "$WT/libs/sm" commit -qm "wt side change" >/dev/null 2>&1
  git -C "$WT" add libs/sm >/dev/null 2>&1
  git -C "$WT" commit -qm "bump gitlink" >/dev/null 2>&1
}

echo "[50] 源侧无关未跟踪文件不再阻断（死锁修复本体：放行并降级为提示）"
mkmbfixture WT50
echo "主会话手上的活" > "$T/unrelated.md"   # 未跟踪、未 staged、与 libs/sm 无交集
OUT="$(run_supply merge-back --worktree "$WT" 2>&1)"; RC=$?
if [ "$RC" -eq 0 ]; then ok "无关 WIP 挂着也能过前置校验（exit 0）"
else bad "应 exit 0（这正是死锁场景）" "0" "$RC"; fi
has "无关改动降级为提示而不是 blocker" "$OUT" "提示"
has "提示里点名了具体路径"             "$OUT" "unrelated.md"
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[51] 源侧 index 有 staged 内容仍必须阻断（回写 gitlink 的 commit 不带 pathspec，会卷走它）"
mkmbfixture WT51
echo "主会话手上的活" > "$T/unrelated.md"
git -C "$T" add unrelated.md >/dev/null 2>&1     # 同一个文件，只多了一步 git add
OUT="$(run_supply merge-back --worktree "$WT" 2>&1)"; RC=$?
if [ "$RC" -eq 2 ]; then ok "staged 内容阻断（exit 2）"
else bad "应 exit 2" "2" "$RC"; fi
has "报清是 staged 惹的祸、不是笼统的不干净" "$OUT" "staged"
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo "[52] 源侧未 staged 改动与本次合并路径相交时仍必须阻断（git merge 会覆盖它）"
mkmbfixture WT52
echo "源侧也在改同一个子模块" > "$T/libs/sm/a.txt"   # 使源父仓出现 ` M libs/sm`，与合并路径相交
OUT="$(run_supply merge-back --worktree "$WT" 2>&1)"; RC=$?
if [ "$RC" -eq 2 ]; then ok "相交的未 staged 改动阻断（exit 2）"
else bad "应 exit 2" "2" "$RC"; fi
has "报清阻断理由是与合并路径相交" "$OUT" "相交"
rm -rf "$T" "$SM_SRC" 2>/dev/null

echo
echo "== H14 · Chore 队列快照（task-keeper 新增，无 radnove-core 对应实现）=="

echo "[57] 零成本保证：没有 .keeper/chore/items/ 的项目 stdout 必须全空"
T="$(newtmpdir)"; : > "$T/.git"
OUT="$(run_chore "$T" '记一下这笔支出')"
if [ -z "$OUT" ]; then ok "无 chore 队列项目零输出（含杂务特征词也不注入）"
else bad "无队列应零输出" "空" "$OUT"; fi

echo "[58] 造一条 open 条目后，注入体含 id + kind，且字节数预算 ≤900（H14 硬指标）"
mkchore "$T/.keeper/chore" CHR-001 open ledger "记一笔支出台账"
OUT="$(run_chore "$T" '继续')"
has "open 计数、id 与类别" "$OUT" "open 1: CHR-001(ledger)"
BYTES="$(printf '%s' "$OUT" | wc -c | tr -d ' ')"
if [ "$BYTES" -le 900 ]; then ok "chore 快照输出 ${BYTES} 字节 ≤900（低频背景事务不该吃主会话注意力预算）"
else bad "chore 快照输出应 ≤900 字节" "<=900" "$BYTES"; fi
rm -rf "$T"

echo
echo "== H15 · 决策信箱（decision_inbox：pending/blocking 计数 + debug↔chore 去重注入）=="

echo "[59] pending 计数排除已答复、blocking 计数按 frontmatter 累加；chore 启用时改由它承接摘要"
T="$(newtmpdir)"; : > "$T/.git"
mkdir -p "$T/.keeper/decisions/answers"
printf -- '---\nblocking: true\n---\n\n需要拍板 A\n' > "$T/.keeper/decisions/2026-07-30-1200-debug-keeper.md"
printf -- '---\nblocking: false\n---\n\n需要拍板 B\n' > "$T/.keeper/decisions/2026-07-30-1300-debug-keeper.md"
printf -- '---\nblocking: true\n---\n\n已经回复过的\n' > "$T/.keeper/decisions/2026-07-30-1100-debug-keeper.md"
printf -- '答复：已确认\n' > "$T/.keeper/decisions/answers/2026-07-30-1100-debug-keeper.md"
CNT="$(/usr/bin/python3 -c '
import sys; sys.path.insert(0, sys.argv[1])
import decision_inbox as d
items = d.pending_decisions(sys.argv[2])
print(len(items))
print(sum(1 for _n, b in items if b))
' "$LIBDIR" "$T/.keeper")"
PEND_COUNT="$(printf '%s\n' "$CNT" | sed -n '1p')"
BLOCK_COUNT="$(printf '%s\n' "$CNT" | sed -n '2p')"
if [ "$PEND_COUNT" = "2" ]; then ok "pending 计数=2（已答复的第三条不计入 answers/ 也不算决策文件）"
else bad "pending 应为 2" "2" "$PEND_COUNT"; fi
if [ "$BLOCK_COUNT" = "1" ]; then ok "blocking 计数=1（宽松匹配 frontmatter 布尔真值，缺失/写错按非 blocking 计）"
else bad "blocking 应为 1" "1" "$BLOCK_COUNT"; fi

mkdir -p "$T/.keeper/debug/issues"
mkissue "$T/.keeper/debug" DBG-001 open P1 "占位问题，仅用于触发 debug 快照"
OUT="$(run_hook "$T" '继续')"
has "chore 未启用时由 debug 快照代注待拍板摘要" "$OUT" "待拍板 2 条"
has "摘要点出 blocking 计数"                   "$OUT" "blocking 1"

mkdir -p "$T/.keeper/chore/items"
mkchore "$T/.keeper/chore" CHR-001 open ledger "占位杂务，仅用于触发 chore 快照"
OUT_DEBUG2="$(run_hook "$T" '继续')"
hasnt "chore 队列一旦启用，debug 快照不再重复代注待拍板（去重判据：.keeper/chore/items 目录存在性）" \
  "$OUT_DEBUG2" "待拍板"
OUT_CHORE="$(run_chore "$T" '继续')"
has "chore 快照改为承接待拍板摘要" "$OUT_CHORE" "待拍板 2 条"
rm -rf "$T"

echo
echo "== H16 · 双队列互不串号（debug 与 chore 各自独立的 next_id / 归档不互相影响）=="

echo "[60] 同项目 debug 与 chore 各自独立编号"
T="$(newtmpdir)"
mkissue "$T/.keeper/debug" DBG-003 open P1 "已有的问题"
mkchore "$T/.keeper/chore" CHR-001 open ledger "已有的杂务"
DBG_NEXT="$(/usr/bin/python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import queue_files as f; print(f.next_id(sys.argv[2], f.DEBUG))' "$LIBDIR" "$T/.keeper/debug")"
CHR_NEXT="$(/usr/bin/python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import queue_files as f; print(f.next_id(sys.argv[2], f.CHORE))' "$LIBDIR" "$T/.keeper/chore")"
if [ "$DBG_NEXT" = "DBG-004" ]; then ok "debug next_id = DBG-004"
else bad "应为 DBG-004" "DBG-004" "$DBG_NEXT"; fi
if [ "$CHR_NEXT" = "CHR-002" ]; then ok "chore next_id = CHR-002（不受 debug 编号影响）"
else bad "应为 CHR-002" "CHR-002" "$CHR_NEXT"; fi

echo "[61] debug 队列归档进 archive/ 后，chore 队列编号仍不受影响"
mkissue "$T/.keeper/debug" DBG-004 done P1 "已完成待归档"
/usr/bin/python3 "$ARCH" --queue debug --queue-dir "$T/.keeper/debug" --batch H16-test --apply >/dev/null 2>&1
DBG_NEXT2="$(/usr/bin/python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import queue_files as f; print(f.next_id(sys.argv[2], f.DEBUG))' "$LIBDIR" "$T/.keeper/debug")"
CHR_NEXT2="$(/usr/bin/python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import queue_files as f; print(f.next_id(sys.argv[2], f.CHORE))' "$LIBDIR" "$T/.keeper/chore")"
if [ "$DBG_NEXT2" = "DBG-005" ]; then ok "debug 归档后 next_id 前进到 DBG-005（archive/ 也计入历史，不回收编号）"
else bad "应为 DBG-005" "DBG-005" "$DBG_NEXT2"; fi
if [ "$CHR_NEXT2" = "CHR-002" ]; then ok "chore 队列 next_id 不受 debug 归档动作影响，仍为 CHR-002"
else bad "应仍为 CHR-002" "CHR-002" "$CHR_NEXT2"; fi
rm -rf "$T"

echo
echo "== H17 · archive_done.py --auto 自动归档（done 数量阈值 / 超龄阈值）=="

echo "[62] done ≥ AUTO_DONE_THRESHOLD（10）条即触发，批次名固定 auto-<今日>，next_id 不回收"
T="$(newtmpdir)"
for i in 1 2 3 4 5 6 7 8 9 10; do
  mkissue "$T/.keeper/debug" "DBG-$(printf '%03d' "$i")" done P2 "第 $i 条已完成"
done
before="$(py_nextid "$T/.keeper/debug")"
TODAY_STAMP="$(/usr/bin/python3 -c 'import datetime; print(datetime.date.today().strftime("%Y%m%d"))')"
out="$(/usr/bin/python3 "$ARCH" --queue-dir "$T/.keeper/debug" --auto --apply 2>&1)"
has "达到数量阈值触发" "$out" "触发自动归档"
has "触发理由点明 done 10 条 ≥ 阈值 10" "$out" "done 10 条 ≥ 阈值 10"
has "批次名固定 auto-<今日>" "$out" "auto-$TODAY_STAMP"
for i in 1 2 3 4 5 6 7 8 9 10; do
  f="$T/.keeper/debug/archive/auto-$TODAY_STAMP/issues/DBG-$(printf '%03d' "$i").md"
  if [ ! -f "$f" ]; then bad "DBG-$(printf '%03d' "$i") 应归档进 auto-$TODAY_STAMP" "存在" "缺失：$f"; fi
done
ok "10 条 done 全部归档进 archive/auto-$TODAY_STAMP/"
after="$(py_nextid "$T/.keeper/debug")"
if [ "$after" = "$before" ]; then ok "自动归档不回收 next_id（仍为 ${before}）"
else bad "next_id 不应变化" "$before" "$after"; fi
rm -rf "$T"

echo "[63] done 未达数量阈值（9 条）且都不超龄时不触发，不建 archive/ 目录"
T="$(newtmpdir)"
for i in 1 2 3 4 5 6 7 8 9; do
  mkissue "$T/.keeper/debug" "DBG-$(printf '%03d' "$i")" done P2 "第 $i 条已完成"
done
out="$(/usr/bin/python3 "$ARCH" --queue-dir "$T/.keeper/debug" --auto --apply 2>&1)"
has "未达阈值时明确说明判据" "$out" "未达自动归档阈值"
if [ ! -d "$T/.keeper/debug/archive" ]; then ok "未触发时不创建 archive/ 目录"
else bad "不应创建 archive/ 目录" "不存在" "已创建"; fi
rm -rf "$T"

echo "[64] done 数量不足阈值，但存在 reported_at 超龄（>14 天）条目仍触发"
T="$(newtmpdir)"
OLD_DATE="$(/usr/bin/python3 -c 'import datetime; print((datetime.date.today()-datetime.timedelta(days=15)).isoformat())')"
mkissue "$T/.keeper/debug" DBG-001 done P2 "很久以前修完但一直没归档" "$OLD_DATE"
TODAY_STAMP="$(/usr/bin/python3 -c 'import datetime; print(datetime.date.today().strftime("%Y%m%d"))')"
out="$(/usr/bin/python3 "$ARCH" --queue-dir "$T/.keeper/debug" --auto --apply 2>&1)"
has "超龄触发，报出实际天数与阈值对比" "$out" "距今 15 天 > 阈值 14 天"
if [ -f "$T/.keeper/debug/archive/auto-$TODAY_STAMP/issues/DBG-001.md" ]; then
  ok "超龄条目被归档进 auto-<今日> 批次（批次名不取该条目自己的日期）"
else
  bad "应归档进 auto-$TODAY_STAMP" "存在" "缺失"
fi
rm -rf "$T"

echo
echo "== H18 · SessionStart 主会话路由注入（keeper_routing.py：opt-in 分档 + heredoc-stdin 回归）=="

echo "[65] 项目未启用 .keeper/：只注入一句话介绍，长度 ≤300 字符"
T="$(newtmpdir)"; : > "$T/.git"
OUT="$(run_routing "$T")"
TEXT="$(printf '%s' "$OUT" | /usr/bin/python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])
except Exception:
    print("")
')"
CHARS="$(/usr/bin/python3 -c 'import sys; print(len(sys.argv[1]))' "$TEXT")"
if [ "$CHARS" -le 300 ]; then ok "未启用文案 ${CHARS} 字符 ≤300"
else bad "未启用文案应 ≤300 字符" "<=300" "$CHARS"; fi
has "未启用文案给出两种启用方式" "$TEXT" "mkdir -p .keeper/debug/issues"

echo "[66] 项目已启用 .keeper/debug/issues：注入完整三岔口，长度 ≤2000 字符（硬上限）且含已启用文案"
mkdir -p "$T/.keeper/debug/issues"
mkissue "$T/.keeper/debug" DBG-001 open P1 "占位问题，仅用于触发 routing 已启用分支"
OUT="$(run_routing "$T")"
TEXT="$(printf '%s' "$OUT" | /usr/bin/python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])
except Exception:
    print("")
')"
CHARS="$(/usr/bin/python3 -c 'import sys; print(len(sys.argv[1]))' "$TEXT")"
if [ "$CHARS" -le 2000 ]; then ok "已启用文案 ${CHARS} 字符 ≤2000（硬上限）"
else bad "已启用文案应 ≤2000 字符" "<=2000" "$CHARS"; fi
has "含三岔口分诊文案" "$TEXT" "三岔口分诊"
has "含决策打包主会话侧职责说明" "$TEXT" "决策打包"
rm -rf "$T"

echo
printf '通过 %d / 失败 %d\n' "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1
