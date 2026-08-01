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
| hook × 6 | 见下表 | 注入路由/队列快照 + 三道窄判据守卫 |

## hooks（挂载事件与实际行为）

| 脚本 | 事件 | 行为（按动作描述，不是按愿望描述） |
|---|---|---|
| `session-start-keeper-routing.sh` | SessionStart | 纯注入三岔口分诊指引（即时做 / 转已有体系 / 转 keeper）。未启用项目注入 ~175 字符，已启用 ~792 字符，不拦截任何操作 |
| `user-prompt-submit-debug-queue.sh` | UserPromptSubmit | 注入 debug 队列实时快照（open 逐条 + 在飞派生 + done 计数）、重算薄索引 `index.md`；`.gitignore` 缺 `.keeper/` 行时加一句提醒；存量 `.debug/` 未迁移时加一句迁移提示；命中 bug 特征词时给出下一个可用 DBG-id |
| `user-prompt-submit-chore-queue.sh` | UserPromptSubmit | 注入 chore 队列快照（输出预算 ≤900 字符）；代注待拍板决策计数（chore 未启用时由 debug 快照兜底，两边按目录存在性去重） |
| `pre-tool-use-debug-worktree-push.sh` | PreToolUse(Bash) | `git push` 的目标落在 `.keeper/worktrees/` 内时 deny（fixer 产物只回流不推远端） |
| `pre-tool-use-debug-worktree-destroy.sh` | PreToolUse(Bash) | 强制删除形态（`rm -rf` / `worktree remove --force` / `clean -fdx`）命中 `.keeper/worktrees/` 路径时 ask 弹确认框 |
| `pre-tool-use-debug-evidence.sh` | PreToolUse(Write\|Edit) | 只对 `.keeper/debug/issues/*.md` 介入：新内容含 `image-cache` 会话级临时路径时 deny（跨会话必 404），带次数熔断，`origin_path` 留档豁免 |

三道守卫的判据都是路径子串 + 命令形态的机械判定，未启用队列的项目全部零输出零成本。

## 产物布局：`.keeper/`，整树 gitignore

```
<项目根>/.keeper/
├── debug/{index.md, issues/DBG-NNN.md, attachments/, receipts/, archive/}
├── chore/{index.md, items/CHR-NNN.md, archive/}
├── decisions/{<stamp>-<keeper>.md, answers/<同名>.md}
└── worktrees/<id>/          ← tk-worktree init 的固定落点（与 debug/ 平级）
```

**为什么不入库（有意取舍，不是遗漏）**：前身 radnove-core 的 `.debug/` 设计为整树入库，
issue 历史与跨 worktree 共享靠 git；代价是工作区常年挂着队列 diff、并行 worktree 会在
`index.md` 上互写冲突。`.keeper/` 反过来：队列是纯本机产物，工作区永远干净、index 抖动
问题直接消失，代价是**误删 `.keeper/` 无法从 git 恢复**、多人不共享队列。缓解手段是
自动归档把 done 沉到 `archive/` 降低活跃面损失 + destroy 守卫对强删弹确认框。

**gitignore 写入分工**：keeper 冷启动（首次 `mkdir -p .keeper/...`）负责向项目 `.gitignore`
追加 `.keeper/` 行并**回读验证**；快照 hook 发现缺行时只注入一句提醒、不代写文件。

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
| 1 | keeper | 写 `.keeper/decisions/<stamp>-<keeper>.md`（from/about/kind/blocking/options/recommend），`SendMessage(main)` ≤3 行打铃 |
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
编号分配——这些硬教训全部原样保留，只去掉了公司专属部分并把产物仓从入库的 `.debug/` 改为
gitignored 的 `.keeper/`。radnove-core 自 5.0.0 起已删除全部 debug 资产、只留
`debug-ones-writeback` 适配器。

**不要与 radnove-core ≤4.5.1 同装**：守卫会双注册（同一命令弹两次确认框）、`debug-keeper`
agent 同名二义。装本插件请把 radnove-core 升到 5.0.0+。

## 存量 `.debug/` 迁移（一次性）

旧版 radnove-core 项目里入库的 `.debug/` 迁到新布局：

```bash
mkdir -p .keeper/debug
mv .debug/* .keeper/debug/
git rm -r --cached .debug && rm -rf .debug
printf '.keeper/\n' >> .gitignore
git add .gitignore && git commit -m "chore: debug 队列迁出 git 跟踪（task-keeper .keeper/ 布局）"
```

历史 issue 的 git 历史留在旧提交里可考古。漏做迁移时快照 hook 会检测到
「`.debug/issues/` 存在而 `.keeper/debug/` 缺失」并注入迁移提示，不会静默丢队列。

## 测试

```bash
bash plugins/task-keeper/hooks/tests/run-tests.sh
```

真实进程回归（JSON 喂 stdin、断言 stdout，不 mock），覆盖：队列快照分桶/排序/坏文件显式告警、
index 幂等、三道守卫的拦与不拦两侧、wt_supply 供给/幂等/回流前置校验、归档与编号不回收、
chore 快照字节预算、决策信箱计数、双队列互不串号、自动归档判据、路由注入分档。
