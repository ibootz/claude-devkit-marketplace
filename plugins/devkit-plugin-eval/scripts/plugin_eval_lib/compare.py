"""离线对照（compare）编排：查登记 → 组装各臂 → 每臂跑 eval → 规则判分 → 落盘 → 清理。

臂：不装、上一版（取得到才跑）、当前版、当前版+环境插件（传了才跑）。扩展点：
- 前置检查（票 04，preflight.py）在臂计划定好之后、任何仓库写入之前；
- 上一版 / 环境插件臂（票 05）由 armplan.plan_arms 定，臂清单在 plan.specs；
- 注入到达核验（票 06）在 _run_arm 里搬 trace 之前读转录；
- AI 评委（票 09）在所有臂跑完、写 run.json 之前。
"""
import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import armplan, arms, envplugins, evalrun, fingerprint, preflight, record, registry, scoring, traces


# eval 正常跑完的退出码：0 全过、1 有用例低于 --threshold（判分我们自己重算，不看它）。其余（如 2）是中途中止。
EVAL_OK_EXIT_CODES = (0, 1)


class CompareError(Exception):
    pass


@dataclass
class CompareResult:
    run_dir: Path
    record: dict
    exit_code: int


def _now_iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def git_state(repo, plugin_path):
    """返回 (HEAD sha, 插件目录是否有未提交改动)。不在 git 仓或没有 git 时都是 None。"""
    git = shutil.which('git')
    if not git:
        return None, None
    head = subprocess.run([git, '-C', str(repo), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    if head.returncode != 0:
        return None, None
    scope = ['--', '.', ':(exclude)plugin-evals'] if plugin_path == '.' else ['--', plugin_path]
    st = subprocess.run([git, '-C', str(repo), 'status', '--porcelain', *scope], capture_output=True, text=True)
    return head.stdout.strip(), (bool(st.stdout.strip()) if st.returncode == 0 else None)


def ensure_gitignore(repo, plugin_path):
    """把 <插件>/evals/results/ 写进仓根 .gitignore（eval 裸跑时会往那里写产物）。已有则不动。"""
    line = 'evals/results/' if plugin_path == '.' else '%s/evals/results/' % plugin_path.rstrip('/')
    gi = Path(repo) / '.gitignore'
    text = gi.read_text(encoding='utf-8') if gi.exists() else ''
    if line in (ln.strip() for ln in text.splitlines()):
        return False
    if text and not text.endswith('\n'):
        text += '\n'
    gi.write_text(text + line + '\n', encoding='utf-8')
    return True


def _case_slug(case):
    return scoring._case_rel_dir(case).replace('/', '__')


def _run_arm(spec, *, ctx):
    arm_dir = arms.assemble_arm(ctx['assembly_root'], spec, ctx['evals_src'], extra_exclude=ctx['extra_exclude'])
    env_skipped = envplugins.install(arm_dir, spec.env_plugins) if spec.env_plugins else None
    out_dir = ctx['assembly_root'] / '_out' / spec.key
    log_dir = ctx['traces_root'] / spec.key
    log_dir.mkdir(parents=True, exist_ok=True)
    cmd = evalrun.build_eval_command(ctx['claude'], arm_dir, out_dir, runs=ctx['runs'],
                                     concurrency=ctx['concurrency'], report_path=log_dir / 'report.html',
                                     model=ctx['model'])
    ctx['log']('[%s] 开跑：%s 个用例 × %s 次' % (spec.label, len(ctx['cases']), ctx['runs']))
    exit_code, stderr = ctx['runner'](cmd, arm_dir, ctx['env'], log_dir)

    rec = {
        'label': spec.label,
        'source': 'stub' if spec.source is None else 'working-tree',
        'eval_exit_code': exit_code,
        'trace_dir': 'traces/%s/%s' % (ctx['run_id'], spec.key),
        'cleanup_warnings': [],
    }
    if spec.source is None:
        rec.update(stub_name=arms.STUB_NAME, version=None)
    else:
        rec.update(version=ctx['version'], head_sha=ctx['head_sha'], dirty=ctx['dirty'])
    if spec.record is not None:
        rec.update(spec.record)
    if env_skipped is not None:
        rec['env_not_applied_cases'] = env_skipped

    agg_path = evalrun.find_aggregate(out_dir)
    if agg_path is None:
        rec.update(score=None, cases={}, invalid_run_count=0, aggregate_result=None, cost_usd=None,
                   usage=traces.merge_usage([]), main_model=None, claude_version=None,
                   load_issues=['eval 没有产出 aggregate-result.json（退出码 %s），stderr 见 %s/eval.stderr'
                                % (exit_code, rec['trace_dir'])])
        return rec

    arm_out = ctx['run_dir'] / 'arms' / spec.key
    arm_out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(agg_path, arm_out / 'aggregate-result.json')
    agg = json.loads(agg_path.read_text(encoding='utf-8'))

    usages, models = [], Counter()
    for case in agg.get('cases', []):
        for i, run in enumerate(case.get('arms', {}).get('with', []), 1):
            tp = run.get('tracePath')
            s = traces.summarize_trace(tp)
            usages.append(s['usage'])
            if s['main_model']:
                models[s['main_model']] += 1
            rec['cleanup_warnings'] += traces.harvest_sandbox(
                tp, log_dir / ('%s-%d' % (_case_slug(case), i)), ctx['sandbox_roots'])

    rec.update(
        aggregate_result='arms/%s/aggregate-result.json' % spec.key,
        cost_usd=agg.get('costUsd'), usage=traces.merge_usage(usages),
        main_model=models.most_common(1)[0][0] if models else None,
        claude_version=agg.get('claudeVersion'),
        load_issues=scoring.check_loaded_cases(agg, ctx['cases'], stderr),
    )
    rec['_agg'] = agg   # 判分用，写 run.json 前去掉
    return rec


def _score_arms(arm_records, log):
    """mock_calls grader 是否视同 with-only 只能从装了插件的当前版臂看，两臂用同一份结论，分数才可比。"""
    cur_agg = (arm_records.get('current') or {}).get('_agg')
    mock_cases = scoring.mock_with_only_cases(cur_agg) if cur_agg else set()
    for rec in arm_records.values():
        agg = rec.pop('_agg', None)
        if agg is None:
            continue
        scored = scoring.score_arm(agg, mock_cases)
        rec.update(score=scored['score'], cases=scored['cases'], invalid_run_count=scored['invalid_run_count'])
        log('[%s] 规则分 %s，eval 退出码 %s' % (
            rec['label'], '—' if rec['score'] is None else '%.2f' % rec['score'], rec['eval_exit_code']))


def run_compare(data_dir, name, *, runs=3, concurrency=3, model=None, threshold=1.0, claude=None,
                runner=evalrun.run_eval, env=None, tmp_parent=None, sandbox_roots=None,
                keep_assembly=False, log=None, now=None, base=None, env_plugins=(), preflight_check=None):
    log = log or (lambda msg: print(msg, file=sys.stderr))
    data_dir = Path(data_dir)
    entry = registry.lookup(data_dir, name)          # 未登记即抛 NotRegistered
    repo = Path(entry['repo'])
    plugin_dir = registry.plugin_dir(entry)
    manifest_path = plugin_dir / '.claude-plugin' / 'plugin.json'
    if not manifest_path.is_file():
        raise CompareError('登记的插件目录里没有 .claude-plugin/plugin.json：%s' % plugin_dir)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('name') != name:
        raise CompareError('%s 的 name 是 %r，与登记名 %r 不一致，请重新登记' % (manifest_path, manifest.get('name'), name))
    version = manifest.get('version') or 'noversion'

    evals_src = plugin_dir / 'evals'
    cases = arms.discover_cases(evals_src)
    if not cases:
        raise CompareError('%s 下没有用例（含 prompt.md 或 case.yaml 的目录）' % evals_src)

    extra_exclude = ('.git', 'plugin-evals') if entry['plugin_path'] == '.' else ()
    # 臂计划先定：只往临时目录解快照、不碰仓库，前置检查要拿快照与环境插件去冒烟、validate。
    # 版本号用 plugin.json 原值（没写为 None），别拿占位的 'noversion' 去和历史比。
    plan = armplan.plan_arms(
        plugin_dir=plugin_dir, name=name, version=manifest.get('version'), cases=cases, evals_src=evals_src,
        base=base, env_specs=env_plugins, tmp_parent=tmp_parent, extra_exclude=extra_exclude, env=env, log=log)
    try:
        # 前置检查（票 04）：硬项在任何仓库写入之前查，失败即中止；软项 dirty 在取 git 状态后补，版本与模型跑完后补
        pre = (preflight_check or preflight.check_compare)(
            data_dir=data_dir, name=name, env=evalrun.child_env(env), claude=claude, model=model,
            others=plan.preflight_targets(), env_plugins=plan.env_plugins, tmp_parent=tmp_parent)
        if not pre.passed:
            raise preflight.PreflightFailed(pre)
        claude = claude or pre.claude or evalrun.resolve_claude()
        # 插件在仓根时 .gitignore 就在插件目录里：先写它，再取 git 状态与指纹，否则指纹一跑完就对不上
        ensure_gitignore(repo, entry['plugin_path'])
        head_sha, dirty = git_state(repo, entry['plugin_path'])
        pre.dirty = dirty
        pre.add(preflight.check_dirty(head_sha, dirty))
        plugin_fp = fingerprint.plugin_fingerprint(plugin_dir, extra_exclude)
        child_env = evalrun.child_env(env)

        started = (now or (lambda: datetime.now(timezone.utc)))()
        run_id = '%s-%s-compare' % (started.strftime('%Y%m%dT%H%M%SZ'), version)
        run_dir = repo / 'plugin-evals' / name / 'runs' / run_id
        if run_dir.exists():
            raise CompareError('运行目录已存在：%s' % run_dir)
        run_dir.mkdir(parents=True)

        assembly_root = Path(tempfile.mkdtemp(prefix='devkit-plugin-eval-', dir=tmp_parent))
        ctx = {
            'assembly_root': assembly_root, 'evals_src': evals_src, 'extra_exclude': extra_exclude,
            'traces_root': data_dir / 'traces' / run_id, 'run_dir': run_dir, 'run_id': run_id,
            'claude': claude, 'runs': runs, 'concurrency': concurrency, 'model': model,
            'runner': runner, 'env': child_env, 'cases': cases, 'log': log, 'version': version,
            'head_sha': head_sha, 'dirty': dirty, 'sandbox_roots': sandbox_roots,
        }
        arm_records = {}
        try:
            for spec in plan.specs:
                arm_records[spec.key] = _run_arm(spec, ctx=ctx)
        finally:
            if not keep_assembly:
                shutil.rmtree(assembly_root, ignore_errors=True)
    finally:
        plan.cleanup()
    reasons = []
    _score_arms(arm_records, log)
    for spec in plan.specs:
        rec = arm_records[spec.key]
        if rec['eval_exit_code'] not in EVAL_OK_EXIT_CODES:
            reasons.append('%s臂：eval 退出码 %s（0 / 1 以外：中途中止，如 --max-cost-usd 触顶为 2），结果可能不全'
                           % (spec.label, rec['eval_exit_code']))
        reasons += ['%s臂：%s' % (spec.label, i) for i in rec['load_issues']]
        if rec['invalid_run_count']:
            reasons.append('%s臂：%d 个 run 出错，判无效不计分' % (spec.label, rec['invalid_run_count']))

    rec = record.build_run_record(
        run_id=run_id,
        plugin={'name': name, 'version': version,
                'fingerprint': plugin_fp,
                'fingerprint_exclude': list(fingerprint.FINGERPRINT_EXCLUDE) + list(extra_exclude),
                'path_in_repo': entry['plugin_path']},
        arms=arm_records,
        delta=scoring.delta(arm_records['current'], arm_records['none']),
        cases=cases, incomplete_reasons=reasons, threshold=threshold,
        started_at=_now_iso(started), finished_at=_now_iso(datetime.now(timezone.utc)),
        environment={'claude_path': str(claude), 'node_path': evalrun.which_node(child_env),
                     'runs_per_case': runs, 'concurrency': concurrency, 'model_override': model,
                     'platform': sys.platform},
    )
    rec.update(plan.record_fields(arm_records))
    pre.add(preflight.check_version_model(preflight.previous_compare(run_dir.parent, exclude=run_id),
                                          rec['claude_code_version'], rec['main_model']))
    rec['preflight'] = pre.to_dict()
    rec = record.scrub_home(rec)   # 产物会入库：本机家目录前缀换成 ~
    (run_dir / 'run.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (run_dir / 'report.md').write_text(record.render_report(rec), encoding='utf-8')
    return CompareResult(run_dir, rec, 0 if rec['complete'] else 3)
