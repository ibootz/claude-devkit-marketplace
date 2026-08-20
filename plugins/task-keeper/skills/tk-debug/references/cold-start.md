# 冷启动：建队列目录与补 .gitignore 四条

> 本文件从 `agents/debug-keeper.md` §3 下推。keeper 第一次在某个 worktree 接手 debug 队列时照此执行；
> 入库策略的演变史见 `references/history.md` §1。
> chore-keeper 的冷启动逻辑与本文件同一份（`.gitignore` 四条逐字一致），后续会统一指向这里。

## 什么时候跑

当前 worktree 根下没有 `.keeper/<交付id>/debug/` 目录时。已存在说明之前跑过，跳过整段。

## 建目录

```bash
# ROOT 必须这样算：先跳出 submodule，再取当前 worktree 根。
# 直接 `git rev-parse --show-toplevel` 在 submodule 里会返回 submodule 根而不是宿主
# 工作区根；判据与 hooks/lib/keeper_paths.py 的 find_worktree_root 保持一致。
SUP="$(git -C . rev-parse --show-superproject-working-tree)"
ROOT="$(git -C "${SUP:-.}" rev-parse --show-toplevel)"
DID="$(basename "$ROOT")"
case "$DID" in D-[0-9]*-*|hotfix-*) ;; *) DID="_main" ;; esac   # 非交付 worktree 落兜底桶

mkdir -p "$ROOT/.keeper/$DID/debug" "$ROOT/.keeper/$DID/debug/_inbox"
# ↑ 只要 .keeper/ 顶层已存在，"$ROOT/.keeper/$DID/debug" 本身每轮已由
#   UserPromptSubmit hook（find_queue 自动补建，见 hooks/lib/queue_snapshot.py
#   的 docstring「为什么自动补建」）建好，这里的 mkdir -p 对它只是幂等兜底
#   （覆盖 hook 未生效的环境）。但 "_inbox/" 不在自动补建范围内——自动补建只建
#   debug/ 与 chore/ 两个队列目录本身，_inbox/ 仍要靠这一行手工建，跳过这行会让
#   截图落盘目标缺失。
```

## 确保 .gitignore 四条精确排除在位

当前生效策略（v6）：**正文与附件入库，只精确排除四类本机产物**。冷启动时缺就整块补写。

```bash
# 确保四条精确排除在位；缺就整块补写
GI="$ROOT/.gitignore"
# v5 的整树忽略行若还在，它会覆盖下面四条、让队列继续不入库，且**不会有任何报错**
if grep -qxF '.keeper/' "$GI" 2>/dev/null; then
  echo "ACTION: $GI 里还有 v5 的 '.keeper/' 整树忽略行，它覆盖四条精确规则——按 §12 上报请用户拍板删除"
fi
# 四行一起追加，用第一条当哨兵（有它就有另三条，因为只可能整块写入）
if ! grep -qxF '.keeper/**/worktree/' "$GI" 2>/dev/null; then
  printf '\n# task-keeper 队列：正文与附件入库，只排除四类本机产物\n.keeper/**/worktree/\n.keeper/**/.keeper-instance.json\n.keeper/.keeper-active\n.keeper/**/.merge.lock*\n' >> "$GI"
fi
# 回读验证：**验行为不验文本**——写对了不等于 git 按它生效（已跟踪的文件就是反例）
git -C "$ROOT" check-ignore -q ".keeper/$DID/debug/index.md" \
  && echo "FAILED: 队列文本仍被忽略——检查是不是整树行还在" \
  || echo "OK: 队列文本不再被忽略"
git -C "$ROOT" check-ignore -q ".keeper/$DID/.keeper-instance.json" \
  && echo "OK: 实例登记已排除" \
  || echo "FAILED: 写入 $GI 失败，停下人工处理"
```

### 四条 pattern 的写法纪律

**注释与那四条 pattern 必须逐字照抄，不许自由发挥。** 实测过两个分支各自在 EOF 追加**内容不同**的注释即产生合并冲突。文案固定之后，各分支追加的字节逐字相同，git 合并时视为同一处改动、不冲突。理想情况是这五行一次性提交到主分支，各交付分支的 `grep -qxF` 直接命中、什么都不写。

**`.keeper-active` 那条不带 `**`**，不要照抄 worktree 那条的写法——它是 `.keeper/` 顶层的单文件，不是每交付一份；写成 `.keeper/**/.keeper-active` 匹配不到它。反过来另三条**必须用 `**`** 而不是写死中间层（`.keeper/*/debug/*/worktree/`）——兜底桶 `_main` 与交付桶层级数虽相同，但写死中间层在嵌套变化时会漏网。

### 四条分别排除什么

- **入库**：issue、receipts、index、decisions、截图与附件。
- **排除**：
  - `worktree/`（入库会种野生 gitlink）
  - `.keeper-instance.json`（含 `session_id` 与随机 agent name，跨机器无意义、多人并行必冲突）
  - `.keeper-active`（本机活跃交付指针）
  - `.merge.lock*`（合并锁与抢占后留下的 `.merge.lock.stale-<旧持有者>` 诊断现场，都是运行态。**被 git 看见会让 merge-back 的前置校验判脏树，拿了锁反而合不了**；末尾的 `*` 不能省，否则匹配不到 stale 残留）

### v5 整树忽略行残留的处置

若冷启动检出 v5 的 `.keeper/` 整树忽略行还在——**不要自己删它**。删掉会让存量队列一次性变成待提交、把历史 bug 细节与截图一次推上远端。按 §12 上报请 Human 拍板删除。

## 回读验证不能跳过

改完 `.gitignore` 必须 `grep` 回来确认那几行真的落在文件里，理由与「截图落盘必须回读」（`references/screenshot.md`）同源。`queue_snapshot.py`（每轮 hook）的 `gitignore_findings` 也做同一组检查，但那是兜底、不是跳过这一步的理由——hook 提醒发生在下一轮，冷启动这一刻你能立刻做完。

## v6 连带代价：截图脱敏升级为红线

v5 时截图不进 git 历史，脱敏是额外防线；v6 起它会被正常收录并**随 push 公开到远端**。keeper 没有图像编辑能力、打不了码，所以**「不落盘」是唯一那道机械闸**——判据与三步处置见 `references/screenshot.md` §4。撞到含 token / 密码 / 手机号 / 身份证 / 真实客户机构名 / 产线金额的图，一律转文字、敏感值写 `<脱敏>`，不要落盘。

## ugrep 的静默零命中只影响 worktree/ 内部

Claude Code 把 `grep` 影子成自带 ugrep 且参数写死 `--ignore-files`（`~/.claude/shell-snapshots/snapshot-zsh-*.sh:5160`），被 ignore 的文件**静默零命中、不报错**。v6 起队列文本已入库，从仓库根搜正常命中，**只有 `worktree/` 里的内容仍需把搜索根设进去**。

> 判据来自 2026-08-01 实测：ugrep 只读递归下降途中遇到的 `.gitignore`，**不向上找**。

`Read` 不走 grep，任何时候都正常。拿不准时用 `Read` 或 `ls` 正面列举，**不要用否定式检索得出「队列里没有这条」**——那个「没有」可能是假的。

## 目录最终形态

`<交付id>` = worktree 根 basename，非交付一律 `_main`：

```
.keeper/
├── .keeper-active            ← 单行文本，当前活跃交付目录名。解析器自动写入自愈
└── <交付id>/
    ├── debug/                ← debug-keeper 管理
    │   ├── index.md          ← hook 每轮重算的派生视图，不要手改
    │   ├── _inbox/           ← 未分配 DBG-id 的截图暂存区
    │   ├── DBG-NNN/
    │   │   ├── issue.md      ← 数据源，唯一信源
    │   │   ├── receipts.md   ← fixer 的交付回执
    │   │   ├── *.png         ← 报告截图（主会话落盘、已脱敏）
    │   │   └── worktree/     ← 派发用的 git worktree（§6）
    │   └── archive/<批次>/<DBG-id>/   ← 按批次归档的 done 条目（§9），整目录搬
    ├── decisions/            ← 待拍板协议用（§12），keeper 写、主会话只读+写 answers/
    │   ├── <stamp>-debug-keeper.md
    │   └── answers/<同名>.md
└── chore/                    ← chore-keeper 管，不归 debug-keeper 写
```

**这条断言只管单个 `DBG-NNN/` 目录内部**：里面只放四样（issue.md / receipts.md / 截图 / worktree/），不要新建第五种混合职责的文件。队列级的 `index.md` 与 `archive/` 是 `DBG-NNN/` 的兄弟、不在这四样里；`_inbox/` / `decisions/` / `chore/` 层级更高，同样不受这条约束。

## 队列数据的 L1 豁免（仅装了 dc:quality-lint 的项目）

判据：项目根有 `.deepcritique/` 目录。有则冷启动时顺手建一份豁免 `.keeper/**` 的 profile，落点 `<项目根>/.deepcritique/profiles/keeper-queue-exempt.js`；没有那个目录就跳过本节，不要凭空创建。

不建的后果：队列文件一旦超 500 行，此后每次 `Edit` / `Write` 的 PostToolUse 都以退出码 2 收场。可直接照抄的文件内容、三个会静默失效的坑（name 撞名 / priority 排序 / `**` 写法）与回读验法，见 `references/queue.md` 的「队列数据要豁免 L1 行数检查」一节。

这份 profile 落在项目根的 `.deepcritique/profiles/`，**不在 `.keeper/` 里面**，所以它不构成上面那条「只放四样」的第五样。
