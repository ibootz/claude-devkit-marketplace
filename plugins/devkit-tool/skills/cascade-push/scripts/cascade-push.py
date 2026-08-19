#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cascade-push.py — 嵌套 git submodule 逐层提交推送（由内向外），push 前强制出简报

发现 superproject 下所有 submodule（含多层嵌套），按路径深度降序（最内 → 最外）
逐层 git add -A → commit（有改动才提交）→ push，链式更新每一层父仓的 gitlink。

四段流程，每段一个动作：
  1. 默认（无 flag）= 简报（briefing）。逐层调查两类内容：未提交改动（含 untracked）
     与待推送 commit（`<远端 SHA>..HEAD` 逐条列 subject + 文件清单 + gitlink 标注）。
  2. --apply = 本地 commit，可逆。commit 后自动回读各层 gitlink 变化行。
  3. --push --approved = 推送，不可逆。缺 --approved 直接拒绝执行，把「Human 看过
     简报并批准」做成机械闸，而不是靠调用方自觉。
  4. 每层 push 后写后回读远端 SHA，不一致立即整体中止。

机制依据（写进 SKILL.md 与本注释，须准确）：
  - gitlink：父仓 index 里 mode 160000 的条目，指向子模块的某个 commit SHA。
  - 父仓的 commit 引用子 SHA 前，该 SHA 必须先 push 到远端，否则产生 dangling
    reference——别人 clone 父仓时拿不到子的那个 commit。
  - 故顺序恒为「最内 → 最外」：子先 commit / push，父随后 add -A（捕获 gitlink
    变化）+ commit / push。脚本按路径深度降序天然满足「子先于父」的偏序
    （子的路径必然比父深），平级 submodule 之间顺序无关。
  - 不用 `git submodule foreach --recursive` 做提交——它是「父先于子」
    （tail-recursive），方向正好相反，照搬会直接制造上面的顺序错。
  - 待推送范围以 `git ls-remote` 取到的**远端实际 SHA** 为基线，不用本地远端跟踪
    引用（refs/remotes/...）——后者是上次 fetch 的快照，可能已过期，用它算出的
    「待推送 commit」会漏或多。默认先 fetch 一次刷新对象库，--no-fetch 可关。
  - 未 init 的 submodule（空目录、没有自己的 .git）必须剔除：在其中跑 git 会沿目录
    树向上命中**上级仓**并返回上级仓的状态，exit 0、无任何警告；在这类目录上跑
    `git add -A` 会把上级仓的全部改动裹进一个无关提交。判据是
    `git -C <层> rev-parse --show-toplevel` 归一化后是否等于该层自身。

风格仿 marketplace-cache-sync/scripts/probe-refresh.py：标准库、无第三方依赖、
GIT_TERMINAL_PROMPT=0 防无凭证挂起、subprocess.run(timeout=)（macOS 默认没有
`timeout` 二进制，不用它包命令）。
"""

import argparse
import os
import re
import subprocess
import sys

# ---- 运行环境 ------------------------------------------------------------
GIT_ENV = dict(os.environ)
GIT_ENV["GIT_TERMINAL_PROMPT"] = "0"          # HTTPS 凭证不再交互式弹问
GIT_ENV["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=10"  # SSH 不弹密码
GIT_TIMEOUT = 60    # 单条 git 命令默认超时（秒）
FETCH_TIMEOUT = 120  # fetch 放宽
PUSH_TIMEOUT = 180   # push 放宽

MAX_COMMITS_SHOWN = 30   # 每层展开的待推送 commit 条数上限，超出给续查命令
MAX_FILES_PER_COMMIT = 40  # 单条 commit 展开的文件行数上限

# untracked 里疑似不该提交的形态（`git add -A` 会无差别带上它们）
SUSPICIOUS_UNTRACKED = re.compile(
    r"(^|/)(\.env(\..+)?|\.DS_Store|node_modules|__pycache__|\.venv|venv)(/|$)"
    r"|\.(log|key|pem|p12|pfx|keystore|jks|sqlite3?|db|pyc|swp|orig|rej)$"
    r"|(^|/)id_(rsa|dsa|ecdsa|ed25519)$",
    re.IGNORECASE,
)

# ---- ANSI 着色（非 tty 自动关闭）-----------------------------------------
_RED = "\033[31m"
_YEL = "\033[33m"
_GRN = "\033[32m"
_CYA = "\033[36m"
_RST = "\033[0m"


def _color(seg, text):
    return f"{seg}{text}{_RST}" if sys.stdout.isatty() else text


def red(t):
    return _color(_RED, t)


def yel(t):
    return _color(_YEL, t)


def grn(t):
    return _color(_GRN, t)


def cya(t):
    return _color(_CYA, t)


# ---- git 调用 ------------------------------------------------------------
def run_git(args, cwd=None, timeout=GIT_TIMEOUT, strip_out=True):
    """跑一条 git 命令，返回 (rc, stdout, stderr)。超时/异常不抛，返回空串。

    strip_out=False 用于 `status --porcelain` 这类**列首字符有语义**的输出：
    porcelain v1 每行前两列是 XY 状态码，unstaged-only 的行形如 ` M path`，
    整体 strip 会吃掉首行那个前导空格，把 unstaged 误读成 staged、并让路径少一个字符。
    """
    try:
        p = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            env=GIT_ENV,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = p.stdout.strip() if strip_out else p.stdout.rstrip("\n")
        return p.returncode, out, p.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s: git {' '.join(args)}"
    except Exception as e:  # noqa: BLE001 — 任何异常都吞成可报告的空结果
        return 1, "", str(e)


def git_repo_root(path=None):
    rc, out, _ = run_git(["rev-parse", "--show-toplevel"], cwd=path)
    return out if rc == 0 and out else None


def is_git_repo(path):
    return os.path.isdir(os.path.join(path, ".git")) or os.path.isfile(os.path.join(path, ".git"))


def owns_itself(abs_dir):
    """该目录是不是一个独立 git 仓的根。

    未 init 的 submodule 是空目录，在其中跑 git 会命中上级仓并 exit 0，
    返回的 toplevel 是上级仓——据此剔除。linked worktree 里 `.git` 是文件不是
    目录，故不能用 `isdir('.git')` 判，只能比 toplevel。
    """
    top = git_repo_root(abs_dir)
    if not top:
        return False
    return os.path.realpath(top) == os.path.realpath(abs_dir)


def is_detached(abs_dir):
    """detached HEAD 时 `symbolic-ref --short HEAD` 失败（rc != 0）。"""
    rc, _, _ = run_git(["symbolic-ref", "--short", "HEAD"], cwd=abs_dir)
    return rc != 0


def current_branch(abs_dir):
    rc, out, _ = run_git(["symbolic-ref", "--short", "HEAD"], cwd=abs_dir)
    return out if rc == 0 and out else None


def upstream(abs_dir):
    """返回 (remote, branch) 或 None（未配置 upstream 时）。"""
    rc, out, _ = run_git(["rev-parse", "--abbrev-ref", "@{upstream}"], cwd=abs_dir)
    if rc != 0 or "/" not in out:
        return None
    remote, _, branch = out.partition("/")
    return (remote, branch) if remote and branch else None


def status_porcelain(abs_dir):
    rc, out, _ = run_git(["status", "--porcelain"], cwd=abs_dir, strip_out=False)
    return [ln for ln in out.splitlines() if ln.strip()] if rc == 0 else []


def ls_remote_sha(abs_dir, remote, branch):
    """远端该分支的实际 SHA；分支在远端不存在时返回空串。"""
    _, out, _ = run_git(["ls-remote", remote, f"refs/heads/{branch}"], cwd=abs_dir)
    parts = out.split()
    return parts[0] if parts else ""


def object_exists(abs_dir, sha):
    rc, _, _ = run_git(["cat-file", "-e", f"{sha}^{{commit}}"], cwd=abs_dir)
    return rc == 0


def read_submodule_paths(abs_dir):
    """读该层的 .gitmodules，返回直接子模块（相对本层）的路径列表。"""
    gm = os.path.join(abs_dir, ".gitmodules")
    if not os.path.exists(gm):
        return []
    rc, out, _ = run_git(["config", "-f", gm, "--get-regexp", r"^submodule\..*\.path$"], cwd=abs_dir)
    paths = []
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            paths.append(parts[1].strip())
    return paths


# ---- 发现嵌套树 ----------------------------------------------------------
def discover(root):
    """递归收集所有层（顶层 superproject + 全部已 init 的嵌套 submodule）。

    返回 (layers, skipped)：
      layers  — list[dict]，字段 abs / rel / depth / subs（本层直接子模块相对路径）
      skipped — list[(rel, 原因)]，未 init 或目录缺失而剔除的层
    """
    layers = []
    skipped = []

    def walk(abs_dir, rel_dir, depth):
        subs = read_submodule_paths(abs_dir)
        layers.append({"abs": abs_dir, "rel": rel_dir, "depth": depth, "subs": subs})
        for sub_rel in subs:
            sub_abs = os.path.join(abs_dir, sub_rel)
            sub_rel_root = sub_rel if rel_dir == "." else os.path.normpath(os.path.join(rel_dir, sub_rel))
            if not os.path.isdir(sub_abs):
                skipped.append((sub_rel_root, "目录不存在（submodule 未 checkout）"))
                continue
            if not owns_itself(sub_abs):
                skipped.append((sub_rel_root, "未 init（无自己的 .git，跑 git 会命中上级仓）"))
                continue
            walk(sub_abs, sub_rel_root, depth + 1)

    walk(root, ".", 0)
    return layers, skipped


def label_of(rel):
    return "(root)" if rel == "." else rel


# ---- 调查：未提交改动 ----------------------------------------------------
def classify_worktree(abs_dir, sub_paths):
    """把 `git status --porcelain` 分成 staged / unstaged / untracked 三组。

    porcelain v1 每行前两字符是 XY：X=index 侧、Y=worktree 侧，`??` 为 untracked。
    子模块路径命中的行额外标注 gitlink——那一行代表的是指针移动，不是文件内容改动。
    """
    staged, unstaged, untracked = [], [], []
    for ln in status_porcelain(abs_dir):
        xy, path = ln[:2], ln[3:]
        norm = path.rstrip("/")
        tag = "  (gitlink)" if norm in sub_paths else ""
        entry = f"{xy} {path}{tag}"
        if xy == "??":
            if SUSPICIOUS_UNTRACKED.search(path):
                entry += yel("  ← 疑似不该提交")
            untracked.append(entry)
            continue
        if xy[0] != " ":
            staged.append(entry)
        if xy[1] != " ":
            unstaged.append(entry)
    return staged, unstaged, untracked


# ---- 调查：待推送 commit -------------------------------------------------
def parse_raw_files(lines):
    """解析 `git log --raw` 的 diff 行，返回 [(status, path, is_gitlink)]。

    raw 行形如 `:100644 100644 <old> <new> M\tpath`，重命名多一个路径字段。
    mode 160000 = gitlink，代表子模块指针移动。
    """
    files = []
    for ln in lines:
        if not ln.startswith(":"):
            continue
        head, _, paths = ln.partition("\t")
        fields = head[1:].split()
        if len(fields) < 5:
            continue
        old_mode, new_mode, status = fields[0], fields[1], fields[4]
        is_gitlink = "160000" in (old_mode, new_mode)
        path = paths.replace("\t", " → ") if paths else "(未知路径)"
        files.append((status, path, is_gitlink))
    return files


def pending_commits(abs_dir, base):
    """返回 base..HEAD 的 commit 列表（时间正序，最早的在前）。

    每条：sha / short / date / author / subject / merge(bool) / files。
    """
    # 不加 --no-abbrev：它会让 %h 也退回全长 SHA，简报里读着累；raw 行只取 mode 判 gitlink，
    # 缩写的 blob SHA 够用。
    fmt = "%x00%H%x1f%h%x1f%ad%x1f%an%x1f%s%x1f%P"
    rc, out, _ = run_git(
        ["log", "--reverse", "--date=short", f"--format={fmt}", "--raw", f"{base}..HEAD"],
        cwd=abs_dir,
    )
    if rc != 0:
        return None  # 范围算不出来（base 不在本地对象库等）
    commits = []
    for block in out.split("\x00"):
        block = block.strip("\n")
        if not block:
            continue
        head, _, rest = block.partition("\n")
        parts = head.split("\x1f")
        if len(parts) < 6:
            continue
        sha, short, date, author, subject, parents = parts[:6]
        commits.append({
            "sha": sha,
            "short": short,
            "date": date,
            "author": author,
            "subject": subject,
            "merge": len(parents.split()) > 1,
            "files": parse_raw_files(rest.splitlines()),
        })
    return commits


def ahead_behind(abs_dir, base):
    rc, out, _ = run_git(["rev-list", "--left-right", "--count", f"{base}...HEAD"], cwd=abs_dir)
    if rc != 0:
        return (None, None)
    parts = out.split()
    if len(parts) != 2:
        return (None, None)
    try:
        return (int(parts[1]), int(parts[0]))  # (ahead, behind)
    except ValueError:
        return (None, None)


def unpushed_other_branches(abs_dir, cur_branch):
    """本地其它分支上还有多少 commit 没进任何远端——本次不推，只提示。"""
    rc, out, _ = run_git(
        ["log", "--format=%H %D", "--branches", "--not", "--remotes"], cwd=abs_dir
    )
    if rc != 0 or not out:
        return 0
    total = 0
    for ln in out.splitlines():
        refs = ln.partition(" ")[2]
        if cur_branch and re.search(rf"(^|,\s*)(HEAD -> )?{re.escape(cur_branch)}(,|$)", refs):
            continue
        total += 1
    return total


def survey_layer(layer, no_fetch):
    """把一层调查透：未提交改动 + 待推送 commit + push 目标 + 阻塞判定。"""
    a, rel = layer["abs"], layer["rel"]
    sub_paths = {p.rstrip("/") for p in layer["subs"]}
    info = {
        "label": label_of(rel),
        "rel": rel,
        "depth": layer["depth"],
        "detached": is_detached(a),
        "branch": current_branch(a),
        "upstream": None,
        "remote_sha": "",
        "base": None,
        "ahead": None,
        "behind": None,
        "commits": None,
        "fetch_warn": "",
        "other_branch_unpushed": 0,
    }
    info["staged"], info["unstaged"], info["untracked"] = classify_worktree(a, sub_paths)
    info["dirty"] = bool(info["staged"] or info["unstaged"] or info["untracked"])

    if info["detached"]:
        return info

    up = upstream(a)
    info["upstream"] = up
    info["other_branch_unpushed"] = unpushed_other_branches(a, info["branch"])
    if not up:
        return info

    remote, branch = up
    if not no_fetch:
        rc, _, err = run_git(["fetch", remote, branch], cwd=a, timeout=FETCH_TIMEOUT)
        if rc != 0:
            info["fetch_warn"] = err.splitlines()[0] if err else "fetch 失败（原因未回报）"
    info["remote_sha"] = ls_remote_sha(a, remote, branch)

    if info["remote_sha"] and object_exists(a, info["remote_sha"]):
        info["base"] = info["remote_sha"]
    elif info["remote_sha"]:
        # 远端有该分支但本地没这个对象（fetch 被跳过或失败）——退回跟踪引用并标注
        info["base"] = f"{remote}/{branch}"
        info["fetch_warn"] = (info["fetch_warn"] + "；" if info["fetch_warn"] else "") + \
            "远端 SHA 不在本地对象库，待推送范围按本地跟踪引用估算，可能不准"
    else:
        info["base"] = None  # 远端还没有这个分支

    if info["base"]:
        info["ahead"], info["behind"] = ahead_behind(a, info["base"])
        info["commits"] = pending_commits(a, info["base"])
    else:
        rc, out, _ = run_git(["rev-list", "--count", "HEAD"], cwd=a)
        info["ahead"] = int(out) if rc == 0 and out.isdigit() else None
        info["behind"] = 0
        info["commits"] = pending_commits(a, "--root") if (info["ahead"] or 0) <= MAX_COMMITS_SHOWN else None
    return info


# ---- 简报输出 ------------------------------------------------------------
def print_worktree_block(info):
    n = len(info["staged"]) + len(info["unstaged"]) + len(info["untracked"])
    if not n:
        print("    未提交改动：无")
        return
    print(f"    未提交改动：staged {len(info['staged'])} / unstaged {len(info['unstaged'])} "
          f"/ untracked {len(info['untracked'])}")
    for title, group in (("staged", info["staged"]), ("unstaged", info["unstaged"]),
                         ("untracked", info["untracked"])):
        if not group:
            continue
        print(f"      [{title}]")
        for entry in group:  # 全量列出，不截断——这是 --apply 时 add -A 的实际范围
            print(f"        {entry}")


def print_commits_block(info):
    commits = info["commits"]
    ahead = info["ahead"]
    if info["base"] is None and not info["upstream"]:
        return
    if info["base"] is None:
        print(yel(f"    待推送 commit：远端还没有 {info['upstream'][0]}/{info['upstream'][1]} "
                  f"分支，本地全部 {ahead if ahead is not None else '?'} 条 commit 都会是首推内容"))
    elif not ahead:
        print("    待推送 commit：无（本地与远端同步）")
    else:
        print(grn(f"    待推送 commit：{ahead} 条") + f"（远端领先 {info['behind']} 条）")
    if commits is None:
        print("      （条数过多或范围算不出，逐条清单略；用 git -C <该层> log <base>..HEAD --stat 自查）")
        return
    for i, c in enumerate(commits[:MAX_COMMITS_SHOWN], 1):
        tag = "  [merge commit]" if c["merge"] else ""
        print(f"      {i}) {c['short']}  {c['date']}  {c['author']}  {c['subject']}{tag}")
        if c["merge"] and not c["files"]:
            print("           （merge commit，文件清单需 git show -m 展开）")
            continue
        for status, path, is_gitlink in c["files"][:MAX_FILES_PER_COMMIT]:
            mark = cya("  ← gitlink 指针移动") if is_gitlink else ""
            print(f"           {status}  {path}{mark}")
        if len(c["files"]) > MAX_FILES_PER_COMMIT:
            print(f"           ... 还有 {len(c['files']) - MAX_FILES_PER_COMMIT} 个文件，"
                  f"用 git -C {info['rel']} show --stat {c['short']} 看全")
    if len(commits) > MAX_COMMITS_SHOWN:
        print(f"      ... 还有 {len(commits) - MAX_COMMITS_SHOWN} 条 commit 未展开，"
              f"用 git -C {info['rel']} log {info['base'][:10]}..HEAD --stat 看全")


def do_brief(layers, skipped, no_fetch):
    """逐层调查并打印简报。返回 exit code：0 可继续，2 有硬阻塞。"""
    print("嵌套 submodule 推送简报（由内向外，depth 大的先处理）\n")
    if skipped:
        print(yel(f"已剔除 {len(skipped)} 个不是独立 git 仓的层（在它们上面跑 git add -A "
                  f"会裹进上级仓的改动）："))
        for rel, why in skipped:
            print(f"    {rel} — {why}")
        print()

    infos = [survey_layer(layer, no_fetch) for layer in layers]

    detached, no_upstream, behind_layers, need_commit, need_push = [], [], [], 0, 0
    for info in infos:
        head = f"── depth {info['depth']}  {info['label']}"
        if info["detached"]:
            print(red(f"{head}  [detached HEAD]"))
            detached.append(info["label"])
            print_worktree_block(info)
            print()
            continue
        up = info["upstream"]
        if up:
            target = f"{up[0]}/{up[1]}"
            rsha = info["remote_sha"][:10] if info["remote_sha"] else "远端无此分支"
            print(f"{head}  [{info['branch']} → {target}，远端当前 {rsha}]")
        else:
            print(f"{head}  [{info['branch']}]" + yel("  无 upstream，push 会失败"))
            no_upstream.append(info["label"])
        if info["fetch_warn"]:
            print(yel(f"    ⚠ 远端信息可能不新：{info['fetch_warn']}"))
        print_worktree_block(info)
        print_commits_block(info)
        if info["other_branch_unpushed"]:
            print(yel(f"    另有 {info['other_branch_unpushed']} 条 commit 在本地其它分支上未进远端"
                      f"（本次只推当前分支 {info['branch']}，它们不会被推）"))
        if info["dirty"]:
            need_commit += 1
        if info["ahead"]:
            need_push += 1
        if info["behind"]:
            behind_layers.append(f"{info['label']}（落后 {info['behind']} 条）")
        print()

    print(f"汇总：共 {len(infos)} 层；{need_commit} 层有未提交改动；{need_push} 层有待推送 commit。")

    blocked = False
    if detached:
        print(red(f"⚠ {len(detached)} 层处于 detached HEAD，无法 commit/push：{', '.join(detached)}"))
        print("   修复：在各层 git checkout <branch>（或 git checkout -b <new-branch>）后重跑简报。")
        blocked = True
    if behind_layers:
        print(red(f"⚠ {len(behind_layers)} 层远端领先本地，push 会被拒（非 fast-forward）："
                  f"{', '.join(behind_layers)}"))
        print("   修复：在该层先 git pull --rebase（或 cascade-pull），再重跑简报。")
        blocked = True
    if no_upstream:
        print(yel(f"⚠ {len(no_upstream)} 层无 upstream 分支，--push 会失败：{', '.join(no_upstream)}"))
        print("   修复：先 git -C <该层> push -u <remote> <branch>。")

    print("\n把上面的简报交 Human 逐层过一遍，取得批准后：")
    print("  提交：python3 cascade-push.py --apply --message '<commit message>'")
    print("  推送：python3 cascade-push.py --push --approved")
    print("  （--approved 表示 Human 已看过本简报并批准推送；缺它 --push 直接拒绝执行）")
    return 2 if blocked else 0


# ---- apply：逐层 commit -------------------------------------------------
def gitlink_lines(abs_dir, sub_paths):
    """HEAD 这次提交里，哪些行是 gitlink 指针移动——「gitlink 关系处理好」的判据。"""
    rc, out, _ = run_git(["show", "--raw", "--no-abbrev", "--format=", "HEAD"], cwd=abs_dir)
    if rc != 0:
        return []
    return [(s, p) for s, p, is_gl in parse_raw_files(out.splitlines()) if is_gl]


def do_apply(layers, message):
    """layers 已按 depth 降序。逐层 add -A → commit（有 staged 才提交）。"""
    committed = []
    for layer in layers:
        a, rel = layer["abs"], layer["rel"]
        sub_paths = {p.rstrip("/") for p in layer["subs"]}
        lbl = label_of(rel)
        if is_detached(a):
            print(red(f"中止：{lbl} 处于 detached HEAD，无法 commit。"))
            print(f"   修复：git -C {rel} checkout <branch> 后重跑。已提交层: "
                  f"{', '.join(committed) if committed else '（无）'}")
            return 2
        run_git(["add", "-A"], cwd=a)
        rc, _, _ = run_git(["diff", "--cached", "--quiet"], cwd=a)
        if rc == 0:
            print(f"跳过（无改动）: {lbl}")
            continue
        msg = f"[{lbl}] {message}"
        rc, out, err = run_git(["commit", "-m", msg], cwd=a)
        if rc != 0:
            print(red(f"commit 失败 {lbl}: {err or out}"))
            return 2
        committed.append(lbl)
        print(grn(f"committed: {lbl}"))
        gl = gitlink_lines(a, sub_paths)
        if gl:
            for status, path in gl:
                print(cya(f"    gitlink 已更新  {status}  {path}"))
        elif sub_paths:
            print(yel(f"    本层有 {len(sub_paths)} 个子模块，但这次 commit 没有 gitlink 变化行"
                      f"（子模块本轮无新提交时正常）"))
    print(f"\n共提交 {len(committed)} 层: {', '.join(committed) if committed else '（无）'}")
    return 0


# ---- push：逐层 push + 写后回读 -----------------------------------------
def do_push(layers):
    """layers 已按 depth 降序（子先于父）。逐层 push，每层写后回读 SHA。"""
    results = []
    for layer in layers:
        a, rel = layer["abs"], layer["rel"]
        lbl = label_of(rel)
        if is_detached(a):
            print(red(f"中止：{lbl} 处于 detached HEAD，无法 push。"))
            _print_push_partial(results, lbl)
            return 2
        up = upstream(a)
        if not up:
            print(red(f"中止：{lbl} 无 upstream 分支，无法 push。"))
            print(f"   修复：git -C {rel} push -u <remote> <branch>。")
            _print_push_partial(results, lbl)
            return 2
        remote, branch = up
        rc, out, err = run_git(["push", remote, f"HEAD:{branch}"], cwd=a, timeout=PUSH_TIMEOUT)
        if rc != 0:
            print(red(f"push 失败 {lbl}: {err or out}"))
            _print_push_partial(results, lbl)
            return 2
        # 写后回读：本地 HEAD 与远端该分支 SHA 必须一致
        _, local_sha, _ = run_git(["rev-parse", "HEAD"], cwd=a)
        remote_sha = ls_remote_sha(a, remote, branch)
        ok = bool(local_sha) and local_sha == remote_sha
        results.append((lbl, local_sha[:10], remote_sha[:10], ok))
        mark = grn("OK") if ok else red("MISMATCH")
        print(f"pushed [{mark}] {lbl}: local {local_sha[:10]} / remote {remote_sha[:10]}")
        if not ok:
            print(red(f"中止：{lbl} push 后写后回读不一致（本地 {local_sha} vs 远端 {remote_sha}）。"))
            _print_push_partial(results, lbl)
            return 2
    print("\npush 写后回读对照:")
    for lbl, l, r, ok in results:
        flag = "OK" if ok else "MISMATCH"
        print(f"  {lbl:32} local {l}  remote {r}  {flag}")
    return 0


def _print_push_partial(results, aborted):
    done = [r[0] for r in results]
    print(yel(f"已成功 push: {', '.join(done) if done else '（无）'}；{aborted} 及更外层未推送。"))


# ---- main ----------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="嵌套 git submodule 逐层提交推送（由内向外，链式更新 gitlink），push 前强制出简报"
    )
    ap.add_argument("--root", help="superproject 根目录，缺省取 git rev-parse --show-toplevel")
    ap.add_argument("--message", "-m", help="commit message（--apply 时必传，每层前缀 [层路径]）")
    ap.add_argument("--apply", action="store_true", help="执行 commit（逐层 add -A + commit，本地可逆）")
    ap.add_argument("--push", action="store_true", help="执行 push（逐层 push + 写后回读，不可逆，须配 --approved）")
    ap.add_argument("--approved", action="store_true",
                    help="声明 Human 已看过简报并批准推送；--push 缺它直接拒绝执行")
    ap.add_argument("--no-fetch", action="store_true",
                    help="简报阶段不 fetch（离线场景）；此时待推送范围按本地跟踪引用估算，可能不准")
    args = ap.parse_args()

    root = args.root or git_repo_root() or os.getcwd()
    root = os.path.abspath(root)
    if not is_git_repo(root):
        print(red(f"不是 git 仓库: {root}"))
        return 2

    if args.push and not args.approved:
        print(red("拒绝执行 --push：缺 --approved。"))
        print("push 是不可逆的外部写。先跑一次不带 flag 的简报，把每层的未提交改动与待推送")
        print("commit 逐条交 Human 过目、取得当轮批准，再带 --approved 重跑：")
        print("  python3 cascade-push.py                    # 出简报")
        print("  python3 cascade-push.py --push --approved   # 批准后推送")
        return 2

    layers, skipped = discover(root)
    layers_sorted = sorted(layers, key=lambda x: -x["depth"])  # 由内向外

    if len(layers) == 1 and not skipped:
        print(yel(f"未发现 submodule（无 .gitmodules / 无嵌套），仅顶层仓 {root}。"))
        print("本工具面向「类 submodule 嵌套」项目；单仓直接用 git commit / git push 即可。\n")

    if args.apply and not args.message:
        print(red("--apply 需要 --message <msg>（不自动编 message，避免 garbage commit）"))
        return 2

    if args.apply:
        rc = do_apply(layers_sorted, args.message)
        if rc != 0:
            return rc
    if args.push:
        rc = do_push(layers_sorted)
        if rc != 0:
            return rc
    if not args.apply and not args.push:
        return do_brief(layers_sorted, skipped, args.no_fetch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
