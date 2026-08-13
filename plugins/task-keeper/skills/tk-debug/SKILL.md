---
name: tk-debug
description: >-
  Debug 队列工程化处理（主会话侧入口）。把「Human 报 bug → AI 立刻派 subagent 修」
  改造成「主会话只转发 → debug-keeper agent 独立跑完登记/triage/派发/对账/收尾，
  自己直接并行派第二层 fixer subagent」的并行流水线。队列落在项目根
  `.keeper/<交付id>/debug/`（一 issue 一个目录，跨 session 持久；v6 起 issue 文本、
  receipts 与截图入库，只有 fixer worktree 等三类本机产物排除在外）。**主会话在本流程里只做三件事：截图落盘（如果用户附了图）→ 把原话转给
  debug-keeper → 立刻回到原任务。** 不做 triage、不写 issue 文件、不派 fixer、
  不对账，这些全部由 debug-keeper 在独立上下文里完成，避免打断主会话手上的工作。
when_to_use: |
  用户报 bug / 缺陷 / 报错 / 白屏 / 崩溃 / 数据不对 / 点了没反应，或说「登记这个
  问题」「triage 一下」「这条插队」「启用 debug 队列」「这些 bug 一起修」，或在
  verify 阶段发现 in-scope 缺陷需要排期修复时，必须用这个 skill。**禁止绕过队列
  直接派 subagent 修 bug**——「收到即派发」正是本机制要消除的行为。项目根还没有
  `.keeper/<交付id>/debug/` 时也走这里（由 debug-keeper 负责冷启动初始化）。
---

# Debug 队列（主会话侧 · 你只做三件事）

## 0. 职责边界：为什么主会话几乎什么都不做

用户报 bug 的时刻，主会话大概率正在做别的任务。让主会话承担整条流水线里的绝大部分
（登记、triage 派发、写队列、对账、收尾），后果是：主任务被打断、上下文被队列细节
撑大、bug 处理与主任务串行而非并行。

现在这些全部移到 **`debug-keeper` agent**（task-keeper 插件自带，
`agents/debug-keeper.md`）。它在独立上下文里跑完全流程，**包括自己直接调用
`Agent` 工具并行派发第二层 fixer subagent**（标准 `subagent_type` 路径不受嵌套深度
限制，debug-keeper 按常驻 agent 正常工作；撞到「具名 teammate 唤醒后再发起 `Agent`
调用被拒绝」这类报错时，先判断卡住的是哪条调用路径——teammate 路径还是标准
`subagent_type` 路径，不要一概而论）；需要用户拍板时它走 `agents/debug-keeper.md`
§12 的待拍板协议——写 `.keeper/<交付id>/decisions/` 文件 + `SendMessage` 指针通知，
不经过你转达正文。

**你只做三件事，按顺序**：

1. 用户附了截图 → 先落盘（§1，**只有你能做，keeper 看不到图**）
2. 把用户原话逐字转给 `debug-keeper`（§2）
3. 立刻回到原来在做的事（§3）

不要做的事：不判定优先级、不定位代码、不写 `.keeper/<交付id>/debug/` 下的文件、不派
fixer、不对账、不回「已登记 DBG-xxx，当前队列…」这类状态模板（§4 说明反馈从哪来）。

## 1. 用户附了截图：必须由你落盘，且必须回读验证

**为什么只有你能做**：图片以 base64 形式存在于**主会话的对话流**里，`debug-keeper`
是独立上下文的 subagent，拿不到这段数据。

**为什么必须当场做**：harness 给的源路径
`/Users/<me>/.claude/image-cache/<session-uuid>/<序号>.png` 是**会话级临时资源**，
实测只保留当前活跃会话的目录、会话一换整个目录消失，而 debug 队列是**跨 session
持久**的（等用户 accept、reopen 重修、收官时推迟到下次交付，登记与修复隔几天是
常态）。两者生命周期不匹配，队列里任何指向 `image-cache` 的路径**在下一个会话
必然 404**。已实测的失败案例：某会话 AI 宣布「截图先落盘」并执行了 `cp`，下一轮
才发现源文件已不存在——`cp` 静默失败没被察觉。所以**只看 `cp` 退出码不够，必须
回读验证**。

### 落盘流程（四步，一步都不能跳）

**第一步，取源路径：只能照抄消息里 `[Image: source: <绝对路径>]` 那段 `source:`
后面的原文，禁止按 `image-cache/<session-uuid>/<序号>.png` 的规律自己拼。** 猜出来的
路径必然失效（会话没贴过图 / 序号猜错），且假路径会一路写进 issue 的「证据」章节，
让后续会话把成因误报成「原图被临时清理了」，而真相是它从未存在过——排查方向就此
带偏，这是 DBG-006 的成因。消息里没有 `source:` 原文时的处置顺序见
`references/screenshot.md` §2（先 `ls` 枚举、再 `Read` 验证内容、仍不确定请用户重发；
枚举命令**不要挂 `2>/dev/null`**，会吞掉报错并被 hook 拦下）。

**第二步，落盘到 `_inbox/`（不是 `<DBG-id>/`）。** `DBG-id` 由 `debug-keeper` 分配
——`.keeper/<交付id>/debug/` 是单一写者，你自行预分配就出现第二个写者（hook 注入体里
那个「下一个可用 id」是给 keeper 用的，不是让你去建文件）。keeper 登记时会 `mv` 到
`.keeper/<交付id>/debug/<DBG-id>/` 并写进「证据」章节：

```bash
# ROOT 先跳出 submodule 再取当前 worktree 根；直接 --show-toplevel 在 submodule 里
# 会返回 submodule 根而不是宿主工作区根。判据与 hooks/lib/keeper_paths.py 一致。
SUP="$(git -C . rev-parse --show-superproject-working-tree)"
ROOT="$(git -C "${SUP:-.}" rev-parse --show-toplevel)"
DID="$(basename "$ROOT")"
case "$DID" in D-[0-9]*-*|hotfix-*) ;; *) DID="_main" ;; esac
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$ROOT/.keeper/$DID/debug/_inbox"
DST="$ROOT/.keeper/$DID/debug/_inbox/$STAMP-01-<简短英文或拼音说明>.png"
cp "<照抄来的源路径>" "$DST"
```

文件名带时间戳避免撞名，尽量用 ASCII（macOS 的 NFC/NFD 差异会让含中文的路径在
「一边来自 git 输出、一边来自磁盘枚举」的比对里静默匹配不上）。

**第三步，回读验证（关键，缺了这步等于没落盘）：**

```bash
[ -s "$DST" ] && echo "OK $(wc -c < "$DST") bytes" || echo "FAILED"
```

只有输出 `OK` 且字节数与预期相符才算成功。**输出 `FAILED` 或 `cp` 报错时立刻走
§1.1 兜底，不要重试同一个路径**——源文件已经不存在，重试只会重复失败。

**第四步，无论落盘成功与否，都要做文字转录**——报错文本原文、涉及的页面标题 / 菜单
路径 / 按钮文案、错位的具体元素、期望效果、图上可见的数值。理由：fixer 读文字比读图
快，且图仍可能因别的原因读不到（权限、路径含非 ASCII 字符、worktree 隔离），文字是
唯一不会丢的信息。转录与落盘路径一起写进转发给 keeper 的消息（§2 模板里有位置）。

### 1.1 第三步输出 `FAILED` 时怎么办

**不要重试同一个路径**——源文件已经不存在，重试只会重复失败。按
`references/screenshot.md` §3 走两条兜底：先试**从系统剪贴板抢救真实像素**
（`osascript` 读 `«class PNGf»`，只读不修改剪贴板，已实测可行；局限是只对最后一次
复制的内容有效，用户贴图后又复制过别的东西就取不到），再做第四步的文字转录。两条都
用不上时，在转发消息里明确写「**原图未落盘，原因：<具体原因>**」——**绝不要留一个
几天后必然 404 的假指针**，那比不留更糟，会让后续会话误以为「有图可看」。

### 1.2 图里可能含敏感信息时：不落盘

**截图与同目录的 `issue.md` 会进 git 历史、随 push 公开到远端**，所以「不落盘」是
**唯一那道拦得住敏感信息公开的机械闸**——你没有图像编辑能力、打不了码，闸只有这一道，
而 git 历史删不干净：即使之后 `rm` 掉文件，那次提交仍在。图里出现 token / cookie /
密码 / 密钥、手机号 / 邮箱 / 身份证 / 员工工号、真实客户机构名称、产线金额 / 成单
数据 / 用户明细时**不要落盘**。

**处置不是「打码后落盘」——你没有图像编辑能力，做不到打码。** 把打码写成指令等于要求
执行一个不可能的动作。正确处置是跳过落盘 + 只做文字转录（把敏感值本身替换成
`<脱敏>`，保留排查需要的结构信息）+ 在转发消息里写「图含敏感信息未入库，如需入库请
自行打码后重发」。拿不准时按敏感处理。完整判据见 `references/screenshot.md` §4。

## 2. 唯一动作：派出或唤醒 `debug-keeper`

**派发与唤醒机制（三岔口注入、name 生成、description 锚定、换代）见
`references/keeper-dispatch.md`，两 keeper 共用同一套，本文只写 debug 特异的判据。**
读 reference 时占位替换：`<keeper>`→`debug-keeper`、`<kind>`→`debug`、
`<prefix>`→`debug 队列`、`<正则前缀>`→`opus-debug-keeper`。

**`model` 固定 `"opus"`，不按 bug 看起来难不难来下调。** keeper 是第一层调度者，它做的
triage 打分、落点行区间、同根因判定、对账三件套误报识别，判错一次的返工成本由后面整条
流水线承担（理由详见 `agents/debug-keeper.md` §0）。**第二层才分档**——keeper 派 fixer
时按 `difficulty` 从 `sonnet` 起选，见 `references/queue.md` §4「模型分层」。

首次派发的 `Agent` 调用形态（三岔口注入说「首次派发」时照这模板填，name 自己生成
4 位随机短哈希、description 以 `debug 队列` 起头——完整规则与反模式清单见
`references/keeper-dispatch.md` §2/§3）：

```
Agent(
  subagent_type: "task-keeper:debug-keeper",   # 若该 subagent_type 不可用则退回 "general-purpose"
  name: "opus-debug-keeper-4bb6",   # 自己生成 4 位随机小写字母/数字后缀，不要逐字抄这个例子
  description: "debug 队列 · 关三条 + 开工 DBG-140",   # 前缀 `debug 队列` 不可省，之后写这一批接的活（不是当次单个动作）
  model: "opus",
  run_in_background: true,
  prompt: "【目标】接管本项目 debug 队列，按 agents/debug-keeper.md 的流程处理下述
            bug 报告，包括你自己直接调用 Agent 工具并行派发第二层 fixer subagent。\n
           【上下文】项目根：<git rev-parse --show-toplevel 的结果>。\n
            用户原话逐字如下：\n<原话逐字照抄，不要改写、不要总结>\n
            截图：已落盘 <_inbox 下的绝对路径>（登记时请 mv 到
            .keeper/<交付id>/debug/<DBG-id>/ 并写进「证据」章节）；图片内容
            转录：<文字转录>。\n
            〔若落盘失败则写〕原图未落盘，原因：<具体原因>；图片内容转录：<文字转录>。\n
           【约束】你独占 .keeper/<交付id>/debug/ 写权限；不要动业务代码；需要用户
            拍板时走 agents/debug-keeper.md §12 的待拍板协议，不要经过我传正文。\n
           【期望输出】按 agents/debug-keeper.md §13 的回执格式返回。"
)
```

**`description` 锚定 `<prefix>` 起头 + 这一批的摘要**：例如「debug 队列 · 关三条 +
开工 DBG-140」，不要写成某个具体动作（比如只写「修 DBG-140」就丢了同批的另外两条）。
完整机制（为什么前缀锚定而不是逐字固定串、面板渲染时机、check 11 拦下、向后兼容
旧固定串、与 §2.1 换代的"两条腿并用"关系）见 `references/keeper-dispatch.md` §3。

`run_in_background: true` 是必须的——它让 keeper 在后台跑，你不必等它，也让它具备
`SendMessage` 到 `main` 的能力。`name` 派发成功后 `PreToolUse(Agent)` hook 会自动
把它写进 `.keeper/<交付id>/.keeper-instance.json` 的 `debug` 键，你不需要自己再写
这个文件。

**此后每一次**（同一会话内再报 bug），用 `SendMessage` 唤醒同一个实例，**不要再派
第二个**——唤醒形态、读取真实 name 的等价命令、上下文跨唤醒保留的事实、"唤醒不到
就乱重派"为什么仍然禁止，见 `references/keeper-dispatch.md` §5。debug 侧的
`SendMessage` 消息体要把用户原话 + 截图路径 + 文字转录一起带过去（§1 落盘流程的
产物）。

### 2.1 换代：队列收口时新派一个实例

完整机制（hook 注入触发、五项条件、换代该怎么做、不需要作废登记、是否必须做）见
`references/keeper-dispatch.md` §4。debug 侧的条件就是该节列出的五项——第 5 项
「没有任何 `debug/<id>/worktree/` 目录残留」是 debug 专项，chore 侧没有。第 4 项
一票否决涉及 `agents/debug-keeper.md` §12.3 的裁决抄回收口动作——一旦换代会丢掉
这个收口能力，原因见 reference §4。

## 3. 转完立刻回到原任务

转发之后**不要等 keeper 回执**，直接继续你原来在做的事。keeper 是后台 agent，
它完成时你会收到通知，需要用户拍板时它会通过 `.keeper/<交付id>/decisions/` + `SendMessage`
指针找你——那时你只需要照 `agents/debug-keeper.md` §12.2 攒批转达、写答复，不需要
自己去猜决策内容。

## 3.1 keeper 因系统原因被终止时：唤醒它，处置权交回给它

判据是**非任务原因**的终止：`API 529 Overloaded`、限流、额度耗尽、网络超时、连接断流。
（keeper 自己回报"这条我判不了"属于任务内原因，走 §12 待拍板协议，不是本节。）

**你只做一件事**：先读 `.keeper/<交付id>/.keeper-instance.json` 的 `debug` 键取出
它现在的真实 name（这个场景是在同一次会话内发现自己刚派出的 keeper 被系统原因掐断，
登记的 `session_id` 必然与当前一致，不需要走 §2 那套跨会话比对），用 `SendMessage`
唤醒那个 name（**不是**字面量 `opus-debug-keeper`——name 带随机短哈希，凭记忆拼写
不出来），把"你上一轮因 <具体原因> 被终止"这个事实告诉它，然后回到原任务。它的
transcript 完整保留，会照 `agents/debug-keeper.md` §6.2 自己把在飞 fixer 收口。

**三件不许做**：

1. **不许凭产物 mtime 或「文件零写入」推断它派的 fixer 是死是活。** keeper 死了，它派的
   第二层 fixer **可能仍在跑**——2026-08-03 实测有一个在 keeper 死后继续工作了至少 9 分钟。
   mtime 停更无法区分"已终止"与"正在思考 / 正在跑长命令"。
2. **不许替它派 fixer、停 fixer、改 issue 文件。** 那次事故里主会话据错判派了第二个
   fixer，两个 `opus` fixer 同时写一个 worktree 的同一批文件。哪个 fixer 对应哪条 issue、
   该停该续，只有 keeper 知道。
3. **不许因为唤醒不到就新派一个 keeper。** `SendMessage` 报
   `No agent named '<x>' is reachable.` 说明你用的名字不对，不是它不在了——先检查
   有没有重新读一次 `.keeper/<交付id>/.keeper-instance.json` 取最新 name（name 带
   随机短哈希，凭记忆拼、或抄一份旧记录都可能对不上），或用首次派发返回的 agentId
   寻址。新派第二个 keeper 会让两个实例抢同一个 `.keeper/<交付id>/debug/` 的独占
   写权限（`working-discipline` 的 `agent-dispatch.js` check 10 现在会把自造名的
   keeper 派发直接拦下）。

**若你在读到本节之前已经对 fixer 做过动作**（停过、派过、改过文件），唤醒消息里必须
**逐条如实交代做了什么**，包括你当时的判断依据——不要只给结论。keeper 要靠这些信息
判断现在有几个 fixer 在飞、哪些产物是谁写的。

## 4. 反馈从哪来（不要自己汇报队列状态）

三条通道都不经过你手写状态：

1. `user-prompt-submit-debug-queue.sh` hook 每轮自动注入队列实时快照（open 各条的
   id + 优先级 + 是否在飞、done 计数、reopen 告警，一律现算不落盘）
2. `.keeper/<交付id>/debug/index.md` 由同一个 hook 重算，人类随时打开就能看全部 issue 一览
3. keeper 通过 §12 待拍板协议找你（decisions 文件 + SendMessage 指针）

用户问「debug 状态」「队列里还有啥」时**不必唤醒 keeper**，但要注意这两个来源的
新鲜度不同：**本轮注入体里那份快照是现算的，最权威**，优先用它回答；
`.keeper/<交付id>/debug/index.md` 是落盘文件，只在需要每条的摘要或链接时才读。两者同源
（共用 `hooks/lib/queue_files.py` 的分桶计算），正常情况下一致。

**不要手工编辑 `index.md`**（下一轮就被 hook 覆盖），也不要把它当数据源
（`.keeper/<交付id>/debug/` 下的文件才是）。发现 `index.md` 与注入体的 open 条数不
一致时，以注入体为准，并检查是不是撞上了「fixer 的 `DBG-*` worktree 里不重算」这条
规则——那是设计行为，不是 bug。

「谁在修哪条」这类在飞状态不在任何文件里——它由 `git worktree list` 现算，路径含
`DBG-\d+` 即在飞。要确认时跑 `git worktree list | grep DBG-`，不要去翻 issue 文件
找状态字段（frontmatter 里只有 `open` / `done` 两个值）。

## 5. 什么时候不触发本 skill

- 用户只是**查询**队列状态（「还有啥没修」）→ 读 `.keeper/<交付id>/debug/index.md` 直接答，
  不派/不唤醒 keeper
- 范围外的新功能需求、feature-creep → 走项目 backlog，不进 debug 队列
- 用户明确说「这个我自己改」或指定要主会话立刻手改的一行小修 → 按用户指令做，
  但仍建议登记以免丢失（登记与否听用户）
- 已在 keeper 手上的 issue，用户追加补充信息 → 用 `SendMessage` 追加给 keeper，
  不要自己去改 `.keeper/<交付id>/debug/` 下的文件

## 6. 分流边界（keeper 执行，主会话仅需知晓判据）

判据一句话：**「修它是否是本次交付验收的前置？」** 是 → 留在 `.keeper/debug/`
队列；否（范围外需求、feature-creep）→ 升到项目 backlog，不占 debug 队列；交付
收官时仍未修完 → keeper 在 issue 正文的「结局」章节写明推迟原因，批量建外部
issue 作跨 worktree 接力棒，记下引用写进 `external_ref`，`status` 标 `done`。

**外部工单回写也由 keeper 承担，主会话零参与**：具体系统（Jira / GitLab issue /
公司自建工单平台等）与写法各不相同，本插件不内置任何一种，完整的可插拔适配器契约
见 `references/external-tracker.md`。

## 7. 与 tk-chore 分工

同属 task-keeper 插件的另一条队列是 `tk-chore`：bug / 异常 / 回归这类**有可复现的
错误行为**的走 debug-keeper；台账维护、沉淀整理、收尾杂务、外部系统零碎操作这类
**没有错误行为、只是需要有人跟进的事**走 chore-keeper（`tk-chore` skill）。拿不准
时按这条判据分：能不能指出「预期是什么、实际是什么、怎么复现」——能，进 debug 队列；
不能，进 chore 队列。

**有一条反向流转，你要认得出来**：debug-keeper 可能把一条已登记的 DBG 条目退回给你、
请你转 chore。判据不是「它没有错误行为」——它有可复现的现象，当初进 debug 队列是对的；
而是 triage 查完八类规格来源后发现**没有任何一份文档定义过正确行为是什么**
（`references/queue.md` §3.1 的 `spec_status: gap`）。这种条目在 debug 队列里收不了口
——「修好了」没有判据，派 fixer 只会让它凭直觉补一个同样没人确认过的行为，把规格空白
伪装成已定案。

收到这类退回时照常走 `tk-chore` 转 chore-keeper，摘要**逐字用 keeper 给的「待产品确认
X 的语义」，不要改写成「修复 X」**——改写一次，这条就又变回一个看起来该由工程解决的
问题了。原 DBG 条目仍由 debug-keeper 持有、保持 `open`，等产品答复，不必你跟进。

## 8. 配套 hook（task-keeper 插件内，与 `plugin.json` 注册一致）

| hook 文件 | 时机 | 作用 |
|---|---|---|
| `session-start-keeper-routing.sh` | SessionStart | **纯注入**主会话三岔口分诊规则（即时做 / 转 debug-keeper / 转 chore-keeper）与决策打包主会话侧职责；未启用项目只注入 ≤300 字符介绍。不拦截任何操作 |
| `user-prompt-submit-debug-queue.sh` | 每轮 prompt | 注入 debug 队列快照 + 重算 `.keeper/<交付id>/debug/index.md`（只在 fixer 的 `DBG-*` worktree 里跳过重算；交付级 worktree 照常重算） |
| `user-prompt-submit-chore-queue.sh` | 每轮 prompt | 同上机制的 chore 队列版，属于 `tk-chore`，本 skill 不消费它的输出 |
| `pre-tool-use-debug-evidence.sh` | 写 `issues/*.md` | 拦下指向 `image-cache` 的截图路径（跨 session 必然 404），`permissionDecision: deny` |
| `pre-tool-use-debug-worktree-push.sh` | fixer 执行 `git push` | 目标路径含 `.keeper/<交付id>/debug/<DBG-id>/worktree/` 时直接 `deny`（见 `agents/debug-keeper.md` §5） |
| `pre-tool-use-debug-worktree-destroy.sh` | 针对 `.keeper/<交付id>/debug/<DBG-id>/worktree/` 的强制删除类命令 | `permissionDecision: ask` 弹框确认，不是 `deny`——`rm -rf` 一类命令在少数恢复场景下是合法手段，改用 ask 给用户一个放行的出口 |

两个已摘除的 hook，不要再引用：派发前六项校验的 hook——它要判断的不是「派发是否
合规」而是「这次派发是不是在修 bug」，后者无法从 `tool_input` 机械判定；自动对账
的 hook——它的介入门槛是 `status == "in_progress"`，而实测该值从未被写入过一次，
在跑了 14 个 subagent 的会话里零命中。两次摘除的共同病根是**拿 AI 手写的业务字段当
机械防线的触发门槛**，等于把开关交给要防的对象。原约束现由 `agents/debug-keeper.md`
§7/§8 承载（keeper 自觉遵守 + 合并前手工对账）。

**hook 算出的标记是权威值。** 不要凭记忆判断队列状态，也不要把它们写回 issue 文件。
