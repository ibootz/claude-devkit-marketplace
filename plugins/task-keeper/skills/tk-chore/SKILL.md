---
name: tk-chore
description: 主会话把杂务（台账/沉淀/收尾/外部系统小操作）转交常驻 chore-keeper subagent 托管的最小流程：判断是杂务 → 逐字转发 → 回原任务。登记、分类、攒批执行、外部写打包拍板、归档全部由 chore-keeper 在独立上下文完成，主会话不亲手做杂务。队列落盘 `.keeper/<交付id>/chore/`（v6 起正文与附件入库，只排除 worktree/instance.json/keeper-active 三类本机产物）。
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

**派发与唤醒机制（三岔口注入、name 生成、description 锚定、换代）见
`../tk-debug/references/keeper-dispatch.md`，两 keeper 共用同一套，本文只写 chore
特异的判据。** 读 reference 时占位替换：`<keeper>`→`chore-keeper`、`<kind>`→`chore`、
`<prefix>`→`chore 队列`、`<正则前缀>`→`opus-chore-keeper`。

**`model` 固定 `"opus"`，不按杂务看起来多小来下调。** 杂务本身粒度小，但 keeper 要判的是
外部写红线（判漏一次就是未授权写入外部系统）、共享工作区让位、决策打包，判错代价与活的
体量无关（理由详见 `agents/chore-keeper.md` §0）。它派的只读 `Explore` 才用 `sonnet`。

首次派发的 `Agent` 调用形态（三岔口注入说「首次派发」时照这模板填，name 自己生成
4 位随机短哈希、description 以 `chore 队列` 起头——完整规则与反模式清单见
`../tk-debug/references/keeper-dispatch.md` §2/§3）：

```
Agent(
  name: "opus-chore-keeper-9f2a",   // 自己生成 4 位随机小写字母/数字后缀，不要逐字抄这个例子
  subagent_type: "task-keeper:chore-keeper",   // 插件 agent；不可用时退 general-purpose 并把 agents/chore-keeper.md 全文放进 prompt
  description: "chore 队列 · 登记五项杂务",   // 前缀 `chore 队列` 不可省，之后写这一批接的活（不是当次单个动作）
  model: "opus",
  run_in_background: true,
  prompt: "<用户原话逐字> + 项目根绝对路径"
)
```

**`description` 锚定 `<prefix>` 起头 + 这一批的摘要**：例如「chore 队列 · 登记五项
杂务」，不要写成某个具体动作。完整机制（为什么前缀锚定而不是逐字固定串、面板渲染
时机、check 11 拦下、向后兼容旧固定串、与「换代」小节的"两条腿并用"关系）见
`../tk-debug/references/keeper-dispatch.md` §3。

派发成功后 `PreToolUse(Agent)` hook 会自动登记这个 name，不需要你自己再写登记文件。

**之后每一次**（同一会话内再有新杂务），用 `SendMessage` 唤醒同一个实例，**不要再派
第二个**——唤醒形态、读取真实 name 的等价命令、上下文跨唤醒保留的事实、"唤醒不到
就乱重派"为什么仍然禁止，见 `../tk-debug/references/keeper-dispatch.md` §5。

## 换代：队列收口时新派一个实例

完整机制（hook 注入触发、四项条件、换代该怎么做、不需要作废登记、是否必须做）见
`../tk-debug/references/keeper-dispatch.md` §4。chore 侧的条件就是该节列出的前四项
（没有 debug 专项的「`debug/<id>/worktree/` 目录残留」检查）。第 4 项一票否决涉及
`agents/chore-keeper.md` §7 第 4 条的裁决抄回收口动作——一旦换代会丢掉这个收口
能力，原因见 reference §4。

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
