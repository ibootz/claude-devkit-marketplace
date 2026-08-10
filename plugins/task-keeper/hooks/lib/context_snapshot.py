#!/usr/bin/env python3
"""Context 队列实时快照（UserPromptSubmit）

与 chore_snapshot.py 同构、更薄。三条刻意的减法：

  · **零 git 调用**——上下文包没有 worktree 隔离，不存在「在飞」概念。
  · **不报待拍板计数、不报 gitignore 告警**。这两项现有分工是二元的：待拍板由
    chore 快照主报、debug 仅在 chore 缺失时代报；gitignore 反过来由 debug 主报、
    chore 代报。context 加进去只会在同一轮注入里出现第三遍同样的文案，而三者
    检查的是同一份磁盘状态。所以本文件**不参与**这两项，现有二元分工一行不动。
  · **不做特征词提醒**。chore 有 `CHORE_HINTS`（「记一下」「台账」等），context
    没有对应物——它的触发条件是「这次动作算不算一个功能单元」，那是语义判断，
    做成关键词只会大面积误报（几乎每轮 prompt 都在说要做点什么）。按本仓
    `hook-restraint` 的强度阶梯，这条规则的正确落点是 skill 正文与三岔口注入，
    不是 hook 判据。

## 唯一一条超出「列个清单」的机械信号：销账表填了没有

`ledger_progress()` 数 `ledger.md` 里状态列非空的行数。这是整套机制**最核心的
失效形态**——表排好了、交出去了、没人填，于是上下文包退化成一份没人读的报告，
而「规格写了没照做」照旧发生，只是这次还多留了一份「做过了」的痕迹。

它够格做 hook 判据，因为它是**纯计数**：数表格数据行里第 5 个 cell 空不空，不需要
理解任何一行写了什么。解析不出来（列数被改、格式被换）一律 fail-soft 返回 None，
按「不报」处理——宁可漏报，不可把一个格式变化说成「没人填」。

零成本保证：worktree 根下没有 `.keeper/` 就直接 return，stdout 全空。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from queue_files import CONTEXT, load_all, split_by_status, write_index
    from queue_snapshot import find_queue
except Exception:
    load_all = None

MAX_LIST = 6

# `ledger.md` 表格的列数（`| # | 约束 | 判据 | 实现位置 | 状态 | 备注 |`）与状态列
# 的下标。写成常量而不是散在代码里，是因为改 artifacts.md 的模板列数时这里必须跟着
# 改——两处不一致的表现是「永远数出 0 行已填」，而那看起来完全像是真的没人填。
LEDGER_COLS = 6
LEDGER_STATUS_IDX = 4


def ledger_progress(item_dir):
    """数 `ledger.md` 的 (已填, 总行数)。任何解析异常一律返回 None（= 不报）。

    数据行判据三条同时成立：以 `|` 开头、去掉首尾空串后恰好 `LEDGER_COLS` 个 cell、
    第一个 cell 是纯数字。第三条把表头（`| # |`）与分隔行（`|---|`）一起排除掉，
    不需要按行号跳过前两行——实现者在表格上方加说明文字是常见的，按行号跳会错位。
    """
    path = os.path.join(item_dir, "ledger.md")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return None
    total = filled = 0
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != LEDGER_COLS or not cells[0].isdigit():
            continue
        total += 1
        if cells[LEDGER_STATUS_IDX]:
            filled += 1
    return (filled, total) if total else None


def render(queue_dir):
    items = load_all(queue_dir, CONTEXT)
    op, dn, unk = split_by_status(items)
    lines = []

    if op:
        parts, unfilled = [], []
        for fm, _b, path in op[:MAX_LIST]:
            tag = str(fm.get("id"))
            if fm.get("stage"):
                tag += "(%s)" % fm["stage"]
            # sources 只能是 5 或 3。3 = 降级为三方印证，必须可见——它是判断这份包
            # 可信到什么程度的第一个数字，埋在正文里等于没有。
            if str(fm.get("sources") or "") == "3":
                tag += "·三方"
            inc = fm.get("inconsistent")
            if inc and str(inc) != "0":
                tag += "·不一致%s" % inc
            parts.append(tag)

            prog = ledger_progress(os.path.dirname(str(path)))
            if prog and prog[0] == 0:
                unfilled.append("%s(%d 行未填)" % (fm.get("id"), prog[1]))

        more = " +%d" % (len(op) - MAX_LIST) if len(op) > MAX_LIST else ""
        lines.append("open %d: %s%s" % (len(op), " ".join(parts), more))
        if unfilled:
            lines.append("⚠ 销账表无人填：%s —— 包交出去了没人销账，等于没收集。"
                         "催实现者逐行填，或问清楚是不是已经绕开这份包动手了。"
                         % "、".join(unfilled))
    else:
        lines.append("open 0（无在途上下文包）")

    if dn:
        lines.append("done %d（已跑过事后核对）" % len(dn))
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

    if load_all is None:
        return
    found = find_queue(cwd, CONTEXT)
    if found is None:
        return  # 未启用 task-keeper，或在 fixer worktree 里：零成本静默退出
    queue_dir = str(found)

    try:
        write_index(queue_dir, CONTEXT)
    except Exception:
        pass

    out = ["# Context 队列（%s · harness 注入，非 AI 记忆）" % queue_dir]
    out += render(queue_dir)
    out.append("纪律：实现/修改业务功能前先请一次上下文包——转 context-keeper 收集，"
               "它只汇报不实现；`status` 翻 done 的唯一判据是跑过事后核对。")

    print("\n".join(out))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 任何异常都不得阻断用户 prompt 提交
