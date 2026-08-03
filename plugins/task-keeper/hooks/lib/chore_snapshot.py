#!/usr/bin/env python3
"""Chore 队列实时快照（UserPromptSubmit）

与 queue_snapshot.py（debug 队列）同构但刻意更薄：
  · **零 git 调用**——杂务没有 worktree 隔离（chore-keeper 在共享工作区攒批执行），
    不存在「在飞」概念，也就不需要 `git worktree list`。
  · 注入体目标 ≤900 字符（回归测试 H14 有 wc -c 预算断言）——chore 是低频背景事务，
    不配吃掉主会话更多注意力预算。

判据与存储层全部复用 queue_files.py 的 CHORE spec，不复制第二份实现。

零成本保证：当前 worktree 根下没有 `.keeper/`（= 项目未启用 task-keeper）就直接
return，stdout 全空。**`.keeper/` 已存在但 `<交付id>/chore/` 缺失时不再零输出**
——2026-08-03 起 `find_queue` 会自动补建该目录（连同 `debug/` 一起），理由见
`queue_snapshot.py` 的 `find_queue` docstring「为什么自动补建」：旧行为让缺失的
那条队列永远无法启用（零输出 → 主会话收不到提醒 → keeper 从不被派出 → 它冷启动
里那句 mkdir 永不执行 → 目录继续不存在）。

待拍板计数（decision_inbox）随本快照注入；debug 快照只在 chore 未启用时代为注入，
两边不重复（判据：`<交付>/chore` 目录存在性）。**自动补建后这个判据恒为「chore
已启用」**，所以待拍板计数稳定由本文件注入、debug 侧不再代劳；补建当轮也不会重复，
因为 `find_queue` 把 `debug/` 与 `chore/` 一起建（见 `_sibling_queue_names`）。

v4 起路径改为 `<worktree 根>/.keeper/<交付id>/chore/CHR-NNN/item.md`，根解析与
find_queue 全部复用 queue_snapshot 那份（它已委托给 keeper_paths）。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from queue_files import CHORE, load_all, split_by_status, write_index, next_id
    from queue_snapshot import find_queue, gitignore_findings
    from decision_inbox import summary_line
except Exception:
    load_all = None

MAX_LIST = 8


def sibling_chore_dirs(queue_dir):
    """`.keeper/*/chore` 全部交付目录，供 `next_id` 取全局最大值（判据 4）。"""
    try:
        import keeper_paths
        keeper_root = os.path.dirname(os.path.dirname(os.path.abspath(queue_dir)))
        return keeper_paths.all_queue_dirs(keeper_root, CHORE)
    except Exception:
        return []

# 杂务特征词。命中即追加 register-first 提醒（只在 `.keeper/` 顶层已存在 = 项目
# opt-in 时生效；chore 子目录本身由 find_queue 自动补建，不再是 opt-in 判据）。
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
    found = find_queue(cwd, CHORE)
    if found is None:
        return  # 未启用 task-keeper（无 .keeper/）或在 fixer worktree 里：零成本静默退出
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

    # gitignore 告警只由 debug 快照报一次；两个队列都报会在同一轮注入里重复两遍
    # 同样的文案，而它们检查的是同一个文件。debug 未启用时这里代报。
    if not os.path.isdir(os.path.join(os.path.dirname(queue_dir), "debug")):
        out += gitignore_findings(queue_dir)

    out.append("纪律：杂务只登记不亲手做——转 chore-keeper（SendMessage 唤醒，首次 "
               "Agent 派出）后回原任务；一切外部系统写由 keeper 打包过用户后才执行。")

    if CHORE_HINTS.search(prompt):
        try:
            nid = next_id(queue_dir, CHORE, sibling_dirs=sibling_chore_dirs(queue_dir))
        except Exception:
            nid = "<下一个 CHR-id>"
        out.append("⚠ 本轮疑似杂务：转给 chore-keeper 登记为 `%s/%s/item.md`"
                   "（用户原话逐字带上），不要在主会话亲手做。" % (queue_dir, nid))

    print("\n".join(out))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 任何异常都不得阻断用户 prompt 提交
