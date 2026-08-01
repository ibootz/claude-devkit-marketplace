# H7 · 截图证据路径守卫（写 issue 文件时拦 image-cache 路径）。
# 依赖 harness.sh 的 ok/bad/has/hasnt；HOOK_DIR 由 run-tests.sh 提供。
# 本节自己定义 EVD / run_evd（只在本文件内使用，不被其他 case 文件依赖）。
# 本文件由 run-tests.sh source 执行，不要单独 `bash` 它。
# 【节间耦合】无——本文件不依赖任何其他 case 文件留下的变量或函数。

echo
echo "== H7 · 截图证据路径守卫（写 issue 文件时拦 image-cache 路径）=="
# 【判据】写入目标从 .keeper/debug/issues.yaml（v2）→ .keeper/debug/issues/<DBG-id>.md（v3）
# → .keeper/<交付id>/debug/<DBG-id>/issue.md（v4 一交付一目录，<交付id> 含兜底桶 _main）；
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

# v4 布局：一个真实交付目录 + 兜底桶 _main，DBG-id 是目录、issue.md 是固定文件名。
Q_MD="/repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-001/issue.md"
Q_MD_MAIN="/repo/.keeper/_main/debug/DBG-001/issue.md"
P_BAD="- \`/Users/me/.claude/image-cache/abc-123/1.png\`"
P_OK="- \`/repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-001/01-header.png\`"

echo "[25] 范围极窄：非 issue 文件的写入、以及已废弃的 v3 布局字面量，一律零成本放行"
OUT="$(run_evd Write /repo/src/Foo.java content "$P_BAD" EVDTEST1)"
if [ -z "$OUT" ]; then ok "写源码文件不介入（即使内容含 image-cache 字样）"
else bad "非队列文件应放行" "空" "$OUT"; fi
OUT="$(run_evd Write /repo/docs/note.md content "$P_BAD" EVDTEST1)"
if [ -z "$OUT" ]; then ok "写其他 md 不介入"
else bad "非队列文件应放行" "空" "$OUT"; fi
OUT="$(run_evd Write /repo/.keeper/D-001-feat-job-sequence-model/debug/index.md content "$P_BAD" EVDTEST1)"
if [ -z "$OUT" ]; then ok "写 index.md 不介入（它是派生物，不承载证据）"
else bad "index.md 应放行" "空" "$OUT"; fi
OUT="$(run_evd Write /repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-001/receipts.md content "$P_BAD" EVDTEST1)"
if [ -z "$OUT" ]; then ok "同一 DBG-id 目录下的 receipts.md 不介入（只锁 issue.md 这一个文件名）"
else bad "receipts.md 应放行" "空" "$OUT"; fi
OUT="$(run_evd Write /repo/.keeper/debug/issues/DBG-001.md content "$P_BAD" EVDTEST1)"
if [ -z "$OUT" ]; then ok "旧 v3 布局字面量（.keeper/debug/issues/）不再命中——迁移是排他式的"
else bad "旧 v3 布局应放行" "空" "$OUT"; fi

echo "[26] 判据：issue 文件里的 image-cache 路径 → deny，并给出两条可达出路（覆盖有交付与 _main 兜底两种深度）"
OUT="$(run_evd Write "$Q_MD" content "$P_BAD" EVDTEST2)"
has "返回 deny 而非 ask" "$OUT" '"permissionDecision": "deny"'
has "指出会 404"         "$OUT" "404"
has "出路1：cp 到同目录" "$OUT" "本条 issue 自己的目录"
has "出路2：不写路径只转录"    "$OUT" "不要写任何图片路径"
has "提示必须回读验证"   "$OUT" "回读验证"
OUT="$(run_evd Write "$Q_MD_MAIN" content "$P_BAD" EVDTEST2M)"
has "_main 兜底桶下的 issue.md 同样命中 deny" "$OUT" '"permissionDecision": "deny"'

echo "[27] 合规写法与出路二都必须放行（判据存在可达的通过态 · DBG-007 教训）"
OUT="$(run_evd Write "$Q_MD" content "$P_OK" EVDTEST3)"
if [ -z "$OUT" ]; then ok "同目录下的副本路径放行（v4 无独立 attachments 子目录，截图与 issue.md 平级）"
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

- `/repo/.keeper/D-001-feat-job-sequence-model/debug/DBG-001/01-x.png`
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
