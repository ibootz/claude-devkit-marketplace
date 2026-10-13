#!/usr/bin/env python3
"""wt_remove.py —— `remove` 子命令：深度优先清理目标 worktree 的 submodule 层与父仓。

从 wt_supply.py 拆出的原因
--------------------------
`remove` 是一条独立的清理链路（先子后父地 `git worktree remove`、清空目录消除
父层 dirty、best-effort 删分支），与「供给」「回流合并」两条主链路没有耦合，
只依赖 `wt_levels.py` 的层级遍历结果（`walk_levels`）与状态常量（`OK` /
`ISOLATED` / `UNREACHABLE`），以及 `wt_source.py` 的 `resolve_source`。拆开后
`wt_supply.py` 不必再装这段与 init/supply/status 无关的清理细节。
"""

from __future__ import annotations

from pathlib import Path

from wt_git import Fail, branch_exists, current_branch, git, resolve_worktree
from wt_levels import ISOLATED, OK, UNREACHABLE, walk_levels
from wt_source import resolve_source

# ---------------------------------------------------------------- remove


def clean_parent_after_removal(parent_wt: Path, rel: str, target: Path) -> None:
    """删掉子层 worktree 会把目录物理删除，父层随即出现 `D <rel>` 变 dirty，
    父层自己的 `worktree remove` 就会报 `contains modified or untracked files`。

    消除办法是把**空目录**建回来——对未初始化的 submodule，git 认为空目录即干净
    状态，父层立刻恢复 clean（实测：`D vendor/n` 在 mkdir 后归零）。

    **刻意不用 `git submodule deinit -f <rel>`，未来也不要加回来。** 实测：linked
    worktree 的 `.git/config` 与主仓**共享**，在 worktree 里 deinit 会把
    `submodule.<name>.url` 从那份共享 config 里删掉，连主 checkout 的
    `git submodule status` 都跟着从 ` `（已初始化）变成 `-`（未初始化）——那是波及
    主 checkout 的副作用。本工具的新链路完全不碰主 checkout 的 submodule 初始化状态
    （供给全部从源侧发起），源 worktree 与主 checkout 都毫发无损，没有任何理由 deinit。
    也不用 `worktree remove --force`：那是掩盖因果，不是消除原因。
    """
    target.mkdir(parents=True, exist_ok=True)
    dirty = git(parent_wt, "status", "--porcelain", "--", rel,
                check=False).stdout.strip()
    if not dirty:
        return
    raise Fail(
        f"删除 {target} 后，父层 {parent_wt} 里 {rel} 仍是 dirty",
        stderr=dirty,
        hint=f"人工检查 `git -C {parent_wt} status`，确认里面没有要留的内容后重跑",
    )


def try_delete_branch(repo: Path, branch: str, force: bool) -> str:
    """尽力删除 remove 遗留下的分支，best-effort：删不掉只警告，不阻断整体清理。

    默认走 `git branch -d`（安全删除，未完全合并会拒绝）；显式 --force-delete-branches
    时才用 `-D`。之所以默认安全删除而不是直接强删：merge-back --apply 成功之后，
    这条分支已经被 merge --no-ff 进源侧对应分支，`-d` 天然能删掉；如果 -d 失败，
    说明这条分支还有未合并的提交（fixer 交付但从未跑过 merge-back，或本来就是要
    丢弃的 reject 场景），这时不该默默丢内容，要么走 --force-delete-branches
    显式表态丢弃，要么保留分支手工核实。
    """
    if not branch_exists(repo, branch):
        return "跳过（分支已不存在）"
    flag = "-D" if force else "-d"
    proc = git(repo, "branch", flag, branch, check=False)
    if proc.returncode == 0:
        return f"已删除（git branch {flag}）"
    # git 拒绝删除时 stderr 形如「error: 分支未完全合并」+ 若干条 hint: 提示，
    # 取第一条非 hint: 行（即真正的 error: 原因），不要取最后一行——那通常是
    # 「用 git config 关掉这条提示」之类的 hint，对判断为什么保留没有帮助。
    lines = [l for l in proc.stderr.strip().splitlines() if l.strip()]
    reason = next((l for l in lines if not l.lstrip().startswith("hint:")), None) \
        or (lines[0] if lines else "未知原因")
    return f"保留（{reason}；如确认要丢弃，重跑 remove 时加 --force-delete-branches）"


def cmd_remove(args) -> None:
    target = resolve_worktree(args.worktree)
    source = resolve_source(target, args.source)
    levels = walk_levels(target, source)
    live = [(lv, st) for lv, st in levels if st in (OK, ISOLATED, UNREACHABLE)]
    broken = [lv for lv, st in live if st != OK]
    if broken:
        raise Fail(
            "这些层不是共享对象库的 linked worktree（isolated-objdir / unreachable），"
            "`git worktree remove` 处理不了：" + ", ".join(str(lv.target) for lv in broken),
            hint="人工 `rm -rf` 这些目录后重跑 remove；若里面有未推送提交，先备份",
        )

    # 深度优先：先删子层，再删父层。先删父会报
    # `fatal: working trees containing submodules cannot be moved or removed`
    # 分支名必须在 worktree 还存在时先读出来（读的是这层此刻检出的分支，删完
    # worktree 后分支 ref 还在，但读的时机要在 worktree remove 之前）。
    plan = [(lv, current_branch(lv.target)) for lv, _st in sorted(live, key=lambda t: -t[0].depth)]
    clean_branches = not args.keep_branches
    print(f"[wt_supply] remove 计划（深度优先，先子后父；共 {len(plan)} 层 + 父仓工作区）：")
    for lv, branch in plan:
        print(f"  git -C {lv.src} worktree remove {lv.target}")
        print(f"    ↳ 随后 mkdir 回空目录，消除父层 `D {lv.rel}` 的 dirty")
        if clean_branches and branch:
            print(f"    ↳ 之后 git -C {lv.src} branch -d {branch}（清理本层分支）")
    parent_branch = current_branch(target)
    print(f"  git -C {source} worktree remove {target}   ← 收尾，删父仓工作区本身")
    if clean_branches and parent_branch and not args.keep_parent:
        print(f"    ↳ 之后 git -C {source} branch -d {parent_branch}（清理父仓分支）")
    print(f"  源 worktree {source} 不受影响（本链路从不碰主 checkout 的 "
          f"submodule 初始化状态，也不跑 submodule deinit）")
    if not args.yes:
        print("\n[wt_supply] 未加 --yes，仅打印计划，未执行任何删除。")
        return

    # done_actions 记录本次已真实完成的删除动作（层 + 分支），用于中途失败时
    # 告知人「已经删掉了什么」——中途失败不回滚（既有设计），已删的层与分支
    # 无法从失败那一步的报错里看出来，必须显式记账。
    done_actions: list[str] = []
    for idx, (lv, branch) in enumerate(plan):
        print(f"  git -C {lv.src} worktree remove {lv.target}")
        proc = git(lv.src, "worktree", "remove", str(lv.target), check=False)
        if proc.returncode != 0:
            remaining = [str(l.target) for l, _b in plan[idx:]] + [f"{target}（父仓工作区）"]
            raise Fail(
                f"删除 {lv.target} 失败",
                cmd=f"git -C {lv.src} worktree remove {lv.target}",
                stderr=proc.stderr,
                hint="若报 contains modified or untracked files，说明里面有未提交内容——"
                     "先人工确认要不要留，**不要**盲加 --force 掩盖因果；"
                     "若报 working trees containing submodules cannot be removed，"
                     "说明还有子层没删完（本脚本按深度优先排序，正常不会撞到）\n"
                     f"本次已经完成的部分（不会自动回滚）：{'；'.join(done_actions) if done_actions else '无'}；"
                     f"剩余未处理：{'；'.join(remaining)}",
            )
        clean_parent_after_removal(lv.parent_wt, lv.rel, lv.target)
        done_actions.append(f"已删除 worktree 层 {lv.target}")
        if clean_branches and branch:
            res = try_delete_branch(lv.src, branch, args.force_delete_branches)
            print(f"    ↳ git -C {lv.src} branch -d {branch}：{res}")
            if res.startswith("已删除"):
                done_actions.append(f"已删除分支 {branch}（在 {lv.src} 里）")

    if args.keep_parent:
        print(f"\n[wt_supply] remove 完成（--keep-parent：父仓工作区 {target} 保留）。")
        return
    print(f"  git -C {source} worktree remove {target}")
    proc = git(source, "worktree", "remove", str(target), check=False)
    if proc.returncode != 0:
        raise Fail(
            f"删除父仓工作区 {target} 失败",
            cmd=f"git -C {source} worktree remove {target}",
            stderr=proc.stderr,
            hint="里面还有未提交内容或未跟踪文件——人工确认后手动处理；"
                 "或加 --keep-parent 只清 submodule 层\n"
                 f"本次已经完成的部分（不会自动回滚）：{'；'.join(done_actions) if done_actions else '无'}；"
                 f"剩余未处理：{target}（父仓工作区）",
        )
    if clean_branches and parent_branch:
        print(f"  git -C {source} branch -d {parent_branch}：{try_delete_branch(source, parent_branch, args.force_delete_branches)}")
    print(f"\n[wt_supply] remove 完成。目标 worktree 已整体清除，源 worktree {source} 未受影响。")
