// SessionStart hook: 注入 omp 使用指南
console.log(JSON.stringify({
  additionalContext: `【OMP 强制使用提醒】
本项目启用了 omp 插件。根据 using-omp 技能：
- 你 = Orchestrator（指挥者）：理解需求、拆解任务、审阅结果
- omp = Worker（执行者）：执行所有实际操作

⚠️ 重要：不要自己直接使用 Read/Edit/Write/Grep/Bash 等工具操作代码。
✅ 正确做法：使用 omp -p --tools "<工具集>" "<任务描述>" 委托执行。

调用范式：
  omp -p --tools "read,write,edit,bash,grep,lsp" "
  【目标】...
  【上下文】...
  【约束】...
  【期望输出】...
  "

工具集选择：
- 代码审查: read,grep,lsp,bash
- 代码编写: read,write,edit,bash,grep,lsp
- 技术调研: web_search,fetch,read
- 项目探索: read,find,grep
- Git 操作: bash,git-overview,git-file-diff

请严格遵守此约定。`
}));
