"""条款清单的 AI 一侧（票 10）：抽取与增量重抽的提示词、输出 schema、调 `claude -p` 与校验。

调用口径：`claude -p --output-format json --json-schema <schema>`，结果取 `structured_output`。
- 不给工具（`--tools ""`）、不加载设置源（`--setting-sources ""`，用户插件的 hook 不往抽取会话里注入）、
  不连 MCP（`--strict-mcp-config`）、不落会话（`--no-session-persistence`）。不用 `--bare`：它只认 API key，
  订阅用户的 OAuth 登录态在 bare 下读不到。
- 模型缺省 DEFAULT_MODEL（spec「2.4」AI 评委默认最贵一档，抽取沿用同一档，可由参数改）。
- 只读注入文字、旧清单与差异，不读插件其它文件（spec「2.2」第 2 步：「AI 只读旧清单加新旧注入文本的差异」）。

模型只给判定标准与新增条款的临时引用（N1、N2…），id 一律由程序分配（clauses.allocate_ids），保证永不复用。
"""
import json
import re
import subprocess

DEFAULT_MODEL = 'claude-fable-5-1'
CALL_TIMEOUT_SEC = 900
EVENTS = ('SessionStart', 'UserPromptSubmit', 'SubagentStart')
RETIRE_REASONS = ('split', 'merge', 'delete', 'criterion-changed')
_USAGE_LIMIT_RE = re.compile(r'usage limit|rate limit|limit reached|429|overloaded', re.IGNORECASE)
_REF_RE = re.compile(r'^N\d+$')

SYSTEM_PROMPT = '你是 Claude Code 插件评测里的条款清单维护者。只输出符合给定 JSON Schema 的结果，不输出别的文字。'

_EVENT_NOTE = ('注入文字按事件分节：SessionStart 在每次会话开头注入，UserPromptSubmit 在用户每次提问时注入，'
               'SubagentStart 在每个子代理启动时注入（子代理读到的版本）。')

_CLAUSE_RULES = '''条款的写法：
- 条款 = 一个可以单独判定是否遵守的行为要求。判定标准写成一句话：评委读完一次会话的转录，据此能判「遵守 / 违反 / 不适用」。
- 一条只管一件可观察的行为；原文一句里有两个独立要求，拆成两条。
- 判定标准写行为本身，不照抄原文措辞，不引用原文的章节编号（编号会漂移）；用原文的语言写（中文原文就写中文）。
- 背景、理由、示例、授权声明、术语解释这类不要求模型做或不做什么的文字，不成条款。
- 同一要求在几个事件里重复出现，只算一条，events 列出它出现的全部事件。'''

EXTRACT_SCHEMA = {
    'type': 'object',
    'properties': {
        'clauses': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'criterion': {'type': 'string'},
                    'events': {'type': 'array', 'items': {'type': 'string', 'enum': list(EVENTS)}},
                },
                'required': ['criterion', 'events'],
            },
        },
    },
    'required': ['clauses'],
}

DELTA_SCHEMA = {
    'type': 'object',
    'properties': {
        'added': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'ref': {'type': 'string'},
                    'criterion': {'type': 'string'},
                    'events': {'type': 'array', 'items': {'type': 'string', 'enum': list(EVENTS)}},
                },
                'required': ['ref', 'criterion', 'events'],
            },
        },
        'rewritten': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {'id': {'type': 'string'}, 'criterion': {'type': 'string'}},
                'required': ['id', 'criterion'],
            },
        },
        'retired': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'id': {'type': 'string'},
                    'reason': {'type': 'string', 'enum': list(RETIRE_REASONS)},
                    'replaced_by': {'type': 'array', 'items': {'type': 'string'}},
                    'rehang_hint': {'type': 'string'},
                },
                'required': ['id', 'reason', 'replaced_by', 'rehang_hint'],
            },
        },
    },
    'required': ['added', 'rewritten', 'retired'],
}


class ClauseAIError(Exception):
    pass


def extract_prompt(plugin_name, injection_text):
    return '\n\n'.join([
        '下面是 Claude Code 插件 `%s` 注入给模型的全部文字。%s' % (plugin_name, _EVENT_NOTE),
        '把它拆成条款清单。',
        _CLAUSE_RULES,
        '不写编号与 id，id 由程序分配。',
        '<injection>\n%s\n</injection>' % injection_text,
    ])


def delta_prompt(plugin_name, old_clauses, diff_text):
    """old_clauses：[{id, criterion, events, status, replaced_by?}]，含已退役的（退役 id 不得再用）。"""
    listing = json.dumps([{k: c.get(k) for k in ('id', 'criterion', 'events', 'status', 'replaced_by') if k in c}
                          for c in old_clauses], ensure_ascii=False, indent=1)
    return '\n\n'.join([
        '插件 `%s` 的注入文字改了。下面给你两样：旧条款清单（含已退役条款），以及新旧注入文字的差异（unified diff，'
        '`-` 行是旧文字、`+` 行是新文字）。%s只依据这两样产出条款清单的变更。' % (plugin_name, _EVENT_NOTE),
        _CLAUSE_RULES,
        '''变更的判法（id 绑判定标准、不绑措辞）：
- 判定标准没变、只是该写的一句话需要跟着新措辞改：放 rewritten，保留原 id。措辞变了但判定标准一句话不用改的，不列。
- 判定标准变了：旧 id 退役（reason=criterion-changed），added 里新增一条替代它。
- 一条拆成几条：旧 id 退役（reason=split），added 里新增几条，replaced_by 列出全部新条款。
- 几条合成一条：每个旧 id 都退役（reason=merge），added 里新增一条，各自的 replaced_by 指向它。
- 要求被删掉：退役（reason=delete），replaced_by 为空。
- 新出现的要求：放 added。
- 差异没碰到的条款不列。差异只改了排版、时间、与条款无关的文字时，三个列表都留空。
- 只能退役或改写 status 为 active 的条款；已退役的 id 永不复用。
- added 里每条给一个临时引用 ref（N1、N2…），不要编 id；replaced_by 里写新条款的 ref，或仍有效的旧 id。
- 每条退役写一句 rehang_hint：挂在旧条款上的用例应改挂到哪条、为什么；删除的写「用例经确认后删除」。''',
        '<old_clauses>\n%s\n</old_clauses>' % listing,
        '<diff>\n%s\n</diff>' % diff_text,
    ])


def build_command(claude, model, schema):
    return [str(claude), '-p', '--model', model, '--output-format', 'json', '--tools', '',
            '--no-session-persistence', '--strict-mcp-config', '--setting-sources', '',
            '--system-prompt', SYSTEM_PROMPT, '--json-schema', json.dumps(schema, ensure_ascii=False)]


def claude_caller(claude, *, env=None, cwd=None, timeout=CALL_TIMEOUT_SEC, run=subprocess.run):
    """返回 ai(prompt, schema, model) -> (结构化结果 dict, 元信息)。元信息：model、cost_usd、usage、duration_ms。
    失败（起不来、超时、非零退出、is_error、没有 structured_output）一律抛 ClauseAIError。"""
    def ai(prompt, schema, model):
        cmd = build_command(claude, model, schema)
        try:
            proc = run(cmd, input=prompt.encode('utf-8'), capture_output=True, timeout=timeout, env=env, cwd=cwd)
        except subprocess.TimeoutExpired:
            raise ClauseAIError('调 claude -p 超时（%d 秒）' % timeout)
        except OSError as e:
            raise ClauseAIError('调 claude -p 起不来：%s' % e)
        out = proc.stdout.decode('utf-8', errors='replace') if isinstance(proc.stdout, bytes) else (proc.stdout or '')
        err = proc.stderr.decode('utf-8', errors='replace') if isinstance(proc.stderr, bytes) else (proc.stderr or '')
        try:
            data = json.loads(out) if out.strip() else None
        except ValueError:
            data = None
        if proc.returncode != 0 or not isinstance(data, dict) or data.get('is_error'):
            detail = (data or {}).get('result') if isinstance(data, dict) else None
            text = ' '.join(str(x) for x in (detail, (data or {}).get('api_error_status') if isinstance(data, dict)
                                             else None, err[-300:]) if x)
            kind = '撞订阅用量限制或限流：' if _USAGE_LIMIT_RE.search(text) else ''
            raise ClauseAIError('%sclaude -p 失败（退出码 %s）：%s' % (kind, proc.returncode, text[:400] or '无输出'))
        obj = data.get('structured_output')
        if not isinstance(obj, dict):
            raise ClauseAIError('claude -p 没有返回 structured_output（result 前 200 字：%s）'
                                % str(data.get('result'))[:200])
        meta = {'model': model, 'cost_usd': data.get('total_cost_usd'), 'duration_ms': data.get('duration_ms'),
                'usage': {k: (data.get('usage') or {}).get(k) for k in
                          ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')},
                'cost_basis': '按标价（list price）估算，订阅用户只作信息'}
        return obj, meta
    return ai


def _clean_events(events):
    out = [e for e in (events or []) if e in EVENTS]
    return sorted(set(out), key=EVENTS.index)


def validate_extract(obj):
    """返回 [{criterion, events}]；结构不对抛 ClauseAIError。"""
    items = obj.get('clauses') if isinstance(obj, dict) else None
    if not isinstance(items, list) or not items:
        raise ClauseAIError('抽取结果里没有条款')
    out = []
    for i, c in enumerate(items, 1):
        crit = (c or {}).get('criterion') if isinstance(c, dict) else None
        if not isinstance(crit, str) or not crit.strip():
            raise ClauseAIError('抽取结果第 %d 条没有判定标准' % i)
        out.append({'criterion': ' '.join(crit.split()), 'events': _clean_events(c.get('events'))})
    return out


def validate_delta(obj, old_clauses):
    """校验增量变更，返回规整后的 {added, rewritten, retired}（引用仍是 ref，id 由调用方分配后替换）。

    规则：rewritten / retired 的 id 必须是旧清单里 active 的条款，同一 id 不能既改写又退役、不能退役两次；
    added 的 ref 形如 N1 且不重复；replaced_by 只能写本次 added 的 ref 或仍有效（且不在本次退役）的旧 id；
    delete 的 replaced_by 必须为空，其余退役原因必须至少有一个替代；split 至少两个替代。"""
    if not isinstance(obj, dict):
        raise ClauseAIError('增量结果不是对象')
    active = {c['id'] for c in old_clauses if c.get('status', 'active') == 'active'}
    known = {c['id'] for c in old_clauses}
    added, refs = [], set()
    for i, a in enumerate(obj.get('added') or [], 1):
        ref = (a or {}).get('ref') if isinstance(a, dict) else None
        crit = a.get('criterion') if isinstance(a, dict) else None
        if not isinstance(ref, str) or not _REF_RE.match(ref) or ref in refs:
            raise ClauseAIError('新增第 %d 条的 ref %r 不合法或重复（应为 N1、N2…）' % (i, ref))
        if not isinstance(crit, str) or not crit.strip():
            raise ClauseAIError('新增 %s 没有判定标准' % ref)
        refs.add(ref)
        added.append({'ref': ref, 'criterion': ' '.join(crit.split()), 'events': _clean_events(a.get('events'))})
    touched = set()
    rewritten = []
    for r in obj.get('rewritten') or []:
        cid = (r or {}).get('id') if isinstance(r, dict) else None
        crit = r.get('criterion') if isinstance(r, dict) else None
        if cid not in active:
            raise ClauseAIError('改写的 %r 不是旧清单里有效的条款%s' % (cid, '（已退役）' if cid in known else ''))
        if cid in touched:
            raise ClauseAIError('条款 %s 在变更里出现了两次' % cid)
        if not isinstance(crit, str) or not crit.strip():
            raise ClauseAIError('改写的 %s 没有新判定标准' % cid)
        touched.add(cid)
        rewritten.append({'id': cid, 'criterion': ' '.join(crit.split())})
    retired = []
    retiring = {r.get('id') for r in obj.get('retired') or [] if isinstance(r, dict)}
    for r in obj.get('retired') or []:
        cid = (r or {}).get('id') if isinstance(r, dict) else None
        if cid not in active:
            raise ClauseAIError('退役的 %r 不是旧清单里有效的条款%s' % (cid, '（已退役）' if cid in known else ''))
        if cid in touched:
            raise ClauseAIError('条款 %s 在变更里出现了两次' % cid)
        touched.add(cid)
        reason = r.get('reason')
        if reason not in RETIRE_REASONS:
            raise ClauseAIError('退役 %s 的原因 %r 不在 %s 之内' % (cid, reason, '、'.join(RETIRE_REASONS)))
        repl = list(dict.fromkeys(x for x in (r.get('replaced_by') or []) if isinstance(x, str)))
        for x in repl:
            if x not in refs and not (x in active and x not in retiring):
                raise ClauseAIError('退役 %s 的替代 %r 既不是本次新增的 ref，也不是仍有效的旧条款' % (cid, x))
        if reason == 'delete' and repl:
            raise ClauseAIError('退役 %s 原因是删除，不应写替代条款' % cid)
        if reason != 'delete' and not repl:
            raise ClauseAIError('退役 %s（%s）没写替代条款' % (cid, reason))
        if reason == 'split' and len(repl) < 2:
            raise ClauseAIError('退役 %s 原因是拆分，替代条款至少两条' % cid)
        hint = r.get('rehang_hint') if isinstance(r.get('rehang_hint'), str) else ''
        retired.append({'id': cid, 'reason': reason, 'replaced_by': repl, 'rehang_hint': hint.strip()})
    return {'added': added, 'rewritten': rewritten, 'retired': retired}
