"""上一版臂：沿 HEAD 按改名追踪 plugin.json 找引入提交、--base 覆盖、退化、git archive 快照、跨改名不可比用例。

用真 git 在临时目录造仓（不联网、结果确定）。
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

import _support
from _support import tmpdir, write
from plugin_eval_lib import previous

GIT = shutil.which('git')


class GitRepo:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.git('init', '-q')

    def git(self, *args):
        return subprocess.run(
            ['git', '-C', str(self.root), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid',
             '-c', 'commit.gpgsign=false', *args],
            check=True, capture_output=True, text=True).stdout.strip()

    def manifest(self, rel, name, version, extra=''):
        # 多行缩进、带几个不变字段，接近真实 plugin.json：git 改名检测按行算相似度，单行 JSON 一改就认不出改名
        write(self.root / rel / '.claude-plugin' / 'plugin.json', json.dumps({
            'name': name, 'version': version, 'description': '示例插件，用于上一版臂单测' + extra,
            'author': {'name': 'tester'}, 'license': 'MIT', 'keywords': ['eval', 'demo', 'previous'],
        }, ensure_ascii=False, indent=2) + '\n')

    def commit(self, msg):
        self.git('add', '-A')
        self.git('commit', '-q', '-m', msg)
        return self.git('rev-parse', 'HEAD')


@unittest.skipUnless(GIT, 'git 不可用')
class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.repo = GitRepo(self.tmp / 'repo')
        r = self.repo
        r.manifest('plugins/p', 'p', '1.0.0')
        write(r.root / 'plugins/p/hooks/a.js', 'v1\n')
        self.c1 = r.commit('1.0.0 引入')
        write(r.root / 'plugins/p/hooks/a.js', 'v1 fix\n')
        r.manifest('plugins/p', 'p', '1.0.0', extra='同号中途修复')
        self.c2 = r.commit('1.0.0 中途修复')
        r.manifest('plugins/p', 'p', '1.1.0')
        write(r.root / 'plugins/p/hooks/a.js', 'v2\n')
        self.c3 = r.commit('1.1.0')
        self.plugin = r.root / 'plugins' / 'p'

    def test_auto_picks_introducing_commit_of_nearest_different_version(self):
        res = previous.resolve(self.plugin, '1.1.0')
        self.assertFalse(res.degraded, res.reason)
        self.assertEqual(res.version, '1.0.0')
        self.assertEqual(res.commit, self.c1)          # 同号跨两个提交，取引入的那个
        self.assertEqual(res.obtained_by, 'auto')
        self.assertEqual(res.path_in_repo, 'plugins/p')
        self.assertEqual(res.name, 'p')
        self.assertFalse(res.cross_rename)

    def test_uncommitted_version_bump_compares_against_head_version(self):
        # 工作目录已升到 1.2.0 但没提交：上一版是 HEAD 的 1.1.0
        self.repo.manifest('plugins/p', 'p', '1.2.0')
        res = previous.resolve(self.plugin, '1.2.0')
        self.assertEqual((res.version, res.commit), ('1.1.0', self.c3))

    def test_base_version(self):
        res = previous.resolve(self.plugin, '1.1.0', base='1.0.0')
        self.assertEqual((res.version, res.commit, res.obtained_by, res.base), ('1.0.0', self.c1, '--base', '1.0.0'))

    def test_base_commit(self):
        res = previous.resolve(self.plugin, '1.1.0', base=self.c2[:10])
        self.assertEqual((res.version, res.commit, res.obtained_by), ('1.0.0', self.c2, '--base'))
        self.assertEqual(res.path_in_repo, 'plugins/p')

    def test_base_unknown_raises(self):
        with self.assertRaises(previous.BaseNotFound):
            previous.resolve(self.plugin, '1.1.0', base='9.9.9')

    def test_single_version_history_degrades(self):
        r = GitRepo(self.tmp / 'solo')
        r.manifest('plugins/q', 'q', '0.1.0')
        r.commit('init')
        r.manifest('plugins/q', 'q', '0.1.0', extra='改内容不升号')
        r.commit('same version')
        res = previous.resolve(r.root / 'plugins' / 'q', '0.1.0')
        self.assertTrue(res.degraded)
        self.assertEqual(res.reason_kind, 'no-different-version')
        self.assertIn('0.1.0', res.reason)

    def test_not_in_git_repo_degrades(self):
        d = self.tmp / 'plain' / 'p'
        write(d / '.claude-plugin' / 'plugin.json', json.dumps({'name': 'p', 'version': '1.0.0'}))
        res = previous.resolve(d, '1.0.0', git=GIT, ceiling=self.tmp)
        self.assertTrue(res.degraded)
        self.assertEqual(res.reason_kind, 'not-git')

    def test_no_git_executable_degrades(self):
        res = previous.resolve(self.plugin, '1.1.0', git='')
        self.assertTrue(res.degraded)
        self.assertEqual(res.reason_kind, 'not-git')

    def test_follows_rename_and_flags_cross_rename(self):
        r = self.repo
        r.git('mv', 'plugins/p', 'plugins/devkit-p')
        r.manifest('plugins/devkit-p', 'devkit-p', '2.0.0')
        c4 = r.commit('改名 2.0.0')
        res = previous.resolve(r.root / 'plugins' / 'devkit-p', '2.0.0')
        self.assertEqual((res.version, res.commit, res.path_in_repo, res.name), ('1.1.0', self.c3, 'plugins/p', 'p'))
        self.assertTrue(res.cross_rename)
        # --base 指向改名前的提交：路径取当时的旧路径
        res2 = previous.resolve(r.root / 'plugins' / 'devkit-p', '2.0.0', base=self.c2)
        self.assertEqual(res2.path_in_repo, 'plugins/p')
        # 改名提交自身版本号 2.0.0 = 工作目录：不当上一版
        self.assertNotEqual(res.commit, c4)

    def test_snapshot_extracts_plugin_at_commit(self):
        res = previous.resolve(self.plugin, '1.1.0')
        dest = self.tmp / 'snap'
        plugin_dir = previous.snapshot(res, dest)
        self.assertEqual((plugin_dir / 'hooks' / 'a.js').read_text(encoding='utf-8'), 'v1\n')
        self.assertEqual(json.loads((plugin_dir / '.claude-plugin' / 'plugin.json').read_text())['version'], '1.0.0')

    def test_snapshot_failure_raises(self):
        res = previous.resolve(self.plugin, '1.1.0')
        res.commit = '0' * 40
        with self.assertRaises(previous.SnapshotError):
            previous.snapshot(res, self.tmp / 'snap2')

    def test_repo_root_plugin(self):
        r = GitRepo(self.tmp / 'rootplug')
        r.manifest('.', 'rp', '1.0.0')
        c1 = r.commit('1.0.0')
        r.manifest('.', 'rp', '1.1.0')
        r.commit('1.1.0')
        res = previous.resolve(r.root, '1.1.0')
        self.assertEqual((res.version, res.commit, res.path_in_repo), ('1.0.0', c1, '.'))
        plugin_dir = previous.snapshot(res, self.tmp / 'snap3')
        self.assertTrue((plugin_dir / '.claude-plugin' / 'plugin.json').is_file())


class SkillRefTest(unittest.TestCase):
    def test_lists_cases_whose_graders_name_plugin_skills(self):
        tmp = tmpdir(self)
        ev = tmp / 'evals'
        write(ev / 'uses-skill' / 'prompt.md', '---\nname: x\n---\n用 devkit-p:audit 检查\n')
        write(ev / 'uses-skill' / 'graders' / 'g.md',
              '---\ntype: regex\ntarget: trace\npattern: "devkit-p:audit"\n---\n')
        write(ev / 'old-name' / 'case.yaml',
              'schema_version: "1.1"\nname: o\nexecution:\n  prompt: "提到 p:audit 不算"\n'
              'graders:\n  - type: tool_used\n    name: g\n    tool: Skill\n    input_match: "p:audit"\n')
        write(ev / 'prompt-only' / 'prompt.md', '---\nname: y\n---\n请调 devkit-p:audit\n')
        write(ev / 'prompt-only' / 'graders' / 'g.md', '---\ntype: regex\ntarget: last_message\npattern: ok\n---\n')
        write(ev / 'other-plugin' / 'graders' / 'g.md', '---\ntype: regex\ntarget: trace\npattern: "devkit-pp:audit"\n---\n')
        write(ev / 'other-plugin' / 'prompt.md', 'x\n')
        cases = ['old-name', 'other-plugin', 'prompt-only', 'uses-skill']
        got = previous.cases_naming_skills(ev, cases, {'devkit-p', 'p'})
        self.assertEqual(got, {'old-name': ['p:audit'], 'uses-skill': ['devkit-p:audit']})


if __name__ == '__main__':
    unittest.main()
