# token-saver

运行时提醒 AI 节用 token 的 Claude Code 插件。

## 它做什么

两条机制，皆**零硬拦**（恒 `exit 0`，不阻止任何操作，只注入提醒）：

1. **SessionStart 注入 5 行核心纪律** —— 每会话（含 auto-compact 后重注）注入极简正向省 token
   纪要，以 `frugal` 一词锚定。
2. **PreToolUse(Read) 大文件软提醒** —— 当 `Read` 一个 >100KB 且未带 `offset`/`limit` 的文件时，
   注入一句提醒：先 `grep -n` 定位行号再定点读。

详细原则在 [`references/principles.md`](references/principles.md)，hook 提醒里引导按需读，不常驻。

## 设计原则

**省 token 插件自身不能烧 token** —— 这是第一性原理。故：

- SessionStart 注入控制在 5 行（~80 token）；
- PreToolUse 只在大文件（>100KB）整读时触发，低频；提醒文本一两行，极短；
- **不做 Bash 收窄 hook** —— 「输出大不大」要猜语义，判据不准会刷屏浪费 token（违反本仓
  `hook-restraint` 规则的机械判定要求），改放 SessionStart 注入靠自觉；
- **无 skill 组件** —— 省 token 场景 AI 难自知，skill 触发率低；少一组件即少占 context。

## 启用 / 停用

- 停用单次会话：环境变量 `TOKEN_SAVER=off`。
- 彻底停用：`/plugin` 里停用本插件。

## 依据

凝聚自互联网最佳实践调研（52 条 agentic coding 技巧 + 13 篇论文 + 25 个开源项目）与两个写作
技能（writing-for-agents、skill-creator）。完整信源见 [`references/principles.md`](references/principles.md)。

## 与 working-discipline 的关系

`working-discipline` 是通用工作纪律（含并行、读前定位、收窄等，每轮注入数千 token）。
token-saver 聚焦省 token 一个维度，注入极短（~80 token），角度互补；两者可共存，token-saver
在省 token 维度更集中、自身更轻。
