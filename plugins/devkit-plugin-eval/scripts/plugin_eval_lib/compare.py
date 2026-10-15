"""离线对照（compare）编排：查登记 → 组装各臂 → 每臂跑 eval → 规则判分 → 落盘 → 清理。

臂：不装、上一版（取得到才跑）、当前版、当前版+环境插件（传了才跑）。扩展点：
- 前置检查（票 04，preflight.py）在臂计划定好之后、任何仓库写入之前；
- 上一版 / 环境插件臂（票 05）由 armplan.plan_arms 定，臂清单在 plan.specs；
- 注入到达核验（票 06）：静态画像在 eval 开跑前按臂算好；_run_arm 把逐 run 搬出的转录目录写进汇总
  （devkitTraceDir），finalize_run 据此重建清单交 injection_check.build；
- AI 评委（票 09）在所有臂跑完、写 run.json 之前。
不完整与续跑（票 07）：每跑完一臂写一次检查点 run.json（complete=false），中途退出也留得下；
收尾在 finalize_run，续跑（resume.py）复用它与 _run_arm，所以这两处的扩展续跑自动带上。
"""
import json
import shutil
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import (armplan, arms, envplugins, evalrun, fingerprint, gitstate, injection, injection_check, preflight,
               record, registry, resume, sandbox_sweep, scoring, traces)


# eval 正常跑完的退出码：0 全过、1 有用例低于 --threshold（判分我们自己重算，不看它）。其余（如 2）是中途中止。
EVAL_OK_EXIT_CODES = (0, 1)
# 汇总里每个 with run 记它搬出的转录目录（相对数据目录的 posix 路径），续跑合并后仍能找回
TRACE_DIR_KEY = 'devkitTraceDir'


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
    """返回 (HEAD sha, 插件目录是否有未提交改动)。不在 git 仓或没有 git 时都是 None。
    dirty 口径（排除 evals/ 与本模块自写的 .gitignore 行）见 gitstate.py，票 14 统一。"""
    return gitstate.git_state(repo, plugin_path)


def ensure_gitignore(repo, plugin_path):
    """把 <插件>/evals/results/ 写进仓根 .gitignore（eval 裸跑时会往那里写产物）。已有则不动。"""
    line = gitstate.gitignore_line(plugin_path)
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


def static_profiles(specs, env, tmp_parent=None):
    """各臂常驻注入的静态画像（票 06）：{臂 key: 画像}，「不装」臂为 None。同一插件目录只算一次。
    在 eval 开跑前算：静态执行 hook 的结果与 eval 无关，放到跑完后算会让中途退出的运行缺这份数据。
    与冒烟一样在插件副本里执行：hook 往 ${CLAUDE_PLUGIN_ROOT} 写的文件不落进用户工作区，也不改插件指纹。"""
    by_source, out = {}, {}
    for spec in specs:
        if spec.source is None:
            out[spec.key] = None
            continue
        src = str(spec.source)
        if src not in by_source:
            work = Path(tempfile.mkdtemp(prefix='devkit-plugin-eval-static-', dir=tmp_parent)).resolve()
            try:
                copy = preflight._plugin_copy(Path(spec.source).resolve(), work / 'plugin')
                by_source[src] = injection.static_profile(copy, env=env, work_parent=work / 'work')
            finally:
                shutil.rmtree(work, ignore_errors=True)
        out[spec.key] = by_source[src]
    return out


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
        rec['cleanup_warnings'] += sandbox_sweep.sweep_orphans(arm_dir, log_dir, ctx['sandbox_roots'])
        return rec

    agg = json.loads(agg_path.read_text(encoding='utf-8'))
    usages, models = [], Counter()
    for case in agg.get('cases', []):
        for i, run in enumerate(case.get('arms', {}).get('with', []), 1):
            tp = run.get('tracePath')
            s = traces.summarize_trace(tp)
            usages.append(s['usage'])
            if s['main_model']:
                models[s['main_model']] += 1
            run_name = '%s-%d' % (_case_slug(case), i)
            rec['cleanup_warnings'] += traces.harvest_sandbox(tp, log_dir / run_name, ctx['sandbox_roots'])
            run[TRACE_DIR_KEY] = '%s/%s' % (rec['trace_dir'], run_name)
    rec['cleanup_warnings'] += sandbox_sweep.sweep_orphans(arm_dir, log_dir, ctx['sandbox_roots'])

    arm_out = ctx['run_dir'] / 'arms' / spec.key
    arm_out.mkdir(parents=True, exist_ok=True)
    resume.write_json_atomic(arm_out / 'aggregate-result.json', agg)   # 带上 devkitTraceDir 标注
    rec.update(
        aggregate_result='arms/%s/aggregate-result.json' % spec.key,
        cost_usd=agg.get('costUsd'), usage=traces.merge_usage(usages),
        main_model=models.most_common(1)[0][0] if models else None,
        claude_version=agg.get('claudeVersion'),
        load_issues=scoring.check_loaded_cases(agg, ctx['cases'], stderr),
    )
    rec['_agg'] = agg   # 判分用，写 run.json 前去掉
    return rec


def _runs_from_agg(agg, data_dir):
    """注入核验要的逐 run 转录位置：[{case, run, dir, trace_path}]。dir 取汇总里记的 devkitTraceDir。"""
    out = []
    for case in (agg or {}).get('cases', []):
        for i, run in enumerate(case.get('arms', {}).get('with', []), 1):
            rel = run.get(TRACE_DIR_KEY)
            out.append({'case': scoring._case_rel_dir(case), 'run': i,
                        'dir': Path(data_dir) / rel if rel else None, 'trace_path': run.get('tracePath')})
    return out


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


def load_target(data_dir, name):
    """读登记与被测插件：返回 (entry, plugin_dir, manifest, evals_src, cases, extra_exclude)。
    未登记抛 registry.NotRegistered；plugin.json 缺失、name 不符或没有用例抛 CompareError。compare 与 check 共用。"""
    entry = registry.lookup(Path(data_dir), name)
    plugin_dir = registry.plugin_dir(entry)
    manifest_path = plugin_dir / '.claude-plugin' / 'plugin.json'
    if not manifest_path.is_file():
        raise CompareError('登记的插件目录里没有 .claude-plugin/plugin.json：%s' % plugin_dir)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('name') != name:
        raise CompareError('%s 的 name 是 %r，与登记名 %r 不一致，请重新登记' % (manifest_path, manifest.get('name'), name))
    evals_src = plugin_dir / 'evals'
    cases = arms.discover_cases(evals_src)
    if not cases:
        raise CompareError('%s 下没有用例（含 prompt.md 或 case.yaml 的目录）' % evals_src)
    extra_exclude = ('.git', 'plugin-evals') if entry['plugin_path'] == '.' else ()
    return entry, plugin_dir, manifest, evals_src, cases, extra_exclude


def plan_for(plugin_dir, name, manifest, cases, evals_src, extra_exclude, *, base=None, env_plugins=(),
             tmp_parent=None, env=None, log=None):
    """臂计划：只往临时目录解快照、不碰仓库。版本号用 plugin.json 原值（没写为 None），别拿占位的 'noversion' 去和历史比。"""
    return armplan.plan_arms(
        plugin_dir=plugin_dir, name=name, version=manifest.get('version'), cases=cases, evals_src=evals_src,
        base=base, env_specs=env_plugins, tmp_parent=tmp_parent, extra_exclude=extra_exclude, env=env, log=log)


def run_compare(data_dir, name, *, runs=3, concurrency=3, model=None, threshold=1.0, claude=None,
                runner=evalrun.run_eval, env=None, tmp_parent=None, sandbox_roots=None,
                keep_assembly=False, log=None, now=None, base=None, env_plugins=(), preflight_check=None):
    log = log or (lambda msg: print(msg, file=sys.stderr))
    data_dir = Path(data_dir)
    entry, plugin_dir, manifest, evals_src, cases, extra_exclude = load_target(data_dir, name)  # 未登记即抛 NotRegistered
    repo = Path(entry['repo'])
    version = manifest.get('version') or 'noversion'
    # 臂计划先定：前置检查要拿快照与环境插件去冒烟、validate。
    plan = plan_for(plugin_dir, name, manifest, cases, evals_src, extra_exclude, base=base, env_plugins=env_plugins,
                    tmp_parent=tmp_parent, env=env, log=log)
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
        evals_fp = fingerprint.evals_fingerprint(evals_src, cases)
        child_env = evalrun.child_env(env)

        started = (now or (lambda: datetime.now(timezone.utc)))()
        run_id = '%s-%s-compare' % (started.strftime('%Y%m%dT%H%M%SZ'), version)
        run_dir = repo / 'plugin-evals' / name / 'runs' / run_id
        if run_dir.exists():
            raise CompareError('运行目录已存在：%s' % run_dir)
        run_dir.mkdir(parents=True)

        meta = dict(log=log, run_id=run_id, name=name, version=version, plugin_fp=plugin_fp, evals_fp=evals_fp,
                    extra_exclude=extra_exclude, entry=entry, cases=cases, threshold=threshold, started=started,
                    claude=claude, child_env=child_env, runs=runs, concurrency=concurrency, model=model,
                    run_dir=run_dir, data_dir=data_dir, plan=plan, pre=pre)
        arm_records = {}
        lock = resume.RunLock(data_dir, run_id)
        lock.acquire()
        try:
            resume.write_checkpoint(meta, arm_records)
            meta['statics'] = static_profiles(plan.specs, child_env, tmp_parent)
            assembly_root = Path(tempfile.mkdtemp(prefix='devkit-plugin-eval-', dir=tmp_parent))
            ctx = {
                'assembly_root': assembly_root, 'evals_src': evals_src, 'extra_exclude': extra_exclude,
                'traces_root': data_dir / 'traces' / run_id, 'run_dir': run_dir, 'run_id': run_id,
                'claude': claude, 'runs': runs, 'concurrency': concurrency, 'model': model,
                'runner': runner, 'env': child_env, 'cases': cases, 'log': log, 'version': version,
                'head_sha': head_sha, 'dirty': dirty, 'sandbox_roots': sandbox_roots,
            }
            try:
                for spec in plan.specs:
                    arm_records[spec.key] = _run_arm(spec, ctx=ctx)
                    resume.write_checkpoint(meta, arm_records)
            finally:
                if not keep_assembly:
                    shutil.rmtree(assembly_root, ignore_errors=True)
            return finalize_run(arm_records, [], **meta)
        finally:
            lock.release()
    finally:
        plan.cleanup()


def finalize_run(arm_records, reasons, *, log, run_id, name, version, plugin_fp, evals_fp, extra_exclude, entry,
                 cases, threshold, started, claude, child_env, runs, concurrency, model, run_dir, data_dir,
                 plan, pre, statics, prior_preflight=None, decorate=None):
    """判分、注入核验、汇总不完整原因、写 injection-check.json、run.json 与 report.md。
    arm_records 里带 _agg 的臂才判分、才有逐 run 的注入核验。pre 是本次的前置检查报告（Report）；
    prior_preflight 是续跑时首跑记下的那份（dict），软项提示并进本次。decorate(rec) 在落盘前改记录。"""
    for key, rec in arm_records.items():
        rec['_static'] = statics.get(key)
        rec['_runs'] = _runs_from_agg(rec.get('_agg'), data_dir)
    _score_arms(arm_records, log)
    inj_check, resident = injection_check.build(arm_records)
    for problem in inj_check['problems']:
        log('[注入核验] %s' % problem)
    for spec in plan.specs:
        rec = arm_records[spec.key]
        if rec['eval_exit_code'] not in EVAL_OK_EXIT_CODES:
            reasons.append('%s臂：eval 退出码 %s（0 / 1 以外：中途中止，如 --max-cost-usd 触顶为 2），结果可能不全'
                           % (spec.label, rec['eval_exit_code']))
        reasons += ['%s臂：%s' % (spec.label, i) for i in rec['load_issues']]
        if rec['invalid_run_count']:
            reasons.append('%s臂：%d 个 run 出错，判无效不计分%s' % (spec.label, rec['invalid_run_count'],
                                                               resume.usage_limit_note(rec)))
        if len(rec.get('main_models') or []) > 1:
            reasons.append('%s臂：续跑时主力模型与首跑不同（%s），前后两段结果不可比，续跑合不成完整；请重新对照'
                           % (spec.label, ' → '.join(rec['main_models'])))

    rec = record.build_run_record(
        run_id=run_id,
        plugin=resume.plugin_block(name=name, version=version, plugin_fp=plugin_fp, evals_fp=evals_fp,
                                   extra_exclude=extra_exclude, entry=entry),
        arms=arm_records,
        delta=scoring.delta(arm_records['current'], arm_records['none']),
        cases=cases, incomplete_reasons=reasons, threshold=threshold,
        started_at=_now_iso(started), finished_at=_now_iso(datetime.now(timezone.utc)),
        environment={'claude_path': str(claude), 'node_path': evalrun.which_node(child_env),
                     'runs_per_case': runs, 'concurrency': concurrency, 'model_override': model,
                     'platform': sys.platform},
    )
    rec.update(plan.record_fields(arm_records))
    pre.add(preflight.check_version_model(preflight.previous_compare(Path(run_dir).parent, exclude=run_id),
                                          rec['claude_code_version'], rec['main_model']))
    rec['preflight'] = _merge_preflight(pre.to_dict(), prior_preflight)
    rec.update(injection_check=injection_check.summary(inj_check), resident_tokens=resident)
    if decorate:
        rec = decorate(rec)
    rec = record.scrub_home(rec)   # 产物会入库：本机家目录前缀换成 ~
    resume.write_json_atomic(Path(run_dir) / 'injection-check.json', record.scrub_home(inj_check))
    resume.write_json_atomic(Path(run_dir) / 'run.json', rec)
    (Path(run_dir) / 'report.md').write_text(record.render_report(rec) + resume.report_section(rec), encoding='utf-8')
    return CompareResult(Path(run_dir), rec, 0 if rec['complete'] else 3)


def _merge_preflight(current, prior):
    """续跑：首跑的软项提示保留（去重后排在前面），整份首跑结果另存在 first_run 下。
    多次续跑时 prior 已是合并过的那份：first_run 沿用它记下的真正首跑，不层层嵌套。"""
    if not prior:
        return current
    merged = dict(current)
    merged['warnings'] = list(dict.fromkeys(list(prior.get('warnings') or []) + list(current.get('warnings') or [])))
    merged['first_run'] = prior.get('first_run') or prior
    return merged

