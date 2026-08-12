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

  · 登记存在且 `session_id` 与当前一致 → 直接告诉 AI "唤醒 `<真实 name>`"。
  · 登记存在但不一致（或是加 `session_id` 之前落的旧格式，压根没这个键）→ 告诉
    AI "这份登记已失效，当首次派发处理"。
  · 没有任何登记 → 保持原来的措辞，首次派发。

同一轮只注入当下成立的那一种——预算是每轮成本，把三种都注等于把预算浪费在另外
两种当下不成立的分支上。

## 第 4 种状态：登记有效但这一代已经收口，建议换代（2026-08-10 加）

上面第一支「唤醒它」在 2026-08-10 起再分两路：`keeper_generation.retirable_kinds`
现算这个 kind 的队列是不是已经收口（done 非空 / open 空 / unknown 空 / 无待答复裁决
/ debug 还要求无残留 worktree），收口了就改成建议**新派一代**而不是继续唤醒。

为什么要有代际：在飞面板那一行的 description 在派发那一刻就永久定格，SendMessage
与 SubagentStart hook 两条通道都写不回它（对 CLI 2.1.226 逐条核实过）。常驻实例活
整场会话，那一行就定格整场会话，看板价值归零。换代把定格的粒度从「一场会话」缩小
到「一批活」，配套 working-discipline 的 check 11 把 description 判据从「逐字固定串」
放宽为「`<kind> 队列` 前缀 + 本批摘要」，两者缺一都不成立。

**这一支给的是建议不是命令**：判据看不见「keeper 正在推理、活还没落盘」这一瞬间，
所以措辞用「可退场」而不是「必须重派」。主会话若明知刚转过活过去，照常唤醒即可。

判定失败（import 不到、解析异常）一律回落到「全部唤醒」——那是加换代之前的行为。

`debug`/`chore` 两档可以各自处在不同状态（一个还在跑、另一个已收口），此时两段话
同时出现在同一句里，H29 的 [134] 断言这个形态。
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
    from keeper_generation import retirable_kinds
except Exception:
    retirable_kinds = None

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
2. 转 debug-keeper：bug/报错/异常行为，逐字转发（首次 `Agent` 派出，之后 `SendMessage` 唤醒）。属于既有交付流程的活走该流程。
3. 转 chore-keeper：台账/沉淀/收尾/外部系统小操作等杂务，逐字转发。
4. 转 context-keeper：**动手前**收齐某功能单元的规格/约束（implement 前、debug 派 fixer 前），转发用户原话 + 单元边界。

"""

TRIAGE_TAIL = """

三原则：逐字（不改写原话）、即回（转完回主线不追问进度）、不越位（`.keeper/` 队列你只读）。

最常见失效是「这个我顺手做了更快」——转发是为了不让任务状态只活在本轮上下文里，compact 一次就没了。"""

# 分支 1：没有任何登记（本会话与之前任何会话都没派过）——保持原有措辞。
# 句尾补一句 description 提示（≤30 汉字）：working-discipline 的 agent-dispatch
# check 11 要求 keeper 的 description 以 `<kind> 队列` 起头，首次派发就写对可省一轮 deny。
# 2026-08-10 起前缀之后可以（也应该）接本批摘要，见 keeper_generation 模块头「为什么需要换代」。
WAKE_LINE_NONE = ("还没有登记：首次转发用 `Agent` 派出，name 自带 4 位随机短哈希后缀，"
                   "description 写『<kind> 队列 · <本批摘要>』，前缀不可省。")

# 分支 3：登记存在但不属于本会话（session_id 不一致，或是加会话隔离之前落的旧格式、
# 压根没有 session_id 键）——一律当陈旧处理，判据见 keeper_paths.read_keeper_instance_name。
WAKE_LINE_STALE = ("`.keeper-instance.json` 的登记来自上一个会话，已失效：当首次派发，"
                    "用 `Agent` 派出并生成新的 4 位随机短哈希后缀，"
                    "description 写『<kind> 队列 · <本批摘要>』。")

# 分支 4（2026-08-10 加）：登记有效、实例还在，但这一代手上的活已经全部收口——
# 建议换代而不是继续唤醒。判据在 `keeper_generation.retirable_kinds`（四项全过），
# 那边的模块头写清了为什么换代不需要「作废登记」这个动作（覆盖写即代际交替）。
#
# **这一支是建议不是命令**：判据看不见「keeper 正在推理、活还没落盘」这一瞬间，
# 所以主会话若明知刚转过活过去，照常唤醒即可。措辞用「可以」不用「必须」。
WAKE_LINE_RETIRE = ("%s 手上的活已收口（open 0 / 无待拍板 / 无残留 worktree），"
                    "这一代可退场：本次改用 `Agent` 新派（name 换新短哈希，"
                    "description 写『%s 队列 · <本批摘要>』），旧登记会被自动覆盖。")

# 与 `keeper_instance_register.KEEPER_SUBAGENT_KIND` 是一对必须同增同减的清单：
# 那边决定 name 落不落盘，这边决定落了盘的 name 会不会被读出来注进三岔口。
# 只加一边的后果是「登记了但永远不提示唤醒」或「提示唤醒一个从未登记的 kind」。
KIND_LABELS = (("debug", "debug-keeper"), ("chore", "chore-keeper"),
               ("context", "context-keeper"))


def triage_wake_line(worktree_root, session_id):
    """算三岔口里"唤醒前怎么办"这句话，三选一，失败一律回落到"没有登记"这一支。

    `worktree_root` 是 `find_worktree_root` 的返回值（本函数不重新解析，避免重复
    起 git 子进程）；`session_id` 是本轮 `UserPromptSubmit` payload 里的 `session_id`
    字段，取不到时传 `None`——此时任何登记都判不出"匹配"，一律落到"陈旧"或"没有
    登记"两支中的一支，这是安全的降级方向（宁可多提示一次首次派发，也不要在无法
    确认的情况下让 AI 去唤醒一个可能早已不存在的实例）。

    `debug`/`chore` 两档分别判断：session_id 匹配的进 matched，登记存在但不匹配
    （含旧格式无 session_id 键）的进 stale。matched 非空优先；否则 stale 非空则
    提陈旧；两者都空则是"没有登记"。
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

    matched, stale = [], []
    for kind, label in KIND_LABELS:
        entry = data.get(kind)
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        entry_session_id = entry.get("session_id")
        if session_id and isinstance(entry_session_id, str) and entry_session_id == session_id:
            matched.append((kind, label, name))
        else:
            stale.append((label, name))

    if matched:
        # 有效实例再分两路：手上活已收口的建议换代（分支 4），其余照旧唤醒。
        # 判定失败一律回落到「全部唤醒」——那是加换代之前的行为，安全方向。
        retire_set = set()
        if retirable_kinds is not None:
            try:
                retire_set = retirable_kinds(
                    os.path.join(worktree_root, ".keeper", delivery_id))
            except Exception:
                retire_set = set()
        wake = [(l, n) for k, l, n in matched if k not in retire_set]
        retire = [(k, l, n) for k, l, n in matched if k in retire_set]
        segs = []
        if wake:
            parts = "、".join("%s（name `%s`）" % (l, n) for l, n in wake)
            segs.append("本会话已有 %s在跑，用 `SendMessage` 唤醒它，不要重派。" % parts)
        for kind, label, _name in retire:
            segs.append(WAKE_LINE_RETIRE % (label, kind))
        return " ".join(segs)
    if stale:
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

## 布局（v5）

`<worktree 根>/.keeper/<交付id>/{debug,chore,context,decisions}/`，交付 id 取 worktree 根 basename，非交付用 `_main`。一条 bug 全在 `debug/<DBG-id>/`，一个上下文包全在 `context/<CTX-id>/`。**v6 起队列正文与附件入库**（issue/receipts/index/decisions/截图都进版本库），只精确排除三类本机产物：`worktree/`、`.keeper-instance.json`、`.keeper-active`。所以截图脱敏是红线——落盘即公开。

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
