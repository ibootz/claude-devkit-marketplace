#!/usr/bin/env python3
"""Debug 队列实时快照（UserPromptSubmit）· schema v4

## v2 → v3 改了什么，以及为什么（源自真实项目实测，判据设计的通用教训）

v2 的注入体有五个分组：在飞 / 待调度 / 已 triage 待登记 / 待 triage / 文件冲突。
实测下来其中三个是**恒空或恒假**的：

  · 「在飞 N/4」按 `status == "in_progress"` 统计。而在一个跑了 22 条 issue、
    7 次提交的真实项目里，`git log -S'status: in_progress'` 零命中——这个值
    从未被写入过一次。于是注入体每轮稳定输出「在飞 0/4」，哪怕当时真有两个
    triage agent 在跑。假信息比没信息更糟。
  · 「文件冲突」由 in_flight issue 的 `affected_files` 求并集算出。in_flight
    恒空 → 冲突集恒空 → 「派发前查文件占用」在机械层面从来没有依据。
  · 「待调度」要求 `stage == "scheduled"`，而 `→ scheduled` 的准入条件在
    schema 里压根没定义过，AI 不知道何时该推进，于是 issue 卡在 `triaged`
    再也不动（实测有 issue 卡了一整个会话直到结束）。

三者的共同病根是**拿 AI 手写的业务字段当机械判据**。v3 把这些状态挪到 AI 写
不错的地方：

  · 「谁在修哪条」→ `git worktree list` 的路径里含 `DBG-\\d+` 即在飞。
    一 issue 一 worktree 是物理隔离，目录存在性不可能写错，也不需要谁去登记。
  · 「文件冲突」→ 不存在了。worktree 各自独立工作区，两个 fixer 改同一个文件
    也互不可见，冲突推迟到合并时由 git 处理。整套互斥调度算法随之删除。
  · 「改了什么 / 修完没有」→ `git diff --stat` 与 `git merge-base --is-ancestor`，
    只在合并前对账时需要，不进每轮注入。

落盘状态因此只剩 `open` / `done` 两个，在 `<DBG-NNN>/issue.md` 的 frontmatter 里。

## v3 → v4：队列改为跟随交付 worktree

路径从 `<某个根>/.keeper/debug/issues/DBG-NNN.md` 变成
`<worktree 根>/.keeper/<交付id>/debug/DBG-NNN/issue.md`，且**文本入库**。
本文件的三处相应改动：根解析委托给 `keeper_paths`（不再自带一份）、
`gitignore_*` 语义反转（整树忽略从「期望」变成「要告警的错误配置」）、
`next_id` 纳入 fixer worktree 保护范围。成因见 `keeper_paths.py` 与
`queue_files.py` 的模块头。

## 零成本保证不变

本 hook 随插件装到所有项目、每轮触发。当前 worktree 根下没有
`.keeper/<交付id>/debug/` 就直接 return，stdout 全空，等价于本 hook 不存在。
唯一例外：项目里有 v3（`.keeper/debug/issues/`）或 v2（`.debug/issues/`）布局的
旧队列时，注入一句迁移提示——否则用户看到的只是「队列消失」且无从归因。
判据是目录存在性，纯机械。

**2026-08-03 起这条保证的判据边界收窄到 `.keeper/` 顶层**：`.keeper/<交付id>/debug/`
缺失但 `.keeper/` 顶层已存在时，`find_queue` 会自动补建它（连同 `chore/` 一起），
不再直接 return——真正维持「未启用项目零成本」的判据变成 `.keeper/` 顶层是否
存在，细节见下方 `find_queue` docstring「为什么自动补建」。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from queue_files import DEBUG, load_all, split_by_status, write_index, next_id
except Exception:                                    # 依赖缺失时静默退出，绝不阻断
    load_all = None
    DEBUG = None

try:
    import keeper_paths
except Exception:
    keeper_paths = None

MAX_ASCEND = 30         # 向上查找 .keeper/ 的最大层数（防符号链接环）
MAX_PER_GROUP = 8       # 注入体里每个分组最多列出的 issue 数
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
LEGACY_QUEUE = ".debug"  # radnove-core 时代的旧队列目录，仅用于迁移提示

# 会把整棵队列吞掉的 `.keeper` 忽略写法。**v4 起这是要告警的错误配置，不是期望配置**
# ——语义相对 v3 完全反转：v3 队列是纯本机产物、整树 gitignore 才对；v4 队列文本入库
# （否则 Claude Code 的影子 grep 带 `--ignore-files`，搜队列静默零命中而不报错）。
# strip 后整行相等才算命中，不解析通配符语义。
GITIGNORE_SWALLOW = {".keeper/", ".keeper", "/.keeper/", "/.keeper", ".keeper/**"}

# v4 期望的四条规则（判据 6）。用 `**` 而非 `*/debug/*/`——后者在 `_main` 兜底桶
# 那一层少一级会漏网（实测）。第四条（2026-08-05 补）排除的是
# `.keeper-instance.json`——它是会话级运行时状态，跨会话即失效（见
# `keeper_paths.py` 模块头「`.keeper-instance.json` 的会话隔离」），入库既产生
# 噪音 diff（每派一个新 keeper 实例就一次），也会把已失效的 name 同步给协作者。
GITIGNORE_WANT = (
    ".keeper/**/worktree/",
    ".keeper/**/*.png",
    ".keeper/**/*.jpg",
    ".keeper/**/.keeper-instance.json",
)

# bug 报告特征词。命中即追加 register-first 提醒。
# 只在 `.keeper/` 顶层已存在（= 该项目显式 opt-in）时生效，避免污染其他项目；
# debug 子目录本身由 find_queue 自动补建，不再是 opt-in 判据。
BUG_HINTS = re.compile(
    r"报个?\s*bug|有个问题|报错|白屏|崩了|崩溃|挂了|不生效|没反应|点了没|"
    r"显示不对|数据不对|对不上|异常|失败了|错位|乱码|卡住|加载不出|"
    r"这个有问题|修一下|修复一下",
    re.IGNORECASE,
)


def sh(args, cwd=None):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def wt_id_re():
    return re.compile(r"(%s-\d+)" % re.escape(DEBUG.prefix))


# ────────────────────────── 定位 ──────────────────────────

def find_queue(start, spec):
    """定位本 worktree 的队列目录；`.keeper/` 已存在但该队列子目录缺失时**自动补建**。

    **v4 起委托给 `keeper_paths`，本文件不再自带一份根解析**。v3 这里是「向上找
    `<dir_name>/<item_dir>/`、遇 `.git` 停」，而 linked worktree 根自己就有一个
    `.git` 文件，循环第一轮就返回 None——aisdlc 交付跑在
    `.sdlc/worktrees/D-NNN-<slug>/` 里时队列恒为空，冷启动又直接 mkdir，于是长出
    第二份 `.keeper/`。完整成因见 `keeper_paths.py` 模块头。

    同一份判据当时有三份实现（本文件、`keeper_routing.py`、`archive_done.py`），
    且第三份不检查 `.git`、会一路走到文件系统根。合并成一份就是为了消掉这个。

    ## 为什么自动补建（2026-08-03 加，修一个自锁死循环）

    v4 这里是 `return qd if qd and os.path.isdir(qd) else None`——队列子目录不存在
    就零输出。**这让缺失的那条队列永远无法被启用**，实测证据：某交付的
    `.keeper/<did>/` 下只有 `debug/` 与 `decisions/`，`chore/` 从未被创建，全仓
    零个 `CHR-*`，而 `debug/` 有 15 open + 69 archived。死循环是：

        chore/ 不存在 → 本函数返回 None → 快照与「⚠ 本轮疑似杂务」提醒零输出
        → 主会话没有任何机械信号提示它转发 → 杂务被就地做掉 → chore-keeper
        从未被 `Agent` 真正派出 → 它冷启动里那句 mkdir 永无机会执行 → 回到第一步

    补建的判据是**纯 `isdir`、不猜语义**：`keeper_paths.queue_dir()` 返回非 None
    已经等价于 `<worktree 根>/.keeper/` 存在（见 `keeper_paths.find_keeper_root`
    的 opt-in 语义），所以**未启用 task-keeper 的项目不会被凭空造目录**，零成本
    保证不变。建出来是空目录，git 不跟踪空目录，因此不产生任何 `git diff`——这是
    这个副作用可以接受的前提。本函数所在的调用路径本来就带写副作用
    （`write_back=True` 会写 `.keeper-active`），补建不引入新性质。

    **fixer worktree 里不补建**，与下方 `write_index` 同一条「fixer 侧只读不写」
    原则：v4 起 `keeper_paths` 会从 fixer 回溯到 delivery worktree，在那边建目录
    等于让 fixer 的 hook 去改 delivery 的工作区。此时行为与改动前一致（返回
    None、零输出），没有退化。

    **补建时 debug 与 chore 一起建，不只建自己那个**——见
    `_sibling_queue_names` 的 docstring，只建自己会在补建当轮重复注入待拍板计数。
    """
    if keeper_paths is None:
        return _legacy_find_queue(start, spec)
    qd = keeper_paths.queue_dir(start, spec, write_back=True)
    if not qd:
        return None                      # `.keeper/` 不存在 = 项目未 opt-in
    if os.path.isdir(qd):
        return qd
    if in_fixer_worktree(start):
        return None                      # fixer 侧只读不写
    delivery_root = os.path.dirname(qd)
    for name in _sibling_queue_names():
        try:
            os.makedirs(os.path.join(delivery_root, name), exist_ok=True)
        except Exception:
            pass                         # 只读挂载等场景：静默降级
    return qd if os.path.isdir(qd) else None


def _sibling_queue_names():
    """补建时要一起建的队列子目录名（`debug` 与 `chore`）。

    **为什么两个一起建**：`plugin.json` 的 UserPromptSubmit 里 debug 快照**先于**
    chore 快照执行，而 debug 侧「是否代为注入待拍板计数」的判据是
    `os.path.isdir(<交付>/chore)`（见本文件 `render_injection` 之后那段）。若补建
    时只建自己那个，debug 那轮跑完时 `chore/` 仍不存在 → debug 判 chore 未启用、
    代为注入一次 → 紧随其后的 chore 快照发现自己目录被建好了、又注入一次，同一轮
    重复两行。两个一起建，debug 快照跑完时 `chore/` 已在，那个判据自然归位。

    名字从 `QueueSpec.dir_name` 取而不是写字面量——它的信源是 `queue_files.py`，
    v3→v4 改过一次语义（v3 是 `.keeper/debug` 相对路径，v4 只是子目录名）。顶层
    import 失败（`DEBUG is None`）时退回字面量：补建成功比取值精确更重要，少建一个
    目录会让那条队列继续困在死循环里。
    """
    try:
        from queue_files import CHORE
        names = [DEBUG.dir_name, CHORE.dir_name]
    except Exception:
        names = ["debug", "chore"]
    return [n for n in names if n]


def _legacy_find_queue(start, spec):
    """`keeper_paths` 不可用时的兜底：v3 的向上找。仅在 import 失败时走到。"""
    try:
        cur = Path(start).resolve()
    except Exception:
        return None
    for _ in range(MAX_ASCEND):
        cand = cur / ".keeper" / spec.dir_name
        try:
            if cand.is_dir():
                return str(cand)
            if (cur / ".git").exists():
                return None
        except OSError:
            return None
        if cur.parent == cur:
            return None
        cur = cur.parent
    return None


def sibling_queue_dirs(queue_dir):
    """`.keeper/*/debug` 全部交付目录，供 `next_id` 取全局最大值（判据 4）。

    只扫当前交付会让 D-002 的第一条 issue 又叫 DBG-001；跨交付 reopen 是
    `skills/tk-debug/SKILL.md` 明文规定的常规路径，重号会让「DBG-078」同时指向
    两条不同的 bug。
    """
    if keeper_paths is None:
        return []
    keeper_root = os.path.dirname(os.path.dirname(os.path.abspath(queue_dir)))
    try:
        return keeper_paths.all_queue_dirs(keeper_root, DEBUG)
    except Exception:
        return []


def legacy_hints(cwd):
    """没找到 v4 队列时的迁移提示。返回 0 或 1 条文案，不做任何迁移动作。

    两类旧布局都要认，否则用户看到的只是「队列消失」且无从归因：
      · v3：`.keeper/debug/issues/`（本插件 1.x）
      · v2：`.debug/issues/`（radnove-core 时代）
    """
    root = keeper_paths.find_worktree_root(cwd) if keeper_paths else None
    if not root:
        root = os.path.abspath(cwd)
    v3 = os.path.join(root, ".keeper", "debug", "issues")
    if os.path.isdir(v3):
        return ["⚠ 检测到 v3 布局队列 `%s`。v4 改为一交付一目录、一条目一目录，"
                "两者路径不兼容。一次性迁移："
                "`python3 <插件>/skills/tk-debug/scripts/migrate_layout.py --dry-run` "
                "核对映射后去掉 `--dry-run` 真跑。" % v3]
    v2 = os.path.join(root, LEGACY_QUEUE, "issues")
    if os.path.isdir(v2):
        return ["⚠ 检测到旧版 debug 队列 `%s`（radnove-core 布局），task-keeper 读的是 "
                "`.keeper/<交付id>/debug/`。先按 v3 布局收拢到 `.keeper/debug/issues/`，"
                "再跑 `migrate_layout.py` 迁到 v4。" % v2]
    return []


def is_linked_worktree(cwd):
    """判断当前是否在 git 的 linked worktree（而非主工作区）里。

    判据是 `--git-dir` 与 `--git-common-dir` 是否指向同一处：worktree 的 `.git`
    是个指向主仓 `worktrees/<name>` 的文件，两者必然不同。
    """
    gd = sh(["git", "-C", cwd, "rev-parse", "--git-dir"]).strip()
    gc = sh(["git", "-C", cwd, "rev-parse", "--git-common-dir"]).strip()
    if not gd or not gc:
        return False
    try:
        return os.path.realpath(gd) != os.path.realpath(gc)
    except Exception:
        return gd != gc


def in_fixer_worktree(cwd):
    """判断当前工作区是否是「为某条 issue 开的 fixer worktree」。

    为什么要判：若每个 fixer 的 worktree 里都重算一次 index.md，几份并行修改
    会在下游被误当成各自的真身。fixer 的 worktree 里那份队列只是随分支
    checkout 出来的副本，只读不写。

    **判据是「路径里带 DBG-\\d+」而不是「是不是 linked worktree」**（2026-07-29
    修正）。旧判据只用 `is_linked_worktree()`，隐含假设「队列住在主工作区、
    worktree 一定是 fixer 开的」。该假设被交付级 worktree 打破：某些交付框架
    会把整个交付跑在一个 linked worktree 里（如 `<项目>/.sdlc/worktrees/
    D-001-xxx/`），队列**就住在里面、是唯一真身**，却因为它是 linked worktree
    而永远不刷 index.md。实测后果：index.md 停在 `open 6`，而磁盘上已经是
    `open 9`，三条新 issue（含两条 P1）完全不在索引里——而 skill 教主会话
    「查队列状态直接读 index.md」，于是给出漏条的过期答案。

    新判据下两类 worktree 各自归位：fixer 的 `.keeper/worktrees/DBG-017` 路径
    带 id → 跳过写（它那份队列是随分支 checkout 出来的副本）；交付级
    worktree 路径不带 id → 正常写（那份是真身）。

    两个条件都要满足才跳过：路径带 `DBG-\\d+` **且**确实是 linked worktree。只判
    前者会让「主工作区路径恰好含 DBG-」的仓库被误跳过。

    v4 增加一条**先于**路径判据的精确通道：`<git-dir>/wt-supply-source` 存在即
    确定是 `wt_supply.py` 建的 fixer worktree。该文件由 `record_source()` 在建
    worktree 时写入，是确定信息，不需要从路径长相去猜。路径判据保留为兜底——
    手工 `git worktree add` 出来的、或 v3 时代遗留的 worktree 没有这个标记。
    """
    if keeper_paths is not None:
        try:
            if keeper_paths._read_source_mark(cwd):
                return True
        except Exception:
            pass
    if not wt_id_re().search(str(cwd)):
        return False
    return is_linked_worktree(cwd)


def worktree_in_flight(cwd):
    """从 `git worktree list --porcelain` 派生在飞 issue。

    约定：为某条 issue 开的 worktree，路径里带它的 id（v4 落点是
    `.keeper/<交付id>/debug/DBG-017/worktree`，v3 是 `.keeper/worktrees/DBG-017`）。
    这里**不硬编码父目录**——只要路径里出现 `DBG-\\d+` 就认，落点放哪都能识别。
    v3→v4 落点整体搬家而这个函数一行没改，就是这条判据挣来的。

    返回 {DBG-id: worktree 绝对路径}。
    """
    idre = wt_id_re()
    out = sh(["git", "-C", cwd, "worktree", "list", "--porcelain"])
    found = {}
    for line in out.splitlines():
        if not line.startswith("worktree "):
            continue
        path = line[len("worktree "):].strip()
        m = idre.search(os.path.basename(path)) or idre.search(path)
        if m:
            found[m.group(1)] = path
    return found


def gitignore_findings(queue_dir):
    """检查 worktree 根 `.gitignore`，返回告警文案列表（全对时返回空列表）。

    worktree 根 = 队列目录上溯三级（`<根>/.keeper/<交付id>/debug` → `<根>`）。
    **v4 比 v3 多一级**——漏改这里会把 `.keeper/` 自己当成项目根去找 `.gitignore`。

    两类问题分开报，因为改法完全不同：
      · 整树忽略（`.keeper/`）**存在** → 它会把入库的 issue 一起吞掉。而 Claude
        Code 把 `grep` 影子成自带 ugrep 且参数写死 `--ignore-files`，被 ignore 的
        文件搜起来**静默零命中、不报错**——「搜一下有没有类似 issue」会得到错误
        的「没有」。删这一行是 v4 能成立的前提。
      · 四条精确规则**缺失** → worktree 与截图会被 `git add -A` 一起提交。嵌套
        worktree 尤其糟：它会被种成幽灵 gitlink（实测 `git add -n` 报
        `warning: adding embedded git repository`），而这个场景下的宿主仓真的有
        submodule，野生 gitlink 会让 `wt_supply.merge_into` 的冲突白名单整体阻断；
        第四条（`.keeper-instance.json`）缺失则是把会话级死 name 同步进 git 历史。

    判据都是 strip 后整行相等，不解析通配符语义。只提醒不代写——v4 起冷启动也
    **不再自动追加**：两个分支各自 EOF 追加内容不同的注释即冲突，实测过。
    """
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(queue_dir))))
    gi = os.path.join(root, ".gitignore")
    try:
        with open(gi, encoding="utf-8") as f:
            lines = {line.strip() for line in f}
    except Exception:
        lines = set()
    out = []
    hit = sorted(lines & GITIGNORE_SWALLOW)
    if hit:
        out.append("⚠ `%s/.gitignore` 有整树忽略行 %s——v4 队列文本入库，这一行会把 "
                   "issue 一起吞掉，且被 ignore 的文件用 grep 搜是**静默零命中**。"
                   "请删除它，改用下面四条精确规则。" % (root, "、".join("`%s`" % h for h in hit)))
    missing = [w for w in GITIGNORE_WANT if w not in lines]
    if missing:
        out.append("⚠ `%s/.gitignore` 缺 %s——worktree 与截图会被 `git add -A` 提交进去。"
                   "请补齐并回读验证。" % (root, "、".join("`%s`" % m for m in missing)))
    return out


# ────────────────────────── 渲染 ──────────────────────────

def sort_open(items):
    """open 桶排序：优先级升序（P0 最前），无优先级的排最后，同级按 id。"""
    def key(item):
        fm = item[0]
        p = PRIORITY_ORDER.get(str(fm.get("priority") or ""), 9)
        return (p, str(fm.get("id") or ""))
    return sorted(items, key=key)


def render_injection(queue_dir, cwd):
    issues = load_all(queue_dir, DEBUG)
    op, dn, unk = split_by_status(issues)
    flight = worktree_in_flight(cwd)
    open_ids = {str(fm.get("id")) for fm, _b, _p in op}

    lines = []

    if op:
        parts = []
        for fm, _b, _p in sort_open(op)[:MAX_PER_GROUP]:
            iid = str(fm.get("id"))
            tag = iid
            if fm.get("priority"):
                tag += "(%s)" % fm["priority"]
            if iid in flight:
                tag += "⚙在飞"
            parts.append(tag)
        more = " +%d" % (len(op) - MAX_PER_GROUP) if len(op) > MAX_PER_GROUP else ""
        lines.append("open %d: %s%s" % (len(op), " ".join(parts), more))
    else:
        lines.append("open 0（队列已清空）")

    # 在飞里出现了 open 桶之外的 id：worktree 还在，但 issue 已标 done——
    # 多半是修完忘了删 worktree。不提示的话 worktree 会越积越多，
    # 且下次 grep 到这个陈旧目录还会以为有人在修。
    stray = sorted(i for i in flight if i not in open_ids)
    if stray:
        lines.append("⚠ 以下 worktree 对应的 issue 已不在 open 桶，修完请清理："
                     + " ".join("%s→%s" % (i, flight[i]) for i in stray))

    if dn:
        lines.append("done %d（正文不进上下文，需回溯时再单独打开）" % len(dn))

    if unk:
        lines.append("⚠ 读不懂 %d: %s —— frontmatter 损坏或 status 不是 open/done，"
                     "这几条已从队列视图消失，先修好再继续"
                     % (len(unk), ",".join(str(fm.get("id")) for fm, _b, _p in unk)))

    # reopen 告警：反复 reopen 说明前几轮修错了方向，原样重派只会再错一次
    for fm, _b, _p in op:
        n = fm.get("reopen_count") or 0
        if isinstance(n, int) and n >= 2:
            lines.append("⚠ %s 已 reopen %d 次 → %s"
                         % (fm.get("id"), n,
                            "强制升档 opus + 先 Explore 出根因" if n == 2
                            else "停止自动重派，打回重新 triage"))

    lines += gitignore_findings(queue_dir)
    return lines


def main():
    try:
        ev = json.loads(sys.stdin.read())
    except Exception:
        ev = {}

    cwd = ev.get("cwd") or os.getcwd()
    prompt = ev.get("prompt") or ""

    if load_all is None:
        return
    found = find_queue(cwd, DEBUG)
    if found is None:
        for hint in legacy_hints(cwd):
            print(hint)
        return  # 未启用 task-keeper（无 .keeper/）或在 fixer worktree 里：零成本静默退出
    queue_dir = str(found)

    # fixer worktree 里**只读不写**：那份队列是随分支 checkout 出来的副本。
    # v4 起 keeper_paths 已能从 fixer 回溯到 delivery worktree，于是这里读到的
    # 其实是真身——但仍然不写，因为 fixer 的 hook 去改 delivery 的 index.md
    # 会在 delivery 那边凭空多出一条工作区修改（v4 index.md 入库）。
    fixer = in_fixer_worktree(cwd)
    if not fixer:
        try:
            write_index(queue_dir, DEBUG)
        except Exception:
            pass

    # 全路径只在标题给一次，正文一律用 `<队列>/...` 相对形式——注入体每轮都进
    # 上下文，重复三遍绝对路径纯属浪费（实测那条 worktree 路径单条 96 字符）。
    out = ["# Debug 队列（%s · harness 注入，非 AI 记忆）" % queue_dir, ""]
    out += render_injection(queue_dir, cwd)
    out += ["",
            "索引 `<队列>/index.md`（薄，含每条链接）。一条 bug 的全部内容"
            "（原话 / 证据 / triage / 历次修订）都在 `<队列>/<DBG-id>/issue.md` 里，"
            "**按需打开单条，不要为了看状态去读全部正文**。同目录还有该条的 "
            "receipts.md、截图与 fixer 的 worktree/。",
            "纪律：收到 bug 只登记不派发（register-first）；一 issue 一 worktree "
            "物理隔离并行；合并前用 `git diff --stat` 与 receipts 申报清单对账。"]

    # 待拍板计数兜底：正常由 chore 快照注入；chore 未启用（chore 目录不存在）时
    # 这里代注。两边判据是同一个目录的存在性，不会重复注入。**自动补建后 chore
    # 目录恒存在**，这条兜底分支实际只在 fixer worktree（find_queue 在那里不补建）
    # 或补建失败（如只读挂载）时才会走到，见 `find_queue` 与 `_sibling_queue_names`
    # 的 docstring。
    # 注意 v4 的层级：queue_dir = <keeper_root>/<交付id>/debug，decisions 与 chore
    # 都是它的**兄弟**，所以 delivery_root 只上溯一级，keeper_root 上溯两级。
    try:
        from queue_files import CHORE
        from decision_inbox import summary_line
        delivery_root = os.path.dirname(queue_dir)
        if not os.path.isdir(os.path.join(delivery_root, CHORE.dir_name)):
            dline = summary_line(delivery_root)
            if dline:
                out += ["", dline]
    except Exception:
        pass

    if BUG_HINTS.search(prompt):
        # 直接把下一个可用 id 算出来给它——AI 自己扫目录取最大值再 +1 是白费一次
        # 工具调用，而且它可能把 done 的条目漏掉导致 id 重用。
        #
        # **fixer worktree 里不给这个提示**：v3 只保护了 write_index，next_id 照算
        # 不误，而 fixer 里那份队列是陈旧副本，算出来的编号必然偏小 → 两条不同
        # issue 抢同一个 id。v4 虽已能回溯到真身，但 fixer 的职责是修一条 bug、
        # 不是登记新 bug，这里静默省掉比给个可能过期的号更安全。
        if fixer:
            nid = None
        else:
            try:
                nid = next_id(queue_dir, DEBUG, sibling_dirs=sibling_queue_dirs(queue_dir))
            except Exception:
                nid = "<下一个 DBG-id>"
        if nid:
            out += ["",
                    "⚠ 本轮疑似 bug 报告：先建 `%s/%s/issue.md`"
                    "（frontmatter 写 `status: open`，正文「用户原话」章节逐字照抄、"
                    "禁止改写），回「已登记 + 队列快照」，**不要直接派 subagent 修**。"
                    % (queue_dir, nid)]

    print("\n".join(out))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 任何异常都不得阻断用户 prompt 提交
