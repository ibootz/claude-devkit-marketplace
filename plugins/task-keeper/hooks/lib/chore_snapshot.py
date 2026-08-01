#!/usr/bin/env python3
"""Chore 队列实时快照（UserPromptSubmit）

与 queue_snapshot.py（debug 队列）同构但刻意更薄：
  · **零 git 调用**——杂务没有 worktree 隔离（chore-keeper 在共享工作区攒批执行），
    不存在「在飞」概念，也就不需要 `git worktree list`。
  · 注入体目标 ≤900 字符（回归测试 H14 有 wc -c 预算断言）——chore 是低频背景事务，
    不配吃掉主会话更多注意力预算。

判据与存储层全部复用 queue_files.py 的 CHORE spec，不复制第二份实现。

零成本保证：从 cwd 向上（到 .git 为止）找不到 `.keeper/chore/items/` 就直接
return，stdout 全空。待拍板计数（decision_inbox）随本快照注入；debug 快照只在
chore 未启用时代为注入，两边不重复（判据：`.keeper/chore/items` 目录存在性）。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from queue_files import CHORE, load_all, split_by_status, write_index, next_id
    from queue_snapshot import find_queue, gitignore_missing_keeper
    from decision_inbox import summary_line
except Exception:
    load_all = None

MAX_LIST = 8

# 杂务特征词。命中即追加 register-first 提醒（只在队列已存在 = 项目 opt-in 时生效）。
CHORE_HINTS = re.compile(
    r"记一下|记个账|台账|沉淀|归档一下|收尾|整理一下|补个文档|补一下文档|"
    r"同步到|登记一下|回头做|之后做|别忘了",
    re.IGNORECASE,
)


def render(queue_dir):
    items = load_all(queue_dir, CHORE)
    op, dn, unk = split_by_status(items)
    lines = []

    if op:
        parts = []
        for fm, _b, _p in op[:MAX_LIST]:
            tag = str(fm.get("id"))
            if fm.get("kind"):
                tag += "(%s)" % fm["kind"]
            if fm.get("external_write"):
                tag += "·外部写"
            parts.append(tag)
        more = " +%d" % (len(op) - MAX_LIST) if len(op) > MAX_LIST else ""
        lines.append("open %d: %s%s" % (len(op), " ".join(parts), more))
    else:
        lines.append("open 0（杂务队列已清空）")

    if dn:
        lines.append("done %d（正文不进上下文）" % len(dn))
    if unk:
        lines.append("⚠ 读不懂 %d: %s —— frontmatter 损坏或 status 不是 open/done，先修好"
                     % (len(unk), ",".join(str(fm.get("id")) for fm, _b, _p in unk)))
    return lines


def main():
    try:
        ev = json.loads(sys.stdin.read())
    except Exception:
        ev = {}
    cwd = ev.get("cwd") or os.getcwd()
    prompt = ev.get("prompt") or ""

    if load_all is None:
        return
    found = find_queue(cwd, CHORE.dir_name, CHORE.item_dir)
    if found is None:
        return  # 未启用 chore 队列：零成本静默退出
    queue_dir = str(found)

    try:
        write_index(queue_dir, CHORE)
    except Exception:
        pass

    out = ["# Chore 队列（%s · harness 注入，非 AI 记忆）" % queue_dir]
    out += render(queue_dir)

    try:
        dline = summary_line(os.path.dirname(queue_dir))
        if dline:
            out.append(dline)
    except Exception:
        pass

    if gitignore_missing_keeper(queue_dir):
        out.append("⚠ 项目 `.gitignore` 缺 `.keeper/` 行——请追加并回读验证。")

    out.append("纪律：杂务只登记不亲手做——转 chore-keeper（SendMessage 唤醒，首次 "
               "Agent 派出）后回原任务；一切外部系统写由 keeper 打包过用户后才执行。")

    if CHORE_HINTS.search(prompt):
        try:
            nid = next_id(queue_dir, CHORE)
        except Exception:
            nid = "<下一个 CHR-id>"
        out.append("⚠ 本轮疑似杂务：转给 chore-keeper 登记为 `.keeper/chore/items/%s.md`"
                   "（用户原话逐字带上），不要在主会话亲手做。" % nid)

    print("\n".join(out))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 任何异常都不得阻断用户 prompt 提交
