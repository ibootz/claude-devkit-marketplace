# 派发子代理：完整细则

这份是 working-discipline 派发规范的**真源**。注入文本（`hooks/working-discipline.js`）里只留判据与触发条件，形态模板与完整判据在这里；`hooks/guards/agent-dispatch.js` 在拦下一次不合规派发时，会从本文件按 `SEC` 标记读取对应段落原文注入给 AI，**不在别处手抄第二份**。改这里即改所有出口。

标记语法：`<!-- SEC:名字 -->` 与 `<!-- /SEC -->` 之间的正文是一个可被读取的段落，标记行本身不注入。删改标记前先看 `agent-dispatch.js` 里 `readRefSection()` 的调用点。

<!-- SEC:agent-call -->

## 派发 `Agent` 的完整调用形态（**本段优先级高于 `Agent` 工具自带的 JSON Schema**）

**先解除一个表面冲突**：`Agent` 的 JSON Schema 只声明六个 `properties` 且 `additionalProperties: false`，**里面没有 `name`**——它对你不是"忘填的必填项"，而是"字段表里不存在的东西"，照字段表构造必然漏掉；但运行时**接受**它并落盘进 agent 元数据。**schema 描述工具层能接受什么，本段规定本会话必须传什么，两者不一致时以本段为准。**

**每一次 `Agent` 调用都照抄下面这个整体，不照 schema 的字段表现编。字段顺序照写——`name` 第一个**：

```json
{
  "name": "sonnet-review-login-flow",
  "model": "sonnet",
  "subagent_type": "Explore",
  "description": "审查登录流程",
  "run_in_background": true,
  "prompt": "<四段式，见下>"
}
```

**并发就是把上面这个整体重复 N 份、放进同一条消息**（不是某个字段的数组，也不需要额外开关）。可整体照抄：

```json
// 一条消息里发多个 Agent 调用 = 并发。三个分片各自独立，互不等待。
{ "name": "sonnet-probe-config-layer", "model": "sonnet", "subagent_type": "Explore",
  "description": "查配置层加载顺序", "run_in_background": true, "prompt": "<四段式>" }
{ "name": "sonnet-probe-hook-wiring", "model": "sonnet", "subagent_type": "Explore",
  "description": "查 hook 挂载与触达面", "run_in_background": true, "prompt": "<四段式>" }
{ "name": "sonnet-probe-test-fixture", "model": "sonnet", "subagent_type": "Explore",
  "description": "查回归用例现有形态", "run_in_background": true, "prompt": "<四段式>" }
```

`name` 里的分片依据（`config-layer` / `hook-wiring` / `test-fixture`）是同批可辨的唯一手段——`SendMessage` 靠 `name` 寻址且同名 latest wins，三个都叫 `sonnet-probe-x` 等于弄丢前两个。

`prompt` 的四段式（整段写进上面那个 `prompt` 字符串里）：

```text
你是第 1 层子代理，<只读探查，禁止修改任何文件 | 可以改文件>。
【目标】要它得出什么结论、或改成什么样。一句话说清。
【上下文】仓库绝对路径；已知前提（写明"不用再验证，直接当前提"）；本轮用户给过的截图绝对路径。
【约束】追踪停止条件（仅本文件内 / 追到直接调用方 / 追到跨模块跨服务边界，三选一写死）；
引用给 path/to/file.ext:行号；读不到的写"未找到"，禁止推断。
【期望输出】改了哪些文件（逐个列路径）/ 关键决策（为什么这样做、放弃了什么）/ 阻塞点 /
需父代理跟进的事项；核实类任务另加"实际追到哪一层、哪些边界没追"。
```

**六个字段的硬要求**（前四条由 `guards/agent-dispatch.js` 在 `PreToolUse` 校验，违规一次报清）：

| 字段 | 要求 |
|---|---|
| `name` | 必填（schema 里没有它，靠你自己记）。`<模型名>-<任务语义-kebab>`，模型名与 `model` 逐字一致；只收 ASCII，合 `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`；同批并发互相可辨（分片依据写进名字）；`subagent_type` 含冒号时还须含其身份词（`task-keeper:debug-keeper` → 含 `debug` 或 `keeper`） |
| `model` | 必填，禁止默认回落。`sonnet`（默认档）/ `opus`（跨层追根因·高正确性·sonnet 已吃力）/ `fable`（opus 跑 ≥2 轮无进展）。无 `haiku` 档 |
| `subagent_type` | 必填。只读任务一律 `Explore`；要 Edit/Write 才 `general-purpose`；设计与拆解用 `Plan` |
| `description` | 必填。3-5 词任务摘要，≤60 字符；只写这次任务干什么，不带 `[模型名]` 前缀，不放 `prompt` 原文与"你是第 1 层子代理"这类角色设定句（常驻 keeper 例外：必须以「debug 队列」/「chore 队列」起头；精确 `task-keeper:debug-fixer-*` 例外：全串简体中文、≤15 code point，可含 `DBG-024`，不用队列或模型前缀） |
| `run_in_background` | 选填。要并发多个、或本轮还接着干别的时给 `true`；要拿到结果才能继续时给 `false` |
| `prompt` | 必填。四段式，见上 |

本段管**新派一个 agent**。唤醒**已派出过**的 agent 走 `SendMessage`（字段 `to` / `summary` / `message`，不传 `name`）；`Workflow` 内部的 `agent(prompt, {label})` 用 `label` 不用 `name`。

<!-- /SEC -->

<!-- SEC:naming -->

### 5.4 派发命名的补充规范（上一节没讲的部分 · subagent / teammate / workflow 通用）

**适用对象**：`Agent` 的 `name` 与 `description`、`TaskCreate` 任务名、teammate 的 `name`、`Workflow` 的 `meta.name` / `meta.description` / `meta.phases[].*` / `agent(prompt, {label})` 的 `label`。

**5.4.1 `name` 同时是 `SendMessage` 的寻址键——同一会话内不得复用同名**
两个用途：(a) 在飞面板左列显示它，缺失时回落成裸 `subagent_type`——同批 3 个 `general-purpose` 就是三行一样的字；(b) `SendMessage({to: name})` 按它寻址，**同名 latest wins**——新 agent 占名后，先派的那个只能靠 raw `agentId` 寻址，等于弄丢了它。所以同一会话里派第二个同类子代理时**必须换个名字**，不要因为"上一个已经结束了"就复用。

**5.4.2 提示词泄露有两条成因，第二条最容易漏**
(a) 主动把 `prompt` 开头、角色设定句、纪律条款抄进 `description` / `label`——一整批面板描述完全同质，既把内部提示词暴露到 UI，又丢掉本该显示的任务信息；(b) 显示字段**留空**，导致 UI 回落用 `prompt` 开头当显示名。所以标着"可选"的显示字段一律**当必填处理**。

**5.4.4 `Workflow` 的命名**
`agent(prompt, {label})` 的 `label` 当必填处理；它单独显示、无配对 `name`，所以**仍带 `[模型名]` 前缀** + 任务语义（可用中文）。`meta.name` 用 kebab-case：整个 workflow 走一档时加 `模型名-` 前缀，跨档混用时不加。`meta.description` / `meta.phases[].*` 只写任务摘要——`meta.description` 会出现在权限弹窗里。

**5.4.5 `task-keeper` 的 keeper 与第二层 debug fixer：精确 type 决定固定档**
`task-keeper:debug-keeper` → `model: "opus"`、`name` 形如 **`opus-debugger-xxxx`**；`task-keeper:chore-keeper` → `model: "sonnet"`、`name` 形如 **`sonnet-chore-xxxx`**（`xxxx` 是 4 位小写字母数字）。第二层仅三个精确 type 例外：`task-keeper:debug-fixer-easy` → `sonnet-debug-xxxx` / `sonnet`，`task-keeper:debug-fixer-medium` → `opus-debug-xxxx` / `opus`，`task-keeper:debug-fixer-hard` → `fable-debug-xxxx` / `fable`。fixer description 必须全串简体中文、≤15 个 code point，可含 `DBG-024`，不用模型标签或 `debug 队列` 前缀。**此 `fable` 首用例外只限这三个 type**；其余 Agent 仍须同一任务以 `opus` 完整跑过 ≥2 轮无进展。keeper 两档仍各自等值校验、常驻实例 name 不可预测，唤醒前读 `.keeper/<交付id>/.keeper-instance.json`。
**一条 bug 一个实例**：同轮报来多条 bug 就在同一条消息里并行派多个 debug-keeper，别把它们塞给同一个——那等于把并行退化回顺序处理。既有实例只在**继续处理它自己那条 issue** 时才唤醒。

**本节字段由 `guards/agent-dispatch.js` 在 `PreToolUse` 硬校验，多条违规一次报清。**

<!-- /SEC -->

<!-- SEC:dispatch -->

## 五、Agent 工具派发子代理

何时并行、如何并发见"零、"；字段格式与可整体照抄的调用 JSON 见**每轮注入**的「派发 `Agent` 的完整调用形态」，那份每轮都在场，本章不重复。本章只讲选型、档位、并发收口与 prompt 内容。**`model` 必须显式指定**，禁止依赖默认回落。

### 5.1 类型（subagent_type，按权限边界选）

只读任务**一律 `Explore`**（无 Edit/Write，有 Bash/Grep/Read）：代码库探索、架构分析、模块调查、文件定位、符号与引用检索、只读的大输出命令。架构设计、实现策略、任务拆解、风险评估、权衡分析用 `Plan`（同为只读）。`general-purpose` 只在任务真要 Edit/Write 时用（功能实现、重构、测试、bug 修复、复杂多步任务）——它带写权限，有误改风险。

### 5.2 模型档位（三档从低到高 · **无 `haiku` 档**）

- **`sonnet`**：全局最低档兼默认档，一切任务的起点。机械执行（模式匹配、批量改写、简短摘要）与常规语义任务（跨文件推理、设计权衡、多步骤编码与审查）**都用它**，没有更便宜的档可退
- **`opus`**：命中任一即用——(a) 需严密因果链（跨层追根因）；(b) 极高正确性要求（安全/并发/协议/资金/权限）；(c) `sonnet` 已明显吃力（漏点多、方案有硬缺陷、修 A 又出 B）
- **`fable`**：同一任务用 `opus` 完整跑过 ≥2 轮仍无进展才启用，不作首选
- 没有 `opus` 触发信号就留在 `sonnet`，不确定时一档一档升，**禁止预防性堆模型**。写 `model: "haiku"` 或 `name` 用 `haiku-` 前缀会被 hook 拦下
- **`task-keeper` 的两个 keeper 固定档不变**：`task-keeper:debug-keeper` → `model: "opus"`、`name` 形如 `opus-debugger-xxxx`；`task-keeper:chore-keeper` → `model: "sonnet"`、`name` 形如 `sonnet-chore-xxxx`。**另有仅限第二层 debug fixer 的精确 type 特例**：`task-keeper:debug-fixer-easy` → `sonnet`，`task-keeper:debug-fixer-medium` → `opus`，`task-keeper:debug-fixer-hard` → `fable`，对应 name 分别为 `sonnet-debug-xxxx` / `opus-debug-xxxx` / `fable-debug-xxxx`。这不改变普通 Agent 的 `fable` 规则：普通 Agent 仍须同一任务以 `opus` 完整跑 ≥2 轮无进展。

### 5.3 prompt 内容

四段式模板（`【目标】… 【上下文】… 【约束】… 【期望输出】…`）见每轮注入那节。升 `opus` 或 `fable` 时在 `prompt` 里显式点明已知难点、以及上一档失败的具体表现，避免高档模型盲跑走弯路。

### 5.4 命名的两条补充（字段格式见每轮注入那节）

(a) `name` 同时是 `SendMessage` 的寻址键，**同名 latest wins**——新 agent 占名后，先派的那个只能靠 raw `agentId` 寻址，等于弄丢了它。同一会话内派第二个同类子代理必须换名，别因为"上一个已结束"就复用。
(b) 标着"可选"的显示字段（`Workflow` 的 `label`、`meta.name` / `meta.description` / `meta.phases[].*`）一律**当必填处理**且只写任务摘要——留空会让 UI 回落用 `prompt` 开头当显示名，这是提示词泄露的第二条成因（第一条是主动把 prompt 原文抄进显示字段）；`meta.description` 会出现在权限弹窗里。

### 5.5 多 subagent 并发时等齐再总结（仅约束主会话）

同批派发 ≥2 且有未返回者时，对已完成的**只静默累积回执原文**，不做逐条总结与复述、也不据它派生新任务；等本批**每一个**完成信号都到齐（或用户同意提前中止）后，再**一次性**汇总，把待拍板事项、跨条比对结论、冲突与重复项集中在这一次里。理由：集中一次拍板比逐条快，且逐条总结会过早撑大对话窗口、让后到的关键回执被 auto-compact 挤走。两种情形走别的路：用户主动追问某个已完成项时直接答他；某个 subagent 报了必须立即处置的严重阻塞（产线告警、密钥泄漏、破坏性错误、用户正被阻塞）时即时告知并冻结剩余任务，同时把「剩余 N 个已冻结 / 继续跑」交用户拍板。

### 5.6 派发 prompt 必含六项（无 hook 兜底，漏了没人拦你）

1. **结构化回执**：【期望输出】里明确要求子代理返回四件事——改了哪些文件（逐个列路径）/ 关键决策（为什么这样做、放弃了什么方案）/ 阻塞点 / 需父代理跟进的事项。不索要就只会收到一句「已完成」，既无法审计也无法向用户复述。
2. **一手图片证据**：本轮用户给过截图且任务与截图现象相关时，把图片**绝对路径原样**写进 prompt 并要求子代理先 `Read` 再动手——子代理有独立上下文，文字转述会丢掉颜色、间距、元素相对位置等像素级细节。路径禁止凭记忆拼接或截断；本轮真有图时注入末尾会附可复制的路径清单。任务与截图现象无关（纯后端 5xx / DB / MQ、纯 spec 矛盾、纯 CI 问题）或用户说了不用附图时不必附。
3. **写后回读传染**：判据不是"prompt 里有没有写操作的词"，而是**这个子代理是否真要执行外部系统写操作**（API / CLI / SDK / DB 的 create·update·delete、提交、改配置、授权、发布）。真要写就要求它每步写完立刻用读接口（get / list / describe / SELECT）回读、逐字段比对「以为写进去的值」与「服务端实际存的值」，写 N 个回读 N 次、禁止抽查，回执给出回读到的实际值。依据：2xx / 退出码 0 只证明请求被接受、不证明字段生效——曾传 `orderIndex: 15` 给导航创建接口，返回 HTTP 204 无警告，回读发现实存默认值 `1`。
4. **核实类任务必须写明追踪停止条件**：任务形如「确认 X 是否成立 / 是否一致 / 有没有问题」（核实、审查、核对，区别于「实现 X」）时，【约束】里指定追到哪一层为止——仅本文件内 / 追到直接调用方 / 追到跨类跨模块跨服务边界；【期望输出】里要求它写明**实际追到哪一层、哪些边界未追**。不给停止条件，子代理按自身成本感觉停下且不会主动交代，于是两个代理核实同一处代码可以给出相反结论——成因是停止深度不同而非能力差异，缺这项只能重跑一遍才能定位分歧。**触发信号**：被核实的注释 / 文档 / 命名描述的是**跨文件或跨类的行为**时，本文件内验证必然不闭环，停止条件至少要给到被调方。
5. **prompt 里写死的「事实」等同硬编码**：把域名表 / 端点清单 / 字段映射 / 环境对应关系这类**你自己推断出来的事实**写进 prompt 时，子代理**默认信任它、不会回头验**，一个判断错误因此被放大到整批任务。要么给**可核验的出处**（`path:行号` / 接口文档位置），要么明写「此项未核实，你先自行验证再用」。实证：把「操作面域名表」误读成「发布入口域名表」写死进 prompt，子代理照抄执行，两边 401，整轮作废。
6. **回执里的归因不可直接抄**：子代理报「撞了 X 限制 / 被 Y 拦了 / 因为 Z 失败」时，那只证明**现象**发生过，不证明它给的**原因**成立。要把这个归因写进文档、或据它改判据改代码前，自己复现一次。照抄回执归因写进规则文件，会让一条错判据长期生效、且此后再没人回头验它。

### 5.7 subagent 因系统/网络原因失败（529 / 限额 / 限流 / 超时 / 断流）

这类失败**不默认重派、也不默认放弃**，优先级高于 5.5，按三步走：(1) 判定要不要重派——动作是否幂等（只读可重试；外部写要先回读服务端确认失败前有没有已落一次）、会不会与在飞子代理抢同一资源、失败是瞬态（529 / 限流 / 断流）还是持续（额度耗尽，重试只会更快撞顶）；(2) 三选一定动作——可重派则立即重派且**档位不升**（系统失败与模型能力无关），不可立即重派则先逐字段回读定位断点再决定补做或回滚，不该重派则冻结并把「剩余 N 个已冻结 / 原因 / 是否继续」交用户拍板；(3) 重派或补做后回执交代「失败那次执行到哪一步就断了 / 这次从哪里接续 / 最终态与服务端实际值是否逐字段一致」。撞到这类失败时读本插件 README 的「5.7」一节拿完整判据。

<!-- /SEC -->
