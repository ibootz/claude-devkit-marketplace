"""会话复盘（`review`）：读本机会话 jsonl，覆盖全部已登记插件，结果写回各插件所在仓的
`plugin-evals/<插件>/reviews/<日期>.json`（零计数也写）。spec「2.5 会话复盘」。

原始 jsonl 不入库、不另存；抽取在 review_scan 里完成，结果只含计数、信号名与定位指针（会话 id、uuid、时间、版本），
不含对话原文。写盘前先对未脱敏的结果自检（assert_no_text：路径含 `~/`、长文本；check_pointers：指针字段白名单），
全部插件都过了再统一写盘（每个文件拿与待审页写回同一把锁，锁内重读同一天旧结果再合并、再自检），写前再过一遍 record.scrub_home。

同一天重跑覆盖当天文件，已勾选的复盘候选（按候选 id）与「建议跑对照」的已读标记带过去；旧待审页作废。
更早日期已裁定的同一候选 id 跨日期沿用（插件版本相同时），记下沿用自哪天的哪次裁定（carried_from）；
插件版本变了就重新上页；命中新的规则键时候选 id 本身就不同。
日期用本机本地日期命名 reviews/<日期>.json，结果里另记时区偏移 tz_offset；时刻字段仍是 UTC。
"""
import copy
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import evalrun, injection, preflight, record, registry, review_clauses, review_scan

SCHEMA_VERSION = 1
KIND = 'review'
REVIEW_ID_PREFIX = 'review-'
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
LONG_TEXT_LIMIT = 300       # 结果里任何字符串超过这个长度就当成混进了原文，拒绝写盘
_PATH_RE = re.compile(r'/(?:Users|home)/|[A-Za-z]:\\Users\\|~/')
_UUID_RE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
_TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_TS_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$')
_RULE_RE = re.compile(r'^(?:\?|[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)(?:#check=[A-Za-z0-9_.:-]{1,80})?$')
_VERSION_RE = re.compile(r'^[A-Za-z0-9_.+-]{1,40}$')
KIND_TEXT = {'block': '拦截', 'hook_error': 'hook 报错'}


class ReviewError(Exception):
    pass


def review_id(date):
    return REVIEW_ID_PREFIX + date


def reviews_dir(repo, name):
    return Path(repo) / 'plugin-evals' / name / 'reviews'


# ---------------- 插件索引 ----------------

def _read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def collect_renames(entries, cfg):
    """已登记插件所在仓的 marketplace.json 与本机已加的市场里的 renames，合成一张表。"""
    raw = {}
    paths = [Path(e['repo']) / '.claude-plugin' / 'marketplace.json' for e in entries.values()]
    mdir = cfg / 'plugins' / 'marketplaces'
    if mdir.is_dir():
        paths += sorted(mdir.glob('*/.claude-plugin/marketplace.json'))
    for p in paths:
        data = _read_json(p)
        ren = data.get('renames') if isinstance(data, dict) else None
        if isinstance(ren, dict):
            for old, new in ren.items():
                if isinstance(old, str) and (new is None or isinstance(new, str)):
                    raw.setdefault(old, new)
    return review_scan.resolve_renames(raw)


def read_installed(cfg, renames):
    """installed_plugins.json 读一次：{插件现名: [{id, version, scope, path}]}。不带 projectPath（含项目目录名）；
    path 只给本进程读 hooks.json 用，不写进结果。"""
    data = _read_json(cfg / 'plugins' / 'installed_plugins.json')
    out = {}
    for pid, recs in ((data or {}).get('plugins') or {}).items() if isinstance(data, dict) else []:
        name = pid.split('@', 1)[0]
        name = renames.get(name, name)
        for r in recs if isinstance(recs, list) else []:
            if isinstance(r, dict):
                out.setdefault(name, []).append({'id': pid, 'version': r.get('version'), 'scope': r.get('scope'),
                                                 'path': r.get('installPath')})
    return out


def build_index(entries, cfg, *, env, hook_labels=True, log=None):
    renames = collect_renames(entries, cfg)
    installed = read_installed(cfg, renames)
    specs, labels, notes = [], {}, []
    for name, entry in sorted(entries.items()):
        pdir = registry.plugin_dir(dict(entry, name=name))
        errs = []
        specs += [(name, s) for s in injection.load_hook_specs(pdir, errors=errs)]
        notes += ['%s：%s' % (name, e) for e in errs]
        if hook_labels:
            try:
                prof = injection.static_profile(pdir, env=env)
                labels[name] = {h['label'] for h in prof['hooks'] if h.get('label')}
            except Exception as e:  # noqa: BLE001 —— 取不到标签只少一种归因手段，不中止复盘
                notes.append('%s：静态执行常驻 hook 取内容标签失败 %s' % (name, type(e).__name__))
    for name, recs in installed.items():
        seen = set()
        for r in recs:
            path = r.get('path')
            if not path or path in seen or not Path(path).is_dir():
                continue
            seen.add(path)
            specs += [(name, s) for s in injection.load_hook_specs(path, errors=[])]
    idx = review_scan.PluginIndex(set(entries), renames=renames, specs=specs, labels=labels)
    return idx, installed, notes


# ---------------- 汇总 ----------------

def _summarize_events(events):
    by_rule = {}
    for kind, rule, sub, seg, ptr in events:
        s = by_rule.setdefault(rule, {'total': 0, 'main': 0, 'subagent': 0, 'before_compact': 0, 'after_compact': 0,
                                      'plugin_versions': Counter(), 'via': Counter()})
        s['total'] += 1
        s['subagent' if sub else 'main'] += 1
        s['after_compact' if seg >= 1 else 'before_compact'] += 1
        if ptr.get('plugin_version'):
            s['plugin_versions'][ptr['plugin_version']] += 1
        if ptr.get('via'):
            s['via'][ptr['via']] += 1
    for s in by_rule.values():
        s['plugin_versions'] = dict(s['plugin_versions'])
        s['via'] = dict(s['via'])
    return dict(sorted(by_rule.items()))


def candidate_id(plugin, kind, rule, after):
    h = hashlib.sha1(('%s|%s|%s|%d' % (plugin, kind, rule, int(after))).encode('utf-8')).hexdigest()[:12]
    return 'c-' + h


def script_events(index, name):
    """被测插件 hooks.json：{脚本相对路径: {事件}}，复盘候选按它推条款。"""
    out = {}
    for p, spec in index.specs:
        if p == name:
            out.setdefault(review_scan.Scanner._script(spec.command), set()).add(spec.event)
    return out


def build_candidates(plugin, events, clauses, *, script_events=None, has_list=True):
    """复盘候选：同一插件、同一信号种类、同一规则、同在 compact 前或后的若干次命中并成一个候选，
    只存次数与最近 EXAMPLES_PER_GROUP 次的定位指针（会话 id、子代理 id、uuid、时间、插件版本、Claude Code 版本）。"""
    groups = {}
    for kind, rule, sub, seg, ptr in events:
        key = (kind, rule, seg >= 1)
        g = groups.setdefault(key, {'count': 0, 'subagent': 0, 'versions': Counter(), 'pointers': []})
        g['count'] += 1
        g['subagent'] += 1 if sub else 0
        if ptr.get('plugin_version'):
            g['versions'][ptr['plugin_version']] += 1
        g['pointers'].append(ptr)
    out = []
    for (kind, rule, after), g in sorted(groups.items(), key=lambda kv: (-kv[1]['count'], kv[0])):
        ptrs = sorted(g['pointers'], key=lambda p: p.get('timestamp') or '', reverse=True)[:review_scan.EXAMPLES_PER_GROUP]
        ids, mapping = review_clauses.match(clauses, rule, script_events or {}, has_list=has_list)
        out.append({
            'id': candidate_id(plugin, kind, rule, after), 'kind': kind, 'rule': rule, 'count': g['count'],
            'subagent_count': g['subagent'], 'after_compact': after,
            'clause_ids': ids, 'clause_mapping': mapping,
            'plugin_versions': dict(g['versions']),
            'pointers': [{k: p.get(k) for k in ('session_id', 'agent_id', 'uuid', 'timestamp', 'plugin_version',
                                                 'claude_code_version')} for p in ptrs],
            'selection': None, 'decided_at': None, 'carried_from': None,
        })
    return out


def compare_hint(prev, env):
    """与上次离线对照的 Claude Code 版本、主力模型比；任一个变了就建议跑对照。"""
    if not prev:
        return {'suggest': False, 'previous_run': None, 'diffs': [], 'unknown': [],
                'reason': '没有离线对照记录，无从比较'}
    fields = (('Claude Code 版本', prev.get('claude_code_version'), env.get('claude_code_version')),
              ('主力模型', prev.get('main_model'), env.get('main_model')))
    diffs = [{'field': n, 'previous': old, 'current': new} for n, old, new in fields if old and new and old != new]
    unknown = ['%s（%s）' % (n, '上次对照没记' if not old else '会话里取不到') for n, old, new in fields if not (old and new)]
    return {'suggest': bool(diffs), 'previous_run': prev.get('run_id'), 'diffs': diffs, 'unknown': unknown,
            'acknowledged_at': None}


def _latency(lat):
    return {k: {'count': len(v), 'p50_ms': review_scan.percentile(v, 0.5), 'p95_ms': review_scan.percentile(v, 0.95),
                'max_ms': max(v)} for k, v in sorted(lat.items()) if v}


def local_date(now, tz=None):
    """(本机本地日期, 时区偏移 '+08:00')。tz 只给单测固定时区用。"""
    loc = now.astimezone(tz) if tz else now.astimezone()
    off = loc.strftime('%z')
    return loc.strftime('%Y-%m-%d'), '%s:%s' % (off[:3], off[3:]) if off else '+00:00'


def build_record(*, name, entry, ps, scan, index, installed, clauses, clause_note, prev, now, days, since,
                 date=None, tz_offset='+00:00', has_list=True):
    date = date or now.strftime('%Y-%m-%d')
    manifest = _read_json(registry.plugin_dir(dict(entry, name=name)) / '.claude-plugin' / 'plugin.json') or {}
    events = ps['blocks'] + ps['hook_errors']
    has_ss = any(s.event == 'SessionStart' for p, s in index.specs if p == name)
    # 同会话加载的插件只具名登记过的（与本插件同在评测登记表里、名字可公开）；
    # 其余（第三方、公司内部、项目级 skill 目录）只给个数，名字不落盘。
    co = {p: len(s) for p, s in ps['co_loaded'].items() if p != name and p in index.registered}
    co_other = len([p for p in ps['co_loaded'] if p != name and p not in index.registered])
    inst = {r['id']: r['version'] for recs in installed.values() for r in recs}
    return {
        'schema_version': SCHEMA_VERSION, 'kind': KIND, 'run_id': review_id(date), 'date': date,
        'date_basis': 'local', 'tz_offset': tz_offset,
        'generated_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'plugin': {'name': name, 'version': manifest.get('version'),
                   'installed': [{'id': r['id'], 'version': r['version'], 'scope': r['scope']}
                                 for r in installed.get(name, [])]},
        'window': {'days': days, 'since': since.strftime('%Y-%m-%dT%H:%M:%SZ'),
                   'until': now.strftime('%Y-%m-%dT%H:%M:%SZ')},
        'scan': scan.stats,
        'environment': dict(scan.environment, main_model=(scan.main_models or {}).get(name), co_loaded_plugins=[
            {'name': p, 'sessions': n, 'installed_versions': sorted({v for i, v in inst.items()
                                                                     if i.split('@', 1)[0] == p and v})}
            for p, n in sorted(co.items(), key=lambda kv: (-kv[1], kv[0]))],
            co_loaded_unregistered_count=co_other),
        'signals': {
            'sessions_listed': len(ps['sessions_listed']), 'sessions_with_signal': len(ps['sessions_signal']),
            'skills': {k: dict(v) for k, v in sorted(ps['skills'].items())},
            'blocks': _summarize_events(ps['blocks']),
            'hook_errors': _summarize_events(ps['hook_errors']),
            'permission_decisions': dict(ps['decisions']),
            'injections': dict(sorted(ps['injections'].items())),
            'hook_latency': _latency(ps['latency']),
            'compact': {'has_session_start_hook': has_ss, 'boundaries_seen': ps['compact']['boundaries_seen'],
                        'reinjected_after': ps['compact']['reinjected']},
        },
        'candidates': build_candidates(name, events, clauses, script_events=script_events(index, name),
                                       has_list=has_list),
        'clause_list_note': clause_note,
        'compare_hint': compare_hint(prev, dict(scan.environment, main_model=(scan.main_models or {}).get(name))),
        'pending': None,
    }


def carry_earlier(rec, earlier):
    """跨日期沿用：earlier = [(日期, 记录)]（新到旧，都早于本次）。同一候选 id 在更早日期已裁定、且那次复盘时的
    插件版本与本次相同，就沿用裁定并记下来源（哪天、哪次裁定）；版本变了不沿用，重新上页。"""
    version = (rec.get('plugin') or {}).get('version')
    for c in rec['candidates']:
        if c.get('selection'):
            continue
        for d, old in earlier:
            if not isinstance(old, dict):
                continue
            hit = next((o for o in old.get('candidates') or [] if isinstance(o, dict) and o.get('id') == c['id']
                        and o.get('selection')), None)
            if hit is None:
                continue
            if (old.get('plugin') or {}).get('version') == version:
                src = hit.get('carried_from') or {'date': d, 'run_id': review_id(d), 'decided_at': hit.get('decided_at'),
                                                   'plugin_version': version}
                c['selection'], c['decided_at'], c['carried_from'] = hit['selection'], hit.get('decided_at'), src
                # 已改写成草稿、或 AI 判为写不成的（都是终态）不再调 AI；作废的不沿用，重判不花钱（审查 13 S4）
                if (hit.get('conversion') or {}).get('status') in ('drafted', 'skipped'):
                    c['conversion'] = hit['conversion']
            break           # 只看最近一次出现过裁定的日期：那次版本不同就不再往前找
    return rec


def merge_previous(rec, old):
    """同一天重跑：带过已勾选的候选与「建议跑对照」的已读标记；旧待审页作废（page_id 置空，进 history）。"""
    if not isinstance(old, dict):
        return rec
    done = {c.get('id'): c for c in old.get('candidates') or [] if isinstance(c, dict) and c.get('selection')}
    for c in rec['candidates']:
        if c['id'] in done:
            c['selection'], c['decided_at'] = done[c['id']]['selection'], done[c['id']].get('decided_at')
            c['carried_from'] = done[c['id']].get('carried_from')
            if done[c['id']].get('conversion'):         # 票 13 转草稿的结果（drafted / void / …）同一天重跑照带
                c['conversion'] = done[c['id']]['conversion']
    oh, nh = old.get('compare_hint') or {}, rec['compare_hint']
    if oh.get('acknowledged_at') and oh.get('diffs') == nh.get('diffs'):
        nh['acknowledged_at'] = oh['acknowledged_at']
    op = old.get('pending')
    if isinstance(op, dict):
        history = list(op.get('history') or [])
        if op.get('page_id'):
            history.append({k: op.get(k) for k in ('page_id', 'generated_at', 'applied_at', 'decisions')})
        rec['pending'] = {'page_id': None, 'superseded_by_rerun': rec['generated_at'], 'history': history}
    return rec


def assert_no_text(obj, path='$'):
    """兜底：结果里不许有绝对路径、家目录与长文本（像是混进了对话原文）。返回违规位置列表。"""
    bad = []
    home = os.path.expanduser('~')
    if isinstance(obj, dict):
        for k, v in obj.items():
            bad += assert_no_text(k, '%s.<key>' % path) + assert_no_text(v, '%s.%s' % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad += assert_no_text(v, '%s[%d]' % (path, i))
    elif isinstance(obj, str):
        if len(obj) > LONG_TEXT_LIMIT or '\n' in obj or (home and home != '~' and home in obj) or _PATH_RE.search(obj):
            bad.append(path)
    return bad


def check_pointers(rec):
    """指针字段白名单：会话 id 是 uuid、uuid / 子代理 id 是短标识、时间戳合 ISO 形态、规则键是脚本相对路径或 `?`、
    版本号是短版本串。返回违规位置列表。"""
    bad = []

    def chk(value, rx, where, nullable=True):
        if value is None and nullable:
            return
        if not isinstance(value, str) or not rx.match(value):
            bad.append(where)

    for kind in ('blocks', 'hook_errors'):
        for rule in ((rec.get('signals') or {}).get(kind) or {}):
            chk(rule, _RULE_RE, '$.signals.%s.<key>' % kind, nullable=False)
    for i, c in enumerate(rec.get('candidates') or []):
        chk(c.get('rule'), _RULE_RE, '$.candidates[%d].rule' % i, nullable=False)
        for j, ptr in enumerate(c.get('pointers') or []):
            at = '$.candidates[%d].pointers[%d]' % (i, j)
            chk(ptr.get('session_id'), _UUID_RE, at + '.session_id', nullable=False)
            chk(ptr.get('agent_id'), _TOKEN_RE, at + '.agent_id')
            chk(ptr.get('uuid'), _TOKEN_RE, at + '.uuid')
            chk(ptr.get('timestamp'), _TS_RE, at + '.timestamp')
            for k in ('plugin_version', 'claude_code_version'):
                chk(ptr.get(k), _VERSION_RE, '%s.%s' % (at, k))
    return bad


def _merged(rec, path, date):
    """带上同一天旧结果里的裁定与更早日期可沿用的裁定（读的是盘上当前内容）。"""
    return carry_earlier(merge_previous(rec, _read_json(path) if path.is_file() else None),
                         _earlier(path.parent, date))


def _self_check(name, rec):
    """自检必须在 scrub_home 之前：脱敏会把家目录换成 ~，家目录不在 /Users、/home 下时再查就漏了。"""
    bad = assert_no_text(rec) + check_pointers(rec)
    if bad:
        raise ReviewError('%s 的复盘结果里有疑似原文、路径或不合形态的指针（%s），整批拒绝写盘'
                          % (name, '、'.join(bad[:5])))
    return rec


def _write(path, rec):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


# ---------------- 入口 ----------------

def _earlier(d, date):
    """reviews/ 下早于 date 的结果：[(日期, 记录)]，新到旧。"""
    if not d.is_dir():
        return []
    dates = sorted((p.stem for p in d.glob('*.json') if DATE_RE.match(p.stem) and p.stem < date), reverse=True)
    return [(x, _read_json(d / ('%s.json' % x))) for x in dates]


def run_review(data_dir, *, days=None, now=None, env=None, cfg=None, hook_labels=True, check=True, log=None,
               tz=None):
    """返回 [(插件名, 结果文件路径, 记录)]。前置检查硬项失败抛 preflight.PreflightFailed。
    先给全部插件建好结果并自检，任一不过即整批不写；都过了再逐个拿锁写盘。tz 只给单测固定时区用。"""
    from . import pending        # 延迟导入：pending → resume → compare，导入期会与本模块成环
    log = log or (lambda m: print(m, file=sys.stderr))
    env = dict(os.environ if env is None else env)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cfg = Path(cfg) if cfg else preflight.config_dir(env)
    if check:
        rep = preflight.check_review(data_dir=data_dir, env=dict(env, CLAUDE_CONFIG_DIR=str(cfg)), now=now)
        if not rep.passed:
            raise preflight.PreflightFailed(rep)
        for item in rep.warnings:
            log('注意：%s：%s' % (item.label, item.detail))
    entries = registry.load(data_dir)['plugins']
    if not entries:
        raise ReviewError('登记清单为空：先用 register 登记被测插件')
    if days is None:
        days, _ = preflight._cleanup_period_days(cfg)
    since = now - timedelta(days=days)

    index, installed, notes = build_index(entries, cfg, env=evalrun.child_env(env), hook_labels=hook_labels, log=log)
    for n in notes:
        log('注意：%s' % n)
    scanner = review_scan.Scanner(index, since.strftime('%Y-%m-%dT%H:%M:%S'))
    for path, sub in review_scan.iter_session_files(cfg / 'projects', since.timestamp()):
        scanner.scan_file(path, is_subagent=sub)
    scan = scanner.result()

    date, tz_offset = local_date(now, tz)
    built = []
    for name, entry in sorted(entries.items()):
        repo = Path(entry['repo'])
        evals = repo / 'plugin-evals' / name
        clauses, clause_note = review_clauses.load(evals)
        prev = preflight.previous_compare(evals / 'runs')
        rec = build_record(name=name, entry=entry, ps=scan.plugins[name], scan=scan, index=index, installed=installed,
                           clauses=clauses, clause_note=clause_note, prev=prev, now=now, days=days, since=since,
                           date=date, tz_offset=tz_offset, has_list=(evals / review_clauses.LIST_FILE).is_file())
        path = reviews_dir(repo, name) / ('%s.json' % date)
        _self_check(name, _merged(copy.deepcopy(rec), path, date))     # 先全部自检，一个不过整批不写
        built.append((name, path, rec))
    out = []
    for name, path, rec in built:
        with pending._locked(data_dir, 'review-%s-%s' % (name, date), err=ReviewError):   # 与待审页写回同一把锁
            # 旧结果在锁内重读再合并：自检到拿锁之间若有一次待审页写回，它的裁定不被覆盖
            rec = _self_check(name, _merged(rec, path, date))
            rec = record.scrub_home(rec)
            _write(path, rec)
        out.append((name, path, rec))
    return out


def add_parser(sub):
    r = sub.add_parser('review', help='会话复盘：读本机会话记录，给每个已登记插件写 plugin-evals/<插件>/reviews/<日期>.json')
    r.add_argument('--days', type=int, help='往回看几天；缺省取 settings 的 cleanupPeriodDays（未设为 30）')
    r.add_argument('--no-hook-labels', action='store_true',
                   help='不静态执行被测插件的常驻 hook 取内容标签（注入只按指纹与插件名归因）')
    return r


def main(args, data_dir):
    if args.days is not None and args.days < 1:
        print('错误：--days 至少为 1', file=sys.stderr)
        return 2
    try:
        results = run_review(data_dir, days=args.days, hook_labels=not args.no_hook_labels)
    except preflight.PreflightFailed as e:
        print(e.report.render(), file=sys.stderr)
        return 2
    except (ReviewError, registry.RegistryError) as e:
        print('错误：%s' % e, file=sys.stderr)
        return 2
    first = results[0][2] if results else {}
    sc = first.get('scan') or {}
    print('复盘窗口：%s 起 %s 天；主会话文件 %s、子代理文件 %s，计入记录 %s，按 uuid 去重跳过 %s'
          % ((first.get('window') or {}).get('since'), (first.get('window') or {}).get('days'), sc.get('main_files'),
             sc.get('subagent_files'), sc.get('records_counted'), sc.get('duplicate_records')))
    for name, path, rec in results:
        s = rec['signals']
        todo = [c for c in rec['candidates'] if not c.get('selection')]
        hint = rec['compare_hint']
        print('%s：拦截 %d、hook 报错 %d、注入 %d、skill 调用 %d；复盘候选 %d（未勾选 %d）%s'
              % (name, sum(v['total'] for v in s['blocks'].values()), sum(v['total'] for v in s['hook_errors'].values()),
                 s['injections'].get('total', 0),
                 sum(v.get('tool', 0) + v.get('slash', 0) for v in s['skills'].values()),
                 len(rec['candidates']), len(todo), '；建议跑对照' if hint.get('suggest') else ''))
        print('  结果：%s' % path)
        if todo or (hint.get('suggest') and not hint.get('acknowledged_at')):
            print("  待审页：python3 plugin_eval.py --data-dir '%s' pending %s --review %s" % (data_dir, name, rec['date']))
    return 0
