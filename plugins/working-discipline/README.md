# Working Discipline

一个纯 hook 插件，用两种方式把「AI 工作纪律」落到 Claude Code 上：

1. **注入**：每轮往主会话、以及每次子代理启动时的 context 里，塞入一份可审计、可复用的行为准则
2. **拦截**：Bash 工具执行前硬拦截污染 cwd 的独立 `cd` 命令；Write/Edit 工具写入完成后硬拦截超 1000 行的单一源码文件、超 200 行的 CLAUDE.md

零 skill、零命令、零子代理，装了就生效。不修改用户文件（拦截类 hook 只阻断"继续往下走"，不撤销已完成的写入），无副作用。

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
| 一、上下文纪律 | 精确路径读文件、子代理优先、bash 输出限流、macOS 中文路径防漏检（NFC/NFD） | ✅ | ✅ |
| 二、子代理协作 | 在飞≤16、嵌套≤2、共享骨架文件、结构化回执 | ✅ | ✅ |
| 三、表达约束 | 关键对象点名、待确认四要素、行号引用、简体中文、列表编号 | ✅ | ✅ |
| 四、思维模式 | 举一反三 / 整体 / 第一性 / 逆向 / 自查自纠 / 读者视角 / 写 md 前受众分辨 | ✅ | — |
| 五、Agent 派发 | subagent_type × model 路由表、显式 model、成本意识 | ✅ | — |
| 六、外部写操作授权 | dws 钉钉 CLI 默认只读；写操作（发消息/写删文档/写表格等）须逐批出示内容清单获用户当次明确许可；上游放行不算授权；叫停即冻结 | ✅ | ✅ |

子代理版带一~三、六节。四、五两节主要是指导父代理如何派发子代理，对子代理自身无意义，故省 token 略去；六节必须进子代理版——general-purpose 子代理带 Bash 权限，同样能执行 `dws` 写命令（章节编号与主版一致，故子代理版编号跳过四、五）。

> 完整注入文本见 `hooks/working-discipline.js` 里的 `SECTION_*` 数组。

## 二、拦截：`block-cd` 挡住污染 cwd 的独立 `cd`

Bash 工具的 cwd 在多次调用之间**持久保留**。AI 中间执行一次 `cd /tmp`，后续所有相对路径操作都会失准——排查半天才发现是 cwd 被静默改掉了。

`block-cd` 在 `PreToolUse` 里扫描每条 Bash 命令：

- **阻断**（exit 2）：命令链里存在会真正改动 cwd 的独立 `cd`，stderr 输出改写指引
- **放行**（exit 0）：
  - 子 shell：`(cd /path && cmd)`，cwd 不回流父进程
  - 命令替换：`$(cd /path && pwd)`、`` `cd /path && pwd` ``
  - 字符串内的 `cd`：`echo "cd /tmp"`、`git commit -m "cd fix"`
  - **no-op cd**：目标解析后等于当前 cwd（`cd .`、`cd ./`、`cd <当前目录绝对路径>`）

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

## 五、拦截：`agent-browser-headed` 挡住 headless 起动，指路怎么起可见 CFT

**设计理由**：AI 会话用 agent-browser 时默认走 headless 模式起 Chrome for Testing（CFT）实例。虽然 CFT 与用户日常 Google Chrome 是两个不同的 app bundle（分别在 `/Users/zhangq/.agent-browser/browsers/chrome-*` 和 `/Applications/Google Chrome.app`），profile 也可以完全隔离，但 headless 模式下**用户视角看不到 AI 在操作什么**——AI 点了哪个按钮、填了什么表单、跳到了哪个 URL、遇到了什么弹窗，全都是黑箱。用户会误以为 AI 没启动实例、或在动自己的 Chrome。真实事故：2026-07-20 D-001 verify 期间 AI 用 headless 起 CFT 复现前端问题，用户看不到窗口质疑"你现在是创建了一个 headless 的 chrome 浏览器实例吗？为啥我看还是在向我使用的 chrome 实例进行权限申请呢"，AI 才发现 --headed 应该是硬要求。正确做法是 AI 必须用 `--headed` 起可见独立 CFT 窗口 + 用 `--profile <独立临时目录>` 指定独立 profile 目录，让用户能眼睛看到 AI 每一步操作、随时打断纠正、可视化调试。这条规范的原则是"AI 的自动化操作对用户可见，不做黑箱"。

`agent-browser-headed` 在 `PreToolUse` 里扫描每条 Bash 命令，**同时满足以下三条**才拦截：

- 命令里出现 `agent-browser` 或 `npx agent-browser`，且紧跟其后（同一顶层命令片段内，跳过 flag 与 flag 的值）能匹配到一个**启动类子命令**
- 命令整串**缺** `--headed`（`--headed false` 视为显式选择 headless，不算缺）
- 命令整串**不含** `AGENT_BROWSER_HEADED=true` 环境变量前缀

**启动类子命令**（会真正拉起一个新 CFT 实例）：

| 子命令 | 说明 |
|--------|------|
| `open` | 打开新页面/新实例 |
| `connect` | 连接并拉起实例 |
| `chat` | 仅当后面接了 URL 位置参数才算启动；纯 REPL 模式（`chat` 不带参数）不拦 |

**探测/后续操作类子命令一律放行**（即使含 `agent-browser` 也不触发本规则）：只读探测（`skills` `doctor` `install` `upgrade`）、生命周期无关（`close` `mcp` `dashboard` `session` `plugin` `auth` `profiles` `confirm` `deny`）、后续操作类（browser 已启动后的动作，如 `snapshot` `click` `fill` `type` `screenshot` `eval` `network` `tab` 等一整套）。

命中拦截时 `stderr` 输出：

```text
[L1-BLOCKER] tool=Bash check=agent-browser-headed finding="agent-browser {子命令} 缺 --headed;起 headless CFT 会让用户看不到 AI 操作过程" hint="改用 agent-browser --headed --profile /tmp/ab-<slug>-profile {子命令} <args>,起可见独立 CFT 窗口;若确实要 headless 显式加 --headed false 或前缀 AGENT_BROWSER_HEADED=true"
```

**放行场景**：子命令不属于启动类 / 命令含 `--headed`（含 `--headed false`）/ 命令含 `AGENT_BROWSER_HEADED=true` / `chat` 后没有 URL 位置参数（REPL 模式）。

正确调用示例：

```bash
agent-browser --headed --profile /tmp/ab-dogfood-profile open https://example.com
AGENT_BROWSER_HEADED=true agent-browser open https://example.com   # 环境变量放行，等价效果
agent-browser --headed false open https://example.com              # 显式选择 headless，允许
```

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
   ↓    UserPromptSubmit → 完整纪律（一~六节）
   ↓    SubagentStart    → 精简纪律（一~三、六节）
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

**拦截 hook**（`hooks/guards/agent-browser-headed.js`）

```text
PreToolUse（Bash 工具调用前）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/guards/agent-browser-headed.js
   ↓  读 stdin 的 tool_input.command：
   ↓    不含 agent-browser → exit 0 放行
   ↓    命令整串含 --headed / --headed false / AGENT_BROWSER_HEADED=true → exit 0 放行
   ↓    切分顶层片段 → 定位 agent-browser（或 npx agent-browser）→ 匹配子命令
   ↓    子命令不属于启动类（open/connect/chat） → exit 0 放行
   ↓    chat 子命令且无 URL 位置参数（REPL 模式） → exit 0 放行
   ↓    其余情况（启动类子命令 + 缺 --headed） → exit 2 阻断（stderr 输出改法指引）
```

---

## 深入话题

### 「在飞≤16」和「嵌套≤2」是纪律软约束

这两条不是 Claude Code 的硬限制，是靠注入文本让 AI 自觉遵守：

- **在飞≤16**：Claude Code 没有并发数的原生配置。规则要求 AI 每次派发前用 `TaskList` 统计 `status=running` 的在飞子代理，全系统总量控制在 16 以内。
- **嵌套≤2**：Claude Code 原生嵌套硬上限是 **5 层且不可配置**，`SubagentStart` 也无法拦截派发行为。所以 2 层限制只能由各层自觉传递——第 1 层子代理在给第 2 层写 prompt 时，须明确写「你是第 2 层子代理，禁止再派任何 subagent」。

### 与其他插件的关系

- 与 `omp` 插件互补：`omp` 的 `orchestrator-protocol-remind.js` 注入 omp 编排协议（强制委派 omp 子代理），本插件注入通用工作纪律（覆盖 Claude 原生 Agent 工具）——二者可并行启用。
- `block-cd.js` 原本在 `devkit-core`（现已更名 `devkit-tool`），本插件 1.3.0 起迁入此处；`devkit-tool` 自 5.1.0 起不再内置任何 hook。同批删除的 `guard-full-read.js`（大文件全文读取拦截）因与「精确读文件」注入纪律重复，未一并迁入。
- `max-source-lines.js` / `claude-md-max-lines.js` 与另一个插件 `quality-lint` 的 md 200 行拦截是同类思路（`PostToolUse` 拦 Write/Edit、`[L1-BLOCKER]` 输出格式）但各自独立实现——两个插件归属不同、不互相依赖，`quality-lint` 管的是文档质量的通用规则，本插件这两条是「最高宪法」层面单独声明的行数硬约束。
- `agent-browser-headed.js` 只管 `agent-browser` CLI 的启动参数（`--headed`），不涉及浏览器自动化能力本身；具体怎么用 agent-browser 走各会话的个人 memory / 全局 CLAUDE.md 约定（如是否用 `--profile` 指向独立临时目录），本插件只负责在缺 `--headed` 时硬拦。

---

## 目录结构

```text
plugins/working-discipline/
├── .claude-plugin/plugin.json      # hook 注册（注入 + 拦截）
├── hooks/
│   ├── working-discipline.js       # UserPromptSubmit / SubagentStart 注入
│   └── guards/
│       ├── block-cd.js             # PreToolUse 拦截（阻断污染 cwd 的独立 cd）
│       ├── agent-browser-headed.js # PreToolUse 拦截（agent-browser 启动类命令缺 --headed）
│       ├── max-source-lines.js     # PostToolUse 拦截（单一源码文件超 1000 行）
│       └── claude-md-max-lines.js  # PostToolUse 拦截（CLAUDE.md 超 200 行，指路拆到 .claude/rules/）
└── README.md
```

## 自定义

- 增删注入条款 / 切换风格 → 编辑 `hooks/working-discipline.js` 里的 `SECTION_*` 数组，每行是 markdown 一行
- 调整 `cd` 拦截行为（阈值、放行场景） → 编辑 `hooks/guards/block-cd.js`
- 调整 agent-browser 启动类子命令 / 白名单子命令 → 编辑 `hooks/guards/agent-browser-headed.js` 里的 `LAUNCH_SUBCOMMANDS` / `ALLOWLIST_SUBCOMMANDS`
- 调整源码文件行数阈值 / 扩展名列表 → 编辑 `hooks/guards/max-source-lines.js` 里的 `LINE_LIMIT` / `SOURCE_EXTENSIONS`
- 调整 CLAUDE.md 行数阈值 / 排除目录 → 编辑 `hooks/guards/claude-md-max-lines.js` 里的 `LINE_LIMIT` / `EXCLUDED_SEGMENT_PATTERN`

---

版本 1.6.0 · 作者 zhangq · MIT
