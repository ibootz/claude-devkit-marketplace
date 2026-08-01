#!/usr/bin/env python3
"""把 `.keeper/` 队列从 v3 布局（单目录、按类型分桶）迁移到 v4 布局
（一交付一目录，`<交付id>` 形如 `D-001-feat-job-sequence-model`，兜底桶 `_main`）。

## v3 → v4 布局对照

v3（schema v3，见 `references/queue.md` §1）：

    .keeper/debug/index.md
    .keeper/debug/issues/DBG-NNN.md
    .keeper/debug/receipts/DBG-NNN.md
    .keeper/debug/attachments/DBG-NNN/<原文件名>
    .keeper/debug/attachments/_inbox/<还没分配 id 的截图>
    .keeper/debug/archive/<批次>/{issues,receipts,attachments}/...
    .keeper/worktrees/DBG-NNN/          ← fixer 的 git worktree，是活的 git worktree
    .keeper/chore/index.md
    .keeper/chore/items/CHR-NNN.md
    .keeper/decisions/{<stamp>-<keeper>.md, answers/<同名>.md}

v4（见 `hooks/lib/keeper_paths.py` 模块头）：

    .keeper/.keeper-active                       ← 单行文本 = 当前活跃交付目录名
    .keeper/<交付id>/debug/index.md
    .keeper/<交付id>/debug/DBG-NNN/issue.md
    .keeper/<交付id>/debug/DBG-NNN/receipts.md
    .keeper/<交付id>/debug/DBG-NNN/<原文件名>
    .keeper/<交付id>/debug/DBG-NNN/worktree/     ← 新 fixer worktree 的落点（本脚本不代建）
    .keeper/<交付id>/debug/archive/<批次>/DBG-NNN/{issue.md,receipts.md,*.png}
    .keeper/<交付id>/chore/CHR-NNN/item.md
    .keeper/<交付id>/chore/index.md
    .keeper/<交付id>/decisions/{...}

`attachments/_inbox/` 是例外：v4 布局图里没有画它，但它装的是**还没分配 id 的
暂存截图**，天然不属于任何交付、也不属于任何 issue，本脚本原样保留不动。

## 为什么不用 `hooks/lib/keeper_paths.py` 的交付归属推断来决定迁移落点

`resolve_delivery_id` 回答的是「当前 worktree 该归属哪个交付」，输入是**运行时
cwd**；本脚本面对的是**存量数据**——这 79 条 issue 是在 v3 单目录时代跨多次交付
攒下来的，「这条 issue 当初属于哪次交付」这件事在 v3 schema 里从未被记录过。
硬套 `resolve_delivery_id(cwd)` 只会得到「跑迁移脚本这一刻 cwd 恰好在哪」这一个
值，与历史上 79 条 issue 各自的真实归属无关——这是脚本该拒绝的臆断。默认策略
因此是「存量条目一律进 `_main`，除非人工用 `--delivery` 显式指定」。

**归档批次是唯一例外**：`archive_done.py` 的 `guess_batch` 在 v3 下把交付 worktree
的 slug 直接当批次名用（归档动作本身发生在某次交付收尾时，批次名与交付 id 同源），
所以归档目录可以复用同一个 `DELIVERY_RE` 正则——批次名匹配
`^(?:D-\\d+-|hotfix-)` 就直接拿它当交付 id；不匹配（如 `auto-YYYYMMDD` 或某个
不规范分支名）时同样落 `_main`。这个判断与 `--delivery` 参数是否传入无关，各批次
独立判断。

## 为什么跳过 `.keeper/worktrees/<id>/`，且**不**尝试自动 `git worktree repair`

一个 linked git worktree 靠两处互相指向的记录维系：worktree 内的 `.git`（文件，
内容是 `gitdir: <主仓>/.git/worktrees/<name>`）与主仓 `.git/worktrees/<name>/gitdir`
（反向指回 worktree 路径）。`shutil.move` 只搬工作树目录，不改这两处指针——搬完后
`.git` 文件里的路径失效、主仓那份 `gitdir` 记录也没人更新，`git worktree list`
会把它标成 `prunable`，continue 使用会報 `fatal: <path>/.git file points to non-
existent location`。

`git worktree repair [<path>...]` 官方设计正是用来修这类「worktree 与主仓记录
不同步」的场景，但它要求**在新路径下调用、且新路径下的 `.git` 文件已经指向了
正确的 gitdir**——也就是说它修的是「gitdir 记录滞后」，不是「文件被随意搬到哪
都能追认」。本仓 2026-08-01 在 `/tmp` 用真实 `git worktree add` + `mv`（不用
`shutil.move`，效果等价）+ `git worktree repair` 做过实证（结论见本文件同批
交付回执，未内置进本脚本）：**先搬目录、再在新路径跑 `repair`，确实能让主仓与
worktree 双向记录都指向新路径、`git worktree list` 恢复正常、`git status` 在
新路径下工作正常**——但前提是原 worktree 没有 `.keeper/worktrees/<id>/` 本身
被误伤（比如遗留半个 `.git`）。鉴于（a）这属于「移动之后修」的高风险操作，
一旦目标路径下 `.git` 文件的相对路径计算错误就会两头都指错；（b）v4 目标落点
（`debug/<id>/worktree/`）目前还没有任何 hook/脚本依赖它必须在这一刻就位——
本脚本选择保守策略：**只探测 + 跳过 + 在报告里给出下一步该做什么**，把「要不要
现在就搬」的判断交还给操作者，不在迁移脚本里做「移动 + 修复」这种一旦出错就是
两头都坏的连续动作。

探测判据：`<worktrees 目录>/<id>/.git` 存在（文件或目录都算）即视为活的 git
worktree，无条件跳过。不存在 `.git` 的条目视为形态异常（不应该出现在这个位置），
同样跳过并要求人工检查，不猜测处置方式。

## 幂等

迁移计划完全从「legacy 路径当前是否还存在这个文件/目录」现算，不维护任何迁移
进度记录。第一次 `--apply` 把文件搬到 v4 落点后，legacy 路径不再存在，第二次
运行时该条目自然不会再出现在计划里——不需要额外的「已迁移」标记，重复运行的
唯一区别是计划为空。`--apply` 执行时若目标路径已存在（理论上只会发生在人工
手工建过同名文件的异常情况），本脚本 fail-loud 报出来并跳过该条，不覆盖、不
中断整批，与 `archive_done.py` 的 `fs_move` 同一约定。

## 用法

    python3 migrate_layout.py                                   # 自动定位 .keeper，dry-run
    python3 migrate_layout.py --keeper-dir /path/to/.keeper      # 显式指定
    python3 migrate_layout.py --delivery D-001-feat-xxx          # 存量条目归入指定交付桶而非 _main
    python3 migrate_layout.py --apply                            # 核对 dry-run 输出无误后才加这个

默认 dry-run，只打印迁移清单不动文件；`--apply` 才真正移动。
"""
import argparse
import os
import re
import shutil
import sys

# ── 尝试复用 hooks/lib/keeper_paths.py 的常量与定位逻辑（只读用途，不改它） ──
# 该模块由另一位协作者同步在改，做 try/except 兜底，避免因为它当下的实现变动
# 导致本脚本连基本常量都拿不到。
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "hooks", "lib"))

try:
    from keeper_paths import (KEEPER_DIR, ACTIVE_MARK, MAIN_BUCKET, DELIVERY_RE,
                              find_keeper_root)
except Exception:
    KEEPER_DIR = ".keeper"
    ACTIVE_MARK = ".keeper-active"
    MAIN_BUCKET = "_main"
    DELIVERY_RE = re.compile(r"^(?:D-\d+-|hotfix-)")
    find_keeper_root = None

DBG_RE = re.compile(r"^DBG-\d+$")
CHR_RE = re.compile(r"^CHR-\d+$")


def default_keeper_dir():
    """定位待迁移的 `.keeper` 目录：优先复用 `find_keeper_root`，
    不可用（导入失败）时退回本脚本自带的向上找。"""
    if find_keeper_root is not None:
        try:
            found = find_keeper_root(os.getcwd())
            if found:
                return found
        except Exception:
            pass
    cur = os.path.abspath(os.getcwd())
    for _ in range(30):
        cand = os.path.join(cur, KEEPER_DIR)
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def plan_queue_dir(keeper_root, legacy_dir, queue_key, id_re, item_dir_name,
                   item_filename, delivery_default):
    """扫一个队列（debug 或 chore）的 legacy 目录，产出 (moves, warnings)。

    moves: [(label, src, dst)]
    warnings: [(path, reason)] —— 形态不认识的条目，不猜测处置方式，只报告。

    debug 与 chore 结构同构（index / 条目 / receipts / attachments / archive），
    差异只在 `item_dir_name`（issues vs items）与 `item_filename`（issue.md vs
    item.md），因此参数化成一份实现，不复制第二份。
    """
    moves = []
    warnings = []
    if not os.path.isdir(legacy_dir):
        return moves, warnings

    idx = os.path.join(legacy_dir, "index.md")
    if os.path.isfile(idx):
        moves.append(("%s-index" % queue_key, idx,
                      os.path.join(keeper_root, delivery_default, queue_key, "index.md")))

    items_dir = os.path.join(legacy_dir, item_dir_name)
    if os.path.isdir(items_dir):
        for name in sorted(os.listdir(items_dir)):
            if not name.endswith(".md"):
                warnings.append((os.path.join(items_dir, name),
                                 "%s/ 下出现非 .md 条目，跳过" % item_dir_name))
                continue
            iid = name[:-3]
            if not id_re.match(iid):
                warnings.append((os.path.join(items_dir, name),
                                 "文件名不匹配 id 格式，跳过"))
                continue
            src = os.path.join(items_dir, name)
            dst = os.path.join(keeper_root, delivery_default, queue_key, iid, item_filename)
            moves.append(("%s-item" % queue_key, src, dst))

    receipts_dir = os.path.join(legacy_dir, "receipts")
    if os.path.isdir(receipts_dir):
        for name in sorted(os.listdir(receipts_dir)):
            if not name.endswith(".md"):
                warnings.append((os.path.join(receipts_dir, name),
                                 "receipts/ 下出现非 .md 条目，跳过"))
                continue
            iid = name[:-3]
            if not id_re.match(iid):
                warnings.append((os.path.join(receipts_dir, name),
                                 "文件名不匹配 id 格式，跳过"))
                continue
            src = os.path.join(receipts_dir, name)
            dst = os.path.join(keeper_root, delivery_default, queue_key, iid, "receipts.md")
            moves.append(("%s-receipt" % queue_key, src, dst))

    attach_dir = os.path.join(legacy_dir, "attachments")
    if os.path.isdir(attach_dir):
        for name in sorted(os.listdir(attach_dir)):
            full = os.path.join(attach_dir, name)
            if name == "_inbox":
                continue   # 保持原位不动：还没分配 id 的暂存截图，不属于任何交付
            if not os.path.isdir(full):
                warnings.append((full, "attachments/ 下出现非目录条目，跳过"))
                continue
            if not id_re.match(name):
                warnings.append((full, "目录名不匹配 id 格式，跳过"))
                continue
            for fname in sorted(os.listdir(full)):
                src = os.path.join(full, fname)
                if os.path.isdir(src):
                    warnings.append((src, "attachments/<id>/ 下出现子目录，未预期，跳过"))
                    continue
                dst = os.path.join(keeper_root, delivery_default, queue_key, name, fname)
                moves.append(("%s-attachment" % queue_key, src, dst))

    archive_root = os.path.join(legacy_dir, "archive")
    if os.path.isdir(archive_root):
        for batch in sorted(os.listdir(archive_root)):
            batch_dir = os.path.join(archive_root, batch)
            if not os.path.isdir(batch_dir):
                continue
            # 归档批次名与交付 id 同源（archive_done.py 的 guess_batch），能匹配就
            # 直接当交付 id 用；这与 --delivery 参数无关，各批次独立判断。
            archive_bucket = batch if DELIVERY_RE.match(batch) else MAIN_BUCKET

            b_items = os.path.join(batch_dir, item_dir_name)
            b_receipts = os.path.join(batch_dir, "receipts")
            b_attach = os.path.join(batch_dir, "attachments")
            ids = set()
            if os.path.isdir(b_items):
                ids |= {n[:-3] for n in os.listdir(b_items)
                       if n.endswith(".md") and id_re.match(n[:-3])}
            if os.path.isdir(b_receipts):
                ids |= {n[:-3] for n in os.listdir(b_receipts)
                       if n.endswith(".md") and id_re.match(n[:-3])}
            if os.path.isdir(b_attach):
                ids |= {n for n in os.listdir(b_attach) if id_re.match(n)}

            for iid in sorted(ids):
                dest_root = os.path.join(keeper_root, archive_bucket, queue_key,
                                         "archive", batch, iid)
                isrc = os.path.join(b_items, iid + ".md")
                if os.path.isfile(isrc):
                    moves.append(("%s-archive-item" % queue_key, isrc,
                                 os.path.join(dest_root, item_filename)))
                rsrc = os.path.join(b_receipts, iid + ".md")
                if os.path.isfile(rsrc):
                    moves.append(("%s-archive-receipt" % queue_key, rsrc,
                                 os.path.join(dest_root, "receipts.md")))
                asrc = os.path.join(b_attach, iid)
                if os.path.isdir(asrc):
                    for fname in sorted(os.listdir(asrc)):
                        fsrc = os.path.join(asrc, fname)
                        if os.path.isfile(fsrc):
                            moves.append(("%s-archive-attachment" % queue_key, fsrc,
                                         os.path.join(dest_root, fname)))
    return moves, warnings


def plan_decisions(keeper_root, delivery_default):
    """`.keeper/decisions/` 整树搬迁到 `<桶>/decisions/`，保留内部结构
    （`<stamp>-<keeper>.md` 与 `answers/<同名>.md`）。decisions 没有天然的
    「按条目」粒度，不做 per-id 拆分，整棵子树按相对路径搬。"""
    moves = []
    legacy = os.path.join(keeper_root, "decisions")
    if not os.path.isdir(legacy):
        return moves
    dest_root = os.path.join(keeper_root, delivery_default, "decisions")
    for dirpath, _dirnames, filenames in os.walk(legacy):
        rel = os.path.relpath(dirpath, legacy)
        for fname in sorted(filenames):
            src = os.path.join(dirpath, fname)
            dst = (os.path.join(dest_root, fname) if rel == "."
                  else os.path.join(dest_root, rel, fname))
            moves.append(("decision", src, dst))
    return moves


def plan_worktrees(keeper_root):
    """`.keeper/worktrees/<id>/` 一律不搬，只探测 + 报告。见文件头「为什么跳过」。"""
    skipped = []
    wt_dir = os.path.join(keeper_root, "worktrees")
    if not os.path.isdir(wt_dir):
        return skipped
    for name in sorted(os.listdir(wt_dir)):
        full = os.path.join(wt_dir, name)
        if not os.path.isdir(full):
            skipped.append((full, "worktrees/ 下出现非目录条目，跳过，请人工检查"))
            continue
        if os.path.exists(os.path.join(full, ".git")):
            skipped.append((full,
                "活的 git worktree（%s/.git 存在）。不能用 shutil.move 直接搬——"
                "会让 worktree 登记变成 prunable 坏态。请先用 wt_supply.py remove "
                "清掉这条 issue 的 worktree 再重跑本脚本；或迁移后手动在新路径下执行 "
                "`git worktree repair <新路径>`（自动化风险见脚本头部说明，"
                "本脚本不代做这一步）" % name))
        else:
            skipped.append((full,
                "worktrees/%s 下没有 .git，形态不是预期中的 git worktree，"
                "跳过并请人工检查（可能是残留的空目录）" % name))
    return skipped


def fs_move(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        return False, "目标已存在：%s" % dst
    shutil.move(src, dst)
    return True, ""


def prune_empty_dirs(root, protect_names=("_inbox",)):
    """搬完之后清理空出来的 legacy 目录壳，纯粹为了整洁，不是幂等的必要条件。
    自底向上，basename 命中 protect_names 的目录（如 `_inbox`）永不删除，
    即使它当前为空——它是长期存在的暂存区，不因为搬迁而消失。"""
    if not os.path.isdir(root):
        return
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if os.path.basename(dirpath) in protect_names:
            continue
        if dirnames or filenames:
            continue
        try:
            os.rmdir(dirpath)
        except OSError:
            pass


def print_moves(title, moves):
    print("\n-- %s --" % title)
    if not moves:
        print("（无待迁移内容）")
        return
    print("计划 %d 条：" % len(moves))
    for label, src, dst in moves:
        print("  [%s] %s\n    → %s" % (label, src, dst))


def print_warnings(title, warnings):
    if not warnings:
        return
    print("\n-- %s（%d 条，均已跳过）--" % (title, len(warnings)))
    for path, reason in warnings:
        print("  ⚠ %s：%s" % (path, reason))


def main():
    ap = argparse.ArgumentParser(
        description="把 .keeper/ 队列从 v3 布局迁移到 v4 布局（一交付一目录）")
    ap.add_argument("--keeper-dir", default=None,
                    help="要迁移的 .keeper 目录绝对路径，缺省自动定位")
    ap.add_argument("--delivery", default=None,
                    help="存量条目（issues/receipts/attachments/chore/decisions）"
                         "统一归入的交付桶，缺省 %s" % MAIN_BUCKET)
    ap.add_argument("--apply", action="store_true", help="真正执行迁移；缺省 dry-run")
    ap.add_argument("--dry-run", action="store_true",
                    help="显式声明 dry-run（默认行为，可省略）")
    args = ap.parse_args()

    keeper_dir = args.keeper_dir or default_keeper_dir()
    if not keeper_dir or not os.path.isdir(keeper_dir):
        sys.exit("找不到 .keeper 目录，用 --keeper-dir 指定")
    keeper_dir = os.path.abspath(keeper_dir)
    delivery = args.delivery or MAIN_BUCKET
    apply = bool(args.apply) and not args.dry_run

    print("=== task-keeper 队列布局迁移：v3 → v4 ===")
    print(".keeper 目录：%s" % keeper_dir)
    print("存量条目归入交付桶：%s%s" % (delivery, "（默认）" if not args.delivery else "（--delivery 指定）"))

    active_path = os.path.join(keeper_dir, ACTIVE_MARK)
    if os.path.isfile(active_path):
        try:
            cur_active = open(active_path, encoding="utf-8").read().strip()
        except Exception:
            cur_active = "<读取失败>"
        print("提示：%s 已存在（内容 %r）——该 .keeper 可能已部分或全部是 v4 布局，"
             "本次计划只会包含仍留在 legacy 路径下的条目" % (ACTIVE_MARK, cur_active))

    debug_moves, debug_warnings = plan_queue_dir(
        keeper_dir, os.path.join(keeper_dir, "debug"), "debug", DBG_RE,
        "issues", "issue.md", delivery)
    chore_moves, chore_warnings = plan_queue_dir(
        keeper_dir, os.path.join(keeper_dir, "chore"), "chore", CHR_RE,
        "items", "item.md", delivery)
    decisions_moves = plan_decisions(keeper_dir, delivery)
    wt_skipped = plan_worktrees(keeper_dir)

    print_moves("debug 队列", debug_moves)
    print_warnings("debug 队列 · 未识别条目", debug_warnings)
    print_moves("chore 队列", chore_moves)
    print_warnings("chore 队列 · 未识别条目", chore_warnings)
    print_moves("decisions", decisions_moves)

    if wt_skipped:
        print("\n-- worktrees（.keeper/worktrees/，全部跳过不搬）--")
        for path, reason in wt_skipped:
            print("  ⚠ %s：%s" % (path, reason))
    else:
        print("\n-- worktrees（.keeper/worktrees/）--")
        print("（不存在或为空，无需处理）")

    all_moves = debug_moves + chore_moves + decisions_moves
    total_warnings = len(debug_warnings) + len(chore_warnings)

    from collections import Counter
    label_counts = Counter(label for label, _s, _d in all_moves)

    def c(*labels):
        return sum(label_counts.get(l, 0) for l in labels)

    print("\n=== 汇总 ===")
    print("debug：index %d / issue %d / receipts %d / attachments 文件 %d / "
         "归档条目（issue+receipts+attachment）%d" % (
        c("debug-index"), c("debug-item"), c("debug-receipt"), c("debug-attachment"),
        c("debug-archive-item", "debug-archive-receipt", "debug-archive-attachment")))
    print("chore：index %d / item %d / receipts %d / attachments 文件 %d / "
         "归档条目（item+receipts+attachment）%d" % (
        c("chore-index"), c("chore-item"), c("chore-receipt"), c("chore-attachment"),
        c("chore-archive-item", "chore-archive-receipt", "chore-archive-attachment")))
    print("decisions 文件: %d" % len(decisions_moves))
    print("跳过的 worktrees 条目: %d" % len(wt_skipped))
    print("未识别 / 跳过的其它条目: %d" % total_warnings)
    print("迁移条目合计: %d" % len(all_moves))

    if not apply:
        print("\n[dry-run] 未移动任何文件。加 --apply 执行。")
        return

    ok_count, fail_count = 0, 0
    for _label, src, dst in all_moves:
        moved, msg = fs_move(src, dst)
        if moved:
            ok_count += 1
        else:
            fail_count += 1
            print("  ✗ 移动失败：%s → %s\n    %s" % (src, dst, msg))

    prune_empty_dirs(os.path.join(keeper_dir, "debug"))
    prune_empty_dirs(os.path.join(keeper_dir, "chore"))
    prune_empty_dirs(os.path.join(keeper_dir, "decisions"))

    print("\n成功 %d 条 / 失败 %d 条" % (ok_count, fail_count))

    if fail_count == 0 and (all_moves or not os.path.isfile(active_path)):
        # 只在「这次真的搬了东西」或「标记文件本来就不存在」时才写——避免在一次
        # 无事可做的重跑上，因为传了不同的 --delivery 就把已经正确的旧标记覆盖掉。
        try:
            with open(active_path, "w", encoding="utf-8") as f:
                f.write(delivery + "\n")
            print("已写入 %s = %s（避免 hook 自愈逻辑按 cwd worktree basename 猜出"
                 "另一个桶，导致刚迁移的数据被晾在一边）" % (ACTIVE_MARK, delivery))
        except Exception as e:
            print("写入 %s 失败（不影响已完成的文件迁移）：%s" % (ACTIVE_MARK, e))
    elif fail_count == 0:
        print("本次无实际迁移动作，%s 已存在，保持不动" % ACTIVE_MARK)
    else:
        print("存在失败条目，未写入 %s——先处理失败项，确认全部干净后可重跑本脚本"
             "（幂等，只会处理仍留在 legacy 路径下的条目）" % ACTIVE_MARK)


if __name__ == "__main__":
    main()
