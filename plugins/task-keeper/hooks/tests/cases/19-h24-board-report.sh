# H24 · 看板报告脚本（skills/tk-board/scripts/board.py）的四态派生与三类告警。
# 依赖 harness.sh 的 newtmpdir/mkissue/ok/bad/has/hasnt。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件自成一体，不依赖其他 case 文件留下的变量或函数。
#
# 【为什么这一节非有不可】board.py 的四种看板状态里只有「已解决」直接来自
# frontmatter 的 `status: done`，另外三种全是从文件系统事实反推的：
#   · 进行中 ← 条目目录下有 `worktree/`
#   · 待拍板 ← `decisions/<未答复>.md` 的 `about:` 指向本条
#   · 未解决 ← 兜底
# 这些判据没有任何一处写在 frontmatter 里，真实队列也不总是四态齐全（2026-08-05
# 实测那份 151 条的真实队列里，`decisions/` 恰好全部已答复，「待拍板」一条都跑不
# 出来）。不造 fixture 就等于这三条判据从未被验证过。

echo
echo "== H24 · 看板报告 board.py（四态派生 + 陈旧 worktree / 悬空拍板 / 归属不明 三类告警）=="

# runner 只导出 HOOK_DIR（= plugins/task-keeper/hooks），没有插件根变量，
# 这里自己上溯一层。
BOARD_PY="$HOOK_DIR/../skills/tk-board/scripts/board.py"

# 四态 + 三类告警一次性造齐：
#   DBG-001 open、无 worktree                        → 未解决
#   DBG-002 open、有 worktree/                       → 进行中
#   DBG-003 open、被未答复的 a-pending.md 指向        → 待拍板
#   DBG-004 done、有 worktree/（忘删）               → 已解决 + 陈旧 worktree 告警
#   b-orphan.md   未答复、没写 about                 → 归属不明告警
#   c-dangling.md 未答复、about 指向已 done 的 004   → 悬空拍板告警
#   d-answered.md 有同名 answers/ → 已答复，一律不算
T="$(newtmpdir)"; : > "$T/.git"
Q="$T/.keeper/_main/debug"
mkissue "$Q" DBG-001 open P2 "纯 open 无在飞"
mkissue "$Q" DBG-002 open P1 "已派 fixer 在飞"
mkissue "$Q" DBG-003 open P0 "等人拍板"
mkissue "$Q" DBG-004 done P1 "已收尾但 worktree 没删"
mkdir -p "$Q/DBG-002/worktree" "$Q/DBG-004/worktree" "$T/.keeper/_main/decisions/answers"
DEC="$T/.keeper/_main/decisions"
printf -- '---\nabout: DBG-003\nblocking: true\n---\n问？\n' > "$DEC/a-pending.md"
printf -- '---\nblocking: false\n---\n没写 about\n' > "$DEC/b-orphan.md"
printf -- '---\nabout: DBG-004\n---\n指向已 done 的条目\n' > "$DEC/c-dangling.md"
printf -- '---\nabout: DBG-001\n---\n已答复的不算\n' > "$DEC/d-answered.md"
printf -- 'ok\n' > "$DEC/answers/d-answered.md"
OUT="$(/usr/bin/python3 "$BOARD_PY" --queue-dir "$Q" 2>&1)"

echo "[99] 四态派生：status 只有 open/done 两值，另三态从 worktree/ 与 decisions/ 反推"
has "DBG-001 判未解决" "$OUT" "| DBG-001 | 纯 open 无在飞 | 未解决 |"
has "DBG-002 有 worktree/ 判进行中" "$OUT" "| DBG-002 | 已派 fixer 在飞 | 进行中 |"
has "DBG-003 被未答复决策指向判待拍板" "$OUT" "| DBG-003 | 等人拍板 | 待拍板 |"
has "DBG-004 done 判已解决" "$OUT" "| DBG-004 | 已收尾但 worktree 没删 | 已解决 |"

echo "[100] 判定优先级：done 短路在 worktree/ 之前，陈旧 worktree 不冒充「进行中」"
hasnt "DBG-004 不被误判成进行中" "$OUT" "| DBG-004 | 已收尾但 worktree 没删 | 进行中 |"
has "陈旧 worktree 单列告警" "$OUT" "陈旧 worktree"
has "陈旧告警点名 DBG-004" "$OUT" "没清理，归档会被它卡住）：DBG-004"

echo "[101] 三类告警都不静默丢弃（v2 教训：读不懂的东西静默跳过，16 条 issue 人间蒸发）"
has "悬空拍板告警点名 DBG-004 与来源文件" "$OUT" "DBG-004（c-dangling.md）"
has "归属不明告警点名 b-orphan.md" "$OUT" "b-orphan.md"
hasnt "已答复的 decision 不进任何告警" "$OUT" "d-answered.md"

echo "[102] 进度总览四态计数与合计"
has "待拍板 1 条" "$OUT" "| 待拍板 | 1 |"
has "进行中 1 条" "$OUT" "| 进行中 | 1 |"
has "未解决 1 条" "$OUT" "| 未解决 | 1 |"
has "已解决 1 条" "$OUT" "| 已解决 | 1 |"
has "合计 4 条" "$OUT" "| **合计** | **4** |"

echo "[103] 只读保证：跑完不改变队列任何状态（对比跑前跑后的文件清单与内容校验和）"
BEFORE="$(cd "$T" && find . -type f | sort | xargs -I{} sh -c 'printf "%s " "{}"; wc -c < "{}"' 2>/dev/null)"
/usr/bin/python3 "$BOARD_PY" --queue-dir "$Q" >/dev/null 2>&1
AFTER="$(cd "$T" && find . -type f | sort | xargs -I{} sh -c 'printf "%s " "{}"; wc -c < "{}"' 2>/dev/null)"
if [ "$BEFORE" = "$AFTER" ]; then ok "看板脚本无写副作用（文件清单与大小逐项一致）"
else bad "看板脚本应只读" "文件树不变" "跑前后有差异"; fi
if [ ! -e "$Q/index.md" ]; then ok "不像 queue_snapshot 那样顺手写 index.md"
else bad "不应写 index.md" "不存在" "存在"; fi

echo "[104] --status 过滤只筛明细，进度总览仍给全量（看板要的是全局进度）"
OUT_F="$(/usr/bin/python3 "$BOARD_PY" --queue-dir "$Q" --status 待拍板,进行中 2>&1)"
has "明细只剩两条" "$OUT_F" "## 条目明细（2 条）"
hasnt "已解决条目被筛掉" "$OUT_F" "| DBG-004 | 已收尾但 worktree 没删 |"
has "总览仍显示已解决 1 条" "$OUT_F" "| 已解决 | 1 |"
BADOUT="$(/usr/bin/python3 "$BOARD_PY" --queue-dir "$Q" --status 已修复 2>&1 || true)"
has "不认识的状态值直接报错并列出合法值" "$BADOUT" "--status 不认识的值"

echo "[105] summary 前导【…】状态块被剥掉——真实数据里它常写成状态叙述而非问题说明"
mkissue "$Q" DBG-005 done P2 "【已关闭 —— 用户拍板】【与 DBG-105 重叠】导入侧权重校验缺失"
OUT_S="$(/usr/bin/python3 "$BOARD_PY" --queue-dir "$Q" 2>&1)"
has "连续两块【】都被剥掉，露出真正的问题说明" "$OUT_S" "| DBG-005 | 导入侧权重校验缺失 |"
rm -rf "$T"

echo "[106] 空队列与缺队列都不报错（看板是随手可跑的只读命令，不该因为没数据就崩）"
T2="$(newtmpdir)"; : > "$T2/.git"; mkdir -p "$T2/.keeper/_main/debug"
OUT_E="$(/usr/bin/python3 "$BOARD_PY" --queue-dir "$T2/.keeper/_main/debug" 2>&1)"
has "空队列出合计 0" "$OUT_E" "| **合计** | **0** |"
has "空队列明细给占位行" "$OUT_E" "（无）"
OUT_M="$(/usr/bin/python3 "$BOARD_PY" --queue-dir "$T2/.keeper/_main/nosuch" 2>&1)"
has "队列目录不存在时给可读提示而不是 traceback" "$OUT_M" "找不到"
hasnt "不吐 python traceback" "$OUT_M" "Traceback"
rm -rf "$T2"
