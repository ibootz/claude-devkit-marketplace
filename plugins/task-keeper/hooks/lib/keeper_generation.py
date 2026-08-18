#!/usr/bin/env python3
"""keeper 换代判定：这一代 keeper 手上的活是不是已经全部收口

## 为什么需要换代（2026-08-10 用户拍板加）

keeper 是常驻实例：首次 `Agent` 派出，此后一律 `SendMessage` 唤醒。这带来一个
无法在 CLI 层面绕过的副作用——**在飞 agent 面板那一行的 description 在派发那一刻
就永久定格**。SendMessage 的字段只有 `to` / `summary` / `message`，`SubagentStart`
hook 的输出 schema 只认 `additionalContext`，两条通道都不写回 job 状态（2026-08-10
对 CLI 2.1.226 的 bundle 逐条核实）。于是一个跑了整场会话的 keeper，面板上永远挂着
它第一次接的那个活，看板价值归零。

原先的处置是「既然改不了，就把 description 钉死成角色串」。本模块换一条路：**不追求
改写已派实例的 description，而是让 keeper 有代际**——一代 keeper 把手上的活干完、
队列确实收口了，就让它退场，下一批任务重新派一个新实例，新实例的 description 写
这一批的批次摘要。面板于是大部分时候都在显示「当前这一代在干什么」。

## 换代不需要「作废登记」这个动作

`.keeper-instance.json` 的写入是**覆盖式**的（`keeper_paths.write_keeper_instance`
只覆盖对应 kind 那一路），而写入时机是 `PreToolUse(Agent)` hook 在派发那一刻自动登记。
所以主会话只要按提示新派一个实例，旧 name 就被新 name 顶掉，旧实例自然失去寻址、
不再被唤醒。**不需要新增任何「退役标记」字段或删除路径**——多一个状态字段就多一处
可能与磁盘真相分叉的地方，而覆盖写本身已经是原子的代际交替。

旧实例本身不会被杀掉（Claude Code 的 subagent 没有终态，停止只是等消息）。它安静地
留在后台不再收到消息，随会话一起结束。这是可接受的：它不持有锁、不轮询、不写盘。

## 判据（全部机械，五项全过才算可换代）

对某个 kind 判定「这一代可以退场了」，五项**全部**满足：

  1. **该队列 done 桶非空**——这一代确实干完过至少一条活。**这一项是「换代」与
     「压根没开工」的唯一分界线**，缺了它整个机制会反向失效，理由见下方「为什么
     空队列不算干完」。
  2. **该队列 open 桶为空**——还有没做完的条目就不能换代，新实例接手会重读一遍。
  3. **该队列 unknown 桶也为空**——`split_by_status` 把 `_broken`（正文缺失 /
     frontmatter 解析失败 / 目录名与 id 不一致）和状态值读不懂的条目都归进第三桶。
     读不懂 ≠ 已完成，方向上必须保守：一条读不懂的条目挡住换代，代价只是多用一代
     keeper；反过来放行的代价是一条真未完成的活被新实例漏掉。
  4. **该交付下没有待答复的决策**（`decision_inbox.pending_decisions` 为空）。
     这一项**不按 kind 细分，任何一条挂起裁决都挡住所有 kind 的换代**，理由见下方
     「为什么裁决要一票否决」。
  5. **debug 专项：没有任何 `debug/<id>/worktree/` 目录残留**。worktree 还在说明
     上一代的合并/清理没走完，新实例不知道那个工作区是谁开的、为什么还没删。

判 False 的代价只是「继续用现在这一代」，判 True 的代价是「一批活可能被交接丢掉」。
两侧代价不对称，所以任何异常（读不到目录、解析失败、import 失败）一律判**不可换代**。

## 为什么空队列不算干完（第 1 项，实测出来的，不是设计时想到的）

第一版判据只有「open 空 + unknown 空」，没有第 1 项。结果 task-keeper 回归里
[88] / [91] 两组用例立刻炸了 5 条断言——它们的 fixture 是**刚建好的空队列**，于是
判定说「这一代可以退场了」，注入里再也不出现「本会话已有 xxx 在跑」。

用例炸得对，暴露的是真缺陷而不是用例过时：**空队列恰恰是 keeper 生命周期开头的常态**。
主会话派出 keeper、把 bug 逐字转过去，keeper 要读队列、triage、写 `issue.md`，这中间
隔着好几轮工具调用；在它落盘之前，磁盘上就是一个空队列。没有第 1 项的话，下一轮注入
就会建议「新派一个」，主会话照做，两个实例同时抢 `.keeper/<交付>/debug/` 的独占写权限
——这正是 2026-08-03 那次「唤醒不到就重派」事故的形态，只是触发路径换了一条。

第 1 项还顺带覆盖了另一种空：归档（`archive_done.py`）把 done 条目搬走之后 done 桶会
重新变空，此时判不可换代、继续用现役实例。这是保守方向的正确一侧：多用一代 keeper 的
代价是面板摘要旧一点，而误判换代的代价是双写者。

## 为什么裁决要一票否决（这是本模块最容易被改错的一条）

`debug-keeper.md` §12 明确写着 `blocking: true` **只冻结 `about` 指向的那一条 issue，
不冻结整条队列**——照这个语义，似乎「有待拍板项」不该挡住换代，因为 keeper 本来就
还在处理别的条目。

但换代场景下的风险与 blocking 语义无关，在于**裁决的交接**：keeper 写了
`decisions/<stamp>-<keeper>.md` 之后，答复是主会话后写的 `answers/<同名>.md`，
而「把裁决抄回 issue、再删掉这对文件」这个收口动作**只写在 keeper 的 §12.3 里**。
一旦这一代在答复落盘前退场，新实例的冷启动流程里没有任何一步会去扫 `decisions/`
待答复清单（2026-08-10 核实：`index.md` 的渲染只输出 `spec.index_cols` 声明的字段，
不含「这条在等拍板」的标记；debug-keeper 冷启动段也没有扫 decisions 的动作），
那对文件会静默留在磁盘上，裁决永远不会被抄回 issue。

所以这一项拦的不是「keeper 忙不忙」，而是「换代会不会让一次已经付出过的人类决策
凭空蒸发」。它必须一票否决，也不能只否决提出裁决的那个 kind——`about: "-"` 的全局
决策关联不到具体 kind，按 kind 细分会让这类裁决从判据里漏掉。

## 覆盖边界（如实记录，勿删）

  · **假阴性（该换代却说不能）**：队列里躺着一条状态值写错的历史条目（v2 遗留的
    `status: fixed` 之类）会永久落进 unknown 桶，于是这个 kind 永远判不出可换代。
    这是有意的方向选择——修那条条目比放宽判据便宜，且 unknown 桶本来就该被清理。
  · **假阳性（不该换代却说能）**：keeper 手上的活**没有落盘**时判据看不见它。
    典型是「正在推理、还没写 issue 文件」这一瞬间。缓解靠的是换代不是强制——
    注入只是「建议」，主会话若知道刚转过去一个活，照常 SendMessage 唤醒即可。
    所以本模块的输出**永远只用于软提示，不得升级成任何拦截**。
  · **本模块只回答「可不可以换代」，不回答「该不该现在换」**。后者取决于主会话
    手上是不是正好有新一批活，那是语义判断，机械层面不碰。

## v7：两层判定并存，各回答一个不同的问题（2026-08-18）

多实例架构下「一档 = 一代 keeper」这个等式不再成立，于是本模块分成两个函数：

  · `instance_state(delivery_root, kind, issue)`——**按实例**问「绑了这条 issue 的
    实例还有没有活」。这是每轮注入实际使用的那个，因为主会话要逐个决定唤醒谁。
  · `retirable_kinds(delivery_root)`——**按档**问「这一档是不是全清了」。它在 v7
    里不再驱动「换代」，只用于「这一档可以收尾了」这类整体提示。上面五项判据原样
    保留（含裁决一票否决），因为整档收口本来就该比单个实例收工更严。

改任何一个之前先确认改的是哪一层的问题。把按档判据搬去按实例用，会让 DBG-207 的
实例被 DBG-208 的存在挡住、永远判不出收工；反过来把按实例判据搬去按档用，会在还有
别的实例在跑时报「整档已清」。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from queue_files import (DEBUG, CHORE, STATUS_DONE, item_dir_path, item_path,
                             load_all, parse_item_file, split_by_status)
except Exception:
    DEBUG = CHORE = STATUS_DONE = None
    item_dir_path = item_path = load_all = parse_item_file = split_by_status = None

try:
    from decision_inbox import pending_decisions
except Exception:
    pending_decisions = None

# 与 keeper_routing.KIND_LABELS / keeper_instance_register.KEEPER_SUBAGENT_KIND
# 是同增同减的一组清单。少一个 kind 的后果是那个 kind 永远判不出可换代（安全方向）。
# v7 删掉了 `context`——context 队列整条拆除，收集降级成 prompt 模板。
SPEC_BY_KIND = {}
if DEBUG is not None:
    SPEC_BY_KIND = {"debug": DEBUG, "chore": CHORE}


def _batch_finished(delivery_root, spec):
    """这一代在该队列上「干完过一批」：done 非空，且 open 与 unknown 都空。

    **目录不存在返回 False**（不是 True）——没有队列目录等于没开过工，不是干完了。
    同理空目录也返回 False，理由见模块头「为什么空队列不算干完」。

    任何异常判 False（不可换代），理由见模块头「两侧代价不对称」。
    """
    if spec is None or load_all is None or split_by_status is None:
        return False
    qdir = os.path.join(delivery_root, spec.dir_name)
    if not os.path.isdir(qdir):
        return False
    try:
        op, done, unk = split_by_status(load_all(qdir, spec))
    except Exception:
        return False
    return bool(done) and not op and not unk


def _worktree_residue(delivery_root):
    """debug 队列下还有没有 `<DBG-id>/worktree/` 目录。有 → True（挡住换代）。

    只看目录存在性，不起 git 子进程——本判定跑在每轮 UserPromptSubmit 里，
    `git worktree list` 的进程开销不该压在每一轮上。目录存在性与 git 记录在
    正常路径下同步（`wt_supply.py remove` 两者一起清），偏差只会偏向「还剩着」
    这个保守方向。
    """
    if DEBUG is None:
        return True
    qdir = os.path.join(delivery_root, DEBUG.dir_name)
    if not os.path.isdir(qdir):
        return False
    try:
        for name in os.listdir(qdir):
            if os.path.isdir(os.path.join(qdir, name, "worktree")):
                return True
    except Exception:
        return True
    return False


def _decisions_pending(delivery_root):
    """该交付下有没有待答复的裁决。任何异常判 True（挡住换代）。"""
    if pending_decisions is None:
        return True
    try:
        return bool(pending_decisions(delivery_root))
    except Exception:
        return True


def retirable_kinds(delivery_root, kinds=None):
    """返回可以换代的 kind 集合。`delivery_root` = `<worktree 根>/.keeper/<交付id>`。

    `kinds` 缺省时判全部三个 kind。任何一步异常都只会让某个 kind 落选，不抛异常
    ——调用方（每轮注入）不能因为这个判定失败而丢掉整段三岔口。
    """
    if not delivery_root or not SPEC_BY_KIND:
        return set()
    if _decisions_pending(delivery_root):
        return set()          # 裁决一票否决，见模块头
    residue = _worktree_residue(delivery_root)
    out = set()
    for kind in (kinds if kinds is not None else SPEC_BY_KIND.keys()):
        spec = SPEC_BY_KIND.get(kind)
        if spec is None:
            continue
        if kind == "debug" and residue:
            continue
        if _batch_finished(delivery_root, spec):
            out.add(kind)
    return out


def instance_state(delivery_root, kind, issue):
    """**按实例**判：绑了 `issue` 的这个 keeper 实例现在处于什么状态。

    返回 `"live"` / `"retirable"` / `"unknown"` 三者之一。

    ## 为什么 v7 要按实例判，而不是继续按档判

    `retirable_kinds` 问的是「这一**档**的活是不是全干完了」。那个问题在「一个 keeper
    顺序处理整条队列」的 v6 架构下等于「这一**代** keeper 是不是该退场」——两者同义，
    因为一档只有一个实例。

    v7 一条 issue 一个实例之后，两者彻底分开了：DBG-207 的实例干完了它那条，此时
    debug 档大概率还有 DBG-208、DBG-209 在跑。按档判会说「还不能退场」，于是主会话
    继续把它当活人唤醒——而它手上早就没活了。反过来，等整档收口再判，等于要求所有
    实例齐步走，把并行又压回串行。

    ## 判据（两项，都机械）

      1. 该条目的 `status` 是 `done`。
      2. 该条目目录下没有 `worktree/` 残留——worktree 还在说明合并或清理没走完，
         这个实例还欠一步收尾动作，不能当它已经交差。

    ## 三种返回值分别意味着什么

      · `"retirable"`——两项都过。主会话**不必再唤醒它**；同一条 issue 若 reopen，
        按新一轮处理重新派实例，不要复活旧的（它的上下文停在「我已收工」那一刻）。
      · `"live"`——条目还在 open，或还有 worktree 残留。正常唤醒。
      · `"unknown"`——`issue` 为空（登记时没抽到编号）、条目目录还不存在（刚派出、
        keeper 尚未认领编号）、或解析失败。**一律按 live 对待**：注入措辞上不提退场。
        理由与 v6「空队列不算干完」同源——实例生命周期的开头本来就有一段磁盘上什么
        都没有的窗口，把那一瞬判成可退场，会让主会话立刻重派一个，两个实例抢同一条
        issue 的写权。

    裁决（`decisions/`）**不参与本判定**。v6 里它一票否决整档换代，是因为一代 keeper
    退场后没有任何人会去扫待答复裁决。v7 把这条责任改成了「读盘现算、谁碰到谁做」：
    任一活着的实例都会在每轮注入里看到待拍板计数并收口它，不再依赖某个特定实例活着。
    """
    if not issue or parse_item_file is None:
        return "unknown"
    spec = SPEC_BY_KIND.get(kind)
    if spec is None:
        return "unknown"
    idir = item_dir_path(os.path.join(delivery_root, spec.dir_name), issue)
    if not os.path.isdir(idir):
        return "unknown"
    try:
        fm, _body = parse_item_file(os.path.join(idir, spec.item_file))
    except Exception:
        return "unknown"
    if not isinstance(fm, dict):
        return "unknown"
    if str(fm.get("status", "")).strip() != STATUS_DONE:
        return "live"
    if os.path.isdir(os.path.join(idir, "worktree")):
        return "live"          # 活干完了但工作区没清，还欠一步
    return "retirable"


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    print(sorted(retirable_kinds(root)) or "（无可换代的 kind）")
