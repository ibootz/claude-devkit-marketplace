#!/usr/bin/env python3
"""决策信箱计数（被 chore_snapshot / queue_snapshot 复用，也可单独执行自测）

## 协议背景（正典在 skills/tk-decisions/SKILL.md）

subagent 永远拿不到 AskUserQuestion（harness 永久黑名单），keeper 需要 Human 拍板时
只能走文件 + SendMessage 中继：keeper 写 `.keeper/decisions/<stamp>-<keeper>.md`，
主会话拿到用户裁决后写 `.keeper/decisions/answers/<同名>.md` 回给它。
本模块只做一件事：数「还没有答复的决策文件」，供每轮快照注入一行计数——
SendMessage 可能被 auto-compact 挤掉，磁盘现算的计数是不依赖对话记忆的兜底。

## 判据全部机械

  · 待拍板 = `decisions/*.md` 存在而 `decisions/answers/<同名>.md` 不存在。
    文件存在性判据，不解析语义。**answers/ 子目录本身不算决策文件**。
  · blocking = frontmatter 里 `blocking: true` 一行（宽松匹配布尔真值写法）。
    keeper 写文件时按 tk-decisions skill 的模板写这行；写错或缺失按非
    blocking 计——计数偏保守不偏打扰。
"""
import os
import re

BLOCKING_RE = re.compile(r"^blocking:\s*(true|yes|on)\s*$", re.I | re.M)


def decisions_dir(keeper_root):
    """keeper_root = 项目根下的 .keeper 目录绝对路径。"""
    return os.path.join(keeper_root, "decisions")


def pending_decisions(keeper_root):
    """返回 [(文件名, 是否 blocking)]，按文件名排序（文件名以时间戳开头即时间序）。"""
    d = decisions_dir(keeper_root)
    if not os.path.isdir(d):
        return []
    answers = set()
    adir = os.path.join(d, "answers")
    if os.path.isdir(adir):
        answers = {n for n in os.listdir(adir) if n.endswith(".md")}
    out = []
    for name in sorted(os.listdir(d)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(d, name)
        if not os.path.isfile(path):
            continue
        if name in answers:
            continue
        blocking = False
        try:
            with open(path, encoding="utf-8") as f:
                head = f.read(2048)   # frontmatter 在头部，读 2K 足够
            blocking = bool(BLOCKING_RE.search(head))
        except Exception:
            pass
        out.append((name, blocking))
    return out


def summary_line(keeper_root):
    """给快照注入用的一行摘要；无待拍板时返回 None（零成本）。"""
    items = pending_decisions(keeper_root)
    if not items:
        return None
    blocking = sum(1 for _n, b in items if b)
    tail = "（其中 blocking %d 条，有 keeper 停在原地等）" % blocking if blocking else ""
    return ("⚠ 待拍板 %d 条%s：`.keeper/decisions/` 逐个打开，攒批后一次 AskUserQuestion "
            "并列问完，答复原文写 `answers/<同名>.md` 并 SendMessage 通知对应 keeper。"
            % (len(items), tail))


if __name__ == "__main__":
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), ".keeper")
    line = summary_line(root)
    print(line or "（无待拍板）")
