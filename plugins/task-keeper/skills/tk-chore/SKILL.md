---
name: tk-chore
description: 主会话把杂务（台账/沉淀/收尾/外部系统小操作）转交常驻 chore-keeper subagent 托管的最小流程：判断是杂务 → 逐字转发 → 回原任务。登记、分类、攒批执行、外部写打包拍板、归档全部由 chore-keeper 在独立上下文完成，主会话不亲手做杂务。队列落盘 `.keeper/<交付id>/chore/`（v6 起正文与附件入库，只排除 worktree/instance.json/keeper-active/merge.lock 四类本机产物）。
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

**唤醒判断与派发骨架见 `../tk-debug/references/keeper-dispatch.md`**（三岔口每轮
怎么判断该首次派发还是唤醒、name 为什么带 4 位短哈希、description 前缀锚定的道理、
会话隔离）——占位替换 `<keeper>`→`chore-keeper`、`<kind>`→`chore`、`<prefix>`→
`chore 队列`。**该文档写于两 keeper 共享同一档位（`opus-`）的年代，`<正则前缀>`
这条映射、以及它描述的「换代」机制，均已被 2026-08-18 起的改动部分覆盖——具体差异
见下面两节，以本文为准，不要按该文档的旧例子照抄。**

### name 与 model

**`model` 固定 `"sonnet"`，`name` 形态固定 `sonnet-chore-<4位随机小写字母或数字>`**
（如 `sonnet-chore-9f2a`，正则 `^sonnet-chore-[0-9a-z]{4}$`，由 `working-discipline`
的 `agent-dispatch.js`（`KEEPER_SPECS` 表）校验）。2026-08-18 用户拍板把 chore-keeper
从 `opus` 降到 `sonnet`、name 的身份段从 `chore-keeper` 简化成 `chore`——debug-keeper
不受影响，仍是 `opus-debugger-<4位>`。**判据是等值，不是下限**：给 chore-keeper 派
`"opus"` 与派 `"haiku"` 一样会被硬拦，不是"越高越安全"。降档理由是登记、分类、
攒批、归档这类机械杂务不需要 debug-keeper 那种跨层追根因的判断力（那条判断力
判错一次代价由后面整条流水线承担，chore 没有这条流水线；详见 `agents/chore-keeper.md`
§0）。它派的只读 `Explore` 同样用 `sonnet`，不再下探。

首次派发的 `Agent` 调用形态（三岔口注入说「首次派发」时照这模板填，name 自己生成
4 位随机短哈希、description 以 `chore 队列` 起头）：

```
Agent(
  name: "sonnet-chore-9f2a",   // 自己生成 4 位随机小写字母/数字后缀，不要逐字抄这个例子
  subagent_type: "task-keeper:chore-keeper",   // 插件 agent；不可用时退 general-purpose 并把 agents/chore-keeper.md 全文放进 prompt
  description: "chore 队列 · 登记五项杂务",   // 前缀 `chore 队列` 不可省，之后写这一批接的活（不是当次单个动作）
  model: "sonnet",
  run_in_background: true,
  prompt: "<用户原话逐字> + 项目根绝对路径"
)
```

**`description` 锚定 `<prefix>` 起头 + 这一批的摘要**，不要写成某个具体动作——完整
机制（为什么前缀锚定而不是逐字固定串、面板渲染时机、check 11 拦下、向后兼容旧固定串）
见 `../tk-debug/references/keeper-dispatch.md` §3，该节未受 2026-08-18 改动影响，
可以照抄。

派发成功后 `PreToolUse(Agent)` hook 会自动把这个 name（连同它从 prompt 里提取到的
`CHR-NNN`）登记进 `.keeper/<交付id>/.keeper-instance.json` 的 `chore` 键，不需要你
自己再写登记文件。

### 唤醒 vs 再派一个：默认单实例攒批

**之后每一次**（同一会话内再有新杂务），默认用 `SendMessage` 唤醒同一个实例，**不要
自己主动多开**。这是 chore 与 debug 最大的分野：debug 是「一条 bug 一个实例」，并行
本身就是收益；chore 反过来，价值恰恰在跨条目视野——攒批执行、把散落的待拍板事项打成
一个包一次问完（`agents/chore-keeper.md` §0）、归档时看的是整个 done 桶。拆成多个
各管一段，这三件事全部失效，Human 会收到 N 个各说各话的拍板请求，而不是一次。

**唯一的例外是 Human 或用户当轮明确要求并行清账。** 此时才多派一个，新实例的 name
另生成一个短哈希，登记表按下述 v7 格式记多条；要给某条 issue 补充信息时按 `issue`
唤醒认领了它的那个实例，不是猜"最近派的那个"。

**每轮三岔口注入里"新条目一律新派实例"那句话是给 debug 写的**——它按 kind 合并展示
"还有活"的实例，看到这句话不代表这条杂务也要照单再开一个实例，除非属于上一段说的
例外情形；对 chore 的缺省判断仍是"唤醒现有那个"。唤醒形态、读取真实 name 的等价
命令、上下文跨唤醒保留的事实，见 `../tk-debug/references/keeper-dispatch.md` §5，
该节同样未受 2026-08-18 改动影响。

## 收工信号：v7 里不是「换代」，是「别再主动叫它」

`../tk-debug/references/keeper-dispatch.md` §4 描述的"队列收口时新派一个实例、换一句
新鲜 description"是 v6 的设计，**2026-08-18 后不再是每轮注入实际驱动的行为，读到它
不要照做**：v7 把驱动注入的判据从"按档"（`keeper_generation.retirable_kinds`，现在
只是一个未接入任何注入的诊断函数）换成"按实例"（`instance_state`）——判断的是**这个
实例当前认领的那条 issue** 是否已经 `status: done` 且无 `worktree/` 残留，不是整档
是否收口。

命中时注入会说「已收工，别再唤醒：`<name>`」，意思仅仅是"它认领的这条杂务处理完了，
现在没理由主动 `SendMessage` 给它"，**不代表要新派一个替代它**。它仍是你默认要用的
那个 chore-keeper：下一条新杂务照常唤醒它（走上一节的默认路径），它的上下文完整
保留，记得之前处理过什么。真正需要另开一个的场景只有上一节说的"明确要求并行清账"，
与这个实例是否"收工"无关。

### 登记格式与并发原语（v7）

`.keeper/<交付id>/.keeper-instance.json` 的 `chore` 键是一个**实例列表**（多个
chore-keeper 并存的场景下才会超过一条）：

```json
{"chore": {"instances": [
    {"name": "sonnet-chore-9f2a", "ts": "...", "session_id": "...", "issue": "CHR-014"}
]}}
```

`issue` 由 `pre-tool-use-keeper-instance.sh` 从派发的 `prompt`（抽不到再退
`description`）里正则抽第一个 `CHR-NNN`，抽不到就不写这个键，不编造。原子认领编号
用 `scripts/keeper_cli.py claim --kind chore`（见「配套件」表）——**不要自己扫目录
算下一个编号**，两个实例几乎同时扫到同一个最大值会撞号，后写的整份覆盖先写的且
不报错。

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
| `scripts/keeper_cli.py` | v7 新增的多实例并发原语 CLI：`claim --kind chore` 原子认领 `CHR-NNN`；`bind` 登记 issue→name；`peers --kind chore` 看同档还有哪些实例。chore 通常不需要 `lock`（合并锁是 debug 侧合并回主仓时用的，chore 各条目独立目录、天然无锁竞争） |
| `skills/tk-decisions/SKILL.md` | 决策打包 HITL 协议正典 |
| `skills/tk-debug/scripts/archive_done.py` | 归档脚本（`--queue chore`），keeper 自动跑 |
