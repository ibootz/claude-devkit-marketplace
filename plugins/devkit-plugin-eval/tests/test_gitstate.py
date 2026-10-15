"""dirty 口径（票 14 统一）：排除 evals/ 与 compare 自写的 .gitignore 行；取不到 git 状态为 None。用真 git 造临时仓。"""
import shutil
import subprocess
import unittest

from _support import make_plugin, tmpdir, write

from plugin_eval_lib import compare, gitstate

GIT = shutil.which('git')


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def commit_all(root, msg='c'):
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', msg)


@unittest.skipUnless(GIT, 'git 不可用')
class SubdirPluginTest(unittest.TestCase):
    def setUp(self):
        self.repo = tmpdir(self)
        git(self.repo, 'init', '-q')
        self.plugin = make_plugin(self.repo / 'plugins' / 'demo-plugin')
        write(self.repo / 'README.md', 'x\n')
        commit_all(self.repo)

    def state(self):
        return gitstate.git_state(self.repo, 'plugins/demo-plugin')

    def test_clean(self):
        head, dirty = self.state()
        self.assertEqual(len(head), 40)
        self.assertIs(dirty, False)

    def test_evals_changes_do_not_count(self):
        write(self.plugin / 'evals' / 'case-new' / 'prompt.md', 'new\n')
        write(self.plugin / 'evals' / 'case-a' / 'prompt.md', 'changed\n')
        self.assertIs(self.state()[1], False)

    def test_gitignore_line_written_by_compare_is_outside_scope(self):
        compare.ensure_gitignore(self.repo, 'plugins/demo-plugin')
        self.assertIs(self.state()[1], False)

    def test_other_change_counts(self):
        write(self.plugin / 'hooks' / 'inject.js', 'console.log("changed")\n')
        self.assertIs(self.state()[1], True)

    def test_untracked_file_counts(self):
        write(self.plugin / 'skills' / 'new' / 'SKILL.md', 'x\n')
        self.assertIs(self.state()[1], True)

    def test_change_outside_plugin_ignored(self):
        write(self.repo / 'README.md', 'y\n')
        self.assertIs(self.state()[1], False)

    def test_compare_git_state_delegates(self):
        write(self.plugin / 'evals' / 'case-a' / 'prompt.md', 'changed\n')
        self.assertEqual(compare.git_state(self.repo, 'plugins/demo-plugin'), self.state())


@unittest.skipUnless(GIT, 'git 不可用')
class RootPluginTest(unittest.TestCase):
    """插件就是仓根：.gitignore 在插件目录里，compare 首次对照会往里写一行。"""

    def setUp(self):
        self.repo = make_plugin(tmpdir(self) / 'repo')
        git(self.repo, 'init', '-q')
        write(self.repo / '.gitignore', 'node_modules/\n')
        commit_all(self.repo)

    def state(self):
        return gitstate.git_state(self.repo, '.')[1]

    def test_self_written_gitignore_line_not_dirty(self):
        self.assertTrue(compare.ensure_gitignore(self.repo, '.'))
        self.assertIs(self.state(), False)

    def test_untracked_gitignore_with_only_self_line_not_dirty(self):
        (self.repo / '.gitignore').unlink()
        commit_all(self.repo, 'rm gitignore')
        compare.ensure_gitignore(self.repo, '.')
        self.assertIs(self.state(), False)

    def test_other_gitignore_change_dirty(self):
        compare.ensure_gitignore(self.repo, '.')
        with open(self.repo / '.gitignore', 'a', encoding='utf-8') as f:
            f.write('dist/\n')
        self.assertIs(self.state(), True)

    def test_evals_and_results_dir_not_dirty(self):
        write(self.repo / 'evals' / 'case-a' / 'prompt.md', 'changed\n')
        write(self.repo / 'plugin-evals' / 'demo-plugin' / 'runs' / 'r' / 'run.json', '{}\n')
        self.assertIs(self.state(), False)

    def test_content_change_dirty(self):
        write(self.repo / 'hooks' / 'inject.js', 'console.log("changed")\n')
        self.assertIs(self.state(), True)


class NoGitTest(unittest.TestCase):
    def test_not_in_repo_or_no_git_is_none(self):
        d = tmpdir(self)
        self.assertEqual(gitstate.git_state(d, '.', git=''), (None, None))
        if GIT:
            # 临时目录可能落在某个仓里（极少见）；用 GIT_CEILING 不便，这里只断言无提交仓也是 None
            git(d, 'init', '-q')
            self.assertEqual(gitstate.git_state(d, '.'), (None, None))


if __name__ == '__main__':
    unittest.main()
