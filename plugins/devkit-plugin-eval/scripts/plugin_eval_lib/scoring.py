"""规则判分：从 eval 的 aggregate-result.json 重算每臂分数，再算臂间差。

为什么不直接用 eval 给的 score：
- `--ablation none` 下 with-only 的 grader 也计分（票 01 实测：空桩臂 0.2 而非 0.33），
  而逐 run 结果里的 withOnly / scored 在 none 模式下都标成计分，剔除依据只能取用例级
  `cases[].graders[].config`，判据照抄 2.1.300 二进制里 with-without 模式的判定（见 _exclusion_reason）；
- 本机制只用规则判分，llm / baseline 这类付费 grader 一律不计（spec「一」规则判分一行）。
分数口径与 eval 一致：单 run 分 = 通过的计分 grader 权重和 / 计分 grader 权重和；
用例分 = 有效 run 的均值；臂总分 = 有分用例的均值。error 非空的 run 判无效、不计分。
"""
import re

RULE_GRADER_TYPES = ('regex', 'tool_order', 'tool_used', 'file_exists')
LOAD_FAIL_RE = re.compile(r'(\d+)\s+case file\(s\) failed to load')


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _exclusion_reason(g, mock_with_only=False):
    """2.1.300 二进制在 with-without 模式下把三类 grader 当「插件起效指示」、不计分：
    显式 `arm: with-only`；arm 未写且 `type: tool_used` + `tool: Skill`（--help 原文 incl. `tool_used: Skill`）；
    arm 未写、target / focus 为 mock_calls，且该用例的 mock 全是替插件 server 顶班的 shadow（mock_with_only）。"""
    cfg = g.get('config') or {}
    arm = cfg.get('arm')
    if arm == 'with-only':
        return 'with-only'
    if arm is None and g.get('type') == 'tool_used' and cfg.get('tool') == 'Skill':
        return 'with-only（tool_used: Skill，eval 隐式视同）'
    if (arm is None and mock_with_only
            and ((g.get('type') == 'regex' and cfg.get('target') == 'mock_calls')
                 or (g.get('type') == 'llm' and cfg.get('focus') == 'mock_calls'))):
        return 'with-only（mock_calls，mock 全为插件 server 的 shadow，eval 隐式视同）'
    if g.get('type') not in RULE_GRADER_TYPES:
        return g.get('type') or 'unknown'
    return None


def _shadow_only(mocks):
    """二进制 Da()：未 withheld 的 mock server 至少一个，且没有 standalone（全是替插件 server 顶班的 shadow）。"""
    servers = [s for s in (mocks or {}).get('servers', []) if not s.get('withheld')]
    return bool(servers) and all(s.get('kind') != 'standalone' for s in servers)


def mock_with_only_cases(agg):
    """哪些用例的 mock_calls grader 要视同 with-only。只能从装了插件的臂看：
    不装臂里没有插件 server，同一份 mock 会被 eval 判成 standalone。"""
    return {_case_rel_dir(c) for c in agg.get('cases', [])
            if any(_shadow_only(r.get('mocks')) for r in c.get('arms', {}).get('with', []))}


_detect_mock_with_only = mock_with_only_cases   # score_arm 的同名参数会遮住函数名


def score_case(case, mock_with_only=False):
    excluded = {}
    weights = {}
    for g in case.get('graders', []):
        reason = _exclusion_reason(g, mock_with_only)
        if reason:
            excluded[g['name']] = reason
        else:
            weights[g['name']] = g.get('weight', 1)
    run_scores, invalid = [], []
    for i, run in enumerate(case.get('arms', {}).get('with', [])):
        if run.get('error'):
            invalid.append({'index': i, 'error': run['error']})
            continue
        total = sum(weights.values())
        if not total:
            run_scores.append(None)
            continue
        passed = {r['name'] for r in run.get('graders', []) if r.get('passed')}
        run_scores.append(sum(w for n, w in weights.items() if n in passed) / total)
    return {
        'score': _mean(run_scores),
        'run_scores': run_scores,
        'valid_runs': len(run_scores),
        'invalid_runs': invalid,
        'excluded_graders': excluded,
        'no_scored_graders': not sum(weights.values()),
    }


def score_arm(agg, mock_with_only_cases=None):
    """按用例目录（去掉 evals/）建键：frontmatter name 可以重名，按 name 建键会互相覆盖。
    mock_with_only_cases 缺省时从本臂自己的 run 推（只对装了插件的臂成立）。"""
    if mock_with_only_cases is None:
        mock_with_only_cases = _detect_mock_with_only(agg)
    cases = {}
    for c in agg.get('cases', []):
        key = _case_rel_dir(c)
        cases[key] = score_case(c, key in mock_with_only_cases)
    return {
        'score': _mean(c['score'] for c in cases.values()),
        'cases': cases,
        'invalid_run_count': sum(len(c['invalid_runs']) for c in cases.values()),
    }


def delta(arm, baseline):
    """arm − baseline，逐用例与总体。只在两臂都有分的用例上相减；总体差 = 这些用例差的均值。"""
    names = sorted(set(arm.get('cases', {})) | set(baseline.get('cases', {})))
    per_case, missing = {}, []
    for n in names:
        a = arm.get('cases', {}).get(n)
        b = baseline.get('cases', {}).get(n)
        if a is None or b is None:
            missing.append(n)
            per_case[n] = None
        elif a['score'] is None or b['score'] is None:
            per_case[n] = None
        else:
            per_case[n] = a['score'] - b['score']
    return {'cases': per_case, 'overall': _mean(per_case.values()), 'missing_cases': missing}


def parse_load_failures(stderr):
    m = LOAD_FAIL_RE.search(stderr or '')
    return int(m.group(1)) if m else 0


def _case_rel_dir(case):
    """eval 的 cases[].dir 形如 evals/<用例>（相对插件根）；取 evals/ 之后的部分，与 discover_cases 对齐。
    frontmatter 的 name 可以与目录名不同，所以按目录比，不按 name 比。"""
    d = (case.get('dir') or '').replace('\\', '/')
    if d.startswith('evals/'):
        return d[len('evals/'):]
    return d or case.get('name')


def check_loaded_cases(agg, expected, stderr):
    """加载失败的用例不进 JSON，casesTotal 也不计它；这里把它找出来当错误。返回问题清单。"""
    issues = []
    failed = parse_load_failures(stderr)
    if failed:
        issues.append('%d 个用例加载失败（eval stderr：%d case file(s) failed to load）' % (failed, failed))
    ran = {_case_rel_dir(c) for c in agg.get('cases', [])}
    missing = [e for e in expected if e not in ran]
    if missing:
        issues.append('用例目录有、eval 结果里没有：%s' % ', '.join(missing))
    if agg.get('partial'):
        issues.append('eval 结果标为 partial（中途中止）')
    return issues
