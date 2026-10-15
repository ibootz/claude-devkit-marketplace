"""AI 评委（票 09）：规则判不了的判定标准交模型读完整转录判分，每条判两遍；金标校准；分歧样本与抽检。

用例怎么声明「这条交 AI 评委」：在用例目录下放 judge/<判定标准 id>.md（eval 不读用例目录下的子目录，
票 01 报告「三、问题 3」实测静默忽略），正文是判定标准，可选 frontmatter：
    rule: <grader 名>      与之对照的规则 grader；评委判法与它相反即「评委与规则冲突」，算分歧样本
    arms: [current, none]  只判这些臂；缺省判全部臂
    clause: C001           这条判定标准所属的条款 id（票 10 的 clauses.json）；金标随之记下，条款退役后金标停用
frontmatter 只认这三个键。未知键、未知臂名、条款 id 形态不对：compare 开跑前报错（check_criteria）；
rule 指向的 grader 在用例里不存在、条款 id 不在清单里或已退役：在报告里显式告警（judge.json 的 warnings）。
样本 = 臂 × 用例 × 第几次 run × 判定标准。每个样本调两次评委（两遍独立判），判法：
- 两遍都出错之外的任一遍出错 → error（不进待审页，运行判不完整，续跑时重判）；
- 两遍判法不同，或两遍都判「判不了」，或两遍一致却与 rule grader 相反 → disagreement（分歧样本，全进待审页）；
- 其余 → agreed；从中以 run_id 为种子随机抽 SPOT_CHECK_COUNT 条进待审页（抽检），不足全进。
分歧与抽检样本的 trace 压缩存进 runs/<run_id>/samples/<臂>--<用例>--<trace 目录哈希>.jsonl.gz，入库；其余 trace 只留本机。
入库只留三类行：assistant（去掉 thinking 块）、user 里的 tool_result、result；system/init 等整行不入库，
再去掉家目录、邮箱与签名。样本 id、样本文件名与金标 id 都按 trace 目录（哈希）定：续跑换了第几次 run 的编号，
沿用的判分、用户裁定与金标仍指向原来那份 trace。

金标（plugin-evals/<插件>/gold/<id>.json）：用户在待审页裁定过的分歧样本与抽检样本（judgepending.py 写，
source = disagreement / spot-check）。每次判样本之前，先让评委把全部有效金标判一遍（active=false 的、所属条款
已退役的不判），按来源分开记一致率。判采信与否只用分歧来源：配置了阈值与启用所需条数、且分歧来源判成的金标
够条数时才校准，一致率低于阈值即「不采信」（trusted=false），不低于即采信（true）；没配置或条数不够即
「采信（未校准）」（trusted=null）。配置了、但因评委调用出错才不够条数时，运行判不完整，续跑时重判。

配置：plugin-evals/<插件>/judge-config.json（可缺省）：
    {"model": "claude-fable-5-1", "gold_agreement_threshold": 0.8, "gold_min_samples": 5}
评委模型优先级：compare --judge-model > 配置 model > 续跑时首跑记下的模型 > DEFAULT_MODEL（最贵一档）。
续跑沿用首跑的 --judge-model 与 --no-judge（记在 run.json 的 environment.judge）。
阈值、条数留空（null 或不写）即不启用校准。--no-judge 时不读本配置。
"""
import gzip
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import evalrun

DEFAULT_MODEL = 'claude-fable-5-1'     # 用户拍板：默认最贵一档（08 Comments），可配置
CONFIG_NAME = 'judge-config.json'
JUDGE_FILE = 'judge.json'
SAMPLES_DIR = 'samples'
GOLD_DIR = 'gold'
PASSES = 2
SPOT_CHECK_COUNT = 3
VERDICTS = ('pass', 'fail', 'unclear')
VERDICT_LABEL = {'pass': '通过', 'fail': '不通过', 'unclear': '判不了', None: '—'}
TRANSCRIPT_LIMIT = 80000                # 喂给评委的转录字符上限；超出保留头 1/4、尾 3/4
CALL_TIMEOUT_SEC = 900
SCHEMA_VERSION = 1

SYSTEM_PROMPT = (
    '你是离线评测的 AI 评委。你会读到一次 Claude Code 会话的用户请求、会话转录（助手回复、工具调用、工具结果）'
    '和一条判定标准。只依据转录里看得见的行为判断这次会话是否满足判定标准，不猜测转录之外发生过什么；'
    '转录可能被截断，截断处有标注。只输出一个 JSON 对象，不加任何其它文字：'
    '{"verdict": "pass" 或 "fail" 或 "unclear", "reason": "不超过 80 字的中文理由"}。'
    'pass = 满足判定标准；fail = 不满足；unclear = 转录不足以判断。')

_EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+')
_FM_RE = re.compile(r'\A---\s*\n(.*?)\n---\s*\n?', re.S)
_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
_CLAUSE_RE = re.compile(r'^C\d{3,}$')
FRONTMATTER_KEYS = ('rule', 'arms', 'clause')
KNOWN_ARMS = ('none', 'previous', 'current', 'current_with_env')   # armplan 的臂键
SOURCES = ('disagreement', 'spot-check')
SOURCE_LABEL = {'disagreement': '分歧样本', 'spot-check': '抽检样本'}


class JudgeConfigError(Exception):
    pass


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _sha(text, n=12):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:n]


# ---------------- 配置 ----------------

def plugin_evals_dir(run_dir):
    """runs/<run_id>/ 的上两级：plugin-evals/<插件>/。"""
    return Path(run_dir).parent.parent


def load_config(plugin_evals):
    """读 judge-config.json；不存在返回全空配置。值不合法抛 JudgeConfigError（对照开跑前就报，免得白跑）。"""
    p = Path(plugin_evals) / CONFIG_NAME
    cfg = {'model': None, 'gold_agreement_threshold': None, 'gold_min_samples': None, 'path': None}
    if not p.is_file():
        return cfg
    try:
        raw = json.loads(p.read_text(encoding='utf-8'))
    except ValueError as e:
        raise JudgeConfigError('%s 不是合法 JSON：%s' % (p, e))
    if not isinstance(raw, dict):
        raise JudgeConfigError('%s 顶层应是对象' % p)
    unknown = sorted(set(raw) - {'model', 'gold_agreement_threshold', 'gold_min_samples'})
    if unknown:
        raise JudgeConfigError('%s 有不认识的键：%s（可用：model、gold_agreement_threshold、gold_min_samples）'
                               % (p, '、'.join(unknown)))
    m, t, n = raw.get('model'), raw.get('gold_agreement_threshold'), raw.get('gold_min_samples')
    if m is not None and (not isinstance(m, str) or not m.strip()):
        raise JudgeConfigError('%s 的 model 应是非空字符串或 null' % p)
    if t is not None and (isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 <= t <= 1):
        raise JudgeConfigError('%s 的 gold_agreement_threshold 应是 0～1 的数或 null' % p)
    if n is not None and (isinstance(n, bool) or not isinstance(n, int) or n < 1):
        raise JudgeConfigError('%s 的 gold_min_samples 应是 ≥1 的整数或 null' % p)
    cfg.update(model=m, gold_agreement_threshold=t, gold_min_samples=n, path=CONFIG_NAME)
    return cfg


def resolve_options(opts, run_dir):
    """合并命令行（opts）、配置文件与续跑前的 judge.json，返回完整选项。opts 为 None 表示未指定（早于
    environment.judge 的运行续跑时也是 None）。enabled=False（--no-judge）时直接返回，不读配置。"""
    opts = dict(opts or {})
    if opts.get('enabled') is False:
        return {'enabled': False}
    cfg = opts.get('config') or load_config(plugin_evals_dir(run_dir))
    prev = _read_json(Path(run_dir) / JUDGE_FILE) or {}
    if opts.get('model'):
        model, source = opts['model'], '命令行 --judge-model'
    elif cfg.get('model'):
        model, source = cfg['model'], '配置 %s' % CONFIG_NAME
    elif prev.get('requested_model'):
        model, source = prev['requested_model'], '续跑沿用首跑'
    else:
        model, source = DEFAULT_MODEL, '默认（最贵一档）'
    return {'enabled': True, 'model': model, 'model_source': source, 'config': cfg,
            'runner': opts.get('runner'), 'concurrency': opts.get('concurrency')}


def _read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


# ---------------- 判定标准 ----------------

def _frontmatter(text):
    """极简 frontmatter：key: value，value 可写成 [a, b]。返回 (dict, 正文)。"""
    m = _FM_RE.match(text)
    if not m:
        return {}, text.strip()
    meta = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith('#') or ':' not in line:
            continue
        k, v = line.split(':', 1)
        v = v.strip().strip('"\'')
        if v.startswith('[') and v.endswith(']'):
            v = [x.strip().strip('"\'') for x in v[1:-1].split(',') if x.strip()]
        meta[k.strip()] = v
    return meta, text[m.end():].strip()


def case_criteria(evals_src, case):
    """用例 judge/*.md → [{id, text, rule, arms, clause, problems, fingerprint}]，按 id 排序。没有 judge/ 返回 []。
    problems：frontmatter 的未知键、未知臂名、条款 id 形态不对（check_criteria 据此在开跑前报错）。"""
    d = Path(evals_src) / case / 'judge'
    out = []
    if not d.is_dir():
        return out
    for f in sorted(d.glob('*.md')):
        raw = f.read_text(encoding='utf-8')
        meta, body = _frontmatter(raw)
        if not body:
            continue
        arms = meta.get('arms')
        arms = [arms] if isinstance(arms, str) else arms
        clause = meta.get('clause') or None
        problems = ['不认识的键 %s（只认 %s）' % (k, '、'.join(FRONTMATTER_KEYS))
                    for k in sorted(meta) if k not in FRONTMATTER_KEYS]
        problems += ['arms 里有不认识的臂名 %s（可用：%s）' % (a, '、'.join(KNOWN_ARMS))
                     for a in arms or [] if a not in KNOWN_ARMS]
        if clause is not None and (not isinstance(clause, str) or not _CLAUSE_RE.match(clause)):
            problems.append('clause 应是一个条款 id（形如 C001）：%r' % (clause,))
        out.append({'id': f.stem, 'text': body, 'rule': meta.get('rule') or None, 'arms': arms,
                    'clause': clause if isinstance(clause, str) else None, 'problems': problems,
                    'fingerprint': 'sha256:' + _sha(raw, 64)})
    return out


def check_criteria(evals_src, cases):
    """开跑前查各用例 judge/*.md 的 frontmatter：有问题抛 JudgeConfigError（列全），免得各臂白跑。"""
    bad = ['%s/judge/%s.md：%s' % (c, crit['id'], p) for c in cases for crit in case_criteria(evals_src, c)
           for p in crit['problems']]
    if bad:
        raise JudgeConfigError('AI 评委判定标准的 frontmatter 有问题：\n  ' + '\n  '.join(bad))


def _clause_status(plugin_evals):
    """(清单里全部 id 集合或 None, 退役 id 集合)。清单读不出时当作没有清单（金标照常参与，告警里不判条款）。"""
    from . import clauses     # 延迟导入：clauses → pending → resume → compare → judge
    try:
        lst = clauses._read_json(Path(plugin_evals) / clauses.LIST_FILE)
    except (OSError, ValueError):
        return None, set()
    if not isinstance(lst, dict):
        return None, set()
    return {c.get('id') for c in lst.get('clauses') or [] if isinstance(c, dict)}, set(clauses.retired_ids(lst))


def case_prompt(evals_src, case):
    p = Path(evals_src) / case / 'prompt.md'
    if not p.is_file():
        return '（用例没有 prompt.md）'
    return _frontmatter(p.read_text(encoding='utf-8'))[1]


# ---------------- 转录 ----------------

def _clip(s, n):
    s = s if isinstance(s, str) else json.dumps(s, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + '…（截断，原长 %d 字）' % len(s)


def _content_text(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return '\n'.join(x.get('text', '') if isinstance(x, dict) else str(x) for x in c)
    return json.dumps(c, ensure_ascii=False)


def render_transcript(lines, limit=TRANSCRIPT_LIMIT):
    """stream-json trace → 给评委与用户读的转录。只留助手文字、工具调用与工具结果、最终回复；
    hook 输出、init（插件清单）与 thinking 不进转录：评委据此看不出是哪一臂，判法不受「装没装插件」左右。"""
    out, last_text = [], None
    for o in lines:
        if not isinstance(o, dict):
            continue
        sub = '[子代理] ' if o.get('parent_tool_use_id') else ''
        t = o.get('type')
        if t == 'assistant':
            for c in (o.get('message') or {}).get('content') or []:
                if not isinstance(c, dict):
                    continue
                if c.get('type') == 'text' and c.get('text', '').strip():
                    last_text = c['text']
                    out.append('%s[助手]\n%s' % (sub, c['text']))
                elif c.get('type') == 'tool_use':
                    out.append('%s[工具调用 %s] %s' % (sub, c.get('name'), _clip(c.get('input'), 3000)))
        elif t == 'user':
            content = (o.get('message') or {}).get('content')
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get('type') == 'tool_result':
                        flag = '（出错）' if c.get('is_error') else ''
                        out.append('%s[工具结果%s] %s' % (sub, flag, _clip(_content_text(c.get('content')), 3000)))
        elif t == 'result':
            res = o.get('result')
            if isinstance(res, str) and res.strip() and res != last_text:
                out.append('[最终回复]\n%s' % res)
    text = '\n\n'.join(out) or '（转录里没有助手回复与工具调用）'
    if len(text) > limit:
        head = limit // 4
        text = text[:head] + '\n\n…（中间截断 %d 字）…\n\n' % (len(text) - limit) + text[-(limit - head):]
    return text


def read_trace_lines(path):
    p = Path(path)
    if not p.is_file():
        return None
    opener = gzip.open if p.suffix == '.gz' else open
    out = []
    with opener(p, 'rt', encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _scrub_obj(o, home):
    if isinstance(o, str):
        return _EMAIL_RE.sub('<email>', o)
    if isinstance(o, list):
        return [_scrub_obj(x, home) for x in o]
    if isinstance(o, dict):
        return {k: _scrub_obj(v, home) for k, v in o.items() if k != 'signature'}
    return o


def scrub(obj, home=None):
    """写进被测仓（会入库）前：家目录前缀换成 ~，邮箱换成 <email>，去掉 thinking 签名。"""
    from . import record
    return _scrub_obj(record.scrub_home(obj, home), home)


def sample_lines(lines):
    """入库样本只留评委与用户要读的三类行：assistant（去掉 thinking 块）、user 里的 tool_result、result。
    system/init（插件清单、本机路径）、hook 输出、用户原始请求行等整行不入库。"""
    out = []
    for o in lines:
        if not isinstance(o, dict):
            continue
        t = o.get('type')
        if t == 'assistant':
            msg = dict(o.get('message') or {})
            content = msg.get('content')
            if isinstance(content, list):
                msg['content'] = [c for c in content
                                  if not (isinstance(c, dict) and c.get('type') in ('thinking', 'redacted_thinking'))]
            out.append(dict(o, message=msg))
        elif t == 'user':
            content = (o.get('message') or {}).get('content')
            if isinstance(content, list):
                results = [c for c in content if isinstance(c, dict) and c.get('type') == 'tool_result']
                if results:
                    out.append(dict(o, message=dict(o.get('message') or {}, content=results)))
        elif t == 'result':
            out.append(o)
    return out


def sample_file_name(sample):
    """样本文件按 trace 目录的哈希命名：续跑换了第几次 run 的编号也不会覆盖或错指。"""
    return '%s/%s--%s--%s.jsonl.gz' % (SAMPLES_DIR, sample['arm'], sample['case'].replace('/', '__'),
                                       _sha(sample['trace_dir'] or sample['key']))


def store_sample(trace_path, dest, home=None):
    """trace.jsonl → 只留三类行（sample_lines），去家目录、邮箱、thinking 签名后 gzip（mtime=0，同内容同字节）。"""
    lines = read_trace_lines(trace_path)
    if lines is None:
        return False
    body = ''.join(json.dumps(scrub(o, home), ensure_ascii=False) + '\n' for o in sample_lines(lines))
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + '.tmp')
    with open(tmp, 'wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as gz:
            gz.write(body.encode('utf-8'))
    os.replace(tmp, dest)
    return True


# ---------------- 调评委 ----------------

def build_prompt(criterion_text, prompt, transcript):
    return ('## 判定标准\n\n%s\n\n## 用户请求\n\n%s\n\n## 会话转录\n\n%s\n\n'
            '## 输出\n\n只输出 JSON：{"verdict": "pass|fail|unclear", "reason": "…"}' % (criterion_text, prompt, transcript))


def parse_verdict(text):
    """评委回复 → (verdict, reason)；取第一个能解析、带合法 verdict 的 JSON 对象。解析不了抛 ValueError。"""
    s = (text or '').strip()
    for m in re.finditer(r'\{', s):
        depth = 0
        for j in range(m.start(), len(s)):
            depth += {'{': 1, '}': -1}.get(s[j], 0)
            if depth == 0:
                try:
                    o = json.loads(s[m.start():j + 1])
                except ValueError:
                    break
                v = str(o.get('verdict', '')).strip().lower() if isinstance(o, dict) else ''
                if v in VERDICTS:
                    return v, str(o.get('reason') or '')[:300]
                break
    raise ValueError('评委回复里没有带合法 verdict 的 JSON：%r' % s[:200])


def claude_runner(claude, env):
    """真调评委：claude -p --safe-mode（不加载用户的 CLAUDE.md、插件、hook，判法不受评测者自己的配置影响），
    不给任何工具，在空临时目录里跑，不留会话。返回 {text, models, usage, cost_usd, error}。"""
    def run(prompt, model):
        cwd = tempfile.mkdtemp(prefix='devkit-plugin-eval-judge-')
        try:
            cmd = [str(claude), '-p', '--safe-mode', '--model', model, '--output-format', 'json', '--tools', '',
                   '--no-session-persistence', '--system-prompt', SYSTEM_PROMPT]
            try:
                p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding='utf-8',
                                   cwd=cwd, env=env, timeout=CALL_TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                return {'error': '评委调用超时（%d 秒）' % CALL_TIMEOUT_SEC}
            except OSError as e:
                return {'error': '评委调用起不来：%s' % e}
            try:
                o = json.loads(p.stdout)
            except ValueError:
                return {'error': '评委输出不是 JSON（退出码 %s）：%s' % (p.returncode, (p.stderr or p.stdout)[:300])}
            usage = {}
            for m, u in (o.get('modelUsage') or {}).items():
                usage[m] = {'input_tokens': u.get('inputTokens') or 0, 'output_tokens': u.get('outputTokens') or 0,
                            'cache_read_input_tokens': u.get('cacheReadInputTokens') or 0,
                            'cache_creation_input_tokens': u.get('cacheCreationInputTokens') or 0,
                            'cost_usd': u.get('costUSD') or 0}
            out = {'text': o.get('result'), 'models': sorted(usage), 'usage': usage,
                   'cost_usd': o.get('total_cost_usd') or 0}
            if o.get('is_error') or p.returncode != 0:
                out['error'] = '评委调用失败（退出码 %s）：%s' % (p.returncode, str(o.get('result') or p.stderr)[:300])
            return out
        finally:
            shutil.rmtree(cwd, ignore_errors=True)
    return run


def _judge_once(runner, prompt, model):
    res = runner(prompt, model) or {}
    entry = {'verdict': None, 'reason': None, 'error': res.get('error'), 'models': res.get('models') or [],
             'usage': res.get('usage') or {}, 'cost_usd': res.get('cost_usd') or 0}
    if not entry['error']:
        try:
            entry['verdict'], entry['reason'] = parse_verdict(res.get('text'))
        except ValueError as e:
            entry['error'] = str(e)
    return entry


# ---------------- 样本 ----------------

def _rule_result(agg_case, run_idx, rule):
    if not rule:
        return None
    runs = (agg_case.get('arms') or {}).get('with') or []
    if run_idx >= len(runs):
        return None
    for g in runs[run_idx].get('graders') or []:
        if g.get('name') == rule:
            return bool(g.get('passed'))
    return None


def _case_key(case):
    d = (case.get('dir') or '').replace('\\', '/')
    return d[len('evals/'):] if d.startswith('evals/') else (d or case.get('name'))


def sample_id(trace_dir, key, criterion):
    """样本 id 按（trace 目录、判定标准）定；没有 trace 目录时退回按样本 key。"""
    return 's-' + _sha('%s#%s' % (trace_dir, criterion) if trace_dir else key, 10)


def grader_problems(arm_records, labels, evals_src):
    """rule 指向的 grader 在该用例的汇总里不存在：[告警文字]（开跑前读不到 grader 名单，判分时才查）。"""
    out, seen = [], set()
    for arm in labels:
        agg = (arm_records.get(arm) or {}).get('_agg')
        for case in (agg or {}).get('cases', []):
            ck = _case_key(case)
            names = {g.get('name') for run in (case.get('arms') or {}).get('with') or []
                     for g in run.get('graders') or []}
            names |= {g.get('name') for g in case.get('graders') or [] if isinstance(g, dict)}
            if not names:
                continue
            for c in case_criteria(evals_src, ck):
                if c['rule'] and c['rule'] not in names and (ck, c['id']) not in seen:
                    seen.add((ck, c['id']))
                    out.append('%s/judge/%s.md 的 rule 指向的 grader「%s」在该用例里不存在（有：%s），本条不与规则对照'
                               % (ck, c['id'], c['rule'], '、'.join(sorted(n for n in names if n))))
    return out


def collect_samples(arm_records, labels, evals_src, trace_key):
    """从各臂汇总里列出要判的样本。arm_records[臂]['_agg'] 是 eval 汇总（带 devkitTraceDir）。"""
    samples = []
    crit_cache = {}
    for arm in labels:
        agg = (arm_records.get(arm) or {}).get('_agg')
        if not agg:
            continue
        for case in agg.get('cases', []):
            ck = _case_key(case)
            if ck not in crit_cache:
                crit_cache[ck] = case_criteria(evals_src, ck)
            for i, run in enumerate((case.get('arms') or {}).get('with') or []):
                if run.get('error'):
                    continue            # 无效 run 不计分，也不交评委
                for c in crit_cache[ck]:
                    if c['arms'] and arm not in c['arms']:
                        continue
                    key = '%s/%s/%d/%s' % (arm, ck, i + 1, c['id'])
                    trace_dir = run.get(trace_key)
                    samples.append({
                        'id': sample_id(trace_dir, key, c['id']), 'key': key, 'arm': arm, 'arm_label': labels[arm],
                        'case': ck, 'run': i + 1, 'criterion': c['id'], 'criterion_fingerprint': c['fingerprint'],
                        'clause': c.get('clause'),
                        'rule_grader': c['rule'], 'rule_passed': _rule_result(case, i, c['rule']),
                        'trace_dir': trace_dir, 'passes': [], 'status': None, 'disagreement': None,
                        'spot_check': False, 'sample_file': None, 'user': None, 'final_verdict': None,
                        'gold_id': None, '_criterion': c,
                    })
    return samples


def classify(sample):
    """两遍判完后定状态：error / disagreement（two-pass / unclear / rule-conflict）/ agreed。"""
    ps = sample['passes']
    if len(ps) < PASSES or any(p.get('error') or p.get('verdict') is None for p in ps):
        return 'error', None
    vs = [p['verdict'] for p in ps]
    if len(set(vs)) > 1:
        return 'disagreement', 'two-pass'
    if vs[0] == 'unclear':
        return 'disagreement', 'unclear'
    if sample.get('rule_passed') is not None and (vs[0] == 'pass') != sample['rule_passed']:
        return 'disagreement', 'rule-conflict'
    return 'agreed', None


DISAGREEMENT_LABEL = {'two-pass': '两遍判法不同', 'unclear': '两遍都判不了', 'rule-conflict': '评委与规则冲突'}


def final_verdict(sample):
    """用户裁定（通过 / 不通过）优先；否则两遍一致的评委判法；分歧未裁定、出错、判不了为 None。"""
    u = sample.get('user') or {}
    if u.get('verdict') in ('pass', 'fail'):
        return u['verdict']
    if u.get('verdict') == 'unclear':
        return None
    if sample.get('status') == 'agreed' and sample['passes'][0]['verdict'] in ('pass', 'fail'):
        return sample['passes'][0]['verdict']
    return None


def compute_scores(samples, exclude=()):
    """AI 判分：样本通过记 1、不通过记 0；用例分 = 该臂该用例已定样本的均值；臂分 = 有分用例均值。
    差 = 当前版 − 不装，只在两臂都有分的用例上算。只作信息，不改规则分与「是否通过」。
    exclude：回归守护用例（基线已满足，票 11），不计入差（spec 2.3「不计相对不装的差」），见 delta_excluding。"""
    per = {}
    for s in samples:
        v = s.get('final_verdict')
        if v is None:
            continue
        per.setdefault(s['arm'], {}).setdefault(s['case'], []).append(1.0 if v == 'pass' else 0.0)
    arms = {}
    for arm, cases in per.items():
        cs = {c: sum(xs) / len(xs) for c, xs in cases.items()}
        arms[arm] = {'score': sum(cs.values()) / len(cs), 'cases': cs}
    return delta_excluding({'arms': arms}, exclude)


def delta_excluding(scores, exclude=()):
    """按 scores['arms'] 重算「当前版 − 不装」的差，跳过 exclude 里的用例；原地改并返回 scores。
    excluded_baseline_satisfied 记实际被剔除的用例（两臂都有分、本该进差的那些），报告据此注明「不含 N 个」。"""
    arms = scores.get('arms') or {}
    cur, none = (arms.get('current') or {}).get('cases') or {}, (arms.get('none') or {}).get('cases') or {}
    both = set(cur) & set(none)
    common = sorted(both - set(exclude))
    scores['delta_current_vs_none'] = (sum(cur[c] - none[c] for c in common) / len(common)) if common else None
    scores['excluded_baseline_satisfied'] = sorted(both & set(exclude))
    return scores


def summarize(doc):
    """judge.json → run.json 的 judge 字段（报告据此渲染）：不含评委理由全文以外的大块内容。"""
    samples = doc.get('samples') or []
    keys = ('id', 'arm', 'arm_label', 'case', 'run', 'criterion', 'status', 'disagreement', 'spot_check',
            'rule_grader', 'rule_passed', 'final_verdict', 'gold_id', 'sample_file')
    flagged = [dict({k: s.get(k) for k in keys}, verdicts=[p.get('verdict') for p in s.get('passes') or []],
                    user_verdict=(s.get('user') or {}).get('verdict'))
               for s in samples if s.get('status') in ('disagreement', 'error') or s.get('spot_check')]
    count = lambda st: sum(1 for s in samples if s.get('status') == st)
    return {
        'file': JUDGE_FILE, 'model': doc.get('model'), 'requested_model': doc.get('requested_model'),
        'model_source': doc.get('model_source'), 'passes': PASSES, 'trusted': doc.get('trusted'),
        'untrusted_reason': doc.get('untrusted_reason'), 'complete': doc.get('complete'),
        'samples': len(samples), 'agreed': count('agreed'), 'disagreements': count('disagreement'),
        'errors': count('error'), 'spot_checks': sum(1 for s in samples if s.get('spot_check')),
        'user_decided': sum(1 for s in samples if s.get('user')),
        'gold': {k: (doc.get('gold') or {}).get(k) for k in ('total', 'judged', 'agreed', 'agreement_rate', 'threshold',
                                                           'min_samples', 'enabled', 'state', 'note', 'by_source',
                                                           'basis_source', 'call_errors', 'retired_clauses')},
        'warnings': doc.get('warnings') or [],
        'scores': doc.get('scores'), 'usage': doc.get('usage'), 'flagged': flagged,
        'arm_labels': {s['arm']: s.get('arm_label') for s in samples},
    }


# ---------------- 金标 ----------------

def gold_source(g):
    """金标来源；早于来源字段的金标都是分歧样本裁定的（票 09 首版只存分歧）。"""
    return g.get('source') if g.get('source') in SOURCES else 'disagreement'


def load_gold(plugin_evals, retired=()):
    """有效金标：active 不是 false、用户裁定为通过 / 不通过、所属条款没有退役（clause 在 retired 里的不参与校准）。"""
    d = Path(plugin_evals) / GOLD_DIR
    out = []
    if not d.is_dir():
        return out
    for f in sorted(d.glob('*.json')):
        g = _read_json(f)
        if isinstance(g, dict) and g.get('active', True) and g.get('user_verdict') in ('pass', 'fail') \
                and g.get('clause') not in retired:
            out.append(g)
    return out


def _rate(items):
    judged = [i for i in items if i['match'] is not None]
    agreed = sum(1 for i in judged if i['match'])
    return {'total': len(items), 'judged': len(judged), 'agreed': agreed,
            'agreement_rate': agreed / len(judged) if judged else None}


def calibrate(plugin_evals, cfg, judge_fn):
    """先判金标：每条判一遍，与用户裁定比；一致率按来源分开记，判采信只看分歧来源。judge_fn(prompt) -> 判分条目。
    state：not-configured / insufficient（金标本身不够）/ insufficient-errors（够，但调用出错后判成的不够）/ enabled。"""
    _, retired = _clause_status(plugin_evals)
    gold = load_gold(plugin_evals, retired)
    items = []
    for g in gold:
        src = gold_source(g)
        lines = read_trace_lines(Path(plugin_evals) / (g.get('sample_file') or ''))
        if lines is None:
            items.append({'id': g.get('id'), 'source': src, 'gold_verdict': g['user_verdict'], 'ai_verdict': None,
                          'match': None, 'error': '样本 trace 不在仓里：%s' % g.get('sample_file')})
            continue
        e = judge_fn(build_prompt(g.get('criterion_text') or '', g.get('prompt') or '', render_transcript(lines)))
        items.append({'id': g.get('id'), 'source': src, 'gold_verdict': g['user_verdict'], 'ai_verdict': e['verdict'],
                      'reason': e['reason'], 'error': e['error'], '_entry': e, 'call_error': bool(e['error']),
                      'match': None if e['error'] else e['verdict'] == g['user_verdict']})
    overall = _rate(items)
    by_source = {src: _rate([i for i in items if i['source'] == src]) for src in SOURCES}
    basis = by_source['disagreement']
    call_errors = sum(1 for i in items if i['source'] == 'disagreement' and i.get('call_error'))
    t, n = cfg.get('gold_agreement_threshold'), cfg.get('gold_min_samples')
    if t is None or n is None:
        state, note = 'not-configured', '未配置一致率阈值或启用所需条数（%s），不启用校准，只记一致率' % CONFIG_NAME
    elif basis['judged'] >= n:
        state, note = 'enabled', '已启用校准（只按分歧来源的一致率判）'
    elif basis['judged'] + call_errors >= n:
        state, note = 'insufficient-errors', ('分歧来源的金标够 %d 条，但 %d 条评委调用出错，判成 %d 条不足启用所需 %d 条；'
                                              '运行判不完整，续跑时重判' % (n, call_errors, basis['judged'], n))
    else:
        state, note = 'insufficient', '分歧来源判成的金标 %d 条，不足启用所需 %d 条，不启用校准' % (basis['judged'], n)
    return dict(overall, threshold=t, min_samples=n, enabled=state == 'enabled', state=state, note=note,
                by_source=by_source, basis_source='disagreement', call_errors=call_errors,
                retired_clauses=sorted(retired), items=items)


# ---------------- 主流程 ----------------

def run(*, arm_records, labels, evals_src, run_dir, run_id, opts, claude, env, trace_key, data_dir,
        concurrency=3, log=print, now=None):
    """对一次对照做 AI 评委判分。没有任何用例声明判定标准、或 opts 关闭时返回 None（不调评委、不写 judge.json）。
    返回 (judge.json 文档, 不完整原因列表)。judge.json 由调用方写。"""
    now = now or (lambda: datetime.now(timezone.utc))
    if not opts.get('enabled'):
        return None, []
    samples = collect_samples(arm_records, labels, evals_src, trace_key)
    if not samples:
        return None, []
    plugin_evals = plugin_evals_dir(run_dir)
    runner = opts.get('runner') or claude_runner(claude, env)
    model = opts['model']
    started = _iso(now())
    prev = {}
    for old in (_read_json(Path(run_dir) / JUDGE_FILE) or {}).get('samples') or []:
        # 续跑按（trace 目录、判定标准）对上首跑的样本：补跑会让同一份 trace 的「第几次 run」编号变掉
        prev[(old.get('trace_dir'), old.get('criterion')) if old.get('trace_dir') else old.get('key')] = old

    def judge_fn(prompt):
        return _judge_once(runner, prompt, model)

    log('[AI 评委] 模型 %s（%s）：先判金标' % (model, opts.get('model_source')))
    gold = calibrate(plugin_evals, opts['config'], judge_fn)

    # 续跑：同一样本、同一份 trace、同一判定标准、两遍都没出错的，沿用首跑判分与用户裁定
    todo = []
    for s in samples:
        old = prev.get((s['trace_dir'], s['criterion']) if s['trace_dir'] else s['key'])
        if (old and old.get('trace_dir') == s['trace_dir']
                and old.get('criterion_fingerprint') == s['criterion_fingerprint'] and old.get('status') != 'error'
                and len(old.get('passes') or []) == PASSES):
            s['passes'], s['user'], s['gold_id'] = old['passes'], old.get('user'), old.get('gold_id')
            s['sample_file'] = old.get('sample_file')
            s['reused'], s['_was_spot'] = True, bool(old.get('spot_check'))
            continue
        trace = Path(data_dir) / s['trace_dir'] / 'trace.jsonl' if s['trace_dir'] else None
        lines = read_trace_lines(trace) if trace else None
        if lines is None:
            s['passes'] = [{'verdict': None, 'reason': None, 'error': '本机 trace 不在：%s' % s['trace_dir']}] * PASSES
            continue
        prompt = build_prompt(s['_criterion']['text'], case_prompt(evals_src, s['case']), render_transcript(lines))
        todo += [(s, prompt)] * PASSES
    log('[AI 评委] 样本 %d 个，本次要调评委 %d 次（每条两遍）' % (len(samples), len(todo)))
    workers = max(1, min(int(opts.get('concurrency') or concurrency or 1), 8))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda sp: judge_fn(sp[1]), todo))
    for (s, _), e in zip(todo, results):
        s['passes'].append(e)

    for s in samples:
        s['status'], s['disagreement'] = classify(s)
    agreed = [s for s in samples if s['status'] == 'agreed']
    kept = [s for s in agreed if s.get('_was_spot')]          # 续跑：首跑抽中的抽检照旧（可能已裁定）
    rest = [s for s in agreed if not s.get('_was_spot')]
    for s in kept + random.Random(run_id).sample(rest, min(max(0, SPOT_CHECK_COUNT - len(kept)), len(rest))):
        s['spot_check'] = True
    for s in samples:
        s['final_verdict'] = final_verdict(s)
        if (s['status'] == 'disagreement' or s['spot_check']) and s['trace_dir']:
            rel = sample_file_name(s)
            if s.get('sample_file') == rel and (Path(run_dir) / rel).is_file():
                continue
            if store_sample(Path(data_dir) / s['trace_dir'] / 'trace.jsonl', Path(run_dir) / rel):
                s['sample_file'] = rel

    # 用量与模型：沿用样本的判分条目带着首跑记下的 usage，一并合计（续跑后是整份 judge.json 的总数）
    entries = [p for s in samples for p in s['passes']]
    entries += [i['_entry'] for i in gold['items'] if '_entry' in i]
    models = sorted({m for e in entries for m in e.get('models') or []})
    usage = _merge_usage(entries)
    errors = [s for s in samples if s['status'] == 'error']
    reasons = []
    if errors:
        reasons.append('AI 评委：%d 个样本判分出错（%s），续跑时重判' % (
            len(errors), '；'.join(sorted({next((p['error'] for p in s['passes'] if p.get('error')), '?')[:120]
                                         for s in errors}))[:400]))
    if gold['state'] == 'insufficient-errors':
        reasons.append('AI 评委：金标校准有 %d 条评委调用出错，分歧来源判成 %d 条不足启用所需 %d 条，续跑时重判' % (
            gold['call_errors'], gold['by_source']['disagreement']['judged'], gold['min_samples']))
    trusted, why = None, None          # null = 采信（未校准）
    basis = gold['by_source']['disagreement']
    if gold['enabled']:
        trusted = basis['agreement_rate'] >= gold['threshold']
        if not trusted:
            why = '分歧来源的金标一致率 %.2f 低于阈值 %.2f（判成 %d 条，一致 %d 条）' % (
                basis['agreement_rate'], gold['threshold'], basis['judged'], basis['agreed'])
    warnings = grader_problems(arm_records, labels, evals_src)
    known, retired = _clause_status(plugin_evals)
    for ck, cid, clause in sorted({(s['case'], s['criterion'], s.get('clause')) for s in samples if s.get('clause')}):
        if clause in retired:
            warnings.append('%s/judge/%s.md 所属条款 %s 已退役：这条判定标准上的金标不参与校准，用例待改挂' % (ck, cid, clause))
        elif known is not None and clause not in known:
            warnings.append('%s/judge/%s.md 所属条款 %s 不在条款清单里' % (ck, cid, clause))
        elif known is None:
            warnings.append('%s/judge/%s.md 声明了所属条款 %s，但还没有条款清单可核对' % (ck, cid, clause))
    for i in gold['items']:
        i.pop('_entry', None)
        i.pop('call_error', None)
    cases_info = {}
    for s in samples:   # 待审页与金标要用的用例原文：用例 prompt 与判定标准（都来自已入库的用例目录）
        info = cases_info.setdefault(s['case'], {'prompt': case_prompt(evals_src, s['case']), 'criteria': {}})
        info['criteria'][s['criterion']] = s['_criterion']['text']
    for s in samples:
        s.pop('_criterion', None)
        s.pop('reused', None)
        s.pop('_was_spot', None)
    doc = {
        'schema_version': SCHEMA_VERSION, 'run_id': run_id, 'requested_model': model,
        'model': model if (not models or model in models) else models[0],   # 实际所用：以评委回报的模型为准
        'models_used': models, 'model_source': opts.get('model_source'), 'passes': PASSES,
        'started_at': started, 'finished_at': _iso(now()),
        'config': {k: opts['config'].get(k) for k in ('path', 'model', 'gold_agreement_threshold', 'gold_min_samples')},
        'gold': gold, 'trusted': trusted, 'untrusted_reason': why,
        'complete': not errors and gold['state'] != 'insufficient-errors', 'warnings': warnings,
        'spot_check_rule': '从两遍一致的样本里以 run_id 为种子随机抽 %d 条，不足全抽' % SPOT_CHECK_COUNT,
        'cases': cases_info, 'samples': samples, 'scores': compute_scores(samples), 'usage': usage,
    }
    log('[AI 评委] 两遍一致 %d、分歧 %d、出错 %d；抽检 %d；金标一致率 %s%s' % (
        len(agreed), sum(1 for s in samples if s['status'] == 'disagreement'), len(errors),
        sum(1 for s in samples if s['spot_check']),
        '—' if gold['agreement_rate'] is None else '%.2f' % gold['agreement_rate'],
        {False: '；AI 判分不采信', None: '；采信（未校准）'}.get(trusted, '')))
    return doc, reasons


def _merge_usage(entries):
    keys = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'cost_usd')
    total = {k: 0 for k in keys}
    by_model = {}
    for e in entries:
        for m, u in (e.get('usage') or {}).items():
            acc = by_model.setdefault(m, {k: 0 for k in keys})
            for k in keys:
                acc[k] += u.get(k) or 0
                total[k] += u.get(k) or 0
    total['calls'] = len(entries)
    total['by_model'] = by_model
    total['cost_basis'] = '按标价（list price）估算，订阅用户只作信息'
    return total
