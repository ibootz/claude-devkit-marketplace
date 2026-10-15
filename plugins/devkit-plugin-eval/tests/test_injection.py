"""接缝：读被测插件的 hook 声明；在真实 HOME、空临时 cwd 下执行常驻注入 hook，按输出估 token。"""
import json
import os
import shlex
import sys
import unittest
from pathlib import Path

import _support
from _support import tmpdir, write
from plugin_eval_lib import injection

PY = shlex.quote(sys.executable) if os.name != 'nt' else '"%s"' % sys.executable

# 被测 hook：按 hook_event_name 输出不同注入；环境变量 FAIL_EVENT 命中时照常输出、以 FAIL_CODE（缺省 3）退出
HOOK_SRC = r'''
import json, os, sys
ev = json.load(sys.stdin)
name = ev.get("hook_event_name")
if os.environ.get("FAIL_EVENT") == name:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": "# 会失败的注入"}}))
    sys.exit(int(os.environ.get("FAIL_CODE", "3")))
texts = {"SessionStart": "# 会话级纪律\n\n第一条：先读再写。",
         "UserPromptSubmit": "# 每轮要点 abc\n\nkeep going",
         "SubagentStart": "# 子代理版纪律（%s）" % ev.get("agent_type")}
if name in texts:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": texts[name]}}))
'''
PLAIN_SRC = 'import sys\nsys.stdin.read()\nprint("纯文本注入 plain")\n'
SILENT_SRC = 'import sys\nsys.stdin.read()\n'
ECHO_ENV_SRC = r'''
import json, os, sys
ev = json.load(sys.stdin)
out = {"cwd": os.getcwd(), "ev": ev, "root": os.environ.get("CLAUDE_PLUGIN_ROOT"),
       "data": os.environ.get("CLAUDE_PLUGIN_DATA"), "argv": sys.argv[1:]}
print(json.dumps({"hookSpecificOutput": {"additionalContext": json.dumps(out)}}))
'''


def hook_cmd(script, *args):
    return ' '.join([PY, '${CLAUDE_PLUGIN_ROOT}/hooks/%s' % script] + list(args))


def make_hook_plugin(root, hooks, name='inj-plugin', files=None, version='1.0.0'):
    root = Path(root)
    write(root / '.claude-plugin' / 'plugin.json', json.dumps({'name': name, 'version': version, 'hooks': hooks}))
    for fname, src in (files or {'inj.py': HOOK_SRC}).items():
        write(root / 'hooks' / fname, src)
    return root


def std_hooks(extra_ups=()):
    return {
        'SessionStart': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': hook_cmd('inj.py')}]}],
        'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': hook_cmd('inj.py')}] + list(extra_ups)}],
        'SubagentStart': [{'hooks': [{'type': 'command', 'command': hook_cmd('inj.py')}]}],
        'PreToolUse': [{'matcher': 'Agent', 'hooks': [{'type': 'command', 'command': hook_cmd('inj.py')}]}],
    }


class LoadHookSpecsTest(unittest.TestCase):
    def test_inline_hooks_in_plugin_json(self):
        root = make_hook_plugin(tmpdir(self) / 'p', std_hooks())
        specs = injection.load_hook_specs(root)
        self.assertEqual([s.event for s in specs], ['SessionStart', 'UserPromptSubmit', 'SubagentStart', 'PreToolUse'])
        self.assertEqual(specs[0].matcher, '*')
        self.assertEqual(specs[1].matcher, None)
        self.assertEqual(specs[3].matcher, 'Agent')
        self.assertEqual(specs[0].command, hook_cmd('inj.py'))

    def test_default_hooks_json_and_string_path(self):
        tmp = tmpdir(self)
        root = tmp / 'p'
        write(root / '.claude-plugin' / 'plugin.json', json.dumps({'name': 'x', 'hooks': './extra/more.json'}))
        write(root / 'hooks' / 'hooks.json', json.dumps({'description': 'd', 'hooks': {
            'SessionStart': [{'hooks': [{'type': 'command', 'command': 'echo a', 'timeout': 5}]}]}}))
        write(root / 'extra' / 'more.json', json.dumps({'hooks': {
            'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': 'echo b'},
                                            {'type': 'prompt', 'prompt': 'ignored'}]}]}}))
        specs = injection.load_hook_specs(root)
        self.assertEqual([(s.event, s.command, s.timeout) for s in specs],
                         [('UserPromptSubmit', 'echo b', None), ('SessionStart', 'echo a', 5)])   # plugin.json 声明的在前

    def test_plugin_json_pointing_at_default_file_not_loaded_twice(self):
        root = tmpdir(self) / 'p'
        write(root / '.claude-plugin' / 'plugin.json', json.dumps({'name': 'x', 'hooks': './hooks/hooks.json'}))
        write(root / 'hooks' / 'hooks.json', json.dumps({'hooks': {
            'SessionStart': [{'hooks': [{'type': 'command', 'command': 'echo a'}]}]}}))
        self.assertEqual(len(injection.load_hook_specs(root)), 1)

    def test_no_hooks(self):
        root = tmpdir(self) / 'p'
        write(root / '.claude-plugin' / 'plugin.json', json.dumps({'name': 'x'}))
        self.assertEqual(injection.load_hook_specs(root), [])

    def test_key_is_event_matcher_command(self):
        spec = injection.HookSpec('PreToolUse', 'Agent', 'node ${CLAUDE_PLUGIN_ROOT}/hooks/a.js', None)
        self.assertEqual(spec.key, 'PreToolUse|Agent|node ${CLAUDE_PLUGIN_ROOT}/hooks/a.js')


class ExtractAndEstimateTest(unittest.TestCase):
    def test_extract_json_additional_context(self):
        out = json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': 'hello'}})
        self.assertEqual(injection.extract_injection('SessionStart', out + '\n'), 'hello')

    def test_plain_stdout_counts_only_for_sessionstart_and_userpromptsubmit(self):
        self.assertEqual(injection.extract_injection('UserPromptSubmit', '  纯文本\n'), '纯文本')
        self.assertEqual(injection.extract_injection('SessionStart', 'x'), 'x')
        self.assertIsNone(injection.extract_injection('SubagentStart', 'x'))

    def test_json_without_context_or_empty(self):
        self.assertIsNone(injection.extract_injection('SessionStart', '{"continue": true}'))
        self.assertIsNone(injection.extract_injection('SessionStart', ''))
        self.assertIsNone(injection.extract_injection('SessionStart', '{"hookSpecificOutput": {"additionalContext": ""}}'))

    def test_estimate_tokens_wide_vs_narrow(self):
        self.assertEqual(injection.estimate_tokens(''), 0)
        # 100 个汉字 ≈ 133；100 个 ASCII ≈ 29
        self.assertEqual(injection.estimate_tokens('字' * 100), 133)
        self.assertEqual(injection.estimate_tokens('a' * 100), 29)
        self.assertEqual(injection.estimate_tokens('字' * 100 + 'a' * 100), 162)

    def test_label_is_first_nonempty_line_truncated(self):
        self.assertEqual(injection.content_label('\n\n# 标题 abc  \n正文'), '# 标题 abc')
        self.assertEqual(len(injection.content_label('x' * 500)), injection.LABEL_MAX)
        self.assertIsNone(injection.content_label('  \n '))


class RunHookTest(unittest.TestCase):
    def test_runs_in_empty_cwd_with_plugin_vars_and_event_payload(self):
        tmp = tmpdir(self)
        root = make_hook_plugin(tmp / 'p', {}, files={'echo.py': ECHO_ENV_SRC})
        spec = injection.HookSpec('SubagentStart', None, hook_cmd('echo.py', '${CLAUDE_PLUGIN_DATA}'), None)
        res = injection.run_hook(spec, root, env=dict(os.environ), work_parent=tmp / 'work')
        self.assertEqual(res['exit_code'], 0)
        out = json.loads(res['raw_text'])
        self.assertEqual(out['ev']['hook_event_name'], 'SubagentStart')
        self.assertEqual(out['ev']['agent_type'], 'general-purpose')
        self.assertEqual(os.path.realpath(out['root']), os.path.realpath(str(root)))
        self.assertEqual(out['argv'], [out['data']])                      # ${CLAUDE_PLUGIN_DATA} 已替换
        self.assertNotEqual(os.path.realpath(out['data']), os.path.realpath(str(root)))
        self.assertEqual(os.path.realpath(out['cwd']), os.path.realpath(out['ev']['cwd']))
        self.assertFalse((tmp / 'work').exists() and any((tmp / 'work').iterdir()))   # 临时目录已清理

    def test_sessionstart_source_follows_matcher(self):
        tmp = tmpdir(self)
        root = make_hook_plugin(tmp / 'p', {}, files={'echo.py': ECHO_ENV_SRC})
        for matcher, source in (('*', 'startup'), (None, 'startup'), ('startup|resume', 'startup'), ('compact', 'compact')):
            spec = injection.HookSpec('SessionStart', matcher, hook_cmd('echo.py'), None)
            out = json.loads(injection.run_hook(spec, root, env=dict(os.environ), work_parent=tmp)['raw_text'])
            self.assertEqual(out['ev']['source'], source, matcher)

    def test_nonzero_exit_other_than_2_still_injects(self):
        # 2.1.300 实测：UserPromptSubmit hook 输出 JSON 后以 3 退出，additionalContext 照样进了转录
        tmp = tmpdir(self)
        root = make_hook_plugin(tmp / 'p', {})
        env = dict(os.environ, FAIL_EVENT='UserPromptSubmit')
        res = injection.run_hook(injection.HookSpec('UserPromptSubmit', None, hook_cmd('inj.py'), None),
                                 root, env=env, work_parent=tmp)
        self.assertEqual(res['exit_code'], 3)
        self.assertEqual(res['raw_text'], '# 会失败的注入')
        self.assertEqual(res['text'], '# 会失败的注入')

    def test_exit_2_drops_output(self):
        tmp = tmpdir(self)
        root = make_hook_plugin(tmp / 'p', {})
        env = dict(os.environ, FAIL_EVENT='UserPromptSubmit', FAIL_CODE='2')
        res = injection.run_hook(injection.HookSpec('UserPromptSubmit', None, hook_cmd('inj.py'), None),
                                 root, env=env, work_parent=tmp)
        self.assertEqual(res['exit_code'], 2)
        self.assertEqual(res['raw_text'], '# 会失败的注入')
        self.assertIsNone(res['text'])

    def test_timeout(self):
        tmp = tmpdir(self)
        root = make_hook_plugin(tmp / 'p', {}, files={'slow.py': 'import time\ntime.sleep(5)\n'})
        res = injection.run_hook(injection.HookSpec('SessionStart', None, hook_cmd('slow.py'), 1),
                                 root, env=dict(os.environ), work_parent=tmp)
        self.assertTrue(res['timed_out'])
        self.assertIsNone(res['text'])


class StaticProfileTest(unittest.TestCase):
    def test_profile_by_event(self):
        tmp = tmpdir(self)
        silent = {'type': 'command', 'command': hook_cmd('silent.py')}
        root = make_hook_plugin(tmp / 'p', std_hooks(extra_ups=[silent]),
                                files={'inj.py': HOOK_SRC, 'silent.py': SILENT_SRC})
        prof = injection.static_profile(root, env=dict(os.environ), work_parent=tmp)
        by = prof['by_event']
        self.assertEqual(by['SessionStart']['injecting_hooks'], 1)
        self.assertEqual(by['SessionStart']['tokens_est'], injection.estimate_tokens('# 会话级纪律\n\n第一条：先读再写。'))
        self.assertEqual(by['UserPromptSubmit']['hooks'], 2)
        self.assertEqual(by['UserPromptSubmit']['injecting_hooks'], 1)
        self.assertIn('SubagentStart', by)
        self.assertNotIn('PreToolUse', by)                       # 条件注入不执行
        self.assertEqual([h['event'] for h in prof['conditional_hooks']], ['PreToolUse'])
        ups = [h for h in prof['hooks'] if h['event'] == 'UserPromptSubmit']
        self.assertEqual(ups[0]['label'], '# 每轮要点 abc')
        self.assertTrue(ups[0]['expected'])
        self.assertFalse(ups[1]['expected'])                      # 静态无输出：条件注入，不核验到达
        self.assertEqual(prof['total_tokens_est'], sum(v['tokens_est'] for v in by.values()))
        self.assertIn('method', prof)

    def test_nonzero_exit_counted_but_flagged(self):
        tmp = tmpdir(self)
        root = make_hook_plugin(tmp / 'p', std_hooks())
        prof = injection.static_profile(root, env=dict(os.environ, FAIL_EVENT='UserPromptSubmit'), work_parent=tmp)
        ups = [h for h in prof['hooks'] if h['event'] == 'UserPromptSubmit'][0]
        self.assertEqual(ups['exit_code'], 3)
        self.assertTrue(ups['expected'])
        self.assertEqual(ups['tokens_est'], injection.estimate_tokens('# 会失败的注入'))
        self.assertEqual(ups['label'], '# 会失败的注入')
        self.assertIn('退出码 3', prof['errors'][0])

    def test_missing_script_expected_without_label(self):
        tmp = tmpdir(self)
        hooks = {'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': hook_cmd('gone.py')}]}]}
        root = make_hook_plugin(tmp / 'p', hooks)
        prof = injection.static_profile(root, env=dict(os.environ), work_parent=tmp)
        h = prof['hooks'][0]
        self.assertNotEqual(h['exit_code'], 0)
        self.assertTrue(h['expected'])            # 失败时不知道它会不会注入，从严算应到达
        self.assertIsNone(h['label'])
        self.assertEqual(h['tokens_est'], 0)
        self.assertTrue(prof['errors'])

    def test_malformed_hooks_file_recorded_not_raised(self):
        root = tmpdir(self) / 'p'
        write(root / '.claude-plugin' / 'plugin.json', json.dumps({'name': 'x'}))
        write(root / 'hooks' / 'hooks.json', '{not json')
        prof = injection.static_profile(root, env=dict(os.environ))
        self.assertEqual(prof['hooks'], [])
        self.assertIn('读 hook 声明失败', prof['errors'][0])

    def test_no_hooks_profile(self):
        root = tmpdir(self) / 'p'
        write(root / '.claude-plugin' / 'plugin.json', json.dumps({'name': 'x'}))
        prof = injection.static_profile(root, env=dict(os.environ))
        self.assertEqual(prof['hooks'], [])
        self.assertEqual(prof['total_tokens_est'], 0)


if __name__ == '__main__':
    unittest.main()
