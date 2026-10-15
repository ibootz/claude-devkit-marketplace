"""接缝：run.json 组装与 report.md 渲染。"""
import unittest

import _support
from plugin_eval_lib import record


def arm(label, score, cases, **kw):
    base = {
        'label': label, 'source': 'stub' if label == '不装' else 'working-tree', 'version': None,
        'score': score, 'cases': cases, 'invalid_run_count': 0, 'load_issues': [], 'eval_exit_code': 1,
        'aggregate_result': 'arms/x/aggregate-result.json', 'cost_usd': 0.4,
        'usage': {'input_tokens': 1, 'output_tokens': 2, 'cache_read_input_tokens': 3,
                  'cache_creation_input_tokens': 4, 'cost_usd': 0.4, 'by_model': {}},
        'main_model': 'claude-opus-5-5', 'claude_version': '2.1.300', 'trace_dir': 'traces/r/x',
        'cleanup_warnings': [],
    }
    base.update(kw)
    return base


def case(score, runs=(1, 1, 1), excluded=None):
    return {'score': score, 'run_scores': list(runs), 'valid_runs': len(runs), 'invalid_runs': [],
            'excluded_graders': excluded or {}}


def build(cur_scores=(1.0, 1.0), complete_reasons=()):
    none = arm('不装', 0.5, {'a': case(1 / 3, (1 / 3,) * 3, {'m': 'with-only'}), 'b': case(2 / 3)})
    cur = arm('当前版', sum(cur_scores) / 2, {'a': case(cur_scores[0]), 'b': case(cur_scores[1])},
              head_sha='abc123', dirty=False, version='1.2.3')
    delta = {'cases': {'a': cur_scores[0] - 1 / 3, 'b': cur_scores[1] - 2 / 3},
             'overall': (cur_scores[0] - 1 / 3 + cur_scores[1] - 2 / 3) / 2, 'missing_cases': []}
    return record.build_run_record(
        run_id='20261015T080000Z-1.2.3-compare',
        plugin={'name': 'demo', 'version': '1.2.3', 'fingerprint': 'sha256:ff', 'path_in_repo': 'plugins/demo'},
        arms={'none': none, 'current': cur}, delta=delta, cases=['a', 'b'],
        incomplete_reasons=list(complete_reasons), threshold=1.0,
        started_at='2026-10-15T08:00:00Z', finished_at='2026-10-15T08:05:00Z',
        environment={'claude_path': '/c', 'node_path': '/n', 'runs_per_case': 3})


class RunRecordTest(unittest.TestCase):
    def test_required_fields(self):
        r = build()
        self.assertEqual(r['kind'], 'compare')
        self.assertEqual(r['plugin']['name'], 'demo')
        self.assertEqual(r['plugin']['version'], '1.2.3')
        self.assertEqual(r['plugin']['fingerprint'], 'sha256:ff')
        self.assertEqual(r['claude_code_version'], '2.1.300')
        self.assertEqual(r['main_model'], 'claude-opus-5-5')
        self.assertEqual(r['review'], {'status': '待审', 'reviewed_at': None})
        self.assertTrue(r['complete'])
        self.assertEqual(r['usage']['input_tokens'], 2)
        self.assertAlmostEqual(r['usage']['cost_usd'], 0.8)
        self.assertEqual(r['arms']['current']['head_sha'], 'abc123')
        self.assertIn('none', r['arms'])

    def test_reserved_keys_present_as_null(self):
        r = build()
        for k in ('clause_list_fingerprint', 'judge_model', 'injection_check', 'judge', 'resident_tokens', 'preflight'):
            self.assertIn(k, r)
            self.assertIsNone(r[k])
        self.assertIsNone(r['arms']['previous'])
        self.assertIsNone(r['arms']['current_with_env'])

    def test_passed_requires_complete_and_current_cases_at_threshold(self):
        self.assertTrue(build()['passed'])
        self.assertFalse(build(cur_scores=(1.0, 0.5))['passed'])
        self.assertFalse(build(complete_reasons=['当前版臂：1 个用例加载失败'])['passed'])
        self.assertFalse(build(complete_reasons=['x'])['complete'])

    def test_mixed_versions_listed(self):
        r = build()
        r2 = record.build_run_record(
            run_id='x', plugin=r['plugin'],
            arms={'none': arm('不装', 0, {}, claude_version='2.1.300'),
                  'current': arm('当前版', 0, {}, claude_version='2.1.301')},
            delta={'cases': {}, 'overall': None, 'missing_cases': []}, cases=[], incomplete_reasons=[],
            threshold=1.0, started_at='a', finished_at='b', environment={})
        self.assertEqual(r2['claude_code_version'], ['2.1.300', '2.1.301'])


class ReportTest(unittest.TestCase):
    def test_report_has_status_scores_and_delta(self):
        md = record.render_report(build(cur_scores=(1.0, 0.5)))
        self.assertIn('待审', md)
        self.assertIn('demo', md)
        self.assertIn('1.2.3', md)
        self.assertIn('| 不装 |', md)
        self.assertIn('| 当前版 |', md)
        self.assertIn('0.50', md)      # 不装臂总分
        self.assertIn('+0.67', md)     # 用例 a 的差
        self.assertIn('-0.17', md)     # 用例 b 的差
        self.assertIn('with-only', md)  # 剔除说明

    def test_report_lists_cases_below_threshold(self):
        md = record.render_report(build(cur_scores=(1.0, 0.5)))
        self.assertIn('未达 threshold', md)
        section = md.split('未达 threshold', 1)[1].split('\n## ', 1)[0]
        self.assertIn('b', section)
        self.assertNotIn('- a', section)
        self.assertNotIn('未达 threshold', record.render_report(build()))

    def test_report_warns_cases_without_scored_graders(self):
        r = build()
        r['arms']['current']['cases']['a'] = dict(case(None, (None,)), no_scored_graders=True,
                                                  excluded_graders={'m': 'with-only'})
        md = record.render_report(r)
        self.assertIn('没有可计分的 grader', md)
        self.assertIn('当前版', md.split('没有可计分的 grader', 1)[1].split('\n## ', 1)[0])

    def test_report_states_trust_scope(self):
        md = record.render_report(build())
        self.assertIn('scaffold_script', md)
        self.assertIn('--trust-plugin', md)

    def test_scrub_home(self):
        home = '/Users/someone'
        rec = {'a': '/Users/someone/.local/bin/claude', 'b': ['/Users/someone', '/Users/someoneelse/x'],
               'c': {'d': 'see /Users/someone/x and /tmp/y'}, 'e': 3}
        out = record.scrub_home(rec, home)
        self.assertEqual(out['a'], '~/.local/bin/claude')
        self.assertEqual(out['b'], ['~', '/Users/someoneelse/x'])
        self.assertEqual(out['c']['d'], 'see ~/x and /tmp/y')
        self.assertEqual(out['e'], 3)

    def test_report_lists_incomplete_reasons(self):
        md = record.render_report(build(complete_reasons=['当前版臂：1 个用例加载失败']))
        self.assertIn('不完整', md)
        self.assertIn('1 个用例加载失败', md)


if __name__ == '__main__':
    unittest.main()
