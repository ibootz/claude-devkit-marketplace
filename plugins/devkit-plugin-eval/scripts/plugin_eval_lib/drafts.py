"""用例草稿区与草稿待审（票 11，spec「2.3 用例从哪来」，设计票 17、11 第 4 条）。

一、草稿区：`<仓>/plugin-evals/<插件>/drafts/<用例>/`，在插件目录之外。eval 递归扫 `<插件>/evals/**`，草稿放进去
   会被当正式用例跑；compare / gate 只读 `<插件>/evals/`，草稿因此不参与任何运行。每个草稿是 eval 原生格式
   （casefiles.py），另带一份 draft.json（META_FILE）：来源、类别、挂的条款、意图、优先级证据、状态。

二、所有来源一律先进草稿区：AI 起草（drafter.py）、历史素材迁入（来源 history）、退役条款的用例退回（来源 rehang，
   本模块 sync_rehang 消费票 10 的 clause-rehang.json）、复盘候选改写（来源 review-candidate，票 13）。

三、待审：一批草稿 = 一次运行 `runs/<时间>-<版本>-drafts/`（run.json 的 kind=drafts），批次按优先级取前 PAGE_LIMIT
   个可审草稿，生成待审页。优先级（小者先）：1 已证明有差的条款、2 复盘已命中的条款、3 退役改挂、4 其余。
   勾选「通过」把草稿目录移到 `<插件>/evals/<用例>/`（不带 draft.json），「打回」留在草稿区、标 rejected、不再上页。
   条款已删除的退役用例单列一类：确认后删除。新用例进 evals/ 后还要跑 baseline（基线已满足判定，baseline.py）。

四、挂不上条款的草稿（纪律 / 文风类没有有效条款 id，如历史素材迁入时清单还没有、或退役条款有多个替代）不上页，
   由下一次 `drafts write` 先让 AI 挂上条款（drafter.link_orphans），或手改 tags。
"""
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import arms, casefiles, clauses, pending, record, registry

DRAFTS_DIR = 'drafts'
META_FILE = 'draft.json'
KIND = 'drafts'
SCHEMA_VERSION = 1
DRAFT_PRIORITY = 300          # 分歧样本 10 > 抽检 20 > 用例草稿 300 > 复盘候选 400（票 08 集成口径）
STATUS_OPEN = 'open'
STATUS_REJECTED = 'rejected'
SOURCES = ('ai', 'history', 'rehang', 'review-candidate', 'compact-replay')
# 类别 → 用例 tags 里的类别标记。纪律、文风、诱导三类要挂条款 id；skill / agent 类按 skill:<名> / agent:<名> 归属
CATEGORIES = ('discipline', 'style', 'style-scenario', 'induced', 'skill-trigger', 'skill-no-trigger',
              'agent-dispatch', 'agent-no-dispatch', 'agent-follow', 'compact-replay', 'review-replay')
# compact-replay（票 13 compact 回放）挂条款；review-replay（复盘候选改写）由改写 AI 判挂哪条，判不出不挂，也能上页
CLAUSE_CATEGORIES = ('discipline', 'style', 'style-scenario', 'induced', 'compact-replay')
TIER_PROVEN, TIER_REVIEW, TIER_REHANG, TIER_OTHER = 1, 2, 3, 4
TIER_TEXT = {TIER_PROVEN: '已证明有差的条款', TIER_REVIEW: '复盘已命中的条款', TIER_REHANG: '退役条款的用例退回改挂',
             TIER_OTHER: '其余'}
_CLAUSE_ID_RE = re.compile(r'^C(\d+)$')   # 同 clauses._ID_RE；导入期不读 clauses 的属性（循环导入）


class DraftError(Exception):
    pass


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def drafts_root(repo, name):
    return clauses.evals_root(repo, name) / DRAFTS_DIR


def clause_ids(tags):
    return [t for t in tags if _CLAUSE_ID_RE.match(t)]


# ---------------- 列草稿 ----------------

@dataclass
class Draft:
    case: str                     # drafts/ 下的相对目录
    path: Path
    meta: dict
    tags: list
    problems: list = field(default_factory=list)   # eval 加载不了的问题（check_case_dir）

    @property
    def status(self):
        return self.meta.get('status') or STATUS_OPEN

    @property
    def category(self):
        return self.meta.get('category')


def read_meta(case_dir):
    p = Path(case_dir) / META_FILE
    if not p.is_file():
        return {}
    try:
        m = json.loads(p.read_text(encoding='utf-8'))
    except ValueError:
        return {'_corrupt': True}
    return m if isinstance(m, dict) else {'_corrupt': True}


def write_meta(case_dir, meta):
    (Path(case_dir) / META_FILE).write_text(json.dumps(record.scrub_home(meta), ensure_ascii=False, indent=2) + '\n',
                                            encoding='utf-8')


def list_drafts(repo, name):
    root = drafts_root(repo, name)
    out = []
    for c in arms.discover_cases(root):
        d = root / c
        out.append(Draft(c, d, read_meta(d), clauses.case_tags(d), casefiles.check_case_dir(d)))
    return out


def prune_empty(repo, name):
    """写回待审页只删文件，移走的草稿会留下空目录：清掉。"""
    root = drafts_root(repo, name)
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in sorted(os.walk(root, topdown=False), key=lambda t: -len(t[0])):
        if Path(dirpath) != root and not os.listdir(dirpath):
            os.rmdir(dirpath)


def link_state(d, active):
    """纪律 / 文风 / 诱导类草稿是否挂上了有效条款：返回 (是否需要挂, 原因)。skill / agent 类不需要条款。"""
    if d.category not in CLAUSE_CATEGORIES:
        return False, None
    ids = clause_ids(d.tags)
    if not ids:
        return True, '还没挂条款 id'
    bad = [i for i in ids if i not in active]
    if bad:
        return True, '挂的 %s 不是有效条款（已退役或不在清单里）' % '、'.join(bad)
    return False, None


# ---------------- 退役条款的用例退回草稿区（消费票 10 的 clause-rehang.json） ----------------

def _rehang_target(s):
    """改挂目标：单一替代即它；多个替代时 AI 的改挂提示里恰好点名其中一个即它；删除返回 'delete'；其余 None（人工）。"""
    repl = s.get('replaced_by') or []
    if s.get('reason') == 'delete':
        return 'delete'
    if len(repl) == 1:
        return repl[0]
    named = [r for r in repl if re.search(r'(?<![A-Za-z0-9])%s(?![0-9])' % re.escape(r), s.get('ai_hint') or '')]
    return named[0] if len(named) == 1 else None


def _retag(case_dir, retired, target):
    tags = clauses.case_tags(case_dir)
    if target and target != 'delete':
        new = [target if t == retired else t for t in tags]
        casefiles.retarget_judge_clause(case_dir, retired, target)
    else:
        new = tags
    if new != tags:
        casefiles.set_tags(case_dir, new)
    return tags, new


def sync_rehang(repo, name, plugin_dir, *, now=None, log=None):
    """把 clause-rehang.json 里 status=open 的建议落实：evals/ 下的用例移进 drafts/，按建议改挂 tags 并附建议；
    本来就在 drafts/ 的草稿就地改挂、附建议。处理过的建议标 moved / annotated / missing，写回 clause-rehang.json。
    返回 [(用例, 结果)]。"""
    log = log or (lambda msg: print(msg, file=sys.stderr))
    now = now or datetime.now(timezone.utc)
    path = clauses.evals_root(repo, name) / clauses.REHANG_FILE
    if not path.is_file():
        return []
    doc = json.loads(path.read_text(encoding='utf-8'))
    evals = Path(plugin_dir) / 'evals'
    root = drafts_root(repo, name)
    done = []
    for s in doc.get('suggestions') or []:
        if not isinstance(s, dict) or s.get('status', 'open') != 'open':
            continue
        where, _, case = str(s.get('case') or '').partition('/')
        src = evals / case if where == 'evals' else root / case
        dst = root / case
        target = _rehang_target(s)
        if where == 'evals' and src.is_dir():
            if dst.exists():
                s.update(status='conflict', handled_at=_iso(now),
                         note='drafts/%s 已存在，未移动；处理掉那份草稿后把本条 status 改回 open 重试' % case)
                done.append((case, 'conflict'))
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            result = 'moved'
        elif dst.is_dir():
            result = 'annotated'
        else:
            s.update(status='missing', handled_at=_iso(now), note='用例目录已不在 evals/ 与 drafts/ 里')
            done.append((case, 'missing'))
            continue
        before, after = _retag(dst, s['retired_id'], target)
        meta = read_meta(dst) or {'schema_version': SCHEMA_VERSION, 'case': case, 'source': 'rehang',
                                  'created_at': _iso(now)}
        if result == 'moved':
            meta.update(source='rehang', status=STATUS_OPEN, category=meta.get('category') or 'discipline')
        meta['clauses'] = clause_ids(after)
        meta.setdefault('rehang', []).append({
            'retired_id': s['retired_id'], 'reason': s.get('reason'), 'replaced_by': s.get('replaced_by') or [],
            'suggestion': s.get('suggestion'), 'ai_hint': s.get('ai_hint') or '', 'from_run': s.get('from_run'),
            'action': 'delete' if target == 'delete' else ('retag' if target else 'manual'),
            'target': None if target == 'delete' else target, 'tags_before': before, 'tags_after': after,
            'returned_from': 'evals' if result == 'moved' else 'drafts', 'at': _iso(now)})
        write_meta(dst, meta)
        s.update(status=result, handled_at=_iso(now), draft='drafts/%s' % case)
        done.append((case, result))
        log('[草稿] 退役条款 %s 的用例 %s：%s（%s）' % (s['retired_id'], case,
                                              '已退回草稿区' if result == 'moved' else '草稿已附改挂建议',
                                              {'delete': '条款已删除，待确认后删除用例', None: '多个替代，需人工改挂'}
                                              .get(target, '已按建议改挂到 %s' % target)))
    if done:
        path.write_text(json.dumps(record.scrub_home(doc), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return done


def _is_delete(d):
    rh = d.meta.get('rehang') or []
    return bool(rh) and rh[-1].get('action') == 'delete'


# ---------------- 优先级 ----------------

def evidence(repo, name, plugin_dir):
    """(已证明有差的条款 id 集合, 复盘已命中的条款 id 集合)。
    有差：任一离线对照运行里，挂在该条款上的用例「当前版 − 不装」> 0（按当前 evals/ 的 tags 归属）。
    复盘命中：reviews/*.json 的候选里映射到的条款 id（票 12；多数候选未映射，见票 13 Comments）。"""
    root = clauses.evals_root(repo, name)
    cov = clauses.coverage(plugin_dir) if (Path(plugin_dir) / 'evals').is_dir() else {}
    case_clauses = {}
    for tag, cases in cov.items():
        if _CLAUSE_ID_RE.match(tag):
            for c in cases:
                case_clauses.setdefault(c, set()).add(tag)
    proven, hit = set(), set()
    runs = root / 'runs'
    for p in sorted(runs.glob('*/run.json')) if runs.is_dir() else []:
        try:
            rec = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or rec.get('kind') != 'compare':
            continue
        for c, dv in ((rec.get('delta') or {}).get('cases') or {}).items():
            if isinstance(dv, (int, float)) and dv > 0:
                proven |= case_clauses.get(c, set())
    rv = root / 'reviews'
    for p in sorted(rv.glob('*.json')) if rv.is_dir() else []:
        try:
            doc = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        for cand in (doc.get('candidates') or []) if isinstance(doc, dict) else []:
            if isinstance(cand, dict):
                hit |= set(cand.get('clause_ids') or [])
    return proven, hit


def priority(d, proven, hit):
    """(档位, 原因清单)。草稿自带的证据（draft.json evidence.proven_delta，如 probe 实测）也算已证明有差。"""
    ids = set(clause_ids(d.tags))
    ev = d.meta.get('evidence') or {}
    reasons = []
    if ids & proven:
        reasons.append('条款 %s 在离线对照里已证明有差' % '、'.join(sorted(ids & proven)))
    if ev.get('proven_delta') is not None:
        reasons.append('历史实测已证明有差：%s' % (ev.get('proven_note') or 'Δ=%+.2f' % ev['proven_delta']))
    if reasons:
        return TIER_PROVEN, reasons
    if ids & hit or d.meta.get('source') == 'review-candidate':
        return TIER_REVIEW, ['条款 %s 在会话复盘里命中过' % '、'.join(sorted(ids & hit))] if ids & hit \
            else ['来自会话复盘候选']
    if d.meta.get('rehang'):
        return TIER_REHANG, ['退役条款 %s 的用例退回改挂' % d.meta['rehang'][-1].get('retired_id')]
    return TIER_OTHER, []


def _clause_order(d):
    ids = clause_ids(d.tags)
    return min(clauses._id_no(i) for i in ids) if ids else 10 ** 9


# ---------------- 待审批次 ----------------

def _on_open_page(repo, name):
    """较早的草稿批次里、页还没写回的草稿：{用例: run_id}。新批次不再收它们，免得两页争同一份草稿。"""
    runs = clauses.evals_root(repo, name) / 'runs'
    out = {}
    for p in sorted(runs.glob('*-%s/run.json' % KIND)) if runs.is_dir() else []:
        try:
            rec = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        pend = rec.get('pending') or {}
        if pend.get('page_id') and not pend.get('applied_at'):
            for it in pend.get('items') or []:
                c = (it.get('payload') or {}).get('case')
                if c:
                    out[c] = rec.get('run_id')
    return out


def classify(repo, name, plugin_dir):
    """把草稿分成：可审（按优先级排好）、挂不上条款、加载不了、已打回、在别的页上。"""
    lst = clauses.load_list(repo, name)
    active = set(clauses.active_ids(lst))
    proven, hit = evidence(repo, name, plugin_dir)
    busy = _on_open_page(repo, name)
    out = {'ready': [], 'needs_link': [], 'broken': [], 'rejected': [], 'busy': []}
    for d in list_drafts(repo, name):
        if d.meta.get('_corrupt'):
            out['broken'].append((d, ['%s 不是合法 JSON' % META_FILE]))
        elif d.status == STATUS_REJECTED:
            out['rejected'].append((d, None))
        elif d.problems:
            out['broken'].append((d, d.problems))
        elif d.case in busy:
            out['busy'].append((d, busy[d.case]))
        elif not _is_delete(d) and link_state(d, active)[0]:
            out['needs_link'].append((d, link_state(d, active)[1]))
        else:
            tier, reasons = priority(d, proven, hit)
            out['ready'].append((d, tier, reasons))
    out['ready'].sort(key=lambda t: (t[1], _clause_order(t[0]), t[0].case))
    return out


def _plugin_version(plugin_dir):
    try:
        return json.loads((Path(plugin_dir) / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8')).get(
            'version') or 'noversion'
    except (OSError, ValueError):
        return 'noversion'


def create_batch(data_dir, name, *, now=None, drafting=None, limit=pending.PAGE_LIMIT, log=None):
    """取优先级最高的 ≤ limit 个可审草稿建一次 kind=drafts 的运行并生成待审页。没有可审草稿返回 (None, None, 分类)。
    drafting：本批由 AI 起草时的摘要（drafter 传入），一并记进 run.json。"""
    log = log or (lambda msg: print(msg, file=sys.stderr))
    now = (now or (lambda: datetime.now(timezone.utc)))()
    entry = registry.lookup(data_dir, name)
    repo, plugin_dir = Path(entry['repo']), registry.plugin_dir(entry)
    prune_empty(repo, name)
    cls = classify(repo, name, plugin_dir)
    ready = cls['ready']
    if not ready:
        return None, None, cls
    batch = ready[:limit]
    version = _plugin_version(plugin_dir)
    run_id = '%s-%s-%s' % (now.strftime('%Y%m%dT%H%M%SZ'), version, KIND)
    run_dir = clauses.evals_root(repo, name) / 'runs' / run_id
    if run_dir.exists():
        raise DraftError('运行目录已存在：%s' % run_dir)
    run_dir.mkdir(parents=True)
    rec = {
        'schema_version': record.SCHEMA_VERSION, 'kind': KIND, 'run_id': run_id,
        'started_at': _iso(now), 'finished_at': _iso(datetime.now(timezone.utc)),
        'plugin': {'name': name, 'version': version, 'path_in_repo': entry['plugin_path']},
        'clause_list_fingerprint': clauses.list_fingerprint(clauses.load_list(repo, name)),
        'priority_rule': '；'.join('%d %s' % kv for kv in sorted(TIER_TEXT.items())) + '；同档按条款号、用例名',
        'batch': [{'case': d.case, 'tier': tier, 'reasons': reasons, 'source': d.meta.get('source'),
                   'category': d.category, 'clauses': clause_ids(d.tags),
                   'type': CASE_DELETE.key if _is_delete(d) else CASE_DRAFT.key, 'decision': None}
                  for d, tier, reasons in batch],
        'not_on_page': {'ready_beyond_limit': [d.case for d, _, _ in ready[limit:]],
                        'needs_link': [{'case': d.case, 'reason': r} for d, r in cls['needs_link']],
                        'broken': [{'case': d.case, 'problems': p} for d, p in cls['broken']],
                        'on_earlier_page': [{'case': d.case, 'run_id': r} for d, r in cls['busy']],
                        'rejected': [d.case for d, _ in cls['rejected']]},
        'drafting': drafting,
    }
    rec = record.scrub_home(rec)
    (run_dir / 'run.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (run_dir / 'report.md').write_text(record.scrub_home(render_report(rec)), encoding='utf-8')
    page = pending.generate(data_dir, name, run_id=run_id, now=lambda: now)
    return run_dir, page, cls


def render_report(rec):
    p = rec.get('plugin') or {}
    lines = ['# 用例草稿待审：%s %s' % (p.get('name'), p.get('version')), '',
             '> 草稿不参与任何运行；在待审页勾选「通过」后才移进 `<插件>/evals/`，随后跑 `baseline` 判基线已满足。', '',
             '- 运行：`%s`' % rec.get('run_id'),
             '- 优先级：%s' % rec.get('priority_rule'), '',
             '## 本页草稿', '', '| 序 | 用例 | 类别 | 条款 | 来源 | 优先级 |', '|---|---|---|---|---|---|']
    for i, b in enumerate(rec.get('batch') or [], 1):
        lines.append('| %d | %s | %s | %s | %s | %s：%s |' % (
            i, b['case'], b.get('category') or '—', '、'.join(b.get('clauses') or []) or '—', b.get('source') or '—',
            TIER_TEXT.get(b['tier']), '；'.join(b.get('reasons') or []) or '—'))
    n = rec.get('not_on_page') or {}
    rows = [('排在本页之后（下一批再审）', ['`%s`' % c for c in n.get('ready_beyond_limit') or []]),
            ('挂不上条款（下次 `drafts write` 由 AI 先挂，或手改 tags）',
             ['`%s`（%s）' % (x['case'], x['reason']) for x in n.get('needs_link') or []]),
            ('eval 加载不了（修好再审）', ['`%s`（%s）' % (x['case'], '；'.join(x['problems'])) for x in n.get('broken') or []]),
            ('在较早的待审页上，等那页写回', ['`%s`（%s）' % (x['case'], x['run_id']) for x in n.get('on_earlier_page') or []]),
            ('已打回', ['`%s`' % c for c in n.get('rejected') or []])]
    if any(v for _, v in rows):
        lines += ['', '## 没上页的草稿', '']
        lines += ['- %s：%s' % (k, '、'.join(v)) for k, v in rows if v]
    dr = rec.get('drafting')
    if dr:
        lines += ['', '## 本批 AI 起草', '',
                  '- 模型：%s；调用 %d 次；花费（标价估算）：$%.4f' % (dr.get('model'), dr.get('calls', 0),
                                                         dr.get('cost_usd') or 0),
                  '- 写进草稿区 %d 个；挂上条款 %d 个；结构不合格未写 %d 个；判为离线评不了而跳过 %d 条' % (
                      len(dr.get('written') or []), len(dr.get('linked') or []), len(dr.get('invalid') or []),
                      len(dr.get('skipped') or []))]
        lines += ['- 跳过 %s：%s' % (s.get('target'), s.get('reason')) for s in dr.get('skipped') or []]
        lines += ['- 不合格 %s：%s' % (s.get('slug'), '；'.join(s.get('problems') or [])) for s in dr.get('invalid') or []]
    return '\n'.join(lines) + '\n'


# ---------------- 待审项 ----------------

def _clause_texts(subject):
    rel = '../../%s' % clauses.LIST_FILE
    try:
        lst = subject.read_json(rel)
    except ValueError:
        lst = None
    return {c['id']: c for c in (lst or {}).get('clauses') or []}


def _draft_rel(subject, case):
    return '../../%s/%s' % (DRAFTS_DIR, case)


def _case_body(case_dir):
    parts = []
    for f in sorted(p for p in Path(case_dir).rglob('*') if p.is_file() and p.name != META_FILE):
        try:
            text = f.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            text = '（非文本文件）'
        parts.append('===== %s =====\n%s' % (f.relative_to(case_dir).as_posix(), text.rstrip('\n')))
    return '\n\n'.join(parts)


def _collect(subject, key):
    rec = subject.rec
    if rec.get('kind') != KIND:
        return []
    texts = _clause_texts(subject)
    out = []
    for b in rec.get('batch') or []:
        if b.get('decision') or b.get('type', CASE_DRAFT.key) != key:
            continue
        d = subject.path(_draft_rel(subject, b['case']))
        meta = read_meta(d)
        if not d.is_dir() or meta.get('status', STATUS_OPEN) != STATUS_OPEN:
            continue
        tags = clauses.case_tags(d)
        facts = [('类别', meta.get('category') or '—'), ('来源', meta.get('source') or '—'),
                 ('意图', meta.get('intent') or meta.get('clause_intent') or '—')]
        for cid in clause_ids(tags):
            c = texts.get(cid) or {}
            facts.append(('条款 %s' % cid, '%s%s' % (c.get('criterion') or '（清单里没有）',
                                                   '（已退役）' if c.get('status') == 'retired' else '')))
        facts.append(('tags', '、'.join(tags) or '—'))
        facts.append(('优先级', '%s%s' % (TIER_TEXT.get(b.get('tier')), '：' + '；'.join(b['reasons'])
                                         if b.get('reasons') else '')))
        for rh in meta.get('rehang') or []:
            facts.append(('退役改挂', '%s（%s）→ %s；%s%s' % (
                rh.get('retired_id'), rh.get('reason'), '、'.join(rh.get('replaced_by') or []) or '无替代',
                {'retag': '已按建议改挂到 %s' % rh.get('target'), 'delete': '条款已删除，确认即删除用例',
                 'manual': '需人工改挂'}.get(rh.get('action'), rh.get('action')),
                '；AI 建议：%s' % rh['ai_hint'] if rh.get('ai_hint') else '')))
        if meta.get('history_source'):
            facts.append(('历史素材出处', meta['history_source']))
        rp = meta.get('replay') or {}
        if rp:
            facts.append(('compact 回放', '合成历史 %s（模板 %s，尾巴 %s 轮）；底本 %s' % (
                rp.get('history_file'), rp.get('summary_template'), rp.get('tail_turns'), rp.get('base_case') or 'AI 起草')))
        rc = meta.get('review_candidate') or {}
        if rc:
            facts.append(('复盘候选', '%s 的 %s（%s %s）；挂条款理由：%s' % (
                rc.get('review_date'), rc.get('candidate_id'), rc.get('kind'), rc.get('rule'),
                meta.get('clause_reason') or '—')))
        title = '%s：%s' % (b['case'], meta.get('intent') or meta.get('clause_intent') or meta.get('category') or '')
        out.append(pending.PendingItem(id='%s:%s' % (key, b['case']), title=title[:160], body=_case_body(d),
                                       facts=tuple(facts), payload={'case': b['case']}))
    return out


def _entry(subject, case):
    for b in subject.rec.get('batch') or []:
        if b.get('case') == case:
            return b
    raise pending.PendingError('草稿批次里没有用例 %s' % case)


def _files(subject, case):
    d = subject.path(_draft_rel(subject, case))
    return d, sorted(p for p in d.rglob('*') if p.is_file())


def _rel_from_run(subject, path):
    return os.path.relpath(str(path), str(subject.run_dir))


def _apply_draft(subject, item, code, now):
    case = (item.get('payload') or {}).get('case')
    b = _entry(subject, case)
    ts = _iso(now)
    p = subject.rec.get('plugin') or {}
    evals_dir = subject.repo / (p.get('path_in_repo') or '.') / 'evals'
    d, files = _files(subject, case)
    if code == 'A':
        dest = evals_dir / case
        if not d.is_dir():
            if dest.is_dir():
                subject.warn('%s 已在 evals/ 里（别的页通过过），本项只记裁定' % case)
                b['decision'] = {'code': 'A', 'status': 'approved', 'at': ts, 'note': 'already-in-evals'}
                return
            raise pending.PendingError('草稿 %s 已不在草稿区' % case)
        if dest.exists():
            raise pending.PendingError('evals/%s 已存在，通过不了；先改草稿目录名或删掉旧用例' % case)
        problems = casefiles.check_case_dir(d)
        if problems:
            raise pending.PendingError('草稿 %s eval 加载不了：%s' % (case, '；'.join(problems)))
        for f in files:
            rel = f.relative_to(d)
            if f.name != META_FILE or rel.parent != Path('.'):
                try:
                    text = f.read_text(encoding='utf-8')
                except UnicodeDecodeError:
                    raise pending.PendingError('草稿 %s 的 %s 不是 UTF-8 文本，移不了' % (case, rel.as_posix()))
                subject.stage_text(_rel_from_run(subject, dest / rel), text)
            subject.stage_delete(_rel_from_run(subject, f))
        b['decision'] = {'code': 'A', 'status': 'approved', 'at': ts,
                         'moved_to': (dest.relative_to(subject.repo)).as_posix()}
        subject.warn('新用例 %s 已进 evals/：跑 `baseline %s` 判它是否基线已满足（不装臂 3 次 ≥ 2/3 通过）'
                     % (case, p.get('name')))
    else:
        if not d.is_dir():
            subject.warn('草稿 %s 已不在草稿区，本项只记裁定' % case)
            b['decision'] = {'code': code, 'status': 'rejected', 'at': ts, 'note': 'draft-missing'}
            return
        meta = read_meta(d)
        meta.update(status=STATUS_REJECTED, rejected_at=ts, rejected_in_run=subject.rec.get('run_id'))
        subject.stage_text(_rel_from_run(subject, d / META_FILE),
                           json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
        b['decision'] = {'code': code, 'status': 'rejected', 'at': ts}


def _apply_delete(subject, item, code, now):
    case = (item.get('payload') or {}).get('case')
    b = _entry(subject, case)
    ts = _iso(now)
    d, files = _files(subject, case)
    if not d.is_dir():
        subject.warn('草稿 %s 已不在草稿区，本项只记裁定' % case)
        b['decision'] = {'code': code, 'status': 'missing', 'at': ts}
        return
    if code == 'A':
        for f in files:
            subject.stage_delete(_rel_from_run(subject, f))
        b['decision'] = {'code': 'A', 'status': 'deleted', 'at': ts}
    else:
        meta = read_meta(d)
        for rh in meta.get('rehang') or []:
            if rh.get('action') == 'delete':
                rh['action'] = 'manual'
                rh['kept_at'] = ts
        subject.stage_text(_rel_from_run(subject, d / META_FILE),
                           json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
        b['decision'] = {'code': code, 'status': 'kept', 'at': ts}


CASE_DRAFT = pending.ItemType(
    key='case-draft', label='用例草稿',
    options=(('A', '通过：移进 <插件>/evals/，之后每次对照都跑'), ('B', '打回：留在草稿区，不再上页')),
    collect=lambda s: _collect(s, 'case-draft'), apply=_apply_draft, priority=DRAFT_PRIORITY,
    kinds=frozenset({KIND}),
    hint='草稿不参与任何运行，通过才跑。看三件事：prompt 像不像真实任务、没有把要测的规矩直接告诉模型；'
         'grader 判的是行为而不是措辞；tags 挂的条款对不对。')
CASE_DELETE = pending.ItemType(
    key='case-draft-delete', label='退役条款用例删除',
    options=(('A', '删除：条款已删除，这个用例不再需要（git 历史留底）'), ('B', '保留：留在草稿区，手改 tags 挂到别的条款')),
    collect=lambda s: _collect(s, 'case-draft-delete'), apply=_apply_delete, priority=DRAFT_PRIORITY,
    kinds=frozenset({KIND}),
    hint='这个用例原挂的条款在条款清单变更里被删除（没有替代条款）。spec：条款删除时其用例经用户确认后删除。')
pending.register_type(CASE_DELETE)
pending.register_type(CASE_DRAFT)


# ---------------- 命令行 ----------------

def add_parser(sub):
    p = sub.add_parser('drafts', help='用例草稿：write 让 AI 起草并出待审页；page 只出待审页；list 只读地看草稿区；'
                                      'sync 把退役条款的用例退回草稿区（write、page 也会先做这一步）；'
                                      'compact 生成 compact 之后的回放用例（每插件 ≤3）；'
                                      'from-review 把复盘里选了「转草稿」的候选由 AI 改写成合成用例')
    p.add_argument('action', choices=('write', 'page', 'list', 'sync', 'compact', 'from-review'))
    p.add_argument('name')
    p.add_argument('--model', help='write：起草用的模型，缺省 %s' % 'claude-fable-5-1')
    p.add_argument('--limit', type=int, default=20, help='write：本次最多起草几个目标（条款 / skill / agent 的缺口），默认 20；'
                        'compact：本次最多生成几个，另受每插件合计 ≤3 的上限约束')
    p.add_argument('--clauses', help='write / compact：只起草这些条款，逗号分隔，如 C001,C007（含之前判为离线评不了的）；'
                                     '点名时已打回的草稿不算覆盖，会重写。不点名时打回的草稿仍算该条款已有草稿，不自动重写')
    p.add_argument('--no-page', action='store_true', help='write / compact / from-review：只写草稿，不出待审页')
    p.add_argument('--date', help='from-review：用哪天的复盘结果（YYYY-MM-DD），缺省最新一份')
    return p


def _print_page(run_dir, page, data_dir, name):
    print('运行目录：%s' % run_dir)
    print('待审页：%s（本页 %d 项）' % (page.html_path, len(page.items)))
    print('浏览器打开：%s' % page.html_path.resolve().as_uri())
    print('用户贴回回复码后运行：')
    print("  python3 plugin_eval.py --data-dir '%s' pending %s --reply '<回复码>'" % (data_dir, name))


def _print_classes(cls):
    for d, tier, reasons in cls['ready']:
        print('  可审  [%s] %s %s' % (TIER_TEXT[tier], d.case, '、'.join(clause_ids(d.tags))))
    for key, label in (('needs_link', '待挂条款'), ('broken', '加载不了'), ('busy', '已在页上'), ('rejected', '已打回')):
        for d, why in cls[key]:
            extra = '；'.join(why) if isinstance(why, list) else (why or '')
            print('  %s %s %s' % (label, d.case, extra))


def main(args, data_dir):
    try:
        entry = registry.lookup(data_dir, args.name)
        repo, plugin_dir = Path(entry['repo']), registry.plugin_dir(entry)
        if args.action == 'write':
            from . import drafter
            return drafter.main(args, data_dir)
        if args.action == 'compact':
            from . import replay
            return replay.main(args, data_dir)
        if args.action == 'from-review':
            from . import candidate_drafts
            return candidate_drafts.main(args, data_dir)
        if args.action == 'list':
            # 只读（审查 11 应修 3）：不退回退役用例、不清空目录。退回会把用例移出 evals/、改变 evals 指纹，
            # 有对照在跑或待续跑时续跑会被拒；退回只在 sync / page / write 时做
            cls = classify(repo, args.name, plugin_dir)
            print('草稿区：%s' % drafts_root(repo, args.name))
            _print_classes(cls)
            return 0
        done = sync_rehang(repo, args.name, plugin_dir)
        if args.action == 'sync':
            print('退役条款的用例：处理 %d 条建议' % len(done))
            for case, res in done:
                print('  %s：%s' % (case, res))
            return 0
        run_dir, page, cls = create_batch(data_dir, args.name)
        if page is None:
            print('没有可审的草稿')
            _print_classes(cls)
            return 0
        _print_page(run_dir, page, data_dir, args.name)
        return 0
    except (DraftError, registry.RegistryError, pending.PendingError, ValueError) as e:
        print('错误：%s' % e, file=sys.stderr)
        return 2
