#!/usr/bin/env python3
"""keeper 实例的并发原语 CLI（认领编号 / 绑定 issue / 合并锁 / 看同档实例 /
跨队列查重候选 / 转出互链校验）

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

v8（4.6.0）补两个**只读**子命令，对应「一个事项一个活跃主条目」规则的机械面：

  · `candidates`：列出当前交付 debug 与 chore 两个队列的**全部 open 条目**，供
    keeper 在 claim 前做语义查重。它只做「列出」，不做「是否同一事项」的判断——
    那个判断是语义的，留给 keeper，hook 正则与脚本都不得代判（详见两个 agent
    定义的登记章节）。
  · `check-transfers`：规格空白转出互链的机械完整性校验（`candidates` 的姊妹
    判据，见下方「转出互链约定」）。

## 转出互链约定（check-transfers 的判据来源）

debug-keeper 判 `spec_status: gap` 转 chore 时，两边各写一行固定格式的正文标记
（**逐字照抄这两个形态，机械校验只认它们**）：

  · 原 DBG 的 `issue.md` 正文「修订记录」里写：`转出至：CHR-NNN（规格空白，待产品确认）`
  · 目标 CHR 的 `item.md` 正文里写：`来源：DBG-NNN（规格空白转出）`

check-transfers 只校验**引用完整性**，不判断两个自然语言事项是否相同。
**top-level 与 `archive/<批次>/` 都纳入**：done 条目会被 `archive_done.py`
整目录搬去归档（互链标记原样保留），只扫 top-level 会把「已归档的合法 done
源」误报成「不存在」——归档不解除互链义务。

  1. CHR 声明来源 `DBG-NNN`，但该 DBG 不存在 → 报错（来源断了）。
  2. CHR **为 open**、声明来源 `DBG-NNN`，但该 DBG 的 status 不是 `done` →
     报错（活跃的 CHR 挂在一个未关闭的源上，违反「转出即关闭」）。status
     缺失、未知值或条目损坏一律按「不是 done」处理——读不懂不能当作没这回事。
  3. CHR **为 open**、声明来源 `DBG-NNN`，但该 DBG 正文没有反向写
     `转出至：CHR-NNN` → 报错（互链只写了一半，「双向」必须成对，只看目标
     存在会放过只写了半边引用的队列）。
  4. DBG 声明转出至 `CHR-NNN`，但该 CHR 不存在 → 报错（去向断了）。
  5. DBG 声明转出至 `CHR-NNN`，但该 CHR 正文没有反向写 `来源：DBG-NNN` →
     报错（同第 3 条，互链必须成对）。

「CHR 已 done、源 DBG 重新 open」不报错——那是产品确认属 bug 后的**重开**路径，
互链由正文修订记录承担，不在机械校验值域内（第 2/3 条只约束 open 的 CHR）。

## 输出契约（agent 要按它判成败，别靠读措辞）

  · 成功 → 退出码 0，stdout 第一行是机器可读的结果（编号 / `OK` / `HELD`）。
  · 失败 → 退出码非 0，stderr 一行原因。
  · 锁被别人持有 → **退出码 3**（不是 1）。这是「正常竞争」不是「出错」，调用方
    应当等待重试，而不是把它当故障上报。
  · `check-transfers` 检出问题 → **退出码 2**（与 `check_staged_gitlink.py` 同款
    约定：检出即 2，问题清单进 stderr），调用方按清单修完重跑。
  · `candidates` 检出损坏/读不懂的条目（frontmatter 解析失败、缺正文文件、
    目录名非法的条目目录）→ **退出码 2**（同「检出即 2」约定），
    stderr 逐条报出、**stdout 不给候选**——候选清单不完整时 fail closed，
    残缺清单不能当查重依据，先修队列再 claim。损坏检查总覆盖两队列：
    `--kind` 只收窄候选列举，不豁免另一队列的检查。

## 用法

    keeper_cli.py claim  --kind debug --summary "登录页白屏"
    keeper_cli.py bind   --kind debug --name opus-debugger-4bb6 --issue DBG-208
    keeper_cli.py lock   acquire --name opus-debugger-4bb6 --issue DBG-208
    keeper_cli.py lock   release --name opus-debugger-4bb6
    keeper_cli.py lock   status
    keeper_cli.py peers  --kind debug
    keeper_cli.py candidates [--kind both|debug|chore] [--json]
    keeper_cli.py check-transfers

所有子命令都接受 `--cwd <路径>` 覆盖工作目录（缺省取当前目录），用于 keeper 在
fixer worktree 里调用时指回交付根。
"""
import argparse
import json
import os
import re
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


def cmd_candidates(args):
    """列出当前交付两队列的**全部 open 条目**，供登记前语义查重。

    「一个事项一个活跃主条目」（v8 / 4.6.0）的机械面：keeper 在 claim 之前把这份
    清单逐条与手上这条比对，判断是不是同一事项。本命令**只负责把候选列全**，不
    做任何「是不是同一事项」的判断——那个判断是语义的，脚本与 hook 正则都不得
    代判（判断错了会让重复登记静默通过，判断对了也只是省一次登记，两边的代价
    不成比例）。done 条目不列入候选：它们已不活跃，不是「第二个活跃主条目」的
    竞争者。

    为什么是「全部 open」而不是关键词检索：同义表述（「表头错位」vs「列头对不
    上」）会让关键词检索静默漏判，而把候选全列出来由 keeper 逐条语义比对不存在
    这个盲区。open 条目通常在个位数到十几条，逐条扫一遍的代价低于漏判一次。

    **读不动就 fail closed**：某队列读失败（权限、目录损坏等）时报错退出（非 0），
    **绝不**把异常吞成空队列——「队列读不动」不能伪装成「没有候选」，否则 keeper
    会在残缺清单上做查重、重复登记静默通过。损坏条目（frontmatter 解析失败、
    缺正文文件、**目录名非法的条目目录**）进不了 open 候选，**它们存在时同样
    fail closed：exit 2、stdout 不给任何候选**，stderr 逐条报出损坏条目——它们
    可能本来 open，候选清单因此不完整，残缺清单被拿去查重等于没查，先修好再查重。

    `--kind` 只收窄候选列举，损坏检查总覆盖两队列——任一队列有读不懂的条目都
    exit 2，哪怕这次只列举其中一个队列。
    """
    root, delivery_id = resolve(args)
    keeper_root = os.path.join(root, keeper_paths.KEEPER_DIR)
    # `--kind` 只收窄**候选列举**；损坏检查不受它影响——「任一队列存在读不懂的
    # 条目」就说明候选清单不完整。跨队列查重的意义正是「同一事项可能正躺在另一
    # 条队列里」，另一队列的候选同样可能残缺：只查一半就 exit 0，等于在残缺
    # 清单上做查重。所以扫描总是两队列都扫，`kinds` 只决定哪些 open 进候选。
    kinds = ["debug", "chore"] if args.kind == "both" else [args.kind]
    rows = []
    unknown_rows = []
    for kind in ("debug", "chore"):
        spec = SPEC_BY_KIND[kind]
        qdir = os.path.join(keeper_root, delivery_id, spec.dir_name)
        try:
            items = queue_files.scan_frontmatter(qdir, spec)
        except Exception as e:
            die("candidates 读 %s 队列失败（%s）：队列读不动时不能当「没有候选」"
                "继续登记——先修好队列再 claim。" % (kind, e))
        # 目录级完整性：scan_frontmatter 只认 id_re 匹配的目录名，目录名非法的
        # 条目目录（DBG-abc、拷贝残留的 CHR-007(1) 之类）会被它静默跳过——它们
        # 可能装着 open 条目，候选清单因此不完整，**同样 fail closed**。白名单：
        # `archive/`（归档根）与 `_` 开头的系统目录（`_inbox/` 收截图）；`_` 前缀
        # 是既有系统目录约定（`_main`、`_inbox`），报它们会误杀真实目录。
        # 队列路径**存在但不是目录**（误 touch 出同名文件、合并残留等）也属于
        # 「读不动」：scan_frontmatter 对非目录静默返回空，等于把整个队列当成
        # 「没有条目」，照样 fail closed。
        if os.path.exists(qdir) and not os.path.isdir(qdir):
            die("candidates 读 %s 队列失败（%s 存在但不是目录）：队列读不动时不能当"
                "「没有候选」继续登记——先修好队列再 claim。" % (kind, qdir))
        if os.path.isdir(qdir):
            try:
                for name in sorted(os.listdir(qdir)):
                    if not os.path.isdir(os.path.join(qdir, name)):
                        continue
                    if queue_files.id_re(spec).match(name) or name == "archive" \
                            or name.startswith("_"):
                        continue
                    unknown_rows.append((kind, {"id": name,
                                                "_broken": "目录名不是 %s-NNN 条目，编号读不懂"
                                                % spec.prefix}))
            except Exception as e:
                die("candidates 读 %s 队列失败（%s）：队列读不动时不能当「没有候选」"
                    "继续登记——先修好队列再 claim。" % (kind, e))
        op, _dn, unk = queue_files.split_by_status(items)
        if kind in kinds:
            for fm, _p in op:
                rows.append((kind, str(fm.get("id") or ""),
                             str(fm.get("summary") or "").strip()))
        for fm, _p in unk:
            unknown_rows.append((kind, fm))
    if unknown_rows:
        # fail closed：候选清单不完整时**不给 stdout 任何候选**——残缺清单被拿去
        # 查重等于没查；stderr 逐条报出后以退出码 2 结束（与 check-transfers 的
        # 「检出即 2」同一约定），调用方按「先修队列再 claim」处置。
        for kind, fm in unknown_rows:
            sys.stderr.write("%s\t%s\t读不懂：%s（status=%r）——候选清单不完整，先修好再查重\n"
                             % (kind, str(fm.get("id") or "?"),
                                fm.get("_broken") or "status 值不在枚举内",
                                fm.get("status")))
        die("candidates 检出 %d 条损坏/读不懂的条目（见上方逐条报出）：候选清单不完整，"
            "不能据此查重——先修好队列再 claim。" % len(unknown_rows), 2)
    if args.json:
        sys.stdout.write(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
        return 0
    if not rows:
        sys.stdout.write("（当前交付两个队列没有 open 条目）\n")
        return 0
    for kind, iid, summary in rows:
        sys.stdout.write("%s\t%s\t%s\n" % (kind, iid, summary))
    return 0


# 转出互链的正文标记（形态见模块头「转出互链约定」）。只认行首精确形态，
# 其余写法（如把 DBG-NNN 塞进一句叙述里）一律不认——机械校验只对约定负责。
# 不锚定行尾：keeper 会在编号后跟一句注释（如「来源：DBG-042（规格空白转出）」），
# 行首锚定已足够把「叙述句里提到的编号」排除在值域外。
TRANSFER_SOURCE_RE = re.compile(r"^来源[:：]\s*(DBG-\d+)", re.M)
TRANSFER_TARGET_RE = re.compile(r"^转出至[:：]\s*(CHR-\d+)", re.M)


def cmd_check_transfers(args):
    """转出互链的机械完整性校验（只读，不写任何文件）。

    判据五条，见模块头「转出互链约定」。检出问题 → 退出码 2（同
    `check_staged_gitlink.py` 约定），问题清单进 stderr；全过 → 退出码 0。

    刻意不做的两件事：
      · 不判「两个自然语言事项是否相同」——那是语义判断，本轮规则明确不允许机械
        代判。
      · 不报「open 的 DBG 带着转出标记」——那是产品确认属 bug 后的重开路径
        （决策 5），互链由正文修订记录承担，不在本校验值域内；它若真的违反
        「转出即关闭」，会通过「活跃 CHR 的源必须 done」这条报出来。
    """
    root, delivery_id = resolve(args)
    keeper_root = os.path.join(root, keeper_paths.KEEPER_DIR)
    qd_debug = os.path.join(keeper_root, delivery_id, "debug")
    qd_chore = os.path.join(keeper_root, delivery_id, "chore")

    try:
        # top-level ∪ archive/<批次>/：done 条目合法归档后（archive_done.py 整目录
        # 搬走、互链标记原样保留）互链必须仍然可校验，否则转出源归档后
        # check-transfers 会把「已归档的合法 done 源」误报成「不存在」。
        chr_items = (queue_files.load_all(qd_chore, queue_files.CHORE)
                     + queue_files.load_archived(qd_chore, queue_files.CHORE))
        dbg_items = (queue_files.load_all(qd_debug, queue_files.DEBUG)
                     + queue_files.load_archived(qd_debug, queue_files.DEBUG))
    except Exception as e:
        die("check-transfers 读队列失败（%s）：读不动时不能判「互链完整」，"
            "先修好队列再校验。" % e)
    chr_by_id = {str(fm.get("id")): (fm, body)
                 for fm, body, _p in chr_items}
    dbg_by_id = {str(fm.get("id")): (fm, body)
                 for fm, body, _p in dbg_items}

    def _has_mark(body, regex, iid):
        """正文里是否有指向 iid 的固定形态标记（沿用行首精确形态的纪律）。"""
        return any(m.group(1).upper() == iid for m in regex.finditer(body or ""))

    problems = []
    for fm, body, _p in chr_items:
        cid = str(fm.get("id") or "?")
        c_status = str(fm.get("status", "")).strip()
        for m in TRANSFER_SOURCE_RE.finditer(body or ""):
            src = m.group(1).upper()
            sfm = dbg_by_id.get(src)
            if sfm is None:
                problems.append("%s 声明来源 %s，但 debug 队列里不存在该条目"
                                % (cid, src))
                continue
            if c_status == queue_files.STATUS_DONE:
                # CHR 已 done：重开路径，源 DBG 可以是 open，互链由修订记录承担。
                continue
            # 活跃 CHR 必须挂在一个已关闭的源上，且源必须反向写「转出至」。
            # 源条目损坏（frontmatter 读不懂）一律按「不是合法转出源」报错——
            # 读不懂不能当作没这回事（与 index.md 的「读不懂」桶同一原则）。
            if sfm[0].get("_broken"):
                problems.append(
                    "%s 为 open、声明来源 %s，但 %s 读不懂（%s）——"
                    "损坏条目不能作为合法转出源，先修好再校验"
                    % (cid, src, src, sfm[0].get("_broken")))
                continue
            s_status = str(sfm[0].get("status", "")).strip()
            if s_status != queue_files.STATUS_DONE:
                problems.append(
                    "%s 为 open、声明来源 %s，但 %s 的 status 是 %r，不是 done——"
                    "转出后源 DBG 必须是 done（只有一个活跃主条目）"
                    % (cid, src, src, s_status))
                continue
            if not _has_mark(sfm[1], TRANSFER_TARGET_RE, cid):
                problems.append(
                    "%s 为 open、声明来源 %s，但 %s 正文没有反向写「转出至：%s」——"
                    "双向互链必须成对写齐，只写半边等于没有互链"
                    % (cid, src, src, cid))
    for fm, body, _p in dbg_items:
        did = str(fm.get("id") or "?")
        for m in TRANSFER_TARGET_RE.finditer(body or ""):
            tgt = m.group(1).upper()
            cfm = chr_by_id.get(tgt)
            if cfm is None:
                problems.append("%s 声明转出至 %s，但 chore 队列里不存在该条目"
                                % (did, tgt))
                continue
            if not _has_mark(cfm[1], TRANSFER_SOURCE_RE, did):
                problems.append(
                    "%s 声明转出至 %s，但 %s 正文没有反向写「来源：%s」——"
                    "双向互链必须成对写齐，只写半边等于没有互链"
                    % (did, tgt, tgt, did))

    if problems:
        sys.stderr.write("\n".join(problems) + "\n")
        return 2
    sys.stdout.write("OK：转出互链完整（来源 DBG 存在且已关闭、转出标记成对；"
                     "去向 CHR 存在且来源标记成对）\n")
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

    cand = sub.add_parser(
        "candidates",
        help="列出当前交付两队列全部 open 条目，供登记前语义查重（只读）")
    cand.add_argument("--kind", choices=("both", "debug", "chore"), default="both",
                      help="查哪个队列，默认 both（决策 6 要求两队列都查）")
    cand.add_argument("--json", action="store_true")
    cand.set_defaults(func=cmd_candidates)

    ct = sub.add_parser(
        "check-transfers",
        help="转出互链机械完整性校验：CHR 来源 DBG 必须存在且为 done（只读）")
    ct.set_defaults(func=cmd_check_transfers)
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    raise SystemExit(args.func(args) or 0)
