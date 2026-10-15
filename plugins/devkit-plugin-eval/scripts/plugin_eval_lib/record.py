"""run.json（唯一真源）的组装与 report.md（给人读）的渲染。

run.json 字段按 spec「四、目录布局与状态文件」列：本版能填的照填，后续票才填的留键位、值为 null：
clause_list_fingerprint（条款清单，票 10）、judge_model / judge（AI 评委，票 09）、
injection_check（注入到达核验，票 06）、resident_tokens（常驻 token，票 06）、preflight（前置检查，票 04）、
arms.previous / arms.current_with_env（上一版与环境插件臂，票 05）。
"""
import os
import re
from collections import Counter

from .registry import TRUST_SCOPE

SCHEMA_VERSION = 1
ARM_ORDER = ('none', 'current', 'previous', 'current_with_env')
REVIEW_PENDING = '待审'


def scrub_home(obj, home=None):
    """把字符串里的本机家目录前缀换成 ~（run.json / report.md 会入库，不留用户名）。只换完整路径段。"""
    home = (home or os.path.expanduser('~')).rstrip('/')
    if not home or home == '~':
        return obj
    pat = re.compile(re.escape(home) + r'(?=/|$|[^\w.-])')

    def walk(o):
        if isinstance(o, str):
            return pat.sub('~', o)
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        return o
    return walk(obj)


def _uniq(values):
    vals = sorted({v for v in values if v})
    if not vals:
        return None
    return vals[0] if len(vals) == 1 else vals


def _sum_usage(arms):
    keys = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'cost_usd')
    total = {k: 0 for k in keys}
    by_model = {}
    for a in arms:
        u = a.get('usage') or {}
        for k in keys:
            total[k] += u.get(k) or 0
        for model, vals in (u.get('by_model') or {}).items():
            acc = by_model.setdefault(model, {k: 0 for k in keys})
            for k in keys:
                acc[k] += vals.get(k) or 0
    total['by_model'] = by_model
    total['cost_basis'] = '按标价（list price）估算，订阅用户只作信息'
    return total


def _passed(complete, current, threshold):
    if not complete or not current:
        return False
    scores = [c['score'] for c in current.get('cases', {}).values() if c.get('score') is not None]
    return bool(scores) and all(s >= threshold for s in scores)


def build_run_record(*, run_id, plugin, arms, delta, cases, incomplete_reasons, threshold,
                     started_at, finished_at, environment):
    present = [arms[k] for k in ARM_ORDER if arms.get(k)]
    complete = not incomplete_reasons
    main_models = Counter(a.get('main_model') for a in present if a.get('main_model'))
    return {
        'schema_version': SCHEMA_VERSION,
        'kind': 'compare',
        'run_id': run_id,
        'started_at': started_at,
        'finished_at': finished_at,
        'plugin': plugin,
        'clause_list_fingerprint': None,
        'cases': cases,
        'arms': {k: arms.get(k) for k in ARM_ORDER},
        'delta': dict(delta, arm='current', baseline='none'),
        'claude_code_version': _uniq(a.get('claude_version') for a in present),
        'main_model': main_models.most_common(1)[0][0] if main_models else None,
        'judge_model': None,
        'usage': _sum_usage(present),
        'complete': complete,
        'incomplete_reasons': list(incomplete_reasons),
        'threshold': threshold,
        'passed': _passed(complete, arms.get('current'), threshold),
        'pass_criterion': '运行完整，且当前版臂每个有分用例的规则分都 ≥ threshold',
        'review': {'status': REVIEW_PENDING, 'reviewed_at': None},
        'injection_check': None,
        'judge': None,
        'resident_tokens': None,
        'preflight': None,
        'environment': environment,
    }


def _f(x):
    return '—' if x is None else '%.2f' % x


def _d(x):
    return '—' if x is None else '%+.2f' % x


def _runs(case):
    if not case:
        return '—'
    return ' / '.join(_f(s) for s in case.get('run_scores', [])) or '—'


def render_report(rec):
    p = rec['plugin']
    arms = [(k, rec['arms'][k]) for k in ARM_ORDER if rec['arms'].get(k)]
    u = rec['usage']
    lines = [
        '# 离线对照报告：%s %s' % (p['name'], p['version']),
        '',
        '> 状态：**%s**。待审报告不能作为改插件或发版的依据；用户审过后改为「已审」。' % rec['review']['status'],
        '',
        '> 信任范围：%s' % TRUST_SCOPE,
        '',
        '- 运行：`%s`，%s 至 %s（UTC）' % (rec['run_id'], rec['started_at'], rec['finished_at']),
        '- 插件内容指纹：`%s`' % p['fingerprint'],
        '- Claude Code：%s；主力模型：%s' % (rec['claude_code_version'], rec['main_model']),
        '- 判分：只用规则 grader；每例每臂 %s 次' % (rec.get('environment') or {}).get('runs_per_case', '?'),
        '- 是否完整：%s' % ('是' if rec['complete'] else '**不完整**'),
        '- 是否通过：%s（口径：%s，threshold=%s）' % ('是' if rec['passed'] else '否', rec['pass_criterion'], rec['threshold']),
        '- 花费：$%.4f（%s）；token：输入 %d、输出 %d、缓存读 %d、缓存写 %d' % (
            u['cost_usd'], u['cost_basis'], u['input_tokens'], u['output_tokens'],
            u['cache_read_input_tokens'], u['cache_creation_input_tokens']),
    ]
    if rec['incomplete_reasons']:
        lines += ['', '## 不完整的原因', '']
        lines += ['- %s' % r for r in rec['incomplete_reasons']]

    lines += ['', '## 各臂总分', '', '| 臂 | 总分 | 有效 run | 无效 run | 花费 |', '|---|---|---|---|---|']
    for _, a in arms:
        valid = sum(c.get('valid_runs', 0) for c in a.get('cases', {}).values())
        lines.append('| %s | %s | %d | %d | $%.4f |' % (a['label'], _f(a.get('score')), valid,
                                                      a.get('invalid_run_count', 0), a.get('cost_usd') or 0))
    lines.append('| 差（当前版 − 不装） | %s | | | |' % _d(rec['delta'].get('overall')))

    none = rec['arms'].get('none') or {}
    cur = rec['arms'].get('current') or {}
    lines += ['', '## 逐用例', '', '| 用例 | 不装 | 当前版 | 差 | 不装逐次 | 当前版逐次 |', '|---|---|---|---|---|---|']
    for name in rec['cases']:
        n = none.get('cases', {}).get(name)
        c = cur.get('cases', {}).get(name)
        lines.append('| %s | %s | %s | %s | %s | %s |' % (
            name, _f(n and n.get('score')), _f(c and c.get('score')),
            _d(rec['delta']['cases'].get(name)), _runs(n), _runs(c)))

    below = [n for n in rec['cases']
             if (cur.get('cases', {}).get(n) or {}).get('score') is not None
             and cur['cases'][n]['score'] < rec['threshold']]
    if below:
        lines += ['', '## 当前版未达 threshold 的用例', '',
                  '「是否通过」要求当前版每个有分用例 ≥ threshold（%s）；下列用例没达到：' % rec['threshold'], '']
        lines += ['- %s：%s' % (n, _f(cur['cases'][n]['score'])) for n in below]

    unscored = [(a['label'], n) for _, a in arms for n, c in a.get('cases', {}).items() if c.get('no_scored_graders')]
    if unscored:
        lines += ['', '## 告警：没有可计分的 grader', '',
                  '下列用例的 grader 全被剔除（with-only 或付费类型），得分为空，不进臂总分与差，也不参与「是否通过」：', '']
        lines += ['- %s臂：%s' % (label, n) for label, n in unscored]

    excluded = {}
    for _, a in arms:
        for name, c in a.get('cases', {}).items():
            for g, why in c.get('excluded_graders', {}).items():
                excluded.setdefault(name, {})[g] = why
    if excluded:
        lines += ['', '## 未计分的 grader', '',
                  'with-only 的 grader 在 `--ablation none` 下会被 eval 计入分数，本报告照 eval 在 with-without '
                  '模式下的判据剔除：显式 `arm: with-only`、未写 arm 的 `tool_used: Skill`、mock 全为插件 server 替身时'
                  '未写 arm 的 mock_calls grader；`llm` / `baseline` 等付费 grader 不在规则判分范围内，也剔除。', '']
        for name in sorted(excluded):
            lines.append('- %s：%s' % (name, '、'.join('`%s`（%s）' % (g, why) for g, why in sorted(excluded[name].items()))))

    lines += ['', '## 本报告未覆盖', '',
              '前置检查、上一版臂、注入到达核验、AI 评委、常驻 token 尚未接入，run.json 里对应字段为 null。', '']
    return '\n'.join(lines)
