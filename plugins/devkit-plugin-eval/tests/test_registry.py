"""接缝：用户级数据目录推导 + 登记清单。"""
import json
import unittest
from pathlib import Path

import _support
from _support import tmpdir, make_plugin
from plugin_eval_lib import datadir, registry


class DataDirTest(unittest.TestCase):
    def test_cli_value_wins_over_env(self):
        got = datadir.resolve_data_dir('/a/b', env={'CLAUDE_PLUGIN_DATA': '/c/d'}, script_path='/x/y.py')
        self.assertEqual(got, Path('/a/b').resolve())

    def test_env_used_when_no_cli_value(self):
        got = datadir.resolve_data_dir(None, env={'CLAUDE_PLUGIN_DATA': '/c/d'}, script_path='/x/y.py')
        self.assertEqual(got, Path('/c/d'))

    def test_derived_from_marketplace_cache_path(self):
        script = '/home/u/.claude/plugins/cache/claude-devkit-marketplace/devkit-plugin-eval/0.1.0/scripts/plugin_eval.py'
        got = datadir.resolve_data_dir(None, env={}, script_path=script)
        self.assertEqual(got, Path('/home/u/.claude/plugins/data/devkit-plugin-eval-claude-devkit-marketplace'))

    def test_derived_id_replaces_special_chars(self):
        script = '/h/.claude/plugins/cache/my.mkt@x/devkit-plugin-eval/0.1.0/scripts/plugin_eval.py'
        got = datadir.resolve_data_dir(None, env={}, script_path=script)
        self.assertEqual(got.name, 'devkit-plugin-eval-my-mkt-x')

    def test_not_under_cache_requires_explicit_arg(self):
        with self.assertRaises(datadir.DataDirError) as ctx:
            datadir.resolve_data_dir(None, env={}, script_path='/repo/plugins/devkit-plugin-eval/scripts/plugin_eval.py')
        self.assertIn('--data-dir', str(ctx.exception))


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.data = self.tmp / 'data'
        self.repo = self.tmp / 'repo'
        make_plugin(self.repo / 'plugins' / 'demo-plugin')

    def test_register_writes_registry_with_relative_plugin_path(self):
        entry = registry.register(self.data, 'demo-plugin', self.repo)
        self.assertEqual(entry['plugin_path'], 'plugins/demo-plugin')
        saved = json.loads((self.data / 'registry.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['plugins']['demo-plugin']['repo'], str(self.repo.resolve()))
        self.assertIn('registered_at', saved['plugins']['demo-plugin'])

    def test_register_plugin_at_repo_root(self):
        root_repo = self.tmp / 'root-repo'
        make_plugin(root_repo, name='solo')
        entry = registry.register(self.data, 'solo', root_repo)
        self.assertEqual(entry['plugin_path'], '.')

    def test_register_rejects_missing_plugin(self):
        with self.assertRaises(registry.RegistryError):
            registry.register(self.data, 'nope', self.repo)

    def test_register_rejects_name_mismatch(self):
        make_plugin(self.repo / 'plugins' / 'other', name='not-other')
        with self.assertRaises(registry.RegistryError):
            registry.register(self.data, 'other', self.repo)

    def test_reregister_overwrites_repo(self):
        registry.register(self.data, 'demo-plugin', self.repo)
        repo2 = self.tmp / 'repo2'
        make_plugin(repo2 / 'plugins' / 'demo-plugin')
        registry.register(self.data, 'demo-plugin', repo2)
        self.assertEqual(registry.lookup(self.data, 'demo-plugin')['repo'], str(repo2.resolve()))

    def test_lookup_unregistered_raises_with_register_hint(self):
        with self.assertRaises(registry.NotRegistered) as ctx:
            registry.lookup(self.data, 'demo-plugin')
        msg = str(ctx.exception)
        self.assertIn('register', msg)
        self.assertIn('demo-plugin', msg)
        # 从源码仓跑时推不出数据目录，提示里的登记命令要带 --data-dir（且就是这次用的那个）
        self.assertIn("--data-dir '%s'" % self.data, msg)
        # 写明信任范围：登记后会以用户身份跑用例的 scaffold_script
        self.assertIn('scaffold_script', msg)

    def test_plugin_dir_resolves(self):
        registry.register(self.data, 'demo-plugin', self.repo)
        entry = registry.lookup(self.data, 'demo-plugin')
        self.assertEqual(registry.plugin_dir(entry), (self.repo / 'plugins' / 'demo-plugin').resolve())


if __name__ == '__main__':
    unittest.main()
