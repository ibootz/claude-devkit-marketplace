#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deps Investigator Script

从本地 m2/node_modules 读取依赖源码。
与 mcp-server/deps_mcp 保持逻辑同步。
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


# =============================================================================
# 配置数据类（同步自 deps_mcp/main.py）
# =============================================================================

@dataclass(frozen=True)
class JavaConfig:
    m2_repo: Path
    max_bytes: int
    total_timeout_seconds: int

    @classmethod
    def default(cls) -> "JavaConfig":
        return cls(
            m2_repo=Path.home() / ".m2" / "repository",
            max_bytes=2000000,
            total_timeout_seconds=30,
        )


@dataclass(frozen=True)
class NodeConfig:
    default_project_root: Optional[Path]
    max_bytes: int
    total_timeout_seconds: int

    @classmethod
    def default(cls) -> "NodeConfig":
        return cls(
            default_project_root=None,
            max_bytes=2000000,
            total_timeout_seconds=30,
        )


# 兼容旧配置
@dataclass(frozen=True)
class DepsConfig:
    m2_repo: Path
    default_node_project_root: Optional[Path]
    java_max_bytes: int
    node_max_bytes: int

    @classmethod
    def default(cls) -> "DepsConfig":
        java_config = JavaConfig.default()
        node_config = NodeConfig.default()
        return cls(
            m2_repo=java_config.m2_repo,
            default_node_project_root=node_config.default_project_root,
            java_max_bytes=java_config.max_bytes,
            node_max_bytes=node_config.max_bytes,
        )


# =============================================================================
# 辅助函数（同步自 deps_mcp/java_resolver.py 和 node_resolver.py）
# =============================================================================

def _read_limited_text(file_path: Path, max_bytes: int) -> str:
    """读取文件内容并限制大小。"""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise IOError(f"Failed to read file: {e}")

    encoded = content.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return content
    return encoded[:max_bytes].decode("utf-8", errors="replace") + "\n// ... truncated ..."


def _truncate(code: str, max_bytes: int) -> str:
    """截断代码内容。"""
    encoded = code.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return code
    return encoded[:max_bytes].decode("utf-8", errors="replace") + "\n// ... truncated ..."


def _find_sources_jar(m2_repo: Path, group_id: str, artifact_id: str, version: str) -> Optional[Path]:
    """查找 sources.jar 文件。

    优先查找 -sources.jar，如果不存在则回退到普通 .jar。
    """
    group_path = group_id.replace(".", "/")
    base_dir = m2_repo / group_path / artifact_id / version

    sources_jar = base_dir / f"{artifact_id}-{version}-sources.jar"
    if sources_jar.exists():
        return sources_jar

    regular_jar = base_dir / f"{artifact_id}-{version}.jar"
    if regular_jar.exists():
        return regular_jar

    return None


def _extract_class_from_jar(jar_path: Path, class_fqn: str, max_bytes: int) -> Dict[str, Any]:
    """从 JAR 文件中提取类源码。"""
    class_path = class_fqn.replace(".", "/") + ".java"

    try:
        with zipfile.ZipFile(jar_path) as zf:
            namelist = zf.namelist()

            if class_path in namelist:
                with zf.open(class_path) as f:
                    code = f.read().decode("utf-8", errors="replace")
                return {
                    "success": True,
                    "classPath": class_path,
                    "code": _truncate(code, max_bytes),
                }

            class_simple_name = class_fqn.split(".")[-1] + ".java"
            candidates: List[str] = []
            for name in namelist:
                if name.endswith(class_simple_name):
                    candidates.append(name)

            if len(candidates) == 1:
                with zf.open(candidates[0]) as f:
                    code = f.read().decode("utf-8", errors="replace")
                return {
                    "success": True,
                    "classPath": candidates[0],
                    "code": _truncate(code, max_bytes),
                    "note": f"Class found at alternative path: {candidates[0]}",
                }

            if len(candidates) > 1:
                return {
                    "success": False,
                    "error": "AMBIGUOUS_CLASS",
                    "message": f"Multiple classes found matching '{class_simple_name}': {candidates[:5]}",
                    "candidates": candidates[:10],
                }

            return {
                "success": False,
                "error": "CLASS_NOT_FOUND",
                "message": f"Class not found in JAR: {class_path}",
            }

    except zipfile.BadZipFile:
        return {"success": False, "error": "BAD_JAR", "message": f"Invalid JAR file: {jar_path}"}
    except Exception as e:
        return {"success": False, "error": "READ_ERROR", "message": str(e)}


def _read_java_class_source_local(
    config: DepsConfig, group_id: str, artifact_id: str, version: str, class_fqn: str
) -> Dict[str, Any]:
    """读取 Java 类源码的核心实现。"""
    jar_path = _find_sources_jar(config.m2_repo, group_id, artifact_id, version)
    if not jar_path:
        group_path = group_id.replace(".", "/")
        expected_path = config.m2_repo / group_path / artifact_id / version
        return {
            "success": False,
            "error": "JAR_NOT_FOUND",
            "message": f"Source JAR not found. Expected at: {expected_path}",
            "hint": "Try running: mvn dependency:sources -DincludeGroupIds=" + group_id,
        }

    result = _extract_class_from_jar(jar_path, class_fqn, config.java_max_bytes)

    if result.get("success"):
        result.update({
            "groupId": group_id,
            "artifactId": artifact_id,
            "version": version,
            "classFqn": class_fqn,
            "jarPath": str(jar_path),
            "jarType": "sources" if "-sources.jar" in str(jar_path) else "regular",
        })

    return result


def _read_node_module_source_local(
    config: DepsConfig, package_name: str, file_path: str, project_root: Optional[str]
) -> Dict[str, Any]:
    """读取 Node 模块源码的核心实现。"""
    root: Path
    if project_root:
        root = Path(project_root).expanduser()
    elif config.default_node_project_root:
        root = config.default_node_project_root
    else:
        root = Path.cwd()

    if not root.exists():
        return {
            "success": False,
            "error": "PROJECT_ROOT_NOT_FOUND",
            "message": f"Project root does not exist: {root}",
        }

    node_modules = root / "node_modules"
    if not node_modules.exists():
        return {
            "success": False,
            "error": "NODE_MODULES_NOT_FOUND",
            "message": f"node_modules directory not found at: {node_modules}",
            "hint": "Try running: npm install",
        }

    candidate = node_modules / package_name / file_path
    if not candidate.exists():
        package_dir = node_modules / package_name
        if not package_dir.exists():
            return {
                "success": False,
                "error": "PACKAGE_NOT_FOUND",
                "message": f"Package '{package_name}' not found in node_modules",
                "hint": f"Try running: npm install {package_name}",
            }
        return {
            "success": False,
            "error": "FILE_NOT_FOUND",
            "message": f"File not found: {candidate}",
        }

    try:
        code = _read_limited_text(candidate, config.node_max_bytes)
    except IOError as e:
        return {"success": False, "error": "READ_ERROR", "message": str(e)}

    return {
        "success": True,
        "packageName": package_name,
        "projectRoot": str(root),
        "filePath": file_path,
        "fullPath": str(candidate),
        "code": code,
    }


# =============================================================================
# 结果格式化
# =============================================================================

def _format_java_result(result: Dict[str, Any]) -> str:
    """格式化 Java 源码读取结果。"""
    if not result.get("success"):
        error_type = result.get("error", "UNKNOWN")
        message = result.get("message", "Unknown error")
        hint = result.get("hint", "")
        hint_line = f"\n**提示**: {hint}" if hint else ""
        return f"""## ❌ Java 源码读取失败

**错误类型**: `{error_type}`
**错误信息**: {message}{hint_line}
"""

    jar_type = result.get("jarType", "unknown")
    jar_type_note = " (sources)" if jar_type == "sources" else " (regular JAR, may not contain source)"
    note = result.get("note", "")
    note_line = f"\n**注意**: {note}" if note else ""

    return f"""## ✅ Java 源码读取成功

**坐标**: `{result["groupId"]}:{result["artifactId"]}:{result["version"]}`
**类**: `{result["classFqn"]}`

**文件位置**
- JAR: `{result["jarPath"]}`{jar_type_note}
- 路径: `{result["classPath"]}`{note_line}

```java
{result["code"]}
```
"""


def _format_node_result(result: Dict[str, Any]) -> str:
    """格式化 Node 源码读取结果。"""
    if not result.get("success"):
        error_type = result.get("error", "UNKNOWN")
        message = result.get("message", "Unknown error")
        hint = result.get("hint", "")
        hint_line = f"\n**提示**: {hint}" if hint else ""
        return f"""## ❌ Node 源码读取失败

**错误类型**: `{error_type}`
**错误信息**: {message}{hint_line}
"""

    full_path = result.get("fullPath", "")
    full_path_line = f"\n- 完整路径: `{full_path}`" if full_path else ""

    return f"""## ✅ Node 源码读取成功

**包信息**
- 包名: `{result["packageName"]}`
- 项目根目录: `{result["projectRoot"]}`
- 文件路径: `{result["filePath"]}`{full_path_line}

```javascript
{result["code"]}
```
"""


# =============================================================================
# 公开 API 函数
# =============================================================================

def read_java_source(
    group_id: str,
    artifact_id: str,
    version: str,
    class_fqn: str,
) -> str:
    """读取 Java 类源码并返回格式化结果。"""
    config = DepsConfig.default()
    return _format_java_result(_read_java_class_source_local(config, group_id, artifact_id, version, class_fqn))


def read_node_source(
    package_name: str,
    file_path: str,
    project_root: Optional[str],
) -> str:
    """读取 Node 模块源码并返回格式化结果。"""
    config = DepsConfig.default()
    return _format_node_result(_read_node_module_source_local(config, package_name, file_path, project_root))


def main() -> None:
    parser = argparse.ArgumentParser(description="Deps Investigator - 读取依赖源码")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    java_parser = subparsers.add_parser("java", help="读取 Java 类源码")
    java_parser.add_argument("--group-id", required=True, help="Maven groupId")
    java_parser.add_argument("--artifact-id", required=True, help="Maven artifactId")
    java_parser.add_argument("--version", required=True, help="版本号")
    java_parser.add_argument("--class-fqn", required=True, help="完整类名")

    node_parser = subparsers.add_parser("node", help="读取 Node 模块源码")
    node_parser.add_argument("--package-name", required=True, help="npm 包名")
    node_parser.add_argument("--file-path", required=True, help="文件路径（相对包根目录）")
    node_parser.add_argument("--project-root", help="项目根目录")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "java":
        print(
            read_java_source(
                group_id=args.group_id,
                artifact_id=args.artifact_id,
                version=args.version,
                class_fqn=args.class_fqn,
            )
        )
        return

    if args.command == "node":
        print(
            read_node_source(
                package_name=args.package_name,
                file_path=args.file_path,
                project_root=args.project_root,
            )
        )
        return

    print("❌ 未知命令", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
