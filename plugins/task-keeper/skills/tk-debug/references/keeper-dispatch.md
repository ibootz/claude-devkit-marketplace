# Keeper 派发与唤醒机制（debug-keeper 与 chore-keeper 共用）

> 两 keeper（`debug-keeper` / `chore-keeper`）的派发、唤醒、换代共用同一套机制，本文是通用版。
> 读时按所在 skill 做占位替换：
>
> - `<keeper>` → `debug-keeper` 或 `chore-keeper`
> - `<kind>` → `debug` 或 `chore`
> - `<prefix>` → `debug 队列` 或 `chore 队列`
> - `<正则前缀>` → `opus-debug-keeper` 或 `opus-chore-keeper`
>
> 各 SKILL.md 正文里 debug/chore 特异的判据（例如 debug 的"不按 bug 看起来难不难下调"、
> chore 的"不按杂务看起来多小下调"）仍留在 SKILL 本身，本文只承载两 keeper 完全同构的部分。

## 1. 三岔口注入决定你该唤醒还是首次派发

**先看这一轮的三岔口注入怎么说，不要自己重新判断**：`user-prompt-submit-keeper-routing.sh`
每轮都会读 `.keeper/<交付id>/.keeper-instance.json` 并核对 `session_id`，直接给出
三种结论之一——「本会话已有 `<keeper>` 在跑，name 是 `<真实 name>`，唤醒它」／
「登记来自上一个会话（或是加会话隔离之前落的旧格式、压根没有 `session_id` 键），
已失效，这是首次派发」／「还没有登记，首次派发」。**照它说的做**：说唤醒就用给出
的 name 唤醒，说首次派发就用 `Agent` 派出并自己生成新的短哈希。

**为什么不是你自己读文件判断**：`session_id` 只在 hook 收到的 payload 里才有，主会话
拿不到自己的这个字段，重新读一遍登记文件只能看到 name 存不存在，判断不出它是不是
上一个会话留下的死 name——这正是「唤醒不到就重派、两个实例抢同一个目录写权限」这类
事故的根因，现在这层判断交给 hook 现算，不要自己再猜。

**不要因为 `SendMessage` 唤醒失败就直接改判首次派出再派第二个**——先确认自己用的 name
是不是这一轮注入给你的那个；hook 已经说了「首次派发」你却拿旧文档或旧记忆里的名字去
唤醒，失败是预期的，应该照 hook 的结论首次派出，不是"再派一个"。

## 2. name：带 4 位随机短哈希

**首次派出时，`name` 自己生成一个带 4 位随机短哈希的后缀，形态
`<正则前缀>-<4位小写字母或数字>`**（如 `<正则前缀>-4bb6`，正则
`^<正则前缀>-[0-9a-z]{4}$`）。

档位已钉死 `opus`，模型段恒为 `opus-`，但**不再逐字写死 `<正则前缀>`**——随机后缀让
每个实例天生不重名，避免「上一个实例结束、下一个又叫同名」时 `SendMessage` 的 name
寻址（latest wins）撞车。代价是主会话没法再靠记忆或文档拼出实际 name——`PreToolUse(Agent)`
hook 在派发那一刻自动把 name（连同 `session_id`）写进
`.keeper/<交付id>/.keeper-instance.json` 的 `<kind>` 键，每轮三岔口注入据此现算该
唤醒还是首次派发。

四类写错会被 `working-discipline` 的 `agent-dispatch` check 10 直接拦下：

- `<keeper>`（缺模型段）
- `<正则前缀>-<交付id>`（拿交付 id 当后缀，不是随机短哈希）
- `opus-task-keeper-<kind>-queue-manager` 这类带额外修饰的长名
- 任何不含 4 位随机后缀的逐字固定形态

## 3. description：前缀锚定 + 这一批摘要

**`description` 必须以 `<prefix>` 起头，前缀之后接这一批的摘要**，例如「`<prefix>` ·
登记五项杂务」或「`<prefix>` · 关三条 + 开工 DBG-140」（分隔符 `·` 推荐但不强制）。
这句话描述的是**这一代**而不是**这一秒**——`<keeper>` 是常驻实例，此后一律靠
`SendMessage` 唤醒、反复接不同的活，所以摘要要覆盖首次派发时手头已知的这一批范围，
不要写成某个具体动作。

**为什么是前缀锚定而不是逐字固定串**：在飞 agent 面板渲染的是**首次 `Agent` 派发那一刻**
的 `description`，`SendMessage` 只有 `to` / `summary` / `message` 三个字段，**没有任何
入口能更新已派出 agent 的 description**——这是实证过的事实。钉死成固定串之后，这句话
只说得出角色（「这是个 `<keeper>`」），说不出这一代在干什么，看板价值归零。所以现在
要写这一批的摘要，让它在**这一代**存续期间有信息量；队列收口时再靠 §4 的换代机制换
一句新的（这是"两条腿并用"的另一条腿）。

不带前缀的纯当次任务摘要会被 `working-discipline` 的 `agent-dispatch` check 11 拦下
（判据是 startsWith 比较：以 `<prefix>` 起头就放行；旧的固定串「`<prefix>` 常驻管理」
仍然放行，向后兼容）。

## 4. 换代：队列收口时新派一个实例，而不是继续唤醒旧的

**触发信号来自每轮的 hook 注入，不是你自己判断。** `hooks/lib/keeper_generation.py`
每轮 `UserPromptSubmit` 现算一次：某个 kind 的队列同时满足下列条件时，注入会建议你
新派一个实例、而不是继续 `SendMessage` 唤醒旧的——

1. `done` 桶非空（这一代确实干完了一批活，不是刚派出还没落盘）；
2. `open` 桶为空（没有还没处理的条目）；
3. `unknown` 桶为空；
4. 该交付下没有待答复的裁决（`.keeper/<交付id>/decisions/` 里没有缺对应
   `answers/` 的文件）；
5. **（debug 专项）** 没有任何 `debug/<id>/worktree/` 目录残留。`chore` 侧没有这一项，
   只有前四项。

**这些条件缺一不可，尤其第 1 项。** 「`done` 桶非空」是为了区分「刚开局」（活还没
落盘、open 暂时为空）与「刚收工」（确实干完了一批）这两种同样表现为 open 为空的状态
——没有它，主会话会在转完一条 issue 的下一轮就急着重派，两个实例抢同一个队列目录的
独占写权限。

第 4 项是一票否决、不按 kind 细分：`<keeper>` 写 `decisions/<stamp>-<keeper>.md` 之后，
答复是主会话后写的 `answers/<同名>.md`，「把裁决抄回条目正文、再删掉这对文件」这个
收口动作只写在各 keeper agent 规范里（debug-keeper 与 chore-keeper 各自的章节，见
对应 SKILL.md 的指针）——一旦这一代在答复落盘前退场，新实例的冷启动流程里没有任何
一步会去扫 `decisions/` 待答复清单，那对文件会静默留在磁盘上，裁决永远不会被抄回。

**换代该怎么做**：照 §1 一样用 `Agent` 新派——`subagent_type` 不变、`model` 仍是
`"opus"`、`name` 换一个新的 4 位随机短哈希（见 §2）、`description` 写新一批的摘要
（同样以 `<prefix>` 起头，见 §3）。这是一次全新的 `Agent` 调用，不是编辑或重启旧实例。

**不需要任何「作废登记」动作。** `.keeper/<交付id>/.keeper-instance.json` 的写入是
覆盖式的，`PreToolUse(Agent)` hook 在新实例派发那一刻自动登记，新 name 直接顶掉旧
name——旧实例从此失去寻址，但**不会被杀掉**（Claude Code 的 subagent 没有终态，
「停止」只是不再收消息），它安静留在后台，随会话结束，你不需要专门去关它或清理它的
登记。

**换代不是「必须做」，是「hook 给出建议之后你可以做」**：条件不全都满足时，继续照 §1
的方式 `SendMessage` 唤醒同一个实例，这仍是默认路径；本节只管条件全都满足之后新增的
另一个选择。

## 5. 唤醒同一实例的等价写法

每一轮的三岔口注入已经直接给出真实 name（见 §1），不需要再自己读文件——下面这段读取
命令只是给你在需要单独确认时用的等价写法：

```
NAME="$(/usr/bin/python3 -c '
import json
print(json.load(open(".keeper/<交付id>/.keeper-instance.json")).get("<kind>", {}).get("name", ""))
' 2>/dev/null)"
```

```
SendMessage(
  to: "<上面读出来的 NAME，不是字面量 <正则前缀>>",
  summary: "新增 <kind> 条目",
  message: "<用户原话逐字>"
)
```

`SendMessage` 唤醒时 keeper 的上下文完整保留（已实测确认），所以它记得之前登记过
什么、能判断新报的这条是否与旧条目同根因。**每次新派一个 keeper 都会丢掉这个能力，
并且产生两个写者竞争 `.keeper/<交付id>/<kind>/`**——「唤醒不到就乱重派」这种情形
仍然禁止；§4 讲的换代是另一种情形（hook 主动建议换代），那时新派一个是机制本身要
你做的事，不是违反本条。
