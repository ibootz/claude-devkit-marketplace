#!/usr/bin/env python3
"""wt_git.py —— wt_supply.py 的 git 管道层（无业务语义，只做「问 git 要事实」）。

为什么单独一个文件
------------------
本插件仓有 PostToolUse guard（`hooks/guards/write-guard.js`）在单一源码文件超过
1000 行时阻断写入。`wt_supply.py` 在改造成「完整聚合仓 worktree」形态后，
init / supply / status / remove / merge-back 五个子命令连注释会撞线，故把
**不含任何业务判断**的 git 调用封装拆到这里。拆分依据是「有没有业务语义」，
不是单纯按行数切——本文件里的每个函数都能用一句「git 的某个事实」说清。

约定
----
* 所有 git 调用走 `subprocess.run` + 显式 `-C <path>`：不用 `cd`，不用 `shell=True`。
* 路径一律 `pathlib.Path`，跨 macOS（/tmp → /private/tmp 符号链接）时统一 `.resolve()`。
* 失败即抛 `Fail`，由调用方的顶层 `die()` 统一打印「实际命令 / stderr 原文 / 建议下一步」。
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------- fail-loud


class Fail(Exception):
    """fail-loud 载体：带上实际命令 / stderr / 建议下一步。"""

    def __init__(self, msg, cmd=None, stderr=None, hint=None):
        super().__init__(msg)
        self.msg = msg
        self.cmd = cmd
        self.stderr = stderr
        self.hint = hint


def fail_lines(exc: Fail, prefix: str = "") -> list[str]:
    """把一个 `Fail` 渲染成「实际命令 / stderr 原文 / 建议下一步」三段文本行。

    单独抽出来是给**批量 init** 用的：批量下某个 id 失败不能直接 `die()`
    （那会 `sys.exit` 掉整个进程、把其余 id 一起带走），得先收集、最后统一打印，
    每行带 `[<id>] ` 前缀。`die()` 自己也复用它，保证两条路径的格式逐字一致。
    """
    out = [f"{prefix}失败：{exc.msg}"]
    if exc.cmd:
        out.append(f"{prefix}  实际执行：{exc.cmd}")
    if exc.stderr:
        for line in str(exc.stderr).rstrip().splitlines():
            out.append(f"{prefix}  stderr> {line}")
    if exc.hint:
        out.append(f"{prefix}  建议下一步：{exc.hint}")
    return out


def die(exc: Fail) -> None:
    lines = fail_lines(exc)
    print(f"\n[wt_supply] {lines[0]}", file=sys.stderr)
    for line in lines[1:]:
        print(line, file=sys.stderr)
    sys.exit(1)


def fmt(args) -> str:
    return " ".join(str(a) for a in args)


# ---------------------------------------------------------------- 锁冲突退避
#
# 批量 init 并行跑多个 id 时，所有 id 都从**同一个源仓**派生：父仓层的
# `worktree add` 写同一个 `<source>/.git/`，每个 submodule 层的 `worktree add` 写同一个
# 源侧 submodule 目录的 gitdir。git 对 index / refs / config 都用「建 `<file>.lock`」
# 做互斥，撞上时直接非零退出，**不自旋、不等待**。所以并行化必须自己退避重试。
#
# 判据一律是 stderr 里的**确定字符串**（`lock_conflict()`），不是「非零退出码」——
# 把所有非零退出都当可重试会把真实业务失败（gitlink 对象不存在、路径已占用、分支已
# 存在）重试 5 遍再报同一个错，既慢又掩盖因果。
#
# 取值理由：单次 `worktree add` 持锁时间是「写几个小文件」级别（毫秒到几十毫秒），
# 冲突窗口极窄，指数退避从 0.1s 起已经远大于持锁时长、第一次重试就大概率成功；
# 上限 2s 避免罕见的长事务把等待拖成分钟级；5 次重试的累计等待是
# 0.1+0.2+0.4+0.8+1.6 = 3.1s，足以熬过 8 个并行 id 排队写同一个仓，又不至于在真的
# 有陈留 `.lock` 文件（进程被 kill 后残留、重试永远不会成功）时白等太久。
LOCK_RETRIES = 5
LOCK_BACKOFF_BASE = 0.1
LOCK_BACKOFF_CAP = 2.0


def lock_conflict(stderr) -> bool:
    """stderr 是否是 git 的**瞬时**加锁/竞态失败（可退避重试），判据为确定字符串。

    前四条是**写侧**：git 用「建 `<file>.lock`」互斥 index / refs / config，撞上直接
    非零退出。第五条是**读侧**，2026-08-05 在 `--jobs 6` 压测里实测出来的：

        git -C <源侧某层> worktree list --porcelain
        fatal: failed to read '<gitdir>/worktrees/n20/locked': No such file or directory

    成因是 `git worktree add` 在建 `<gitdir>/worktrees/<id>/` 期间会先写一个 `locked`
    标记文件、装配完再删掉；并发跑的 `worktree list` 恰好在「readdir 已看到这个目录」
    与「open 那个 locked 文件」之间撞上删除动作，就 fatal 128。本工具的
    `worktree_entries()` / `branch_in_use()` / `classify()` 都会调 `worktree list`，
    所以多个 id 同时供给同一个源侧 submodule 时这条必踩。窗口只有毫秒级（不是整个
    checkout 时长——`locked` 存在期间读得到、不报错，只有写/删的瞬间才撞），退一下
    重读即可。
    """
    s = str(stderr or "")
    if "index.lock" in s:
        return True
    if "cannot lock ref" in s or "Cannot lock ref" in s:
        return True
    if "could not lock config file" in s:
        return True
    if ".lock" in s and ("Unable to create" in s or "unable to create" in s):
        return True
    if "failed to read" in s and "/locked'" in s:
        return True
    return False


def git(repo, *args, check=True, hint=None):
    """在 repo 里跑 git（显式 -C，不 cd）。check=True 时失败即 Fail。

    命中 `lock_conflict()` 时按 `LOCK_RETRIES` / `LOCK_BACKOFF_*` 指数退避重试；
    其他失败一律照原样返回（或抛 `Fail`），不重试。
    """
    cmd = ["git", "-C", str(repo), *[str(a) for a in args]]
    for attempt in range(LOCK_RETRIES + 1):
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 or attempt == LOCK_RETRIES \
                or not lock_conflict(proc.stderr):
            break
        time.sleep(min(LOCK_BACKOFF_CAP, LOCK_BACKOFF_BASE * (2 ** attempt)))
    if check and proc.returncode != 0:
        raise Fail(
            f"git 命令返回 {proc.returncode}",
            cmd=fmt(cmd),
            stderr=proc.stderr,
            hint=hint,
        )
    return proc


def git_out(repo, *args, hint=None) -> str:
    return git(repo, *args, hint=hint).stdout.strip()


# ---------------------------------------------------------------- 工作区拓扑


def resolve_worktree(path: str, what: str = "worktree") -> Path:
    p = Path(path).expanduser()
    if not p.exists():
        raise Fail(
            f"{what} 路径不存在：{p}",
            hint="确认路径拼写；源 worktree 需先存在，目标 worktree 由 `init` 建出",
        )
    p = p.resolve()
    if not (p / ".git").exists():
        raise Fail(
            f"{p} 下没有 .git，不是一个 git 工作区",
            hint=f"确认 --{'source' if what != 'worktree' else 'worktree'} "
                 f"指向一个 git checkout 或 `git worktree add` 产出的目录",
        )
    return p


def main_checkout(repo: Path) -> Path:
    """`git worktree list --porcelain` 的第一条恒为主 checkout（与发起命令的 worktree 无关）。

    实测从主 checkout / 任一派生 worktree 三个视角跑结果完全一致。本项目只用它做
    信息展示，不再作为供给来源——供给一律从 `--source` 侧发起（见 wt_supply.py 顶部说明）。
    """
    out = git_out(repo, "worktree", "list", "--porcelain")
    for line in out.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):]).resolve()
    raise Fail(
        f"无法从 {repo} 解析出主 checkout",
        cmd=f"git -C {repo} worktree list --porcelain",
        hint="确认该目录属于一个正常的 git 仓库",
    )


def worktree_entries(repo: Path):
    """返回 [{path, branch, detached, prunable}]。"""
    out = git_out(repo, "worktree", "list", "--porcelain")
    entries, cur = [], None
    for line in out.splitlines():
        if line.startswith("worktree "):
            if cur:
                entries.append(cur)
            cur = {
                "path": Path(line[len("worktree "):]).resolve(),
                "branch": None,
                "detached": False,
                "prunable": None,
            }
        elif cur is None:
            continue
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].replace("refs/heads/", "", 1)
        elif line.strip() == "detached":
            cur["detached"] = True
        elif line.startswith("prunable"):
            cur["prunable"] = line[len("prunable"):].strip() or "prunable"
    if cur:
        entries.append(cur)
    return entries


def current_branch(repo: Path) -> str | None:
    """返回分支名；detached HEAD 返回 None。

    用 `symbolic-ref` 而不是 `rev-parse --abbrev-ref HEAD`：后者在 detached 时
    返回字面字符串 `HEAD`，会被误当成一个叫 HEAD 的分支名。
    """
    proc = git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    return proc.stdout.strip() or None


def git_dir(repo: Path) -> Path:
    """本 worktree 私有的 gitdir（linked worktree 是 <主仓>/.git/worktrees/<name>）。"""
    return Path(git_out(repo, "rev-parse", "--path-format=absolute",
                        "--git-dir")).resolve()


def git_common_dir(repo: Path) -> Path:
    """跨 worktree 共享的对象库目录。两个 worktree 此值相同 ⇔ 对象库共享。"""
    return Path(git_out(repo, "rev-parse", "--path-format=absolute",
                        "--git-common-dir")).resolve()


def branch_exists(repo: Path, name: str) -> bool:
    return git(repo, "rev-parse", "--verify", "--quiet",
               f"refs/heads/{name}", check=False).returncode == 0


def branch_in_use(repo: Path, name: str) -> Path | None:
    for e in worktree_entries(repo):
        if e["branch"] == name:
            return e["path"]
    return None


# ---------------------------------------------------------------- 内容读取


def parse_gitmodules(worktree: Path):
    """手写解析 <worktree>/.gitmodules，返回 [(name, relpath)]。

    刻意不走 `git -C <dir> config` / `git submodule status`：当某个 submodule 目录
    尚为空时，`git -C <空目录>` 会**静默向上逃逸到父仓执行**（`git -C libs/a
    rev-parse --git-dir` 解析成 `super/.git`），报出语义无关的错误。直接读文件
    没有 git-dir 发现过程，不会撞这个陷阱。
    """
    f = worktree / ".gitmodules"
    if not f.is_file():
        return []  # 无 submodule 的仓：直接跳过全部 submodule 逻辑
    name, path, out = None, None, []
    sec = re.compile(r'^\[submodule\s+"(.*)"\]\s*$')
    kv = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*(.*?)\s*$")
    for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        m = sec.match(line)
        if m:
            if name is not None and path:
                out.append((name, path))
            name, path = m.group(1), None
            continue
        m = kv.match(raw)
        if m and m.group(1).lower() == "path" and name is not None:
            path = m.group(2)
    if name is not None and path:
        out.append((name, path))
    return out


def gitlink_sha(repo: Path, rel: str) -> str:
    """读 repo 的 **index** 里 rel 那条 gitlink（160000 条目）的 40 位 SHA。

    「问哪个仓」决定了拿到哪个版本：不同 worktree / 不同分支记录的 gitlink 不同。
    本工具一律问**源 worktree 对应层**要（见 wt_supply.py 顶部「base ref 取哪里」）。
    """
    proc = git(repo, "rev-parse", f":{rel}", check=False)
    sha = proc.stdout.strip()
    if proc.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise Fail(
            f"读不到 {repo} index 里 {rel} 的 gitlink",
            cmd=f"git -C {repo} rev-parse :{rel}",
            stderr=proc.stderr,
            hint=f"确认 {rel} 在该 worktree 所在分支的 index 里是一条 gitlink（160000 条目）",
        )
    return sha


def read_dotgit_file(dotgit: Path) -> Path | None:
    txt = dotgit.read_text(encoding="utf-8", errors="replace").strip()
    m = re.match(r"^gitdir:\s*(.+)$", txt)
    if not m:
        return None
    p = Path(m.group(1))
    if not p.is_absolute():
        p = (dotgit.parent / p)
    return p


def commit_line(repo: Path, sha: str) -> str:
    """`<短hash> <日期> <subject>` 一行。gitlink 红线要求的三件套就是这个格式。"""
    proc = git(repo, "show", "-s", "--date=short",
               "--format=%h %ad %s", sha, check=False)
    return proc.stdout.strip() or f"{sha[:12]} (对象不在 {repo} 的对象库里)"


# ---------------------------------------------------------------- 干净度判定


def dirty_lines(repo: Path) -> list[str]:
    """`git status --porcelain -uall` 的行，但**剔除登记在案的嵌套 worktree 目录**。

    为什么必须剔除：本工具刻意把目标 worktree 建在
    `<源>/.keeper/<交付id>/debug/<id>/worktree/`（理由见 wt_supply.py `cmd_init`），
    它在源 worktree 眼里就是一个未跟踪目录。task-keeper 现行约定（v5，2026-08-06
    用户拍板「不要公开」）是 `.gitignore` 里有整树规则 `.keeper/`（历史上 v4 期间是
    精确规则 `.keeper/**/worktree/`，判据 6 同样成立），此时 `git status` 本来就不会
    列出它——**这段剔除是那条规则缺失时的兜底**：缺行时 `git status` 恒输出
    `?? .keeper/<交付id>/debug/<id>/worktree/`，不剔除的话源 worktree 永远「不干净」，
    merge-back 的前置校验会 100% 误拦。剔除逻辑靠 `worktree_entries()` 现算的登记路径
    做匹配，不写死具体层级——v3→v4→v5 落点与 gitignore 形态几经变化，这段逻辑一行
    没改，只有下面举例的路径字面量需要同步。

    **v4 期间的特殊情况（v5 已不再成立）**：v4 队列文本本身入库，所以
    `.keeper/<交付id>/debug/*/issue.md` 这类文件的修改会**正常出现在这里**，且不该
    被剔除——它们是真实的工作区改动。源侧因此改用 `source_dirty_check()` 的收窄判据
    （只有与本次合并路径相交才拦）；目标侧仍走本函数的全树严格检查，靠「fixer
    worktree 里不写 index.md」（`queue_snapshot.in_fixer_worktree`）来保证那份副本
    不会被 hook 改脏。**v5 起 `.keeper/` 整树未跟踪，`issue.md` 等文件的修改不会再
    出现在 `git status` 里**，`source_dirty_check()` 的收窄判据因此在 v5 下大多数
    情况已无实际命中面（对 v4 存量仓仍然有效），但两套判据都未删除，逻辑保持不变。

    为什么用 `-uall` 而不是默认的 `-unormal`：默认模式会把未跟踪目录**折叠**成
    `?? .keeper/`（实测，折叠到未跟踪链的最上层目录），一旦折叠就无法区分「折叠掉的
    只有那个 worktree」还是「里面另有真的未跟踪文件」，剔除就变成掩盖。`-uall` 逐条
    列出、且不会下钻进嵌套 git 仓库（实测只出一行 `?? <落点>/`），可以精确剔除而
    不掩盖任何东西。
    """
    # 不走 git_out：它对整段 stdout 做 .strip()，会吃掉第一行开头的空格——
    # porcelain 状态码里 " M" / " D" 这类"未 staged"码正是以空格开头，一旦被吃掉，
    # 第一行的 code/path 切片全部错位（实测：路径首字符被吞）。只 rstrip 换行即可。
    out = git(repo, "status", "--porcelain", "-uall").stdout.rstrip("\n")
    if not out:
        return []
    root = Path(repo).resolve()
    nested = set()
    for e in worktree_entries(repo):
        try:
            rel = e["path"].relative_to(root)
        except ValueError:
            continue
        if str(rel) not in (".", ""):
            nested.add(str(rel))
    keep = []
    for line in out.splitlines():
        code, path = line[:2], line[3:]
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]  # core.quotepath 打开时的引号形态
        if code == "??" and path.rstrip("/") in nested:
            continue
        keep.append(line)
    return keep


def staged_paths(repo: Path) -> list[str]:
    out = git_out(repo, "diff", "--cached", "--name-only")
    return [l for l in out.splitlines() if l]


def dirty_paths(repo: Path) -> list[str]:
    """从 `dirty_lines()` 的输出里抽取纯路径（去掉状态码与引号），供路径相交判定用。

    rename 条目形如 `R  old -> new`：old/new 任一边与本次合并路径相交，都足以让
    `git merge` 报 local changes would be overwritten，故两边都纳入结果。
    """
    paths = []
    for line in dirty_lines(repo):
        p = line[3:]
        if p.startswith('"') and p.endswith('"'):
            p = p[1:-1]
        if " -> " in p:
            a, b = p.split(" -> ", 1)
            paths.extend([a, b])
        else:
            paths.append(p)
    return paths


def unmerged_paths(repo: Path) -> list[str]:
    out = git_out(repo, "diff", "--name-only", "--diff-filter=U")
    return [l for l in out.splitlines() if l]


def changed_paths(repo: Path, span: str) -> list[str]:
    """`git diff --name-only <span>` 的行：本次 merge 实际会触碰的路径集合。

    span 形如 `A..B`。merge-back 用它判定"源侧未 staged 的脏文件是否与本次合并
    路径相交"——不相交则无害（`git commit` 不带 pathspec 才会牵连未跟踪/未暂存内容，
    未 staged 的改动本就不会被 commit 带走），相交才是 `git merge` 自己也会因
    local changes would be overwritten 拒绝的真实冲突。
    """
    out = git_out(repo, "diff", "--name-only", span)
    return [l for l in out.splitlines() if l]


def rev_count(repo: Path, span: str) -> int:
    """`git rev-list --count <span>`。span 形如 `A..B`。读不到就当 0。"""
    proc = git(repo, "rev-list", "--count", span, check=False)
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return 0
