#!/usr/bin/env python3
"""upgrade-dws.py 的离线判据回归（不调用 dws，不发网络请求）。

为什么这份用例存在：升级脚本依赖 `dws version` / `dws upgrade --check` 的外部输出形态。
dws 的正常输出是 JSON，但实测会遇到「提示行 + JSON」、纯文本形态，以及 npm registry
偶发 TLS 失败时返回的 `{"error": ...}`。判据一旦退化，脚本会把「检查失败」误读成
「已是最新」而静默跳过升级——这类错误不会报错，只会让升级永远不发生。

跑法：python3 plugins/devkit-tool/tests/upgrade-dws.test.py
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(
    HERE, "..", "skills", "marketplace-cache-sync", "scripts", "upgrade-dws.py"
)

spec = importlib.util.spec_from_file_location("upgrade_dws", os.path.abspath(TARGET))
ud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ud)

FAILED = []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n          期望 {want!r}\n          实得 {got!r}")
        FAILED.append(label)


print("\n[1] normalize_version：统一 v 前缀")
check("1.0.68 → v1.0.68", ud.normalize_version("1.0.68"), "v1.0.68")
check("v1.0.68 保持", ud.normalize_version("v1.0.68"), "v1.0.68")
check("V1.0.68 → v1.0.68", ud.normalize_version("V1.0.68"), "v1.0.68")
check("空值 → 空串", ud.normalize_version(""), "")

print("\n[2] extract_json：从混合输出里取第一个完整 JSON")
check("纯 JSON", ud.extract_json('{"a": 1}'), {"a": 1})
check(
    "提示行 + JSON",
    ud.extract_json('检查更新...\n{\n  "needs_upgrade": true\n}'),
    {"needs_upgrade": True},
)
check("无效文本 → None", ud.extract_json("not json"), None)
check(
    "跳过前面不合法的花括号",
    ud.extract_json('x {bad} y {"ok": true}'),
    {"ok": True},
)
check("空串 → None", ud.extract_json(""), None)

print("\n[3] parse_version_payload：版本与缓存结论")
version_payload = {
    "_notice": {
        "update": {
            "current": "v1.0.66",
            "latest": "1.0.68",
            "command": "dws upgrade",
        }
    },
    "version": "v1.0.66",
    "version_check": {
        "current": "v1.0.66",
        "latest": "1.0.68",
        "status": "update_available",
        "checked_at": "2026-11-16T06:14:18.542586Z",
        "cached": True,
    },
}
info = ud.parse_version_payload(version_payload)
check("当前版本", info["version"], "v1.0.66")
check("缓存状态", info["cached_status"], "update_available")
check("缓存最新版带 v 前缀", info["cached_latest"], "v1.0.68")
check("检查时间原样保留", info["checked_at"], "2026-11-16T06:14:18.542586Z")
check("缺 version → None", ud.parse_version_payload({"version_check": {}}), None)
check(
    "带 error 的 JSON 不当作版本信息",
    ud.parse_version_payload({"version": "v1.0.66", "error": {"message": "x"}}),
    None,
)
check("非 dict → None", ud.parse_version_payload("v1.0.66"), None)
check(
    "只有 _notice 时也能取到缓存最新版",
    ud.parse_version_payload(
        {"version": "v1.0.66", "_notice": {"update": {"latest": "1.0.68"}}}
    )["cached_latest"],
    "v1.0.68",
)

print("\n[4] parse_check_payload：JSON 检查结论")
check_payload = {
    "changelog": None,
    "current_version": "v1.0.66",
    "latest_version": "v1.0.68",
    "needs_upgrade": True,
    "prerelease": False,
    "track": "release",
}
result = ud.parse_check_payload(check_payload, "v1.0.66")
check("ok", result["ok"], True)
check("needs_upgrade", result["needs_upgrade"], True)
check("最新版", result["latest"], "v1.0.68")
check("当前版", result["current"], "v1.0.66")
check(
    "已是最新（needs_upgrade=false）",
    ud.parse_check_payload(
        {"current_version": "v1.0.68", "latest_version": "v1.0.68", "needs_upgrade": False},
        "v1.0.68",
    )["needs_upgrade"],
    False,
)
error_payload = {
    "error": {
        "category": "internal",
        "code": 5,
        "message": "检查更新失败: 获取 npm 版本 latest 失败: 无法连接 npm Registry",
    }
}
error_result = ud.parse_check_payload(error_payload, "v1.0.66")
check("错误 JSON → ok=False", error_result["ok"], False)
check(
    "错误 JSON 保留原因",
    "检查更新失败" in error_result["error"],
    True,
)
check("缺 needs_upgrade → None", ud.parse_check_payload({"foo": 1}, "v1.0.66"), None)
check("非 dict → None", ud.parse_check_payload([], "v1.0.66"), None)

print("\n[5] parse_check_text：人类可读输出兜底")
text_update = "  检查更新...\n\n  新版本可用:  v1.0.66 → v1.0.68\n\n  运行 dws upgrade 进行升级"
result = ud.parse_check_text(text_update, "v1.0.66")
check("文本：可升级", result["needs_upgrade"], True)
check("文本：最新版", result["latest"], "v1.0.68")
check("文本：当前版", result["current"], "v1.0.66")
text_latest = "  检查更新...\n  指定版本: v1.0.66\n\n  ✔ 已是最新版本 v1.0.66"
result = ud.parse_check_text(text_latest, "v1.0.66")
check("文本：已是最新", result["needs_upgrade"], False)
check("文本：最新版回落当前版", result["latest"], "v1.0.66")
check(
    "文本：无可用更新",
    ud.parse_check_text("版本检查: 当前 v1.0.68，无可用更新", "v1.0.68")["needs_upgrade"],
    False,
)
check("无法解析 → None", ud.parse_check_text("garbage", "v1.0.66"), None)

print("\n[6] build_upgrade_args：升级命令形态")
check(
    "钉住检查到的版本并跳过确认",
    ud.build_upgrade_args("v1.0.68"),
    ["upgrade", "--version", "v1.0.68", "-y"],
)

print("\n[7] one_line：多行错误压成一行并截断")
check("多行压平", ud.one_line("a\n b\tc"), "a b c")
check("超长截断", ud.one_line("x" * 10, limit=5), "xxxxx…")
check("短文本不截断", ud.one_line("abc", limit=5), "abc")

print("\n[8] condense_output：过滤下载进度条")
progress_raw = (
    "[1/5] 备份当前版本... ✓\n"
    "[2/5] 下载 dws-darwin-arm64.tar.gz [███░░░░░░░]  50.0% (1.00/2.00 MiB)\n"
    "[3/5] 校验 dws-darwin-arm64.tar.gz... ✓\r\n"
    "  ✔ 升级完成  v1.0.66 → v1.0.68\n"
)
check(
    "保留步骤行与结果行",
    ud.condense_output(progress_raw),
    "[1/5] 备份当前版本... ✓\n"
    "[3/5] 校验 dws-darwin-arm64.tar.gz... ✓\n"
    "✔ 升级完成  v1.0.66 → v1.0.68",
)
check(
    "全部是进度条 → 空串",
    ud.condense_output("[2/5] 下载 dws-skills.zip [███] 10.0% (0.1/3.3 MiB)"),
    "",
)
check(
    "下载失败行保留（没有百分比）",
    ud.condense_output("[2/5] 下载失败: timeout"),
    "[2/5] 下载失败: timeout",
)
check("错误 JSON 原样保留", ud.condense_output('{"error": {"code": 5}}'), '{"error": {"code": 5}}')

if FAILED:
    print(f"\n不合格 {len(FAILED)} 条：")
    for label in FAILED:
        print(f"  - {label}")
    sys.exit(1)
print("\n全部通过")
