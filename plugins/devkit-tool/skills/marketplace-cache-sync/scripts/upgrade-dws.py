#!/usr/bin/env python3
"""检查并升级钉钉 Workspace CLI（dws）：默认只检查，--apply 才改动。

dws 是外部 CLI，和 Claude Code 的插件市场/缓存无关。把它放进本 skill，只是因为两者经常在
同一次「刷新本机工具」里一起做；前五步的顺序与判据不受影响。

判据与坑（2026-11-16 本机实测，dws v1.0.66）：

  - 当前版本：`dws version --format json` 的 `version`。
  - 是否有新版：`dws upgrade --check --format json` 的 `needs_upgrade` / `latest_version`。
  - 这次检查会去查 npm registry，偶发 `TLS handshake timeout`——同机 `curl` 同一 URL
    却能返回 200，重试即过。检查失败时回落到 `dws version --format json` 里
    `version_check` 的缓存结论，并明确标注「缓存，可能过期」；缓存也没有就报错，不猜。
  - 升级用 `dws upgrade --version <latest> -y`：带版本号是为了钉住刚刚检查到的版本，
    不再依赖第二次“latest”解析；它**仍然会去 npm registry 取该版本的元数据**。本机实测
    npmjs 的 TLS 握手偶发超时（同机 `curl` 同一 URL 却返回 200），此时显式换源：
    `--registry https://registry.npmmirror.com`（第三方镜像，确认可用再用）。
  - 升级后会按新版本官方清单**全量覆盖**预制 skill；同名旧 skill 备份在
    `~/.dws/skill-backups/<时间戳>/`。回滚用 `dws upgrade --rollback -y`。

退出码：0 无需动作 / 成功 / dws 未安装；1 检查或升级失败；2 参数错误。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

CHECK_TIMEOUT = 60
VERSION_TIMEOUT = 30
UPGRADE_TIMEOUT = 900


def normalize_version(value):
    """把 `1.0.68` 与 `v1.0.68` 统一成 `v1.0.68`；空值返回空串。"""
    text = (value or "").strip()
    if not text:
        return ""
    if text[0] in "vV":
        return "v" + text[1:]
    return "v" + text


def extract_json(text):
    """从可能夹着提示行的输出里取出第一个完整 JSON 对象；没有就返回 None。

    dws 的正常输出是纯 JSON，但错误信息、版本提示可能混在前后。用 raw_decode 逐个 `{`
    尝试，避免把「提示行 + JSON」整段当成非法 JSON。
    """
    if not text:
        return None
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = decoder.raw_decode(text[start:])
            return obj
        except ValueError:
            start = text.find("{", start + 1)
    return None


def one_line(text, limit=400):
    """把多行 CLI 输出压成一行，避免把整段错误灌进上下文；超过上限截断。"""
    flat = " ".join((text or "").split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


_PROGRESS_RE = re.compile(r"\[\d+/\d+\]\s+下载.*\d+(?:\.\d+)?%")


def condense_output(text):
    """去掉下载进度条，保留步骤行与结果行。

    `dws upgrade` 的进度条会输出上百行，直接回显会把上下文与终端都刷满；
    步骤行（备份 / 校验 / 替换）和最后的 `✔ 升级完成` 才是要看的。
    """
    kept = []
    for raw in re.split(r"[\r\n]+", text or ""):
        line = raw.strip()
        if not line or _PROGRESS_RE.search(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def parse_version_payload(data):
    """从 `dws version --format json` 的 JSON 里取版本与缓存的更新结论。"""
    if not isinstance(data, dict) or data.get("error") or not data.get("version"):
        return None
    check = data.get("version_check") or {}
    notice = (data.get("_notice") or {}).get("update") or {}
    latest = check.get("latest") or notice.get("latest")
    return {
        "version": normalize_version(data.get("version")),
        "cached_status": check.get("status"),
        "cached_latest": normalize_version(latest),
        "checked_at": check.get("checked_at") or "",
    }


def parse_check_payload(data, current):
    """从 `dws upgrade --check --format json` 的 JSON 里取检查结论。"""
    if not isinstance(data, dict):
        return None
    if data.get("error"):
        err = data["error"]
        message = err.get("message") if isinstance(err, dict) else str(err)
        return {"ok": False, "error": one_line(message or "dws upgrade --check 返回错误")}
    if "needs_upgrade" not in data:
        return None
    return {
        "ok": True,
        "needs_upgrade": bool(data.get("needs_upgrade")),
        "latest": normalize_version(data.get("latest_version")) or current,
        "current": normalize_version(data.get("current_version")) or current,
    }


def parse_check_text(text, current):
    """解析 `dws upgrade --check` 的人类可读输出（JSON 不可用时的兜底）。

    实测两种形态：
      新版本可用:  v1.0.66 → v1.0.68
      ✔ 已是最新版本 v1.0.66
    """
    text = text or ""
    match = re.search(r"新版本可用:\s*(\S+)\s*→\s*(\S+)", text)
    if match:
        return {
            "ok": True,
            "needs_upgrade": True,
            "latest": normalize_version(match.group(2)),
            "current": normalize_version(match.group(1)) or current,
        }
    if "已是最新" in text or "无可用更新" in text:
        return {"ok": True, "needs_upgrade": False, "latest": current, "current": current}
    return None


def build_upgrade_args(latest):
    """升级到指定版本并跳过确认；版本号来自刚刚的检查，避免再解析一次 latest。"""
    return ["upgrade", "--version", latest, "-y"]


def run_dws(exe, args, timeout, env=None):
    """跑一条 dws 命令，返回 (returncode, stdout, stderr)。

    外部 CLI 先解析成绝对路径再传给 subprocess：Windows 上 npm 装出来的 dws 是 `.cmd`，
    裸命令名会报「没安装」，而 `.cmd` 需要经 cmd.exe 调起。
    """
    cmd = [exe, *args]
    if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
        cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", *cmd]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"命令超时（{timeout}s）"
    except OSError as exc:
        return 127, "", type(exc).__name__


def read_version(exe, env):
    """回读当前版本与缓存更新结论，返回 (info, err)。"""
    rc, out, err = run_dws(exe, ["version", "--format", "json"], VERSION_TIMEOUT, env)
    info = parse_version_payload(extract_json(out))
    if info:
        return info, ""
    match = re.search(r"Version:\s*(v?[\d.]+)", out)
    if match:
        return {
            "version": normalize_version(match.group(1)),
            "cached_status": None,
            "cached_latest": "",
            "checked_at": "",
        }, ""
    return None, one_line(out or err or f"dws version 退出码 {rc}，且没有可解析的输出")


def fresh_check(exe, current, env):
    """实时检查更新；返回统一形态的检查结论，失败时带可读原因。

    npm registry 的 TLS 握手实测是偶发失败，重试一次几乎不花时间，所以这里重试一次；
    升级动作本身不重试——那是写操作，失败后交给调用方决定。
    """
    last = None
    for attempt in range(2):
        rc, out, err = run_dws(
            exe, ["upgrade", "--check", "--format", "json"], CHECK_TIMEOUT, env
        )
        # 成功时 JSON 走 stdout；实测 npm registry 失败时错误 JSON 走 stderr，两路都要试。
        result = parse_check_payload(extract_json(out), current)
        if not result:
            result = parse_check_payload(extract_json(err), current)
        if not result:
            result = parse_check_text(out + "\n" + err, current)
        if result and result.get("ok"):
            return result
        last = result or {
            "ok": False,
            "error": one_line(
                out or err or f"dws upgrade --check 退出码 {rc}，且没有可解析的输出"
            ),
        }
    return last


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="检查并升级 dws CLI。默认只检查；--apply 才升级。",
    )
    parser.add_argument(
        "--apply", action="store_true", help="有新版本时真的执行升级（默认只检查）"
    )
    parser.add_argument(
        "--registry",
        help="覆盖 npm registry（设置 DWS_UPGRADE_REGISTRY），检查更新失败时用",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=UPGRADE_TIMEOUT,
        help=f"升级命令超时秒数（默认 {UPGRADE_TIMEOUT}）",
    )
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass

    env = None
    if args.registry:
        env = dict(os.environ, DWS_UPGRADE_REGISTRY=args.registry)
        print(f"使用自定义 npm registry：{args.registry}")

    # 读版本与缓存结论时不要带自定义 registry：实测 DWS_UPGRADE_REGISTRY 会让
    # `dws version` 的 version_check 变成 status=unknown，丢掉可用的缓存回落。
    cache_env = dict(os.environ)
    cache_env.pop("DWS_UPGRADE_REGISTRY", None)

    # 输出里给出的后续命令要能直接照抄，所以拼出当前解释器与本脚本的绝对路径。
    self_cmd = f'"{sys.executable}" "{os.path.abspath(__file__)}"'

    exe = shutil.which("dws")
    if not exe:
        print("未找到 dws（PATH 中没有）。跳过 dws 升级；装好 dws 后重跑本脚本。")
        return 0

    print(f"dws：{exe}")
    info, version_error = read_version(exe, cache_env)
    if not info:
        print(f"✗ 无法读取 dws 版本：{version_error}")
        return 1
    current = info["version"]
    print(f"当前版本：{current}")

    check = fresh_check(exe, current, env)
    if check.get("ok"):
        latest = check.get("latest") or current
        needs_upgrade = bool(check.get("needs_upgrade"))
        source = "实时检查"
    else:
        cached_latest = info.get("cached_latest") or ""
        checked_at = info.get("checked_at") or "时间未知"
        if info.get("cached_status") == "update_available" and cached_latest:
            latest = cached_latest
            needs_upgrade = normalize_version(latest) != normalize_version(current)
            source = f"缓存（{checked_at}，可能过期）"
            print(f"⚠ 实时检查失败：{check.get('error', '未知原因')}")
            print(f"  回落到缓存：{current} -> {latest}")
        elif info.get("cached_status") == "up_to_date":
            # 缓存说已是最新，但实时检查没成功；不把缓存当成实时结论，也不升级。
            print(f"⚠ 实时检查失败：{check.get('error', '未知原因')}")
            print(f"  缓存显示已是最新（{checked_at}），但本次没有实时确认；未升级。")
            return 1
        else:
            print(f"✗ 检查更新失败：{check.get('error', '未知原因')}")
            print(
                "  缓存里也没有可用的更新信息。稍后重试；npm registry 不可达时可显式换源："
            )
            print(
                f"    {self_cmd} --apply --registry https://registry.npmmirror.com"
            )
            return 1

    print(f"最新版本：{latest}（{source}）")

    if not needs_upgrade:
        print("已是最新，无需升级。")
        return 0

    if not args.apply:
        print(f"可升级：{current} -> {latest}")
        print(f"检查模式：未改动 dws 二进制与 skill。执行升级：{self_cmd} --apply")
        return 0

    upgrade_args = build_upgrade_args(latest)
    print(f"升级中：{current} -> {latest}（超时 {args.timeout}s）")
    print(f"$ dws {' '.join(upgrade_args)}")
    rc, out, err = run_dws(exe, upgrade_args, args.timeout, env)
    summary = condense_output(out)
    if summary:
        print(summary)
    error_summary = condense_output(err)
    if error_summary:
        print(error_summary, file=sys.stderr)

    if rc != 0:
        print(f"✗ 升级命令失败（exit={rc}）。")
        print(
            "  可重试；npm registry 不可达时显式换源（第三方镜像，确认可用再用）："
        )
        print(
            f"    {self_cmd} --apply --registry https://registry.npmmirror.com"
        )
        print("  已经升级过一半时用 `dws upgrade --rollback -y` 回滚。")
        return 1

    after, after_error = read_version(exe, env)
    if not after:
        print(f"✗ 升级命令返回 0，但回读版本失败：{after_error}")
        return 1
    new_version = after["version"]
    if normalize_version(new_version) != normalize_version(latest):
        print(f"✗ 回读核实不一致：期望 {latest}，实得 {new_version}。")
        print(
            "  升级可能没有落盘；检查 dws 输出，必要时用 `dws upgrade --rollback -y` 回滚。"
        )
        return 1

    print(f"✓ 回读核实：{current} -> {new_version}")
    print("  dws 官方 skill 已按新版本清单覆盖；同名旧 skill 备份在 ~/.dws/skill-backups/。")
    print("  二进制下一条命令即生效；本会话已加载的 skill 文本可能要下个会话才更新。")
    print("  回滚：dws upgrade --rollback -y")
    return 0


if __name__ == "__main__":
    sys.exit(main())
