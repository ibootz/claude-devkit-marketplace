"""接缝：用例发现与臂组装。"""
import json
import unittest
from pathlib import Path

import _support
from _support import tmpdir, make_plugin, write
from plugin_eval_lib import arms


class DiscoverCasesTest(unittest.TestCase):
    def test_prompt_md_or_case_yaml_dirs_count_once(self):
        tmp = tmpdir(self)
        ev = tmp / 'evals'
        write(ev / 'a' / 'prompt.md', 'x')
        write(ev / 'b' / 'case.yaml', 'name: b')
        write(ev / 'b' / 'prompt.md', 'x')
        write(ev / 'group' / 'c' / 'prompt.md', 'x')
        write(ev / 'a' / 'sub' / 'README.md', 'ignored')
        write(ev / 'README.md', 'ignored')
        write(ev / 'results' / 'old' / 'prompt.md', 'stale result copy')
        self.assertEqual(arms.discover_cases(ev), ['a', 'b', 'group/c'])

    def test_missing_dir_returns_empty(self):
        self.assertEqual(arms.discover_cases(tmpdir(self) / 'none'), [])


class AssembleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.plugin = make_plugin(self.tmp / 'repo' / 'plugins' / 'demo', name='demo', cases=('own-case',))
        write(self.plugin / 'evals' / 'results' / '2026' / 'aggregate-result.json', '{}')
        self.evals = self.plugin / 'evals'
        self.root = self.tmp / 'assembly'

    def test_current_arm_has_plugin_and_current_evals(self):
        d = arms.assemble_arm(self.root, arms.ArmSpec('current', '当前版', self.plugin), self.evals)
        self.assertEqual(d, self.root / 'current')
        self.assertEqual(json.loads((d / '.claude-plugin' / 'plugin.json').read_text())['name'], 'demo')
        self.assertTrue((d / 'hooks' / 'inject.js').exists())
        self.assertTrue((d / 'evals' / 'own-case' / 'prompt.md').exists())
        self.assertFalse((d / 'evals' / 'results').exists())

    def test_evals_always_from_given_source_not_from_plugin_copy(self):
        snapshot = make_plugin(self.tmp / 'snapshot', name='demo', cases=('stale-case',))
        d = arms.assemble_arm(self.root, arms.ArmSpec('previous', '上一版', snapshot), self.evals)
        self.assertFalse((d / 'evals' / 'stale-case').exists())
        self.assertTrue((d / 'evals' / 'own-case').exists())

    def test_none_arm_is_stub_plus_evals(self):
        d = arms.assemble_arm(self.root, arms.ArmSpec('none', '不装', None), self.evals)
        manifest = json.loads((d / '.claude-plugin' / 'plugin.json').read_text())
        self.assertEqual(manifest['name'], arms.STUB_NAME)
        self.assertEqual(sorted(p.name for p in d.iterdir()), ['.claude-plugin', 'evals'])
        self.assertEqual(sorted(p.name for p in (d / '.claude-plugin').iterdir()), ['plugin.json'])

    def test_repo_root_plugin_excludes_git_and_plugin_evals(self):
        solo = make_plugin(self.tmp / 'solo', name='solo')
        write(solo / '.git' / 'HEAD', 'ref')
        write(solo / 'plugin-evals' / 'solo' / 'runs' / 'x' / 'run.json', '{}')
        d = arms.assemble_arm(self.root, arms.ArmSpec('current', '当前版', solo),
                              solo / 'evals', extra_exclude=('.git', 'plugin-evals'))
        self.assertFalse((d / '.git').exists())
        self.assertFalse((d / 'plugin-evals').exists())


if __name__ == '__main__':
    unittest.main()
