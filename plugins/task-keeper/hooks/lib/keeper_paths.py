#!/usr/bin/env python3
"""队列根与交付 id 的统一解析（v4 · 一交付一目录）

## 为什么要有这个模块：三套实现各走各的

v3 有**三份**独立的「找 `.keeper` 在哪」实现，判据还不一致：

  · `keeper_routing.py` 的 `find_keeper_root`   —— 向上找，遇 `.git` 停
  · `queue_snapshot.py` 的 `find_queue`          —— 向上找，遇 `.git` 停
  · `archive_done.py`   的 `find_queue_dir`      —— 向上找，**不检查 `.git`**，
                                                    一路走到文件系统根

改前两处不会带到第三处。v4 把三份合并进本模块，其余文件一律 import。

## 「向上找 + 遇 .git 停」为什么必须废弃

**linked worktree 的根目录自己就有一个 `.git` 文件**（内容形如
`gitdir: <主仓>/.git/worktrees/<name>`）。于是当 cwd 落在任何 linked worktree 内时，
向上找的第一轮（`cur = start`）查完 `cur/.keeper` 就会在 `cur/.git` 命中并返回
`None`——**根本没有机会向上爬出这个 worktree 边界**。

后果在 aisdlc 工作流下是确定复现的（2026-08-01 现场实测）：交付跑在
`<项目>/.sdlc/worktrees/D-NNN-<slug>/` 这个 linked worktree 里，主仓那份 `.keeper/`
有 79 个 issue，而在交付 worktree 里跑 hook 得到的队列是空的。冷启动逻辑又不检测
外层是否已有队列，直接 `mkdir -p`，于是长出第二份 `.keeper/`——两份各缺一半：
主仓那份有 `debug/` 没 `worktrees/`，交付那份有 `worktrees/` 没 `debug/`。

## v4 的解析顺序（每一步都有实测依据）

1. **`git rev-parse --show-superproject-working-tree` 非空 → 递归到它。**
   cwd 在 submodule 里时，队列该归属父仓而不是 submodule。
   **不能改用 `--git-common-dir`**：实测在 submodule 内它返回
   `<主仓>/.git/modules/src/<name>`，父目录是 `.git/modules` 而不是工作区根。
   `--show-superproject-working-tree` 才正确返回 `<主仓>`。

2. **在 fixer worktree 内 → 读 `<git-dir>/wt-supply-source` 回溯到 delivery worktree。**
   fixer worktree 里那份队列是随分支 checkout 出来的**副本**，不是真身。v4 队列入库
   之后这个副本一定存在（v3 因为整树 gitignore 反而不存在），若拿它算 `next_id` 会
   得到比真身小的编号 → 两条不同 issue 抢同一个 id，而 id 复用是本插件列为
   「唯一硬风险」的那一条（见 `queue_files.py` 模块头）。
   `wt-supply-source` 由 `wt_supply.py` 的 `record_source` 在建 worktree 时写入，
   落在主仓 `.git/worktrees/<name>/` 下而非工作树内，是现成且可靠的回溯链路——
   比用路径字面量猜「我是不是 fixer」稳。

3. **`git rev-parse --show-toplevel` → 当前 worktree 根**，`.keeper/` 挂在它下面。
   注意这里要的就是「当前 worktree 根」而不是主仓根：v4 的队列**跟随交付**，
   delivery worktree 里那份就是真身。

4. **不在 git 仓库内 → 退回 v3 的「向上找 `.keeper`」兜底。** 插件不能假设宿主
   一定是 git 仓库。

## 交付 id：从 worktree 根的 basename 取，取不到用 `_main`

判据是**完整 slug**（`D-001-feat-job-sequence-model`，不是 `D-001`），与
`archive_done.py` 的 `guess_batch` 同源——两处取值不一致会导致「归档批次名与队列
目录名对不上」。

在主仓 master 上、detached HEAD、bisect 中途等「没有交付」的情形，一律落固定兜底桶
`_main`。**必须有具名兜底**：没有兜底就只能返回 None，而 hook 侧「解析不到就静默
零输出」正是本插件反复记录要避免的失败模式（假信息比没信息更糟，没信息又无从归因）。

## `.keeper-active`：解析器只认它指向的那一个交付目录

交付 G5 merge 回主仓后，`.keeper/D-001-xxx/` 就躺在 master 上了。此后任何从 master
切出的新交付 worktree 里都带着这份副本，`.keeper/*/` 会有多个匹配。若解析器「取第一个
匹配」，新 issue 会被写进**已经关闭的交付目录**；若「多匹配就返回 None」，队列静默消失。

所以引入 `.keeper/.keeper-active`：单行文本，内容是当前活跃交付目录名。冷启动写入，
交付收尾时删除。解析器**只认它**，不做任何 glob 猜测。文件不存在时按 basename 现算
并写入——这让它自愈，而不是变成一个必须人工维护的配置。
"""
import io
import os
import subprocess
from pathlib import Path

KEEPER_DIR = ".keeper"
ACTIVE_MARK = ".keeper-active"
MAIN_BUCKET = "_main"

# 交付目录名的形态。与 aisdlc 的 `.sdlc/worktrees/<slug>` 命名一致：`D-<数字>-<slug>`
# 或 `hotfix-<slug>`。不匹配的 worktree（含主仓）一律落 MAIN_BUCKET。
import re
DELIVERY_RE = re.compile(r"^(?:D-\d+-|hotfix-)")

MAX_ASCEND = 30
SOURCE_MARK = "wt-supply-source"   # 与 wt_supply.py 的同名常量保持一致


def _sh(args, cwd=None):
    """跑一条只读命令，失败返回空串。hook 里不能因为 git 不可用就炸。"""
    try:
        out = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=10)
        return out.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _git(cwd, *args):
    return _sh(["git", "-C", str(cwd)] + list(args))


def _read_source_mark(cwd):
    """当前若是 fixer worktree，返回 `wt-supply-source` 记录的 delivery 根。

    `--git-dir` 在 linked worktree 里返回 `<主仓>/.git/worktrees/<name>`，
    标记文件就落在那个目录下。主工作区里该路径不存在，自然返回 None。
    """
    gd = _git(cwd, "rev-parse", "--absolute-git-dir")
    if not gd:
        return None
    mark = os.path.join(gd, SOURCE_MARK)
    try:
        val = io.open(mark, encoding="utf-8").read().strip()
    except Exception:
        return None
    return val if val and os.path.isdir(val) else None


def _legacy_ascend(start):
    """v3 兜底：从 start 向上找 `.keeper` 目录，遇 `.git` 停。

    只在「不在任何 git 仓库内」时才会走到这里——此时不存在 worktree 边界问题，
    旧判据的缺陷不会被触发。
    """
    try:
        cur = Path(start).resolve()
    except Exception:
        return None
    for _ in range(MAX_ASCEND):
        try:
            if (cur / KEEPER_DIR).is_dir():
                return str(cur / KEEPER_DIR)
            if (cur / ".git").exists():
                return None
        except OSError:
            return None
        if cur.parent == cur:
            return None
        cur = cur.parent
    return None


def find_worktree_root(start):
    """解析「队列该挂在哪个工作区根下」。返回绝对路径，或 None（不在 git 仓库内）。

    顺序见模块头。每一步都做了实测验证，不要凭直觉调换。
    """
    try:
        cur = os.path.abspath(start)
    except Exception:
        return None

    # 1. 跳出 submodule（可能嵌套，所以循环）
    for _ in range(MAX_ASCEND):
        sup = _git(cur, "rev-parse", "--show-superproject-working-tree")
        if not sup or not os.path.isdir(sup):
            break
        cur = sup

    # 2. 在 fixer worktree 内 → 回溯到 delivery worktree
    src = _read_source_mark(cur)
    if src:
        cur = src

    # 3. 当前 worktree 根
    top = _git(cur, "rev-parse", "--show-toplevel")
    return top if top and os.path.isdir(top) else None


def resolve_delivery_id(worktree_root):
    """worktree 根 → 交付 id。不是交付 worktree 时返回 `_main`。

    取 basename 的**完整 slug**，与 archive_done.guess_batch 同源。
    """
    if not worktree_root:
        return MAIN_BUCKET
    base = os.path.basename(os.path.abspath(worktree_root))
    return base if DELIVERY_RE.match(base) else MAIN_BUCKET


def find_keeper_root(start):
    """返回 `<worktree 根>/.keeper` 的绝对路径；目录不存在时返回 None。

    「不存在就返回 None」是刻意的——它是 opt-in 判据（没建过队列的项目不该被注入
    队列内容），与 v3 语义一致，`keeper_routing.py` 的两档分流依赖它。
    """
    root = find_worktree_root(start)
    if root is None:
        return _legacy_ascend(start)
    cand = os.path.join(root, KEEPER_DIR)
    return cand if os.path.isdir(cand) else None


def active_delivery(keeper_root, worktree_root=None, write_back=True):
    """读 `.keeper/.keeper-active` 决定当前活跃交付目录名。

    文件缺失时按 worktree basename 现算，并（默认）写回，使其自愈。
    write_back=False 供只读场景（守卫、快照）使用——hook 不该有副作用。
    """
    if not keeper_root:
        return MAIN_BUCKET
    mark = os.path.join(keeper_root, ACTIVE_MARK)
    try:
        val = io.open(mark, encoding="utf-8").read().strip()
        if val:
            return val
    except Exception:
        pass
    did = resolve_delivery_id(worktree_root or os.path.dirname(keeper_root))
    if write_back:
        try:
            with io.open(mark, "w", encoding="utf-8") as f:
                f.write(did + "\n")
        except Exception:
            pass   # 只读挂载等场景下写不进去不该让 hook 失败
    return did


def queue_dir(start, spec, write_back=False):
    """一步到位：cwd + QueueSpec → 该队列的绝对目录，找不到返回 None。

    结果形如 `<worktree 根>/.keeper/<交付id>/debug`。
    """
    kr = find_keeper_root(start)
    if not kr:
        return None
    did = active_delivery(kr, write_back=write_back)
    return os.path.join(kr, did, spec.dir_name)


def all_queue_dirs(keeper_root, spec):
    """枚举 `.keeper/*/<spec.dir_name>` 全部交付目录。

    `next_id` 用它做**全局唯一**编号：只扫当前交付会让 D-002 从 DBG-001 重新开始，
    而 `fix/<id>` 分支名在 refs 命名空间里是仓库全局的，重号会让 `worktree add`
    直接 `fatal: a branch named ... already exists`。
    """
    out = []
    if not keeper_root or not os.path.isdir(keeper_root):
        return out
    try:
        names = sorted(os.listdir(keeper_root))
    except OSError:
        return out
    for name in names:
        if name.startswith("."):
            continue
        cand = os.path.join(keeper_root, name, spec.dir_name)
        if os.path.isdir(cand):
            out.append(cand)
    return out


def git_midstate(worktree_root):
    """rebase / bisect / merge 进行中返回 True——此时不该改动已跟踪的 index.md。

    队列入库后 `index.md` 是被跟踪文件，每轮重算会把工作区改脏；而 rebase 的
    `--continue`、bisect 的 `good/bad` 都要做 checkout，遇到本地修改直接拒绝。
    """
    if not worktree_root:
        return False
    gd = _git(worktree_root, "rev-parse", "--absolute-git-dir")
    if not gd:
        return False
    for name in ("rebase-merge", "rebase-apply", "BISECT_LOG", "MERGE_HEAD",
                 "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        if os.path.exists(os.path.join(gd, name)):
            return True
    return False
