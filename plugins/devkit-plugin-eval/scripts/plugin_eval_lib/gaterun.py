"""规则判分子集（票 15；spec「2.8 发版闸门（gate）」覆盖范围第 2 条，设计票 12 第 2 条）。

闸门外的版本（非 major、未声明 eval-required:）发版前的依据：取全部能用规则判分的用例，只跑当前版一臂、
不调 AI 评委、不跑条款清单检查、不进待审页、无需审阅，但真跑模型。结果写
`<仓>/plugin-evals/<插件>/runs/<UTC 时间>-<版本>-gate/`，run.json 的 kind=gate，供 gate.assess_run 采信。

为什么不复用 compare.run_compare：它固定按 armplan 排「不装 / 上一版 / 当前版」三臂（还要解 git 快照）、
第 2 步总会调条款清单检查、收尾总算「当前版 − 不装」的差并调 AI 评委，报告也按多臂渲染；
要它只跑一臂得在共享文件里加一串开关。这里直接复用它的零件（load_target、_run_arm、static_profiles、
ensure_gitignore）与 record / resume / injection_check 的落盘函数，编排单独写。

与离线对照的差别：
- 用例：只取有规则 grader（regex / tool_order / tool_used / file_exists）的用例（select_rule_cases）；
  只有付费 grader（llm 等）或只有 AI 评委判定标准的用例不跑，列进 rule_subset.excluded_cases。
- 判分：只有一臂、不比臂，with-only 的 grader 照计分（scoring.score_arm(count_with_only=True)），
  与 eval 在 --ablation none 下的原生计分一致；付费 grader 照旧不计。
- 是否通过：运行完整，且每个有分用例的规则分都 ≥ threshold（票 03 口径，作用在这一臂上）。
- 不能续跑（resume 只认 kind=compare）：不完整就重跑一次规则子集。
前置检查（spec 2.6）照 compare 跑 check_compare：硬项失败即中止；dirty 等软项照跑并记进 run.json。
"""
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import (arms, compare, evalrun, fingerprint, gate, gitstate, injection_check, preflight, record, resume, scoring)

KIND = 'gate'
RUN_SUFFIX = '-gate'
JUDGE_SKIPPED = 'gate-rule-subset'
PASS_CRITERION = ('运行完整，且当前版每个有分用例的规则分都 ≥ threshold（规则子集：只跑当前版一臂，'
                  'with-only grader 照计分，付费 grader 不计）')
NO_SCORABLE_REASON = '没有可计分的规则 grader'
_TYPE_RE = re.compile(r'^type\s*:\s*["\']?([A-Za-z_]+)', re.MULTILINE)
_YAML_GRADERS_RE = re.compile(r'^graders\s*:', re.MULTILINE)


class GateRunError(Exception):
    pass


def _grader_type(text):
    text = (text or '').replace('\r\n', '\n')
    if not text.startswith('---\n'):
        return None
    end = text.find('\n---', 4)
    m = _TYPE_RE.search(text[4:end if end != -1 else len(text)])
    return m.group(1) if m else None


def select_rule_cases(evals_src, cases):
    """(要跑的用例, {不跑的用例: 原因})。

    看用例 graders/*.md 的 frontmatter type：至少一个是规则类型就跑；声明了 grader 却全是付费类型就不跑。
    读不出（没有 graders/*.md，或 case.yaml 里另有 graders: 段）时照跑，交给跑完后的判分——宁可多跑，不漏判。"""
    evals_src = Path(evals_src)
    run, skipped = [], {}
    for case in cases:
        d = evals_src / case
        types = [_grader_type(p.read_text(encoding='utf-8', errors='replace'))
                 for p in sorted((d / 'graders').glob('*.md'))] if (d / 'graders').is_dir() else []
        types = [t for t in types if t]
        yaml_graders = (d / 'case.yaml').is_file() and \
            _YAML_GRADERS_RE.search((d / 'case.yaml').read_text(encoding='utf-8', errors='replace'))
        if not types or yaml_graders or any(t in scoring.RULE_GRADER_TYPES for t in types):
            run.append(case)
        else:
            skipped[case] = '没有规则 grader（只有 %s）' % '、'.join(sorted(set(types)))
    return run, skipped


def _now_iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def _build(meta, arm_records, reasons, finished):
    rec = record.build_run_record(
        run_id=meta['run_id'], plugin=resume.plugin_block(**meta),
        arms={k: resume._public(v) for k, v in arm_records.items()},
        delta={'cases': {}, 'overall': None, 'missing_cases': []}, cases=meta['cases'],
        incomplete_reasons=reasons, threshold=meta['threshold'], started_at=_now_iso(meta['started']),
        finished_at=finished, environment=resume.environment_block(**meta))
    rec.update(kind=KIND, delta=None, review=None, judge={'skipped': JUDGE_SKIPPED}, pass_criterion=PASS_CRITERION,
               rule_subset={'cases': meta['cases'], 'excluded_cases': meta['excluded'], 'count_with_only': True})
    rec['preflight'] = meta['pre'].to_dict()
    return rec


def run_subset(data_dir, name, *, runs=3, concurrency=3, model=None, threshold=1.0, claude=None,
               runner=evalrun.run_eval, env=None, tmp_parent=None, sandbox_roots=None, keep_assembly=False,
               log=None, now=None, preflight_check=None, plugin_dir=None):
    """跑一次规则子集，返回 compare.CompareResult（退出码 0 完整、3 不完整）。
    plugin_dir：gate 入参的插件目录；给了就核对与登记的是同一个目录，免得评到别处的同名插件。"""
    log = log or (lambda msg: print(msg, file=sys.stderr))
    data_dir = Path(data_dir)
    entry, pdir, manifest, evals_src, all_cases, extra_exclude = compare.load_target(data_dir, name)
    if plugin_dir is not None and Path(plugin_dir).resolve() != pdir.resolve():
        raise GateRunError('登记的 %s 在 %s，与 gate 入参 %s 不是同一个目录；请重新登记或改入参'
                           % (name, pdir, Path(plugin_dir).resolve()))
    cases, excluded = select_rule_cases(evals_src, all_cases)
    if not cases:
        raise GateRunError('%s 下没有能用规则判分的用例（%s）：规则子集无从跑起，需改跑离线对照或补规则 grader'
                           % (evals_src, '；'.join('%s：%s' % kv for kv in sorted(excluded.items()))))
    repo = Path(entry['repo'])
    child_env = evalrun.child_env(env)
    pre = (preflight_check or preflight.check_compare)(
        data_dir=data_dir, name=name, env=child_env, claude=claude, model=model, tmp_parent=tmp_parent)
    if not pre.passed:
        raise preflight.PreflightFailed(pre)
    claude = claude or pre.claude or evalrun.resolve_claude()
    compare.ensure_gitignore(repo, entry['plugin_path'])
    head_sha, dirty = gitstate.git_state(repo, entry['plugin_path'])
    pre.dirty = dirty
    pre.add(preflight.check_dirty(head_sha, dirty))

    version = manifest.get('version') or 'noversion'
    started = (now or (lambda: datetime.now(timezone.utc)))()
    run_id = '%s-%s%s' % (started.strftime('%Y%m%dT%H%M%SZ'), version, RUN_SUFFIX)
    run_dir = repo / 'plugin-evals' / name / 'runs' / run_id
    if run_dir.exists():
        raise GateRunError('运行目录已存在：%s' % run_dir)
    run_dir.mkdir(parents=True)
    meta = dict(run_id=run_id, name=name, version=version, entry=entry, extra_exclude=extra_exclude,
                plugin_fp=fingerprint.plugin_fingerprint(pdir, extra_exclude),
                evals_fp=fingerprint.evals_fingerprint(evals_src, cases), cases=cases, excluded=excluded,
                threshold=threshold, started=started, claude=claude, child_env=child_env, runs=runs,
                concurrency=concurrency, model=model, judge_opts={'enabled': False}, clause_model=None, pre=pre)
    log('[规则子集] %d 个用例 × %d 次，只跑当前版一臂；不跑的用例 %d 个' % (len(cases), runs, len(excluded)))

    lock = resume.RunLock(data_dir, run_id)
    lock.acquire()
    try:
        ckpt = _build(meta, {}, ['%s（规则子集）' % resume.CHECKPOINT_REASON], None)
        resume.write_json_atomic(run_dir / 'run.json', record.scrub_home(ckpt))
        spec = arms.ArmSpec('current', '当前版', pdir)
        statics = compare.static_profiles([spec], child_env, tmp_parent)
        work = Path(tempfile.mkdtemp(prefix='devkit-plugin-eval-gate-', dir=tmp_parent))
        try:
            subset_evals = resume._subset_evals(evals_src, set(cases), work / 'evals')
            ctx = {'assembly_root': work / 'arms', 'evals_src': subset_evals, 'extra_exclude': extra_exclude,
                   'traces_root': data_dir / 'traces' / run_id, 'run_dir': run_dir, 'run_id': run_id,
                   'claude': claude, 'runs': runs, 'concurrency': concurrency, 'model': model, 'runner': runner,
                   'env': child_env, 'cases': cases, 'log': log, 'version': version, 'head_sha': head_sha,
                   'dirty': dirty, 'sandbox_roots': sandbox_roots}
            (work / 'arms').mkdir()
            arm = compare._run_arm(spec, ctx=ctx)
        finally:
            if not keep_assembly:
                shutil.rmtree(work, ignore_errors=True)
        return _finalize(arm, statics, meta, run_dir, data_dir, log)
    finally:
        lock.release()


def _finalize(arm, statics, meta, run_dir, data_dir, log):
    agg = arm.pop('_agg', None)
    arm['_static'] = statics.get('current')
    arm['_runs'] = compare._runs_from_agg(agg, data_dir)
    if agg is not None:
        scored = scoring.score_arm(agg, count_with_only=True)
        arm.update(score=scored['score'], cases=scored['cases'], invalid_run_count=scored['invalid_run_count'])
    log('[规则子集] 规则分 %s，eval 退出码 %s' % ('—' if arm.get('score') is None else '%.2f' % arm['score'],
                                         arm['eval_exit_code']))
    inj, resident = injection_check.build({'current': arm})
    for problem in inj['problems']:
        log('[注入核验] %s' % problem)
    reasons = []
    if arm['eval_exit_code'] not in compare.EVAL_OK_EXIT_CODES:
        reasons.append('eval 退出码 %s（0 / 1 以外：中途中止），结果可能不全' % arm['eval_exit_code'])
    reasons += list(arm.get('load_issues') or [])
    if arm.get('invalid_run_count'):
        reasons.append('%d 个 run 出错，判无效不计分%s' % (arm['invalid_run_count'], resume.usage_limit_note(arm)))
    if agg is not None and not any(c.get('score') is not None for c in (arm.get('cases') or {}).values()):
        # B 批集成定稿第 6 条：全部用例都没有可计分的规则 grader 时记不完整，gate 不采信，也不报「规则子集未通过」
        reasons.append(NO_SCORABLE_REASON)
    rec = _build(meta, {'current': arm}, reasons, _now_iso(datetime.now(timezone.utc)))
    pre = meta['pre']
    pre.add(preflight.check_version_model(preflight.previous_compare(Path(run_dir).parent),
                                          rec['claude_code_version'], rec['main_model']))
    rec['preflight'] = pre.to_dict()
    rec.update(injection_check=injection_check.summary(inj), resident_tokens=resident)
    rec = record.scrub_home(rec)
    resume.write_json_atomic(Path(run_dir) / 'injection-check.json', record.scrub_home(inj))
    resume.write_json_atomic(Path(run_dir) / 'run.json', rec)
    (Path(run_dir) / 'report.md').write_text(render_report(rec), encoding='utf-8')
    return compare.CompareResult(Path(run_dir), rec, 0 if rec['complete'] else 3)


def _f(x):
    return '—' if x is None else '%.2f' % x


def render_report(rec):
    p, cur, u = rec['plugin'], (rec['arms'].get('current') or {}), rec['usage']
    lines = [
        '# 规则判分子集：%s %s' % (p['name'], p['version']), '',
        '> 闸门外版本的发版依据（spec 2.8）：只跑当前版一臂、只用规则判分；不调 AI 评委、不跑条款清单检查、'
        '不进待审页、无需审阅。闸门内版本（major 升版、声明 eval-required:）不认这份结果。', '',
        '- 运行：`%s`，%s 至 %s（UTC）' % (rec['run_id'], rec['started_at'], rec['finished_at']),
        '- 插件内容指纹：`%s`' % p['fingerprint'],
        '- Claude Code：%s；主力模型：%s' % (rec['claude_code_version'], rec['main_model']),
        '- 每例 %s 次' % (rec.get('environment') or {}).get('runs_per_case', '?'),
        '- 是否完整：%s' % ('是' if rec['complete'] else '**不完整**（规则子集不能续跑，重跑一次）'),
        '- 是否通过：%s（口径：%s；%s）' % ('是' if rec['passed'] else '否', rec['pass_criterion'],
                                       gate.threshold_text(rec['threshold'])),
        '- 花费：$%.4f（%s）' % (u['cost_usd'], u['cost_basis']),
    ]
    pre = rec.get('preflight') or {}
    if pre.get('warnings'):
        lines += ['', '> **前置检查软项**（照跑；dirty 的结果不计入发版闸门）：', '>']
        lines += ['> - %s' % w for w in pre['warnings']]
    lines += injection_check.report_banner(rec)
    if rec['incomplete_reasons']:
        lines += ['', '## 不完整的原因', ''] + ['- %s' % r for r in rec['incomplete_reasons']]
    lines += ['', '## 逐用例', '', '| 用例 | 规则分 | 逐次 | 未计分的 grader |', '|---|---|---|---|']
    for name in rec['cases']:
        c = (cur.get('cases') or {}).get(name) or {}
        ex = '、'.join('`%s`（%s）' % kv for kv in sorted((c.get('excluded_graders') or {}).items())) or '—'
        lines.append('| %s | %s | %s | %s |' % (name, _f(c.get('score')),
                                               ' / '.join(_f(s) for s in c.get('run_scores', [])) or '—', ex))
    below = [n for n in rec['cases'] if ((cur.get('cases') or {}).get(n) or {}).get('score') is not None
             and cur['cases'][n]['score'] < rec['threshold']]
    if below:
        lines += ['', '## 未达 threshold 的用例', ''] + ['- %s：%s' % (n, _f(cur['cases'][n]['score'])) for n in below]
    unscored = [n for n, c in (cur.get('cases') or {}).items() if c.get('no_scored_graders')]
    if unscored:
        lines += ['', '## 没有可计分 grader 的用例（不参与「是否通过」）', ''] + ['- %s' % n for n in unscored]
    excluded = (rec.get('rule_subset') or {}).get('excluded_cases') or {}
    if excluded:
        lines += ['', '## 不在规则子集里的用例（未跑）', '']
        lines += ['- %s：%s' % kv for kv in sorted(excluded.items())]
    lines += injection_check.report_sections(rec)
    return '\n'.join(lines) + '\n'


def console_lines(res):
    rec = res.record
    cur = rec['arms'].get('current') or {}
    out = ['规则子集运行目录：%s' % res.run_dir,
           '当前版规则分 %s；完整：%s；通过：%s；花费（标价估算）：$%.4f' % (
               _f(cur.get('score')), '是' if rec['complete'] else '否', '是' if rec['passed'] else '否',
               rec['usage']['cost_usd']),
           '口径：%s' % gate.threshold_text(rec['threshold'])]
    out += ['  不完整原因：%s' % r for r in rec['incomplete_reasons']]
    return out
