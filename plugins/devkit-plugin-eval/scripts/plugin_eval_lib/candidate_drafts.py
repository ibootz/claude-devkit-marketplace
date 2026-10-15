"""复盘候选转用例草稿（`drafts from-review`，票 13，spec「2.3 用例从哪来」复盘候选段）。

输入：`reviews/<日期>.json` 里用户在待审页选了「转草稿」（selection=draft）、还没转过的候选。
每个候选按定位指针（新到旧）现读本机会话 jsonl，取触发那条记录与它之前最多两轮的对话，**只在内存里**交给 AI
改写成合成用例：去掉项目名、路径、业务内容，换成虚构的通用场景。原文片段不落盘、不进日志。

结果写回该候选的 `conversion`（复盘结果文件里，与待审页写回同一把锁）：
  drafted           写进了草稿区（draft = 草稿目录名）
  void              过了保留期：指针指向的会话文件或记录已不在，或时间早于 cleanupPeriodDays（code 说明哪种）
  skipped           AI 判为写不成离线用例（code 是枚举，不记 AI 的自由文字：复盘结果入库，自由文字可能带原文）
  privacy-rejected  隐私自检不过，整条不写（findings 只记命中类别与个数）
  invalid           改写结果结构不合格或 eval 加载不了
  error             AI 调用失败
前三种是终态，不再重试；后三种下次 from-review 再试。

隐私自检（写盘前，对将写盘的每段文字）：
  - 路径形态（家目录、`/Users|home/`、Windows 用户目录、`~/`）与邮箱形态（`example.invalid` 除外）；
  - 从这次会话本身取出的私有词：工作目录的项目名、家目录用户名、git 分支名、出现过的主机名与包名里的非通用段；
  - 用户自配的私有词：环境变量 PLUGIN_EVAL_PRIVATE_TERMS（逗号分隔，不区分大小写；词表不进仓库）；
  - 与原文片段（用户与助手的话、工具调用参数）去空白后逐字重合 ≥ OVERLAP_CHARS 字。
任一命中整条不写。改写出的合成历史另查与被测插件注入文字的重合（replay.injection_hits），命中也不写。
"""
import copy
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import casefiles, clauses, drafts, pending, preflight, record, registry, replay, review
from . import review_pending  # noqa: F401  （注册复盘待审项类型；find_review 也在里面）

SOURCE = 'review-candidate'
CATEGORY = 'review-replay'
TAG = 'review-replay'
TERMINAL = ('drafted', 'void', 'skipped')
OVERLAP_CHARS = 24
EXCERPT_TURNS = 2           # 触发记录之前最多带几轮用户发言
TEXT_LIMIT = 1200           # 片段里每段文字截断长度
EXCERPT_LIMIT = 12000       # 片段总长上限
MAX_CHAIN = 60
PRIVATE_TERMS_ENV = 'PLUGIN_EVAL_PRIVATE_TERMS'
SKIP_CODES = ('not-reproducible-offline', 'needs-write-tools', 'needs-user-reply', 'not-plugin-behavior',
              'cannot-anonymize')
_EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)')
_HOST_RE = re.compile(r'\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+){1,6}\b')
_TLDS = {'com', 'cn', 'net', 'org', 'io', 'dev', 'ai', 'app', 'co', 'cc', 'me', 'info', 'biz', 'edu', 'gov'}
_GENERIC = {'github', 'gitlab', 'google', 'anthropic', 'claude', 'example', 'localhost', 'npmjs', 'python', 'pypi',
            'apple', 'microsoft', 'openai', 'stackoverflow', 'mozilla', 'docs', 'www', 'http', 'https', 'mail',
            'main', 'master', 'develop', 'head', 'feature', 'release', 'test', 'tests', 'users', 'home', 'workspace',
            'projects', 'project', 'src', 'code', 'repo', 'repos', 'tmp', 'private', 'worktrees', 'plugins', 'cache',
            'shared', 'user', 'admin', 'root', 'json', 'html', 'yaml', 'markdown', 'none', 'null', 'true', 'false'}

SYSTEM_PROMPT = ('你是 Claude Code 插件离线评测的用例改写者。你会读到一段真实会话的片段，把它改写成一个合成的离线用例：'
                 '保留「什么样的任务、什么样的动作触发了这个信号」，其余全部换成虚构内容。'
                 '只输出符合给定 JSON Schema 的结果，不输出别的文字。')

REWRITE_SCHEMA = {
    'type': 'object',
    'properties': {
        'skip_code': {'type': 'string', 'enum': [''] + list(SKIP_CODES)},
        'clause_ids': {'type': 'array', 'items': {'type': 'string'}},
        'clause_reason': {'type': 'string'},
        'case': {},          # _schema() 填入：drafter 的单个用例结构，加 history 与 compact_summary
    },
    'required': ['skip_code', 'clause_ids', 'clause_reason'],
}


class CandidateError(Exception):
    pass


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _schema():
    from . import drafter
    case = copy.deepcopy(drafter.CASE_SCHEMA['properties']['cases']['items'])
    case['properties'].pop('technique', None)
    case['properties']['history'] = {'type': 'array', 'maxItems': 2 * EXCERPT_TURNS, 'items': {
        'type': 'object', 'properties': {'role': {'type': 'string', 'enum': ['user', 'assistant']},
                                         'text': {'type': 'string'}}, 'required': ['role', 'text']}}
    case['properties']['compact_summary'] = {'type': 'string'}
    case['required'] = ['slug', 'intent', 'prompt', 'graders']
    case['properties'].pop('target', None)
    s = copy.deepcopy(REWRITE_SCHEMA)
    s['properties']['case'] = case
    return s


# ---------------- 定位会话 ----------------

def locate(cfg, ptr):
    """指针 → 会话 jsonl 路径；指针形态不合白名单或文件不在返回 None。"""
    sid, aid = ptr.get('session_id'), ptr.get('agent_id')
    if not isinstance(sid, str) or not review._UUID_RE.match(sid):
        return None
    if aid is not None and (not isinstance(aid, str) or not review._TOKEN_RE.match(aid)):
        return None
    projects = Path(cfg) / 'projects'
    if not projects.is_dir():
        return None
    for proj in sorted(p for p in projects.iterdir() if p.is_dir()):
        f = proj / sid / 'subagents' / ('agent-%s.jsonl' % aid) if aid else proj / ('%s.jsonl' % sid)
        if f.is_file():
            return f
    return None


def _records(path):
    out = []
    with open(str(path), encoding='utf-8', errors='replace') as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if isinstance(o, dict):
                out.append(o)
    return out


def _parse_ts(s):
    try:
        return datetime.strptime(str(s)[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def resolve(cfg, cand, *, now, retention_days):
    """按指针（新到旧）找第一个还能读的触发记录。返回 (片段 dict, None) 或 (None, 作废原因码)。"""
    codes = []
    for ptr in cand.get('pointers') or []:
        ts = _parse_ts(ptr.get('timestamp'))
        if ts is not None and ts < now - timedelta(days=retention_days):
            codes.append('past-retention')
            continue
        f = locate(cfg, ptr)
        if f is None:
            codes.append('file-gone')
            continue
        recs = _records(f)
        if not any(r.get('uuid') == ptr.get('uuid') for r in recs):
            codes.append('record-gone')
            continue
        return excerpt(recs, ptr.get('uuid')), None
    return None, (codes[0] if codes else 'no-pointer')


# ---------------- 片段（只在内存里） ----------------

def _cut(text, n=TEXT_LIMIT):
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return text if len(text) <= n else text[:n] + '…（截断）'


def _items(rec):
    t = rec.get('type')
    if t == 'system' and rec.get('subtype') == 'compact_boundary':
        return [('compact', '（此处发生过 compact）')]
    msg = rec.get('message') if isinstance(rec.get('message'), dict) else {}
    content = msg.get('content')
    if t == 'user':
        if rec.get('isCompactSummary'):
            return [('compact_summary', content if isinstance(content, str) else '')]
        if isinstance(content, str):
            return [] if rec.get('isMeta') else [('user', content)]
        out = []
        for b in content if isinstance(content, list) else []:
            if not isinstance(b, dict):
                continue
            if b.get('type') == 'text':
                out.append(('user', b.get('text') or ''))
            elif b.get('type') == 'tool_result':
                c = b.get('content')
                if isinstance(c, list):
                    c = ' '.join(x.get('text', '') for x in c if isinstance(x, dict))
                out.append(('tool_result_error' if b.get('is_error') else 'tool_result', c or ''))
        return out
    if t == 'assistant':
        out = []
        for b in msg.get('content') or []:
            if not isinstance(b, dict):
                continue
            if b.get('type') == 'text':
                out.append(('assistant', b.get('text') or ''))
            elif b.get('type') == 'tool_use':
                out.append(('tool_use', '%s %s' % (b.get('name'), json.dumps(b.get('input'), ensure_ascii=False))))
        return out
    if t == 'attachment':
        a = rec.get('attachment') if isinstance(rec.get('attachment'), dict) else {}
        if 'error' in str(a.get('type') or ''):
            return [('hook_error', a.get('content') or a.get('stderr') or '')]
    return []


def excerpt(recs, trigger_uuid):
    """触发记录沿 parentUuid 往回取，到凑够 EXCERPT_TURNS 轮用户发言为止。返回 {items, private}：
    items 是 [(角色, 文字)]，private 是从这段会话取出的私有词（工作目录、分支、用户名）。"""
    by_uuid = {r.get('uuid'): r for r in recs if r.get('uuid')}
    chain, cur, seen = [], by_uuid.get(trigger_uuid), set()
    while cur is not None and len(chain) < MAX_CHAIN and cur.get('uuid') not in seen:
        seen.add(cur.get('uuid'))
        chain.append(cur)
        cur = by_uuid.get(cur.get('parentUuid'))
    chain.reverse()
    items, users = [], 0
    for r in reversed(chain):
        its = _items(r)
        items[:0] = its
        users += sum(1 for k, _ in its if k == 'user')
        if users >= EXCERPT_TURNS:
            break
    items = [(k, _cut(v)) for k, v in items]
    total, kept = 0, []
    for k, v in reversed(items):        # 超总长时丢最早的
        total += len(v)
        if total > EXCERPT_LIMIT and kept:
            break
        kept.insert(0, (k, v))
    private = set()
    for r in chain:
        private |= _path_terms(r.get('cwd'))
        b = r.get('gitBranch')
        if isinstance(b, str):
            private |= {x for x in re.split(r'[/\s]+', b) if len(x) >= 4 and x.lower() not in _GENERIC}
    for _, v in kept:
        private |= host_terms(v)
    return {'items': kept, 'private': private}


def _path_terms(cwd):
    if not isinstance(cwd, str) or not cwd:
        return set()
    parts = [p for p in re.split(r'[/\\]+', cwd) if p]
    out = set()
    home = Path(os.path.expanduser('~')).name
    if home and len(home) >= 3:
        out.add(home)
    if parts:
        out.add(parts[-1])
    if '.claude' in parts:           # worktree：.claude/worktrees/<名> 前一段才是项目名
        i = parts.index('.claude')
        if i > 0:
            out.add(parts[i - 1])
    return {x for x in out if len(x) >= 4 and x.lower() not in _GENERIC}


def host_terms(text):
    """主机名、Java 包名里的非通用段（如 a.b.example.com 的 a、b）。"""
    out = set()
    for m in _HOST_RE.finditer(text or ''):
        labels = m.group(0).lower().split('.')
        if not (labels[-1] in _TLDS or labels[0] in _TLDS):
            continue
        out |= {lb for lb in labels if len(lb) >= 4 and lb not in _TLDS and lb not in _GENERIC and not lb.isdigit()}
    return out


# ---------------- 隐私自检 ----------------

def _norm(text):
    return re.sub(r'\s+', '', text or '')


def configured_terms(env=None):
    raw = (env if env is not None else os.environ).get(PRIVATE_TERMS_ENV) or ''
    return {t.strip() for t in raw.split(',') if t.strip()}


def privacy_findings(texts, *, private_terms=(), source_texts=(), home=None):
    """将写盘的文字里命中的隐私类别与个数：{类别: 个数}。空 = 通过。不回命中原文。"""
    home = (home or os.path.expanduser('~')).rstrip('/')
    found = {}

    def hit(kind):
        found[kind] = found.get(kind, 0) + 1

    terms = [t.lower() for t in private_terms if t]
    windows = set()
    for s in source_texts:
        n = _norm(s)
        windows |= {n[i:i + OVERLAP_CHARS] for i in range(len(n) - OVERLAP_CHARS + 1)}
    for t in texts:
        if not t:
            continue
        if review._PATH_RE.search(t) or (home and home != '~' and home in t):
            hit('path')
        for m in _EMAIL_RE.finditer(t):
            if not m.group(1).lower().endswith('example.invalid'):
                hit('email')
        low = t.lower()
        for term in terms:
            if term in low:
                hit('private-term')
        if windows:
            n = _norm(t)
            if any(n[i:i + OVERLAP_CHARS] in windows for i in range(len(n) - OVERLAP_CHARS + 1)):
                hit('verbatim-overlap')
    return found


def _case_texts(case_dir):
    out = []
    for f in sorted(Path(case_dir).rglob('*')):
        if f.is_file():
            try:
                out.append(f.read_text(encoding='utf-8'))
            except (OSError, UnicodeDecodeError):
                out.append('')
            out.append(f.relative_to(case_dir).as_posix())
    return out


# ---------------- 提示词 ----------------

def build_prompt(name, cand, ex, active):
    from . import drafter
    lines = ['被测插件：%s' % name, '',
             '会话复盘发现了下面这个信号，用户选了「转用例草稿」：',
             '- 信号：%s；规则：%s；出现 %s 次%s' % (review.KIND_TEXT.get(cand.get('kind'), cand.get('kind')),
                                               cand.get('rule'), cand.get('count'),
                                               '；发生在 compact 之后' if cand.get('after_compact') else ''),
             '', '触发前后的会话片段（真实会话，只供你理解情境，一个字都不要照抄）：', '<excerpt>']
    for k, v in ex['items']:
        lines.append('[%s] %s' % (k, v))
    lines += ['</excerpt>', '',
              '把它改写成一个合成的离线用例，要求：',
              '1. 隐私：项目名、仓库名、目录与文件路径、公司与产品名、人名、账号、主机名、分支名、业务术语与数据，'
              '全部换成虚构的通用内容（例如一个虚构的开源小工具）。不照抄片段里的任何句子、命令或代码。'
              '换不干净就把 skip_code 设为 cannot-anonymize。',
              '2. 保留触发结构：被测 prompt 让模型面对同类任务、自然地走到同类动作，守与不守在会话里看得出来。',
              '3. history（可选，最多 %d 轮）：被测 prompt 之前的合成对话，用来还原触发时的情境；每轮一条 user 一条 assistant。'
              '%s' % (EXCERPT_TURNS, '这个信号发生在 compact 之后：再写 compact_summary，一段虚构的「此前对话摘要」。'
                      if cand.get('after_compact') else '不需要就留空数组。'),
              '4. history 与 compact_summary 只写普通对话，不写被测插件的规矩原文或 hook 注入的文字（不装插件的对照组也会读到它们）。',
              '5. 条款：下面是被测插件的有效条款。判断这个用例测的是哪一条，把 id 写进 clause_ids（最多 2 个），'
              '理由写进 clause_reason（一句话、不引用片段原文）。判不出就留空数组。',
              '6. 写不成离线用例时 skip_code 填对应枚举（%s），case 可省略；能写时 skip_code 为空串。'
              % '、'.join(SKIP_CODES), '',
              drafter.ENV_NOTE, '', drafter.GRADER_NOTE, '', drafter.JUDGE_NOTE, '', '有效条款：']
    lines += ['- %s：%s' % (c['id'], c.get('criterion')) for c in active]
    return '\n'.join(lines)


# ---------------- 写草稿 ----------------

def _history(case, slug, after_compact):
    turns, pend = [], None
    for h in case.get('history') or []:
        if h.get('role') == 'user':
            pend = h.get('text') or ''
        elif h.get('role') == 'assistant' and pend is not None:
            turns.append((pend, h.get('text') or ''))
            pend = None
    summary = (case.get('compact_summary') or '').strip()
    if not turns and not (after_compact and summary):
        return None, None
    if after_compact and summary:
        summary = ('This session is being continued from a previous conversation that ran out of context. '
                   'The summary below covers the earlier portion of the conversation.\n\nSummary:\n' + summary)
    sid, recs = replay.build_history('review:%s' % slug, turns, compact=bool(after_compact and summary),
                                     summary=summary or replay.SUMMARY)
    return sid, recs


def convert_one(cand, ex, *, repo, name, ai, model, active, review_date, private_terms, injection_text, now, taken):
    """改写一个候选。返回 conversion dict（写回复盘结果）与 (花费, 调用次数)。只在全部检查通过后才写盘。"""
    from . import drafter
    obj, meta = ai(build_prompt(name, cand, ex, active), _schema(), model)
    cost = (meta or {}).get('cost_usd') or 0
    at = _iso(now)
    if obj.get('skip_code'):
        code = obj['skip_code'] if obj['skip_code'] in SKIP_CODES else 'not-reproducible-offline'
        return {'status': 'skipped', 'code': code, 'at': at}, cost
    case = obj.get('case') or {}
    active_ids = {c['id'] for c in active}
    cids = [c for c in obj.get('clause_ids') or [] if c in active_ids][:2]
    slug = drafter._unique_slug('review-%s' % (case.get('slug') or cand.get('id')), taken)
    spec = drafter._spec(case, {'kind': 'clause', 'clause': cids[0] if cids else None}, slug)   # tags 下一行整体改写
    spec['tags'] = [TAG] + cids
    sid, recs = _history(case, slug, cand.get('after_compact'))
    if recs:
        spec['history_file'] = replay.HISTORY_FILE
        spec['history_text'] = replay.history_text(recs)
    problems = casefiles.validate_spec(spec)
    if problems:
        return {'status': 'invalid', 'code': 'spec', 'problems': len(problems), 'at': at}, cost
    if recs and injection_text and replay.injection_hits(replay.message_texts(recs), injection_text):
        return {'status': 'invalid', 'code': 'history-has-injection', 'at': at}, cost
    meta_out = {'schema_version': drafts.SCHEMA_VERSION, 'case': slug, 'source': SOURCE, 'category': CATEGORY,
                'clauses': cids, 'clause_reason': obj.get('clause_reason') or None,
                'intent': case.get('intent'), 'target': 'review:%s' % cand.get('id'), 'created_at': at,
                'created_by': {'model': model}, 'status': drafts.STATUS_OPEN,
                'review_candidate': {'review_date': review_date, 'candidate_id': cand.get('id'),
                                     'kind': cand.get('kind'), 'rule': cand.get('rule'),
                                     'after_compact': bool(cand.get('after_compact'))},
                'replay': {'history_file': replay.HISTORY_FILE, 'history_session_id': sid,
                           'history_turns': len(case.get('history') or []) // 2,
                           'compact': bool(recs and recs[0].get('subtype') == 'compact_boundary')} if recs else None}
    rendered = casefiles.render_case(spec)
    texts = list(rendered.values()) + list(rendered.keys()) + [json.dumps(meta_out, ensure_ascii=False)]
    sources = [v for k, v in ex['items'] if k in ('user', 'assistant', 'tool_use', 'compact_summary')]
    found = privacy_findings(texts, private_terms=set(private_terms) | ex['private'], source_texts=sources)
    if found:
        return {'status': 'privacy-rejected', 'findings': dict(sorted(found.items())), 'at': at}, cost
    dest = drafts.drafts_root(repo, name) / slug
    casefiles.write_case(dest, spec)
    drafts.write_meta(dest, meta_out)
    left = casefiles.check_case_dir(dest)
    found = privacy_findings(_case_texts(dest), private_terms=set(private_terms) | ex['private'], source_texts=sources)
    if left or found:
        import shutil
        shutil.rmtree(str(dest), ignore_errors=True)
        if found:
            return {'status': 'privacy-rejected', 'findings': dict(sorted(found.items())), 'at': at}, cost
        return {'status': 'invalid', 'code': 'case-dir', 'problems': len(left), 'at': at}, cost
    return {'status': 'drafted', 'draft': slug, 'clauses': cids, 'at': at}, cost


def _existing(repo, name):
    """草稿区里已由复盘候选改写出的草稿：{候选 id: 草稿目录名}（含打回的）。"""
    out = {}
    for d in drafts.list_drafts(repo, name):
        rc = d.meta.get('review_candidate') or {}
        if rc.get('candidate_id'):
            out[rc['candidate_id']] = d.case
    return out


def run(data_dir, name, *, date=None, ai, model, now=None, env=None, injection_text=None, log=None):
    """转换 date（缺省最新）那份复盘结果里待转的候选，写回 conversion。返回摘要。"""
    log = log or (lambda msg: print(msg, file=sys.stderr))
    now = now or datetime.now(timezone.utc)
    env = os.environ if env is None else env
    try:
        repo, path = review_pending.find_review(data_dir, name, date, err=CandidateError)
    except pending.NothingPending as e:
        raise CandidateError(str(e))
    rec = json.loads(path.read_text(encoding='utf-8'))
    review_date = path.stem
    entry = registry.lookup(data_dir, name)
    plugin_dir = registry.plugin_dir(entry)
    cfg = preflight.config_dir(env)
    retention, _ = preflight._cleanup_period_days(cfg)
    lst = clauses.load_list(repo, name) or {}
    active = [c for c in lst.get('clauses') or [] if c.get('status') == 'active']
    have = _existing(repo, name)
    todo = [c for c in rec.get('candidates') or [] if isinstance(c, dict) and c.get('selection') == 'draft'
            and (c.get('conversion') or {}).get('status') not in TERMINAL]
    summary = {'review_date': review_date, 'model': model, 'calls': 0, 'cost_usd': 0.0, 'written': [], 'invalid': [],
               'skipped': [], 'linked': [], 'stopped': None, 'conversions': {}}
    if not todo:
        return summary
    if injection_text is None:
        injection_text = replay.default_injection_text(plugin_dir, repo, name)
    private_terms = configured_terms(env)
    root = drafts.drafts_root(repo, name)
    taken = {p.name for p in root.iterdir()} if root.is_dir() else set()
    for cand in todo:
        cid = cand.get('id')
        if cid in have:
            conv = {'status': 'drafted', 'draft': have[cid], 'at': _iso(now), 'code': 'already-in-drafts'}
        else:
            ex, void = resolve(cfg, cand, now=now, retention_days=retention)
            if void:
                conv = {'status': 'void', 'code': void, 'at': _iso(now)}
            else:
                try:
                    conv, cost = convert_one(cand, ex, repo=repo, name=name, ai=ai, model=model, active=active,
                                             review_date=review_date, private_terms=private_terms,
                                             injection_text=injection_text, now=now, taken=taken)
                except Exception as e:  # noqa: BLE001 —— clause_ai.ClauseAIError 等：记 error，停止后续（同 drafter）
                    conv = {'status': 'error', 'code': type(e).__name__, 'at': _iso(now)}
                    summary['stopped'] = str(e)[:200]
                    summary['conversions'][cid] = conv
                    log('[from-review] 中止：%s' % e)
                    break
                finally:
                    ex = None          # 片段只在内存里用一次
                summary['calls'] += 1
                summary['cost_usd'] += cost
        summary['conversions'][cid] = conv
        if conv['status'] == 'drafted':
            summary['written'].append(conv['draft'])
        elif conv['status'] in ('invalid', 'privacy-rejected'):
            summary['invalid'].append({'slug': 'review:%s' % cid, 'target': 'review:%s' % cid,
                                       'problems': ['%s %s' % (conv['status'], conv.get('code') or conv.get('findings'))]})
        elif conv['status'] in ('skipped', 'void'):
            summary['skipped'].append({'target': 'review:%s' % cid, 'code': conv.get('code'),
                                       'reason': '过了保留期，作废' if conv['status'] == 'void' else 'AI 判为写不成离线用例'})
        log('[from-review] 候选 %s：%s %s' % (cid, conv['status'], conv.get('draft') or conv.get('code') or ''))
    summary['cost_usd'] = round(summary['cost_usd'], 6)
    write_back(data_dir, name, path, summary['conversions'])
    return summary


def write_back(data_dir, name, path, conversions):
    """把 conversion 写回复盘结果：与待审页写回、review 重跑同一把锁，锁内重读再改，自检不过不写。"""
    if not conversions:
        return
    with pending._locked(data_dir, 'review-%s-%s' % (name, path.stem), err=CandidateError):
        rec = json.loads(path.read_text(encoding='utf-8'))
        for c in rec.get('candidates') or []:
            if isinstance(c, dict) and c.get('id') in conversions:
                c['conversion'] = conversions[c['id']]
        try:
            review._self_check(name, rec)
        except review.ReviewError as e:
            raise CandidateError(str(e))
        review._write(path, record.scrub_home(rec))


# ---------------- 命令行 ----------------

STATUS_TEXT = {'drafted': '已写进草稿区', 'void': '作废（过了保留期）', 'skipped': 'AI 判为写不成离线用例',
               'privacy-rejected': '隐私自检不过，未写', 'invalid': '结构不合格，未写', 'error': 'AI 调用失败'}


def main(args, data_dir, *, ai=None, injection_text=None):
    from . import drafter
    model = args.model or drafter.DEFAULT_MODEL
    ai = ai or replay.lazy_ai(SYSTEM_PROMPT)
    try:
        summary = run(data_dir, args.name, date=getattr(args, 'date', None), ai=ai, model=model,
                      injection_text=injection_text)
    except (CandidateError, registry.RegistryError) as e:
        print('错误：%s' % e, file=sys.stderr)
        return 2
    conv = summary['conversions']
    print('复盘候选转草稿（%s）：处理 %d 个；AI 调用 %d 次，花费（标价估算）$%.4f' % (
        summary['review_date'], len(conv), summary['calls'], summary['cost_usd']))
    for cid, c in sorted(conv.items()):
        extra = c.get('draft') or c.get('code') or ''
        if c.get('findings'):
            extra = '、'.join('%s×%d' % kv for kv in c['findings'].items())
        print('  %s：%s %s' % (cid, STATUS_TEXT.get(c['status'], c['status']), extra))
    stopped = drafter.STOPPED_EXIT if summary['stopped'] else 0
    if args.no_page or not summary['written']:
        return stopped
    run_dir, page, cls = drafts.create_batch(data_dir, args.name, drafting=summary)
    if page is None:
        print('没有可审的草稿')
        return stopped
    drafts._print_page(run_dir, page, data_dir, args.name)
    return stopped
