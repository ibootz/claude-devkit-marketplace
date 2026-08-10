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

`init` 支持批量并行：`--ids A,B,C --jobs 3`。批量把 fail-loud 的粒度从「进程」下调到
「单个 id」——某个 id 失败不牵连其他 id，逐 id 汇报成败，退出码按「有任一失败=1 /
无失败但有非全绿=2 / 全绿=0」汇总（单 id 时与批量化之前逐字等价）。并行带来的三个
并发问题（同源仓抢锁、`pick_branch` 的 check-then-act、共享 stdout 交错）分别由
`wt_git.git()` 的锁冲突退避重试、`wt_levels.reserve_branch()` 的按源仓互斥锁、
`wt_par` 的按 id 输出缓冲解决，各自的函数注释里有判据与取值理由。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from wt_git import (Fail, current_branch, die, dirty_lines, fail_lines, git,
                    main_checkout, parse_gitmodules, resolve_worktree,
                    worktree_entries)
from wt_levels import report_levels, supply_all
from wt_par import attach, detach, emit, flush, run_parallel, say
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

DEFAULT_JOBS = 3


def parse_init_ids(args) -> list[str]:
    """把 `--id` / `--ids` 归一成一个 id 列表，并挡掉四类**整条命令级**的错用。

    这里只挡「不针对某个具体 id」的错误——它们一律让整条命令失败、什么都不建：
    两个入口同时给（按报错处理，不静默取其一）、两个都没给、`--ids` 里有空元素
    （末尾多写一个逗号）、`--ids` 里有重复 id（无法判定该以哪一份为准）。

    **id 本身的形态校验刻意不在这里做**，而是留给 `init_one()` 在每个 id 的任务里
    做：批量的核心语义是「某个 id 失败不牵连其他 id」，一个 id 拼错就把整批打回去，
    与那条语义直接冲突。
    """
    if args.id and args.ids:
        raise Fail(
            "--id 与 --ids 只能给一个（收到两个）",
            hint="单个 id 用 --id DBG-017；批量用 --ids DBG-017,DBG-018,DBG-019",
        )
    if not args.id and not args.ids:
        raise Fail(
            "必须给 --id（单个）或 --ids（逗号分隔的批量）之一",
            hint="批量形态：--ids DBG-017,DBG-018,DBG-019 --jobs 3",
        )
    raw = [args.id] if args.id else args.ids.split(",")
    ids: list[str] = []
    for item in raw:
        wid = item.strip()
        if not wid:
            raise Fail(
                f"--ids 里有空 id：{args.ids!r}",
                hint="检查是不是多写了逗号，或有连续两个逗号",
            )
        if wid in ids:
            raise Fail(
                f"--ids 里 id {wid} 出现了两次",
                hint="去掉重复项；同一个 id 建两次没有意义，且两个任务会抢同一个落点",
            )
        ids.append(wid)
    if len(ids) > 1 and args.branch:
        raise Fail(
            f"批量模式（{len(ids)} 个 id）下不接受 --branch",
            hint="分支名按 id 派生（fix/<交付id>-<id>），多个 id 共用一个分支名不合理；"
                 "要自定义分支名就一个一个用 --id 跑",
        )
    if args.jobs < 1:
        raise Fail(f"--jobs 必须 ≥ 1，收到 {args.jobs}",
                   hint="--jobs 1 即串行；缺省 3")
    return ids


def init_one(args, source: Path, did: str, wid: str) -> dict:
    """建**一个** id 的聚合仓 worktree：父仓 + 全部 submodule 层 + 自校验。

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

    v3 时 `.keeper/` 整树 gitignore、worktree 无需单独排除；v4 队列文本入库，改为要求
    `.gitignore` 必须有精确规则 `.keeper/**/worktree/`（判据 6），缺它时 `git add -A`
    会把嵌套 worktree 种成幽灵 gitlink（实测 `git add -n` 报
    `warning: adding embedded git repository`），而聚合仓真有 submodule，野生
    gitlink 会让 `merge_into` 的冲突白名单判定整体阻断。v5 绕回整树 gitignore、判据 6
    一度失去必要性；**v6（2026-08-10 用户拍板）把入库策略反转回来之后，判据 6 恢复为
    主线判据**——`.keeper/**/worktree/` 又是唯一挡住幽灵 gitlink 的东西，且它带写法坑
    （必须用 `**`，写死中间层在嵌套变化时漏网）。配套的 `check_staged_gitlink.py`
    同步恢复为每次提交队列前都要跑的常规校验，不再是存量仓专用。

    分支名同样带交付前缀：`fix/<交付id>-<id>`。编号虽然全局唯一（`next_id` 扫所有
    交付目录），但多人并行时各自的扫描看不到对方未合并的 issue，两人可能拿到同一个
    DBG-NNN；文件路径因交付 id 不同而不撞，**refs 命名空间却是仓库全局的**——不加
    前缀，第二个人 `worktree add` 直接 `fatal: a branch named ... already exists`。

    **所以这个落点不是随手挑的，挪走它会静默破坏宿主工具链的 worktree 识别。**

    批量下的线程安全
    ----------------
    批量 `--ids` 时本函数由 `ThreadPoolExecutor` 的多个线程各跑一份，共享的可变状态
    只有两处，都已处理：(1) stdout——所有输出走 `wt_par.emit()` 进本线程的缓冲区，
    由 `cmd_init` 统一 flush；(2) 源仓的 refs 与 index——`wt_levels.reserve_branch()`
    的按源仓互斥锁 + `wt_git.git()` 的锁冲突退避重试。**本函数不再调 `sys.exit`**：
    失败抛 `Fail`、自校验非全绿在返回值里报 `status="bad"`，退出码由 `cmd_init` 汇总
    后统一决定，这样一个 id 失败不会把其余 id 一起带走。
    """
    quiet = args.quiet
    if not WID_RE.match(wid):
        raise Fail(
            f"id 只接受字母数字开头、由字母数字与 . _ - 组成的名字，收到：{wid!r}",
            hint="它会作为目录名用在 <source>/.keeper/<交付id>/debug/<id>/worktree/，"
                 "不接受路径分隔符",
        )
    target = Path(os.path.normpath(
        str(source / ".keeper" / did / "debug" / wid / "worktree")))
    branch = args.branch or f"fix/{did}-{wid}"
    result = {"wid": wid, "status": "ok", "target": target, "branch": branch,
              "stats": None, "bad": []}

    emit(f"  目标落点    : {target}   ← 固定 <source>/.keeper/<交付id>/debug/<id>/worktree/，"
         f"理由见 init_one docstring")
    emit(f"  目标分支    : {branch}")

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
        emit(f"  父仓工作区已存在且分支一致，跳过创建，直接续跑供给（幂等）")
    else:
        if target.exists() and any(target.iterdir()):
            raise Fail(
                f"{target} 已存在且非空，但没登记在 worktree list 里",
                hint=f"确认里面没有要留的东西后 `rm -rf {target}` 再重跑 init",
            )
        if args.dry_run:
            emit(f"  [dry-run] git -C {source} worktree add {target} -b {branch} HEAD")
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

    emit(f"\n  供给全部 submodule 层（范围 = 源侧 .gitmodules 全量，递归下钻）：")
    if args.dry_run and not target.exists():
        for _n, rel in parse_gitmodules(source):
            emit(f"    [dry-run] 待供给 {rel}（及其嵌套层，需父仓工作区存在后才能逐层展开）")
        emit("\n[wt_supply] init dry-run 结束，未执行任何写操作。")
        result["status"] = "dry-run"
        return result
    stats = supply_all(target, source, branch, args.dry_run)
    result["stats"] = stats
    emit(f"  供给统计：新建 {stats['supplied']} / 跳过 {stats['skipped']}"
         + (f" / 计划 {stats['planned']}" if args.dry_run else ""))
    if args.dry_run:
        emit("\n[wt_supply] init dry-run 结束，未执行任何写操作。")
        result["status"] = "dry-run"
        return result

    # 自校验：`--quiet` 只省掉**逐层清单的输出**（见 report_levels 的 quiet 注释），
    # 校验本身照跑；真有非 ok 层时再以 quiet=False 重跑一次把清单打全——失败路径的
    # 信息一行不减，省的只是成功路径的输出。
    if not quiet:
        emit(f"\n  自校验（等价于 `status --worktree {target}`）：")
    bad = report_levels(target, source, quiet=quiet)
    if bad:
        result["status"], result["bad"] = "bad", bad
        if quiet:
            emit(f"\n  自校验非全绿，逐层清单（--quiet 下仍打印，"
                 f"因为它是判定失败的依据）：")
            report_levels(target, source, quiet=False)
        emit(f"\n[wt_supply] init 未全绿：{len(bad)} 层非 ok。**已建出的部分刻意不回滚**，"
             f"保留现场供排查；修掉根因后重跑同一条 init 即可（幂等）。")
        return result
    emit(f"\n[wt_supply] init 完成。目标 worktree：{target}")
    emit(f"  合并回源 worktree：wt_supply.py merge-back --worktree {target}"
         f"（默认 dry-run，核对后加 --apply）")
    emit(f"  清理：wt_supply.py remove --worktree {target} --yes")
    return result


def cmd_init(args) -> None:
    """`init` 的入口：单 id 与批量 id 走同一条路径，只在并行度与输出形态上分叉。

    退出码的汇总规则（批量的核心语义：一个 id 失败不牵连其他 id）
    ------------------------------------------------------------
    有任一 id 抛 `Fail` → `1`；没有失败但有 id 自校验非全绿 → `2`；全绿 → `0`。
    单 id 时这套规则与改造前逐字等价（失败 1 / 非全绿 2 / 成功 0），所以 `--id`
    的调用方不需要跟着改。

    单 id 的输出刻意保持「不带前缀、直接流式打印」——`--id` 是既有调用方与文档里的
    形态，加前缀等于无谓地改掉它们比对的输出。多 id 才启用「按 id 缓冲 + 前缀」。
    """
    ids = parse_init_ids(args)
    source = resolve_worktree(args.source, "source")
    did = (keeper_paths.resolve_delivery_id(str(source))
           if keeper_paths else "_main")
    multi = len(ids) > 1
    quiet = args.quiet
    jobs = min(args.jobs, len(ids))

    head = f"[wt_supply] init{'（dry-run）' if args.dry_run else ''}"
    if multi:
        head += f"：批量 {len(ids)} 个 id、并行度 {jobs}（{', '.join(ids)}）"
    say(head)
    say(f"  源 worktree : {source}（分支 {current_branch(source) or 'detached'}）")
    say(f"  交付 id     : {did}")
    say(f"  主 checkout : {main_checkout(source)}")
    # 源侧脏度只与源有关、与 id 无关：批量下在这里打一次，不在每个 id 里重复 N 遍。
    src_dirty = dirty_lines(source)
    if src_dirty:
        say(f"  ⚠ 源 worktree 有 {len(src_dirty)} 项未提交改动。"
            f"`worktree add ... HEAD` 只带走 HEAD 的内容，这些改动**不会**进目标 worktree：")
        for line in src_dirty[:10]:
            say(f"      {line}")
        if len(src_dirty) > 10:
            say(f"      … 另有 {len(src_dirty) - 10} 项")

    def worker(wid: str) -> dict:
        # 多 id → 缓冲并加 `[id]` 前缀；单 id 且非 quiet → 不缓冲、行为与改造前一致；
        # quiet → 缓冲但成功时丢弃（失败/非全绿才 flush，保证排查信息不丢）。
        sink = attach(wid if multi else None) if (multi or quiet) else None
        rec = {"wid": wid, "status": "ok", "fail": None, "target": None,
               "branch": None, "stats": None, "bad": []}
        try:
            rec.update(init_one(args, source, did, wid))
        except Fail as e:
            rec["status"], rec["fail"] = "fail", e
        except Exception as e:  # 兜底：线程里漏出的任何异常都只算这个 id 失败
            rec["status"] = "fail"
            rec["fail"] = Fail(f"未预期异常 {type(e).__name__}: {e}",
                               hint="这是 wt_supply 自身的缺陷，请连同上面的输出一起反馈")
        finally:
            detach()
            if sink is not None and (not quiet or rec["status"] != "ok"):
                flush(sink)
        return rec

    results = run_parallel(ids, worker, jobs)
    fails = [r for r in results if r["status"] == "fail"]
    bads = [r for r in results if r["status"] == "bad"]

    if multi or quiet:
        say("")
        say(f"[wt_supply] init 汇总：{len(ids)} 个 id → "
            f"成功 {len(ids) - len(fails) - len(bads)} / "
            f"自校验非全绿 {len(bads)} / 失败 {len(fails)}")
        for r in results:
            if r["status"] == "fail":
                detail = r["fail"].msg
            elif r["status"] == "bad":
                detail = f"{len(r['bad'])} 层非 ok → {r['target']}"
            elif r["status"] == "dry-run":
                detail = f"dry-run，未写任何东西 → {r['target']}"
            else:
                s = r["stats"] or {}
                detail = (f"新建 {s.get('supplied', 0)} / 跳过 {s.get('skipped', 0)} 层"
                          f" → {r['target']}")
            say(f"  {r['status'].ljust(7)} {r['wid']}  {detail}")

    if fails:
        if not multi:
            raise fails[0]["fail"]  # 单 id：交给 main() 的 die()，stderr 形态不变
        print("", file=sys.stderr)
        for r in fails:
            for line in fail_lines(r["fail"], f"[{r['wid']}] "):
                print(line, file=sys.stderr)
        print(f"[wt_supply] {len(fails)}/{len(ids)} 个 id 失败；其余 id 各自独立完成、"
              f"未受牵连。修掉根因后只需重跑失败的那几个 id（init 幂等）。",
              file=sys.stderr)
        sys.exit(1)
    if bads:
        sys.exit(2)


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

    s = sub.add_parser("init", help="建目标 worktree（父仓 + 全量 submodule）并自校验；"
                                    "支持 --ids 批量 + --jobs 并行")
    s.add_argument("--source", required=True, help="源 worktree 绝对路径")
    s.add_argument("--id",
                   help="单个工作区标识（如 DBG-021）；落点固定 "
                        "<source>/.keeper/<交付id>/debug/<id>/worktree/")
    s.add_argument("--ids",
                   help="批量：逗号分隔的多个 id（如 DBG-017,DBG-018,DBG-019）。"
                        "与 --id 二者给一个，同时给报错")
    s.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                   help=f"批量的并行度，缺省 {DEFAULT_JOBS}；1 = 串行")
    s.add_argument("--quiet", action="store_true",
                   help="不打印逐层供给与自校验清单，只留每个 id 一行结论"
                        "（自校验本身照跑，非全绿仍非零退出并打全清单）")
    s.add_argument("--branch",
                   help="目标分支名，缺省 fix/<交付id>-<id>；批量模式下给它报错")
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
