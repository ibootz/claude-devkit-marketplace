"""--keep-temp 沙箱里的 trace：汇总 token 与模型，再搬到用户级 traces/ 并删掉沙箱。

沙箱形态（2.1.300 实测）：<tmp>/e-XXXXXX/{out/trace.jsonl, config/projects/<项目>/<会话>.jsonl, sealed/}，
沙箱根目录是 r-x、sealed/ 是 000，搬动前要先给自己加写权限。
子会话转录含 eval 注入的账号邮箱：只进用户级 traces/，不进被测插件所在仓。
"""
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

USAGE_FIELDS = (
    ('inputTokens', 'input_tokens'),
    ('outputTokens', 'output_tokens'),
    ('cacheReadInputTokens', 'cache_read_input_tokens'),
    ('cacheCreationInputTokens', 'cache_creation_input_tokens'),
    ('costUSD', 'cost_usd'),
)


def summarize_trace(trace_path):
    """主会话模型取第一条 system/init 的 model；token 取最后一条 result 行的 modelUsage（含子代理用的模型）。

    派后台子代理时一个 trace 会有多条 result，每条都是截至当时的累计值（2.1.300 实测，
    最后一条与 eval 的 run.costUsd 相等），所以只取最后一条，不能相加。
    """
    out = {'main_model': None, 'usage': {}}
    if not trace_path or not Path(trace_path).is_file():
        return out
    with open(trace_path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            if o.get('type') == 'system' and o.get('subtype') == 'init' and out['main_model'] is None:
                out['main_model'] = o.get('model')
            elif o.get('type') == 'result':
                out['usage'] = {model: {dst: u.get(src) or 0 for src, dst in USAGE_FIELDS}
                                for model, u in (o.get('modelUsage') or {}).items()}
    return out


def merge_usage(usages):
    by_model = {}
    for u in usages:
        for model, vals in u.items():
            acc = by_model.setdefault(model, {k: 0 for _, k in USAGE_FIELDS})
            for _, k in USAGE_FIELDS:
                acc[k] += vals.get(k) or 0
    total = {k: sum(m[k] for m in by_model.values()) for _, k in USAGE_FIELDS}
    total['by_model'] = by_model
    return total


def default_sandbox_roots():
    roots = {Path(tempfile.gettempdir()).resolve()}
    for p in ('/tmp', '/private/tmp'):
        if Path(p).is_dir():
            roots.add(Path(p).resolve())
    return sorted(roots)


def _make_writable(path):
    try:
        os.chmod(path, stat.S_IRWXU)
    except OSError:
        pass


def _rmtree(path):
    def retry(func, p, _exc):
        _make_writable(os.path.dirname(p))
        _make_writable(p)
        func(p)
    # 先把整棵树改成可写可进入：sealed/ 是 000，os.walk 进不去就看不到里面的文件
    _make_writable(path)
    for dirpath, dirnames, _ in os.walk(path):
        for d in dirnames:
            _make_writable(os.path.join(dirpath, d))
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


def harvest_sandbox(trace_path, dest, allowed_roots=None):
    """把一个 run 的 trace 与子会话转录搬到 dest，然后删掉沙箱。返回告警清单（空 = 顺利）。

    只认形如 <允许的临时根>/e-*/out/trace.jsonl 的路径，别的路径一律不动，防误删。
    """
    if not trace_path:
        return ['run 没有 tracePath，无 trace 可搬']
    trace_path = Path(trace_path)
    sandbox = trace_path.parent.parent
    roots = [Path(r).resolve() for r in (allowed_roots or default_sandbox_roots())]
    if not (trace_path.name == 'trace.jsonl' and trace_path.parent.name == 'out'
            and sandbox.name.startswith('e-') and sandbox.parent.resolve() in roots):
        return ['%s 不像 eval 沙箱，未搬动也未删除' % trace_path]
    if not trace_path.exists():
        return ['%s 不存在（沙箱已被清理？）' % trace_path]
    warnings = []
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    _make_writable(sandbox)
    _make_writable(sandbox / 'out')
    shutil.move(str(trace_path), str(dest / 'trace.jsonl'))
    projects = sandbox / 'config' / 'projects'
    if projects.is_dir():
        _make_writable(sandbox / 'config')
        shutil.move(str(projects), str(dest / 'projects'))
    try:
        _rmtree(sandbox)
    except OSError as e:
        warnings.append('沙箱 %s 未能删除：%s' % (sandbox, e))
    return warnings
