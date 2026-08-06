#!/usr/bin/env python3
"""漏派体检：算出 debug 队列里「已 triage、但没人管」的那批 issue。

**只读脚本，没有任何写副作用**——不落盘、不 mkdir、不做任何 `git` 写操作。定位队列一律传
`keeper_paths.queue_dir(..., write_back=False)`，与 `board.py` 同一纪律（见其文件头
:4-7）。跑多少次都不改变队列或工作区状态。

## 要解决的真实症状

debug-keeper 登记完一条 bug 后，随着新 bug 陆续进来，它有时会忘了把之前登记、且已经
triage 完的那条捡起来派 fixer——issue 卡在原地，既不在飞、也没人在等它的拍板，纯粹是
被后来的条目挤出了注意力。看板（`board.py`）能看出「未解决」有多少条，但「未解决」桶里
混着两种性质完全不同的条目：**还没 triage**（keeper 的正常待办，不该催）与**triage 完了
却没派**（漏派，该催）。本脚本只挑后一种。

## 「漏派」的判据（四条全机械，不解析任何自然语言语义）

```
漏派 = { issue | status == "open"
                且 priority 与 difficulty 都非空（= triage 已完成）
                且 该 id 不在 `git worktree list` 的 DBG-* 集合里（= 没派 fixer）
                且 该 id 不在「未答复的 decisions」的 about 字段集合里（= 不是在等拍板） }
```

四个判据各自委托给现成模块，本文件不重新发明任何一个：

1. `status`/`priority`/`difficulty` —— `queue_files.load_all()` 解析出的 frontmatter dict。
2. 在飞 —— `queue_snapshot.worktree_in_flight(cwd)`，直接跑 `git worktree list --porcelain`
   正则抓路径里的 `DBG-\\d+`。**这是权威口径**，故意不用 `os.path.isdir(<条目目录>/worktree)`
   那种判据——`board.py:202` 的 `derive_state` 用的正是后者（判断进行中态时看条目目录下有没有
   `worktree/` 子目录），与本脚本的口径存在分叉可能：例如 fixer 已经把 `git worktree remove`
   跑了但条目目录里的 `worktree/` 残留（或反过来，worktree 已建但因为某种原因目录判断失手），
   两个口径会给出不同结论。这是已知的实现细节差异，不是本脚本的 bug，也不是 `board.py` 的
   bug——只是两个脚本各自选了不同的现成判据，使用者需要知道这一点，不能假设两边永远一致。
3. 待拍板 —— `decision_inbox.pending_decisions()` 给出「未答复决策文件名 + blocking」，
   但它不解析 `about:` 字段（全文没有一处），本文件按 `tk-decisions/SKILL.md`「决策文件格式」
   一节自己解析（复用 `board.py` 已验证过的 `ABOUT_RE`/`ID_RE` 写法）。
4. 交付/keeper 根定位 —— `keeper_paths.queue_dir()` / `find_keeper_root()` / `all_queue_dirs()`。

## 追踪停止条件

仅限 `plugins/task-keeper/` 目录树内部（读依赖模块、读队列文件、读决策文件）。不追
Claude Code 本身的实现，不追其他插件。

## 退出码

`0` = 正常执行完，**无论有没有漏派**——「有漏派」是这个脚本的正常产出，不是错误。
非 `0` 只用于真正执行不下去的错误：依赖模块导入失败、显式给的 `--queue-dir` 不存在。
**「自动探测到 `.keeper/` 顶层不存在」不算错误**——那是 task-keeper 未在本项目启用的
正常状态（与 `keeper_paths.find_keeper_root` 的 opt-in 语义一致，也是 `board.py`
遇到同样情况时的处理方式：打印一句提示、退出码仍是 0）。二者的区别只在于「谁的责任」：
自动探测落空是环境的常态，显式路径给错是调用方的输入错误。

不要用退出码表达「有没有漏派」——那会让调用方（尤其是 hook）无法区分「有漏派」和
「脚本坏了」，两者需要完全不同的处置。

## 三种输出模式

- 默认（人/AI 读）：每条一行 `DBG-017 [P1/medium] 已 triage 未派发`；无漏派时输出
  一行「无漏派」而不是空输出——空输出无法区分「真的没有」与「脚本啥也没干」。
- `--json`：机器可读，供 hook 的 `additionalContext` 或其他脚本消费。
- `--oneline`：压成一行摘要，供注入文案直接引用；无漏派时输出**空字符串**、退出码 0
  ——调用方可以用「输出非空」当判据，零成本。

`--oneline` 与 `--json` 是同一件事的两种消费形态，互斥（同一次调用只切一种）。
"""
import argparse
import io
import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "hooks", "lib"))

try:
    from queue_files import DEBUG, load_all, STATUS_OPEN
except Exception as e:
    sys.exit("无法导入 queue_files（应在 plugins/task-keeper/hooks/lib/）：%s" % e)

try:
    from queue_snapshot import worktree_in_flight
except Exception as e:
    sys.exit("无法导入 queue_snapshot（应在 plugins/task-keeper/hooks/lib/）：%s" % e)

try:
    import decision_inbox
except Exception as e:
    sys.exit("无法导入 decision_inbox（应在 plugins/task-keeper/hooks/lib/）：%s" % e)

try:
    import keeper_paths
except Exception as e:
    sys.exit("无法导入 keeper_paths（应在 plugins/task-keeper/hooks/lib/）：%s" % e)

# `about:` 字段的解析。与 `board.py` 的 `ABOUT_RE`/`ID_RE` 逐字一致——这段判据已经在
# 真实队列（151 条 debug）上验证过，不重新发明一份可能不一致的正则。
ABOUT_RE = re.compile(r"^about:\s*(.+?)\s*$", re.I | re.M)
ID_RE = re.compile(r"\b(%s-\d+)\b" % re.escape(DEBUG.prefix), re.I)


def pending_about_ids(delivery_root):
    """未答复决策文件的 `about:` 指向的 DBG id 集合，外加一份「读不懂」清单。

    返回 (ids, unreadable)：
      · ids —— 排除集合，漏派判定要用它把「在等拍板」的 issue 摘出去。
      · unreadable —— 决策文件存在但读不出内容（IO 异常）的文件名列表，必须可见，
        不能静默吞掉：读不到的决策文件既不能确认它 about 了谁，也不能确认它没 about
        任何人，若悄悄当成「没有排除任何 issue」处理，可能把一条正在等拍板的 issue
        误判成漏派——这属于「读不懂的东西不能静默丢弃」的同一类教训（v2 的教训见
        `queue_files.py` 模块头），所以单独列出来交人判断，而不是塞进 ids 或直接丢弃。

    `about: "-"`（跨 issue 决策，边界 (d)）是合法输入：`ID_RE` 抽不出任何 `DBG-\\d+`，
    自然不排除任何具体 issue——这正是预期行为，不需要特判。

    `decisions/` 目录不存在（边界 (c)）：`decision_inbox.pending_decisions()` 直接
    返回空列表，这里自然得到空集合，不需要特判。
    """
    items = decision_inbox.pending_decisions(delivery_root)  # [(文件名, blocking)]
    d = decision_inbox.decisions_dir(delivery_root)
    ids, unreadable = set(), []
    for name, _blocking in items:
        path = os.path.join(d, name)
        try:
            head = io.open(path, encoding="utf-8").read(2048)  # frontmatter 在头部
        except Exception:
            unreadable.append(name)
            continue
        m = ABOUT_RE.search(head)
        if not m:
            continue
        for iid in ID_RE.findall(m.group(1)):
            ids.add(iid.upper())
    return ids, unreadable


def compute(queue_dir, cwd):
    """算出一个交付目录下的漏派集合。

    返回 dict：
      · underdispatched —— [fm, ...]，漏派条目的 frontmatter dict，按 id 数字序
        （`load_all` 已排好，这里不重排）。
      · broken —— [fm, ...]，`_broken` 标记的条目（frontmatter 损坏，边界 (b)）。
        **不计入漏派、也不计入非漏派**——priority/difficulty 读不出来，无法确认
        triage 是否完成，机械判据在这类条目上不成立；但必须可见，理由与
        `queue_files.load_all` 一致：读不懂的东西不能静默消失。
      · unreadable_decisions —— 决策文件读不出来的文件名列表，同样必须可见。
    """
    delivery_root = os.path.dirname(queue_dir)
    flight = worktree_in_flight(cwd)                      # {DBG-id: worktree 绝对路径}
    pending_ids, unreadable = pending_about_ids(delivery_root)

    underdispatched, broken = [], []
    for fm, _body, _path in load_all(queue_dir, DEBUG):
        if fm.get("_broken"):
            broken.append(fm)
            continue
        if str(fm.get("status", "")).strip() != STATUS_OPEN:
            continue
        priority = str(fm.get("priority") or "").strip()
        difficulty = str(fm.get("difficulty") or "").strip()
        if not priority or not difficulty:
            continue                                       # 未 triage：keeper 的正常待办，不算漏派
        iid = str(fm.get("id", "")).strip().upper()
        if iid in flight:
            continue                                        # 已派 fixer
        if iid in pending_ids:
            continue                                         # 在等拍板
        underdispatched.append(fm)

    return {"underdispatched": underdispatched, "broken": broken,
            "unreadable_decisions": unreadable}


def resolve_targets(cwd, queue_dir_arg, all_deliveries):
    """算出要检查的 (queue_dir, git_cwd) 列表；找不到队列返回 (None, None, reason)。

    `git_cwd` 是喂给 `worktree_in_flight` 的目录——不能直接用 `os.getcwd()`：
    `--queue-dir` 显式指到别处时，`os.getcwd()` 未必落在同一个 git 工作区内，
    `git worktree list` 会跑错仓库却不报错（静默返回空，进而把所有条目误判成
    「不在飞」）。这里统一从队列目录反推 worktree 根：`<根>/.keeper/<交付id>/<dir_name>`
    上溯两级即根。
    """
    def git_cwd_of(queue_dir):
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(queue_dir))))

    if queue_dir_arg:
        # 边界 (a) 的另一半：显式给的路径不存在，是调用方输入错误，算真正的执行错误。
        if not os.path.isdir(queue_dir_arg):
            return None, None, "给定的 --queue-dir 不存在：%s" % queue_dir_arg
        qd = os.path.abspath(queue_dir_arg)
        return [qd], git_cwd_of(qd), None

    kr = keeper_paths.find_keeper_root(cwd)
    if not kr:
        # 边界 (a)：`.keeper/` 顶层不存在 = task-keeper 未在本项目启用。这是正常状态，
        # 不是错误——与 `keeper_paths.find_keeper_root` 的 opt-in 语义、`board.py`
        # 遇到同样情况时的处理方式（打印提示、退出码仍是 0）保持一致。
        return None, None, None

    if all_deliveries:
        # 边界 (e)：多交付目录场景，`all_queue_dirs()` 按需扫全部。
        dirs = keeper_paths.all_queue_dirs(kr, DEBUG)
        if not dirs:
            return [], os.path.dirname(kr), None  # `.keeper/` 存在但一个交付都没有：空结果，非错误
        return dirs, os.path.dirname(kr), None

    qd = keeper_paths.queue_dir(cwd, DEBUG, write_back=False)
    if not qd or not os.path.isdir(qd):
        return [], git_cwd_of(qd) if qd else cwd, None    # 当前交付还没建 debug/ 子目录：空结果
    return [qd], git_cwd_of(qd), None


def fmt_line(fm):
    priority = str(fm.get("priority") or "").strip().upper() or "-"
    difficulty = str(fm.get("difficulty") or "").strip() or "-"
    return "%s [%s/%s] 已 triage 未派发" % (fm.get("id", "?"), priority, difficulty)


def render_text(agg):
    lines = []
    if agg["underdispatched"]:
        for fm in agg["underdispatched"]:
            lines.append(fmt_line(fm))
    else:
        lines.append("无漏派")
    if agg["broken"]:
        lines.append("⚠ 读不懂 %d 条（frontmatter 损坏，未参与漏派判定，需先修好）：%s"
                     % (len(agg["broken"]),
                        "、".join(str(fm.get("id", "?")) for fm in agg["broken"])))
    if agg["unreadable_decisions"]:
        lines.append("⚠ %d 个决策文件读取失败（无法确认其 about 归属，未参与排除计算）：%s"
                     % (len(agg["unreadable_decisions"]),
                        "、".join(agg["unreadable_decisions"])))
    return "\n".join(lines)


def render_json(agg):
    items = [{"id": fm.get("id"),
              "priority": str(fm.get("priority") or "").strip().upper() or None,
              "difficulty": str(fm.get("difficulty") or "").strip() or None,
              "summary": fm.get("summary")}
             for fm in agg["underdispatched"]]
    return {
        "total": len(items),
        "items": items,
        "broken_count": len(agg["broken"]),
        "broken_ids": [fm.get("id") for fm in agg["broken"]],
        "unreadable_decisions": agg["unreadable_decisions"],
    }


def render_oneline(agg):
    """压成一行，供 hook `additionalContext` 直接引用。无漏派返回空字符串。

    刻意**不带** broken / unreadable_decisions 信息——`--oneline` 的消费场景是
    「本轮该不该催派发」，这两类是「数据本身有问题」，性质不同，硬塞进一行会让
    这行字同时表达两件不相关的事，注入文案的读者（AI）分不清该对哪个动手。
    这两类信息只在 `--json` / 默认文本模式里出现。
    """
    items = agg["underdispatched"]
    if not items:
        return ""
    ids = [str(fm.get("id", "?")) for fm in items]
    return ("⚠ 漏派 %d 条：%s —— 已 triage 未派发，本轮应优先派它们"
           % (len(ids), " ".join(ids)))


def main():
    ap = argparse.ArgumentParser(
        description="算出 debug 队列里已 triage 但既没派 fixer、也不在等拍板的漏派 issue（只读）")
    ap.add_argument("--queue-dir", default=None,
                    help="debug 队列目录（如 <根>/.keeper/D-001-xxx/debug），缺省从 cwd 往上找")
    ap.add_argument("--all-deliveries", action="store_true",
                    help="扫全部交付目录（默认只算当前交付）")
    out_group = ap.add_mutually_exclusive_group()
    out_group.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    out_group.add_argument("--oneline", action="store_true",
                           help="压成一行摘要，供 hook additionalContext 引用；无漏派时输出空字符串")
    args = ap.parse_args()

    cwd = os.getcwd()
    dirs, git_cwd, err = resolve_targets(cwd, args.queue_dir, args.all_deliveries)
    if err:
        sys.exit(err)
    if dirs is None:
        # `.keeper/` 顶层不存在：task-keeper 未启用，正常状态，退出码 0。
        if args.oneline:
            print("")
        elif args.json:
            import json as _json
            print(_json.dumps({"total": 0, "items": [], "broken_count": 0,
                               "broken_ids": [], "unreadable_decisions": [],
                               "note": "task-keeper 未启用（.keeper/ 不存在）"},
                              ensure_ascii=False))
        else:
            print("task-keeper 未启用（找不到 .keeper/），无需检查漏派")
        return

    merged = {"underdispatched": [], "broken": [], "unreadable_decisions": []}
    for qd in dirs:
        agg = compute(qd, git_cwd)
        merged["underdispatched"] += agg["underdispatched"]
        merged["broken"] += agg["broken"]
        merged["unreadable_decisions"] += agg["unreadable_decisions"]

    if args.oneline:
        print(render_oneline(merged))
    elif args.json:
        import json as _json
        print(_json.dumps(render_json(merged), ensure_ascii=False, indent=2))
    else:
        print(render_text(merged))


if __name__ == "__main__":
    main()
