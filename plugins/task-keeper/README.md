# task-keeper

常驻 keeper 子代理托管 debug 队列与杂务队列：主会话只做「分类分派 + 需要人拍板时集中问一次」，
登记、triage、修复派发、对账、归档全流程都在 keeper 的独立上下文里跑，不占用主会话窗口。
通用、机构无关——公司专属能力（如 ONES 工单回写）通过适配器接线，不进本插件。

2.7.0 起多一个**非 keeper** 的 agent `sdlc-writer`：跑 ai-sdlc 流程时，Gate 已放行后
那一大段由 AI 自主落盘的文档（scope / behaviors / contracts / entities / ui …）交它写，
主会话只留 Gate 交互、Human 拍板与审查汇报。它与两个 keeper 的区别见下方专节。

## 组成

| 类型 | 名称 | 作用 |
|---|---|---|
| skill | `tk-debug` | debug 队列全流程指引（登记 → triage → 一 issue 一 worktree 派发 → 合并前对账 → 归档） |
| skill | `tk-chore` | 杂务队列：主会话判是杂务就转 chore-keeper，自己立刻回原任务 |
| skill | `tk-sdlc` | sdlc 流程产物派发：切割线、按 feature 的分片规则、prompt 模板、回执收尾 |
| skill | `tk-context` | **动手前**收齐某功能单元的规格/约束：五方并行查（需求/原型/spec/ontology/代码）相互印证 → 上下文包 + 空销账表 → 事后差异核对。只收集与汇报，不参与实现 |
| skill | `tk-decisions` | 决策打包 HITL 协议正典（keeper 与主会话之间怎么攒批问人） |
| skill | `tk-worktree` | 为 `git worktree` 建的工作区供给 submodule 内容（含嵌套递归），6 个子命令；`init` 支持 `--ids` 批量 + `--jobs` 并行建多个 issue 的 worktree |
| skill | `tk-board` | 进度看板：每条一行（编号 + 20 字说明 + 四态）+ 计数占比 + 告警段，纯只读、不唤醒 keeper。同目录另有 `pending_dispatch.py`——只算「漏派」一件事（已 triage 但既不在飞、也不在等拍板），三种输出模式 |
| agent | `debug-keeper` | 独占 `.keeper/debug/` 写权限，承接 bug 报告全流程 |
| agent | `chore-keeper` | 独占 `.keeper/chore/` 写权限，承接杂务登记与攒批执行 |
| agent | `context-keeper` | 独占 `.keeper/<交付id>/context/` 写权限，五方并行收集 → 归一印证 → 排空销账表 → 事后核对。**只汇报不实现**：不写业务代码、不派实现者、不写 `sdlc/`、不拦截 ai-sdlc |
| agent | `sdlc-writer` | **非 keeper**，一次性：写 Gate 后的 sdlc 文档正文，不常驻、不登记、无队列 |
| hook × 9 | 见下表 | 注入路由/队列快照 + 三道窄判据守卫 + 1 个 keeper 实例登记 + 1 个 debug-keeper 专属的漏派清单注入 |

## hooks（挂载事件与实际行为）

| 脚本 | 事件 | 行为（按动作描述，不是按愿望描述） |
|---|---|---|
| `session-start-keeper-routing.sh` | SessionStart | 纯注入**静态参考**（决策打包主会话侧职责、v4 布局、指针）。未启用 195 字符（一句话介绍 + 启用方式），已启用 495 字符，不拦截任何操作 |
| `user-prompt-submit-keeper-routing.sh` | UserPromptSubmit | 纯注入**四岔口分诊**（自己做 / 转 debug-keeper / 转 chore-keeper / 转 context-keeper）+ 转发三原则 + 现算的一句"唤醒前怎么办"（三选一：唤醒某个真实 name / 登记已失效当首次派发 / 没有登记当首次派发，见下方「登记 keeper 实例 name」的会话隔离说明）。实测长度：没有登记 479 字符、已失效 511 字符；session 匹配那支随实际 name 长度浮动。工作区在跑 ai-sdlc 流程时**追加第 5 支路**「转 sdlc-writer」（判据 `sdlc_present`：worktree 根 + 往上 4 层里任一层有 `sdlc/specs` 或 `sdlc/deliveries`；不命中时输出与没有这条支路时逐字相同），该支路 +108 字符，实测无登记 587 字符、已失效 619 字符。硬上限 800。未启用项目 stdout 全空 |
| `user-prompt-submit-debug-queue.sh` | UserPromptSubmit | 注入 debug 队列实时快照（open 逐条 + 在飞派生 + done 计数）、重算薄索引 `index.md`（git rebase/bisect/merge 中间态跳过）；`.gitignore` 缺 v6 那三条精确排除、或还留着 v5 的整树忽略行时加一句提醒；存量 v3/v2 布局未迁移时加一句迁移提示；命中 bug 特征词时给出下一个可用 DBG-id（fixer worktree 内不给） |
| `user-prompt-submit-chore-queue.sh` | UserPromptSubmit | 注入 chore 队列快照（输出预算 ≤900 字符）；`.keeper/` 顶层存在时缺失的 `chore/`（连同 `debug/`）由 `find_queue` 每轮自动补建，不需要手工 mkdir；代注待拍板决策计数（自动补建后 `chore/` 恒存在，debug 快照的兜底注入分支实际只在 fixer worktree 内或补建失败时才会走到，两边判据仍是同一个目录的存在性） |
| `user-prompt-submit-context-queue.sh` | UserPromptSubmit | 注入 context 队列快照（open 逐条：id + `stage` + 降级为三方印证的标记 + 不一致条数；`ledger.md` 一行没填时告警并给出未填行数；done 计数），重算 `context/index.md`。**刻意不做三件事**：不报待拍板计数、不报 gitignore 告警（这两项由 debug/chore 二元分工，第三方加入只会重复注入同样文案）、不做特征词提醒（「这次算不算一个功能单元」是语义判断，做成关键词会大面积误报） |
| `pre-tool-use-debug-worktree-push.sh` | PreToolUse(Bash) | `git push` 的目标落在 `.keeper/<交付id>/debug/<DBG-id>/worktree/` 内时 deny（fixer 产物只回流不推远端） |
| `pre-tool-use-debug-worktree-destroy.sh` | PreToolUse(Bash) | 强制删除形态（`rm -rf` / `worktree remove --force` / `clean -fdx`）命中 `.keeper/<交付id>/debug/<DBG-id>/worktree/` 路径时 ask 弹确认框 |
| `pre-tool-use-debug-evidence.sh` | PreToolUse(Write\|Edit) | 只对 `.keeper/<交付id>/debug/*.md` 介入：新内容含 `image-cache` 会话级临时路径时 deny（跨会话必 404），带次数熔断，`origin_path` 留档豁免 |
| `pre-tool-use-sdlc-writer-guard.sh` | PreToolUse(Write\|Edit) | 主会话（payload 无 `agent_id`）写 `sdlc/(specs\|deliveries)/` 下非 `_index.md` 文件时 deny，逼派 sdlc-writer（文案给派发照抄形态 + 四条出路）；`_index.md` 放行（承载 gate 状态 frontmatter，是主会话/Human 门禁动作）；子代理带 `agent_id` 一律放行（sdlc-writer 写自己的产物不拦）；带次数熔断。第 5 支路软提醒压不过「顺手写更快」，故上机械闸 |
| `pre-tool-use-keeper-instance.sh` | PreToolUse(Agent) | 命中 keeper 类 `subagent_type`（`debug-keeper`/`chore-keeper`/`context-keeper`）的派发时，把 `tool_input.name` 连同这次派发所在的 `session_id` 写进 `.keeper/<交付id>/.keeper-instance.json` 对应键，另一个键原样保留；**纯写文件，不拦截任何操作**，不输出 permissionDecision，写不进去就静默放弃 |
| `subagent-start-debug-keeper.sh` | SubagentStart（matcher `task-keeper:debug-keeper`） | 跑 `skills/tk-board/scripts/pending_dispatch.py --oneline`，输出非空时注入一段「漏派体检」（那一行 + 处置指引）。**无漏派时零输出**、未启用项目零输出、坏 payload 零输出，恒 exit 0。matcher 精确到单个 agent_type，**不是 `*`**——写 `*` 会把 debug 队列的清单灌给本机每一个子代理 |

三道守卫的判据都是路径子串 + 命令形态的机械判定，未启用队列的项目全部零输出零成本。
`pre-tool-use-keeper-instance.sh` 不是守卫——它不拦下任何动作，只有"顺手写一个登记
文件"这个副作用，供主会话下次唤醒 keeper 前读取真实 `name`（见下方「登记 keeper
实例 name」）。

## 产物布局：`.keeper/<交付id>/`，正文与附件入库（v6）

```
<项目根>/.keeper/
├── .keeper-active                       ← 单行文本，记当前活跃交付目录名
└── <交付id>/                            ← worktree 根 basename，非交付一律 `_main`
    ├── debug/
    │   ├── index.md                     派生视图，hook 每轮重算，不要手改
    │   ├── archive/<批次>/<DBG-id>/     归档整目录搬
    │   └── DBG-NNN/
    │       ├── issue.md                 入库（唯一信源）
    │       ├── receipts.md              入库（fixer commit 进自己分支）
    │       ├── 01-xxx.png               入库（v6 起；含敏感信息则**不落盘**，见下）
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

**正文与附件入库，只精确排除三类本机产物（v6，2026-08-10 用户拍板）**。keeper 冷启动
自动写入：

```gitignore
# task-keeper 队列：正文与附件入库，只排除三类本机产物
.keeper/**/worktree/
.keeper/**/.keeper-instance.json
.keeper/.keeper-active
```

> **对 v5「整树不入库」拍板的覆盖标注**：本文件与两个 keeper 定义里 2026-08-06 那份
> 「`.keeper/` 整树 gitignore、不要公开」的决定，**已于 2026-08-10 被用户拍板整体
> 覆盖**，原话是「`.keeper` 之前把它从整个项目中忽略了，现在看来还是需要提交到远端
> 纳入版本控制，除了少数内容比如里面的 worktree 之外，其他都可以（包括当时的问题
> 附件/图片/文件等）纳入版本控制」。
>
> 被覆盖的是入库策略。**连带反转的下游判据有五条**，每条都在对应文件里改过，读到旧
> 措辞不要照旧行动：截图脱敏（从「额外谨慎」升级为红线）、`check_staged_gitlink.py`
> （从「存量仓专用」恢复主线）、receipts 对账（从 `cat` 回到 `git show HEAD:`）、
> 清理 worktree 前手工 `cp` receipts（已作废）、`decisions/` 留痕（恢复版本库兜底）。
>
> ugrep `--ignore-files` 那条实测结论**没有被覆盖**，仍然成立，只是适用范围从「整个
> `.keeper/` 搜不到」收窄到「只有那三类搜不到」。
>
> 排除清单里 `worktree/` 是用户点名的；另两条是技术判断——`.keeper-instance.json` 含
> `session_id` 与随机 agent name，跨机器无意义且多人并行必冲突，`.keeper-active` 是
> 本机活跃交付指针。`decisions/` 经 2026-08-10 用户拍板**入库**。

五轮各自解决了什么、留下了什么：

| 版本 | 做法 | 解决了 | 留下的代价 |
|---|---|---|---|
| radnove-core `.debug/` | 整树入库 | issue 有 git 历史、跨 worktree 共享 | 工作区常年挂队列 diff；并行 worktree 在同一个 `index.md` 上互写冲突 |
| v3 `.keeper/` | 整树 gitignore | 工作区干净、index 抖动消失 | 误删无法恢复、多人不共享；**且被 gitignore 的文件搜不到**（当时未找到规避手段） |
| v4 `.keeper/<交付id>/` | 文本入库、四条规则排除产物 | 可搜、可恢复、index 冲突面收敛到单个交付内 | 队列被跟踪，`git checkout` 会把它从工作区物理删掉、`git stash` 会把队列改动一起带走；**且 bug 细节与内部系统坐标随推送公开** |
| v5 `.keeper/` | 整树 gitignore + 搜索根硬约束 | 不公开、工作区干净 | 误删无法恢复、多人不共享（与 v3 同）；搜队列必须记得换搜索根 |
| **v6（现行）** | 正文与附件入库 + 三条精确排除 | 可搜、可恢复、跨 worktree 共享、receipts 随 merge 自动带回 | **bug 细节、内部坐标、截图随推送公开**——所以截图脱敏成了红线；幽灵 gitlink 这条路重开，`check_staged_gitlink.py` 必跑；`index.md` 每轮重算会造工作区 diff |

**v3 与 v5 做法相同、结论不同，差别只在一条规避手段**。压垮 v3 的是可搜性：Claude Code
把 `grep` 影子成自带 ugrep，参数写死 `--ignore-files`
（`~/.claude/shell-snapshots/snapshot-zsh-*.sh:5160`）。被 ignore 的文件搜起来**静默
零命中、不报错**——"搜一下有没有类似 issue"给出的"没有"是假的，且无从察觉。注意杀手是
`--ignore-files` 不是点前缀：`--hidden` 已经处理了点前缀，所以当年"改个不带点的目录名"
这个方向从一开始就不成立。`Read` 不走 grep，一直正常。

2026-08-01 实测找到了规避手段，这是 v5 敢绕回来的全部理由：ugrep 只读递归下降途中遇到
的 `.gitignore`，**不向上找**。所以：

> ### 硬约束：搜队列一律把搜索根设进 `.keeper/`
>
> ```bash
> grep -rn "关键词" .keeper/          # ✅ 正常命中
> grep -rn "关键词" .                 # ❌ 静默零命中，且不报错
> ```
>
> 从仓库根搜是 AI 的默认动作，所以这条必须写死在两个 keeper 的定义里、不能只留在
> README。拿不准时用 `Read` / `ls` 正面列举，**不要用否定式检索得出「队列里没有
> 这条」**——那个「没有」可能是假的。

**gitignore 分工（自动追加，靠文案写死避免冲突）**：keeper 冷启动检查那三条在不在，
缺就整块追加，**注释与 pattern 逐字写死**（`GITIGNORE_BLOCK`，
`hooks/lib/queue_snapshot.py`）。v4 当初禁止自动追加的唯一理由是实测过「两个分支各自
EOF 追加**内容不同**的注释即冲突」——内容逐字相同则 git 视为同一处改动、不冲突。
**三处必须逐字同步**（该常量 + 两个 agent 定义里的 `printf`），回归用例 H28 [121] 锁
这一条，且反向验证过它真能抓到失同步。

快照 hook 只注入提醒、不代写文件——**代写只发生在 keeper 冷启动这一处**，两处都代写
会在 hook 未生效的环境里制造「以为写了其实没写」的分叉。它报两类：v5 整树忽略行残留
（`GITIGNORE_LEGACY_ALL` 命中，它覆盖三条精确规则且静默生效）、三条里缺了哪几条
（`GITIGNORE_RULES` 逐条比对）。

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

### 会话隔离（2026-08-05 补）

登记文件落在磁盘上、**跨会话存活**，但派出去的 keeper 只活在派出它的那次会话里。
上一版只登记 name，没有字段能区分"这条登记是不是本会话写的"——于是新会话第一次
转 bug 时，主会话读到的是上一个会话的死 name，`SendMessage` 报
`No agent named ... is reachable`，按"唤醒不到就重派"的错误反应会直接又派第二个
实例，两个实例抢同一个 `.keeper/<交付id>/debug/` 的独占写权限——这正是登记机制
本来要消除的失败模式，在跨会话场景下原样复活了一次。

修法是登记里多写一个 `session_id` 键（取自 hook payload 的 `session_id` 字段，这是
所有 hook 输入 schema 的公共字段），形状变成
`{"debug": {"name": "...", "ts": "...", "session_id": "..."}}`。真正做会话比对的
落点**不是主会话自己读文件**——主会话拿不到自己的 `session_id`，没有任何机械手段
验证"这条登记是不是本会话写的"；比对现算在 `user-prompt-submit-keeper-routing.sh`
每轮注入里（它能拿到当前 `session_id`），直接把结论注成一句话：

- 登记存在且 `session_id` 与当前一致 → 直接告诉主会话"唤醒 `<真实 name>`"。
- 登记存在但不一致，**或是加会话隔离之前落的旧格式（压根没有 `session_id` 键）**
  → 告诉主会话"这份登记已失效，当首次派发处理"——旧格式一律当陈旧，不做"没写就
  算通过"的宽松判断。
- 没有任何登记 → 保持原有措辞，首次派发。

`keeper_paths.write_keeper_instance` 的 `session_id` 参数取不到时**不写这个键**
（不是写 `null`），登记本身不受影响，只是这条记录之后没法被会话比对认领。
`keeper_paths.read_keeper_instance_name` 新增 `current_session_id` 参数：传了就要求
一致才返回 name，不传则维持旧行为（不比较会话）。

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

## 进度看板（2.8.0 新增 · `tk-board`）

`skills/tk-board/scripts/board.py`，**纯只读**：不落盘、不 mkdir、不 `git` 写，跑多少次
都不改队列状态（回归用例 [103] 逐文件比对跑前跑后的清单与大小来守这一点）。用户问
「进度怎么样 / 还剩多少 / 哪些等我拍板」时跑它，把输出原样贴回去。

输出三段：四态计数与占比 → 条目明细（编号 / 20 字说明 / 状态 / 优先级或类别 / 类型或
外部写 / 外部工单）→ 告警。

**四态里只有一态来自 `status` 字段。** frontmatter 的 `status` 只有 `open` / `done`
两个值（v2 的 `in_progress` 在 v3 被砍，理由见 `hooks/lib/queue_snapshot.py` 模块头：
AI 手写的业务字段当机械判据不可靠），另两态从文件系统事实反推：

| 状态 | 判据 |
|---|---|
| 已解决 | `status: done` |
| 待拍板 | `decisions/` 里有未答复的 `.md`，其 `about:` 指向这条 |
| 进行中 | 条目目录下有 `worktree/` |
| 未解决 | 以上都不是的 `open` |

判定自上而下短路。`done` 排最前，所以「修完了但 `worktree/` 忘删」不会冒充在飞——它进
告警段（那正是归档跳过该条的原因）。「待拍板」优先于「进行中」：一条 issue 可以既派了
fixer 又卡在等人答复，此时该突出需要人动作的那一面。

`about:` 的解析是本脚本新写的——`decision_inbox.pending_decisions()` 只回答「总共几条
待拍板」，全文不解析 `about:`，给不出「哪条 issue 在等」。解析不出归属的、以及归属指向
已 `done` 条目的，都单列进告警段，不静默丢弃（v2 教训：读不懂的静默跳过，16 条 issue
从视图里人间蒸发）。

另做两处真实数据脏点归一（2026-08-05 在一份 151 条的真实队列里实测到）：外部工单号有
`external_ref` 与 `ones` 两种字段名，两个都读；`priority` 出现过小写 `p1`，upper() 后
再比。`summary` 前导的 `【已关闭 —— …】` 状态块在显示时剥掉——20 字的说明列被状态叙述
占满就一条也看不出讲什么，而状态本身已经在状态列里。

## 动手前的上下文收集（2.14.0 新增 · `tk-context` + `context-keeper`）

与下一节是同一件事的两端：**下一节是诊断侧**（已经坏了，回头查规格上原本怎么写），
**本节是预防侧**（还没动手，先把规格收齐）。

### 它要防的那件事

某次交付的事后归因里最大的一类是「**规格写了，但没照着做**」——55 条、占 27.9%。
根因不是能力问题：实现只看了原型，那几份文字规格 md 没人读，整片规格就此失效。

上游也没兜住：ai-sdlc 的三道机械硬闸基线全是原型 html，覆盖文字规格的 `spec-sync-audit`
轴是 advisory 不阻断、且明文排除 UI 元素——**UI 文字规格在整条链路里唯一被校验的是
「原型存不存在」，不是「原型内容忠不忠于它」**。

### 对策：不保证遵守，只让不遵守可见

保证遵守做不到——没有任何机械判据能判「这段代码是不是符合这句中文规格」。所以本通道
改追一个做得到的目标：动手前把约束一条条排成表，实现完逐行核。**只要那一行还是空的，
不遵守就是可见的。**

### 五方并行，相互印证

需求 / 原型 / sdlc spec / ontology / 代码，**同批并发派五个只读 `Explore`**，回来后
归一并出印证矩阵。

**刻意不走「ontology 为主入口」**：那等于让一个未经确认的中间层决定该看什么，它漏收的
元素会静默传播成「查过了、没有」，且全程无信号。ontology 是**第四个平等信源**，不是索引。
涉及其他领域知识、读不到代码时降级为三方（需求/原型/ontology），降级必须落在产物的
`sources` 字段上——参与方数量要可见，不能埋在正文里。

### 产物三件套与谁填哪一份

```
.keeper/<交付id>/context/CTX-001/
├── context.md      ← 上下文包 + 印证矩阵      （keeper 写）
├── ledger.md       ← 空销账表                  （**外部实现者填**）
└── reconcile.md    ← 事后差异核对              （keeper 写）
```

**销账表必须由写代码的那个人填**，keeper 一行状态列都不预填——预填等于替实现者做了
声明，而它并没有看过对方的代码；事后核对时它还要拿这份表当基线，等于自己印证自己。

`status` 翻 `done` 的唯一判据：**跑过一次事后核对且 `reconcile.md` 已落盘**。不接受
「实现者说做完了」（那是声明不是核对）、「挂太久了」（挂久不改变它没被核对这个事实）。

### 职责边界：只收集与汇报

四条硬约束，写进了 agent 定义与 skill 正文：

1. **不写业务代码**——实现是 ai-sdlc 的 implement 或 debug 的 fixer 的职责。
2. **不拦截、不阻断任何流程。** 判据一句话：**产物存在与否，不改变 ai-sdlc 任何一步的
   行为。** 这是唯一不会让两套流程互相甩锅的形态。
3. **不写 `sdlc/` 下任何文件，`sdlc/ontology/` 尤其不写**——那边有自己的收口闸与 sync
   脚本。发现 ontology 漏收，写成建议留在包里。
4. **不填销账表状态列、不催填。**

### 两个入口，都不自动触发

| 入口 | 谁叫 | 时机 |
|---|---|---|
| A | 主会话 | 用户说要做 X 功能 / 改 Y，尚未动手 |
| B | debug-keeper | triage 完成、派 fixer 之前（`agents/debug-keeper.md` §6.0） |

**不做成 hook 是有意的**：「这次动作算不算一个功能单元」是语义判断，做成关键词闸只会
误杀与漏放同时发生（见本仓 `.claude/rules/project/hook-restraint.md` 的强度阶梯）。

入口 B 有一条豁免，由 debug-keeper 自己判：`difficulty: easy` **且**
`spec_status: violation` **且**已有明确规格锚——规格已在手，不必再收。三个条件缺一
不豁免；`spec_status: unchecked` 一律不豁免，那说明规格根本没查过。

### 何为「一个功能单元」

> **共享同一份规格来源、且必须一起验证的那组断言 = 一个功能单元。**

31 条错误提示文案共享同一份需求表格、少一条就是没做完 → 一个单元、31 条断言、销账表
31 行，**不是 31 个单元、也不是压成一行「按需求文档的表格实现」**。

拆错的代价不对称：拆太细的成本是重复劳动 + 漏掉跨条目冲突；**拆太粗的成本是整条机制
空转**——断言上百条、表没人填得完、最后空着交回来，比不做还糟，因为留下了「做过了」
的痕迹。拿不准时偏细。

判据细则见 `skills/tk-context/references/collect.md`（五路分片与停止条件、归一锚点
优先序、矩阵四态、同构扩散面）与 `artifacts.md`（三件套模板与填写纪律）。

## 规格溯源与收官归因（2.13.0 新增）

**解决的问题**：bug 台账天然只记「什么坏了、怎么修的」，不记「规格上原本怎么写」。于是
「规格写了、实现没照着做」这一类在事后归因里完全不可见——它会被摊进「基本功不扎实」和
「需求没写清」两个筐，而这两个筐指向的改进动作（加培训 / 催产品写细）对它一个都不管用。
真实量级：某次交付里这一类占 27.9%、共 55 条、为最大的一类，而同一批数据上不带规格栏的
那轮归因把它统计成了零。

**三处改动**：

1. `issue.md` frontmatter 新增第 10 个键 `spec_status`，四态 `violation` / `gap` /
   `conformant` / `unchecked`（判据见 `skills/tk-debug/references/queue.md` §3.1），
   `index.md` 的 open 表格随之新增「规格」列。
2. triage 多一个必做落点——定位完「代码在哪出的错」，还要定位「规格原本怎么写的」，依据
   逐条写进正文新增的「规格依据」章节。判 `gap`（规格空白）前必须把八类来源全查过并**逐条
   列出结果**，因为「没有」是唯一无法自证的检索结果：它可能是事实，也可能是正则写错 / 被
   gitignore 静默吞掉 / NFC-NFD 路径形态对不上。判为 `gap` 的条目**不派 fixer**，退回主
   会话转 chore 队列问产品——规格空白派 fixer，它会凭直觉补一个同样没人确认过的行为，把
   空白伪装成已定案。
3. `spec_status: violation` 的 fixer prompt 带规格原文摘录与出处，**修复判据从「现象不再
   复现」换成「与规格逐条一致」**，回执要给规格逐条核对表。

**为什么修复判据必须换锚**：实测过一次——需求表格逐条给全了 31 条导入错误提示文案，用户
只报了其中 1 条。按「现象消失」口径修完即收工，剩下 30 条原样落空。

**一个已知的上游盲区，§3.1 要求把 view spec 与原型分开查正是为它**：ai-sdlc 的三道机械
硬闸（写 `.vue` 前的原型消费证据登记、G4 的实现↔原型渲染比对、写原型时的保真校验）基线
全是原型 html；覆盖文字规格的 `spec-sync-audit` 轴是 advisory 不阻断，且明文声明 UI 元素
不在其值域内。所以「文字规格写了、只是没画进原型」这类偏差，在「原型存在」这个前提下不会
被任何一层拦住——**原型命中不等于规格命中**。

**收官归因**：交付收官时 debug-keeper 产出一张「规格失守清单」（`agents/debug-keeper.md`
§9.1），四项缺一不可——`violation` 占比 / 按规格文件聚合（同一份 md 上挂 5 条以上，说明它
整片没被读，而不是有人漏了一条）/ 原型缺口条数 / `gap` 攒批待问产品清单。

## sdlc-writer：不是 keeper 的第三个 agent（2.7.0 新增）

跑 ai-sdlc 流程时，一次 Define 展开要落十几份文档（`scope.md`、`specs/features/<name>/`
下的 `_index.md` / `behaviors/*.gherkin` / `contracts.md` / `entities.md` / `ui/views/`
/ `nfr.md` …）。主会话若自己逐份写，每份全文都进它的窗口，几份之后就 auto-compact，
而它真正该保留的是与用户的需求对话和 Gate 判断。`sdlc-writer` 承接的就是这一段。

**为什么不做成第三类 keeper。** keeper 是「队列托管 + 跨会话唤醒 + 独占写域」模型，
代价是三处硬编码白名单（`keeper_routing.KIND_LABELS`、
`keeper_instance_register.KEEPER_SUBAGENT_KIND`、`queue_snapshot._sibling_queue_names`）
加一套快照 hook 与队列目录。而 sdlc 文档编写是**一次交付内一口气写完的流程内 fan-out**，
没有「跨会话回来接着处理待办」的需求——用不上队列，也就不该付队列的代价。三处白名单
因此**都不动**，它们只管常驻实例。

| | 两个 keeper | sdlc-writer |
|---|---|---|
| 生命周期 | 常驻，`.keeper-instance.json` 登记 + `SendMessage` 唤醒 | 一次性，做完即销 |
| 写域 | 独占 `.keeper/<交付id>/{debug,chore}/` | 派发时点名的那些 sdlc 文档 |
| 档位 | 钉死 `opus`（`agent-dispatch.js` 白名单强制） | 默认 `sonnet`，跨 feature 契约一致性等场景升 `opus` |
| `name` | `opus-(debug\|chore)-keeper-[0-9a-z]{4}` | `sonnet-sdlc-writer-<分片名>`，只要求含身份词 |
| 待拍板 | 写 `decisions/` 信箱 | 写进回执，主会话攒批问 |

**切割线**（`skills/tk-sdlc/SKILL.md` 有完整表）：需求收集、G1–G5 门禁确认、翻
`gates.g*.status`、Gate 审查汇报（Inline Digest）、调 `spec-reviewer` 与各类 audit、
`git commit` —— 全部留主会话；**只有往 `sdlc/` 下落盘文档正文这一件事**派出去。
Define 阶段的切割点是 G1，取自 ai-sdlc 的 `define/SKILL.md` 原文「G1 通过后 AI 自主
展开、不需再确认」，不是本插件自定的。

**这条切割线有机械闸兜底（2.16.0 新增）**：第 5 支路（UserPromptSubmit 每轮注入的
「转 sdlc-writer」）是软提醒，压不过主会话「顺手写更快」的默认行为——实测主会话在
「写」的瞬间会把自己归到三岔口第 1 条「自己做：……需要你上下文才能做的事」。`pre-tool-use-sdlc-writer-guard.sh` 在主会话用 Write/Edit 写 `sdlc/(specs|deliveries)/`
下非 `_index.md` 文件时 deny，文案给派 sdlc-writer 的照抄形态；`_index.md`（gate 状态）
与子代理发起（`agent_id` 真值）放行。判据、四条出路与为什么用 deny 不用 ask 见
`hooks/lib/sdlc_writer_guard.py` 模块文档。

**分片只能按 feature 切，单 feature 内串行。** Define 的产出物有依赖链
`behaviors → contracts → entities → prototype`，`validate-prototype.js` 会强制后两者
的字段与前面一致。按文档类型分片（一个写所有 behaviors、另一个写所有 contracts）必然
字段对不上。所以第 1 波先串行写交付级的 `scope.md`，第 2 波再按 feature 并行（≤6）。

**最大的风险点是散文级 MUST 静默失效。** ai-sdlc 的校验分两类：挂在
`PreToolUse`/`PostToolUse(Write|Edit)` 的机械 hook（`write-guard.js`、
`validate-gherkin.js`、`validate-prototype.js` …）对 subagent 同样生效，因为它们绑的是
工具调用不是会话；但另有一批只写在 SKILL.md 正文里、靠执行者读了照做的 MUST，跳过了
不报错、没有 finding。所以 `agents/sdlc-writer.md` 的第一条硬性前置是**整读目标阶段
SKILL.md 全文**（不许 Grep 后定点读——规范有跨段约束），并在回执里逐条交代执行了哪些、
跳过了哪些及原因。

## 主会话保持精炼的手段（设计目标，已写进各文档）

1. 三岔口路由只转发不亲做：bug 原话逐字转给 debug-keeper、杂务转给 chore-keeper，主会话立刻回原任务。
2. keeper 的 `SendMessage` 一律 ≤3 行指针化（结论 + 文件路径），不往主会话倒正文。
3. 决策攒批：多条待拍板合成一次 `AskUserQuestion`，不逐条打断。
4. 注入有字节预算：chore 快照 ≤900 字符、路由注入未启用/已启用两档（~195 / ~495 字符），未启用项目的队列快照零输出。
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

`.gitignore` 那两行理想情况**一次性提交到主分支**，之后各交付分支的冷启动检查直接命中、
什么都不写；即使某个分支自己追加了，因为文案逐字写死、合并时不冲突。

**v4 → v5 的存量仓要单独处置**：v4 期间队列文本是入库的，`.gitignore` 只管未跟踪文件，
所以加了整树规则对已跟踪的队列**完全不生效，且不会有任何报错**。先查：

```bash
git ls-files '.keeper/' | head -n 3       # 有输出=已跟踪
git log --oneline -- '.keeper/' | wc -l   # 已推送的历史有多少
```

有输出时**由 Human 拍板**，keeper 与 AI 不得自行处置。三条出路的代价差别很大：
`git rm -r --cached .keeper` 停止继续入库但历史仍在远端；`git filter-repo` 连历史一起
清但要 force push、会打断所有协作者；什么都不做则该仓维持 v4 行为。v4 期间那四条精确
规则（`.keeper/**/worktree/` 等）留着无害，被整树规则完全覆盖。

## 测试

```bash
bash plugins/task-keeper/hooks/tests/run-tests.sh
```

真实进程回归（JSON 喂 stdin、断言 stdout，不 mock），覆盖：队列快照分桶/排序/坏文件显式告警、
index 幂等、三道守卫的拦与不拦两侧、wt_supply 供给/幂等/回流前置校验、归档与编号不回收、
chore 快照字节预算、决策信箱计数、双队列互不串号、自动归档判据、路由注入分档、
keeper 实例登记的写入与放弃两侧（白名单命中/不命中、name 缺失、目录不存在时自动建出、
另一个键保留）、会话隔离两侧（`session_id` 写入/同会话读得到/跨会话读不到/旧格式
无 `session_id` 键当陈旧处理/payload 缺 `session_id` 时仍正常登记 name、三岔口注入
按会话状态三选一各自的措辞）、sdlc 第 4 支路的条件注入两侧（无 sdlc 目录时逐字不变、
`specs` 与 `deliveries` 两个子目录各自命中、交付跑在 `.sdlc/worktrees/D-NNN-*/` 里时
向上三层仍命中、空的同名 `sdlc/` 与超出查找深度都不命中、命中后总长度仍 ≤800）。
236 条用例，覆盖见 `hooks/tests/run-tests.sh` 头部按 H 编号的分节说明。
