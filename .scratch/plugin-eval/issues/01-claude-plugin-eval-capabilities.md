# 01: claude plugin eval 能评什么

Type: research
Status: resolved
Blocked by: 无

## Question

Claude Code 内置的 `claude plugin eval` 与 `/skill-doctor` 各能评什么、怎么判分、隔离到什么程度、成本怎么控？本仓的 hook 注入、output style、多插件干扰能不能在其中评？

## Answer

详见 [research/claude-plugin-eval-capabilities.md](../research/claude-plugin-eval-capabilities.md)。

要点：

- 它和 skill-creator 的 `evals.json` 是两套，互不读取。
- 已覆盖：skill 触发（`tool_used: Skill`）、单轮输出、MCP 打桩；6 种 grader（4 种免费确定性 + `llm` 3 票 + `baseline`）；每臂默认 3 次、自动给出有无插件的 Δ；每个 run 临时 home，用户配置与其它插件全不加载；`--max-cost-usd` 成本上限，JSON 带版本号，退出码可接 CI。
- 没有一等支持：hook 注入是否进入 `trace`（未查到）、output style（未查到）、多插件同时加载（未明确）、自定义代码判分（明确没有）、真实会话事后分析。
- `/skill-doctor` 只是用量报告，不评行为。

## Comments
