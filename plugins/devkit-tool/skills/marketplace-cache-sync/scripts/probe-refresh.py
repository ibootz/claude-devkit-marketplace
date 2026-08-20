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
                   两类源都比版本号，只是版本号读的位置不同：市场仓内源读市场仓里的
                   manifest（纯本地）；url 独立仓源读远端仓根 .claude-plugin/plugin.json
                   （一次 HTTP GET，不 clone），按远端仓去重后本机只有十几个请求。

输出一律是「给人看的诊断 + 机器可读清单文件」两部分，清单文件路径见 --out 参数。
"""

import argparse
import concurrent.futures as futures
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PLUGINS_HOME = os.path.expanduser("~/.claude/plugins")
MARKETPLACES = os.path.join(PLUGINS_HOME, "marketplaces")
INSTALLED = os.path.join(PLUGINS_HOME, "installed_plugins.json")
USER_SETTINGS = os.path.expanduser("~/.claude/settings.json")

# 自建 GitLab 的 API 需要 PRIVATE-TOKEN。取自环境变量，**值一律不进任何打印或异常文本**；
# 且只在目标主机与 $GITLAB_HOST 同主机时才附带，避免把内网凭证发给任意第三方主机。
GITLAB_HOST = os.environ.get("GITLAB_HOST", "").strip()
GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN", "").strip()

# fetch_manifest_version 的哨兵返回值：manifest 取到了、但里面没有 version 字段。
# 这与「manifest 压根没取到」必须分开——前者要回落去比 sha，后者只能保守刷。
NO_VERSION = "manifest 无 version 字段"

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


# --------------------------------------------------------- url 独立仓源的判据取值
#
# 这一节是本脚本最容易判错的地方，所以把「CLI 到底比什么」写在这里，不要凭直觉改。
#
# `claude plugin update` 判 `already at the latest version` 的条件（2.1.237 二进制里的函数
# yJT）是：installed_plugins.json 里该记录的 `version`，等于 CLI 从远端解析出的版本号。
# 解析优先级（辅助函数 S1e）逐条是：
#   1. 远端仓根 `.claude-plugin/plugin.json` 的 `version`   ← 本机全部 url 源都命中这一支
#   2. 所属 marketplace.json 条目上的 `version`
#   3. `gitCommitSha` 的前 12 位
#   4. archive / 本地 sha / 字面量 "unknown"
# **`gitCommitSha` 从不参与那个相等判断。** 所以拿 sha 当判据必然大面积误判：同一 id 的多条
# 记录共享同一个 version 却带不同 sha（cctx-dev-yxt-design-system 14 条里有 3 个不同 sha、
# version 全是 1.9.12）。2026-08-20 实测后果是 54 条被判待刷的记录 54 条回执都是
# `already at the latest version`，白付 22 分钟。
#
# 另一面：`version` 是字面量 "unknown" 时 CLI 恒重装（回执 `refreshed from source`），
# 这是**可以直接用的反向判据**——这类记录一律列入待刷，剪掉它就是漏刷。


def _looks_like_sha(s):
    return bool(s) and len(s) >= 12 and all(c in "0123456789abcdefABCDEF" for c in s)


def url_revision(src):
    """取 url 源钉住的 revision。

    sha 优先于 ref：钉了 sha 的源就是钉死在那个提交上，此时 ref 无意义。曾经只读 `ref` 的写法
    对「有 sha、无 ref」的源（如 mattpocock-skills）会去探该仓 HEAD，拿到的必然不是钉住的
    那个提交——结构性必然误判，不是概率问题。
    """
    if not isinstance(src, dict):
        return "HEAD"
    return src.get("sha") or src.get("ref") or "HEAD"


def manifest_endpoints(url, rev, token=None, token_host=None):
    """构造「不 clone 就能取远端仓根 plugin.json」的候选 HTTP 端点。

    返回 [(endpoint, headers), ...] 按优先级排列。纯函数：不发请求、不读磁盘，便于回归测试。
    token / token_host 缺省时取自 $GITLAB_TOKEN / $GITLAB_HOST。

    判据值只是一个 JSON 文件里的字段，取一个文件不需要 clone——这是整个剪枝方案成立的前提。
    注意 `git ls-remote` 在这里帮不上忙：它只返回 ref→sha，**给不到文件内容**。它唯一的用处
    是上面第 3 支（manifest 没有 version 字段）时补一个 sha。
    """
    if token is None:
        token = GITLAB_TOKEN
    if token_host is None:
        token_host = urllib.parse.urlsplit(GITLAB_HOST).hostname or ""
    if not url:
        return []
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    repo = parts.path.lstrip("/")
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    if not host or not repo:
        return []

    files = (".claude-plugin/plugin.json", "plugin.json")
    if host in ("github.com", "www.github.com"):
        return [
            (f"https://raw.githubusercontent.com/{repo}/{urllib.parse.quote(rev)}/{f}", {})
            for f in files
        ]

    # 其余一律按 GitLab REST v4 处理（自建 GitLab 是本机 url 源的绝大多数）。
    # project path 与文件路径都要整段 urlencode，斜杠转 %2F。
    headers = {}
    scheme = parts.scheme or "https"
    netloc = parts.netloc
    if token and host == token_host:
        headers = {"PRIVATE-TOKEN": token}
        # 附了凭证就不走明文——内网 GitLab 同时提供 https，源 url 写 http 不代表只能走 http。
        scheme = "https"
    base = f"{scheme}://{netloc}"
    proj = urllib.parse.quote(repo, safe="")
    return [
        (
            f"{base}/api/v4/projects/{proj}/repository/files/"
            f"{urllib.parse.quote(f, safe='')}/raw?ref={urllib.parse.quote(rev)}",
            headers,
        )
        for f in files
    ]


def fetch_manifest_version(url, rev, timeout=12):
    """取远端仓根 plugin.json 的 version，返回 (version, err)。

    err == NO_VERSION 表示「远端没有可用的 version」——manifest 取到了但没这个字段，或者候选
    端点全部 404（仓里压根没有 manifest）。这两种都要回落去比 sha，**不能当成探测失败**：
    404 是一个确定答案（文件不存在），与超时 / 401 / DNS 失败那种「不知道」性质不同。
    本机实测有两个 url 源正是这一类（fecenter-docs / agent-cli-docs 仓根无 manifest，
    它们的记录 version 就是 gitCommitSha 前 12 位）。

    其余非空 err 一律是真失败，调用方按保守侧「刷一次」处理。
    异常文本只记类型名或状态码，避免把带凭证的请求细节写进输出。
    """
    endpoints = manifest_endpoints(url, rev)
    err = "无可用端点（url 形态无法解析）"
    all_absent = bool(endpoints)
    for endpoint, headers in endpoints:
        req = urllib.request.Request(endpoint, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            all_absent = all_absent and e.code == 404
            continue
        except Exception as e:
            err = type(e).__name__
            all_absent = False
            continue
        try:
            data = json.loads(body)
        except Exception:
            err = "manifest 不是合法 JSON"
            all_absent = False
            continue
        if isinstance(data, dict) and data.get("version"):
            return (str(data["version"]), "")
        return ("", NO_VERSION)
    return ("", NO_VERSION if all_absent else err)


def url_verdict(rec, remote_version, remote_sha12):
    """判一条 url 源记录要不要刷，返回 ("need"|"skip", 理由)。

    纯函数，判据全部来自入参。保守侧优先：缓存目录不存在、探测失败、判不了一律 need——
    剪枝只在能确证「跑 update 必然 no-op」时才生效，方向错了宁可多刷一次。
    """
    cur = rec.get("version") or ""
    install_path = rec.get("installPath") or ""
    if install_path and not os.path.isdir(install_path):
        return ("need", f"缓存目录不存在：{install_path}")
    if cur == "unknown":
        return ("need", "记录 version 是字面量 unknown，CLI 恒重装（refreshed from source）")
    if remote_version:
        if remote_version == cur:
            return ("skip", f"远端 manifest 版本一致（{cur}）")
        return ("need", f"版本号落后：{cur or '?'} -> {remote_version}")
    if remote_sha12:
        short = remote_sha12[:12]
        if cur and cur[:12] == short:
            return ("skip", f"manifest 无 version，回落比 sha 前 12 位一致（{short}）")
        return ("need", f"manifest 无 version，回落比 sha：{cur[:12] or '?'} -> {short}")
    return ("need", "远端 manifest 探测失败（网络/凭证/形态），保守刷一次")


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
                urlsrc.append((pid, rec, src.get("url"), url_revision(src)))
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
        elif cur == "unknown":
            # 与 url 源同一条反向判据：记录 version 是字面量 unknown 时 CLI 恒重装。
            # 本机这一类恰好也是市场源没声明版本号的那批，两条判据指向同一结论。
            need.append((pid, rec))
            why.append((pid, rec, "记录 version 是字面量 unknown，CLI 恒重装（refreshed from source）"))
        elif src_ver is None:
            need.append((pid, rec))
            why.append((pid, rec, "市场源未声明版本号，判不了，保守刷一次"))
        elif src_ver != cur:
            need.append((pid, rec))
            why.append((pid, rec, f"版本号落后：{cur} -> {src_ver}"))
        else:
            skip.append((pid, rec, f"版本号一致（{cur}）"))

    # (2) url 源（插件内容在独立 git 仓里，不在市场仓内）：判据同样是版本号，只是那个版本号
    #     住在**远端仓根的 .claude-plugin/plugin.json** 里，得去远端取一次（一个 HTTP GET，
    #     不 clone）。判据的完整依据见本文件「url 独立仓源的判据取值」一节。
    #     这类插件的 update 最慢——CLI 每次都真把那个仓拉下来，也是 temp_git_* 残留的来源。
    #     按 (url, revision) 去重后请求数从记录数塌缩到远端仓数（本机 110 条 -> 15 个仓）。
    def probe_remote(key):
        url, rev = key
        if not url:
            return (key, "", "", "url 缺失")
        ver, err = fetch_manifest_version(url, rev)
        if ver:
            return (key, ver, "", "")
        if err == NO_VERSION:
            # 落到 CLI 的第 3 支：判据变成 sha 前 12 位，此时 ls-remote 才是对的工具。
            out = run_git(["git", "ls-remote", url, rev])
            sha = out.split("\t")[0] if out else ""
            if not sha and _looks_like_sha(rev):
                # 源本来就钉死在一个 sha 上，ls-remote 查不到它（它是提交不是 ref），直接用它。
                sha = rev
            if sha:
                return (key, "", sha[:12], "")
            return (key, "", "", "manifest 无 version 且 sha 也取不到")
        return (key, "", "", err)

    keys = sorted({(url, rev) for _, _, url, rev in urlsrc})
    t0 = time.time()
    with futures.ThreadPoolExecutor(max_workers=16) as ex:
        probed = {r[0]: r[1:] for r in ex.map(probe_remote, keys)} if keys else {}
    url_elapsed = time.time() - t0

    for pid, rec, url, rev in urlsrc:
        remote_version, remote_sha12, err = probed.get((url, rev), ("", "", "未探测"))
        verdict, reason = url_verdict(rec, remote_version, remote_sha12)
        if verdict == "need":
            if err and not remote_version and not remote_sha12:
                reason = f"远端 manifest 探测失败（{err}），保守刷一次"
            need.append((pid, rec))
            why.append((pid, rec, reason))
        else:
            skip.append((pid, rec, reason))

    for pid, rec, reason in unknown:
        need.append((pid, rec))
        why.append((pid, rec, reason))

    def fmt(rec):
        return f"{rec.get('scope')}|{rec.get('projectPath') or ''}"

    with open(out_path, "w", encoding="utf-8") as f:
        for pid, rec in need:
            f.write(f"{pid}|{rec.get('scope')}|{rec.get('projectPath') or ''}\n")

    print(
        f"=== 阶段二：插件层探测（url 源 {len(urlsrc)} 条记录去重成 {len(keys)} 个远端仓，"
        f"并发取 manifest 耗时 {url_elapsed:.1f}s）==="
    )
    print(f"  市场仓内源 {len(inrepo)} 条 / url 独立仓源 {len(urlsrc)} 条 / 判不了 {len(unknown)} 条")
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
