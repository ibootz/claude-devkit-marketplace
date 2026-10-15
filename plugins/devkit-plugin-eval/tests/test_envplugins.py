"""环境插件：入参解析（插件名@市场 / 路径）、拷进臂组装目录、给用例写 plugins 字段。"""
import json
import os
import unittest
from pathlib import Path

import _support
from _support import tmpdir, write
from plugin_eval_lib import envplugins


def make_env_plugin(root, name='env-a', version='2.0.0'):
    root = Path(root)
    write(root / '.claude-plugin' / 'plugin.json', json.dumps({'name': name, 'version': version}))
    write(root / 'hooks' / 'hooks.json', '{}\n')
    write(root / '.in_use' / '12345', '')
    write(root / 'evals' / 'own' / 'prompt.md', 'x\n')
    return root


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.cfg = self.tmp / 'cfg'
        self.cache = make_env_plugin(self.cfg / 'plugins' / 'cache' / 'mkt' / 'env-a' / '2.0.0')
        entries = {
            'env-a@mkt': [
                {'scope': 'project', 'projectPath': '/x', 'installPath': str(self.tmp / 'stale'),
                 'version': '1.0.0', 'lastUpdated': '2026-10-14T00:00:00.000Z', 'gitCommitSha': 'aaa'},
                {'scope': 'user', 'installPath': str(self.cache), 'version': '2.0.0',
                 'lastUpdated': '2026-10-01T00:00:00.000Z', 'gitCommitSha': 'bbb'},
            ],
            'proj-only@mkt': [
                {'scope': 'project', 'installPath': str(self.cache), 'version': '2.0.0',
                 'lastUpdated': '2026-10-01T00:00:00.000Z', 'gitCommitSha': 'c1'},
                {'scope': 'local', 'installPath': str(self.cache), 'version': '2.0.0',
                 'lastUpdated': '2026-10-02T00:00:00.000Z', 'gitCommitSha': 'c2'},
            ],
        }
        write(self.cfg / 'plugins' / 'installed_plugins.json', json.dumps({'version': 2, 'plugins': entries}))
        self.env = {'CLAUDE_CONFIG_DIR': str(self.cfg)}

    def test_installed_id_prefers_user_scope(self):
        ep = envplugins.resolve('env-a@mkt', env=self.env)
        self.assertEqual(ep.source, 'installed')
        self.assertEqual(ep.dir, self.cache.resolve())
        self.assertEqual((ep.name, ep.version, ep.git_commit_sha, ep.scope), ('env-a', '2.0.0', 'bbb', 'user'))
        self.assertEqual(ep.record()['spec'], 'env-a@mkt')

    def test_installed_id_without_user_scope_takes_latest(self):
        ep = envplugins.resolve('proj-only@mkt', env=self.env)
        self.assertEqual((ep.scope, ep.git_commit_sha), ('local', 'c2'))

    def test_unknown_id_raises(self):
        with self.assertRaises(envplugins.EnvPluginError):
            envplugins.resolve('ghost@mkt', env=self.env)

    def test_path(self):
        d = make_env_plugin(self.tmp / 'src' / 'env-b', name='env-b', version='0.3.0')
        ep = envplugins.resolve(str(d), env=self.env)
        self.assertEqual((ep.source, ep.name, ep.version), ('path', 'env-b', '0.3.0'))

    def test_path_without_manifest_raises(self):
        (self.tmp / 'empty').mkdir()
        with self.assertRaises(envplugins.EnvPluginError):
            envplugins.resolve(str(self.tmp / 'empty'), env=self.env)

    def test_default_config_dir_is_home_dot_claude(self):
        self.assertEqual(envplugins.config_dir({}), Path.home() / '.claude')


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.arm = self.tmp / 'arm'
        write(self.arm / '.claude-plugin' / 'plugin.json', '{"name": "demo", "version": "1.0.0"}')
        self.ep = envplugins.EnvPlugin(spec='x', source='path', dir=make_env_plugin(self.tmp / 'e'),
                                       name='env-a', version='2.0.0')

    def plugins_field(self, text):
        for line in text.splitlines():
            if line.startswith('plugins:'):
                return json.loads(line[len('plugins:'):])
        return None

    def test_copies_without_runtime_files_and_writes_plugins_field(self):
        write(self.arm / 'evals' / 'with-fm' / 'prompt.md', '---\nname: a\ntags: [x]\n---\n做事\n')
        write(self.arm / 'evals' / 'no-fm' / 'prompt.md', '只有正文\n')
        write(self.arm / 'evals' / 'group' / 'deep' / 'case.yaml', 'schema_version: "1.1"\nname: d\n')
        conflicts = envplugins.install(self.arm, [self.ep])
        self.assertEqual(conflicts, [])
        env_dir = self.arm / envplugins.ENV_DIR / 'env-a'
        self.assertTrue((env_dir / 'hooks' / 'hooks.json').is_file())
        self.assertFalse((env_dir / '.in_use').exists())
        self.assertFalse((env_dir / 'evals').exists())

        for case, fname in (('with-fm', 'prompt.md'), ('no-fm', 'prompt.md'), ('group/deep', 'case.yaml')):
            case_dir = self.arm / 'evals' / case
            text = (case_dir / fname).read_text(encoding='utf-8')
            entries = self.plugins_field(text)
            self.assertIsNotNone(entries, case)
            resolved = [os.path.normpath(case_dir / e) for e in entries]
            self.assertEqual(resolved, [os.path.normpath(self.arm), os.path.normpath(env_dir)], case)
        self.assertTrue((self.arm / 'evals' / 'with-fm' / 'prompt.md').read_text(encoding='utf-8').endswith('---\n做事\n'))
        no_fm = (self.arm / 'evals' / 'no-fm' / 'prompt.md').read_text(encoding='utf-8')
        self.assertTrue(no_fm.startswith('---\nplugins: '))
        self.assertTrue(no_fm.endswith('---\n只有正文\n'))

    def test_case_declaring_plugins_left_alone_and_reported(self):
        write(self.arm / 'evals' / 'own' / 'prompt.md', '---\nplugins: ["../.."]\n---\nx\n')
        write(self.arm / 'evals' / 'yaml-own' / 'case.yaml', 'schema_version: "1.1"\nplugins:\n  - ../..\n')
        write(self.arm / 'evals' / 'yaml-own' / 'prompt.md', '正文\n')
        conflicts = envplugins.install(self.arm, [self.ep])
        self.assertEqual(conflicts, ['own', 'yaml-own'])
        self.assertEqual((self.arm / 'evals' / 'yaml-own' / 'prompt.md').read_text(encoding='utf-8'), '正文\n')

    def test_name_clash_with_top_level_dir_raises(self):
        (self.arm / envplugins.ENV_DIR).mkdir()
        with self.assertRaises(envplugins.EnvPluginError):
            envplugins.install(self.arm, [self.ep])


class CheckSetTest(unittest.TestCase):
    def test_duplicate_or_self_name_rejected(self):
        a = envplugins.EnvPlugin(spec='a', source='path', dir=Path('/a'), name='x', version='1')
        b = envplugins.EnvPlugin(spec='b', source='path', dir=Path('/b'), name='x', version='2')
        with self.assertRaises(envplugins.EnvPluginError):
            envplugins.check_set([a, b], tested_name='demo')
        with self.assertRaises(envplugins.EnvPluginError):
            envplugins.check_set([a], tested_name='x')
        envplugins.check_set([a], tested_name='demo')


if __name__ == '__main__':
    unittest.main()
