"""待审页上的两类 AI 评委项（票 09）：分歧样本、抽检。import 本模块即注册到 pending 的默认注册表。

优先级照票 08 集成口径：报告审阅、条款清单变更必上页；其余「分歧样本 > 抽检 > 用例草稿 > 复盘候选」，
本模块取 10、20（票 11 / 12 往后排）。
用户在页上给出自己的判法（通过 / 不通过 / 判不了），写回 judge.json 的样本 user 字段；通过、不通过两种
另存为金标样本 plugin-evals/<插件>/gold/<id>.json，下次对照先判它校准评委。判不了的不进金标。
页上不显示样本来自哪一臂：用户盲判，金标不受「装没装插件」的预期左右。
写回可重复执行（同一回复码重试时结果相同），接得住 pending 落盘中途失败后的重试。
"""
import hashlib

from . import judge, judgereport, pending

PAGE_TRANSCRIPT_LIMIT = 30000
OPTIONS = (('A', '通过：满足判定标准'), ('B', '不通过：不满足判定标准'), ('C', '判不了：样本无效或信息不足（不存金标）'))
_CODE = {'A': 'pass', 'B': 'fail', 'C': 'unclear'}


def _samples(subject):
    doc = subject.read_json(judge.JUDGE_FILE)
    return doc, (doc or {}).get('samples') or []


def _pass_text(p):
    if p.get('error'):
        return '出错：%s' % p['error'][:120]
    return '%s：%s' % (judge.VERDICT_LABEL.get(p.get('verdict'), '?'), p.get('reason') or '')


def _item(subject, doc, s, kind):
    case_info = (doc.get('cases') or {}).get(s['case']) or {}
    facts = [('用例', s['case']), ('第几次 run', s['run']), ('判定标准', s['criterion'])]
    facts += [('评委第 %d 遍' % (i + 1), _pass_text(p)) for i, p in enumerate(s.get('passes') or [])]
    if s.get('rule_grader'):
        facts.append(('规则 grader', '%s：%s' % (s['rule_grader'], {True: '通过', False: '不通过', None: '没跑到'}[
            s.get('rule_passed')])))
    if kind == 'disagreement':
        facts.append(('分歧原因', judge.DISAGREEMENT_LABEL.get(s.get('disagreement'), s.get('disagreement'))))
    lines = None
    if s.get('sample_file'):
        try:
            lines = judge.read_trace_lines(subject.path(s['sample_file']))
        except pending.PendingError:
            lines = None
    transcript = (judge.render_transcript(lines, PAGE_TRANSCRIPT_LIMIT) if lines is not None
                  else '（样本 trace 不在仓里：%s）' % s.get('sample_file'))
    body = '【判定标准】\n%s\n\n【用户请求】\n%s\n\n【会话转录】\n%s' % (
        (case_info.get('criteria') or {}).get(s['criterion'], '（未记录）'), case_info.get('prompt', '（未记录）'),
        transcript)
    title = '%s · 第 %d 次 · %s' % (s['case'], s['run'], s['criterion'])
    return pending.PendingItem(id='judge:%s' % s['id'], title=title, body=body, facts=tuple(facts),
                               payload={'sample_id': s['id']})


def _collect_disagreements(subject):
    doc, samples = _samples(subject)
    return [_item(subject, doc, s, 'disagreement') for s in samples
            if s.get('status') == 'disagreement' and not s.get('user')]


def _collect_spot_checks(subject):
    doc, samples = _samples(subject)
    return [_item(subject, doc, s, 'spot-check') for s in samples
            if s.get('spot_check') and s.get('status') == 'agreed' and not s.get('user')]


def gold_id(run_id, key):
    return 'g-' + hashlib.sha256(('%s/%s' % (run_id, key)).encode('utf-8')).hexdigest()[:12]


def _apply(subject, item, code, now, source):
    doc, samples = _samples(subject)
    sid = (item.get('payload') or {}).get('sample_id')
    s = next((x for x in samples if x.get('id') == sid), None)
    if doc is None or s is None:
        raise pending.PendingError('judge.json 里找不到样本 %s' % sid)
    verdict, ts = _CODE[code], pending._iso(now)
    s['user'] = {'verdict': verdict, 'decided_at': ts, 'via': 'pending'}
    s['final_verdict'] = judge.final_verdict(s)
    run_id = doc.get('run_id') or subject.rec.get('run_id')
    if verdict in ('pass', 'fail'):
        gid = gold_id(run_id, s['key'])
        case_info = (doc.get('cases') or {}).get(s['case']) or {}
        p = subject.rec.get('plugin') or {}
        subject.stage_json('../../%s/%s.json' % (judge.GOLD_DIR, gid), {
            'schema_version': 1, 'id': gid, 'active': True, 'created_at': ts, 'source': source,
            'plugin': p.get('name'), 'plugin_version': p.get('version'), 'run_id': run_id,
            'sample_key': s['key'], 'sample_id': s['id'], 'arm': s['arm'], 'case': s['case'], 'run': s['run'],
            'criterion': s['criterion'], 'criterion_fingerprint': s.get('criterion_fingerprint'),
            'criterion_text': (case_info.get('criteria') or {}).get(s['criterion']),
            'prompt': case_info.get('prompt'),
            'sample_file': 'runs/%s/%s' % (run_id, s['sample_file']) if s.get('sample_file') else None,
            'user_verdict': verdict, 'ai_verdicts': [x.get('verdict') for x in s.get('passes') or []],
            'disagreement': s.get('disagreement'), 'rule_grader': s.get('rule_grader'),
            'rule_passed': s.get('rule_passed'), 'judge_model': doc.get('model'),
        })
        s['gold_id'] = gid
    else:
        if s.get('gold_id'):
            subject.stage_delete('../../%s/%s.json' % (judge.GOLD_DIR, s['gold_id']))
        s['gold_id'] = None
    doc['scores'] = judge.compute_scores(samples)
    subject.stage_json(judge.JUDGE_FILE, doc)
    subject.rec['judge'] = judge.summarize(doc)
    report = subject.read_text('report.md')
    if report is not None:
        subject.stage_text('report.md', pending.upsert_section(
            report, judgereport.SECTION_HEADING, judgereport.section_body(subject.rec)))


DISAGREEMENT = pending.ItemType(
    key='judge-disagreement', label='分歧样本', options=OPTIONS, priority=10,
    collect=_collect_disagreements, apply=lambda sub, it, code, now: _apply(sub, it, code, now, 'disagreement'),
    hint='AI 评委两遍判法不同、两遍都判不了，或与规则 grader 相反。读判定标准与转录，给出你自己的判法；'
         '通过 / 不通过会存为金标样本，下次对照先拿它校准评委。')

SPOT_CHECK = pending.ItemType(
    key='judge-spot-check', label='抽检', options=OPTIONS, priority=20,
    collect=_collect_spot_checks, apply=lambda sub, it, code, now: _apply(sub, it, code, now, 'spot-check'),
    hint='评委两遍判法一致的样本里随机抽的，防评委稳定地判错。读判定标准与转录，给出你自己的判法；'
         '通过 / 不通过会存为金标样本。')

pending.register_type(DISAGREEMENT)
pending.register_type(SPOT_CHECK)
