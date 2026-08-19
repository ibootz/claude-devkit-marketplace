#!/usr/bin/env python3
"""主会话路由注入（分两层：三岔口每轮注入 / 静态参考 SessionStart 注入）

纯注入，零拦截——分诊是语义判断，按 hook 克制原则只能做软约束。

## 为什么分两层（2026-08-01 改）

原先整块只在 `SessionStart` 注入一次。实测遵循度不够：AI 在会话中段收到 bug
报告时会直接自己修、收到杂务时会直接自己做，把「先分诊」整条跳过。成因不是它
没读到，而是**分诊这条规则与 system prompt 的默认行为直接对立**——base 指令是
「有足够信息就动手」，而分诊要求的恰恰是「先别动手，判归属」。会话开头读过一次
的软约束，压不过每轮都在生效的 base 指令。

所以按本仓 `hook-injection-layering` 的分层判据切开：

  · **对抗 system prompt 的段落 → 每轮注入**（`UserPromptSubmit`）：三岔口本身
    + 转发三原则 + 一句反合理化。它必须与 base 指令同频出现才有效。
  · **静态参考 → 留 SessionStart**：决策打包协议、v4 布局、指针。这些是「需要
    时去查」的内容，不与任何默认行为对立，每轮重复只是白烧 token。

两层文本**刻意不重叠**：SessionStart 那份不再复述三岔口，只留一句指明它每轮注入，
避免同一会话里同一段规则出现两遍。

## opt-in 分档

判据是 `.keeper/` 目录存在性（**v4 起由 `keeper_paths` 解析：先跳出 submodule、
fixer worktree 回溯到 delivery、再取当前 worktree 根**。v3 那份「向上找、遇 `.git`
停」的本地实现已删——linked worktree 根自己就有 `.git` 文件，第一轮就返回 None，
交付跑在 worktree 里时这里会误判成「未启用」注入启用引导，成因见 `keeper_paths.py`
模块头）：

  · SessionStart 未启用：≤300 字符的一句话介绍 + 启用方式（每会话一次，可接受）。
  · SessionStart 已启用：静态参考，硬上限 2000（H18 断言）。
  · UserPromptSubmit 未启用：**stdout 全空**，等价于本 hook 不存在。与两个队列
    快照 hook 同一条零成本保证——它每轮触发、装在所有项目里，未启用项目一个字符
    都不能付。
  · UserPromptSubmit 已启用：三岔口，硬上限 800（H19 断言）。

## 调用约定

`--event user-prompt-submit` 出每轮那份；缺省（或 `--event session-start`）出
SessionStart 那份。`hookSpecificOutput.hookEventName` 必须与真实事件名一致，
写错 harness 会丢弃整个输出且不报错。

注意不能用 `python3 - <<'EOF'` 内联写法：heredoc 会占用 stdin，事件 JSON（含
cwd）就读不到了——2026-07-31 实测踩过，遂独立成文件。

## 三岔口里"唤醒前怎么办"那句话：为什么现算而不是让 AI 自己读文件（2026-08-05 补）

`.keeper-instance.json` 落在磁盘上跨会话存活，但派出去的 keeper 只活在派出它的那次
会话里——新会话第一次转 bug 时，AI 读到的是上一个会话的死 `name`，唤醒失败后容易
误判成"重派"，两个实例抢同一个目录的独占写权限（完整事故描述见 `keeper_paths.py`
模块头「`.keeper-instance.json` 的会话隔离」）。

修法**不是**教 AI 自己去读文件比对 `session_id`——AI（主会话）本身拿不到自己的
`session_id`，这个字段只在 hook 收到的 payload 里才有，AI 没有任何机械手段验证
"这条登记是不是本会话写的"。所以比对这一步必须由本 hook 现算，直接把结论注进
三岔口文案：

  · 登记存在且 `session_id` 与当前一致 → 告诉 AI 这些实例在跑、各自认领了哪条。
  · 登记存在但不一致（或是加 `session_id` 之前落的旧格式，压根没这个键）→ 告诉
    AI "这份登记已失效，当首次派发处理"。
  · 没有任何登记 → 保持原来的措辞，首次派发。

同一轮只注入当下成立的那一种——预算是每轮成本，把三种都注等于把预算浪费在另外
两种当下不成立的分支上。

## v7：同一档并存多个实例，注入要给的是「issue → name」映射（2026-08-18）

v6 是一档一个常驻 keeper 顺序处理整条队列，所以注入只需回答一个问题：**唤不唤醒它**。
v7 改成一条 issue 一个实例并行跑，注入要回答的问题变成两个：

  1. **这条新 bug 该新派还是该唤醒？**——答案几乎总是「新派」。这是与 v6 最容易搞反
     的一条：v6 的措辞「已有 X 在跑，用 SendMessage 唤醒它，不要重派」若原样留着，
     主会话会把第二条、第三条 bug 全塞进同一个实例，它们于是排队等前一条修完——
     并行化的收益当场归零，而且**表面上一切正常**，没有任何报错提示串行化发生了。
  2. **要补充的信息该发给谁？**——按 `issue` 找，不按时间猜。所以注入里给的是
     `DBG-207→name` 这样的映射，不是一个孤零零的 name。

「已收工」那一支由 `keeper_generation.instance_state` **按实例**现算（该条目 status
是 done、且没有 worktree 残留）。它替代了 v6 的按档换代判定——按档判会让 DBG-207 的
实例被还在跑的 DBG-208 挡住、永远判不出收工。两层判定的分工见 `keeper_generation.py`
模块头「v7：两层判定并存」。

判定失败（import 不到、解析异常、登记里没有 `issue`）一律算作「还有活」——那是保守
方向：多提示一次唤醒的代价，远小于把一个刚派出、还没来得及认领编号的实例判成收工，
继而让主会话重派第二个去抢同一条 issue。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from keeper_paths import find_keeper_root, resolve_delivery_id, read_keeper_instances
except Exception:
    find_keeper_root = None
    resolve_delivery_id = None
    read_keeper_instances = None

try:
    from keeper_generation import instance_state
except Exception:
    instance_state = None

NOT_ENABLED = (
    "task-keeper 未启用（无 .keeper/）。启用后 bug 转 debug-keeper、杂务转 "
    "chore-keeper 常驻处理，主会话只分诊转发。启用："
    "`mkdir -p .keeper/$(basename $(git rev-parse --show-toplevel))/debug`"
    "（非交付用 `_main` 代替 basename），`chore/` 自动补建。")

# 每轮注入：只放与 system prompt 默认行为对立的部分。改这段前先读模块头
# 「为什么分两层」——往里加静态参考会让每轮成本白涨且稀释对抗力。
#
# TRIAGE_HEAD/TRIAGE_TAIL 夹着一句现算的动态提示（见 `triage_wake_line`），三选一：
# 唤醒某个真实 name / 登记已失效当首次派发 / 没有登记当首次派发。三者共用同一个
# 头尾骨架，只有中间这一句不同——见模块头「为什么现算而不是让 AI 自己读文件」。
TRIAGE_HEAD = """# task-keeper 分诊（先分诊，再动手）

判一次归属，不要为分类反问用户：

1. 自己做：主线任务本身、几句话能答的问题、需要你上下文才能做的事。
2. 转 debug-keeper：bug/报错/异常行为，逐字转发。**一条 bug 一个实例**——同轮报来多条就在同一条消息里并行派多个，别塞给同一个。
3. 转 chore-keeper：台账/沉淀/收尾/外部系统小操作等杂务，逐字转发。**杂务相反，攒在同一个实例里**——它要跨条目攒批、一次打包拍板。

"""

TRIAGE_TAIL = """

三原则：逐字（不改写原话）、即回（转完回主线不追问进度）、不越位（`.keeper/` 队列你只读）。

最常见失效是「这个我顺手做了更快」——转发是为了不让任务状态只活在本轮上下文里，compact 一次就没了。"""

# 分支 1：本会话没有任何活着的实例——首次派发。
# 句尾那句 description 提示（≤30 汉字）对应 working-discipline 的 agent-dispatch
# check 11：keeper 的 description 必须以 `<kind> 队列` 起头，首次派发就写对可省一轮 deny。
#
# v7 多了一句「name 原样写进 prompt 第一行」：实例要用自己的 name 去取合并锁、写登记
# （`scripts/keeper_cli.py` 的 `--name` 参数），而 **subagent 拿不到自己的 name**——
# 那个值只存在于主会话这一侧的派发参数里。不传下去，实例就只能瞎猜一个标识，合并锁的
# 持有者校验会因此失效（谁都能释放谁的锁）。
WAKE_LINE_NONE = ("本会话还没有实例：用 `Agent` 派出，name 自带 4 位随机短哈希后缀，"
                   "description 写『<kind> 队列 · <本条摘要>』（前缀不可省），"
                   "并把这个 name 原样写进 prompt 第一行——实例要用它取合并锁。")

# 分支 2：登记存在但不属于本会话（session_id 不一致，或是加会话隔离之前落的旧格式、
# 压根没有 session_id 键）——一律当陈旧处理，判据见 keeper_paths.live_instances。
WAKE_LINE_STALE = ("`.keeper-instance.json` 里的登记来自上一个会话，已失效：当首次派发，"
                    "用 `Agent` 派出并生成新的 4 位随机短哈希后缀，"
                    "description 写『<kind> 队列 · <本条摘要>』，name 原样写进 prompt 第一行。")

# 分支 3（v7 改）：本会话有活着的实例。与 v6 最大的差别是**这里不再劝你唤醒**——
# 唤醒只对「补充某条既有 issue 的信息」成立，新 bug 一律新派一个实例。
#
# v6 的措辞是「本会话已有 X 在跑，用 SendMessage 唤醒它，不要重派」，那句话在一档
# 一实例的架构下是对的，在 v7 下会直接把并行压回串行：主会话看到有实例在跑，就把
# 第二条、第三条 bug 全塞给同一个，于是它们排队等前一条修完。
#
# 4.2.0 起按 kind 分成两句：两档的处置方向恰好相反（debug 新派、chore 唤醒），合成
# 一句只能取一个口径，另一档必然读到反的那句。4.0.0～4.1.0 期间这里只有 debug 口径，
# 靠 `TRIAGE_HEAD` 第 3 条那句「杂务相反」远距离兜着——两句同时在场时，紧贴着实例
# 清单的这一句更近、更具体，会盖过头部那句通则。
WAKE_LINE_LIVE_DEBUG = ("debug 在跑：%s。**新 bug 一律新派实例**（同轮多条就在同一条"
                        "消息里并行派完）；只有补充某条既有 issue 的信息，才 "
                        "`SendMessage` 唤醒认领了它的那一个。")

WAKE_LINE_LIVE_CHORE = ("chore 在跑：%s。**新杂务一律 `SendMessage` 交给它**——攒批与"
                        "打包拍板正是它的价值；只有它已收工才新派。")

# 分支 3 的附加段：这些实例认领的条目已 done 且无 worktree 残留，手上没活了。
# 措辞是「别再唤醒」而不是「已死」——实例本身还在后台，只是没有理由再叫醒它。
WAKE_LINE_RETIRED = "已收工，别再唤醒：%s。"

# 同一句里最多列几个实例。超出的收成「等 N 个」——每轮注入有 800 字符硬上限（H19），
# 十几个实例的完整清单会把三岔口本体挤掉。要看全的用 `keeper_cli.py peers`。
#
# 4.2.0 起「还有活」按 kind 分两句，这个上限是**每句各自**生效（debug 与 chore 混跑时
# 最多列 4+4=8 个）。仍守得住 800：两句合计的固定骨架约 150 字符，8 个条目按最长的
# `DBG-207→\`opus-debugger-4bb6\`` 算也就 240 字符左右。
MAX_LISTED = 4

# 与 `keeper_instance_register.KEEPER_SUBAGENT_KIND` 是一对必须同增同减的清单：
# 那边决定 name 落不落盘，这边决定落了盘的 name 会不会被读出来注进三岔口。
# 只加一边的后果是「登记了但永远不提示唤醒」或「提示唤醒一个从未登记的 kind」。
KIND_LABELS = (("debug", "debug-keeper"), ("chore", "chore-keeper"))


def _fmt_instances(items):
    """`[(issue, name)]` → `DBG-207→\\`name\\`、DBG-208→\\`name\\``，超出 MAX_LISTED 收尾。

    `issue` 为空的实例显示成「未认领编号」而不是省略：它同样占着一个 keeper，主会话
    需要知道它在那儿，否则会以为那个 name 是野的。
    """
    shown = items[:MAX_LISTED]
    parts = ["%s→`%s`" % (iid or "未认领编号", name) for iid, name in shown]
    rest = len(items) - len(shown)
    if rest > 0:
        parts.append("等 %d 个" % rest)
    return "、".join(parts)


def triage_wake_line(worktree_root, session_id):
    """算三岔口里"唤醒前怎么办"这句话。失败一律回落到"没有实例"那一支。

    `worktree_root` 是 `find_worktree_root` 的返回值（本函数不重新解析，避免重复
    起 git 子进程）；`session_id` 是本轮 `UserPromptSubmit` payload 里的 `session_id`
    字段，取不到时传 `None`——此时任何登记都判不出"匹配"，一律落到"陈旧"或"没有
    实例"两支中的一支，这是安全的降级方向（宁可多提示一次首次派发，也不要在无法
    确认的情况下让 AI 去唤醒一个可能早已不存在的实例）。

    v7 起同一档可以有多个实例，所以这里遍历的是**列表**而不是单条记录，并按
    `keeper_generation.instance_state` 分出「已收工」一组单独成句；「还有活」的再按
    kind 分成 debug / chore 两句（4.2.0 起），因为两档的处置方向相反。
    """
    if resolve_delivery_id is None or read_keeper_instances is None or not worktree_root:
        return WAKE_LINE_NONE
    try:
        delivery_id = resolve_delivery_id(worktree_root)
        data = read_keeper_instances(worktree_root, delivery_id)
    except Exception:
        return WAKE_LINE_NONE
    if not isinstance(data, dict):
        return WAKE_LINE_NONE

    delivery_root = os.path.join(worktree_root, ".keeper", delivery_id)
    live = {"debug": [], "chore": []}
    retired, has_stale = [], False
    for kind, _label in KIND_LABELS:
        for rec in data.get(kind) or []:
            if not isinstance(rec, dict):
                continue
            name = rec.get("name")
            if not isinstance(name, str) or not name:
                continue
            sid = rec.get("session_id")
            if not (session_id and isinstance(sid, str) and sid == session_id):
                has_stale = True
                continue
            issue = rec.get("issue")
            state = "unknown"
            if instance_state is not None:
                try:
                    state = instance_state(delivery_root, kind, issue)
                except Exception:
                    state = "unknown"
            # unknown 与 live 一起进「还有活」——判据看不见「刚派出、还没认领编号」
            # 这一瞬，把它算成收工会让主会话立刻重派，两个实例抢同一条 issue。
            #
            # 「还有活」再按 kind 落桶，各自成句；「已收工」不分桶，「别再唤醒」这句
            # 对两档同样成立，分开只会白占字符预算。
            if state == "retirable":
                retired.append((issue, name))
            else:
                live[kind].append((issue, name))

    segs = []
    if live["debug"]:
        segs.append(WAKE_LINE_LIVE_DEBUG % _fmt_instances(live["debug"]))
    if live["chore"]:
        segs.append(WAKE_LINE_LIVE_CHORE % _fmt_instances(live["chore"]))
    if retired:
        segs.append(WAKE_LINE_RETIRED % _fmt_instances(retired))
    if segs:
        return " ".join(segs)
    if has_stale:
        return WAKE_LINE_STALE
    return WAKE_LINE_NONE


def build_triage(wake_line):
    """组装三岔口（TRIAGE_HEAD + 唤醒句 + TRIAGE_TAIL）。"""
    return TRIAGE_HEAD + wake_line + TRIAGE_TAIL


# SessionStart：静态参考。刻意不复述三岔口（那份每轮注入）。
ENABLED = """# task-keeper 主会话侧参考

三岔口分诊每轮随 UserPromptSubmit 注入，此处不复述，以下是按需查的静态部分。

## 决策打包（主会话侧职责）

keeper 待拍板会写 `<交付>/decisions/<stamp>-<keeper>.md` 并 SendMessage 打铃。攒批处理（待拍板 ≥3 条/出现 blocking/用户问起/停顿点才处理）：一次 AskUserQuestion 并列问完（不用文本选项块），原文写 `<交付>/decisions/answers/<同名>.md` 并通知 keeper。「待拍板 N 条」由磁盘现算。

## 布局（v7）

`<worktree 根>/.keeper/<交付id>/{debug,chore,decisions}/`，交付 id 取 worktree 根 basename，非交付用 `_main`。一条 bug 全在 `debug/<DBG-id>/`。**v6 起队列正文与附件入库**（issue/receipts/index/decisions/截图都进版本库），只精确排除本机产物：`worktree/`、`.keeper-instance.json`、`.keeper-active`、`.merge.lock*`。所以截图脱敏是红线——落盘即公开。

## 多实例（v7）

同一档并存多个实例，一条 issue 一个。谁认领了哪条看每轮注入的映射，或跑 `scripts/keeper_cli.py peers --kind debug`。合并回主仓是唯一的共享资源，由 `.merge.lock` 互斥（超时 15 分钟自动抢占），实例侧走同一个 CLI 的 `lock` 子命令。

指针：skills/tk-decisions；状态看每轮注入或各队列 index.md。"""


def main():
    ev_name = "SessionStart"
    argv = sys.argv[1:]
    if "--event" in argv:
        i = argv.index("--event")
        if i + 1 < len(argv) and argv[i + 1] == "user-prompt-submit":
            ev_name = "UserPromptSubmit"
    try:
        ev = json.loads(sys.stdin.read())
    except Exception:
        ev = {}
    cwd = ev.get("cwd") or os.getcwd()
    keeper_root = find_keeper_root(cwd) if find_keeper_root else None
    enabled = bool(keeper_root)

    if ev_name == "UserPromptSubmit":
        if not enabled:
            return  # 零成本保证：未启用项目一个字符都不注入
        session_id = ev.get("session_id")
        session_id = session_id if isinstance(session_id, str) and session_id else None
        # keeper_root 形如 <worktree 根>/.keeper，取父目录拿 worktree 根——避免再起
        # 一次 git 子进程重新解析（find_keeper_root 内部已经解析过一遍）。
        worktree_root = os.path.dirname(keeper_root)
        text = build_triage(triage_wake_line(worktree_root, session_id))
    else:
        text = ENABLED if enabled else NOT_ENABLED

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": ev_name,
            "additionalContext": text,
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 注入类 hook 静默降级
