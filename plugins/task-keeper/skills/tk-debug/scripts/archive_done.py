#!/usr/bin/env python3
"""按批次把 `status: done` 的条目整目录归档到 `archive/<批次>/<id>/`。debug 与
chore 两个队列共用本脚本，用 `--queue debug|chore` 选择（默认 debug）。

## v4 起归档是「搬一个目录」而不是「搬三处文件」

v3 一条 issue 的东西分散在 `issues/DBG-007.md`、`receipts/DBG-007.md`、
`attachments/DBG-007/` 三棵平行子树里，归档要靠文件名把它们对齐后逐个搬；漏搬
一处不报错，只是那部分永远留在原地。v4 一条目一目录，归档退化成一次
`shutil.move`，这个失败模式消失了。

## 为什么要归档

条目目录与 `index.md` 会被历史上已经 done 的条目越撑越大——虽然 `index.md`
的 done 桶只列 id 不列正文，但队列目录本身仍在无限增长，每一轮 `load_all()`
都要扫过全部历史条目。归档把已收尾的条目成组搬到 `archive/<批次>/` 下，
队列目录和 `index.md` 就只装当前仍在流转的条目。

## 为什么用 shutil.move 而不是 git mv

**v6（2026-08-10 用户拍板）起队列正文与附件入库，但本脚本仍用 `shutil.move`，行为
不变。** 判据是「不依赖跟踪状态」而不是「文件入不入库」：

  · 一次归档动辄搬几十个目录，只要其中**任何一个**文件未被跟踪，`git mv` 就会在它
    上面报 `fatal: not under version control` 中途停下，留下搬了一半的状态。
  · v6 下这种混合态照样出现：keeper 刚写的新截图、刚生成的 `index.md`、以及尚未
    commit 的 `receipts.md` 都是未跟踪的，而归档时机与 commit 时机并不同步。
  · `worktree/` 永远被排除（归档前要求已清理，判据 8，但清理失败时它就在那里）。

纯文件系统搬移天然绕开这个问题。代价是 git 不会把它识别成 rename——归档后的 `git add`
表现为「旧路径删除 + 新路径新增」而不是一条 rename 记录。这个代价是明知的：rename
识别只影响 `git log --follow` 的可读性，而搬了一半的状态会让归档动作无法重跑。

（v5 期间的旧理由是「整树 gitignore、一切都是未跟踪文件」，那个前提已作废，但结论
不变——只是理由从「全都没跟踪」换成了「跟踪状态混合且不可预测」。）

## 归档前必须确认 worktree 已清理（判据 8）

`shutil.move` 一个活着的 git worktree 会让主仓 `.git/worktrees/<name>/gitdir`
指向失效路径——那个 worktree 从此既不能用也不能 `git worktree remove`，要手工
`git worktree prune` 才能收场。所以 `worktree_blocks_archive()` 用两条腿判：
条目目录下 `worktree/` 存在，**或** `git worktree list --porcelain` 里仍有登记。
任一命中就跳过该条，不搬。

## id 复用是唯一的硬风险，本脚本必须与 `hooks/lib/queue_files.py` 的
## `next_id()` / `scan_archived_ids()` 配套使用

`next_id()` 只看条目目录时，「现存目录名集合即完整 id 历史」的前提会被本脚本
打破——归档后旧编号被当成「没用过」重新分配，两条不同条目共用一个 id。
`queue_files.py` 的 `next_id()` 是归档感知的：把 `archive/<批次>/<id>/` 的
目录名也计入历史（只看目录名、不解析 frontmatter、也不要求正文存在，即使归档
条目损坏也不会导致编号被回收重用）。**不要在没有这个前置逻辑的存储层上单独
使用本脚本**。

## 自动归档（--auto）

keeper 在每次「收尾/执行窗口」结束时跑一次 `--auto`：满足任一条件才归档，
否则打印「未达阈值」直接退出——
  · done 条目 ≥ %(AUTO_DONE_THRESHOLD)s 条；
  · 最早 done 条目的 `reported_at` 距今 > %(AUTO_AGE_DAYS)s 天。
批次名固定 `auto-<YYYYMMDD>`（当天日期）。判据全是文件计数与 frontmatter
日期比较，机械可核；`reported_at` 缺失或格式不对的条目不参与年龄判据
（只影响触发时机，不影响归档正确性）。

## 用法

    python3 archive_done.py --queue-dir <根>/.keeper/D-001-feat-xxx/debug
    python3 archive_done.py --queue-dir <根>/.keeper/_main/debug --apply
    python3 archive_done.py --queue chore --auto --apply   # chore 队列自动归档
    python3 archive_done.py                                # 自动定位队列与批次名

默认 dry-run，只打印搬迁清单不动文件；`--apply` 才真正移动。
"""
import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys

AUTO_DONE_THRESHOLD = 10
AUTO_AGE_DAYS = 14

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "hooks", "lib"))

try:
    from queue_files import (DEBUG, CHORE, item_dir_path, archive_dir, load_all,
                             split_by_status, next_id)
except Exception as e:
    sys.exit("无法导入 queue_files（应在 plugins/task-keeper/hooks/lib/）：%s" % e)

try:
    import keeper_paths
except Exception:
    keeper_paths = None

SPECS = {"debug": DEBUG, "chore": CHORE}


def sh(args, cwd=None):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except Exception:
        return ""


def find_queue_dir(spec):
    """定位队列目录。**v4 起委托给 `keeper_paths`，与两个 hook 用同一份判据**。

    v3 这里是独立的第三份实现，且与另两份不一致：它**不检查 `.git`**，一路走到
    文件系统根。后果是在没有队列的项目里跑归档，会静默命中上层某个不相干项目的
    队列并对它执行搬移。
    """
    if keeper_paths is None:
        sys.exit("无法导入 keeper_paths（应在 plugins/task-keeper/hooks/lib/）")
    return keeper_paths.queue_dir(os.getcwd(), spec, write_back=False)


def guess_batch(queue_dir, explicit, auto):
    """确定归档批次名，来源必须 fail-loud 说清楚，不允许静默拼一个可能错的名字。

    优先级：
      1. 显式 `--batch` 参数
      2. `--auto` 模式固定 `auto-<YYYYMMDD>`
      3. **当前**交付 id（`keeper_paths.resolve_delivery_id`，与队列目录名同源）。
         注意取的是归档发生时所在的交付，不是队列目录名——跨交付 reopen 是常规
         路径（`skills/tk-debug/SKILL.md`），D-001 的 issue 可能在 D-002 期间才
         归档，批次要记后者才有回溯价值。兜底桶 `_main` 不算「交付」，跳到下一档
      4. 退回当前 git 分支名（清洗成安全的目录名）
      5. 都取不到就报错要求显式传 `--batch`，不猜
    """
    if explicit:
        return explicit, "显式 --batch 参数"
    if auto:
        stamp = datetime.date.today().strftime("%Y%m%d")
        return "auto-%s" % stamp, "--auto 模式固定 auto-<YYYYMMDD>"

    # `<worktree 根>/.keeper/<交付id>/<队列>` → 上溯三级
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(queue_dir))))

    if keeper_paths is not None:
        did = keeper_paths.resolve_delivery_id(keeper_paths.find_worktree_root(os.getcwd()))
        if did and did != keeper_paths.MAIN_BUCKET:
            return did, "当前交付 id（keeper_paths.resolve_delivery_id）"

    branch = sh(["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"])
    if branch and branch != "HEAD":
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-")
        if safe:
            return safe, ("不在交付 worktree 内（落 %s 桶），退回当前 git 分支名 "
                          "%r 清洗得到"
                          % (getattr(keeper_paths, "MAIN_BUCKET", "_main"), branch))

    sys.exit(
        "无法确定归档批次：既不在交付 worktree 内，也取不到当前 git 分支名"
        "（可能是 detached HEAD 或不在 git 仓库内）。请显式传 --batch <名字>。")


def parse_date(s):
    try:
        return datetime.datetime.strptime(str(s).strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def auto_should_archive(done_items):
    """--auto 的触发判据：done ≥ 阈值条，或最早 done 的 reported_at 超龄。
    返回 (bool, 说明文字)。"""
    if len(done_items) >= AUTO_DONE_THRESHOLD:
        return True, "done %d 条 ≥ 阈值 %d" % (len(done_items), AUTO_DONE_THRESHOLD)
    dates = [d for d in (parse_date((fm or {}).get("reported_at"))
                         for fm, _b, _p in done_items) if d]
    if dates:
        oldest = min(dates)
        age = (datetime.date.today() - oldest).days
        if age > AUTO_AGE_DAYS:
            return True, ("最早 done 条目 reported_at=%s，距今 %d 天 > 阈值 %d 天"
                          % (oldest, age, AUTO_AGE_DAYS))
    return False, ("done %d 条 < 阈值 %d，且无超龄条目（>%d 天）"
                   % (len(done_items), AUTO_DONE_THRESHOLD, AUTO_AGE_DAYS))


def fs_move(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        if os.path.exists(dst):
            return False, "目标已存在：%s" % dst
        shutil.move(src, dst)
        return True, ""
    except Exception as e:
        return False, str(e)


def registered_worktrees(queue_dir):
    """`git worktree list --porcelain` 里登记的全部 worktree 绝对路径集合。

    判据 8 的第二条腿：目录已被手工删掉、但 git 那边登记还在（administrative
    files 残留）时，`os.path.isdir` 是 False，搬走条目目录不会立刻报错，但那条
    登记从此指向一个不存在的路径，后续 `git worktree list` 与 `wt_supply remove`
    都会在这条上失败。只看目录存在性会漏掉这一半。
    """
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(queue_dir))))
    out = sh(["git", "-C", root, "worktree", "list", "--porcelain"])
    paths = set()
    for line in out.splitlines():
        if line.startswith("worktree "):
            try:
                paths.add(os.path.realpath(line[len("worktree "):].strip()))
            except Exception:
                pass
    return paths


def worktree_blocks_archive(queue_dir, iid, registered):
    """该条目还挂着活 worktree → 返回原因字符串；干净则返回 None（判据 8）。

    **归档必须跳过它，不能搬**。`shutil.move` 一个 git worktree 会让主仓
    `.git/worktrees/<name>/gitdir` 指向失效路径，那个 worktree 从此既不能用也
    不能 `git worktree remove`（要手工 `prune` 才能收场）。
    """
    wt = os.path.join(item_dir_path(queue_dir, iid), "worktree")
    if os.path.isdir(wt):
        return "`%s` 目录仍存在" % wt
    try:
        if os.path.realpath(wt) in registered:
            return "`git worktree list` 里仍有 %s 的登记（目录已不在，需先 prune）" % wt
    except Exception:
        pass
    return None


def plan_for_item(queue_dir, spec, batch, iid):
    """给定条目 id，返回 [(标签, src, dst)]。

    **v4 只有一项**：整个条目目录搬走。v3 要分别搬 `issues/DBG-007.md`、
    `receipts/DBG-007.md`、`attachments/DBG-007/` 三处，靠文件名对齐——漏搬一处
    不会报错，只是那部分永远留在原地。v4 一条目一目录之后这个失败模式消失了。
    """
    dest_root = os.path.join(archive_dir(queue_dir), batch)
    return [("item", item_dir_path(queue_dir, iid), os.path.join(dest_root, iid))]


def main():
    ap = argparse.ArgumentParser(description="把 status: done 的队列条目按批次归档")
    ap.add_argument("--queue", choices=sorted(SPECS), default="debug",
                    help="哪个队列（默认 debug）")
    ap.add_argument("--queue-dir", default=None,
                    help="队列目录（如 <项目>/.keeper/debug），缺省从 cwd 往上找")
    ap.add_argument("--batch", default=None,
                    help="归档批次名，缺省自动推断（见 guess_batch）")
    ap.add_argument("--auto", action="store_true",
                    help="自动归档模式：done ≥%d 条或最早 done 超 %d 天才归档，"
                         "批次名 auto-<YYYYMMDD>" % (AUTO_DONE_THRESHOLD, AUTO_AGE_DAYS))
    ap.add_argument("--apply", action="store_true", help="真正执行搬迁；缺省 dry-run")
    ap.add_argument("--dry-run", action="store_true",
                    help="显式声明 dry-run（默认行为，可省略）")
    args = ap.parse_args()

    spec = SPECS[args.queue]
    queue_dir = args.queue_dir or find_queue_dir(spec)
    if not queue_dir or not os.path.isdir(queue_dir):
        sys.exit("找不到 %s 目录，用 --queue-dir 指定" % spec.dir_name)
    queue_dir = os.path.abspath(queue_dir)
    apply = bool(args.apply) and not args.dry_run

    items = load_all(queue_dir, spec)
    _op, dn, _unk = split_by_status(items)

    if not dn:
        print("无可归档条目（%s 下没有 status: done 的条目）。" % queue_dir)
        sys.exit(0)

    if args.auto:
        ok, why = auto_should_archive(dn)
        if not ok:
            print("[auto] 未达自动归档阈值：%s。不归档。" % why)
            sys.exit(0)
        print("[auto] 触发自动归档：%s" % why)

    batch, batch_source = guess_batch(queue_dir, args.batch, args.auto)
    print("归档批次：%s（来源：%s）" % (batch, batch_source))

    before_next = next_id(queue_dir, spec)
    print("归档前 next_id() = %s" % before_next)

    to_archive = []      # [(iid, plan)]
    skipped = []         # [(iid, reason)]

    # v4 的 worktree 落点在条目目录里（`<queue>/DBG-NNN/worktree`），不再是与队列
    # 平级的 `.keeper/worktrees/<id>`。判据 8 两条腿：目录存在性 + git 登记。
    registered = registered_worktrees(queue_dir)

    for fm, _body, _path in dn:
        iid = str(fm.get("id"))
        blocked = worktree_blocks_archive(queue_dir, iid, registered)
        if blocked:
            skipped.append((iid, "%s——worktree 还没清理干净，可能有 fixer 未提交的"
                                 "产物；直接搬走会让主仓那条登记指向失效路径，跳过归档"
                                 % blocked))
            continue
        to_archive.append((iid, plan_for_item(queue_dir, spec, batch, iid)))

    print("\n计划归档 %d 条，跳过 %d 条：" % (len(to_archive), len(skipped)))
    for iid, plan in to_archive:
        print("  %s：" % iid)
        for label, src, dst in plan:
            print("    [%s] %s\n      → %s" % (label, src, dst))
    for iid, reason in skipped:
        print("  ⚠ %s 跳过：%s" % (iid, reason))

    if not apply:
        print("\n[dry-run] 未移动任何文件。加 --apply 执行。")
        after_next = next_id(queue_dir, spec)
        print("（dry-run 不改变文件，next_id() 仍为 %s，符合预期）" % after_next)
        return

    ok_count, fail_count = 0, 0
    for iid, plan in to_archive:
        item_ok = True
        for label, src, dst in plan:
            ok, msg = fs_move(src, dst)
            if not ok:
                item_ok = False
                print("  ✗ %s 的 [%s] 移动失败：%s → %s\n    %s"
                     % (iid, label, src, dst, msg))
        if item_ok:
            ok_count += 1
            print("  ✓ %s 已归档到 archive/%s/" % (iid, batch))
        else:
            fail_count += 1

    print("\n成功 %d 条 / 失败 %d 条" % (ok_count, fail_count))

    after_next = next_id(queue_dir, spec)
    print("归档后 next_id() = %s（应与归档前一致：%s）" % (after_next, before_next))
    if after_next != before_next:
        print("✗ 警告：next_id() 在归档前后不一致！说明归档感知逻辑失效，"
             "存在 id 复用风险，请立即排查。")


if __name__ == "__main__":
    main()
