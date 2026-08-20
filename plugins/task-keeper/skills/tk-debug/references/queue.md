# 队列结构 · 派发 · 对账（schema v3）

## 目录

本文较长，按需查阅——先在本节定位要读的章节，再用
`grep -n '^##\|^### ' references/queue.md` 跳到对应行。

- **§1 文件布局**——`.keeper/<交付id>/debug/` 目录结构、哪些入库哪些不入库、
  worktree 落点
- **§2 issue 文件格式**——frontmatter 9 键、正文章节、`status` 为什么只有二值
- **§3 三维打分**——`priority`/`difficulty`/`type` 各自的消费者；为什么都不决定派发
  顺序；reopen 升级阶梯
- **§4 派发：一 issue 一 worktree**——全文最大的一节
  - gitlink 铁律（贯穿本文多处，先在这里讲一次）
  - 派发步骤（`wt_supply.py init`、为什么不用 `isolation`/`cwd`、供给范围不裁剪）
  - 两轨派发：`easy` → 一次性 subagent；`medium`/`hard` → 交互式 subagent（各附
    prompt 模板）
  - 修复前比对确认（headless `agent-browser`）、模型分层表、并行度上限
- **§5 合并前对账**——三件套判据（幽灵改动 / 幻觉回执 / 量级偏离）与它抓不到什么
- **§6 收尾**——`merge-back` 前先 commit gitlink、回流本体、归档、合并后统一实测、
  外部工单回写（通用契约）、reject 之后
- **§7 什么时候不适用本文**

---

本文合并了 v2 的 `schema.md` / `dispatch.md` / `reconcile.md`。合并的原因不是嫌文件
多，而是那三份里各有一半篇幅在描述**已经删除的东西**：`stage` 三态、`in_progress`
记账、`affected_files` 文件锁、互斥调度、饥饿让位。删干净之后剩下的内容不足以各自
成篇。

## 1. 文件布局

```
<worktree 根>/.keeper/
├── .keeper-active           单行文本，当前活跃交付目录名。解析器自动写入自愈
└── <交付id>/                worktree 根 basename；非交付 worktree 一律 `_main`
    ├── debug/
    │   ├── index.md         派生视图。hook 每轮重算，人和 AI 共用。入库，不要手改
    │   ├── _inbox/          主会话刚落盘、还没分配 DBG-id 的截图（v6 起入库；登记时 mv 进 <DBG-id>/）
    │   ├── DBG-017/         **一 issue 一目录**——四样全在这里；index.md 与 archive/ 在上一层
    │   │   ├── issue.md     唯一信源。入库
    │   │   ├── receipts.md  fixer 的交付回执。入库，由 fixer commit 进自己分支
    │   │   ├── 01-xxx.png   登记后从 _inbox/ mv 到这里。落盘但**不入库**
    │   │   └── worktree/    派发用的 git worktree（§4）。**不入库**
    │   └── archive/         按交付批次归档的 done 条目（§6「归档」），整目录搬
    │       └── D-001-feat-xxx/
    │           └── DBG-005/{issue.md, receipts.md, *.png}
    ├── decisions/           keeper 与主会话的 HITL 通道（agents/debug-keeper.md §12）
    │   └── answers/
    └── chore/               另一个 keeper 管，不归本文档
```

**`<交付id>` 怎么算**：由 `hooks/lib/keeper_paths.py` 解析——先
`git rev-parse --show-superproject-working-tree` 跳出 submodule、fixer worktree 经
`<git-dir>/wt-supply-source` 回溯到 delivery、再取 `--show-toplevel` 的 basename，
匹配 `^(?:D-\d+-|hotfix-)` 才算交付，否则落固定兜底桶 `_main`。**不要**自己写成
「从 cwd 向上找 `.keeper`、遇 `.git` 停」——linked worktree 根自己就有一个 `.git`
文件，那样第一轮就返回 None，aisdlc 交付跑在 `.sdlc/worktrees/D-NNN-<slug>/` 里时
队列恒为空，而冷启动不检测外层已有队列、直接 mkdir 出第二份（实测两份各缺一半）。

**这条断言只管单个 `DBG-NNN/` 目录内部**——它里面只有那四样。队列级的 `index.md` 与
`archive/` 是 `DBG-NNN/` 的兄弟、不在其中；`_inbox/` / `decisions/` / `chore/` 层级更
高，同样不受这条约束。
v3 把 issue / receipts / attachments / worktree 分散在四棵平行子树里靠文件名对齐，
删一条要记得删四处——实际从来没删干净过。
v2 还有个 `journal.md` 装「跨 issue 的批次记录」，删除——它是 v2 `issues.yaml` 的
`meta` 段原样搬迁的产物，没做过归属重判，实测装的绝大部分是**单条 issue 的**决策与
对账（「DBG-002 走方案 1」「DBG-005 外延要一起去」），且没有任何 hook 读它写它校验
它。一个无机制保障、无人校验、内容大半该属于别人的手写 append-only 文件，会稳定长成
第二个 `issues.yaml`。批次信息按归属分流，**不要落在 `.keeper/debug/`**：属于某条
issue 的（Human 对它的拍板、它的落点与量级对账、它的字段变动）写进那条 issue 的
「修订记录」章节；真正跨 issue 的交付级事实（一次批量流转的结果、整个交付的 spec
delta、本次交付的台账）属于项目自己的交付文档体系（如仓库里的 `.sdlc/` 或等价
目录），`.keeper/debug/` 只装 bug 队列本身。

**队列正文与附件入库，只精确排除四类本机产物**（v7；前三类是 v6 2026-08-10 用户拍板，
第四类随合并锁在 v7 补入）。keeper 冷启动自动写入固定五行（注释与 pattern 逐字写死，
避免不同分支各自追加不同注释导致合并冲突）：

```gitignore
# task-keeper 队列：正文与附件入库，只排除四类本机产物
.keeper/**/worktree/
.keeper/**/.keeper-instance.json
.keeper/.keeper-active
.keeper/**/.merge.lock*
```

入库的是 `issue.md` / `receipts.md` / `index.md` / `decisions/` / 截图与附件；排除的
四类各有理由：`worktree/` 入库会种野生 gitlink；`.keeper-instance.json` 含 `session_id`
与当次 subagent 的随机 name，跨机器无意义且多人并行必冲突；`.keeper-active` 是本机
活跃交付指针；`.merge.lock*` 是合并锁的运行态。

第四条末尾那个 `*` 不能省。抢占一把超时锁时，旧锁目录会被改名成
`.merge.lock.stale-<旧持有者>` 留在原地当诊断现场，写成 `.merge.lock/` 只匹配得到锁
本身、匹配不到这个残留——于是抢占路径上仍会冒出未跟踪目录，merge-back 的前置校验判
脏树，**抢到锁的那个实例反而合不了**。

### 队列数据要豁免 L1 行数检查

**只对装了 `dc:quality-lint` 的项目适用。判据：项目根有 `.deepcritique/` 目录**——没有
就跳过本节，不要凭空创建那个目录。另一个信号是写完队列文件后 stderr 出现
`[L1-WARN] ... 500` 这类行数告警。

原因：dc 的内置 `fallback` profile 给一切 `**/*.md` / `**/*.yaml` / `**/*.json` 施 500
行上限，只排除 `node_modules/**` / `dist/**` / `.git/**`（`profiles/fallback.js` 的
`line-limit` check，`severity: 'warning'`）。那个上限是给**人写的文档**定的可读性阈值，
而队列数据只增不减——`index.md` 随条目数单调增长，`issue.md` 带行级锚点与多场景复现步
骤。为压行数删锚点，等于把派发修复时唯一有用的信息删掉。

**`warning` 不等于「只提示」**：hook 里 warning 一样置 `hasError = true`，末尾
`process.exit(hasError ? 2 : 0)`。所以每写一次超限的队列文件，那次 `Edit` / `Write` 的
PostToolUse 都以退出码 2 收场，不是刷一行日志了事。

冷启动时在 `<项目根>/.deepcritique/profiles/keeper-queue-exempt.js` 建这份文件，照抄：

```js
// dc:quality-lint 豁免 profile —— .keeper/ 下全部文件排除在 L1 检查之外。
// 理由：task-keeper 的队列数据（index.md / issue.md / receipts.md / item.md）随条目数
// 单调增长，不适用 fallback profile 给「人写文档」定的 500 行可读性上限。
// 只关 L1（机械行数与结构检查）；未声明 l2/loops，不影响任何 L2 评审能力。
module.exports = {
  name: 'keeper-queue-exempt',
  description: 'Exempt .keeper/ (task-keeper queue data) from L1 quality checks',
  priority: 10,

  l1: {
    paths: ['.keeper/**'],
    checks: []
  }
}
```

三个坑，写错任一条都是**静默不生效**——不报错、不警告，要等下次撞 exit 2 才发现：

1. **`name` 不能撞 dc 内置 profile 的名字**（当前是 `fallback` 与 `meta-docs`）。profile
   发现的顺序是「内置目录先扫、项目级后扫」，按 name 去重且**先加载者胜**，撞名的项目级
   profile 会被静默跳过。
2. **`priority` 必须严格小于 `fallback` 的 `100`**。profiles 按 priority 升序排，取第一个
   `included && !excluded` 的就 return——只有排在 fallback 前面，才短路得掉它的
   `line-limit`。取 `10`。
3. **必须写 `.keeper/**`，不能写 `.keeper/*`**。dc 的路径匹配是自实现的四分支函数，只有
   `dir/**` 那一支走目录前缀判断（`filePath.startsWith(dir + '/')`，故任意深度都命中）；
   单星会掉进兜底的 basename / 后缀精确匹配分支，深层文件基本匹配不到。

`checks: []` 已经保证命中该 profile 的文件零 finding，**不需要**再写 `!` 前缀的排除项；
`!` 只在「大目录整体豁免、但其中某个子集仍要检查」时才用得上。

这份 profile 落在项目根的 `.deepcritique/profiles/`，**不在 `.keeper/` 里面**，所以它不
构成前面那条「一个 `DBG-NNN/` 目录里只有那四样」的第五样。

建完回读一次：对 `.keeper/` 下某个超过 500 行的 md 做一次 `Edit`，确认 stderr 不再出现
`[L1-WARN]`。文件写对了不等于 hook 真的按新值生效——同一条纪律与「改完 `.gitignore` 必须
grep 回来确认」同源。

若项目里已有一份别的豁免 profile（例如老 debug 队列时期的
`.deepcritique/profiles/debug-queue-exempt.js`，`paths` 只写了 `.debug/**`），两条路都行：
给它的 `paths` 补一条 `.keeper/**`，或按上面新建独立文件。选前者要同步改掉那份文件顶部
「影响面仅限 .debug/」之类的注释，否则代码与注释脱节。

`index.md` 由 hook 每轮重算，**不要手工编辑它**，下一轮就被覆盖。v6 起它是被跟踪
文件，所以手改还会在 `git diff` 里留下一条随即被抹掉的假改动（这条 v4 的副作用随入库
策略一起回来了）。

> **对 v5「整树不入库」拍板的覆盖标注**：本节 2026-08-06 那份「`.keeper/` 整树忽略、
> issue 文本与截图均不入库」的决定，**已于 2026-08-10 被用户拍板整体覆盖**，原话是
> 「`.keeper` 之前把它从整个项目中忽略了，现在看来还是需要提交到远端纳入版本控制，
> 除了少数内容比如里面的 worktree 之外，其他都可以（包括当时的问题附件/图片/文件等）
> 纳入版本控制」。
>
> 被覆盖的是**入库策略**。连带反转的下游判据有四条，都在本文件与两个 agent 定义里
> 各自改过，读到旧措辞不要照旧行动：截图脱敏（从「额外谨慎」升级为红线）、
> `check_staged_gitlink.py`（从「存量仓专用」恢复主线）、receipts 对账（从 `cat`
> 回到 `git show HEAD:`）、清理 worktree 前手工 `cp` receipts（已作废，merge 会带回来）。
>
> 下面那段 ugrep 实测结论**没有被覆盖**，它仍然成立，只是**适用范围收窄**——从
> 「整个 `.keeper/` 都搜不到」缩小到「只有 `worktree/` 等三类搜不到」。

三次反转的历史值得留着，因为它解释了为什么这些判据看起来会自相矛盾。v3「一行 `.keeper/`
整树排除」的理由是"一行覆盖全部子目录"，那个便利是真的，但它带来一个当时没预见的
后果：Claude Code 把 `grep` 影子成自带 ugrep 且参数写死 `--ignore-files`
（`~/.claude/shell-snapshots/snapshot-zsh-*.sh:5160`），**被 ignore 的文件搜起来静默
零命中、不报错**。于是「先搜一下有没有类似 issue」在整个 v3 期间返回的都是假的
「没有」。v4 为保住可搜性让队列文本入库；v5 判定「公开代价不可接受」，绕回整树忽略、
改用「换搜索根」规避；v6 又判定这个代价可以接受，回到入库这一侧。

ugrep 那个坑之所以拖了整个 v3 才被发现，是因为**时灵时不灵**（2026-08-01 实测）：
ugrep 只读递归下降途中遇到的 `.gitignore`、**不向上找**。从仓库根搜静默零命中；把
搜索根直接设进被忽略的目录反而正常命中——那条规则在搜索根上一层，没被读到。同一份
数据同一个词，换个起点换个结论。**排查这类「搜不到」时不要用缩小搜索根的办法去复现**，
那恰好会绕开症状。

> ### 硬约束（v6 收窄版）：只有 `worktree/` 里的内容需要换搜索根
>
> ```bash
> grep -rn "关键词" .                              # ✅ 队列正文已入库，正常命中
> grep -rn "关键词" .keeper/<交付id>/debug/<id>/worktree/   # ✅ 搜 worktree 内部要设根
> ```
>
> 仍被排除的只有三类：`worktree/`、`.keeper-instance.json`、`.keeper-active`。对它们
> 从仓库根搜是**静默零命中且不报错**。拿不准时用 `Read` / `ls` 正面列举，
> **不要用否定式检索得出「队列里没有这条」**——那个「没有」可能是假的。

**写法坑：v4 踩过的那两个在 v6 重新适用，外加一个新的。** v6 又回到「多条精确规则」
形态，所以这些不再是存档：

- **必须用 `**` 而不是写死中间层。** 兜底桶 `_main` 与交付桶层级数相同，但写死中间层
  （`.keeper/*/debug/*/worktree/`）在嵌套变化时会漏网。`gitignore_findings` **不解析
  通配符语义**，写死中间层的「等价物」不算命中、会被报成缺规则——这是有意的。
- **不能用 `.keeper/` 打头再 `!` 白名单回捞。** git 明文规定父目录被排除后无法重新
  包含其中文件。v6 的形态是「默认不排除 + 三条精确排除」，方向与白名单回捞相反，
  照白名单思路写会得到一个完全不生效的配置。
- **（v6 新增）`.keeper/.keeper-active` 不带 `**`。** 它是 `.keeper/` 顶层的单文件、
  不是每交付一份；照抄 worktree 那条写成 `.keeper/**/.keeper-active` 匹配不到它，
  而匹配不到的表现是「这个本机状态文件天天出现在 `git status` 里」。

`check_staged_gitlink.py` 校验暂存区有没有新增野生 gitlink（mode `160000`），**v6 起
恢复为每个仓提交队列前都要跑的主线校验**（v5 曾降级为存量仓专用，那条已作废）。原因是
现在挡住野生 gitlink 的只有上面那条 `.keeper/**/worktree/`，而它正是有写法坑的那条：

```bash
python3 <插件>/skills/tk-debug/scripts/check_staged_gitlink.py
```

判据是 `git diff --cached --diff-filter=A --raw` 里 mode 字段等于 `160000`——git 自己
输出的确定字段，没有假阳性；`--diff-filter=A` 只看新增，已声明的 submodule 每次
gitlink 更新是 `M` 不是 `A`，天然被排除在外。exit 2 时按它打印的命令逐条撤出暂存区，
不要强行提交。

**冷启动检查那三条精确规则是否都在位，缺就整块追加，注释与 pattern 逐字写死**。
v4 当初改成 fail-loud、不自动追加，理由是「两个分支各自在 EOF 追加内容不同的注释就会
冲突」；把追加文案钉死为上面那固定四行字节（`hooks/lib/queue_snapshot.py` 的
`GITIGNORE_BLOCK`）之后，内容逐字相同时 git 视为同一处改动、不冲突，问题因此解决。

**追加用第一条当哨兵**（`grep -qxF '.keeper/**/worktree/'`）：三行只可能整块写入，
有它就有另两条。

**冷启动还要多做一件 v6 特有的检查**：v5 的整树忽略行若还留在 `.gitignore` 里，它会
覆盖这三条、让队列继续不入库，**且不会有任何报错**。检出它不要自己删——那会让存量
队列一次性变成待提交，属于按 §12 报 Human 拍板的处置。

快照 hook（`gitignore_findings`）仍只在每轮注入时提醒，代写只发生在 keeper 冷启动
这一处；两处都代写会在 hook 未生效的环境里制造「以为写了其实没写」的分叉。

## 2. issue 文件格式

frontmatter 只放**能被机械消费的状态**，一共 10 个键，声明与渲染顺序见
`hooks/lib/queue_files.py` 里 `DEBUG` 这个 `QueueSpec` 的 `fm_order`（用
`grep -n 'fm_order' hooks/lib/queue_files.py` 定位，不要凭行号——这份文件改过几次，
写死的行号会静默失效）。长文本一律进正文章节——否则 frontmatter 会重新长成第二个
`issues.yaml`。

```markdown
---
id: DBG-017                 # 与文件名一致
summary: 一句话摘要         # index.md 直接用它，写清楚
status: open                # open | done ← 只有两个
priority: P1                # P0 阻断 / P1 主流程 / P2 体验
difficulty: medium          # easy | medium | hard
type: bug                   # bug | ux | perf | arch
spec_status: violation      # violation | gap | conformant | unchecked ← 见 §3.1
reported_at: 2026-07-29
reopen_count: 0
external_ref: TRACKER#644168   # 可选，格式 <系统名>#<id>，见 references/external-tracker.md
---

# DBG-017 · <一句话问题陈述，写当前事实，不写"疑似/未证实/待核查"等过程状态词>

## 问题

一句话：什么操作 → 什么后果。让读者 10 秒内知道这是个什么 bug。证据紧跟其后，
给 `file:行号` + 最小代码片段。**不要用「来源与性质」「登记线索」「本条不是用户报告」
这类过程叙事占第一节**——那是修订记录的职责。

## 用户原话

> 仅当本条来自用户直接报告时写本节，**逐字照抄，禁止改写、禁止摘要**。
> 派生项（从别的 issue 修复过程推断出的待核查线索）没有用户原话，**省略本节**，
> 不要拿过程叙事填空——「问题」节靠现象 + 证据就能独立成立。

```text
<逐字照抄>
```

## 证据

- `.keeper/<交付id>/debug/DBG-017/01-xxx.png`
  - origin_path：<image-cache 原路径，仅留档>
  - 转录：<图里能看到什么，文字描述>

## 规格依据

<triage 必产出，判据与三态语义见 §3.1。缺这一节的 issue 不许派 fixer。>

- 结论：`violation`（规格写了、实现没照做）
- 查过的来源（**逐条列，命中与否都写**；没查的那类也要列出来并写原因）：

| 来源 | 结果 | 备注 |
|---|---|---|
| `sdlc/specs/features/<f>/ui/views/pc-import.md:88-119` | 命中 | 见下方摘录 |
| `sdlc/specs/features/<f>/ui/views/pc-import.prototype.html` | 未命中 | 该表格未画进原型 |
| `sdlc/specs/features/<f>/contracts.md` | 未命中 | — |
| i18n 文案 / DB 列注释 / ADR | 未查 | 本条是纯前端提示文案，不涉及 |

- 规格原文摘录（**逐字，禁止转述与摘要**——fixer 要照它改，转述一次就丢一次约束）：

```text
<从规格文件里逐字抄来的那几行 / 那张表>
```

- 期望 vs 实际：<规格说 A，实现是 B，差在 C>
- **本条的修复判据**：与上述规格逐条一致；**不是**「用户报的那一条现象不再复现」。

## <按需的顶层小节：triage 产出的当前结论>

如「血缘与归属」「生效机制」「影响面」等。每节是一个**当前事实**（缺陷是否存在、落点、
机制、归属），不是推理过程。落点必须带 file + 行区间；验证场景穷举 A/B/C；需要人拍板的
歧义也写在这里。triage 还没做的结论先不立这一节，有了再补——但**补的时候是回改到这里，
不是在修订记录里追加一个「结论」小节**（见下方「正文结构纪律」第 3 条）。

## Triage

三维打分 `priority` × `difficulty` × `type` 各附一句判据 + 处置建议（修 / 转出 / 关闭）。

## 验证

<逐场景的验证步骤与结果>

## 修订记录

**过程日志，append-only**：登记时的初始判断、派了什么 triage、核实推翻了什么、何时
reopen / 关闭。这一层只承担审计职责，**不承担「说清问题」的职责**——说清问题靠正文顶层小节。

### 登记（2026-07-29）
<初始判断、当时的未核实项。后续若被推翻，旧说法留在这里、正文顶层已改掉。>

### 首轮修复（2026-07-29）
<改了什么、有意偏离报告诉求的地方、未验证的部分>

### reopen（2026-07-30）
<为什么打回、这次要求与上次的差别在哪>
```

**正文结构纪律（结论前置，不要写成侦探笔记）**：上面这个模板的生命线是
**正文 = 当前事实 / 修订记录 = 过程日志**这条分层。读者（主会话、未来的 debug-keeper、
审计的用户）第一诉求是「这是什么 bug、严重吗、现在什么状态」，不是「debug-keeper 是怎么
一步步走到这个结论的」。五条：

1. **H1 与 summary 写当前事实**，不写「疑似 / 未证实 / 待核查 / 待确认」这类过程状态词。
   核实升级了（推断 → 实证、open → done、建议转出 → 已关闭）就回改 H1 与 summary，不要让
   标题和摘要停在旧状态。
2. **正文第一节必须是「问题」**（一句话：操作 → 后果 + 证据）。禁止用「来源与性质」「登记
   线索」「本条不是用户报告」这类元叙事占第一节——它们属于修订记录。
3. **核实推翻旧结论时，必须回改正文顶层小节**，把旧说法改掉；旧叙述（登记时的推断、被
   推翻前的表述）压进「修订记录」。**禁止只追加新小节、正文仍留着已被推翻的旧描述**——
   那会让从头读的人先撞上一段现在已经不成立的判断，读半篇才到结论。
4. **summary 一句话**，不塞多个结论。commit hash / 作者 / 日期 / 修复路径这些细节进正文
   顶层小节，不进 summary——`index.md` 直接渲染 summary，长句会让整个队列列表不可读。
5. **派生项（无用户原话）也照常写「问题」节**——现象 + 证据能独立成立。「来源」压成修订
   记录里一句话（「2026-XX-XX 从 DBG-NNN 修复过程派生」）即可，不要展开成节。

**`status: done` 在 wontfix 场景的语义**：队列只有 `open`/`done` 两档（见下文），wontfix 归一
至 `done`。当一条 issue 是「关闭不处理」而非「已修复」时，在 H1 下用一句 blockquote 显式
声明（例：「`done` 在本条语义是关闭不处理，不是已修复，缺陷仍存在于源码」），避免后续把
wontfix 误读成已修复。

**为什么 `status` 只有两个值**：v2 定义了 `open | in_progress | resolved`，而
`in_progress` 在一个跑了 22 条 issue、7 次提交的真实项目里**从未被写入过一次**
（`git log -S'status: in_progress'` 零命中）。AI 反而自创了 `fixed` 用了 14 次。
一个被反复绕过的字段说明它不该由 AI 维护——v3 把「谁在修」交给 `git worktree list`
派生，落盘状态只留下 git 无法表达的那个二值。历史 `fixed` / `resolved` / `obsolete`
/ `duplicate` / `wontfix` 到 `done` 的归一映射见 `hooks/lib/queue_files.py` 的
`STATUS_MAP`。

**不要写进 frontmatter 的东西**：任何能从 git 或文件系统算出来的（谁在修、改了
哪些文件、修完没有）；任何超过一行的文本（进正文章节）；任何派生计数（done 有
多少条由 `index.md` 现算）。

## 3. 三维打分

triage 完成时给出 `priority` × `difficulty` × `type`。**它们各有一个明确的消费者，
不要把它们当调度输入**（见本节末）。

`priority` 看**阻断程度**：`P0` 功能完全不可用或产生脏数据；`P1` 主流程受影响但
有绕行路径；`P2` 体验问题。注意「用户催得急」不是 P0 的判据，「不修会产生错误
数据」才是。**它的消费者是收官分流**——交付要收尾而队列没清空时，靠它决定哪几条
必须修完、哪几条推迟到外部 issue（`agents/debug-keeper.md` §10）。

`difficulty` 看**改动面**：`easy` 单文件、有明确锚点、改法唯一；`medium` 跨 2-3
文件或需要先定位；`hard` 跨模块、涉及数据结构或集成缺失。估错难度的代价是模型
档位配错，宁可高估。**它的消费者是 §4 的模型分层表。** 字段本身的声明只是
`hooks/lib/queue_files.py:80` 上的一行注释（`"difficulty",    # easy | medium |
hard`），完整的判据语义（单文件明确锚点 / 跨 2-3 文件 / 跨模块涉及数据结构）只
写在本节，不要指望代码里还有更详细的定义。

`type` 取 `bug` / `ux` / `perf` / `arch`。`bug` 与 `ux` 的分界是**行为错误还是
观感不一致**——「点了没反应」是 bug，「间距不对」是 ux。**它只被 `index.md` 消费**
（渲染成一列给人扫读），没有任何流程按它分支，所以填错的代价最小、不确定时不必纠结。

### 这三个字段都不决定派发顺序

v2 写的是「它决定派发顺序与模型档位」，后来删掉了前半句。理由是 worktree
物理隔离 + 并发上限之后，「顺序」几乎不产生可观察的差别：open 有 10 条、同时在飞 8
个，那么排序只决定哪 2 条晚一轮，而不是哪几条会被修。真正影响结果的是**并发上限**
（§4 末）与**收官时谁被推迟**（`priority` 的用途）。

把 `priority` 当调度输入还有一层风险：它是 AI 打的分，而 v2 那套调度算法之所以从未
运行过一次，病根正是「拿 AI 手写的业务字段当机械判据」（见 §4）。同一个坑不要踩第
二次——派发顺序就按 id 顺序走，够了。

### 3.1 规格溯源：`spec_status` 四态

triage 时除了定位**代码落点**，还要定位**规格落点**——这个行为在需求文档 / 原型 /
view spec / i18n 文案 / DB 列注释 / ADR 里原本是怎么写的。产出四值之一写进 frontmatter
的 `spec_status`，依据写进正文「规格依据」章节（§2 模板）。

| 值 | 判据 | 处置 |
|---|---|---|
| `violation` | 找到明确表述，实现与之不符 | **缺陷**。照常派 fixer，但 prompt 必带规格原文摘录 + 出处，修复判据 = 与规格逐条一致（§4 模板） |
| `gap` | 下面八类来源全查过，无任何表述 | **不派 fixer**。这是规格空白不是缺陷——「正确行为是什么」从没人定义过，派 fixer 只会让它凭直觉补一个，把空白伪装成已定案。转 chore 队列，摘要写「待产品确认 X 的语义」 |
| `conformant` | 规格写了、实现照做了，用户仍不满 | **规格本身要改**，走需求变更，不在 debug 队列里改代码 |
| `unchecked` | 还没查——登记那一刻的初值 | triage 完成时必须落到上面三个之一。停在 `unchecked` 的 issue 视为 triage 未完成，不许派 fixer |

**八类来源（判 `gap` 前必须全部查过，并在「规格依据」表格里逐条列出结果）**：

1. 需求文字规格：`sdlc/specs/features/{f}/{contracts,entities,_index}.md`、`behaviors/*.gherkin`
2. view spec：`sdlc/specs/features/{f}/ui/views/*.md`
3. 原型 html：`ui/views/{page}.prototype.html`、`deliveries/D-*/ui/{page}.proposal.html`、`backlog/{feat-*}/upstream/*.html`
4. 交付级决策：`sdlc/deliveries/D-*/decisions.md`、项目 ADR
5. i18n 文案与其 key 注释
6. DB 列注释与数据字典
7. API 契约 / 错误码文案
8. 用户在本 issue 或历史对话里给出的明确期望

**项目没有 `sdlc/` 目录时本节不豁免**——1~4 类退化成「这个项目自己的需求文档在哪」，
5~8 类与目录结构无关、恒可查。八类确实全都不存在时才写 `gap`，备注里写明
「本项目无规格产物」。

**第 2 与第 3 类必须分开查、分开记结果，这是本节最要紧的一条。** 已实测的失效形态是：
文字规格写得很细，只是**没画进原型**；实现方照原型做，那几份 md 从头到尾没被打开，
整片规格就此失效。这类偏差在「原型存在」这个前提下不会被任何机械闸拦住——上游
`ai-sdlc` 的三道硬闸（写 `.vue` 前的原型消费证据、G4 的实现↔原型渲染比对、写原型时的
保真校验）基线全是原型 html，而覆盖文字规格的那道 `spec-sync-audit` 轴是 advisory
不阻断、且明文声明 UI 元素不在其值域内。所以**原型命中不等于规格命中**：两行都要
列，只在原型里找到就写「第 2 类未查」是不合格的 triage。

**判 `gap` 的门槛比判 `violation` 高，这是有意的。**「没有」是唯一无法自证的检索
结果——它可能是事实，也可能是正则写错 / 被 gitignore 静默吞掉 / 大小写不匹配 /
macOS 的 NFC-NFD 路径形态对不上。所以本节要的是**正面列举查过哪些来源**（肯定结论，
自带证据），不接受「搜了一圈没有」（否定结论，无从核验）。

**`spec_status` 与 `type` 正交，不要互相替代。** 一条 `type: ux` 同样可以是
`spec_status: violation`（规格写间距 8px、实现做成 12px）。`type` 只被 `index.md`
消费；`spec_status` 的消费者是 fixer 派发（§4）与收官归因统计
（`agents/debug-keeper.md` §9.1）。

**什么时候不必逐条走完八类**：

- `type: perf` 且问题是纯资源指标（内存泄漏、慢查询、包体积）——规格通常不定义这类
  阈值。直接写 `gap`，备注写「性能阈值类，八类来源不适用」。收官归因只统计
  `violation`，所以这样写不会污染统计。
- reopen 第 2 次及以后——首次 triage 已产出过 `spec_status`，沿用即可。**例外**是
  reopen 原因本身就是「规格理解错了」，那要重查并回改。

### reopen 升级阶梯

同一 issue 反复失败是**「triage 判错」的信号**，不是「subagent 不够努力」。用同样
的模型和 prompt 重派第三次不会有不同结果。

| `reopen_count` | 强制动作 |
|---|---|
| 1 | 原配置重派，但把用户 reject 原因**全文**塞进 fixer prompt |
| 2 | **强制升档**（`sonnet` → `opus`），且先派 `Explore` 出根因分析再修 |
| ≥3 | **停止自动重派**。打回重新 triage，或交用户拍板 |

## 4. 派发：一 issue 一 worktree

### gitlink 铁律（贯穿本文多处，先在这里讲一次）

供给与回流全部由 `tk-worktree` skill 的 `wt_supply.py` 承担，它有两条不可违反的
铁律，本文后面多处依赖它们才成立，值得先讲一次而不是每次都跳去 `tk-worktree`：

1. **linked worktree 里绝不跑 `git submodule update --init`**。它会新建一份**独立
   对象库**（有自己的 `objects/`、不链回源仓），导致源侧本地未推送的提交在这份独立
   对象库里永远不可见，回流合并时才炸（`git cat-file` 报 `could not get object
   info`，因为对象根本不在这份独立仓里）。正确手法永远是 `git worktree add`。
2. **gitlink 一律以源侧同层 index 为准**（`git -C <源侧父仓> rev-parse
   :<submodule相对路径>`），不能从主 checkout 读——不同 worktree 在不同分支上，
   各分支记录的 gitlink 不同，从主 checkout 读会静默检出错误版本，不报错、内容却
   是别的分支的，极难发现。

完整实现细节、六个子命令、状态判据表见 `tk-worktree` skill 正文；本节后面只在
用到的地方点一句引用，不重复讲机制。

### 为什么是物理隔离而不是调度

v2 靠 `affected_files` 求交集做互斥调度：两个 issue 改同一文件就串行、否则并行。
这套逻辑的输入是 AI 手填的字段，而它依赖的 `status: in_progress` 从未被写过，
于是「在飞集合」恒空、「文件冲突」恒不成立——整套调度算法从未真正运行过一次。

worktree 让这个问题消失：每个 fixer 在自己的工作区里改，两个人改同一个文件也
互相看不见，冲突推迟到合并时由 git 处理（那是 git 最擅长的事）。**因此 v3 没有
文件锁、没有 `depends_on` 冲突检测、没有饥饿让位、没有「派发前查文件占用」。**

### 派发步骤

**v7 起，下面的「本批 K 条 issue」通常就是你自己认领的那一条（K=1）。** 一个
debug-keeper 实例只负责自己认领的那一条 issue，不再像 v6 那样由一个常驻实例批量
处理整条队列里互不相关的多条 issue——`--ids` 批量建 worktree 这套机制**不是因此
作废**，只是调用者变了：K≥2 的场景不再是「一个实例同时给队列里 3 条不相关的 bug
建 worktree」，而是「你自己这一条 issue 确实需要拆成几个可并行的子任务、各自开
一个 worktree」这种更少见的情形。凡是下文写着「本批 K 条」的地方，先按「K=1，
就是我自己这条」理解；只有你判断自己的这一条 issue 真的需要拆成多个并行子任务时，
才会用到 K≥2 的批量写法。

**一条 `init` 命令建完本批全部 worktree**：建父仓工作区 → 记住源 worktree → 全量递归供给
所有 submodule 层（含嵌套）→ 自校验，本批 K 条 issue 一次建完，不要循环调 K 次。这是派发
前**唯一**的串行前置——它跑完之后，K 个 `Agent` 调用才一次性发出（同消息批量发出的硬规则
见下一节「两轨派发」）。真正的瓶颈从来不是 `Agent` 本身（默认后台起跑），而是每派一个前
串行等一次这条命令；把 K 次 `--id` 压成 1 次 `--ids` 才是省下来的那部分时间。不要自己先
`git worktree add` 再单独调供给——`init` 的落点是它自己算的，手动建的目录它认不了。

```bash
ROOT="$(git -C . rev-parse --show-toplevel)"
WT_SUPPLY="$(find ~/.claude/plugins/cache -maxdepth 6 \
  -path '*/task-keeper/*/skills/tk-worktree/scripts/wt_supply.py' 2>/dev/null | head -1)"
python3 "$WT_SUPPLY" init --source "$ROOT" --ids DBG-017,DBG-018,DBG-019 --jobs 3 --quiet
WT_017="$ROOT/.keeper/<交付id>/debug/DBG-017/worktree"   # 每条 issue 各自的落点仍是 <source>/.keeper/<交付id>/debug/<DBG-id>/worktree/<id>/，分支 fix/<交付id>-DBG-017
WT_018="$ROOT/.keeper/<交付id>/debug/DBG-018/worktree"
WT_019="$ROOT/.keeper/<交付id>/debug/DBG-019/worktree"
```

`--ids` 逗号分隔批量建（本例 3 条），`--jobs` 控制并行度（默认 3），`--quiet` **不打印
逐层供给明细与自校验清单、只留每个 id 一行结论**（实测 3 层仓、3 个 id：73 行 → 9 行）。
它省的只是**成功路径**的输出——自校验照跑，非全绿仍退出 `2`，且那时会自动把完整逐层清单
打全，不需要你再跑一次去看详情。旧的
`--id`（单值）参数仍保留兼容，只建一条 issue 时可以继续用它，但**本批待派 issue 有 K≥2 条
时一律走 `--ids` 一条命令**，不要为省事循环调 K 次 `--id`——循环调用会把本该消失的串行
瓶颈重新引入。

**落点不可配**，`--worktree` 之类的参数在 `init` 上不存在。核心原因是很多工具链
（hook、状态注入、路径识别）靠 **cwd 的路径字面量**反推「当前处于哪个工作区」——
目标 worktree 落在源 worktree **内部**时，它的绝对路径天然包含源 worktree 的完整
路径前缀，这类识别全部照常工作；落到外部（比如与源平级的目录）会被静默判成另一个
无关工作区，没有任何报错。一个真实例子：某交付框架的路径识别常量是 `MARKER =
'/.sdlc/worktrees/'`（`scripts/lib/path-resolve.js:18`）+ slug 白名单（同文件
`:27` 的 `isValidSlug`，只认 `^D-\d+` / `^hotfix-` 开头），fixer worktree 若直接
落到 `.sdlc/worktrees/DBG-021`，MARKER 命中但 slug 校验不认，一整串依赖 cwd 判断
的 hook 集体失准；落在源 worktree 内部的 `.keeper/<交付id>/debug/DBG-021/worktree` 则前缀完整
保留、识别不受任何影响。**这条约束的通用原理是「宿主工具链靠 cwd 路径字面量识别
工作区」，不是这一个交付框架独有的毛病**——任何靠 cwd 前缀判断上下文的工具链都有
同样的脆弱性，落点必须在源 worktree 内部这条要求因此具有普遍性。

`init` 是**幂等**的：目标已存在且分支一致就跳过创建、直接续跑供给。自校验没全绿时
退出码 `2`，**已建出的部分刻意不回滚**（保留现场排查），修掉根因后重跑同一条命令即可。
批量场景下退出码 `2` 可能只代表 K 条里的某一条没过自校验，其余都建好了。**哪一条没过不用
另外去查**——`--quiet` 在非全绿时会自动把完整的逐层清单打出来，直接读那份输出即可，
**不要去掉 `--quiet` 重跑一遍**（那次重跑什么新信息都拿不到，还会让已建好的 id 各自再走
一遍全树 `classify()`）。重跑只针对没过的那几个 id，用 `--ids` 单独列出它们，不必整批推倒
重来——`init` 幂等，但整批重跑等于让已经建好的那些白走一遍。
另外源 worktree 里未提交的改动**不会**进目标 worktree（`worktree add ... HEAD` 只带走
HEAD 内容），`init` 会把这些改动列出来警告，看到就要判断 fixer 是否依赖它们。

**为什么用 `find` 动态发现而不是 `${CLAUDE_PLUGIN_ROOT}`**：`${CLAUDE_PLUGIN_ROOT}` 只在
`hooks/hooks.json` 的 `command` 字段、MCP server 配置、slash command 里的 `!`command``
执行块这几处会被 harness 预处理替换——那是宿主在调用前就做的静态替换，不是进程环境变量。
本节这段命令是 keeper 自己在 `Bash` 工具里现场跑的普通 shell，实测当前会话 `env | grep
CLAUDE_PLUGIN_ROOT` 空输出，写在这里的 `${CLAUDE_PLUGIN_ROOT}` 只会原样保留字面量或展开成
空串，拼出的路径不存在。跨插件引用另一插件脚本时常撞到同一类问题——目标路径里含随插件
版本变化的内容哈希，标准解法都是用 `find` 在 `~/.claude/plugins/cache` 下按固定的插件名
+ 相对路径模式动态定位，不依赖任何 harness 只在特定上下文才生效的替换机制。上面的
`WT_SUPPLY` 就是这个模式：`tk-worktree` 与 `tk-debug`、`debug-keeper` 同属
`task-keeper` 插件，缓存路径形如 `~/.claude/plugins/cache/<marketplace>/task-keeper/
<版本哈希>/skills/tk-worktree/scripts/wt_supply.py`，`find` 按 `*/task-keeper/*/
skills/tk-worktree/scripts/wt_supply.py` 这个模式匹配即可跨版本哈希稳定命中；若
`WT_SUPPLY` 解析为空，说明 `task-keeper` 未启用或缓存未刷新，需先处理再重试。

供给能力来自同插件内 `skills/tk-worktree/`（与 `tk-debug/` 同级），六个子命令
是 `init` / `supply` / `status` / `remove` / `merge-back` / `explain-scope`。派发只需要
`init`；`supply` 是给"父仓工作区已经在了、只想补 submodule 层"这种续跑场景用的。

**供给范围是源侧 `.gitmodules` 全量递归，不做裁剪。** 早先设计过"按 issue 落点只供给
相关那几个 submodule"，已经推翻——修一个 bug 常常要顺手改 spec（住在某个 submodule 里）、
要查知识库、要翻组件库做 UI 组件溯源，按落点裁剪会让 fixer 在半路撞上空目录卡住，省下的
那点建 worktree 时间远不够抵消返工。

想知道"这条 issue 碰了哪些 submodule"仍然可以查，但它现在是一个**只读**子命令、
不影响供给范围：

```bash
python3 "$WT_SUPPLY" explain-scope --worktree "$WT" --from-triage "$ROOT/.keeper/<交付id>/debug/DBG-017/issue.md"
```

它解析 issue 正文里的 `<path>:<行号>` 引用、按 `.gitmodules` 声明路径做最长前缀匹配反推
影响面，用途是排查时判范围、写 issue 时核对有没有漏层。这仍然意味着 triage 阶段该把落点
写清到 file + 行号（§3 已有此要求），只不过现在写不清**不会**导致供给缺层。

**绝对不要**用 `git submodule update --init` 代替这一步图省事——见本节开头「gitlink
铁律」第一条，实测它在 linked worktree 里会新建一份**独立对象库**，回流合并时才炸。

**不要用 `Agent` 工具的 `isolation: "worktree"`**。理由不是「目录名随机、无法
反查」（这个说法不准确——实测目录名其实是确定性的 `agent-<agentId>`，派发返回
值里就带 `worktreePath`，并非查不到）。真正的理由换成下面四条：(a) 它建在**主
仓根** `<主仓>/.claude/worktrees/agent-<id>`，不在当前 delivery worktree 下；
(b) **基线是 `master`**——实测 `git branch -a --contains HEAD` 在那个 worktree
里只返回 `master / origin/master / origin/HEAD`，**不含**当前 delivery 分支，
fixer 会在一个没有本交付任何成果的基线上改代码；(c) submodule **全部未初始化**，
子目录直接是 `total 0` 的空目录，fixer 什么都读不到；(d) 目录名不含 issue id，
打掉 `git worktree list | grep DBG-` 零成本在飞判定（原文这条说对了，保留）。改用 `init` 只多一行命令，换来的是正确的
基线 + 已全量供给的 submodule + 可反查的目录名。

**也不要指望 `Agent` 工具的 `cwd` 参数能顶替这套约定**——实测传了 `cwd` 后
agent 仍报主会话的 cwd，**静默丢弃、不报错**，你以为传了就生效，实际完全没
起作用。隔离**必须**靠 prompt 里写死 worktree 绝对路径 + `git -C <worktree>` +
明确一句「不要 cd」来实现，没有参数能省掉这套约定。

派发时**不带** `isolation`、也**不传** `cwd`，在 prompt 里写死绝对路径。具体走哪版
prompt 模板，先看下一节按 `difficulty` 分的两条路径。

### 两轨派发：一次性 subagent vs 交互式 subagent

判据用 issue frontmatter 已有的 `difficulty` 字段（`easy` / `medium` / `hard`，
声明位置见 §2、§3）：

- **`easy` → 一次性 subagent**。改一个 `v-if`、补一个字段序列化这类无需拍板的
  机械修复走这条，`Agent` 发出去就不用再管，出问题时对账阶段（§5）会发现。
- **`medium` / `hard` → 交互式 subagent**。需要确认意图的改法、跨模块、改数据
  结构这类走这条：两版模板都要传 `name`（必须带模型档次前缀）与
  `run_in_background: true`，medium/hard 版在此之上额外在 prompt 里加一段交互
  纪律，让它在真正卡住时用 `SendMessage` 问 keeper 自己的 name。keeper 的 name
  带随机短哈希（形态 `opus-debugger-<4位>`），fixer 拿不到 keeper 自己的调度
  元数据，所以 debug-keeper 派发 fixer 之前要把**自己当前这个实例的 name**
  （就是自己被 `Agent` 派出/`SendMessage` 唤醒时那个 name，通常已经写在自己
  收到的 prompt 第一行里，不需要额外去查）写进 fixer 的 prompt 里替换掉占位符，
  而不是自己拍板续做——**不要**去 `.keeper/<交付id>/.keeper-instance.json` 里
  按 `debug` 这个 kind 键查，v7 起那是一份实例列表（`debug.instances`），同一档
  可能有好几条记录，凭 kind 查不出该填哪一个，只有自己知道自己是谁。这份登记从
  2026-08-05 起还带 `session_id`（用于主会话跨会话判断"这条登记是不是本会话
  写的"，完整说明见 `agents/debug-keeper.md` §0），但这与本节无关——本节要的
  只是"我自己叫什么"，不涉及登记表查询。

#### 同消息批量发出（硬约束）

**本批要派 K 个 fixer 时，K 个 `Agent` 调用必须放进同一条消息里发出。** 理由：`Agent`
默认后台执行，一条消息里发 K 个 tool_use 就是 K 个并发起跑；一轮只发一个的话，每轮之间
还要等一次模型往返，K 条 issue 里除第一条，其余 K-1 条都在白等对应的轮次——瓶颈不在
`Agent` 本身慢，在发送节奏把本可并发的任务拆成了串行。

这条对两轨都适用：easy 的一次性 subagent 与 medium/hard 的交互式 subagent 可以混在同
一条消息里一起发出，不必先发完一轨再发另一轨。

**什么时候不触发**：本批只有一条 issue 可派时（没有「批量」可言，无需凑消息）；某条
issue 在上一节批量建 worktree 时没通过自校验时（那一条跳过，其余仍在同一条消息里照发，
不要因为一条建失败就把整批也拆成逐个发送）。

**为什么这样设计（实测支撑）**：

1. 交互式 subagent → keeper 的 `SendMessage` 实测送达；keeper 回复后，它能答出
   等待前记住的口令，证明 transcript 完整保留、上下文连续——被唤醒后不是
   「从零开始」，而是接着上次的状态往下走。
2. `SendMessage` 返回值原文是 `Agent "<name>" had no active task; resumed
   from transcript in the background with your message.`——说明该 subagent
   发完问题后**任务已终结、不占并发槽**，是「结束 + 被消息唤醒」而非「挂起
   等待」。所以**多个 fixer 同时挂着问题等 keeper 不会挤占 §4 末尾的并发上限**
   ——这条改变了「同时在飞最多 8 个」的计数口径：正在等待答复的
   交互式 subagent 不计入这个数字。
3. 代价：每次唤醒都要重放 transcript，token 成本比真正挂起高——所以 `easy`
   档不必用交互式 subagent，一次性 subagent 更省。

`name` 必须带模型档次前缀且格式合规——实测撞过 `agent-dispatch` 守卫拦下纯
`DBG-024` 这种名字，报 `name="DBG-probe-subagent" 缺模型档次前缀`，改成
`sonnet-DBG-024` 这类形态才放行。

#### easy 档模板：一次性 subagent

```
Agent(
  subagent_type: "general-purpose",
  name: "sonnet-fix-dbg017-step3-style",
  description: "修 DBG-017 样式对齐",
  model: "sonnet",
  run_in_background: true,
  prompt: "【目标】修 DBG-017。
           【上下文】你的工作区是 <worktree 绝对路径>。所有文件操作用该前缀下的
            绝对路径，git 操作用 `git -C <worktree 绝对路径>`。**不要 cd**。
            issue 全文见 <worktree>/.keeper/<交付id>/debug/DBG-017/issue.md，先读它。
            截图（如有）：<绝对路径>，动手前先 Read。
            规格锚：<规格文件绝对路径:行区间>，动手前先 Read **全文**，不要只看 issue
            「规格依据」章节里那段摘录。〔本条 spec_status 不是 violation 时改写成
            「本条 spec_status 为 <值>，无规格锚」〕
           【约束】**修复判据是「实现与上述规格逐条一致」，不是「issue 里报的那个现象
            不再复现」。** 规格若是一张表或一份清单，**逐行核对**——报告里只列了其中
            一条，不代表其余各条已经实现（实测过一次：需求表格给全了 31 条错误提示
            文案，用户只报了其中 1 条，按「现象消失」口径修完即收工，剩下 30 条原样
            落空）。核对结果逐条写进回执。
            禁止修改 .keeper/<交付id>/debug/ 与 .keeper/<交付id>/debug/index.md——队列
            写权限只在主工作区，你在 worktree 里改会造成合并冲突。
            改完不要自己重启本地服务，交回执由 debug-keeper 拍板。
            **禁止在这个 worktree 里启动任何本地服务**（如 mvn spring-boot:run /
            npm run dev / java -jar）——这条不放开。**允许**在修复前调用
            `agent-browser` **无头模式**（显式传 `--headed false`，不要只是不传
            `--headed`——不带这个显式参数会被 bash-guard 拦下）做比对确认：
            对着已经在运行的目标环境（不是你自己起的服务）核实 bug 现象、比对
            期望与实际，帮助你在动手改代码前确认理解是否准确。**必须**同时传
            `--profile <本 issue 专属的临时 profile 目录，例如
            /tmp/agent-browser-profiles/DBG-017>`，不要用 Human 的个人 Chrome
            Profile 或与其他并发 fixer 共用同一个 profile 目录——多个 headless
            实例抢同一份 profile 会因为 Chrome 的 profile 锁而互相冲突。**改完
            之后的运行时验证依旧不属于你**：验证章节此刻只能基于代码审查、单元
            测试、编译期检查（如 mvn compile / tsc --noEmit）+ 修复前的那次
            headless 比对给结论，修复是否真的生效，等本轮全部 issue 合并回主
            分支后由 debug-keeper 统一实测一次。
            **退出前必须把所有改动 commit 在本地分支上，一层都不能漏**——父仓层与
            每一个你碰过的 submodule 层各自 commit（submodule 一提交，父仓就会出现
            一条 `M <submodule路径>` 的 gitlink 变更，那条留给 debug-keeper 处理，
            你不用管）。**未提交的改动不算交付**：你退出后这个 worktree 随时可能被
            清理，工作区里没 commit 的东西会跟着消失；而且合并前对账用的是
            `git diff <基线>...HEAD`（**基于 commit**），你没 commit 就等于 diff
            全空，会被判成「幻觉回执」要求整轮重做。commit 完对每一层跑一次
            `git -C <该层> status --short` 确认输出为空（父仓层只剩 gitlink 变更
            也算干净），确认干净了才算做完。
            **禁止执行 `git push`（不管 push 到这个 worktree 的分支还是任何远程）**——
            commit 在本地分支上就够了，回流合并由 debug-keeper 之后统一处理，push
            完全不属于你的职责范围。
           【期望输出】把结论写进 <worktree>/.keeper/<交付id>/debug/DBG-017/receipts.md，
            包含：改了哪些文件（逐个列路径）/ 关键决策（为什么这样做、放弃了什么）/
            阻塞点 / 需要 debug-keeper 跟进的事项。同时在回执正文里返回同样内容。
            外加一段**逐层 commit 清单**：每层给出「层路径 + commit 短 hash +
            commit message」，以及该层 `git status --short` 的实际输出（应为空）。
            缺这一段的回执一律视为未完成、会被打回。
            `spec_status: violation` 的 issue 另加一段**规格逐条核对表**：规格里
            每一条断言一行，给出「规格条目 → 实现位置 `file:行号` → 已实现 / 未实现
            + 理由」。规格是表格或清单时，核对表行数必须与规格条数相同，**不许合并
            成一句「已全部实现」**——那句话无法核验，等于没核对。"
)
```

`run_in_background: true` 不是因为「不传就变成同步等待」——`Agent` 不传它默认也是后台
执行，行为不会变。补上这一行是为了不让读这份模板的人凡事从字面猜：easy 档模板里没有
这一行时，容易被误读成「easy 档是同步等待、只有 medium/hard 才后台」，而实际两轨都
后台，区别只在于 medium/hard 额外需要 `name` 支持 `SendMessage` 的 addressing、easy 档
不需要。**这是两件独立的事**——`run_in_background` 管要不要占着等结果，`name` 管日后
能不能用 `SendMessage({to: name})` 唤醒它；easy 档不需要后者，不代表可以省前者。上面
的模板本来就带着 `name`（用于在飞面板可辨识、以及 §5 对账阶段回查），继续保留，不要因为
「easy 档不需要 addressing」把它删掉。

#### medium / hard 档模板：交互式 subagent

```
Agent(
  subagent_type: "general-purpose",
  name: "sonnet-DBG-024",
  description: "修 DBG-024 序列模型分类归属",
  model: "sonnet",
  run_in_background: true,
  prompt: "【目标】修 DBG-024。
           【上下文】你的工作区是 <worktree 绝对路径>。所有文件操作用该前缀下的
            绝对路径，git 操作用 `git -C <worktree 绝对路径>`。**不要 cd**。
            issue 全文见 <worktree>/.keeper/<交付id>/debug/DBG-024/issue.md，先读它。
            截图（如有）：<绝对路径>，动手前先 Read。
            规格锚：<规格文件绝对路径:行区间>，动手前先 Read **全文**，不要只看 issue
            「规格依据」章节里那段摘录。〔本条 spec_status 不是 violation 时改写成
            「本条 spec_status 为 <值>，无规格锚」〕
           【约束】**修复判据是「实现与上述规格逐条一致」，不是「issue 里报的那个现象
            不再复现」。** 规格若是一张表或一份清单，**逐行核对**——报告里只列了其中
            一条，不代表其余各条已经实现。**核对中发现规格另有一条与本 issue 无关、
            但实现同样没照做时，不要顺手改**：写进回执交 debug-keeper 另立 issue，
            一 issue 一 worktree 的隔离靠的就是「改动面不外溢」。
            禁止修改 .keeper/<交付id>/debug/ 与 .keeper/<交付id>/debug/index.md——队列
            写权限只在主工作区，你在 worktree 里改会造成合并冲突。
            改完不要自己重启本地服务，交回执由 debug-keeper 拍板。
            **禁止在这个 worktree 里启动任何本地服务**（如 mvn spring-boot:run /
            npm run dev / java -jar）——这条不放开。**允许**在修复前调用
            `agent-browser` **无头模式**（显式传 `--headed false`，不要只是不传
            `--headed`——不带这个显式参数会被 bash-guard 拦下）做比对确认：
            对着已经在运行的目标环境（不是你自己起的服务）核实 bug 现象、比对
            期望与实际，帮助你在动手改代码前确认理解是否准确。**必须**同时传
            `--profile <本 issue 专属的临时 profile 目录，例如
            /tmp/agent-browser-profiles/DBG-017>`，不要用 Human 的个人 Chrome
            Profile 或与其他并发 fixer 共用同一个 profile 目录——多个 headless
            实例抢同一份 profile 会因为 Chrome 的 profile 锁而互相冲突。**改完
            之后的运行时验证依旧不属于你**：验证章节此刻只能基于代码审查、单元
            测试、编译期检查（如 mvn compile / tsc --noEmit）+ 修复前的那次
            headless 比对给结论，修复是否真的生效，等本轮全部 issue 合并回主
            分支后由 debug-keeper 统一实测一次。
            **退出前必须把所有改动 commit 在本地分支上，一层都不能漏**——父仓层与
            每一个你碰过的 submodule 层各自 commit（submodule 一提交，父仓就会出现
            一条 `M <submodule路径>` 的 gitlink 变更，那条留给 debug-keeper 处理，
            你不用管）。**未提交的改动不算交付**：你退出后这个 worktree 随时可能被
            清理，工作区里没 commit 的东西会跟着消失；而且合并前对账用的是
            `git diff <基线>...HEAD`（**基于 commit**），你没 commit 就等于 diff
            全空，会被判成「幻觉回执」要求整轮重做。commit 完对每一层跑一次
            `git -C <该层> status --short` 确认输出为空（父仓层只剩 gitlink 变更
            也算干净），确认干净了才算做完。**被 `SendMessage` 唤醒等拍板之前也要
            先 commit** —— 等待期间你会被结束，没 commit 的改动同样有丢失风险。
            **禁止执行 `git push`（不管 push 到这个 worktree 的分支还是任何远程）**——
            commit 在本地分支上就够了，回流合并由 debug-keeper 之后统一处理，push
            完全不属于你的职责范围。
            **遇到需要拍板的歧义**（两种改法都说得通、triage 没写清、发现 issue
            描述与代码实际不符）时，**不要猜、不要挑一个继续**：用 `SendMessage`
            把选项和你的倾向发给 `<debug-keeper 的实际 name，派发前由
            debug-keeper 把它自己当前这个实例的 name 原样填进这段 prompt，
            不要写字面量 opus-debugger——v7 起一档并存多个实例，字面量找不到
            任何一个具体实例>`；不是 `main`——你是
            debug-keeper 派出的末层 fixer，禁止再派任何 subagent；只有
            debug-keeper 判断这个歧义超出它自己权限时才会再走 §12 待拍板协议
            转交给用户），等它拍板。等待期间你会被结束，它答复后你会从
            transcript 被唤醒继续，上下文不会丢。
           【期望输出】把结论写进 <worktree>/.keeper/<交付id>/debug/DBG-024/receipts.md，
            包含：改了哪些文件（逐个列路径）/ 关键决策（为什么这样做、放弃了什么）/
            阻塞点 / 需要 debug-keeper 跟进的事项。同时在回执正文里返回同样内容。
            外加一段**逐层 commit 清单**：每层给出「层路径 + commit 短 hash +
            commit message」，以及该层 `git status --short` 的实际输出（应为空）。
            缺这一段的回执一律视为未完成、会被打回。
            `spec_status: violation` 的 issue 另加一段**规格逐条核对表**：规格里
            每一条断言一行，给出「规格条目 → 实现位置 `file:行号` → 已实现 / 未实现
            + 理由」。规格是表格或清单时，核对表行数必须与规格条数相同，**不许合并
            成一句「已全部实现」**——那句话无法核验，等于没核对。"
)
```

两版模板都保留「禁止修改 `.keeper/<交付id>/debug/` 与 `.keeper/<交付id>/debug/index.md`」
「改完不要自己重启本地服务」「回执写进 `<worktree>/.keeper/<交付id>/debug/<DBG-id>/receipts.md
DBG-NNN.md`」这些既有约束，以及 `name` 与 `run_in_background: true` 这两个字段本身——两条
轨道都要传。真正的差别不在字段有没有，在字段的**用途**与多出来的那一段内容：medium/hard
版的 `name` 是**功能性**的——`SendMessage({to: name})` 唤醒它就靠这个值；easy 档的 `name`
只用于在飞面板可辨识与 §5 对账阶段回查，不会被拿来做 addressing（easy 档一次性发出就不再
管，不存在被唤醒这一步）。medium/hard 版多出来的是交互纪律那一整段（【约束】里教它怎么用
`SendMessage` 问 keeper）与「等拍板前也要先 commit」这半句，这两处 easy 档没有，因为 easy
档从不会走到「等待答复」这个状态。

**「退出前必须逐层 commit」这条不是可以裁掉的客套话，删了它就等于恢复产物丢失
的旧行为。** 实测（真实项目一次高强度批处理）：三个 fixer 交回执宣称完成，改动
却全部停在各自 worktree 的工作区、一个 commit 都没建——因为当时模板里
`commit` 只出现在「禁止 push」那句的从句里（"你只需要把改动 commit 在本地分支上"），
语义重心是"不用你 push"，【期望输出】段则完全没提 commit，于是"改完文件、写好
回执、不 commit 就退出"在字面上完全合规。后果是 keeper 被迫临时把这些未提交改动
导出成一份 patch 分发给其他 fixer 当基线，污染了后续所有对账的基准（多个 worktree
的 `diff --stat` 里出现大量并非本 issue 所改的文件）。所以这条要求必须同时出现在
**【约束】段（写清后果）与【期望输出】段（变成可核对的回执字段）**——只写一处，
fixer 很容易当成背景说明滑过去。

`DBG-NNN/receipts.md` 与回执正文写同样的内容是刻意冗余：回执正文进 debug-keeper
上下文供当场判断，`receipts.md` 随 commit 进入所在 worktree 的分支供合并前对账
与日后回溯（v4 起这份文件**入库**，「随 commit」指的是它作为
fixer 工作产物的一部分被提交在 worktree 的本地分支上，不是说它会进 git 远端历史）。

### 修复前比对确认：fixer 可用 headless agent-browser（不含起服务）

2026-07-30 Human 立规放开了一部分：fixer 仍然**绝对不能**在自己的 DBG worktree
里启动本地服务（这条硬规则不变），但**允许**在动手改代码前调用 `agent-browser`
**无头模式**对着一个**已经在运行、不是自己起的**目标环境做一次比对确认——核实
bug 现象是否与 issue 描述一致、期望效果具体是什么样。这填的是 triage 阶段和
「修复后统一实测」之间的一个空档：triage 阶段（`agents/debug-keeper.md` §4）已经
用 `agent-browser` 拿过一手证据，但那是登记时的快照；fixer 真正动手前，如果对
triage 结论仍有疑问（比如截图转录不够精确、怀疑现象已经变化），可以自己再确认
一次，而不必带着一个可能过时或有偏差的理解直接开始改代码。

**三条硬约束，缺一不可**：

1. **只能无头模式，且必须显式声明**：命令里要有 `--headed false`，不能省略这个
   参数指望它默认走 headless——省略会被全局 `bash-guard.js` 拦下（判据只看命令行
   有没有出现 `--headed` 或 `--headed false` 这个字面片段，不解析真实意图）。
2. **必须传独立的 `--profile`**，路径建议 `/tmp/agent-browser-profiles/<DBG-id>/`，
   不要用 Human 的个人 Chrome Profile，也不要与其他并发 fixer 共用同一个目录——
   同一时刻最多有 3 个 fixer 在开浏览器（见下一小节「并行度」，这个 3 管的是浏览器
   并发上限，不是同时在飞的 fixer 总数），如果都指向同一份 profile，Chrome 的
   profile 锁会让并发实例互相冲突、报「profile 正被另一进程占用」之类的错误。
3. **只能看，不能替代运行时验证**：这次确认只用于「改代码前弄清楚现象」，不能
   当成「改完之后已经验证过」——修复是否真的生效，仍然只由本轮全部 issue 合并
   回主分支后 debug-keeper 的统一实测（§6「合并后统一实测」）来判定。

### 模型分层

**本表只管第二层，不适用于 keeper 自己。** debug-keeper 固定跑 `opus`
（`agents/debug-keeper.md` frontmatter 写死，理由见该文件 §0），因为它的活是「判错一次
由整条流水线承担代价」的调度判断。**这个档不向下传染**：keeper 派 fixer 时按下表从
`sonnet` 起选档，**不要因为「keeper 自己是 opus」就给 fixer 一律开 `opus`**——那是预防性
堆模型，白烧额度且不提高修复质量。

| difficulty × 场景 | 派发 |
|---|---|
| easy × UI/文案 | 有锚点 → `general-purpose/sonnet`；无锚点 → 先 `Explore/sonnet` 定位 |
| easy × 后端机械 | `general-purpose/sonnet` |
| medium × 前端联动 | `general-purpose/sonnet` |
| medium × 后端单方法 | `general-purpose/sonnet` |
| hard × 库 API 密集 | `general-purpose/sonnet`，回执附自测证据 |
| hard × 集成缺失 / 跨文件 | 先 `Explore/sonnet` 出集成图 → `general-purpose/opus` 修 |
| 跨模块 / 改数据结构 | 先 `Plan/opus` 出方案 → **用户拍板** → `general-purpose/opus` 实施 |

`haiku` 档已废弃，不要写（会被 `agent-dispatch` 守卫拦下）。**合并派发至少
`sonnet`**——合并任务的回执要逐 issue 分节对账，低档模型做不到。难度决定档位，
而**并发任务数是一个独立的降档约束**：两个 easy 打包给一个 agent 也不安全，
打包本身消耗指令遵循预算。

**纯探查任务一律选 `Explore`**，权限面更小。`general-purpose` 哪怕 prompt 写明
「只探查不改」也带着写权限，没人能保证它不顺手改。`Explore` / `Plan` 类派发
不需要建 worktree（它们没有 `Edit` / `Write`，产生不了 diff）。

### 并行度

同时在飞的 fixer **最多 8 个**（原 2026-07-30 立规的 5 个已放宽；判据变化见下面两条
拆开之后的独立约束）。这条上限不来自文件冲突——worktree 已经把它物理隔离掉了（见本节
前面「为什么是物理隔离而不是调度」）——只来自**审阅带宽**：8 个回执同时回来时，逐个
核对 diff、判断有没有偏离诉求、决定哪些能合并，这件事本身有上限，超过就会开始「看着
像对的就 accept」。

**另一条独立约束：同一时刻正在调用 headless `agent-browser` 的 fixer 不超过 3 个。**
这个 3 与上面的 8 是**正交**的两个数字——8 管同时在飞几个 fixer，3 管这些在飞的 fixer
里同时有几个正在开浏览器做上一小节「修复前比对确认」。3 的来源是全机唯一那道
`agent-browser` 并发护栏：working-discipline 插件 `hooks/guards/bash-guard.js:252` 写死
`const INSTANCE_LIMIT = 4`，挂在 `PreToolUse(Bash)` 上、只拦命令行里的 `agent-browser
open/connect/chat`，与 `Agent` 派发本身无关。撞满 4 之后，第 5 个发起 `agent-browser
open` 的 Bash 调用会被这道闸 `deny`——**卡点是那次 Bash 调用本身（浏览器启动这一步），
不是这条 fixer 被派发的那一步**：fixer 已经在跑，只是走到开浏览器这一步才被拦。留 1 个
名额给主会话自己可能同时开着的 `agent-browser` 会话，分给 fixer 的额度因此是 4-1=3。
**修复前比对确认本身是可选动作**（上一小节原文用的是「允许」不是「必须」），大多数
批次里同时要开浏览器的 fixer 远少于 3，只有 8 个在飞 fixer 里凑巧有超过 3 个在同一
时刻都要做这次比对确认时才会撞到这条上限——撞到时晚发起的那个等前面的关闭再开，
不是任务失败。

**正在等待答复的交互式 subagent 不占「8 个」这个额度**——上一节已给出实测依据
（`SendMessage` 返回 `had no active task`，说明它是「结束 + 被唤醒」而非挂起）。
所以并发计数只统计真正在跑的 fixer，不含挂着问题等拍板的交互式 subagent。

## 5. 合并前对账（三件套）

### 时机：合并前，不是 subagent 结束时

v2 把对账挂在 `SubagentStop` hook 上。实测在一个跑了 14 个 subagent 的会话里，
该 hook 的三种输出串在主 transcript 与全部 14 份 subagent transcript 里**零命中**
——它的介入门槛是 `status == "in_progress"`，而那个值从未被写过。

v3 改在合并前手工做，反而更可靠：那时改动已经是 commit，`git diff --stat` 就是
权威事实，不需要从回执文本里猜。对 `claude --bg` 起的独立后台会话也适用（它们
结束时触发的是 `SessionEnd` 而非 `SubagentStop`，hook 方案对其完全失效）。

### 判据

设 `D` = git 实际改动文件集，`R` = `DBG-NNN/receipts.md` 声称改动的文件集：

```bash
DID="$(basename "$ROOT")"                                    # 交付 id，非交付 worktree 用 _main
WT="$ROOT/.keeper/$DID/debug/DBG-017/worktree"
SRC_BRANCH="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"   # 源 worktree 当前分支
git -C "$WT" diff --stat "$SRC_BRANCH"...HEAD   # 得到 D 与行数
# R 读 HEAD 那一份（v6；工作区那份可能是未 commit 版本，见下）
git -C "$WT" show "HEAD:.keeper/$DID/debug/DBG-017/receipts.md"
```

**为什么 R 必须用 `git show HEAD:` 而不是 `cat`**（v6 判据，2026-08-10 入库策略反转后
**恢复 v4 那条、推翻中间那版 v5 的「用 `cat` 读工作区」**）：

v6 起 `receipts.md` 是被跟踪文件，fixer 在自己 worktree 里 commit 它、`merge-back` 把
`HEAD` 那份带回来。而工作区那份可能是它写了但**还没 commit** 的版本；两者不一致时
`cat` 让你对着一份**不会被合并**的申报做对账，结论全错且没有任何信号提示你读错了那份。

v5 期间 `.keeper/` 整树被忽略，`git add` 不会暂存 receipts，`git show HEAD:` 恒定报
`does not exist in 'HEAD'`，所以当时改用 `cat`、并把「回去追 fixer 补 commit」判为
「追一件它做不到的事」。**那个前提已经不成立**——ignore 规则不再挡住 `git add`，追得
动了。照 v5 的说法用 `cat`，会重新踩回 v4 当初修掉的那个坑。

失败信号回到 git 通道：`git show HEAD:` 报 `does not exist in 'HEAD'` 时说明 fixer
写了没 commit（或压根没写），**回去追它补 commit**——这半判据的动作没变，只是这次
它确实做得到。

**两条连带动作，都没有机械兜底**：

1. **accept 之后、清理 worktree 之前**，把 receipts 拷回 delivery 队列，否则它随
   worktree 一起消失（v4 靠合并带回来，v5 不会）：
   ```bash
   cp "$WT/.keeper/$DID/debug/DBG-017/receipts.md" \
      "$ROOT/.keeper/$DID/debug/DBG-017/receipts.md"
   ```
   注意「各层 `git status --short` 为空才允许清理」那道保命闸**对它不响**——receipts
   被 ignore、压根不出现在 status 里。
2. **存量仓例外**：v4 期间队列已被 git 跟踪的仓里 ignore 规则不生效、receipts 仍在
   版本库中，v4 那条「工作区版本可能未 commit」的风险依然存在。那种仓里两份都读、比对
   一致再对账。

**基线必须取源 worktree 的当前分支，不能写死 `main`。** `init` 建 worktree 用的是
`git worktree add <target> -b fix/<id> HEAD`，基线是**源 worktree 的 HEAD**；而
debug-keeper 通常跑在和主会话同一个源 worktree 上下文里，源侧分支可能形如
`D-001-feat-xxx`。写死 `main` 时实测**不是算错、而是命令直接报错**（`main` 这个 ref
在那个仓里根本不存在）：

```
Use '--' to separate paths from revisions, like this:
'git <command> [<revision>...] -- [<file>...]'
```

拿不到 `D` 就等于跳过了对账。用 `"$SRC_BRANCH"...HEAD` 的三点语法则天然正确——它等价于
`merge-base($SRC_BRANCH, HEAD)..HEAD`，那个分叉点就是建 worktree 那一刻源侧的 HEAD。这也
意味着**源侧在 `init` 之后继续提交不会污染对账**：实测源侧新增 `other.js` 后再跑，输出
仍只有 fixer 改的 `bug.js`。若源侧处于 detached HEAD（`--abbrev-ref HEAD` 会返回字面量
`HEAD`），先把它切回分支再对账。

1. **幽灵改动**（`D − R ≠ ∅`）：改了没说。多半是顺手改或任务串味。
2. **幻觉回执**（`R − D ≠ ∅`）：说了没改。**比第 1 条更危险**——它会让你以为
   修好了直接 accept，bug 原样留着还被标成 done。
3. **量级偏离**（实际行数 > 3× 预期）：改对文件但溢出，把 3 行修复变成 200 行
   待 review 的重构。

`.keeper/` 下的文件在两侧都豁免——fixer 写自己的 `DBG-017/receipts.md` 是规定动作，
把它算成幽灵改动会让每次对账都不过。**v5 下这条豁免多数时候自动生效**：整树忽略让
`.keeper/` 压根不出现在 `git diff --stat` 里（回到 v3 的处境），豁免属于"总不命中、
但留着无害"。仍然保留明文，是因为 v4 期间队列已被 git 跟踪的存量仓里它**一定会出现在
`D` 里**，那种仓不豁免就是每次必然误判。

### 这套对账抓不到什么（别高估它）

它只比对**文件集合与行数**，不判断改得对不对。三种情况它完全无感：改对了文件但
逻辑是错的；改对了逻辑但没覆盖 `验证` 章节列出的全部场景；申报与实际都是同一个
错误文件（比如把 `Step3Indicators.vue` 错写成 `Step4Matrix.vue`，而 fixer 也确实
改了后者）。所以对账通过**不等于**可以 accept，它只是排除了三类机械性失真。

运行时行为是否真的正确，对账本身不覆盖、也不应该覆盖——那是 §6「合并后统一实测」的
职责。fixer 已被禁止在自己的 worktree 里起本地服务（见 §4 两版模板【约束】段），
修复前允许的那次 headless `agent-browser` 比对确认（见 §4「修复前比对确认」）也
只是「改代码前弄清楚现象」，不是运行时验证，所以 `验证` 章节此刻交回的结论天然
只是代码审查/单测层面的，对账通过 + `验证` 章节看着合理，也只能支撑「按现有信息
accept、进入合并」，不能当成「运行时已验证」。

## 6. 收尾

### accept 之后：先合 submodule，再回写 gitlink，顺序不能颠倒

fixer 的 commit 在 worktree 供给出来的 submodule 分支上。回流必须先合 submodule、
再回写父仓 gitlink——父仓 gitlink 只有在 submodule 合完之后才有新值可写。这个顺序
由 `wt_supply.py merge-back` 内部保证，**不需要你手工分两步做**。

#### v7 新增前置：merge-back 前必须先拿合并锁

同一个交付的 `.keeper/<交付id>/debug/` 下可能同时并存好几个 debug-keeper 实例，各自
认领不同的 issue，但它们的 fixer 最终都要 merge-back 回**同一个** delivery worktree
父仓——这是所有实例共享的唯一资源。两个实例前后脚各自跑 `merge-back --apply`，
后一个会在前一个还没提交完的中间状态上开始操作，轻则拿到误导性的"父仓不干净"前置
校验失败，重则在多层 submodule 场景下把两次回写交织进同一次 `git merge`，产生分不清
源头的冲突。

跑 merge-back（含下面"先在目标 worktree 父仓 commit gitlink"这一步）之前，先拿锁：

```bash
python3 <插件根>/scripts/keeper_cli.py lock acquire --name <自己的 name> --issue <DBG-NNN>
# ...跑下面「先 commit gitlink」与「回流本体」两步...
python3 <插件根>/scripts/keeper_cli.py lock release --name <自己的 name>
```

退出码 3 = 锁被别的实例占着，正常竞争，等一会儿重试，不要绕开锁硬跑。完整的锁语义
（TTL、抢占后要先检查目标 worktree 是不是停在半完成的 merge 状态、`release` 失败
代表什么）见 `references/keeper-dispatch.md` §5——两处共用同一把锁，不要重新发明一套。

#### 跑 merge-back 之前：先在目标 worktree 父仓 commit gitlink（不做这步必定被阻断）

fixer 在 submodule 里一提交，目标 worktree 的**父仓**立刻出现一条 `M <submodule路径>`
（gitlink 指向变了）。而 `merge-back` 的前置校验要求目标 worktree 父仓干净，于是照
「fixer 交付 → 直接 merge-back」的顺序跑，**100% 会被挡下**，实测退出码 `2`：

```
  前置校验不通过（1 项），未执行任何操作：
    ✗ 目标 worktree 父仓不干净（1 项）：<WT>
      M libs/sm
[wt_supply] merge-back 中止。修掉上面每一项后重跑。
```

所以先把这条 gitlink 提交掉（在**目标 worktree** 里做，不是源侧）：

```bash
git -C "$WT" status --short                       # 应只有 M <submodule路径> 这类 gitlink 变更
git -C "$WT" add <submodule路径>                   # 逐个 add，别 add -A（避免捎带无关文件）
git -C "$WT" commit -m "chore(DBG-017): 回写 submodule gitlink"
```

补完这次 commit 后同一条 `merge-back` 就能通过（实测退出码由 `2` 变 `0`）。注意 `git status`
里若出现的**不止** gitlink 变更，说明 fixer 有未提交的工作，先回去追问、不要替它 commit。

#### 回流本体

`WT_SUPPLY` 的动态发现写法见 §4（`${CLAUDE_PLUGIN_ROOT}` 在这里不可靠，不要用）：

```bash
WT_SUPPLY="$(find ~/.claude/plugins/cache -maxdepth 6 \
  -path '*/task-keeper/*/skills/tk-worktree/scripts/wt_supply.py' 2>/dev/null | head -1)"
python3 "$WT_SUPPLY" merge-back --worktree "$WT"            # dry-run，零副作用
python3 "$WT_SUPPLY" merge-back --worktree "$WT" --apply    # 核对无误后才跑这条
```

**没有 `--onto` 参数**，不要去传：合并落点就是**源 worktree 当前所在的分支**，各层的
落点是源侧那一层当前所在的分支。脚本自底向上（最深嵌套层先合）逐层做三件事——先 commit
子层刚回写的 gitlink，再 `git merge --no-ff <目标侧分支>`，然后把本层新 HEAD `git add`
进父层，父仓最后合。

"先 commit 子层 gitlink"这一步是必须的，不是可选优化。实测：若把子层合出
的新 HEAD 留在工作树里不 commit 就直接 merge 父层，git **不报错**，而是把父层 gitlink
直接写成目标侧那个 tip、丢掉源侧刚做出的 merge commit，工作树只留下一条 `M <sm>`——
源侧该层若本来有自己的提交，那些内容就在这一步被静默丢弃。

**前置校验不通过就整体阻断**（退出码 `2`，不做局部执行）：两侧父仓与每一层的目标侧、
源侧都必须干净；目标侧父仓不能 detached HEAD；有层处于 `isolated-objdir` / `unreachable`
/ `source-missing` / `prunable` 一律拦下；**每层源侧分支必须等于源父仓分支**——不一致时
无法判定该层该合到哪里，所以整体阻断而不是猜（旧实现在这里会静悄悄合到错分支）。

`--apply` 会在**源侧各层与父仓上真的建 commit**（gitlink 回写用 `chore(wt-supply): …`，
合并用 `merge(wt-supply): …`），但**不 push**。

**push 不是这个流程默认包含的动作，任何情况下都不要未经 Human 当轮明确同意就自己
执行。**（2026-07-30 Human 立规）走完 `merge-back --apply` 只是在本地建好了
commit，push 与否、什么时候 push，由 debug-keeper 在 Human 当轮明确同意后自己
决定和执行——不能把 Human 对 merge-back dry-run 清单的确认，或对某条 issue 的
accept，误读成 push 授权，这是两次分开的决定。fixer 更不允许 push：它在自己隔离的
worktree 里执行 `git push` 会被 `hooks/pre-tool-use-debug-worktree-push.sh` 机械
拦下（deny，命中路径含 `.keeper/<交付id>/debug/<DBG-id>/worktree/` 即触发，见该 hook 与
`lib/debug_worktree_push_guard.py` 的模块头注释）；debug-keeper 自己推主分支的
push 不在这个机械覆盖范围内（该 hook 只拦截目标路径落在 `.keeper/<交付id>/debug/<DBG-id>/worktree/` 下的
push），只能靠这条写死的指令自觉遵守。

**这一步会改 gitlink 指针，凡是会改 gitlink 指针的操作，通用纪律都是同一条**：
操作前把新旧 commit 的 message + 短 hash + 日期列出来给 Human 过目、等确认后再
执行不可逆的那一半——`merge-back` 的 dry-run 输出就是给 Human 确认用的那份清单，
`--apply` 前把它贴给用户看，等确认了再补跑一次 `--apply`。这条纪律不是本插件
独有，凡是涉及 submodule gitlink 变更的操作都适用，遇到专门的 gitlink 更新类
skill 时以那个 skill 的具体流程为准，本节只强调"确认在先、不可逆在后"这个顺序
不能颠倒。

gitlink 回写完成后，把 issue 文件的 `status` 改成 `done`，在「修订记录」章节
追加本轮结果，然后清理 worktree：

```bash
WT_SUPPLY="$(find ~/.claude/plugins/cache -maxdepth 6 \
  -path '*/task-keeper/*/skills/tk-worktree/scripts/wt_supply.py' 2>/dev/null | head -1)"
python3 "$WT_SUPPLY" remove --worktree "$WT" --yes
```

**不要**直接用 `git worktree remove` + `git branch -d` 两行清理含 submodule 的
worktree——实测会失败：`git worktree remove` 报 `fatal: working trees containing
submodules cannot be moved or removed`；就算强行先删子层，父层又会因为子层的
残留状态报 `contains modified or untracked files` 变 dirty。`wt_supply.py
remove` 内部按深度优先顺序清理（先子后父），删掉子层 worktree 后**把空目录
`mkdir` 回填**来消除父层的 `D <path>` dirty——对未初始化的 submodule，git 认为
空目录即干净状态，父层立刻恢复 clean。缺省它会连父仓工作区一起删干净，只想清
submodule 层就加 `--keep-parent`。

**它刻意不跑 `git submodule deinit -f`，将来也不要加回来。** 实测在 linked
worktree 里 deinit 会从**与源仓共享的** `.git/config` 里删掉
`submodule.<name>.url`，连主 checkout 的 `git submodule status` 都跟着从 ` `
（已初始化）变成 `-`（未初始化）——那是波及主 checkout 的副作用。而本链路的供给
全部从源侧发起、从不碰主 checkout 的 submodule 初始化状态，压根没有需要 deinit
收拾的东西。同理也不用 `worktree remove --force`：那是掩盖因果而不是消除原因，
真报 `contains modified or untracked files` 时说明里面有未提交内容，该人工确认。

**worktree 必须删**。不删的话 `git worktree list` 里它还在，hook 会继续把这条
issue 标成「在飞」，而 index.md 里它已经是 done——快照会给出「⚠ 这个 worktree
对应的 issue 已不在 open 桶」的提示，那就是提醒你清理。

**`remove --yes` 会顺带自动清理它当初建过的每层分支**（`fix/<id>` 这类），不需要
你再手工 `git branch -d` 一遍：已被上面 `merge-back --apply` 合过的分支直接删掉，
这次 issue 根本没碰到的 submodule（分支存在但没有新提交）也一并删掉；只有分支还
有未合并提交时才会保留并打印原因（多半是 `merge-back` 没跑就直接叫了 `remove`）。
想保留分支供人工核实时加 `--keep-branches`。

### 销毁 delivery worktree：git 不会警告你正在删掉 fixer

上面整段讲的是**销毁 fixer worktree**（`.keeper/<交付id>/debug/<DBG-id>/worktree/`）。
这一小节讲的是**销毁 delivery worktree 本身**（`.sdlc/worktrees/D-NNN-<slug>/`），
两者是不同的对象、规矩也不同——delivery worktree 不是 task-keeper 建的、也不归它
管，但整个队列连同还在飞的 fixer 都住在它里面，所以销毁它的后果由 task-keeper 承担。

**先记住这一条，其余都是它的推论：`.gitignore` 里那条整树忽略规则（v5 是 `.keeper/`
一行；v4 时是精确的 `.keeper/**/worktree/`，效果对本节结论没有区别），让 git 在删
delivery 时看不见嵌套的 fixer worktree，因此不会给出任何警告。**

平时保命的那道闸是 `fatal: '<path>' contains modified or untracked files, use
--force to delete it`——本文和 `agents/debug-keeper.md` 都写着「撞到它别加
`--force`，那是在删掉 fixer 还没提交的修复」。**那条闸在这里不响**。2026-08-01 实测：
delivery worktree 里嵌着一个内容完整的 fixer worktree 时，直接跑
`git worktree remove <delivery路径>` **exit 0、静默成功**，fixer 连同里面未提交、
未推送的修复一起消失，只在主仓留下一条可 prune 的悬空登记。对照实验：同一个
delivery 里放一个**没被 ignore** 的 `scratch.txt`，同一条命令立刻报
`contains modified or untracked files` 并拒绝执行。

也就是说：ignore 规则买到了「队列 diff 不污染工作区」，代价是**丢掉了这个位置上的
误删保护**。这不是可以修的 bug（要保护就得让 fixer worktree 入库，那会种野生
gitlink，见 §gitlink 铁律），只能靠下面的顺序自己补上。

#### 执行顺序（照抄，不要跳第 1 步）

```bash
DELIVERY="$(cd <delivery路径> && pwd -P)"   # 必须 -P：/tmp 之类的符号链接会让下面的前缀匹配静默漏掉
MAIN=<主仓路径>

# 1. 枚举并逐个正常清理嵌套 fixer worktree —— 这一步是给你自己看的保护，不是给 git 看的
git -C "$MAIN" worktree list --porcelain | awk '/^worktree /{print $2}' \
  | while read -r wt; do case "$wt" in "$DELIVERY"/*) echo "$wt";; esac; done
#    对列出的每一个跑（它带干净度检查，脏了会拒绝，那正是你要的）：
python3 <插件根>/skills/tk-worktree/scripts/wt_supply.py remove --worktree "$wt" --yes

# 2. 删 delivery 本体
git -C "$MAIN" worktree remove --force "$DELIVERY"

# 3. 清残留登记（第 1 步漏掉的、以及 submodule 层的，都在这里被收走）
git -C "$MAIN" worktree prune -v

# 4. 验零残留
git -C "$MAIN" worktree list --porcelain
ls "$MAIN/.git/worktrees/"
git -C "$MAIN" worktree prune -v -n        # 应无输出

# 5. 分支要单独删 —— remove 与 prune 从不碰 refs
git -C "$MAIN" branch --list "fix/<交付id>-*" "delivery/<交付id>"
```

第 1 步不能省，理由就是本节开头那条：**没有它，第 2 步会静默吃掉 fixer 的未提交
修复**。`wt_supply.py remove` 自带的干净度检查是这个位置上唯一还在工作的保护。

第 1 步的枚举也**不是完备的**，别把它当作充分条件：`git worktree list --porcelain`
从主仓跑**看不到 submodule 层的 worktree 登记**（那些登记住在
`<主仓>/.git/worktrees/<delivery-admin>/modules/<sub>/worktrees/<name>`，不在主仓
自己的登记表里）。它们由第 3 步的 `prune` 收走——那些层的 gitdir 物理上就在被删的
delivery 里面，删完即成悬空。所以顺序必须是「先删 delivery、后 prune」，反过来
prune 什么也清不掉。

#### `--force` 在这里是必须的，这不推翻「不许加 --force」那条

第 2 步的 `--force` 与本文和 `debug-keeper.md` 里禁止 `--force` 的表述**不冲突**，
因为 `git worktree remove` 有两种拒绝，此前的文字把它们混为一谈了：

| 报错 | 性质 | 处置 |
|---|---|---|
| `fatal: working trees containing submodules cannot be moved or removed` | **结构性拒绝**，与干净与否无关。实测：delivery 只要有一个已初始化的 submodule，即使工作区完全干净也照样退 128 | 加 `--force`。它在这里跳过的是一条与安全无关的限制，不掩盖任何东西。有 submodule 的项目里这是唯一出路 |
| `fatal: '<path>' contains modified or untracked files, use --force to delete it` | **干净度拒绝**，里面真有没提交的内容 | **不许加 `--force`**。先查清是谁的改动。这条规矩不变 |

判据是**看报错原文**，不是看命令。同一条 `--force` 用在前一种是必要，用在后一种
是删数据。`wt_supply.py remove` 之所以不需要 `--force`，是因为它用「深度优先 +
删完子层把空目录 `mkdir` 回填」把第一种拒绝从根上消掉了（见上一小节）；delivery
worktree 没有对应的脚本，只能直接吃 `--force`。

#### 未覆盖的边界（撞到了别按本节推断）

2026-08-01 那次实测**没有**覆盖：≥2 层嵌套 submodule；用户自建的符号链接（只测了
`/tmp` 这个系统符号链接）；`git worktree lock` 生效时的行为；先 `merge-back --apply`
再销毁的组合；remote 不可达的 submodule。撞到这些先停下人工确认。

`status: done` 的条目**这一轮先留在队列目录不动，等交付收官再统一
归档**（见下一小节「归档」）。

v2 有个 `archive.yaml` 归档机制，v3 曾一度取消它：done 的文件本来就不进上下文
（`index.md` 只列一行 id 链接），移动它会让 `next_id` 的派生逻辑失去 id 历史、
造成编号重用——这是真实风险，不是臆测：`next_id` 当时的实现只扫现存条目
目录的文件名，一旦 done 文件被移出这个目录，它的编号就会被误判成「没用过」，
下一条新 bug 可能拿到同一个编号，两条不同的 bug 共用一个 id、分别躺在两个
目录里。

归档功能重新做回来，但**形态不同、不会重犯这个坑**：不是 v2 那种
需要人工维护的 `archive.yaml` 索引文件，而是「按交付批次的目录搬迁
（`shutil.move`）+ `next_id` 归档感知」的组合——`next_id`（`hooks/lib/
queue_files.py`）现在同时扫现存条目目录名**与** `archive/<批次>/<id>/` 归档目录名
两处的文件名再取最大值+1，只看文件名不解析 frontmatter（即使归档文件的
frontmatter 损坏，编号也仍然计入历史）。所以归档之后旧编号不会被回收：
「移动 done 文件」与「id 历史完整」这两件事这次是同时满足的，不再是二选一。
**用 `shutil.move` 而不是 `git mv`**——一次归档搬几十个目录、夹着未跟踪的截图，
从未被 git 跟踪过，`git mv` 对未跟踪文件必然报 `fatal: not under version
control`，归档只能是纯文件系统操作。

### 归档：交付收官后把 done 条目搬进 archive/

队列目录会被历史上已经 done 的条目越撑越大——虽然 `index.md` 的 done
桶只列 id 不列正文，但 `load_all()` 每轮都要扫过全部历史文件，目录本身也会
无限增长。**每一轮交付收官、本轮涉及的 worktree 都清理完成之后**，跑一次归档
脚本，把这一批 done 条目连同它的 receipts 与 attachments 成组搬到
`archive/<交付批次>/` 下：

```bash
ARCHIVE="$(find ~/.claude/plugins/cache -maxdepth 6 \
  -path '*/task-keeper/*/skills/tk-debug/scripts/archive_done.py' 2>/dev/null | head -1)"
python3 "$ARCHIVE" --queue-dir "$ROOT/.keeper/debug" --batch D-001-feat-xxx           # dry-run，先看清单
python3 "$ARCHIVE" --queue-dir "$ROOT/.keeper/debug" --batch D-001-feat-xxx --apply   # 核对无误后才跑这条
```

也可以用自动归档模式，不必自己判断阈值，脚本会按 done 条目数与最早 `reported_at`
的年龄自己决定要不要归档：

```bash
python3 "$ARCHIVE" --queue-dir "$ROOT/.keeper/debug" --auto --apply
```

批次名默认从队列目录绝对路径里提取 `worktrees/<slug>/`（交付级 worktree 布局下
天然带这一段；fixer 自己的 `.keeper/<交付id>/debug/DBG-*/worktree` 不会走到这里，归档由 keeper
在真身队列上执行）；取不到时退回当前 git 分支名清洗后使用；`--auto` 模式固定用
`auto-<YYYYMMDD>`（当天日期）；都取不到就要求显式传 `--batch <名字>`，不会静默
拼一个可能错的名字。`--queue chore` 可以对 chore 队列跑同一套归档，但那是
`tk-chore` 的事，不在本文档范围内。

**安全边界**：只搬 `status: done` 的条目，`open` 的绝不碰；`worktrees/` 与
`index.md` 绝不碰（前者是未入库的临时产物，后者由 hook 重算）；某条 done issue
仍存在对应的 `worktrees/DBG-NNN/` 时会被跳过并给出警告——那说明 worktree 还没
清理干净，可能还有 fixer 未提交的产物，此时不该把这条 issue 归档走。脚本用
`shutil.move` 而不是普通移动或 `git mv`，失败时（比如目标已存在）fail-loud 报出来
并跳过该条，不中断整批。搬迁完不自动 commit——由 keeper 在收尾窗口一并提交，
不存在「是否 commit 这次归档」的问题。

### 从 v3 迁移到 v4（一次性布局迁移）

**本文正文描述的已经是 v4**（一交付一目录、一条目一目录，见 §1）。已建过 v3 队列
（单目录、按类型分桶：`issues/` / `receipts/` / `attachments/`）的项目需要跑一次性
迁移，脚本是 `skills/tk-debug/scripts/migrate_layout.py`：

```bash
MIGRATE="$(find ~/.claude/plugins/cache -maxdepth 6 \
  -path '*/task-keeper/*/skills/tk-debug/scripts/migrate_layout.py' 2>/dev/null | head -1)"
python3 "$MIGRATE" --keeper-dir "$ROOT/.keeper"                # dry-run，先看清单
python3 "$MIGRATE" --keeper-dir "$ROOT/.keeper" --apply        # 核对无误后才跑这条
```

默认 dry-run；存量条目（无法判定原本属于哪次交付）一律归入 `_main` 桶，可用
`--delivery <id>` 显式指定改归到哪个交付。幂等（重复跑只会处理仍留在 legacy 路径
下的条目，不会出错也不会重搬）。`.keeper/<交付id>/debug/DBG-NNN/worktree/`（活的 git worktree）
一律跳过不搬，报告里会列出来并提示先 `wt_supply.py remove` 清理，或迁移后手动执行
`git worktree repair <新路径>`（实测可行，但脚本刻意不自动做这一步——「移动 + 修复」
连续动作一旦某一步算错，两头登记都会指错，细节见脚本文件头注释）。

### 合并后统一实测（二次确认）

fixer 已被禁止在自己的 DBG worktree 里起本地服务（见 §4 两版模板【约束】段），
唯一允许的 headless `agent-browser` 调用也只是修复前的比对确认（见 §4「修复前
比对确认」），不构成运行时验证，所以「对账通过 → accept → 合并 → 删 worktree」
这条链路走完时，
本轮所有 issue 各自的 `验证` 章节还只是代码审查/单测层面的结论，没有一条被真实跑过。
**这一步补的就是这个缺口**：本轮涉及的 issue 全部合并、worktree 清理完成之后，由
debug-keeper 在主工作区（不是任何一个已经删掉的 DBG worktree）**统一起一次服务**，
逐条按各 issue `验证` 章节列出的场景实测。

判定与后续处理：全部场景都通过，各 issue 保持 `status: done` 不再动；某条 issue 的场景
测出问题，视为该条被 reject——`reopen_count` +1、`status` 改回 `open`，把失败现象（哪个
场景、实际表现是什么）写进该条「修订记录」章节，按 §3 的 reopen 升级阶梯决定下一轮怎么
派，**不影响本轮其余已通过 issue 的 `done` 状态**（一条测出问题不必连坐拖住整批）。

这一步是 accept 之后的**二次确认**，不是 accept 的前置依据——accept 的判断依据仍然是
§5 的对账三件套（文件集合+行数比对）；这么设计是为了避免「先起服务实测、通过了才 accept」
这种顺序在多个 worktree 并行修复时逼着每个 fixer 各自起一份服务（端口冲突、也不代表合并
后的真实状态），统一挪到合并之后一次性测，既避免资源浪费，也让实测对象是「真正会上线的
那份合并结果」而不是某个孤立 worktree 里的半成品状态。

### 外部工单回写（通用契约，合并 + 实测通过后，仅带 `external_ref` 的 issue）

**触发判据**：issue frontmatter 的 `external_ref` 存在，格式 `<系统名>#<id>`（例如
`TRACKER#644168`，字段声明见 `hooks/lib/queue_files.py:84`；代码不做前缀校验，
任何系统名都可以写）。task-keeper 机构无关，不内置任何具体工单系统的回写代码——
具体是 Jira、GitLab issue、公司自建系统，各有各的鉴权和 API，这部分交给
`references/external-tracker.md` 描述的可插拔适配器 skill 承担。

放在「合并 + 实测通过」之后而不是 `status→done` 那一刻，是为了避免状态流转在
实测打回 reopen 时要再回退一次——多一次流转既打扰工单关注者，也让「已修复」语义
失真。流转发生时改动已被真实验证，工单状态与代码实际状态才会一致。

**通用五步**（无论对接哪个系统都适用，具体动作名 / API 调用由找到的适配器 skill
决定）：

1. **读适配器契约**：按 `references/external-tracker.md` 的三层发现顺序找到能
   处理这条 `external_ref` 的适配器 skill；找不到就在回执里报「未回写（无
   适配器）」，不阻塞 `done`，进第 6 步之前的流程到此为止。
2. **回写前把动作清单 + 对象 + 内容原文出示给 Human，等当轮授权**：状态流转多数
   不可逆，落地前一次性列出「工单号 + 打算执行的动作名 + 要写的评论/字段全文」，
   等 Human 明确回复确认再继续——不能把「合并已确认」或「issue accept」误读成
   这次外部写操作的授权，这是两次分开的决定。
3. **逐条回写**：按适配器 skill 的接口执行状态流转 / 追加评论 / 更新字段。
4. **每写一条立即用读接口回读逐字段核对**：2xx 响应不等于字段真的生效，写完
   立刻用只读接口把刚写的字段读回来，逐个比对是否与期望一致。
5. **把回读到的实际值写进回执**：不要只写「已回写」，要写「回读到状态=X、评论
   已在列表里」这类可核verify 的具体值。

**三条铁律**：

- **不编造工单号或状态名**：动作名 / 状态名随系统、随团队模板变化，编造或用
  近似值硬写会被平台拒绝或写进错误状态；解析不到就问 Human，不要猜。
- **不跨组织写**：适配器 skill 的鉴权范围是什么就只在那个范围内写，不要因为
  凑巧有权限就写到范围外的工单或系统。
- **2xx 不等于字段生效**：写操作的 HTTP 状态码成功只代表请求被接受，不代表
  目标字段真的变成了期望值（异步处理、字段校验失败但静默降级等情况都会导致
  「写了但没生效」），第 4 步的回读不可省略。

鉴权失败、适配器不可用等属于「未回写」而非「阻塞」：代码已经修复合并，工单侧
的回写是锦上添花的收尾动作，缺了它不应该反过来卡住 `done` 状态。在 issue「结局」
章节记一句「外部工单未回写：<具体原因>」，交给后续人工或下一次会话处理。

完整的三层适配器发现顺序、适配器 skill 必须实现的输入输出契约，见
`references/external-tracker.md`。

### reject 之后

把用户的 reject 原因**全文**写进 issue 文件的「修订记录」章节，`reopen_count` +1，
`status` 保持 `open`，按 §3 的升级阶梯决定下一轮怎么派。不要清掉上一轮的记录——
下一个 fixer 需要知道上次错在哪，否则很可能原样再错一次。

## 7. 什么时候不适用本文

单条一行的小修（改个错别字、调个常量），用户明确说「你直接改」时，不必建
worktree、不必写 receipts——建 worktree 的开销比改动本身大。但**仍要登记 issue
文件**，否则这次改动在队列里没有痕迹，日后回溯不到是谁、为什么改的。
