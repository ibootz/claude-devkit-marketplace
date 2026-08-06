---
name: tk-decisions
description: keeper（后台 subagent）与 Human 之间的决策打包 HITL 协议正典：keeper 把待拍板事项写 `.keeper/<交付id>/decisions/` 文件 + SendMessage 一句话通知，主会话攒批后一次 AskUserQuestion 并列问完，答复原文写 `answers/` 回传。解决「subagent 永远拿不到 AskUserQuestion」与「逐条弹框打断用户」两个问题。
when_to_use: |
  主会话收到 keeper 的 SendMessage 待拍板通知、每轮注入出现「待拍板 N 条」、用户问"有什么要我拍板的"、交付停顿点自查、或任何 keeper 报了需要 Human 决定的事项时。keeper 侧写决策文件的完整规范也在本文件（keeper 的 agent 定义里有摘要）。
---

# tk-decisions：决策打包 HITL 协议

## 为什么存在

1. harness 事实（2.1.220 二进制取证）：`AskUserQuestion` 对所有 subagent 是永久
   黑名单，keeper 无法直接问用户；后台 subagent 可以 `SendMessage(to:"main")`。
2. 体验事实：keeper 每遇一个决策就打断用户一次，比没有 keeper 更糟。所以决策
   **打包**：磁盘攒批、一次问完、答复分发。
3. 可靠性事实：SendMessage 会被 auto-compact 挤出主会话上下文，磁盘文件不会——
   文件是信道真身，SendMessage 只是铃铛；每轮 hook 注入的「待拍板 N 条」计数
   由磁盘现算（hooks/lib/decision_inbox.py），是不依赖对话记忆的兜底。

## 通道与写者（一文件一写者，天然免锁）

| 路径 | 写者 | 内容 |
|---|---|---|
| `.keeper/<交付id>/decisions/<stamp>-<keeper>.md` | 该 keeper | 待拍板事项全文 |
| `.keeper/<交付id>/decisions/answers/<同名>.md` | 主会话 | 用户答复原文 |

`<stamp>` 用 UTC 紧凑时间戳（如 `20260731T083015Z`），文件名排序即时间序。
裁决落地后**两个文件都由 keeper 删除**（见流程第 5 步），目录里只留未决事项。

## 决策文件格式（keeper 写）

```markdown
---
from: chore-keeper          # 写者名，也是答复要送回的 SendMessage 目标
about: CHR-014              # 关联的队列条目 id，没有就写 "-"
kind: external-write        # external-write 外部写授权 / conflict 冲突让位 / scope 范围取舍 / other
blocking: true              # true = 冻结 about 指向的那一条 issue，keeper 继续处理队列其他条目；false = 不急
options:                    # 2-4 个选项，每个一句说明；自由回答类可省
  - "A：现在就发，全文见正文"
  - "B：改到下个窗口再发"
recommend: A                # keeper 的推荐，可省
---

正文按工作纪律 3.3 讲透：事情起源 / 现状与期望的差距 / 选错的影响 /
现场摘抄（外部写类必须含动作原文、目标对象、可逆性、回滚方法）。
```

## 流程（5 步闭环）

1. **keeper 写文件 + 打铃**：写好决策文件后 `SendMessage(to:"main")`，消息 ≤3 行
   ——一句摘要 + 文件路径，**不粘贴正文**（主会话按需打开，保持精炼）。
2. **主会话攒批，a/b 是硬约束、c/d 才是触发点**：
   a. **待拍板 ≥3 条**——命中即**必须**在本轮就走第 3 步问用户，不允许再攒、
      不允许推到下一个停顿点。
   b. **出现 `blocking: true`**（有 keeper 的某条 issue 冻在原地等这条）——命中即
      **必须**在本轮就走第 3 步，同样不允许再攒。
   c. 用户主动问「有什么要拍板的」——不足 3 条、也没有 `blocking: true` 时，用它
      主动清空积压。
   d. 交付/任务的自然停顿点——同 c，不足 3 条时的主动清空时机，不是阈值。

   **a/b 命中却继续攒的后果**：被冻的那几条 issue（`blocking` 的定义见下方——冻的
   是 `about` 指向的那一条，不是整条队列）在 keeper 那一侧原地不动，而新的 bug 还会
   持续报进来，待拍板队列只会越攒越厚。攒批的收益是「少打扰用户一次」，这个收益在
   3 条这个点上已经被「keeper 侧积压 + 待拍板还在继续增长」的成本盖过——所以 a/b
   不是「够了可以处理」的建议，是「够了必须处理」的硬约束。

   **什么时候不触发**：待拍板不足 3 条且没有任何 `blocking: true` 时，照旧只让计数
   攒着，不要为了凑够 c/d 的触发条件主动去问用户「有什么要拍板的」——那是用户或
   停顿点自己触发的时机，不是主会话该抢先做的事。
3. **一次 AskUserQuestion 并列问完**：逐个打开决策文件，把每条压成一个 question
   （header 用 about 的条目 id，options 照抄文件里的 options，正文要点进
   question 文字）。一次调用最多 4 问，超出分批、blocking 优先。
4. **答复原文回传**：把用户对每条的答复**原文**写 `answers/<同名>.md`（不改写、
   不概括），然后 `SendMessage(to: <from 字段的 keeper>)` 一句话通知「CHR-014 已
   拍板，见 answers/<文件名>」。
5. **keeper 落地留痕**：keeper 把裁决正文抄进对应队列条目文件（`.keeper/` 不入库
   且 decisions 文件即将删除，条目正文是唯一留痕处），执行裁决，然后删除
   decisions 与 answers 两个同名文件。

## 边界与禁忌

1. 主会话**不替用户拍板**，也不对 keeper 的推荐做二次加工——问卷忠实转述。
2. 主会话不写 decisions/ 根目录，keeper 不写 answers/——写者越位会造成竞态。
3. blocking 事项不攒批凑数：出现即触发第 3 步（可以只问这一条）。
4. AskUserQuestion 必须用工具本体，禁止用文本选项块代替（happy 手机推送只认
   工具调用，文本块不触发推送，用户在外面收不到任何提示）。
5. 答复分发后主会话即退出该事项——落地与留痕是 keeper 的职责，不要追踪重复确认。
