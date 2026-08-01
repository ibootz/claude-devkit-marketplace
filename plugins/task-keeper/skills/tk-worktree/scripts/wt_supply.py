#!/usr/bin/env python3
"""wt_supply.py —— 从一个**源 worktree** 派生出结构完整的聚合仓 worktree，并能整体合并回去。

它解决的问题：submodule 密集的聚合仓里跑交付时，人在一个 delivery worktree（下称
**源 worktree**）里工作，测试报了一批 bug，想给每个 bug 开一个隔离工作区并行修，
最后统一合回源 worktree 的分支。每个 bug 工作区必须是**结构完整的聚合仓**（修 bug
常顺手改 spec/查知识库/翻组件库，缺任何一层都会卡住），所以供给范围不是「按 triage
落点挑几个 submodule」，而是**源 worktree 自己那份 `.gitmodules` 声明的全部
submodule，递归下钻到无 `.gitmodules` 为止**。

三条不可动摇的手法：
1. **绝不在 linked worktree 里跑 `git submodule update --init`。** 它会建一个独立
   对象库（无 `objects/info/alternates` 链回上游），源侧本地未推送的提交在新工作区
   里永远看不到，回流时报 `fatal: not our ref <sha>`。正确手法是对每个 submodule 也
   各自 `git worktree add`，产物 `.git` 是一个**文件**、对象库与源侧共享。
2. **`git worktree add` 一律从「源侧那个 submodule 目录」发起，不从主 checkout
   发起。** 实测很多 submodule 在主 checkout 侧根本没有对象库（是 `git submodule
   update --init` 在 worktree 里跑出来的私有克隆），从主 checkout 发起会找不到仓库。
3. **base ref 一律取「源侧父层 index 里的 gitlink SHA」**（`git -C <源侧父层>
   rev-parse :<子路径>`），「父层」是相对的，问错层/问错仓会**静默检出错误版本**。

「给分支还是 detach」机械照抄源侧该层的形态：源侧 `symbolic-ref` 有输出（on-branch）
→ 目标侧开同名分支；无输出（detached）→ 目标侧 `--detach`（detached 的层本不承载
分支工作，硬开分支只会制造没人合回去的悬空分支）。

gitlink 语义分界：`init`/`supply`/`status`/`remove`/`explain-scope` 不改任何 gitlink
指针，纯供给；`merge-back` 会改指针且在源侧建 commit，默认 dry-run、显式 `--apply`
才执行。

设计约束：fail-loud（失败即非零退出，打印实际命令/stderr/建议下一步）；幂等（已 ok
的层再跑 supply 是 no-op）；退出码 0=成功 2=有非 ok 层或前置校验不通过 其他非 0=硬
错误；只用标准库，git 调用全部走 `wt_git.py`（显式 `-C`，不 `cd`，不 `shell=True`）。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from wt_git import (Fail, current_branch, die, dirty_lines, git, main_checkout,
                    parse_gitmodules, resolve_worktree, worktree_entries)
from wt_levels import report_levels, supply_all
from wt_mergeback import cmd_merge_back
from wt_remove import cmd_remove
from wt_scope import cmd_explain_scope
from wt_source import record_source, resolve_source

# 队列布局（落点与分支名要跟着交付 id 走）由 hooks/lib/keeper_paths.py 定义。
# 这里做**软依赖**：tk-worktree 也可以脱离队列独立使用（给任意 worktree 供给
# submodule 层），import 不到就退回不带交付前缀的 v3 形态，而不是硬失败。
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "hooks", "lib"))
try:
    import keeper_paths
except Exception:
    keeper_paths = None


# ---------------------------------------------------------------- init

WID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def cmd_init(args) -> None:
    """一条命令建出结构完整的聚合仓 worktree：父仓 + 全部 submodule 层 + 自校验。

    落点为什么**固定**在 `<source>/.keeper/<交付id>/debug/<id>/worktree/`，不做成可配
    -----------------------------------------------------------------------
    很多工具链（hook、状态注入、路径识别）靠 **cwd 的路径字面量**反推「当前处于
    哪个工作区」。把目标 worktree 放在源 worktree **内部**时，它的绝对路径天然
    包含源 worktree 的完整路径前缀，这类识别全部照常工作；落到外部会被静默判成
    另一个无关工作区，没有任何报错。

    一个真实例子：某交付框架的路径识别常量是 `MARKER = '/.sdlc/worktrees/'`，
    紧跟一个 slug 白名单（只认 `^D-\\d+` 或 `^hotfix-` 开头）。fixer worktree 若
    直接落到 `.sdlc/worktrees/DBG-021`，MARKER 命中、slug 校验不认 → 一整串依赖
    cwd 判断的 hook 集体失准；落在源 worktree 内部则前缀完整保留、识别不受影响。

    v4 在「必须落在源 worktree 内部」这条约束之上又收紧了一级：**落进它所属那条
    issue 自己的目录**。v3 放在 `.keeper/worktrees/<id>/`，与队列数据平级——同一条
    bug 的 issue / receipts / 截图 / worktree 分散在四棵子树里，删一条要记得删四处。
    v4 收进 `debug/<id>/worktree/` 之后，一条 issue 的全部东西就是一个目录。

    v3 时 `.keeper/` 整树 gitignore、worktree 无需单独排除；**v4 队列文本入库**，
    所以 `.gitignore` 必须有 `.keeper/**/worktree/`（判据 6）。缺这条规则时
    `git add -A` 会把嵌套 worktree 种成幽灵 gitlink（实测 `git add -n` 报
    `warning: adding embedded git repository`），而聚合仓真有 submodule，野生
    gitlink 会让 `merge_into` 的冲突白名单判定整体阻断。

    分支名同样带交付前缀：`fix/<交付id>-<id>`。编号虽然全局唯一（`next_id` 扫所有
    交付目录），但多人并行时各自的扫描看不到对方未合并的 issue，两人可能拿到同一个
    DBG-NNN；文件路径因交付 id 不同而不撞，**refs 命名空间却是仓库全局的**——不加
    前缀，第二个人 `worktree add` 直接 `fatal: a branch named ... already exists`。

    **所以这个落点不是随手挑的，挪走它会静默破坏宿主工具链的 worktree 识别。**
    """
    source = resolve_worktree(args.source, "source")
    wid = args.id.strip()
    if not WID_RE.match(wid):
        raise Fail(
            f"--id 只接受字母数字开头、由字母数字与 . _ - 组成的名字，收到：{args.id!r}",
            hint="它会作为目录名用在 <source>/.keeper/<交付id>/debug/<id>/worktree/，"
                 "不接受路径分隔符",
        )
    did = (keeper_paths.resolve_delivery_id(str(source))
           if keeper_paths else "_main")
    target = Path(os.path.normpath(
        str(source / ".keeper" / did / "debug" / wid / "worktree")))
    branch = args.branch or f"fix/{did}-{wid}"

    print(f"[wt_supply] init{'（dry-run）' if args.dry_run else ''}")
    print(f"  源 worktree : {source}（分支 {current_branch(source) or 'detached'}）")
    print(f"  交付 id     : {did}")
    print(f"  目标落点    : {target}   ← 固定 <source>/.keeper/<交付id>/debug/<id>/worktree/，"
          f"理由见 cmd_init docstring")
    print(f"  目标分支    : {branch}")
    print(f"  主 checkout : {main_checkout(source)}")

    src_dirty = dirty_lines(source)
    if src_dirty:
        print(f"  ⚠ 源 worktree 有 {len(src_dirty)} 项未提交改动。"
              f"`worktree add ... HEAD` 只带走 HEAD 的内容，这些改动**不会**进目标 worktree：")
        for line in src_dirty[:10]:
            print(f"      {line}")
        if len(src_dirty) > 10:
            print(f"      … 另有 {len(src_dirty) - 10} 项")

    existing = None
    for e in worktree_entries(source):
        if e["path"] == target:
            existing = e
            break
    if existing:
        if existing["branch"] != branch:
            raise Fail(
                f"{target} 已登记为 worktree，但它在分支 "
                f"{existing['branch'] or 'detached'} 上，不是 {branch}",
                hint=f"要换分支先 `wt_supply.py remove --worktree {target} --yes`；"
                     f"或用 --branch {existing['branch']} 续跑供给",
            )
        print(f"  父仓工作区已存在且分支一致，跳过创建，直接续跑供给（幂等）")
    else:
        if target.exists() and any(target.iterdir()):
            raise Fail(
                f"{target} 已存在且非空，但没登记在 worktree list 里",
                hint=f"确认里面没有要留的东西后 `rm -rf {target}` 再重跑 init",
            )
        if args.dry_run:
            print(f"  [dry-run] git -C {source} worktree add {target} -b {branch} HEAD")
        else:
            proc = git(source, "worktree", "add", str(target), "-b", branch, "HEAD",
                       check=False)
            if proc.returncode != 0:
                raise Fail(
                    f"建父仓工作区失败",
                    cmd=f"git -C {source} worktree add {target} -b {branch} HEAD",
                    stderr=proc.stderr,
                    hint=f"若报 branch already used，换 --branch；"
                         f"若报 already exists，先 rm -rf {target}",
                )
            record_source(target, source)

    print(f"\n  供给全部 submodule 层（范围 = 源侧 .gitmodules 全量，递归下钻）：")
    if args.dry_run and not target.exists():
        for _n, rel in parse_gitmodules(source):
            print(f"    [dry-run] 待供给 {rel}（及其嵌套层，需父仓工作区存在后才能逐层展开）")
        print("\n[wt_supply] init dry-run 结束，未执行任何写操作。")
        return
    stats = supply_all(target, source, branch, args.dry_run)
    print(f"  供给统计：新建 {stats['supplied']} / 跳过 {stats['skipped']}"
          + (f" / 计划 {stats['planned']}" if args.dry_run else ""))
    if args.dry_run:
        print("\n[wt_supply] init dry-run 结束，未执行任何写操作。")
        return

    print(f"\n  自校验（等价于 `status --worktree {target}`）：")
    bad = report_levels(target, source)
    if bad:
        print(f"\n[wt_supply] init 未全绿：{len(bad)} 层非 ok。**已建出的部分刻意不回滚**，"
              f"保留现场供排查；修掉根因后重跑同一条 init 即可（幂等）。")
        sys.exit(2)
    print(f"\n[wt_supply] init 完成。目标 worktree：{target}")
    print(f"  合并回源 worktree：wt_supply.py merge-back --worktree {target}"
          f"（默认 dry-run，核对后加 --apply）")
    print(f"  清理：wt_supply.py remove --worktree {target} --yes")


# ---------------------------------------------------------------- status
# （逐层状态汇总 report_levels() 已搬到 wt_levels.py，供 cmd_init 自校验复用）

def cmd_status(args) -> None:
    target = resolve_worktree(args.worktree)
    source = resolve_source(target, args.source)
    print(f"[wt_supply] status")
    print(f"  目标 worktree : {target}（分支 {current_branch(target) or 'detached'}）")
    print(f"  源 worktree   : {source}（分支 {current_branch(source) or 'detached'}）")
    print(f"  主 checkout   : {main_checkout(target)}")
    for label, repo in (("目标", target), ("源", source)):
        d = dirty_lines(repo)
        if d:
            print(f"  {label}侧父仓有 {len(d)} 项未提交改动（已剔除嵌套 worktree 目录）")
    print()
    bad = report_levels(target, source)
    prunable = [e for e in worktree_entries(target) if e["prunable"]]
    if prunable:
        print(f"\n  父仓 worktree 登记里有 {len(prunable)} 条 prunable，"
              f"跑 `git -C {source} worktree prune` 清理：")
        for e in prunable:
            print(f"    {e['path']}  ({e['prunable']})")
    sys.exit(0 if not bad else 2)


# ---------------------------------------------------------------- supply 子命令


def cmd_supply(args) -> None:
    target = resolve_worktree(args.worktree)
    source = resolve_source(target, args.source)
    declared = [rel for _n, rel in parse_gitmodules(source)]
    base = args.branch or current_branch(target)
    if not base:
        raise Fail(
            f"{target} 处于 detached HEAD，取不到默认分支名",
            hint="用 --branch <name> 显式指定 submodule 侧新分支名",
        )
    print(f"[wt_supply] supply{'（dry-run）' if args.dry_run else ''}")
    print(f"  目标 worktree : {target}（分支 {current_branch(target) or 'detached'}）")
    print(f"  源 worktree   : {source}（分支 {current_branch(source) or 'detached'}）")
    print(f"  submodule 侧  : {base}（仅用于源侧 on-branch 的层；撞占用则派生 <base>-<末段>）")
    if not declared:
        print(f"[wt_supply] {source} 没有 .gitmodules，无 submodule 需要供给。")
        return
    print(f"  供给范围      : 源侧 .gitmodules 全量 {len(declared)} 个顶层"
          f"（{', '.join(declared)}）+ 递归嵌套层")
    if args.source:
        record_source(target, source)  # 显式给过源就记下来，后续子命令不必再给
    stats = supply_all(target, source, base, args.dry_run)
    print(f"\n[wt_supply] supply 完成：新建 {stats['supplied']} / 跳过 {stats['skipped']}"
          + (f" / 计划 {stats['planned']}" if args.dry_run else "")
          + "。（本子命令不改任何 gitlink 指针，只按源侧已记录的 gitlink 拉出内容）")


# ---------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wt_supply.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "从一个源 worktree 派生出**结构完整的聚合仓 worktree**（父仓 + 全部\n"
            "submodule 层，含嵌套递归），并能把它整体合并回源 worktree 的分支。\n"
            "手法：每个 submodule 也各自 `git worktree add`，且一律**从源侧那个\n"
            "submodule 目录**发起，对象库与源侧共享。绝不在 linked worktree 里跑\n"
            "`git submodule update --init`——那会建独立对象库，让源侧本地未推送提交\n"
            "不可见、回流时报 not our ref。"
        ),
        epilog=(
            "gitlink 语义：init / supply / status / remove / explain-scope 不改任何\n"
            "gitlink 指针；merge-back 会改并在源侧建 commit，故默认 dry-run 并逐层\n"
            "打印新旧 commit（短 hash + 日期 + subject）供确认。\n"
            "退出码：0 成功 / 2 有非 ok 层或前置校验不通过 / 其他非 0 硬错误。"
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="建目标 worktree（父仓 + 全量 submodule）并自校验")
    s.add_argument("--source", required=True, help="源 worktree 绝对路径")
    s.add_argument("--id", required=True,
                   help="工作区标识（如 DBG-021）；落点固定 "
                        "<source>/.keeper/<交付id>/debug/<id>/worktree/")
    s.add_argument("--branch", help="目标分支名，缺省 fix/<交付id>-<id>")
    s.add_argument("--dry-run", action="store_true", help="只打印将执行的命令")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("supply",
                       help="全量递归供给 submodule 层（范围 = 源侧 .gitmodules）")
    s.add_argument("--worktree", required=True, help="目标 worktree 路径")
    s.add_argument("--source", help="源 worktree 路径；缺省读 init 时记下的那份")
    s.add_argument("--branch",
                   help="submodule 侧新分支名，缺省用目标 worktree 父仓当前分支名")
    s.add_argument("--dry-run", action="store_true", help="只打印将执行的命令")
    s.set_defaults(func=cmd_supply)

    s = sub.add_parser("status", help="逐层（含嵌套）报状态 + 源侧/目标侧形态差异")
    s.add_argument("--worktree", required=True)
    s.add_argument("--source", help="源 worktree 路径；缺省读 init 时记下的那份")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("remove", help="深度优先清理目标 worktree（submodule 层 + 父仓）")
    s.add_argument("--worktree", required=True)
    s.add_argument("--source", help="源 worktree 路径；缺省读 init 时记下的那份")
    s.add_argument("--keep-parent", action="store_true",
                   help="只清 submodule 层，保留父仓工作区")
    s.add_argument("--keep-branches", action="store_true",
                   help="不清理 remove 建过的分支（reject 场景想保留分支供人工核实时用）")
    s.add_argument("--force-delete-branches", action="store_true",
                   help="对未合并的分支也强删（默认只安全删除，未合并的会保留并提示）")
    s.add_argument("--yes", action="store_true", help="确认执行（缺省只打印计划）")
    s.set_defaults(func=cmd_remove)

    s = sub.add_parser("merge-back",
                       help="把目标 worktree 各层合回源 worktree 对应分支并回写 gitlink")
    s.add_argument("--worktree", required=True)
    s.add_argument("--source", help="源 worktree 路径；缺省读 init 时记下的那份")
    s.add_argument("--apply", action="store_true",
                   help="真正执行（缺省 dry-run，只打印命令与新旧 gitlink 对照）")
    s.set_defaults(func=cmd_merge_back)

    s = sub.add_parser("explain-scope",
                       help="只读：从 issue 正文的 <path>:<行号> 反推涉及哪些 submodule")
    s.add_argument("--worktree", required=True)
    s.add_argument("--from-triage", metavar="ISSUE_MD", required=True)
    s.set_defaults(func=cmd_explain_scope)
    return p


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except Fail as e:
        die(e)
    except KeyboardInterrupt:
        print("\n[wt_supply] 已中断", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
