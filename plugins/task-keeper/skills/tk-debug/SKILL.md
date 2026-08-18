---
name: tk-debug
description: >-
  Debug 队列工程化处理（主会话侧入口）。把「Human 报 bug → AI 立刻派 subagent 修」
  改造成「主会话只转发 → debug-keeper agent 独立跑完登记/triage/派发/对账/收尾，
  自己直接并行派第二层 fixer subagent」的并行流水线。**v7 起一条 issue 一个
  debug-keeper 实例**，同一档可以并存多个；同轮报来多条 bug 要在同一条消息里并行
  派多个实例，各管一条，互不干扰。队列落在项目根
  `.keeper/<交付id>/debug/`（一 issue 一个目录，跨 session 持久；v6 起 issue 文本、
  receipts 与截图入库，只有 fixer worktree 等四类本机产物排除在外）。**主会话在本流程里只做三件事：截图落盘（如果用户附了图）→ 把原话转给
  debug-keeper → 立刻回到原任务。** 不做 triage、不写 issue 文件、不派 fixer、
  不对账，这些全部由 debug-keeper 在独立上下文里完成，避免打断主会话手上的工作。
when_to_use: |
  用户报 bug / 缺陷 / 报错 / 白屏 / 崩溃 / 数据不对 / 点了没反应，或说「登记这个
  问题」「triage 一下」「这条插队」「启用 debug 队列」「这些 bug 一起修」，或在
  verify 阶段发现 in-scope 缺陷需要排期修复时，必须用这个 skill。**禁止绕过队列
  直接派 subagent 修 bug**——「收到即派发」正是本机制要消除的行为。项目根还没有
  `.keeper/<交付id>/debug/` 时也走这里（由首次派出的 debug-keeper 实例负责冷启动
  初始化）。同轮收到多条 bug 时，一律并行派多个实例，不要塞给同一个实例排队处理。
---

# Debug 队列（主会话侧 · 你只做三件事）

## 0. 职责边界：为什么主会话几乎什么都不做

用户报 bug 的时刻，主会话大概率正在做别的任务。让主会话承担整条流水线里的绝大部分
（登记、triage 派发、写队列、对账、收尾），后果是：主任务被打断、上下文被队列细节
撑大、bug 处理与主任务串行而非并行。

现在这些全部移到 **`debug-keeper` agent**（task-keeper 插件自带，
`agents/debug-keeper.md`）。**v7 起它不再是"同一档唯一的常驻实例"，而是一条 issue
一个实例**：每收到一条新 bug，就为它新派一个 debug-keeper 实例；已经在跑的实例只在
"补充信息给它自己认领的那条 issue"这一种场景下才用 `SendMessage` 唤醒，绝不会因为
"这一档已经有实例在跑"就把新 bug 转塞给它排队——那会把本该并行的处理压回串行，
且不会有任何报错提示这件事发生了。每个实例在独立上下文里跑完自己那条 issue 的全流程，
**包括自己直接调用 `Agent` 工具并行派发第二层 fixer subagent**（标准 `subagent_type`
路径不受嵌套深度限制，debug-keeper 按常驻 agent 正常工作；撞到「具名 teammate 唤醒后
再发起 `Agent` 调用被拒绝」这类报错时，先判断卡住的是哪条调用路径——teammate 路径还是
标准 `subagent_type` 路径，不要一概而论）；需要用户拍板时它走 `agents/debug-keeper.md`
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

**第二步，落盘到 `_inbox/`（不是 `<DBG-id>/`）。** `DBG-id` 由接手这条 bug 的
debug-keeper 实例分配——它跑 `scripts/keeper_cli.py claim --kind debug` 原子认领
编号（v7 起同一档可能并存多个实例同时登记新 bug，这条 CLI 靠 mkdir CAS 保证不撞号；
不要自己预分配 id，也不要凭「下一个可用 id」这类估算去建文件）。keeper 登记时会
`mv` 到 `.keeper/<交付id>/debug/<DBG-id>/` 并写进「证据」章节：

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

## 2. 唯一动作：为每条 bug 新派一个实例，或唤醒它自己认领的那条 issue

**v7 起是一条 issue 一个 debug-keeper 实例，同一档可以并存多个。** 每收到一条
**新** bug，一律用 `Agent` 新派一个实例，即使这一档已经有别的实例在跑也不例外
——那个在跑的实例正在管别的 issue，把新 bug 转给它只会让它排队处理，白白丢掉
本该并行的收益，且不会有任何报错提示这件事发生了。只有**补充信息给某条已经被
认领的 issue**（比如用户追加了这条 bug 的更多细节）才用 `SendMessage` 唤醒认领
了它的那一个实例，见下方"此后每一次"。

**派发与唤醒机制（三岔口注入、name 生成、description 锚定、多实例登记与检索）见
`references/keeper-dispatch.md`，两 keeper 共用同一套，本文只写 debug 特异的判据。**
读 reference 时占位替换：`<keeper>`→`debug-keeper`、`<kind>`→`debug`、
`<prefix>`→`debug 队列`、`<正则前缀>`→`opus-debugger`。

**`model` 固定 `"opus"`，不按 bug 看起来难不难来下调。** keeper 是第一层调度者，它做的
triage 打分、落点行区间、同根因判定、对账三件套误报识别，判错一次的返工成本由后面整条
流水线承担（理由详见 `agents/debug-keeper.md` §0）。**第二层才分档**——keeper 派 fixer
时按 `difficulty` 从 `sonnet` 起选，见 `references/queue.md` §4「模型分层」。

每条新 bug 的 `Agent` 调用形态（三岔口注入说「新派」时照这模板填，name 自己生成
4 位随机短哈希、description 以 `debug 队列` 起头——完整规则与反模式清单见
`references/keeper-dispatch.md` §2/§3）。**同轮报来多条 bug 时，把下面这个调用
重复多份、放进同一条消息里一次性发出**（各自 name 不同），不要一条一条发：

```
Agent(
  subagent_type: "task-keeper:debug-keeper",   # 若该 subagent_type 不可用则退回 "general-purpose"
  name: "opus-debugger-4bb6",   # 自己生成 4 位随机小写字母/数字后缀，不要逐字抄这个例子
  description: "debug 队列 · 登录页白屏",   # 前缀 `debug 队列` 不可省，之后写这条 bug 的摘要（一个实例只认领一条 issue）
  model: "opus",
  run_in_background: true,
  prompt: "opus-debugger-4bb6\n
           【目标】接管这一条 bug 报告，按 agents/debug-keeper.md 的流程完成登记 →
            triage → 派发（自己直接调用 Agent 工具并行派发第二层 fixer subagent）→
            对账 → 收尾。\n
           【上下文】项目根：<git rev-parse --show-toplevel 的结果>。你自己的
            name 是上面第一行那个字符串——你读不到自己的调度元数据，认领 issue
            后要用它跑 scripts/keeper_cli.py bind 与 lock 相关子命令。\n
            用户原话逐字如下：\n<原话逐字照抄，不要改写、不要总结>\n
            截图：已落盘 <_inbox 下的绝对路径>（登记时请 mv 到
            .keeper/<交付id>/debug/<DBG-id>/ 并写进「证据」章节）；图片内容
            转录：<文字转录>。\n
            〔若落盘失败则写〕原图未落盘，原因：<具体原因>；图片内容转录：<文字转录>。\n
           【约束】认领这条 issue 后先跑 scripts/keeper_cli.py claim --kind debug
            原子取号，再跑 bind 把 name 与 issue 登记好；合并回主仓前先跑
            scripts/keeper_cli.py lock acquire 拿合并锁（同档其它实例可能同时在合并，
            exit 3 是正常竞争，等一会重试）；不要动业务代码；需要用户拍板时走
            agents/debug-keeper.md §12 的待拍板协议，不要经过我传正文。\n
           【期望输出】按 agents/debug-keeper.md §13 的回执格式返回。"
)
```

**prompt 第一行必须原样写实际用的 name**，不是客套话——subagent 拿不到自己的调度
参数，而它认领 issue 后要用这个 name 去跑 `keeper_cli.py bind` / `lock`，读不到就
没法完成登记与合并互斥（完整原因见 `references/keeper-dispatch.md` §2）。

**`description` 锚定 `<prefix>` 起头**：前缀 `debug 队列` 不可省，之后接这条 bug 的
摘要即可——v7 下一个实例通常只对应一条 issue，不再需要像 v6 那样凑「这一代接的
整批活」。完整机制（为什么前缀锚定而不是逐字固定串、面板渲染时机、check 11 拦下、
向后兼容旧固定串）见 `references/keeper-dispatch.md` §3。

`run_in_background: true` 是必须的——它让 keeper 在后台跑，你不必等它，也让它具备
`SendMessage` 到 `main` 的能力。`name` 派发成功后 `PreToolUse(Agent)` hook 会自动
把它连同这次派发所在的 `session_id` 追加进
`.keeper/<交付id>/.keeper-instance.json` 的 `debug` 键（v7 起是一份实例列表，不是
单条记录），你不需要自己再写这个文件；`issue` 这一列由实例自己跑 `bind` 补上。

**此后每一次**（同一会话内用户追加信息给同一条 bug），先在 `.keeper-instance.json`
的 `debug.instances` 列表里按 `issue` 字段找到认领了它的那条记录，用它的 `name`
`SendMessage` 唤醒——**不要凭时间顺序猜最近派的那个**，那恰好是并行化要消灭的
串行假设，猜错的后果是把另一条 issue 的进展写进了这条的 `issue.md`。唤醒形态、
读取真实 name 的等价命令、上下文跨唤醒保留的事实，见 `references/keeper-dispatch.md`
§5。debug 侧的 `SendMessage` 消息体要把用户原话 + 截图路径 + 文字转录一起带过去
（§1 落盘流程的产物）。

### 2.1 实例的收尾：done 就别再唤醒，reopen 时新派一个而不是复活旧的

v7 不再有"队列收口后新派一整代"这回事——每个实例本来就只对应一条 issue，它做完
自己那条、`status` 变 `done` 且没有 `worktree/` 残留，就自然没活可干了。每轮三岔口
注入会现算出这类"已收工，别再唤醒"的实例并列出来（判据见
`references/keeper-dispatch.md` §4），看到就不要再 `SendMessage` 它。

**同一条 issue 之后又 reopen（用户反馈没修好），给它新派一个实例，不要去唤醒那个
已收工的旧实例**——它的上下文停在"我已经交差"那一刻，复活它只会让它对着一个自己
以为已经解决的问题懵掉。完整机制见 `references/keeper-dispatch.md` §4。

## 3. 转完立刻回到原任务

转发之后**不要等 keeper 回执**，直接继续你原来在做的事。keeper 是后台 agent，
它完成时你会收到通知，需要用户拍板时它会通过 `.keeper/<交付id>/decisions/` + `SendMessage`
指针找你——那时你只需要照 `agents/debug-keeper.md` §12.2 攒批转达、写答复，不需要
自己去猜决策内容。

## 3.1 keeper 因系统原因被终止时：唤醒它，处置权交回给它

判据是**非任务原因**的终止：`API 529 Overloaded`、限流、额度耗尽、网络超时、连接断流。
（keeper 自己回报"这条我判不了"属于任务内原因，走 §12 待拍板协议，不是本节。）

**你只做一件事**：在 `.keeper/<交付id>/.keeper-instance.json` 的 `debug.instances`
列表里找到**这次被掐断的那一条**——按你派发时用的 name 核对（v7 起同一档可能同时
有好几条记录，各自认领不同的 issue，只处理这一条对应的实例，其它还活着的实例照常
不受影响，不要把整个 `debug` 键都当成一个实例来处理）。这个场景是在同一次会话内
发现自己刚派出的某个 debug-keeper 实例被系统原因掐断，登记的 `session_id` 必然与
当前一致，不需要走 §2 那套跨会话比对。用 `SendMessage` 唤醒那个 name（**不是**字面量
`opus-debugger`——name 带随机短哈希，凭记忆拼写不出来），把"你上一轮因 <具体原因>
被终止"这个事实告诉它，然后回到原任务。它的 transcript 完整保留，会照
`agents/debug-keeper.md` §6.2 自己把在飞 fixer 收口。

**三件不许做**：

1. **不许凭产物 mtime 或「文件零写入」推断它派的 fixer 是死是活。** keeper 死了，它派的
   第二层 fixer **可能仍在跑**——2026-08-03 实测有一个在 keeper 死后继续工作了至少 9 分钟。
   mtime 停更无法区分"已终止"与"正在思考 / 正在跑长命令"。
2. **不许替它派 fixer、停 fixer、改 issue 文件。** 那次事故里主会话据错判派了第二个
   fixer，两个 `opus` fixer 同时写一个 worktree 的同一批文件。哪个 fixer 对应哪条 issue、
   该停该续，只有 keeper 知道。
3. **不许因为唤醒不到就为同一条 issue 新派一个 keeper。** `SendMessage` 报
   `No agent named '<x>' is reachable.` 说明你用的名字不对，不是它不在了——先检查
   有没有重新读一次 `.keeper/<交付id>/.keeper-instance.json` 按 `issue` 字段核对
   最新 name（name 带随机短哈希，凭记忆拼、或抄一份旧记录都可能对不上），或用首次
   派发返回的 agentId 寻址。为**同一条** issue 新派第二个实例会让两个实例抢这条
   issue 的独占写权限（`working-discipline` 的 `agent-dispatch.js` check 10 现在
   会把自造名的 keeper 派发直接拦下）——这条禁令不影响你继续为**别的新 bug**并行
   新派实例，那是 v7 的常态，不受这次系统性终止影响。

**若你在读到本节之前已经对 fixer 做过动作**（停过、派过、改过文件），唤醒消息里必须
**逐条如实交代做了什么**，包括你当时的判断依据——不要只给结论。keeper 要靠这些信息
判断现在有几个 fixer 在飞、哪些产物是谁写的。

## 4. 反馈从哪来（不要自己汇报队列状态）

四条通道都不经过你手写状态：

1. `user-prompt-submit-debug-queue.sh` hook 每轮自动注入队列实时快照（open 各条的
   id + 优先级 + 是否在飞、done 计数、reopen 告警，一律现算不落盘）
2. `.keeper/<交付id>/debug/index.md` 由同一个 hook 重算，人类随时打开就能看全部 issue 一览
3. keeper 通过 §12 待拍板协议找你（decisions 文件 + SendMessage 指针）
4. **「谁在管哪条」看 `user-prompt-submit-keeper-routing.sh` 每轮现算的三岔口注入**
   （issue→name 映射，超过 4 条会收成"等 N 个"），要看全表跑
   `python3 scripts/keeper_cli.py peers --kind debug`——v7 起同一档并存多个实例，
   这条通道是「谁认领了哪条」的权威来源，不要凭对话记忆猜

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
| `session-start-keeper-routing.sh` | SessionStart | **纯注入**静态参考：未启用项目只注入 ≤300 字符介绍；已启用项目注入 v7 布局、多实例说明与决策打包指针（三岔口本身不在这里，见下一行）。不拦截任何操作 |
| `user-prompt-submit-keeper-routing.sh` | 每轮 prompt | **纯注入**三岔口分诊（自己做 / 转 debug-keeper / 转 chore-keeper）+ v7 的"新派还是唤醒"判定：现算 issue→name 映射告诉你该 `SendMessage` 谁，登记来自上一会话时提示当首次派发处理。不拦截任何操作 |
| `pre-tool-use-keeper-instance.sh` | `Agent` 派发命中 `debug-keeper`/`chore-keeper` 的 subagent_type | 把这次派发的 `name`（连同 `session_id`）追加进 `.keeper-instance.json` 对应 kind 键（v7 起是实例列表，同名视为更新而非新增）。纯写文件，不拦截 |
| `subagent-start-debug-keeper.sh` | debug-keeper 实例每次启动或被 `SendMessage` 唤醒 | 注入漏派清单 + 同档实例认领表（`peers`），提醒"漏派条目如果已经在某个实例名下就别碰它"。纯注入，不拦截 |
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
