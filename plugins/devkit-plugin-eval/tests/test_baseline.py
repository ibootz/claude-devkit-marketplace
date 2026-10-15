"""票 11：基线已满足判定（不装臂 3 次 ≥ 2/3）与离线对照里的回归守护（假的 eval 运行器，不调模型）。"""
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import _support
from _support import aggregate, grader, make_plugin, make_sandbox, run_result, tmpdir, write
from plugin_eval_lib import baseline, cli, clauses, compare, record, registry
from test_compare import passing_preflight

NAME = 'demo-plugin'
SILENT = lambda *a: None
GRADERS = [grader('rule'), grader('marker', 'regex', arm='with-only')]


def at(minute):
    return lambda: datetime(2026, 10, 15, 8, minute, tzinfo=timezone.utc)


class ScriptedEval:
    """passes(臂, 用例, 第几次) -> 是否通过 rule；error(臂, 用例, 第几次) -> 出错文本或 None。记下每次跑到的用例。"""

    def __init__(self, sandbox_root, passes, error=None):
        self.sandbox_root, self.passes, self.error = Path(sandbox_root), passes, error or (lambda *a: None)
        self.seen = []

    def __call__(self, cmd, cwd, env, log_dir):
        arm_dir = Path(cmd[3])
        arm = arm_dir.name
        out = Path(cmd[cmd.index('--output-dir') + 1])
        out.mkdir(parents=True, exist_ok=True)
        names = sorted(p.name for p in (arm_dir / 'evals').iterdir() if p.is_dir())
        self.seen.append((arm, names))
        cases = []
        for n in names:
            runs = []
            for i in range(int(cmd[cmd.index('--runs') + 1])):
                sb = make_sandbox(self.sandbox_root, '%s-%s-%d-%d' % (arm, n, i, len(self.seen)))
                runs.append(run_result({'rule': self.passes(arm, n, i), 'marker': arm != 'none'},
                                       error=self.error(arm, n, i), trace_path=str(sb / 'out' / 'trace.jsonl')))
            cases.append((n, GRADERS, runs))
        (out / 'aggregate-result.json').write_text(json.dumps(aggregate(cases, root=str(arm_dir))), encoding='utf-8')
        (Path(log_dir) / 'eval.stderr').write_text('', encoding='utf-8')
        return 0, ''


class VerdictTest(unittest.TestCase):
    def v(self, scores, invalid=0, no_graders=False):
        return baseline.verdict({'run_scores': scores, 'invalid_runs': [{}] * invalid, 'valid_runs': len(scores),
                                 'no_scored_graders': no_graders}, 3, 1.0)['verdict']

    def test_two_of_three(self):
        self.assertEqual(self.v([1.0, 1.0, 1.0]), 'satisfied')
        self.assertEqual(self.v([1.0, 0.5, 1.0]), 'satisfied')
        self.assertEqual(self.v([1.0, 0.0, 0.5]), 'not-satisfied')
        self.assertEqual(self.v([1.0, 1.0], invalid=1), 'satisfied')        # 剩下那次怎样都不改结论
        self.assertEqual(self.v([1.0, 0.0], invalid=1), 'undecided')
        self.assertEqual(self.v([0.0, 0.0], invalid=1), 'not-satisfied')
        self.assertEqual(self.v([None, None, None], no_graders=True), 'no-rule-graders')
        self.assertEqual(baseline.verdict(None, 3, 1.0)['verdict'], 'undecided')


class RunBaselineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.data = self.tmp / 'data'
        self.repo = self.tmp / 'repo'
        self.plugin = make_plugin(self.repo / 'plugins' / NAME, name=NAME, cases=('easy', 'hard', 'old'))
        registry.register(self.data, NAME, self.repo)
        self.sandboxes = self.tmp / 'sb'
        self.sandboxes.mkdir()
        self.asm = self.tmp / 'asm'
        self.asm.mkdir()
        self.root = self.repo / 'plugin-evals' / NAME
        # old 已有结论且内容没变：默认不重判
        write(self.root / baseline.RECORD_FILE, json.dumps({'schema_version': 1, 'plugin': NAME, 'cases': {
            'old': {'verdict': 'not-satisfied', 'case_fingerprint': baseline.case_fingerprint(self.plugin / 'evals', 'old')}}}))

    def run_bl(self, passes, minute=1, **kw):
        fake = ScriptedEval(self.sandboxes, passes, kw.pop('error', None))
        res = baseline.run_baseline(self.data, NAME, runner=fake, claude='/fake/claude', tmp_parent=self.asm,
                                    sandbox_roots=[self.sandboxes], preflight_check=passing_preflight, log=SILENT,
                                    now=at(minute), **kw)
        return fake, res

    def test_tags_satisfied_case_and_records_verdict(self):
        fake, (run_dir, res) = self.run_bl(lambda arm, n, i: n == 'easy' or (n == 'hard' and i == 0))
        self.assertEqual(fake.seen, [('none', ['easy', 'hard'])])          # 只跑不装臂、只跑没有结论的用例
        self.assertEqual({c: v['verdict'] for c, v in res.items()}, {'easy': 'satisfied', 'hard': 'not-satisfied'})
        self.assertIn(baseline.TAG, clauses.case_tags(self.plugin / 'evals' / 'easy'))
        self.assertNotIn(baseline.TAG, clauses.case_tags(self.plugin / 'evals' / 'hard'))
        rec = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual((rec['kind'], list(rec['arms'])), ('baseline', ['none']))
        self.assertIn('基线已满足', (run_dir / 'report.md').read_text(encoding='utf-8'))
        doc = baseline.load_record(self.repo, NAME)
        self.assertEqual(doc['cases']['easy']['passes'], 3)
        # 第二次：都有结论，不跑
        fake2, (rd2, res2) = self.run_bl(lambda *a: True, minute=2)
        self.assertEqual((fake2.seen, rd2), ([], None))
        # 改了用例内容：重判；这次不装臂做不到了，去掉 tag
        write(self.plugin / 'evals' / 'easy' / 'graders' / 'g2.md', '---\ntype: regex\npattern: y\n---\n')
        fake3, (_, res3) = self.run_bl(lambda *a: False, minute=3)
        self.assertEqual(fake3.seen, [('none', ['easy'])])
        self.assertNotIn(baseline.TAG, clauses.case_tags(self.plugin / 'evals' / 'easy'))

    def test_undecided_keeps_tag_untouched_and_is_retried(self):
        err = lambda arm, n, i: 'boom' if i == 2 else None
        _, (_, res) = self.run_bl(lambda arm, n, i: i == 0, cases=['easy'], error=err)
        self.assertEqual(res['easy']['verdict'], 'undecided')
        self.assertNotIn(baseline.TAG, clauses.case_tags(self.plugin / 'evals' / 'easy'))
        doc = baseline.load_record(self.repo, NAME)
        self.assertIn('easy', baseline.select_cases(self.plugin / 'evals', ['easy', 'old'], doc))

    def test_compare_reports_regression_only_for_satisfied_cases(self):
        self.run_bl(lambda arm, n, i: n == 'easy')
        fake = ScriptedEval(self.sandboxes, lambda arm, n, i: (n == 'easy' and arm == 'none') or (n == 'hard' and arm == 'current'))
        res = compare.run_compare(self.data, NAME, runs=3, concurrency=1, claude='/fake/claude', runner=fake,
                                  tmp_parent=self.asm, sandbox_roots=[self.sandboxes], log=SILENT,
                                  preflight_check=passing_preflight, use_judge=False, now=at(10),
                                  clause_ai=lambda *a: (_ for _ in ()).throw(Exception('no ai')))
        rec = res.record
        self.assertIsNone(rec['delta']['cases']['easy'])
        self.assertEqual(rec['delta']['excluded_baseline_satisfied'], ['easy'])
        self.assertEqual(rec['baseline']['cases']['easy']['status'], 'below-baseline')  # 无上一版臂，装上后反而做不到
        self.assertEqual(rec['baseline']['cases']['easy']['raw_delta'], -1.0)
        self.assertAlmostEqual(rec['delta']['overall'], 0.5)                          # 只剩 hard（+1）与 old（0）
        report = (res.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn('| easy | 1.00 | 0.00 | 回归守护 |', report)
        self.assertIn('回归守护', report)
        self.assertIn('## 回归守护（基线已满足的用例）', report)
        self.assertIn('**低于基线**', report)
        self.assertIn('不含 1 个回归守护用例', report)

    def test_cli_baseline_subcommand_registered(self):
        args = cli._parser().parse_args(['baseline', NAME, '--case', 'easy', '--recheck'])
        self.assertEqual((args.cmd, args.case, args.recheck, args.runs), ('baseline', ['easy'], True, 3))


class ApplyToRecordTest(unittest.TestCase):
    def test_compares_with_previous_then_falls_back(self):
        rec = {'threshold': 1.0, 'delta': {'cases': {'a': 0.0, 'b': None, 'c': 0.5, 'd': 0.0, 'e': -1.0}, 'overall': 0},
               'arms': {'current': {'cases': {'a': {'score': 1.0, 'run_scores': [1.0, 1.0, 0.0]},
                                              'b': {'score': None, 'run_scores': [None]},
                                              'd': {'score': 0.5, 'run_scores': [1.0, 0.0]},
                                              'e': {'score': 0.0, 'run_scores': [0.0]}}},
                        'previous': {'cases': {'a': {'score': 0.67}, 'd': {'score': 1.0}}},
                        'none': {'cases': {'a': {'score': 1.0}}}}}
        baseline.apply_to_record(rec, {'a', 'b', 'd', 'e', 'zzz'})
        st = {c: v['status'] for c, v in rec['baseline']['cases'].items()}
        self.assertEqual(st, {'a': 'held', 'b': 'no-score', 'd': 'regressed', 'e': 'below-baseline'})
        self.assertEqual(rec['delta']['overall'], 0.5)
        self.assertEqual(rec['baseline']['regressed'], ['d', 'e'])
        self.assertIn('**退化**', '\n'.join(baseline.report_sections(rec)))
        untouched = {'delta': {'cases': {'a': 0.0}, 'overall': 0.0}}
        baseline.apply_to_record(untouched, set())
        self.assertNotIn('baseline', untouched)


if __name__ == '__main__':
    unittest.main()
