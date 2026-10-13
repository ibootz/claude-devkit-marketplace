# H1 · Debug 队列快照（schema v4：一条目一目录，落点 .keeper/<交付id>/debug/）。
# 依赖 harness.sh 的 newtmpdir/mkissue/run_hook/ok/bad/has/hasnt。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】本节结尾故意不清理 $T/$Q（T=造出来的队列所在 worktree 根、
# Q="$T/.keeper/_main/debug"，在 [2] 处赋值），留给下一个文件
# 02-h1b-index.sh 的 [9]-[11] 继续复用同一份现场验证 index.md；这两个文件
# 必须按 01→02 的顺序连续 source，不能拆开或调换顺序。

echo "== H1 · Debug 队列快照（schema v4：一条目一目录，落点 .keeper/<交付id>/debug/）=="

echo "[1] 零成本保证：没有 .keeper/<交付id>/debug/ 的项目 stdout 必须全空"
T="$(newtmpdir)"; : > "$T/.git"
OUT="$(run_hook "$T" '报错了，白屏')"
if [ -z "$OUT" ]; then ok "无队列项目零输出（含 bug 特征词也不注入）"
else bad "无队列应零输出" "空" "$OUT"; fi
# 只有 .keeper/ 根目录、还没建出 <交付id>/debug/ ——2026-08-03 起 opt-in 判据收窄到
# .keeper/ 顶层本身（keeper_paths.find_keeper_root），不再是 <交付id>/debug 这一层：
# find_queue 会自动补建缺失的 debug/（连同 chore/），不再零输出。完整场景矩阵见
# 15-h20-queue-autocreate.sh；这里只保留「已启用 .keeper/ 时不再是零输出」这一条，
# 与上面「.keeper/ 完全不存在才零输出」形成对照，不重复 15 的补建细节断言。
mkdir -p "$T/.keeper"
OUT="$(run_hook "$T" '继续')"
if [ -n "$OUT" ]; then ok "有 .keeper/ 但无 <交付id>/debug/ 视为已启用（自动补建，不再零输出）"
else bad "应有输出（debug/ 应被自动补建）" "非空" "$OUT"; fi
rm -rf "$T"

echo "[2] 分桶：open 列出、done 只给计数"
# 裸临时目录（basename 不匹配 D-\d+-/hotfix- 前缀）解析出的交付 id 恒为兜底桶
# _main（keeper_paths.resolve_delivery_id），所以队列真实落点是 .keeper/_main/debug。
T="$(newtmpdir)"; : > "$T/.git"
Q="$T/.keeper/_main/debug"
mkissue "$Q" DBG-001 done ""   "已修好的历史问题"
mkissue "$Q" DBG-002 done ""   "另一条历史问题"
mkissue "$Q" DBG-003 open P2   "待办的体验问题"
OUT="$(run_hook "$T" '继续')"
has "open 计数与 id"      "$OUT" "open 1: DBG-003(P2)"
has "done 只给计数"       "$OUT" "done 2"
hasnt "done 的 id 不进注入体" "$OUT" "DBG-001"
has "标题给出完整队列路径（唯一给一次绝对路径的地方）" "$OUT" ".keeper/_main/debug · harness 注入"
has "正文引用薄索引用相对占位符，不重复绝对路径"        "$OUT" "<队列>/index.md"
has "强调按需打开单条"    "$OUT" "按需打开单条"

echo "[3] open 排序：P0 最前，无优先级最后"
mkissue "$Q" DBG-004 open P0 "阻断问题"
mkissue "$Q" DBG-005 open ""  "没打分的问题"
mkissue "$Q" DBG-006 open P1 "主流程问题"
OUT="$(run_hook "$T" '继续')"
has "P0→P1→P2→无分 的顺序" "$OUT" "DBG-004(P0) DBG-006(P1) DBG-003(P2) DBG-005"

echo "[4] 未知 status 必须显式告警（v2 回归：曾被 if/elif 链静默丢弃）"
mkissue "$Q" DBG-007 fixed "" "status 用了枚举外的值"
OUT="$(run_hook "$T" '继续')"
has "读不懂桶把它捞出来" "$OUT" "读不懂 1: DBG-007"
has "说明后果"           "$OUT" "已从队列视图消失"
rm -rf "$Q/DBG-007"

echo "[5] frontmatter 损坏的文件同样进读不懂桶，不静默跳过"
mkdir -p "$Q/DBG-008"
printf 'id: DBG-008\n没有 frontmatter 分隔符\n' > "$Q/DBG-008/issue.md"
OUT="$(run_hook "$T" '继续')"
has "损坏文件被显式列出" "$OUT" "DBG-008"
rm -rf "$Q/DBG-008"

echo "[6] bug 特征词 → register-first 提示，并直接给出下一个可用 id"
OUT="$(run_hook "$T" '这个页面点了没反应')"
has "提示先登记"       "$OUT" "不要直接派 subagent 修"
has "给出具体 id（v4：id 是目录，issue.md 是同目录固定文件名）" "$OUT" "DBG-007/issue.md"
has "要求原话逐字"     "$OUT" "逐字照抄"
OUT="$(run_hook "$T" '继续推进')"
hasnt "无特征词时不提示" "$OUT" "不要直接派 subagent 修"

echo "[7] reopen 升级阶梯"
mkissue "$Q" DBG-009 open P1 "反复修不好的问题"
mkdir -p "$Q/DBG-009"
printf -- '---\nid: DBG-009\nsummary: 反复修不好\nstatus: open\npriority: P1\nreopen_count: 2\n---\n\n正文\n' > "$Q/DBG-009/issue.md"
OUT="$(run_hook "$T" '继续')"
has "reopen 2 次要升档"  "$OUT" "已 reopen 2 次"
has "给出具体动作"       "$OUT" "强制升档 opus"
rm -rf "$Q/DBG-009"

echo "[8] 向上查找：子目录启动能找到队列，但不越过仓库根"
mkdir -p "$T/src/deep/deeper"
OUT="$(run_hook "$T/src/deep/deeper" '继续')"
has "从深层子目录仍找到队列" "$OUT" "open 4"
OUTSIDE="$(newtmpdir)"; : > "$OUTSIDE/.git"; mkdir -p "$OUTSIDE/sub"
OUT="$(run_hook "$OUTSIDE/sub" '继续')"
if [ -z "$OUT" ]; then ok "另一个仓库不会串到本队列（.git 是上界）"
else bad "不应串队列" "空" "$OUT"; fi
rm -rf "$OUTSIDE"
