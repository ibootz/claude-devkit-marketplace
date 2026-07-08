# Working Discipline

**版本**: 1.1.0
**作者**: zhangq
**许可证**: MIT

每次用户提交对话时，向当前轮次 Claude 上下文注入一份 **AI 工作纪律**，覆盖上下文管理、子代理协作、表达约束、思维模式、Agent 工具派发五个维度，让 AI 的产出与协作行为保持在可审计、可复用的轨道上。

---

## 插件定位

- 一个 `UserPromptSubmit` hook，零 skill、零命令、零子代理
- 不依赖任何项目结构与外部工具
- 适合作为**全局基线**长期开启（用户级安装），任何项目都能受益
- 注入内容仅约束 AI 行为，不修改用户文件，无副作用

## 注入内容概要

| 维度 | 关键约束 |
|------|---------|
| **一、上下文纪律** | 精确路径/行号读文件、子代理优先、bash 输出限流 |
| **二、子代理协作** | 并发上限 4、共享骨架文件、任务组合、结构化回执 |
| **三、表达约束** | 不自造术语、关键对象点名、引用自带信息、待确认四要素、行号引用、求真、简体中文、有序列表编号 |
| **四、思维模式** | 举一反三 / 整体 / 第一性 / 逆向 / 自查自纠 / 读者视角（按需触发） |
| **五、Agent 工具派发** | subagent_type × model 路由表、显式 model 指定、成本意识 |

## 工作机制

```text
UserPromptSubmit 事件
   ↓
plugin.json hooks.UserPromptSubmit.matcher = "*"
   ↓
node ${CLAUDE_PLUGIN_ROOT}/hooks/working-discipline.js
   ↓
stdout 输出 { hookSpecificOutput: { additionalContext: "<纪律全文>" } }
   ↓
Claude Code 把 additionalContext 拼接进当前轮上下文
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
