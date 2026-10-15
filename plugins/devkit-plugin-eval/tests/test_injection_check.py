"""接缝：读 --keep-temp 子会话转录与 trace，核验被测插件的注入是否到达；汇总成 injection-check.json 与报告段落。"""
import json
import unittest
import uuid
from pathlib import Path

import _support
from _support import tmpdir, write
from plugin_eval_lib import injection_check

SS_CMD = 'node ${CLAUDE_PLUGIN_ROOT}/hooks/wd.js'
LEDGER_CMD = 'node ${CLAUDE_PLUGIN_ROOT}/hooks/ledger.js'
GUARD_CMD = 'node ${CLAUDE_PLUGIN_ROOT}/hooks/guard.js'


def hook(event, matcher, command, label, expected=True, exit_code=0):
    key = '%s|%s|%s' % (event, matcher or '', command)
    return {'key': key, 'event': event, 'matcher': matcher, 'command': command, 'label': label,
            'expected': expected, 'exit_code': exit_code, 'chars': 10, 'tokens_est': 8, 'timed_out': False}


def profile(ups_label='# 每轮要点'):
    hooks = [hook('SessionStart', '*', SS_CMD, '# 会话级纪律'),
             hook('UserPromptSubmit', '*', SS_CMD, ups_label),
             hook('UserPromptSubmit', '*', LEDGER_CMD, None, expected=False),
             hook('SubagentStart', None, SS_CMD, '# 子代理版')]
    return {'method': {'name': 'm'}, 'hooks': hooks,
            'by_event': {'SessionStart': {'hooks': 1, 'injecting_hooks': 1, 'chars': 10, 'tokens_est': 8},
                         'UserPromptSubmit': {'hooks': 2, 'injecting_hooks': 1, 'chars': 10, 'tokens_est': 8},
                         'SubagentStart': {'hooks': 1, 'injecting_hooks': 1, 'chars': 10, 'tokens_est': 8}},
            'total_tokens_est': 24,
            'conditional_hooks': [{'key': 'PreToolUse|Agent|' + GUARD_CMD, 'event': 'PreToolUse',
                                   'matcher': 'Agent', 'command': GUARD_CMD}],
            'errors': []}


def att(a):
    return {'type': 'attachment', 'uuid': str(uuid.uuid4()), 'attachment': a}


def ctx(event, text, name=None):
    return att({'type': 'hook_additional_context', 'content': [text], 'hookName': name or event,
                'hookEvent': event, 'toolUseID': 't'})


def success(event, command):
    return att({'type': 'hook_success', 'hookName': event, 'hookEvent': event, 'command': command,
                'exitCode': 0, 'stdout': '', 'stderr': '', 'content': '', 'durationMs': 5, 'toolUseID': 't'})


def fail(event, command, code, name=None):
    return att({'type': 'hook_non_blocking_error', 'hookName': name or event, 'hookEvent': event, 'command': command,
                'exitCode': code, 'stdout': '', 'stderr': 'Failed', 'durationMs': 5, 'toolUseID': 't'})


def trace(hook_codes=(), first_input=(100, 20, 3)):
    lines = [{'type': 'system', 'subtype': 'hook_response', 'hook_event': ev, 'hook_name': ev + ':startup',
              'exit_code': code, 'outcome': 'success' if code == 0 else 'error'} for ev, code in hook_codes]
    lines.append({'type': 'system', 'subtype': 'init', 'model': 'm'})
    i, c, r = first_input
    lines.append({'type': 'assistant', 'message': {'usage': {'input_tokens': i, 'cache_creation_input_tokens': c,
                                                             'cache_read_input_tokens': r}}})
    lines.append({'type': 'assistant', 'message': {'usage': {'input_tokens': 9999}}})
    return '\n'.join(json.dumps(x, ensure_ascii=False) for x in lines) + '\n'


def make_run(root, main_lines, sub_lines=None, trace_text=None):
    """仿 traces.harvest_sandbox 搬出后的布局：<dir>/trace.jsonl、<dir>/projects/<p>/<sid>.jsonl、
    <dir>/projects/<p>/<sid>/subagents/agent-x.jsonl。"""
    root = Path(root)
    write(root / 'trace.jsonl', trace_text if trace_text is not None else trace())
    body = '\n'.join(json.dumps(x, ensure_ascii=False) for x in main_lines) + '\n'
    write(root / 'projects' / '-tmp-cwd' / 'sid.jsonl', body)
    if sub_lines is not None:
        write(root / 'projects' / '-tmp-cwd' / 'sid' / 'subagents' / 'agent-1.jsonl',
              '\n'.join(json.dumps(x, ensure_ascii=False) for x in sub_lines) + '\n')
    return root


GOOD_MAIN = [ctx('SessionStart', '# 会话级纪律\n正文'), success('SessionStart', SS_CMD),
             ctx('UserPromptSubmit', '# 每轮要点\n正文'), {'type': 'user'},
             ctx('PreToolUse', '[guard] 提示', 'PreToolUse:Agent'), success('PreToolUse', GUARD_CMD)]


class ObserveRunTest(unittest.TestCase):
    def test_counts_events_failures_and_first_request(self):
        d = make_run(tmpdir(self) / 'r', GOOD_MAIN + [fail('PreToolUse', GUARD_CMD, 126, 'PreToolUse:Agent')],
                     sub_lines=[ctx('SubagentStart', '# 子代理版 xx')],
                     trace_text=trace(hook_codes=[('SessionStart', 0), ('SessionStart', 127)]))
        obs = injection_check.observe_run(d)
        self.assertTrue(obs['transcript_found'])
        self.assertEqual(obs['events'], {'SessionStart': 1, 'UserPromptSubmit': 1, 'PreToolUse': 1, 'SubagentStart': 1})
        self.assertEqual(obs['subagent_transcripts'], 1)
        self.assertEqual(obs['failures'], [{'event': 'PreToolUse', 'command': GUARD_CMD, 'exit_code': 126,
                                            'type': 'hook_non_blocking_error'}])
        self.assertEqual(obs['trace_hook_failures'], [{'event': 'SessionStart', 'hook_name': 'SessionStart:startup',
                                                       'exit_code': 127}])
        self.assertEqual(obs['first_request_input_tokens'], 123)

    def test_dedupes_by_uuid_across_files(self):
        line = ctx('UserPromptSubmit', '# 每轮要点')
        d = make_run(tmpdir(self) / 'r', [line, line], sub_lines=[line])
        self.assertEqual(injection_check.observe_run(d)['events'], {'UserPromptSubmit': 1})

    def test_fallback_to_sandbox_layout_and_missing(self):
        tmp = tmpdir(self)
        sb = tmp / 'e-abc'
        write(sb / 'out' / 'trace.jsonl', trace())
        write(sb / 'config' / 'projects' / 'p' / 's.jsonl', json.dumps(ctx('SessionStart', 'x')) + '\n')
        obs = injection_check.observe_run(tmp / 'not-harvested', trace_path=sb / 'out' / 'trace.jsonl')
        self.assertEqual(obs['events'], {'SessionStart': 1})
        missing = injection_check.observe_run(tmp / 'nothing', trace_path=None)
        self.assertFalse(missing['transcript_found'])
        self.assertIsNone(missing['first_request_input_tokens'])


class CheckRunTest(unittest.TestCase):
    def check(self, main, sub=None, prof=None, trace_text=None):
        d = make_run(tmpdir(self) / 'r', main, sub, trace_text)
        return injection_check.check_run(injection_check.observe_run(d), prof or profile())

    def test_all_arrived(self):
        r = self.check(GOOD_MAIN, sub=[ctx('SubagentStart', '# 子代理版')])
        v = {k.split('|')[0] + '/' + k.split('|')[-1]: h['verdict'] for k, h in r['hooks'].items()}
        self.assertEqual(v, {'SessionStart/' + SS_CMD: 'arrived', 'UserPromptSubmit/' + SS_CMD: 'arrived',
                             'SubagentStart/' + SS_CMD: 'arrived'})
        self.assertTrue(r['arrived'])

    def test_subagentstart_not_triggered_without_subagent(self):
        r = self.check(GOOD_MAIN)
        self.assertEqual(r['hooks']['SubagentStart||' + SS_CMD]['verdict'], 'not_triggered')
        self.assertTrue(r['arrived'])

    def test_failed_hook_marked_not_arrived(self):
        main = [ctx('SessionStart', '# 会话级纪律'), fail('UserPromptSubmit', SS_CMD, 1)]
        r = self.check(main)
        h = r['hooks']['UserPromptSubmit|*|' + SS_CMD]
        self.assertEqual(h['verdict'], 'failed')
        self.assertEqual(h['exit_codes'], [1])
        self.assertFalse(r['arrived'])

    def test_missing_without_failure(self):
        r = self.check([ctx('SessionStart', '# 会话级纪律')])
        self.assertEqual(r['hooks']['UserPromptSubmit|*|' + SS_CMD]['verdict'], 'missing')
        self.assertFalse(r['arrived'])

    def test_trace_exit_code_marks_sessionstart_failed(self):
        # SessionStart 结果只进 trace 时（转录缺失或未记失败），trace 的 exit_code 作第二道防线
        r = self.check([ctx('UserPromptSubmit', '# 每轮要点')],
                       trace_text=trace(hook_codes=[('SessionStart', 126)]))
        h = r['hooks']['SessionStart|*|' + SS_CMD]
        self.assertEqual(h['verdict'], 'failed')
        self.assertEqual(h['exit_codes'], [126])

    def test_trace_failure_does_not_flip_hook_that_should_not_fire(self):
        """票 06 审查 D：trace 失败记录只有事件名；本 run 没派子代理时，SubagentStart 的失败（如环境插件的）
        不把被测插件本不触发的 SubagentStart hook 判成 failed。"""
        r = self.check(GOOD_MAIN, trace_text=trace(hook_codes=[('SubagentStart', 1)]))
        self.assertEqual(r['hooks']['SubagentStart||' + SS_CMD]['verdict'], 'not_triggered')
        self.assertTrue(r['arrived'])

    def test_conditional_hook_failure_reported_but_deny_exit_2_is_not(self):
        main = GOOD_MAIN + [fail('PreToolUse', GUARD_CMD, 126), fail('PreToolUse', GUARD_CMD, 2)]
        r = self.check(main)
        self.assertEqual([(f['event'], f['exit_code']) for f in r['plugin_hook_failures']], [('PreToolUse', 126)])
        self.assertTrue(r['arrived'])      # 条件注入不在到达判定里，但失败单列

    def test_unlabeled_expected_hook(self):
        prof = profile(ups_label=None)
        r = self.check([ctx('SessionStart', '# 会话级纪律'), ctx('UserPromptSubmit', '别的')], prof=prof)
        self.assertEqual(r['hooks']['UserPromptSubmit|*|' + SS_CMD]['verdict'], 'unverified')

    def test_no_transcript(self):
        obs = injection_check.observe_run(tmpdir(self) / 'none')
        r = injection_check.check_run(obs, profile())
        self.assertEqual(r['verdict'], 'no_transcript')
        self.assertFalse(r['arrived'])


def arm_rec(label, static, runs):
    return {'label': label, '_static': static, '_runs': runs}


class BuildCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)

    def runs(self, arm, mains):
        out = []
        for i, main in enumerate(mains, 1):
            d = make_run(self.tmp / arm / ('case-a-%d' % i), main, trace_text=trace(first_input=(100 * (2 if arm == 'current' else 1), 0, 0)))
            out.append({'case': 'case-a', 'run': i, 'dir': d, 'trace_path': None})
        return out

    def test_happy(self):
        arms = {'none': arm_rec('不装', None, self.runs('none', [[{'type': 'user'}]] * 2)),
                'current': arm_rec('当前版', profile(), self.runs('current', [GOOD_MAIN, GOOD_MAIN]))}
        check, resident = injection_check.build(arms)
        self.assertTrue(check['ok'])
        self.assertEqual(check['problems'], [])
        cur = check['arms']['current']
        self.assertEqual(cur['kind'], 'with')
        self.assertEqual((cur['runs_total'], cur['runs_arrived']), (2, 2))
        self.assertEqual(cur['runs'][0]['events'], {'SessionStart': 1, 'UserPromptSubmit': 1, 'PreToolUse': 1})
        none = check['arms']['none']
        self.assertEqual(none['kind'], 'control')
        self.assertEqual(none['events_total'], {})
        self.assertEqual(none['plugin_injections'], 0)
        for rec in arms.values():                     # 内部字段被取走
            self.assertNotIn('_runs', rec)
            self.assertNotIn('_static', rec)
        self.assertEqual(resident['arms']['current']['total_tokens_est'], 24)
        self.assertNotIn('none', resident['arms'])
        self.assertEqual(resident['measured_first_request_input_tokens'], {'none': 100, 'current': 200})
        self.assertEqual(resident['measured_delta_vs_none'], {'current': 100})

    def test_not_arrived_and_contamination_are_problems(self):
        broken = [ctx('SessionStart', '# 会话级纪律'), fail('UserPromptSubmit', SS_CMD, 1)]
        arms = {'none': arm_rec('不装', None, self.runs('none', [[ctx('SessionStart', '# 会话级纪律')]])),
                'current': arm_rec('当前版', profile(), self.runs('current', [broken, GOOD_MAIN, broken]))}
        check, _ = injection_check.build(arms)
        self.assertFalse(check['ok'])
        cur = check['arms']['current']
        self.assertEqual((cur['runs_total'], cur['runs_arrived'], cur['runs_not_arrived']), (3, 1, 2))
        text = '\n'.join(check['problems'])
        self.assertIn('当前版臂', text)
        self.assertIn('2/3', text)
        self.assertIn('退出码 1', text)
        self.assertIn('不装臂', text)
        self.assertEqual(check['arms']['none']['plugin_injections'], 1)

    def test_with_arm_without_runs_is_a_problem(self):
        """票 06 审查 E：eval 没产出逐 run 结果时，with 臂 0 个 run 可核验，不判通过。"""
        arms = {'none': arm_rec('不装', None, self.runs('none', [[{'type': 'user'}]])),
                'current': arm_rec('当前版', profile(), [])}
        check, _ = injection_check.build(arms)
        self.assertFalse(check['ok'])
        self.assertIn('当前版臂：0 个 run 可核验', '\n'.join(check['problems']))

    def test_static_errors_become_problems(self):
        prof = profile()
        prof['errors'] = ['UserPromptSubmit|*|x：退出码 127']
        arms = {'current': arm_rec('当前版', prof, self.runs('current', [GOOD_MAIN]))}
        check, resident = injection_check.build(arms)
        self.assertFalse(check['ok'])
        self.assertIn('静态执行', '\n'.join(check['problems']))
        self.assertEqual(resident['arms']['current']['errors'], prof['errors'])


class ReportTest(unittest.TestCase):
    def rec(self, ok=True):
        check = {'ok': ok, 'problems': [] if ok else ['当前版臂：2/3 个 run 有注入未到达'],
                 'arms': {'current': {'label': '当前版', 'kind': 'with', 'runs_total': 3, 'runs_arrived': 1 if not ok else 3,
                                      'runs_not_arrived': 2 if not ok else 0, 'runs_unverified': 0,
                                      'events_total': {'SessionStart': 3}, 'plugin_injections': 3},
                          'none': {'label': '不装', 'kind': 'control', 'runs_total': 3, 'runs_arrived': 0,
                                   'runs_not_arrived': 0, 'runs_unverified': 0, 'events_total': {},
                                   'plugin_injections': 0}}}
        resident = {'method': {'formula': 'f', 'scope': 's'},
                    'arms': {'current': {'label': '当前版', 'by_event': profile()['by_event'], 'total_tokens_est': 24,
                                         'errors': []},
                             'previous': {'label': '上一版', 'by_event': {'SessionStart': {'tokens_est': 5, 'chars': 6,
                                                                                         'hooks': 1, 'injecting_hooks': 1}},
                                          'total_tokens_est': 5, 'errors': []}},
                    'measured_first_request_input_tokens': {'none': 100, 'current': 200},
                    'measured_delta_vs_none': {'current': 100}}
        return {'injection_check': check, 'resident_tokens': resident,
                'arms': {'none': {'label': '不装'}, 'current': {'label': '当前版'}, 'previous': {'label': '上一版'}}}

    def test_banner_only_when_problems(self):
        self.assertEqual(injection_check.report_banner(self.rec(ok=True)), [])
        banner = '\n'.join(injection_check.report_banner(self.rec(ok=False)))
        self.assertIn('注入未到达', banner)
        self.assertIn('2/3', banner)
        self.assertEqual(injection_check.report_banner({'injection_check': None}), [])

    def test_sections_list_resident_tokens_per_arm(self):
        text = '\n'.join(injection_check.report_sections(self.rec()))
        self.assertIn('## 注入到达核验', text)
        self.assertIn('## 常驻 token', text)
        self.assertIn('| 事件 | 当前版 | 上一版 |', text)
        self.assertIn('| SessionStart | 8 | 5 |', text)
        self.assertIn('| UserPromptSubmit | 8 | — |', text)
        self.assertIn('+100', text)


if __name__ == '__main__':
    unittest.main()
