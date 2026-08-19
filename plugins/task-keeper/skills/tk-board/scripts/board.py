#!/usr/bin/env python3
"""看板报告：把 debug / chore 队列的当前状态渲染成一张一眼能看完的 markdown 表。

**只读脚本，没有任何写副作用**——不落盘、不 mkdir、不 `git` 写操作。这一点与
`hooks/lib/queue_snapshot.py`（每轮注入用，内部会 `write_index` 并在队列子目录
缺失时自动补建）和 `skills/tk-debug/scripts/archive_done.py`（归档动作）都不同，
所以本脚本可以随便跑、跑多少次都不改变队列状态。

## 为什么不直接复用 index.md 或每轮注入的快照

三者的取舍不同，不是重复造轮子：

- `queue_files.render_index()` 出的 `index.md` 是**存档视图**：open 桶列表格、
  done 桶只列 id、列固定为 `QueueSpec.index_cols`。它回答「队列里有什么」，
  不回答「进度到哪了」——没有状态分布计数，也不区分 open 里哪些在飞、哪些卡在
  等人拍板。
- `queue_snapshot.render_injection()` 是**每轮注入视图**，有硬截断
  （`MAX_PER_GROUP = 8`），真实队列 20 条时会挤掉 12 条。它为省 token 而生，
  当看板会漏。
- 本脚本是**汇报视图**：不截断、带四态派生、带占比、带告警段。

## 四种状态怎么来的：`status` 字段只有两个值

`queue_files.py` 只承认 `open` / `done`（`STATUS_OPEN` / `STATUS_DONE`）。
v2 曾有 `in_progress`，v3 砍掉了，理由写在 `queue_snapshot.py` 模块头：**AI 手写
的业务字段当机械判据不可靠**。所以「进行中」「待拍板」这两态不存在于 frontmatter
里，只能从文件系统事实反推：

| 看板状态 | 判据 | 判据出处 |
|---|---|---|
| 已解决 | `status: done` | frontmatter |
| 待拍板 | `decisions/<未答复>.md` 的 `about:` 指向本条 | `decisions/` 与 `decisions/answers/` 的文件名差集 |
| 进行中 | 条目目录下有 `worktree/` 子目录 | 文件系统 |
| 未解决 | 以上都不是的 `status: open` | 兜底 |

**判定按上表自上而下短路**，四态互斥。两处顺序是有意的：

1. `done` 排最前，于是「已 done 但 `worktree/` 忘了删」不会被误报成进行中——
   那属于清理遗漏，单独进告警段（`queue_snapshot.py` 里叫 `stray`）。
2. 「待拍板」优先于「进行中」：一条 issue 完全可能既派了 fixer 又卡在等人答复，
   此时看板要突出的是**需要人动作**的那一面，否则它会混在一堆自动推进的条目里。

## `about:` 字段的解析是本脚本新写的

`decision_inbox.pending_decisions()` 只回答「总共几条待拍板」，全文没有任何一处
解析 `about:`——也就是说现有代码给不出「哪条 issue 在等拍板」。本脚本自己解析
（`ABOUT_RE` + `ID_RE`），并把**没写 `about:` 或写了但对不上任何条目**的待拍板
文件单列进告警段，不静默丢弃（v2 的教训：读不懂的东西静默跳过，16 条 issue 从
视图里人间蒸发）。

## 两处已知的真实数据脏点，本脚本做归一

都是 2026-08-05 在真实队列（D-001-feat-job-sequence-model，151 条 debug + 31 条
chore）里实测到的，不是假想：

- **外部工单号有两个字段名**：`external_ref: ONES#644559`（`DBG-033`）与
  `ones: 644559`（`DBG-024`）表达同一件事。只读前者会漏掉后者，故两个都读。
- **`priority` 有小写写法**：`p1`（归档里的 `DBG-039`）。`queue_snapshot.py:75`
  的 `PRIORITY_ORDER` 只认大写精确串，会把它扔进无优先级兜底桶。本脚本 upper()
  后再比。

## 用法

    python3 board.py                          # debug 队列，未归档条目
    python3 board.py --queue chore            # chore 队列
    python3 board.py --queue both             # 两个队列各出一份
    python3 board.py --all                    # 连归档条目一起列（151 条会很长）
    python3 board.py --status 待拍板,进行中    # 只看这两态
    python3 board.py --summary-width 30       # 说明列放宽到 30 字
    python3 board.py --queue-dir <根>/.keeper/D-001-xxx/debug
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "hooks", "lib"))

try:
    from queue_files import (DEBUG, CHORE, load_all, parse_item_file,
                             archive_dir, STATUS_DONE)
except Exception as e:
    sys.exit("无法导入 queue_files（应在 plugins/task-keeper/hooks/lib/）：%s" % e)

try:
    import keeper_paths
except Exception:
    keeper_paths = None

SPECS = {"debug": DEBUG, "chore": CHORE}

# 四态。顺序即判定优先级，也是表格与总览的排序权重。
S_PENDING = "待拍板"
S_FLIGHT = "进行中"
S_OPEN = "未解决"
S_DONE = "已解决"
STATE_ORDER = [S_PENDING, S_FLIGHT, S_OPEN, S_DONE]

# 说明列默认宽度（汉字数）。用户口径是「20 字左右」，超出截断加省略号。
DEFAULT_SUMMARY_WIDTH = 20

# decisions 文件头部里的归属字段。`about: DBG-146` 是真实数据里的写法；
# 允许一条 decision 关联多个条目（逗号 / 顿号 / 空格分隔），全部抽出来。
ABOUT_RE = re.compile(r"^about:\s*(.+?)\s*$", re.I | re.M)
ID_RE = re.compile(r"\b((?:DBG|CHR)-\d+)\b", re.I)

# 优先级排序权重。缺失或写法不认识的排在已知优先级之后，但**不丢弃**。
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
PRIORITY_UNKNOWN = 9


def w(s):
    """显示宽度：CJK 算 2、其余算 1。表格对齐用不上（markdown 自己排），
    这里只用于「20 字左右」的截断判据——按 unicode 码点数截会让纯 ASCII 摘要
    在 20 字符处被砍成半句。"""
    n = 0
    for ch in str(s):
        n += 2 if ord(ch) > 0x2E80 else 1
    return n


# summary 开头的状态方括号块。真实数据里大量条目的 summary 被写成
# 「【已关闭 —— 2026-08-05 用户拍板关闭，**……】导入指定负责人不校验……」这种形态——
# 状态叙述在前、问题说明在后。看板的「说明」列只有 20 字，不剥掉这个前缀就全是
# 噪音、一条也看不出讲什么，而状态本身在「状态」列里已经有了，剥掉不丢信息。
# `+` 是必要的：真实数据里有条目连着写了两块（`【已关闭 —— …】【与 DBG-105 部分
# 重叠…】导入侧…`），只剥一块会露出第二块、说明列照样看不出讲什么。
LEAD_BRACKET_RE = re.compile(r"^(?:\s*【[^】]*】\s*)+")


def strip_status_lead(s):
    """剥掉 summary 开头连续的 `【…】` 状态块。剥完为空则退回原文——宁可显示噪音，
    也不要显示一个空白单元格（那会让人以为这条 issue 没写摘要）。"""
    out = LEAD_BRACKET_RE.sub("", str(s or "")).strip()
    return out or str(s or "")


def clip(s, width):
    """截到 width 个汉字宽（width * 2 显示宽度），超出补 `…`。"""
    s = " ".join(strip_status_lead(s).split())   # 摘要里的换行会撑破表格
    limit = width * 2
    if w(s) <= limit:
        return s
    out = ""
    for ch in s:
        if w(out) + w(ch) > limit - 1:
            break
        out += ch
    return out + "…"


def cell(s):
    """markdown 表格单元格转义：`|` 会把一列劈成两列。"""
    return str(s if s not in (None, "") else "-").replace("|", "\\|")


def cell_link(iid, path):
    """编号列专用：渲染成 `[DBG-140](file:///abs/path/issue.md#1)` 可点击链接。

    与 `cell()` 分开一个函数，是因为 `cell()` 还被说明/状态等其它列复用——把
    链接逻辑塞进 `cell()` 会给那些列也套上链接。`path` 来自 `load_all()` /
    `load_archived()` 已经算好的条目正文路径（`<queue_dir>` 在 `render()` 入口
    处已用 `os.path.abspath()` 兜过一层，见 `main()`），这里再兜一次
    `os.path.abspath()` 是防御性的——不假设调用方一定传的是绝对路径。

    条目目录一旦不存在（理论上不该发生，但归档会把条目搬走、`_broken` 条目
    也可能缺正文文件），`os.path.isfile` 为假，此时优雅退化成裸编号，不抛异常
    让整张看板挂掉。
    """
    text = cell(iid)
    if not path:
        return text
    try:
        abspath = os.path.abspath(path)
    except Exception:
        return text
    if not os.path.isfile(abspath):
        return text
    return "[%s](file://%s#1)" % (text, abspath)


def pending_by_id(delivery_root):
    """扫 `decisions/` 未答复文件，返回 ({条目id: [文件名…]}, [未归属文件名…])。

    「未答复」的判据与 `decision_inbox.pending_decisions()` 一致：文件名在
    `decisions/` 里而不在 `decisions/answers/` 里。这里多做一步 `about:` 解析，
    那一步现有代码没有。
    """
    d = os.path.join(delivery_root, "decisions")
    if not os.path.isdir(d):
        return {}, []
    answers = set()
    adir = os.path.join(d, "answers")
    if os.path.isdir(adir):
        answers = {n for n in os.listdir(adir) if n.endswith(".md")}
    by_id, orphan = {}, []
    for name in sorted(os.listdir(d)):
        if not name.endswith(".md") or name in answers:
            continue
        path = os.path.join(d, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                head = f.read(2048)     # frontmatter 在头部，2K 足够
        except Exception:
            orphan.append(name)
            continue
        m = ABOUT_RE.search(head)
        ids = ID_RE.findall(m.group(1)) if m else []
        if not ids:
            orphan.append(name)
            continue
        for i in ids:
            by_id.setdefault(i.upper(), []).append(name)
    return by_id, orphan


def derive_state(fm, item_dir, pending):
    """四态派生。判定顺序见模块头那张表，短路返回。"""
    if str(fm.get("status", "")).strip() == STATUS_DONE:
        return S_DONE
    if str(fm.get("id", "")).strip().upper() in pending:
        return S_PENDING
    if os.path.isdir(os.path.join(item_dir, "worktree")):
        return S_FLIGHT
    return S_OPEN


def priority_of(fm):
    """归一大小写后返回 (排序权重, 显示值)。真实数据里出现过小写 `p1`。"""
    raw = str(fm.get("priority", "") or "").strip()
    up = raw.upper()
    return PRIORITY_ORDER.get(up, PRIORITY_UNKNOWN), (up or "")


def external_of(fm):
    """外部工单号。`external_ref` 与 `ones` 是同一语义的两种写法，都读。"""
    for key in ("external_ref", "ones"):
        v = fm.get(key)
        if v not in (None, ""):
            return str(v)
    return ""


def id_num(fm):
    m = re.search(r"(\d+)", str(fm.get("id", "")))
    return int(m.group(1)) if m else 0


def load_archived(queue_dir, spec):
    """扫 `archive/<批次>/<id>/<item_file>`。`load_all` 只看队列目录顶层，
    归档条目它一条都不返回——真实队列 151 条里有 131 条在这下面。"""
    root = archive_dir(queue_dir)
    out = []
    if not os.path.isdir(root):
        return out
    for batch in sorted(os.listdir(root)):
        bdir = os.path.join(root, batch)
        if not os.path.isdir(bdir):
            continue
        for name in sorted(os.listdir(bdir)):
            path = os.path.join(bdir, name, spec.item_file)
            if not os.path.isfile(path):
                continue
            fm, body = parse_item_file(path)
            if not isinstance(fm, dict):
                fm = {"id": name, "_broken": "frontmatter 解析失败"}
            fm.setdefault("id", name)
            out.append((fm, body, path, batch))
    return out


def render(queue_dir, spec, show_all, width, only_states):
    delivery_root = os.path.dirname(queue_dir)
    delivery_id = os.path.basename(delivery_root)
    pending, orphan = pending_by_id(delivery_root)

    rows, warn_stray, warn_unknown = [], [], []
    for fm, _body, path in load_all(queue_dir, spec):
        item_dir = os.path.dirname(path)
        state = derive_state(fm, item_dir, pending)
        st_raw = str(fm.get("status", "")).strip()
        if st_raw not in ("open", STATUS_DONE):
            warn_unknown.append("%s：status=%r 读不懂" % (fm.get("id", "?"), st_raw))
        if fm.get("_broken"):
            warn_unknown.append("%s：%s" % (fm.get("id", "?"), fm["_broken"]))
        if state == S_DONE and os.path.isdir(os.path.join(item_dir, "worktree")):
            warn_stray.append(str(fm.get("id", "?")))
        rows.append((fm, state, "", path))

    # 有 `about:` 指向、但那条最终没被标成「待拍板」的未答复 decision。成因有二：
    # 指向的条目已经 done（`derive_state` 里 done 短路在前），或 `about:` 写了一个
    # 队列里不存在的 id。两种都不能静默——前者意味着「人还欠一个答复、issue 却已
    # 收尾」，后者是脏数据。v2 的教训（读不懂的东西静默跳过、16 条 issue 人间蒸发）
    # 就是在这种地方发生的。
    marked = {str(fm.get("id", "")).strip().upper()
              for fm, st, _b, _p in rows if st == S_PENDING}
    warn_dangling = []
    for iid, files in sorted(pending.items()):
        if iid not in marked:
            warn_dangling.append("%s（%s）" % (iid, "、".join(files)))

    archived_n = 0
    for fm, _body, path, batch in load_archived(queue_dir, spec):
        archived_n += 1
        if show_all:
            rows.append((fm, S_DONE, batch, path))

    # 总览按四态计数；归档条目只有在 --all 时才进 rows，所以单列一行说明。
    counts = {s: 0 for s in STATE_ORDER}
    for fm, state, _b, _p in rows:
        counts[state] += 1
    total = sum(counts.values()) or 1

    if only_states:
        rows = [r for r in rows if r[1] in only_states]

    rows.sort(key=lambda r: (STATE_ORDER.index(r[1]), priority_of(r[0])[0], id_num(r[0])))

    L = []
    L.append("# %s 看板 · %s" % (spec.key, delivery_id))
    L.append("")
    L.append("## 进度总览")
    L.append("")
    L.append("| 状态 | 条数 | 占比 |")
    L.append("|---|---:|---:|")
    for s in STATE_ORDER:
        L.append("| %s | %d | %.0f%% |" % (s, counts[s], counts[s] * 100.0 / total))
    L.append("| **合计** | **%d** | |" % sum(counts.values()))
    L.append("")
    if archived_n and not show_all:
        L.append("> 另有已归档 %d 条（`archive/` 下，全部 `done`），未计入上表；"
                 "要看明细加 `--all`。" % archived_n)
        L.append("")

    is_debug = spec.key == "debug"
    head = ["编号", "说明", "状态", "优先级" if is_debug else "类别", "类型" if is_debug else "外部写", "外部工单"]
    if show_all:
        head.append("归档批次")
    L.append("## 条目明细（%d 条）" % len(rows))
    L.append("")
    L.append("| " + " | ".join(head) + " |")
    L.append("|" + "---|" * len(head))
    for fm, state, batch, path in rows:
        c4 = priority_of(fm)[1] if is_debug else fm.get("kind", "")
        c5 = fm.get("type", "") if is_debug else fm.get("external_write", "")
        cols = [cell_link(fm.get("id"), path), cell(clip(fm.get("summary"), width)), cell(state),
                cell(c4), cell(c5), cell(external_of(fm))]
        if show_all:
            cols.append(cell(batch))
        L.append("| " + " | ".join(cols) + " |")
    if not rows:
        L.append("| （无） | | | | | |")
    L.append("")

    warns = []
    if warn_stray:
        warns.append("**陈旧 worktree**（已 done 但 `worktree/` 没清理，归档会被它卡住）：%s"
                     % "、".join(warn_stray))
    if warn_unknown:
        warns.append("**读不懂的条目**：" + "；".join(warn_unknown))
    if warn_dangling:
        warns.append("**未答复的拍板项指向的条目不在「待拍板」态**"
                     "（该条已 done 收尾、或 `about:` 写了个不存在的 id，两种都要人看一眼）："
                     + "；".join(warn_dangling))
    if orphan:
        warns.append("**待拍板但归属不明**（`decisions/` 里未答复、`about:` 缺失或抽不出条目 id，"
                     "没算进上表任何一条）：%s" % "、".join(orphan))
    if warns:
        L.append("## 告警")
        L.append("")
        for x in warns:
            L.append("- " + x)
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="把 debug / chore 队列渲染成看板表（只读）")
    ap.add_argument("--queue", choices=["debug", "chore", "both"], default="debug")
    ap.add_argument("--queue-dir", default=None,
                    help="队列目录（如 <根>/.keeper/D-001-xxx/debug），缺省从 cwd 往上找")
    ap.add_argument("--all", action="store_true", help="连归档条目一起列进明细")
    ap.add_argument("--summary-width", type=int, default=DEFAULT_SUMMARY_WIDTH,
                    help="说明列宽度（汉字数，默认 %d）" % DEFAULT_SUMMARY_WIDTH)
    ap.add_argument("--status", default="",
                    help="只看这些状态，逗号分隔（%s）" % "/".join(STATE_ORDER))
    args = ap.parse_args()

    only = [s.strip() for s in args.status.split(",") if s.strip()]
    bad = [s for s in only if s not in STATE_ORDER]
    if bad:
        sys.exit("--status 不认识的值：%s（只能是 %s）" % ("、".join(bad), "/".join(STATE_ORDER)))

    keys = ["debug", "chore"] if args.queue == "both" else [args.queue]
    if args.queue_dir and args.queue == "both":
        sys.exit("--queue-dir 与 --queue both 不能同时用（一个目录只对应一个队列）")

    outs = []
    for key in keys:
        spec = SPECS[key]
        qd = args.queue_dir
        if not qd:
            if keeper_paths is None:
                sys.exit("无法导入 keeper_paths（应在 plugins/task-keeper/hooks/lib/）")
            qd = keeper_paths.queue_dir(os.getcwd(), spec, write_back=False)
        if not qd or not os.path.isdir(qd):
            outs.append("（找不到 %s 队列目录，用 --queue-dir 指定）" % spec.dir_name)
            continue
        outs.append(render(os.path.abspath(qd), spec, args.all,
                           args.summary_width, only))
    print("\n\n".join(outs))


if __name__ == "__main__":
    main()
