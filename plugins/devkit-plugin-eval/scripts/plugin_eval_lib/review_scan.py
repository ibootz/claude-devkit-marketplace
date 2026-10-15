"""会话复盘的抽取层：逐行读本机会话 jsonl，把信号归到已登记插件，只留计数与定位指针，不留对话原文。

字段路径见 .scratch/plugin-eval/research/session-jsonl-signals.md（2.1.263–2.1.299 本机实测，非官方格式）。
本模块读到的正文（prompt、tool_result、注入文本、hook stdout）只在内存里用来归因，一律不进返回值：
返回值里的字符串只有插件名、skill 全名、规则键（插件内脚本相对路径加 check 标记）、hook 声明原文（未展开的
`${CLAUDE_PLUGIN_ROOT}/…`）、会话 id、uuid、时间戳与版本号。

归因口径（spec「2.5 会话复盘」信号表）：
- skill 调用：assistant 的 `Skill` tool_use（input.skill）、user 字符串里的 `<command-name>/x:y</command-name>`、
  assistant 记录的 attributionSkill。裸名 skill 归不到插件，不计。
- 拦截：user 记录里 is_error 的 tool_result，文本开头 `<Event>:<Tool> hook error: [<展开后的命令>]`，从命令里的
  `plugins/cache/<市场>/<插件>/<版本>/<脚本>` 取插件与版本，取不到再看尾注 `This hook comes from the <插件>@<市场> plugin`；
  `hook_blocking_error` 的 blockingError.command 同样是展开路径。
- 注入：`hook_additional_context.content[]` 没有 command。先在同一文件里找文本相同的 hook_success（其 stdout 的
  additionalContext、纯文本 stdout 或 content），按它的「事件 + matcher + 命令」指纹归插件；配不上再用内容标签
  （静态执行常驻 hook 得到的首行，或首行里出现插件名）。都不行记进未归因。
- hook 时延：hook_success / hook_non_blocking_error 的 durationMs、stop_hook_summary.hookInfos[]，按指纹归插件。
- compact：system 记录 subtype=compact_boundary 把一个文件切成若干段，段号 ≥1 即「compact 之后」。
- 去重：按记录 uuid，全部文件（主会话与子代理）共用一个已见集合；文件按修改时间从旧到新读，resume / fork
  复制进新文件的历史只在最早那份里计一次。重复记录照样推进 compact 段号与配对用的文本表，只是不计数。
- 改名：插件名一律经 marketplace 的 renames 归一（链式改名取到底；值为 null 的是已删除插件，原样保留）。
"""
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import injection

# 脚本相对路径只收 ASCII 路径字符：拒绝诊断文案里紧跟路径的全角标点与正文混进规则键（隐私 + 归并）。
SCRIPT_PATH = r'[A-Za-z0-9_.+@~/\\-]+'
CACHE_PATH_RE = re.compile(r'plugins[/\\]cache[/\\]([^/\\\s"\'\]]+)[/\\]([^/\\\s"\'\]]+)[/\\]([^/\\\s"\'\]]+)[/\\](%s)' % SCRIPT_PATH)
ROOT_VAR_RE = re.compile(r'\$\{?CLAUDE_PLUGIN_ROOT\}?[/\\](%s)' % SCRIPT_PATH)
TRAILER_RE = re.compile(r'This hook comes from the ([A-Za-z0-9._-]+)@([A-Za-z0-9._-]+) plugin')
CHECK_RE = re.compile(r'\bcheck=([A-Za-z0-9_.-]+)')
HOOK_ERROR_RE = re.compile(r'^\s*([A-Za-z]+):([^\s]*) hook error: \[')
COMMAND_NAME_RE = re.compile(r'<command-name>/?([^<\s]+)</command-name>')
EXAMPLES_PER_GROUP = 3


def _digest(text):
    return hashlib.sha1(text.strip().encode('utf-8', errors='replace')).hexdigest()


def _first_line(text):
    return injection.content_label(text) or ''


def resolve_renames(renames):
    """{旧名: 新名或 None} → 链式取到底的 {旧名: 现名}；None（已删除）与成环的不收。"""
    out = {}
    for old in renames:
        cur, seen = old, {old}
        while cur in renames and renames[cur] is not None:
            cur = renames[cur]
            if cur in seen:
                cur = None
                break
            seen.add(cur)
        if cur and cur != old:
            out[old] = cur
    return out


@dataclass
class PluginIndex:
    """已登记插件与本机已装插件的 hook 指纹、内容标签、改名表。"""
    registered: set
    renames: dict = field(default_factory=dict)                # 旧名 -> 现名（已链式展开）
    specs: list = field(default_factory=list)                  # [(插件现名, HookSpec)]，含已登记与已安装插件
    labels: dict = field(default_factory=dict)                 # 插件 -> {首行标签}
    _tokens: dict = field(default_factory=dict)

    def __post_init__(self):
        for name in self.registered:
            names = {name} | {old for old, new in self.renames.items() if new == name}
            pats = [re.escape(n) for n in sorted(names) if '-' in n and len(n) >= 6]
            if pats:
                self._tokens[name] = re.compile(r'(?<![\w-])(?:%s)(?![\w-])' % '|'.join(pats))

    def norm(self, name):
        return self.renames.get(name, name) if name else name

    def by_hook(self, event, hook_name, command):
        """「事件 + matcher + 命令原文」与声明相同的插件集合（含未登记的已装插件，用来判有没有撞名）。"""
        if not command:
            return set()
        value = hook_name.split(':', 1)[1] if hook_name and ':' in hook_name else ''
        out = set()
        for plugin, spec in self.specs:
            if spec.event != event or spec.command.strip() != command.strip():
                continue
            if value and not injection.matcher_matches(spec.matcher, value):
                continue
            out.add(plugin)
        return out

    def by_text(self, text, among=None):
        """按内容标签认插件：首行等于该插件静态注入的首行，或首行里出现插件名（含改名前旧名）。只返回已登记插件。"""
        line = _first_line(text)
        if not line:
            return set()
        pool = self.registered if among is None else (self.registered & set(among))
        hits = {p for p in pool if line in self.labels.get(p, ())}
        if not hits:
            hits = {p for p in pool if p in self._tokens and self._tokens[p].search(line)}
        return hits

    def resolve(self, candidates, text=None):
        """指纹候选 → (已登记插件或 None, 方式)。唯一命中直接定；撞名时用内容标签在候选里挑；没有候选时只靠标签。"""
        if len(candidates) == 1:
            p = next(iter(candidates))
            return (p, 'fingerprint') if p in self.registered else (None, 'other')
        if candidates:
            hits = self.by_text(text, among=candidates) if text else set()
            if len(hits) == 1:
                return next(iter(hits)), 'fingerprint+label'
            return None, ('ambiguous' if candidates & self.registered else 'other')
        hits = self.by_text(text) if text else set()
        if len(hits) == 1:
            return next(iter(hits)), 'label'
        return None, 'ambiguous' if hits else 'unknown'


def _new_plugin_stats():
    return {
        'sessions_listed': set(), 'sessions_signal': set(),
        'skills': defaultdict(Counter),            # skill 全名 -> {tool, slash, attributed_records}
        'blocks': [],                               # [(kind, rule, 是否子代理, 段号, 指针)]
        'hook_errors': [],
        'decisions': Counter(),                     # hook stdout 里的 permissionDecision（ask / deny / allow）
        'injections': Counter(),                    # by_event:<事件> / via:<方式> / after_compact
        'latency': defaultdict(list),               # hook 声明 key -> [durationMs]
        'compact': Counter(),                       # boundaries_seen / reinjected
        'co_loaded': defaultdict(set),              # 同会话 skill_listing 里的其它插件 -> {会话 id}
    }


@dataclass
class ScanResult:
    plugins: dict
    stats: dict
    environment: dict


class Scanner(object):
    def __init__(self, index, since_iso):
        self.index = index
        self.since = (since_iso or '')[:19]
        self.seen = set()
        self.p = {name: _new_plugin_stats() for name in index.registered}
        self.stats = {
            'main_files': 0, 'subagent_files': 0, 'unreadable_files': 0, 'bad_lines': 0,
            'records_counted': 0, 'duplicate_records': 0, 'out_of_window_records': 0,
            'claude_code_versions': Counter(), 'entrypoints': Counter(), 'compact_boundaries': 0,
            'field_coverage': {'permission_decision_hook': 0, 'hook_deny_tool_results': 0, 'deny_trailer': 0,
                               'deny_without_plugin': 0},
            'unattributed_injections': Counter(), 'sessions': set(),
        }
        self.latest_version = (None, None)          # (时间, Claude Code 版本)
        self.latest_main_model = (None, None)
        self.models = Counter()

    # ---------- 文件 ----------

    def scan_file(self, path, is_subagent=False):
        path = Path(path)
        agent_id = path.stem[len('agent-'):] if is_subagent and path.stem.startswith('agent-') else None
        self.stats['subagent_files' if is_subagent else 'main_files'] += 1
        ctx = {'segment': 0, 'hook_texts': {}, 'hac': [], 'ss_by_segment': defaultdict(set), 'agent_id': agent_id,
               'subagent': is_subagent, 'file_session': path.stem if not is_subagent else path.parent.parent.name,
               'listed_sessions': set(), 'counted_segments': set()}
        try:
            fh = open(str(path), 'r', encoding='utf-8', errors='replace')
        except OSError:
            self.stats['unreadable_files'] += 1
            return
        with fh:
            try:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        self.stats['bad_lines'] += 1
                        continue
                    if isinstance(rec, dict):
                        self._record(rec, ctx)
            except OSError:
                self.stats['unreadable_files'] += 1
        self._finish_file(ctx)

    # ---------- 记录 ----------

    def _pointer(self, rec, ctx, plugin_version=None):
        return {'session_id': rec.get('sessionId') or ctx['file_session'], 'agent_id': ctx['agent_id'],
                'uuid': rec.get('uuid'), 'timestamp': rec.get('timestamp'), 'claude_code_version': rec.get('version'),
                'plugin_version': plugin_version}

    def _record(self, rec, ctx):
        t = rec.get('type')
        if t == 'system' and rec.get('subtype') == 'compact_boundary':
            ctx['segment'] += 1
        ts = rec.get('timestamp')
        in_window = not (self.since and isinstance(ts, str) and ts[:19] < self.since)
        uid = rec.get('uuid')
        dup = bool(uid) and uid in self.seen
        if uid:
            self.seen.add(uid)
        count = in_window and not dup
        if dup:
            self.stats['duplicate_records'] += 1
        elif not in_window:
            self.stats['out_of_window_records'] += 1
        if count and t in ('user', 'assistant', 'attachment', 'system'):
            self.stats['records_counted'] += 1
            v = rec.get('version')
            if v:
                self.stats['claude_code_versions'][v] += 1
                if isinstance(ts, str) and (self.latest_version[0] is None or ts > self.latest_version[0]):
                    self.latest_version = (ts, v)
            sid = rec.get('sessionId')
            if sid and sid not in self.stats['sessions'] and not ctx['subagent']:
                self.stats['sessions'].add(sid)
                self.stats['entrypoints'][rec.get('entrypoint') or '未记录'] += 1
            if t == 'system' and rec.get('subtype') == 'compact_boundary':
                self.stats['compact_boundaries'] += 1
                ctx['counted_segments'].add(ctx['segment'])     # 只有窗口内、非 resume 复制的边界才进 compact 统计
        if t == 'assistant':
            self._assistant(rec, ctx, count)
        elif t == 'user':
            self._user(rec, ctx, count)
        elif t == 'attachment':
            self._attachment(rec, ctx, count)
        elif t == 'system' and rec.get('subtype') == 'stop_hook_summary' and count:
            for info in rec.get('hookInfos') or []:
                if isinstance(info, dict):
                    self._latency('Stop', 'Stop', info.get('command'), info.get('durationMs'), None, rec, ctx)

    def _sig(self, plugin, rec, ctx):
        sid = rec.get('sessionId') or ctx['file_session']
        self.p[plugin]['sessions_signal'].add(sid)

    def _assistant(self, rec, ctx, count):
        if not count:
            return
        msg = rec.get('message') if isinstance(rec.get('message'), dict) else {}
        model = msg.get('model')
        if model and model != '<synthetic>':
            self.models[model] += 1
            ts = rec.get('timestamp')
            if not rec.get('isSidechain') and not ctx['subagent'] and isinstance(ts, str) and \
                    (self.latest_main_model[0] is None or ts > self.latest_main_model[0]):
                self.latest_main_model = (ts, model)
        for block in msg.get('content') or []:
            if isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('name') == 'Skill':
                skill = (block.get('input') or {}).get('skill') if isinstance(block.get('input'), dict) else None
                self._skill(skill, 'tool', rec, ctx)
        attr = rec.get('attributionSkill')
        if isinstance(attr, str):
            self._skill(attr, 'attributed_records', rec, ctx)

    def _skill(self, full, how, rec, ctx):
        if not isinstance(full, str) or ':' not in full:
            return
        plugin, _, skill = full.partition(':')
        plugin = self.index.norm(plugin)
        if plugin in self.p and skill:
            self.p[plugin]['skills']['%s:%s' % (plugin, skill)][how] += 1
            self._sig(plugin, rec, ctx)

    def _user(self, rec, ctx, count):
        msg = rec.get('message') if isinstance(rec.get('message'), dict) else {}
        content = msg.get('content')
        if not count:
            return
        if isinstance(content, str):
            for m in COMMAND_NAME_RE.finditer(content[:2000]):
                self._skill(m.group(1), 'slash', rec, ctx)
            return
        pd = rec.get('permissionDecision')
        hook_pd = isinstance(pd, dict) and pd.get('reasonType') == 'hook' and pd.get('decision') == 'reject'
        if hook_pd:
            self.stats['field_coverage']['permission_decision_hook'] += 1
        for block in content if isinstance(content, list) else []:
            if not (isinstance(block, dict) and block.get('type') == 'tool_result' and block.get('is_error')):
                continue
            text = block.get('content')
            if isinstance(text, list):
                text = ' '.join(x.get('text', '') for x in text if isinstance(x, dict))
            if not isinstance(text, str) or not HOOK_ERROR_RE.match(text[:300]):
                continue
            self.stats['field_coverage']['hook_deny_tool_results'] += 1
            self._block(text, 'tool_result', rec, ctx)

    def _plugin_from_command(self, text):
        """展开后的命令（或含它的文本）→ (插件现名, 版本, 脚本相对路径)；取不到返回 (None, None, None)。"""
        head = text[:1500]
        areas = [(head, False)]
        if HOOK_ERROR_RE.match(head):
            # 新版 `<Event>:<Tool> hook error: [<展开后的命令>]: <诊断>`：脚本只认命令段里的；
            # 旧版方括号里是诊断标签、没有命令，诊断里提到的文档路径只用来认插件与版本，脚本记 '?'
            start = head.find('[') + 1
            end = head.find(']', start)
            areas = [(head[start:end if end > 0 else len(head)], True), (head, False)]
        for area, is_command in areas:
            m = CACHE_PATH_RE.search(area)
            if m:
                return self.index.norm(m.group(2)), m.group(3), m.group(4).rstrip(':;,.') if is_command else None
            # --plugin-dir / 源码仓加载：路径里有 /<插件名>/ 段，后面是脚本
            for name in list(self.index.registered) + list(self.index.renames):
                mm = re.search(r'[/\\]%s[/\\](%s)' % (re.escape(name), SCRIPT_PATH), area)
                if mm:
                    return self.index.norm(name), None, mm.group(1).rstrip(':;,.') if is_command else None
        return None, None, None

    def _rule(self, script, text):
        m = CHECK_RE.search(text[:3000]) if text else None
        return '%s#check=%s' % (script or '?', m.group(1)) if m else (script or '?')

    def _block(self, text, via, rec, ctx):
        plugin, version, script = self._plugin_from_command(text)
        tr = TRAILER_RE.search(text)
        if tr:
            self.stats['field_coverage']['deny_trailer'] += 1
            if plugin is None:
                plugin = self.index.norm(tr.group(1))
        if plugin is None:
            self.stats['field_coverage']['deny_without_plugin'] += 1
            return
        if plugin not in self.p:
            return
        self.p[plugin]['blocks'].append(('block', self._rule(script, text), ctx['subagent'], ctx['segment'],
                                         dict(self._pointer(rec, ctx, version), via=via)))
        self._sig(plugin, rec, ctx)

    def _attachment(self, rec, ctx, count):
        a = rec.get('attachment')
        if not isinstance(a, dict):
            return
        at = a.get('type')
        if at == 'hook_success':
            texts = self._hook_texts(a)
            cands = self.index.by_hook(a.get('hookEvent'), a.get('hookName'), a.get('command'))
            plugin, how = self.index.resolve(cands, texts[0] if texts else None)
            for tx in texts:   # 归不到已登记插件的记成 __other / __ambiguous / __unknown，收尾时据此决定要不要再看标签
                ctx['hook_texts'].setdefault(_digest(tx), set()).add(plugin or '__' + how)
            if count:
                self._latency(a.get('hookEvent'), a.get('hookName'), a.get('command'), a.get('durationMs'),
                              texts[0] if texts else None, rec, ctx, cands=cands)
                self._decision(a, plugin, rec, ctx)
        elif at == 'hook_additional_context':
            for item in a.get('content') or []:
                if isinstance(item, str) and item.strip():
                    ctx['hac'].append((ctx['segment'], a.get('hookEvent'), _digest(item), _first_line(item), count,
                                       rec.get('sessionId') or ctx['file_session']))
        elif at == 'hook_blocking_error' and count:
            be = a.get('blockingError') if isinstance(a.get('blockingError'), dict) else {}
            cmd = be.get('command') or ''
            self._block(cmd + ' ' + str(be.get('blockingError') or '')[:2000], 'blocking_error', rec, ctx)
        elif at == 'hook_non_blocking_error' and count:
            cands = self.index.by_hook(a.get('hookEvent'), a.get('hookName'), a.get('command'))
            plugin, _ = self.index.resolve(cands, None)
            if plugin is None:
                plugin, version, script = self._plugin_from_command(a.get('command') or '')
                plugin = plugin if plugin in self.p else None
            if plugin:
                script = self._script(a.get('command'))
                self.p[plugin]['hook_errors'].append(('hook_error', script, ctx['subagent'], ctx['segment'],
                                                      dict(self._pointer(rec, ctx), exit_code=a.get('exitCode'))))
                self._sig(plugin, rec, ctx)
            self._latency(a.get('hookEvent'), a.get('hookName'), a.get('command'), a.get('durationMs'), None, rec, ctx,
                          cands=cands)
        elif at == 'skill_listing' and count:
            sid = rec.get('sessionId') or ctx['file_session']
            names = {self.index.norm(n.split(':', 1)[0]) for n in a.get('names') or [] if isinstance(n, str) and ':' in n}
            for p in names & set(self.p):
                self.p[p]['sessions_listed'].add(sid)
                for other in names - {p}:
                    self.p[p]['co_loaded'][other].add(sid)

    @staticmethod
    def _script(command):
        m = ROOT_VAR_RE.search(command or '') or CACHE_PATH_RE.search(command or '')
        if not m:
            return '?'
        return (m.group(1) if m.re is ROOT_VAR_RE else m.group(4)).rstrip(':;,')

    @staticmethod
    def _hook_texts(a):
        """hook_success 里可能成为注入的文本：stdout 的 additionalContext、纯文本 stdout、content。"""
        out = []
        stdout = a.get('stdout') or ''
        try:
            j = json.loads(stdout) if stdout.strip().startswith('{') else None
        except ValueError:
            j = None
        if isinstance(j, dict):
            h = j.get('hookSpecificOutput') if isinstance(j.get('hookSpecificOutput'), dict) else {}
            if isinstance(h.get('additionalContext'), str) and h['additionalContext'].strip():
                out.append(h['additionalContext'])
        elif stdout.strip():
            out.append(stdout)
        if isinstance(a.get('content'), str) and a['content'].strip():
            out.append(a['content'])
        return out

    def _decision(self, a, plugin, rec, ctx):
        if plugin is None:
            return
        stdout = a.get('stdout') or ''
        if 'permissionDecision' not in stdout:
            return
        try:
            j = json.loads(stdout)
            d = (j.get('hookSpecificOutput') or {}).get('permissionDecision')
        except (ValueError, AttributeError):
            return
        if isinstance(d, str):
            self.p[plugin]['decisions'][d] += 1
            self._sig(plugin, rec, ctx)

    def _latency(self, event, hook_name, command, ms, text, rec, ctx, cands=None):
        if not isinstance(ms, (int, float)) or not command:
            return
        cands = self.index.by_hook(event, hook_name, command) if cands is None else cands
        if not cands:       # 时延只按声明指纹归：只靠内容标签认出的 hook，命令可能是用户级 hook 的绝对路径
            return
        plugin, _ = self.index.resolve(cands, text)
        if plugin is None:
            return
        value = hook_name.split(':', 1)[1] if hook_name and ':' in hook_name else ''
        key = None
        for p, spec in self.index.specs:
            if p == plugin and spec.event == event and spec.command.strip() == command.strip() and \
                    (not value or injection.matcher_matches(spec.matcher, value)):
                key = spec.key
                break
        self.p[plugin]['latency'][key or '%s||%s' % (event, command.strip())].append(int(ms))

    # ---------- 文件收尾：注入归因与 compact 重新到达 ----------

    def _finish_file(self, ctx):
        for seg, event, dg, line, count, sid in ctx['hac']:
            marks = ctx['hook_texts'].get(dg, set())
            owners = {p for p in marks if not p.startswith('__')}
            if len(owners) == 1:
                plugin, how = next(iter(owners)), 'fingerprint'
            elif not owners and marks == {'__other'}:
                continue        # 配上的是未登记插件的 hook：不是被测插件的注入，也不算未归因
            else:
                hits = self.index.by_text(line)
                plugin, how = (next(iter(hits)), 'label') if len(hits) == 1 else (None, None)
            if plugin is None or plugin not in self.p:
                if count:
                    self.stats['unattributed_injections'][event or '?'] += 1
                continue
            if event == 'SessionStart' and seg >= 1:
                ctx['ss_by_segment'][seg].add(plugin)
            if not count:
                continue
            c = self.p[plugin]['injections']
            c['total'] += 1
            c['by_event:%s' % event] += 1
            c['via:%s' % how] += 1
            if seg >= 1:
                c['after_compact'] += 1
            self.p[plugin]['sessions_signal'].add(sid)
        for seg in sorted(ctx['counted_segments']):
            for plugin in self.p:
                self.p[plugin]['compact']['boundaries_seen'] += 1
                if plugin in ctx['ss_by_segment'].get(seg, ()):
                    self.p[plugin]['compact']['reinjected'] += 1

    # ---------- 结果 ----------

    def result(self):
        env = {'claude_code_version': self.latest_version[1], 'main_model': self.latest_main_model[1],
               'models': dict(self.models.most_common())}
        stats = dict(self.stats)
        stats['claude_code_versions'] = dict(sorted(self.stats['claude_code_versions'].items()))
        stats['entrypoints'] = dict(self.stats['entrypoints'])
        stats['unattributed_injections'] = dict(self.stats['unattributed_injections'])
        stats['sessions'] = len(self.stats['sessions'])
        return ScanResult(self.p, stats, env)


def iter_session_files(projects_dir, since_ts=None):
    """<projects>/** 下的会话 jsonl：(路径, 是否子代理)，按修改时间从旧到新；修改时间早于 since_ts 的跳过。
    读的过程中被 Claude Code 清理掉的文件静默跳过。"""
    found = []
    for dirpath, _dirs, files in os.walk(str(projects_dir)):
        sub = os.path.basename(dirpath) == 'subagents'
        for f in files:
            if not f.endswith('.jsonl'):
                continue
            p = os.path.join(dirpath, f)
            try:
                mt = os.path.getmtime(p)
            except OSError:
                continue
            if since_ts is not None and mt < since_ts:
                continue
            found.append((mt, sub, p))
    found.sort()
    return [(Path(p), sub) for _, sub, p in found]


def percentile(values, q):
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[k]
