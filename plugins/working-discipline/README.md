# Working Discipline

**版本**: 1.2.0
**作者**: zhangq
**许可证**: MIT

向 Claude 上下文注入一份 **AI 工作纪律**，覆盖上下文管理、子代理协作、表达约束、思维模式、Agent 工具派发五个维度，让 AI 的产出与协作行为保持在可审计、可复用的轨道上。通过两个 hook 事件覆盖主会话与子代理：`UserPromptSubmit` 在主会话每轮注入完整纪律，`SubagentStart` 在子代理启动时注入精简版纪律（补齐 subagent 覆盖缺口）。

---

## 插件定位

- 两个 hook：`UserPromptSubmit`（主会话每轮）+ `SubagentStart`（子代理启动时），零 skill、零命令、零子代理
- 不依赖任何项目结构与外部工具
- 适合作为**全局基线**长期开启（用户级安装），任何项目都能受益
- 注入内容仅约束 AI 行为，不修改用户文件，无副作用

## 注入内容概要

| 维度 | 关键约束 | 主会话 | 子代理 |
|------|---------|:---:|:---:|
| **一、上下文纪律** | 精确路径/行号读文件、子代理优先、bash 输出限流 | ✅ | ✅ |
| **二、子代理协作** | **在飞总量动态上限 16**（派发前 `TaskList` 统计）、**嵌套≤2 层软约束**、共享骨架文件、任务组合、结构化回执 | ✅ | ✅ |
| **三、表达约束** | 不自造术语、关键对象点名、引用自带信息、待确认四要素、行号引用、求真、简体中文、有序列表编号 | ✅ | ✅ |
| **四、思维模式** | 举一反三 / 整体 / 第一性 / 逆向 / 自查自纠 / 读者视角（按需触发） | ✅ | — |
| **五、Agent 工具派发** | subagent_type × model 路由表、显式 model 指定、成本意识 | ✅ | — |

> 子代理版（`SubagentStart`）只注入一、二、三节——四、五两节主要指导父代理如何派发，对子代理自身无意义，故略去以省 token。

### 关于"在飞≤16"与"嵌套≤2"的性质说明

这两条是**纪律软约束**，靠注入文本让 AI 自觉遵守，不是 Claude Code 的硬限制：

- **在飞≤16**：Claude Code 无并发数原生配置；规则要求每次派发前用 `TaskList` 统计 status=running 的在飞子代理，控制全系统在飞总量 ≤16。
- **嵌套≤2**：Claude Code 原生嵌套硬上限为 **5 层且不可配置**（`SubagentStart` 也无法拦截派发），故 2 层限制只能作为软约束由各层自觉传递——第 1 层子代理在给第 2 层写 prompt 时须写明"禁止再派 subagent"。

## 工作机制

```text
UserPromptSubmit（主会话每轮）  或  SubagentStart（子代理启动时）
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/working-discipline.js
   ↓  读取 stdin 的 hook_event_name 分流：
   ↓    UserPromptSubmit → 完整纪律（一~五节）
   ↓    SubagentStart    → 子代理版纪律（一、二、三节）
   ↓
stdout 输出 { hookSpecificOutput: { hookEventName, additionalContext } }
   ↓
Claude Code 把 additionalContext 拼接进对应上下文
（SubagentStart 的注入进子代理自己的 transcript，不入主会话）
```

## 安装

### Claude Code

```bash
/plugin install working-discipline@claude-devkit-marketplace
```

### Codex CLI

```bash
node scripts/install-codex.js --plugins=working-discipline --scope=user
```

`--scope=user` 会写入用户目录，对所有项目生效。

## 目录结构

```text
plugins/working-discipline/
├── .claude-plugin/plugin.json    # hook 注册
├── hooks/working-discipline.js   # UserPromptSubmit 注入脚本
└── README.md
```

## 与其他插件的关系

- 与 `omp` 插件互补：omp 的 `orchestrator-protocol-remind.js` 注入 omp 编排协议（强制委派 omp 子代理），本插件注入通用工作纪律（覆盖 Claude 原生 Agent 工具），二者可并行启用
- 与 `devkit-core` 的 `block-cd.js` / `guard-full-read.js` 互补：那些是 `PreToolUse` 拦截器，本插件是 `UserPromptSubmit` 注入器，触发时机与作用对象不同

## 自定义

如需调整注入内容（增删条款 / 切换风格），直接编辑 `hooks/working-discipline.js` 内的 `prompt` 数组即可，每行是 markdown 的一行。
