#!/usr/bin/env python3
"""一条目一文件的队列存储层（schema v3 · QueueSpec 参数化）

## 为什么从单文件改成一条目一文件（源自 debug 队列 v2 的实测教训）

v2 把 22 条 issue 塞在一个 `issues.yaml` 里，实测长到 1492 行 / 72567 字符
（平均 3.1K 字符/条，最大单条 8850 字符）。任何一次读取都要吞下全部历史，
包括 16 条已终态的。而 AI 每轮真正需要的只是「有哪几条待办」——那是索引，
不是正文。

v3 的分工（以 debug 队列为例，chore 队列同构）：
  · `.keeper/debug/issues/DBG-NNN.md`  唯一信源。frontmatter 管状态，正文管
                                       全生命周期（用户原话 / 证据 / triage /
                                       修订记录 / 验证）。一条 bug 的所有内容
                                       都在这一个文件里，包括反复 reopen 的
                                       多轮记录。
  · `.keeper/debug/index.md`           派生视图。open 条目给一行摘要 + 文件
                                       链接供 AI 按需索引，done 条目只列 id。
                                       人和 AI 共用这一份。

## QueueSpec：一份存储层伺候多个队列

debug（DBG-NNN，keeper 修 bug 流水线）与 chore（CHR-NNN，杂务台账）共用
本模块。差异全部收敛进 `QueueSpec`：目录名、条目子目录名、id 前缀、
frontmatter 键序、index 标题与列。**不复制第二份存储层**——next_id 归档感知、
`_broken` 标记、index 幂等这三条都是踩过坑换来的，复制一份等于给未来留两处
要同步修的坑。

## 幂等是硬要求

`index.md` 是状态的纯函数——同样的条目集合渲染出逐字节相同的内容，所以这里
**不写任何时间戳**，`write_index` 只在内容真变了时落盘。`.keeper/` 整树在
`.gitignore` 里（队列是纯本机产物，不入库），幂等的意义不再是防假 git diff，
而是防 mtime 抖动、并让「同状态双跑输出相同」这一性质可被回归测试断言。

## next_id 不落盘

直接从 `issues/`（或 `items/`）目录里的文件名取最大值 +1。归档功能会把 done
的文件移出条目目录、按批次搬进 `archive/<批次>/<item_dir>/`，这意味着「文件名
集合即完整 id 历史」的前提被打破——如果 `next_id` 只看条目目录，归档之后旧编号
会被当成「没用过」重新分配，两条不同的条目共用一个 id、分别躺在两个目录里。

所以 `next_id` 必须同时扫 `archive/**/<item_dir>/<prefix>-*.md`（见
`scan_archived_ids`），取现存 id 与归档 id 的并集再求 max。扫描只看文件名，
不解析 frontmatter——即使某个归档文件的 frontmatter 损坏，它的编号也仍然计入
历史，不能因为解析失败就让这个编号被回收重用。
"""
import io
import os
import re
from collections import namedtuple

# 一个队列的全部形态差异。字段：
#   key          队列短名（debug / chore），用于日志与测试断言
#   dir_name     项目根下的队列目录相对路径（.keeper/debug）
#   item_dir     条目子目录名（issues / items）
#   prefix       id 前缀（DBG / CHR）
#   pad          id 数字位数（3 → DBG-001）
#   fm_order     frontmatter 允许的键与渲染顺序
#   index_title  index.md 的一级标题
#   index_cols   index.md open 表格的 (frontmatter 键, 列名) 列表
#   generated_by index.md frontmatter 的 generated_by 值
QueueSpec = namedtuple(
    "QueueSpec",
    "key dir_name item_dir prefix pad fm_order index_title index_cols generated_by")

# frontmatter 里允许出现的键与渲染顺序。**只放能被机械消费的状态**——
# 长文本一律进正文章节，避免 frontmatter 重新长成第二个 issues.yaml。
DEBUG = QueueSpec(
    key="debug",
    dir_name=".keeper/debug",
    item_dir="issues",
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
    dir_name=".keeper/chore",
    item_dir="items",
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

def items_dir(queue_dir, spec):
    return os.path.join(queue_dir, spec.item_dir)


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
    """扫条目目录，按 id 数字序返回 [(fm, body, path)]。

    坏文件（frontmatter 解析失败 / 缺 id）不静默跳过——塞一条 `_broken` 标记
    进去，让 index.md 能把它显示出来。v2 的教训：快照的 if/elif 链把未知
    status 值静默丢弃，16 条 issue 从视图里人间蒸发，没有任何告警。
    任何「读不懂」都必须可见。
    """
    d = items_dir(queue_dir, spec)
    if not os.path.isdir(d):
        return []
    idre = id_re(spec)
    out = []
    for name in os.listdir(d):
        if not name.endswith(".md"):
            continue
        path = os.path.join(d, name)
        fm, body = parse_item_file(path)
        if fm is None:
            out.append(({"id": name[:-3], "_broken": "frontmatter 解析失败"},
                        body or "", path))
            continue
        if not fm.get("id"):
            fm = dict(fm)
            fm["id"] = name[:-3]
            fm["_broken"] = "frontmatter 缺 id 字段，已按文件名回填"
        out.append((fm, body, path))

    def sort_key(item):
        m = idre.match(str(item[0].get("id", "")))
        return (0, int(m.group(1))) if m else (1, 0)

    return sorted(out, key=sort_key)


def scan_archived_ids(queue_dir, spec):
    """递归扫 `archive/**/<item_dir>/<prefix>-*.md` 的文件名，返回 id 集合。

    刻意**不解析 frontmatter**、只看文件名——即使某个归档文件的 frontmatter
    已损坏，它的 id 也必须仍然被计入历史，否则这个编号会在下一次 `next_id`
    调用时被误判为「没用过」而重新分配，造成两条不同条目共用一个 id。
    """
    root = archive_dir(queue_dir)
    idre = id_re(spec)
    ids = set()
    if not os.path.isdir(root):
        return ids
    for dirpath, _dirnames, filenames in os.walk(root):
        if os.path.basename(dirpath) != spec.item_dir:
            continue
        for name in filenames:
            if name.endswith(".md") and idre.match(name[:-3]):
                ids.add(name[:-3])
    return ids


def next_id(queue_dir, spec):
    """从文件名派生下一个可用 id。

    id 历史来自两处并集：条目目录里现存的文件名，以及
    `archive/**/<item_dir>/` 里已归档条目的文件名（见 `scan_archived_ids`）。
    done 的条目会被 `archive_done.py` 移出条目目录，所以只看现存文件已经
    不足以还原完整历史，必须把归档目录也算进来才不会重用编号。
    """
    idre = id_re(spec)
    mx = 0
    for fm, _body, _path in load_all(queue_dir, spec):
        m = idre.match(str(fm.get("id", "")))
        if m:
            mx = max(mx, int(m.group(1)))
    for iid in scan_archived_ids(queue_dir, spec):
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
    rel = "%s/" % spec.item_dir

    md = [
        "---",
        "schema_version: 3",
        "generated_by: %s" % spec.generated_by,
        "---",
        "",
        "# %s" % spec.index_title,
        "",
        "> 本文件是 `%s%s-*.md` 各文件 frontmatter 的**派生视图**，由 task-keeper"
        % (rel, spec.prefix),
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
            md.append("| [%s](%s%s.md) | %s | %s |" % (
                fm.get("id"), rel, fm.get("id"),
                " | ".join(cells),
                str(fm.get("summary") or "-").replace("|", "\\|")))
        md.append("")
    else:
        md += ["_无_", ""]

    md += ["## done %d" % len(dn), ""]
    if dn:
        # done 只列 id：它们的正文不该进任何人的上下文，除非明确要回溯某一条。
        md += [" ".join("[%s](%s%s.md)" % (fm.get("id"), rel, fm.get("id"))
                        for fm, _b, _p in dn), ""]
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
    """只在内容真变了时才落盘——避免 mtime 抖动，也让幂等性可被测试断言。"""
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
