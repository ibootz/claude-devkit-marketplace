# H29 · 整档收口判定（keeper_generation.retirable_kinds）。判据五项全过才算这一档收口：
# done 桶非空 + open 桶为空 + unknown 桶为空 + 该交付下无待答复裁决 +（debug 专项）
# 无 `<DBG-id>/worktree/` 残留。
# 依赖 harness.sh 的 newtmpdir/mkrealrepo/ok/bad/has/hasnt。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件自成一体。
# 【为什么用真实 git 仓库】同 17-h22：keeper_paths.find_worktree_root 靠真实 git 命令
# 定位工作区根，假 `.git` 占位文件在这里不适用。
#
# 【v7 改了观测点，判据本身一条没动】v6 时 `retirable_kinds` 是每轮三岔口注入的第 4 分支，
# 所以本节原先断言的是注入文案里有没有「可退场」。v7 起注入改成**按实例**现算
# （`keeper_generation.instance_state`，见 25-h30 那一节），`retirable_kinds` 不再进注入，
# 只回答「这一整档是不是全清了」。于是本节的观测点从注入文本下移到函数返回值——
# 同一批 fixture、同一批判据，只是不再经过一层措辞。
#
# 【判据两侧都要覆盖，这是本文件存在的理由】收口判定的误判代价是「一批活被当成干完了」。
# 所以四条否定用例（open 未清 / 有裁决 / 有 worktree / 队列全空）比那条肯定用例更重要，
# 缺任何一条这个判定都不该被任何调用方信任。

echo
echo "== H29 · 整档收口判定（retirable_kinds：五项全过才算这一档清空）=="

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
' "$1" "$LIBDIR"
}

# 判定结果归一成一行可比较的字符串：空集合打印 `-`，非空按字典序空格分隔。
# 用固定字符串比较而不是子串包含——`has "debug"` 在返回 `debug chore` 时也会通过，
# 那正好放过「不该收口的档也被判收口」这一类错误，而那是本节最要防的方向。
gen_retirable() {   # $1=仓库根
  /usr/bin/python3 -c '
import sys
sys.path.insert(0, sys.argv[2])
from keeper_generation import retirable_kinds
print(" ".join(sorted(retirable_kinds(sys.argv[1]))) or "-")
' "$(gen_delivery_root "$1")" "$LIBDIR"
}

# 断言 gen_retirable 的输出恰好等于期望值。$1=断言名 $2=仓库根 $3=期望
# 【必须写成 ${_got}】紧跟变量的全角右括号 `）` 会被 bash 当成变量名的一部分
# （macOS 的 bash 3.2 实测：报 `_got）: unbound variable`），裸 `$_got` 在这里必炸。
gen_eq() {
  _got="$(gen_retirable "$2")"
  if [ "$_got" = "$3" ]; then ok "$1（=${_got}）"
  else bad "$1" "$3" "$_got"; fi
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

echo "[128] done 非空 + open 为空 + 无裁决 + 无 worktree → 该档判为已收口"
T="$(newtmpdir)"; mkrealrepo "$T"
gen_mkitem "$T" debug DBG-001 done
gen_eq "收口后 debug 档判为可收口（chore 没有队列目录，不入集）" "$T" "debug"
rm -rf "$T"

echo "[129] 队列全空（keeper 刚派出、活还没落盘）→ **不得**判为收口"
# 这一条是第一版判据的实测缺陷：没有「done 非空」这一项时，空队列被判成已收口，
# 而空队列恰恰是 keeper 生命周期开头的常态。
T="$(newtmpdir)"; mkrealrepo "$T"
mkdir -p "$(gen_delivery_root "$T")/debug"
gen_eq "空队列不算收口" "$T" "-"
rm -rf "$T"

echo "[130] done 非空但仍有 open 条目 → 不得判为收口"
T="$(newtmpdir)"; mkrealrepo "$T"
gen_mkitem "$T" debug DBG-001 done
gen_mkitem "$T" debug DBG-002 open
gen_eq "有 open 条目时不算收口" "$T" "-"
rm -rf "$T"

echo "[131] 队列已收口但有待答复裁决 → 一票否决"
# 理由不是 blocking 语义（blocking 只冻结 about 指向那一条 issue），而是裁决交接：
# 「把裁决抄回 issue 再删掉这对文件」只写在 keeper 的 §12.3 里。
T="$(newtmpdir)"; mkrealrepo "$T"
gen_mkitem "$T" debug DBG-001 done
mkdir -p "$(gen_delivery_root "$T")/decisions"
printf -- '---\nfrom: debug-keeper\nabout: DBG-001\nblocking: false\n---\n待拍板正文\n' \
  >"$(gen_delivery_root "$T")/decisions/20260810T000000Z-debug-keeper.md"
gen_eq "有待答复裁决时一票否决所有档" "$T" "-"
rm -rf "$T"

echo "[132] 裁决已答复（answers/ 同名文件在位）→ 不再算挂起，恢复判为收口"
T="$(newtmpdir)"; mkrealrepo "$T"
gen_mkitem "$T" debug DBG-001 done
D="$(gen_delivery_root "$T")/decisions"
mkdir -p "$D/answers"
printf -- '---\nfrom: debug-keeper\nabout: DBG-001\n---\n待拍板正文\n' >"$D/20260810T000000Z-debug-keeper.md"
printf -- '裁决原文\n' >"$D/answers/20260810T000000Z-debug-keeper.md"
gen_eq "裁决已答复后恢复判为收口" "$T" "debug"
rm -rf "$T"

echo "[133] 队列已收口但 worktree 目录还在 → debug 档不得判为收口"
T="$(newtmpdir)"; mkrealrepo "$T"
gen_mkitem "$T" debug DBG-001 done
mkdir -p "$(gen_delivery_root "$T")/debug/DBG-001/worktree"
gen_eq "有残留 worktree 时 debug 不算收口" "$T" "-"
rm -rf "$T"

echo "[134] debug 有残留 worktree、chore 已收口 → 只有 chore 入集（worktree 是 debug 专项判据）"
T="$(newtmpdir)"; mkrealrepo "$T"
gen_mkitem "$T" debug DBG-001 done
gen_mkitem "$T" chore CHR-001 done
mkdir -p "$(gen_delivery_root "$T")/debug/DBG-001/worktree"
gen_eq "worktree 残留只牵连 debug，不牵连 chore" "$T" "chore"
rm -rf "$T"

echo "[135] 状态值读不懂的条目（unknown 桶）挡住收口——读不懂不等于已完成"
T="$(newtmpdir)"; mkrealrepo "$T"
gen_mkitem "$T" debug DBG-001 done
gen_mkitem "$T" debug DBG-002 fixed   # v2 遗留值，split_by_status 归进 unknown 桶
gen_eq "unknown 桶非空时不算收口" "$T" "-"
rm -rf "$T"
