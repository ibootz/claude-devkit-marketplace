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

from wt_git import (Fail, branch_exists, branch_in_use, changed_paths,
                    commit_line, current_branch, die, dirty_lines, dirty_paths,
                    git, git_common_dir, git_dir, git_out, gitlink_sha,
                    main_checkout, parse_gitmodules, read_dotgit_file,
                    resolve_worktree, rev_count, staged_paths, unmerged_paths,
                    worktree_entries)
from wt_scope import cmd_explain_scope

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


# ---------------------------------------------------------------- init

WID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def cmd_init(args) -> None:
    """一条命令建出结构完整的聚合仓 worktree：父仓 + 全部 submodule 层 + 自校验。

    落点为什么**固定**在 `<source>/.keeper/worktrees/<id>/`，不做成可配
    -------------------------------------------------------------
    很多工具链（hook、状态注入、路径识别）靠 **cwd 的路径字面量**反推「当前处于
    哪个工作区」。把目标 worktree 放在源 worktree **内部**时，它的绝对路径天然
    包含源 worktree 的完整路径前缀，这类识别全部照常工作；落到外部会被静默判成
    另一个无关工作区，没有任何报错。

    一个真实例子：某交付框架的路径识别常量是 `MARKER = '/.sdlc/worktrees/'`，
    紧跟一个 slug 白名单（只认 `^D-\\d+` 或 `^hotfix-` 开头）。fixer worktree 若
    直接落到 `.sdlc/worktrees/DBG-021`，MARKER 命中、slug 校验不认 → 一整串依赖
    cwd 判断的 hook 集体失准；落在源 worktree 内部的 `.keeper/worktrees/DBG-021`
    则前缀完整保留、识别不受任何影响。这条约束只要求「落点在源 worktree 内部」，
    具体挂哪个子目录不重要——统一放 `.keeper/worktrees/<id>/`，与 `.keeper/debug/`
    的队列数据（`issues/`/`receipts/`/`attachments/`）平级分层。`.keeper/` 整树
    在项目 `.gitignore` 里，worktree 临时产物不需要单独的排除规则。

    **所以这个落点不是随手挑的，挪走它会静默破坏宿主工具链的 worktree 识别。**
    """
    source = resolve_worktree(args.source, "source")
    wid = args.id.strip()
    if not WID_RE.match(wid):
        raise Fail(
            f"--id 只接受字母数字开头、由字母数字与 . _ - 组成的名字，收到：{args.id!r}",
            hint="它会直接作为目录名用在 <source>/.keeper/worktrees/<id>/，不接受路径分隔符",
        )
    target = Path(os.path.normpath(str(source / ".keeper" / "worktrees" / wid)))
    branch = args.branch or f"fix/{wid}"

    print(f"[wt_supply] init{'（dry-run）' if args.dry_run else ''}")
    print(f"  源 worktree : {source}（分支 {current_branch(source) or 'detached'}）")
    print(f"  目标落点    : {target}   ← 固定 <source>/.keeper/worktrees/<id>/，理由见 cmd_init docstring")
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
                   help="工作区标识（如 DBG-021）；落点固定 <source>/.keeper/worktrees/<id>/")
    s.add_argument("--branch", help="目标分支名，缺省 fix/<id>")
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
