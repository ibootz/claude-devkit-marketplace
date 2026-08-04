# task-keeper

常驻 keeper 子代理托管 debug 队列与杂务队列：主会话只做「分类分派 + 需要人拍板时集中问一次」，
登记、triage、修复派发、对账、归档全流程都在 keeper 的独立上下文里跑，不占用主会话窗口。
通用、机构无关——公司专属能力（如 ONES 工单回写）通过适配器接线，不进本插件。

## 组成

| 类型 | 名称 | 作用 |
|---|---|---|
| skill | `tk-debug` | debug 队列全流程指引（登记 → triage → 一 issue 一 worktree 派发 → 合并前对账 → 归档） |
| skill | `tk-chore` | 杂务队列：主会话判是杂务就转 chore-keeper，自己立刻回原任务 |
| skill | `tk-decisions` | 决策打包 HITL 协议正典（keeper 与主会话之间怎么攒批问人） |
| skill | `tk-worktree` | 为 `git worktree` 建的工作区供给 submodule 内容（含嵌套递归），4 个子命令 |
| agent | `debug-keeper` | 独占 `.keeper/debug/` 写权限，承接 bug 报告全流程 |
| agent | `chore-keeper` | 独占 `.keeper/chore/` 写权限，承接杂务登记与攒批执行 |
| hook × 7 | 见下表 | 注入路由/队列快照 + 三道窄判据守卫 + 1 个 keeper 实例登记 |

## hooks（挂载事件与实际行为）

| 脚本 | 事件 | 行为（按动作描述，不是按愿望描述） |
|---|---|---|
| `session-start-keeper-routing.sh` | SessionStart | 纯注入**静态参考**（决策打包主会话侧职责、v4 布局、指针）。未启用 221 字符（一句话介绍 + 启用方式），已启用 671 字符，不拦截任何操作 |
| `user-prompt-submit-keeper-routing.sh` | UserPromptSubmit | 纯注入**三岔口分诊**（自己做 / 转 debug-keeper / 转 chore-keeper）+ 转发三原则 + 唤醒前先读 name 登记文件那句提醒，523 字符。未启用项目 stdout 全空 |
| `user-prompt-submit-debug-queue.sh` | UserPromptSubmit | 注入 debug 队列实时快照（open 逐条 + 在飞派生 + done 计数）、重算薄索引 `index.md`（git rebase/bisect/merge 中间态跳过）；`.gitignore` 有整树忽略行或缺三条精确规则时各加一句提醒；存量 v3/v2 布局未迁移时加一句迁移提示；命中 bug 特征词时给出下一个可用 DBG-id（fixer worktree 内不给） |
| `user-prompt-submit-chore-queue.sh` | UserPromptSubmit | 注入 chore 队列快照（输出预算 ≤900 字符）；`.keeper/` 顶层存在时缺失的 `chore/`（连同 `debug/`）由 `find_queue` 每轮自动补建，不需要手工 mkdir；代注待拍板决策计数（自动补建后 `chore/` 恒存在，debug 快照的兜底注入分支实际只在 fixer worktree 内或补建失败时才会走到，两边判据仍是同一个目录的存在性） |
| `pre-tool-use-debug-worktree-push.sh` | PreToolUse(Bash) | `git push` 的目标落在 `.keeper/<交付id>/debug/<DBG-id>/worktree/` 内时 deny（fixer 产物只回流不推远端） |
| `pre-tool-use-debug-worktree-destroy.sh` | PreToolUse(Bash) | 强制删除形态（`rm -rf` / `worktree remove --force` / `clean -fdx`）命中 `.keeper/<交付id>/debug/<DBG-id>/worktree/` 路径时 ask 弹确认框 |
| `pre-tool-use-debug-evidence.sh` | PreToolUse(Write\|Edit) | 只对 `.keeper/<交付id>/debug/*.md` 介入：新内容含 `image-cache` 会话级临时路径时 deny（跨会话必 404），带次数熔断，`origin_path` 留档豁免 |
| `pre-tool-use-keeper-instance.sh` | PreToolUse(Agent) | 命中 keeper 类 `subagent_type`（`debug-keeper`/`chore-keeper`）的派发时，把 `tool_input.name` 写进 `.keeper/<交付id>/.keeper-instance.json` 对应键，另一个键原样保留；**纯写文件，不拦截任何操作**，不输出 permissionDecision，写不进去就静默放弃 |

三道守卫的判据都是路径子串 + 命令形态的机械判定，未启用队列的项目全部零输出零成本。
`pre-tool-use-keeper-instance.sh` 不是守卫——它不拦下任何动作，只有"顺手写一个登记
文件"这个副作用，供主会话下次唤醒 keeper 前读取真实 `name`（见下方「登记 keeper
实例 name」）。

## 产物布局：`.keeper/<交付id>/`，文本入库、截图与 worktree 不入库

```
<项目根>/.keeper/
├── .keeper-active                       ← 单行文本，记当前活跃交付目录名
└── <交付id>/                            ← worktree 根 basename，非交付一律 `_main`
    ├── debug/
    │   ├── index.md                     入库（派生视图，hook 每轮重算）
    │   ├── archive/<批次>/<DBG-id>/     入库（归档整目录搬）
    │   └── DBG-NNN/
    │       ├── issue.md                 入库（唯一信源）
    │       ├── receipts.md              入库（fixer commit 进自己分支）
    │       ├── 01-xxx.png               落盘但 **不入库**
    │       └── worktree/                **不入库**，tk-worktree init 的固定落点
    ├── chore/{index.md, CHR-NNN/item.md, archive/}
    ├── decisions/{<stamp>-<keeper>.md, answers/<同名>.md}
    └── .keeper-instance.json            ← keeper 实例 name 登记，见下方「登记 keeper 实例 name」
```

`<交付id>` 由 `hooks/lib/keeper_paths.py` 解析：先 `--show-superproject-working-tree`
跳出 submodule、fixer worktree 经 `<git-dir>/wt-supply-source` 回溯到 delivery、
再取 `--show-toplevel` 的 basename。**不能**简单地"从 cwd 向上找 `.keeper`、遇 `.git`
停"——linked worktree 根自己就有一个 `.git` 文件，那样第一轮就返回 None，aisdlc 交付
跑在 `.sdlc/worktrees/D-NNN-<slug>/` 里时队列恒为空，冷启动还会 mkdir 出第二份。

**文本入库、截图与 worktree 不入库（v4，2026-08-01）**。三条规则划边界：
`.keeper/**/worktree/`、`.keeper/**/*.png`、`.keeper/**/*.jpg`。

这一版**推翻了 v3 的「整树不入库」**，而 v3 当初又是推翻前身 radnove-core 的 `.debug/`
整树入库而来的——所以这里等于绕回了一圈，得说清每一轮各自解决了什么、留下了什么：

| 版本 | 做法 | 解决了 | 留下的代价 |
|---|---|---|---|
| radnove-core `.debug/` | 整树入库 | issue 有 git 历史、跨 worktree 共享 | 工作区常年挂队列 diff；并行 worktree 在同一个 `index.md` 上互写冲突 |
| v3 `.keeper/` | 整树 gitignore | 工作区干净、index 抖动消失 | 误删无法恢复、多人不共享；**且被 gitignore 的文件搜不到** |
| v4 `.keeper/<交付id>/` | 文本入库、截图与 worktree 不入库 | 可搜、可恢复、按交付分目录后 index 冲突面收敛到单个交付内 | 队列是被跟踪文件，`git checkout` 会把它从工作区物理删掉、`git stash` 会把队列改动一起带走 |

**压垮 v3 的是可搜性**：Claude Code 把 `grep` 影子成自带 ugrep，参数写死
`--ignore-files`（`~/.claude/shell-snapshots/snapshot-zsh-*.sh:5160`）。被 ignore 的
文件搜起来**静默零命中、不报错**——"搜一下有没有类似 issue"给出的"没有"是假的，且
无从察觉。注意杀手是 `--ignore-files` 不是点前缀：`--hidden` 已经处理了点前缀，所以
当年"改个不带点的目录名"这个方向从一开始就不成立。`Read` 不走 grep，一直正常。

这个坑之所以拖了整整一个 v3 才被发现，是因为**它时灵时不灵**——2026-08-01 实测：
ugrep 只读递归下降途中遇到的 `.gitignore`，**不向上找**。所以从仓库根搜
（`grep -rn "xxx" .`，AI 的默认动作）是静默零命中；而把搜索根直接设进被忽略的目录
（`grep -rn "xxx" .keeper/`）反而正常命中，因为那条规则所在的 `.gitignore` 在搜索根
上一层、压根没被读到。同一份数据、同一个词，换个起点就换个结论。

v4 对上表最后一行代价的缓解：keeper 每个工作窗口结束 commit 一次队列，把未提交窗口
压到最短。这不能消除风险，只能缩小暴露面——如实记在这里。

**gitignore 分工（v4 改为 fail-loud，不再自动追加）**：keeper 冷启动检查这三行是否
齐备，**缺行就报错停下要求人工补**，不再像 v3 那样自动追加。原因是实测过：两个分支
各自在 EOF 追加内容不同的注释即产生合并冲突，而脚本追加裸规则、AI 实际执行时会自由
发挥注释文案。快照 hook 只注入提醒、不代写文件（与 v3 一致）。

## 登记 keeper 实例 name（2026-08-04 起）

keeper 的 `name` 强制带 4 位随机短哈希（形态 `opus-(debug|chore)-keeper-[0-9a-z]{4}`，
如 `opus-debug-keeper-4bb6`；正则由 `working-discipline` 插件的 `agent-dispatch.js`
校验，不在本插件内）。起因是旧版逐字固定名（`opus-debug-keeper`）在「同一段会话里
前一个实例结束、下一个又叫同名」时会撞车——`SendMessage` 的 name 寻址是 latest wins，
唤起前一个就会失联。

短哈希是随机的，主会话没法靠记忆或文档拼出实际 name，所以需要落盘登记：
`pre-tool-use-keeper-instance.sh` 挂在 `PreToolUse(Agent)`，命中 `tool_input.subagent_type`
为 `debug-keeper`/`chore-keeper` 的派发时，把 `tool_input.name` 写进
`.keeper/<交付id>/.keeper-instance.json`（`debug`/`chore` 两键各自独立，写一个不
覆盖另一个）。主会话唤醒 keeper 之前先读这个文件取真实 name，读不到才当作首次、
自己生成一个新的短哈希后缀派出。

这是纯写文件的副作用 hook：不判断该不该放行这次 `Agent` 调用（放行判据是
`working-discipline` 的职责），任何异常（找不到 git 仓库、文件写不进去）都静默降级，
不影响本次 Agent 派发——写失败的后果只是"主会话下次唤醒时可能读到旧登记或读空，
需要退回首次派出这条路径"，不是"这次派发失败了"。读写函数在
`hooks/lib/keeper_paths.py`（`read_keeper_instances` / `write_keeper_instance`），
判据与异常处理在 `hooks/lib/keeper_instance_register.py`。

## 自动归档

两个 keeper 在每次收尾窗口自查 done 条目，满足任一条件即跑
`skills/tk-debug/scripts/archive_done.py --auto --apply`（debug/chore 共用，`--queue` 区分）：

| 判据 | 阈值 |
|---|---|
| done 条目数 | ≥ 10 |
| 最早 done 条目的 `reported_at` 距今 | > 14 天 |

批次名 `auto-<YYYYMMDD>`。`next_id` 的扫描覆盖 `archive/**`，归档后编号**不回收**。
worktree 目录还在的 done 条目跳过并警告（先收工作区再归档）。

## 决策打包 HITL（需要人拍板的事怎么走）

subagent 拿不到 `AskUserQuestion` 工具（harness 硬限制），所以拍板走文件信箱 + 主会话代问：

| 步 | 谁 | 动作 |
|---|---|---|
| 1 | keeper | 写 `.keeper/<交付id>/decisions/<stamp>-<keeper>.md`（from/about/kind/blocking/options/recommend），`SendMessage(main)` ≤3 行打铃 |
| 2 | 主会话 | 攒批：待决 ≥3 条 / 出现 blocking / 用户问起 / 自然停顿点，四触发点任一命中才问 |
| 3 | 主会话 | 一次 `AskUserQuestion` 把多条并列问完 |
| 4 | 主会话 | 用户答复**原文**写 `answers/<同名>.md`，`SendMessage` 回 keeper |
| 5 | keeper | 把裁决抄进对应条目正文留痕，删 decisions 与 answers 两文件 |

一文件一写者，免锁。协议全文在 `skills/tk-decisions/SKILL.md`。

## 主会话保持精炼的手段（设计目标，已写进各文档）

1. 三岔口路由只转发不亲做：bug 原话逐字转给 debug-keeper、杂务转给 chore-keeper，主会话立刻回原任务。
2. keeper 的 `SendMessage` 一律 ≤3 行指针化（结论 + 文件路径），不往主会话倒正文。
3. 决策攒批：多条待拍板合成一次 `AskUserQuestion`，不逐条打断。
4. 注入有字节预算：chore 快照 ≤900 字符、路由注入未启用/已启用两档（~175 / ~792 字符），未启用项目的队列快照零输出。
5. `index.md` 是薄索引，快照只给 id + 状态一行，细节按需打开单条 issue 文件。

## 外部工单适配器（公司能力接线口）

debug issue 带 `external_ref: <系统>#<编号>` 时，收尾要回写外部工单。本插件不内置任何
公司系统，按三层发现适配器（契约全文见 `skills/tk-debug/references/external-tracker.md`）：

1. 项目配置 `.claude/task-keeper.local.md` 里声明 `external_tracker_skill: <skill 名>`（配置不能放 gitignored 的 `.keeper/`，所以落这里）；
2. 无配置时按已装 skill 列表探测；
3. 都没有则在回执里如实报「未回写」，**不阻塞 done**。

实例：云学堂内部用 radnove-core（≥5.0.0）的 `debug-ones-writeback` skill，配置写
`external_tracker_skill: debug-ones-writeback` 即接上。

## 与 radnove-core 的关系（二选一，不共存）

本插件是 radnove-core（云学堂内部插件）debug-triage / worktree-supply / debug-keeper 体系
在 2.x–4.x 十几个版本里打磨出的机制的通用化搬迁：register-first、一 issue 一文件 schema、
一 issue 一 worktree 物理隔离、submodule 跨对象库共享供给、合并前三件套对账、归档感知的
编号分配——这些硬教训全部原样保留，只去掉了公司专属部分并把产物仓改为按交付分目录的
`.keeper/<交付id>/`。radnove-core 自 5.0.0 起已删除全部 debug 资产、只留
`debug-ones-writeback` 适配器。

**不要与 radnove-core ≤4.5.1 同装**：守卫会双注册（同一命令弹两次确认框）、`debug-keeper`
agent 同名二义。装本插件请把 radnove-core 升到 5.0.0+。

## 存量迁移（一次性）

**v3 → v4**（`.keeper/debug/issues/` → `.keeper/<交付id>/debug/<id>/issue.md`）用脚本，
默认 dry-run：

```bash
python3 plugins/task-keeper/skills/tk-debug/scripts/migrate_layout.py --dry-run
# 核对映射清单无误后
python3 plugins/task-keeper/skills/tk-debug/scripts/migrate_layout.py --apply
```

v3 schema 从未记录「这条 issue 属于哪次交付」，所以存量条目一律进 `_main` 桶，
`--delivery` 可显式改指定桶；归档批次例外，它复用与 `archive_done.py` 同一条交付
正则独立判断每个批次。活的 git worktree 一律跳过不搬——`shutil.move` 一个活 worktree
会让主仓 `gitdir` 指向失效路径，那条 worktree 从此既不能用也不能 `remove`（要手工
`git worktree prune` 收场）。已实测 `git worktree repair` 能在「先移动后修复」的顺序下
自愈，但脚本刻意不自动调它，留给操作者确认后执行。

**v2 → v4**（radnove-core 时代入库的 `.debug/`）先按 v3 布局收拢到 `.keeper/debug/`，
再跑上面的脚本。漏做迁移时快照 hook 会检测到旧布局目录存在而 v4 队列缺失，注入一句
迁移提示，不会静默丢队列。

`.gitignore` 三条规则**一次性提交到主分支**，之后各交付分支只读不写：

```gitignore
.keeper/**/worktree/
.keeper/**/*.png
.keeper/**/*.jpg
```

若历史上有过整树 `.keeper/` 忽略行，**先删掉它**——两者并存时它会把入库的 issue 一起
吞掉，而 hook 每轮都会为此告警。

## 测试

```bash
bash plugins/task-keeper/hooks/tests/run-tests.sh
```

真实进程回归（JSON 喂 stdin、断言 stdout，不 mock），覆盖：队列快照分桶/排序/坏文件显式告警、
index 幂等、三道守卫的拦与不拦两侧、wt_supply 供给/幂等/回流前置校验、归档与编号不回收、
chore 快照字节预算、决策信箱计数、双队列互不串号、自动归档判据、路由注入分档、
keeper 实例登记的写入与放弃两侧（白名单命中/不命中、name 缺失、目录不存在时自动建出、
另一个键保留）。
