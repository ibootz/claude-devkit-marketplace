# Working Discipline

一个纯 hook 插件，用三种方式把「AI 工作纪律」落到 Claude Code 上：

1. **常驻注入**：每轮往主会话、以及每次子代理启动时的 context 里，塞入一份可审计、可复用的行为准则
2. **硬拦截**（`PreToolUse` deny）：派发 subagent 时命名/档位/回执/截图不合规、写 `.md` 前没声明受众判定、污染 cwd 的独立 `cd`、缺 `--headed`/`--profile` 的 `agent-browser` 启动、非 ASCII 路径探测命令挂 `2>/dev/null`；以及写入完成后（`PostToolUse`）拦超 1000 行源码文件、超 200 行 CLAUDE.md
3. **条件注入**（`additionalContext`）：只在真的执行了外部系统写操作之后才讲回读核验要求，只在真的用中文路径检索时才讲 NFC/NFD 规避法

零 skill、零命令、零子代理，装了就生效。不修改用户文件（拦截类 hook 只阻断"继续往下走"，不撤销已完成的写入），无副作用。

### 核心设计原则：常驻 vs 按需，别错配

2.0.0 是一次大幅瘦身：主会话每轮注入从实测 **13632 字符压到约 5900**（-57%）。起因是一个反直觉的观察——**注入的规则越多，AI 的整体遵从度反而越低**，连那些写得很清楚的规则也开始被跳过。

根因不是规则写得不好，而是**常驻与按需错配**。原注入里有一大半属于「只在某个具体工具调用时刻才有用」的细则：写操作后怎么回读、派发时 `description` 该长什么样、md 的三类受众各查什么、NFC/NFD 怎么绕。它们每一轮都在跟真正只能靠自觉的语义规则（求真、思维模式、等齐再总结）抢同一份注意力预算。

所以 2.0.0 的判据是：**一条规则若能被机械判定，就不该常驻**。它有三档去处，按优先级——

| 档 | 机制 | 适用 | 成本特征 |
|---|---|---|---|
| ① 硬拦截 | `PreToolUse` 的 `permissionDecision: "deny"`，`permissionDecisionReason` **是给 Claude 看的**（官方文档明确） | 判据 100% 机械（字段缺失、前缀不符、字符串是否出现） | **做对时零开销**，只有做错才付细则的 token |
| ② 条件注入 | `PreToolUse`/`PostToolUse` 的 `hookSpecificOutput.additionalContext` | 判据机械但不该阻断（提醒性质），或时机点比内容更重要 | 只在触发时付费，且同轮去重 |
| ③ 常驻注入 | `UserPromptSubmit` / `SubagentStart` | **只能靠自觉**的语义规则：求真、表达约束、思维模式、协作节奏 | 每轮全额 |

留在常驻里的每一条，都是因为它无法被机械判定——这也是判断某条规则该不该继续常驻的唯一标准。反过来，把已经硬化的规则再留一份完整副本在常驻里，是纯粹的浪费：AI 做对时白付，做错时 hook 会原样给出。所以下沉的章节在常驻里只剩一行索引（第六章 `SECTION_HOOK_ENFORCED`，约 680 字符），告诉 AI「这些有硬门禁，别在这儿花注意力」。

---

## 什么时候用

- 想让 Claude 的行为在长会话、多 agent 协作里更规整、更可预测
- 被 AI 独立 `cd /tmp` 之后所有相对路径失准坑过
- 团队或个人想固化一套「工作纪律基线」，任何项目都能开着

## 什么时候不用

- 项目里已有更严格的 `CLAUDE.md`，且不希望被通用纪律覆盖
- 只是短会话、单文件微改，不想付出每轮注入的 token 成本

---

## 一、注入：主会话与子代理各注入什么

| 维度 | 关键约束 | 主会话 | 子代理 |
|------|---------|:---:|:---:|
| 一、上下文纪律 | 精确路径读文件、子代理优先、bash 输出限流、macOS 中文路径「空结果不得判无」（NFC/NFD 细则已下沉第九章） | ✅ | ✅ |
| 二、子代理协作 | 在飞≤16（靠自记账盘点，明确禁用 `TaskList` 统计——它是任务板不是在飞 agent 列表）、嵌套≤2、共享骨架文件、结构化回执 | ✅ | ✅ |
| 三、表达约束 | 关键对象点名、待确认四要素、行号引用、简体中文、列表编号 | ✅ | ✅ |
| 四、思维模式 | 举一反三 / 整体 / 第一性 / 逆向 / 自查自纠 / 读者视角 / 写 md 前受众分辨（细则已下沉第七章，此处只剩一行） | ✅ | — |
| 五、Agent 派发 | 5.1 `subagent_type` 类型选择、5.2 四档 model 判定标尺、5.3 调用范式（并发发同一条消息里）、5.4 派发命名要点索引、5.5 多 subagent 并发时等齐再总结（收执时机·仅主会话适用·等齐判据是各 agent 的完成通知到齐而非查 `TaskList`·防主对话上下文膨胀·让用户一次拍板省切换成本） | ✅ | 仅 5.4 |
| 六、hook 已硬化清单 | 一份索引：哪些规则由 hook 在时机点强制、被拦时会拿到什么。**不复述细则** | ✅ | ✅ |

子代理版带一~三节、五节的 5.4 派发命名规范（**完整版**）、六节索引。四节与五节其余部分主要是指导父代理如何选 `subagent_type` × `model`，对子代理自身价值低，故省 token 略去。

**外部写操作授权（原第六章 dws）已从本插件移出**（2.0.0）：钉钉 dws CLI 的写授权改由 `radnove-core` 插件的 `hooks/pre-tool-use-dws-write.sh` 承担，`PreToolUse` 命中写子命令时输出 `permissionDecision: "ask"`，把「须获用户当次明确许可」这个语义要求变成 harness 强制的确认弹窗——比每轮注入 918 字符的自觉约束强得多。radnove-core 的 `user-prompt-submit.sh` 里还保留一条语义兜底，删掉本插件这章不会留下空档。

**5.4 为什么在子代理版保留完整版、主会话只留索引**：这是一处**有意的例外**。第 1 层子代理可以再派第 2 层（受二节的嵌套上限约束），派发时同样要给 `name` / `description`，而第六章的 `agent-dispatch` 硬门禁对**子代理发起的** `Agent` 调用一样生效。但两者处境不同——主会话每轮注入，被拦一次就学会了，索引足够；子代理**只在启动时注入一次**、且更可能对规范一无所知，被拦后只能靠 deny reason 反推。所以主会话走「索引 + 硬门禁」，子代理付这 2.5k 字符换「一次就写对」。章节编号与主版严格一致（子代理版为一、二、三、五、六，缺四），同一条规则不出现两套编号。

> 完整注入文本见 `hooks/working-discipline.js` 里的 `SECTION_*` 数组。实测体积：主会话 6845 字符，子代理 6854 字符。

### 派发命名规范：为什么禁止把 prompt 灌进 `description`（注入文本 5.4 节）

**事故来源（2026-07-25）**：用户截图的在飞 agent 面板上，5 个子代理是这样显示的——

```text
> ● main
  ○ ontology-drain      你是第 1 层子代理（orch...
  ○ verdict-part1       你是第 1 层子代理，可派...
  ○ verdict-part2       你是第 1 层子代理，可派...
  ○ general-purpose   [sonnet] 映射 16 个 spe...
  ○ verdict-part3      你是第 1 层子代理，可派...
```

面板左列显示 `Agent` 工具的 `name`（未指定 `name` 时回落显示 `subagent_type`），右列显示 `description`。这一屏同时暴露三个问题：

1. `ontology-drain` / `verdict-part1` / `verdict-part2` / `verdict-part3` 四个 `name` 都不带模型档次前缀——用户看不出这批在飞任务烧的是 `haiku` 还是 `opus`，成本与"这个任务值不值得上高档模型"无从评估
2. 这四个的右列全是 `prompt` 原文的开头「你是第 1 层子代理，可派…」——一方面把内部提示词（角色设定句、嵌套层级约束这类纪律条款）暴露到 UI 上，另一方面四行描述文字完全同质，面板彻底失去"谁在做什么"的信息量
3. 唯一合规的 `[sonnet] 映射 16 个 spe…` 那行反过来没给 `name`，左列回落成裸的 `general-purpose`——一旦同批并发多个 `general-purpose`，左列同样退化成若干行相同文字

对应的注入规则（子代理版 `SECTION_NAMING` 的 5.4 节完整版；主会话 `SECTION_DISPATCH` 5.4 只留要点索引）分四条：`name` 必填、同会话内不重名、格式 `模型名-任务语义`（`name` 受正则 `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` 约束，只能写 ASCII 字母数字与 `-` `_`，中文和方括号会被直接拒绝，这也是 `name` 用连字符前缀而 `description` 用方括号前缀的原因）；`description` 必填、`[模型名]` 前缀 + 3-5 词任务摘要，`prompt` 与 `description` **禁止共用同一段文字**（`prompt` 给子代理读，长、含约束与上下文；`description` 给面板显示，短、只讲任务是什么）；同批并发的名字必须互相可辨，光加数字后缀不算合格（`verdict-part1/2/3` 应改成把分片依据写进名字的 `sonnet-verdict-spec-01-05` 这类，或在 `description` 里点明范围 `[sonnet] 判定 spec 01-05`）；`Workflow` 的 `meta.name` / `meta.description` / `meta.phases[].title` / `meta.phases[].detail` / `agent(prompt, {label})` 的 `label` 同规，其中 `meta.description` 会出现在权限确认弹窗里，粘 prompt 等于让用户在弹窗里读一段内部指令。

#### 「面板显示提示词」的成因：字段抄错，还是字段留空后的 UI 回落？

一个自然的怀疑是：会不会是因为**子代理压根没法命名**，Claude Code 才只能拿 prompt 第一行凑一个显示名？据工具契约核对，答案是**能命名，且两条成因都存在**：

- **能命名（已核实）**：`Agent` 工具确实有 `name` 参数，受正则 `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` 约束，文档职责是「Makes it addressable via `SendMessage({to: name})`」——用于给长期在飞的 subagent / teammate 一个可寻址的稳定标识。截图左列出现的 `ontology-drain` / `verdict-part1` 本身就是命名生效的证据：它们不是任何已注册的 `subagent_type`，只可能是当次传入的 `name`。
- **成因 a：把 prompt 原文抄进了显示字段**。`Agent` 工具的 `description` 是 **required** 字段（schema 里 `required: ["description", "prompt"]`），不可能因为"没给值"而被系统拿 prompt 顶替——所以经 `Agent` 工具派发的子代理，右列出现 prompt 文字只能是 `description` 被主动填成了 prompt 开头。
- **成因 b：可选的显示字段留空，UI 回落到 prompt 摘要**。`Workflow` 的 `agent(prompt, {label})` 里 `label` 是**可选**参数，文档原文写的是「`opts.label` **overrides** the display label」——`override`（覆盖）一词意味着不传 `label` 时存在一个系统默认显示名，而这个默认名极可能就是 prompt 的开头截断。

第三条属于**依据文档措辞的推断，未做实测确认**（要确证需跑一个最小 workflow，一个 `agent()` 不给 `label`、一个给 `label`，对比 `/workflows` 进度树的显示）。因此 5.4 节的规则不去赌单一成因，而是两条都堵：显示字段禁止与 `prompt` 共用文字（防 a），同时把所有**可选**的显示字段一律当必填处理、显式给值（防 b）。

另外提醒一处易混：`TaskList` 工具返回的是**任务板**字段（`id` / `subject` / `status` / `owner` / `blockedBy`），与上面这张 agent 面板不是同一个数据源，`TaskList` 里并不存在 `name` / `subagent_type` / `model` 字段，也**不能**用来统计在飞子代理数（详见下方「深入话题 → 「在飞≤16」和「嵌套≤2」是纪律软约束」，1.10.1 修掉了旧规则里这处误用）。

1.11.0 起这一节**有了配套硬门禁**，2.0.0 起该门禁已并入 `hooks/guards/agent-dispatch.js`：在 `PreToolUse` 拦 `Agent` 工具调用，违规即 `deny` 并把 finding 回灌给 AI，详见下方「六、拦截：`agent-dispatch`」。注入纪律负责"让 AI 知道该怎么命名"，硬门禁负责"AI 没照做时拦下来"，两者配套——这也是主会话敢把这一节压成索引的前提。

## 二、拦截：`block-cd` 挡住污染 cwd 的独立 `cd`

Bash 工具的 cwd 在多次调用之间**持久保留**。AI 中间执行一次 `cd /tmp`，后续所有相对路径操作都会失准——排查半天才发现是 cwd 被静默改掉了。

`block-cd` 在 `PreToolUse` 里扫描每条 Bash 命令：

- **阻断**（exit 2）：命令链里存在会真正改动 cwd 的独立 `cd`，stderr 输出改写指引
- **放行**（exit 0）：
  - 子 shell：`(cd /path && cmd)`，cwd 不回流父进程
  - 命令替换：`$(cd /path && pwd)`、`` `cd /path && pwd` ``
  - 字符串内的 `cd`：`echo "cd /tmp"`、`git commit -m "cd fix"`
  - **no-op cd**：目标解析后等于当前 cwd（`cd .`、`cd ./`、`cd <当前目录绝对路径>`）

**2.0.0 的改动**：拦截时的 stderr 从约 1500 字符压到 130 字符。原文里那段 2026-07-20 跨插件误伤事故的完整复盘（就是下面这一节）每次拦截都被灌进上下文——**这本身就是本次要治的"注意力抢占"的一个实例**，而且是最讽刺的一种：一个用来纠正行为的提示，自己占掉了比被纠正的行为更多的注意力。复盘搬进了 `block-cd.js` 的文件头注释（给维护者读），stderr 只留「用绝对路径 / 用子 shell / git 用 `git -C`」三条处置加违规片段回显。命令解析逻辑也抽到了 `hooks/lib/shell-parse.js` 共享（原先 `block-cd.js` 与 `agent-browser-launch.js` 各有一份完全相同的 `splitSegments` 实现）。

**已知误报**：shell 函数定义 `cd() { ...; }` 会被判成独立 `cd`——tokenizer 只看到段首的 `cd` token，不区分「调用」与「定义」。真实触发过一次（2026-07-26 本插件自身的开发会话）。这类写法本就罕见且没有必要，未做特判：加一条「后跟 `()` 则跳过」的规则会让解析器为一个近乎不存在的场景变复杂，而绕开的成本只是删掉那行。

### Known Limitation：跨插件 cd 探测差异

`block-cd` 只保证"AI 自己的 cwd 不被污染"，但它**不能**保证其他插件对同一条命令的 cwd 探测逻辑与 AI 实际使用的语法兼容——这是一个跨插件的已知局限，遇到时不要去改对方插件的探测逻辑，改 AI 自己发出的命令语法即可规避。

**事故来源（2026-07-20，D-001-feat-job-sequence-model 会话）**：上一轮 subagent 在 commit `7b88241` 之后要把改动 push 到 `claude-devkit-marketplace`（一个与当前项目完全无关的第三方仓库），用的命令是 `(cd /Users/zhangq/Workspace/mine/claude-devkit-marketplace && git push origin main)`——这条命令本身完全合法，`block-cd` 也正常放行（子 shell 语法，cwd 不回流父进程）。但推送被同时装着的 **sdlc 插件**的 `hooks/ontology-push-guard.js` 拦截，报错「BLOCKED: ontology 正向同步未收口 for D-001-feat-job-sequence-model」——这条错误信息里提到的 delivery 分支跟 `claude-devkit-marketplace` 毫无关系，是一次跨仓库误伤。

追下去发现根因在 sdlc 插件的 `hooks/lib/worktree-utils.js:317-345` 的 `resolveGitCwd()` 函数：它需要判定"这条 git 命令实际作用于哪个仓库"，用的识别手段是正则 `/^cd\s+.../` 匹配命令字符串**开头**的 `cd` 前缀（第 328-342 行同时显式支持 `git -C <path>` 这种全局选项形式）。`block-cd` 教 AI 用的子 shell 语法 `(cd /path && cmd)` 带括号、不以 `cd` 开头，那个正则天然匹配不上；`resolveGitCwd()` 找不到显式 cwd 声明后，fall back 到 `stdinCwd`（也就是当前 Claude 会话所在的 worktree），于是把发往 `claude-devkit-marketplace` 的 push 误认成是 D-001 delivery 分支的 push，触发了一个完全不相关的 ontology 收口门禁。

**推荐用法**：涉及 git 命令时，优先直接用 `git -C <path> <cmd>`，而不是 `(cd /path && git ...)` 子 shell 语法——`-C` 是 git 官方支持的全局选项，语义等价（"以 `<path>` 作为 git 操作的工作目录"），但字面上不含 `cd` token、不进子 shell，`block-cd` 本身放行（天然不触发 `CD_PATTERN`），且各类插件的 cwd 探测正则（如上面这个 sdlc 插件的例子）通常会显式支持 `-C` 这种标准写法。例如：

```bash
git -C /Users/zhangq/Workspace/mine/claude-devkit-marketplace push origin main
git -C /abs/path/to/repo status
git -C /abs/path/to/repo log --oneline -5
```

非 git 命令（如任意 shell 命令）仍然只能走 `(cd /path && cmd)` 子 shell 语法——`-C` 是 git 专有选项，不是通用 shell 机制。本节仅描述现象与规避方法，`block-cd.js` 的核心拦截逻辑（识别独立 `cd`）从未改动。2.0.0 之前，这段事故复盘作为第 5 条指引写在 stderr 里；现在它只保留在 `block-cd.js` 的文件头注释和本节中，stderr 只剩一句「git 命令用 `git -C <path>`」。

---

## 三、拦截：`max-source-lines` 挡住超 1000 行的单一源码文件

单一源码文件行数超过硬阈值是"职责过大"的信号——该文件大概率在做不止一件事，继续往里堆代码只会让可读性、可测试性、review 成本一起变差。这条规范只管"行数"这一个维度，不做语法/风格检查，交给 linter 去做。

`max-source-lines` 在 `PostToolUse` 里检查每次 Write / Edit 落盘后的文件：

- **触发时机**：Write / Edit 工具写入完成之后（文件已落盘，检查的是落盘后的真实内容，不是本次 diff 的增量行数）
- **命中扩展名**（小写比对）：`.java .js .ts .jsx .tsx .vue .py .go .rs .rb .php .cpp .cc .cxx .c .h .hpp .cs .kt .swift .m .mm .css .scss .sass .less .sql`——只管源码，`.md .json .yaml .yml .toml .env .lock` 等非源码文件不受此规则约束
- **判定条件**：命中扩展名 AND 总行数（按 `\n` 字面分割，空文件计 0 行）> 1000
- **阻断**（exit 2）：`stderr` 输出 `[L1-BLOCKER] file={相对路径} check=source-max-lines finding="{N} lines exceeds limit 1000"`
- **放行**（exit 0）：扩展名不在源码列表 / 行数 ≤ 1000 / `file_path` 缺失或文件读取失败（基础设施异常不误拦）

注意这是 `PostToolUse` 钩子——文件已经写完，阻断的是"继续往下走"而非撤销这次写入。命中后应当把文件拆分成职责更单一的多个模块，而不是无视提示继续在同一文件里累加代码。

---

## 四、拦截：`claude-md-max-lines` 挡住超 200 行的 CLAUDE.md，并指路怎么拆

这条规范要解决的不是"CLAUDE.md 不许长"，而是"不许靠压缩正文来规避长"。真实事故：某项目的 CLAUDE.md 逼近 200 行阈值后，AI 把原本 3 段独立的踩坑记录（症状 / 根因 / 解法三段式）硬压成 1 段紧凑文字塞进 200 行以内——压缩过程中丢掉了完整因果链、具体的 `file:行号` 引用、以及未来 AI 需要的典型场景与边界场景示例，CLAUDE.md 表面上"合规"了，但作为纪律文档的可用性被严重削弱。正确做法是拆分文档结构：CLAUDE.md 只保留"一览目录 + 短标题 + 相对路径引用"，具体细节各自落成独立文件放进 `.claude/rules/{topic}.md`（不受 200 行限制），CLAUDE.md 里用 markdown 相对链接指过去，比如 `[本机启动纪律](./.claude/rules/local-dev-startup.md)`。

`claude-md-max-lines` 在 `PostToolUse` 里检查每次 Write / Edit 落盘后的文件：

- **触发时机**：Write / Edit 工具写入完成之后
- **命中文件**：`basename` 不区分大小写等于 `claude.md`（`CLAUDE.md` / `claude.md` / `Claude.Md` 均命中），且不限于仓库根——多 CLAUDE.md 项目里子目录下的 CLAUDE.md 同样受此规则约束
- **排除**：路径含 `.claude/rules/` 目录段的 md 文件不受限——这正是拆分后应当落脚的地方，天然可以超过 200 行
- **判定条件**：命中文件 AND 总行数（按 `\n` 字面分割，空文件计 0 行）> 200
- **阻断**（exit 2）：`stderr` 输出 `[L1-BLOCKER] file={相对路径} check=claude-md-max-lines finding="{N} lines exceeds limit 200" hint="拆到 .claude/rules/{topic}.md 用相对链接引用,禁止压缩正文导致约束丢失"`——注意 `hint` 字段明确指路"怎么拆"，不是只报一个数字让 AI 自己瞎猜怎么合规
- **放行**（exit 0）：`basename` 不是 `claude.md` / 路径落在 `.claude/rules/**` 下 / 行数 ≤ 200 / `file_path` 缺失或文件读取失败

同样是 `PostToolUse` 钩子，阻断的是"继续往下走"。命中后正确的应对是把超限段落搬到 `.claude/rules/` 下的新文件、CLAUDE.md 里换成一行链接引用，绝不是把多段内容硬压缩成一段。

---

## 五、拦截：`agent-browser-launch` 挡住 headless 起动 / 缺 profile 起动，指路怎么起可见且能复用登录态的 CFT

**设计理由（--headed 部分）**：AI 会话用 agent-browser 时默认走 headless 模式起 Chrome for Testing（CFT）实例。虽然 CFT 与用户日常 Google Chrome 是两个不同的 app bundle（分别在 `/Users/zhangq/.agent-browser/browsers/chrome-*` 和 `/Applications/Google Chrome.app`），profile 也可以完全隔离，但 headless 模式下**用户视角看不到 AI 在操作什么**——AI 点了哪个按钮、填了什么表单、跳到了哪个 URL、遇到了什么弹窗，全都是黑箱。用户会误以为 AI 没启动实例、或在动自己的 Chrome。真实事故：2026-07-20 D-001 verify 期间 AI 用 headless 起 CFT 复现前端问题，用户看不到窗口质疑"你现在是创建了一个 headless 的 chrome 浏览器实例吗？为啥我看还是在向我使用的 chrome 实例进行权限申请呢"，AI 才发现 --headed 应该是硬要求。

**设计理由（--profile 部分）**：同一 D-001 会话里加了 `--headed` 硬要求之后，暴露出第二个问题——AI 默认用一次性临时 profile 目录（如 `/tmp/ab-spsd-d001-profile`）起 CFT，profile 目录里没有任何登录态，导致**每次会话都要在浏览器里重新登录一遍业务系统**（手动登录拿 token 再注入 URL），浪费大量时间。用户拍板方案：硬要求 `--profile`（或等价的 `AGENT_BROWSER_PROFILE` 环境变量），引导 AI 复用一个用户在日常 Chrome 里专门建立、一次性登录好业务系统的 "AI Testing" profile 目录（与用户日常用的 `Default` profile 物理隔离，不会互相抢 `SingletonLock`），登录态跨会话持久化；纯隔离测试场景仍可以用 `--profile "$(mktemp -d)"` 之类的独立临时目录满足这条硬性要求（不复用登录态，但也不违反规则）。具体如何创建与使用 "AI Testing" profile 见本节末尾子章节。

这条规范的原则是"AI 的自动化操作对用户可见，不做黑箱；且默认应该复用登录态，不强迫用户反复登录"。

`agent-browser-launch`（原名 `agent-browser-headed`，2026-07-20 因职责扩展为同时管 `--headed` 与 `--profile` 而改名）在 `PreToolUse` 里扫描每条 Bash 命令：

- 先判定命令里出现 `agent-browser` 或 `npx agent-browser`，且紧跟其后（同一顶层命令片段内，跳过 flag 与 flag 的值）能匹配到一个**启动类子命令**——不是启动类子命令一律放行
- 对匹配到启动类子命令的调用，**以下两条独立检查，命中任意一条就拦截**（两条都缺时，`finding`/`hint` 会把两个问题都列出来）：
  1. 命令整串**缺** `--headed`（`--headed false` 视为显式选择 headless，不算缺）且**不含** `AGENT_BROWSER_HEADED=true` 环境变量前缀
  2. 该 agent-browser 调用**缺** `--profile <值>`（或 `--profile=<值>`，值本身不做路径合法性校验，交给 agent-browser CLI 自己校验）且**不含** `AGENT_BROWSER_PROFILE=<值>` 环境变量前缀

**启动类子命令**（会真正拉起一个新 CFT 实例）：

| 子命令 | 说明 |
|--------|------|
| `open` | 打开新页面/新实例 |
| `connect` | 连接并拉起实例 |
| `chat` | 仅当后面接了 URL 位置参数才算启动；纯 REPL 模式（`chat` 不带参数）不拦 |

**探测/后续操作类子命令一律放行**（即使含 `agent-browser` 也不触发本规则）：只读探测（`skills` `doctor` `install` `upgrade`）、生命周期无关（`close` `mcp` `dashboard` `session` `plugin` `auth` `profiles` `confirm` `deny`）、后续操作类（browser 已启动后的动作，如 `snapshot` `click` `fill` `type` `screenshot` `eval` `network` `tab` 等一整套）。

命中拦截时 `stderr` 输出（示例为两条都缺的情况；只缺一条时 `finding`/`hint` 只列那一条）：

```text
[L1-BLOCKER] tool=Bash check=agent-browser-launch finding="agent-browser open 缺 --headed;起 headless CFT 会让用户看不到 AI 操作过程;缺 --profile;不设置 profile 每次都要在浏览器里重新登录业务系统,无法复用登录态" hint="加 --headed 起可见独立 CFT 窗口(若确实要 headless 显式加 --headed false 或前缀 AGENT_BROWSER_HEADED=true);加 --profile <目录>(复用登录态用专门建的"AI Testing" Chrome profile 目录,纯隔离测试场景可用 --profile "$(mktemp -d)" 独立临时目录满足硬性要求;或前缀 AGENT_BROWSER_PROFILE=<目录>);示例:agent-browser --headed --profile \"/Users/<user>/Library/Application Support/Google/Chrome/Profile 1\" open <args>"
```

**放行场景**：子命令不属于启动类 / `chat` 后没有 URL 位置参数（REPL 模式）/ 命令同时含 `--headed`（或 `AGENT_BROWSER_HEADED=true`）**且**含 `--profile <值>`（或 `AGENT_BROWSER_PROFILE=<值>`）。**注意 1.6.0 版本里的旧放行示例 `agent-browser --headed open https://example.com`（只带 `--headed` 不带 `--profile`）在 1.7.0 起会被拦截**——这是本次改动带来的预期行为变更，不是回归 bug。

正确调用示例：

```bash
agent-browser --headed --profile "/Users/<user>/Library/Application Support/Google/Chrome/Profile 1" open https://example.com
AGENT_BROWSER_HEADED=true AGENT_BROWSER_PROFILE=/tmp/ab-profile agent-browser open https://example.com   # 环境变量放行，等价效果
agent-browser --headed false --profile /tmp/ab-profile open https://example.com   # 显式选择 headless，仍需带 --profile
agent-browser --headed --profile "$(mktemp -d)" open https://example.com          # 纯隔离测试场景，独立临时目录也满足硬性要求
```

### AI Testing profile 创建与使用指南

**为什么需要**：AI 每次用 agent-browser 起 CFT 若用一次性临时 profile 目录（`--profile /tmp/xxx`），目录里没有任何登录态，每次都要在浏览器里重新登录业务系统才能继续测试，浪费大量往返时间。让用户在日常 Chrome 里建一个专用的 "AI Testing" profile，一次性登录好目标业务系统，之后 AI 每次起 CFT 都 `--profile` 指向这同一个目录，登录态（cookie / localStorage）就能跨会话持久化复用，不用每次重新走登录流程。

**一次性设置步骤（用户端操作，AI 不能代做，需要用户本人在日常 Chrome 里手动操作）**：

1. 打开 Google Chrome（用户日常在用的那个，不是 CFT）→ 点右上角头像 → 选"添加"/"Add"→ 输入 profile 名字，比如 `AI Testing`（名字随意，只是 UI 显示名，不影响磁盘路径）→ 完成创建，Chrome 会打开一个新窗口，这个新窗口就是 `AI Testing` profile。
2. 在这个新窗口里手动登录一次目标业务系统（例如某个内部测试环境的域名，具体域名以各项目实际情况为准，此处不写死）。
3. 在同一个 `AI Testing` profile 窗口里（**不是** `Default` profile 窗口）打开 `chrome://version/`，找到 "个人资料路径" / "Profile Path" 字段，复制这个绝对路径。macOS 上通常形如：

   ```text
   /Users/<user>/Library/Application Support/Google/Chrome/Profile 1
   ```

   注意：`AI Testing` 是这个 profile 的 UI 显示名，磁盘上的实际目录名是 `Profile N`（`N` 取决于这是你创建的第几个非 Default profile），两者不是同一个字符串，别搞混。
4. 把这个路径记到项目 `CLAUDE.md` 或个人 memory 里，后续所有 AI 起 CFT 时的 `--profile` 参数都指向它。

**AI 起 CFT 时的调用方式**：

```bash
agent-browser --headed --profile "/Users/<user>/Library/Application Support/Google/Chrome/Profile 1" open "http://localhost:8084/#/"
```

或用环境变量等价替代：

```bash
export AGENT_BROWSER_PROFILE="/Users/<user>/Library/Application Support/Google/Chrome/Profile 1"
agent-browser --headed open "http://localhost:8084/#/"
```

**关键坑警告**：macOS 上，用户日常 Chrome 主实例只要正在运行，它当前打开的那个 profile 目录就会被 `SingletonLock` 独占——如果 CFT 用同一个 profile 目录起，会**强制关掉用户日常 Chrome 或者干脆起不来**。这正是为什么 `AI Testing` **必须是一个与用户日常主力使用的 profile（通常是 `Default`）不同的独立 profile**：用户日常 Chrome 平时停留在 `Default` profile 上，AI 的 CFT 专用 `AI Testing` profile，两者各自持有各自的 `SingletonLock`，互不干扰、可以同时开着。相应地，AI 用 CFT 跑 `AI Testing` profile 期间，用户不要手动把自己的日常 Chrome 窗口切到 `AI Testing` profile，否则会跟 CFT 抢锁。

**豁免场景**：如果 AI 的任务本身就是要做"隔离测试、完全不带任何登录态"（比如测一个匿名可访问的公开页面），不需要复用 `AI Testing` 的登录态，可以用 `--profile /tmp/<随机目录>` 或直接 `--profile "$(mktemp -d)"`——这样起的仍然是一个全新、干净的 profile 目录，同样满足本 hook "必须带 `--profile`" 的硬性要求，只是不复用登录态。不要误以为"任何时候都必须用 `AI Testing` 这一个固定 profile"，具体用哪个 profile 由当次任务性质决定。

---

## 六、拦截：`agent-dispatch` 把派发 subagent 的全部机械要求挡在派发前

**本章是两个 guard 合并的产物（2.0.0）**：1.11.0 引入的 `agent-naming.js` 负责命名与 `model` 的 8 项校验，2.0.0 新增的 `agent-dispatch.js` 负责派发质量的 4 项校验。两者都挂 `PreToolUse` + matcher `Agent`，且有三项重叠（`model` 必填 / `description` 的 `[模型名]` 前缀 / `name` 的 `模型名-` 前缀），不合并会重复拦截、输出两份 finding。合并后 `agent-naming.js` 已删除，全部校验在 `hooks/guards/agent-dispatch.js`。

**触发条件**：`tool_name` 是 `Agent`。注意**不匹配旧工具名 `Task`**——旧名环境下的 `tool_input` 可能压根没有 `name` / `model` 字段，强制校验会造成永久性误拦，fail-open 优于误伤。

### 两层校验，形态不同是有意的

**第一层「命名与 model」多条一并列出**，因为这类问题往往同时出现好几个（缺 `name` + `description` 抄 prompt + 超长），一次报清才能一次改对：

| # | 校验 | 为什么 |
|---|------|--------|
| 1 | `model` 缺失或不在 `haiku`/`sonnet`/`opus`/`fable` | 纪律要求显式指定，禁止默认回落。**这一条命中时额外附完整路由表**帮助选档 |
| 2 | `name` 缺失 | 省略后面板左列只能回落显示裸 `subagent_type`，同批多个无法分辨 |
| 3 | `name` 不以 `{model}-` 开头 | 前缀必须与实际 `model` 一致，不许写不符的档次 |
| 4 | `name` 不满足 `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` | Agent 工具的原生约束，提前拦下来并给清楚提示（写中文会被工具直接拒） |
| 5 | `description` 缺失或不以 `[{model}] ` 开头 | 同上，且方括号内档次要与 `model` 一致 |
| 6 | `description` 正文以角色设定句开头（`你是` / `You are` / `【` / `#` / `作为一名` 等） | 把 prompt 原文抄进 `description` 的高置信特征 |
| 7 | `description` 正文长度 ≥ 20 且正好是 `prompt` 的开头 | 抄袭特征。20 字符门槛用来避免误报——3-5 词摘要与 prompt 开头偶然重合的概率不低，短文本不判 |
| 8 | `description` 正文超过 60 字符 | 纪律要求 3-5 词摘要，超长说明塞了 prompt 内容 |

**第二层「派发质量」取第一个命中**，每条给一段长细则。这类问题一次一个就够，同时倒出多段长文本会重演常驻注入的老问题——**只有第一层全过才进第二层**，命名都没写对时谈档位选择为时过早：

| 校验 | 判定条件 | deny reason 给什么 |
|---|---|---|
| 档位错配 | ① 只读意图 prompt 用了 `general-purpose`；② prompt 含高复杂度信号（安全/并发/竞态/泄漏/性能/根因/架构/一致性）却选 `haiku`；③ `Plan` 类型用 `haiku` | 对应改法 + 完整 `subagent_type × model` 路由表（约 1900 字符，这是路由表唯一的出场时机） |
| 回执要求 | prompt 不含「回执」「改了哪些文件」「阻塞点」任一 | 回执四要件模板 |
| 截图附带 | 本轮用户给过截图，而 prompt 里无任何图片路径 | 说明「子代理无主会话截图记忆、文字转述丢像素细节」+ **自动列出本轮所有图片路径** |
| 写操作传染 | prompt 含外部写意图（`curl -X POST/PUT/PATCH/DELETE`、发布 / 授权 / 建对象 / INSERT 等）却不含「回读」 | 完整回读要求 + 2026-07-26 `orderIndex` 静默丢弃事故 |

**档位错配这条是刻意保守的**。判定「只读」用的是「命中只读意图词 **且** 不含写意图词」，而中文里 `实现` / `测试` / `执行` 这些写意图词同时是常用名词——「定位登录流程**实现**」是纯只读任务，却会命中写意图词表而被放行。这是**有意的 fail-open**：让判定更激进（比如给 `实现` 加名词上下文排除）会把误报引进来，而误报的代价是挡住合法派发，远高于漏掉几个本可以拦的。开发时另外核对过一处潜在冲突：强制要求的回执措辞「改了哪些文件」不会被写意图词表命中（词表里是 `修改` 不是 `改`），否则「必须写回执」和「档位检查」这两条规则会互相抵消。

**两个逃生舱**（档位与截图两类的语义边界无法被正则完全覆盖，硬拦死会挡住合法场景）：prompt 里写 `档位已确认：<理由>` 跳过档位检查；写 `豁免图片：<理由>` 跳过截图检查（对应原纪律明列的豁免：纯后端 5xx/DB/MQ、纯 spec 矛盾、纯 CI 问题）。

**放行场景**：`tool_name` 不是 `Agent` / `subagent_type` 属于豁免名单 / stdin 读取或 JSON 解析失败 / `tool_input` 缺失 / 两层校验全过。

**豁免名单**（`EXEMPT_SUBAGENT_TYPES`）：`fork`、`statusline-setup`、`output-style-setup`。其中 `fork` 是必须豁免的——Agent 工具文档明确写它「always inherit the parent model」，`model` 覆盖会被忽略，强制模型前缀自相矛盾。

**输出通道**：本 guard 输出 JSON `permissionDecision: "deny"`（不是 exit 2）。官方文档明确 `permissionDecisionReason` 是展示给 Claude 的，语义比 exit code 约定更明确。第一层的 reason 沿用本仓库 guard 的 `[L1-BLOCKER] ... finding= hint=` 格式便于统一识别：

```text
[L1-BLOCKER] tool=Agent check=agent-dispatch finding="name="verdict-part1" 缺模型档次前缀;description="你是第 1 层子代理..." 缺 [模型名] 方括号前缀" hint="name 改成 "sonnet-verdict-part1";description 改成 "[sonnet] <3-5 词任务摘要>";完整规范见注入纪律 5.4 节;确需临时关闭本门禁用 AGENT_DISPATCH_GUARD=off"
```

### 误拦风险与总开关

这道门禁**默认开启且全局生效**，需要清楚它的影响面：其他插件或 skill 内部派发 subagent 时（如 `omp` 的强制委派、各类 spec 工作流），若它们不遵守本插件的命名规范，同样会被拦下来。这是**预期行为**——规范要统一才有意义——但如果它挡住了你必须跑的既有工作流，用环境变量关闭：

```bash
AGENT_DISPATCH_GUARD=off   # 大小写不敏感，设为 off 即整条门禁放行
AGENT_NAMING_GUARD=off     # 1.11.0 起沿用的旧名，继续有效
```

想永久关闭就从 `.claude-plugin/plugin.json` 的 `PreToolUse` 里删掉这条 hook 注册；想放宽某类 agent，把它的 `subagent_type` 加进 `agent-dispatch.js` 的 `EXEMPT_SUBAGENT_TYPES`。

### Known Limitation：`Workflow` 内部的 `label` 拦不到

本 hook 只覆盖 `Agent` 工具的直接派发。`Workflow` 脚本内部 `agent(prompt, {label})` 的调用**不经过 `PreToolUse`**（它发生在 workflow 运行时的脚本执行层），因此 `label` 缺失或抄 prompt 都拦不到，只能靠注入纪律 5.4.4 约束。理论上可以拦 `Workflow` 工具本身、对 `script` 字符串做正则提取来校验 `meta.name` 与各 `agent()` 的 `label`，但正则解析 JS 源码的可靠性太低（易误判模板字符串、嵌套括号、注释里的调用），故未实现。

---

## 七、拦截：`md-audience-declaration` 逼出写 md 前的受众判定

`PreToolUse` + matcher `Write|Edit`，目标文件扩展名为 `.md` / `.markdown` 时生效。

原纪律自己就写着「防止 AI 心里想过就跳过」——这句话恰好证明它靠自觉守不住：约 900 字符的三分支准则常驻注入，却仍然经常被跳过。而「是否留过痕」是 100% 机械的字符串检查，所以这条最适合硬化。

- **阻断**：本轮（按 `prompt_id` 界定）assistant 文本里不含「受众判定」字样 → deny，reason 给出完整三分支准则（偏人读 / 偏 AI 读 / 人机混合，各带必检项）
- **放行**：非 md 文件；本轮已声明；**transcript 读不到或解析失败**（基础设施异常不该表现为纪律违规）

**为什么不豁免小改动**：「大改 md」与「小改 md」无法从 `tool_input` 机械区分，而声明本身只要一句话。只改错别字时声明「本次 md 受众判定：<沿用原判定>，理由：仅修正错别字」即可通过——这句话本身也提醒了 AI 别顺手扩大改动范围。

---

## 八、条件注入：`external-write-readback` 在写操作之后才讲回读

`PostToolUse` + matcher `Bash`。

**为什么必须是 `PostToolUse`**：回读的对象是「刚写进去的值」，只有写操作执行完才存在；注入时机恰好落在「AI 刚拿到写接口的成功响应、正要判定这步成功」的那一刻，比提前一整轮注入更有效。官方文档明确 `PostToolUse` 的 exit code 2 **不能阻断**（工具已执行完），所以本 hook 只注入、不拦截——在这里拦截也没有意义。

两档强度，避免制造新的上下文膨胀：

- **外部系统写**（`curl` 写方法或带 `--data`、`mysql`/`psql` 的 DML、`redis-cli` 写命令、`dbops`/`ymcas`/`dws`/`gh`/`kubectl`/`aws` 等平台 CLI 的写子命令）→ 注入**完整**回读要求（约 1030 字符）：三类静默失败（静默忽略字段 / 静默降级 / 部分成功）、判定基线（写 N 个回读 N 次、必须走读接口、层级关系从父对象侧确认）、2026-07-26 `orderIndex: 15` 返回 204 却存成默认值 `1` 的真实事故
- **Bash 本地写**（`sed -i`、重定向、`tee`、`mv`/`cp`/`rm`）→ 注入**精简**提醒（约 160 字符）：`Write`/`Edit` 有 harness 的落盘保证，Bash 写入没有，继续之前先 `Read` 或 `git diff` 确认。这类命令频率极高，若也注入 1000+ 字符就会造出新的膨胀

`curl -X GET/HEAD/OPTIONS` 显式只读方法一律放行。**同一轮内同一档位只注入一次**（一轮里连续跑 5 条 curl 写命令是常态，每次都注入同一段长文本会把上下文重新撑大）。

---

## 九、拦截 + 条件注入：`nonascii-path` 管 macOS 中文路径的静默漏检

`PreToolUse` + matcher `Bash`。macOS 下 git 输出的路径是 NFC 归一形态（`core.precomposeunicode`），磁盘上实际文件名则常是 NFD 分解形态——两种形态字节不同、肉眼完全相同。

- **阻断**：探测/统计类命令（`grep`/`rg`/`find`/`ls`/`wc`/`stat`/`git grep` 等）同时满足「命令含非 ASCII 字符」与「挂了 `2>/dev/null`」。这是原纪律明列的禁止项：形态不一致导致的 No such file 报错会被 `2>/dev/null` 吞掉，空结果随即被误读成「确实没有」，错误结论从此一路传递
- **条件注入**：命令含非 ASCII 且用了检索/比对类命令（`grep`/`find`/`diff`/`comm`/`xargs`/`git diff` 等）→ 注入完整规避法（git 单源闭环、`iconv -f UTF-8-MAC -t UTF-8`、非 ASCII 段换 glob 通配）。同一轮只注入一次
- **放行**：命令不含非 ASCII；命令不属于检索/探测类（`git commit -m 修复登录` 这类里的中文是内容不是路径，与 NFC/NFD 无关）

两种处置都要求「命令属于检索/探测类」这个前置条件，把误报压到可接受范围——宁可漏掉少数场景，也不要让每条带中文的命令都被打扰。

---

## 安装

**Claude Code**

```bash
/plugin install working-discipline@claude-devkit-marketplace
```

**Codex CLI**（用户级安装，对所有项目生效）

```bash
node scripts/install-codex.js --plugins=working-discipline --scope=user
```

---

## 工作机制速览

**注入 hook**（`hooks/working-discipline.js`）

```text
UserPromptSubmit（主会话每轮） 或 SubagentStart（子代理启动时）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/working-discipline.js
   ↓  读 stdin 的 hook_event_name 分流：
   ↓    UserPromptSubmit → 一、二、三、四、五（含 5.4 要点索引）、六（hook 硬化清单）
   ↓    SubagentStart    → 一、二、三、5.4 命名规范完整版、六（缺四；缺 5.1-5.3、5.5）
   ↓
stdout 输出 { hookSpecificOutput: { hookEventName, additionalContext } }
   ↓
Claude Code 把 additionalContext 拼进对应 context
（SubagentStart 的注入只进子代理自己的 transcript，不入主会话）
```

**拦截 hook**（`hooks/guards/block-cd.js`）

```text
PreToolUse（Bash 工具调用前）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/guards/block-cd.js
   ↓  读 stdin 的 tool_input.command 与 cwd：
   ↓    剥离子 shell / 命令替换 → 切分顶层片段 → 逐个判定 cd
   ↓    存在会改变 cwd 的独立 cd → exit 2 阻断（stderr 输出改法指引）
   ↓    全部是子 shell cd 或 no-op cd → exit 0 放行
```

**拦截 hook**（`hooks/guards/agent-dispatch.js`）

```text
PreToolUse（Agent 工具调用前）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/guards/agent-dispatch.js
   ↓  读 stdin 的 tool_name / tool_input / transcript_path / prompt_id：
   ↓    AGENT_DISPATCH_GUARD=off 或 AGENT_NAMING_GUARD=off → 放行（总开关）
   ↓    tool_name 不是 Agent → 放行（不匹配旧名 Task，避免永久误拦）
   ↓    subagent_type ∈ {fork, statusline-setup, output-style-setup} → 放行
   ↓  第一层【命名与 model】——聚合所有 finding，一次报清：
   ↓    model 显式且合法 / name 必填·前缀符 model·满足原生正则
   ↓    description 必填·[模型名] 前缀符 model
   ↓    description 正文非 prompt 角色句 / 非 prompt 开头逐字重合 / ≤60 字符
   ↓    有 finding → deny（model 本身非法时额外附完整路由表）
   ↓  第二层【派发质量】——第一层全过才进，取第一个命中：
   ↓    档位错配（只读用 general-purpose / 高复杂度用 haiku / Plan 用 haiku）
   ↓      → deny + 完整 subagent_type × model 路由表   〔逃生舱：prompt 写「档位已确认：…」〕
   ↓    prompt 无回执要求 → deny + 回执四要件模板
   ↓    本轮有截图而 prompt 无图片路径 → deny + 自动列出本轮图片路径
   ↓                                     〔逃生舱：prompt 写「豁免图片：…」〕
   ↓    prompt 含外部写意图而无「回读」 → deny + 完整回读要求
   ↓    全过 → 放行
```

**拦截 hook**（`hooks/guards/md-audience-declaration.js`）

```text
PreToolUse（Write / Edit 工具调用前）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/guards/md-audience-declaration.js
   ↓  读 stdin 的 tool_input.file_path / transcript_path / prompt_id：
   ↓    扩展名不是 .md / .markdown → 放行
   ↓    经 hooks/lib/transcript.js 取本轮 assistant 文本
   ↓      （从后往前找最后一个 promptId == payload.prompt_id 的 user 行，取其后所有行）
   ↓    读不到 / 解析失败 → 放行（基础设施异常不表现为纪律违规）
   ↓    文本含「受众判定」→ 放行
   ↓    不含 → deny + 三分支准则（偏人读 / 偏 AI 读 / 人机混合）
```

**条件注入 hook**（`hooks/guards/external-write-readback.js`）

```text
PostToolUse（Bash 工具执行完成后 —— 此处 exit 2 无法阻断，只能注入）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/guards/external-write-readback.js
   ↓  读 stdin 的 tool_input.command：
   ↓    curl -X GET/HEAD/OPTIONS 等显式只读方法 → 放行
   ↓    命中外部系统写（curl 写方法/--data、SQL DML、redis 写、平台 CLI 写子命令）
   ↓      → additionalContext 注入完整回读要求（约 1030 字符，含 orderIndex 事故）
   ↓    命中本地写（sed -i / tee / 重定向 / mv / cp / rm）
   ↓      → additionalContext 注入精简提醒（约 160 字符）
   ↓    经 hooks/lib/notify-once.js 按 (scope, session_id, prompt_id, 档位) 去重
   ↓      → 同一轮同一档位只注入一次
```

**拦截 + 条件注入 hook**（`hooks/guards/nonascii-path.js`）

```text
PreToolUse（Bash 工具调用前）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/guards/nonascii-path.js
   ↓  读 stdin 的 tool_input.command：
   ↓    命令不含非 ASCII 字符 → 放行
   ↓    探测/统计类命令（grep/rg/find/ls/wc/stat/git grep）且挂 2>/dev/null
   ↓      → deny（空结果会被误读成「确实没有」）
   ↓    检索/比对类命令（grep/find/diff/comm/xargs/git diff）
   ↓      → additionalContext 注入 NFC/NFD 规避法（同轮去重）
   ↓    其余（如 git commit -m 修复登录，中文是内容不是路径）→ 放行
```

**拦截 hook**（`hooks/guards/max-source-lines.js`）

```text
PostToolUse（Write / Edit 工具写入完成后）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/guards/max-source-lines.js
   ↓  读 stdin 的 tool_input.file_path 与 cwd：
   ↓    扩展名不在源码列表 → exit 0 放行
   ↓    读落盘后文件内容，按 \n 分割计数行数
   ↓    行数 > 1000 → exit 2 阻断（stderr 输出 source-max-lines 提示）
   ↓    行数 ≤ 1000 → exit 0 放行
```

**拦截 hook**（`hooks/guards/claude-md-max-lines.js`）

```text
PostToolUse（Write / Edit 工具写入完成后）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/guards/claude-md-max-lines.js
   ↓  读 stdin 的 tool_input.file_path 与 cwd：
   ↓    basename 不是 claude.md（大小写不敏感）→ exit 0 放行
   ↓    路径含 .claude/rules/ 目录段 → exit 0 放行（拆分后的细节页不受限）
   ↓    读落盘后文件内容，按 \n 分割计数行数
   ↓    行数 > 200 → exit 2 阻断（stderr 输出 claude-md-max-lines 提示 + hint 拆分指引）
   ↓    行数 ≤ 200 → exit 0 放行
```

**拦截 hook**（`hooks/guards/agent-browser-launch.js`，原名 `agent-browser-headed.js`）

```text
PreToolUse（Bash 工具调用前）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/guards/agent-browser-launch.js
   ↓  读 stdin 的 tool_input.command：
   ↓    不含 agent-browser → exit 0 放行
   ↓    切分顶层片段 → 定位 agent-browser（或 npx agent-browser）→ 匹配子命令
   ↓    子命令不属于启动类（open/connect/chat） → exit 0 放行
   ↓    chat 子命令且无 URL 位置参数（REPL 模式） → exit 0 放行
   ↓    命令整串缺 --headed（非 --headed false/AGENT_BROWSER_HEADED=true）→ 记一条 finding
   ↓    该调用缺 --profile <值>（非 AGENT_BROWSER_PROFILE=<值>）→ 记一条 finding
   ↓    有 finding → exit 2 阻断（stderr 输出改法指引，两条问题都缺时一并列出）
   ↓    无 finding → exit 0 放行
```

---

## 深入话题

### 「在飞≤16」和「嵌套≤2」是纪律软约束

这两条不是 Claude Code 的硬限制，是靠注入文本让 AI 自觉遵守：

- **在飞≤16**：Claude Code 没有并发数的原生配置，也**没有任何工具能枚举在飞子代理**。规则要求 AI 每次派发前靠**自记账**盘点本会话在飞数（派发时 +1，收到某 agent 的 `<task-notification>` 完成通知或其 `Agent` 工具返回时 -1），把本会话在飞总量控制在 16 以内。

  这里曾有一处错误，1.10.1 修掉：旧版规则文本写的是「用 `TaskList` 统计当前 `status=running` 的在飞子代理数量」，两处都不成立——`TaskList` 读的是**任务板**（字段 `id` / `subject` / `status` / `owner` / `blockedBy`），跟在飞子代理不是同一个数据源；而它的 `status` 枚举只有 `pending` / `in_progress` / `completed` / `deleted`，**根本没有 `running` 这个值**，照字面执行只会拿到一个恒为空的过滤结果，等于把上限约束变成了空转。同批修正的还有第 5.7 节「等齐再总结」的判据：旧文本写「等 `TaskList` 显示本批次全部在飞子代理都到 `completed`」，同样查错了数据源，现改为「本批次每个 agent 各自的完成通知/工具返回都已到齐」。

  另外两点边界要清楚：`TaskOutput` 虽然能按 `task_id` 查后台任务状态，但它已被标记 DEPRECATED，且只接受**单个已知的** `task_id`，无法枚举；能列出全系统在飞任务的入口是用户侧的 `/tasks` 斜杠命令，**AI 无法自行调用**。所以规则同时收窄了口径——自查范围只限本会话自己派发的子代理，禁止 AI 声称统计过"全系统在飞总量"，跨会话口径需请用户用 `/tasks` 核对；长会话 auto-compact 压掉早期派发记录导致记账失准时，按保守口径分批派或请用户报数，不许凭印象估。
- **嵌套≤2**：Claude Code 原生嵌套硬上限是 **5 层且不可配置**，`SubagentStart` 也无法拦截派发行为。所以 2 层限制只能由各层自觉传递——第 1 层子代理在给第 2 层写 prompt 时，须明确写「你是第 2 层子代理，禁止再派任何 subagent」。

### 怎么可靠地界定「本轮」

第七章（md 受众判定）和第六章的截图检查都依赖一个判据：**AI 在本轮说过什么 / 用户在本轮给过什么**。这没法从 `tool_input` 得出，必须回看 `transcript_path` 指向的 JSONL。实现在 `hooks/lib/transcript.js`，2026-07-26 在真实会话文件上实测确认了三件事：

1. **只有 `type=='user'` 的行带 `promptId`**，`assistant` 行的 `promptId` 恒为 `null`。所以不能用「筛出 `promptId == payload.prompt_id` 的所有行」——那样一条 assistant 文本都拿不到。正确做法是**从后往前找最后一个 `promptId` 匹配的 user 行，取它之后的全部行**。
2. **落盘足够及时**。官方文档提到 transcript 是异步写入，但在「AI 刚输出文本 → 同一轮下一次工具调用触发 hook」这个时间尺度上实测无问题（本插件开发时就是这样自测的：先输出受众判定声明，下一次 Bash 调用时已能 grep 到）。
3. `prompt_id` 匹配不上时**降级为「最后一个 user 行之后」**，读文件或 JSON 解析失败则返回 `null`/`[]`，调用方一律放行。宁可漏拦，不可因为读不到 transcript 就误拦——基础设施异常不该表现为纪律违规。

同一个 lib 也用来提取本轮的图片路径（匹配 `image-cache/` 路径与 `.png`/`.jpg`/`.webp`/`.gif` 绝对路径，只看用户侧的行）。

### 为什么有四项机械规则没有下沉

设计时评估过、最终**决定不实现**的四项，它们的注入文本因此仍然常驻：

| 候选 | 本可以怎么做 | 为什么不做 |
|---|---|---|
| 在飞 subagent ≤16 的计数拦截 | `PreToolUse` 拦 `Agent`，用状态文件记账，超 16 则 deny | 状态文件的崩溃残留会造成**永久性误拦**——会话异常退出时计数不归零，下次开会话直接被拦死，而用户很难猜到原因 |
| `Stop` hook 校验输出语言与列表编号 | `Stop` 的 exit 2 可以「阻止停止、让对话继续」，读 transcript 校验 AI 自己的输出 | 误报的代价是**强行多跑一轮**（比 deny 一次工具调用贵得多）；且繁简判定极易误伤引用的繁体原文 |
| 大输出命令 `PreToolUse` 拦截 | 识别 `cat` 大文件、无 `head` 的 `find /` 等 | 误报多，且用户明确要求看全量输出时会碍事——这条本来就有合理的例外 |
| 嵌套深度 ≤2 的记账拦截 | 派发时按父子链累加深度 | **官方 payload 里没有 parent 信息**，父子链只能靠时序推断，并发派发时有竞态；判据本身不可靠就不该做成硬拦截 |

共同的取舍是：**硬拦截的误报成本远高于漏报**。一条规则做成 deny 之前，判据必须机械且几乎无歧义；只要判据要靠推断、状态或时序，就宁可留在常驻注入里靠自觉。第六章那两个逃生舱（`档位已确认：` / `豁免图片：`）是同一个原则的另一种形态——判据大体可靠但边界模糊时，给一条留痕即可通过的出口，而不是硬拦死。

### 与其他插件的关系

- 与 `omp` 插件互补：`omp` 的 `orchestrator-protocol-remind.js` 注入 omp 编排协议（强制委派 omp 子代理），本插件注入通用工作纪律（覆盖 Claude 原生 Agent 工具）——二者可并行启用。
- `block-cd.js` 原本在 `devkit-core`（现已更名 `devkit-tool`），本插件 1.3.0 起迁入此处；`devkit-tool` 自 5.1.0 起不再内置任何 hook。同批删除的 `guard-full-read.js`（大文件全文读取拦截）因与「精确读文件」注入纪律重复，未一并迁入。
- `max-source-lines.js` / `claude-md-max-lines.js` 与另一个插件 `quality-lint` 的 md 200 行拦截是同类思路（`PostToolUse` 拦 Write/Edit、`[L1-BLOCKER]` 输出格式）但各自独立实现——两个插件归属不同、不互相依赖，`quality-lint` 管的是文档质量的通用规则，本插件这两条是「最高宪法」层面单独声明的行数硬约束。
- `agent-browser-launch.js`（原名 `agent-browser-headed.js`）管 `agent-browser` CLI 的两个启动参数（`--headed` 与 `--profile`），不涉及浏览器自动化能力本身；`--profile` 具体指向哪个目录（"AI Testing" 专用 profile 还是临时目录）走各会话的个人 memory / 全局 CLAUDE.md 约定，本插件只负责在缺 `--headed` 或缺 `--profile` 时硬拦，不管值本身是否合法。

---

## 目录结构

```text
plugins/working-discipline/
├── .claude-plugin/plugin.json          # hook 注册（注入 + 拦截 + 条件注入）
├── hooks/
│   ├── working-discipline.js           # UserPromptSubmit / SubagentStart 常驻注入
│   ├── lib/                            # guard 之间共享的工具（2.0.0 新增）
│   │   ├── shell-parse.js              #   命令切分/分词/剥引号剥子 shell（block-cd 与
│   │   │                               #   agent-browser-launch 原先各有一份重复实现）
│   │   ├── transcript.js               #   按 prompt_id 读「本轮」assistant 文本与图片路径
│   │   └── notify-once.js              #   同轮同档位去重，状态文件在 TMPDIR，失败降级为照常注入
│   └── guards/
│       ├── agent-dispatch.js           # PreToolUse 拦截（Agent 派发：第一层命名与 model 聚合报错，
│       │                               #   第二层档位/回执/截图/写传染取首个命中）
│       ├── md-audience-declaration.js  # PreToolUse 拦截（写 .md 前本轮未声明「受众判定」）
│       ├── block-cd.js                 # PreToolUse 拦截（污染 cwd 的独立 cd；git 命令指引 git -C）
│       ├── agent-browser-launch.js     # PreToolUse 拦截（agent-browser 启动缺 --headed 或 --profile）
│       ├── nonascii-path.js            # PreToolUse 拦截 + 条件注入（非 ASCII 路径挂 2>/dev/null；
│       │                               #   检索类命令注入 NFC/NFD 规避法）
│       ├── external-write-readback.js  # PostToolUse 条件注入（外部写→完整回读要求；本地写→精简提醒）
│       ├── max-source-lines.js         # PostToolUse 拦截（单一源码文件超 1000 行）
│       └── claude-md-max-lines.js      # PostToolUse 拦截（CLAUDE.md 超 200 行，指路拆 .claude/rules/）
└── README.md
```

`agent-naming.js`（1.11.0）已在 2.0.0 删除，其 8 项校验并入 `agent-dispatch.js`。

## 自定义

- 增删注入条款 / 切换风格 → 编辑 `hooks/working-discipline.js` 里的 `SECTION_*` 数组，每行是 markdown 一行
- 调整 `cd` 拦截行为（阈值、放行场景、git -C 教育提示文案） → 编辑 `hooks/guards/block-cd.js`
- 调整 agent-browser 启动类子命令 / 白名单子命令 / `--headed`、`--profile` 硬要求 → 编辑 `hooks/guards/agent-browser-launch.js` 里的 `LAUNCH_SUBCOMMANDS` / `ALLOWLIST_SUBCOMMANDS`
- 调整 subagent 派发门禁 → 编辑 `hooks/guards/agent-dispatch.js`：第一层改 `EXEMPT_SUBAGENT_TYPES` / `DESC_BODY_MAX` / `PROMPT_LEAK_PREFIXES` / `LEAK_MATCH_MIN` / `NAME_PATTERN`，第二层改 `ROUTING_TABLE` / `RECEIPT_TEMPLATE` / `READBACK_REQUIREMENT` / `IMAGE_REQUIREMENT` 及各自的判定词表；临时整体关闭用环境变量 `AGENT_DISPATCH_GUARD=off`（旧名 `AGENT_NAMING_GUARD=off` 同样有效）
- 调整 md 受众判定门禁（判定关键词、deny 时给的三分支准则文案） → 编辑 `hooks/guards/md-audience-declaration.js`
- 调整写后回读的触发范围与两档文案 → 编辑 `hooks/guards/external-write-readback.js` 里的 `EXTERNAL_WRITE_PATTERNS` / `LOCAL_WRITE_PATTERNS` / `EXPLICIT_READ_METHOD` / `FULL_READBACK` / `BRIEF_READBACK`
- 调整 NFC/NFD 门禁的命令范围 → 编辑 `hooks/guards/nonascii-path.js` 里的 `PROBE_COMMANDS` / `SEARCH_OR_DIFF_COMMANDS` / `SILENCE_STDERR` / `NFC_NFD_GUIDE`
- 调整源码文件行数阈值 / 扩展名列表 → 编辑 `hooks/guards/max-source-lines.js` 里的 `LINE_LIMIT` / `SOURCE_EXTENSIONS`
- 调整 CLAUDE.md 行数阈值 / 排除目录 → 编辑 `hooks/guards/claude-md-max-lines.js` 里的 `LINE_LIMIT` / `EXCLUDED_SEGMENT_PATTERN`

> 改注入文本时留一句自检：**这条规则能被机械判定吗？** 能，就该做成 guard 而不是加进 `SECTION_*`——否则又会一步步回到「注入越多、遵从度越低」的老路。

---

版本 2.0.0 · 作者 zhangq · MIT
