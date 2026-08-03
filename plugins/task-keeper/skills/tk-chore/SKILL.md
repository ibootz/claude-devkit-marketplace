---
name: tk-chore
description: 主会话把杂务（台账/沉淀/收尾/外部系统小操作）转交常驻 chore-keeper subagent 托管的最小流程：判断是杂务 → 逐字转发 → 回原任务。登记、分类、攒批执行、外部写打包拍板、归档全部由 chore-keeper 在独立上下文完成，主会话不亲手做杂务。队列落盘 `.keeper/chore/`（整树 gitignore，不入库）。
when_to_use: |
  用户说"记一下 / 记个账 / 台账加一条"、"这个结论沉淀到文档 / 同步到 wiki"、"回头收尾 / 别忘了清理"、"帮我提个单 / 发个通知（非 bug 类）"，或任何不改核心代码、不修 bug、可以攒着批量做的琐碎事务。bug / 报错 / 异常行为不走这里——那是 tk-debug 的 debug-keeper 管的。
---

# tk-chore：主会话侧的杂务转交流程

## 主会话只做三个动作

1. **判断是杂务**：不改核心代码、没有可复现的错误行为、可以攒着做。拿不准时按
   「有没有可复现的错误行为」分——有 → 转 debug-keeper（tk-debug skill）；没有 → 这里。
2. **逐字转发**：把用户原话原文转给 chore-keeper，不改写、不总结、不补充你的理解
   ——原话是唯一不失真的需求锚点，keeper 有独立上下文自己消化。
3. **回原任务**：转发完回一句「已转 chore-keeper」就继续手上的事。登记结果由
   keeper 的 SendMessage 回执带回，队列状态由每轮 hook 快照注入，都不需要你追问。

## 派出与唤醒

首次（本会话还没有 chore-keeper 在跑时）：

**`name` 的形态是 `<模型档>-chore-keeper`，三段，不加任何多余前后缀**——模型段必须
与同一次调用的 `model` 一致（`model: "sonnet"` → `sonnet-chore-keeper`；换 `opus`
派就是 `opus-chore-keeper`，此后 `SendMessage` 的 `to` 同步换）。不要写成
`chore-keeper`（缺模型段，会被 `working-discipline` 的 `agent-dispatch` 门禁拦下），
也不要写成 `sonnet-task-keeper-chore-queue-manager` 这类带额外修饰的长名。

```
Agent(
  name: "sonnet-chore-keeper",
  subagent_type: "task-keeper:chore-keeper",   // 插件 agent；不可用时退 general-purpose 并把 agents/chore-keeper.md 全文放进 prompt
  description: "chore 队列常驻管理",
  model: "sonnet",
  run_in_background: true,
  prompt: "<用户原话逐字> + 项目根绝对路径"
)
```

之后一律 `SendMessage(to: "sonnet-chore-keeper", message: "<用户原话逐字>")` 唤醒——
keeper 上下文跨唤醒保留，重新 Agent 派出会丢掉它已有的队列认知。

## 主会话的边界（禁止越位）

1. 不写 `.keeper/chore/` 下任何文件（唯一写者是 chore-keeper；index.md 由 hook 重算）。
2. 不替 keeper 执行杂务，哪怕看起来 30 秒就能做完——主会话的注意力预算属于用户
   的原任务。
3. keeper 送回的待拍板事项（`.keeper/<交付id>/decisions/` + SendMessage 通知）按
   tk-decisions skill 处理：攒批后一次 AskUserQuestion 并列问完，答复原文写
   `answers/` 回传。不要替用户拍板，也不要一条一弹。

## 状态从哪看

- 每轮 UserPromptSubmit hook 注入 open/done/待拍板 计数（未启用的项目零注入）。
- 要细看某条：`.keeper/chore/index.md` 是薄索引，单条全文在
  `.keeper/<交付id>/chore/CHR-NNN/item.md`——按需打开单条，不要读全目录。

## 配套件

| 组件 | 作用 |
|---|---|
| `agents/chore-keeper.md` | keeper 全流程规范（登记/分类/攒批/共享工作区纪律/外部写红线/归档） |
| `hooks/user-prompt-submit-chore-queue.sh` | 每轮队列快照注入（零 git 调用，≤900 字符） |
| `skills/tk-decisions/SKILL.md` | 决策打包 HITL 协议正典 |
| `skills/tk-debug/scripts/archive_done.py` | 归档脚本（`--queue chore`），keeper 自动跑 |
