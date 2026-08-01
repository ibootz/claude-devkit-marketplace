#!/usr/bin/env python3
"""wt_source.py —— 目标 worktree 的"源 worktree 记忆"：记录 / 解析它是从哪个源
worktree 供给出来的。

从 wt_supply.py 拆出的原因
--------------------------
`SOURCE_MARK` 这个值被 `hooks/lib/keeper_paths.py` 依赖（该文件第 87 行也定义了
同名字面量 `SOURCE_MARK = "wt-supply-source"`，靠字面量约定协作、没有 import
关系，用于从 fixer worktree 的 gitdir 回溯到 delivery worktree）——改这里的值前，
先去同步 `hooks/lib/keeper_paths.py` 那份拷贝，两边必须一致。

`resolve_source()` 被 `cmd_status` / `cmd_supply`（留在 `wt_supply.py`）、
`cmd_remove`（`wt_remove.py`）、`cmd_merge_back`（`wt_mergeback.py`）四处共用。
把它连同 `record_source()` 一起拆成这个不依赖任何 `cmd_*` 的叶子模块，是为了
避免循环 import：`wt_remove.py` 与 `wt_mergeback.py` 都需要 `resolve_source`，
若把它留在 `wt_supply.py` 里，那两个文件反过来又要被 `wt_supply.py` import
它们各自的 `cmd_*`，会形成 `wt_supply → wt_remove → wt_supply` 这样的环。
"""

from __future__ import annotations

from pathlib import Path

from wt_git import Fail, git_dir, resolve_worktree

# ---------------------------------------------------------------- 源 worktree 记忆

SOURCE_MARK = "wt-supply-source"


def record_source(target: Path, source: Path) -> None:
    """把源 worktree 路径记在**目标 worktree 私有的 gitdir** 里。

    落在 gitdir（`<主仓>/.git/worktrees/<name>/`）而不是工作树里，有两个原因：
    工作树里放文件会让目标仓 `git status` 多一条未跟踪项、进而污染 merge-back 的
    干净度校验；而 `git config` 默认写的是**跨 worktree 共享**的 `.git/config`，
    会波及主 checkout 和所有兄弟 worktree。gitdir 下的普通文件两个问题都没有。
    """
    (git_dir(target) / SOURCE_MARK).write_text(str(source) + "\n", encoding="utf-8")


def resolve_source(target: Path, explicit: str | None) -> Path:
    """定源 worktree：显式 `--source` 优先，否则读 `init`/`supply` 记下的那份。"""
    if explicit:
        source = resolve_worktree(explicit, "source")
    else:
        mark = git_dir(target) / SOURCE_MARK
        if not mark.is_file():
            raise Fail(
                f"没给 --source，且 {target} 的 gitdir 里也没有 {SOURCE_MARK} 记录",
                hint="显式加 --source <源 worktree 绝对路径>；由 `init` 建出的目标"
                     "worktree 会自动记住源，无需每次都给",
            )
        source = resolve_worktree(mark.read_text(encoding="utf-8").strip(), "source")
    if source == target:
        raise Fail(
            f"--source 与 --worktree 指向同一个目录（{target}）",
            hint="源 worktree 与目标 worktree 必须是两个不同的工作区",
        )
    return source
