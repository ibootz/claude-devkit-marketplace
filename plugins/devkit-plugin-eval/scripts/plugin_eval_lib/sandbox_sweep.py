"""认领并清理没被正常搬走的 eval 沙箱。

正常情况下 compare 按汇总里每个 run 的 tracePath 搬 trace、删沙箱（traces.harvest_sandbox）。
两种情况会留下 <临时根>/e-*：eval 没产出 aggregate-result.json（中途中止、超时被杀），
或某个 run 出错、汇总里没有 tracePath。这些沙箱按 trace 第一条 system/init 的 plugins[].path
认领：落在本臂组装目录里的才是本臂的（组装目录由 mkdtemp 生成，唯一），别的会话的沙箱不动。
"""
import json
from pathlib import Path

from . import traces

# 只读 trace 开头这么多行找 system/init，不整份读
INIT_SCAN_LINES = 50


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(root)
        return True
    except (ValueError, OSError):
        return False


def _claimed_by(trace_path, arm_dir):
    try:
        with open(trace_path, encoding='utf-8', errors='replace') as f:
            for i, line in enumerate(f):
                if i >= INIT_SCAN_LINES:
                    return False
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if isinstance(o, dict) and o.get('type') == 'system' and o.get('subtype') == 'init':
                    return any(isinstance(p, dict) and p.get('path') and _inside(p['path'], arm_dir)
                               for p in o.get('plugins') or [])
    except OSError:
        return False
    return False


def sweep_orphans(arm_dir, dest_root, roots=None):
    """把属于 arm_dir 的残留沙箱搬到 dest_root/orphan-<沙箱名>/ 并删除沙箱。返回告警清单。"""
    arm_dir = Path(arm_dir).resolve()
    roots = [Path(r) for r in (roots or traces.default_sandbox_roots())]
    warnings = []
    for root in roots:
        try:
            candidates = sorted(root.glob('e-*'))
        except OSError:
            continue
        for sb in candidates:
            trace = sb / 'out' / 'trace.jsonl'
            try:
                if not trace.is_file():
                    continue
            except OSError:
                continue
            if _claimed_by(trace, arm_dir):
                warnings += traces.harvest_sandbox(trace, Path(dest_root) / ('orphan-' + sb.name), roots)
    return warnings
