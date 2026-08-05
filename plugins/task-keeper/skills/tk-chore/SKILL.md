---
name: tk-chore
description: 主会话把杂务（台账/沉淀/收尾/外部系统小操作）转交常驻 chore-keeper subagent 托管的最小流程：判断是杂务 → 逐字转发 → 回原任务。登记、分类、攒批执行、外部写打包拍板、归档全部由 chore-keeper 在独立上下文完成，主会话不亲手做杂务。队列落盘 `.keeper/chore/`（整树 gitignore，不入库）。
when_to_use: |
  用户说"记一下 / 记个账 / 台账加一条"、"这个结论沉淀到文档 / 同步到 wiki"、"回头收尾 / 别忘了清理"、"帮我提个单 / 发个通知（非 bug 类）"，或任何不改核心代码、不修 bug、可以攒着批量做的琐碎事务。**禁止主会话亲手做掉杂务，哪怕它看起来 30 秒就能完**——「顺手做更快」正是本机制要消除的行为：就地做完的杂务只活在本轮上下文里，compact 一次就没了，也没有任何跨 session 的恢复锚点。bug / 报错 / 异常行为不走这里——那是 tk-debug 的 debug-keeper 管的。
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

**先看这一轮的三岔口注入怎么说，不要自己重新判断**：`user-prompt-submit-keeper-routing.sh`
每轮都会读 `.keeper/<交付id>/.keeper-instance.json` 并核对 `session_id`，直接给出
「唤醒 `<真实 name>`」／「登记来自上一个会话（或是加会话隔离之前落的旧格式、压根
没有 `session_id` 键），已失效，首次派发」／「还没有登记，首次派发」三种结论之一。
**照它说的做**——你（主会话）自己读不到自己的 `session_id`，重新读一遍文件只能看到
name 存不存在，判断不出它是不是上一个会话留下的死 name，这正是"唤醒不到就重派、
两个实例抢同一个目录写权限"这类事故的根因，现在交给 hook 现算。**不要因为
`SendMessage` 唤醒失败就直接改判成首次派出再派第二个**——先确认自己用的 name 是不是
这一轮注入给你的那个，见下方事故。

**`model` 固定 `"opus"`，不按杂务看起来多小来下调。** 杂务本身粒度小，但 keeper 要判的是
外部写红线（判漏一次就是未授权写入外部系统）、共享工作区让位、决策打包，判错代价与活的
体量无关（理由详见 `agents/chore-keeper.md` §0）。它派的只读 `Explore` 才用 `sonnet`。

**首次派出时，`name` 自己生成一个带 4 位随机短哈希的后缀，形态
`opus-chore-keeper-<4位小写字母或数字>`（如 `opus-chore-keeper-9f2a`，正则
`^opus-chore-keeper-[0-9a-z]{4}$`）。** 档位已钉死 `opus`，所以模型段恒为
`opus-`，但**不再逐字写死 `opus-chore-keeper`**——2026-08-04 起改为强制带随机后缀，
原因是逐字固定名会在「上一个实例结束、下一个又叫同名」时撞车：`SendMessage` 的
name 寻址是 latest wins，想唤起前一个就冲突。随机后缀让每个实例天生不重名，但
代价是你没法再靠记忆或本文档拼出实际 name——`PreToolUse(Agent)` hook 会在派发那
一刻自动把 name（连同 `session_id`，2026-08-05 补，见上方「派出与唤醒」的会话隔离
说明）写进 `.keeper/<交付id>/.keeper-instance.json` 的 `chore` 键，每轮三岔口注入
据此现算该唤醒还是首次派发。拿交付 id 当后缀（`opus-chore-keeper-<交付id>`）或额外
修饰都仍会被 `working-discipline` 的 `agent-dispatch` check 10 拦下。不要写成
`chore-keeper`（缺模型段，会被 `working-discipline` 的 `agent-dispatch` 门禁拦下），
也不要写成 `opus-task-keeper-chore-queue-manager` 这类带额外修饰的长名。

```
Agent(
  name: "opus-chore-keeper-9f2a",   // 自己生成 4 位随机小写字母/数字后缀，不要逐字抄这个例子
  subagent_type: "task-keeper:chore-keeper",   // 插件 agent；不可用时退 general-purpose 并把 agents/chore-keeper.md 全文放进 prompt
  description: "chore 队列常驻管理",
  model: "opus",
  run_in_background: true,
  prompt: "<用户原话逐字> + 项目根绝对路径"
)
```

派发成功后 `PreToolUse(Agent)` hook 会自动登记这个 name，不需要你自己再写登记文件。

**之后每一次**（同一会话内再有新杂务），这一轮的三岔口注入已经直接给出真实 name
（见上方「派出与唤醒」），不需要再自己读文件——下面这段读取命令只是给你在需要单独
确认时用的等价写法：一律先读 `.keeper/<交付id>/.keeper-instance.json` 的 `chore`
键取出真实 name，再 `SendMessage(to: "<读出来的 NAME，不是字面量 opus-chore-keeper>", message:
"<用户原话逐字>")` 唤醒——keeper 上下文跨唤醒保留，重新 Agent 派出会丢掉它已有的
队列认知，也会让两个实例抢同一个 `.keeper/<交付id>/chore/` 的独占写权限。

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
