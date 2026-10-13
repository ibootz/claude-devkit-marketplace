#!/usr/bin/env python3
"""wt_mergeback.py —— `merge-back` 子命令：把目标 worktree 各层合回源 worktree。

从 wt_supply.py 拆出的原因
--------------------------
回流合并（自底向上 `merge --no-ff` + gitlink 回写，默认 dry-run、显式 `--apply`
才真正执行）是四个子命令里逻辑最重的一块，且是唯一会改 gitlink 指针、在源侧
建 commit 的子命令——与其余「纯供给」子命令（`init`/`supply`/`status`/`remove`
一律不改 gitlink）的语义边界泾渭分明，拆开后这条边界从文件边界上也看得出来。
只依赖 `wt_levels.py` 的层级遍历（`walk_levels`）与状态常量
（`BLOCKING`/`EMPTY`/`PRUNABLE`），以及 `wt_source.py` 的 `resolve_source`。
"""

from __future__ import annotations

import sys
from pathlib import Path

from wt_git import (Fail, changed_paths, commit_line, current_branch,
                    dirty_lines, dirty_paths, git, git_out, gitlink_sha,
                    parse_gitmodules, resolve_worktree, rev_count,
                    staged_paths, unmerged_paths)
from wt_levels import BLOCKING, EMPTY, PRUNABLE, walk_levels
from wt_source import resolve_source

# ---------------------------------------------------------------- merge-back


def sub_rels(repo: Path) -> set:
    return {rel.rstrip("/") for _n, rel in parse_gitmodules(repo)}


def merge_into(repo: Path, branch: str, msg: str, layer: str) -> str:
    """在 repo 里 `merge --no-ff <branch>`。冲突若全是 gitlink（⊆ 本仓声明的 submodule
    路径集合），按「取工作树里已 merge 好的实际 HEAD」`git add` + `commit --no-edit`
    收敛（本流程自底向上，子层早已合完并前进到包含双方内容的提交）；有任何一条非
    gitlink 冲突就整体阻断。"""
    proc = git(repo, "merge", "--no-ff", "-m", msg, branch, check=False)
    if proc.returncode == 0:
        return "merged"
    conflicts = unmerged_paths(repo)
    subs = sub_rels(repo)
    if conflicts and all(c.rstrip("/") in subs for c in conflicts):
        print(f"    gitlink 冲突 {len(conflicts)} 条，全部按「取工作树实际 HEAD」解决："
              f"{', '.join(conflicts)}")
        for c in conflicts:
            git(repo, "add", c)
        git(repo, "commit", "--no-edit")
        return "merged-with-gitlink-resolve"
    raise Fail(
        f"在 {repo} 里 merge {branch} 失败（层 {layer}）",
        cmd=f"git -C {repo} merge --no-ff {branch}",
        stderr=(proc.stdout or "") + (proc.stderr or ""),
        hint=f"**已成功的层刻意不回滚**（与 aisdlc 的回流语义一致，整个流程幂等可重跑）。"
             f"恢复路径二选一：(a) 在 {repo} 里手工解决冲突并 `git commit`，"
             f"然后重跑同一条 merge-back --apply，已合完的层会显示 Already up to date；"
             f"(b) `git -C {repo} merge --abort` 放弃这一层，"
             f"注意比它更深的层已经合完、不会被 abort 撤销。"
             f"非 gitlink 冲突文件："
             f"{', '.join(c for c in conflicts if c.rstrip('/') not in subs) or '(见 stderr)'}",
    )


def source_dirty_check(repo: Path, changed: set, label: str,
                       blockers: list, notices: list) -> None:
    """源侧收窄判据（目标侧不用这条，仍走 dirty_lines 全树严格检查）：已 staged 会被
    `--apply` 里不带 pathspec 的 gitlink 回写 commit 卷走，故硬拦；未 staged 的脏文件
    只在与 `changed`（本次合并触碰的路径）相交时才拦（否则放行、只记提示）——不相交
    则 `git commit` 碰不到它，相交则 `git merge` 自己也会拒绝，等价提前拦下。"""
    staged = staged_paths(repo)
    if staged:
        blockers.append(f"{label}已 staged {len(staged)} 项，会被不带 pathspec 的 gitlink "
                        f"回写 commit 卷入：{repo}\n      " + "\n      ".join(staged[:20])
                        + "\n      → 先 commit 或 `git restore --staged <path>` 撤出暂存区")
    unstaged = [p for p in dirty_paths(repo) if p not in set(staged)]
    hit = [p for p in unstaged if p in changed]
    if hit:
        blockers.append(f"{label}未 staged 改动与合并路径相交（{len(hit)} 项），git merge 会报 "
                        f"local changes would be overwritten：{repo}\n      " + "\n      ".join(hit[:20]))
    miss = [p for p in unstaged if p not in changed]
    if miss:
        notices.append(f"{label}有 {len(miss)} 项未 staged 改动与本次合并无关，已放行：{repo}\n      "
                       + "\n      ".join(miss[:20]))


def cmd_merge_back(args) -> None:
    target = resolve_worktree(args.worktree)
    source = resolve_source(target, args.source)
    apply_mode = bool(args.apply)

    tgt_root_branch = current_branch(target)
    src_root_branch = current_branch(source)
    if not tgt_root_branch:
        raise Fail(f"目标 worktree {target} 处于 detached HEAD，取不到要回流的分支名",
                   hint=f"在该目录里 `git checkout -b <name>` 命名当前工作后重跑")
    if not src_root_branch:
        raise Fail(f"源 worktree {source} 处于 detached HEAD，无法作为 merge 落点",
                   hint=f"先 `git -C {source} checkout <目标分支>` 再重跑")

    print(f"[wt_supply] merge-back{'（--apply 真实执行）' if apply_mode else '（dry-run，默认；零副作用）'}")
    print(f"  目标 worktree : {target}（分支 {tgt_root_branch}）")
    print(f"  源 worktree   : {source}（分支 {src_root_branch}）  ← 合并落点")
    print(f"  顺序          : 自底向上（最深嵌套层先合），父仓最后")
    print(f"  每层做三件事  : 先 commit 子层刚回写的 gitlink → merge --no-ff → "
          f"把本层新 HEAD stage 进父层\n")

    # ---- 前置校验（任何一条不过就整体阻断，不做局部执行） ----
    # 目标侧（fixer 工作区）全树严格：脏了即有未提交产物，必须硬拦；源侧（主会话日常
    # 干活处）改用 source_dirty_check 收窄判据，避免全树严格造成主会话与 keeper 死锁。
    blockers, notices = [], []
    src_root_head = git_out(source, "rev-parse", "HEAD")
    d = dirty_lines(target)
    if d:
        blockers.append(f"目标 worktree 父仓不干净（{len(d)} 项）：{target}\n      "
                        + "\n      ".join(d[:20]))
    source_dirty_check(source, set(changed_paths(target, f"{src_root_head}..{tgt_root_branch}")),
                       "源 worktree 父仓", blockers, notices)

    plan, skipped = [], []
    for lv, st in walk_levels(target, source):
        if st == EMPTY:
            skipped.append((lv, "目标侧未供给这一层，无内容可回流"))
            continue
        if st in BLOCKING or st == PRUNABLE:
            blockers.append(f"层 {lv.rel} 状态为 {st}，不可回流：{lv.target}")
            continue
        sb, tb = current_branch(lv.src), current_branch(lv.target)
        src_head = git_out(lv.src, "rev-parse", "HEAD")
        d = dirty_lines(lv.target)
        if d:
            blockers.append(f"目标侧层 {lv.rel} 不干净（{len(d)} 项）：{lv.target}\n      "
                            + "\n      ".join(d[:20]))
        changed_lv = set(changed_paths(lv.target, f"{src_head}..{tb}")) if tb else set()
        source_dirty_check(lv.src, changed_lv, f"源侧层 {lv.rel} ", blockers, notices)
        if sb is None:
            # 源侧 detached 的层本不该被改动。目标侧一旦出现新提交，说明流程被绕过了
            # （在 detached 层上开发的内容没有分支承载，回流没有落点）。
            ahead = rev_count(lv.target, f"{src_head}..HEAD")
            if ahead:
                blockers.append(
                    f"层 {lv.rel} 在源侧是 detached（不参与回流），但目标侧有 {ahead} 个"
                    f"新提交：{lv.target}\n      "
                    f"这些提交没有分支承载、回流无落点。先在目标侧 "
                    f"`git -C {lv.target} checkout -b <name>` 命名它们，"
                    f"并在源侧把该层切到同名分支，再重跑")
            else:
                skipped.append((lv, "源侧 detached，照设计不参与回流"))
            continue
        if tb is None:
            blockers.append(f"层 {lv.rel} 源侧在分支 {sb} 但目标侧是 detached："
                            f"{lv.target}（形态漂移，supply 时应已同步）")
            continue
        if sb != src_root_branch:
            blockers.append(
                f"层 {lv.rel} 源侧在分支 {sb}，与源父仓分支 {src_root_branch} 不一致："
                f"{lv.src}\n      "
                f"聚合仓的各层应与父仓同名分支同步推进；不一致时无法判定该层该合到哪里，"
                f"故整体阻断（旧实现在这里静悄悄合到错分支，是必须修的缺陷）。"
                f"先 `git -C {lv.src} checkout {src_root_branch}` 再重跑")
            continue
        plan.append((lv, sb, tb, src_head))

    if notices:
        print(f"  提示（{len(notices)} 项，与本次合并无关的源侧未 staged 改动，已放行）：")
        for n in notices:
            print(f"    · {n}")
        print()

    if blockers:
        print(f"  前置校验不通过（{len(blockers)} 项），未执行任何操作：")
        for b in blockers:
            print(f"    ✗ {b}")
        print(f"\n[wt_supply] merge-back 中止。修掉上面每一项后重跑。")
        sys.exit(2)

    for lv, why in skipped:
        print(f"  跳过 {lv.rel}：{why}")
    if skipped:
        print()

    plan.sort(key=lambda t: -t[0].depth)  # 自底向上：子层深度严格大于父层

    # ---- 逐层打印新旧 gitlink 对照（gitlink 红线要求的短 SHA + 日期 + subject） ----
    for lv, sb, tb, src_head in plan:
        tip = git_out(lv.target, "rev-parse", tb)
        old_link = gitlink_sha(lv.parent_src, lv.rel)
        ahead = rev_count(lv.target, f"{src_head}..{tip}")
        print(f"=== {lv.rel}（depth {lv.depth}）===")
        print(f"  合并目标分支 : {sb}  ← 源侧 {lv.src} 当前所在分支")
        print(f"  目标侧分支   : {tb}（tip {tip[:12]}）")
        print(f"  命令         : git -C {lv.src} merge --no-ff {tb}")
        print(f"  gitlink 回写 : git -C {lv.parent_src} add {lv.rel}")
        print(f"    旧 gitlink : {commit_line(lv.src, old_link)}")
        if ahead == 0:
            print(f"    新 gitlink : 与旧值一致（目标侧无新提交，merge 会报 "
                  f"Already up to date）")
        else:
            print(f"    新 gitlink : merge --no-ff 产生的新 merge commit，"
                  f"将包含目标侧 tip {commit_line(lv.target, tip)}")
            span = git(lv.target, "log", "--date=short", "--format=%h %ad %s",
                       f"{src_head}..{tip}", check=False)
            lines = [l for l in span.stdout.strip().splitlines() if l]
            print(f"    跨越 {len(lines)} 个提交：")
            for l in lines[:20]:
                print(f"      {l}")
            if len(lines) > 20:
                print(f"      … 另有 {len(lines) - 20} 条")
        print()

    root_ahead = rev_count(target, f"{src_root_head}..{tgt_root_branch}")
    print(f"=== 父仓（{source}）===")
    print(f"  合并目标分支 : {src_root_branch}")
    print(f"  命令         : git -C {source} merge --no-ff {tgt_root_branch}")
    if root_ahead == 0:
        print(f"  目标侧父仓无新提交，merge 会报 Already up to date")
    else:
        span = git(target, "log", "--date=short", "--format=%h %ad %s",
                   f"{src_root_head}..{tgt_root_branch}", check=False)
        lines = [l for l in span.stdout.strip().splitlines() if l]
        print(f"  跨越 {len(lines)} 个提交：")
        for l in lines[:20]:
            print(f"    {l}")
        if len(lines) > 20:
            print(f"    … 另有 {len(lines) - 20} 条")
    print()

    if not apply_mode:
        print("[wt_supply] dry-run 结束，未执行任何写操作（零副作用）。"
              "核对上面每层的新旧 gitlink（短 hash + 日期 + message）后，"
              "加 --apply 真正执行。")
        return

    # ---- 真实执行 ----
    # 每层顺序：先 commit 子层刚 stage 的 gitlink → merge → stage 进父层。
    # 「先 commit」这一步不是可选的。实测（2026-07-29）：若把子层合出的新 HEAD 留在
    # 工作树里不 commit 就直接 merge 父层，git **不会**报错，而是把父层 gitlink 直接
    # 写成目标侧那个 tip、丢掉源侧刚做出的 merge commit，工作树留下一条 `M <sm>`。
    # 源侧该层若本来有自己的提交，那些内容就在这一步被静默丢弃。
    for lv, sb, tb, _src_head in plan:
        print(f"[apply] === {lv.rel} ===")
        pending = staged_paths(lv.src)
        if pending:
            print(f"  git -C {lv.src} commit（回写子层 gitlink：{', '.join(pending)}）")
            git(lv.src, "commit", "-m",
                f"chore(wt-supply): 回写 {', '.join(pending)} gitlink"
                f"（merge-back {tb}）")
        print(f"  git -C {lv.src} merge --no-ff {tb}")
        merge_into(lv.src, tb, f"merge(wt-supply): 合入 {tb}", lv.rel)
        new_head = git_out(lv.src, "rev-parse", "HEAD")
        print(f"  git -C {lv.parent_src} add {lv.rel}   （gitlink → {new_head[:12]}）")
        git(lv.parent_src, "add", lv.rel)

    print(f"[apply] === 父仓 {source} ===")
    pending = staged_paths(source)
    if pending:
        print(f"  git -C {source} commit（回写 gitlink：{', '.join(pending)}）")
        git(source, "commit", "-m",
            f"chore(wt-supply): 回写 {', '.join(pending)} gitlink"
            f"（merge-back {tgt_root_branch}）")
    print(f"  git -C {source} merge --no-ff {tgt_root_branch}")
    merge_into(source, tgt_root_branch,
               f"merge(wt-supply): 合入 {tgt_root_branch}", "(父仓)")

    print(f"\n[wt_supply] merge-back --apply 完成。最终 gitlink：")
    for lv, _sb, _tb, _sh in plan:
        print(f"  {lv.rel.ljust(30)} {commit_line(lv.src, gitlink_sha(lv.parent_src, lv.rel))}")
    left = dirty_lines(source)
    if left:
        print(f"  ⚠ 源 worktree 仍有 {len(left)} 项未提交改动，请人工核对：")
        for l in left[:20]:
            print(f"      {l}")
    else:
        print(f"  源 worktree 干净（已剔除嵌套 worktree 目录）。")
    print(f"  提交已落在源侧各层与父仓的分支上，**未 push**。"
          f"push 与否、何时 push 由主会话在 Human 明确同意后另行执行，"
          f"不是本工具或任何调用者的默认职责；"
          f"清理目标 worktree 用 "
          f"`wt_supply.py remove --worktree {target} --yes`。")
