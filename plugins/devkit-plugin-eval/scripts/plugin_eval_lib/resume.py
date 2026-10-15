"""不完整运行的检查点与断点续跑（spec「2.2 离线对照」末段，票 07）。

- 检查点：compare 开跑前、每跑完一臂，都把当前进度写成 run.json（complete=false）。进程中途退出
  （异常、Ctrl-C、被杀）也留得下一份不完整的 run.json，闸门据此排除，续跑据此接着跑。
- 续跑：`resume <运行目录>`。逐臂对照 arms/<臂>/aggregate-result.json：每个用例的有效 run
  （error 为空）留着不重跑，缺多少补多少；没有汇总的臂整臂重跑。补跑的 run 合并进同一份汇总后，
  按 compare 同一套判分重算（compare.finalize_run），所以分数口径与一次跑完相同。
- 只在插件版本与内容指纹都与首跑一致时续跑；用例集合沿用首跑 run.json 的 cases。
- 臂计划按首跑记下的来源重建（armplan.rebuild_plan）：上一版须是同一提交、环境插件须同版本同内容。
  拿锁之前重跑前置检查硬项（票 04），不过即中止。注入核验与常驻 token（票 06）在 finalize_run 里按合并后的
  汇总重算，所以续跑后仍按臂完整。
- 同一个运行目录同一时刻只许一个进程写：操作系统咨询锁，锁文件在用户级数据目录 locks/ 下，不进被测仓。
"""
import copy
import json
import os
import shutil
import socket
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import armplan, arms, completeness, evalrun, fingerprint, preflight, record, registry, scoring
from . import compare  # 循环导入：compare 也导入本模块，这里只在函数体里用 compare.X

CHECKPOINT_REASON = '运行未结束：对照进行中，或进程中途退出、没写入最终结果'


class ResumeError(Exception):
    pass


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def _public(arm_rec):
    """去掉 _agg 这类只在内存里用的键，深拷贝一份。"""
    return copy.deepcopy({k: v for k, v in (arm_rec or {}).items() if not k.startswith('_')})


# ---------- 锁 ----------

if sys.platform == 'win32':
    import msvcrt

    def _try_lock(fh):
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)   # 锁第 0 字节；被占用抛 OSError

    def _unlock(fh):
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_lock(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)   # 被占用抛 OSError（EWOULDBLOCK）

    def _unlock(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class RunLock:
    """<数据目录>/locks/<run_id>.lock 上的操作系统咨询锁（POSIX flock / Windows msvcrt.locking）。

    持锁进程活着就一直持有，进程一死（含被 kill -9）由系统自动释放，不用判断「持有者是否已死」，
    也就没有「空锁文件被当成死锁接管」「两个进程同时接管」这类竞态。锁文件本身不删（删了会让后来者
    锁到另一个 inode 上），内容只是持有者的 pid 与主机名，供报错时提示。
    """

    def __init__(self, data_dir, run_id):
        self.path = Path(data_dir) / 'locks' / ('%s.lock' % run_id)
        self.held = False
        self._fh = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(str(self.path), 'a+', encoding='utf-8')
        try:
            _try_lock(fh)
        except OSError:
            fh.close()
            holder = self._holder()
            raise ResumeError('运行 %s 正在被进程 %s（主机 %s）对照或续跑；它结束后再续跑'
                              % (self.path.stem, holder.get('pid', '?'), holder.get('host', '?')))
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps({'pid': os.getpid(), 'host': socket.gethostname()}))
        fh.flush()
        self._fh, self.held = fh, True
        return self

    def busy(self):
        """别的进程正持有这把锁（试拿一下立刻放掉）。"""
        if self.held or not self.path.exists():
            return False
        try:
            fh = open(str(self.path), 'a+', encoding='utf-8')
        except OSError:
            return False
        try:
            _try_lock(fh)
        except OSError:
            return True
        else:
            _unlock(fh)
            return False
        finally:
            fh.close()

    def _holder(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def release(self):
        if self.held:
            try:
                self._fh.seek(0)
                self._fh.truncate()
                self._fh.flush()
                _unlock(self._fh)
            except OSError:
                pass
            finally:
                self._fh.close()
                self._fh, self.held = None, False


# ---------- 检查点 ----------

def plugin_block(*, name, version, plugin_fp, evals_fp, extra_exclude, entry, **_):
    """run.json 的 plugin 段。evals_fingerprint 是用例目录指纹（不进插件指纹），续跑据此拒绝改过用例的运行。"""
    return {'name': name, 'version': version, 'fingerprint': plugin_fp,
            'fingerprint_exclude': list(fingerprint.FINGERPRINT_EXCLUDE) + list(extra_exclude),
            'path_in_repo': entry['plugin_path'], 'evals_fingerprint': evals_fp}


def environment_block(*, claude, child_env, runs, concurrency, model, judge_opts=None, clause_model=None, **_):
    """run.json 的 environment 段（检查点与最终结果共用）。judge / clause_model 是首跑的命令行选项，续跑读回沿用：
    judge = {enabled, model}（model 只记 --judge-model，配置文件与缺省值续跑时照常解析）；早于本字段的运行为 None。"""
    jo = judge_opts if isinstance(judge_opts, dict) else None
    return {'claude_path': str(claude), 'node_path': evalrun.which_node(child_env),
            'runs_per_case': runs, 'concurrency': concurrency, 'model_override': model,
            'platform': sys.platform,
            'judge': None if jo is None else {'enabled': jo.get('enabled') is not False, 'model': jo.get('model')},
            'clause_model': clause_model}


def _environment(meta):
    return environment_block(**meta)


def judge_opts_from(environment, plugin_evals, runner=None):
    """续跑：按首跑记下的 environment.judge 还原评委选项。首跑 --no-judge → 不调评委、不读配置；
    首跑 --judge-model X → 仍用 X。早于本字段的运行返回 None（按配置与 judge.json 解析，同旧行为）。"""
    from . import judge
    j = (environment or {}).get('judge')
    if not isinstance(j, dict):
        return {'runner': runner} if runner else None
    if j.get('enabled') is False:
        return {'enabled': False}
    try:
        cfg = judge.load_config(plugin_evals)
    except judge.JudgeConfigError as e:
        raise ResumeError(str(e))
    return {'enabled': True, 'model': j.get('model'), 'runner': runner, 'config': cfg}


def write_json_atomic(path, obj):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(str(tmp), str(path))





def write_checkpoint(meta, arm_records, extra=None):
    """把进度写成 run.json：complete=false，已跑完的臂照记（尚未判分），没跑的臂为 null。
    同时记下臂计划的来源字段（续跑据此重建）与前置检查结果。"""
    done = [arm_records[k].get('label', k) for k in record.ARM_ORDER if arm_records.get(k)]
    rec = record.build_run_record(
        run_id=meta['run_id'], plugin=plugin_block(**meta),
        arms={k: _public(v) for k, v in arm_records.items() if v},
        delta={'cases': {}, 'overall': None, 'missing_cases': []},
        cases=meta['cases'],
        incomplete_reasons=['%s（已跑完的臂：%s）' % (CHECKPOINT_REASON, '、'.join(done) or '无')],
        threshold=meta['threshold'], started_at=_iso(meta['started']), finished_at=None,
        environment=_environment(meta))
    rec.update(meta['plan'].checkpoint_fields(arm_records))
    rec['preflight'] = meta['pre'].to_dict()
    if extra:
        rec.update(extra)
    write_json_atomic(Path(meta['run_dir']) / 'run.json', record.scrub_home(rec))


# ---------- 报告与提示 ----------

def usage_limit_note(arm_rec):
    n = completeness.usage_limit_count(arm_rec)
    return '（其中 %d 个撞订阅用量限制）' % n if n else ''


def _cli_prefix(data_dir):
    script = Path(__file__).resolve().parents[1] / 'plugin_eval.py'
    return '"%s" "%s" --data-dir "%s"' % (sys.executable, script, data_dir)


def resume_hint(run_dir, data_dir):
    """给命令行输出用的续跑命令（含本机绝对路径，不写进入库产物）。"""
    return '%s resume "%s"' % (_cli_prefix(data_dir), run_dir)


def pending_hint(data_dir, name, run_id):
    """compare 收尾打印的下一步（生成本次对照的待审页）。带 --run：后台跑期间别的 drafts / clauses 运行不会抢走「最新」。"""
    return '下一步：生成待审页 → %s pending %s --run %s' % (_cli_prefix(data_dir), name, run_id)


def report_section(rec):
    """report.md 末尾：续跑记录；不完整时附续跑办法。"""
    lines = []
    attempts = (rec.get('resume') or {}).get('attempts') or []
    if attempts:
        lines += ['', '## 续跑记录', '',
                  '已完成的 run 不重跑，只补跑判无效与未跑的 run；分数按合并后的有效 run 计，口径与一次跑完相同。'
                  '花费与 token 含首跑里出错的 run。', '']
        for a in attempts:
            reran = '；'.join('%s臂 %s' % (((rec.get('arms') or {}).get(arm) or {}).get('label', arm),
                                          '、'.join('%s × %d' % (c, n) for c, n in cs.items()))
                             for arm, cs in a.get('reran', {}).items()) or '无'
            kinds = Counter(r.get('error_kind') for r in a.get('replaced_invalid_runs', []))
            lines.append('- 第 %d 次（%s 至 %s，UTC）：补跑 %s；替换掉的无效 run %d 个，其中撞订阅用量限制 %d 个' % (
                a['attempt'], a.get('started_at'), a.get('finished_at') or '未结束', reran,
                sum(kinds.values()), kinds.get('usage_limit', 0)))
            lines += ['  - 注意：%s' % w for w in a.get('warnings', [])]
    if not rec.get('complete'):
        lines += ['', '## 续跑', '',
                  '本次运行不完整，不计入发版闸门。撞订阅用量限制的，等额度恢复后在被测插件所在仓根执行：', '',
                  '```',
                  'python3 <devkit-plugin-eval 插件目录>/scripts/plugin_eval.py --data-dir <数据目录> resume '
                  'plugin-evals/%s/runs/%s' % (rec['plugin']['name'], rec['run_id']),
                  '```', '',
                  '已完成的 run 不重跑，只补跑判无效与未跑的 run。插件内容指纹与首跑不同时不能续跑，要重新对照。']
    return '\n'.join(lines) + '\n' if lines else ''


# ---------- 续跑 ----------

def missing_runs(agg, cases, runs_per_case):
    """{用例: 还缺几个有效 run}。agg 为 None 时每个用例都缺 runs_per_case 个。"""
    have = {}
    for c in (agg or {}).get('cases', []):
        have[scoring._case_rel_dir(c)] = sum(1 for r in c.get('arms', {}).get('with', []) if not r.get('error'))
    return {c: runs_per_case - have.get(c, 0) for c in cases if runs_per_case - have.get(c, 0) > 0}


def merge_aggregates(prev, news, cases, attempt_no):
    """首跑汇总只留有效 run，再接上续跑新跑的 run（标 devkitResumeAttempt）。都没有时返回 None。"""
    if prev is None and not news:
        return None
    base = copy.deepcopy(prev if prev is not None else news[0])
    by_key = {}
    if prev is not None:
        for c in base.get('cases', []):
            c.setdefault('arms', {})['with'] = [r for r in c['arms'].get('with', []) if not r.get('error')]
            by_key[scoring._case_rel_dir(c)] = c
        new_list = news
    else:
        new_list = news[1:]
        for c in base.get('cases', []):
            for r in c.get('arms', {}).get('with', []):
                r['devkitResumeAttempt'] = attempt_no
            by_key[scoring._case_rel_dir(c)] = c
    for new in new_list:
        for c in copy.deepcopy(new.get('cases', [])):
            fresh = c.get('arms', {}).get('with', [])
            for r in fresh:
                r['devkitResumeAttempt'] = attempt_no
            key = scoring._case_rel_dir(c)
            if key in by_key:
                by_key[key].setdefault('arms', {})['with'] = by_key[key]['arms'].get('with', []) + fresh
            else:
                by_key[key] = c
    ordered = [by_key[c] for c in cases if c in by_key] + [v for k, v in by_key.items() if k not in cases]
    for c in ordered:
        c['runsPerCase'] = len(c.get('arms', {}).get('with', []))
    base['cases'] = ordered
    costs = [a.get('costUsd') for a in ([prev] if prev is not None else []) + list(news) if a.get('costUsd') is not None]
    base['costUsd'] = sum(costs) if costs else None
    base['partial'] = any(n.get('partial') for n in news) if news else bool(base.get('partial'))
    base.setdefault('aggregates', {})['casesTotal'] = len(ordered)
    base['devkitMerged'] = {'attempt': attempt_no,
                            'note': 'devkit-plugin-eval 续跑合并：只留首跑有效 run 与续跑新跑的 run；'
                                    'aggregates 除 casesTotal 外是首跑原值，判分以 devkit-plugin-eval 重算为准'}
    return base


def _add_usage(usages):
    keys = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'cost_usd')
    total = {k: 0 for k in keys}
    by_model = {}
    for u in usages:
        for k in keys:
            total[k] += (u or {}).get(k) or 0
        for model, vals in ((u or {}).get('by_model') or {}).items():
            acc = by_model.setdefault(model, {k: 0 for k in keys})
            for k in keys:
                acc[k] += vals.get(k) or 0
    total['by_model'] = by_model
    return total


def _subset_evals(evals_src, subset, dest):
    """拷一份 evals/，只留 subset 里的用例目录；evals/ 根下的共用文件（mocks/ 等）照留。"""
    evals_src = Path(evals_src)

    def ignore_results(dirpath, names):
        return ['results'] if Path(dirpath) == evals_src and 'results' in names else []
    arms.copy_tree(evals_src, dest, ignore=ignore_results)
    for c in arms.discover_cases(dest):
        if c not in subset:
            shutil.rmtree(dest / c)
    return dest


def _resume_arm(spec, *, old_rec, run_dir, cases, runs, base_ctx, tmp_root, attempt, attempt_no):
    agg_path = Path(run_dir) / 'arms' / spec.key / 'aggregate-result.json'
    prev_agg = json.loads(agg_path.read_text(encoding='utf-8')) if old_rec and agg_path.is_file() else None
    # 0.1.0 的老运行汇总没记转录目录：按票 03 的命名 traces/<run_id>/<臂>/<用例>-<序号> 补上（序号取剔除无效 run 之前的位置）
    for c in (prev_agg or {}).get('cases', []):
        for i, r in enumerate(c.get('arms', {}).get('with', []), 1):
            r.setdefault(compare.TRACE_DIR_KEY, 'traces/%s/%s/%s-%d' % (base_ctx['run_id'], spec.key,
                                                                          compare._case_slug(c), i))
    need = missing_runs(prev_agg, cases, runs)
    if prev_agg is not None and not need:
        rec = _public(old_rec)
        rec['load_issues'] = scoring.check_loaded_cases(prev_agg, cases, '')
        rec['_agg'] = prev_agg
        return rec

    for c in (prev_agg or {}).get('cases', []):
        for r in c.get('arms', {}).get('with', []):
            if r.get('error'):
                attempt['replaced_invalid_runs'].append({
                    'arm': spec.key, 'case': scoring._case_rel_dir(c),
                    'error_kind': completeness.classify_run_error(r['error']), 'error': str(r['error'])[:500]})
    attempt['reran'][spec.key] = dict(need)

    groups = {}
    for c in cases:
        if c in need:
            groups.setdefault(need[c], []).append(c)
    new_recs, stderr_texts = [], []
    for n in sorted(groups):
        tag = 'resume-%d' % attempt_no if len(groups) == 1 else 'resume-%d-r%d' % (attempt_no, n)
        work = tmp_root / spec.key / tag
        (work / 'asm').mkdir(parents=True)
        ctx = dict(base_ctx, assembly_root=work / 'asm', evals_src=_subset_evals(base_ctx['evals_src'], groups[n],
                                                                                   work / 'evals'),
                   traces_root=base_ctx['traces_root'] / tag, run_dir=work / 'stage',
                   run_id='%s/%s' % (base_ctx['run_id'], tag), runs=n, cases=groups[n])
        base_ctx['log']('[%s] 续跑：%s 个用例各补 %d 次' % (spec.label, len(groups[n]), n))
        new_recs.append(compare._run_arm(spec, ctx=ctx))
        stderr_file = ctx['traces_root'] / spec.key / 'eval.stderr'
        if stderr_file.is_file():
            stderr_texts.append(stderr_file.read_text(encoding='utf-8', errors='replace'))

    new_aggs = [r.pop('_agg') for r in new_recs if '_agg' in r]
    no_agg_issues = [i for r in new_recs if r.get('aggregate_result') is None for i in r['load_issues']]
    merged = merge_aggregates(prev_agg, new_aggs, cases, attempt_no)

    if old_rec:
        rec = _public(old_rec)
        prev_usage, prev_cost, prev_warn = rec.get('usage'), rec.get('cost_usd'), list(rec.get('cleanup_warnings') or [])
    else:
        rec = _public(new_recs[0])
        prev_usage, prev_cost, prev_warn = None, None, []
    codes = [r['eval_exit_code'] for r in new_recs]
    bad = [c for c in codes if c not in compare.EVAL_OK_EXIT_CODES]
    rec['eval_exit_code'] = bad[0] if bad else codes[-1]
    rec['cleanup_warnings'] = prev_warn + [w for r in new_recs for w in r['cleanup_warnings']]
    rec['usage'] = _add_usage([prev_usage] + [r['usage'] for r in new_recs])
    costs = [c for c in [prev_cost] + [r.get('cost_usd') for r in new_recs] if c is not None]
    rec['cost_usd'] = sum(costs) if costs else None
    rec['resume_trace_dirs'] = list(rec.get('resume_trace_dirs') or []) + [r['trace_dir'] for r in new_recs]
    for field, what in (('claude_version', 'Claude Code 版本'), ('main_model', '主力模型')):
        new_vals = {r.get(field) for r in new_recs if r.get(field)}
        if not rec.get(field) and new_vals:
            rec[field] = sorted(new_vals)[0]
        diff = sorted(new_vals - {rec.get(field)})
        if diff:
            attempt['warnings'].append('%s臂续跑时%s与首跑不同：%s → %s' % (spec.label, what, rec[field], '、'.join(diff)))
    # 拍板 07-1：单值字段保留首跑值，另记首跑与各次续跑出现过的全部值（按出现先后）。
    # Claude Code 版本不同照常合并；主力模型不同由 finalize_run 判不完整，再续跑也合不成完整
    for field, many in (('claude_version', 'claude_versions'), ('main_model', 'main_models')):
        seen = list(rec.get(many) or ([rec[field]] if rec.get(field) else []))
        for v in (r.get(field) for r in new_recs):
            if v and v not in seen:
                seen.append(v)
        rec[many] = seen

    if merged is None:
        rec.update(score=None, cases={}, invalid_run_count=0, aggregate_result=None, load_issues=no_agg_issues)
        return rec
    agg_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(agg_path, merged)
    rec['aggregate_result'] = 'arms/%s/aggregate-result.json' % spec.key
    rec['load_issues'] = scoring.check_loaded_cases(merged, cases, '\n'.join(stderr_texts)) + no_agg_issues
    rec['_agg'] = merged
    return rec


def _evals_changed(old, new, cases):
    """首跑记的用例目录指纹与现在比：返回变了的部分（共用件、各用例），首跑没记则为空。新增的用例不算。"""
    if not isinstance(old, dict):
        return []
    out = ['evals/ 下的共用文件'] if old.get('shared') != new['shared'] else []
    return out + ['用例 %s' % c for c in cases
                  if (old.get('cases') or {}).get(c) and old['cases'][c] != new['cases'].get(c)]


def resume_run(data_dir, run_dir, *, claude=None, runner=evalrun.run_eval, env=None, tmp_parent=None,
               sandbox_roots=None, keep_assembly=False, log=None, now=None, preflight_check=None,
               judge_runner=None, clause_ai=None):
    log = log or (lambda msg: print(msg, file=sys.stderr))
    now = now or (lambda: datetime.now(timezone.utc))
    data_dir, run_dir = Path(data_dir), Path(run_dir)
    rec_path = run_dir / 'run.json'
    if not rec_path.is_file():
        raise ResumeError('%s 下没有 run.json，不是对照运行目录' % run_dir)
    try:
        old = json.loads(rec_path.read_text(encoding='utf-8'))
    except ValueError as e:
        raise ResumeError('%s 不是合法 JSON（%s），无法续跑；请重新对照' % (rec_path, e))
    if not isinstance(old, dict) or old.get('kind') != 'compare':
        raise ResumeError('只能续跑离线对照（kind=compare），%s 是 %r'
                          % (rec_path, old.get('kind') if isinstance(old, dict) else type(old).__name__))
    if old.get('complete') is True:
        log('运行已完整，无需续跑：%s' % run_dir)
        return compare.CompareResult(run_dir, old, 0)
    p = old.get('plugin') if isinstance(old.get('plugin'), dict) else {}
    missing = [k for k in ('plugin.name', 'plugin.version', 'plugin.fingerprint', 'run_id', 'started_at')
               if not (p.get(k.split('.')[1]) if k.startswith('plugin.') else old.get(k))]
    if missing:
        raise ResumeError('%s 缺少续跑必需的字段：%s；请重新对照' % (rec_path, '、'.join(missing)))

    name = p['name']
    entry = registry.lookup(data_dir, name)          # 未登记即抛 NotRegistered：续跑同样要信任声明
    repo = Path(entry['repo'])
    plugin_dir = registry.plugin_dir(entry)
    manifest_path = plugin_dir / '.claude-plugin' / 'plugin.json'
    if not manifest_path.is_file():
        raise ResumeError('登记的插件目录里没有 .claude-plugin/plugin.json：%s' % plugin_dir)
    raw_version = json.loads(manifest_path.read_text(encoding='utf-8')).get('version')
    version = raw_version or 'noversion'
    if version != p['version']:
        raise ResumeError('插件版本已从 %s 变为 %s，不能续跑；请重新对照' % (p['version'], version))
    extra_exclude = ('.git', 'plugin-evals') if entry['plugin_path'] == '.' else ()
    plugin_fp = fingerprint.plugin_fingerprint(plugin_dir, extra_exclude)
    if plugin_fp != p['fingerprint']:
        raise ResumeError('插件内容指纹与首跑不同（%s → %s）：插件改过，续跑会混入两份内容的结果；请重新对照'
                          % (p['fingerprint'], plugin_fp))

    environment = old.get('environment') or {}
    runs = environment.get('runs_per_case')
    if not isinstance(runs, int) or runs < 1:
        raise ResumeError('run.json 的 environment.runs_per_case 缺失或非法：%r' % runs)
    concurrency = environment.get('concurrency') or 1
    model = environment.get('model_override')
    judge_opts = judge_opts_from(environment, repo / 'plugin-evals' / name, runner=judge_runner)
    clause_model = environment.get('clause_model')
    threshold = old.get('threshold', 1.0)
    cases = list(old.get('cases') or [])
    evals_src = plugin_dir / 'evals'
    gone = sorted(set(cases) - set(arms.discover_cases(evals_src)))
    if gone:
        raise ResumeError('首跑的用例已不在 %s 下：%s；请重新对照' % (evals_src, ', '.join(gone)))
    evals_fp = fingerprint.evals_fingerprint(evals_src, arms.discover_cases(evals_src))
    changed = _evals_changed(p.get('evals_fingerprint'), evals_fp, cases)
    if changed:
        raise ResumeError('首跑之后改过用例或 grader（%s）：补跑的 run 会按新判据、首跑的按旧判据，合在一起静默错分；'
                          '请重新对照' % '、'.join(changed))
    evals_fp = {'shared': evals_fp['shared'], 'cases': {c: evals_fp['cases'][c] for c in cases}}

    try:
        plan = armplan.rebuild_plan(old, plugin_dir=plugin_dir, name=name, version=raw_version, cases=cases,
                                    evals_src=evals_src, tmp_parent=tmp_parent, extra_exclude=extra_exclude,
                                    env=env, log=log)
    except armplan.ArmSourceError as e:
        raise ResumeError(str(e))
    try:
        # 前置检查硬项（票 04）：拿锁、写任何东西之前重跑一遍，环境可能在首跑之后变了
        pre = (preflight_check or preflight.check_compare)(
            data_dir=data_dir, name=name, env=evalrun.child_env(env), claude=claude, model=model,
            others=plan.preflight_targets(), env_plugins=plan.env_plugins, tmp_parent=tmp_parent)
        if not pre.passed:
            raise preflight.PreflightFailed(pre)
        claude = claude or pre.claude or evalrun.resolve_claude()
        child_env = evalrun.child_env(env)
        run_id = old['run_id']
        started = datetime.strptime(old['started_at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        head_sha, dirty = compare.git_state(repo, entry['plugin_path'])
        pre.dirty = dirty
        pre.add(preflight.check_dirty(head_sha, dirty))
        prior = list((old.get('resume') or {}).get('attempts') or [])
        attempt_no = len(prior) + 1
        attempt = {'attempt': attempt_no, 'started_at': _iso(now()), 'finished_at': None,
                   'reran': {}, 'replaced_invalid_runs': [], 'warnings': []}
        if not p.get('evals_fingerprint'):
            attempt['warnings'].append('首跑没有记用例目录指纹（早于集成版的运行），无法核对首跑之后用例或 grader 是否改过')

        meta = dict(log=log, run_id=run_id, name=name, version=version, plugin_fp=plugin_fp, evals_fp=evals_fp,
                    extra_exclude=extra_exclude, entry=entry, cases=cases, threshold=threshold, started=started,
                    claude=claude, child_env=child_env, runs=runs, concurrency=concurrency, model=model,
                    run_dir=run_dir, data_dir=data_dir, plan=plan, pre=pre, judge_opts=judge_opts,
                    clause_model=clause_model)
        old_arms = {k: v for k, v in (old.get('arms') or {}).items() if v}
        old_pending = old.get('pending')
        lock = RunLock(data_dir, run_id).acquire()
        try:
            if not (Path(run_dir) / compare.clauses.CHECK_FILE).is_file():
                # 首跑在条款检查之前就退出了：续跑补做，沿用首跑的 --clause-model
                compare.clauses.check_for_run(repo=repo, name=name, plugin_dir=plugin_dir, run_dir=run_dir,
                                              run_id=run_id, env=child_env, cases=cases, ai=clause_ai,
                                              model=clause_model, claude=claude, tmp_parent=tmp_parent,
                                              now=started, log=log)
            meta['statics'] = compare.static_profiles(plan.specs, child_env, tmp_parent)
            tmp_root = Path(tempfile.mkdtemp(prefix='devkit-plugin-eval-resume-', dir=tmp_parent))
            base_ctx = {
                'evals_src': evals_src, 'extra_exclude': extra_exclude, 'traces_root': data_dir / 'traces' / run_id,
                'run_id': run_id, 'claude': claude, 'concurrency': concurrency, 'model': model, 'runner': runner,
                'env': child_env, 'log': log, 'version': version, 'head_sha': head_sha, 'dirty': dirty,
                'sandbox_roots': sandbox_roots,
            }
            arm_records = {}
            try:
                for spec in plan.specs:
                    arm_records[spec.key] = _resume_arm(
                        spec, old_rec=old_arms.get(spec.key), run_dir=run_dir, cases=cases, runs=runs,
                        base_ctx=base_ctx, tmp_root=tmp_root, attempt=attempt, attempt_no=attempt_no)
                    progress = {k: v for k, v in old_arms.items() if k not in arm_records}
                    progress.update(arm_records)
                    # 续跑中途再崩时，检查点照样留着首跑的前置检查与待审页历史，下次续跑才接得上
                    ckpt = {'resume': {'attempts': prior + [attempt]},
                            'preflight': compare._merge_preflight(pre.to_dict(), old.get('preflight'))}
                    if old_pending:
                        ckpt['pending'] = _superseded_pending(old_pending, attempt_no)
                    write_checkpoint(meta, progress, extra=ckpt)
            finally:
                if not keep_assembly:
                    shutil.rmtree(tmp_root, ignore_errors=True)
            attempt['finished_at'] = _iso(now())

            def decorate(rec):
                rec['resume'] = {'attempts': prior + [attempt]}
                if old_pending:
                    rec['pending'] = _superseded_pending(old_pending, attempt_no)
                return rec
            res = compare.finalize_run(arm_records, [], decorate=decorate, prior_preflight=old.get('preflight'),
                                       **meta)
        finally:
            lock.release()
    finally:
        plan.cleanup()
    if old_pending:
        res = _regenerate_pending(data_dir, name, res, log)
    return res


def _superseded_pending(old_pending, attempt_no):
    """续跑改了结果，旧待审页作废（page_id 清空，旧回复码对不上）；已写回过的页留进 history。"""
    history = list(old_pending.get('history') or [])
    if old_pending.get('applied_at'):
        history.append({k: old_pending.get(k) for k in ('page_id', 'generated_at', 'applied_at', 'decisions')})
    return {'page_id': None, 'superseded_by_resume': attempt_no, 'history': history}


def _regenerate_pending(data_dir, name, res, log):
    """首跑生成过待审页的，续跑收尾重新生成一页（票 08）：pending 字段与 report.md「待审页抽样」一节随之更新。"""
    from . import pending   # 延迟导入：pending 依赖本模块
    try:
        page = pending.generate(data_dir, name, run_id=res.run_dir.name)
        log('续跑改了结果，旧待审页作废，已重新生成：%s' % page.html_path)
    except pending.PendingError as e:
        log('续跑后重新生成待审页没成功：%s；稍后手动运行 pending' % e)
        return res
    rec = json.loads((res.run_dir / 'run.json').read_text(encoding='utf-8'))
    return compare.CompareResult(res.run_dir, rec, res.exit_code)
