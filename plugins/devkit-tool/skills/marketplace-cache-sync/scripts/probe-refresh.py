#!/usr/bin/env python3
"""探测「哪些 marketplace / 哪些插件真的需要刷新」，把 claude CLI 的调用次数降到最低。

背景：`claude plugin update <id>` 即使什么都不用做（回执 already at the latest version），
本机实测仍固定耗时约 25 秒；而它在无更新时对 installed_plugins.json 是零改动的。
所以「跳过一次必然 no-op 的 update」与「跑一次 no-op 的 update」结果完全等价，只是省掉 25 秒。
本脚本负责算出那个「必然 no-op」的集合，并把它从待刷清单里剔掉。

两个阶段必须分开跑，顺序不能颠倒：

  --stage market   探测各 marketplace 远端是否有新提交（并发 git ls-remote，本机 17 个约 5 秒）。
                   输出需要执行 `claude plugin marketplace update <name>` 的市场名单。
  --stage plugin   在市场已更新之后，算出真正需要 `claude plugin update` 的记录清单。
                   市场仓内源插件比版本号（纯本地读）；url 源插件并发 ls-remote 比 commit sha。

输出一律是「给人看的诊断 + 机器可读清单文件」两部分，清单文件路径见 --out 参数。
"""

import argparse
import concurrent.futures as futures
import json
import os
import subprocess
import sys
import time

PLUGINS_HOME = os.path.expanduser("~/.claude/plugins")
MARKETPLACES = os.path.join(PLUGINS_HOME, "marketplaces")
INSTALLED = os.path.join(PLUGINS_HOME, "installed_plugins.json")
USER_SETTINGS = os.path.expanduser("~/.claude/settings.json")

# 走 ssh 的源在无凭证时会挂起等交互，这两个变量让它直接失败而不是卡住。
GIT_ENV = dict(
    os.environ,
    GIT_TERMINAL_PROMPT="0",
    GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=8",
)


def run_git(args, timeout=25):
    """跑一条 git 命令，返回 stdout（失败或超时返回空串）。

    注意不要用 shell 的 `timeout` 命令包装——macOS 默认没有这个二进制，
    包上去会让每条命令瞬间失败、被误判成「远端探测全挂」。这里用 subprocess 自带的超时。
    """
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, env=GIT_ENV, timeout=timeout
        )
        return r.stdout.strip()
    except Exception:
        return ""


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def marketplace_manifest(mkt):
    """读某个市场的 marketplace.json（两种可能的位置都试）。"""
    for rel in (".claude-plugin/marketplace.json", "marketplace.json"):
        data = load_json(os.path.join(MARKETPLACES, mkt, rel))
        if data:
            return data
    return None


def marketplace_entry(mkt, plugin):
    data = marketplace_manifest(mkt)
    if not data:
        return None
    entries = data.get("plugins")
    if not isinstance(entries, list):
        return None
    for e in entries:
        if isinstance(e, dict) and e.get("name") == plugin:
            return e
    return None


def source_version(mkt, entry):
    """取「市场源里该插件当前声明的版本号」。

    marketplace.json 的条目上通常有 version；没有时回落去读该插件目录自己的 plugin.json。
    两处都拿不到返回 None，调用方按「判不了、保守刷一次」处理。
    """
    v = entry.get("version")
    if v:
        return v
    src = entry.get("source")
    if isinstance(src, str):
        base = os.path.join(MARKETPLACES, mkt, src.lstrip("./"))
        for rel in (".claude-plugin/plugin.json", "plugin.json"):
            data = load_json(os.path.join(base, rel))
            if data and data.get("version"):
                return data["version"]
    return None


def is_enabled(pid, rec):
    """判断某条安装记录当前是否处于 enabled。

    user scope 读 ~/.claude/settings.json；project/local scope 读该项目目录下的 settings。
    这样做是为了避开 `claude plugin list --json`——那条命令本机实测要 23 秒。
    key 不存在时按未启用处理（installed 但从未 enable 的插件不需要刷）。
    """
    scope = rec.get("scope")
    if scope == "user":
        cfg = load_json(USER_SETTINGS, {}) or {}
        return bool((cfg.get("enabledPlugins") or {}).get(pid))
    ppath = rec.get("projectPath")
    if not ppath:
        return False
    for name in ("settings.json", "settings.local.json"):
        cfg = load_json(os.path.join(ppath, ".claude", name), {}) or {}
        if (cfg.get("enabledPlugins") or {}).get(pid):
            return True
    return False


# ---------------------------------------------------------------- stage: market


def stage_market(out_path, only_enabled=True):
    rows = []
    for name in sorted(os.listdir(MARKETPLACES)):
        d = os.path.join(MARKETPLACES, name)
        if not os.path.isdir(d):
            continue
        rows.append((name, d, os.path.isdir(os.path.join(d, ".git"))))

    def probe(row):
        name, d, has_git = row
        if not has_git:
            # 例如官方市场：按内容哈希做整体快照同步（只有 .gcs-sha，没有 .git），
            # 无法用 ls-remote 探。记下当前 .gcs-sha，无条件更新一次后再比对它是否变化。
            sha = ""
            p = os.path.join(d, ".gcs-sha")
            if os.path.isfile(p):
                try:
                    sha = open(p, encoding="utf-8").read().strip()[:12]
                except Exception:
                    pass
            return (name, "NO_GIT", "", "", sha)
        local = run_git(["git", "-C", d, "rev-parse", "HEAD"])
        out = run_git(["git", "-C", d, "ls-remote", "origin", "HEAD"])
        remote = out.split("\t")[0] if out else ""
        if not remote:
            return (name, "PROBE_FAIL", local, "", "")
        if remote == local:
            return (name, "SAME", local, remote, "")
        return (name, "STALE", local, remote, "")

    t0 = time.time()
    with futures.ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(probe, rows))
    elapsed = time.time() - t0

    need = [r[0] for r in results if r[1] in ("STALE", "NO_GIT", "PROBE_FAIL")]
    with open(out_path, "w", encoding="utf-8") as f:
        for n in need:
            f.write(n + "\n")

    print(f"=== 阶段一：marketplace 远端探测（{len(rows)} 个，耗时 {elapsed:.1f}s）===")
    for name, state, local, remote, gcs in sorted(results, key=lambda x: (x[1], x[0])):
        if state == "SAME":
            print(f"  SAME       {name}  (HEAD {local[:8]})")
        elif state == "STALE":
            print(f"  STALE      {name}  {local[:8]} -> {remote[:8]}  需要 update")
        elif state == "NO_GIT":
            print(f"  NO_GIT     {name}  gcs-sha={gcs or '?'}  无法探测，无条件 update 一次")
        else:
            print(f"  PROBE_FAIL {name}  探测失败（网络/凭证），保守起见列入 update")
    print(f"\n需要执行 marketplace update 的市场 {len(need)} 个，已写入 {out_path}")
    if need:
        print("  " + " ".join(need))
    skipped = len(rows) - len(need)
    print(f"跳过 {skipped} 个已是最新的市场（每个约省 4~60s 的 clone）")
    return need


# ---------------------------------------------------------------- stage: plugin


def stage_plugin(out_path, only_enabled=True):
    data = load_json(INSTALLED, {}) or {}
    plugins = data.get("plugins", {})

    inrepo, urlsrc, unknown, disabled = [], [], [], 0
    for pid, recs in plugins.items():
        plugin, _, mkt = pid.rpartition("@")
        for rec in recs:
            if only_enabled and not is_enabled(pid, rec):
                disabled += 1
                continue
            entry = marketplace_entry(mkt, plugin)
            if not entry:
                unknown.append((pid, rec, "市场清单里没有该插件条目"))
                continue
            src = entry.get("source")
            if isinstance(src, dict) and src.get("source") == "url":
                urlsrc.append((pid, rec, src.get("url"), src.get("ref") or "HEAD"))
            elif isinstance(src, str):
                inrepo.append((pid, rec, mkt, entry))
            else:
                unknown.append((pid, rec, f"未识别的 source 形态：{src!r}"))

    need, skip, why = [], [], []

    # (1) 市场仓内源：比版本号。这正是 CLI 判定 already at the latest version 的依据。
    for pid, rec, mkt, entry in inrepo:
        cur = rec.get("version")
        src_ver = source_version(mkt, entry)
        install_path = rec.get("installPath") or ""
        if install_path and not os.path.isdir(install_path):
            need.append((pid, rec))
            why.append((pid, rec, f"缓存目录不存在：{install_path}"))
        elif src_ver is None:
            need.append((pid, rec))
            why.append((pid, rec, "市场源未声明版本号，判不了，保守刷一次"))
        elif src_ver != cur:
            need.append((pid, rec))
            why.append((pid, rec, f"版本号落后：{cur} -> {src_ver}"))
        else:
            skip.append((pid, rec, f"版本号一致（{cur}）"))

    # (2) url 源（插件内容在独立 git 仓里，不在市场仓内）：
    #     installed_plugins.json 里的 gitCommitSha 就是那个独立仓的 commit sha，可以直接比。
    #     这类插件的 update 最慢——CLI 每次都要重新 clone 那个仓，也是 temp_git_* 残留的来源。
    def probe_url(item):
        pid, rec, url, ref = item
        if not url:
            return (item, "", "url 缺失")
        out = run_git(["git", "ls-remote", url, ref])
        return (item, out.split("\t")[0] if out else "", "")

    t0 = time.time()
    with futures.ThreadPoolExecutor(max_workers=16) as ex:
        url_results = list(ex.map(probe_url, urlsrc)) if urlsrc else []
    url_elapsed = time.time() - t0

    for (pid, rec, url, ref), remote, err in url_results:
        recorded = rec.get("gitCommitSha") or ""
        install_path = rec.get("installPath") or ""
        if install_path and not os.path.isdir(install_path):
            need.append((pid, rec))
            why.append((pid, rec, f"缓存目录不存在：{install_path}"))
        elif not remote:
            need.append((pid, rec))
            why.append((pid, rec, f"远端探测失败（{err or '网络/凭证'}），保守刷一次"))
        elif remote != recorded:
            need.append((pid, rec))
            why.append((pid, rec, f"独立仓有新提交：{recorded[:8]} -> {remote[:8]}"))
        else:
            skip.append((pid, rec, f"独立仓 sha 一致（{recorded[:8]}）"))

    for pid, rec, reason in unknown:
        need.append((pid, rec))
        why.append((pid, rec, reason))

    def fmt(rec):
        return f"{rec.get('scope')}|{rec.get('projectPath') or ''}"

    with open(out_path, "w", encoding="utf-8") as f:
        for pid, rec in need:
            f.write(f"{pid}|{rec.get('scope')}|{rec.get('projectPath') or ''}\n")

    print(f"=== 阶段二：插件层探测（url 源并发探测 {len(urlsrc)} 个，耗时 {url_elapsed:.1f}s）===")
    print(f"  市场仓内源 {len(inrepo)} 条 / url 独立仓源 {len(url_results)} 条 / 判不了 {len(unknown)} 条")
    if only_enabled:
        print(f"  已按 enabled 过滤掉 {disabled} 条未启用记录")
    print(f"\n--- 需要刷新 {len(need)} 条 ---")
    for pid, rec, reason in why:
        tail = f"  @ {rec.get('projectPath')}" if rec.get("projectPath") else ""
        print(f"  {pid}  [{rec.get('scope')}]  {reason}{tail}")
    print(f"\n--- 可跳过 {len(skip)} 条（跑 update 必然是 no-op，每条约省 25s）---")
    for pid, rec, reason in skip[:80]:
        tail = f"  @ {rec.get('projectPath')}" if rec.get("projectPath") else ""
        print(f"  {pid}  [{rec.get('scope')}]  {reason}{tail}")
    saved = len(skip) * 25
    print(
        f"\n清单已写入 {out_path}\n"
        f"预计省下 {len(skip)} 次 update 调用 ≈ {saved // 60} 分 {saved % 60} 秒"
    )
    return need


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=("market", "plugin"), required=True)
    ap.add_argument("--out", help="清单输出路径（默认按阶段取 /tmp 下固定名）")
    ap.add_argument(
        "--include-disabled",
        action="store_true",
        help="连未 enabled 的安装记录也一起刷（默认只刷 enabled 的）",
    )
    args = ap.parse_args()

    if not os.path.isfile(INSTALLED):
        print(f"找不到 {INSTALLED}", file=sys.stderr)
        return 2

    if args.stage == "market":
        out = args.out or "/tmp/mkt_to_update.txt"
        stage_market(out)
    else:
        out = args.out or "/tmp/plugins_to_refresh.txt"
        stage_plugin(out, only_enabled=not args.include_disabled)
    return 0


if __name__ == "__main__":
    sys.exit(main())
