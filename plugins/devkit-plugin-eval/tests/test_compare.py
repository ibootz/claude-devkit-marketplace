"""接缝：compare 编排（假的 eval 运行器，不调模型）与命令行入口。"""
import io
import json
import re
import shutil
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import _support
from _support import tmpdir, aggregate, grader, make_plugin, make_sandbox, run_result
from plugin_eval_lib import cli, compare, registry

GRADERS = [grader('rule'), grader('marker', 'regex', arm='with-only')]


class FakeEval:
    """记下每次调用的命令，按臂名写 aggregate-result.json，并造 --keep-temp 沙箱。"""

    def __init__(self, sandbox_root, scores, drop_case=None):
        self.sandbox_root = Path(sandbox_root)
        self.scores = scores          # {臂名: 是否通过 rule}
        self.drop_case = drop_case    # (臂名, 用例名)：模拟该用例加载失败
        self.calls = []

    def __call__(self, cmd, cwd, env, log_dir):
        self.calls.append({'cmd': cmd, 'cwd': cwd, 'env': env})
        arm_dir = Path(cmd[3])
        arm = arm_dir.name
        out = Path(cmd[cmd.index('--output-dir') + 1])
        out.mkdir(parents=True, exist_ok=True)
        names = sorted(p.name for p in (arm_dir / 'evals').iterdir() if p.is_dir())
        stderr = ''
        if self.drop_case and self.drop_case[0] == arm:
            names.remove(self.drop_case[1])
            stderr = '1 case file(s) failed to load\n'
        cases = []
        for n in names:
            runs = []
            for i in range(int(cmd[cmd.index('--runs') + 1])):
                sb = make_sandbox(self.sandbox_root, '%s-%s-%d' % (arm, n, i))
                runs.append(run_result({'rule': self.scores[arm], 'marker': arm == 'current'},
                                       trace_path=str(sb / 'out' / 'trace.jsonl')))
            cases.append((n, GRADERS, runs))
        (out / 'aggregate-result.json').write_text(json.dumps(aggregate(cases, root=str(arm_dir))), encoding='utf-8')
        (Path(log_dir) / 'eval.stderr').write_text(stderr, encoding='utf-8')
        return 1, stderr


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.data = self.tmp / 'data'
        self.repo = self.tmp / 'repo'
        self.plugin = make_plugin(self.repo / 'plugins' / 'demo-plugin', cases=('case-a', 'case-b'))
        self.sandboxes = self.tmp / 'sandboxes'
        self.sandboxes.mkdir()
        self.assembly_parent = self.tmp / 'assembly'
        self.assembly_parent.mkdir()

    def run_compare(self, fake, **kw):
        return compare.run_compare(
            self.data, 'demo-plugin', runs=2, concurrency=2, claude='/fake/claude', runner=fake,
            env={'PATH': '/usr/bin'}, tmp_parent=self.assembly_parent, sandbox_roots=[self.sandboxes],
            log=lambda *a: None, **kw)

    def test_unregistered_plugin_rejected(self):
        with self.assertRaises(registry.NotRegistered):
            self.run_compare(FakeEval(self.sandboxes, {'none': False, 'current': True}))

    def test_happy_path_layout_and_record(self):
        registry.register(self.data, 'demo-plugin', self.repo)
        fake = FakeEval(self.sandboxes, {'none': False, 'current': True})
        res = self.run_compare(fake)

        self.assertEqual(res.exit_code, 0)
        self.assertRegex(res.run_dir.name, r'^\d{8}T\d{6}Z-1\.2\.3-compare$')
        self.assertEqual(res.run_dir.parent, self.repo.resolve() / 'plugin-evals' / 'demo-plugin' / 'runs')
        for rel in ('run.json', 'report.md', 'arms/none/aggregate-result.json', 'arms/current/aggregate-result.json'):
            self.assertTrue((res.run_dir / rel).exists(), rel)

        rec = json.loads((res.run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual(rec['kind'], 'compare')
        self.assertEqual(rec['review']['status'], '待审')
        self.assertTrue(rec['complete'])
        self.assertEqual(rec['arms']['none']['score'], 0)
        self.assertEqual(rec['arms']['current']['score'], 1)
        self.assertEqual(rec['delta']['overall'], 1)
        self.assertEqual(rec['cases'], ['case-a', 'case-b'])
        self.assertTrue(rec['plugin']['fingerprint'].startswith('sha256:'))
        self.assertEqual(rec['main_model'], 'claude-opus-5-5')
        self.assertGreater(rec['usage']['input_tokens'], 0)

        # 每臂都带 --trust-plugin（已登记），且在臂组装目录里跑
        self.assertEqual(len(fake.calls), 2)
        for call in fake.calls:
            self.assertIn('--trust-plugin', call['cmd'])
            self.assertEqual(call['cmd'][0], '/fake/claude')
        # 「不装」臂是空桩
        self.assertEqual([Path(c['cmd'][3]).name for c in fake.calls], ['none', 'current'])

        # 全量 trace 移到用户级 traces/，沙箱删掉
        traces_root = self.data / 'traces' / res.run_dir.name
        self.assertTrue((traces_root / 'none' / 'case-a-1' / 'trace.jsonl').exists())
        self.assertTrue((traces_root / 'current' / 'case-b-2' / 'projects').exists())
        self.assertEqual(list(self.sandboxes.iterdir()), [])
        # 臂组装目录清理掉
        self.assertEqual(list(self.assembly_parent.iterdir()), [])
        # 被测插件目录里不留 evals/results，且该目录写进仓根 .gitignore
        self.assertFalse((self.plugin / 'evals' / 'results').exists())
        self.assertIn('plugins/demo-plugin/evals/results/', (self.repo / '.gitignore').read_text().splitlines())

    def test_gitignore_line_added_once(self):
        registry.register(self.data, 'demo-plugin', self.repo)
        (self.repo / '.gitignore').write_text('node_modules/', encoding='utf-8')
        for minute in (1, 2):
            self.run_compare(FakeEval(self.sandboxes, {'none': False, 'current': True}),
                             now=lambda m=minute: datetime(2026, 10, 15, 8, m, tzinfo=timezone.utc))
        lines = (self.repo / '.gitignore').read_text().splitlines()
        self.assertEqual(lines.count('plugins/demo-plugin/evals/results/'), 1)
        self.assertEqual(lines[0], 'node_modules/')

    def test_load_failure_marks_incomplete(self):
        registry.register(self.data, 'demo-plugin', self.repo)
        res = self.run_compare(FakeEval(self.sandboxes, {'none': False, 'current': True},
                                        drop_case=('current', 'case-b')))
        self.assertNotEqual(res.exit_code, 0)
        rec = json.loads((res.run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertFalse(rec['complete'])
        self.assertFalse(rec['passed'])
        self.assertTrue(any('加载失败' in r for r in rec['incomplete_reasons']))

    def test_no_cases_is_error(self):
        shutil.rmtree(self.plugin / 'evals')
        registry.register(self.data, 'demo-plugin', self.repo)
        with self.assertRaises(compare.CompareError):
            self.run_compare(FakeEval(self.sandboxes, {'none': False, 'current': True}))

    @unittest.skipUnless(shutil.which('git'), 'git 不可用')
    def test_git_head_and_dirty_recorded(self):
        def git(*args):
            subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid',
                            '-c', 'commit.gpgsign=false', *args], check=True, capture_output=True)
        git('init', '-q')
        git('add', '-A')
        git('commit', '-q', '-m', 'init')
        head = subprocess.run(['git', '-C', str(self.repo), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        (self.plugin / 'hooks' / 'inject.js').write_text('changed', encoding='utf-8')
        registry.register(self.data, 'demo-plugin', self.repo)
        res = self.run_compare(FakeEval(self.sandboxes, {'none': False, 'current': True}))
        rec = json.loads((res.run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual(rec['arms']['current']['head_sha'], head)
        self.assertTrue(rec['arms']['current']['dirty'])


class CliTest(unittest.TestCase):
    def test_compare_unregistered_exits_2_with_hint(self):
        data = tmpdir(self)
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = cli.main(['--data-dir', str(data), 'compare', 'ghost'])
        self.assertEqual(code, 2)
        self.assertIn('register', err.getvalue())
        self.assertIn('ghost', err.getvalue())

    def test_register_then_list(self):
        tmp = tmpdir(self)
        repo = tmp / 'repo'
        make_plugin(repo / 'plugins' / 'demo-plugin')
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(['--data-dir', str(tmp / 'd'), 'register', 'demo-plugin', '--repo', str(repo)]), 0)
        self.assertIn('demo-plugin', out.getvalue())
        self.assertTrue(re.search(r'plugins/demo-plugin', out.getvalue()))


if __name__ == '__main__':
    unittest.main()
