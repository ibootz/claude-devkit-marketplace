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
