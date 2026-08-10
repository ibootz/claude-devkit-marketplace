# H28 · v6 入库策略的 gitignore 判据（2026-08-10 用户拍板：队列入库，只排除三类本机产物）。
#
# 【为什么这一节必须存在】v4→v5→v6 三次反转，每次都改同一组常量与同一段冷启动 bash，
# 而在本节写出来之前**没有任何测试覆盖它们**——改错的表现是「队列悄悄没进版本库」或
# 「本机状态文件天天产生 diff」，两者都不报错、都要等人某天发现。
#
# 【锁两组东西】
#   (a) 三处逐字同步：`queue_snapshot.GITIGNORE_BLOCK` 与两个 agent 定义里 printf 的
#       字节必须完全相同。这条纪律的成因是实测过的——两个分支各自在 EOF 追加**内容
#       不同**的注释即产生合并冲突；逐字相同则 git 视为同一处改动。人工同步三处极易
#       漏一处，且漏了要等下次分支合并才炸。
#   (b) `gitignore_findings` 的五种配置：正确 / v5 整树行残留（即使三条都在也要报，
#       因为它覆盖一切且静默）/ 缺其中几条 / 完全没有 .gitignore。
# 依赖 harness.sh 的 ok/bad/has。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无。

echo
echo "== H28 · v6 gitignore 判据（默认入库，只精确排除三类本机产物）=="

AGENTS_DIR="$(cd "$HOOK_DIR/../agents" && pwd)"

echo "[121] 三处逐字同步：GITIGNORE_BLOCK 与两个 agent 冷启动 bash 的 printf 字节相同"
SYNC="$(/usr/bin/python3 -c '
import io, re, sys
sys.path.insert(0, sys.argv[1])
from queue_snapshot import GITIGNORE_BLOCK
pat = re.compile(r"printf \x27([^\x27]*)\x27 >> \"\$GI\"")
bad = []
for f in ("debug-keeper.md", "chore-keeper.md"):
    t = io.open(sys.argv[2] + "/" + f, encoding="utf-8").read()
    m = pat.findall(t)
    if len(m) != 1:
        bad.append("%s: printf 行 %d 条（预期 1）" % (f, len(m)))
    elif m[0].replace("\\n", "\n") != GITIGNORE_BLOCK:
        bad.append("%s: 与 GITIGNORE_BLOCK 不一致" % f)
print("SYNCED" if not bad else " / ".join(bad))
' "$LIBDIR" "$AGENTS_DIR")"
if [ "$SYNC" = "SYNCED" ]; then ok "两个 agent 的 printf 与 GITIGNORE_BLOCK 逐字一致"
else bad "三处 gitignore 文案必须逐字同步（分支各自追加不同注释会冲突）" "SYNCED" "$SYNC"; fi

echo "[122] 写入的四行内容正确：worktree 与 instance.json 用 \`**\`，"
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
from queue_snapshot import gitignore_findings, GITIGNORE_BLOCK
d = tempfile.mkdtemp()
q = os.path.join(d, ".keeper", "_main", "debug")
os.makedirs(q)
mode = sys.argv[2]
content = {
    "ok": GITIGNORE_BLOCK,
    "legacy": ".keeper/\n",
    "both": ".keeper/\n" + GITIGNORE_BLOCK,
    "partial": ".keeper/**/worktree/\n",
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

echo "[123] 正确配置（v6 四行）→ 0 条告警"
N="$(probe_gi ok | head -1)"
if [ "$N" = "0" ]; then ok "正确配置零告警"
else bad "v6 正确配置不应有告警" "0" "$N"; fi

echo "[124] v5 整树忽略行残留 → 必须报，**即使三条精确规则都已在位**"
echo "      （它覆盖一切且静默生效：git 不会说「你的精确规则被盖住了」）"
OUT="$(probe_gi both)"
N="$(printf '%s\n' "$OUT" | head -1)"
if [ "$N" = "1" ]; then ok "整树行与三条并存时仍报 1 条（只报整树那条）"
else bad "整树行残留必须报，即使三条都在" "1" "$N"; fi
has "告警点名整树忽略行" "$OUT" "整树忽略行"
has "告警说明它不报错这一失效特征" "$OUT" "不会有任何报错"

echo "[125] 缺规则时逐条报，且报出缺的是哪几条（只写了 worktree → 还缺 2 条）"
OUT="$(probe_gi partial)"
has "报出缺 2 条" "$OUT" "缺 2 条精确排除"
has "点名缺的是 instance.json" "$OUT" ".keeper/**/.keeper-instance.json"
has "点名缺的是 keeper-active" "$OUT" ".keeper/.keeper-active"
case "$OUT" in
  *'.keeper/**/worktree/'*)
    bad "已在位的 worktree 那条不该出现在缺失清单里" "不含 worktree 条目" "$OUT" ;;
  *) ok "已在位的那条不重复报" ;;
esac

echo "[126] 完全没有 .gitignore → 报缺 3 条（不是崩溃、也不是静默放行）"
OUT="$(probe_gi none)"
has "无 .gitignore 时报缺 3 条" "$OUT" "缺 3 条精确排除"

echo "[127] v5 的整树忽略行**不再**被当成期望配置（判据方向相对 v5 整体反转）"
OUT="$(probe_gi legacy)"
N="$(printf '%s\n' "$OUT" | head -1)"
if [ "$N" = "2" ]; then ok "只有整树行时报 2 条（整树行要删 + 三条都缺）"
else bad "只有 v5 整树行时应报 2 条" "2" "$N"; fi
