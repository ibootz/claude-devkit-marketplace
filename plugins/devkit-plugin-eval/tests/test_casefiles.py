"""票 11：用例文件（eval 原生格式）的生成、检查与 tags 改写。"""
import unittest
from pathlib import Path

import _support
from _support import tmpdir, write
from plugin_eval_lib import casefiles, clauses


def spec(**kw):
    s = {'slug': 'dispatch-sets-model', 'tags': ['discipline', 'C001'], 'prompt': '分别派两个子代理查两件事。',
         'max_turns': 8, 'timeout_seconds': 300, 'allowed_tools': ['Agent', 'Read'],
         'graders': [{'name': 'agent-has-model', 'type': 'tool_used', 'tool': 'Agent', 'input_match': '"model"\\s*:',
                      'min': 2}],
         'judge': [{'id': 'model-set', 'criterion': '每次派子代理都写明 model', 'rule': 'agent-has-model',
                    'clause': 'C001'}]}
    s.update(kw)
    return s


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)

    def test_written_case_loads_and_keeps_tags(self):
        d = casefiles.write_case(self.tmp / 'c', spec(scaffold_files=[{'path': 'a/b.txt', 'content': 'x\nPE_EOF_1\n'}]))
        self.assertEqual(casefiles.check_case_dir(d), [])
        self.assertEqual(clauses.case_tags(d), ['discipline', 'C001'])
        sh = (d / casefiles.SCAFFOLD_FILE).read_text(encoding='utf-8')
        self.assertIn("mkdir -p 'a'", sh)
        self.assertIn("<<'PE_EOF_1_X'", sh)          # 内容里撞上定界符时换一个
        self.assertIn('scaffold_script: scaffold.sh', (d / 'case.yaml').read_text(encoding='utf-8'))
        judge = (d / 'judge' / 'model-set.md').read_text(encoding='utf-8')
        self.assertIn('clause: C001', judge)
        self.assertIn('rule: agent-has-model', judge)
        g = (d / 'graders' / 'agent-has-model.md').read_text(encoding='utf-8')
        self.assertIn("input_match: '\"model\"\\s*:'", g)  # 正则单引号原样，不双写反斜杠

    def test_validate_catches_structural_problems(self):
        self.assertEqual(casefiles.validate_spec(spec()), [])
        probs = casefiles.validate_spec(spec(slug='Bad Slug', allowed_tools=['Bash'], graders=[
            {'name': 'skill', 'type': 'tool_used', 'tool': 'Skill'}], judge=[{'id': 'j', 'criterion': 'x', 'rule': 'nope'}]))
        text = '\n'.join(probs)
        self.assertIn('slug', text)
        self.assertIn('Bash', text)
        self.assertIn('没有计分的规则 grader', text)     # tool_used Skill 不写 arm 不计分
        self.assertIn("rule 'nope'", text)
        both = spec(graders=[{'name': 'skill', 'type': 'tool_used', 'tool': 'Skill', 'arm': 'both'}], judge=[])
        self.assertEqual(casefiles.validate_spec(both), [])

    def test_check_case_dir_reports_eval_load_failures(self):
        d = self.tmp / 'bad'
        write(d / 'prompt.md', '---\nname: bad\nexpected_output: x\n---\n做事\n')
        write(d / 'graders' / 'g.md', '---\npattern: x\n---\n')
        probs = '\n'.join(casefiles.check_case_dir(d))
        self.assertIn('expected_output', probs)
        self.assertIn('没有 type', probs)


class TagTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)

    def test_set_tags_in_prompt_frontmatter_block_list(self):
        d = self.tmp / 'c'
        write(d / 'prompt.md', '---\nname: c\ntags:\n  - discipline\n  - C002\nmax_turns: 3\n---\n正文\n')
        casefiles.set_tags(d, ['discipline', 'C003', 'C003'])
        text = (d / 'prompt.md').read_text(encoding='utf-8')
        self.assertIn('tags: ["discipline", "C003"]\nmax_turns: 3', text)
        self.assertTrue(text.endswith('正文\n'))
        self.assertEqual(clauses.case_tags(d), ['discipline', 'C003'])

    def test_set_tags_prefers_case_yaml_line_and_union_read(self):
        d = self.tmp / 'c'
        write(d / 'case.yaml', 'schema_version: "1.1"\nname: c\ntags: [a]\n')
        write(d / 'prompt.md', '---\nname: c\ntags: [b]\n---\n正文\n')
        self.assertEqual(clauses.case_tags(d), ['a', 'b'])      # 两处取并集
        casefiles.set_tags(d, ['a', 'C009'])
        self.assertIn('tags: ["a", "C009"]', (d / 'case.yaml').read_text(encoding='utf-8'))

    def test_retarget_judge_clause(self):
        d = self.tmp / 'c'
        write(d / 'judge' / 'j.md', '---\nrule: g\nclause: C002\n---\n标准\n')
        self.assertEqual(casefiles.retarget_judge_clause(d, 'C002', 'C005'), 1)
        self.assertEqual((d / 'judge' / 'j.md').read_text(encoding='utf-8'), '---\nrule: g\nclause: C005\n---\n标准\n')
        self.assertEqual(casefiles.retarget_judge_clause(d, 'C005', None), 1)
        self.assertEqual((d / 'judge' / 'j.md').read_text(encoding='utf-8'), '---\nrule: g\n---\n标准\n')


class RepoHistoryDraftsTest(unittest.TestCase):
    """仓内迁入的历史素材草稿（plugin-evals/devkit-discipline/drafts/）都能被 eval 加载。"""

    def test_history_drafts_load(self):
        root = Path(__file__).resolve().parents[3] / 'plugin-evals' / 'devkit-discipline' / 'drafts'
        if not root.is_dir():
            self.skipTest('仓内没有草稿区')
        from plugin_eval_lib import arms
        cases = arms.discover_cases(root)
        self.assertGreaterEqual(len(cases), 5)
        for c in cases:
            self.assertEqual(casefiles.check_case_dir(root / c), [], c)
            self.assertTrue((root / c / 'draft.json').is_file(), c)


if __name__ == '__main__':
    unittest.main()
