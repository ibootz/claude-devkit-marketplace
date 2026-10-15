"""会话复盘的待审页：每个插件每次复盘一页，复用 pending 的页面框架、抽样、回复码与写回事务。

页的主体（Subject）是 `<仓>/plugin-evals/<插件>/reviews/<日期>.json`，回复码的 run_id 是 `review-<日期>`，
pending.apply_reply 见到这个前缀就转到本模块。两种待审项：

- 复盘候选（`review-candidate`）：A 转用例草稿（由票 13 现读本机 jsonl 改写成合成用例）/ B 不转。写回候选的
  `selection`（draft / skip）与 `decided_at`。优先级排在分歧样本、抽检、用例草稿之后（票 08 集成口径）。
- 建议跑对照（`review-compare-hint`）：Claude Code 版本或主力模型与上次离线对照不同时出现，必上页。
  A 知道了：写回 `compare_hint.acknowledged_at`。

页上只显示信号名、次数与定位指针（会话 id、uuid、时间），不显示也不读取对话原文。
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import pending, registry, review

CANDIDATE_PRIORITY = 400      # 分歧样本 > 抽检 > 用例草稿 > 复盘候选（票 08 集成口径），前几档由票 09、11 设值
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _iso(now):
    return pending._iso(now)


# ---------------- 待审项类型 ----------------

def _candidate_collect(subject):
    rec = subject.rec
    if rec.get('kind') != review.KIND:
        return []
    out = []
    for c in rec.get('candidates') or []:
        if not isinstance(c, dict) or c.get('selection'):
            continue
        kind = review.KIND_TEXT.get(c.get('kind'), c.get('kind'))
        ptrs = ['%s%s / %s / %s' % (p.get('session_id'), ' 子代理 %s' % p['agent_id'] if p.get('agent_id') else '',
                                     p.get('uuid'), p.get('timestamp')) for p in c.get('pointers') or []]
        facts = [('信号', kind), ('规则', c.get('rule')), ('次数（按 uuid 去重后）', c.get('count')),
                 ('其中子代理', c.get('subagent_count')), ('是否在 compact 之后', '是' if c.get('after_compact') else '否'),
                 ('命中条款 id', '、'.join(c.get('clause_ids') or []) or
                  '未映射（%s）' % ((c.get('clause_mapping') or {}).get('reason') or '条款清单没有登记这个信号')),
                 ('插件版本', '、'.join('%s×%d' % kv for kv in sorted((c.get('plugin_versions') or {}).items())) or '取不到')]
        facts += [('定位指针 %d（会话 / uuid / 时间）' % i, p) for i, p in enumerate(ptrs, 1)]
        out.append(pending.PendingItem(
            id='review-candidate:%s' % c.get('id'),
            title='%s：%s ×%s%s' % (kind, c.get('rule'), c.get('count'), '（compact 之后）' if c.get('after_compact') else ''),
            facts=tuple(facts), payload={'candidate_id': c.get('id')}))
    return out


def _candidate_apply(subject, item, code, now):
    cid = (item.get('payload') or {}).get('candidate_id')
    for c in subject.rec.get('candidates') or []:
        if isinstance(c, dict) and c.get('id') == cid:
            c['selection'] = 'draft' if code == 'A' else 'skip'
            c['decided_at'] = _iso(now)
            c['carried_from'] = None
            return
    raise pending.PendingError('复盘结果里找不到候选 %s（复盘结果可能被重跑覆盖过）' % cid)


REVIEW_CANDIDATE = pending.ItemType(
    key='review-candidate', label='复盘候选',
    options=(('A', '转用例草稿（由 AI 现读本机会话改写成合成用例，进 drafts/ 再审）'), ('B', '不转')),
    collect=_candidate_collect, apply=_candidate_apply, priority=CANDIDATE_PRIORITY, kinds=frozenset({review.KIND}),
    hint='会话复盘发现的一类违规或现象。只列信号与定位指针，不含对话原文；转草稿时才现读本机会话，原文读不到（多半是过了保留期被清掉）即作废。')


def _hint_collect(subject):
    rec = subject.rec
    h = rec.get('compare_hint') or {}
    if rec.get('kind') != review.KIND or not h.get('suggest') or h.get('acknowledged_at'):
        return []
    facts = [(d.get('field'), '%s → %s' % (d.get('previous'), d.get('current'))) for d in h.get('diffs') or []]
    facts.append(('上次对照', h.get('previous_run')))
    return [pending.PendingItem(id='review-compare-hint:%s' % rec.get('run_id'),
                                title='建议跑对照：Claude Code 版本或主力模型与上次离线对照不同',
                                facts=tuple(facts), payload={'run_id': rec.get('run_id')})]


def _hint_apply(subject, item, code, now):
    h = subject.rec.get('compare_hint')
    if not isinstance(h, dict):
        raise pending.PendingError('复盘结果里没有 compare_hint')
    h['acknowledged_at'] = _iso(now)


COMPARE_HINT = pending.ItemType(
    key='review-compare-hint', label='建议跑对照', options=(('A', '知道了（之后去跑 compare）'),),
    collect=_hint_collect, apply=_hint_apply, always=True, kinds=frozenset({review.KIND}),
    hint='上次离线对照的结果与现在的运行环境不可直接比。选「知道了」只记已读，不会自动跑对照。')

pending.register_type(COMPARE_HINT)       # 先注册：页上排在复盘候选前面
pending.register_type(REVIEW_CANDIDATE)


# ---------------- 定位复盘结果 ----------------

def find_review(data_dir, name, date=None, err=pending.PendingError):
    entry = registry.lookup(data_dir, name)
    repo = Path(entry['repo'])
    d = review.reviews_dir(repo, name)
    if date is None:
        dates = sorted(p.stem for p in d.glob('*.json') if _DATE_RE.match(p.stem)) if d.is_dir() else []
        if not dates:
            raise pending.NothingPending('%s 下没有会话复盘结果；先跑 review' % d)
        date = dates[-1]
    if not _DATE_RE.match(date or '') or not (d / ('%s.json' % date)).is_file():
        raise err('插件 %s 没有 %s 的复盘结果（找的是 %s/%s.json）' % (name, date, d, date))
    return repo, d / ('%s.json' % date)


def _subject(repo, path):
    try:
        rec = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as e:
        raise pending.PendingError('%s 不是合法 JSON：%s' % (path, e))
    if not isinstance(rec, dict) or rec.get('kind') != review.KIND:
        raise pending.PendingError('%s 不是会话复盘结果' % path)
    return pending.Subject(repo, path.parent, rec, record_name=path.name)


def _lock_id(name, path):
    return 'review-%s-%s' % (name, path.stem)


def generate(data_dir, name, date=None, *, now=None, types=None):
    types = types or pending._REGISTRY
    now = now() if callable(now) else (now or datetime.now(timezone.utc))   # pending.apply_reply 传来的已是时刻
    repo, path = find_review(data_dir, name, date)
    with pending._locked(data_dir, _lock_id(name, path)):
        subject = _subject(repo, path)
        return pending._generate(data_dir, name, repo, path.parent, now, types, subject=subject)


def apply_reply(data_dir, name, code_run, page_id, decisions, *, now=None, types=None):
    types = types or pending._REGISTRY
    now = now() if callable(now) else (now or datetime.now(timezone.utc))   # pending.apply_reply 传来的已是时刻
    date = code_run[len(review.REVIEW_ID_PREFIX):]
    try:
        repo, path = find_review(data_dir, name, date, err=pending.ReplyError)
    except pending.NothingPending as e:
        raise pending.ReplyError(str(e))
    with pending._locked(data_dir, _lock_id(name, path), err=pending.ReplyError):
        try:
            subject = _subject(repo, path)
        except pending.PendingError as e:
            raise pending.ReplyError(str(e))
        return pending._apply(repo, path.parent, code_run, page_id, decisions, now, types, subject=subject)
