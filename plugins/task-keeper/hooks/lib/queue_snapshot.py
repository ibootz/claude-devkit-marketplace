#!/usr/bin/env python3
"""Debug 队列实时快照（UserPromptSubmit）· schema v3

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

落盘状态因此只剩 `open` / `done` 两个，在 `issues/DBG-NNN.md` 的 frontmatter 里。

## 零成本保证不变

本 hook 随插件装到所有项目、每轮触发。从 cwd 向上（到 .git 为止）找不到
`.keeper/debug/issues/` 就直接 return，stdout 全空，等价于本 hook 不存在。
唯一例外：项目里有**旧版** `.debug/issues/`（radnove-core 时代的队列目录）而
没有 `.keeper/debug/` 时，注入一句迁移提示——否则装了新版插件的用户会看到
「队列消失」且无从归因。判据是两个目录的存在性，纯机械。
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

MAX_ASCEND = 30         # 向上查找 .keeper/ 的最大层数（防符号链接环）
MAX_PER_GROUP = 8       # 注入体里每个分组最多列出的 issue 数
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
LEGACY_QUEUE = ".debug"  # radnove-core 时代的旧队列目录，仅用于迁移提示

# .gitignore 里认可的 `.keeper` 忽略写法（strip 后整行相等才算命中——
# 行存在性判据，不做通配符语义解析）
GITIGNORE_OK = {".keeper/", ".keeper", "/.keeper/", "/.keeper", ".keeper/**"}

# bug 报告特征词。命中即追加 register-first 提醒。
# 只在队列目录已存在（= 该项目显式 opt-in）时生效，避免污染其他项目。
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

def find_queue(start, dir_name, item_dir):
    """从 start 向上查找 `<dir_name>/<item_dir>/` 目录，遇到 .git（仓库根）即停。

    向上找的理由：cwd 不必然等于项目根，用户可能在子目录启动会话。
    仓库根是上界——多仓库工作区里无限向上会误命中父目录的队列，把 A 项目的
    issue 注进 B 项目的会话。

    认的是**目录**而非某个文件，冷启动入口相应是 `mkdir -p <dir_name>/<item_dir>`。
    返回队列目录（`<dir_name>` 对应的绝对路径），找不到返回 None。
    """
    try:
        cur = Path(start).resolve()
    except Exception:
        return None
    for _ in range(MAX_ASCEND):
        cand = cur.joinpath(*dir_name.split("/")) / item_dir
        try:
            if cand.is_dir():
                return cand.parent
            if (cur / ".git").exists():   # 到达仓库根仍未找到 → 本项目没有队列
                return None
        except OSError:
            return None
        if cur.parent == cur:             # 文件系统根
            return None
        cur = cur.parent
    return None


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
    """
    if not wt_id_re().search(str(cwd)):
        return False
    return is_linked_worktree(cwd)


def worktree_in_flight(cwd):
    """从 `git worktree list --porcelain` 派生在飞 issue。

    约定：为某条 issue 开的 worktree，路径里带它的 id（如
    `.keeper/worktrees/DBG-017`）。这里**不硬编码父目录**——只要路径里出现
    `DBG-\\d+` 就认，落点放哪都能识别，免得约定一变 hook 就瞎。

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


def gitignore_missing_keeper(queue_dir):
    """项目根 `.gitignore` 是否**缺** `.keeper` 忽略行（缺 → True）。

    项目根 = 队列目录的祖父目录（`<根>/.keeper/debug` → `<根>`）。
    判据是 strip 后整行相等（GITIGNORE_OK 枚举），不解析通配符语义——
    宁可对 `**/.keeper/` 这类等效写法多提醒一句，也不做猜测性放行。
    只提醒不代写：写 `.gitignore` 是 keeper 冷启动的职责，hook 不做文件写入。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(queue_dir)))
    gi = os.path.join(root, ".gitignore")
    try:
        with open(gi, encoding="utf-8") as f:
            lines = {line.strip() for line in f}
    except Exception:
        return True   # 没有 .gitignore 文件 → 当然缺
    return not (lines & GITIGNORE_OK)


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

    if gitignore_missing_keeper(queue_dir):
        lines.append("⚠ 项目 `.gitignore` 缺 `.keeper/` 行——队列产物不该入库，"
                     "请在项目根 `.gitignore` 追加一行 `.keeper/` 并回读验证。")
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
    found = find_queue(cwd, DEBUG.dir_name, DEBUG.item_dir)
    if found is None:
        # 迁移提示（R11）：装了 task-keeper 但项目里还是旧版 .debug/ 队列时，
        # 表现为「队列消失」且无从归因。只提醒一句，不做任何迁移动作。
        legacy = find_queue(cwd, LEGACY_QUEUE, "issues")
        if legacy is not None:
            print("⚠ 检测到旧版 debug 队列 `%s`（radnove-core 布局），task-keeper 读的是 "
                  "`.keeper/debug/`。一次性迁移：`mkdir -p .keeper/debug && "
                  "mv %s/* .keeper/debug/ && git rm -r --cached .debug && rm -rf .debug`，"
                  "并在 `.gitignore` 追加 `.keeper/`。" % (legacy, legacy))
        return  # 未启用 debug 队列的项目：零成本静默退出
    queue_dir = str(found)

    # 副作用：刷新索引。fixer 的 DBG-* worktree 里跳过——见 in_fixer_worktree()。
    if not in_fixer_worktree(cwd):
        try:
            write_index(queue_dir, DEBUG)
        except Exception:
            pass

    # 全路径只在标题给一次，正文一律用 `.keeper/debug/...` 相对形式——注入体每轮
    # 都进上下文，重复三遍绝对路径纯属浪费（实测那条 worktree 路径单条 96 字符）。
    out = ["# Debug 队列（%s · harness 注入，非 AI 记忆）" % queue_dir, ""]
    out += render_injection(queue_dir, cwd)
    out += ["",
            "索引 `.keeper/debug/index.md`（薄，含每条链接）。一条 bug 的全部内容"
            "（原话 / 证据 / triage / 历次修订）都在 `.keeper/debug/issues/<DBG-id>.md` "
            "里，**按需打开单条，不要为了看状态去读全部正文**。",
            "纪律：收到 bug 只登记不派发（register-first）；一 issue 一 worktree "
            "物理隔离并行；合并前用 `git diff --stat` 与 receipts 申报清单对账。"]

    # 待拍板计数兜底：正常由 chore 快照注入；chore 未启用（items 目录不存在）时
    # 这里代注。两边判据是同一个目录的存在性，不会重复注入。
    try:
        from queue_files import CHORE
        from decision_inbox import summary_line
        keeper_root = os.path.dirname(queue_dir)
        if not os.path.isdir(os.path.join(keeper_root, "chore", CHORE.item_dir)):
            dline = summary_line(keeper_root)
            if dline:
                out += ["", dline]
    except Exception:
        pass

    if BUG_HINTS.search(prompt):
        # 直接把下一个可用 id 算出来给它——AI 自己扫目录取最大值再 +1 是白费一次
        # 工具调用，而且它可能把 done 的文件漏掉导致 id 重用。
        try:
            nid = next_id(queue_dir, DEBUG)
        except Exception:
            nid = "<下一个 DBG-id>"
        out += ["",
                "⚠ 本轮疑似 bug 报告：先建 `.keeper/debug/issues/%s.md`"
                "（frontmatter 写 `status: open`，正文「用户原话」章节逐字照抄、"
                "禁止改写），回「已登记 + 队列快照」，**不要直接派 subagent 修**。"
                % nid]

    print("\n".join(out))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 任何异常都不得阻断用户 prompt 提交
