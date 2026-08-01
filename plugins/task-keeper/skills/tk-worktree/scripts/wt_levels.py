#!/usr/bin/env python3
"""wt_levels.py —— submodule 层级遍历与供给引擎。

从 wt_supply.py 拆出的原因
--------------------------
这是 `init` / `supply` / `status` 三个子命令共用的核心机制：状态判据
（`classify` 与 OK/EMPTY/ISOLATED/... 常量）、层级遍历（`Level` / `walk_levels`）、
逐层供给（`pick_branch` / `supply_level` / `supply_all`）、状态汇总
（`report_levels`，同时被 `cmd_init` 的自校验与 `cmd_status` 复用）。这部分体量
最大且自成闭环，与「回流合并」（`wt_mergeback.py`）、「remove 清理」
（`wt_remove.py`）两条链路各自独立，拆开后三处改动互不干扰。
"""

from __future__ import annotations

import os
from pathlib import Path

from wt_git import (Fail, branch_exists, branch_in_use, current_branch, git,
                    git_common_dir, gitlink_sha, parse_gitmodules,
                    read_dotgit_file, worktree_entries)

# ---------------------------------------------------------------- 状态判据

OK = "ok"
EMPTY = "empty"
ISOLATED = "isolated-objdir"
UNREACHABLE = "unreachable"
PRUNABLE = "prunable"
SRCMISSING = "source-missing"

BLOCKING = (ISOLATED, UNREACHABLE, SRCMISSING)


def classify(target: Path, src: Path) -> str:
    """判定目标侧某一层工作区的状态。判据全部取自文件系统与 git 的确定输出。

    ok              —— `.git` 是文件，指向的 gitdir 有 `commondir`、**没有**自己的
                        `objects/`，且该 commondir **等于源侧同层的 git-common-dir**
                        = 对象库与源侧共享。
    empty           —— 目录不存在 / 存在但无 `.git`（还没供给）。
    isolated-objdir —— `.git` 是目录，或指向一个完整独立对象库，或 commondir 与
                        源侧同层不一致（对象库没共享，回流会失败）。
    unreachable     —— `.git` 文件指向的 gitdir 已不存在。
    prunable        —— 目录被手动 `rm -rf` 掉，但仍登记在 `worktree list` 里。
    source-missing  —— **源侧**这一层没有 `.git`。源侧缺内容时目标侧无从供给，
                        且没有对象库可比对，其余判据全部无意义，故优先返回它。

    「commondir 等于源侧同层」这条判据取代了早先「commondir 落在
    `<主仓>/.git/modules/` 之下」——后者只认「主 checkout 侧有对象库」这一种拓扑，
    会把源侧是 worktree 私有克隆的那 18 个层全部误判成 isolated-objdir（实测）。
    """
    if not (src / ".git").exists():
        return SRCMISSING
    dotgit = target / ".git"
    if not target.exists() or not dotgit.exists():
        for e in worktree_entries(src):
            if e["path"] == target and e["prunable"]:
                return PRUNABLE
        return EMPTY
    if dotgit.is_dir():
        return ISOLATED
    gitdir = read_dotgit_file(dotgit)
    if gitdir is None:
        return ISOLATED
    if not gitdir.exists():
        return UNREACHABLE
    commondir = gitdir / "commondir"
    if not commondir.is_file() or (gitdir / "objects").is_dir():
        return ISOLATED  # 完整独立对象库，不是共享对象库的 linked worktree
    common = Path(commondir.read_text(encoding="utf-8").strip())
    if not common.is_absolute():
        common = gitdir / common
    if common.resolve() != git_common_dir(src):
        return ISOLATED
    return OK


# ---------------------------------------------------------------- 层级遍历


class Level:
    """一层 submodule：目标侧父工作区 / 源侧父工作区 / 相对路径 / 嵌套深度。"""

    def __init__(self, parent_wt: Path, parent_src: Path, rel: str, depth: int):
        self.parent_wt = Path(parent_wt)
        self.parent_src = Path(parent_src)
        self.rel = rel.rstrip("/")
        self.depth = depth
        self.target = Path(os.path.normpath(str(self.parent_wt / self.rel)))
        self.src = Path(os.path.normpath(str(self.parent_src / self.rel)))

    @property
    def label(self) -> str:
        return f"{'  ' * self.depth}{self.rel}"


def walk_levels(root_wt: Path, root_src: Path):
    """按**源侧** `.gitmodules` 递归枚举所有层，前序返回 [(Level, status)]。

    刻意从源侧枚举而不是目标侧：目标侧未供给的层是空目录、读不到它自己的
    `.gitmodules`，从目标侧枚举会看不见嵌套层的存在（旧实现的已知盲区）。
    源侧是完整的，枚举它才能在供给前就把整棵树列全。
    """
    out = []

    def rec(parent_wt, parent_src, depth):
        for _name, rel in parse_gitmodules(parent_src):
            lv = Level(parent_wt, parent_src, rel, depth)
            out.append((lv, classify(lv.target, lv.src)))
            if (lv.src / ".git").exists():
                rec(lv.target, lv.src, depth + 1)

    rec(Path(root_wt), Path(root_src), 0)
    return out


# ---------------------------------------------------------------- supply


def pick_branch(level: Level, base: str) -> str:
    """撞分支占用 / 同名已存在时，派生 `<base>-<相对路径最后一段>`。"""
    if not branch_exists(level.src, base):
        return base
    holder = branch_in_use(level.src, base)
    derived = f"{base}-{level.rel.split('/')[-1]}"
    why = (f"已被 worktree {holder} 占用" if holder else "同名分支已存在")
    if not branch_exists(level.src, derived):
        print(f"      分支 {base} {why}，改用派生名 {derived}")
        return derived
    raise Fail(
        f"{level.src} 里分支 {base} 与派生名 {derived} 都不可用（{why}）",
        hint=f"用 --branch <其他名字> 显式指定，或先清理占用它的 worktree",
    )


def supply_level(level: Level, base_branch: str, dry_run: bool, stats: dict) -> None:
    """供给一层。目标侧形态（分支 / detach）机械照抄源侧同层。"""
    indent = "  " * (level.depth + 1)
    st = classify(level.target, level.src)
    if st == SRCMISSING:
        raise Fail(
            f"源侧 {level.src} 没有 .git，这一层在源 worktree 里就是空的",
            hint=f"先在源 worktree 侧把这层补齐（`wt_supply.py status --worktree "
                 f"{level.parent_src}` 看它自己的状态），再供给目标 worktree",
        )

    sha = gitlink_sha(level.parent_src, level.rel)
    src_branch = current_branch(level.src)
    mode = f"-b {base_branch}" if src_branch else "--detach"
    print(f"{indent}[{level.rel}] gitlink={sha[:12]} 状态={st} "
          f"源侧={'分支 ' + src_branch if src_branch else 'detached'} → 目标侧 {mode}")

    if st == OK:
        tb = current_branch(level.target)
        want = base_branch if src_branch else None
        if tb != want and not (want and tb and tb.startswith(want)):
            print(f"{indent}  已 ok 但形态与源侧不匹配："
                  f"目标侧={'分支 ' + tb if tb else 'detached'}，"
                  f"按源侧应为 {'分支 ' + want if want else 'detached'}"
                  f"（不自动纠正；要纠正先 remove 这一层再 supply）")
        else:
            print(f"{indent}  已 ok，跳过（幂等）")
        stats["skipped"] += 1
        return
    if st == ISOLATED:
        raise Fail(
            f"{level.target} 是独立对象库（isolated-objdir），不能原地转成共享 worktree",
            hint=f"先 `rm -rf {level.target}` 再重跑 supply；若里面有未推送提交，"
                 f"先在该目录里 `git bundle create` 或 push 到别处备份",
        )
    if st == UNREACHABLE:
        raise Fail(
            f"{level.target}/.git 指向的 gitdir 不存在（unreachable）",
            hint=f"`rm -rf {level.target}` 后重跑 supply；"
                 f"并在 {level.src} 里跑 `git worktree prune` 清残留登记",
        )
    if st == PRUNABLE:
        print(f"{indent}  登记残留（prunable），先 prune")
        if dry_run:
            print(f"{indent}  [dry-run] git -C {level.src} worktree prune")
        else:
            git(level.src, "worktree", "prune")

    if level.target.exists() and any(level.target.iterdir()):
        raise Fail(
            f"目标路径 {level.target} 已存在且非空，`git worktree add` 会报 "
            f"fatal: '<path>' already exists",
            hint=f"确认里面没有要留的东西后 `rm -rf {level.target}`，再重跑 supply",
        )

    if dry_run:
        print(f"{indent}  [dry-run] git -C {level.src} worktree add "
              f"{mode} {level.target} {sha[:12]}")
        stats["planned"] += 1
        return

    if src_branch:
        add_args = ["-b", pick_branch(level, base_branch)]
    else:
        add_args = ["--detach"]
    proc = git(level.src, "worktree", "add", *add_args,
               str(level.target), sha, check=False)
    if proc.returncode != 0:
        err = proc.stderr
        hint = f"检查 {level.src} 的对象库里是否有 gitlink 提交 {sha[:12]}"
        if "already used by worktree at" in err:
            hint = (f"分支 {base_branch} 已被别的 worktree 占用，"
                    f"用 --branch <其他名字> 显式指定")
        elif "already exists" in err:
            hint = f"目标路径已存在且非空，先 rm -rf {level.target}"
        raise Fail(
            f"为 {level.rel} 建 submodule worktree 失败",
            cmd=f"git -C {level.src} worktree add {' '.join(add_args)} "
                f"{level.target} {sha}",
            stderr=err,
            hint=hint,
        )
    st2 = classify(level.target, level.src)
    if st2 != OK:
        raise Fail(
            f"供给后 {level.target} 状态是 {st2}，不是 ok",
            hint=f"人工比对 `cat {level.target}/.git` 与 "
                 f"`git -C {level.src} rev-parse --git-common-dir`",
        )
    tb = current_branch(level.target)
    print(f"{indent}  已供给：{'分支 ' + tb if tb else 'detached ' + sha[:12]}，"
          f".git → {read_dotgit_file(level.target / '.git')}")
    stats["supplied"] += 1


def supply_all(target: Path, source: Path, base_branch: str, dry_run: bool) -> dict:
    """全量递归供给：范围 = 源侧 `.gitmodules` 声明的全部层，逐层下钻。"""
    stats = {"supplied": 0, "skipped": 0, "planned": 0}

    def rec(parent_wt, parent_src, depth):
        for _name, rel in parse_gitmodules(parent_src):
            lv = Level(parent_wt, parent_src, rel, depth)
            supply_level(lv, base_branch, dry_run, stats)
            if (lv.src / ".git").exists():
                rec(lv.target, lv.src, depth + 1)

    rec(target, source, 0)
    return stats


# ---------------------------------------------------------------- status


def report_levels(target: Path, source: Path) -> list:
    """逐层打印状态 + 源侧/目标侧形态差异，返回非 ok 层清单。"""
    rows = walk_levels(target, source)
    if not rows:
        print("    无 .gitmodules —— 源 worktree 没有 submodule，无需供给。")
        return []
    src_root_branch = current_branch(source)
    width = max(len(lv.label) for lv, _st in rows)
    print(f"    {'path'.ljust(width)}  status           形态")
    bad = []
    for lv, st in rows:
        sb = current_branch(lv.src) if (lv.src / ".git").exists() else None
        tb = current_branch(lv.target) if (lv.target / ".git").exists() else None
        shape = f"源={'分支 ' + sb if sb else 'detached'} / " \
                f"目标={'分支 ' + tb if tb else ('detached' if st == OK else '—')}"
        print(f"    {lv.label.ljust(width)}  {st.ljust(15)}  {shape}")
        if st != OK:
            bad.append((lv, st))
        notes = []
        if st == EMPTY:
            notes.append(f"源侧声明了但目标侧缺失——跑 `supply --worktree {target}`")
        elif st == PRUNABLE:
            notes.append(f"需要 `git -C {lv.src} worktree prune`（目录已删但登记还在）")
        elif st == ISOLATED:
            notes.append(f"对象库未与源侧共享，本地未推送提交不可见；"
                         f"`rm -rf {lv.target}` 后重跑 supply")
        elif st == UNREACHABLE:
            notes.append(".git 指向的 gitdir 已不存在")
        elif st == SRCMISSING:
            notes.append(f"**源侧** {lv.src} 就没有 .git，先修源 worktree")
        elif st == OK:
            if bool(sb) != bool(tb):
                notes.append(f"形态与源侧不一致（源侧 {'on-branch' if sb else 'detached'}，"
                             f"目标侧 {'on-branch' if tb else 'detached'}）")
            if sb and src_root_branch and sb != src_root_branch:
                notes.append(f"源侧分支名 {sb} ≠ 源父仓分支名 {src_root_branch}，"
                             f"merge-back 会 fail-loud")
        for n in notes:
            print(f"    {' ' * width}  ↳ {n}")
    return bad
