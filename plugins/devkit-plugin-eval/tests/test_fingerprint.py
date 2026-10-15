"""接缝：插件内容指纹（整个插件目录、排除 evals/）。"""
import shutil
import unittest
from pathlib import Path

import _support
from _support import tmpdir, make_plugin, write
from plugin_eval_lib import fingerprint


class FingerprintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.p = make_plugin(self.tmp / 'p')

    def fp(self, path=None, **kw):
        return fingerprint.plugin_fingerprint(path or self.p, **kw)

    def test_format_and_stability(self):
        a = self.fp()
        self.assertTrue(a.startswith('sha256:'))
        self.assertEqual(a, self.fp())

    def test_exclude_constant_lists_evals(self):
        self.assertIn('evals', fingerprint.FINGERPRINT_EXCLUDE)

    def test_evals_change_does_not_change_fingerprint(self):
        a = self.fp()
        write(self.p / 'evals' / 'new-case' / 'prompt.md', 'x')
        self.assertEqual(a, self.fp())

    def test_content_change_changes_fingerprint(self):
        a = self.fp()
        write(self.p / 'hooks' / 'inject.js', 'console.log("changed")\n')
        self.assertNotEqual(a, self.fp())

    def test_rename_changes_fingerprint(self):
        a = self.fp()
        (self.p / 'hooks' / 'inject.js').rename(self.p / 'hooks' / 'inject2.js')
        self.assertNotEqual(a, self.fp())

    def test_crlf_normalized(self):
        a = self.fp()
        (self.p / 'hooks' / 'inject.js').write_bytes(b'console.log("hi")\r\n')
        self.assertEqual(a, self.fp())

    def test_noise_files_ignored(self):
        a = self.fp()
        write(self.p / 'scripts' / '__pycache__' / 'x.cpython-312.pyc', 'junk')
        write(self.p / '.DS_Store', 'junk')
        self.assertEqual(a, self.fp())

    def test_same_content_in_other_location_same_fingerprint(self):
        other = self.tmp / 'copy'
        shutil.copytree(self.p, other)
        self.assertEqual(self.fp(), self.fp(other))

    def test_extra_exclude(self):
        a = self.fp(extra_exclude=('plugin-evals',))
        write(self.p / 'plugin-evals' / 'x' / 'run.json', '{}')
        self.assertEqual(a, self.fp(extra_exclude=('plugin-evals',)))
        self.assertNotEqual(a, self.fp())


if __name__ == '__main__':
    unittest.main()
