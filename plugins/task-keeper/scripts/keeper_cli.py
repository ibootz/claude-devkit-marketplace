#!/usr/bin/env python3
"""keeper 实例的并发原语 CLI（认领编号 / 绑定 issue / 合并锁 / 看同档实例）

## 为什么需要它

v7 起一条 issue 一个 keeper 实例，同一档并存多个。keeper 是 agent，只能通过 `Bash`
接触磁盘——而多实例正确性依赖三个**必须原子**的动作，靠 agent 用 `Write` 手工完成
一定会出竞态：

  1. **认领编号**：两个实例同时登记新 bug，各自扫出 `DBG-208` 再各自写 `issue.md`，
     后写的整份覆盖先写的。表现是「有一条 bug 凭空消失」，且全程无报错。
  2. **合并回主仓**：两个实例同时 `git merge` 动同一个主仓 HEAD，撞出半完成的 merge
     状态，没有干净的自动恢复路径。
  3. **登记自己认领了哪条 issue**：主会话唤醒时要按 issue 找实例，不是按时间猜。

本 CLI 把这三件事收成三个子命令，实现全部落在 `hooks/lib/` 的共享模块里——**不在
这里重写一份判据**，那样早晚漂移成两个结论。

## 输出契约（agent 要按它判成败，别靠读措辞）

  · 成功 → 退出码 0，stdout 第一行是机器可读的结果（编号 / `OK` / `HELD`）。
  · 失败 → 退出码非 0，stderr 一行原因。
  · 锁被别人持有 → **退出码 3**（不是 1）。这是「正常竞争」不是「出错」，调用方
    应当等待重试，而不是把它当故障上报。

## 用法

    keeper_cli.py claim  --kind debug --summary "登录页白屏"
    keeper_cli.py bind   --kind debug --name opus-debugger-4bb6 --issue DBG-208
    keeper_cli.py lock   acquire --name opus-debugger-4bb6 --issue DBG-208
    keeper_cli.py lock   release --name opus-debugger-4bb6
    keeper_cli.py lock   status
    keeper_cli.py peers  --kind debug

所有子命令都接受 `--cwd <路径>` 覆盖工作目录（缺省取当前目录），用于 keeper 在
fixer worktree 里调用时指回交付根。
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "hooks", "lib"))

import keeper_paths                                    # noqa: E402
import queue_files                                     # noqa: E402

SPEC_BY_KIND = {"debug": queue_files.DEBUG, "chore": queue_files.CHORE}


def die(msg, code=1):
    sys.stderr.write(msg.rstrip("\n") + "\n")
    raise SystemExit(code)


def resolve(args):
    """(worktree_root, delivery_id)。定位不到 git 工作区就退出——**不猜**。

    定位失败时硬失败而不是回落到 cwd：把队列写进一个不是交付根的目录，产生的是一份
    没人会去读的影子队列，比直接报错难发现得多。
    """
    cwd = os.path.abspath(args.cwd or os.getcwd())
    root = keeper_paths.find_worktree_root(cwd)
    if not root:
        die("定位不到 git 工作区（cwd=%s）。用 --cwd 指到交付根再试。" % cwd)
    return root, keeper_paths.resolve_delivery_id(root)


def cmd_claim(args):
    """原子认领下一个编号，落一份占位正文，打印 `<id>\t<目录>`。"""
    spec = SPEC_BY_KIND[args.kind]
    root, delivery_id = resolve(args)
    keeper_root = os.path.join(root, keeper_paths.KEEPER_DIR)
    qdir = os.path.join(keeper_root, delivery_id, spec.dir_name)
    try:
        siblings = keeper_paths.all_queue_dirs(keeper_root, spec)
    except Exception:
        siblings = None

    iid, item_dir = queue_files.claim_id(qdir, spec, sibling_dirs=siblings,
                                         summary=args.summary)
    if not iid:
        die("认领失败：连试 64 个编号都被占用，或队列目录不可写（%s）" % qdir)
    sys.stdout.write("%s\t%s\n" % (iid, item_dir))
    sys.stdout.write(
        "占位正文已落盘，**立刻用真实内容整份改写它**——占位摘要会原样出现在 index.md 里。\n")
    return 0


def cmd_bind(args):
    """把「我这个实例认领了哪条 issue」写进登记，供主会话按 issue 唤醒。

    登记里已有同名记录时是原地更新（`write_keeper_instance` 按 name 去重），所以重复
    调用安全；换绑到另一条 issue 也是同一条路径。
    """
    root, delivery_id = resolve(args)
    ok = keeper_paths.write_keeper_instance(
        root, delivery_id, args.kind, args.name,
        session_id=args.session_id, issue=args.issue)
    if not ok:
        die("登记写入失败（目录不可写？）：%s"
            % keeper_paths.instance_registry_path(root, delivery_id))
    sys.stdout.write("OK\t%s\t%s\n" % (args.name, args.issue))
    return 0


def cmd_lock(args):
    root, delivery_id = resolve(args)
    if args.action == "status":
        holder = keeper_paths.read_merge_lock(root, delivery_id)
        if not holder:
            sys.stdout.write("FREE\n")
            return 0
        sys.stdout.write("HELD\t%s\t%s\t%s\n" % (
            holder.get("name") or "?", holder.get("issue") or "-",
            holder.get("ts") or "?"))
        return 0

    if not args.name:
        die("acquire / release 必须给 --name（合并锁按持有者校验，见 keeper_paths 的锁 API）")

    if args.action == "release":
        if keeper_paths.release_merge_lock(root, delivery_id, args.name):
            sys.stdout.write("OK\n")
            return 0
        die("释放失败：这把锁已不属于你（多半是超时后被别人抢占了）。"
            "**不要重试释放**——把这件事写进回执，并核对主仓是否停在半完成的 merge 状态。", 4)

    ok, info = keeper_paths.acquire_merge_lock(
        root, delivery_id, args.name, issue=args.issue)
    if ok:
        preempted = (info or {}).get("preempted") if isinstance(info, dict) else None
        if preempted:
            sys.stdout.write("OK\tpreempted\t%s\t%s\n" % (
                preempted.get("name") or "?", preempted.get("issue") or "-"))
            sys.stdout.write(
                "上一个持锁者超时未释放，锁已被你抢占。**先在主仓跑一次 "
                "`git -C <主仓> status`**：它可能死在 merge 中途（MERGE_HEAD 还在），"
                "此时要先收拾那次未完成的合并，再开始你自己的。\n")
        else:
            sys.stdout.write("OK\n")
        return 0

    holder = info or {}
    sys.stderr.write("BUSY\t%s\t%s\t%s\n" % (
        holder.get("name") or "?", holder.get("issue") or "-", holder.get("ts") or "?"))
    sys.stderr.write("合并锁被别人持有。等它释放后重试，**不要绕开锁直接合并**。\n")
    return 3


def cmd_peers(args):
    """列出同档还在登记里的实例，给 keeper 判断「谁在跑什么」。"""
    root, delivery_id = resolve(args)
    recs = keeper_paths.live_instances(root, delivery_id, args.kind,
                                       current_session_id=args.session_id)
    if args.json:
        sys.stdout.write(json.dumps(recs, ensure_ascii=False, indent=2) + "\n")
        return 0
    if not recs:
        sys.stdout.write("（同档没有其它实例登记）\n")
        return 0
    for r in recs:
        sys.stdout.write("%s\t%s\t%s\n" % (
            r.get("issue") or "-", r.get("name"), r.get("ts") or "?"))
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="keeper_cli.py", description=__doc__.split("\n")[0])
    p.add_argument("--cwd", help="覆盖工作目录（缺省取当前目录）")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("claim", help="原子认领下一个编号并建条目目录")
    c.add_argument("--kind", choices=sorted(SPEC_BY_KIND), required=True)
    c.add_argument("--summary", help="一句话摘要，会写进占位 frontmatter")
    c.set_defaults(func=cmd_claim)

    b = sub.add_parser("bind", help="把本实例认领的 issue 写进登记")
    b.add_argument("--kind", choices=sorted(SPEC_BY_KIND), required=True)
    b.add_argument("--name", required=True, help="本实例的 name（主会话派发时给的那个）")
    b.add_argument("--issue", required=True, help="DBG-NNN / CHR-NNN")
    b.add_argument("--session-id", dest="session_id",
                   help="不传则登记里不写 session_id，跨会话读到时按陈旧处理")
    b.set_defaults(func=cmd_bind)

    l = sub.add_parser("lock", help="合并锁：acquire / release / status")
    l.add_argument("action", choices=("acquire", "release", "status"))
    l.add_argument("--name", help="持有者标识，用本实例的 name")
    l.add_argument("--issue", help="正在合并哪条 issue，写进锁元数据便于归因")
    l.set_defaults(func=cmd_lock)

    q = sub.add_parser("peers", help="列出同档其它实例")
    q.add_argument("--kind", choices=sorted(SPEC_BY_KIND), required=True)
    q.add_argument("--session-id", dest="session_id")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_peers)
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    raise SystemExit(args.func(args) or 0)
