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

## `.keeper-instance.json`：keeper 实例落盘登记（name 唤醒锚点）

2026-08-04 起 keeper 的 `name` 强制带 4 位随机短哈希（形态
`opus-(debug|chore)-keeper-[0-9a-z]{4}`，如 `opus-debug-keeper-4bb6`；正则判据由
`working-discipline` 插件的 `agent-dispatch.js` 校验，本文件不重复）。改这一条的
起因是旧的逐字固定名（`opus-debug-keeper`）在「上一个实例结束、下一个又叫同名」时
会撞车——`SendMessage` 的 name 寻址是 latest wins，旧实例就此失联。

但短哈希是随机的，主会话没法靠记忆或文档拼出实际 `name`，所以需要一个落盘登记点：
`PreToolUse(Agent)` 命中 keeper 类派发（`tool_input.subagent_type` 的冒号后 slug
是 `debug-keeper` 或 `chore-keeper`）时，把 `tool_input.name` 写进
`<worktree 根>/.keeper/<交付id>/.keeper-instance.json`——`debug`/`chore` 两键各自
独立、互不覆盖。主会话唤醒 keeper 之前先读这个文件取真实 `name`，读不到才首次派出。

`read_keeper_instances` / `write_keeper_instance` 是本模块提供的读写函数；判据（只认
`tool_name === "Agent"` 且 `subagent_type` 命中白名单）、异常静默降级全部在
`hooks/pre-tool-use-keeper-instance.sh` 与配套的 `hooks/lib/keeper_instance_register.py`
里，本模块只管路径与文件格式，不判断"这次调用该不该登记"。

## `.keeper-instance.json` 的会话隔离（2026-08-05 补）

登记文件落在磁盘上、**跨会话存活**，但派出去的 subagent 只活在派出它的那一次会话里。
上一版只登记 `name`，没有任何字段能区分"这条登记是不是本会话写的"——于是新会话第一次
转 bug 时，主会话读到的是**上一个会话的死 name**，`SendMessage` 报
`No agent named ... is reachable`，按"唤醒不到就重派"的错误反应，会直接又派第二个
实例，两个实例抢同一个 `.keeper/<交付id>/debug/` 的独占写权限——这正是本机制本来要
消除的失败模式，在跨会话场景下原样复活了一次。

修法是登记里多写一个 `session_id` 键（`{"debug": {"name": ..., "ts": ..., "session_id":
...}}`），取自 hook payload 的 `session_id` 字段——这是所有 hook 输入 schema 的公共
字段，`PreToolUse` 与 `UserPromptSubmit` 都有。`write_keeper_instance` 的 `session_id`
参数取不到（`None` 或空字符串）时**不写这个键**（不是写 `null`）——省一次"键存在但值
为 null"与"键不存在"的双态判断，读侧统一按"没有这个键"处理。`read_keeper_instance_name`
新增 `current_session_id` 参数：传了就要求登记的 `session_id` 与它相等才返回 `name`，
不传则维持旧行为（不比较会话，只看 name 有没有）。

**旧格式兼容口径**：登记文件里没有 `session_id` 键的记录（即本次改动落地之前写入的
存量登记），在传了 `current_session_id` 比对时**一律当作陈旧处理**——不是"没写就算
通过"。理由是"没有这个字段"和"字段值确实等于当前会话"是两种不同的确定性，前者是
"无法确认"，不能当"确认属于本会话"处理；比对失败的代价只是退回"首次派发"这条已经
验证过安全的路径，比误判成"属于本会话"继而唤醒一个早已不存在的实例代价小得多。

真正做会话比对决策的落点是 `hooks/lib/keeper_routing.py` 的 `UserPromptSubmit` 每轮
注入（它能拿到当前 `session_id`，直接把比对结果算成一句话注给主会话）；主会话自己
读不到自己的 `session_id`，没法重新做这个比对，所以决策不能留给主会话自己读文件猜。
"""
import datetime
import io
import json
import os
import subprocess
from pathlib import Path

KEEPER_DIR = ".keeper"
ACTIVE_MARK = ".keeper-active"
MAIN_BUCKET = "_main"
INSTANCE_MARK = ".keeper-instance.json"

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


def instance_registry_path(worktree_root, delivery_id):
    """`.keeper/<交付id>/.keeper-instance.json` 的绝对路径。不检查存在性、不做
    任何 IO——纯路径拼接，调用方自己决定要读还是要写。
    """
    return os.path.join(worktree_root, KEEPER_DIR, delivery_id, INSTANCE_MARK)


def read_keeper_instances(worktree_root, delivery_id):
    """读整份登记 dict：`{"debug": {"name": ..., "ts": ...}, "chore": {...}}`。

    文件不存在、损坏（非 JSON）、或顶层不是 dict，一律返回 `{}`——调用方（写入前
    的合并、注入文本要展示的 name）不需要自己包一层 try/except。
    """
    path = instance_registry_path(worktree_root, delivery_id)
    try:
        with io.open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def read_keeper_instance_name(worktree_root, delivery_id, kind, current_session_id=None):
    """只取某一档（`"debug"` / `"chore"`）当前登记的 name；取不到返回 `None`。

    `current_session_id` 缺省（`None`）时只看有没有 name，不比较会话——这是旧调用方
    （不关心会话隔离的场景）的行为，原样保留。

    传了非空字符串时，额外要求登记记录里的 `session_id` 键存在且与它相等，否则也
    返回 `None`。这一条判据同时覆盖两种"过期"：`session_id` 不一致（跨会话的死
    登记）、以及登记文件根本没有 `session_id` 键（会话隔离机制落地之前写入的旧格式）
    ——**两种都当"无法确认属于本会话"处理，一律视为陈旧**，不做"没写就算通过"的
    宽松判断。取不到的具体原因（文件不存在/损坏/kind 缺失/name 缺失/会话不匹配/
    旧格式无 session_id）调用方不需要分辨，统一按 `None` 处理、退回"首次派发"。
    """
    entry = read_keeper_instances(worktree_root, delivery_id).get(kind)
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        return None
    if current_session_id:
        entry_session_id = entry.get("session_id")
        if not isinstance(entry_session_id, str) or entry_session_id != current_session_id:
            return None
    return name


def write_keeper_instance(worktree_root, delivery_id, kind, name, session_id=None):
    """把 `kind`（`"debug"` / `"chore"`）对应的实例 name 写进登记文件，**保留另一
    个键**——先读旧文件、只覆盖 `kind` 这一路，再整份写回。旧文件不存在或损坏时
    当空 dict 处理，不报错。

    `session_id` 是这次派发所在会话的 id（取自 hook payload 的 `session_id` 字段），
    用于后续跨会话判断"这条登记还有效吗"。**取不到时（`None` 或空字符串）不写这个
    键**——不是写 `null`：省掉读侧"键存在但值为 null"与"键压根不存在"的双态判断，
    统一按"没有这个键"处理即可（见 `read_keeper_instance_name` 的旧格式兼容口径）。
    `session_id` 取不到不影响登记本身——name 照常写入，只是这条记录之后没法被会话
    比对认领，读它的调用方会一律当陈旧处理、退回首次派发，这是安全的降级方向。

    这是纯写文件动作，**不做任何拦截判断**——那是调用方
    （`hooks/lib/keeper_instance_register.py`）的职责。本函数对外的失败模式只有
    一种：写不进去就返回 `False`，不向上抛异常，因为调用方是一个不允许阻断 Agent
    派发的 `PreToolUse` hook。

    返回 `True`/`False` 只用于调用方记录用途，不代表这次 `Agent` 派发本身受影响
    ——写失败时 keeper 照常被派出，只是主会话之后唤醒它时会读到旧登记或读空，
    需要退回"首次派出"这条路径。
    """
    path = instance_registry_path(worktree_root, delivery_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        return False
    data = read_keeper_instances(worktree_root, delivery_id)
    data = dict(data) if isinstance(data, dict) else {}
    record = {
        "name": name,
        "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if isinstance(session_id, str) and session_id:
        record["session_id"] = session_id
    data[kind] = record
    tmp = path + ".tmp"
    try:
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        return False


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

    队列入库后 `index.md` 是被跟踪文件（v4 如此，v5 一度不是，**v6 起又是**），每轮
    重算会把工作区改脏；而 rebase 的
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
