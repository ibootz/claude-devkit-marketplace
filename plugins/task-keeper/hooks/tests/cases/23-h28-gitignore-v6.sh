# H28 · 入库策略的 gitignore 判据（v6 2026-08-10 用户拍板队列入库；v7 2026-08-18 补第四条
# 精确排除 `.keeper/**/.merge.lock*`）。
#
# 【为什么这一节必须存在】v4→v5→v6 三次反转，每次都改同一组常量与同一段冷启动 bash，
# 而在本节写出来之前**没有任何测试覆盖它们**——改错的表现是「队列悄悄没进版本库」或
# 「本机状态文件天天产生 diff」，两者都不报错、都要等人某天发现。
#
# 【锁两组东西】
#   (a) 逐字同步：`queue_snapshot.GITIGNORE_BLOCK` 与冷启动 bash 里那条 `printf` 的
#       字节必须完全相同。这条纪律的成因是实测过的——两个分支各自在 EOF 追加**内容
#       不同**的注释即产生合并冲突；逐字相同则 git 视为同一处改动。
#       **落点会搬家，所以文件清单写成变量**：v6 时那条 printf 在两个 agent 定义里，
#       现在搬到了 `skills/tk-debug/references/cold-start.md`。清单写死在这里、搬家时
#       一起改，比让断言去全仓搜 printf 稳——全仓搜会把 README 里的示例代码块也算进来。
#   (b) `gitignore_findings` 的五种配置：正确 / v5 整树行残留（即使四条都在也要报，
#       因为它覆盖一切且静默）/ 缺其中几条 / 完全没有 .gitignore。
# 依赖 harness.sh 的 ok/bad/has。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无。

echo
echo "== H28 · gitignore 判据（默认入库，只精确排除四类本机产物）=="

PLUGIN_DIR="$(cd "$HOOK_DIR/.." && pwd)"

echo "[121] 逐字同步：GITIGNORE_BLOCK 与冷启动 bash 的 printf 字节相同"
SYNC="$(/usr/bin/python3 -c '
import io, re, sys
sys.path.insert(0, sys.argv[1])
from queue_snapshot import GITIGNORE_BLOCK
# printf 行的落点清单。搬家时改这里；每个文件都必须**恰好**有一条，多一条同样是
# 失效信号——两条 printf 意味着有人复制了一份忘了删，两份日后必然各自漂移。
TARGETS = ("skills/tk-debug/references/cold-start.md",)
pat = re.compile(r"printf \x27([^\x27]*)\x27 >> \"\$GI\"")
bad = []
for rel in TARGETS:
    try:
        t = io.open(sys.argv[2] + "/" + rel, encoding="utf-8").read()
    except Exception:
        bad.append("%s: 读不到这个文件（printf 是不是又搬家了？）" % rel)
        continue
    m = pat.findall(t)
    if len(m) != 1:
        bad.append("%s: printf 行 %d 条（预期 1）" % (rel, len(m)))
    elif m[0].replace("\\n", "\n") != GITIGNORE_BLOCK:
        bad.append("%s: 与 GITIGNORE_BLOCK 不一致" % rel)
print("SYNCED" if not bad else " / ".join(bad))
' "$LIBDIR" "$PLUGIN_DIR")"
if [ "$SYNC" = "SYNCED" ]; then ok "冷启动 printf 与 GITIGNORE_BLOCK 逐字一致"
else bad "gitignore 文案必须逐字同步（分支各自追加不同注释会冲突）" "SYNCED" "$SYNC"; fi

echo "      并核对条数措辞：BLOCK 首行注释里的「N 类」必须等于 GITIGNORE_RULES 的实际条数"
# 【为什么单独测这个数】它是**最容易漂的一处**：加一条规则时改了 RULES 与 pattern 行，
# 却忘了改注释里的中文数字——而那行注释会被逐字写进每个用户仓库的 .gitignore，
# 说「三类」却排了四条，读的人无从判断是漏了一条还是注释旧了。
CNTOK="$(/usr/bin/python3 -c '
import re, sys
sys.path.insert(0, sys.argv[1])
from queue_snapshot import GITIGNORE_BLOCK, GITIGNORE_RULES
CN = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八"}
head = GITIGNORE_BLOCK.strip("\n").split("\n")[0]
want = "只排除%s类本机产物" % CN.get(len(GITIGNORE_RULES), "?")
body = [l for l in GITIGNORE_BLOCK.strip("\n").split("\n")[1:] if l.strip()]
print("OK" if want in head and len(body) == len(GITIGNORE_RULES)
      else "注释=[%s] 期望含[%s]；pattern 行 %d 条 vs 规则 %d 条"
           % (head, want, len(body), len(GITIGNORE_RULES)))
' "$LIBDIR")"
if [ "$CNTOK" = "OK" ]; then ok "首行注释的条数措辞与 pattern 行数、规则条数三者一致"
else bad "BLOCK 的条数措辞与实际规则条数不符" "OK" "$CNTOK"; fi

echo "[122] 写入的各行内容正确：worktree / instance.json / merge.lock 用 \`**\`，"
echo "      .keeper-active 是顶层单文件**不带** \`**\`（照抄 ** 写法会匹配不到它）"
BLOCK="$(/usr/bin/python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
from queue_snapshot import GITIGNORE_BLOCK
print(GITIGNORE_BLOCK.strip("\n"))
' "$LIBDIR")"
has "worktree 用 ** 通配中间层" "$BLOCK" ".keeper/**/worktree/"
has "instance.json 用 ** 通配中间层" "$BLOCK" ".keeper/**/.keeper-instance.json"
has "keeper-active 是顶层单文件、不带 **" "$BLOCK" ".keeper/.keeper-active"
# v7 第四条。末尾那个 `*` 是判据的一部分，不是随手加的通配：抢占一把超时锁时旧锁目录
# 会被改名成 `.merge.lock.stale-<旧持有者>` 留在原地当诊断现场，写成 `.merge.lock/`
# 匹配不到这个残留 → 抢占路径上仍有未跟踪目录 → merge-back 前置校验判脏树 →
# **抢到锁的那个实例照样合不了**。所以这里连 `*` 一起断言。
has "merge.lock 用 ** 通配中间层，且末尾带 * 以覆盖 .stale- 抢占残留" "$BLOCK" ".keeper/**/.merge.lock*"
case "$BLOCK" in
  *'.keeper/**/.keeper-active'*)
    bad ".keeper-active 不该写成 ** 形式（它是顶层单文件，** 匹配不到）" \
        "不含 .keeper/**/.keeper-active" "$BLOCK" ;;
  *) ok ".keeper-active 没被误写成 ** 形式" ;;
esac

# 探针：造一个临时仓，把给定内容写进 .gitignore，返回告警条数与全文
probe_gi() {
  /usr/bin/python3 -c '
import os, sys, tempfile
sys.path.insert(0, sys.argv[1])
from queue_snapshot import gitignore_findings, GITIGNORE_BLOCK, GITIGNORE_RULES
d = tempfile.mkdtemp()
q = os.path.join(d, ".keeper", "_main", "debug")
os.makedirs(q)
mode = sys.argv[2]
# `no_lock` 从 GITIGNORE_RULES 现算「除合并锁外全都在位」，不写死另外三条 pattern——
# 写死的话，日后再加第五条规则时这个 fixture 会悄悄变成「缺两条」，用例红了却指向
# 一个与合并锁无关的原因。
no_lock = "".join("%s\n" % pat for _why, pat, _ok in GITIGNORE_RULES
                  if ".merge.lock" not in pat)
content = {
    "ok": GITIGNORE_BLOCK,
    "legacy": ".keeper/\n",
    "both": ".keeper/\n" + GITIGNORE_BLOCK,
    "partial": ".keeper/**/worktree/\n",
    "no_lock": no_lock,
    "none": None,
}[mode]
if content is not None:
    open(os.path.join(d, ".gitignore"), "w").write(content)
out = gitignore_findings(q)
print(len(out))
for line in out:
    print(line)
' "$LIBDIR" "$1"
}

echo "[123] 正确配置（当前 BLOCK 全文）→ 0 条告警（误杀侧：配对了就不许再唠叨）"
N="$(probe_gi ok | head -1)"
if [ "$N" = "0" ]; then ok "正确配置零告警"
else bad "正确配置不应有告警" "0" "$N"; fi

echo "[124] v5 整树忽略行残留 → 必须报，**即使四条精确规则都已在位**"
echo "      （它覆盖一切且静默生效：git 不会说「你的精确规则被盖住了」）"
OUT="$(probe_gi both)"
N="$(printf '%s\n' "$OUT" | head -1)"
if [ "$N" = "1" ]; then ok "整树行与四条并存时仍报 1 条（只报整树那条）"
else bad "整树行残留必须报，即使四条都在" "1" "$N"; fi
has "告警点名整树忽略行" "$OUT" "整树忽略行"
has "告警说明它不报错这一失效特征" "$OUT" "不会有任何报错"

echo "[125] 缺规则时逐条报，且报出缺的是哪几条（只写了 worktree → 还缺 3 条）"
OUT="$(probe_gi partial)"
has "报出缺 3 条" "$OUT" "缺 3 条精确排除"
has "点名缺的是 instance.json" "$OUT" ".keeper/**/.keeper-instance.json"
has "点名缺的是 keeper-active" "$OUT" ".keeper/.keeper-active"
has "点名缺的是 merge.lock" "$OUT" ".keeper/**/.merge.lock*"
case "$OUT" in
  *'.keeper/**/worktree/'*)
    bad "已在位的 worktree 那条不该出现在缺失清单里" "不含 worktree 条目" "$OUT" ;;
  *) ok "已在位的那条不重复报" ;;
esac

echo "[126] 完全没有 .gitignore → 报缺 4 条（不是崩溃、也不是静默放行）"
OUT="$(probe_gi none)"
has "无 .gitignore 时报缺 4 条" "$OUT" "缺 4 条精确排除"

echo "[127] v5 的整树忽略行**不再**被当成期望配置（判据方向相对 v5 整体反转）"
OUT="$(probe_gi legacy)"
N="$(printf '%s\n' "$OUT" | head -1)"
if [ "$N" = "2" ]; then ok "只有整树行时报 2 条（整树行要删 + 四条都缺）"
else bad "只有 v5 整树行时应报 2 条" "2" "$N"; fi

# 【编号跳到 [179]】本条是 v7 补的，编号接在 H30 之后取全局唯一值，而不是插进
# [121]-[127] 中间——编号是历史坐标，插号会让「第 N 条用例」这种跨版本指代对不上。
echo "[179] 合并锁那条的两侧：缺它要点名它、四条齐备则一声不吭"
# 【为什么值得单独一条】前三条是 v6 就有的，任何整块照抄旧 BLOCK 的仓库都会**只缺
# 这一条**——那正是升级到 v7 之后最常见的真实状态。而缺它的后果是自伤且反直觉：
# merge-back 前置校验要求父仓干净，持锁期间锁目录被 git 看见就判脏树，于是
# **拿了锁反而合不了**，锁把自己锁死。所以这条必须被点名，不能淹在「缺 N 条」里。
OUT="$(probe_gi no_lock)"
has "只缺合并锁时报缺 1 条" "$OUT" "缺 1 条精确排除"
has "点名缺的正是合并锁那条" "$OUT" ".keeper/**/.merge.lock*"
has "告警说明它是运行态产物、会让前置校验误判脏树" "$OUT" "merge-back"
# 误杀侧：另外三条已在位，不许被重复报进缺失清单。
case "$OUT" in
  *'.keeper/**/worktree/'*|*'.keeper/**/.keeper-instance.json'*|*'.keeper/.keeper-active'*)
    bad "已在位的另外三条不该出现在缺失清单里" "只点名 merge.lock" "$OUT" ;;
  *) ok "已在位的另外三条不重复报（误杀侧）" ;;
esac
# 四条齐备时一条告警都没有——这一侧与 [123] 同源，但这里要的是「补上 merge.lock
# 之后告警确实归零」，证明判据认的就是这条 pattern 本身，而不是碰巧数量对上了。
N="$(probe_gi ok | head -1)"
if [ "$N" = "0" ]; then ok "补齐合并锁那条后告警归零"
else bad "四条齐备应零告警" "0" "$N"; fi
