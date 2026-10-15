"""接缝：规则判分（剔除 with-only 与付费 grader）、臂分数、臂间差、加载失败核对。"""
import unittest

import _support
from _support import aggregate, grader, run_result
from plugin_eval_lib import scoring

STUB_GRADERS = [
    grader('agent-dispatched'), grader('agent-has-model'), grader('agent-missing-model-zero'),
    grader('marker-sessionstart', 'regex', arm='with-only'),
    grader('marker-userpromptsubmit', 'regex', arm='with-only'),
]
STUB_PASSES = {'agent-dispatched': True, 'agent-has-model': False, 'agent-missing-model-zero': False,
               'marker-sessionstart': False, 'marker-userpromptsubmit': False}


class ArmScoreTest(unittest.TestCase):
    def test_with_only_graders_excluded(self):
        # 票 01 实测：none 模式下 eval 给 0.2（5 个过 1 个），剔除 with-only 后应为 1/3
        agg = aggregate([('dispatch-model', STUB_GRADERS, [run_result(STUB_PASSES)] * 3)])
        arm = scoring.score_arm(agg)
        case = arm['cases']['dispatch-model']
        self.assertAlmostEqual(case['score'], 1 / 3)
        self.assertEqual(case['run_scores'], [1 / 3] * 3)
        self.assertEqual(case['excluded_graders'], {'marker-sessionstart': 'with-only', 'marker-userpromptsubmit': 'with-only'})
        self.assertAlmostEqual(arm['score'], 1 / 3)

    def test_paid_graders_excluded(self):
        gs = [grader('rule'), grader('judge', 'llm'), grader('base', 'baseline')]
        agg = aggregate([('c', gs, [run_result({'rule': True, 'judge': False, 'base': False})])])
        case = scoring.score_arm(agg)['cases']['c']
        self.assertEqual(case['score'], 1)
        self.assertEqual(case['excluded_graders'], {'judge': 'llm', 'base': 'baseline'})

    def test_weights_respected(self):
        gs = [grader('a', weight=3), grader('b', weight=1)]
        agg = aggregate([('c', gs, [run_result({'a': True, 'b': False})])])
        self.assertAlmostEqual(scoring.score_arm(agg)['cases']['c']['score'], 0.75)

    def test_errored_runs_invalid_and_not_scored(self):
        gs = [grader('a')]
        runs = [run_result({'a': True}), run_result({'a': False}, error='rate limited'), run_result({'a': True})]
        arm = scoring.score_arm(aggregate([('c', gs, runs)]))
        case = arm['cases']['c']
        self.assertEqual(case['score'], 1)
        self.assertEqual(case['valid_runs'], 2)
        self.assertEqual(case['invalid_runs'], [{'index': 1, 'error': 'rate limited'}])
        self.assertEqual(arm['invalid_run_count'], 1)

    def test_case_without_scored_graders_has_none_score(self):
        gs = [grader('m', 'regex', arm='with-only')]
        arm = scoring.score_arm(aggregate([('c', gs, [run_result({'m': True})])]))
        self.assertIsNone(arm['cases']['c']['score'])
        self.assertIsNone(arm['score'])

    def test_all_runs_invalid_gives_none(self):
        arm = scoring.score_arm(aggregate([('c', [grader('a')], [run_result({'a': True}, error='x')])]))
        self.assertIsNone(arm['cases']['c']['score'])

    def test_no_scored_graders_flagged(self):
        gs = [grader('m', 'regex', arm='with-only'), grader('j', 'llm')]
        case = scoring.score_arm(aggregate([('c', gs, [run_result({'m': True, 'j': True})])]))['cases']['c']
        self.assertTrue(case['no_scored_graders'])
        ok = scoring.score_arm(aggregate([('c', [grader('a')], [run_result({'a': True})])]))['cases']['c']
        self.assertFalse(ok['no_scored_graders'])

    def test_implicit_with_only_tool_used_skill(self):
        # 2.1.300 二进制：arm 未写、type=tool_used、tool=Skill 的 grader 视同 with-only（--help 也写 incl. `tool_used: Skill`）
        skill = {'name': 'skill-fired', 'type': 'tool_used', 'weight': 1, 'config': {'tool': 'Skill'}}
        both = {'name': 'skill-both', 'type': 'tool_used', 'weight': 1, 'config': {'tool': 'Skill', 'arm': 'both'}}
        gs = [grader('a'), skill, both]
        case = scoring.score_arm(aggregate([('c', gs, [run_result({'a': True, 'skill-fired': False,
                                                                    'skill-both': False})])]))['cases']['c']
        self.assertIn('skill-fired', case['excluded_graders'])
        self.assertTrue(case['excluded_graders']['skill-fired'].startswith('with-only'))
        self.assertNotIn('skill-both', case['excluded_graders'])
        self.assertEqual(case['score'], 0.5)


def mock_run(passes, kinds, withheld=()):
    r = run_result(passes)
    r['mocks'] = {'servers': [dict({'server': 's%d' % i, 'kind': k, 'tools': []},
                                   **({'withheld': True} if i in withheld else {}))
                              for i, k in enumerate(kinds)],
                  'warnings': [], 'calls': {'total': 1, 'errors': 0, 'unmocked': []}}
    return r


MOCK_GRADERS = [grader('a'), {'name': 'mock-hit', 'type': 'regex', 'weight': 1,
                              'config': {'target': 'mock_calls', 'pattern': 'x', 'flags': '', 'match': 'contains'}}]


class MockCallsWithOnlyTest(unittest.TestCase):
    """2.1.300 二进制：mock 全是替插件 server 顶班的 shadow（无 standalone、至少一个未 withheld）时，
    arm 未写的 regex target=mock_calls grader 视同 with-only。"""

    def test_cases_detected_from_current_arm_runs(self):
        agg = aggregate([('shadow', MOCK_GRADERS, [mock_run({'a': True}, ['shadow'])]),
                         ('mixed', MOCK_GRADERS, [mock_run({'a': True}, ['shadow', 'standalone'])]),
                         ('withheld', MOCK_GRADERS, [mock_run({'a': True}, ['shadow'], withheld=(0,))]),
                         ('nomock', MOCK_GRADERS, [run_result({'a': True})])])
        self.assertEqual(scoring.mock_with_only_cases(agg), {'shadow'})

    def test_excluded_only_for_given_cases(self):
        runs = [run_result({'a': True, 'mock-hit': False})]
        agg = aggregate([('x', MOCK_GRADERS, runs), ('y', MOCK_GRADERS, runs)])
        arm = scoring.score_arm(agg, mock_with_only_cases={'x'})
        self.assertIn('mock-hit', arm['cases']['x']['excluded_graders'])
        self.assertEqual(arm['cases']['x']['score'], 1)
        self.assertNotIn('mock-hit', arm['cases']['y']['excluded_graders'])
        self.assertEqual(arm['cases']['y']['score'], 0.5)

    def test_default_uses_arms_own_mocks(self):
        agg = aggregate([('x', MOCK_GRADERS, [mock_run({'a': True, 'mock-hit': False}, ['shadow'])])])
        self.assertEqual(scoring.score_arm(agg)['cases']['x']['score'], 1)


class CaseKeyTest(unittest.TestCase):
    def test_same_name_cases_keyed_by_dir(self):
        # frontmatter name 可以重名；按用例目录（去掉 evals/）建键，互不覆盖
        agg = aggregate([('dup', [grader('a')], [run_result({'a': True})]),
                         ('dup', [grader('a')], [run_result({'a': False})])])
        agg['cases'][0]['dir'] = 'evals/group-1/dup'
        agg['cases'][1]['dir'] = 'evals/group-2/dup'
        arm = scoring.score_arm(agg)
        self.assertEqual(set(arm['cases']), {'group-1/dup', 'group-2/dup'})
        self.assertEqual(arm['cases']['group-1/dup']['score'], 1)
        self.assertEqual(arm['cases']['group-2/dup']['score'], 0)
        d = scoring.delta(arm, arm)
        self.assertEqual(set(d['cases']), {'group-1/dup', 'group-2/dup'})


class DeltaTest(unittest.TestCase):
    def test_delta_per_case_and_overall(self):
        none = {'cases': {'a': {'score': 1 / 3}, 'b': {'score': 1.0}}, 'score': 2 / 3}
        cur = {'cases': {'a': {'score': 1.0}, 'b': {'score': 0.5}}, 'score': 0.75}
        d = scoring.delta(cur, none)
        self.assertAlmostEqual(d['cases']['a'], 2 / 3)
        self.assertAlmostEqual(d['cases']['b'], -0.5)
        self.assertAlmostEqual(d['overall'], (2 / 3 - 0.5) / 2)
        self.assertEqual(d['missing_cases'], [])

    def test_delta_skips_unscored_and_missing_cases(self):
        none = {'cases': {'a': {'score': 0.0}, 'b': {'score': None}}}
        cur = {'cases': {'a': {'score': 1.0}, 'b': {'score': 1.0}, 'c': {'score': 1.0}}}
        d = scoring.delta(cur, none)
        self.assertEqual(d['cases'], {'a': 1.0, 'b': None, 'c': None})
        self.assertEqual(d['overall'], 1.0)
        self.assertEqual(d['missing_cases'], ['c'])

    def test_delta_none_when_nothing_comparable(self):
        self.assertIsNone(scoring.delta({'cases': {}}, {'cases': {}})['overall'])


class LoadCheckTest(unittest.TestCase):
    def test_parse_load_failures_from_stderr(self):
        err = 'graders/x.md: frontmatter must include "type:"\n2 case file(s) failed to load\n'
        self.assertEqual(scoring.parse_load_failures(err), 2)
        self.assertEqual(scoring.parse_load_failures('all fine'), 0)

    def test_check_loaded_cases_flags_mismatch(self):
        agg = aggregate([('a', [grader('g')], [run_result({'g': True})])])
        issues = scoring.check_loaded_cases(agg, expected=['a', 'b'], stderr='1 case file(s) failed to load')
        self.assertTrue(any('1 个用例加载失败' in i for i in issues))
        self.assertTrue(any('b' in i for i in issues))

    def test_check_loaded_cases_ok(self):
        agg = aggregate([('a', [grader('g')], [run_result({'g': True})])])
        self.assertEqual(scoring.check_loaded_cases(agg, expected=['a'], stderr=''), [])

    def test_partial_flagged(self):
        agg = aggregate([('a', [grader('g')], [run_result({'g': True})])], partial=True)
        self.assertTrue(scoring.check_loaded_cases(agg, expected=['a'], stderr=''))


if __name__ == '__main__':
    unittest.main()
