# 队列结构 · 派发 · 对账（schema v3）

## 目录

本文较长，按需查阅——先在本节定位要读的章节，再用
`grep -n '^##\|^### ' references/queue.md` 跳到对应行。

- **§1 文件布局**——`.keeper/debug/` 目录结构、`.keeper/` 整树为什么不入库、
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
.keeper/
├── debug/
│   ├── index.md            派生视图。hook 每轮重算，人和 AI 共用。不要手改
│   ├── issues/
│   │   ├── DBG-001.md      一 issue 一文件。唯一信源
│   │   └── DBG-002.md
│   ├── attachments/
│   │   ├── _inbox/         主会话刚落盘、还没分配 DBG-id 的截图
│   │   └── DBG-020/        登记后 mv 到这里
│   ├── receipts/           fixer 的交付回执，一 issue 一个文件
│   │   └── DBG-017.md
│   └── archive/            按交付批次归档的 done 条目（§6「归档」）
│       └── D-001-feat-xxx/
│           ├── issues/DBG-005.md
│           ├── receipts/DBG-005.md
│           └── attachments/DBG-005/
├── worktrees/               派发用的 git worktree（§4），与 debug/ 平级
│   └── DBG-017/
├── decisions/                keeper 与主会话的 HITL 通道（agents/debug-keeper.md §12）
│   └── answers/
└── chore/                    另一个 keeper 管，不归本文档
```

**`debug/` 下五样，外加平级的 `worktrees/` 与 `decisions/` 两层临时/通道产物。**
v2 还有个 `journal.md` 装「跨 issue 的批次记录」，删除——它是 v2 `issues.yaml` 的
`meta` 段原样搬迁的产物，没做过归属重判，实测装的绝大部分是**单条 issue 的**决策与
对账（「DBG-002 走方案 1」「DBG-005 外延要一起去」），且没有任何 hook 读它写它校验
它。一个无机制保障、无人校验、内容大半该属于别人的手写 append-only 文件，会稳定长成
第二个 `issues.yaml`。批次信息按归属分流，**不要落在 `.keeper/debug/`**：属于某条
issue 的（Human 对它的拍板、它的落点与量级对账、它的字段变动）写进那条 issue 的
「修订记录」章节；真正跨 issue 的交付级事实（一次批量流转的结果、整个交付的 spec
delta、本次交付的台账）属于项目自己的交付文档体系（如仓库里的 `.sdlc/` 或等价
目录），`.keeper/debug/` 只装 bug 队列本身。

**`.keeper/` 整树在项目 `.gitignore` 里一行 `.keeper/` 排除，不入库**——这是用户
拍板过的取舍：换来工作区干净、不必维护任何子目录级别的 ignore 例外，代价是队列
数据没有 git 历史、也没法靠 git 在多个 clone/worktree 之间共享，是刻意接受的成本，
不是遗漏。`index.md` 由 hook 每轮重算，同样落在这条 ignore 规则之下——**不要手工
编辑它**，下一轮就被覆盖，改了也不会有 diff 提醒你（反正不入库）。

**因为一行 `.keeper/` 就覆盖了 `debug/`、`worktrees/`、`decisions/`、`chore/`
全部子目录，不需要像早期方案那样单独为 `worktrees/` 这一层再配一条精确匹配的
ignore 规则**——旧方案下 worktree 目录不加专门的 ignore pattern 时，
`git status` 会把它显示成普通未跟踪目录，一旦被 `git add` 选中还会触发
`warning: adding embedded git repository` 把整个 worktree 当 gitlink 提交进父仓；
现在顶层的 `.keeper/` 规则从一开始就让这整棵子树对 `git add -A` / `git add .`
不可见，不会走到那一步。**冷启动时检查这行是否存在、缺了就追加并回读验证**，
是 keeper 的职责（`agents/debug-keeper.md` §3），不是 hook 的职责——hook
（`hooks/lib/queue_snapshot.py`）只在每轮注入时提醒缺失，不代写。

## 2. issue 文件格式

frontmatter 只放**能被机械消费的状态**，一共 9 个键，声明与渲染顺序见
`hooks/lib/queue_files.py:75-85`（`DEBUG` 这个 `QueueSpec` 的 `fm_order`）。长文本
一律进正文章节——否则 frontmatter 会重新长成第二个 `issues.yaml`。

```markdown
---
id: DBG-017                 # 与文件名一致
summary: 一句话摘要         # index.md 直接用它，写清楚
status: open                # open | done ← 只有两个
priority: P1                # P0 阻断 / P1 主流程 / P2 体验
difficulty: medium          # easy | medium | hard
type: bug                   # bug | ux | perf | arch
reported_at: 2026-07-29
reopen_count: 0
external_ref: TRACKER#644168   # 可选，格式 <系统名>#<id>，见 references/external-tracker.md
---

# DBG-017 · <summary>

## 用户原话

> 以下为用户报告原话，**禁止改写、禁止摘要**。

```text
<逐字照抄>
```

## 证据

- `.keeper/debug/attachments/DBG-017/01-xxx.png`
  - origin_path：<image-cache 原路径，仅留档>
  - 转录：<图里能看到什么，文字描述>

## Triage

<改法、落点文件:行号、需要人拍板的歧义>

## 修订记录

### 首轮修复（2026-07-29）
<改了什么、有意偏离报告诉求的地方、未验证的部分>

### reopen（2026-07-30）
<为什么打回、这次要求与上次的差别在哪>

## 验证

<逐场景的验证步骤与结果>
```

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
物理隔离 + 并发上限之后，「顺序」几乎不产生可观察的差别：open 有 7 条、同时在飞 5
个，那么排序只决定哪 2 条晚一轮，而不是哪几条会被修。真正影响结果的是**并发上限**
（§4 末）与**收官时谁被推迟**（`priority` 的用途）。

把 `priority` 当调度输入还有一层风险：它是 AI 打的分，而 v2 那套调度算法之所以从未
运行过一次，病根正是「拿 AI 手写的业务字段当机械判据」（见 §4）。同一个坑不要踩第
二次——派发顺序就按 id 顺序走，够了。

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

**一条 `init` 命令搞定全部**：建父仓工作区 → 记住源 worktree → 全量递归供给所有
submodule 层（含嵌套）→ 自校验。不要自己先 `git worktree add` 再单独调供给——
`init` 的落点是它自己算的，手动建的目录它认不了。

```bash
ROOT="$(git -C . rev-parse --show-toplevel)"
WT_SUPPLY="$(find ~/.claude/plugins/cache -maxdepth 6 \
  -path '*/task-keeper/*/skills/tk-worktree/scripts/wt_supply.py' 2>/dev/null | head -1)"
python3 "$WT_SUPPLY" init --source "$ROOT" --id DBG-017
WT="$ROOT/.keeper/worktrees/DBG-017"   # init 把落点固定算在 <source>/.keeper/worktrees/<id>/，分支 fix/DBG-017
```

**落点不可配**，`--worktree` 之类的参数在 `init` 上不存在。核心原因是很多工具链
（hook、状态注入、路径识别）靠 **cwd 的路径字面量**反推「当前处于哪个工作区」——
目标 worktree 落在源 worktree **内部**时，它的绝对路径天然包含源 worktree 的完整
路径前缀，这类识别全部照常工作；落到外部（比如与源平级的目录）会被静默判成另一个
无关工作区，没有任何报错。一个真实例子：某交付框架的路径识别常量是 `MARKER =
'/.sdlc/worktrees/'`（`scripts/lib/path-resolve.js:18`）+ slug 白名单（同文件
`:27` 的 `isValidSlug`，只认 `^D-\d+` / `^hotfix-` 开头），fixer worktree 若直接
落到 `.sdlc/worktrees/DBG-021`，MARKER 命中但 slug 校验不认，一整串依赖 cwd 判断
的 hook 集体失准；落在源 worktree 内部的 `.keeper/worktrees/DBG-021` 则前缀完整
保留、识别不受任何影响。**这条约束的通用原理是「宿主工具链靠 cwd 路径字面量识别
工作区」，不是这一个交付框架独有的毛病**——任何靠 cwd 前缀判断上下文的工具链都有
同样的脆弱性，落点必须在源 worktree 内部这条要求因此具有普遍性。

`init` 是**幂等**的：目标已存在且分支一致就跳过创建、直接续跑供给。自校验没全绿时
退出码 `2`，**已建出的部分刻意不回滚**（保留现场排查），修掉根因后重跑同一条命令即可。
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
python3 "$WT_SUPPLY" explain-scope --worktree "$WT" --from-triage "$ROOT/.keeper/debug/issues/DBG-017.md"
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
  结构这类走这条：`Agent` 多传 `name`（必须带模型档次前缀）与
  `run_in_background: true`，并在 prompt 里加一段交互纪律，让它在真正卡住时
  用 `SendMessage` 问 `debug-keeper`，而不是自己拍板续做。

**为什么这样设计（实测支撑）**：

1. 交互式 subagent → keeper 的 `SendMessage` 实测送达；keeper 回复后，它能答出
   等待前记住的口令，证明 transcript 完整保留、上下文连续——被唤醒后不是
   「从零开始」，而是接着上次的状态往下走。
2. `SendMessage` 返回值原文是 `Agent "<name>" had no active task; resumed
   from transcript in the background with your message.`——说明该 subagent
   发完问题后**任务已终结、不占并发槽**，是「结束 + 被消息唤醒」而非「挂起
   等待」。所以**多个 fixer 同时挂着问题等 keeper 不会挤占 §4 末尾的并发上限**
   ——这条改变了「同时在飞最多 5 个」的计数口径：正在等待答复的
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
  description: "[sonnet] 修 DBG-017 样式对齐",
  model: "sonnet",
  prompt: "【目标】修 DBG-017。
           【上下文】你的工作区是 <worktree 绝对路径>。所有文件操作用该前缀下的
            绝对路径，git 操作用 `git -C <worktree 绝对路径>`。**不要 cd**。
            issue 全文见 <worktree>/.keeper/debug/issues/DBG-017.md，先读它。
            截图（如有）：<绝对路径>，动手前先 Read。
           【约束】禁止修改 .keeper/debug/issues/ 与 .keeper/debug/index.md——队列
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
           【期望输出】把结论写进 <worktree>/.keeper/debug/receipts/DBG-017.md，
            包含：改了哪些文件（逐个列路径）/ 关键决策（为什么这样做、放弃了什么）/
            阻塞点 / 需要 debug-keeper 跟进的事项。同时在回执正文里返回同样内容。
            外加一段**逐层 commit 清单**：每层给出「层路径 + commit 短 hash +
            commit message」，以及该层 `git status --short` 的实际输出（应为空）。
            缺这一段的回执一律视为未完成、会被打回。"
)
```

#### medium / hard 档模板：交互式 subagent

```
Agent(
  subagent_type: "general-purpose",
  name: "sonnet-DBG-024",
  description: "[sonnet] 修 DBG-024 序列模型分类归属",
  model: "sonnet",
  run_in_background: true,
  prompt: "【目标】修 DBG-024。
           【上下文】你的工作区是 <worktree 绝对路径>。所有文件操作用该前缀下的
            绝对路径，git 操作用 `git -C <worktree 绝对路径>`。**不要 cd**。
            issue 全文见 <worktree>/.keeper/debug/issues/DBG-024.md，先读它。
            截图（如有）：<绝对路径>，动手前先 Read。
           【约束】禁止修改 .keeper/debug/issues/ 与 .keeper/debug/index.md——队列
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
            把选项和你的倾向发给 `debug-keeper`（不是 `main`——你是第 3 层，
            debug-keeper 是第 2 层，只有 debug-keeper 判断这个歧义超出它自己
            权限时才会再走 §12 待拍板协议转交给用户），等它拍板。等待期间你会被
            结束，它答复后你会从 transcript 被唤醒继续，上下文不会丢。
           【期望输出】把结论写进 <worktree>/.keeper/debug/receipts/DBG-024.md，
            包含：改了哪些文件（逐个列路径）/ 关键决策（为什么这样做、放弃了什么）/
            阻塞点 / 需要 debug-keeper 跟进的事项。同时在回执正文里返回同样内容。
            外加一段**逐层 commit 清单**：每层给出「层路径 + commit 短 hash +
            commit message」，以及该层 `git status --short` 的实际输出（应为空）。
            缺这一段的回执一律视为未完成、会被打回。"
)
```

两版模板都保留「禁止修改 `.keeper/debug/issues/` 与 `.keeper/debug/index.md`」
「改完不要自己重启本地服务」「回执写进 `<worktree>/.keeper/debug/receipts/
DBG-NNN.md`」这些既有约束——两条轨道都要遵守，只是 medium/hard 版多了 `name`
（addressing 用，缺了 `SendMessage({to: name})` 唤醒不到它）、`run_in_background:
true`、交互纪律那一段，以及「等拍板前也要先 commit」这半句。

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

`receipts/DBG-NNN.md` 与回执正文写同样的内容是刻意冗余：回执正文进 debug-keeper
上下文供当场判断，`receipts/` 文件随 commit 进入所在 worktree 的分支供合并前对账
与日后回溯（注意：这份文件本身仍在 `.keeper/` 下不入库，「随 commit」指的是它作为
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
   本轮最多同时在飞 5 个 fixer（见下一小节），如果都指向同一份 profile，Chrome
   的 profile 锁会让并发实例互相冲突、报「profile 正被另一进程占用」之类的错误。
3. **只能看，不能替代运行时验证**：这次确认只用于「改代码前弄清楚现象」，不能
   当成「改完之后已经验证过」——修复是否真的生效，仍然只由本轮全部 issue 合并
   回主分支后 debug-keeper 的统一实测（§6「合并后统一实测」）来判定。

### 模型分层

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

同时在飞的 fixer **最多 5 个**（2026-07-30 Human 立规：一批最多同时修复 5 个
bug）。约束不只来自文件冲突（worktree 已解决）与审阅带宽（5 个回执同时回来时，
逐个核对 diff、判断有没有偏离诉求、决定哪些能合并，这件事本身有上限，超过就会
开始「看着像对的就 accept」），也来自上一小节「修复前比对确认」新增的 headless
`agent-browser` 并发限制——5 个是这两条约束共同定死的硬上限，不要因为审阅带宽
还有余量就突破它。

**正在等待答复的交互式 subagent 不占这个额度**——上一节已给出实测依据
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

设 `D` = git 实际改动文件集，`R` = `receipts/DBG-NNN.md` 声称改动的文件集：

```bash
WT="$ROOT/.keeper/worktrees/DBG-017"
SRC_BRANCH="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"   # 源 worktree 当前分支
git -C "$WT" diff --stat "$SRC_BRANCH"...HEAD   # 得到 D 与行数
cat "$WT/.keeper/debug/receipts/DBG-017.md"      # 得到 R 与声称的量级
```

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

`.keeper/debug/` 下的文件在两侧都豁免——fixer 写自己的 `receipts/DBG-017.md` 是规定
动作，把它算成幽灵改动会让每次对账都不过。

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
拦下（deny，命中路径含 `.keeper/worktrees/` 即触发，见该 hook 与
`lib/debug_worktree_push_guard.py` 的模块头注释）；debug-keeper 自己推主分支的
push 不在这个机械覆盖范围内（该 hook 只拦截目标路径落在 `.keeper/worktrees/` 下的
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

`status: done` 的 issue 文件**这一轮先留在 `issues/` 目录不动，等交付收官再统一
归档**（见下一小节「归档」）。

v2 有个 `archive.yaml` 归档机制，v3 曾一度取消它：done 的文件本来就不进上下文
（`index.md` 只列一行 id 链接），移动它会让 `next_id` 的派生逻辑失去 id 历史、
造成编号重用——这是真实风险，不是臆测：`next_id` 当时的实现只扫 `issues/`
目录的文件名，一旦 done 文件被移出这个目录，它的编号就会被误判成「没用过」，
下一条新 bug 可能拿到同一个编号，两条不同的 bug 共用一个 id、分别躺在两个
目录里。

归档功能重新做回来，但**形态不同、不会重犯这个坑**：不是 v2 那种
需要人工维护的 `archive.yaml` 索引文件，而是「按交付批次的目录搬迁
（`shutil.move`）+ `next_id` 归档感知」的组合——`next_id`（`hooks/lib/
queue_files.py`）现在同时扫 `issues/` 目录**与** `archive/**/issues/DBG-*.md`
两处的文件名再取最大值+1，只看文件名不解析 frontmatter（即使归档文件的
frontmatter 损坏，编号也仍然计入历史）。所以归档之后旧编号不会被回收：
「移动 done 文件」与「id 历史完整」这两件事这次是同时满足的，不再是二选一。
**用 `shutil.move` 而不是 `git mv`**——`.keeper/` 整树不入库，`issues/DBG-*.md`
从未被 git 跟踪过，`git mv` 对未跟踪文件必然报 `fatal: not under version
control`，归档只能是纯文件系统操作。

### 归档：交付收官后把 done 条目搬进 archive/

`issues/` 目录会被历史上已经 done 的条目越撑越大——虽然 `index.md` 的 done
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
天然带这一段；fixer 自己的 `.keeper/worktrees/DBG-*` 不会走到这里，归档由 keeper
在真身队列上执行）；取不到时退回当前 git 分支名清洗后使用；`--auto` 模式固定用
`auto-<YYYYMMDD>`（当天日期）；都取不到就要求显式传 `--batch <名字>`，不会静默
拼一个可能错的名字。`--queue chore` 可以对 chore 队列跑同一套归档，但那是
`tk-chore` 的事，不在本文档范围内。

**安全边界**：只搬 `status: done` 的条目，`open` 的绝不碰；`worktrees/` 与
`index.md` 绝不碰（前者是未入库的临时产物，后者由 hook 重算）；某条 done issue
仍存在对应的 `worktrees/DBG-NNN/` 时会被跳过并给出警告——那说明 worktree 还没
清理干净，可能还有 fixer 未提交的产物，此时不该把这条 issue 归档走。脚本用
`shutil.move` 而不是普通移动或 `git mv`，失败时（比如目标已存在）fail-loud 报出来
并跳过该条，不中断整批。搬迁完不会自动做任何多余动作——`.keeper/` 本就不入库，
不存在「是否 commit 这次归档」的问题。

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
