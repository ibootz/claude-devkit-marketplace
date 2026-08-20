#!/usr/bin/env python3
"""probe-refresh.py 的 url 独立仓源判据回归用例（纯离线，不发一个网络请求）。

为什么这份用例存在：改动前脚本对 url 源比的是 commit sha，而 `claude plugin update` 实际比的是
远端仓根 `.claude-plugin/plugin.json` 的 `version`。2026-08-20 实测的后果是 54 条被判「待刷」
的记录里 54 条回执都是 `already at the latest version`——判据错了，剪枝等于没做，白付 22 分钟。

这份用例覆盖的是**判据本身**，所以三个被测函数都设计成纯函数：给定输入必然给定输出，不碰网络、
不碰 ~/.claude。网络那一层（真去取 manifest）由 `references/verification-log.md` 里的实测记录
兜住，不在这里重复。

跑法：python3 plugins/devkit-tool/tests/probe-refresh-url-criterion.test.py
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(
    HERE, "..", "skills", "marketplace-cache-sync", "scripts", "probe-refresh.py"
)

spec = importlib.util.spec_from_file_location("probe_refresh", os.path.abspath(TARGET))
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)

FAILED = []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n          期望 {want!r}\n          实得 {got!r}")
        FAILED.append(label)


# --------------------------------------------------------------- 1. sha 优先于 ref
#
# 钉了 sha 的源就是钉死在那个提交上，ref 此时无意义。mattpocock-skills 正是「有 sha、无 ref」
# 的形态；旧代码 `src.get("ref") or "HEAD"` 会去探该仓的 HEAD，拿到的必然不是钉住的提交——
# 这是结构性必然误判，不是概率问题。
print("\n[1] url_revision：sha 优先于 ref")
check(
    "钉 sha 无 ref → 取 sha",
    pr.url_revision({"source": "url", "url": "https://github.com/o/r.git", "sha": "885e2ca4d842d139e9aef4e48d366c63cb1b8013"}),
    "885e2ca4d842d139e9aef4e48d366c63cb1b8013",
)
check(
    "同时有 sha 与 ref → 仍取 sha",
    pr.url_revision({"source": "url", "url": "https://github.com/o/r.git", "sha": "abc123", "ref": "master"}),
    "abc123",
)
check(
    "只有 ref → 取 ref",
    pr.url_revision({"source": "url", "url": "https://github.com/o/r.git", "ref": "master"}),
    "master",
)
check(
    "两者都无 → 回落 HEAD",
    pr.url_revision({"source": "url", "url": "https://github.com/o/r.git"}),
    "HEAD",
)


# ------------------------------------------------- 2. manifest 端点构造（不 clone）
#
# 判据值是一个 JSON 文件里的字段，取一个文件不需要 clone。GitHub 走 raw.githubusercontent，
# 自建 GitLab 走 api/v4 的 files/:path/raw（路径要整段 urlencode，斜杠转 %2F）。
print("\n[2] manifest_endpoints：不 clone 取 manifest 的 URL 构造")
gh = pr.manifest_endpoints("https://github.com/mattpocock/skills.git", "885e2ca4")
check(
    "GitHub → raw.githubusercontent，带 rev 与 .claude-plugin 路径",
    gh[0][0],
    "https://raw.githubusercontent.com/mattpocock/skills/885e2ca4/.claude-plugin/plugin.json",
)
check("GitHub 不带 PRIVATE-TOKEN 头", gh[0][1], {})
check(
    "GitHub 次选端点是仓根 plugin.json",
    gh[1][0],
    "https://raw.githubusercontent.com/mattpocock/skills/885e2ca4/plugin.json",
)

GL_URL = "http://git-inner.yunxuetang.com.cn/ai-sdlc/cskl-repos/cskl-dev-devops.git"
# 显式传空 token，让这条断言不受本机 $GITLAB_TOKEN 有没有设置的影响。
gl = pr.manifest_endpoints(GL_URL, "main", token="", token_host="")
check(
    "GitLab → api/v4，project path 与文件路径都 urlencode",
    gl[0][0],
    "http://git-inner.yunxuetang.com.cn/api/v4/projects/"
    "ai-sdlc%2Fcskl-repos%2Fcskl-dev-devops/repository/files/"
    ".claude-plugin%2Fplugin.json/raw?ref=main",
)
check("无 token 时不附 PRIVATE-TOKEN 头", gl[0][1], {})

# 凭证只发给 $GITLAB_HOST 那一台，且附了凭证就升到 https，不走明文。
gl_auth = pr.manifest_endpoints(
    GL_URL, "main", token="T0KEN", token_host="git-inner.yunxuetang.com.cn"
)
check("同主机 → 附 PRIVATE-TOKEN 头", gl_auth[0][1], {"PRIVATE-TOKEN": "T0KEN"})
check("附凭证时升到 https", gl_auth[0][0].startswith("https://"), True)
other = pr.manifest_endpoints(
    "https://gitlab.example.com/a/b.git", "main",
    token="T0KEN", token_host="git-inner.yunxuetang.com.cn",
)
check("异主机 → 绝不附凭证", other[0][1], {})


# ------------------------------------------------------- 3. 判据：比 version，不比 sha
#
# `installPath` 缺失、探测失败、判不了一律列入待刷——剪枝只在能确证「必然 no-op」时生效。
print("\n[3] url_verdict：判据是远端 manifest 的 version")
EXIST = HERE  # 一个确定存在的目录，用来让 installPath 检查通过


def rec(version, install_path=EXIST, sha="deadbeefdeadbeef"):
    return {"version": version, "installPath": install_path, "gitCommitSha": sha, "scope": "user"}


check(
    "远端 version 与本地相等 → 跳过",
    pr.url_verdict(rec("0.3.4"), remote_version="0.3.4", remote_sha12="")[0],
    "skip",
)
check(
    "远端 version 更新 → 待刷",
    pr.url_verdict(rec("0.3.4"), remote_version="0.3.5", remote_sha12="")[0],
    "need",
)
check(
    # CLI 的 `unknown` 分支：本地 version 是字面量 unknown 时恒重装，与远端是什么无关。
    # 这四条 refreshed from source 的记录若被剪掉就是漏刷，方向比误刷更坏。
    "本地 version 是 unknown → 待刷（即便远端也 unknown）",
    pr.url_verdict(rec("unknown"), remote_version="unknown", remote_sha12="")[0],
    "need",
)
check(
    "sha 不同但 version 相同 → 跳过（旧代码在这里误判成待刷）",
    pr.url_verdict(rec("1.9.12", sha="6c10772f14aa"), remote_version="1.9.12", remote_sha12="8064cb547a11")[0],
    "skip",
)
check(
    "缓存目录不存在 → 待刷",
    pr.url_verdict(rec("0.3.4", install_path="/definitely/not/here"), remote_version="0.3.4", remote_sha12="")[0],
    "need",
)
check(
    "远端探测失败（version 与 sha 都没拿到）→ 待刷",
    pr.url_verdict(rec("0.3.4"), remote_version="", remote_sha12="")[0],
    "need",
)

print("\n[4] url_verdict：manifest 无 version 时回落比 sha 前 12 位")
# CLI 的 S1e 优先级：远端 manifest 的 version → 市场条目 version → gitCommitSha 前 12 位。
# 落到第三支时，被比较的仍是记录的 `version` 字段（它此时存的就是那 12 位），不是 gitCommitSha。
check(
    "无 version、sha12 与记录 version 相等 → 跳过",
    pr.url_verdict(rec("8064cb547a11"), remote_version="", remote_sha12="8064cb547a11")[0],
    "skip",
)
check(
    "无 version、sha12 与记录 version 不等 → 待刷",
    pr.url_verdict(rec("8064cb547a11"), remote_version="", remote_sha12="6c10772f14aa")[0],
    "need",
)
check(
    "无 version、远端给的是完整 40 位 sha → 按前 12 位比，相等则跳过",
    pr.url_verdict(
        rec("8064cb547a11"),
        remote_version="",
        remote_sha12="8064cb547a11ffffffffffffffffffffffffffff",
    )[0],
    "skip",
)

print("\n[5] _looks_like_sha：钉死 sha 的源在 ls-remote 查不到时靠它兜底")
check("40 位 hex → 是", pr._looks_like_sha("885e2ca4d842d139e9aef4e48d366c63cb1b8013"), True)
check("12 位 hex → 是", pr._looks_like_sha("02128add7690"), True)
check("分支名 main → 否", pr._looks_like_sha("main"), False)
check("短于 12 位 → 否", pr._looks_like_sha("abc123"), False)
check("空 → 否", pr._looks_like_sha(""), False)

print("\n[6] fetch_manifest_version：url 形态无法解析时不当成「远端说没有」")
_, err = pr.fetch_manifest_version("not-a-url", "main")
check("无可用端点时 err 不是 NO_VERSION（否则会误落 sha 分支）", err != pr.NO_VERSION, True)

print("\n[7] 判据理由文案带得出「为什么」")
_, reason = pr.url_verdict(rec("0.3.4"), remote_version="0.3.5", remote_sha12="")
check("版本落后的理由里同时出现新旧版本号", ("0.3.4" in reason and "0.3.5" in reason), True)

if FAILED:
    print(f"\n{len(FAILED)} 条未通过：")
    for f in FAILED:
        print(f"  - {f}")
    sys.exit(1)
print("\n全部通过")
