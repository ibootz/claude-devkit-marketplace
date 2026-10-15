"""回放会话：合成 history_file、compact 之后的回放用例、回放转录清理（票 13，spec「2.3 用例从哪来」compact 段，设计票 19）。

一、history_file（设计票 19 实测，Claude Code 2.1.300）：就是会话转录 jsonl，eval 原样作 `--resume <路径>` 传给子会话。
   每条记录最少要 type、uuid、parentUuid（首条 null）、sessionId、timestamp、isSidechain:false、message。
   compact 版以 `system/compact_boundary` 开头，再接一条 `isCompactSummary:true` 的 user 摘要。
   约束：配了 history_file 必须有被测 prompt；文件在用例目录内、是普通单链接文件。
   回放子会话的转录写进**用例目录**的 `<历史 sessionId>.jsonl` 与同名目录，所以历史文件本身不能叫这个名字
   （HISTORY_FILE 固定为 history.jsonl，sessionId 是 uuid）。

二、compact 之后的回放用例（`drafts compact`）：每个注入插件 ≤ MAX_PER_PLUGIN 个。条款直接从 clauses.json 的未退役条款里挑
   （不经复盘候选的 clause_ids，票 13 Comments「审查 C」），挑法见 select_clauses。每例 = 现成的普通用例（evals/ 优先，
   其次未打回的草稿）原样拷过来 + 合成历史（compact_boundary + 模板化摘要 + TAIL 两轮尾巴）；该条款还没有普通用例时
   由 AI 起草被测 prompt 与 grader（复用 drafter），再套同一份合成历史。
   合成历史不放被测插件的注入文本，否则「不装」臂也读得到：写盘前用 injection_hits 对照被测插件当前的注入文字查一遍，
   命中即整条不写。

三、清理：purge_transcripts 把臂组装目录里回放用例目录下的 `<sessionId>.jsonl` 与同名目录移到本臂的 trace 目录
   （用户级数据目录，不进被测仓；compare._run_arm 跑完每臂即调，--keep-assembly 留下的组装目录里也就没有它们）。
   回放子会话的转录不在沙箱的 projects/ 下，注入核验对回放用例报「找不到子会话转录」（票 13 Comments 已知缺口）。
"""
import json
import re
import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import arms, casefiles, clauses, drafts, registry

HISTORY_FILE = 'history.jsonl'
MAX_PER_PLUGIN = 3
TAG = 'compact-replay'
CATEGORY = 'compact-replay'
SOURCE = 'compact-replay'
SUMMARY_TEMPLATE_ID = 'compact-summary-v1'
OVERLAP_CHARS = 20          # 合成历史与注入文字逐字重合到这么长就算「放了注入文本」
_T0 = datetime(2026, 1, 5, 9, 0, 0, tzinfo=timezone.utc)
_NS = uuid.UUID('6f1c2d3e-4b5a-4c6d-8e7f-90a1b2c3d4e5')     # 合成记录 uuid 的命名空间（uuid5，结果可复现）

# 模板化 compact 摘要：虚构的开源小工具「pagelint」（静态站点链接检查器）。与任何插件的规矩无关，不写工作方法与纪律。
SUMMARY = '''This session is being continued from a previous conversation that ran out of context. The summary below covers the earlier portion of the conversation.

Summary:
1. 主要请求与意图：
   用户在维护一个虚构的开源命令行工具 pagelint（Python 3.12），它扫描静态站点生成的 HTML，报告失效的站内链接与缺失的图片。本段对话里用户先后提了三件事：
   - 把链接抽取从正则改成标准库 html.parser，避免漏掉跨行的 <a> 标签；
   - 新增 `pagelint check --base-url` 参数，让以 / 开头的绝对路径按站点根解析；
   - 报告输出支持 `--format json`，字段为 page、href、status、line。
   用户说过：不引入第三方依赖；测试用 pytest；输出顺序按页面路径排序，便于 diff。

2. 关键技术概念：
   - `html.parser.HTMLParser` 的 handle_starttag 回调，按 (tag, attrs) 收集 href 与 src。
   - `urllib.parse.urljoin` 解析相对链接；`posixpath.normpath` 去掉 ./ 与 ../。
   - 站内链接只查文件是否存在，不发网络请求；片段（#anchor）只查目标页里有没有同名 id。

3. 文件与代码段：
   - `pagelint/extract.py`（改写）：`LinkCollector(HTMLParser)` 记录每个链接的行号，`collect(path)` 返回 [(href, line)]。
   - `pagelint/resolve.py`（新建）：`resolve(page, href, base_url)` 返回站点内的相对文件路径或 None（外链）。
   - `pagelint/report.py`（改动）：`render_text` 与新增的 `render_json`，两者共用排序函数 `_ordered`。
   - `tests/test_resolve.py`（新建）：覆盖相对路径、绝对路径、带 base-url、带片段四种情况，全部通过。

4. 错误与修复：
   - 初版 urljoin 把 `docs/` 页面里的 `../img/a.png` 解析到了站点根之外，改为先 normpath 再判断是否越界，越界记为失效。
   - JSON 输出里 line 原本是字符串，已改为整数，并补了一条测试。

5. 待办与当前状态：
   - 已完成：解析器替换、--base-url、--format json，`pytest -q` 共 31 个用例通过。
   - 未开始：给 CHANGELOG 补一段说明；考虑是否把 resolve 的越界判断做成可配置。
'''

TAIL = (
    ('CHANGELOG 先不写，等我决定版本号。顺便问一下，--format json 的输出现在是一行一个对象还是一个大数组？',
     '现在是一个大数组：`render_json` 先把全部结果按页面路径排好序，再一次性 `json.dumps(..., ensure_ascii=False, indent=2)` 输出。'
     '如果你打算把结果接到 jq 之类的流式工具里，改成一行一个对象（JSON Lines）也很简单，只需要把 dumps 放进循环里，'
     '测试里比对整个数组的那条断言要相应改成逐行解析。'),
    ('先保持数组吧。另外越界的链接现在在报告里显示成什么？',
     '越界的链接记为失效，status 写 `outside-site`，和找不到文件的 `missing` 区分开；文本报告里两者都会列出，'
     'JSON 报告里通过 status 字段区分。这样用户能一眼看出是写错了相对路径还是真的少了文件。'),
)


class ReplayError(Exception):
    pass


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ---------------- 合成历史 ----------------

def build_history(seed, turns, *, compact=True, summary=SUMMARY):
    """返回 (sessionId, 记录列表)。turns：[(用户, 助手)]，全部是合成文字。seed 决定 uuid，同一 seed 结果可复现。"""
    sid = str(uuid.uuid5(_NS, 'session:%s' % seed))
    recs, parent, tick = [], None, [0]

    def common():
        tick[0] += 1
        u = str(uuid.uuid5(_NS, '%s:%d' % (seed, tick[0])))
        return {'parentUuid': parent, 'isSidechain': False, 'uuid': u, 'sessionId': sid,
                'timestamp': (_T0 + timedelta(seconds=7 * tick[0])).strftime('%Y-%m-%dT%H:%M:%S.000Z')}

    if compact:
        b = common()
        b.update({'type': 'system', 'subtype': 'compact_boundary', 'content': 'Conversation compacted', 'level': 'info',
                  'compactMetadata': {'trigger': 'auto', 'preTokens': 160000, 'postTokens': 8000}})
        recs.append(b)
        parent = b['uuid']
        s = common()
        s.update({'type': 'user', 'isCompactSummary': True, 'isVisibleInTranscriptOnly': True,
                  'message': {'role': 'user', 'content': summary}})
        recs.append(s)
        parent = s['uuid']
    for q, a in turns:
        u = common()
        u.update({'type': 'user', 'message': {'role': 'user', 'content': q}})
        recs.append(u)
        parent = u['uuid']
        r = common()
        r.update({'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': a}]}})
        recs.append(r)
        parent = r['uuid']
    return sid, recs


def history_text(recs):
    return ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in recs)


def message_texts(recs):
    """历史里给模型看的文字（摘要、用户与助手的话）。"""
    out = []
    for r in recs:
        c = (r.get('message') or {}).get('content')
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            out += [b.get('text') or '' for b in c if isinstance(b, dict)]
    return out


def history_session_id(path):
    try:
        with open(str(path), encoding='utf-8') as f:
            for line in f:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if isinstance(o, dict) and o.get('sessionId'):
                    return str(o['sessionId'])
    except OSError:
        return None
    return None


# ---------------- 注入文本检查 ----------------

def _norm(text):
    return re.sub(r'\s+', '', text or '')


def injection_hits(texts, injection_text, min_chars=OVERLAP_CHARS):
    """合成历史（texts）与注入文字逐字重合（去空白后）≥ min_chars 的片段数。只回数量，不回原文。"""
    inj = _norm(injection_text)
    if len(inj) < min_chars:
        return 0
    windows = {inj[i:i + min_chars] for i in range(len(inj) - min_chars + 1)}
    hits = 0
    for t in texts:
        s = _norm(t)
        i = 0
        while i + min_chars <= len(s):
            if s[i:i + min_chars] in windows:
                hits += 1
                i += min_chars
            else:
                i += 1
    return hits


def default_injection_text(plugin_dir, repo, name, *, env=None):
    """被测插件当前的注入文字：真实 HOME、空临时目录下执行常驻 hook（同条款清单的取法）；取不到时退回清单快照。"""
    try:
        cap = clauses.capture_injection(plugin_dir, env=env)
        if cap.text.strip():
            return cap.text
    except Exception:  # noqa: BLE001 —— 取不到现文字时用快照兜底，快照也没有就返回空（调用方据此拒绝写）
        pass
    snap = clauses.evals_root(repo, name) / clauses.SNAPSHOT_FILE
    return snap.read_text(encoding='utf-8') if snap.is_file() else ''


# ---------------- 回放转录清理 ----------------

def _history_rel(case_dir):
    y = Path(case_dir) / 'case.yaml'
    if not y.is_file():
        return None
    m = re.search(r'^\s*history_file\s*:\s*[\'"]?([^\'"\s#]+)', y.read_text(encoding='utf-8'), re.M)
    return m.group(1) if m else None


def purge_transcripts(arm_dir, keep_dir=None):
    """清掉 <臂目录>/evals/ 下回放用例目录里的 `<历史 sessionId>.jsonl` 与同名目录。keep_dir 给了就移到
    keep_dir/<用例>/ 下留作排查（compare 传本臂的 trace 目录，在用户级数据目录里，不进被测仓），否则直接删。
    返回清掉的相对路径。"""
    evals = Path(arm_dir) / 'evals'
    removed = []
    for c in arms.discover_cases(evals):
        d = evals / c
        rel = _history_rel(d)
        sid = history_session_id(d / rel) if rel else None
        if not sid or not re.match(r'^[A-Za-z0-9-]{8,64}$', sid):
            continue
        for p in (d / ('%s.jsonl' % sid), d / sid):
            if not (p.is_dir() or p.exists()):
                continue
            if keep_dir is not None:
                dest = Path(keep_dir) / c / p.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    shutil.rmtree(str(dest), ignore_errors=True) if dest.is_dir() else dest.unlink()
                shutil.move(str(p), str(dest))
            elif p.is_dir():
                shutil.rmtree(str(p), ignore_errors=True)
            else:
                p.unlink()
            removed.append('%s/%s' % (c, p.name))
    return removed


# ---------------- 挑条款 ----------------

def _cases_under(root):
    root = Path(root)
    return [(c, root / c) for c in arms.discover_cases(root)]


def existing_compact(repo, name, plugin_dir, *, skip_rejected_for=None):
    """已有的 compact 回放用例（evals/ 与草稿区，含打回的）：{用例键: 条款 id 列表}。
    skip_rejected_for（--clauses 点名的条款 id 集合）：挂着这些条款、已打回的回放草稿不算（C 批定稿 4）。"""
    out = {}
    for c, d in _cases_under(Path(plugin_dir) / 'evals'):
        tags = clauses.case_tags(d)
        if TAG in tags:
            out['evals/' + c] = drafts.clause_ids(tags)
    for d in drafts.list_drafts(repo, name):
        if TAG in d.tags or d.meta.get('source') == SOURCE:
            ids = drafts.clause_ids(d.tags)
            if skip_rejected_for and d.status == drafts.STATUS_REJECTED and set(ids) & set(skip_rejected_for):
                continue
            out['drafts/' + d.case] = ids
    return out


def _rejected_keys(repo, name):
    return {'drafts/' + d.case for d in drafts.list_drafts(repo, name)
            if d.status == drafts.STATUS_REJECTED and (TAG in d.tags or d.meta.get('source') == SOURCE)}


def _scored_ok(case_dir):
    gdir = Path(case_dir) / 'graders'
    for g in sorted(gdir.glob('*.md')) if gdir.is_dir() else []:
        fm, _ = casefiles.frontmatter(g.read_text(encoding='utf-8'))
        keys = dict((ln.split(':', 1)[0].strip(), ln.split(':', 1)[1].strip().strip('\'"'))
                    for ln in (fm or '').splitlines() if ':' in ln and not ln.startswith((' ', '\t')))
        if keys.get('type') in casefiles.GRADER_TYPES and casefiles.scored(
                {'type': keys.get('type'), 'tool': keys.get('tool'), 'arm': keys.get('arm')}):
            return True
    return False


def base_cases(repo, name, plugin_dir):
    """可作 compact 版底本的普通用例：{条款 id: [(用例键, 目录, 草稿元数据)]}，evals/ 在前、草稿在后。
    底本要 eval 加载得了、有计分的规则 grader、自己不是回放用例（没有 history_file）。"""
    out = {}

    def add(key, d, meta):
        tags = clauses.case_tags(d)
        if TAG in tags or 'review-replay' in tags or _history_rel(d) or casefiles.check_case_dir(d) or not _scored_ok(d):
            return
        for cid in drafts.clause_ids(tags):
            out.setdefault(cid, []).append((key, d, meta))

    for c, d in _cases_under(Path(plugin_dir) / 'evals'):
        add('evals/' + c, d, {})
    for dr in drafts.list_drafts(repo, name):
        if dr.status == drafts.STATUS_OPEN and not dr.meta.get('_corrupt') and dr.category in (
                'discipline', 'induced', 'style'):
            add('drafts/' + dr.case, dr.path, dr.meta)
    return out


def select_clauses(repo, name, plugin_dir, *, only=None, limit=MAX_PER_PLUGIN):
    """挑做 compact 版的高风险条款。返回 (选中 [{id, criterion, events, base, reasons}], 说明清单)。
    排序（暂定口径，票 13 Comments）：1 已证明有差（离线对照或底本自带实测证据）→ 2 复盘命中 → 3 事件含 SessionStart
    （真实长会话里它只在开头与 compact / resume 时注入一次，之后各轮不再重注，最容易被稀释；UserPromptSubmit 类每轮都贴着
    用户发言重注）→ 4 已有普通用例可作底本（不花钱起草）→ 条款号。每个插件合计 ≤ MAX_PER_PLUGIN 个（evals/ 与草稿区里已有的、含打回的都算）。
    only（--clauses 点名）时，挂着点名条款、已打回的回放草稿不算覆盖、也不占名额，会重写（C 批定稿 4，同 B 批定稿 3）；
    不点名时打回的仍算覆盖。"""
    lst = clauses.load_list(repo, name)
    if not lst:
        raise ReplayError('插件 %s 还没有条款清单（plugin-evals/%s/%s）：先跑 `clauses %s`' % (
            name, name, clauses.LIST_FILE, name))
    have = existing_compact(repo, name, plugin_dir, skip_rejected_for=only)
    covered = {cid for ids in have.values() for cid in ids}
    quota = MAX_PER_PLUGIN - len(have)
    notes = []
    if only is not None:
        dup = sorted(set(only) & covered)
        if dup:
            notes.append('点名的条款已有 compact 回放用例（未打回），不重做：%s' % '、'.join(dup))
    if quota <= 0:
        rej = sorted(_rejected_keys(repo, name) & set(have))
        hint = '。删除已打回的回放草稿目录可腾出名额（%s）' % (
            '已打回的 %d 个：%s；也可用 --clauses 点名重写它们的条款' % (len(rej), '、'.join(rej)) if rej
            else '目前没有已打回的')
        return [], notes + ['已有 %d 个 compact 回放用例（上限 %d）：%s%s' % (
            len(have), MAX_PER_PLUGIN, '、'.join(sorted(have)), hint)]
    proven, hit = drafts.evidence(repo, name, plugin_dir)
    bases = base_cases(repo, name, plugin_dir)
    for cid, items in bases.items():
        if any((m or {}).get('evidence', {}).get('proven_delta') for _, _, m in items):
            proven = proven | {cid}
    active = [c for c in lst.get('clauses') or [] if c.get('status') == 'active']
    if only is not None:
        unknown = sorted(set(only) - {c['id'] for c in active})
        if unknown:
            notes.append('不是有效条款，跳过：%s' % '、'.join(unknown))
    pool = []
    for c in active:
        cid = c['id']
        if (only is not None and cid not in only) or cid in covered:
            continue
        ev = c.get('events') or []
        reasons = []
        if cid in proven:
            reasons.append('已证明有差')
        if cid in hit:
            reasons.append('复盘命中')
        if 'SessionStart' in ev:
            reasons.append('SessionStart 注入（长会话里不再重注）' if 'UserPromptSubmit' not in ev else '含 SessionStart 注入')
        if cid in bases:
            reasons.append('有现成普通用例作底本')
        key = (cid not in proven, cid not in hit, 'SessionStart' not in ev, cid not in bases, clauses._id_no(cid))
        pool.append((key, {'id': cid, 'criterion': c.get('criterion'), 'events': ev,
                           'base': (bases.get(cid) or [None])[0], 'reasons': reasons}))
    pool.sort(key=lambda kv: kv[0])
    n = max(0, min(quota, limit))
    return [x for _, x in pool[:n]], notes


# ---------------- 写草稿 ----------------

def _slug(base, taken):
    s = re.sub(r'[^a-z0-9-]+', '-', ('compact-%s' % base).lower()).strip('-')[:56]
    out, k = s, 2
    while out in taken:
        out, k = '%s-%d' % (s, k), k + 1
    taken.add(out)
    return out


def _set_fm_name(text, slug):
    fm, body = casefiles.frontmatter(text)
    if fm is None:
        return '---\nname: %s\n---\n%s' % (slug, text)
    lines = [ln for ln in fm.split('\n')]
    if any(re.match(r'^name\s*:', ln) for ln in lines):
        lines = ['name: %s' % slug if re.match(r'^name\s*:', ln) else ln for ln in lines]
    else:
        lines.insert(0, 'name: %s' % slug)
    return '---\n%s\n---\n%s' % ('\n'.join(lines), body)


def case_yaml_with_history(text, slug, history=HISTORY_FILE):
    """在已有 case.yaml（或空）里写上 name 与 context.history_file，其余行（如 scaffold_script）原样保留。"""
    lines = [ln for ln in (text or '').rstrip('\n').split('\n') if ln.strip()] if text else []
    lines = [ln for ln in lines if not re.match(r'^\s*history_file\s*:', ln)]
    if not any(re.match(r'^schema_version\s*:', ln) for ln in lines):
        lines.insert(0, 'schema_version: "1.1"')
    if any(re.match(r'^name\s*:', ln) for ln in lines):
        lines = ['name: %s' % slug if re.match(r'^name\s*:', ln) else ln for ln in lines]
    else:
        lines.insert(1, 'name: %s' % slug)
    ctx = next((i for i, ln in enumerate(lines) if re.match(r'^context\s*:\s*$', ln)), None)
    if ctx is None:
        lines += ['context:', '  history_file: %s' % history]
    else:
        lines.insert(ctx + 1, '  history_file: %s' % history)
    return '\n'.join(lines) + '\n'


def write_from_base(dest, base_dir, slug, cid, hist_text):
    """把底本用例拷成回放用例：去掉 draft.json，改 name、tags，加 history.jsonl 与 case.yaml 的 history_file。"""
    base_dir = Path(base_dir)

    def ignore(dirpath, names):
        return [n for n in names if Path(dirpath) == base_dir and (n == drafts.META_FILE or n.endswith('.jsonl'))]
    arms.copy_tree(base_dir, dest, ignore=ignore)
    p = dest / 'prompt.md'
    if p.is_file():
        p.write_text(_set_fm_name(p.read_text(encoding='utf-8'), slug), encoding='utf-8')
    y = dest / 'case.yaml'
    y.write_text(case_yaml_with_history(y.read_text(encoding='utf-8') if y.is_file() else '', slug),
                 encoding='utf-8')
    (dest / HISTORY_FILE).write_text(hist_text, encoding='utf-8')
    casefiles.set_tags(dest, [TAG, cid])
    return dest


def _ai_base_spec(name, c, ai, model, slug):
    """该条款没有普通用例：让 AI 按条款意图起草被测 prompt 与 grader（复用 drafter 的提示词与校验）。返回 (spec|None, 说明, meta)。"""
    from . import drafter
    g = {'key': 'clause:%s' % c['id'], 'kind': 'clause', 'clause': c['id'], 'criterion': c['criterion'], 'need': 1}
    obj, meta = ai(drafter.build_prompt(name, [g]), drafter.CASE_SCHEMA, model)
    sk = [s for s in obj.get('skipped') or [] if s.get('target') == g['key']]
    cases = [x for x in obj.get('cases') or [] if x.get('target') == g['key']]
    if not cases:
        return None, '起草者判为离线写不出用例（%s）' % ((sk[0].get('code') if sk else None) or '没有返回用例'), meta
    spec = drafter._spec(cases[0], g, slug)
    spec['tags'] = [TAG, c['id']]
    problems = casefiles.validate_spec(spec)
    if problems:
        return None, '起草结果不合格：%s' % '；'.join(problems), meta
    spec['intent'] = cases[0].get('intent')
    return spec, None, meta


def generate(data_dir, name, *, only=None, limit=MAX_PER_PLUGIN, ai=None, model=None, injection_text=None, now=None,
             log=None, env=None):
    """生成 compact 回放草稿。返回摘要 dict（drafts.create_batch 的 drafting 同形，另有 compact 段）。"""
    log = log or (lambda msg: print(msg, file=sys.stderr))
    now = now or datetime.now(timezone.utc)
    entry = registry.lookup(data_dir, name)
    repo, plugin_dir = Path(entry['repo']), registry.plugin_dir(entry)
    chosen, notes = select_clauses(repo, name, plugin_dir, only=only, limit=limit)
    for n in notes:
        log('[compact] %s' % n)
    summary = {'model': model, 'calls': 0, 'cost_usd': 0.0, 'targets': ['compact:%s' % c['id'] for c in chosen],
               'written': [], 'invalid': [], 'skipped': [], 'linked': [], 'stopped': None,
               'compact': {'summary_template': SUMMARY_TEMPLATE_ID, 'tail_turns': len(TAIL), 'chosen': [
                   {'clause': c['id'], 'base': c['base'][0] if c['base'] else None, 'reasons': c['reasons']}
                   for c in chosen], 'injection_hits': {}}}
    if not chosen:
        return summary
    inj = injection_text if injection_text is not None else default_injection_text(plugin_dir, repo, name, env=env)
    if not inj.strip():
        raise ReplayError('取不到被测插件 %s 的注入文字（hook 没输出、清单也没有快照），无法核对合成历史里有没有注入文本'
                          % name)
    root = drafts.drafts_root(repo, name)
    taken = {p.name for p in root.iterdir()} if root.is_dir() else set()
    evals = Path(plugin_dir) / 'evals'
    taken |= {p.name for p in evals.iterdir()} if evals.is_dir() else set()
    for c in chosen:
        base = c['base']
        slug = _slug(Path(base[0]).name if base else c['id'].lower(), taken)
        sid, recs = build_history(slug, TAIL)
        hits = injection_hits(message_texts(recs), inj)
        summary['compact']['injection_hits'][slug] = hits
        if hits:
            summary['invalid'].append({'slug': slug, 'target': 'compact:%s' % c['id'],
                                       'problems': ['合成历史里有 %d 处与被测插件注入文字逐字重合，不写' % hits]})
            continue
        intent = None
        if base:
            dest = root / slug
            write_from_base(dest, base[1], slug, c['id'], history_text(recs))
            intent = (base[2] or {}).get('intent')
        else:
            if ai is None:
                summary['skipped'].append({'target': 'compact:%s' % c['id'], 'code': 'no-base-case',
                                           'reason': '该条款还没有普通用例可作底本，且本次没有调 AI 起草'})
                continue
            try:
                spec, why, meta = _ai_base_spec(name, c, ai, model, slug)
            except Exception as e:  # noqa: BLE001 —— clause_ai.ClauseAIError 等：已写的照常保留，停止后续
                summary['stopped'] = str(e)
                log('[compact] 中止：%s' % e)
                break
            summary['calls'] += 1
            summary['cost_usd'] += (meta or {}).get('cost_usd') or 0
            if spec is None:
                summary['skipped'].append({'target': 'compact:%s' % c['id'], 'code': 'ai-skipped', 'reason': why})
                continue
            spec['history_file'] = HISTORY_FILE
            spec['history_text'] = history_text(recs)
            intent = spec.pop('intent', None)
            dest = root / slug
            casefiles.write_case(dest, spec)
        problems = casefiles.check_case_dir(dest)
        if problems:
            shutil.rmtree(str(dest), ignore_errors=True)
            summary['invalid'].append({'slug': slug, 'target': 'compact:%s' % c['id'], 'problems': problems})
            continue
        meta = {'schema_version': drafts.SCHEMA_VERSION, 'case': slug, 'source': SOURCE, 'category': CATEGORY,
                'clauses': [c['id']], 'clause_intent': c['criterion'],
                'intent': 'compact 之后（长历史稀释）仍遵守：%s' % (intent or c['criterion']),
                'target': 'compact:%s' % c['id'], 'created_at': _iso(now),
                'created_by': {'model': model} if not base else {'by': 'compact 回放生成（底本拷贝，未调 AI）'},
                'status': drafts.STATUS_OPEN,
                'replay': {'base_case': base[0] if base else None, 'summary_template': SUMMARY_TEMPLATE_ID,
                           'tail_turns': len(TAIL), 'history_file': HISTORY_FILE, 'history_session_id': sid,
                           'injection_overlap_chars': OVERLAP_CHARS, 'injection_hits': 0,
                           'selection_reasons': c['reasons']}}
        drafts.write_meta(dest, meta)
        summary['written'].append(slug)
        log('[compact] 写进草稿区 %s（条款 %s，%s）' % (slug, c['id'], '底本 %s' % base[0] if base else 'AI 起草底本'))
    summary['cost_usd'] = round(summary['cost_usd'], 6)
    return summary


# ---------------- 命令行 ----------------

def lazy_ai(system_prompt):
    """第一次真要调 AI 时才找 claude 并建调用器：都有底本 / 都作废时不需要 claude。"""
    holder = {}

    def call(prompt, schema, model):
        if 'ai' not in holder:
            from . import clause_ai, evalrun
            import tempfile
            holder['ai'] = clause_ai.claude_caller(evalrun.resolve_claude(), env=evalrun.child_env(None),
                                                   cwd=tempfile.gettempdir(), system_prompt=system_prompt)
        return holder['ai'](prompt, schema, model)
    return call


def main(args, data_dir, *, ai=None, injection_text=None):
    from . import drafter
    only = {x.strip() for x in args.clauses.split(',') if x.strip()} if getattr(args, 'clauses', None) else None
    model = args.model or drafter.DEFAULT_MODEL
    ai = ai or lazy_ai(drafter.SYSTEM_PROMPT)
    limit = MAX_PER_PLUGIN if args.limit is None else args.limit
    try:
        summary = generate(data_dir, args.name, only=only, limit=limit, ai=ai, model=model,
                           injection_text=injection_text)
    except (ReplayError, registry.RegistryError) as e:
        print('错误：%s' % e, file=sys.stderr)
        return 2
    cp = summary['compact']
    print('compact 回放：选中 %d 条条款，写进草稿区 %d 个，不合格 %d 个，跳过 %d 条；AI 调用 %d 次，花费（标价估算）$%.4f' % (
        len(cp['chosen']), len(summary['written']), len(summary['invalid']), len(summary['skipped']),
        summary['calls'], summary['cost_usd']))
    for c in cp['chosen']:
        print('  %s：%s；底本 %s' % (c['clause'], '、'.join(c['reasons']) or '—', c['base'] or '无（AI 起草）'))
    print('  合成历史与注入文字逐字重合（≥%d 字）的片段数：%s' % (
        OVERLAP_CHARS, '、'.join('%s=%d' % kv for kv in sorted(cp['injection_hits'].items())) or '—'))
    for s in summary['skipped']:
        print('  跳过 %s（%s）：%s' % (s['target'], s['code'], s['reason']))
    for s in summary['invalid']:
        print('  不合格 %s：%s' % (s['slug'], '；'.join(s['problems'])))
    stopped = 2 if summary['stopped'] else 0
    if args.no_page:
        return stopped
    run_dir, page, cls = drafts.create_batch(data_dir, args.name, drafting=summary)
    if page is None:
        print('没有可审的草稿')
        return stopped
    drafts._print_page(run_dir, page, data_dir, args.name)
    return stopped
