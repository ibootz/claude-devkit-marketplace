"""待审页与回复码：人工环节集中在一个本机生成的 HTML 页，用户选完复制回复码贴回对话，CLI 写回。

一页对应一次运行（runs/<run_id>/），页文件写在用户级数据目录 pending/<插件>/<run_id>.html，不进被测仓。

待审项按「类型」组织。新增一种待审项只需构造 ItemType 并 register_type（或注册到传入的 TypeRegistry），
页面框架、回复码、抽样、写回事务都不用改：
- collect(subject) -> [PendingItem]：从本次运行里收集还没裁定的项；
- apply(subject, item, code, now)：按用户选的选项码写回。item 是存进 run.json 的那份
  {no, id, type, title, payload}；改 run.json 直接改 subject.rec，改别的文件用 subject.stage_text / stage_json /
  stage_delete 暂存。全部项都写回成功才统一落盘，任一项抛错则什么都不写。
- options：((选项码, 页上文字), ...)，选项码是单个大写字母；页上另有「暂不裁定」，不进回复码。
- always=True 的类型必上页；其余按 priority（小者先）装满 PAGE_LIMIT，装不下的那一档以 run_id 为种子随机抽取。
- kinds：适用于哪类结果（结果文件的 kind：compare / clauses / review）。生成页只跑 kind 匹配的类型的 collect，
  复盘页（kind=review，run_dir 是 reviews/）不会去跑离线对照那几类的 collect，反之亦然。缺省只适用于 compare。

内置类型只有「报告审阅」（本票）。后续：分歧样本与抽检（票 09）、条款清单变更（票 10）、用例草稿（票 11）、
复盘候选与「建议跑对照」（票 12，见 review_pending：每个插件每次复盘一页，Subject 指向 reviews/<日期>.json，
回复码的 run_id 形如 review-<日期>，apply_reply 按这个前缀转给 review_pending）。

回复码：`PE1 <run_id> <page_id> <序号><选项码> ...`，如 `PE1 20261015T084918Z-4.1.0-compare 3fa9c1d2 1A`。
page_id 每次生成页时重算并记进 run.json 的 pending.page_id；只认最新一页、且只能写回一次。

与续跑（票 07）的关系：生成页与写回都拿该运行的 RunLock，与对照、续跑互斥；未结束的运行（检查点 run.json，
或锁正被占用）不出页，不带 --run 时跳过它们取下一个。续跑重写 run.json 后旧页作废，续跑收尾重新生成。
"""
import hashlib
import html
import json
import os
import random
import re
import secrets
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import record, registry

PAGE_LIMIT = 10
RUN_KINDS = ('compare', 'clauses')   # runs/ 下有待审项的结果种类；不带 --run 时在这两类里挑
REPLY_PREFIX = 'PE1'
REVIEW_DONE = '已审'
SAMPLING_HEADING = '## 待审页抽样'
SAMPLING_RULE = ('每页最多 %d 项。必选类型（报告审阅）先上页；其余按类型优先级依次装入，'
                 '装不下的那一档以 run_id 为种子随机抽取（同一次运行重复生成，抽中的项不变），'
                 '抽中的项保持原顺序。没上页的项本次不裁定，留待下一页。' % PAGE_LIMIT)
_RUN_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
_REPLY_RE = re.compile(r'^PE1\s+(\S+)\s+([0-9a-fA-F]{8})((?:\s+\S+)*)$', re.IGNORECASE)
_TOKEN_RE = re.compile(r'^(\d+)([A-Za-z])$')
REPLY_FORMAT = '回复码格式：PE1 <run_id> <page_id> <序号><选项码> ...，如 PE1 20261015T084918Z-4.1.0-compare 3fa9c1d2 1A'


class PendingError(Exception):
    pass


class ReplyError(PendingError):
    pass


class NothingPending(PendingError):
    pass


@dataclass
class PendingItem:
    id: str                       # 稳定 id，同一项重复生成页时不变；抽样与报告都按它列
    title: str
    body: str = ''                # 长正文，页上原样显示（转义后放 <pre>）
    facts: tuple = ()             # ((标签, 值), ...)，页上显示成摘要表
    payload: Optional[dict] = None  # 写回时要用的定位信息，存进 run.json，不放长文本


@dataclass(frozen=True)
class ItemType:
    key: str
    label: str
    options: tuple
    collect: Optional[Callable]
    apply: Optional[Callable]
    priority: int = 100
    always: bool = False
    hint: str = ''                # 页上该类型项的说明
    kinds: frozenset = frozenset({'compare'})   # 适用于哪类结果（rec['kind']）


class TypeRegistry(object):
    def __init__(self):
        self._types = {}

    def register(self, t):
        for code, _ in t.options:
            if not re.match(r'^[A-Z]$', code):
                raise ValueError('%s 的选项码 %r 不是单个大写字母' % (t.key, code))
        self._types[t.key] = t

    def unregister(self, key):
        self._types.pop(key, None)

    def get(self, key):
        return self._types.get(key)

    def all(self):
        return list(self._types.values())

    def for_kind(self, kind):
        """适用于这类结果的类型（按注册顺序）。"""
        return [t for t in self._types.values() if kind in t.kinds]

    def as_dict(self):
        return dict(self._types)


class Subject(object):
    """一次运行：run_dir 下的 run.json（rec，可直接改）与暂存的其它文件改动。
    会话复盘（票 12）复用它：run_dir 是 reviews/，record_name 是 <日期>.json。"""

    def __init__(self, repo, run_dir, rec, record_name='run.json'):
        self.repo = Path(repo).resolve()
        self.run_dir = Path(run_dir).resolve()
        self.rec = rec
        self.record_name = record_name
        self.staged = {}              # 绝对路径 -> 新文本；None 表示删除
        self.warnings = []

    def path(self, rel):
        p = (self.run_dir / rel).resolve()
        if p != self.repo and self.repo not in p.parents:
            raise PendingError('写回路径越出被测仓：%s' % p)
        return p

    def read_text(self, rel):
        p = self.path(rel)
        if p in self.staged:
            return self.staged[p]
        return p.read_text(encoding='utf-8') if p.is_file() else None

    def read_json(self, rel):
        text = self.read_text(rel)
        return None if text is None else json.loads(text)

    def stage_text(self, rel, text):
        self.staged[self.path(rel)] = text

    def stage_json(self, rel, obj):
        self.stage_text(rel, json.dumps(obj, ensure_ascii=False, indent=2) + '\n')

    def stage_delete(self, rel):
        self.staged[self.path(rel)] = None

    def warn(self, msg):
        self.warnings.append(msg)

    def commit(self):
        """先落其它文件，最后落 run.json（中途失败时 run.json 仍是旧的，用同一回复码重试即可补齐）。
        写进被测仓的内容都过 record.scrub_home（会入库）。返回改动过的文件（相对被测仓）。
        落盘出 OSError 时清掉残片 .pending-tmp，抛 PendingError 并列出已写成的文件。"""
        changed = []
        run_json = self.run_dir / self.record_name
        self.rec = record.scrub_home(self.rec)
        self.staged[run_json] = json.dumps(self.rec, ensure_ascii=False, indent=2) + '\n'
        for p in sorted(self.staged, key=lambda x: x == run_json):
            text = self.staged[p]
            tmp = p.with_name(p.name + '.pending-tmp')
            try:
                if text is None:
                    if p.exists():
                        p.unlink()
                else:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    tmp.write_text(record.scrub_home(text), encoding='utf-8')
                    os.replace(tmp, p)
            except OSError as e:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                self.staged = {}
                raise PendingError('写 %s 失败：%s。已写成：%s；run.json 未更新，排除问题后用同一回复码重试' % (
                    p.relative_to(self.repo).as_posix(), e, '、'.join(changed) or '无'))
            changed.append(p.relative_to(self.repo).as_posix())
        self.staged = {}
        return changed


# ---------------- 内置类型：报告审阅 ----------------

_STATUS_RE = re.compile(r'^> 状态：\*\*待审\*\*。.*$', re.MULTILINE)


def _fmt(x, signed=False):
    if x is None:
        return '—'
    return ('%+.2f' if signed else '%.2f') % x


def _review_collect(subject):
    rec = subject.rec
    if rec.get('kind') != 'compare' or (rec.get('review') or {}).get('status') == REVIEW_DONE or _unfinished(rec):
        return []
    p = rec.get('plugin') or {}
    arms = [(k, rec['arms'][k]) for k in record.ARM_ORDER if (rec.get('arms') or {}).get(k)]
    facts = [('插件', '%s %s' % (p.get('name'), p.get('version'))),
             ('运行', rec.get('run_id')),
             ('是否完整', '是' if rec.get('complete') else '否'),
             ('是否通过', '是' if rec.get('passed') else '否')]
    facts += [('%s臂总分' % a.get('label', k), _fmt(a.get('score'))) for k, a in arms]
    facts.append(('差（当前版 − 不装）', _fmt((rec.get('delta') or {}).get('overall'), signed=True)))
    facts.append(('花费（标价估算）', '$%.4f' % ((rec.get('usage') or {}).get('cost_usd') or 0)))
    facts += [('不完整原因', r) for r in rec.get('incomplete_reasons') or []]
    return [PendingItem(
        id='report-review:%s' % rec.get('run_id'),
        title='审阅离线对照报告：%s %s' % (p.get('name'), p.get('version')),
        body=subject.read_text('report.md') or '（report.md 不存在）',
        facts=tuple(facts),
        payload={'run_id': rec.get('run_id')},
    )]


def _review_apply(subject, item, code, now):
    ts = _iso(now)
    review = dict(subject.rec.get('review') or {})
    review.update(status=REVIEW_DONE, reviewed_at=ts)
    subject.rec['review'] = review
    text = subject.read_text('report.md')
    if text is None:
        subject.warn('report.md 不存在，只改了 run.json')
        return
    new, n = _STATUS_RE.subn('> 状态：**%s**（审阅时间 %s，UTC）。' % (REVIEW_DONE, ts), text, count=1)
    if n:
        subject.stage_text('report.md', new)
    else:
        subject.warn('report.md 里没找到「状态：**待审**」那一行，未改写 report.md')


REPORT_REVIEW = ItemType(
    key='report-review', label='报告审阅', options=(('A', '已审：读完报告，可作改插件或发版的依据'),),
    collect=_review_collect, apply=_review_apply, always=True, kinds=frozenset({'compare'}),
    hint='待审报告不能作为改插件或发版的依据。读完下面的报告后选「已审」；没读完就选「暂不裁定」。')


def default_registry():
    reg = TypeRegistry()
    reg.register(REPORT_REVIEW)
    return reg


_REGISTRY = default_registry()


def register_type(t):
    _REGISTRY.register(t)


def unregister_type(key):
    _REGISTRY.unregister(key)


# ---------------- 抽样 ----------------

def select_items(items, types, limit=PAGE_LIMIT, seed=''):
    """items：[(类型 key, id, ...)]。返回 (上页的, 没上页的)，两者都保持 items 里的原顺序。"""
    idx_always = [i for i, it in enumerate(items) if types[it[0]].always]
    rest = [i for i, it in enumerate(items) if not types[it[0]].always]
    keep = set(idx_always[:limit])
    slots = limit - len(keep)
    for prio in sorted({types[items[i][0]].priority for i in rest}):
        tier = [i for i in rest if types[items[i][0]].priority == prio]
        if len(tier) <= slots:
            keep.update(tier)
            slots -= len(tier)
        else:
            keep.update(random.Random('%s:%s' % (seed, prio)).sample(tier, slots))
            slots = 0
    kept = [it for i, it in enumerate(items) if i in keep]
    out = [it for i, it in enumerate(items) if i not in keep]
    return kept, out


def _sampling_section(total, kept, out):
    lines = [SAMPLING_HEADING, '',
             '本次共 %d 项待判，待审页只出 %d 项。抽样规则：%s' % (total, len(kept), SAMPLING_RULE), '',
             '页上的项：', '']
    lines += ['%d. `%s`（%s）' % (n, it['id'], it['title']) for n, it in enumerate(kept, 1)]
    lines += ['', '没上页的项：', '']
    lines += ['- `%s`（%s）' % (it['id'], it['title']) for it in out]
    return '\n'.join(lines) + '\n'


def upsert_section(text, heading, body):
    """把 report.md 里以 heading 开头的那一节换成 body（body 为 None 则删掉该节）；没有就追加到末尾。"""
    start = text.find('\n' + heading + '\n')
    if start >= 0:
        nxt = text.find('\n## ', start + 1)
        before, after = text[:start + 1], (text[nxt + 1:] if nxt >= 0 else '')
        text = before.rstrip('\n') + '\n' + ('\n' + body if body else '') + ('\n' + after if after else '')
        return text if text.endswith('\n') else text + '\n'
    if body is None:
        return text
    return text.rstrip('\n') + '\n\n' + body


# ---------------- 定位运行 ----------------

def _iso(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _runs_dir(data_dir, name):
    entry = registry.lookup(data_dir, name)
    repo = Path(entry['repo'])
    return repo, repo / 'plugin-evals' / name / 'runs'


def _load_run(run_dir):
    p = run_dir / 'run.json'
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except ValueError as e:
        raise PendingError('%s 不是合法 JSON：%s' % (p, e))


def _unfinished(rec):
    """检查点 run.json：对照或续跑还没走到收尾（进行中，或进程中途退出），没有可审的报告。"""
    return any(str(r).startswith(resume.CHECKPOINT_REASON) for r in rec.get('incomplete_reasons') or [])


def _find_run(data_dir, name, run_id, err=PendingError):
    repo, runs = _runs_dir(data_dir, name)
    if run_id is None:
        cands = sorted(d.name for d in runs.iterdir() if (d / 'run.json').is_file()) if runs.is_dir() else []
        recs = {}
        for c in cands:
            try:
                recs[c] = _load_run(runs / c)
            except PendingError as e:      # 坏的历史记录不挡别的运行；只有 --run 指定它时才报错
                print('注意：跳过 %s' % e, file=sys.stderr)
        # 单跑 clauses 的运行（kind=clauses）也有待审项（条款清单变更），与离线对照同样默认选中、同样列进较早待审
        cands = [c for c in cands if isinstance(recs.get(c), dict) and recs[c].get('kind') in RUN_KINDS]
        if not cands:
            raise NothingPending('%s 下没有离线对照或条款清单的运行记录' % runs)
        # 跳过未结束的运行（锁被占用或检查点）：它们的 run.json 还会被改写
        done = [c for c in cands if not resume.RunLock(data_dir, c).busy() and not _unfinished(recs[c])]
        if not done:
            raise NothingPending('%s 下的运行都还没结束（进行中或中途退出待续跑）：%s' % (runs, '、'.join(cands)))
        run_id = done[-1]
    if not _RUN_ID_RE.match(run_id) or not (runs / run_id / 'run.json').is_file():
        raise err('插件 %s 下没有运行 %r（找的是 %s/%s/run.json）' % (name, run_id, runs, run_id))
    return repo, runs / run_id


# ---------------- 生成页 ----------------

@dataclass
class Page:
    run_id: str
    page_id: str
    html_path: Path
    items: list                   # [{no, id, type, title, payload}]
    total: int
    sampled_out: list = field(default_factory=list)
    report_changed: bool = False


def generate(data_dir, name, run_id=None, *, now=None, types=None):
    """收集待判项、必要时抽样，写 HTML 页到 <数据目录>/pending/<插件>/<run_id>.html，并把本页记进 run.json。"""
    types = types or _REGISTRY
    now = (now or (lambda: datetime.now(timezone.utc)))()
    repo, run_dir = _find_run(data_dir, name, run_id)
    try:
        with _locked(data_dir, run_dir.name):
            return _generate(data_dir, name, repo, run_dir, now, types)
    except NothingPending as e:
        # 不带 --run 时仍只取最新一次；它没有待审项，就把较早仍有待审项的运行逐个列出来（拍板 08-2）
        earlier = [] if run_id is not None else _earlier_with_items(data_dir, repo, run_dir, types)
        if not earlier:
            raise
        lines = ['  - %s（%d 项待判）：pending %s --run %s' % (rid, n, name, rid) for rid, n in earlier]
        raise NothingPending('%s\n较早的运行里仍有待审项，逐个用 --run 指定生成：\n%s' % (e, '\n'.join(lines))) from None


def _earlier_with_items(data_dir, repo, latest_dir, types):
    """比 latest_dir 早、已结束、仍有待判项的运行（离线对照或单跑条款清单）：[(run_id, 项数)]，按时间先后。只读。"""
    out = []
    for d in sorted(latest_dir.parent.iterdir()):
        if d.name >= latest_dir.name or not (d / 'run.json').is_file():
            continue
        try:
            rec = _load_run(d)
            if not isinstance(rec, dict) or rec.get('kind') not in RUN_KINDS or _unfinished(rec) \
                    or resume.RunLock(data_dir, d.name).busy():
                continue
            subject = Subject(repo, d, rec)
            n = sum(len(list(t.collect(subject) or [])) for t in types.for_kind(rec.get('kind')))
        except Exception:  # noqa: BLE001 —— 只是提示，坏记录或收集出错的运行不列
            continue
        if n:
            out.append((d.name, n))
    return out


class _locked(object):
    """拿该运行的 RunLock（与对照、续跑互斥）；被占用时转成 PendingError。"""

    def __init__(self, data_dir, run_id, err=PendingError):
        self.lock, self.err = resume.RunLock(data_dir, run_id), err

    def __enter__(self):
        try:
            self.lock.acquire()
        except resume.ResumeError as e:
            raise self.err('运行 %s 正在对照或续跑，结束后再处理待审页（%s）' % (self.lock.path.stem, e))
        return self.lock

    def __exit__(self, *exc):
        self.lock.release()
        return False


def _generate(data_dir, name, repo, run_dir, now, types, subject=None):
    subject = subject or Subject(repo, run_dir, _load_run(run_dir))
    rec = subject.rec
    run_id = rec.get('run_id') or run_dir.name
    if _unfinished(rec):
        raise NothingPending('运行 %s 还没结束（对照进行中，或中途退出待续跑），没有可审的报告；续跑完成后再生成' % run_id)

    collected = []
    by_key = types.as_dict()
    for t in types.for_kind(rec.get('kind')):   # 只跑适用于这类结果的类型：复盘页不跑离线对照的 collect，反之亦然
        try:
            items = list(t.collect(subject) or [])
        except Exception as ex:  # noqa: BLE001 —— 收集逻辑由各类型提供，出错时给出类型名，不打 traceback
            raise PendingError('收集「%s」类待审项时出错（未改任何文件）：%s: %s' % (t.label, type(ex).__name__, ex))
        for it in items:
            collected.append((t.key, it.id, it))
    if not collected:
        raise NothingPending('运行 %s 没有待判项（报告已审，其它类型也没有未裁定的项）' % run_id)
    kept, out = select_items(collected, by_key, PAGE_LIMIT, seed=run_id)

    gen_at = _iso(now)
    # 带随机数：同一秒重复生成也换新 page_id，旧页的回复码一律作废
    seed_text = '%s|%s|%s|%s' % (run_id, gen_at, secrets.token_hex(8), '|'.join(k[1] for k in kept))
    page_id = hashlib.sha256(seed_text.encode('utf-8')).hexdigest()[:8]
    stored = [{'no': n, 'id': it.id, 'type': key, 'title': it.title, 'payload': it.payload}
              for n, (key, _, it) in enumerate(kept, 1)]
    out_stored = [{'id': it.id, 'type': key, 'title': it.title} for key, _, it in out]

    old = rec.get('pending') or {}
    history = list(old.get('history') or [])
    if old.get('applied_at'):
        history.append({k: old.get(k) for k in ('page_id', 'generated_at', 'applied_at', 'decisions')})
    rec['pending'] = {
        'page_id': page_id, 'generated_at': gen_at, 'limit': PAGE_LIMIT,
        'total': len(collected), 'sampled': bool(out), 'sampling_rule': SAMPLING_RULE if out else None,
        'items': stored, 'sampled_out': [o['id'] for o in out_stored],
        'applied_at': None, 'decisions': None, 'history': history,
    }

    report = subject.read_text('report.md')
    report_changed = False
    if report is not None:
        new = upsert_section(report, SAMPLING_HEADING, _sampling_section(len(collected), stored, out_stored) if out else None)
        if new != report:
            subject.stage_text('report.md', new)
            report_changed = True

    html_path = Path(data_dir) / 'pending' / name / ('%s.html' % run_id)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    page_html = render_page(rec, page_id, [(by_key[key], n, it) for n, (key, _, it) in enumerate(kept, 1)],
                            total=len(collected), sampled_out=out_stored)
    html_path.write_text(page_html, encoding='utf-8')   # 先写页：写页失败时 run.json 不留一个没有页的 page_id
    subject.commit()
    return Page(run_id, page_id, html_path, stored, len(collected), [o['id'] for o in out_stored], report_changed)


_CSS = '''
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:960px;margin:2em auto;padding:0 1em;
background:rgb(253,246,227);color:#222;line-height:1.6}
h1{font-size:1.4em}.meta{color:#555}.item{border:1px solid #ccc;border-radius:6px;padding:1em;margin:1.2em 0;background:#fff}
.item h2{font-size:1.1em;margin:0 0 .4em}.type{color:#8a5a00;font-weight:bold}.hint{color:#555}
table.facts{border-collapse:collapse;margin:.6em 0}table.facts td{border:1px solid #ddd;padding:.2em .6em}
pre{white-space:pre-wrap;background:#f7f7f7;padding:.8em;border-radius:4px;max-height:28em;overflow:auto}
.opts label{display:block;margin:.2em 0;cursor:pointer}#code{width:100%;font-family:monospace;font-size:1.05em;padding:.5em}
.bar{position:sticky;bottom:0;background:rgb(253,246,227);padding:.8em 0;border-top:1px solid #ccc}
button{font-size:1em;padding:.3em 1em}.warn{color:#a00}
'''

_JS = '''
const META = JSON.parse(document.getElementById('pe-meta').textContent);
const box = document.getElementById('code');
function build() {
  const toks = [];
  document.querySelectorAll('.item').forEach(function (el) {
    const c = el.querySelector('input[type=radio]:checked');
    if (c && c.value) toks.push(el.dataset.no + c.value);
  });
  box.value = toks.length ? [META.prefix, META.run_id, META.page_id].concat(toks).join(' ') : '';
  box.placeholder = '还没有裁定任何项';
}
document.querySelectorAll('input[type=radio]').forEach(function (r) { r.addEventListener('change', build); });
document.getElementById('copy').addEventListener('click', function () {
  build();
  if (!box.value) return;
  box.select();
  const done = function () { document.getElementById('copied').textContent = '已复制，贴回对话即可'; };
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(box.value).then(done, function () { document.execCommand('copy'); done(); });
  else { document.execCommand('copy'); done(); }
});
build();
'''


def render_page(rec, page_id, entries, *, total, sampled_out):
    """entries：[(ItemType, 序号, PendingItem)]。只依赖 ItemType 的 label / hint / options 与 PendingItem 的字段。"""
    e = html.escape
    p = rec.get('plugin') or {}
    run_id = rec.get('run_id')
    parts = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
             '<title>待审：%s %s</title><style>%s</style></head><body>' % (e(str(p.get('name'))), e(str(p.get('version'))), _CSS),
             '<h1>待审页：%s %s</h1>' % (e(str(p.get('name'))), e(str(p.get('version')))),
             '<p class="meta">运行 <code>%s</code> · 页 <code>%s</code> · 本页 %d 项' % (e(str(run_id)), e(page_id), len(entries))]
    if sampled_out:
        where = ('复盘结果的 pending.sampled_out' if rec.get('kind') == 'review' else 'report.md「待审页抽样」')
        parts.append('（共 %d 项待判，已按规则抽样，%d 项没上页，名单见 %s）' % (total, len(sampled_out), where))
    parts.append('</p><p class="hint">逐项选择后，点页底的「复制回复码」，把回复码贴回对话。'
                 '这一页只认最新生成的那份回复码，且只能写回一次。</p>')
    for t, no, it in entries:
        parts.append('<div class="item" data-no="%d"><h2>%d. <span class="type">[%s]</span> %s</h2>'
                     % (no, no, e(t.label), e(it.title)))
        if t.hint:
            parts.append('<p class="hint">%s</p>' % e(t.hint))
        if it.facts:
            parts.append('<table class="facts">%s</table>' % ''.join(
                '<tr><td>%s</td><td>%s</td></tr>' % (e(str(k)), e(str(v))) for k, v in it.facts))
        if it.body:
            parts.append('<details open><summary>正文</summary><pre>%s</pre></details>' % e(it.body))
        parts.append('<div class="opts"><label><input type="radio" name="i%d" value="" checked> 暂不裁定</label>' % no)
        parts += ['<label><input type="radio" name="i%d" value="%s"> %s</label>' % (no, e(code), e(label))
                  for code, label in t.options]
        parts.append('</div><p class="meta">项 id：<code>%s</code></p></div>' % e(it.id))
    meta = json.dumps({'prefix': REPLY_PREFIX, 'run_id': run_id, 'page_id': page_id}).replace('</', '<\\/')
    parts.append('<div class="bar"><label>回复码：<input id="code" readonly></label> '
                 '<button id="copy" type="button">复制回复码</button> <span id="copied"></span></div>')
    parts.append('<script type="application/json" id="pe-meta">%s</script><script>%s</script></body></html>' % (meta, _JS))
    return '\n'.join(parts) + '\n'


# ---------------- 回复码 ----------------

@dataclass
class ReplyResult:
    run_id: str
    decisions: list               # [(序号, 选项码, 类型 label, 项 title)]
    changed_files: list
    warnings: list


def parse_reply(code):
    """返回 (run_id, page_id, [(序号, 选项码)])。格式错一律抛 ReplyError。"""
    text = ' '.join((code or '').split())
    m = _REPLY_RE.match(text)
    if not m:
        raise ReplyError('回复码格式不对：%r。%s' % ((code or '').strip()[:80], REPLY_FORMAT))
    run_id, page_id, rest = m.group(1), m.group(2).lower(), m.group(3).split()
    if not _RUN_ID_RE.match(run_id):
        raise ReplyError('回复码里的 run_id 不合法：%r' % run_id)
    decisions, seen = [], set()
    for tok in rest:
        t = _TOKEN_RE.match(tok)
        if not t:
            raise ReplyError('回复码里的裁定 %r 不是「序号+选项码」（如 1A）。%s' % (tok, REPLY_FORMAT))
        no, opt = int(t.group(1)), t.group(2).upper()
        if no in seen:
            raise ReplyError('回复码里第 %d 项出现了两次' % no)
        seen.add(no)
        decisions.append((no, opt))
    if not decisions:
        raise ReplyError('回复码里没有任何裁定（页上每项都是「暂不裁定」）')
    return run_id, page_id, decisions


def apply_reply(data_dir, name, code, run_id=None, *, now=None, types=None):
    """校验回复码对得上该次运行的最新一页，再按类型写回。任何一步出错都抛 ReplyError，不改任何文件。"""
    types = types or _REGISTRY
    now = (now or (lambda: datetime.now(timezone.utc)))()
    code_run, page_id, decisions = parse_reply(code)
    if run_id is not None and run_id != code_run:
        raise ReplyError('回复码对不上该次运行：回复码是 %s 的，命令指定的是 %s' % (code_run, run_id))
    if code_run.startswith('review-'):          # 复盘待审页（票 12）
        from . import review_pending
        return review_pending.apply_reply(data_dir, name, code_run, page_id, decisions, now=now, types=types)
    try:
        repo, run_dir = _find_run(data_dir, name, code_run, err=ReplyError)
    except NothingPending as e:
        raise ReplyError(str(e))
    with _locked(data_dir, run_dir.name, err=ReplyError):
        return _apply(repo, run_dir, code_run, page_id, decisions, now, types)


def _apply(repo, run_dir, code_run, page_id, decisions, now, types, subject=None):
    subject = subject or Subject(repo, run_dir, _load_run(run_dir))
    pend = subject.rec.get('pending') or {}
    if pend.get('page_id') != page_id:
        raise ReplyError('回复码对不上该次运行的最新待审页：回复码的页是 %s，run.json 记的最新页是 %s。'
                         '请用最新生成的页重新选' % (page_id, pend.get('page_id')))
    if pend.get('applied_at'):
        raise ReplyError('这一页的回复码已在 %s 写回过，不重复写回；要改裁定请重新生成待审页' % pend['applied_at'])
    items = {it.get('no'): it for it in pend.get('items') or [] if isinstance(it, dict)}
    plan = []
    for no, opt in decisions:
        it = items.get(no)
        if it is None:
            raise ReplyError('回复码里的第 %d 项不在这一页上（本页 %d 项）' % (no, len(items)))
        t = types.get(it.get('type')) if isinstance(it, dict) else None
        if t is None:
            raise ReplyError('第 %d 项的类型 %r 没有注册写回逻辑（run.json 的 pending.items 可能被改坏）'
                             % (no, it.get('type') if isinstance(it, dict) else it))
        if opt not in dict(t.options):
            raise ReplyError('第 %d 项（%s）没有选项 %s，可选：%s' % (
                no, t.label, opt, '、'.join('%s=%s' % o for o in t.options)))
        plan.append((no, opt, t, it))

    for no, opt, t, it in plan:
        try:
            t.apply(subject, it, opt, now)
        except Exception as ex:  # noqa: BLE001 —— 写回逻辑由各类型提供，任何异常都要挡住，保证不落盘
            raise ReplyError('写回第 %d 项（%s）失败，未改任何文件：%s' % (no, t.label, ex))
    subject.rec['pending'] = dict(pend, applied_at=_iso(now),
                                  decisions={str(no): opt for no, opt, _, _ in plan})
    changed = subject.commit()
    return ReplyResult(code_run, [(no, opt, t.label, it['title']) for no, opt, t, it in plan],
                       changed, subject.warnings)


# ---------------- 命令行 ----------------

def add_parser(sub):
    p = sub.add_parser('pending', help='生成待审页；或带 --reply 接收用户贴回的回复码并写回')
    p.add_argument('name')
    p.add_argument('--run', help='运行 id（runs/ 下的目录名）；生成页时默认取最新一次离线对照')
    p.add_argument('--reply', help='用户从待审页复制回来的回复码（整串，加引号）')
    p.add_argument('--review', nargs='?', const='latest', metavar='日期',
                   help='生成会话复盘的待审页（reviews/<日期>.json，缺省取最新一份）；写回仍用 --reply')
    return p


def main(args, data_dir):
    try:
        if args.reply is None and getattr(args, 'review', None) is not None:
            from . import review_pending
            page = review_pending.generate(data_dir, args.name, None if args.review == 'latest' else args.review)
        elif args.reply is not None:
            res = apply_reply(data_dir, args.name, args.reply, run_id=args.run)
            print('已写回运行 %s：' % res.run_id)
            for no, opt, label, title in res.decisions:
                print('  第 %d 项 [%s] %s → %s' % (no, label, title, opt))
            print('改动的文件（相对被测仓）：%s' % '、'.join(res.changed_files))
            for w in res.warnings:
                print('  注意：%s' % w)
            return 0
        else:
            page = generate(data_dir, args.name, run_id=args.run)
    except NothingPending as e:
        print('没有待审项：%s' % e)
        return 0
    except (PendingError, registry.RegistryError) as e:
        print('错误：%s' % e, file=sys.stderr)
        return 2
    print('待审页：%s' % page.html_path)
    print('浏览器打开：%s' % page.html_path.resolve().as_uri())
    print('本页 %d 项（共 %d 项待判%s）' % (len(page.items), page.total,
                                      ('，已抽样，规则与名单记在复盘结果的 pending 字段' if page.run_id.startswith('review-')
                                       else '，已抽样，规则与名单写进 report.md「待审页抽样」') if page.sampled_out else ''))
    print('回复码以「%s %s %s」开头。用户贴回后运行：' % (REPLY_PREFIX, page.run_id, page.page_id))
    print("  python3 plugin_eval.py --data-dir '%s' pending %s --reply '<回复码>'" % (data_dir, args.name))
    return 0


# resume 放到模块末尾才导入：resume → compare → judgepending / clauses 会在导入期调 register_type，
# 那时本模块必须已定义完 ItemType 与注册表。本模块只在函数体里用 resume.X。
from . import resume  # noqa: E402
