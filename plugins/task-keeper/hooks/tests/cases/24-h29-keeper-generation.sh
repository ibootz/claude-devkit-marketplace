# H29 · keeper 换代判定（keeper_generation.retirable_kinds 经由 keeper_routing 的
# 第 4 分支注入）。判据五项全过才建议换代：done 桶非空 + open 桶为空 + unknown 桶为空
# + 该交付下无待答复裁决 +（debug 专项）无 `<DBG-id>/worktree/` 残留。
# 依赖 harness.sh 的 newtmpdir/mkrealrepo/run_keeper_instance/run_triage_sess/ok/bad/has/hasnt。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件自成一体。
# 【为什么用真实 git 仓库】同 17-h22：keeper_paths.find_worktree_root 靠真实 git 命令
# 定位工作区根，假 `.git` 占位文件在这里不适用。
#
# 【判据两侧都要覆盖，这是本文件存在的理由】换代提示是「建议主会话别再唤醒旧实例、
# 改派新的」，误判的代价是两个实例抢同一个队列目录的独占写权限（2026-08-03 那次
# 「唤醒不到就重派」事故的同形态）。所以四条否定用例（open 未清 / 有裁决 / 有 worktree /
# 队列全空）比那条肯定用例更重要，缺任何一条这个机制都不该上线。

echo
echo "== H29 · keeper 换代判定（队列收口才建议新派一代）=="

# 与 17-h22 同一套抽取方式。
gen_triage_text() {
  printf '%s' "$1" | /usr/bin/python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])
except Exception:
    print("")
'
}

# 交付根 = `<仓库根>/.keeper/<交付id>`。**交付 id 必须现算，不能写成 basename**——
# 临时目录不是交付形态，`resolve_delivery_id` 对它返回 `_main` 而不是目录名，
# 写死 basename 会把队列条目造到一个判定函数根本不看的路径下，表现成「造了条目却
# 判不出收口」（第一版本文件就是这么错的，四条断言全红而判定函数本身是对的）。
gen_delivery_root() {
  /usr/bin/python3 -c '
import sys, os
sys.path.insert(0, sys.argv[2])
from keeper_paths import resolve_delivery_id
print(os.path.join(sys.argv[1], ".keeper", resolve_delivery_id(sys.argv[1])))
' "$1" "$TESTS_DIR/../lib"
}

# 在交付队列里造一条条目。$1=仓库根 $2=队列子目录名 $3=条目 id $4=status
gen_mkitem() {
  _d="$(gen_delivery_root "$1")/$2/$3"
  mkdir -p "$_d"
  # 正文文件名逐队列不同，取自各自 QueueSpec.item_file——**不要照 dir_name 推**：
  # chore 的正文是 `item.md` 而不是 `chore.md`，名字猜错时 load_all 扫不到条目、
  # done 桶恒空，表现成「造了 done 条目却判不出收口」，而判定函数本身没问题。
  _f="issue.md"
  [ "$2" = "chore" ] && _f="item.md"
  [ "$2" = "context" ] && _f="context.md"
  cat >"$_d/$_f" <<EOF
---
id: $3
summary: 回归用例造的条目
status: $4
---

## 现象

回归用例正文，不参与判定。
EOF
}

echo "[128] done 非空 + open 为空 + 无裁决 + 无 worktree → 建议换代新派一代"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "Agent" "sess-A" >/dev/null
gen_mkitem "$T" debug DBG-001 done
OUT="$(run_triage_sess "$T" "sess-A")"
TEXT="$(gen_triage_text "$OUT")"
has "收口后提示这一代可退场" "$TEXT" "可退场"
has "收口后给出新派动作" "$TEXT" "新派"
has "收口后给出带前缀的 description 模板" "$TEXT" "debug 队列 · <本批摘要>"
hasnt "收口后不再提示唤醒旧实例" "$TEXT" "不要重派"
CHARS="$(/usr/bin/python3 -c 'import sys; print(len(sys.argv[1]))' "$TEXT")"
if [ "$CHARS" -le 800 ]; then ok "换代分支 ${CHARS} 字符 ≤800"
else bad "换代分支应 ≤800 字符" "<=800" "$CHARS"; fi
rm -rf "$T"

echo "[129] 队列全空（keeper 刚派出、活还没落盘）→ **不得**建议换代，照旧唤醒"
# 这一条是第一版判据的实测缺陷：没有「done 非空」这一项时，空队列被判成可换代，
# 而空队列恰恰是 keeper 生命周期开头的常态，会导致转完 bug 的下一轮就重派。
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "Agent" "sess-A" >/dev/null
OUT="$(run_triage_sess "$T" "sess-A")"
TEXT="$(gen_triage_text "$OUT")"
has "空队列时仍走唤醒分支" "$TEXT" "本会话已有"
hasnt "空队列时不建议换代" "$TEXT" "可退场"
rm -rf "$T"

echo "[130] done 非空但仍有 open 条目 → 不得建议换代"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "Agent" "sess-A" >/dev/null
gen_mkitem "$T" debug DBG-001 done
gen_mkitem "$T" debug DBG-002 open
OUT="$(run_triage_sess "$T" "sess-A")"
TEXT="$(gen_triage_text "$OUT")"
has "有 open 条目时仍走唤醒分支" "$TEXT" "本会话已有"
hasnt "有 open 条目时不建议换代" "$TEXT" "可退场"
rm -rf "$T"

echo "[131] 队列已收口但有待答复裁决 → 一票否决，不得建议换代"
# 理由不是 blocking 语义（blocking 只冻结 about 指向那一条 issue），而是裁决交接：
# 「把裁决抄回 issue 再删掉这对文件」只写在 keeper 的 §12.3 里，新实例的冷启动流程
# 不扫 decisions/，旧实例先退场会让这次人类决策静默蒸发。
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "Agent" "sess-A" >/dev/null
gen_mkitem "$T" debug DBG-001 done
mkdir -p "$(gen_delivery_root "$T")/decisions"
printf -- '---\nfrom: debug-keeper\nabout: DBG-001\nblocking: false\n---\n待拍板正文\n' \
  >"$(gen_delivery_root "$T")/decisions/20260810T000000Z-debug-keeper.md"
OUT="$(run_triage_sess "$T" "sess-A")"
TEXT="$(gen_triage_text "$OUT")"
has "有待答复裁决时仍走唤醒分支" "$TEXT" "本会话已有"
hasnt "有待答复裁决时不建议换代" "$TEXT" "可退场"
rm -rf "$T"

echo "[132] 裁决已答复（answers/ 同名文件在位）→ 不再算挂起，恢复建议换代"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "Agent" "sess-A" >/dev/null
gen_mkitem "$T" debug DBG-001 done
D="$(gen_delivery_root "$T")/decisions"
mkdir -p "$D/answers"
printf -- '---\nfrom: debug-keeper\nabout: DBG-001\n---\n待拍板正文\n' >"$D/20260810T000000Z-debug-keeper.md"
printf -- '裁决原文\n' >"$D/answers/20260810T000000Z-debug-keeper.md"
OUT="$(run_triage_sess "$T" "sess-A")"
TEXT="$(gen_triage_text "$OUT")"
has "裁决已答复后恢复建议换代" "$TEXT" "可退场"
rm -rf "$T"

echo "[133] 队列已收口但 worktree 目录还在 → debug 档不得建议换代"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "Agent" "sess-A" >/dev/null
gen_mkitem "$T" debug DBG-001 done
mkdir -p "$(gen_delivery_root "$T")/debug/DBG-001/worktree"
OUT="$(run_triage_sess "$T" "sess-A")"
TEXT="$(gen_triage_text "$OUT")"
has "有残留 worktree 时仍走唤醒分支" "$TEXT" "本会话已有"
hasnt "有残留 worktree 时不建议换代" "$TEXT" "可退场"
rm -rf "$T"

echo "[134] debug 有残留 worktree、chore 已收口 → 只对 chore 建议换代，两支并存"
# worktree 残留是 debug 专项判据，不该牵连 chore；同时验证一句话里能同时出现
# 「唤醒 debug」与「chore 可退场」两段。
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "Agent" "sess-A" >/dev/null
run_keeper_instance "$T" "task-keeper:chore-keeper" "opus-chore-keeper-9f2a" "Agent" "sess-A" >/dev/null
gen_mkitem "$T" debug DBG-001 done
gen_mkitem "$T" chore CHR-001 done
mkdir -p "$(gen_delivery_root "$T")/debug/DBG-001/worktree"
OUT="$(run_triage_sess "$T" "sess-A")"
TEXT="$(gen_triage_text "$OUT")"
has "debug 仍提示唤醒（带真实 name）" "$TEXT" "opus-debug-keeper-4bb6"
has "chore 提示可退场" "$TEXT" "chore 队列 · <本批摘要>"
hasnt "不该建议换掉 debug 那一代" "$TEXT" "debug 队列 · <本批摘要>"
CHARS="$(/usr/bin/python3 -c 'import sys; print(len(sys.argv[1]))' "$TEXT")"
if [ "$CHARS" -le 800 ]; then ok "两支并存分支 ${CHARS} 字符 ≤800"
else bad "两支并存分支应 ≤800 字符" "<=800" "$CHARS"; fi
rm -rf "$T"

echo "[135] 状态值读不懂的条目（unknown 桶）挡住换代——读不懂不等于已完成"
T="$(newtmpdir)"; mkrealrepo "$T"
run_keeper_instance "$T" "task-keeper:debug-keeper" "opus-debug-keeper-4bb6" "Agent" "sess-A" >/dev/null
gen_mkitem "$T" debug DBG-001 done
gen_mkitem "$T" debug DBG-002 fixed   # v2 遗留值，split_by_status 归进 unknown 桶
OUT="$(run_triage_sess "$T" "sess-A")"
TEXT="$(gen_triage_text "$OUT")"
hasnt "unknown 桶非空时不建议换代" "$TEXT" "可退场"
rm -rf "$T"
