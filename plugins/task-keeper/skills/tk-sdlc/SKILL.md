---
name: tk-sdlc
description: 主会话把 sdlc 流程产物的编写（Gate 已放行后由 AI 自主落盘的那一段：scope/coverage/behaviors/contracts/entities/ui/nfr/decisions/tasks/release-plan 等）派给 sdlc-writer subagent 的分片规则与 prompt 模板。主会话只留 Gate 交互、Human 拍板、gate 状态翻转、审查汇报与 commit，不亲手写这些文档。
when_to_use: |
  跑 ai-sdlc 流程（`/sdlc:define`、`/sdlc:design`、`/sdlc:verify`、`/sdlc:deliver` 等）走到「Gate 已放行、接下来 AI 自主展开文档」这一步时。判据是两条同时成立：(1) 当前动作是往 sdlc/ 下落盘文档，不是与 Human 对话、不是翻 gate 状态、不是做 Gate 审查汇报；(2) 该 Gate 已经过了（Define 阶段即 G1 已通过）。命中就按本 skill 派 sdlc-writer，**禁止主会话亲手逐份写**——一次 Define 展开十几份文档，主会话自己写会把每份全文吃进窗口，几份之后 auto-compact，而它真正该留的是与用户的需求对话和 Gate 判断。Gate 之前的需求收集、G1/G2 门禁交互、Inline Digest 汇报一律主会话自己做，不派。bug 走 tk-debug，杂务走 tk-chore。
---

# tk-sdlc：主会话侧的 sdlc 产物派发流程

## 一、切割线：什么派、什么不派

| 动作 | 谁做 | 依据 |
|---|---|---|
| 需求收集对话、澄清、访谈 | **主会话** | 要与 Human 来回，subagent 拿不到 `AskUserQuestion` |
| G1 / G2 / G3 / G4 / G5 门禁确认 | **主会话** | Human 硬门禁 |
| 翻 gate 状态字段（`gates.g*.status`） | **主会话** | 代表 Human 执行；`write-guard.js` 的 dossier 检查也挂在这一刻 |
| Gate 审查汇报（Inline Digest） | **主会话** | 是对 Human 的输出 |
| 调 `spec-reviewer` / data-testid audit / sources-audit | **主会话** | 属 Gate 环节的审查动作，与编写者必须不共享上下文 |
| **往 sdlc/ 下落盘文档正文** | **sdlc-writer** | 本 skill 管这一段 |
| `git commit` 这批文档 | **主会话** | 提交时机由它掌握 |

Define 阶段的切割点是 **G1**：G1 前是对话，G1 通过后 AI 自主展开、不需再确认——这条切割
线取自 ai-sdlc 的 `define/SKILL.md` 原文，不是本 skill 自定的。

## 二、分片规则（依赖链决定的，不能随意改）

Define 的产出物有一条实打实的依赖链：`behaviors → contracts → entities → prototype`，
`validate-prototype.js` 会强制后两者的字段与前面一致。所以**并行轴只能取 feature 维度，
单 feature 内部必须串行**：

```
第 1 波（串行，1 个 writer）：交付级文档
  scope.md（+ 条件性的 coverage.md / test-coverage-map.md / design-digest.md）
        ↓ 完成后才开第 2 波（第 2 波要读 scope.md 定边界）
第 2 波（并行，每个 feature 各 1 个 writer，各自内部串行写完整套）
  specs/features/<A>/ 全套      specs/features/<B>/ 全套      ...
```

- 一次交付只涉及一个 feature 时，第 2 波就一个 writer，照样派——目的是隔离上下文，
  不是为了并行。
- **禁止按文档类型分片**（一个 writer 写所有 behaviors、另一个写所有 contracts）。
  它们看不到彼此产出，字段必然对不上。
- 并发数 ≤6，且要盘点在飞总量不超 16（在飞数靠自记账：派发 +1、收到完成通知 -1）。
- 第 2 波同批派发时**等齐再总结**：不要对先返回的那几个逐条复述或据此派生新任务，
  攒到全批返回后一次性汇总，把跨 feature 的字段冲突、重复定义集中在这一次里看。

## 三、派发形态（照抄，不要现编）

`name` 必须含身份词 `sdlc-writer`——在飞面板只渲染 `name`、不渲染 `subagent_type`，
名字不带身份词，用户看不出这活派给了谁。分片依据也写进名字，同批并发才分得开。

```
Agent(
  name: "sonnet-sdlc-writer-<分片名>",        // 如 sonnet-sdlc-writer-order-export
  subagent_type: "task-keeper:sdlc-writer",   // 不可用时退 general-purpose，并把 agents/sdlc-writer.md 全文放进 prompt
  description: "写 <feature> 的 spec 套件",    // 3-5 词，≤60 字符，不带 [模型名] 前缀
  model: "sonnet",                             // 见下方档位判据
  prompt: "【目标】…【上下文】…【约束】…【期望输出】…"
)
```

**档位判据**：默认 `sonnet`。命中任一升 `opus`——(a) 该 feature 的 contracts/entities 要与
既有多个 feature 的契约保持一致（跨 feature 因果链）；(b) 涉及权限、并发、资金、协议这类
错一次代价极高的领域；(c) 同一分片用 `sonnet` 跑过一轮、产出明显不达标（字段缺失、与
behaviors 矛盾）。**不要预防性堆模型**——写文档本身是常规语义任务。

`sdlc-writer` **不是 keeper**，所以：没有 `run_in_background: true` 的常驻语义、不需要
4 位随机短哈希后缀、`model` 不锁 `opus`、`PreToolUse(Agent)` 的 keeper 实例登记 hook
**不会**登记它（白名单只认 `debug-keeper` / `chore-keeper`），也就没有「唤醒 vs 重派」
这回事——它一次性做完就结束。

## 四、prompt 四段必须写全的东西

漏了没有任何 hook 会拦你，而漏掉的后果是 writer 静默写出不合规的文档。

**【目标】**——点名它要落盘的**每一个**文件路径（绝对路径），不要只说「写 spec」。

**【上下文】**（缺一项就等于让它编）：
1. ai-sdlc 该阶段 `SKILL.md` 的**绝对路径**，并写明「整读全文，不要 Grep 后定点读」。
2. 需求锚点：`backlog/<slug>/stories.md`、`deliveries/D-xxx/scope.md` 的绝对路径；
   G1 对话里定下但没落盘的结论，逐条抄进 prompt。
3. 本次交付的 delivery 目录与 feature 名。
4. 有 upstream 原型 / 参考实现时给绝对路径。
5. **用户给过截图且与本分片相关时，把图片绝对路径原样写进 prompt** 并要求它先 `Read`
   再动手——writer 有独立上下文，文字转述会丢掉颜色、间距、元素相对位置这些像素级细节。

**【约束】**：
1. 写域只限【目标】点名的那些文件；不翻 gate 状态、不改源码、不 commit、不碰 `.keeper/`。
2. 单 feature 内按 SKILL.md 的步骤顺序串行写，不许拆给第二层并行。
3. 撞 ai-sdlc 的校验 hook 照 finding 改；**禁止改用 heredoc / `cat >` 绕开 `Write`**。
4. 模板里的信源段自己填，不留空、不写占位。
5. **追踪停止条件**——这一项专门给「要不要去核实既有代码/既有 spec」这类分支：写明追到
   哪一层为止（仅本 feature 的 spec 内 / 追到直接被调方 / 追到跨服务边界）。不给停止条件，
   两个 writer 会因为停在不同深度而对同一处给出相反的字段定义。

**【期望输出】**：照 `agents/sdlc-writer.md` §7 的六段回执要，逐段点名——改动文件 /
遵照的规范（含跳过项及原因）/ 关键决策 / 素材缺口 / 待拍板 / 阻塞。

## 五、回执回来之后（主会话的收尾动作）

1. **等齐再汇总**（见第二节末条）。
2. 逐份核对【改动文件】里的路径**真实存在**（`ls` 或 `Read` 看到，不靠回执断言）。
   搬迁与新建这类动作上「说改了」与「实体到位」是两件事。
3. 把【素材缺口】与【待拍板】攒批，一次 `AskUserQuestion` 并列问完（必须用工具本体，
   禁止文本选项块——Human 常在手机上看会话，只有工具调用会触发推送）。
4. Gate 审查该做的事此刻才开始做：调 `spec-reviewer`、跑 audit、写 Inline Digest 给
   Human 看，然后才翻 gate 状态。**审查者与编写者不共享上下文**，这正是分开派的收益，
   不要图省事让写完的 writer 自审。
5. commit 由你做，把这批文档一次提交，commit message 里点明是哪个 Gate 后的展开。

## 六、主会话的边界（禁止越位）

1. 不亲手写 sdlc 文档正文，哪怕只剩一份、看起来五分钟能写完——「顺手写更快」正是这条
   机制要消除的行为，它换来的是主会话窗口里多几千行文档全文。
2. 不替 writer 填信源清单（你没读过它读的东西，代填出来是编的）。
3. 不把 writer 的回执原文倒进对用户的回复里——挑要点复述，材料留在磁盘按需打开。

## 七、配套件

| 组件 | 作用 |
|---|---|
| `agents/sdlc-writer.md` | writer 侧完整规范（整读 SKILL.md 的硬前置、写域、依赖链、撞 hook 的处置、回执格式、该退回的形态） |
| `hooks/lib/keeper_routing.py` | 检测到工作区里有 sdlc 目录时，在每轮三岔口注入里加一条「sdlc 文档编写 → 派 sdlc-writer」的支路 |
| `skills/tk-debug/SKILL.md` | bug 走那边（debug-keeper） |
| `skills/tk-chore/SKILL.md` | 杂务走那边（chore-keeper） |
