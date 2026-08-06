#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cascade-push.py — 嵌套 git submodule 逐层提交推送（由内向外）

发现 superproject 下所有 submodule（含多层嵌套），按路径深度降序（最内 → 最外）
逐层 git add -A → commit（有改动才提交）→ push，链式更新每一层父仓的 gitlink。
默认 dry-run 只打印计划，不动手；--apply 才 commit（本地、可逆）；--push 才 push
（不可逆，独立显式动作）。三者可组合，把不可逆的 push 永远隔成单独步骤。

机制依据（写进 SKILL.md 与本注释，须准确）：
  - gitlink：父仓 index 里 mode 160000 的条目，指向子模块的某个 commit SHA。
  - 父仓的 commit 引用子 SHA 前，该 SHA 必须先 push 到远端，否则产生 dangling
    reference——别人 clone 父仓时拿不到子的那个 commit。
  - 故顺序恒为「最内 → 最外」：子先 commit / push，父随后 add -A（捕获 gitlink
    变化）+ commit / push。脚本按路径深度降序天然满足「子先于父」的偏序
    （子的路径必然比父深），平级 submodule 之间顺序无关。
  - 不用 `git submodule foreach --recursive` 做提交——它是「父先于子」
    （tail-recursive），方向正好相反，照搬会直接制造上面的顺序错。

风格仿 marketplace-cache-sync/scripts/probe-refresh.py：标准库、无第三方依赖、
GIT_TERMINAL_PROMPT=0 防无凭证挂起、subprocess.run(timeout=)（macOS 默认没有
`timeout` 二进制，不用它包命令）。
"""

import argparse
import os
import subprocess
import sys

# ---- 运行环境 ------------------------------------------------------------
GIT_ENV = dict(os.environ)
GIT_ENV["GIT_TERMINAL_PROMPT"] = "0"          # HTTPS 凭证不再交互式弹问
GIT_ENV["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=10"  # SSH 不弹密码
GIT_TIMEOUT = 60   # 单条 git 命令默认超时（秒）
PUSH_TIMEOUT = 180  # push 单独放宽

# ---- ANSI 着色（非 tty 自动关闭）-----------------------------------------
_RED = "\033[31m"
_YEL = "\033[33m"
_GRN = "\033[32m"
_RST = "\033[0m"


def _color(seg, text):
    return f"{seg}{text}{_RST}" if sys.stdout.isatty() else text


def red(t):
    return _color(_RED, t)


def yel(t):
    return _color(_YEL, t)


def grn(t):
    return _color(_GRN, t)


# ---- git 调用 ------------------------------------------------------------
def run_git(args, cwd=None, timeout=GIT_TIMEOUT):
    """跑一条 git 命令，返回 (rc, stdout, stderr)。超时/异常不抛，返回空串。"""
    try:
        p = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            env=GIT_ENV,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s: git {' '.join(args)}"
    except Exception as e:  # noqa: BLE001 — 任何异常都吞成可报告的空结果
        return 1, "", str(e)


def git_repo_root(path=None):
    rc, out, _ = run_git(["rev-parse", "--show-toplevel"], cwd=path)
    return out if rc == 0 and out else None


def is_git_repo(path):
    return os.path.isdir(os.path.join(path, ".git")) or os.path.isfile(os.path.join(path, ".git"))


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
    rc, out, _ = run_git(["status", "--porcelain"], cwd=abs_dir)
    return [ln for ln in out.splitlines() if ln.strip()] if rc == 0 else []


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
    """递归收集所有层（顶层 superproject + 全部嵌套 submodule）。

    返回 list[dict]，每层字段：abs（绝对路径）/ rel（相对 root 的路径）/ depth。
    """
    layers = []

    def walk(abs_dir, rel_dir, depth):
        layers.append({"abs": abs_dir, "rel": rel_dir, "depth": depth})
        for sub_rel in read_submodule_paths(abs_dir):
            sub_abs = os.path.join(abs_dir, sub_rel)
            sub_rel_root = sub_rel if rel_dir == "." else os.path.normpath(os.path.join(rel_dir, sub_rel))
            if os.path.isdir(sub_abs):
                walk(sub_abs, sub_rel_root, depth + 1)

    walk(root, ".", 0)
    return layers


def label_of(rel):
    return "(root)" if rel == "." else rel


# ---- dry-run：打印计划 --------------------------------------------------
def do_plan(layers):
    """layers 已按 depth 降序（由内向外）。打印计划，不执行。"""
    need_commit = 0
    detached_layers = []
    no_upstream = []
    print("嵌套 submodule 提交推送计划（由内向外，depth 大的先处理）:\n")
    for layer in layers:
        a, rel, depth = layer["abs"], layer["rel"], layer["depth"]
        changes = status_porcelain(a)
        detached = is_detached(a)
        up = None if detached else upstream(a)
        lbl = label_of(rel)
        n = len(changes)

        dtag = red("  [detached HEAD]") if detached else ""
        if detached:
            utag = ""
        elif up:
            utag = f"  push -> {up[0]}/{up[1]}"
        else:
            utag = yel("  (无 upstream，push 前需 push -u 设置)")
            no_upstream.append(lbl)

        ctag = grn(f"需 commit（{n} 项改动）") if n else "无改动（将跳过）"
        print(f"  depth {depth}  {lbl}{dtag}")
        print(f"      {ctag}{utag}")
        if n:
            for line in changes[:15]:
                print(f"        {line}")
            if n > 15:
                print(f"        ... 还有 {n - 15} 项")
            need_commit += 1
        if detached:
            detached_layers.append(lbl)

    print(f"\n共 {len(layers)} 层，{need_commit} 层需 commit。")
    if detached_layers:
        print(red(f"⚠ {len(detached_layers)} 层处于 detached HEAD，须先切到分支才能 commit/push: "
                  f"{', '.join(detached_layers)}"))
        print("   修复：在各层目录 git checkout <branch>，或 git checkout -b <new-branch>，再重跑。")
        return 2
    if no_upstream:
        print(yel(f"⚠ {len(no_upstream)} 层无 upstream 分支，--push 会失败: {', '.join(no_upstream)}"))
        print("   修复：先 git -C <该层> push -u <remote> <branch>。")
    print("\n确认无误后：")
    print("  先提交：python3 cascade-push.py --apply --message '<commit message>'")
    print("  再推送：python3 cascade-push.py --push")
    print("  或一并：python3 cascade-push.py --apply -m '<msg>' --push")
    return 0


# ---- apply：逐层 commit -------------------------------------------------
def do_apply(layers, message):
    """layers 已按 depth 降序。逐层 add -A → commit（有 staged 才提交）。"""
    committed = []
    for layer in layers:
        a, rel = layer["abs"], layer["rel"]
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
        _, rem_out, _ = run_git(["ls-remote", remote, f"refs/heads/{branch}"], cwd=a)
        remote_sha = rem_out.split()[0] if rem_out.split() else ""
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
        description="嵌套 git submodule 逐层提交推送（由内向外，链式更新 gitlink）"
    )
    ap.add_argument("--root", help="superproject 根目录，缺省取 git rev-parse --show-toplevel")
    ap.add_argument("--message", "-m", help="commit message（--apply 时必传，每层前缀 [层路径]）")
    ap.add_argument("--apply", action="store_true", help="执行 commit（逐层 add -A + commit，本地可逆）")
    ap.add_argument("--push", action="store_true", help="执行 push（逐层 push + 写后回读，不可逆）")
    args = ap.parse_args()

    root = args.root or git_repo_root() or os.getcwd()
    root = os.path.abspath(root)
    if not is_git_repo(root):
        print(red(f"不是 git 仓库: {root}"))
        return 2

    layers = discover(root)
    layers_sorted = sorted(layers, key=lambda x: -x["depth"])  # 由内向外

    if len(layers) == 1:
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
        return do_plan(layers_sorted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
