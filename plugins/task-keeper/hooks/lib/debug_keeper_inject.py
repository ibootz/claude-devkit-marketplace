#!/usr/bin/env python3
"""SubagentStart 注入：debug-keeper 每次醒来，把「漏派清单」递到它眼前。

## 要解决的真实症状

debug-keeper 登记完一条 bug 后，随着新 bug 陆续进来，它会忘了把之前登记、且已经
triage 完的那条捡起来派 fixer——那条 issue 卡在原地，既不在飞、也没人在等它的拍板，
纯粹是被后来的条目挤出了注意力。

病根在 `agents/debug-keeper.md` §0 那段纪律：它**明确禁止** keeper 每次被唤醒都重读
一遍全部 `issue.md`（理由是上下文跨唤醒完整保留、靠记忆就够，重读浪费 token）。那个
判断本身有道理——重读整个队列确实贵——但它赌的是「keeper 的记忆不漂移」，且**没有
配任何机械替代**。长会话里新 bug 持续挤进来时，这个赌注会输。

本模块就是那个缺失的机械替代：不要 keeper 自己去读，由 hook 每次替它算好、递到眼前。
省下的仍然是重读整个队列的开销（本模块只注入一行），补上的是「已登记未派」这个状态
的可靠性。

## 为什么挂 SubagentStart（实测，不是推演）

`UserPromptSubmit` 与 `SessionStart` 的注入**不进子代理**（语义上子代理没有「用户提交
prompt」这个动作），所以 task-keeper 原有的三个 `UserPromptSubmit` 快照 hook 一行都到
不了 keeper 手里——它们伺候的是主会话。能给子代理注入开场上下文的只有 `SubagentStart`。

关键的一条是：`SubagentStart` **不只在子代理首次被 `Agent` 派出时触发**。2026-08-05 实测
（探针子代理连做三轮，逐轮报告自己上下文里同一段注入出现了几次）：

  · 首次 `Agent` 派出           → 该段注入出现第 1 次
  · 第一次 `SendMessage` 唤醒它 → 出现第 2 次（紧跟唤醒消息之后）
  · 第二次 `SendMessage` 唤醒它 → 出现第 3 次

两次唤醒都重注入，且探针每轮都能完整复述上一轮自己写的答案（transcript 完整保留、
不是从零开始）。这条实测是本模块可行的前提——debug-keeper 恰恰是「派出一次、之后全靠
`SendMessage` 反复唤醒」的常驻实例，若注入只在首次派出时发生一次，那一次的队列几乎还是
空的，恰好不在症状发生的时刻，整套机制就等于没做。

## 判据全部机械（照 .claude/rules/project/hook-restraint.md 的分界线）

本模块自己**不做任何判定**，漏派集合由 `skills/tk-board/scripts/pending_dispatch.py`
现算，判据是四个确定字段与两次集合差（`status == "open"` / `priority` 与 `difficulty`
非空 / 不在 `git worktree list` 的 DBG-* 集合里 / 不在未答复 decisions 的 about 集合里）。
不解析任何自然语言语义。

**刻意不重新实现那四条判据**：同一判据落在两份代码里，早晚会漂移成两个结论——本仓
已经在「文档写 5 而代码写 4」这类事上吃过账（见 `hook-restraint.md` 实证 5）。这里宁可
多起一个 python 子进程。

## 强度：纯注入，零拦截

按 `hook-restraint.md` 的强度阶梯，本模块停在第 2 档（注入提醒）。它不阻止任何操作，
失败模式只是「多占了几十字符的上下文预算」，所以判据严格性不是它的风险点。任何异常
一律静默降级为「不注入」——见 main() 末尾。**绝不因为算不出漏派就阻断 keeper 启动**。

## 为什么注入的是状态而不是纪律

「派 fixer 要一条消息批量发出」「blocking 只冻结那一条 issue」这类**静态纪律**已经写在
`agents/debug-keeper.md` 里，而 agent 定义是 keeper 的 system prompt、每次唤醒都在场，
不需要 hook 再抄一遍。hook 的独占价值是**注入 agent 定义装不进去的东西**——当前时刻的
落盘状态。静态纪律下沉进 agent 定义、动态状态留给 hook，两层各司其职。
"""
import json
import os
import subprocess
import sys

# 只伺候这一个 agent_type。plugin.json 的 matcher 已经按它过滤了，这里再查一次是双保险：
# 万一将来 matcher 语义变化或配置写错，也不会把 debug 队列的清单灌给每一个子代理。
TARGET_AGENT_TYPE = "task-keeper:debug-keeper"

# 回声白名单。hookEventName 必须与入参 hook_event_name 一致，否则该路注入静默失效
# （不报错、不告警，与压根没挂的外观完全相同——见 hook-restraint.md「注入类 hook 的
# 事件落点」）。这里只允许这一个值，不把 payload 里的任意字符串原样回声出去。
ALLOWED_EVENTS = {"SubagentStart"}

# pending_dispatch.py 相对本文件的位置：hooks/lib/ → 上两级到插件根 → skills/tk-board/scripts/
_HERE = os.path.dirname(os.path.abspath(__file__))
PENDING_DISPATCH = os.path.join(
    _HERE, "..", "..", "skills", "tk-board", "scripts", "pending_dispatch.py"
)


def oneline(cwd):
    """跑 pending_dispatch.py --oneline，返回那一行；无漏派或出任何岔子都返回 ""。

    契约（见 pending_dispatch.py 文件头「退出码」与「三种输出模式」两节）：
      · 有漏派   → stdout 一行摘要，退出码 0
      · 无漏派   → stdout 空串，   退出码 0
      · 执行错误 → 退出码非 0
    所以「输出非空」即「有漏派」，零成本判据，不需要解析 JSON。
    """
    script = os.path.normpath(PENDING_DISPATCH)
    if not os.path.isfile(script):
        return ""
    try:
        proc = subprocess.run(
            [sys.executable or "/usr/bin/python3", script, "--oneline"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        # 超时、python 不可用、权限问题等一律当「没算出来」。注入类 hook 不许把自己的
        # 故障变成 keeper 的故障。
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def render(line):
    """把那一行包成给 keeper 看的注入体。附处置指引，不只是报数字。"""
    return (
        "# 漏派体检（harness 每次唤醒现算，非你的记忆）\n\n"
        "%s\n\n"
        "这几条 **status 仍是 open、triage 已完成（priority 与 difficulty 都有值）、"
        "但既没有 worktree 在飞、也不在等 Human 拍板**——判据机械，四条全由磁盘与 "
        "`git worktree list` 现算，不是推测。成因通常是它们被后来登记的条目挤出了你的"
        "注意力。\n\n"
        "本轮处置：先把它们连同本次唤醒带来的新事项**一起**盘进派发批次，再动手。"
        "一条 `init --ids` 建齐全部 worktree，然后 K 个 `Agent` 调用放**同一条消息**"
        "发出（细则见你的 §6）。\n\n"
        "不必因此重读整个队列——这一行已经是差集结果。要看单条正文再打开那条的 "
        "`issue.md`。" % line
    )


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    event = payload.get("hook_event_name")
    if event not in ALLOWED_EVENTS:
        return

    # matcher 已过滤，这里是双保险；读不到 agent_type 时**不注入**（宁缺勿滥——把 debug
    # 队列的清单灌给一个无关子代理，是纯噪音且会误导它去干不属于它的事）。
    if payload.get("agent_type") != TARGET_AGENT_TYPE:
        return

    cwd = payload.get("cwd") or os.getcwd()
    line = oneline(cwd)
    if not line:
        # 无漏派 = 零注入。这是常态，不该占 keeper 一个字的预算。
        return

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": render(line),
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # 兜底：注入类 hook 一律静默降级，绝不阻断子代理启动。
        pass
