"""接缝：compare 编排里的上一版臂与环境插件臂（假的 eval 运行器，真 git 造历史）。"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import _support
from _support import tmpdir, write
from plugin_eval_lib import armplan, compare, envplugins, preflight, previous, registry, resume
from test_compare import FakeEval

GIT = shutil.which('git')


def manifest(d, name, version, note=''):
    write(Path(d) / '.claude-plugin' / 'plugin.json', json.dumps({
        'name': name, 'version': version, 'description': '多臂编排单测插件' + note,
        'author': {'name': 'tester'}, 'license': 'MIT', 'keywords': ['eval', 'demo', 'arms'],
    }, ensure_ascii=False, indent=2) + '\n')


def make_cases(d, skill_ref=None):
    for c in ('case-a', 'case-b'):
        write(Path(d) / 'evals' / c / 'prompt.md', '---\nname: %s\n---\n做点事\n' % c)
        write(Path(d) / 'evals' / c / 'graders' / 'g1.md', '---\ntype: regex\ntarget: last_message\npattern: ok\n---\n')
    if skill_ref:
        write(Path(d) / 'evals' / 'case-b' / 'graders' / 'skill.md',
              '---\ntype: regex\ntarget: trace\npattern: "%s"\n---\n' % skill_ref)


class InspectingEval(FakeEval):
    """另记下每个臂组装目录里的插件名、环境插件目录与 case-a 的 prompt.md。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.seen = {}

    def __call__(self, cmd, cwd, env, log_dir):
        arm_dir = Path(cmd[3])
        env_root = arm_dir / envplugins.ENV_DIR
        self.seen[arm_dir.name] = {
            'name': json.loads((arm_dir / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))['name'],
            'hook': (arm_dir / 'hooks' / 'a.js').read_text(encoding='utf-8') if (arm_dir / 'hooks' / 'a.js').exists() else None,
            'env': sorted(p.name for p in env_root.iterdir()) if env_root.is_dir() else [],
            'prompt': (arm_dir / 'evals' / 'case-a' / 'prompt.md').read_text(encoding='utf-8'),
        }
        return super().__call__(cmd, cwd, env, log_dir)


SCORES = {'none': False, 'previous': False, 'current': True, 'current_with_env': True}


@unittest.skipUnless(GIT, 'git 不可用')
class MultiArmTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.data = self.tmp / 'data'
        self.repo = self.tmp / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.plugin = self.repo / 'plugins' / 'demo-plugin'
        manifest(self.plugin, 'demo-plugin', '1.0.0')
        write(self.plugin / 'hooks' / 'a.js', 'v1\n')
        make_cases(self.plugin)
        self.c1 = self.commit('1.0.0')
        write(self.plugin / 'hooks' / 'a.js', 'v1 fix\n')
        self.c2 = self.commit('1.0.0 fix')
        manifest(self.plugin, 'demo-plugin', '1.2.3')
        write(self.plugin / 'hooks' / 'a.js', 'v2\n')
        self.c3 = self.commit('1.2.3')
        self.sandboxes = self.tmp / 'sandboxes'
        self.sandboxes.mkdir()
        self.assembly_parent = self.tmp / 'assembly'
        self.assembly_parent.mkdir()
        self.validated = []
        self.preflight_kw = []
        self.validate_problem = None

    def git(self, *args, cwd=None):
        return subprocess.run(['git', '-C', str(cwd or self.repo), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid',
                               '-c', 'commit.gpgsign=false', *args], check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, msg):
        self.git('add', '-A')
        self.git('commit', '-q', '-m', msg)
        return self.git('rev-parse', 'HEAD')

    def preflight(self, **kw):
        """假的前置检查：记下 compare 交来的快照与环境插件（validate / 冒烟对象），可按需判 validate 失败。"""
        self.preflight_kw.append(kw)
        rep = preflight.Report('compare')
        for label, d in kw.get('others') or []:
            self.validated.append(Path(d))
            if self.validate_problem:
                rep.add(preflight.Item('plugin_valid', '插件结构合法', preflight.HARD, preflight.FAIL,
                                       '[%s] %s' % (label, self.validate_problem)))
        return rep

    def run_compare(self, fake, name='demo-plugin', **kw):
        kw.setdefault('preflight_check', self.preflight)
        return compare.run_compare(
            self.data, name, runs=1, concurrency=1, claude='/fake/claude', runner=fake,
            env={'PATH': '/usr/bin'}, tmp_parent=self.assembly_parent, sandbox_roots=[self.sandboxes],
            log=lambda *a: None, **kw)

    def load(self, res):
        rec = json.loads((res.run_dir / 'run.json').read_text(encoding='utf-8'))
        return rec, (res.run_dir / 'report.md').read_text(encoding='utf-8')

    def test_auto_previous_arm(self):
        registry.register(self.data, 'demo-plugin', self.repo)
        fake = InspectingEval(self.sandboxes, SCORES)
        res = self.run_compare(fake)
        rec, report = self.load(res)

        self.assertEqual([Path(c['cmd'][3]).name for c in fake.calls], ['none', 'previous', 'current'])
        self.assertEqual(fake.seen['previous']['hook'], 'v1\n')     # 引入提交 c1 的内容，不是同号的 c2
        prev = rec['arms']['previous']
        self.assertEqual((prev['source'], prev['commit'], prev['version'], prev['obtained_by']),
                         ('git-snapshot', self.c1, '1.0.0', 'auto'))
        self.assertFalse(prev['cross_rename'])
        self.assertTrue(prev['fingerprint'].startswith('sha256:'))
        self.assertEqual(rec['arms']['current']['head_sha'], self.c3)
        # 票 05 (a)：快照取自历史提交，没有工作区；当前版的 HEAD / dirty 不属于它
        self.assertEqual((prev['head_sha'], prev['dirty']), (None, None))
        self.assertEqual(rec['previous_arm']['degraded'], False)
        self.assertEqual(rec['delta_vs_previous']['overall'], 1)
        self.assertIsNone(rec['delta_env_vs_current'])
        self.assertEqual(rec['env_plugins'], [])
        self.assertIn('## 上一版与当前版', report)
        self.assertIn(self.c1[:12], report.split('> 状态')[0])
        self.assertIn('| 差（当前版 − 上一版） | +1.00 |', report)
        self.assertIn(Path(self.validated[0]).name, ('demo-plugin', 'snapshot'))
        self.assertEqual(list(self.assembly_parent.iterdir()), [])    # 快照与组装目录都清掉

    def test_base_version_and_commit(self):
        registry.register(self.data, 'demo-plugin', self.repo)
        fake = InspectingEval(self.sandboxes, SCORES)
        rec, _ = self.load(self.run_compare(fake, base=self.c2))
        self.assertEqual((rec['arms']['previous']['commit'], rec['arms']['previous']['obtained_by']), (self.c2, '--base'))
        self.assertEqual(fake.seen['previous']['hook'], 'v1 fix\n')
        rec2, _ = self.load(self.run_compare(InspectingEval(self.sandboxes, SCORES), base='1.0.0',
                                             now=lambda: compare.datetime(2026, 10, 15, 9, 0, tzinfo=compare.timezone.utc)))
        self.assertEqual(rec2['arms']['previous']['commit'], self.c1)
        self.assertEqual(rec2['previous_arm']['base'], '1.0.0')

    def test_unknown_base_aborts_before_run_dir(self):
        registry.register(self.data, 'demo-plugin', self.repo)
        with self.assertRaises(armplan.ArmSourceError):
            self.run_compare(InspectingEval(self.sandboxes, SCORES), base='no-such-version')
        self.assertFalse((self.repo / 'plugin-evals').exists())

    def test_snapshot_validate_failure_aborts(self):
        registry.register(self.data, 'demo-plugin', self.repo)
        self.validate_problem = 'manifest 不合法'
        with self.assertRaises(preflight.PreflightFailed) as cm:
            self.run_compare(InspectingEval(self.sandboxes, SCORES))
        self.assertIn('上一版快照', str(cm.exception))
        self.assertEqual(list(self.assembly_parent.iterdir()), [])     # 前置检查失败也清掉快照
        self.assertFalse((self.repo / 'plugin-evals').exists())         # 硬项在任何仓库写入之前
        self.assertFalse((self.repo / '.gitignore').exists())

    def test_snapshot_failure_degrades(self):
        registry.register(self.data, 'demo-plugin', self.repo)
        fake = InspectingEval(self.sandboxes, SCORES)
        with mock.patch.object(previous, 'snapshot', side_effect=previous.SnapshotError('git archive 炸了')):
            rec, report = self.load(self.run_compare(fake))
        self.assertEqual([Path(c['cmd'][3]).name for c in fake.calls], ['none', 'current'])
        self.assertTrue(rec['previous_arm']['degraded'])
        self.assertEqual(rec['previous_arm']['reason_kind'], 'snapshot-failed')
        self.assertIsNone(rec['arms']['previous'])
        self.assertIn('git archive 炸了', report.split('> 状态')[0])

    def test_cross_rename_lists_incomparable_cases(self):
        self.git('mv', 'plugins/demo-plugin', 'plugins/devkit-demo')
        newdir = self.repo / 'plugins' / 'devkit-demo'
        manifest(newdir, 'devkit-demo', '2.0.0')
        make_cases(newdir, skill_ref='devkit-demo:audit')
        self.commit('改名 2.0.0')
        registry.register(self.data, 'devkit-demo', self.repo)
        fake = InspectingEval(self.sandboxes, SCORES)
        rec, report = self.load(self.run_compare(fake, name='devkit-demo'))
        self.assertEqual(fake.seen['previous']['name'], 'demo-plugin')     # 快照原样，不改 name
        self.assertTrue(rec['arms']['previous']['cross_rename'])
        self.assertEqual(rec['previous_arm']['incomparable_cases'], {'case-b': ['devkit-demo:audit']})
        self.assertEqual(rec['delta_vs_previous']['excluded_from_overall'], ['case-b'])
        head = report.split('> 状态')[0]
        self.assertIn('跨改名', head)
        self.assertIn('case-b', head)

    def test_not_git_degrades_to_two_arms(self):
        plain = self.tmp / 'plain'
        shutil.copytree(self.plugin, plain / 'plugins' / 'demo-plugin')
        registry.register(self.data, 'demo-plugin', plain)
        fake = InspectingEval(self.sandboxes, SCORES)
        with mock.patch.object(armplan, 'GIT_CEILING', self.tmp):
            rec, report = self.load(self.run_compare(fake))
        self.assertEqual([Path(c['cmd'][3]).name for c in fake.calls], ['none', 'current'])
        self.assertEqual(rec['previous_arm']['reason_kind'], 'not-git')
        self.assertTrue(rec['complete'])
        first = report.split('> 状态')[0]
        self.assertIn('上一版臂已退化', first)
        self.assertIn('不在 git 仓', first)

    def test_env_plugin_arm(self):
        env_src = self.tmp / 'envsrc' / 'env-a'
        manifest(env_src, 'env-a', '0.9.0')
        write(env_src / '.in_use' / '1', '')
        registry.register(self.data, 'demo-plugin', self.repo)
        fake = InspectingEval(self.sandboxes, SCORES)
        rec, report = self.load(self.run_compare(fake, env_plugins=[str(env_src)]))
        self.assertEqual([Path(c['cmd'][3]).name for c in fake.calls], ['none', 'previous', 'current', 'current_with_env'])
        seen = fake.seen['current_with_env']
        self.assertEqual(seen['env'], ['env-a'])
        self.assertIn('plugins: ["../..", "../../%s/env-a"]' % envplugins.ENV_DIR, seen['prompt'])
        self.assertNotIn('plugins:', fake.seen['current']['prompt'])
        envrec = rec['arms']['current_with_env']
        self.assertEqual(envrec['env_plugins'][0]['name'], 'env-a')
        self.assertEqual(envrec['env_plugins'][0]['source'], 'path')
        self.assertEqual(envrec['env_plugins'][0]['version'], '0.9.0')
        self.assertEqual(envrec['head_sha'], self.c3)
        self.assertEqual(rec['env_plugins'][0]['name'], 'env-a')
        self.assertEqual(rec['delta_env_vs_current']['overall'], 0)
        self.assertIn('## 环境插件臂', report)
        self.assertIn(env_src.resolve(), [Path(p) for p in self.validated])

    def test_env_plugin_same_name_as_tested_rejected(self):
        registry.register(self.data, 'demo-plugin', self.repo)
        with self.assertRaises(armplan.ArmSourceError):
            self.run_compare(InspectingEval(self.sandboxes, SCORES), env_plugins=[str(self.plugin)])


class CliSummaryTest(unittest.TestCase):
    def test_prints_previous_and_env_lines(self):
        import io
        from contextlib import redirect_stdout
        from plugin_eval_lib import cli
        fmt = lambda x: '—' if x is None else '%.2f' % x
        rec = {'previous_arm': {'degraded': False, 'version': '4.0.0', 'commit': 'abcdef1234567890', 'cross_rename': True},
               'arms': {'previous': {'score': 0.5}, 'current_with_env': {'score': 1.0, 'env_plugins': [{'name': 'env-a'}]}},
               'delta_vs_previous': {'overall': 0.25}}
        out = io.StringIO()
        with redirect_stdout(out):
            cli._print_extra_arms(rec, fmt)
        self.assertIn('上一版 4.0.0（abcdef123456）0.50 / 差（当前版 − 上一版）+0.25；跨改名', out.getvalue())
        self.assertIn('当前版+环境插件（env-a）1.00', out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            cli._print_extra_arms({'previous_arm': {'degraded': True, 'reason': '不在 git 仓'}, 'arms': {}}, fmt)
        self.assertIn('上一版臂已退化：不在 git 仓', out.getvalue())


class CrashOn(InspectingEval):
    """跑到 crash_on 臂时抛异常（模拟进程中途退出），之后照常。"""

    def __init__(self, *a, crash_on=None, **kw):
        super().__init__(*a, **kw)
        self.crash_on = crash_on

    def __call__(self, cmd, cwd, env, log_dir):
        if Path(cmd[3]).name == self.crash_on:
            self.crash_on = None
            raise RuntimeError('模拟中途退出')
        return super().__call__(cmd, cwd, env, log_dir)


@unittest.skipUnless(GIT, 'git 不可用')
class MultiArmResumeTest(unittest.TestCase):
    """续跑按首跑记下的来源重建上一版臂与环境插件臂（票 05 × 票 07）。搭建沿用 MultiArmTest，不继承它的用例。"""
    setUp, git, commit, preflight, run_compare = (MultiArmTest.setUp, MultiArmTest.git, MultiArmTest.commit,
                                                  MultiArmTest.preflight, MultiArmTest.run_compare)

    def _crash_then_paths(self, env_src):
        registry.register(self.data, 'demo-plugin', self.repo)
        fake = CrashOn(self.sandboxes, SCORES, crash_on='current')
        with self.assertRaises(RuntimeError):
            self.run_compare(fake, env_plugins=[str(env_src)])
        run_dir = next((self.repo / 'plugin-evals' / 'demo-plugin' / 'runs').iterdir())
        return fake, run_dir

    def _env(self):
        env_src = self.tmp / 'envsrc' / 'env-a'
        manifest(env_src, 'env-a', '0.9.0')
        return env_src

    def resume(self, fake, run_dir):
        return resume.resume_run(self.data, run_dir, runner=fake, claude='/fake/claude', env={'PATH': '/usr/bin'},
                                 tmp_parent=self.assembly_parent, sandbox_roots=[self.sandboxes],
                                 log=lambda *a: None, preflight_check=self.preflight)

    def test_checkpoint_keeps_arm_sources_and_resume_rebuilds_all_arms(self):
        env_src = self._env()
        fake, run_dir = self._crash_then_paths(env_src)
        cp = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertFalse(cp['complete'])
        self.assertEqual(cp['previous_arm']['commit'], self.c1)
        self.assertTrue(cp['previous_arm']['ran'])
        self.assertEqual(cp['env_plugins'][0]['version'], '0.9.0')
        self.assertTrue(cp['env_plugins'][0]['fingerprint'].startswith('sha256:'))
        self.assertIsNotNone(cp['preflight'])
        self.assertEqual(list(self.assembly_parent.iterdir()), [])     # 快照目录随中途退出一并清掉

        n_pre = len(self.preflight_kw)
        res = self.resume(fake, run_dir)
        self.assertEqual(len(self.preflight_kw), n_pre + 1)           # 续跑重跑前置检查
        self.assertEqual([lab for lab, _ in self.preflight_kw[-1]['others']][0][:6], '上一版快照 ')
        arms_run = [Path(c['cmd'][3]).name for c in fake.calls]
        self.assertEqual(arms_run, ['none', 'previous', 'current', 'current_with_env'])
        self.assertEqual(fake.seen['current_with_env']['env'], ['env-a'])
        rec = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertTrue(rec['complete'], rec['incomplete_reasons'])
        self.assertEqual(rec['arms']['previous']['commit'], self.c1)
        self.assertIsNone(rec['arms']['previous']['head_sha'])
        self.assertEqual(rec['delta_vs_previous']['overall'], 1)
        self.assertEqual(rec['delta_env_vs_current']['overall'], 0)
        self.assertEqual(set(rec['injection_check']['arms']), {'none', 'previous', 'current', 'current_with_env'})
        self.assertEqual(list(self.assembly_parent.iterdir()), [])

    def test_resume_refused_when_env_plugin_changed(self):
        env_src = self._env()
        fake, run_dir = self._crash_then_paths(env_src)
        write(env_src / 'hooks' / 'x.js', 'changed\n')
        with self.assertRaises(resume.ResumeError) as cm:
            self.resume(fake, run_dir)
        self.assertIn('环境插件', str(cm.exception))
        manifest(env_src, 'env-a', '0.9.1')
        with self.assertRaises(resume.ResumeError) as cm:
            self.resume(fake, run_dir)
        self.assertIn('0.9.0', str(cm.exception))
        self.assertEqual(list(self.assembly_parent.iterdir()), [])

    def test_resume_refused_when_previous_resolves_elsewhere(self):
        env_src = self._env()
        fake, run_dir = self._crash_then_paths(env_src)
        # 首跑后又发了一版、但被测插件内容不变是不可能的；这里直接改首跑记下的提交，模拟认定漂移
        rec = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
        rec['previous_arm']['commit'] = self.c2
        (run_dir / 'run.json').write_text(json.dumps(rec), encoding='utf-8')
        with self.assertRaises(resume.ResumeError) as cm:
            self.resume(fake, run_dir)
        self.assertIn('上一版认定与首跑不同', str(cm.exception))


if __name__ == '__main__':
    unittest.main()
