# task-keeper

keeper 子代理托管 debug 队列与杂务队列：主会话只做「分诊转发 + 需要人拍板时集中问一次」，
登记、triage、修复派发、对账、归档全流程都在 keeper 的独立上下文里跑，不占用主会话窗口。
通用、机构无关——公司专属能力（如 ONES 工单回写）通过适配器接线，不进本插件。

> **4.0.0 起多实例架构：一条 bug 一个 debug-keeper 实例，同一档可并存多个、互不干扰**。
> chore-keeper 默认仍是**单实例攒批**（价值在跨条目视野，见「登记 keeper 实例 name」
> 一节），只有明确要求并行清账时才多开。配套新增 CLI `scripts/keeper_cli.py`：原子
> 认领编号（`claim`，替代"自己扫目录算 next id"，两个实例同时扫会撞号且不报错）、
> 合并锁互斥（`lock`，debug 侧合并回主仓时用，exit 3 = 锁被占用是正常竞争不是故障）、
> 登记 issue→实例（`bind`）、查同档其它实例（`peers`）。agent name 形态同步改变：
> debug 侧 `opus-debugger-<4位>`、chore 侧 `sonnet-chore-<4位>`——**chore-keeper 的
> 固定档同时从 opus 降到 sonnet**，判据是等值，派 opus 同样会被拦，理由是登记/分类/
> 攒批/归档是机械杂务，不需要 debug-keeper 那种跨层追根因的判断力。
> `.keeper-instance.json` 的登记表相应改为列表（同一档可以有多条记录），寻址键从
> "这一档唯一的 name"变成"认领了某条 issue 的那个实例"，细节见「登记 keeper 实例
> name」一节。

> **context 队列已删（4.0.0）**：`context-keeper` agent、`tk-context` skill、
> CTX-NNN 队列、`user-prompt-submit-context-queue.sh` hook 全部拆除。依据是实证
> 而非设计偏好——全机 8 个真实项目的 `.keeper/*/context/` 共 0 条 CTX 条目，它承诺
> 的三份落盘产物（`context.md` 上下文包 / `ledger.md` 空销账表 / `reconcile.md`
> 事后核对）从未被创建过一次（见 `hooks/tests/run-tests.sh` 「2026-08-18 摘除
> H27」）。根因是它依赖的前提——"收集者与实现者是两个能持续对接的常驻角色"——在
> v7 下不再成立：一条 issue 一个 keeper 实例之后，收集与实现落在同一个实例的同一段
> 上下文里，中间不再有需要靠文件传递状态的缝，销账表要填给谁看？答案是"填给三分钟
> 后的自己"，于是没人填。上下文收集能力**降级为一次性 prompt 模板**
> （`skills/tk-debug/references/collector.md`），由 keeper 派给 `general-purpose`
> 当第 2 层子代理，用完即弃，不再落盘独立产物、不再有常驻 agent。

> **3.0.0 起 `sdlc-writer` 整体迁出**：agent + `tk-sdlc` skill +
> `pre-tool-use-sdlc-writer-guard` + 三岔口第 5 支路一并迁到 radnove 市场的
> `radnove-sdlc` 插件（与公司内部 ai-sdlc 流程绑定，不属于公开 devkit）。本插件回到
> debug / chore 两 keeper 纯净态。

## 组成

| 类型 | 名称 | 作用 |
|---|---|---|
| skill | `tk-debug` | debug 队列全流程指引（登记 → triage → 一 issue 一 worktree 派发 → 合并前对账 → 归档） |
| skill | `tk-chore` | 杂务队列：主会话判是杂务就转 chore-keeper，自己立刻回原任务 |
| skill | `tk-decisions` | 决策打包 HITL 协议正典（keeper 与主会话之间怎么攒批问人） |
| skill | `tk-worktree` | 为 `git worktree` 建的工作区供给 submodule 内容（含嵌套递归），6 个子命令；`init` 支持 `--ids` 批量 + `--jobs` 并行建多个 issue 的 worktree |
| skill | `tk-board` | 进度看板：每条一行（编号 + 20 字说明 + 四态）+ 计数占比 + 告警段，纯只读、不唤醒 keeper。同目录另有 `pending_dispatch.py`——只算「漏派」一件事（已 triage 但既不在飞、也不在等拍板），三种输出模式 |
| agent | `debug-keeper` | 独占 `.keeper/<交付id>/debug/` 写权限，承接 bug 报告全流程。**v7 起一条 bug 一个实例**，同档可并存多个 |
| agent | `chore-keeper` | 独占 `.keeper/<交付id>/chore/` 写权限，承接杂务登记与攒批执行。**默认同一交付只有一个实例**，仅在明确要求并行清账时才多开 |
| script | `scripts/keeper_cli.py` | v7 新增的多实例并发原语 CLI：`claim`（原子认领编号）/ `bind`（登记 issue→name）/ `lock acquire\|release\|status`（合并锁，debug 侧合并回主仓用，超时 15 分钟自动抢占）/ `peers`（看同档其它实例）；exit 3 = 锁被占用（正常竞争，非故障） |
| hook × 9 | 见下表 | 注入路由（session-start + user-prompt-submit）+ debug/chore 两份队列快照 + 三道窄判据守卫 + 1 个 keeper 实例登记（含 issue 提取） + 1 个 debug-keeper 专属的漏派清单注入 |

## hooks（挂载事件与实际行为）

| 脚本 | 事件 | 行为（按动作描述，不是按愿望描述） |
|---|---|---|
| `session-start-keeper-routing.sh` | SessionStart | 纯注入**静态参考**（决策打包主会话侧职责、v7 布局、多实例说明、合并锁指针）。未启用 195 字符（一句话介绍 + 启用方式），已启用 795 字符（v7 新增多实例段落后从 495 涨上来），不拦截任何操作 |
| `user-prompt-submit-keeper-routing.sh` | UserPromptSubmit | 纯注入**三岔口分诊**（自己做 / 转 debug-keeper / 转 chore-keeper）+ 转发三原则 + 现算的一句"唤醒前怎么办"。**v7 起同一档可并存多个实例**，这句话按会话归属把有效登记分成「还有活」与「已收工」两组分别成句（各自列出 `issue→name` 映射，超过 4 个收成"等 N 个"），都没有登记时回落成"首次派发"（见下方「登记 keeper 实例 name」）。实测长度：没有登记 434 字符、登记已失效 445 字符、有活实例（2 条映射示例）459 字符、全部已收工 353 字符；硬上限 800（H19/H22/H29 断言）。未启用项目 stdout 全空 |
| `user-prompt-submit-debug-queue.sh` | UserPromptSubmit | 注入 debug 队列实时快照（open 逐条 + 在飞派生 + done 计数）、重算薄索引 `index.md`（git rebase/bisect/merge 中间态跳过）；`.gitignore` 缺 v6 那四条精确排除、或还留着 v5 的整树忽略行时加一句提醒；存量 v3/v2 布局未迁移时加一句迁移提示；命中 bug 特征词时给出下一个可用 DBG-id（fixer worktree 内不给） |
| `user-prompt-submit-chore-queue.sh` | UserPromptSubmit | 注入 chore 队列快照（输出预算 ≤900 字符）；`.keeper/` 顶层存在时缺失的 `chore/`（连同 `debug/`）由 `find_queue` 每轮自动补建，不需要手工 mkdir；代注待拍板决策计数（自动补建后 `chore/` 恒存在，debug 快照的兜底注入分支实际只在 fixer worktree 内或补建失败时才会走到，两边判据仍是同一个目录的存在性） |
| `pre-tool-use-debug-worktree-push.sh` | PreToolUse(Bash) | `git push` 的目标落在 `.keeper/<交付id>/debug/<DBG-id>/worktree/` 内时 deny（fixer 产物只回流不推远端） |
| `pre-tool-use-debug-worktree-destroy.sh` | PreToolUse(Bash) | 强制删除形态（`rm -rf` / `worktree remove --force` / `clean -fdx`）命中 `.keeper/<交付id>/debug/<DBG-id>/worktree/` 路径时 ask 弹确认框 |
| `pre-tool-use-debug-evidence.sh` | PreToolUse(Write\|Edit) | 只对 `.keeper/<交付id>/debug/*.md` 介入：新内容含 `image-cache` 会话级临时路径时 deny（跨会话必 404），带次数熔断，`origin_path` 留档豁免 |
| `pre-tool-use-keeper-instance.sh` | PreToolUse(Agent) | 命中 keeper 类 `subagent_type`（`debug-keeper`/`chore-keeper`）的派发时，把 `tool_input.name` 连同这次派发所在的 `session_id`、以及从 `prompt`（抽不到再退 `description`）里正则抽到的第一个 `DBG-NNN`/`CHR-NNN` 一并写进 `.keeper/<交付id>/.keeper-instance.json` 对应键；**v7 起该键是实例列表**，按 `name` 去重更新、不覆盖同档其它实例；抽不到 issue 就不写这个字段，不编造。纯写文件，不拦截任何操作，不输出 permissionDecision，写不进去就静默放弃 |
| `subagent-start-debug-keeper.sh` | SubagentStart（matcher `task-keeper:debug-keeper`） | 跑 `skills/tk-board/scripts/pending_dispatch.py --oneline`，输出非空时注入一段「漏派体检」（那一行 + 处置指引）。**无漏派时零输出**、未启用项目零输出、坏 payload 零输出，恒 exit 0。matcher 精确到单个 agent_type，**不是 `*`**——写 `*` 会把 debug 队列的清单灌给本机每一个子代理 |

三道守卫的判据都是路径子串 + 命令形态的机械判定，未启用队列的项目全部零输出零成本。
`pre-tool-use-keeper-instance.sh` 不是守卫——它不拦下任何动作，只有"顺手写一个登记
文件"这个副作用，供主会话下次唤醒 keeper 前读取真实 `name`（见下方「登记 keeper
实例 name」）。context 队列已删（见文件头说明），`user-prompt-submit-context-queue.sh`
随之一并拆除，不再出现在上表中。

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
    ├── .keeper-instance.json            ← keeper 实例登记（v7 起每档一个实例列表），见下方「登记 keeper 实例 name」
    └── .merge.lock/owner.json           ← 合并锁，短暂存在；由下面第四条 gitignore 规则排除（连同抢占残留 .merge.lock.stale-<旧持有者>/）
```

`<交付id>` 由 `hooks/lib/keeper_paths.py` 解析：先 `--show-superproject-working-tree`
跳出 submodule、fixer worktree 经 `<git-dir>/wt-supply-source` 回溯到 delivery、
再取 `--show-toplevel` 的 basename。**不能**简单地"从 cwd 向上找 `.keeper`、遇 `.git`
停"——linked worktree 根自己就有一个 `.git` 文件，那样第一轮就返回 None，aisdlc 交付
跑在 `.sdlc/worktrees/D-NNN-<slug>/` 里时队列恒为空，冷启动还会 mkdir 出第二份。

**正文与附件入库，只精确排除四类本机产物（v6，2026-08-10 用户拍板）**。keeper 冷启动
自动写入：

```gitignore
# task-keeper 队列：正文与附件入库，只排除四类本机产物
.keeper/**/worktree/
.keeper/**/.keeper-instance.json
.keeper/.keeper-active
.keeper/**/.merge.lock*
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
> `.keeper/` 搜不到」收窄到「只有那四类搜不到」。
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
| **v6（现行）** | 正文与附件入库 + 四条精确排除 | 可搜、可恢复、跨 worktree 共享、receipts 随 merge 自动带回 | **bug 细节、内部坐标、截图随推送公开**——所以截图脱敏成了红线；幽灵 gitlink 这条路重开，`check_staged_gitlink.py` 必跑；`index.md` 每轮重算会造工作区 diff |

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

**gitignore 分工（自动追加，靠文案写死避免冲突）**：keeper 冷启动检查那四条在不在，
缺就整块追加，**注释与 pattern 逐字写死**（`GITIGNORE_BLOCK`，
`hooks/lib/queue_snapshot.py`）。v4 当初禁止自动追加的唯一理由是实测过「两个分支各自
EOF 追加**内容不同**的注释即冲突」——内容逐字相同则 git 视为同一处改动、不冲突。
**三处必须逐字同步**（该常量 + 两个 agent 定义里的 `printf`），回归用例 H28 [121] 锁
这一条，且反向验证过它真能抓到失同步。

快照 hook 只注入提醒、不代写文件——**代写只发生在 keeper 冷启动这一处**，两处都代写
会在 hook 未生效的环境里制造「以为写了其实没写」的分叉。它报两类：v5 整树忽略行残留
（`GITIGNORE_LEGACY_ALL` 命中，它覆盖四条精确规则且静默生效）、四条里缺了哪几条
（`GITIGNORE_RULES` 逐条比对）。

## 登记 keeper 实例 name（2026-08-04 起，v7 于 2026-08-18 改成多实例）

keeper 的 `name` 强制带 4 位随机短哈希。**2026-08-18 起两个 keeper 的档位与 name
身份段按 kind 分叉**（`working-discipline` 插件 `agent-dispatch.js` 的 `KEEPER_SPECS`
表，正则校验不在本插件内）：

| kind | 档位 | name 形态 | 正则 |
|---|---|---|---|
| debug | `opus`（不变） | `opus-debugger-<4位>` | `^opus-debugger-[0-9a-z]{4}$` |
| chore | `sonnet`（**本次从 opus 降档**） | `sonnet-chore-<4位>` | `^sonnet-chore-[0-9a-z]{4}$` |

判据是**等值不是下限**：chore-keeper 派成 `opus` 与派成 `haiku` 一样会被硬拦。降档
理由是 chore-keeper 的活（登记/分类/攒批/归档）每一步都有明确判据可照着走，不需要
debug-keeper 那种「判错一次、代价由后面整条流水线承担」的跨层追根因能力（triage
错一次整条队列跟着错，这条论证只对 debug 成立）。旧版逐字固定名（`opus-debug-keeper`）
在「同一段会话里前一个实例结束、下一个又叫同名」时会撞车——`SendMessage` 的 name
寻址是 latest wins，唤起前一个就会失联——这条起因两个 kind 都继承，是加短哈希后缀
的根本原因。

### v7：同一档并存多个实例，登记从「一条」变成「列表」

v6 是一档一个常驻 keeper 顺序处理整条队列，登记形如
`{"debug": {"name": ..., "ts": ..., "session_id": ...}}`——每档一条，后写的覆盖
先写的，直接编码了"同一档只允许一个实例"这条旧架构假设。v7 改成**一条 bug 一个
debug-keeper 实例，多个并存互不干扰**；chore-keeper 默认仍是**单实例攒批**（价值
恰恰在跨条目视野：一次攒批执行、把待拍板事项打成一个包一次问完、归档看整个 done
桶——拆成多个各管一段，这三件事全部失效，Human 会收到 N 个各说各话的拍板请求），
只有 Human 明确要求并行清账时才多开。

登记格式相应改为每档一个实例列表：

```json
{"debug": {"instances": [
    {"name": "opus-debugger-4bb6", "ts": "...", "session_id": "...", "issue": "DBG-207"},
    {"name": "opus-debugger-91af", "ts": "...", "session_id": "...", "issue": "DBG-208"}
]}}
```

`issue` 是新增的寻址键：多实例下光有 `name` 不够——主会话手里是"DBG-207 又复现了"
这样的事实，要唤醒的是**认领了 DBG-207 的那个实例**，不是"最近派的那个"（那正是
并行化要消灭的串行假设）。`issue` 由 `pre-tool-use-keeper-instance.sh` 从派发的
`prompt`（抽不到再退 `description`）里正则抽第一个 `DBG-NNN`/`CHR-NNN`，抽不到就
不写这个键——登记照常写入，只是退回按时间定位，不为了"总得有个值"去编一个。

**4.3.0 起 `description` 的规约收成「全串简体中文、上限 15 字」**（按 code point 计，
一个汉字与一个 ASCII 字符都算 1 字），覆盖两层：主会话派 keeper（前缀 `<kind> 队列`
占 8 字，分隔符改用不带空格的 `·`，摘要剩 6 字）与 keeper 派 fixer（形如
`修 DBG-024 分类归属`，14 字）。**同时定下「keeper 的 description 里不写 issue 编号」**——
编号靠 `prompt`，上面那条抽取链本来就是 `prompt` 优先。理由有两层，第二层是实测出来的：
`debug 队列·DBG-042` 已是 16 字超限，而想省掉分隔符压到 15 字的 `debug 队列DBG-042`
会让 `keeper_instance_register.py:84` 的 `\bDBG-\d{3,}\b` **抽不到编号**（汉字在 Python
的 Unicode 模式下属于 `\w`，「列」与 `DBG` 之间没有词边界），登记文件因此静默少一个
`issue` 键。`hooks/tests/cases/25-h30-multi-instance.sh` 的 `[156]` 保留带分隔符的
21 字形态并注明有意超限——它测的是这条兜底通道的 hook 行为，不是文档样例。

读侧（`read_keeper_instances` / `live_instances`）兼容 v6 的单 record 格式（自动
升维成单元素列表），存量登记文件不需要迁移；写侧一律吐 v7 格式，不做"只有一条就
退回 v6"的分支。登记是**追加**而不是覆盖——同名重复登记按更新处理（幂等，重复
派发同一个 name 安全），不同名则并存。淘汰是写入时顺手做的：超过 14 天
（`INSTANCE_TTL_DAYS`）或每档超过 30 条（`MAX_INSTANCES_PER_KIND`）的记录被丢弃，
时间戳解析不出来的记录保留而非丢弃（避免误删还活着的实例）。登记本身只是唤醒线索
不是台账，真正的事实来源是 `debug/DBG-*/issue.md`，丢了最坏是退回"首次派发"。

写文件的副作用 hook（`pre-tool-use-keeper-instance.sh`）不判断该不该放行这次
`Agent` 调用（放行判据是 `working-discipline` 的职责），任何异常（找不到 git 仓库、
文件写不进去）都静默降级，不影响本次 Agent 派发。读写函数在 `hooks/lib/keeper_paths.py`
（`read_keeper_instances` / `live_instances` / `write_keeper_instance`），判据与
异常处理在 `hooks/lib/keeper_instance_register.py`（含 `issue` 抽取逻辑）。

### 会话隔离（2026-08-05 补，v7 下按实例逐条判断）

登记文件落在磁盘上、**跨会话存活**，但派出去的 keeper 只活在派出它的那次会话里。
若无这层隔离，新会话第一次转任务时主会话会读到上一个会话的死 name，`SendMessage`
报 `No agent named ... is reachable`，按"唤醒不到就重派"的错误反应会直接又派第二个
实例，两个实例抢同一个队列目录的独占写权限——这正是登记机制本来要消除的失败模式，
在跨会话场景下原样复活了一次。

修法是登记里多写一个 `session_id` 键（取自 hook payload 的 `session_id` 字段）。
真正做会话比对的落点**不是主会话自己读文件**——主会话拿不到自己的 `session_id`，
没有任何机械手段验证"这条登记是不是本会话写的"；比对现算在
`user-prompt-submit-keeper-routing.sh` 每轮注入里，v7 起遍历的是**列表**，按
`instance_state`（见下方「已收工」）把本会话名下有效的登记分成两组分别成句：

- **还有活**（未收工，或状态无法判定——判不出时按"还有活"保守处理）→ 列出
  `issue→name` 映射，告诉主会话"新条目一律新派实例，只有补充某条既有 issue 的
  信息才唤醒认领了它的那个"。
- **已收工**（认领的 issue 已 `status: done` 且无 `worktree/` 残留）→ 列出
  `issue→name` 映射，告诉主会话"别再主动唤醒它"。
- 都不属于本会话的登记（`session_id` 不一致，或是加会话隔离之前落的旧格式、压根
  没有 `session_id` 键）→ 一律当陈旧处理，不做"没写就算通过"的宽松判断。
- 没有任何登记 → 首次派发。

`keeper_paths.write_keeper_instance` 的 `session_id` 参数取不到时**不写这个键**
（不是写 `null`），登记本身不受影响，只是这条记录之后没法被会话比对认领。

**"新条目一律新派实例"是给 debug 写的，对 chore 不成立**——4.2.0 起「在跑」那一句按
kind 分成两句，各自带本档的处置方向：debug 句写"新 bug 一律新派实例"，chore 句写"新杂务
一律 `SendMessage` 交给它"。4.0.0～4.1.0 期间这里只有 debug 一句，chore 实例在场时主会话
读到的是反的方向；靠头部通则那句「杂务相反」远距离兜着不够——紧贴实例清单的那一句更近、
更具体，会盖过通则。chore 侧只有明确要求并行清账才多开，见 `skills/tk-chore/SKILL.md`
「唤醒 vs 再派一个」一节。

### 「已收工」不是「换代」：v6 的换代机制在 v7 里已不驱动任何注入

v6 曾有一套"队列收口时新派一个实例、换一句新鲜 description"的机制（判据是
`keeper_generation.retirable_kinds`：done 非空 + open 空 + unknown 空 + 无待答复
裁决 +〈debug 专项〉无 worktree 残留，五项全过才算"这一档收口"）。**v7 起
`retirable_kinds` 已从每轮注入里摘掉**，只保留成一个未接入任何 hook 的诊断函数
（供人工按档查询"这一档是不是全清了"）；驱动每轮注入的换成`instance_state`——
按**实例当前认领的那条 issue**判断它是否做完，不是判断整档是否收口。

所以"已收工，别再唤醒：`<name>`"这句话只表示"它认领的这条 issue 处理完了，没理由
主动 `SendMessage` 给它"，**不代表要新派一个替代它**。它仍是默认要用的那个实例：
下一条新活照常唤醒它，上下文完整保留。`keeper-dispatch.md` 已随 4.0.0 一并改写成
按实例的说法，读到别处（旧 agent 定义、旧笔记）仍写着"换代"时以本节为准。

### 合并锁与原子认领：`scripts/keeper_cli.py`

v7 多实例并发引入两个必须原子的动作，靠 agent 用 `Write` 手工做一定会出竞态：

1. **认领编号**——两个实例同时登记新 issue，各自扫目录算 next id 再各自写
   `issue.md`，后写的整份覆盖先写的，表现是"一条 bug 凭空消失"且不报错。
2. **合并回主仓**——两个 debug-keeper 实例同时 `git merge` 同一个主仓 HEAD，撞出
   半完成的 merge 状态，没有干净的自动恢复路径。

| 子命令 | 作用 | 退出码约定 |
|---|---|---|
| `claim --kind <debug\|chore>` | 原子认领下一个编号，落一份占位正文 | 0 成功；连试 64 个编号都被占用则非 0 |
| `bind --kind <k> --name <n> --issue <id>` | 把"这个实例认领了哪条 issue"写进登记 | 0 成功 |
| `lock acquire\|release\|status` | 合并锁（debug 侧合并回主仓用），超时 15 分钟自动抢占 | 0 成功；**3 = 锁被占用**（正常竞争，非故障，应等待重试）；4 = 释放了不属于自己的锁 |
| `peers --kind <k>` | 列出同档还在登记里的其它实例 | 0 |

合并锁落在 `.keeper/<交付id>/.merge.lock/`（目录 mkdir 原子性 + `owner.json` 记录
持有者），chore 通常不需要它——各条目独立目录，写操作天然无锁竞争。

## 归档：两条粒度，常态走单条

`skills/tk-debug/scripts/archive_done.py`（debug/chore 共用，`--queue` 区分）有两个入口，
按**谁拥有这条条目**分工，互斥：

| 入口 | 谁跑 | 什么时候 |
|---|---|---|
| `--issue DBG-216 --apply` | keeper 实例 | 它认领的那条 `status` 转 `done` 之后，一条一次 |
| `--auto --apply` | 主会话 | 确认没有在飞 keeper 实例时，清没人认领的历史 done 条目 |

单条模式不看阈值、不看队列静默期——所有权与操作范围对齐，搬的就是自己那个目录。
全量 `--auto` 仍看两条阈值中的任一条：

| 判据 | 阈值 |
|---|---|
| done 条目数 | ≥ 10 |
| 最早 done 条目的 `reported_at` 距今 | > 14 天 |

**为什么切成两条粒度**：v4 起一个 keeper 实例只认领一条 issue，而全量归档扫全队列逐条
`shutil.move`，会搬走**别的实例正在写的条目目录**。而「那个实例还活着吗」在本插件里没有
可靠数据源（`.keeper-instance.json` 是派发即登记、无摘除环节，记录最长滞留 14 天）。实测
后果是两个 keeper 都判断「跑归档会伤到别人」于是双双跳过，归档永远不发生。降到单条粒度后
这个判断根本不需要做。

`--auto` 另有一道队列静默期闸：debug 队列里只要还有条目挂着活 worktree 就整轮不归档并打印
阻塞原因。**这道闸对 chore 队列恒放行**（chore 条目没有 worktree），所以 `--auto --queue chore`
会额外打印一行提醒，说明本次没有任何机械防线，判断责任在跑它的人。显式 `--batch` 不过这道闸。

批次名 `auto-<YYYYMMDD>`（`--auto` 与 `--issue` 共用）。`next_id` 的扫描覆盖 `archive/**`，
归档后编号**不回收**。worktree 目录还在的 done 条目跳过并警告（先收工作区再归档）。

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

## 动手前的上下文收集：降级为一次性 prompt 模板（4.0.0）

2.14.0 曾引入 `tk-context` skill + `context-keeper` agent，要防的是某次交付事后
归因里最大的一类——「**规格写了，但没照着做**」（55 条、占 27.9%）：实现只看了
原型，文字规格 md 没人读，整片规格就此失效；ai-sdlc 的机械硬闸也兜不住，因为它的
基线全是原型 html，覆盖文字规格的 `spec-sync-audit` 轴是 advisory 不阻断，且明文
排除 UI 元素。当时的对策是常驻收集：五方并行查（需求/原型/spec/ontology/代码）→
归一印证矩阵 → 落盘上下文包 + 空销账表（由实现者事后逐行填）→ 事后差异核对三件套。

**这套常驻产物在实测里从未被真正使用过**：全机 8 个真实项目的 `.keeper/*/context/`
共 0 条 CTX 条目，`context.md`/`ledger.md`/`reconcile.md` 一次都没被创建过（见
`hooks/tests/run-tests.sh` 「2026-08-18 摘除 H27」）。根因是它依赖的前提——"收集者
与实现者是两个能持续对接的常驻角色"——从未成立过；v7 一条 issue 一个 keeper 实例
之后这个前提更加不成立：收集与实现落在同一个实例的同一段上下文里，销账表要填给
谁看？答案是"填给三分钟后的自己"，于是没人填。

4.0.0 起整套拆除（`context-keeper`、`tk-context`、CTX-NNN 队列、
`user-prompt-submit-context-queue.sh` 全删），要防的问题没有消失，但对策改成
**一次性 prompt 模板**（`skills/tk-debug/references/collector.md`）：由 debug-keeper
或 chore-keeper 按需派给 `general-purpose` 当第 2 层子代理，做同样的五路并行检索
（需求/原型/文字规格/ontology/代码）、同样要求逐条给 `path:行号` 坐标、同样要求
"没有"必须先自证检索手段有效、同样有"何为一个功能单元"的边界判据（拆太粗整条机制
空转、拆太细漏发现跨条目矛盾）——差别只在收集完直接把断言清单交回派它的 keeper
手上用，一次性用完即弃，不落盘独立产物、不需要常驻 agent、不需要外部实现者回头
填表。何时派、何时不派、五类信源判据、功能单元边界怎么拆，见
`skills/tk-debug/references/collector.md` 全文。

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

## sdlc-writer 已迁出（3.0.0）

`sdlc-writer` 整套（agent + `tk-sdlc` skill + `pre-tool-use-sdlc-writer-guard` + 三岔口
第 5 支路）已于 3.0.0 迁到 radnove 市场的 `radnove-sdlc` 插件——它与公司内部 ai-sdlc
流程绑定，不属于公开 devkit。本插件回到 debug / chore 两 keeper 纯净态，三岔口不再
有 sdlc 支路（4.0.0 又拆掉了 context，现状见文件头「context 队列已删」）。

## 主会话保持精炼的手段（设计目标，已写进各文档）

1. 三岔口路由只转发不亲做：bug 原话逐字转给 debug-keeper、杂务转给 chore-keeper，主会话立刻回原任务。
2. keeper 的 `SendMessage` 一律 ≤3 行指针化（结论 + 文件路径），不往主会话倒正文。
3. 决策攒批：多条待拍板合成一次 `AskUserQuestion`，不逐条打断。
4. 注入有字节预算：chore 快照 ≤900 字符、SessionStart 路由注入未启用/已启用两档
   （195 / 795 字符）、UserPromptSubmit 三岔口硬上限 800 字符，未启用项目的队列
   快照零输出。
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

## 已知的文档/实现滞后：当前为空（4.3.0）

**这张清单只登记当前仍然成立的滞后。** 4.0.0 交付过程中登记过四条（`keeper-dispatch.md`
§4 的"换代"描述、`.merge.lock` 未列入 gitignore、CLI 与合并锁无回归测试、
`WAKE_LINE_LIVE` 未做 debug/chore 分叉），前三条在 4.0.0 当次补齐，最后一条在 4.2.0
补齐（见上文「新条目一律新派实例」那段），故全部从本清单移除而不是留在这里打勾。

一条已经解决却仍挂在"已知问题"里的条目，比信息缺失更糟：下一个读者会照它绕路，或者
再花一次力气去核实它是不是真的还成立。留着这个空节是为了让下一次交付有个现成的落点——
发现新的滞后就往这里加，别新起一节。

## 测试

```bash
bash plugins/task-keeper/hooks/tests/run-tests.sh
```

真实进程回归（JSON 喂 stdin、断言 stdout，不 mock），覆盖：队列快照分桶/排序/坏文件显式告警、
index 幂等、三道守卫的拦与不拦两侧、wt_supply 供给/幂等/回流前置校验、归档与编号不回收、
chore 快照字节预算、决策信箱计数、双队列互不串号、归档粒度与判据、路由注入分档、
keeper 实例登记的写入与放弃两侧（白名单命中/不命中、name 缺失、目录不存在时自动建出、
另一个键保留）、会话隔离两侧（`session_id` 写入/同会话读得到/跨会话读不到/旧格式
无 `session_id` 键当陈旧处理/payload 缺 `session_id` 时仍正常登记 name、三岔口注入
按会话状态与实例存活状态现算的措辞）、整档收口判定 `retirable_kinds`（H29：done 非空/
open 未清/有裁决/有 worktree 残留四条否定用例 + 一条肯定用例）。

**v7 多实例（H30，`25-h30-multi-instance.sh`）另覆盖**：原子认领 `claim_id`（含 8 个
**真实进程**同时认领拿到 8 个互不相同编号，以及"换回 `next_id` 就只剩 4 个"的阴性
对照）、合并锁 acquire/release/超时抢占与 owner 不匹配拒删、`extract_issue` 的抽取与
跨档不串号、`instance_state` 的 live/retirable/unknown 三态含误杀侧、三岔口措辞与
800 字符上限、`SubagentStart` 的两份事实与"单实例无漏派保持零注入"、登记表的多实例
并存与 v6 单条格式吸收。**4.2.0 追加 kind 分叉两侧**：debug 与 chore 混跑时两句各自
只装本档编号（抽句内片段判定，不锁条目排列顺序），以及"只有 chore 在跑时不得出现
debug 的新派口径"这条阴性对照（`[171b]`）。测试里的日期与时间戳**一律现算**，不写死字面量——写死正是
`[63]` 那条时间炸弹的成因（fixture 的 `reported_at` 钉死后越过 14 天超龄线，用例从
某天起恒红且报错文案指向归档逻辑，与真实成因无关）。覆盖见
`hooks/tests/run-tests.sh` 头部按 H 编号的分节说明。
