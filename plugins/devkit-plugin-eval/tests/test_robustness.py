"""接缝：中途出错时的收尾——断开的符号链接、eval 子进程超时、没被认领的 eval 沙箱。"""
import json
import os
import sys
import time
import unittest
from pathlib import Path

import _support
from _support import tmpdir, make_plugin, write
from plugin_eval_lib import arms, compare, evalrun, registry, sandbox_sweep
from test_compare import passing_preflight


class DanglingSymlinkTest(unittest.TestCase):
    @unittest.skipIf(sys.platform == 'win32', 'Windows 建符号链接要权限')
    def test_assemble_skips_dangling_symlink(self):
        tmp = tmpdir(self)
        plugin = make_plugin(tmp / 'p')
        os.symlink(str(tmp / 'gone'), str(plugin / 'hooks' / 'dangling.js'))
        os.symlink(str(tmp / 'gone'), str(plugin / 'evals' / 'case-a' / 'dangling.md'))
        dest = arms.assemble_arm(tmp / 'asm', arms.ArmSpec('current', '当前版', plugin), plugin / 'evals')
        self.assertTrue((dest / 'hooks' / 'inject.js').is_file())
        self.assertFalse(os.path.lexists(dest / 'hooks' / 'dangling.js'))
        self.assertTrue((dest / 'evals' / 'case-a' / 'prompt.md').is_file())


class EvalTimeoutTest(unittest.TestCase):
    def test_timeout_kills_and_returns_124(self):
        log_dir = tmpdir(self) / 'log'
        t0 = time.monotonic()
        code, stderr = evalrun.run_eval([sys.executable, '-c', 'import time; time.sleep(60)'],
                                        cwd=str(log_dir.parent), env=dict(os.environ), log_dir=log_dir, timeout=1)
        self.assertLess(time.monotonic() - t0, 30)
        self.assertEqual(code, evalrun.EVAL_TIMEOUT_EXIT_CODE)
        self.assertIn('超时', stderr)
        self.assertIn('超时', (log_dir / 'eval.stderr').read_text(encoding='utf-8'))

    def test_no_timeout_by_default(self):
        log_dir = tmpdir(self) / 'log'
        code, _ = evalrun.run_eval([sys.executable, '-c', 'print("ok")'], cwd=str(log_dir.parent),
                                   env=dict(os.environ), log_dir=log_dir)
        self.assertEqual(code, 0)

    def test_runner_with_timeout_binds_seconds(self):
        self.assertIs(evalrun.runner_with_timeout(None), evalrun.run_eval)
        r = evalrun.runner_with_timeout(5)
        self.assertEqual(r.keywords, {'timeout': 5})


def _sandbox_with_plugin(root, label, plugin_path):
    sb = Path(root) / ('e-' + label)
    init = {'type': 'system', 'subtype': 'init', 'model': 'm',
            'plugins': [{'name': 'x', 'path': str(plugin_path), 'source': 'x@inline'}]}
    write(sb / 'out' / 'trace.jsonl', json.dumps(init) + '\n')
    write(sb / 'config' / 'projects' / 'p' / 's.jsonl', '{}\n')
    (sb / 'sealed').mkdir()
    os.chmod(sb / 'sealed', 0)
    os.chmod(sb, 0o500)
    return sb


class SandboxSweepTest(unittest.TestCase):
    def test_claims_only_sandboxes_of_this_arm(self):
        tmp = tmpdir(self)
        roots = tmp / 'tmproot'
        roots.mkdir()
        arm_dir = tmp / 'asm' / 'current'
        arm_dir.mkdir(parents=True)
        mine = _sandbox_with_plugin(roots, 'mine', arm_dir)
        other = _sandbox_with_plugin(roots, 'other', tmp / 'someone-else')
        write(roots / 'e-notrace' / 'x.txt', 'x')
        dest = tmp / 'dest'
        warnings = sandbox_sweep.sweep_orphans(arm_dir, dest, [roots])
        self.assertEqual(warnings, [])
        self.assertFalse(mine.exists())
        self.assertTrue((dest / 'orphan-e-mine' / 'trace.jsonl').is_file())
        self.assertTrue(other.exists())
        self.assertTrue((roots / 'e-notrace').exists())

    def test_compare_without_aggregate_cleans_its_sandboxes(self):
        tmp = tmpdir(self)
        data, repo = tmp / 'data', tmp / 'repo'
        make_plugin(repo / 'plugins' / 'demo-plugin')
        registry.register(data, 'demo-plugin', repo)
        sandboxes = tmp / 'sb'
        sandboxes.mkdir()

        def runner(cmd, cwd, env, log_dir):
            _sandbox_with_plugin(sandboxes, Path(cmd[3]).name, cmd[3])
            (Path(log_dir) / 'eval.stderr').write_text('boom', encoding='utf-8')
            return 2, 'boom'

        res = compare.run_compare(data, 'demo-plugin', runs=1, concurrency=1, claude='/fake/claude', runner=runner,
                                  env={'PATH': '/usr/bin'}, tmp_parent=tmp, sandbox_roots=[sandboxes],
                                  log=lambda *a: None, preflight_check=passing_preflight)
        self.assertFalse(res.record['complete'])
        self.assertEqual(list(sandboxes.iterdir()), [])
        self.assertTrue((data / 'traces' / res.run_dir.name / 'current' / 'orphan-e-current' / 'trace.jsonl').is_file())


if __name__ == '__main__':
    unittest.main()
