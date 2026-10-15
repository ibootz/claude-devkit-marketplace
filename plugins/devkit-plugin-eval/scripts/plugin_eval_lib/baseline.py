"""基线已满足（票 11，spec「2.3」）：新用例先在「不装」臂跑 RUNS 次，≥ 2/3 通过的打 TAG，只作回归守护。

一、判定（`baseline <插件>`）：只跑不装臂（空桩），用例取 evals/ 里没有基线记录、或记录之后改过内容的（`--case` 点名、
   `--recheck` 全部重判）。单次通过 = 该 run 的规则分 ≥ threshold（缺省 1.0，与 compare 同口径）。
   - satisfied：通过次数 ≥ ⌈RUNS × 2/3⌉。打 TAG。
   - not-satisfied：剩下的 run 全通过也够不着 ⌈RUNS × 2/3⌉。去掉 TAG。
   - undecided：有 run 无效（出错）、结果还定不下来；或用例没跑出结果。TAG 不动，下次再判。
   - no-rule-graders：没有计分的规则 grader（with-only / tool_used Skill 不计分），判不了。TAG 不动。
   结论记在 `plugin-evals/<插件>/baseline.json`；每次判定也是一次运行 `runs/<时间>-<版本>-baseline/`（kind=baseline），
   留不装臂的汇总作证据。判据只看规则判分层（scoring.score_case），不改 with-only grader 的剔除逻辑。

二、报告（compare.finalize_run 调 apply_to_record）：带 TAG 的用例不进「当前版 − 不装」的逐例差与总体差，
   改出回归结论（票 11：只比上一版不退化）：上一版臂有分时，当前版分 ≥ 上一版分记守住，否则记退化；
   没有上一版臂（退化或首版）时，当前版臂通过次数 ≥ ⌈有效 run × 2/3⌉ 记「无上一版」，不足记「低于基线」；
   当前版没有分记无分。
"""
import json
import math
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import arms, casefiles, clauses, fingerprint, record, registry, scoring

TAG = 'baseline-satisfied'
RECORD_FILE = 'baseline.json'
KIND = 'baseline'
RUNS = 3
PASS_RATIO = (2, 3)
VERDICTS = {'satisfied': '基线已满足', 'not-satisfied': '基线未满足', 'undecided': '未定（有 run 出错或没跑出结果）',
            'no-rule-graders': '判不了（没有计分的规则 grader）'}
REGRESSION_TEXT = {'held': '守住', 'regressed': '退化', 'no-previous': '无上一版', 'below-baseline': '低于基线',
                   'no-score': '无分'}
FLAGGED = ('regressed', 'below-baseline')


class BaselineError(Exception):
    pass


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def needed(runs):
    return int(math.ceil(runs * PASS_RATIO[0] / float(PASS_RATIO[1])))


def verdict(case_score, runs, threshold):
    """case_score 是 scoring.score_case 的结果（None = 用例没跑出来）。返回 {verdict, passes, invalid, valid, need}。"""
    need = needed(runs)
    if case_score is None:
        return {'verdict': 'undecided', 'passes': 0, 'invalid': runs, 'valid': 0, 'need': need,
                'note': 'eval 结果里没有这个用例'}
    if case_score.get('no_scored_graders'):
        return {'verdict': 'no-rule-graders', 'passes': 0, 'invalid': len(case_score.get('invalid_runs') or []),
                'valid': case_score.get('valid_runs', 0), 'need': need}
    scores = [s for s in case_score.get('run_scores') or [] if s is not None]
    passes = sum(1 for s in scores if s >= threshold)
    pending = max(0, runs - len(scores))     # 出错或没跑到的 run
    if passes >= need:
        v = 'satisfied'
    elif passes + pending < need:
        v = 'not-satisfied'
    else:
        v = 'undecided'
    return {'verdict': v, 'passes': passes, 'invalid': pending, 'valid': len(scores), 'need': need}


# ---------------- 记录与 tag ----------------

def record_path(repo, name):
    return clauses.evals_root(repo, name) / RECORD_FILE


def load_record(repo, name):
    p = record_path(repo, name)
    if not p.is_file():
        return {'schema_version': 1, 'plugin': name, 'cases': {}}
    doc = json.loads(p.read_text(encoding='utf-8'))
    doc.setdefault('cases', {})
    return doc


def save_record(repo, name, doc):
    p = record_path(repo, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record.scrub_home(doc), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def case_fingerprint(evals_dir, case):
    return fingerprint.evals_fingerprint(evals_dir, [case])['cases'].get(case)


def satisfied_cases(evals_dir, cases=None):
    """evals/ 下带 TAG 的用例（相对路径集合）。"""
    evals_dir = Path(evals_dir)
    cases = arms.discover_cases(evals_dir) if cases is None else cases
    return {c for c in cases if TAG in clauses.case_tags(evals_dir / c)}


def set_flag(case_dir, on):
    tags = clauses.case_tags(case_dir)
    if on and TAG not in tags:
        casefiles.set_tags(case_dir, tags + [TAG])
        return True
    if not on and TAG in tags:
        casefiles.set_tags(case_dir, [t for t in tags if t != TAG])
        return True
    return False


def select_cases(evals_dir, all_cases, doc, *, only=None, recheck=False):
    """要判的用例：点名的；或全部（recheck）；或没有记录 / 记录后内容改过的。"""
    if only:
        missing = [c for c in only if c not in all_cases]
        if missing:
            raise BaselineError('evals/ 下没有这些用例：%s' % '、'.join(missing))
        return list(only)
    if recheck:
        return list(all_cases)
    out = []
    for c in all_cases:
        r = (doc.get('cases') or {}).get(c)
        if r is None or r.get('verdict') in ('undecided',) or r.get('case_fingerprint') != case_fingerprint(evals_dir, c):
            out.append(c)
    return out


# ---------------- 跑 ----------------

def run_baseline(data_dir, name, *, cases=None, recheck=False, runs=RUNS, concurrency=3, model=None, threshold=1.0,
                 claude=None, runner=None, env=None, tmp_parent=None, sandbox_roots=None, preflight_check=None,
                 now=None, log=None):
    """返回 (run_dir 或 None, {用例: 判定})。"""
    from . import compare, evalrun, preflight, resume   # compare 在收尾时导入本模块：这里延迟导入免循环
    log = log or (lambda msg: print(msg, file=sys.stderr))
    data_dir = Path(data_dir)
    entry, plugin_dir, manifest, evals_src, all_cases, extra_exclude = compare.load_target(data_dir, name)
    repo = Path(entry['repo'])
    doc = load_record(repo, name)
    todo = select_cases(evals_src, all_cases, doc, only=cases, recheck=recheck)
    if not todo:
        log('[基线] evals/ 下的用例都已有基线结论（--recheck 全部重判，--case 点名重判）')
        return None, {}
    pre = (preflight_check or preflight.check_compare)(
        data_dir=data_dir, name=name, env=evalrun.child_env(env), claude=claude, model=model, tmp_parent=tmp_parent)
    if not pre.passed:
        raise preflight.PreflightFailed(pre)
    claude = claude or pre.claude or evalrun.resolve_claude()
    version = manifest.get('version') or 'noversion'
    started = (now or (lambda: datetime.now(timezone.utc)))()
    run_id = '%s-%s-%s' % (started.strftime('%Y%m%dT%H%M%SZ'), version, KIND)
    run_dir = clauses.evals_root(repo, name) / 'runs' / run_id
    if run_dir.exists():
        raise BaselineError('运行目录已存在：%s' % run_dir)
    run_dir.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix='devkit-plugin-eval-baseline-', dir=tmp_parent))
    try:
        subset = work / 'evals'
        subset.mkdir()
        for c in todo:      # 只拷要判的用例：eval 跑整个 evals/，其余用例不该花钱
            arms.copy_tree(evals_src / c, subset / c)
        spec = arms.ArmSpec('none', '不装', None)
        ctx = {
            'assembly_root': work / 'arms', 'evals_src': subset, 'extra_exclude': extra_exclude,
            'traces_root': data_dir / 'traces' / run_id, 'run_dir': run_dir, 'run_id': run_id,
            'claude': claude, 'runs': runs, 'concurrency': concurrency, 'model': model,
            'runner': runner or evalrun.run_eval, 'env': evalrun.child_env(env), 'cases': todo, 'log': log,
            'version': version, 'head_sha': None, 'dirty': None, 'sandbox_roots': sandbox_roots,
        }
        (work / 'arms').mkdir()
        arm = compare._run_arm(spec, ctx=ctx)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    agg = arm.pop('_agg', None)
    scored = scoring.score_arm(agg) if agg else {'score': None, 'cases': {}, 'invalid_run_count': 0}
    arm.update(score=scored['score'], cases=scored['cases'], invalid_run_count=scored['invalid_run_count'])
    ts = _iso(started)
    results = {}
    for c in todo:
        v = verdict(scored['cases'].get(c), runs, threshold)
        changed = False
        if v['verdict'] in ('satisfied', 'not-satisfied'):
            changed = set_flag(evals_src / c, v['verdict'] == 'satisfied')
        v.update(run_scores=(scored['cases'].get(c) or {}).get('run_scores'), threshold=threshold, runs=runs,
                 run_id=run_id, at=ts, tag_changed=changed, case_fingerprint=case_fingerprint(evals_src, c))
        results[c] = v
        if v['verdict'] != 'undecided' or c not in doc['cases']:
            doc['cases'][c] = v
        log('[基线] %s：%s（不装臂 %d/%d 次通过，需 %d）%s' % (
            c, VERDICTS[v['verdict']], v['passes'], runs, v['need'], '，已%s %s' % (
                '打上' if v['verdict'] == 'satisfied' else '去掉', TAG) if changed else ''))
    save_record(repo, name, doc)
    rec = {
        'schema_version': record.SCHEMA_VERSION, 'kind': KIND, 'run_id': run_id,
        'started_at': ts, 'finished_at': _iso(datetime.now(timezone.utc)),
        'plugin': {'name': name, 'version': version, 'path_in_repo': entry['plugin_path']},
        'cases': todo, 'threshold': threshold, 'runs_per_case': runs,
        'rule': '不装臂 %d 次中 ≥ %d 次规则分 ≥ threshold 即基线已满足' % (runs, needed(runs)),
        'arms': {'none': arm}, 'verdicts': results, 'preflight': pre.to_dict(),
        'usage': {'cost_usd': arm.get('cost_usd') or 0, 'cost_basis': '按标价（list price）估算，订阅用户只作信息'},
    }
    rec = record.scrub_home(rec)
    (run_dir / 'run.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (run_dir / 'report.md').write_text(record.scrub_home(render_report(rec)), encoding='utf-8')
    return run_dir, results


def render_report(rec):
    p = rec['plugin']
    arm = rec['arms']['none']
    lines = ['# 基线判定：%s %s' % (p['name'], p['version']), '',
             '> 判据：%s。基线已满足的用例只作回归守护：离线对照里不出「当前版 − 不装」的差，只出回归结论。' % rec['rule'], '',
             '- 运行：`%s`（UTC %s 至 %s）' % (rec['run_id'], rec['started_at'], rec['finished_at']),
             '- 花费：$%.4f（%s）' % (rec['usage']['cost_usd'], rec['usage']['cost_basis'])]
    issues = list(arm.get('load_issues') or [])
    if arm.get('eval_exit_code') not in (0, 1):
        issues.insert(0, 'eval 退出码 %s，结果可能不全' % arm.get('eval_exit_code'))
    if issues:
        lines += ['', '## 运行问题', ''] + ['- %s' % i for i in issues]
    lines += ['', '## 逐用例', '', '| 用例 | 结论 | 通过 / 需 | 逐次分 | tag |', '|---|---|---|---|---|']
    for c, v in rec['verdicts'].items():
        lines.append('| %s | %s | %d / %d | %s | %s |' % (
            c, VERDICTS[v['verdict']], v['passes'], v['need'],
            ' / '.join('—' if s is None else '%.2f' % s for s in v.get('run_scores') or []) or '—',
            ('已改' if v.get('tag_changed') else '未变')))
    return '\n'.join(lines) + '\n'


# ---------------- 接进离线对照 ----------------

def _pass_count(case, threshold):
    scores = [s for s in (case or {}).get('run_scores') or [] if s is not None]
    return sum(1 for s in scores if s >= threshold), len(scores)


def apply_to_record(rec, satisfied):
    """compare.finalize_run 收尾用：带 TAG 的用例从「当前版 − 不装」的差里拿掉，改记回归结论。原地改 rec。"""
    satisfied = sorted(c for c in satisfied if c in (rec.get('delta') or {}).get('cases', {}))
    if not satisfied:
        return rec
    d = rec['delta']
    cases = d.get('cases') or {}
    raw = {c: cases.get(c) for c in satisfied}
    for c in satisfied:
        cases[c] = None
    kept = [v for k, v in cases.items() if k not in satisfied and v is not None]
    d['overall'] = sum(kept) / len(kept) if kept else None
    d['excluded_baseline_satisfied'] = satisfied
    thr = rec.get('threshold', 1.0)
    cur = (rec.get('arms') or {}).get('current') or {}
    prev = (rec.get('arms') or {}).get('previous') or {}
    out = {}
    for c in satisfied:
        cc = (cur.get('cases') or {}).get(c)
        passes, valid = _pass_count(cc, thr)
        pc = (prev.get('cases') or {}).get(c)
        cur_s, prev_s = (cc or {}).get('score'), (pc or {}).get('score')
        if cur_s is None or not valid:
            status = 'no-score'
        elif prev_s is not None:
            status = 'held' if cur_s >= prev_s else 'regressed'
        else:
            status = 'no-previous' if passes >= needed(valid) else 'below-baseline'
        out[c] = {'status': status, 'current_score': (cc or {}).get('score'), 'current_passes': passes,
                  'current_valid_runs': valid, 'previous_score': (pc or {}).get('score') if pc else None,
                  'none_score': (((rec.get('arms') or {}).get('none') or {}).get('cases') or {}).get(c, {}).get('score'),
                  'raw_delta': raw[c]}
    rec['baseline'] = {
        'tag': TAG, 'cases': out,
        'rule': '基线已满足的用例不进当前版 − 不装的差；有上一版时当前版分 ≥ 上一版分记守住、否则退化；'
                '无上一版时当前版通过 ≥ 有效 run 的 2/3 记无上一版、否则低于基线',
        'regressed': sorted(c for c, v in out.items() if v['status'] in FLAGGED),
    }
    return rec


def report_sections(rec):
    b = rec.get('baseline')
    if not b:
        return []
    lines = ['', '## 回归守护（基线已满足的用例）', '',
             '这些用例在不装插件时就能 ≥ 2/3 通过（`baseline` 判定，tag `%s`），不出「当前版 − 不装」的差，'
             '不计入总体差；只比上一版有没有退化（没有上一版臂时看当前版是否仍 ≥ 2/3 通过）。' % b['tag'], '',
             '| 用例 | 回归结论 | 当前版分 | 当前版通过 / 有效 run | 上一版分 | 不装分 |', '|---|---|---|---|---|---|']
    f = lambda x: '—' if x is None else '%.2f' % x
    for c, v in sorted(b['cases'].items()):
        lines.append('| %s | %s | %s | %d / %d | %s | %s |' % (
            c, ('**%s**' if v['status'] in FLAGGED else '%s') % REGRESSION_TEXT[v['status']],
            f(v['current_score']), v['current_passes'], v['current_valid_runs'], f(v['previous_score']),
            f(v['none_score'])))
    return lines


def is_guarded(rec, case):
    return case in ((rec.get('baseline') or {}).get('cases') or {})


# ---------------- 命令行 ----------------

def add_parser(sub):
    p = sub.add_parser('baseline', help='基线判定：新用例在不装臂跑 %d 次，≥ 2/3 通过的标 %s，只作回归守护' % (RUNS, TAG))
    p.add_argument('name')
    p.add_argument('--case', action='append', help='只判这个用例（evals/ 下的相对目录），可重复')
    p.add_argument('--recheck', action='store_true', help='evals/ 下全部用例重判')
    p.add_argument('--runs', type=int, default=RUNS, help='每例跑几次，默认 %d' % RUNS)
    p.add_argument('--concurrency', type=int, default=3)
    p.add_argument('--model')
    p.add_argument('--threshold', type=float, default=1.0, help='单次通过的规则分下限，默认 1.0')
    return p


def main(args, data_dir):
    from . import compare, preflight
    try:
        run_dir, results = run_baseline(data_dir, args.name, cases=args.case, recheck=args.recheck, runs=args.runs,
                                        concurrency=args.concurrency, model=args.model, threshold=args.threshold)
    except preflight.PreflightFailed as e:
        print('前置检查未通过：%s' % e, file=sys.stderr)
        return 2
    except (BaselineError, compare.CompareError, registry.RegistryError) as e:
        print('错误：%s' % e, file=sys.stderr)
        return 2
    if run_dir is None:
        print('没有要判的用例')
        return 0
    print('运行目录：%s' % run_dir)
    for c, v in results.items():
        print('  %s：%s（%d/%d）' % (c, VERDICTS[v['verdict']], v['passes'], v['runs']))
    return 3 if any(v['verdict'] == 'undecided' for v in results.values()) else 0
