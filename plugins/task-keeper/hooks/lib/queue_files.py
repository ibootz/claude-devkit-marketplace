#!/usr/bin/env python3
"""一条目一目录的队列存储层（schema v4 · QueueSpec 参数化）

## 为什么从单文件改成一条目一文件（源自 debug 队列 v2 的实测教训）

v2 把 22 条 issue 塞在一个 `issues.yaml` 里，实测长到 1492 行 / 72567 字符
（平均 3.1K 字符/条，最大单条 8850 字符）。任何一次读取都要吞下全部历史，
包括 16 条已终态的。而 AI 每轮真正需要的只是「有哪几条待办」——那是索引，
不是正文。

## v4 的布局：队列跟随交付，一条目一目录

```
<worktree 根>/.keeper/<交付id>/debug/
├── index.md                派生视图。open 给一行摘要 + 链接，done 只列 id
└── DBG-NNN/
    ├── issue.md            唯一信源：frontmatter 管状态，正文管全生命周期
    ├── receipts.md         fixer 的处置记录
    ├── 01-xxx.png          截图（落盘但 gitignore，不入库）
    └── worktree/           fixer 的 git worktree（不入库）
```

v3 与 v4 的两处形态差异，改代码时最容易漏：

1. **条目是目录不是文件**。v3 是 `debug/issues/DBG-007.md`，v4 是
   `debug/DBG-007/issue.md`。动机是 v3 把 issue / receipts / attachments /
   worktree 分散在四棵平行子树里，同一条 bug 的四份东西靠文件名对齐——删一条
   要记得删四处，实际从来没删干净过。
2. **队列路径不再是常量**。v3 的 `dir_name` 是 `.keeper/debug` 这个相对路径，
   v4 的 `dir_name` 只是交付目录下的子目录名（`debug`），完整路径由
   `keeper_paths.queue_dir()` 拼成 `<worktree 根>/.keeper/<交付id>/debug`。
   动机见 `keeper_paths.py` 模块头（aisdlc 每个交付一个 linked worktree，
   v3 的「向上找 `.keeper`、遇 `.git` 停」在那里必然裂成两份队列）。

## QueueSpec：一份存储层伺候多个队列

debug（DBG-NNN，keeper 修 bug 流水线）与 chore（CHR-NNN，杂务台账）共用
本模块。差异全部收敛进 `QueueSpec`：子目录名、正文文件名、id 前缀、
frontmatter 键序、index 标题与列。**不复制第二份存储层**——next_id 归档感知、
`_broken` 标记、index 幂等这三条都是踩过坑换来的，复制一份等于给未来留两处
要同步修的坑。

## 幂等是硬要求（v4 起它又多了一层意义）

`index.md` 是状态的纯函数——同样的条目集合渲染出逐字节相同的内容，所以这里
**不写任何时间戳**，`write_index` 只在内容真变了时落盘。v3 时 `.keeper/` 整树
gitignore，幂等只是防 mtime 抖动；**v4 起 `index.md` 入库**，非幂等的渲染会在
每一轮 hook 后制造一次假 diff，把「队列真的变了吗」这个判断彻底淹掉。

## next_id 不落盘

从条目**目录名**取最大值 +1。归档功能会把 done 的条目搬进
`archive/<批次>/DBG-NNN/`，这意味着「现存目录名集合即完整 id 历史」的前提被
打破——如果 `next_id` 只看条目目录，归档之后旧编号会被当成「没用过」重新分配，
两条不同的条目共用一个 id、分别躺在两个目录里。

所以 `next_id` 必须同时扫 `archive/<批次>/<PREFIX>-NNN/`（见
`scan_archived_ids`），取并集再求 max。扫描只看目录名，不解析 frontmatter、
也不要求正文文件存在——即使某个归档条目已损坏，它的编号也仍然计入历史，
不能因为解析失败就让这个编号被回收重用。

v4 还多一层：`next_id` 接受 `sibling_dirs` 参数扫**所有交付目录**取全局最大值
（判据 4）。只扫当前交付会让 D-002 的第一条 issue 又叫 DBG-001。
"""
import io
import os
import re
from collections import namedtuple

# 一个队列的全部形态差异。字段：
#   key          队列短名（debug / chore），用于日志与测试断言
#   dir_name     **交付目录下**的队列子目录名（debug / chore）。v4 起不再是
#                `.keeper/debug` 这样的相对路径——完整路径由 keeper_paths
#                拼成 `<worktree 根>/.keeper/<交付id>/<dir_name>`
#   item_file    条目正文的文件名（issue.md / item.md）。v4 起条目是**一目录**
#                （`DBG-NNN/`）而不是一文件，正文叫这个名字，同目录还放
#                receipts.md、截图、以及 fixer 的 worktree/
#   prefix       id 前缀（DBG / CHR）
#   pad          id 数字位数（3 → DBG-001）
#   fm_order     frontmatter 允许的键与渲染顺序
#   index_title  index.md 的一级标题
#   index_cols   index.md open 表格的 (frontmatter 键, 列名) 列表
#   generated_by index.md frontmatter 的 generated_by 值
QueueSpec = namedtuple(
    "QueueSpec",
    "key dir_name item_file prefix pad fm_order index_title index_cols generated_by")

# frontmatter 里允许出现的键与渲染顺序。**只放能被机械消费的状态**——
# 长文本一律进正文章节，避免 frontmatter 重新长成第二个 issues.yaml。
DEBUG = QueueSpec(
    key="debug",
    dir_name="debug",
    item_file="issue.md",
    prefix="DBG",
    pad=3,
    fm_order=[
        "id",            # DBG-NNN，与文件名一致
        "summary",       # 一句话摘要，index.md 直接用
        "status",        # open | done  ← 只有两个，中间态由 git / 进程表现算
        "priority",      # P0 阻断 / P1 主流程 / P2 体验
        "difficulty",    # easy | medium | hard
        "type",          # bug | ux | perf | arch
        "reported_at",   # YYYY-MM-DD
        "reopen_count",  # 整数，0 表示没 reopen 过
        "external_ref",  # 外部工单号（如 TRACKER#644168），可选
    ],
    index_title="Debug 队列索引",
    index_cols=[("priority", "优先级"), ("difficulty", "难度"), ("type", "类型")],
    generated_by="task-keeper hook",
)

CHORE = QueueSpec(
    key="chore",
    dir_name="chore",
    item_file="item.md",
    prefix="CHR",
    pad=3,
    fm_order=[
        "id",              # CHR-NNN，与文件名一致
        "summary",         # 一句话摘要，index.md 直接用
        "status",          # open | done
        "kind",            # ledger 台账 / sync 沉淀同步 / cleanup 收尾 / misc
        "external_write",  # 布尔：这条杂务是否涉及外部系统写操作（写 = 必须打包过用户）
        "reported_at",     # YYYY-MM-DD
        "external_ref",    # 外部系统对象引用，可选
    ],
    index_title="Chore 队列索引",
    index_cols=[("kind", "类别"), ("external_write", "外部写")],
    generated_by="task-keeper hook",
)

STATUS_OPEN = "open"
STATUS_DONE = "done"

# v2 → v3 的 status 归一。v2 的 schema 只承认 open/in_progress/resolved，
# 但实际数据里出现的是 open(6) / fixed(14) / obsolete(2)——AI 自创了 fixed 与
# obsolete 并各用了 14 次和 2 次。v3 承认现实：除 open 之外一律是 done，
# 具体结局（fixed / obsolete / duplicate）写进正文「结局」一行，不占状态位。
STATUS_MAP = {
    "open": STATUS_OPEN,
    "in_progress": STATUS_OPEN,   # v2 定义过但历史上从未被写入过一次
    "fixed": STATUS_DONE,
    "resolved": STATUS_DONE,
    "obsolete": STATUS_DONE,
    "duplicate": STATUS_DONE,
    "wontfix": STATUS_DONE,
}

FM_SPLIT_RE = re.compile(r"^---\s*$", re.M)


def id_re(spec):
    """spec → 完整锚定的 id 正则（如 ^DBG-(\\d+)$）。"""
    return re.compile(r"^%s-(\d+)$" % re.escape(spec.prefix))


# ────────────────── 读 ──────────────────

def item_dir_path(queue_dir, iid):
    """条目目录：`<queue_dir>/DBG-007`。v4 起一个条目是**一个目录**，不是一个文件。

    同目录下还放 receipts.md、截图、以及 fixer 的 `worktree/`——把它们收在一起是
    v4 的核心动机：v3 把 issue / receipts / attachments / worktree 分散在四棵子树里，
    删一条 issue 要记得删四个地方，实际上从来没删干净过。
    """
    return os.path.join(queue_dir, iid)


def item_path(queue_dir, spec, iid):
    """条目正文：`<queue_dir>/DBG-007/issue.md`。"""
    return os.path.join(queue_dir, iid, spec.item_file)


def archive_dir(queue_dir):
    return os.path.join(queue_dir, "archive")


def parse_item_file(path):
    """读一个条目文件，返回 (frontmatter dict, body str)。

    只解析 frontmatter，正文原样返回不做任何加工——正文是给人和执行者读的，
    结构由约定保证而非解析器保证。frontmatter 用 yaml 解析（值可能含中文冒号、
    引号，手写正则会踩坑）。
    """
    try:
        import yaml
    except Exception:
        return None, None
    try:
        raw = io.open(path, encoding="utf-8").read()
    except Exception:
        return None, None
    if not raw.startswith("---"):
        return None, raw
    parts = FM_SPLIT_RE.split(raw, maxsplit=2)
    # parts = ['', '<frontmatter>', '<body>']
    if len(parts) < 3:
        return None, raw
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except Exception:
        return None, raw
    if not isinstance(fm, dict):
        return None, raw
    return fm, parts[2].lstrip("\n")


def load_all(queue_dir, spec):
    """扫 `<queue_dir>/<PREFIX>-NNN/<item_file>`，按 id 数字序返回 [(fm, body, path)]。

    坏条目不静默跳过——塞一条 `_broken` 标记进去，让 index.md 能把它显示出来。
    v2 的教训：快照的 if/elif 链把未知 status 值静默丢弃，16 条 issue 从视图里
    人间蒸发，没有任何告警。任何「读不懂」都必须可见。

    v4 多了一类坏形态：**目录名合法但正文文件缺失**（DBG-007/ 里没有 issue.md）。
    它同样标 `_broken` 而不是当作「这条不存在」——目录名已经占掉了这个编号，
    静默跳过会让 `next_id` 把它当没用过重新分配。
    """
    if not os.path.isdir(queue_dir):
        return []
    idre = id_re(spec)
    out = []
    for name in sorted(os.listdir(queue_dir)):
        if not idre.match(name):
            continue
        path = os.path.join(queue_dir, name, spec.item_file)
        if not os.path.isfile(path):
            out.append(({"id": name,
                         "_broken": "条目目录存在但缺 %s" % spec.item_file},
                        "", path))
            continue
        fm, body = parse_item_file(path)
        if fm is None:
            out.append(({"id": name, "_broken": "frontmatter 解析失败"},
                        body or "", path))
            continue
        if not fm.get("id"):
            fm = dict(fm)
            fm["id"] = name
            fm["_broken"] = "frontmatter 缺 id 字段，已按目录名回填"
        elif str(fm["id"]) != name:
            # 目录名与 frontmatter id 打架。**以目录名为准**：占住编号命名空间的
            # 是目录名（`next_id` 扫的是它、fixer 分支名 `fix/<交付id>-<目录名>`
            # 用的也是它），frontmatter 只是文本。v4 新增这条校验，是因为迁移
            # 脚本与手工搬目录都可能只改一头，而 v3 那种「一条目一文件」的形态
            # 里文件名与 id 不一致会直接暴露在 index 链接上、肉眼可见，v4 藏在
            # 目录里就看不见了。
            fm = dict(fm)
            fm["_broken"] = ("目录名 %s 与 frontmatter id %s 不一致，已按目录名为准"
                             % (name, fm["id"]))
            fm["id"] = name
        out.append((fm, body, path))

    def sort_key(item):
        m = idre.match(str(item[0].get("id", "")))
        return (0, int(m.group(1))) if m else (1, 0)

    return sorted(out, key=sort_key)


def scan_archived_ids(queue_dir, spec):
    """递归扫 `archive/<批次>/<PREFIX>-NNN/` 的**目录名**，返回 id 集合。

    刻意**不解析 frontmatter**、也不要求正文文件存在——只要目录名占了这个编号，
    它就必须计入历史。否则损坏或半搬迁的归档条目会让编号在下一次 `next_id`
    调用时被误判为「没用过」而重新分配，造成两条不同条目共用一个 id。
    """
    root = archive_dir(queue_dir)
    idre = id_re(spec)
    ids = set()
    if not os.path.isdir(root):
        return ids
    for dirpath, dirnames, _filenames in os.walk(root):
        for name in dirnames:
            if idre.match(name):
                ids.add(name)
    return ids


def next_id(queue_dir, spec, sibling_dirs=None):
    """派生下一个可用 id。`sibling_dirs` 给了就跨交付目录取全局最大值。

    id 历史来自两处并集：现存条目目录名，以及 `archive/<批次>/` 下已归档的
    条目目录名（见 `scan_archived_ids`）。done 的条目会被 `archive_done.py`
    移走，只看现存目录不足以还原完整历史。

    `sibling_dirs` 是 `keeper_paths.all_queue_dirs()` 的返回值——v4 队列按交付
    分目录后，只扫当前交付会让 D-002 的第一条 issue 又叫 DBG-001。文件路径确实
    不撞（交付 id 不同），但 fixer 分支名 `fix/<交付id>-DBG-NNN` 之外，跨交付
    reopen（`skills/tk-debug/SKILL.md` 明文规定的常规路径）会指向两条不同的
    issue。判据 4 定的是**仓库全局唯一**。
    """
    idre = id_re(spec)
    mx = 0
    scan = list(sibling_dirs) if sibling_dirs else []
    if queue_dir and queue_dir not in scan:
        scan.append(queue_dir)
    for qd in scan:
        for fm, _body, _path in load_all(qd, spec):
            m = idre.match(str(fm.get("id", "")))
            if m:
                mx = max(mx, int(m.group(1)))
        for iid in scan_archived_ids(qd, spec):
            m = idre.match(iid)
            if m:
                mx = max(mx, int(m.group(1)))
    return "%s-%0*d" % (spec.prefix, spec.pad, mx + 1)


def split_by_status(items):
    """按 status 分成 (open, done, unknown)。

    unknown 是显式的第三桶而不是被丢弃——见 load_all 的注释。
    """
    op, dn, unk = [], [], []
    for item in items:
        st = str((item[0] or {}).get("status", "")).strip()
        if item[0].get("_broken"):
            unk.append(item)
        elif st == STATUS_OPEN:
            op.append(item)
        elif st == STATUS_DONE:
            dn.append(item)
        else:
            unk.append(item)
    return op, dn, unk


# ────────────────── 写 ──────────────────

def render_frontmatter(fm, spec):
    """按 spec.fm_order 固定顺序输出，未知键排在后面按字母序——保证幂等。"""
    import yaml
    ordered = [(k, fm[k]) for k in spec.fm_order if k in fm and fm[k] is not None]
    rest = sorted(k for k in fm
                  if k not in spec.fm_order and not k.startswith("_") and fm[k] is not None)
    ordered += [(k, fm[k]) for k in rest]
    lines = ["---"]
    for k, v in ordered:
        dumped = yaml.safe_dump({k: v}, allow_unicode=True,
                               default_flow_style=False, sort_keys=False)
        lines.append(dumped.rstrip("\n"))
    lines.append("---")
    return "\n".join(lines)


def render_index(queue_dir, spec):
    """渲染 index.md。**不含任何时间戳**——见模块头「幂等是硬要求」。"""
    items = load_all(queue_dir, spec)
    op, dn, unk = split_by_status(items)
    # v4 链接指向 `DBG-007/issue.md`。v3 的模板是 `issues/DBG-007.md`，在新布局下
    # 生成的是死链——index.md 入库后死链会被一起提交，所以这里必须跟着 spec 走。
    def _link(iid):
        return "[%s](%s/%s)" % (iid, iid, spec.item_file)

    md = [
        "---",
        "schema_version: 4",
        "generated_by: %s" % spec.generated_by,
        "---",
        "",
        "# %s" % spec.index_title,
        "",
        "> 本文件是 `%s-*/%s` 各文件 frontmatter 的**派生视图**，由 task-keeper"
        % (spec.prefix, spec.item_file),
        "> 的 UserPromptSubmit hook 重算。改状态请改对应条目文件，改这里下一轮就被覆盖。",
        "> 每条的完整内容（原话 / 证据 / 处置记录 / 验证）都在它自己那个文件里——",
        "> 按需打开一条，不要为了看状态去读全部正文。",
        "",
    ]

    md += ["## open %d" % len(op), ""]
    if op:
        col_names = [name for _key, name in spec.index_cols]
        md += ["| ID | %s | 摘要 |" % " | ".join(col_names),
               "|---|%s---|" % ("---|" * len(col_names))]
        for fm, _b, _p in op:
            cells = []
            for key, _name in spec.index_cols:
                v = fm.get(key)
                cells.append("-" if v is None or v == "" else str(v))
            md.append("| %s | %s | %s |" % (
                _link(fm.get("id")),
                " | ".join(cells),
                str(fm.get("summary") or "-").replace("|", "\\|")))
        md.append("")
    else:
        md += ["_无_", ""]

    md += ["## done %d" % len(dn), ""]
    if dn:
        # done 只列 id：它们的正文不该进任何人的上下文，除非明确要回溯某一条。
        md += [" ".join(_link(fm.get("id")) for fm, _b, _p in dn), ""]
    else:
        md += ["_无_", ""]

    archived_ids = scan_archived_ids(queue_dir, spec)
    md += ["## archived %d（见 archive/）" % len(archived_ids), ""]
    if archived_ids:
        md += ["已归档 %d 条，按批次分布在 `archive/<批次>/` 下，"
               "需要回溯时直接打开对应目录。" % len(archived_ids), ""]
    else:
        md += ["_无_", ""]

    if unk:
        md += ["## ⚠ 读不懂 %d（必须处理）" % len(unk), "",
               "以下文件的 frontmatter 缺失、损坏或 `status` 不在 `open` / `done` 之内。",
               "它们**不在上面任何一桶里**，等于从队列视图中消失了——先修好再继续。", ""]
        for fm, _b, _p in unk:
            md.append("- `%s`：%s（status=%r）" % (
                fm.get("id"), fm.get("_broken") or "status 值不在枚举内",
                fm.get("status")))
        md.append("")

    return "\n".join(md).rstrip("\n") + "\n"


def write_index(queue_dir, spec):
    """只在内容真变了时才落盘——避免 mtime 抖动，也让幂等性可被测试断言。

    v4 起 `index.md` **入库**，于是「落盘」不再是无副作用的：rebase / bisect /
    merge 进行中时把工作区改脏，`rebase --continue` 与 `bisect good` 都要做
    checkout，遇到本地修改直接拒绝，用户会看到一条与队列毫无关系的 git 报错。
    所以中间态一律跳过（判据 10），返回 False 与「内容没变」同义——调用方本来
    就只用这个返回值决定要不要提示，不会因此丢信息。
    """
    try:
        import keeper_paths
        if keeper_paths.git_midstate(keeper_paths.find_worktree_root(queue_dir)):
            return False
    except Exception:
        pass   # keeper_paths 不可用时退回旧行为，不能因为守卫缺失就不写 index

    path = os.path.join(queue_dir, "index.md")
    new = render_index(queue_dir, spec)
    try:
        old = io.open(path, encoding="utf-8").read()
    except Exception:
        old = None
    if old == new:
        return False
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(new)
    return True
