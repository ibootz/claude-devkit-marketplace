#!/usr/bin/env python3
"""wt_scope.py —— `wt_supply.py explain-scope` 的实现：从 triage issue 反推影响面。

为什么它是独立一个文件、且**不再**决定供给范围
----------------------------------------------
早先的 `supply` 靠这段解析出「这条 issue 碰了哪些 submodule」，然后**只供给那几个**。
该设计已被推翻：修一个 bug 常常要顺手改 spec（住在 `sdlc/` 这类 submodule 里）、
要查知识库、要翻组件库做 UI 组件溯源，按落点裁剪供给会在半路卡住。现在 `supply`
一律按源侧 `.gitmodules` 全量递归供给。

但「这条 issue 碰了哪些 submodule」本身仍是个有用的只读问题——排查时用来判影响面、
写 issue 时用来核对是否漏了某一层。所以这段逻辑降级为独立的只读子命令保留下来，
并搬到本文件：它与「供给 / 回流」两条主链路再无耦合，放在 `wt_supply.py` 里只会
让那个文件更长（该文件受 1000 行硬上限约束）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from wt_git import Fail, parse_gitmodules, resolve_worktree

TRIAGE_PATH_RE = re.compile(
    r"(/?[A-Za-z0-9_][A-Za-z0-9_./@+-]*\.[A-Za-z0-9_]+):(\d+)")


def submodules_from_triage(md: Path, declared: list, worktree: Path) -> dict:
    """从 markdown 正文里的 `<path>:<行号>` 反推涉及哪些 submodule。

    用 `.gitmodules` 声明的 path 做前缀匹配、取最长匹配；返回
    `{submodule相对路径: [命中的原始引用, ...]}`。
    """
    if not md.is_file():
        raise Fail(f"--from-triage 指定的文件不存在：{md}")
    text = md.read_text(encoding="utf-8", errors="replace")
    found = {m.group(1) for m in TRIAGE_PATH_RE.finditer(text)}
    if not found:
        raise Fail(
            f"{md} 里没匹配到任何 `<path>:<行号>` 形态的文件路径",
            hint="确认该 issue 文件正文引用了 file:line",
        )
    prefixes = {str(worktree) + os.sep}
    try:  # macOS 上 /tmp 与 /private/tmp 是同一处，两种字面都可能出现在 issue 里
        prefixes.add(str(Path(os.path.realpath(str(worktree)))) + os.sep)
    except OSError:
        pass
    hits = {}
    for raw in sorted(found):
        p = raw
        for pre in prefixes:
            if p.startswith(pre):
                p = p[len(pre):]
                break
        p = p.lstrip("./")
        best = None
        for d in declared:
            dd = d.rstrip("/")
            if p == dd or p.startswith(dd + "/"):
                if best is None or len(dd) > len(best):
                    best = dd
        if best is None:
            # 前缀不是本 worktree（例如从别的 worktree / 主 checkout 复制过来的引用，
            # 或 macOS /tmp ↔ /private/tmp 形态差异）：退一步按路径段边界找 declared。
            for d in declared:
                dd = d.rstrip("/")
                if raw.find("/" + dd + "/") >= 0 and (best is None or len(dd) > len(best)):
                    best = dd
        if best:
            hits.setdefault(best, []).append(raw)
    if not hits:
        raise Fail(
            f"{md} 里的 {len(found)} 条 file:line 引用都不落在任何 submodule 声明路径下",
            hint=f"本仓声明的 submodule：{', '.join(declared) or '(无)'}；"
                 f"说明这条 issue 只碰父仓文件",
        )
    return hits


def cmd_explain_scope(args) -> None:
    wt = resolve_worktree(args.worktree)
    declared = [rel for _n, rel in parse_gitmodules(wt)]
    md = Path(args.from_triage).expanduser()
    hits = submodules_from_triage(md, declared, wt)
    print(f"[wt_supply] explain-scope（只读，不改任何东西）")
    print(f"  worktree : {wt}")
    print(f"  issue    : {md}")
    print(f"  命中 {len(hits)} 个 submodule：")
    for sm, refs in sorted(hits.items()):
        sample = ", ".join(refs[:3]) + (" …" if len(refs) > 3 else "")
        print(f"    {sm}  ← {len(refs)} 条引用（{sample}）")
    print(f"  注：这只是影响面判断。supply 一律全量供给源侧声明的所有层，"
          f"不按这个结果裁剪——修 bug 常要顺手查 spec / 翻组件库，缺层会卡住。")
