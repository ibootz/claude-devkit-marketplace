#!/usr/bin/env python3
"""按批次把 `status: done` 的条目从队列条目目录归档到 `archive/<批次>/`，
同时把它的 receipts 与 attachments 成组搬走（存在才搬）。debug 与 chore
两个队列共用本脚本，用 `--queue debug|chore` 选择（默认 debug）。

## 为什么要归档

条目目录与 `index.md` 会被历史上已经 done 的条目越撑越大——虽然 `index.md`
的 done 桶只列 id 不列正文，但条目目录本身仍在无限增长，每一轮 `load_all()`
都要扫过全部历史文件。归档把已收尾的条目成组搬到 `archive/<批次>/` 下，
条目目录和 `index.md` 就只装当前仍在流转的条目。`.keeper/` 整树不入库
（gitignore），归档同时也是唯一的「留档」动作——done 条目沉进 archive/ 后
活跃面变小，误删活跃目录的损失也随之变小。

## 为什么用 shutil.move 而不是 git mv

`.keeper/` 整树在 `.gitignore` 里，队列文件不被 git 跟踪，`git mv` 对未跟踪
文件必然报错（fatal: not under version control）。归档是纯文件系统操作。

## id 复用是唯一的硬风险，本脚本必须与 `hooks/lib/queue_files.py` 的
## `next_id()` / `scan_archived_ids()` 配套使用

`next_id()` 只看条目目录时，「文件名集合即完整 id 历史」的前提会被本脚本
打破——归档后旧编号被当成「没用过」重新分配，两条不同条目共用一个 id。
`queue_files.py` 的 `next_id()` 是归档感知的：把 `archive/**/<item_dir>/` 的
文件名也计入历史（只看文件名、不解析 frontmatter，即使归档文件损坏也不会
导致编号被回收重用）。**不要在没有这个前置逻辑的存储层上单独使用本脚本**。

## 自动归档（--auto）

keeper 在每次「收尾/执行窗口」结束时跑一次 `--auto`：满足任一条件才归档，
否则打印「未达阈值」直接退出——
  · done 条目 ≥ %(AUTO_DONE_THRESHOLD)s 条；
  · 最早 done 条目的 `reported_at` 距今 > %(AUTO_AGE_DAYS)s 天。
批次名固定 `auto-<YYYYMMDD>`（当天日期）。判据全是文件计数与 frontmatter
日期比较，机械可核；`reported_at` 缺失或格式不对的条目不参与年龄判据
（只影响触发时机，不影响归档正确性）。

## 用法

    python3 archive_done.py --queue-dir <项目>/.keeper/debug --batch D-001-feat-xxx
    python3 archive_done.py --queue-dir <项目>/.keeper/debug --batch D-001 --apply
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
    from queue_files import (DEBUG, CHORE, items_dir, archive_dir, load_all,
                             split_by_status, next_id)
except Exception as e:
    sys.exit("无法导入 queue_files（应在 plugins/task-keeper/hooks/lib/）：%s" % e)

SPECS = {"debug": DEBUG, "chore": CHORE}


def sh(args, cwd=None):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except Exception:
        return ""


def find_queue_dir(spec):
    """从 cwd 往上找最近的 `<dir_name>`（如 .keeper/debug）目录，纯文件系统查找。"""
    cur = os.path.abspath(os.getcwd())
    parts = spec.dir_name.split("/")
    while True:
        cand = os.path.join(cur, *parts)
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def guess_batch(queue_dir, explicit, auto):
    """确定归档批次名，来源必须 fail-loud 说清楚，不允许静默拼一个可能错的名字。

    优先级：
      1. 显式 `--batch` 参数
      2. `--auto` 模式固定 `auto-<YYYYMMDD>`
      3. 从队列目录的绝对路径里提取交付级 worktree 的 slug（路径含
         `worktrees/<slug>/` 时取 <slug>，适配「整个交付跑在一个 worktree 里」
         的布局；fixer 自己的 `.keeper/worktrees/DBG-*` 不会走到这里——
         归档由 keeper 在真身队列上执行）
      4. 退回当前 git 分支名（清洗成安全的目录名）
      5. 都取不到就报错要求显式传 `--batch`，不猜
    """
    if explicit:
        return explicit, "显式 --batch 参数"
    if auto:
        stamp = datetime.date.today().strftime("%Y%m%d")
        return "auto-%s" % stamp, "--auto 模式固定 auto-<YYYYMMDD>"

    norm = os.path.abspath(queue_dir).replace(os.sep, "/")
    m = re.search(r"/worktrees/([^/]+)/", norm)
    if m and not re.match(r"(DBG|CHR)-\d+$", m.group(1)):
        return m.group(1), "从路径 %s 提取 worktrees/<slug>" % norm

    root = os.path.dirname(os.path.dirname(os.path.abspath(queue_dir)))
    branch = sh(["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"])
    if branch and branch != "HEAD":
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-")
        if safe:
            return safe, ("未检测到 worktrees/<slug> 路径，退回当前 git 分支名 "
                          "%r 清洗得到" % branch)

    sys.exit(
        "无法确定归档批次：既不在 worktrees/<slug> 路径下，也取不到当前 "
        "git 分支名（可能是 detached HEAD 或不在 git 仓库内）。请显式传 --batch <名字>。")


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


def plan_for_item(queue_dir, spec, batch, iid):
    """给定条目 id，算出这条最多三样东西各自的 (标签, src, dst) 计划。
    receipts / attachments 不存在时不进计划（不是失败，是本就没有——
    chore 队列通常两者皆无，自然只搬条目文件本身）。"""
    dest_root = os.path.join(archive_dir(queue_dir), batch)
    plan = []

    item_src = os.path.join(items_dir(queue_dir, spec), "%s.md" % iid)
    item_dst = os.path.join(dest_root, spec.item_dir, "%s.md" % iid)
    plan.append(("item", item_src, item_dst))

    receipts_src = os.path.join(queue_dir, "receipts", "%s.md" % iid)
    if os.path.isfile(receipts_src):
        receipts_dst = os.path.join(dest_root, "receipts", "%s.md" % iid)
        plan.append(("receipt", receipts_src, receipts_dst))

    attach_src = os.path.join(queue_dir, "attachments", iid)
    if os.path.isdir(attach_src):
        attach_dst = os.path.join(dest_root, "attachments", iid)
        plan.append(("attachments", attach_src, attach_dst))

    return plan


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
        print("无可归档条目（%s/ 下没有 status: done 的条目）。" % spec.item_dir)
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

    # worktrees 落点在 .keeper/worktrees/<id>（与队列目录平级），只对 debug 有意义
    wt_root = os.path.join(os.path.dirname(queue_dir), "worktrees")

    for fm, _body, _path in dn:
        iid = str(fm.get("id"))
        wt_dir = os.path.join(wt_root, iid)
        if os.path.isdir(wt_dir):
            skipped.append((iid, "仍存在 %s/——worktree 还没清理干净，"
                                 "可能有 fixer 未提交的产物，跳过归档" % wt_dir))
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
