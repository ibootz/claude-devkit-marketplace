"""测试共用：把 scripts/ 放进 sys.path，并提供造被测插件、造 eval 产物的小工具。"""
import json
import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def tmpdir(testcase):
    """建临时目录并在用例结束时删掉（含仿沙箱的只读子目录）。"""
    import tempfile
    from plugin_eval_lib import traces
    d = Path(tempfile.mkdtemp(prefix='pe-test-'))
    testcase.addCleanup(lambda: d.exists() and traces._rmtree(str(d)))
    return d


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def make_plugin(root, name='demo-plugin', version='1.2.3', cases=('case-a',)):
    """在 root 下造一个最小被测插件：plugin.json、一个 hook 脚本、若干用例。"""
    root = Path(root)
    write(root / '.claude-plugin' / 'plugin.json', json.dumps({'name': name, 'version': version}))
    write(root / 'hooks' / 'inject.js', 'console.log("hi")\n')
    for c in cases:
        write(root / 'evals' / c / 'prompt.md', '---\nname: %s\n---\n做点事\n' % c)
        write(root / 'evals' / c / 'graders' / 'g1.md', '---\ntype: regex\ntarget: last_message\npattern: ok\n---\n')
    return root


def grader(name, gtype='tool_used', arm=None, weight=1):
    cfg = {'tool': 'Agent'}
    if arm:
        cfg['arm'] = arm
    return {'name': name, 'type': gtype, 'weight': weight, 'config': cfg}


def run_result(passes, error=None, trace_path=None, cost=0.1):
    """passes: {grader 名: 是否通过}。eval 在 --ablation none 下把每个 grader 都标成计分。"""
    return {
        'score': 0, 'passed': False, 'turns': 1, 'costUsd': cost, 'judgeCostUsd': 0,
        'durationSeconds': 5, 'startedAt': '2026-10-15T08:00:00.000Z', 'error': error,
        'tracePath': trace_path, 'skippedPaidGraders': False,
        'graders': [
            {'name': n, 'passed': p, 'weight': 1, 'explanation': '', 'withOnly': False, 'scored': True}
            for n, p in passes.items()
        ],
    }


def aggregate(cases, cost=0.3, version='2.1.300', partial=False, root='/tmp/x'):
    """cases: [(用例名, graders 列表, run 列表)]，产出与 eval --json / aggregate-result.json 同形的 dict。"""
    return {
        'schemaVersion': 1, 'claudeVersion': version, 'startedAt': '2026-10-15T08:00:00.000Z',
        'durationSeconds': 10, 'costUsd': cost, 'partial': partial,
        'suite': {'root': root, 'ablation': 'none', 'threshold': 1, 'concurrency': 3, 'plugins': []},
        'cases': [
            {'name': n, 'dir': 'evals/' + n, 'runsPerCase': len(runs), 'graders': gs,
             'arms': {'with': runs}, 'aggregates': {}}
            for n, gs, runs in cases
        ],
        'aggregates': {'casesTotal': len(cases), 'casesPassed': 0, 'overallScore': 0, 'overallPassRate': 0},
    }


def trace_lines(model='claude-opus-5-5', usage=None):
    usage = usage or {model: {'inputTokens': 10, 'outputTokens': 20, 'cacheReadInputTokens': 30,
                              'cacheCreationInputTokens': 40, 'costUSD': 0.5}}
    lines = [
        {'type': 'system', 'subtype': 'init', 'model': model, 'claude_code_version': '2.1.300'},
        {'type': 'assistant', 'message': {'content': []}},
        {'type': 'system', 'subtype': 'init', 'model': 'claude-sonnet-5-5'},
        {'type': 'result', 'subtype': 'success', 'modelUsage': usage, 'total_cost_usd': 0.5},
    ]
    return '\n'.join(json.dumps(x) for x in lines) + '\n'


def make_sandbox(tmp_root, label, model='claude-opus-5-5', readonly=True):
    """仿 eval --keep-temp 留下的沙箱：<e-xxx>/out/trace.jsonl、config/projects/<p>/<sid>.jsonl、sealed/。"""
    sb = Path(tmp_root) / ('e-' + label)
    write(sb / 'out' / 'trace.jsonl', trace_lines(model))
    write(sb / 'config' / 'projects' / '-tmp-cwd' / 'sid.jsonl', '{"type":"user"}\n')
    (sb / 'sealed').mkdir(parents=True, exist_ok=True)
    if readonly:
        os.chmod(sb / 'sealed', 0)
        os.chmod(sb, 0o500)
    return sb
