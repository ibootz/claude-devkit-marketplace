# 待拍板协议（keeper 与主会话的 HITL 通道）

> 本文件从 `agents/debug-keeper.md` §12 下推。keeper 是后台 subagent，`AskUserQuestion` 不在它的工具清单里（已实测确认），没有办法弹选项框直接问 Human。本协议是它唯一的拍板通道。
> 正文 §12 只留四小节骨架与一句话约束，细节全在本文件。

## 什么时候走这条协议

只在两种情况下打断用户，其余一律自己决策：

1. **修复完成待 accept/reject**，按 issue 分节汇报，每节含：改了哪些文件、验证章节每个场景的实际验证结果、对账结论。
2. **出现你无权决定的取舍**：需要改动数据结构 / 涉及产线 / 需要发布环境 / 同一 issue 已 reopen ≥3 次。

同根因判断**不在**其中——worktree 隔离下判错的代价（合并时一个 git 冲突）低于打断用户一次的代价，由 keeper 自己判并在回执里留痕。

## 12.1 keeper 发起

### 第 1 步：写决策文件

路径 `.keeper/<交付id>/decisions/<UTC 时间戳>-debug-keeper.md`，时间戳用 `date -u +%Y%m%dT%H%M%SZ` 这种可排序格式（例：`20260731T143210Z-debug-keeper.md`）。frontmatter 五个键：

```yaml
---
from: debug-keeper
about: DBG-017              # 关联的 issue id，跨 issue 的事项写 "-"
kind: architecture-tradeoff # 用一个短语概括这是哪一类拍板
blocking: true              # 布尔：为 true 时只冻结 about 指向的这一条 issue，
                            # 队列里其他条目照常处理，见下方第 3 条
options:
  - id: A
    label: 一句话概括方案 A
  - id: B
    label: 一句话概括方案 B
recommend: A                # 你的倾向，允许为空
---

正文把前因后果讲透：这条 issue 现在卡在哪、为什么这个决定超出你的权限、
不同选项各自的影响面，让 Human 不用打开任何其他文件就能理解并做决定。
```

### 第 2 步：发 SendMessage 指针通知

`SendMessage(to: "main")`，**≤3 行、只给指针**：

```
DBG-017 待拍板：架构取舍，需要你确认改动方向。
详见 .keeper/<交付id>/decisions/20260731T143210Z-debug-keeper.md
```

**不要**把 frontmatter 或正文粘进 `message`——那份内容已经在文件里，重复一遍只会把主会话的上下文预算花在本可以省下的地方。主会话此刻大概率在做别的事，指针化消息能让它看一眼就决定「现在处理」还是「攒着批量看」。

### 第 3 步：blocking 字段的语义

`blocking: true` **只冻结它 `about` 字段指向的那一条 issue，不冻结整条队列**。

真实后果曾经是反过来的：bug 持续报进来，而 keeper 因为一条 blocking 决策就什么都不做，整条队列跟着停摆——那不是这条字段的本意。收到一条 `blocking: true` 之后，要继续处理队列里其他条目：登记新进来的 bug、triage、派其他 issue 的 fixer、收其他 issue 的回执，一件都不能停。唯一禁止的是对**被冻结那一条 issue**做任何假设性推进——那条决策阻塞的正是它自己，硬去做会导致后续动作建立在还没拍板的假设上。

**不触发**（此时才是真的整条队列原地等）：`about: "-"`，即跨 issue 的全局性决策（例如「本轮要不要整体回滚」），这类决策没有单一 issue 可归属，天然冻结的就是整条队列。`blocking: false` 时连单条冻结都不发生，可以按判断继续推进这条 issue 本身，只是不要假设 Human 事后一定认可没问过的那部分。

### 第 4 步：积压催促

**写一条新决策文件前，先数一下待拍板已经积了多少条，积到 3 条就在通知里主动催**。判据是机械的：数 `.keeper/<交付id>/decisions/` 下**还没有对应 `answers/<同名>.md`** 的文件数（数文件即可，不用判断内容或紧急程度）。写完这一条新决策文件后，若这个数达到 **≥3**，本条 `SendMessage` 的正文必须多写一句「待拍板已积 N 条，请立即批量拍板，不要再攒」，不能像平时一样只发指针。

理由：主会话侧的攒批阈值同样是 3 条，但那边的措辞留了裁量权，而 bug 会持续进来、拍板却可能一直不发生——keeper 这一侧主动催是第二道保险。**不触发**：该数 <3 时照常只发指针，不要每条都催——催成常态等于没催。

## 12.2 主会话攒批、转达、写回

主会话收到指针通知后不必立刻处理，可以攒够一批再一起讲给 Human。拿到 Human 的原话答复后，主会话把**答复原文**写进 `.keeper/<交付id>/decisions/answers/<同名>.md`（文件名与 `decisions/` 下那份完全一致，只是目录换成 `answers/`），然后按 §0 描述的会话隔离机制确认 keeper 还在本会话内（登记的 `session_id` 与当前一致，由每轮三岔口注入现算，主会话不自己重新比对），`SendMessage` 唤醒那个真实 name（**不是**逐字写死的 `opus-debug-keeper`——name 带随机短哈希，写死字面量唤醒不到）告知已写好。

若中间跨了会话（比如 Human 拖了很久才答复、主会话已经重启过一轮），登记会被判定已失效，走首次派发——keeper 写在磁盘上的 issue 文件与 `decisions/`/`answers/` 都还在，新实例被派出后按 §0 描述的方式先看 `index.md` 建立队列认知，能看到这条待决事项，不会当成全新问题重复处理。

## 12.3 keeper 收到答复后

读 `answers/<同名>.md`，把裁决内容**抄进对应 issue 文件**（「修订记录」或「Triage」章节，视决策性质而定）留痕——这一步不能省，`decisions/` 与 `answers/` 这对文件接下来要被删掉，issue 文件是唯一还会被后续会话看到的地方。抄完之后删除这两个文件：

```bash
rm "$ROOT/.keeper/<交付id>/decisions/20260731T143210Z-debug-keeper.md" \
   "$ROOT/.keeper/<交付id>/decisions/answers/20260731T143210Z-debug-keeper.md"
```

## 12.4 一文件一写者

`decisions/` 根目录下的文件**只有 keeper 写**（主会话不得在这里新建或修改文件）；`decisions/answers/` 下的文件**只有主会话写**（keeper 不得抢先在这里放占位内容）。这条边界是为了避免两边同时改同一个文件产生竞态——协议本身没有锁，靠「谁的目录谁写」这条静态约定消除竞态需求。
