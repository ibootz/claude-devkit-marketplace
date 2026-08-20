# Keeper 派发与唤醒机制（debug-keeper 与 chore-keeper 共用，v7：一条 issue 一个实例）

> 两 keeper（`debug-keeper` / `chore-keeper`）的派发、唤醒、多实例协作共用同一套机制，
> 本文是通用版。读时按所在 skill 做占位替换：
>
> - `<keeper>` → `debug-keeper` 或 `chore-keeper`
> - `<kind>` → `debug` 或 `chore`
> - `<prefix>` → `debug 队列` 或 `chore 队列`
> - `<正则前缀>` → `opus-debugger` 或 `sonnet-chore`
>
> 各 SKILL.md 正文里 debug/chore 特异的判据（例如 debug 的"不按 bug 看起来难不难下调"、
> chore 的"不按杂务看起来多小下调"）仍留在 SKILL 本身，本文只承载两 keeper 完全同构的部分。
>
> **v7 起架构从"一档一个常驻实例顺序处理整条队列"改成"一条 issue 一个实例，同一档
> 并存多个"**。本文已按这个模型整体改写，不是 v6 文档打补丁——凡是读到"唯一实例""这一代"
> "换代"这类措辞，均已在下文替换成按实例（而非按档）的说法。若你在别处（agent 定义、
> 存量文档）看到这类旧措辞，按本文为准。

## 1. 新派还是唤醒：三岔口注入现算，不要自己判断

**先看这一轮的三岔口注入怎么说，不要自己重新判断**：`user-prompt-submit-keeper-routing.sh`
每轮都会读 `.keeper/<交付id>/.keeper-instance.json` 并核对 `session_id`，直接给出结论——

- **这一档没有任何属于本会话的活实例** → 首次派发。
- **登记存在但不属于本会话**（`session_id` 不一致，或是加会话隔离之前落的旧格式、
  压根没有这个键）→ 视为陈旧，当首次派发。
- **这一档有活着的实例**（可能不止一个）→ 给出 `issue → name` 的映射。**这不是让你
  唤醒它们**——v7 下"这一档已经有实例在跑"本身**不构成**唤醒任何一个的理由，唯一
  理由是"要补充信息给某条已经被认领的 issue"。新 bug / 新杂务一律新派，哪怕这一档
  已经有十个实例在跑也不例外。

**这条是与 v6 最容易搞反的一条**：v6 的直觉是"已经有人在跑，唤醒它就好，别重复派"，
那条直觉在"一档一个常驻实例"的架构下是对的，在 v7 下会把新任务全部塞给某一个实例
排队处理，并行化的收益当场归零，且**不会有任何报错提示串行化发生了**——两种状态在
表面上看起来一样正常。

**为什么不是你自己读文件判断**：`session_id` 只在 hook 收到的 payload 里才有，主会话
拿不到自己的这个字段，重新读一遍登记文件只能看到有哪些 name、认领了哪些 issue，
判断不出某条记录是不是上一个会话留下的死记录。这层判断交给 hook 现算，不要自己再猜。

**不要因为 `SendMessage` 唤醒失败就直接改判首次派出再派第二个**——先确认自己用的 name
是不是这一轮注入给你的那个（按 `issue` 字段核对，不是按时间顺序猜最近那条）；hook 已经
说了"新派"你却拿旧文档或旧记忆里的名字去唤醒，失败是预期的，应该照 hook 的结论新派，
不是"再派一个顶替"。

## 2. name：带 4 位随机短哈希，前缀按 kind 分叉

**每次新派一个实例，`name` 都要自己生成一个带 4 位随机短哈希的后缀**，形态
`<正则前缀>-<4位小写字母或数字>`（如 `opus-debugger-4bb6` / `sonnet-chore-9f2a`，
正则 `^<正则前缀>-[0-9a-z]{4}$`）。

**两个 kind 的档位与前缀各自钉死、互不参照**（working-discipline 的 `agent-dispatch.js`
`KEEPER_SPECS` 表）：

| kind | 档位 | name 前缀 |
|---|---|---|
| debug | `opus`（triage / 去重 / 对账错一次整条队列跟着错） | `opus-debugger-` |
| chore | `sonnet`（台账登记与归档是机械杂务，不需要 opus 的因果链深度） | `sonnet-chore-` |

判据是**等值**不是"不低于"——给 chore-keeper 派 `opus` 同样会被拦，不是"可以更高档
更保险"。**前缀里不再带 `-keeper-` 段**（2026-08-18 换名，`opus-debug-keeper-4bb6`
现在会被硬 deny）：那个词对着在飞面板看名字的人零信息量，`subagent_type` 本身仍是
`task-keeper:debug-keeper`（SubagentStart 的 matcher 键、登记表反推 kind 都靠它），
只是 name 里的身份段换成了对人更有信息量的 `debugger` / `chore`。

随机后缀让每个实例天生不重名，避免「上一个实例结束、下一个又叫同名」时 `SendMessage`
的 name 寻址（latest wins）撞车——v7 下这一点更关键，因为同一档同时可能有好几个实例
存活，任何一次撞名都会让某条 issue 的寻址悄悄指向另一个实例。代价是主会话没法再靠
记忆或文档拼出实际 name——`PreToolUse(Agent)` hook 在派发那一刻自动把 name（连同
`session_id`）追加进 `.keeper/<交付id>/.keeper-instance.json` 的 `<kind>` 键（v7 起
是一份实例列表，见 §4），每轮三岔口注入据此现算 issue→name 映射。

**`name` 必须原样写进 prompt 第一行**，不是客套话：subagent 读不到自己的调度参数
（已实测确认），而它认领 issue 后要用这个 name 去跑 `scripts/keeper_cli.py bind`
（把自己与认领的 issue 登记到一起）和 `lock`（合并前互斥），读不到就没法完成这两步。

四类写错会被 `working-discipline` 的 `agent-dispatch` check 10 直接拦下：

- `<keeper>`（缺模型段）
- `<正则前缀>-<交付id>`（拿交付 id 当后缀，不是随机短哈希）
- 带额外修饰的长名（如 `opus-debugger-queue-manager-xxxx`）
- 旧的 `opus-debug-keeper-xxxx` / `opus-chore-keeper-xxxx` 形态（`-keeper` 段已废止）
- 任何不含 4 位随机后缀的逐字固定形态

## 3. description：前缀锚定，通常只描述一个实例认领的那条 issue

**`description` 必须以 `<prefix>` 起头，前缀之后接这条 issue 的摘要**，例如
「`<prefix>`·登录页白屏」（分隔符 `·` 推荐但不强制）。

**全串简体中文、上限 15 字**——按 code point 计，一个汉字与一个 ASCII 字符都算 1 字，
`DBG-042` 记 7 字。`<prefix>` 本身（`debug 队列` / `chore 队列`）已占 8 字，所以分隔符
用不带空格的 `·`（1 字）而不是 ` · `（3 字），给摘要留 6 字：`debug 队列·登录页白屏`
恰好 14 字。

**摘要里不写 issue 编号**，写 bug 现象——编号靠 `prompt`（派发模板要求认领目标写在
开头，`extract_issue` 正是先读 `prompt`）。两个理由叠起来堵死了另一条路：一是
`<prefix>` 8 字 + `·` 1 字 + `DBG-042` 7 字 = 16 字，本来就超限；二是想省掉分隔符压到
15 字的话，`debug 队列DBG-042` 会让 `hooks/lib/keeper_instance_register.py:84` 的
`\bDBG-\d{3,}\b` **抽不到编号**——汉字在 Python 的 Unicode 模式下属于 `\w`，「列」与
`DBG` 之间没有词边界。实测：改成这个形态后 `hooks/tests/cases/25-h30-multi-instance.sh`
的 `[156]` 从 `DBG-042` 变成 `None`，登记文件会静默少一个 `issue` 键，主会话此后只能按
时间猜是哪个实例。

**v7 下这句话通常不再需要覆盖"一整批活"**：v6 是一档一个常驻实例、此后一律靠
`SendMessage` 唤醒反复接不同的活，所以 description 要写"这一代"的批次摘要；v7 一条
issue 一个实例，description 写这一条 issue 本身的摘要即可，天然就是"这一代在干什么"，
不需要再刻意凑批次。**唯一仍需要写批次摘要的场景**：同一次 `Agent` 调用如果你判断
确实要让一个实例连续处理关联的几条 issue（罕见，通常应拆成多个实例——见 §1"一条
issue 一个实例"这条默认假设），才在 description 里体现"这一批"而不是单条。

**为什么是前缀锚定而不是逐字固定串**：在飞 agent 面板渲染的是**首次 `Agent` 派发那一刻**
的 `description`，`SendMessage` 只有 `to` / `summary` / `message` 三个字段，**没有任何
入口能更新已派出 agent 的 description**——这是实证过的事实。钉死成固定串会让这句话
只说得出角色（「这是个 `<keeper>`」），说不出这个实例在干什么，看板价值归零。

不带前缀的纯当次任务摘要会被 `working-discipline` 的 `agent-dispatch` check 11 拦下
（判据是 startsWith 比较：以 `<prefix>` 起头就放行；旧的固定串「`<prefix>` 常驻管理」
仍然放行，向后兼容）。

## 4. 认领编号与登记：`keeper_cli.py` 的三个原子原语

v7 起同一档并存多个实例，而下列三件事**必须原子**，靠 agent 自己用 `Write` 手工完成
一定会出竞态：认领编号（两个实例同时登记新 bug，各自扫出同一个 `DBG-208` 再各自写
`issue.md`，后写的整份覆盖先写的，表现是"有一条 bug 凭空消失"且全程无报错）、
登记自己认领了哪条 issue（主会话唤醒时要按 issue 找实例，不是按时间猜）、合并回主仓
（见 §5）。`scripts/keeper_cli.py` 把这三件事收成子命令，实现全部在 `hooks/lib/`
共享模块里，keeper 只调用不重写判据。

```bash
python3 <插件根>/scripts/keeper_cli.py claim  --kind <kind> --summary "一句话摘要"
python3 <插件根>/scripts/keeper_cli.py bind   --kind <kind> --name <自己的 name> --issue <DBG-NNN 或 CHR-NNN>
python3 <插件根>/scripts/keeper_cli.py peers  --kind <kind>
```

- **`claim`**：原子认领下一个编号（mkdir CAS），打印 `<id>\t<目录>` 并落一份占位
  正文——**拿到编号后必须立刻用真实内容整份改写它**，占位摘要会原样出现在
  `index.md` 里。
- **`bind`**：把「这个实例（`--name`）认领了这条 issue（`--issue`）」写进
  `.keeper/<交付id>/.keeper-instance.json`。同名重复登记按更新处理，换绑到另一条
  issue 也是同一条路径，幂等安全。**认领编号之后必须立刻 `bind`**——在此之前主会话
  只能按"未认领编号"显示这个实例，无法用 `issue` 字段路由后续消息给它。
- **`peers`**：列出同档还在登记里的其它实例（`issue` + `name` + 登记时刻），用来
  判断"这条会不会已经有人在管"。

输出契约：成功退出码 0、stdout 第一行是机器可读结果；失败退出码非 0、stderr 一行
原因；锁被别人持有是**退出码 3**（见 §5），这是正常竞争不是出错。

## 5. 合并锁：多实例共享的唯一互斥资源

worktree 让 fixer 之间物理隔离，但**合并回主仓**是所有实例共享的同一个资源——两个
实例同时 `git merge` 动同一个主仓 HEAD 会撞出半完成的 merge 状态，没有干净的自动
恢复路径。合并前必须先拿锁：

```bash
python3 <插件根>/scripts/keeper_cli.py lock acquire --name <自己的 name> --issue <DBG-NNN>
# ...跑 merge-back...
python3 <插件根>/scripts/keeper_cli.py lock release --name <自己的 name>
python3 <插件根>/scripts/keeper_cli.py lock status    # 查看当前持锁者，不需要 --name
```

- **`acquire` 返回退出码 3 = `BUSY`**，正常竞争，不是错误——等一会儿重试，**不要
  绕开锁直接合并**。
- **TTL 900 秒**（15 分钟，一次 merge 正常在分钟内完成）：超时的锁会被下一个
  `acquire` 自动抢占。**抢占成功不等于可以直接开始合并**——先在主仓跑一次
  `git status`：上一个持锁者可能死在 `git merge` 中途（`MERGE_HEAD` 还在），此时
  要先收拾那次未完成的合并（`git merge --abort` 或解决冲突后提交），再开始自己的；
  直接合会撞 "You have not concluded your merge"，这条报错读起来像自己的操作有问题，
  极易被误判成参数写错去反复重试。
- **`release` 只能释放自己持有的锁**：持锁者与 `--name` 不一致时返回失败（退出码
  4）——说明这把锁已经被超时抢占，现在是别人的。**这时不要重试释放**，把这件事写
  进回执，并核对主仓是否停在半完成的 merge 状态。

## 6. 实例的收尾：done 就别再唤醒，reopen 时新派而不是复活旧的

v7 不存在"队列收口后整档换一代"这回事——每个实例天生只对应一条 issue，`hooks/lib/
keeper_generation.instance_state(delivery_root, kind, issue)` **按实例**现算它的状态：

- **`"retirable"`**：该 issue 的 `status` 是 `done`，且它自己的目录下没有 `worktree/`
  残留。主会话**不必再唤醒它**；每轮三岔口注入会把这类实例列进"已收工，别再唤醒"。
- **`"live"`**：条目还在 `open`，或还有 `worktree/` 残留。正常唤醒。
- **`"unknown"`**：`issue` 为空（刚派出、还没认领编号）、条目目录还不存在、或解析
  失败。**一律按 live 对待**——这一瞬正是实例生命周期开头本来就有的窗口（磁盘上
  什么都没有），把它判成可退场会让主会话立刻新派一个，两个实例抢同一条 issue。

**同一条 issue 之后 reopen，给它新派一个实例，不要复活那个已收工的旧实例**——它的
transcript 停在"我已经交差"那一刻，被唤醒后要么懵掉、要么以为自己在重复劳动。

**旧实例本身不会被杀掉**（Claude Code 的 subagent 没有终态，"退场"只是不再收消息），
它安静留在后台随会话结束，不需要专门去关它或清理登记。

**这与"整档收尾"是两个不同层面的判断，别混用**：`keeper_generation.retirable_kinds()`
仍然存在，但它问的是"这一**档**是不是全清了"（五项条件，含裁决一票否决），只用于
"这一档可以收官了"这类整体提示，**不驱动**该唤醒谁这个逐实例判断——按档判据会让
一条 issue 已经收工的实例被同档另一条还在跑的 issue 挡住，永远判不出退场；反过来
按实例判据去判"整档收官"，会在还有别的实例在跑时误报"已清空"。改动前先确认自己
改的是哪一层的问题。

## 7. 唤醒某条 issue 对应实例的等价写法

每一轮的三岔口注入已经直接给出 issue→name 映射（见 §1），不需要再自己读文件——下面
这段读取命令只是给你在需要单独确认时用的等价写法：

```bash
python3 <插件根>/scripts/keeper_cli.py peers --kind <kind>
# 或直接读登记文件、按 issue 字段过滤：
/usr/bin/python3 -c '
import json
data = json.load(open(".keeper/<交付id>/.keeper-instance.json"))
for rec in data.get("<kind>", {}).get("instances", []):
    print(rec.get("issue"), rec.get("name"))
'
```

```
SendMessage(
  to: "<按 issue 字段核对到的那个 name，不是字面量 <正则前缀>>",
  summary: "补充 <issue id> 的信息",
  message: "<用户原话逐字>"
)
```

`SendMessage` 唤醒时该实例的上下文完整保留（已实测确认），所以它记得自己认领这条
issue 之后做过什么。**新 bug 一律新派一个实例**，不要因为同档已经有实例在跑就把它
塞进去；只有"补充某条既有 issue 的信息"才走本节的唤醒路径。
