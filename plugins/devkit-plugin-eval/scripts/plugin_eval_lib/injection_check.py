"""注入到达核验（spec「2.2 离线对照」第 5 步）：只作前置核验、不计分。

为什么读转录：eval 的 trace 只收 SessionStart 的 hook 事件；UserPromptSubmit / PreToolUse / SubagentStart
的注入只在 --keep-temp 保留的子会话转录里（plugin-eval 票 05 实测 0/19 进 trace、19/19 在转录）。

转录里的 hook 记录（Claude Code 2.1.299 / 2.1.300 实测，attachment.type）：
- hook_additional_context：注入到达模型的正文。字段 hookEvent、content（字符串列表），**没有 command**，
  所以按「同事件 + 正文含该 hook 的内容标签」认领到被测插件的某条 hook（标签由 injection.static_profile 静态取）。
- hook_success：带 command（未展开的原文）与 exitCode。UserPromptSubmit 成功时不记这一条。
- hook_non_blocking_error 等其余 hook_*：带 command 与非零 exitCode。stdout 为空的失败（如解释器不可达 126）记这一条、
  注入丢失；hook 输出了 JSON 再以非 2 的码退出时，2.1.300 实测注入照样到达、也不记这一条。所以先看正文到没到，再看失败记录。
trace 里 SessionStart 的 hook_response 带 exit_code，作冒烟之外的第二道防线（只有事件名、没有 command）。

逐 hook 判定（只判 injection.static_profile 标了 expected 的常驻 hook）：
- arrived：转录里有同事件、正文含其标签的注入；
- failed：转录有该 command 的非零退出，或（该 hook 本应触发时）trace 里同事件 hook 非零退出且未到达 → 未到达；
- missing：该事件应当触发、却既无注入也无失败记录 → 未到达；
- not_triggered：SubagentStart 而本 run 没派子代理，或 matcher 不匹配本次触发值。先于 trace 失败记录判：
  trace 的失败记录只有事件名，同事件别的 hook（如环境插件的）失败不该把本不触发的 hook 判成 failed；
- unverified：静态取不到标签，又没有失败记录，无法逐条确认。
"""
import json
import statistics
from collections import Counter
from pathlib import Path

from .injection import RESIDENT_EVENTS, matcher_matches

# 不是失败的退出码：PreToolUse 等以 2 表示拦截（deny），属插件正常行为
DENY_EXIT_CODE = 2
WITH_ARM_ORDER = ('current', 'previous', 'current_with_env')


# ---------- 读一个 run ----------

def _iter_json(path):
    try:
        f = open(path, encoding='utf-8', errors='replace')
    except OSError:
        return
    with f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if isinstance(o, dict):
                yield o


def _locate(run_dir, trace_path):
    """优先读 traces.harvest_sandbox 搬出后的目录；没搬成功时回退到沙箱原位（<e-xxx>/config/projects）。"""
    run_dir = Path(run_dir) if run_dir else None
    projects = trace = None
    if run_dir is not None:
        if (run_dir / 'projects').is_dir():
            projects = run_dir / 'projects'
        if (run_dir / 'trace.jsonl').is_file():
            trace = run_dir / 'trace.jsonl'
    if trace_path:
        tp = Path(trace_path)
        if projects is None and (tp.parent.parent / 'config' / 'projects').is_dir():
            projects = tp.parent.parent / 'config' / 'projects'
        if trace is None and tp.is_file():
            trace = tp
    return projects, trace


def _content_text(content):
    if isinstance(content, list):
        return '\n'.join(c if isinstance(c, str) else json.dumps(c, ensure_ascii=False) for c in content)
    return content if isinstance(content, str) else ''


def observe_run(run_dir, trace_path=None):
    projects, trace = _locate(run_dir, trace_path)
    files = sorted(projects.rglob('*.jsonl')) if projects else []
    obs = {'transcript_found': bool(files), 'subagent_transcripts': 0, 'events': {}, 'contexts': [],
           'successes': [], 'failures': [], 'trace_hook_failures': [], 'first_request_input_tokens': None}
    seen, events = set(), Counter()
    for f in files:
        if 'subagents' in f.parts:
            obs['subagent_transcripts'] += 1
        for o in _iter_json(f):
            a = o.get('attachment')
            if not isinstance(a, dict) or not str(a.get('type', '')).startswith('hook_'):
                continue
            uid = o.get('uuid')
            if uid:
                if uid in seen:
                    continue
                seen.add(uid)
            t, ev = a.get('type'), a.get('hookEvent')
            if t == 'hook_additional_context':
                events[ev] += 1
                obs['contexts'].append((ev, _content_text(a.get('content'))))
            elif t == 'hook_success':
                obs['successes'].append((ev, a.get('command')))
            elif a.get('command') is not None and a.get('exitCode') not in (0, None):
                obs['failures'].append({'event': ev, 'command': a.get('command'), 'exit_code': a.get('exitCode'),
                                        'type': t})
    obs['events'] = dict(events)
    if trace:
        for o in _iter_json(trace):
            if o.get('type') == 'system' and o.get('subtype') == 'hook_response' and o.get('exit_code') not in (0, None):
                obs['trace_hook_failures'].append({'event': o.get('hook_event'), 'hook_name': o.get('hook_name'),
                                                   'exit_code': o.get('exit_code')})
            elif o.get('type') == 'assistant' and obs['first_request_input_tokens'] is None:
                u = (o.get('message') or {}).get('usage') or {}
                obs['first_request_input_tokens'] = sum(u.get(k) or 0 for k in (
                    'input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
    return obs


# ---------- 判一个 run ----------

def _should_fire(hook, obs):
    if hook['event'] == 'SessionStart':
        return matcher_matches(hook['matcher'], 'startup')
    if hook['event'] == 'SubagentStart':
        # 派过子代理才会触发；matcher 限定了 agent_type 时转录里取不到类型，到达了就认、没到达不判缺失
        if hook['matcher'] not in (None, '', '*'):
            return False
        return obs['subagent_transcripts'] > 0 or obs['events'].get('SubagentStart', 0) > 0
    return True


def check_run(obs, profile):
    hooks = [h for h in profile['hooks'] if h['expected']]
    plugin_cmds = {(h['event'], h['command']) for h in profile['hooks']}
    plugin_cmds |= {(h['event'], h['command']) for h in profile.get('conditional_hooks', [])}
    out = {'events': obs['events'], 'subagent_transcripts': obs['subagent_transcripts'], 'hooks': {},
           'plugin_hook_failures': [], 'trace_hook_failures': obs['trace_hook_failures'],
           'first_request_input_tokens': obs['first_request_input_tokens']}
    if not obs['transcript_found']:
        out.update(verdict='no_transcript', arrived=False)
        return out
    resident_fail = Counter()
    for f in obs['failures']:
        if (f['event'], f['command']) not in plugin_cmds:
            continue
        if f['event'] in RESIDENT_EVENTS:
            resident_fail[(f['event'], f['command'], f['exit_code'])] += 1
        elif f['exit_code'] != DENY_EXIT_CODE:
            out['plugin_hook_failures'].append({'event': f['event'], 'command': f['command'], 'exit_code': f['exit_code']})
    trace_fail = {}
    for f in obs['trace_hook_failures']:
        trace_fail.setdefault(f['event'], []).append(f['exit_code'])

    for h in hooks:
        count = sum(1 for ev, text in obs['contexts'] if ev == h['event'] and h['label'] and h['label'] in text)
        codes = sorted(code for (ev, cmd, code), n in resident_fail.items() for _ in range(n)
                       if ev == h['event'] and cmd == h['command'])
        entry = {'event': h['event'], 'command': h['command'], 'count': count}
        if count:
            entry['verdict'] = 'arrived'
        elif codes:
            entry.update(verdict='failed', exit_codes=codes)
        elif not _should_fire(h, obs):
            entry['verdict'] = 'not_triggered'
        elif trace_fail.get(h['event']):
            entry.update(verdict='failed', exit_codes=sorted(trace_fail[h['event']]), source='trace')
        elif not h['label']:
            entry['verdict'] = 'unverified'
        else:
            entry['verdict'] = 'missing'
        out['hooks'][h['key']] = entry
    verdicts = {e['verdict'] for e in out['hooks'].values()}
    if verdicts & {'failed', 'missing'}:
        out['verdict'] = 'not_arrived'
    elif 'unverified' in verdicts:
        out['verdict'] = 'unverified'
    else:
        out['verdict'] = 'arrived'
    out['arrived'] = out['verdict'] == 'arrived'
    return out


# ---------- 汇总全部臂 ----------

def _plugin_labels(profiles):
    labels = set()
    for p in profiles:
        labels |= {(h['event'], h['label']) for h in p['hooks'] if h['label']}
    return labels


def _why(run):
    parts = []
    for e in run['hooks'].values():
        if e['verdict'] == 'failed':
            # 同一 run 里 UserPromptSubmit 每轮都触发，退出码去重后再写，免得「1/1/1」与「1」被当成两种原因
            codes = sorted(set(e['exit_codes']), key=str)
            parts.append('%s `%s`：退出码 %s' % (e['event'], e['command'], '/'.join(str(c) for c in codes)))
        elif e['verdict'] == 'missing':
            parts.append('%s `%s`：未见注入' % (e['event'], e['command']))
    return parts


def _summarize(counter):
    return '；'.join('%s ×%d' % (k, n) for k, n in sorted(counter.items()))


def build(arm_records):
    """取走各臂记录里的 `_static`（静态常驻注入画像，「不装」臂为 None）与 `_runs`（逐 run 的转录位置），
    返回 (injection-check.json 内容, run.json 的 resident_tokens)。"""
    statics = {k: rec.pop('_static', None) for k, rec in arm_records.items()}
    runs_by_arm = {k: rec.pop('_runs', []) for k, rec in arm_records.items()}
    ref_profiles = [statics['current']] if statics.get('current') else [p for p in statics.values() if p]
    plugin_labels = _plugin_labels(ref_profiles)
    check = {'schema_version': 1, 'purpose': '注入到达核验：只作前置核验、不计分', 'ok': True, 'problems': [], 'arms': {}}
    measured = {}

    for key, rec in arm_records.items():
        prof, label = statics.get(key), rec.get('label', key)
        arm = {'label': label, 'kind': 'with' if prof else 'control', 'runs': [], 'events_total': {},
               'runs_total': 0, 'runs_arrived': 0, 'runs_not_arrived': 0, 'runs_unverified': 0,
               'runs_no_transcript': 0, 'plugin_injections': 0}
        events_total, why, cond_fail, firsts = Counter(), Counter(), Counter(), []
        for r in runs_by_arm.get(key, []):
            obs = observe_run(r.get('dir'), r.get('trace_path'))
            if obs['first_request_input_tokens'] is not None:
                firsts.append(obs['first_request_input_tokens'])
            arm['plugin_injections'] += sum(1 for ev, text in obs['contexts']
                                            if any(ev == e and lb in text for e, lb in plugin_labels))
            events_total.update(obs['events'])
            if prof:
                res = check_run(obs, prof)
                for f in res['plugin_hook_failures']:
                    cond_fail['%s `%s`：退出码 %s' % (f['event'], f['command'], f['exit_code'])] += 1
                why.update(_why(res))
            else:
                res = {'events': obs['events'], 'subagent_transcripts': obs['subagent_transcripts'],
                       'trace_hook_failures': obs['trace_hook_failures'],
                       'verdict': 'no_transcript' if not obs['transcript_found'] else 'control'}
            res.update(case=r.get('case'), run=r.get('run'))
            arm['runs'].append(res)
            arm['runs_total'] += 1
            v = res['verdict']
            arm['runs_arrived'] += v == 'arrived'
            arm['runs_not_arrived'] += v == 'not_arrived'
            arm['runs_unverified'] += v == 'unverified'
            arm['runs_no_transcript'] += v == 'no_transcript'
        arm['events_total'] = dict(events_total)
        if prof:
            arm['expected_hooks'] = [{'key': h['key'], 'label': h['label']} for h in prof['hooks'] if h['expected']]
        if firsts:
            measured[key] = statistics.median(firsts)

        n = arm['runs_total']
        if prof:
            if not n:
                check['problems'].append('%s臂：0 个 run 可核验（eval 没产出逐 run 结果），注入是否到达无从判断' % label)
            if arm['runs_not_arrived']:
                check['problems'].append('%s臂：%d/%d 个 run 有注入未到达（%s）' % (label, arm['runs_not_arrived'], n, _summarize(why)))
            if cond_fail:
                check['problems'].append('%s臂：被测插件的条件注入 hook 非零退出（%s）' % (label, _summarize(cond_fail)))
            if prof.get('errors'):
                check['problems'].append('%s臂：常驻注入 hook 静态执行出错（%s），这些 hook 的常驻 token 可能不准'
                                         % (label, '；'.join(prof['errors'])))
        elif arm['plugin_injections']:
            check['problems'].append('%s臂：出现被测插件的注入 %d 条，应为 0' % (label, arm['plugin_injections']))
        if arm['runs_no_transcript']:
            check['problems'].append('%s臂：%d/%d 个 run 找不到子会话转录，注入是否到达无法核验' % (label, arm['runs_no_transcript'], n))
        check['arms'][key] = arm
    check['ok'] = not check['problems']

    method = next((p['method'] for p in statics.values() if p), None)
    resident = {
        'method': method,
        'arms': {k: {'label': arm_records[k].get('label', k), 'by_event': p['by_event'],
                     'total_tokens_est': p['total_tokens_est'],
                     'hooks': [{x: h[x] for x in ('key', 'event', 'chars', 'tokens_est', 'exit_code', 'label')}
                               for h in p['hooks']],
                     'conditional_hooks': len(p.get('conditional_hooks', [])),
                     'errors': p.get('errors', [])}
                 for k, p in statics.items() if p},
        'measured_first_request_input_tokens': measured,
        'measured_delta_vs_none': {k: v - measured['none'] for k, v in measured.items() if k != 'none'}
        if 'none' in measured else {},
    }
    return check, resident


def summary(check):
    """run.json 里的 injection_check：明细在 injection-check.json，这里只留结论与逐臂计数。"""
    keep = ('label', 'kind', 'runs_total', 'runs_arrived', 'runs_not_arrived', 'runs_unverified',
            'runs_no_transcript', 'events_total', 'plugin_injections')
    return {'file': 'injection-check.json', 'ok': check['ok'], 'problems': check['problems'],
            'arms': {k: {x: a[x] for x in keep} for k, a in check['arms'].items()}}


# ---------- 报告 ----------

def report_banner(rec):
    """报告首段的醒目提示；核验通过时为空。"""
    check = rec.get('injection_check')
    if not check or check.get('ok'):
        return []
    lines = ['', '> **注入未到达或无法核验**：下列臂的分数不能直接当作插件效果，先排查 hook 再看结果'
                 '（注入到达核验只作前置核验、不计分，明细见 `injection-check.json`）。', '>']
    lines += ['> - %s' % p for p in check['problems']]
    return lines


def _fmt_num(x):
    return '—' if x is None else ('%d' % x if float(x).is_integer() else '%.1f' % x)


def report_sections(rec):
    lines = []
    check = rec.get('injection_check')
    if check:
        lines += ['', '## 注入到达核验', '',
                  '只作前置核验、不计分。读 `--keep-temp` 子会话转录：注入条数含全部来源；'
                  '「被测插件注入」按内容标签认领。', '',
                  '| 臂 | run 数 | 全部到达 | 未到达 | 无法逐条确认 | 无转录 | 被测插件注入条数 | 各事件注入条数 |',
                  '|---|---|---|---|---|---|---|---|']
        for a in check['arms'].values():
            ev = '、'.join('%s %d' % (k, v) for k, v in sorted(a['events_total'].items())) or '0'
            arrived = a['runs_arrived'] if a['kind'] == 'with' else '—'
            lines.append('| %s | %d | %s | %d | %d | %d | %d | %s |' % (
                a['label'], a['runs_total'], arrived, a.get('runs_not_arrived', 0), a.get('runs_unverified', 0),
                a.get('runs_no_transcript', 0), a.get('plugin_injections', 0), ev))
    resident = rec.get('resident_tokens')
    if resident and resident.get('arms'):
        keys = [k for k in WITH_ARM_ORDER if k in resident['arms']] + \
               [k for k in resident['arms'] if k not in WITH_ARM_ORDER]
        events = [e for e in RESIDENT_EVENTS if any(e in resident['arms'][k]['by_event'] for k in keys)]
        m = resident.get('method') or {}
        lines += ['', '## 常驻 token（静态估算）', '',
                  '直接执行被测插件的常驻注入 hook，按输出估 token，不调模型。口径：%s；%s。'
                  'SessionStart 每次会话一次，UserPromptSubmit 每轮一次，SubagentStart 每个子代理一次。'
                  % (m.get('formula', '—'), m.get('scope', '—')), '',
                  '| 事件 | %s |' % ' | '.join(resident['arms'][k]['label'] for k in keys),
                  '|---|%s' % ('---|' * len(keys))]
        for e in events:
            lines.append('| %s | %s |' % (e, ' | '.join(
                _fmt_num((resident['arms'][k]['by_event'].get(e) or {}).get('tokens_est')) for k in keys)))
        lines.append('| 合计（各事件各触发一次） | %s |' %' | '.join(_fmt_num(resident['arms'][k]['total_tokens_est']) for k in keys))
        cond = [(resident['arms'][k]['label'], resident['arms'][k].get('conditional_hooks', 0)) for k in keys]
        if any(n for _, n in cond):
            lines += ['', '条件注入 hook（PreToolUse 等，按工具入参才注入）不计常驻：%s。'
                      % '、'.join('%s %d 条' % (lb, n) for lb, n in cond)]
        measured = resident.get('measured_first_request_input_tokens') or {}
        if measured:
            labels = {k: (rec.get('arms', {}).get(k) or {}).get('label', k) for k in measured}
            lines += ['', '对照：各臂首请求输入 token 实测中位数 %s' % '、'.join(
                '%s %s' % (labels[k], _fmt_num(v)) for k, v in measured.items())]
            if resident.get('measured_delta_vs_none'):
                lines[-1] += '；相对不装 %s（含 skill 列表等全部差异，不只注入）' % '、'.join(
                    '%s %+d' % (labels[k], d) for k, d in resident['measured_delta_vs_none'].items())
            lines[-1] += '。'
    return lines
