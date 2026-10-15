"""接缝：解析 claude 可执行路径、子进程环境、eval 命令行。"""
import os
import unittest
from pathlib import Path

import _support
from _support import tmpdir
from plugin_eval_lib import evalrun


class ResolveClaudeTest(unittest.TestCase):
    def test_returns_absolute_path_from_which(self):
        got = evalrun.resolve_claude(which=lambda name, path=None: '/opt/bin/claude')
        self.assertEqual(got, '/opt/bin/claude')

    def test_windows_cmd_path_kept(self):
        got = evalrun.resolve_claude(which=lambda name, path=None: r'C:\npm\claude.CMD')
        self.assertEqual(got, r'C:\npm\claude.CMD')

    def test_missing_raises(self):
        with self.assertRaises(evalrun.ClaudeNotFound):
            evalrun.resolve_claude(which=lambda name, path=None: None)


class ChildEnvTest(unittest.TestCase):
    def test_strips_asdf_shims_and_session_vars(self):
        base = {
            'PATH': os.pathsep.join(['/Users/u/.asdf/shims', '/opt/homebrew/bin', '/usr/bin']),
            'CLAUDE_CODE_SESSION_ID': 'x', 'CLAUDE_CODE_ENTRYPOINT': 'cli', 'HOME': '/Users/u',
        }
        env = evalrun.child_env(base)
        self.assertEqual(env['PATH'], os.pathsep.join(['/opt/homebrew/bin', '/usr/bin']))
        self.assertNotIn('CLAUDE_CODE_SESSION_ID', env)
        self.assertNotIn('CLAUDE_CODE_ENTRYPOINT', env)
        self.assertEqual(env['HOME'], '/Users/u')
        self.assertIn('CLAUDE_CODE_SESSION_ID', base)  # 不改入参

    def test_windows_style_shim_path_stripped(self):
        env = evalrun.child_env({'PATH': r'C:\Users\u\.asdf\shims;C:\node'}, pathsep=';')
        self.assertEqual(env['PATH'], r'C:\node')


class CommandTest(unittest.TestCase):
    def test_eval_command_has_required_flags(self):
        cmd = evalrun.build_eval_command('/opt/claude', Path('/tmp/arm'), Path('/tmp/out'),
                                         runs=3, concurrency=2, report_path=Path('/tmp/t/report.html'))
        self.assertEqual(cmd[:4], ['/opt/claude', 'plugin', 'eval', str(Path('/tmp/arm'))])
        joined = ' '.join(cmd)
        for flag in ('--ablation none', '--keep-temp', '--no-publish', '--trust-plugin', '--scaffold',
                     '--runs 3', '-j 2', '--output-dir ' + str(Path('/tmp/out')),
                     '--report ' + str(Path('/tmp/t/report.html'))):
            self.assertIn(flag, joined)
        self.assertNotIn('--model', cmd)

    def test_model_passthrough(self):
        cmd = evalrun.build_eval_command('/c', Path('/a'), Path('/o'), runs=1, concurrency=1,
                                         report_path=Path('/r.html'), model='sonnet')
        self.assertEqual(cmd[cmd.index('--model') + 1], 'sonnet')

    def test_find_aggregate_result(self):
        out = tmpdir(self)
        self.assertIsNone(evalrun.find_aggregate(out))
        (out / 'nested').mkdir()
        (out / 'nested' / 'aggregate-result.json').write_text('{}')
        self.assertEqual(evalrun.find_aggregate(out), out / 'nested' / 'aggregate-result.json')


if __name__ == '__main__':
    unittest.main()
