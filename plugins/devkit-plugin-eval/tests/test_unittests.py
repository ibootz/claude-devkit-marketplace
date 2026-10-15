"""单测声明的 Python 实现：声明校验、解释器解析、执行、两处口径，以及与 JS 实现的共用样例对齐（票 14）。"""
import json
import shutil
import sys
import unittest
from pathlib import Path

from _support import tmpdir, write

from plugin_eval_lib import unittests as ut

# 共用样例在仓根 scripts/unit-tests-fixtures/；插件单独分发（缓存目录里）时没有这份样例，对齐用例跳过
FIXTURES = Path(__file__).resolve().parents[3] / 'scripts' / 'unit-tests-fixtures'
NODE = shutil.which('node')


def codes(text):
    return sorted({c for c, _ in ut.validate_declaration(text)[1]})


class ValidateTest(unittest.TestCase):
    def test_valid_fills_defaults(self):
        tests, errors = ut.validate_declaration('{"tests":[{"run":["node","a.js"]}]}')
        self.assertEqual(errors, [])
        self.assertEqual(tests, [{'run': ['node', 'a.js'], 'timeout_sec': 120,
                                  'platforms': ['darwin', 'linux', 'win32']}])

    def test_error_codes_match_js(self):
        """与 scripts/tests/run-unit-tests.test.js「声明校验：各类不合法给出稳定 code」逐条相同。"""
        self.assertEqual(codes('{'), ['not-json'])
        self.assertEqual(codes('null'), ['not-object'])
        self.assertEqual(codes('{"tests":{}}'), ['bad-tests'])
        self.assertEqual(codes('{"tests":[1]}'), ['bad-test'])
        self.assertEqual(codes('{"tests":[{"run":["node",""]}]}'), ['bad-run'])
        self.assertEqual(codes('{"tests":[{"run":["node",1]}]}'), ['bad-run'])
        self.assertEqual(codes('{"tests":[{"run":["node"],"timeout_sec":-1}]}'), ['bad-timeout'])
        self.assertEqual(codes('{"tests":[{"run":["node"],"platforms":"linux"}]}'), ['bad-platforms'])
        self.assertEqual(codes('{"tests":[],"version":1}'), ['unknown-field'])

    def test_python_specific_pitfalls(self):
        self.assertEqual(codes('{"tests":[{"run":["node"],"timeout_sec":NaN}]}'), ['not-json'])
        self.assertEqual(codes('{"tests":[{"run":["node"],"timeout_sec":Infinity}]}'), ['not-json'])
        self.assertEqual(codes('{"tests":[{"run":["node"],"timeout_sec":true}]}'), ['bad-timeout'])
        self.assertEqual(codes('{"tests":[{"run":["node"],"timeout_sec":1e400}]}'), ['bad-timeout'])
        self.assertEqual(codes('{"tests":[{"run":["node"],"timeout_sec":%s}]}' % ('9' * 400)), ['bad-timeout'])
        self.assertEqual(codes('﻿{"tests":[]}'), ['not-json'])   # JS 的 JSON.parse 不认 BOM


class ResolveTest(unittest.TestCase):
    def test_python3_fallback_order(self):
        tried = []

        def probe_ok(ok):
            def probe(argv):
                tried.append(' '.join(argv))
                return ' '.join(argv) == ok
            return probe
        find = lambda n: '/bin/%s' % n
        self.assertEqual(ut.resolve_interpreter('python3', probe=probe_ok('python'), find=find), ['/bin/python'])
        self.assertEqual(tried, ['python3', 'python'])
        self.assertEqual(ut.resolve_interpreter('python3', probe=probe_ok('py -3'), find=find), ['/bin/py', '-3'])
        self.assertIsNone(ut.resolve_interpreter('python3', probe=lambda a: False, find=find))
        self.assertIsNone(ut.resolve_interpreter('bash', find=lambda n: None))

    def test_windows_pathext_prefers_cmd(self):
        d = tmpdir(self)
        write(d / 'tool', '')
        write(d / 'tool.cmd', '')
        found = ut.find_executable('tool', env={'PATH': str(d), 'PATHEXT': '.EXE;.CMD'}, platform='win32')
        self.assertEqual(found.lower(), str(d / 'tool.cmd').lower())

    def test_relative_path_interpreter_resolved_against_plugin_root(self):
        d = tmpdir(self)
        write(d / 'bin' / 'x', '')
        self.assertEqual(ut.find_executable('bin/x', cwd=str(d)), str((d / 'bin' / 'x').resolve()))
        self.assertIsNone(ut.find_executable('bin/missing', cwd=str(d)))


class RunTest(unittest.TestCase):
    def _plugin(self, decl, files=None):
        d = tmpdir(self)
        write(d / 'unit-tests.json', json.dumps(decl))
        for name, text in (files or {}).items():
            write(d / name, text)
        return d

    def test_gate_verdict_by_status(self):
        py = sys.executable
        d = self._plugin({'tests': [
            {'run': [py, 'ok.py']},
            {'run': ['devkit-no-such-interpreter', 'ok.py']},
            {'run': [py, 'ok.py'], 'platforms': ['win32' if ut.current_platform() != 'win32' else 'linux']},
        ]}, {'ok.py': 'print("ok")\n'})
        res = ut.run_plugin(d)
        self.assertEqual([t['status'] for t in res['tests']], ['passed', 'interpreter-missing', 'skipped-platform'])
        ok, lines = ut.gate_verdict(res)
        self.assertFalse(ok)                                   # 闸门：解释器解析不到判失败
        self.assertEqual(ut.precommit_verdict(res), 'pass')    # pre-commit：只警告
        self.assertTrue(any('解析不到' in ln for ln in lines))

    def test_failure_and_timeout_fail_gate(self):
        py = sys.executable
        d = self._plugin({'tests': [{'run': [py, 'bad.py']}, {'run': [py, 'slow.py'], 'timeout_sec': 1}]},
                         {'bad.py': 'import sys; print("boom"); sys.exit(3)\n',
                          'slow.py': 'import time; time.sleep(30)\n'})
        res = ut.run_plugin(d)
        self.assertEqual([t['status'] for t in res['tests']], ['failed', 'timeout'])
        self.assertLess(res['tests'][1]['ms'], 10000)
        ok, lines = ut.gate_verdict(res)
        self.assertFalse(ok)
        self.assertTrue(any('退出码 3' in ln for ln in lines))
        self.assertTrue(any('boom' in ln for ln in lines))

    def test_undeclared_only_hints(self):
        ok, lines = ut.gate_verdict(ut.run_plugin(tmpdir(self)))
        self.assertTrue(ok)
        self.assertIn('未声明单测', lines[0])

    def test_invalid_fails_gate(self):
        d = tmpdir(self)
        write(d / 'unit-tests.json', '{"tests": [')
        res = ut.run_plugin(d)
        self.assertEqual((res['declaration'], res['errors']), ('invalid', ['not-json']))
        self.assertFalse(ut.gate_verdict(res)[0])

    def test_non_utf8_declaration_is_invalid(self):
        d = tmpdir(self)
        (d / 'unit-tests.json').write_bytes('{"tests": [{"run": ["python3", "测试.py"]}]}'.encode('gbk'))
        res = ut.run_plugin(d)
        self.assertEqual((res['declaration'], res['errors']), ('invalid', ['not-json']))
        self.assertIn('不是 UTF-8', res['messages'][0])
        self.assertFalse(ut.gate_verdict(res)[0])

    def test_git_local_env_stripped(self):
        env = ut.child_env({'GIT_DIR': '/x', 'GIT_INDEX_FILE': '/y', 'KEEP': '1'})
        self.assertNotIn('GIT_DIR', env)
        self.assertNotIn('GIT_INDEX_FILE', env)
        self.assertEqual(env['KEEP'], '1')


@unittest.skipUnless(FIXTURES.is_dir(), '不在本仓里（插件单独分发），没有共用样例')
@unittest.skipUnless(NODE, '样例脚本要 node')
class SharedFixturesTest(unittest.TestCase):
    """仓根 scripts/unit-tests-fixtures/ 的每个样例：Python 实现的结论必须与 JS 实现写下的 expected.json 一致。"""

    def test_every_fixture_matches_js(self):
        dirs = sorted(p for p in FIXTURES.iterdir() if (p / 'expected.json').is_file())
        self.assertGreaterEqual(len(dirs), 20)
        for d in dirs:
            exp = json.loads((d / 'expected.json').read_text(encoding='utf-8'))
            with self.subTest(fixture=d.name):
                res = ut.run_plugin(d, platform=exp['platform'])
                got = {'declaration': res['declaration'], 'errors': res['errors'],
                       'tests': [{'index': t['index'], 'status': t['status']} for t in res['tests']],
                       'precommit': ut.precommit_verdict(res)}
                self.assertEqual(got, {k: exp[k] for k in got})
                # 闸门口径由 declaration 与逐条状态推出（expected.json 不另存）
                gate_ok = ut.gate_verdict(res)[0]
                self.assertEqual(gate_ok, exp['declaration'] != 'invalid' and not any(
                    t['status'] in ('failed', 'timeout', 'interpreter-missing') for t in exp['tests']))


if __name__ == '__main__':
    unittest.main()
