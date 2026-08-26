# H31 · 一个事项一个活跃主条目（v8 / 4.6.0）：
#   keeper_cli.py candidates（跨队列 open 候选列举，done 不列入；读不动 fail closed；
#     损坏条目同样 fail closed：exit 2、stdout 不给候选、stderr 逐条可见）
#   keeper_cli.py check-transfers（规格空白转出互链的机械完整性校验：源必须存在且
#     done、双向互链必须成对写齐）
# 依赖 harness.sh 的 newtmpdir/mkrealrepo/mkissue/mkchore/ok/bad/has/hasnt。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件自成一体，不依赖其他 case 文件留下的变量或函数。
#
# 【为什么这一节非有不可】「一个事项一个活跃主条目」规则的两个机械面没有测试
# 就等于没有实现：candidates 若漏列某条 open（或把 done 也列进来当候选），keeper
# 的语义查重就在错误清单上做，重复登记静默通过；check-transfers 若漏报，转出
# 后 DBG 不标 done、互链缺失这类破损会在队列里长期躺平且无任何信号。两条命令
# 都是纯只读，测试只造 fixture + 断言 stdout/stderr/退出码。
#
# 【python 写法】统一 /usr/bin/python3，与 harness.sh 的「避免 PATH 上装了别的
# python3 导致依赖版本漂移」约定一致，不混用裸 python3。

echo
echo "== H31 · 单一活跃主条目（candidates 跨队列查重 + check-transfers 转出互链）=="

CLI="$HOOK_DIR/../scripts/keeper_cli.py"

echo "[183] candidates 列出当前交付两队列全部 open 条目，done 不列入候选"
T="$(newtmpdir)"; mkrealrepo "$T"
Q="$T/.keeper/_main/debug"; C="$T/.keeper/_main/chore"
mkdir -p "$Q" "$C"
mkissue "$Q" DBG-001 open P1 "表头错位"
mkissue "$Q" DBG-002 done P2 "已修完"
mkchore "$C" CHR-001 open ledger "补 README"
mkchore "$C" CHR-002 done ledger "已归档"
OUT="$(/usr/bin/python3 "$CLI" --cwd "$T" candidates)"
has "debug 的 open 条目在候选里" "$OUT" "debug	DBG-001	表头错位"
has "chore 的 open 条目在候选里" "$OUT" "chore	CHR-001	补 README"
hasnt "done 的 DBG 不列入候选" "$OUT" "DBG-002"
hasnt "done 的 CHR 不列入候选" "$OUT" "CHR-002"

echo "[184] candidates --kind 收窄与 --json 形态"
OUT_D="$(/usr/bin/python3 "$CLI" --cwd "$T" candidates --kind debug)"
has "只看 debug 队列" "$OUT_D" "debug	DBG-001	表头错位"
hasnt "--kind debug 不带 chore 条目" "$OUT_D" "CHR-001"
OUT_J="$(/usr/bin/python3 "$CLI" --cwd "$T" candidates --json)"
has "json 形态可机器读" "$OUT_J" '"DBG-001"'
hasnt "json 里没有 done 条目" "$OUT_J" "DBG-002"

echo "[185] 两队列都空时 candidates 给可读提示而不是报错"
T2="$(newtmpdir)"; mkrealrepo "$T2"
OUT_E="$(/usr/bin/python3 "$CLI" --cwd "$T2" candidates)"
has "空队列提示" "$OUT_E" "没有 open 条目"
rm -rf "$T2"

echo "[196] candidates 对 frontmatter 损坏条目 fail closed：exit 非 0、stderr 逐条报出、stdout 不给候选（候选清单不完整不能当查重依据）"
T3="$(newtmpdir)"; mkrealrepo "$T3"
Q3="$T3/.keeper/_main/debug"; C3="$T3/.keeper/_main/chore"
mkdir -p "$Q3" "$C3"
mkissue "$Q3" DBG-011 open P1 "正常 open 条目"
mkdir -p "$Q3/DBG-012"
printf '# DBG-012\n没有 frontmatter 的损坏条目\n' > "$Q3/DBG-012/issue.md"
OUT_BR="$(/usr/bin/python3 "$CLI" --cwd "$T3" candidates 2>&1)"
RC_BR="$?"
has "损坏条目在 stderr 报出" "$OUT_BR" "DBG-012"
has "报出损坏原因" "$OUT_BR" "读不懂"
has "stderr 指明候选清单不完整" "$OUT_BR" "候选清单不完整"
hasnt "stdout 不给候选（残缺清单不能用于查重）" "$OUT_BR" "DBG-011"
[ "$RC_BR" = "2" ] && ok "损坏条目 exit 2（fail closed）" || bad "损坏条目应 exit 2" "2" "$RC_BR"
rm -rf "$T3"

echo "[195] candidates 队列读不动时 fail closed：exit 非 0 + 可解释错误（不能吞成空队列）"
chmod 000 "$Q"
OUT_FAIL="$(/usr/bin/python3 "$CLI" --cwd "$T" candidates 2>&1)"
RC_FAIL="$?"
chmod 755 "$Q"
has "读不动时报可解释错误" "$OUT_FAIL" "读 debug 队列失败"
has "错误里指明不能当没有候选" "$OUT_FAIL" "先修好队列再 claim"
[ "$RC_FAIL" != "0" ] && ok "队列读不动时 exit 非 0" || bad "队列读不动时应 exit 非 0" "非 0" "$RC_FAIL"

echo "[201] candidates 对缺正文文件的条目 fail closed：exit 2、stderr 逐条报出、stdout 不给候选"
T6="$(newtmpdir)"; mkrealrepo "$T6"
Q6="$T6/.keeper/_main/debug"; C6="$T6/.keeper/_main/chore"
mkdir -p "$Q6" "$C6"
mkissue "$Q6" DBG-031 open P1 "正常 open 条目"
mkdir -p "$Q6/DBG-032"
OUT_MISS2="$(/usr/bin/python3 "$CLI" --cwd "$T6" candidates 2>&1)"
RC_MISS2="$?"
has "缺正文条目在 stderr 报出" "$OUT_MISS2" "DBG-032"
has "报出缺正文原因" "$OUT_MISS2" "缺 issue.md"
has "stderr 指明候选清单不完整" "$OUT_MISS2" "候选清单不完整"
hasnt "stdout 不给候选（残缺清单不能用于查重）" "$OUT_MISS2" "DBG-031"
[ "$RC_MISS2" = "2" ] && ok "缺正文 exit 2（fail closed）" || bad "缺正文应 exit 2" "2" "$RC_MISS2"
rm -rf "$T6"

echo "[202] candidates 对目录名非法的条目目录 fail closed：exit 2、stderr 报出、stdout 不给候选"
T5="$(newtmpdir)"; mkrealrepo "$T5"
Q5="$T5/.keeper/_main/debug"; C5="$T5/.keeper/_main/chore"
mkdir -p "$Q5" "$C5" "$Q5/DBG-021" "$Q5/DBG-abc"
printf -- '---\nid: DBG-021\nsummary: 正常 open 条目\nstatus: open\n---\n# DBG-021\n' > "$Q5/DBG-021/issue.md"
printf -- '---\nid: DBG-abc\nsummary: 目录名非法的条目\nstatus: open\n---\n# DBG-abc\n' > "$Q5/DBG-abc/issue.md"
OUT_ILL="$(/usr/bin/python3 "$CLI" --cwd "$T5" candidates 2>&1)"
RC_ILL="$?"
has "目录名非法的条目在 stderr 报出" "$OUT_ILL" "DBG-abc"
has "报出读不懂原因" "$OUT_ILL" "读不懂"
has "stderr 指明候选清单不完整" "$OUT_ILL" "候选清单不完整"
hasnt "stdout 不给候选（残缺清单不能用于查重）" "$OUT_ILL" "DBG-021"
[ "$RC_ILL" = "2" ] && ok "目录名非法 exit 2（fail closed）" || bad "目录名非法应 exit 2" "2" "$RC_ILL"
rm -rf "$T5"

echo "[203] candidates --kind 只收窄候选列举：损坏检查总覆盖两队列（chore 有损坏条目时，both 与 --kind debug 都 exit 2、stdout 不给候选）"
T7="$(newtmpdir)"; mkrealrepo "$T7"
Q7="$T7/.keeper/_main/debug"; C7="$T7/.keeper/_main/chore"
mkdir -p "$Q7" "$C7"
mkissue "$Q7" DBG-041 open P1 "正常 open 条目"
mkdir -p "$C7/CHR-041"
printf -- '---\nid: CHR-041\nsummary: 状态写坏\nstatus: weird\nreported_at: %s\n---\n# CHR-041\n' "$(today_iso)" > "$C7/CHR-041/item.md"
OUT_CU="$(/usr/bin/python3 "$CLI" --cwd "$T7" candidates 2>&1)"
RC_CU="$?"
has "both 模式报出 chore 的损坏条目" "$OUT_CU" "CHR-041"
has "both 模式 stderr 指明候选清单不完整" "$OUT_CU" "候选清单不完整"
[ "$RC_CU" = "2" ] && ok "both 模式 chore 损坏 exit 2（任一队列不完整即 fail closed）" || bad "both 模式 chore 损坏应 exit 2" "2" "$RC_CU"
OUT_KD="$(/usr/bin/python3 "$CLI" --cwd "$T7" candidates --kind debug 2>&1)"
RC_KD="$?"
has "--kind debug 也报出另一队列的损坏条目" "$OUT_KD" "CHR-041"
hasnt "--kind debug 不给残缺候选（另一队列损坏 = 候选清单不完整）" "$OUT_KD" "DBG-041"
[ "$RC_KD" = "2" ] && ok "--kind debug 遇另一队列损坏条目 exit 2（损坏检查不受收窄影响）" || bad "--kind debug 遇另一队列损坏条目应 exit 2" "2" "$RC_KD"
rm -rf "$T7"

echo "[204] candidates 队列路径存在但不是目录时 fail closed：exit 非 0 + 可解释错误（不能吞成空队列）"
T8="$(newtmpdir)"; mkrealrepo "$T8"
mkdir -p "$T8/.keeper/_main"
touch "$T8/.keeper/_main/debug"
OUT_FILEQ="$(/usr/bin/python3 "$CLI" --cwd "$T8" candidates 2>&1)"
RC_FILEQ="$?"
has "报出队列路径不是目录" "$OUT_FILEQ" "不是目录"
has "错误里指明不能当没有候选" "$OUT_FILEQ" "先修好队列再 claim"
[ "$RC_FILEQ" != "0" ] && ok "队列路径是文件时 exit 非 0" || bad "队列路径是文件时应 exit 非 0" "非 0" "$RC_FILEQ"
rm -rf "$T8"

# ── check-transfers：转出互链机械完整性 ─────────────────────────────
# fixture：
#   DBG-003 done   + 转出至：CHR-003          → 合法互链（双向成对）
#   CHR-003 open   + 来源：DBG-003            → 合法（源存在、done、反向标记成对）
#   CHR-004 open   + 来源：DBG-001（open）    → 报错（活跃 CHR 挂未关闭源）
#   CHR-005 open   + 来源：DBG-999（不存在）  → 报错
#   DBG-004 done   + 转出至：CHR-999（不存在）→ 报错
echo "[186] 无转出标记时 check-transfers 通过（exit 0）"
/usr/bin/python3 "$CLI" --cwd "$T" check-transfers >/dev/null 2>&1
[ "$?" = "0" ] && ok "无标记时 exit 0" || bad "无标记时应 exit 0" "0" "$?"

echo "[187] 合法互链通过：CHR open 的来源 DBG 存在、为 done、且反向写有转出标记"
mkdir -p "$Q/DBG-003" "$C/CHR-003" "$C/CHR-004" "$C/CHR-005" "$Q/DBG-004"
printf -- '---\nid: DBG-003\nsummary: 规格空白待确认\nstatus: done\nreported_at: %s\n---\n# DBG-003\n转出至：CHR-003（规格空白，待产品确认）\n' "$(today_iso)" > "$Q/DBG-003/issue.md"
printf -- '---\nid: CHR-003\nsummary: 待产品确认 X 的语义\nstatus: open\nreported_at: %s\n---\n# CHR-003\n来源：DBG-003（规格空白转出）\n' "$(today_iso)" > "$C/CHR-003/item.md"
OUT_OK="$(/usr/bin/python3 "$CLI" --cwd "$T" check-transfers 2>&1)"
RC_OK="$?"
has "合法互链输出 OK" "$OUT_OK" "OK"
[ "$RC_OK" = "0" ] && ok "合法互链 exit 0" || bad "合法互链应 exit 0" "0" "$RC_OK"

echo "[188] CHR open 声明来源 DBG 不存在 → exit 2 报错"
printf -- '---\nid: CHR-005\nsummary: 待产品确认 Y 的语义\nstatus: open\nreported_at: %s\n---\n# CHR-005\n来源：DBG-999（规格空白转出）\n' "$(today_iso)" > "$C/CHR-005/item.md"
OUT_MISS="$(/usr/bin/python3 "$CLI" --cwd "$T" check-transfers 2>&1)"
RC_MISS="$?"
has "报出来源 DBG 不存在" "$OUT_MISS" "CHR-005 声明来源 DBG-999，但 debug 队列里不存在该条目"
[ "$RC_MISS" = "2" ] && ok "来源不存在 exit 2" || bad "来源不存在应 exit 2" "2" "$RC_MISS"

echo "[189] CHR open 声明来源 DBG 仍 open → exit 2 报错（转出未关闭）"
printf -- '---\nid: CHR-004\nsummary: 待产品确认 Z 的语义\nstatus: open\nreported_at: %s\n---\n# CHR-004\n来源：DBG-001（规格空白转出）\n' "$(today_iso)" > "$C/CHR-004/item.md"
OUT_OPEN="$(/usr/bin/python3 "$CLI" --cwd "$T" check-transfers 2>&1)"
RC_OPEN="$?"
has "报出活跃 CHR 挂在 open 源上" "$OUT_OPEN" "CHR-004 为 open、声明来源 DBG-001，但 DBG-001 的 status 是 'open'，不是 done"
[ "$RC_OPEN" = "2" ] && ok "源未关闭 exit 2" || bad "源未关闭应 exit 2" "2" "$RC_OPEN"

echo "[194] CHR open 声明来源 DBG 的 status 是未知值 → exit 2 报错（读不懂不能当作没这回事）"
mkdir -p "$Q/DBG-007" "$C/CHR-008"
printf -- '---\nid: DBG-007\nsummary: 状态写坏了\nstatus: weird\nreported_at: %s\n---\n# DBG-007\n' "$(today_iso)" > "$Q/DBG-007/issue.md"
printf -- '---\nid: CHR-008\nsummary: 待产品确认 U 的语义\nstatus: open\nreported_at: %s\n---\n# CHR-008\n来源：DBG-007（规格空白转出）\n' "$(today_iso)" > "$C/CHR-008/item.md"
OUT_UNK="$(/usr/bin/python3 "$CLI" --cwd "$T" check-transfers 2>&1)"
RC_UNK="$?"
has "报出未知 status 源" "$OUT_UNK" "CHR-008 为 open、声明来源 DBG-007，但 DBG-007 的 status 是 'weird'，不是 done"
[ "$RC_UNK" = "2" ] && ok "源 status 未知 exit 2" || bad "源 status 未知应 exit 2" "2" "$RC_UNK"

echo "[190] DBG 声明转出至 CHR 不存在 → exit 2 报错（去向断了）"
printf -- '---\nid: DBG-004\nsummary: 已关闭转出\nstatus: done\nreported_at: %s\n---\n# DBG-004\n转出至：CHR-999（规格空白，待产品确认）\n' "$(today_iso)" > "$Q/DBG-004/issue.md"
OUT_TGT="$(/usr/bin/python3 "$CLI" --cwd "$T" check-transfers 2>&1)"
RC_TGT="$?"
has "报出转出去向不存在" "$OUT_TGT" "DBG-004 声明转出至 CHR-999，但 chore 队列里不存在该条目"
[ "$RC_TGT" = "2" ] && ok "去向不存在 exit 2" || bad "去向不存在应 exit 2" "2" "$RC_TGT"

echo "[192] CHR open 声明来源 DBG 存在且 done，但 DBG 没反向写「转出至」→ exit 2 报错（互链只写半边）"
mkdir -p "$Q/DBG-005" "$C/CHR-006"
printf -- '---\nid: DBG-005\nsummary: 已关闭但没写互链\nstatus: done\nreported_at: %s\n---\n# DBG-005\n' "$(today_iso)" > "$Q/DBG-005/issue.md"
printf -- '---\nid: CHR-006\nsummary: 待产品确认 W 的语义\nstatus: open\nreported_at: %s\n---\n# CHR-006\n来源：DBG-005（规格空白转出）\n' "$(today_iso)" > "$C/CHR-006/item.md"
OUT_HALF_C="$(/usr/bin/python3 "$CLI" --cwd "$T" check-transfers 2>&1)"
RC_HALF_C="$?"
has "报出源缺反向转出标记" "$OUT_HALF_C" "CHR-006 为 open、声明来源 DBG-005，但 DBG-005 正文没有反向写「转出至：CHR-006」"
[ "$RC_HALF_C" = "2" ] && ok "源缺反向标记 exit 2" || bad "源缺反向标记应 exit 2" "2" "$RC_HALF_C"

echo "[193] DBG 转出至 CHR 存在，但 CHR 没反向写「来源」→ exit 2 报错（互链只写半边）"
mkdir -p "$Q/DBG-006" "$C/CHR-007"
printf -- '---\nid: DBG-006\nsummary: 已关闭缺反向来源\nstatus: done\nreported_at: %s\n---\n# DBG-006\n转出至：CHR-007（规格空白，待产品确认）\n' "$(today_iso)" > "$Q/DBG-006/issue.md"
printf -- '---\nid: CHR-007\nsummary: 待产品确认 V 的语义\nstatus: open\nreported_at: %s\n---\n# CHR-007\n' "$(today_iso)" > "$C/CHR-007/item.md"
OUT_HALF_D="$(/usr/bin/python3 "$CLI" --cwd "$T" check-transfers 2>&1)"
RC_HALF_D="$?"
has "报出去向缺反向来源标记" "$OUT_HALF_D" "DBG-006 声明转出至 CHR-007，但 CHR-007 正文没有反向写「来源：DBG-006」"
[ "$RC_HALF_D" = "2" ] && ok "去向缺反向标记 exit 2" || bad "去向缺反向标记应 exit 2" "2" "$RC_HALF_D"

echo "[191] 重开放行：CHR 已 done、源 DBG open → 不报错（产品确认属 bug 后的重开路径）"
printf -- '---\nid: CHR-004\nsummary: 待产品确认 Z 的语义\nstatus: done\nreported_at: %s\n---\n# CHR-004\n来源：DBG-001（规格空白转出，产品确认属 bug 已重开 DBG-001）\n' "$(today_iso)" > "$C/CHR-004/item.md"
rm -rf "$C/CHR-005" "$Q/DBG-004" "$Q/DBG-005" "$C/CHR-006" "$Q/DBG-006" "$C/CHR-007" "$Q/DBG-007" "$C/CHR-008"
OUT_RE="$(/usr/bin/python3 "$CLI" --cwd "$T" check-transfers 2>&1)"
RC_RE="$?"
has "重开放行输出 OK" "$OUT_RE" "OK"
[ "$RC_RE" = "0" ] && ok "重开放行 exit 0" || bad "重开放行应 exit 0" "0" "$RC_RE"
rm -rf "$T"

# ── 转出源归档（问题 4）：check-transfers 必须能找到已合法归档的 done DBG ──
# archive_done.py 把 done 条目**整目录**搬到 archive/<批次>/，正文互链标记原样
# 保留——只扫 top-level 会把「已归档的合法 done 源」误报成「不存在」。
echo "[197] 转出源 DBG 已归档到 archive/：CHR open 声明来源它 → exit 0（归档不解除互链）"
T4="$(newtmpdir)"; mkrealrepo "$T4"
Q4="$T4/.keeper/_main/debug"; C4="$T4/.keeper/_main/chore"
mkdir -p "$Q4" "$C4" "$Q4/archive/auto-20260801/DBG-101" "$C4/CHR-101"
printf -- '---\nid: DBG-101\nsummary: 已关闭转出（已归档）\nstatus: done\nreported_at: %s\n---\n# DBG-101\n转出至：CHR-101（规格空白，待产品确认）\n' "$(today_iso)" > "$Q4/archive/auto-20260801/DBG-101/issue.md"
printf -- '---\nid: CHR-101\nsummary: 待产品确认 Q 的语义\nstatus: open\nreported_at: %s\n---\n# CHR-101\n来源：DBG-101（规格空白转出）\n' "$(today_iso)" > "$C4/CHR-101/item.md"
OUT_ARC="$(/usr/bin/python3 "$CLI" --cwd "$T4" check-transfers 2>&1)"
RC_ARC="$?"
has "归档源被找到、互链通过" "$OUT_ARC" "OK"
[ "$RC_ARC" = "0" ] && ok "归档源 exit 0" || bad "归档源应 exit 0" "0" "$RC_ARC"

echo "[198] 归档的源 DBG 缺反向转出标记 → exit 2（归档不解除互链义务）"
mkdir -p "$Q4/archive/auto-20260801/DBG-102" "$C4/CHR-102"
printf -- '---\nid: DBG-102\nsummary: 已关闭但归档时没写互链\nstatus: done\nreported_at: %s\n---\n# DBG-102\n' "$(today_iso)" > "$Q4/archive/auto-20260801/DBG-102/issue.md"
printf -- '---\nid: CHR-102\nsummary: 待产品确认 R 的语义\nstatus: open\nreported_at: %s\n---\n# CHR-102\n来源：DBG-102（规格空白转出）\n' "$(today_iso)" > "$C4/CHR-102/item.md"
OUT_ARC2="$(/usr/bin/python3 "$CLI" --cwd "$T4" check-transfers 2>&1)"
RC_ARC2="$?"
has "报出归档源缺反向标记" "$OUT_ARC2" "CHR-102 为 open、声明来源 DBG-102，但 DBG-102 正文没有反向写「转出至：CHR-102」"
[ "$RC_ARC2" = "2" ] && ok "归档源缺反向标记 exit 2" || bad "归档源缺反向标记应 exit 2" "2" "$RC_ARC2"

echo "[199] DBG 转出至已归档的 CHR → exit 0（去向归档同样能找到，互链仍成对）"
rm -rf "$C4/CHR-102" "$Q4/archive/auto-20260801/DBG-102"
mkdir -p "$Q4/DBG-103" "$C4/archive/auto-20260801/CHR-103"
printf -- '---\nid: DBG-103\nsummary: 已关闭转出\nstatus: done\nreported_at: %s\n---\n# DBG-103\n转出至：CHR-103（规格空白，待产品确认）\n' "$(today_iso)" > "$Q4/DBG-103/issue.md"
printf -- '---\nid: CHR-103\nsummary: 待产品确认 S 的语义\nstatus: done\nreported_at: %s\n---\n# CHR-103\n来源：DBG-103（规格空白转出）\n' "$(today_iso)" > "$C4/archive/auto-20260801/CHR-103/item.md"
OUT_ARC3="$(/usr/bin/python3 "$CLI" --cwd "$T4" check-transfers 2>&1)"
RC_ARC3="$?"
has "归档去向被找到、互链通过" "$OUT_ARC3" "OK"
[ "$RC_ARC3" = "0" ] && ok "归档去向 exit 0" || bad "归档去向应 exit 0" "0" "$RC_ARC3"
rm -rf "$T4"
