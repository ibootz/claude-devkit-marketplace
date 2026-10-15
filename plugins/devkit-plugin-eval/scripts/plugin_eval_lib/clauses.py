"""条款清单的生命周期（票 10，spec「2.2 离线对照」第 2 步、「2.3 用例从哪来」条款清单段，设计票 20）。

一、注入文本指纹（capture_injection）
- 执行被测插件全部常驻注入 hook（injection.RESIDENT_EVENTS：SessionStart / UserPromptSubmit / SubagentStart），
  执行入口复用 injection.load_hook_specs 与 injection.run_hook：真实 HOME、空临时 cwd、插件副本（不写脏工作区）。
  不复用前置检查的冒烟（冒烟用空 HOME，asdf shim 下取不到文字）。
- 取 Claude Code 实际会注入的文字（run_hook 的 text），逐条归一化（normalize_text），按「事件 + 文字」去重排序后
  拼成快照文本，sha256 即指纹。只认文字：改脚本名、改 matcher、改不注入的 hook 都不改指纹。
- 每条 hook 执行两次：归一化后两次仍不同（有没归一掉的易变内容），或有 hook 失败 / 超时，本次指纹判「不可靠」，
  不据此判过期、不重抽，报告标出。退出 0 却没输出的是条件注入（依赖项目目录或会话状态），计数记为残余不确定。

二、清单与提案（落在被测仓 plugin-evals/<插件>/ 下，入库）
- LIST_FILE（clauses.json）：已确认的条款清单。每条 {id, criterion, events, status=active|retired, …}；
  退役条款留在清单里，写 retire_reason 与 replaced_by。记抽取时的注入文本指纹 injection_fingerprint。
- SNAPSHOT_FILE（clauses-injection.txt）：与该指纹对应的归一化注入文字，增量重抽时与新文字做 diff。
- REHANG_FILE（clause-rehang.json）：确认退役后，挂在退役 id 上的用例与改挂建议（票 11 的草稿区据此把用例退回 drafts/）。
- 每次运行目录里：CHECK_FILE（clause-check.json，本步结论，run.json 的 clause_check 照抄它）；有变更时另有
  PROPOSAL_FILE（clause-proposal.json，清单变更）与 RUN_SNAPSHOT_FILE（clause-injection.txt，新文字）。

三、过期与增量重抽（check_for_run）：清单记的指纹与当前相同 → 不重抽、不产生待审项。不同或没有清单 → 先找能复用的
  未裁定提案（同一份旧清单、同一个新指纹，免得每次对照都重新调 AI、每次换一批 id），找不到才调 AI：
  没有清单时整份抽取，有清单时 AI 只读旧清单加新旧文字的 diff，产出新增 / 改写 / 退役。提案进待审页算 1 项
  （ItemType key=clause-list，always=True）。确认前对照照跑，报告标「条款清单待确认」，新条款列「无用例」。

四、id：程序分配 C001、C002…，取清单与 runs/*/clause-proposal.json 里出现过的最大号加一，所以退役 id、
  被打回的提案用过的 id 都不再分配。id 绑判定标准：改写保留 id；判定标准变了、拆分、合并一律「旧 id 退役 + 新 id」。
"""
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import arms, clause_ai, evalrun, injection, pending, preflight, record, registry

LIST_FILE = 'clauses.json'
SNAPSHOT_FILE = 'clauses-injection.txt'
REHANG_FILE = 'clause-rehang.json'
CHECK_FILE = 'clause-check.json'
PROPOSAL_FILE = 'clause-proposal.json'
RUN_SNAPSHOT_FILE = 'clause-injection.txt'
SCHEMA_VERSION = 1
ID_PREFIX = 'C'
_ID_RE = re.compile(r'^%s(\d+)$' % ID_PREFIX)

STATUS_UP_TO_DATE = 'up-to-date'
STATUS_PENDING = 'pending-confirmation'
STATUS_NO_INJECTION = 'no-injection'
STATUS_UNRELIABLE = 'unreliable'
STATUS_AI_ERROR = 'ai-error'
STATUS_ERROR = 'error'
STATUS_CONFIRMED = 'confirmed'     # 待审页上确认后由 _apply 改写（decision 同时记下）
STATUS_REJECTED = 'rejected'       # 待审页上打回后由 _apply 改写；同一组（基线清单指纹、新指纹）的提案此后不再复用

# 易变内容归一化：按顺序替换，先长后短（日期时间先于日期、日期先于时刻）
_VOLATILE = (
    (re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b'), '<UUID>'),
    (re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?(?:\s?(?:Z|UTC|[+-]\d{2}:?\d{2}))?'),
     '<DATETIME>'),
    (re.compile(r'\d{4}年\d{1,2}月\d{1,2}日'), '<DATE>'),
    (re.compile(r'(?<![\d.])\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?![\d.])'), '<DATE>'),
    (re.compile(r'(?<![\d.:])\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?(?![\d:])'), '<TIME>'),
    (re.compile(r'(?<![\w.])1\d{9}(?:\d{3})?(?:\.\d+)?(?![\w.])'), '<EPOCH>'),
    (re.compile(r'(?<![0-9A-Za-z])[0-9a-f]{16,}(?![0-9A-Za-z])'), '<HEX>'),
)
NORMALIZATION = {
    'name': 'injection-text-v1',
    'execution': '真实 HOME、空临时 cwd、插件副本；常驻事件（SessionStart / UserPromptSubmit / SubagentStart）全部 hook，'
                 '每条执行两次；PATH 与 eval 子进程相同（已去掉 asdf shims）',
    'rules': ['CRLF→LF，去行尾空白与首尾空行', '插件副本路径→${CLAUDE_PLUGIN_ROOT}，hook 临时目录→<HOOK_TMP>，家目录→~',
              'UUID→<UUID>，日期时间→<DATETIME>，日期→<DATE>，时刻→<TIME>，10/13 位 Unix 时间戳→<EPOCH>，'
              '16 位以上小写十六进制→<HEX>',
              '按「事件 + 文字」去重、按事件与文字排序后拼接；hook 的命令、matcher、顺序不进指纹'],
}


# ---------------- 一、注入文本指纹 ----------------

def _path_variants(p):
    p = str(p)
    out = {p, os.path.realpath(p)}
    for v in list(out):
        if v.startswith('/private/'):
            out.add(v[len('/private'):])
    return sorted(out, key=len, reverse=True)


def normalize_text(text, *, plugin_root=None, work_parent=None, home=None):
    """归一化一条 hook 的注入文字。plugin_root / work_parent 是本次执行用的插件副本与 hook 临时目录的父目录。"""
    s = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    if plugin_root:
        for v in _path_variants(plugin_root):
            s = s.replace(v, '${CLAUDE_PLUGIN_ROOT}')
    if work_parent:
        for v in _path_variants(work_parent):
            s = re.sub(re.escape(v) + r'[/\\]pe-hook-[^/\\\s]+', '<HOOK_TMP>', s)
            s = s.replace(v, '<TMP>')
    s = record.scrub_home(s, home=home)
    for pat, rep in _VOLATILE:
        s = pat.sub(rep, s)
    lines = [ln.rstrip() for ln in s.split('\n')]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)


def snapshot_text(sections):
    """sections：[(事件, 归一化文字)]，已去重排序。"""
    return ''.join('===== %s =====\n%s\n\n' % (ev, txt) for ev, txt in sections)


def text_fingerprint(snapshot):
    return 'sha256:' + hashlib.sha256(snapshot.encode('utf-8')).hexdigest()


@dataclass
class InjectionCapture:
    sections: list                      # [(事件, 归一化文字)]
    text: str                           # 快照文本（指纹的输入）
    fingerprint: str
    injecting: int = 0                  # 有注入文字的 hook 数
    silent: list = field(default_factory=list)     # 退出 0 却没输出：条件注入，残余不确定
    failed: list = field(default_factory=list)     # 超时或退出码非 0
    unstable: list = field(default_factory=list)   # 归一化后两次执行仍不同
    errors: list = field(default_factory=list)

    @property
    def reliable(self):
        return not (self.failed or self.unstable or self.errors)

    def summary(self):
        return {'injecting_hooks': self.injecting, 'silent_hooks': self.silent, 'failed_hooks': self.failed,
                'unstable_hooks': self.unstable}


def capture_injection(plugin_dir, *, env=None, tmp_parent=None, repeat=2, home=None):
    env = dict(os.environ if env is None else env)
    read_errors = []
    specs = [s for s in injection.load_hook_specs(plugin_dir, errors=read_errors)
             if s.event in injection.RESIDENT_EVENTS]
    errors = ['读 hook 声明失败：%s' % e for e in read_errors]
    work = Path(tempfile.mkdtemp(prefix='devkit-plugin-eval-clauses-', dir=tmp_parent)).resolve()
    seen, sections = set(), []
    cap = InjectionCapture([], '', '', errors=errors)
    try:
        copy = preflight._plugin_copy(Path(plugin_dir).resolve(), work / 'plugin')
        work_parent = work / 'hook'
        for spec in specs:
            outs = []
            for _ in range(max(1, repeat)):
                try:
                    r = injection.run_hook(spec, copy, env=env, work_parent=work_parent)
                except Exception as e:  # noqa: BLE001 —— 单条 hook 起不来不拖垮整份指纹，记成失败
                    cap.failed.append('%s（%s: %s）' % (spec.key, type(e).__name__, e))
                    outs = None
                    break
                # 与 injection.run_hook 同一口径：退出码非 0 但有输出仍算注入（Claude Code 照样注入），
                # 只有超时与退出码 2（阻断）算失败
                if r['timed_out'] or r['exit_code'] == injection.BLOCKING_EXIT_CODE:
                    cap.failed.append('%s（%s）' % (spec.key, '超时' if r['timed_out'] else '退出码 %s' % r['exit_code']))
                    outs = None
                    break
                outs.append(normalize_text(r['text'] or '', plugin_root=copy, work_parent=work_parent, home=home))
            if outs is None:
                continue
            if len(set(outs)) > 1:
                cap.unstable.append(spec.key)
                continue
            if not outs[0]:
                cap.silent.append(spec.key)
                continue
            cap.injecting += 1
            key = (spec.event, outs[0])
            if key not in seen:
                seen.add(key)
                sections.append(key)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    sections.sort(key=lambda kv: (injection.RESIDENT_EVENTS.index(kv[0]), kv[1]))
    cap.sections = sections
    cap.text = snapshot_text(sections)
    cap.fingerprint = text_fingerprint(cap.text)
    return cap


# ---------------- 二、清单读写与 id ----------------

def evals_root(repo, name):
    return Path(repo) / 'plugin-evals' / name


def _read_json(path):
    path = Path(path)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def load_list(repo, name):
    return _read_json(evals_root(repo, name) / LIST_FILE)


def list_fingerprint(lst):
    """清单指纹：只算条款本身（id、判定标准、事件、状态、退役原因与替代），不算时间戳与变更记录。"""
    if not lst:
        return None
    rows = sorted(([c.get('id'), c.get('criterion'), c.get('events') or [], c.get('status'),
                    c.get('retire_reason'), c.get('replaced_by') or []] for c in lst.get('clauses') or []),
                  key=lambda r: str(r[0]))
    blob = json.dumps({'injection_fingerprint': lst.get('injection_fingerprint'), 'clauses': rows},
                      ensure_ascii=False, sort_keys=True)
    return 'sha256:' + hashlib.sha256(blob.encode('utf-8')).hexdigest()


def active_ids(lst):
    return [c['id'] for c in (lst or {}).get('clauses') or [] if c.get('status') == 'active']


def retired_ids(lst):
    """退役 id：挂在它上面的金标样本停止参与评委校准（不删），用例退回草稿（票 09 / 11 消费）。"""
    return [c['id'] for c in (lst or {}).get('clauses') or [] if c.get('status') == 'retired']


def _id_no(cid):
    m = _ID_RE.match(str(cid or ''))
    return int(m.group(1)) if m else 0


def used_ids(repo, name):
    """清单与所有运行目录里的提案出现过的 id：分配新 id 时一律避开（含退役的、被打回的提案用过的）。"""
    root = evals_root(repo, name)
    ids = set()
    try:
        lst = _read_json(root / LIST_FILE)
    except (OSError, ValueError):
        lst = None      # 清单损坏：只按各运行的提案避让（损坏的清单由对照的出错分支报出）
    if isinstance(lst, dict):
        ids.update(c.get('id') for c in lst.get('clauses') or [] if isinstance(c, dict))
    runs = root / 'runs'
    if runs.is_dir():
        for d in runs.iterdir():
            p = d / PROPOSAL_FILE
            if p.is_file():
                try:
                    prop = json.loads(p.read_text(encoding='utf-8'))
                except ValueError:
                    continue
                ids.update(a.get('id') for a in prop.get('added') or [])
    return {i for i in ids if i}


def allocate_ids(repo, name, n):
    start = max([_id_no(i) for i in used_ids(repo, name)] + [0]) + 1
    return ['%s%03d' % (ID_PREFIX, k) for k in range(start, start + n)]


# ---------------- 用例归属（tags） ----------------

def _tags_from_text(text):
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r'^tags\s*:\s*(.*)$', ln)
        if not m:
            continue
        rest = m.group(1).split(' #')[0].strip()
        if rest.startswith('['):
            return [t.strip().strip('\'"') for t in rest.strip('[]').split(',') if t.strip()]
        if rest:
            return [rest.strip('\'"')]
        out = []
        for ln2 in lines[i + 1:]:
            m2 = re.match(r'^\s*-\s*(.+?)\s*$', ln2)
            if m2:
                out.append(m2.group(1).strip('\'"'))
            elif ln2.strip():
                break
        return out
    return []


def case_tags(case_dir):
    case_dir = Path(case_dir)
    yaml = case_dir / 'case.yaml'
    if yaml.is_file():
        return _tags_from_text(yaml.read_text(encoding='utf-8'))
    prompt = case_dir / 'prompt.md'
    if prompt.is_file():
        text = prompt.read_text(encoding='utf-8')
        m = re.match(r'^---\s*\n(.*?)\n---\s*(\n|$)', text, re.DOTALL)
        return _tags_from_text(m.group(1)) if m else []
    return []


def coverage(plugin_dir, cases=None):
    """{条款 id 或其它 tag: [用例]}，用例是 evals/ 下的相对目录。cases 缺省现扫。"""
    evals = Path(plugin_dir) / 'evals'
    cases = arms.discover_cases(evals) if cases is None else cases
    out = {}
    for c in cases:
        for t in case_tags(evals / c):
            out.setdefault(t, []).append(c)
    return out


def _draft_coverage(repo, name):
    drafts = evals_root(repo, name) / 'drafts'
    if not drafts.is_dir():
        return {}
    out = {}
    for c in arms.discover_cases(drafts):
        for t in case_tags(drafts / c):
            out.setdefault(t, []).append(c)
    return out


# ---------------- 三、提案 ----------------

class ClauseError(Exception):
    pass


def injection_diff(old_text, new_text):
    return '\n'.join(difflib.unified_diff((old_text or '').splitlines(), (new_text or '').splitlines(),
                                          'old-injection', 'new-injection', lineterm='', n=3))


def build_proposal(*, repo, name, lst, cap, ai, model, run_id, now):
    """调 AI 产出清单变更（没有清单时整份抽取），分配 id。AI 失败抛 clause_ai.ClauseAIError。"""
    model = model or clause_ai.DEFAULT_MODEL
    base = {'schema_version': SCHEMA_VERSION, 'plugin': name, 'created_in_run': run_id, 'created_at': _iso(now),
            'base_list_fingerprint': list_fingerprint(lst),
            'old_injection_fingerprint': (lst or {}).get('injection_fingerprint'),
            'new_injection_fingerprint': cap.fingerprint}
    if lst is None:
        obj, meta = ai(clause_ai.extract_prompt(name, cap.text), clause_ai.EXTRACT_SCHEMA, model)
        items = clause_ai.validate_extract(obj)
        ids = allocate_ids(repo, name, len(items))
        return dict(base, kind='extract', ai=meta, rewritten=[], retired=[],
                    added=[dict(id=i, **it) for i, it in zip(ids, items)])
    old_snapshot = evals_root(repo, name) / SNAPSHOT_FILE
    old_text = old_snapshot.read_text(encoding='utf-8') if old_snapshot.is_file() else ''
    diff = injection_diff(old_text, cap.text)
    obj, meta = ai(clause_ai.delta_prompt(name, lst.get('clauses') or [], diff), clause_ai.DELTA_SCHEMA, model)
    d = clause_ai.validate_delta(obj, lst.get('clauses') or [])
    ids = allocate_ids(repo, name, len(d['added']))
    refmap = {a['ref']: i for a, i in zip(d['added'], ids)}
    by_id = {c['id']: c for c in lst.get('clauses') or []}
    added = [{'id': refmap[a['ref']], 'criterion': a['criterion'], 'events': a['events'], 'ai_ref': a['ref']}
             for a in d['added']]
    rewritten = [dict(r, old_criterion=by_id[r['id']].get('criterion')) for r in d['rewritten']]
    def ref_to_id(text):   # 改挂建议里 AI 写的临时引用（N1）换成分配好的 id
        return re.sub(r'(?<![A-Za-z0-9])N\d+(?![0-9])', lambda m: refmap.get(m.group(0), m.group(0)), text or '')
    retired = [dict(r, replaced_by=[refmap.get(x, x) for x in r['replaced_by']], rehang_hint=ref_to_id(r['rehang_hint']),
                    old_criterion=by_id[r['id']].get('criterion')) for r in d['retired']]
    return dict(base, kind='delta', ai=dict(meta, old_snapshot_found=old_snapshot.is_file()),
                added=added, rewritten=rewritten, retired=retired)


def apply_proposal(lst, proposal, *, run_id, now):
    """按提案生成新清单（不落盘）。退役条款留在清单里，写原因与替代 id；改写保留 id、旧判定标准进 history。"""
    ts = _iso(now)
    new = json.loads(json.dumps(lst)) if lst else {'schema_version': SCHEMA_VERSION, 'plugin': proposal.get('plugin'),
                                                   'clauses': [], 'changelog': []}
    by_id = {c['id']: c for c in new['clauses']}
    for r in proposal.get('rewritten') or []:
        c = by_id[r['id']]
        c.setdefault('history', []).append({'criterion': c.get('criterion'), 'until': ts})
        c['criterion'] = r['criterion']
    for r in proposal.get('retired') or []:
        c = by_id[r['id']]
        c.update(status='retired', retire_reason=r['reason'], replaced_by=list(r.get('replaced_by') or []),
                 retired_at=ts, retired_in_run=run_id)
    for a in proposal.get('added') or []:
        new['clauses'].append({'id': a['id'], 'criterion': a['criterion'], 'events': a.get('events') or [],
                               'status': 'active', 'added_at': ts, 'added_in_run': run_id})
    new['clauses'].sort(key=lambda c: _id_no(c['id']))
    new.update(schema_version=SCHEMA_VERSION, injection_fingerprint=proposal['new_injection_fingerprint'],
               injection_snapshot=SNAPSHOT_FILE, normalization=NORMALIZATION['name'],
               confirmed_at=ts, confirmed_from_run=run_id)
    new.setdefault('changelog', []).append({
        'run_id': run_id, 'confirmed_at': ts, 'kind': proposal.get('kind'),
        'added': [a['id'] for a in proposal.get('added') or []],
        'rewritten': [r['id'] for r in proposal.get('rewritten') or []],
        'retired': [{'id': r['id'], 'reason': r['reason'], 'replaced_by': r.get('replaced_by') or []}
                    for r in proposal.get('retired') or []],
        'injection_fingerprint': proposal['new_injection_fingerprint'],
    })
    return new


def rehang_suggestions(proposal, cov, draft_cov, *, run_id, now):
    """挂在本次退役 id 上的用例（evals/ 与 drafts/）各出一条改挂建议。"""
    out = []
    for r in proposal.get('retired') or []:
        repl = r.get('replaced_by') or []
        if r['reason'] == 'delete':
            sug = '条款已删除：用例经用户在待审页确认后删除（git 历史留底）'
        elif len(repl) == 1:
            sug = '改挂到 %s' % repl[0]
        else:
            sug = '从 %s 中选一条改挂' % '、'.join(repl)
        for where, cmap in (('evals', cov), ('drafts', draft_cov)):
            for case in cmap.get(r['id'], []):
                out.append({'case': '%s/%s' % (where, case), 'retired_id': r['id'], 'reason': r['reason'],
                            'replaced_by': repl, 'suggestion': sug, 'ai_hint': r.get('rehang_hint') or '',
                            'from_run': run_id, 'created_at': _iso(now), 'status': 'open'})
    return out


# ---------------- 运行时第 2 步 ----------------

def _iso(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def find_reusable(repo, name, base_fp, new_fp, exclude=None):
    """最近一份还没裁定、基于同一份清单、指向同一个新指纹的提案所在运行目录；没有返回 None。
    任一运行对同一组（基线清单指纹、新指纹）记过打回，就不再复用这一组的任何提案（打回 = 下次重抽）。"""
    runs = evals_root(repo, name) / 'runs'
    if not runs.is_dir():
        return None
    found = []
    for d in sorted((p for p in runs.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        if d.name == exclude or not (d / CHECK_FILE).is_file() or not (d / PROPOSAL_FILE).is_file():
            continue
        try:
            cc = json.loads((d / CHECK_FILE).read_text(encoding='utf-8'))
            prop = json.loads((d / PROPOSAL_FILE).read_text(encoding='utf-8'))
        except ValueError:
            continue
        if not isinstance(cc, dict) or not isinstance(prop, dict) \
                or prop.get('base_list_fingerprint') != base_fp or prop.get('new_injection_fingerprint') != new_fp:
            continue
        if (cc.get('decision') or {}).get('status') == STATUS_REJECTED or cc.get('status') == STATUS_REJECTED:
            return None
        found.append((d, cc))
    for d, cc in found:
        if cc.get('status') == STATUS_PENDING and not cc.get('decision') and (d / RUN_SNAPSHOT_FILE).is_file():
            return d
    return None


def _rows(lst, proposal, cov):
    """报告逐条款：已确认清单的每条（标出本次提案要改写 / 退役的）+ 提案新增的（待确认，无用例）。"""
    prop = proposal or {}
    rewriting = {r['id'] for r in prop.get('rewritten') or []}
    retiring = {r['id']: r for r in prop.get('retired') or []}
    rows = []
    for c in (lst or {}).get('clauses') or []:
        row = {'id': c['id'], 'criterion': c.get('criterion'), 'status': c.get('status'),
               'cases': cov.get(c['id'], [])}
        if c.get('status') == 'retired':
            row.update(retire_reason=c.get('retire_reason'), replaced_by=c.get('replaced_by') or [])
        if c['id'] in rewriting:
            row['pending_change'] = 'rewrite'
        if c['id'] in retiring:
            row.update(pending_change='retire', pending_replaced_by=retiring[c['id']].get('replaced_by') or [])
        rows.append(row)
    for a in prop.get('added') or []:
        rows.append({'id': a['id'], 'criterion': a['criterion'], 'status': 'proposed', 'cases': []})
    return rows


@dataclass
class ClauseStep:
    check: dict
    proposal: dict = None
    snapshot: str = None


def evaluate(*, repo, name, plugin_dir, run_id, env=None, cases=None, ai=None, model=None, claude=None,
             tmp_parent=None, now=None, log=None, home=None):
    """第 2 步的判定（不写文件）：返回 ClauseStep。AI 失败记 status=ai-error，不抛。"""
    log = log or (lambda msg: print(msg, file=sys.stderr))
    now = now or datetime.now(timezone.utc)
    cap = capture_injection(plugin_dir, env=env, tmp_parent=tmp_parent, home=home)
    lst = load_list(repo, name)
    cc = {'schema_version': SCHEMA_VERSION, 'status': None, 'stale': None,
          'injection_fingerprint': cap.fingerprint,
          'list_injection_fingerprint': (lst or {}).get('injection_fingerprint'),
          'list_fingerprint': list_fingerprint(lst),
          'list_counts': {'active': len(active_ids(lst)), 'retired': len(retired_ids(lst))} if lst else None,
          'hooks': cap.summary(), 'normalization': NORMALIZATION['name'], 'errors': list(cap.errors),
          'proposal': None, 'proposal_kind': None, 'proposal_counts': None, 'reused_from': None, 'ai': None,
          'decision': None}
    step = ClauseStep(cc)
    if not cap.reliable:
        cc['status'] = STATUS_UNRELIABLE
        log('[条款清单] 注入 hook 有执行失败或两次输出不一致，本次不判过期：%s'
            % '；'.join(cap.failed + ['%s（两次输出不同）' % k for k in cap.unstable] + cap.errors))
    elif not cap.sections and lst is None:
        cc['status'] = STATUS_NO_INJECTION
    elif lst is not None and lst.get('injection_fingerprint') == cap.fingerprint:
        cc.update(status=STATUS_UP_TO_DATE, stale=False)
        log('[条款清单] 注入文本指纹未变，不重抽')
    else:
        cc['stale'] = lst is not None
        reuse = find_reusable(repo, name, cc['list_fingerprint'], cap.fingerprint, exclude=run_id)
        if reuse is not None:
            step.proposal = json.loads((reuse / PROPOSAL_FILE).read_text(encoding='utf-8'))
            cc['reused_from'] = reuse.name
            log('[条款清单] %s；沿用运行 %s 里尚未裁定的清单变更，不重抽'
                % ('注入文本指纹变了' if lst else '还没有条款清单', reuse.name))
        else:
            log('[条款清单] %s，调 AI %s' % ('注入文本指纹变了' if lst else '还没有条款清单',
                                          '增量重抽' if lst else '整份抽取'))
            try:
                step.proposal = build_proposal(repo=repo, name=name, lst=lst, cap=cap,
                                               ai=ai or default_ai(env=env, claude=claude),
                                               model=model, run_id=run_id, now=now)
            except clause_ai.ClauseAIError as e:
                cc['status'] = STATUS_AI_ERROR
                cc['errors'].append('AI %s失败：%s' % ('增量重抽' if lst else '抽取', e))
                log('[条款清单] %s' % cc['errors'][-1])
        if step.proposal is not None:
            step.snapshot = cap.text
            p = step.proposal
            cc.update(status=STATUS_PENDING, proposal=PROPOSAL_FILE, proposal_kind=p.get('kind'), ai=p.get('ai'),
                      proposal_counts={k: len(p.get(k) or []) for k in ('added', 'rewritten', 'retired')})
    cc['rows'] = _rows(lst, step.proposal, coverage(plugin_dir, cases)) if lst or step.proposal else []
    return step


def write_step(run_dir, step):
    run_dir = Path(run_dir)
    if step.proposal is not None:
        (run_dir / PROPOSAL_FILE).write_text(
            json.dumps(record.scrub_home(step.proposal), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (run_dir / RUN_SNAPSHOT_FILE).write_text(record.scrub_home(step.snapshot), encoding='utf-8')
    (run_dir / CHECK_FILE).write_text(json.dumps(record.scrub_home(step.check), ensure_ascii=False, indent=2) + '\n',
                                      encoding='utf-8')


def check_for_run(*, run_dir, log=None, **kw):
    """compare 第 2 步：判定并写进运行目录。意外错误（不是 AI 失败）也不中止对照，记 status=error。"""
    log = log or (lambda msg: print(msg, file=sys.stderr))
    try:
        step = evaluate(log=log, **kw)
    except Exception as e:  # noqa: BLE001 —— spec：条款清单这一步出问题时对照照跑，报告标出
        log('[条款清单] 出错，本次未判是否过期：%s: %s' % (type(e).__name__, e))
        # 出错分支不再读清单：清单损坏正是常见的出错原因，再读一次会把同一个异常抛出去、中止对照
        step = ClauseStep({'schema_version': SCHEMA_VERSION, 'status': STATUS_ERROR, 'stale': None,
                           'errors': ['%s: %s' % (type(e).__name__, e)], 'rows': [], 'decision': None,
                           'list_fingerprint': None})
    write_step(run_dir, step)
    return step.check


def record_fields(run_dir):
    """finalize_run 用：从运行目录的 clause-check.json 取 run.json 的两个字段；续跑也走这里，所以不会丢。"""
    p = Path(run_dir) / CHECK_FILE
    if not p.is_file():
        return {}
    cc = json.loads(p.read_text(encoding='utf-8'))
    return {'clause_list_fingerprint': cc.get('list_fingerprint'), 'clause_check': cc}


def default_ai(*, env=None, claude=None):
    """真调 claude -p。cwd 用系统临时目录，免得读到被测仓的 CLAUDE.md。"""
    cwd = tempfile.gettempdir()
    child = evalrun.child_env(env)
    exe = claude or evalrun.resolve_claude()     # 与 compare 一致：找 claude 用本进程完整 PATH
    return clause_ai.claude_caller(exe, env=child, cwd=cwd)


# ---------------- 待审页：条款清单变更（必上页） ----------------

LIST_REL = '../../%s' % LIST_FILE            # 相对运行目录 plugin-evals/<插件>/runs/<run_id>/
SNAPSHOT_REL = '../../%s' % SNAPSHOT_FILE
REHANG_REL = '../../%s' % REHANG_FILE
PENDING_BANNER_RE = re.compile(r'^> \*\*条款清单待确认\*\*.*$', re.MULTILINE)


def proposal_body(proposal):
    kind = proposal.get('kind')
    lines = []
    if kind == 'extract':
        lines.append('首次抽取：共 %d 条。' % len(proposal.get('added') or []))
    else:
        lines.append('增量变更（注入文本指纹 %s → %s）' % (str(proposal.get('old_injection_fingerprint'))[:19],
                                                str(proposal.get('new_injection_fingerprint'))[:19]))
    if proposal.get('added'):
        lines += ['', '新增：' if kind != 'extract' else '条款：']
        lines += ['  %s [%s] %s' % (a['id'], '/'.join(a.get('events') or []) or '—', a['criterion'])
                  for a in proposal['added']]
    if proposal.get('rewritten'):
        lines += ['', '改写（判定标准不变，保留 id）：']
        for r in proposal['rewritten']:
            lines += ['  %s 旧：%s' % (r['id'], r.get('old_criterion')), '  %s 新：%s' % (r['id'], r['criterion'])]
    if proposal.get('retired'):
        lines += ['', '退役（id 不再分配）：']
        for r in proposal['retired']:
            lines.append('  %s（%s）→ %s：%s' % (r['id'], r['reason'], '、'.join(r.get('replaced_by') or []) or '无替代',
                                              r.get('old_criterion')))
            if r.get('rehang_hint'):
                lines.append('    改挂建议：%s' % r['rehang_hint'])
    if kind != 'extract' and not (proposal.get('added') or proposal.get('rewritten') or proposal.get('retired')):
        lines += ['', 'AI 判定这次文字改动不影响任何条款；确认后只更新清单记的注入文本指纹。']
    return '\n'.join(lines)


def _current_list_fp(subject):
    return list_fingerprint(subject.read_json(LIST_REL))


def _collect(subject):
    cc = subject.read_json(CHECK_FILE)
    if not isinstance(cc, dict) or cc.get('status') != STATUS_PENDING or cc.get('decision'):
        return []
    prop = subject.read_json(cc.get('proposal') or PROPOSAL_FILE)
    if not isinstance(prop, dict) or _current_list_fp(subject) != prop.get('base_list_fingerprint'):
        return []   # 清单在别的运行里已经更新过：这份提案作废，下次对照按新清单重判
    counts = cc.get('proposal_counts') or {}
    rec = subject.rec
    facts = [('插件', '%s %s' % ((rec.get('plugin') or {}).get('name'), (rec.get('plugin') or {}).get('version'))),
             ('变更类型', '首次抽取' if prop.get('kind') == 'extract' else '增量重抽'),
             ('新增 / 改写 / 退役', '%d / %d / %d' % (counts.get('added', 0), counts.get('rewritten', 0),
                                                 counts.get('retired', 0))),
             ('新注入文本指纹', prop.get('new_injection_fingerprint')),
             ('AI 模型', (prop.get('ai') or {}).get('model'))]
    if cc.get('reused_from'):
        facts.append(('沿用自运行', cc['reused_from']))
    return [pending.PendingItem(
        id='clause-list:%s' % prop.get('new_injection_fingerprint'),
        title='确认条款清单变更：%s（%s）' % (prop.get('plugin'), '首次抽取' if prop.get('kind') == 'extract' else '增量'),
        body=proposal_body(prop), facts=tuple(facts),
        payload={'run_id': rec.get('run_id'), 'proposal': cc.get('proposal') or PROPOSAL_FILE})]


def _deactivate_gold(subject, newly_retired, ts):
    """条款退役：挂在它上面的 AI 评委金标（gold/<id>.json 的 clause）置 active=false，停止参与校准（不删）。"""
    gold_dir = subject.run_dir.parent.parent / 'gold'
    if not newly_retired or not gold_dir.is_dir():
        return
    for f in sorted(gold_dir.glob('*.json')):
        rel = '../../gold/%s' % f.name
        try:
            g = subject.read_json(rel)
        except ValueError:
            continue        # 坏金标由评委校准时报出，这里不拦条款清单的确认
        if isinstance(g, dict) and g.get('clause') in newly_retired and g.get('active', True):
            g['active'] = False
            g['deactivated'] = {'reason': 'clause-retired', 'clause': g['clause'], 'at': ts}
            subject.stage_json(rel, g)


def _apply(subject, item, code, now):
    cc = subject.read_json(CHECK_FILE)
    prop = subject.read_json((item.get('payload') or {}).get('proposal') or PROPOSAL_FILE)
    if not isinstance(cc, dict) or not isinstance(prop, dict):
        raise pending.PendingError('运行目录里没有 %s / %s' % (CHECK_FILE, PROPOSAL_FILE))
    ts = _iso(now)
    cur = subject.read_json(LIST_REL)
    cur_fp = list_fingerprint(cur)
    done = cc.get('decision') or {}
    if code == 'A':
        if cur_fp == prop.get('base_list_fingerprint'):
            new = apply_proposal(cur, prop, run_id=subject.rec.get('run_id'), now=now)
            new_fp = list_fingerprint(new)
            snap = subject.read_text(RUN_SNAPSHOT_FILE)
            if snap is None:
                raise pending.PendingError('运行目录里没有 %s，确认不了' % RUN_SNAPSHOT_FILE)
            p = subject.rec.get('plugin') or {}
            plugin_dir = subject.repo / (p.get('path_in_repo') or '.')
            cov = coverage(plugin_dir) if (plugin_dir / 'evals').is_dir() else {}
            name = prop.get('plugin') or p.get('name')
            sugg = rehang_suggestions(prop, cov, _draft_coverage(subject.repo, name),
                                      run_id=subject.rec.get('run_id'), now=now)
            cc['decision'] = {'code': 'A', 'status': STATUS_CONFIRMED, 'at': ts, 'list_fingerprint': new_fp,
                              'rehang_suggestions': len(sugg)}
            cc['status'] = STATUS_CONFIRMED
            subject.stage_json(CHECK_FILE, cc)          # 先记裁定：中途失败重试时据此判已落盘的部分
            subject.stage_text(SNAPSHOT_REL, snap)
            if sugg:
                old = subject.read_json(REHANG_REL) or {'schema_version': SCHEMA_VERSION, 'plugin': name,
                                                        'suggestions': []}
                have = {(s.get('case'), s.get('retired_id')) for s in old.get('suggestions') or []}
                old['suggestions'] = list(old.get('suggestions') or []) + [
                    s for s in sugg if (s['case'], s['retired_id']) not in have]
                subject.stage_json(REHANG_REL, old)
            subject.stage_json(LIST_REL, new)
            _deactivate_gold(subject, set(retired_ids(new)) - set(retired_ids(cur)), ts)
        elif done.get('code') == 'A' and cur_fp == done.get('list_fingerprint'):
            pass   # 上次写回已落盘清单（只差 run.json）：重试时不重复改
        else:
            raise pending.PendingError('条款清单在这份提案之后已被更新，提案作废；重新生成待审页或重跑对照')
        banner = '> **条款清单变更已确认**（%s，UTC）：已写入 `plugin-evals/%s/%s`；本报告的逐条款覆盖仍按确认前的清单计。' % (
            ts, prop.get('plugin'), LIST_FILE)
    else:
        cc['decision'] = {'code': code, 'status': STATUS_REJECTED, 'at': ts}
        cc['status'] = STATUS_REJECTED
        subject.stage_json(CHECK_FILE, cc)
        banner = '> **条款清单变更已打回**（%s，UTC）：清单未改；下次对照会重新抽取。' % ts
    if isinstance(subject.rec.get('clause_check'), dict) or 'clause_check' in subject.rec:
        subject.rec['clause_check'] = cc
    report = subject.read_text('report.md')
    if report is not None:
        new_report, n = PENDING_BANNER_RE.subn(banner.replace('\\', '\\\\'), report, count=1)
        if n:
            subject.stage_text('report.md', new_report)


CLAUSE_LIST = pending.ItemType(
    key='clause-list', label='条款清单变更',
    options=(('A', '确认：按这份变更更新条款清单'), ('B', '打回：不采纳，清单不改，下次对照重抽')),
    collect=_collect, apply=_apply, always=True, kinds=frozenset({'compare', 'clauses'}),
    hint='条款 = 可单独判定是否遵守的一条行为要求；id 绑判定标准，改措辞保留 id，判定标准变了、拆分、合并都退役旧 id 换新 id。'
         '确认后清单落盘，退役条款上的用例出改挂建议、金标停止参与校准。')
pending.register_type(CLAUSE_LIST)


# ---------------- 单跑：clauses 子命令 ----------------

EXISTING_LIST_MSG = '已有条款清单，重抽是跑对照的第一步，请改跑 compare'

def run_clauses(data_dir, name, *, ai=None, model=None, env=None, tmp_parent=None, now=None, log=None, home=None):
    """不跑对照、只做第 2 步（冷启动：还没有用例时也能先抽清单）。有变更时建 runs/<时间>-<版本>-clauses/ 并出待审页。
    只在该插件尚无 clauses.json 时执行：已有清单时抛 ClauseError（重抽是对照的第一步，改跑 compare），不调 AI。
    返回 (状态, 运行目录或 None, 待审页或 None)。"""
    log = log or (lambda msg: print(msg, file=sys.stderr))
    now = (now or (lambda: datetime.now(timezone.utc)))()
    data_dir = Path(data_dir)
    entry = registry.lookup(data_dir, name)
    repo = Path(entry['repo'])
    if (evals_root(repo, name) / LIST_FILE).exists():
        raise ClauseError(EXISTING_LIST_MSG)
    plugin_dir = registry.plugin_dir(entry)
    manifest_path = plugin_dir / '.claude-plugin' / 'plugin.json'
    if not manifest_path.is_file():
        raise ClauseError('登记的插件目录里没有 .claude-plugin/plugin.json：%s' % plugin_dir)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    version = manifest.get('version') or 'noversion'
    run_id = '%s-%s-clauses' % (now.strftime('%Y%m%dT%H%M%SZ'), version)
    child = evalrun.child_env(env)
    step = evaluate(repo=repo, name=name, plugin_dir=plugin_dir, run_id=run_id, env=child, ai=ai, model=model,
                    tmp_parent=tmp_parent, now=now, log=log, home=home)
    cc = step.check
    if cc['status'] != STATUS_PENDING:
        return cc, None, None
    run_dir = evals_root(repo, name) / 'runs' / run_id
    if run_dir.exists():
        raise ClauseError('运行目录已存在：%s' % run_dir)
    run_dir.mkdir(parents=True)
    write_step(run_dir, step)
    rec = {'schema_version': record.SCHEMA_VERSION, 'kind': 'clauses', 'run_id': run_id,
           'started_at': _iso(now), 'finished_at': _iso(datetime.now(timezone.utc)),
           'plugin': {'name': name, 'version': version, 'path_in_repo': entry['plugin_path']},
           'clause_list_fingerprint': cc.get('list_fingerprint'), 'clause_check': cc}
    from . import clausereport
    report = '\n'.join(['# 条款清单：%s %s' % (name, version), ''] + clausereport.banner_lines(rec)
                       + clausereport.section_lines(rec)) + '\n'
    rec = record.scrub_home(rec)
    (run_dir / 'run.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (run_dir / 'report.md').write_text(record.scrub_home(report), encoding='utf-8')
    page = pending.generate(data_dir, name, run_id=run_id)
    return cc, run_dir, page


def add_parser(sub):
    p = sub.add_parser('clauses', help='首次抽条款清单：只在插件尚无 clauses.json 时执行（调 AI 整份抽取并生成待审页）；'
                                       '已有清单时拒绝，重抽请改跑 compare')
    p.add_argument('name')
    p.add_argument('--model', help='抽取用的模型，缺省 %s' % clause_ai.DEFAULT_MODEL)
    return p


def main(args, data_dir):
    try:
        cc, run_dir, page = run_clauses(data_dir, args.name, model=args.model)
    except (ClauseError, registry.RegistryError, evalrun.ClaudeNotFound, pending.PendingError) as e:
        print('错误：%s' % e, file=sys.stderr)
        return 2
    status = cc['status']
    if status == STATUS_UP_TO_DATE:
        print('条款清单未过期（注入文本指纹 %s），不重抽' % cc['injection_fingerprint'])
        return 0
    if status == STATUS_NO_INJECTION:
        print('被测插件没有常驻注入文字，不需要条款清单')
        return 0
    if status in (STATUS_UNRELIABLE, STATUS_AI_ERROR, STATUS_ERROR):
        print('条款清单这一步没做成（%s）：' % status, file=sys.stderr)
        for e in cc.get('errors') or []:
            print('  %s' % e, file=sys.stderr)
        h = cc.get('hooks') or {}
        for k in (h.get('failed_hooks') or []) + ['%s（两次输出不同）' % x for x in h.get('unstable_hooks') or []]:
            print('  %s' % k, file=sys.stderr)
        return 2
    counts = cc.get('proposal_counts') or {}
    print('运行目录：%s' % run_dir)
    print('清单变更（%s）：新增 %d、改写 %d、退役 %d' % ('首次抽取' if cc.get('proposal_kind') == 'extract' else '增量重抽',
                                             counts.get('added', 0), counts.get('rewritten', 0), counts.get('retired', 0)))
    print('待审页：%s' % page.html_path)
    print('浏览器打开：%s' % page.html_path.resolve().as_uri())
    print('用户贴回回复码后运行：')
    print("  python3 plugin_eval.py --data-dir '%s' pending %s --run %s --reply '<回复码>'" % (data_dir, args.name, page.run_id))
    return 0
