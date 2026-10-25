---
id: DBG-009
summary: 被守卫拒绝的派发仍写入 keeper 实例注册表，留下幽灵实例
status: open
priority: P1
difficulty: medium
type: bug
spec_status: violation
reported_at: '2026-09-19'
reopen_count: 0
---

# DBG-009 · 被守卫拒绝的派发仍写入 keeper 实例注册表，留下幽灵实例

## 问题

主会话用 `Agent` 派发一个 keeper，该次调用被另一个插件的 `PreToolUse` 守卫 deny、
subagent **从未被创建**；task-keeper 的 `PreToolUse` 副作用 hook 却照样把这次派发的
`name` 写进了 `.keeper/<交付id>/.keeper-instance.json`。结果是注册表里多出一条**永远
唤不醒的幽灵实例**，后续读注册表的 keeper 把它当成活实例，误判为「同一条 issue 被两个
实例同时认领」，中断工作向主会话报警。

落点与证据：

[keeper_instance_register.py:147-173](file:///C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/task-keeper/hooks/lib/keeper_instance_register.py#147)
——判据只看 `tool_name`/`subagent_type`/`name` 三个入参字段，没有任何一步能知道这次
调用最终是被放行还是被 deny：

```python
    if ev.get("tool_name") != "Agent":
        return
    ...
    kind = keeper_kind(tool_input.get("subagent_type"))
    if kind is None:
        return
    name = tool_input.get("name")
    if not isinstance(name, str) or not name.strip():
        return
    ...
    keeper_paths.write_keeper_instance(root, delivery_id, kind, name.strip(),
                                       session_id=session_id,
                                       issue=extract_issue(tool_input, kind))
```

病根是同一份文件模块头里写死的一条**假设**，
[keeper_instance_register.py:39-43](file:///C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/task-keeper/hooks/lib/keeper_instance_register.py#39)：

```
【为什么不校验 name 是否满足短哈希正则】那是 `working-discipline` 的
  `agent-dispatch.js` 的职责（判断该不该放行这次派发）。本 hook 运行在它之后
  （PreToolUse 同一时机点，两个插件各自独立挂载），如果那道闸已经 deny 了这次
  调用，Agent 根本不会真正派发；
```

「如果那道闸已经 deny 了这次调用，Agent 根本不会真正派发」——这句推的是「所以注册表
里不会留下它」，而本轮实测正好推翻了后半截：Agent 确实没被派发，**注册表却留下了它**。
两件事同时成立，因为 deny 拦住的是工具调用，拦不住另一个 hook 已经产生的写文件副作用。

## 用户原话

（本条由主会话转述本轮实测经过登记，无用户逐字原话。）

## 证据

本轮实测经过（主会话提供，已核实为前提事实）：

1. 主会话派发 `Agent`，参数 `name="sonnet-debug-keeper-a7f3"`、`model="sonnet"`、
   `subagent_type="task-keeper:debug-keeper"`，正文提到 `DBG-006`。
2. working-discipline 的
   [agent-dispatch.js:178](file:///C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/working-discipline/hooks/guards/agent-dispatch.js#178)
   以 L1-BLOCKER deny 这次调用（debug-keeper 固定 opus 档，name 须形如
   `opus-debugger-xxxx`）。Agent **从未创建**，工具返回错误而非 agentId。
3. 主会话改名重派，成功创建 `opus-debugger-4bb6`（同一 issue DBG-006）。
4. 随后读 `.keeper/_main/.keeper-instance.json`，**两条都在**：

   | name | ts | session_id | issue |
   |---|---|---|---|
   | `opus-debugger-4bb6` | 2026-09-19T23:39:35+08:00 | 同一 | DBG-006 |
   | `sonnet-debug-keeper-a7f3` | 2026-09-19T23:39:21+08:00 | 同一 | DBG-006 |

   被拒那条的 ts（:21）**早于**成功那条（:35），说明写入发生在 deny 判定之前或同时，
   不是事后补写。
5. `opus-debugger-4bb6` 读到这份注册表后误判双实例认领，中断工作向主会话报警求裁决。
6. 主会话手工编辑该文件删掉幽灵条目。

`opus-debugger-4bb6` 明确声明：它对该文件只做过一次只读 `cat`，从未写过它——幽灵条目
确系 hook 所写。

**旁证已升级为一手实证**：本条 triage 期间，本实例派发一个无 `name` 的 `Agent` 调用，
当场收到 agent-dispatch 的自动补名回灌（补为 `sonnet-subagentstart-payload-56d1` 并
放行）。这坐实了「补名/副作用逻辑跑在 PreToolUse，且不区分派发最终是否成功」。

## Triage

### 落点

注册表的写入路径**全仓只有两条**（`grep -rn write_keeper_instance plugins/` 穷举）：

| 写入路径 | 时机 | 是否产生幽灵 |
|---|---|---|
| [keeper_instance_register.py:171](file:///C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/task-keeper/hooks/lib/keeper_instance_register.py#171) | `PreToolUse(Agent)` 副作用 hook | **是**，本条根因 |
| [keeper_cli.py:145](file:///C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/task-keeper/scripts/keeper_cli.py#145) | keeper 自己显式调 `bind` | 否——调用者本身就是活着的实例 |

hook 的挂载点在
[plugin.json:81-90](file:///C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/task-keeper/.claude-plugin/plugin.json#81)
（`PreToolUse` / matcher `Agent`），薄壳是
[pre-tool-use-keeper-instance.sh:30-31](file:///C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/task-keeper/hooks/pre-tool-use-keeper-instance.sh#30)。

读侧（被幽灵污染的消费者）：
[keeper_paths.py:356-382](file:///C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/task-keeper/hooks/lib/keeper_paths.py#356)
的 `live_instances`，经
[debug_keeper_inject.py:132-150](file:///C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/task-keeper/hooks/lib/debug_keeper_inject.py#132)
的 `peers()` 注入给每个 keeper，以及 `keeper_routing.py` 每轮注入给主会话。

现有的收敛机制拦不住它：
[keeper_paths.py:398-424](file:///C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/task-keeper/hooks/lib/keeper_paths.py#398)
的 `_prune_instances` 只按 `INSTANCE_TTL_DAYS = 14` 天与每档 30 条截断——对一条
14 秒前写入的幽灵条目完全无效。会话隔离（`session_id` 比对）同样无效：幽灵与真实
实例的 `session_id` **相同**。

### 规格依据

| 来源 | 命中 | 内容 |
|---|---|---|
| 设计文档（README「keeper 实例登记」章） | 命中 | 见下方摘录 |
| 代码内规格（`keeper_instance_register.py` 模块头） | 命中 | 见「问题」节摘录的错误假设 |
| 治理规格 `.claude/rules/project/hook-restraint.md` | 未命中 | 该文件第 280 行自述「约束的是**拦截类** hook」，本 hook 是纯副作用 hook，不在其管辖内 |

[README.md:270-276](file:///C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/task-keeper/README.md#270)
把「注册表里存在不可唤醒的 name」这件事明确定性为**本机制要消除的失败模式**：

> 若无这层隔离，新会话第一次转任务时主会话会读到上一个会话的死 name，`SendMessage`
> 报 `No agent named ... is reachable`，按"唤醒不到就重派"的错误反应会直接又派第二个
> 实例，两个实例抢同一个队列目录的独占写权限——这正是登记机制本来要消除的失败模式，
> 在跨会话场景下原样复活了一次。

本条是同一个失败模式的**第三次复活**：v6 是覆盖式写入导致实例失联，2026-08-05 是跨
会话死 name，本条是同会话内的幽灵条目。规格给出了明确期望（注册表条目必须对应可唤醒
的实例），实现没达到 → `spec_status: violation`，不是 `gap`。

### 依赖假设清单

以下三条是**假设**，修复方案的可行性直接取决于它们，已派 `claude-code-guide` 查证
官方文档，结论未回前不派 fixer：

1. **（假设）** 同一 `PreToolUse` 时机点上各插件的 hook 相互独立执行，任一 hook 的
   deny 不会短路其余 hook、也不会回滚其副作用。——本条已有强实证（幽灵条目的存在
   本身），但「并行还是串行」「有无短路机制」仍需文档确认。
2. **（假设）** `PostToolUse` 只在工具**真正执行过**之后触发；被 deny 的调用不产生
   `PostToolUse`。若成立，它就是天然满足「Agent 确实创建成功之后」的注册时机。
3. **（假设）** `SubagentStart` 的 payload **不含**该 subagent 的 `name`。
   [debug_keeper_inject.py:229-241](file:///C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/task-keeper/hooks/lib/debug_keeper_inject.py#229)
   只读 `hook_event_name` / `agent_type` / `cwd` / `session_id` 四个字段，测试 harness
   [harness.sh:130](file:///C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/task-keeper/hooks/tests/lib/harness.sh#130)
   也只构造这四个——但「现有代码没读」不等于「payload 里没有」，需文档确认。

### 验证章节（修复后必须逐条实测，不得只验首个）

- **场景 A（本条主症状）**：派发一个会被 agent-dispatch deny 的 keeper（如
  `name="sonnet-debug-keeper-xxxx"` + `subagent_type="task-keeper:debug-keeper"`）
  → 注册表**不新增任何条目**。
- **场景 B（不得误伤正常路径）**：派发一个合规的 keeper（`opus-debugger-xxxx`）
  → 注册表正常新增该条目，含 `name`/`ts`/`session_id`/`issue` 四键。
- **场景 C（幂等性不得回归）**：同名重复派发 → 原地更新，不产生第二条。
- **场景 D（非 keeper 不登记）**：派发 `general-purpose` / `debug-fixer-*`
  → 不产生任何登记（现有测试 [76]/[77] 覆盖，不得回归）。
- **场景 E（连带缺口，见下）**：派发一个**不带 `name`** 的 keeper，被自动补名后放行
  → 注册表应当登记**补名后**的真实 name。当前实现在此场景下**完全不登记**。
- **场景 F（回归套件）**：`hooks/tests/run-tests.sh` 全绿，尤其
  `16-h21-keeper-instance-registry.sh` 与 `25-h30-multi-instance.sh`。

### 修复方向：三个候选与各自的失败模式

派发 prompt 要求回答「推迟注册 vs 预注册+回收」，两条都不是最优，补第三条：

**方案 A · 挪到 `SubagentStart` 注册**
成立前提是假设 3 被推翻（payload 含 name）。若 payload 不含 name，注册表将永远为空，
多实例寻址整体失效——**致命失败模式**。注意 keeper**自己拿不到自己的 name**
（`agents/debug-keeper.md` §0，已实测），所以不能让 keeper 自己调 `bind` 补登记，
那是循环依赖。

**方案 B · 保留预注册 + 过期/失败回收**
根本难点：`PreToolUse` hook **无法知道自己这次派发会不会被 deny**——deny 由本体在所有
hook 跑完后汇总。所以回收只能事后做，三个变体都有硬伤：
- *B1 短 TTL*：keeper 等 fixer 回执可能几十分钟不被唤醒，短 TTL 会把**活着的实例**
  删出注册表 → 主会话唤醒不到 → 误判重派 → 双实例抢写。**比原 bug 更严重。**
- *B2 pending 标记 + SubagentStart 确认*：SubagentStart 只为真实启动的 agent 触发，
  确是可靠判别信号；但若假设 3 成立（无 name），只能按「同 session + 同 kind + 最新
  pending」提升，并发派发时张冠李戴。且该变体内部已包含方案 A 的机制。
- *B3 唤醒失败即回收*：依赖主会话自觉，非机械判据，正是本仓反复吃账的失效形态。

**方案 C · 挪到 `PostToolUse(Agent)`（倾向选项）**
成立前提是假设 2。若成立则一次同时解决三件事：被 deny 的调用天然不触发、`tool_input`
仍带 `name`、且 `PostToolUse` 看到的应是**补名后**的入参，连带修好场景 E。
代价：注册时刻比现在晚一个工具往返，主会话在这之前无法唤醒——但主会话在拿到 agentId
之前本来就没有唤醒动机，窗口无实际影响。

**选型待假设 2/3 的查证结论回来后落定**，结论写进本节与「修订记录」。

## 修订记录

- 2026-09-19 登记并完成 triage。`spec_status` 判为 `violation`（规格依据见上）。
- 2026-09-19 **连带发现（另一条独立缺陷，不并入本条）**：keeper 派发若**不带 `name`**，
  agent-dispatch 会用 `hookSpecificOutput.updatedInput` 自动补名并放行
  （[agent-dispatch.js:394-401](file:///C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/working-discipline/hooks/guards/agent-dispatch.js#394)），
  而 task-keeper 的注册 hook 读的是**原始** `tool_input`，其中 `name` 缺失 →
  [keeper_instance_register.py:158-160](file:///C:/Users/momog/workspace/personal/claude-devkit-marketplace/plugins/task-keeper/hooks/lib/keeper_instance_register.py#158)
  直接 return，**该实例永不登记**。症状与本条相反（本条是多一条假的，那条是少一条真的），
  但同源于「注册跑在 PreToolUse、看不到派发的最终结果」。方案 C 可一并修好；若最终选了
  A 或 B，需单独登记一条。已按 `agents/debug-keeper.md` §4 上报主会话决定是否合并。
- 2026-09-19 **注册表无会话退出回收**（主会话指出）：被拒派发留下的条目会残留到
  `INSTANCE_TTL_DAYS = 14` 天后才被 `_prune_instances` 清掉，期间只能手工删。本轮那条
  即由主会话手工删除。方案 C 从源头消除该来源，故不再单独设计回收机制；若最终选 A 或 B，
  回收必须一并设计。
