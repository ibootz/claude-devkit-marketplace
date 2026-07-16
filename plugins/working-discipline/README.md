# Working Discipline

一个纯 hook 插件，用两种方式把「AI 工作纪律」落到 Claude Code 上：

1. **注入**：每轮往主会话、以及每次子代理启动时的 context 里，塞入一份可审计、可复用的行为准则
2. **拦截**：Bash 工具执行前，硬拦截会污染会话 cwd 的独立 `cd` 命令

零 skill、零命令、零子代理，装了就生效。不修改用户文件，无副作用。

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

---

## 深入话题

### 「在飞≤16」和「嵌套≤2」是纪律软约束

这两条不是 Claude Code 的硬限制，是靠注入文本让 AI 自觉遵守：

- **在飞≤16**：Claude Code 没有并发数的原生配置。规则要求 AI 每次派发前用 `TaskList` 统计 `status=running` 的在飞子代理，全系统总量控制在 16 以内。
- **嵌套≤2**：Claude Code 原生嵌套硬上限是 **5 层且不可配置**，`SubagentStart` 也无法拦截派发行为。所以 2 层限制只能由各层自觉传递——第 1 层子代理在给第 2 层写 prompt 时，须明确写「你是第 2 层子代理，禁止再派任何 subagent」。

### 与其他插件的关系

- 与 `omp` 插件互补：`omp` 的 `orchestrator-protocol-remind.js` 注入 omp 编排协议（强制委派 omp 子代理），本插件注入通用工作纪律（覆盖 Claude 原生 Agent 工具）——二者可并行启用。
- `block-cd.js` 原本在 `devkit-core`，本插件 1.3.0 起迁入此处；`devkit-core` 自 5.1.0 起不再内置任何 hook。同批删除的 `guard-full-read.js`（大文件全文读取拦截）因与「精确读文件」注入纪律重复，未一并迁入。

---

## 目录结构

```text
plugins/working-discipline/
├── .claude-plugin/plugin.json      # hook 注册（注入 + 拦截）
├── hooks/
│   ├── working-discipline.js       # UserPromptSubmit / SubagentStart 注入
│   └── guards/block-cd.js          # PreToolUse 拦截（阻断污染 cwd 的独立 cd）
└── README.md
```

## 自定义

- 增删注入条款 / 切换风格 → 编辑 `hooks/working-discipline.js` 里的 `SECTION_*` 数组，每行是 markdown 一行
- 调整 `cd` 拦截行为（阈值、放行场景） → 编辑 `hooks/guards/block-cd.js`

---

版本 1.4.1 · 作者 zhangq · MIT
