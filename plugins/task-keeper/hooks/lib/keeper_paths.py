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

2026-08-04 起 keeper 的 `name` 强制带 4 位随机短哈希；2026-08-18 又去掉了名字里的
`-keeper-` 段、并把 chore 档降到 sonnet，当前形态是 `opus-debugger-[0-9a-z]{4}` 与
`sonnet-chore-[0-9a-z]{4}`（如 `opus-debugger-4bb6`；正则判据由 `working-discipline`
插件的 `agent-dispatch.js` 校验，本文件不重复）。加短哈希的起因是旧的逐字固定名
（`opus-debug-keeper`）在「上一个实例结束、下一个又叫同名」时会撞车——`SendMessage`
的 name 寻址是 latest wins，旧实例就此失联。

**`subagent_type` 没跟着改名**，仍是 `task-keeper:debug-keeper` / `:chore-keeper`：
它是 `SubagentStart` 的 matcher 键，也是本模块按 kind 反查登记的键，跟着改会同时
断掉这两条链路，而两处都是静默失效。

但短哈希是随机的，主会话没法靠记忆或文档拼出实际 `name`，所以需要一个落盘登记点：
`PreToolUse(Agent)` 命中 keeper 类派发（`tool_input.subagent_type` 的冒号后 slug
是 `debug-keeper` 或 `chore-keeper`）时，把 `tool_input.name` 写进
`<worktree 根>/.keeper/<交付id>/.keeper-instance.json`——`debug`/`chore` 两键各自
独立、互不覆盖。主会话唤醒 keeper 之前先读这个文件取真实 `name`，读不到才首次派出。

`read_keeper_instances` / `write_keeper_instance` 是本模块提供的读写函数；判据（只认
`tool_name === "Agent"` 且 `subagent_type` 命中白名单）、异常静默降级全部在
`hooks/pre-tool-use-keeper-instance.sh` 与配套的 `hooks/lib/keeper_instance_register.py`
里，本模块只管路径与文件格式，不判断"这次调用该不该登记"。

## v7：同一档并存多个实例（2026-08-18 改）

v6 的登记是 `{"debug": {"name": ..., "ts": ..., "session_id": ...}}`——**每档一条**，
后写的覆盖先写的。那是"同一档只允许一个实例"这条旧架构的直接编码：一个 debug-keeper
独占整条队列、顺序处理所有 bug。

v7 改成一个 bug 一个实例，多个 debug-keeper 并存互不干扰，登记因此必须能装下多条：

```json
{"debug": {"instances": [
    {"name": "opus-debugger-4bb6", "ts": "...", "session_id": "...", "issue": "DBG-207"},
    {"name": "opus-debugger-91af", "ts": "...", "session_id": "...", "issue": "DBG-208"}
]}}
```

`issue` 是新增的**寻址键**：多实例下光有 name 不够——主会话手里是"DBG-207 又复现了"
这样的事实，要唤醒的是**认领了 DBG-207 的那个实例**，不是"最近派的那个"。没有 `issue`
就只能按 ts 猜最近一条，那正是并行化要消灭的串行假设。

**读侧一律走 `read_keeper_instances`（返回 `{kind: [record, ...]}`）或 `live_instances`**，
两者都吸收 v6 的单条格式（`_normalize_kind_entry` 把裸 record 包成单元素列表），所以
存量登记文件不需要迁移。**写侧一律吐 v7 格式**——不做"只有一条就退回 v6"的分支，
两种写法并存会让读侧每次都要判两回。

**淘汰是写时顺手做的**，没有独立的 GC 时机：`_prune_instances` 丢掉超过
`INSTANCE_TTL_DAYS` 的记录，再按 ts 倒序截到 `MAX_INSTANCES_PER_KIND` 条。理由是这个
文件只有写路径会被 hook 稳定触发（`PreToolUse(Agent)`），挂一个定时清理反而多一处
可失败的机制；而登记条目本身是**唤醒线索**不是台账——丢了最坏是退回"首次派发"，
这条路径已经验证安全。真正的事实来源是 `debug/DBG-*/issue.md`，不是这个文件。

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
import shutil
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


def _normalize_kind_entry(entry):
    """把某一档的登记值归一成 `[record, ...]`，吸收 v6 旧格式。

    v6 是 `{"debug": {"name": ..., "ts": ...}}`（单 record），v7 起是
    `{"debug": {"instances": [record, ...]}}`。两种都可能出现在磁盘上——升级
    插件不会重写既有队列的登记文件，所以读侧必须两种都认。

    归一到列表而不是"v7 读不到就回退读 v6"，是为了让上层只有一条代码路径：
    `for rec in entry` 对新旧格式一样成立。判据分叉留在这一个函数里，别扩散。
    """
    if isinstance(entry, dict):
        insts = entry.get("instances")
        if isinstance(insts, list):
            return [r for r in insts if isinstance(r, dict) and r.get("name")]
        # v6 单 record：有 name 就当一条实例
        if entry.get("name"):
            return [entry]
    return []


def read_keeper_instances(worktree_root, delivery_id):
    """读整份登记并归一：`{"debug": [record, ...], "chore": [...]}`。

    **返回值是每档一个列表**，v6 的单 record 格式会被自动升维成单元素列表
    （见 `_normalize_kind_entry`）。文件不存在、损坏（非 JSON）、或顶层不是
    dict，一律返回 `{}`——调用方不需要自己包一层 try/except。

    record 的字段：`name`（必有）、`ts`（写入时刻）、`session_id`（可选，见
    模块头「会话隔离」）、`issue`（可选，v7 新增，这个实例认领的队列条目 id
    如 `DBG-140`，供路由注入展示"谁在管哪条"）。
    """
    path = instance_registry_path(worktree_root, delivery_id)
    try:
        with io.open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return dict((k, _normalize_kind_entry(v)) for k, v in data.items())


def live_instances(worktree_root, delivery_id, kind, current_session_id=None):
    """某一档当前**属于本会话**的全部实例，按写入时刻从新到旧；没有则返回 `[]`。

    v7 起一条队列可以同时有多个实例在跑（一条 issue 一个 keeper），所以这里返回
    列表而不是单个 name——「唤醒哪一个」由调用方按 record 里的 `issue` 字段决定，
    不是由本函数替它挑。

    `current_session_id` 缺省（`None`）时不比较会话，返回全部登记；传了非空字符串
    时只保留 `session_id` 存在且相等的那些。这条判据同时覆盖两种"过期"：
    `session_id` 不一致（跨会话的死登记）、以及记录根本没有 `session_id` 键（会话
    隔离机制落地之前写入的旧格式）——**两种都当"无法确认属于本会话"处理，一律
    视为陈旧**，不做"没写就算通过"的宽松判断。理由见模块头「旧格式兼容口径」：
    比对失败的代价只是退回"首次派发"这条已验证安全的路径。
    """
    out = []
    for rec in read_keeper_instances(worktree_root, delivery_id).get(kind, []):
        name = rec.get("name")
        if not isinstance(name, str) or not name:
            continue
        if current_session_id:
            sid = rec.get("session_id")
            if not isinstance(sid, str) or sid != current_session_id:
                continue
        out.append(rec)
    out.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    return out


def read_keeper_instance_name(worktree_root, delivery_id, kind, current_session_id=None):
    """最近一条属于本会话的实例 name；取不到返回 `None`。

    **多实例下这个函数不足以定位该唤醒谁**——它只回答"这一档有没有活着的实例"，
    不回答"管 DBG-140 的是哪一个"。要后者用 `live_instances` 拿全表，按 `issue`
    字段自己挑。保留本函数是因为"有没有"这个问题本身仍然常用（例如冷启动判断），
    以及 v6 的调用方与回归用例还在用它。
    """
    recs = live_instances(worktree_root, delivery_id, kind, current_session_id)
    return recs[0].get("name") if recs else None


MAX_INSTANCES_PER_KIND = 30      # 同一档保留的登记条数上限（超出丢最旧的）
INSTANCE_TTL_DAYS = 14           # 超过这个天数的登记视为死records，写入时顺手清掉


def _prune_instances(records):
    """按「先剔过期、再截条数」两步收敛登记列表，返回新列表（从新到旧）。

    登记文件是 append-only 的，不收敛就会随交付周期无限增长——一个跑了两个月的
    交付会攒下几百条死 name，而它们对"该唤醒谁"零贡献（跨会话的实例早就不可达，
    见模块头「会话隔离」）。收敛放在**写入时**而不是读取时，是因为读侧有好几个
    调用点（路由注入每轮都读），在读侧收敛等于每轮都算一遍同样的结果。

    `ts` 解析不出来的记录**保留**而不是丢弃——解析失败的原因可能是格式变更或
    时区写法差异，把它当"过期"删掉会静默丢掉一个可能还活着的实例；保留的代价
    只是多占一个名额。
    """
    now = datetime.datetime.now().astimezone()
    fresh = []
    for rec in records:
        ts = rec.get("ts")
        try:
            age = (now - datetime.datetime.fromisoformat(str(ts))).days
        except Exception:
            fresh.append(rec)      # 解析不了就当它还活着，见 docstring
            continue
        if age <= INSTANCE_TTL_DAYS:
            fresh.append(rec)
    fresh.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    return fresh[:MAX_INSTANCES_PER_KIND]


def write_keeper_instance(worktree_root, delivery_id, kind, name, session_id=None,
                          issue=None):
    """把一个实例登记进 `kind`（`"debug"` / `"chore"` / `"context"`）这一档。

    **v7 起是追加而不是覆盖**：同一档可以同时有多个实例（一条 issue 一个 keeper），
    覆盖式写入会让先派出的那个从登记里消失——它并不会因此停下来，只是再也没人
    唤得到它，而它仍在写同一个队列目录，构成双写且互不知情。这正是 v6 单 record
    schema 的硬伤。

    同名重复登记按**更新**处理（不产生第二条），所以重复派发同一个 name 是幂等的。
    `issue` 是这个实例认领的队列条目 id（如 `DBG-140`），取不到就不写这个键——
    它只用于路由注入展示"谁在管哪条"，缺了不影响寻址。

    另外两档原样保留：先读旧文件、只改 `kind` 这一路，再整份写回。旧文件不存在或
    损坏时当空 dict 处理，不报错。

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
    data = read_keeper_instances(worktree_root, delivery_id)   # 已归一成 {kind: [rec]}
    record = {
        "name": name,
        "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if isinstance(session_id, str) and session_id:
        record["session_id"] = session_id
    if isinstance(issue, str) and issue.strip():
        record["issue"] = issue.strip()
    others = [r for r in data.get(kind, []) if r.get("name") != name]
    data[kind] = _prune_instances([record] + others)
    # 落盘一律用 v7 格式（每档一个 {"instances": [...]}），读侧照样吃得下 v6。
    out = dict((k, {"instances": v}) for k, v in data.items())
    tmp = path + ".tmp"
    try:
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
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


# ---------------------------------------------------------------------------
# 合并锁：多个 keeper 实例把各自 worktree 合回主仓时的互斥点
# ---------------------------------------------------------------------------
#
# 为什么需要它：v7 起同一条队列上并存多个 keeper 实例，各自持有一个 fixer worktree。
# 队列的其余环节（登记、triage、派 fixer、写 issue.md）都落在各自的 DBG 目录里，天然
# 不冲突；**只有合并回主仓这一步是共享资源**——`git merge` 会动主仓的 HEAD、index 与
# 工作区，两个实例同时合会撞出半完成的 merge 状态（`MERGE_HEAD` 存在但另一方已经在
# checkout），而这种状态没有干净的自动恢复路径，要人工介入。
#
# 为什么用 `os.mkdir` 而不是 `flock`/`O_EXCL`：本目录可能落在网络文件系统或
# 容器绑定挂载上，`flock` 在那些介质上的语义不保证；`os.mkdir` 的"目录已存在就失败"
# 是 POSIX 与 Windows 都保证的原子操作，且**锁的持有者信息可以写在目录内**——`O_EXCL`
# 建出的是空文件，要另写一份 owner 元数据，那又引入一次非原子的两步写。
#
# 为什么带超时抢占：持锁的 keeper 可能在合并中途被杀（会话结束、上下文耗尽、用户
# 中断），锁目录就留在磁盘上，此后所有实例永远拿不到锁——整条队列静默停摆，且没有
# 任何报错指向"有一把死锁"。超时抢占把这个必然发生的场景变成"最多等 MERGE_LOCK_TTL_SEC
# 就自愈"。抢占本身也是原子的：抢占者先 `os.rename` 把死锁目录挪走，rename 在同一
# 文件系统内原子，多个抢占者只有一个能成功，其余撞 FileNotFoundError 后重新竞争。

MERGE_LOCK_DIR = ".merge.lock"
MERGE_LOCK_TTL_SEC = 900         # 15 分钟。一次 merge 正常在分钟内完成，超过即视为持锁者已死


def merge_lock_path(worktree_root, delivery_id):
    return os.path.join(worktree_root, KEEPER_DIR, delivery_id, MERGE_LOCK_DIR)


def _lock_meta_path(lock_dir):
    return os.path.join(lock_dir, "owner.json")


def read_merge_lock(worktree_root, delivery_id):
    """返回当前持锁者元数据 `dict`；无人持锁返回 `None`。

    锁目录存在但 `owner.json` 读不出来（写到一半被杀、内容损坏）时返回一个只有
    `name` 为 `None` 的壳——**不返回 `None`**。这两种情况必须可区分：前者是"有锁但
    不知道是谁的"（仍然挡着别人，且会被超时抢占回收），后者是"没有锁"，混起来会让
    调用方以为可以直接合并。
    """
    lock_dir = merge_lock_path(worktree_root, delivery_id)
    if not os.path.isdir(lock_dir):
        return None
    try:
        with io.open(_lock_meta_path(lock_dir), encoding="utf-8") as f:
            meta = json.load(f)
        if isinstance(meta, dict):
            return meta
    except Exception:
        pass
    return {"name": None, "ts": None, "issue": None}


def _lock_age_sec(meta):
    """持锁时长（秒）。时间戳缺失或解析不了时返回 `None`——**不返回 0 也不返回极大值**。

    调用方据此走"无法判断年龄"的分支：既不能当成刚拿的锁（那会让一把没有时间戳的
    死锁永远抢不掉），也不能当成已超时（那会让一把正常持有但元数据写坏的锁被立刻
    抢走）。见 `acquire_merge_lock` 对 `None` 的处置。
    """
    ts = (meta or {}).get("ts")
    try:
        then = datetime.datetime.fromisoformat(str(ts))
    except Exception:
        return None
    now = datetime.datetime.now().astimezone()
    if then.tzinfo is None:
        then = then.replace(tzinfo=now.tzinfo)
    return (now - then).total_seconds()


def _write_lock_meta(lock_dir, owner, issue):
    meta = {
        "name": owner,
        "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "pid": os.getpid(),
    }
    if isinstance(issue, str) and issue.strip():
        meta["issue"] = issue.strip()
    try:
        with io.open(_lock_meta_path(lock_dir), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        pass          # 元数据写不进去不影响互斥本身——锁目录已经建出来了
    return meta


def acquire_merge_lock(worktree_root, delivery_id, owner, issue=None,
                       ttl_sec=MERGE_LOCK_TTL_SEC):
    """尝试取合并锁。返回 `(ok, info)`。

    - `(True, None)`——干净取到。
    - `(True, {"preempted": <旧持锁者元数据>})`——旧锁已超过 `ttl_sec`，抢占成功。
      调用方**应当把这件事写进 issue.md 或回执**：一次抢占意味着有个实例的合并中途
      死了，主仓可能停在半完成状态（详见下面"抢占之后要做什么"）。
    - `(False, <当前持锁者元数据>)`——有人正持锁且未超时。调用方等待后重试，不要
      绕开锁直接合并。

    `owner` 必须是调用方自己的唯一标识（keeper 的 `name`）——`release_merge_lock`
    靠它校验"这把锁还是不是我的"，传固定值或空串会让释放动作变成"谁都能删任何人的锁"。

    ## 抢占之后要做什么（调用方责任，本函数不代劳）

    抢到一把死锁**不等于**可以直接开始合并。先在主仓跑一次 `git_midstate` ——上一个
    实例可能死在 `git merge` 中途，主仓停在 `MERGE_HEAD` 存在的半完成状态。此时
    正确动作是先收拾那次未完成的合并（`git merge --abort` 或把冲突解完提交），
    再开始自己的。直接合会撞 "You have not concluded your merge"，而那个报错读起来
    像是自己的操作有问题，极易被误判成参数写错去反复重试。
    """
    lock_dir = merge_lock_path(worktree_root, delivery_id)
    try:
        os.makedirs(os.path.dirname(lock_dir), exist_ok=True)
    except Exception:
        return (False, {"name": None, "error": "keeper 目录建不出来"})

    for _ in range(2):        # 第二轮留给"抢占时被别人捷足先登"这一种重试
        try:
            os.mkdir(lock_dir)
        except FileExistsError:
            pass
        except Exception:
            return (False, {"name": None, "error": "锁目录建不出来"})
        else:
            _write_lock_meta(lock_dir, owner, issue)
            return (True, None)

        holder = read_merge_lock(worktree_root, delivery_id)
        if holder is None:
            continue          # 刚才那一瞬别人释放了，重新竞争
        if holder.get("name") == owner:
            return (True, None)      # 本来就是自己持有，重入不算失败

        age = _lock_age_sec(holder)
        if age is None or age <= ttl_sec:
            # 年龄不可知时按"仍然有效"处理：误等一会儿的代价，远小于抢走一把
            # 别人正在用的锁——后者会让两个 git merge 同时动主仓。
            return (False, holder)

        stale = lock_dir + ".stale-" + "".join(
            c for c in str(holder.get("name") or "unknown") if c.isalnum() or c in "-_"
        )
        try:
            shutil.rmtree(stale, ignore_errors=True)
            os.rename(lock_dir, stale)
        except Exception:
            continue          # 别人先抢到了，回去重新竞争
        try:
            os.mkdir(lock_dir)
        except Exception:
            continue
        _write_lock_meta(lock_dir, owner, issue)
        return (True, {"preempted": holder})

    return (False, read_merge_lock(worktree_root, delivery_id) or {"name": None})


def release_merge_lock(worktree_root, delivery_id, owner):
    """释放自己持有的合并锁。返回 `True` 表示锁已不在（本次删掉的，或本来就没有）。

    持锁者 `name` 与 `owner` 不一致时**不删、返回 `False`**——这种情况说明自己的锁
    已经被超时抢占、现在这把是别人的。此时删掉它等于把两个实例同时放进合并环节，
    正是这把锁要防的事。调用方读到 `False` 应当把"我的锁被抢占了"写进回执，而不是
    重试释放。
    """
    lock_dir = merge_lock_path(worktree_root, delivery_id)
    if not os.path.isdir(lock_dir):
        return True
    holder = read_merge_lock(worktree_root, delivery_id) or {}
    if holder.get("name") not in (owner, None):
        return False
    try:
        shutil.rmtree(lock_dir)
        return True
    except Exception:
        return False
