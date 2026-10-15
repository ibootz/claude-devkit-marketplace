"""AI 评委（票 09）：两遍判分、分歧样本与抽检进待审页、用户裁定存金标、金标校准与不采信、评委模型配置。
评委用假 runner，不调模型；eval 用 test_compare 的 FakeEval。"""
import gzip
import io
import json
import threading
import unittest
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import _support
from _support import tmpdir, write
from plugin_eval_lib import cli, clauses, compare, judge, judgepending, judgereport, pending, record, registry, resume
from test_compare import FakeEval, passing_preflight
from test_resume import ScriptedEval

T0 = datetime(2026, 10, 15, 9, 0, 0, tzinfo=timezone.utc)


class FakeJudge(object):
    """decide(prompt, 第几次见到这份 prompt) -> verdict 或 ('error', 文字)。记下每次调用。"""

    def __init__(self, decide, models=None):
        self.decide = decide
        self.models = models
        self.calls = []
        self.seen = {}
        self.lock = threading.Lock()

    def __call__(self, prompt, model):
        with self.lock:
            n = self.seen.get(prompt, 0)
            self.seen[prompt] = n + 1
            self.calls.append(model)
        v = self.decide(prompt, n)
        used = self.models or [model]
        usage = {m: {'input_tokens': 100, 'output_tokens': 10, 'cost_usd': 0.01} for m in used}
        if isinstance(v, tuple):
            return {'error': v[1], 'models': used, 'usage': usage, 'cost_usd': 0.01}
        return {'text': '判完了。{"verdict": "%s", "reason": "理由"}' % v, 'models': used, 'usage': usage,
                'cost_usd': 0.01}


def criterion_says(word):
    return lambda prompt: word in prompt.split('## 用户请求')[0]


class JudgeCompareBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.data = self.tmp / 'data'
        self.repo = self.tmp / 'repo'
        self.plugin = _support.make_plugin(self.repo / 'plugins' / 'demo-plugin', cases=('case-a', 'case-b'))
        # case-a：判定标准与规则 grader「rule」对照；case-b：只交评委
        write(self.plugin / 'evals' / 'case-a' / 'judge' / 'follows.md',
              '---\nrule: rule\n---\nCRIT-A 助手照规则做了\n')
        write(self.plugin / 'evals' / 'case-b' / 'judge' / 'tone.md', 'CRIT-B 回复语气平和\n')
        self.sandboxes = self.tmp / 'sandboxes'
        self.sandboxes.mkdir()
        self.assembly = self.tmp / 'assembly'
        self.assembly.mkdir()
        registry.register(self.data, 'demo-plugin', self.repo)
        self.evals = self.repo / 'plugin-evals' / 'demo-plugin'

    def compare(self, fj, minute=0, runs=2, concurrency=2, **kw):
        return compare.run_compare(
            self.data, 'demo-plugin', runs=runs, concurrency=concurrency, claude='/fake/claude',
            runner=FakeEval(self.sandboxes, {'none': False, 'current': True}), env={'PATH': '/usr/bin'},
            tmp_parent=self.assembly, sandbox_roots=[self.sandboxes], log=lambda *a: None,
            preflight_check=passing_preflight, judge_runner=fj,
            now=lambda: datetime(2026, 10, 15, 8, minute, tzinfo=timezone.utc), **kw)

    def judge_json(self, res):
        return json.loads((res.run_dir / 'judge.json').read_text(encoding='utf-8'))

    def run_json(self, res):
        return json.loads((res.run_dir / 'run.json').read_text(encoding='utf-8'))


class TwoPassAndDisagreementTest(JudgeCompareBase):
    def test_two_passes_recorded_and_rule_conflict_goes_to_pending_page(self):
        # 评委对 CRIT-A 一律判 fail：当前版臂规则 rule 通过 → 评委与规则冲突（分歧）；不装臂规则不通过 → 两遍一致
        fj = FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass')
        res = self.compare(fj)
        doc = self.judge_json(res)
        # 2 臂 × 2 用例 × 2 次 × 1 条判定标准 = 8 个样本，每个两遍
        self.assertEqual(len(doc['samples']), 8)
        self.assertEqual(len(fj.calls), 16)
        for s in doc['samples']:
            self.assertEqual(len(s['passes']), 2)
            self.assertTrue(all(p['verdict'] in ('pass', 'fail') for p in s['passes']))
        conflicts = [s for s in doc['samples'] if s['status'] == 'disagreement']
        self.assertEqual({(s['arm'], s['case'], s['disagreement']) for s in conflicts},
                         {('current', 'case-a', 'rule-conflict')})
        self.assertEqual(len(conflicts), 2)
        rec = self.run_json(res)
        self.assertEqual(rec['judge']['disagreements'], 2)
        self.assertEqual(rec['judge_model'], judge.DEFAULT_MODEL)
        self.assertTrue(rec['complete'])
        # 分歧样本全上待审页
        page = pending.generate(self.data, 'demo-plugin', now=lambda: T0)
        types = [it['type'] for it in page.items]
        self.assertEqual(types.count('judge-disagreement'), 2)
        html = page.html_path.read_text(encoding='utf-8')
        self.assertIn('分歧样本', html)
        self.assertIn('评委与规则冲突', html)
        self.assertIn('CRIT-A', html)
        # 盲判：页上不写样本来自哪一臂
        self.assertNotIn('当前版臂', html.split('</h1>', 1)[1].split('报告审阅')[0])

    def test_two_pass_flip_is_disagreement(self):
        # 同一份 prompt 第 1 遍 pass、第 2 遍 fail（串行跑，次序确定）
        fj = FakeJudge(lambda p, n: ('pass', 'fail')[n % 2] if criterion_says('CRIT-B')(p) else 'pass')
        res = self.compare(fj, concurrency=1, runs=1)
        doc = self.judge_json(res)
        flips = [s for s in doc['samples'] if s['case'] == 'case-b']
        self.assertTrue(flips)
        self.assertTrue(all(s['status'] == 'disagreement' and s['disagreement'] == 'two-pass' for s in flips))
        self.assertEqual([p['verdict'] for p in flips[0]['passes']], ['pass', 'fail'])


class SpotCheckTest(JudgeCompareBase):
    def test_three_spot_checks_from_agreed_and_all_when_fewer(self):
        fj = FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass')
        doc = self.judge_json(self.compare(fj))
        agreed = [s for s in doc['samples'] if s['status'] == 'agreed']
        spots = [s for s in doc['samples'] if s['spot_check']]
        self.assertEqual(len(agreed), 6)
        self.assertEqual(len(spots), 3)
        self.assertTrue(all(s['status'] == 'agreed' for s in spots))
        # 抽检样本与分歧样本的 trace 压缩进 samples/；其余不入库
        stored = {s['sample_file'] for s in doc['samples'] if s['sample_file']}
        self.assertEqual(len(stored), len({(s['arm'], s['case'], s['run']) for s in doc['samples']
                                           if s['spot_check'] or s['status'] == 'disagreement'}))
        page = pending.generate(self.data, 'demo-plugin', now=lambda: T0)
        self.assertEqual([it['type'] for it in page.items].count('judge-spot-check'), 3)

    def test_fewer_than_three_agreed_all_spot_checked(self):
        # 只有 case-b 的判定标准判当前版臂，且一次 run：一致样本只有 1 个
        write(self.plugin / 'evals' / 'case-b' / 'judge' / 'tone.md', '---\narms: [current]\n---\nCRIT-B 语气\n')
        (self.plugin / 'evals' / 'case-a' / 'judge' / 'follows.md').unlink()
        doc = self.judge_json(self.compare(FakeJudge(lambda p, n: 'pass'), runs=1))
        self.assertEqual(len(doc['samples']), 1)
        self.assertTrue(doc['samples'][0]['spot_check'])


class GoldTest(JudgeCompareBase):
    def _adjudicate_all(self, code='A'):
        page = pending.generate(self.data, 'demo-plugin', now=lambda: T0)
        nos = [it['no'] for it in page.items if it['type'].startswith('judge-')]
        reply = 'PE1 %s %s %s' % (page.run_id, page.page_id, ' '.join('%d%s' % (n, code) for n in nos))
        return page, pending.apply_reply(self.data, 'demo-plugin', reply, now=lambda: T0)

    def test_user_verdict_saved_as_gold_and_next_run_judges_gold_first(self):
        fj = FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass')
        res = self.compare(fj)
        page, applied = self._adjudicate_all('A')
        doc = self.judge_json(res)
        decided = [s for s in doc['samples'] if s['user']]
        self.assertEqual(len(decided), 5)          # 2 个分歧 + 3 个抽检
        self.assertTrue(all(s['user']['verdict'] == 'pass' and s['gold_id'] for s in decided))
        gold_files = sorted((self.evals / 'gold').glob('*.json'))
        self.assertEqual(len(gold_files), 5)
        g = json.loads(gold_files[0].read_text(encoding='utf-8'))
        self.assertEqual(g['user_verdict'], 'pass')
        self.assertTrue((self.evals / g['sample_file']).is_file())
        self.assertIn('CRIT-', g['criterion_text'])
        # run.json 与 report.md 同步：用户裁定数、金标列
        rec = self.run_json(res)
        self.assertEqual(rec['judge']['user_decided'], 5)
        report = (res.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn(g['id'], report)
        # 分歧经用户裁定后计入 AI 判分：当前版 case-a 两个样本都按用户的「通过」
        self.assertEqual(doc['scores']['arms']['current']['cases']['case-a'], 1.0)
        self.assertIn('gold/', ' '.join(applied.changed_files))

        # 下一次对照：先判金标，记一致率（未配置阈值：只记不校准，仍采信）
        fj2 = FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass')
        res2 = self.compare(fj2, minute=5)
        doc2 = self.judge_json(res2)
        self.assertEqual(doc2['gold']['total'], 5)
        self.assertEqual(doc2['gold']['judged'], 5)
        self.assertEqual({k: v['total'] for k, v in doc2['gold']['by_source'].items()},
                         {'disagreement': 2, 'spot-check': 3})
        self.assertEqual({json.loads(f.read_text(encoding='utf-8'))['source'] for f in gold_files},
                         {'disagreement', 'spot-check'})
        # 5 条金标用户都判通过；评委对 CRIT-A 判 fail：CRIT-A 上的金标不一致
        n_a = sum(1 for f in gold_files if 'CRIT-A' in json.loads(f.read_text(encoding='utf-8'))['criterion_text'])
        self.assertEqual(doc2['gold']['agreed'], 5 - n_a)
        self.assertAlmostEqual(doc2['gold']['agreement_rate'], (5 - n_a) / 5)
        self.assertFalse(doc2['gold']['enabled'])
        self.assertIsNone(doc2['trusted'])                     # 未配置校准：采信（未校准）
        self.assertIn('是否采信：采信（未校准）', (res2.run_dir / 'report.md').read_text(encoding='utf-8'))
        self.assertEqual(len(fj2.calls), 16 + 5)

    def test_unclear_verdict_not_saved_as_gold(self):
        self.compare(FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass'))
        self._adjudicate_all('C')
        self.assertFalse((self.evals / 'gold').exists() and list((self.evals / 'gold').glob('*.json')))

    def test_low_agreement_marks_untrusted(self):
        self.compare(FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass'))
        self._adjudicate_all('A')
        # 分歧来源的金标 2 条（抽检 3 条不计入启用所需条数）
        write(self.evals / 'judge-config.json', json.dumps({'gold_agreement_threshold': 0.9, 'gold_min_samples': 2}))
        res = self.compare(FakeJudge(lambda p, n: 'fail'), minute=5)   # 评委一律 fail：与用户的「通过」全不一致
        rec = self.run_json(res)
        self.assertFalse(rec['judge']['trusted'])
        self.assertTrue(rec['judge']['gold']['enabled'])
        self.assertEqual(rec['judge']['gold']['agreement_rate'], 0)
        report = (res.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn('AI 判分不采信', report)
        self.assertLess(report.index('AI 判分不采信'), report.index('## 各臂总分'))

    def test_calibration_not_enabled_below_min_samples(self):
        self.compare(FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass'))
        self._adjudicate_all('A')
        write(self.evals / 'judge-config.json', json.dumps({'gold_agreement_threshold': 0.9, 'gold_min_samples': 50}))
        res = self.compare(FakeJudge(lambda p, n: 'fail'), minute=5)
        rec = self.run_json(res)
        self.assertIsNone(rec['judge']['trusted'])             # 三态：不足启用条数 → null，报告写「采信（未校准）」
        self.assertFalse(rec['judge']['gold']['enabled'])
        self.assertEqual(rec['judge']['gold']['state'], 'insufficient')
        self.assertIn('不足', rec['judge']['gold']['note'])
        self.assertTrue(rec['complete'])
        self.assertIn('是否采信：采信（未校准）', (res.run_dir / 'report.md').read_text(encoding='utf-8'))

    def test_spot_check_gold_does_not_count_toward_calibration(self):
        """判采信只用分歧来源：抽检来源一致率高也救不回分歧来源的不一致。"""
        self.compare(FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass'))
        self._adjudicate_all('A')                                  # 分歧 2 条（CRIT-A）+ 抽检 3 条，用户全判通过
        write(self.evals / 'judge-config.json', json.dumps({'gold_agreement_threshold': 0.5, 'gold_min_samples': 2}))
        rec = self.run_json(self.compare(FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass'),
                                         minute=5))
        g = rec['judge']['gold']
        self.assertEqual(g['by_source']['disagreement']['agreement_rate'], 0)
        self.assertEqual(g['by_source']['spot-check']['agreement_rate'], 1)
        self.assertGreater(g['agreement_rate'], 0.5)              # 合起来过阈值……
        self.assertFalse(rec['judge']['trusted'])                 # ……但只按分歧来源判：不采信

    def test_calibration_short_because_of_call_errors_is_incomplete(self):
        """校准已配置、金标够条数，却因评委调用出错判成的不够：运行不完整（可续跑），出错进 reasons。"""
        self.compare(FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass'))
        self._adjudicate_all('A')
        write(self.evals / 'judge-config.json', json.dumps({'gold_agreement_threshold': 0.5, 'gold_min_samples': 2}))
        # 金标的判定标准正文就是 CRIT-A / CRIT-B：评委对金标调用（每条只判一遍）一律出错，样本两遍照常
        gold_texts = {json.loads(f.read_text(encoding='utf-8'))['criterion_text']
                      for f in (self.evals / 'gold').glob('*.json')}
        fj = FakeJudge(lambda p, n: ('error', 'You have hit your usage limit')
                       if n == 0 and any(t in p for t in gold_texts) and 'GOLD' not in p else 'pass')
        orig = judge.calibrate

        def failing_calibrate(plugin_evals, cfg, judge_fn):
            return orig(plugin_evals, cfg, lambda prompt: {'verdict': None, 'reason': None, 'error': '撞限',
                                                           'models': [], 'usage': {}, 'cost_usd': 0})
        judge.calibrate = failing_calibrate
        try:
            res = self.compare(fj, minute=5)
        finally:
            judge.calibrate = orig
        rec = self.run_json(res)
        self.assertEqual(rec['judge']['gold']['state'], 'insufficient-errors')
        self.assertFalse(rec['complete'])
        self.assertTrue(any('金标校准' in r and '续跑时重判' in r for r in rec['incomplete_reasons']),
                        rec['incomplete_reasons'])
        self.assertIsNone(rec['judge']['trusted'])


class ModelConfigTest(JudgeCompareBase):
    def test_default_is_most_expensive_tier(self):
        fj = FakeJudge(lambda p, n: 'pass')
        rec = self.run_json(self.compare(fj))
        self.assertEqual(set(fj.calls), {'claude-fable-5-1'})
        self.assertEqual(rec['judge_model'], 'claude-fable-5-1')

    def test_config_file_then_cli_override(self):
        write(self.evals / 'judge-config.json', json.dumps({'model': 'cfg-model'}))
        fj = FakeJudge(lambda p, n: 'pass')
        rec = self.run_json(self.compare(fj))
        self.assertEqual(set(fj.calls), {'cfg-model'})
        self.assertEqual(rec['judge_model'], 'cfg-model')
        self.assertIn('judge-config.json', rec['judge']['model_source'])
        fj2 = FakeJudge(lambda p, n: 'pass')
        rec2 = self.run_json(self.compare(fj2, minute=3, judge_model='cli-model'))
        self.assertEqual(set(fj2.calls), {'cli-model'})
        self.assertEqual(rec2['judge_model'], 'cli-model')

    def test_records_model_actually_used(self):
        fj = FakeJudge(lambda p, n: 'pass', models=['claude-other-9'])
        res = self.compare(fj)
        self.assertEqual(self.run_json(res)['judge_model'], 'claude-other-9')
        self.assertEqual(self.judge_json(res)['requested_model'], 'claude-fable-5-1')

    def test_bad_config_aborts_before_any_eval(self):
        write(self.evals / 'judge-config.json', json.dumps({'gold_agreement_threshold': 3}))
        with self.assertRaises(compare.CompareError):
            self.compare(FakeJudge(lambda p, n: 'pass'))
        self.assertFalse((self.evals / 'runs').exists())

    def test_no_judge_flag_and_no_criteria_skip_judge(self):
        write(self.evals / 'judge-config.json', '{坏的配置')      # --no-judge 时不读配置：坏配置也不拦
        fj = FakeJudge(lambda p, n: 'pass')
        res = self.compare(fj, use_judge=False)
        self.assertEqual(fj.calls, [])
        rec = self.run_json(res)
        self.assertEqual(rec['judge'], {'skipped': 'no-judge'})
        self.assertEqual(rec['environment']['judge'], {'enabled': False, 'model': None})
        self.assertFalse((res.run_dir / 'judge.json').exists())
        report = (res.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn('按 --no-judge 跳过', report)
        self.assertIn('- 判分：规则 grader 定分与是否通过；AI 评委按 --no-judge 跳过', report)
        # 没有判定标准：照旧写「未调 AI 评委」
        for f in self.plugin.glob('evals/*/judge/*.md'):
            f.unlink()
        (self.evals / 'judge-config.json').unlink()
        res2 = self.compare(FakeJudge(lambda p, n: 'pass'), minute=3)
        self.assertIsNone(self.run_json(res2)['judge'])
        self.assertIn('未调 AI 评委', (res2.run_dir / 'report.md').read_text(encoding='utf-8'))
        self.assertIn('只用规则 grader（没有用例声明 AI 评委判定标准）',
                      (res2.run_dir / 'report.md').read_text(encoding='utf-8'))

    def test_cli_flags(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(['--data-dir', str(self.data), 'compare', 'ghost', '--judge-model', 'x', '--no-judge'])
        self.assertEqual(code, 2)     # 未登记；参数本身被接受


class ErrorAndResumeTest(JudgeCompareBase):
    def test_judge_error_marks_incomplete_and_rejudge_reuses_good_samples(self):
        bad = FakeJudge(lambda p, n: ('error', 'You have hit your usage limit') if criterion_says('CRIT-B')(p)
                        else 'pass')
        res = self.compare(bad)
        rec = self.run_json(res)
        self.assertFalse(rec['complete'])
        self.assertTrue(any('AI 评委' in r for r in rec['incomplete_reasons']))
        self.assertEqual(rec['judge']['errors'], 4)
        self.assertIn('判分出错', (res.run_dir / 'report.md').read_text(encoding='utf-8'))
        # 再判一遍（续跑走同一入口）：只重判出错的 4 个样本 × 两遍
        good = FakeJudge(lambda p, n: 'pass')
        arm_records = {}
        for arm, label in (('none', '不装'), ('current', '当前版')):
            agg = json.loads((res.run_dir / 'arms' / arm / 'aggregate-result.json').read_text(encoding='utf-8'))
            arm_records[arm] = {'label': label, '_agg': agg}
        doc, reasons = judge.run(
            arm_records=arm_records, labels={'none': '不装', 'current': '当前版'}, evals_src=self.plugin / 'evals',
            run_dir=res.run_dir, run_id=res.run_dir.name,
            opts=judge.resolve_options({'runner': good}, res.run_dir), claude=None, env={},
            trace_key=compare.TRACE_DIR_KEY, data_dir=self.data, log=lambda *a: None)
        self.assertEqual(reasons, [])
        self.assertEqual(len(good.calls), 8)
        self.assertFalse([s for s in doc['samples'] if s['status'] == 'error'])
        self.assertTrue(doc['complete'])

    def test_judge_step_crash_does_not_abort_finalize_and_resume_rejudges(self):
        """评委这一步整体抛异常（如评委回的 JSON 不是对象、样本写盘 OSError）：收尾照常写 run.json 与报告，
        记为不完整原因；续跑时重判。"""
        with mock.patch.object(compare.judge, 'run', side_effect=ValueError('评委返回的不是 JSON 对象')):
            res = self.compare(FakeJudge(lambda p, n: 'pass'))
        rec = self.run_json(res)
        self.assertFalse(rec['complete'])
        self.assertIn('AI 评委这一步出错（ValueError: 评委返回的不是 JSON 对象），本次没有评委判分；续跑时重判',
                      rec['incomplete_reasons'])
        self.assertEqual(rec['judge'], {'failed': 'ValueError: 评委返回的不是 JSON 对象'})
        report = (res.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn('**AI 评委这一步出错**', report)
        self.assertNotIn('没有用例声明 AI 评委判定标准', report)
        self.assertIn('这一步出错', judgereport.console_line(rec['judge']))
        good = FakeJudge(lambda p, n: 'pass')
        res2 = resume.resume_run(self.data, res.run_dir, claude='/fake/claude',
                                 runner=FakeEval(self.sandboxes, {'none': False, 'current': True}),
                                 tmp_parent=self.assembly, sandbox_roots=[self.sandboxes], log=lambda *a: None,
                                 preflight_check=passing_preflight, judge_runner=good)
        self.assertTrue(res2.record['complete'], res2.record['incomplete_reasons'])
        self.assertTrue(good.calls)
        self.assertNotIn('failed', res2.record['judge'])


class CriteriaAndClauseTest(JudgeCompareBase):
    def test_bad_frontmatter_aborts_before_any_eval(self):
        write(self.plugin / 'evals' / 'case-b' / 'judge' / 'tone.md', '---\nrulez: g1\n---\nCRIT-B 回复语气平和\n')
        with self.assertRaises(compare.CompareError) as cm:
            self.compare(FakeJudge(lambda p, n: 'pass'))
        self.assertIn('不认识的键 rulez', str(cm.exception))
        self.assertFalse((self.evals / 'runs').exists())

    def test_unknown_rule_grader_warned_in_report(self):
        write(self.plugin / 'evals' / 'case-b' / 'judge' / 'tone.md', '---\nrule: nope\n---\nCRIT-B 回复语气平和\n')
        res = self.compare(FakeJudge(lambda p, n: 'pass'))
        rec = self.run_json(res)
        self.assertTrue(any('「nope」在该用例里不存在' in w for w in rec['judge']['warnings']), rec['judge']['warnings'])
        report = (res.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn('AI 评委判定标准有告警', report)
        self.assertIn('### 判定标准告警', report)

    def _clause_list(self, retired=()):
        write(self.evals / 'clauses.json', json.dumps({'clauses': [
            {'id': 'C001', 'criterion': '照规则做', 'status': 'retired' if 'C001' in retired else 'active'},
            {'id': 'C002', 'criterion': '语气平和', 'status': 'active'}]}))

    def test_gold_records_clause_and_retired_clause_gold_is_inactive(self):
        write(self.plugin / 'evals' / 'case-a' / 'judge' / 'follows.md', '---\nrule: rule\nclause: C001\n---\nCRIT-A 助手照规则做了\n')
        self._clause_list()
        self.compare(FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass'))
        GoldTest._adjudicate_all(self, 'A')
        golds = [json.loads(f.read_text(encoding='utf-8')) for f in (self.evals / 'gold').glob('*.json')]
        on_a = [g for g in golds if g['case'] == 'case-a']
        self.assertTrue(on_a and all(g['clause'] == 'C001' and g['active'] for g in on_a))
        self.assertTrue(all(g['trace_dir'] for g in golds))
        # 条款 C001 退役：金标不参与校准，报告告警
        self._clause_list(retired=('C001',))
        res = self.compare(FakeJudge(lambda p, n: 'pass'), minute=5)
        rec = self.run_json(res)
        self.assertEqual(rec['judge']['gold']['total'], len(golds) - len(on_a))
        self.assertEqual(rec['judge']['gold']['retired_clauses'], ['C001'])
        self.assertTrue(any('C001 已退役' in w for w in rec['judge']['warnings']))

    def test_confirming_clause_retirement_deactivates_gold(self):
        write(self.plugin / 'evals' / 'case-a' / 'judge' / 'follows.md', '---\nrule: rule\nclause: C001\n---\nCRIT-A 助手照规则做了\n')
        self._clause_list()
        self.compare(FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass'))
        GoldTest._adjudicate_all(self, 'A')
        sub = pending.Subject(self.repo, next((self.evals / 'runs').iterdir()), {'run_id': 'x'})
        clauses._deactivate_gold(sub, {'C001'}, '2026-10-15T09:00:00Z')
        sub.commit()
        golds = [json.loads(f.read_text(encoding='utf-8')) for f in (self.evals / 'gold').glob('*.json')]
        self.assertTrue(all((not g['active']) == (g.get('clause') == 'C001') for g in golds))
        self.assertTrue(all(g['deactivated']['reason'] == 'clause-retired' for g in golds if not g['active']))


class ResumeOptionsTest(JudgeCompareBase):
    """续跑沿用首跑的评委选项（--no-judge、--judge-model）；补跑后金标仍指向原 trace。"""

    def scripted(self, **kw):
        outcomes = {(arm, c): [True] * 8 for arm in ('none', 'current') for c in ('case-a', 'case-b')}
        return ScriptedEval(self.sandboxes, outcomes, **kw)

    def first(self, fake, **kw):
        return compare.run_compare(
            self.data, 'demo-plugin', runs=2, concurrency=1, claude='/fake/claude', runner=fake, env={'PATH': '/usr/bin'},
            tmp_parent=self.assembly, sandbox_roots=[self.sandboxes], log=lambda *a: None,
            preflight_check=passing_preflight, now=lambda: datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc), **kw)

    def resume(self, fake, run_dir, fj):
        return resume.resume_run(self.data, run_dir, claude='/fake/claude', runner=fake, tmp_parent=self.assembly,
                                 sandbox_roots=[self.sandboxes], log=lambda *a: None,
                                 preflight_check=passing_preflight, judge_runner=fj)

    def test_no_judge_first_run_resume_does_not_judge(self):
        fake = self.scripted(crash_on='current')
        with self.assertRaises(RuntimeError):
            self.first(fake, use_judge=False)
        run_dir = next((self.evals / 'runs').iterdir())
        ckpt = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual(ckpt['environment']['judge'], {'enabled': False, 'model': None})
        fj = FakeJudge(lambda p, n: 'pass')
        res = self.resume(fake, run_dir, fj)
        self.assertEqual(fj.calls, [])
        self.assertEqual(res.record['judge'], {'skipped': 'no-judge'})

    def test_judge_model_from_first_run_kept_on_resume(self):
        fake = self.scripted(crash_on='current')
        with self.assertRaises(RuntimeError):
            self.first(fake, judge_model='model-x', clause_model='clause-model-y')
        run_dir = next((self.evals / 'runs').iterdir())
        ckpt = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual(ckpt['environment']['judge'], {'enabled': True, 'model': 'model-x'})
        self.assertEqual(ckpt['environment']['clause_model'], 'clause-model-y')
        fj = FakeJudge(lambda p, n: 'pass')
        res = self.resume(fake, run_dir, fj)
        self.assertTrue(fj.calls)
        self.assertEqual(set(fj.calls), {'model-x'})
        self.assertEqual(res.record['judge_model'], 'model-x')
        self.assertEqual(res.record['environment']['clause_model'], 'clause-model-y')

    def test_gold_keeps_pointing_at_original_trace_after_resume(self):
        """首跑有无效 run（不完整）→ 用户裁定分歧样本存金标 → 续跑补跑无效 run：金标与沿用的裁定仍对着原 trace。"""
        fake = self.scripted(fail={('current', 'case-a', 0): 'You have hit your usage limit'})
        fj = FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass')
        res = self.first(fake, judge_runner=fj)
        self.assertFalse(res.record['complete'])
        GoldTest._adjudicate_all(self, 'B')
        doc = self.judge_json(res)
        decided = {s['trace_dir']: s for s in doc['samples'] if s.get('user')}
        golds = {g['id']: g for g in (json.loads(f.read_text(encoding='utf-8'))
                                      for f in (self.evals / 'gold').glob('*.json'))}
        self.assertTrue(golds)
        before = {gid: gzip.decompress((self.evals / g['sample_file']).read_bytes()) for gid, g in golds.items()}
        res2 = self.resume(fake, res.run_dir, FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass'))
        self.assertTrue(res2.record['complete'], res2.record['incomplete_reasons'])
        doc2 = self.judge_json(res2)
        by_trace = {(s['trace_dir'], s['criterion']): s for s in doc2['samples']}
        for gid, g in golds.items():
            s = by_trace[(g['trace_dir'], g['criterion'])]
            self.assertEqual(s['gold_id'], gid)
            self.assertEqual(s['user']['verdict'], 'fail')
            self.assertEqual(s['sample_file'], g['sample_file'][len('runs/%s/' % res.run_dir.name):])
            self.assertEqual(gzip.decompress((self.evals / g['sample_file']).read_bytes()), before[gid])
        for t, s in decided.items():
            self.assertEqual(by_trace[(t, s['criterion'])]['user'], s['user'])
        # 用量：沿用样本的判分条目也计入续跑后的合计
        self.assertEqual(doc2['usage']['calls'], sum(len(s['passes']) for s in doc2['samples']) + doc2['gold']['total'])


class PureFunctionTest(unittest.TestCase):
    def test_console_line_covers_three_trust_states_and_no_judge(self):
        base = {'model': 'm', 'samples': 4, 'disagreements': 2, 'spot_checks': 2, 'errors': 0,
                'gold': {'agreement_rate': None}, 'untrusted_reason': None}
        self.assertTrue(judgereport.console_line(dict(base, trusted=None)).endswith('采信（未校准）'))
        self.assertTrue(judgereport.console_line(dict(base, trusted=True)).endswith('；采信'))
        line = judgereport.console_line(dict(base, trusted=False, untrusted_reason='一致率 0.50 低于阈值 0.80'))
        self.assertIn('不采信（一致率 0.50 低于阈值 0.80）', line)
        self.assertNotIn('None', judgereport.console_line(dict(base, trusted=None)))
        self.assertEqual(judgereport.console_line({'skipped': 'no-judge'}), 'AI 评委：按 --no-judge 跳过')
        self.assertIsNone(judgereport.console_line(None))

    def test_parse_verdict(self):
        self.assertEqual(judge.parse_verdict('{"verdict":"pass","reason":"ok"}'), ('pass', 'ok'))
        self.assertEqual(judge.parse_verdict('前言 {"x": {"y": 1}} 然后 {"verdict": "FAIL", "reason": "r"}')[0], 'fail')
        for bad in ('', '没有 JSON', '{"verdict": "maybe"}'):
            with self.assertRaises(ValueError):
                judge.parse_verdict(bad)

    def test_classify(self):
        def s(vs, rule=None, err=False):
            return {'passes': [{'verdict': v, 'error': 'x' if err and i else None} for i, v in enumerate(vs)],
                    'rule_passed': rule}
        self.assertEqual(judge.classify(s(['pass', 'pass'])), ('agreed', None))
        self.assertEqual(judge.classify(s(['pass', 'fail'])), ('disagreement', 'two-pass'))
        self.assertEqual(judge.classify(s(['unclear', 'unclear'])), ('disagreement', 'unclear'))
        self.assertEqual(judge.classify(s(['fail', 'fail'], rule=True)), ('disagreement', 'rule-conflict'))
        self.assertEqual(judge.classify(s(['fail', 'fail'], rule=False)), ('agreed', None))
        self.assertEqual(judge.classify(s(['pass', 'pass'], err=True)), ('error', None))

    def test_config_validation(self):
        tmp = tmpdir(self)
        self.assertIsNone(judge.load_config(tmp)['gold_agreement_threshold'])
        for bad in ({'gold_min_samples': 0}, {'gold_agreement_threshold': 'x'}, {'modle': 'typo'}, {'model': ''}):
            write(tmp / 'judge-config.json', json.dumps(bad))
            with self.assertRaises(judge.JudgeConfigError):
                judge.load_config(tmp)
        write(tmp / 'judge-config.json', json.dumps({'model': 'm', 'gold_agreement_threshold': 0.8,
                                                      'gold_min_samples': 5}))
        self.assertEqual(judge.load_config(tmp)['gold_min_samples'], 5)

    def test_transcript_is_blind_to_arm(self):
        lines = [
            {'type': 'system', 'subtype': 'hook_response', 'output': 'AI 工作纪律 注入文字'},
            {'type': 'system', 'subtype': 'init', 'plugins': [{'name': 'demo-plugin'}]},
            {'type': 'assistant', 'message': {'content': [{'type': 'thinking', 'thinking': '内心'},
                                                          {'type': 'text', 'text': '可见回复'},
                                                          {'type': 'tool_use', 'name': 'Read', 'input': {'p': 1}}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': '文件内容'}]}},
            {'type': 'result', 'result': '可见回复'},
        ]
        t = judge.render_transcript(lines)
        for hidden in ('注入文字', 'demo-plugin', '内心'):
            self.assertNotIn(hidden, t)
        for shown in ('可见回复', '[工具调用 Read]', '文件内容'):
            self.assertIn(shown, t)
        self.assertEqual(t.count('可见回复'), 1)
        long = judge.render_transcript([{'type': 'result', 'result': 'x' * 1000}], limit=100)
        self.assertIn('中间截断', long)

    def test_stored_sample_scrubbed_and_deterministic(self):
        tmp = tmpdir(self)
        home = '/home/someone'
        src = write(tmp / 'trace.jsonl', '\n'.join(json.dumps(o) for o in [
            {'type': 'system', 'subtype': 'init', 'cwd': home + '/proj', 'plugins': [{'name': 'INIT-ONLY'}]},
            {'type': 'system', 'subtype': 'hook_response', 'output': 'HOOK-OUTPUT'},
            {'type': 'user', 'message': {'content': 'USER-PROMPT-LINE'}},
            {'type': 'assistant', 'message': {'content': [
                {'type': 'thinking', 'thinking': 'THINKING-BODY', 'signature': 'SIG'},
                {'type': 'text', 'text': '读 %s/proj，mail a.b@example.invalid' % home}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'TOOL-RESULT'},
                                                     {'type': 'text', 'text': 'USER-SIDE-TEXT'}]}},
            {'type': 'result', 'result': 'FINAL'},
        ]) + '\nnot json\n')
        a, b = tmp / 'a.jsonl.gz', tmp / 'b.jsonl.gz'
        self.assertTrue(judge.store_sample(src, a, home=home))
        judge.store_sample(src, b, home=home)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        text = gzip.decompress(a.read_bytes()).decode('utf-8')
        self.assertNotIn(home, text)
        self.assertNotIn('@example.invalid', text)
        self.assertNotIn('SIG', text)
        self.assertIn('~/proj', text)
        for gone in ('"system"', 'INIT-ONLY', 'HOOK-OUTPUT', 'USER-PROMPT-LINE', 'THINKING-BODY', 'USER-SIDE-TEXT'):
            self.assertNotIn(gone, text)
        for kept in ('TOOL-RESULT', 'FINAL', '"assistant"'):
            self.assertIn(kept, text)
        self.assertEqual(len(text.strip().splitlines()), 3)
        self.assertFalse(judge.store_sample(tmp / 'missing.jsonl', tmp / 'c.gz'))

    def test_criteria_frontmatter(self):
        tmp = tmpdir(self)
        write(tmp / 'c' / 'judge' / 'x.md', '---\nrule: g1\narms: [current, none]\n---\n标准正文\n')
        write(tmp / 'c' / 'judge' / 'empty.md', '---\nrule: g\n---\n')
        cs = judge.case_criteria(tmp, 'c')
        self.assertEqual([c['id'] for c in cs], ['x'])
        self.assertEqual(cs[0]['rule'], 'g1')
        self.assertEqual(cs[0]['arms'], ['current', 'none'])
        self.assertEqual(cs[0]['problems'], [])
        self.assertEqual(judge.case_criteria(tmp, 'nothing'), [])
        judge.check_criteria(tmp, ['c'])
        write(tmp / 'c' / 'judge' / 'y.md', '---\nclause: C001\n---\n正文\n')
        self.assertEqual(judge.case_criteria(tmp, 'c')[1]['clause'], 'C001')
        write(tmp / 'd' / 'judge' / 'z.md', '---\nrules: g1\narms: [current, nobody]\nclause: 第一条\n---\n正文\n')
        with self.assertRaises(judge.JudgeConfigError) as cm:
            judge.check_criteria(tmp, ['c', 'd'])
        msg = str(cm.exception)
        for needle in ('不认识的键 rules', '不认识的臂名 nobody', 'clause 应是一个条款 id'):
            self.assertIn(needle, msg)

    def test_report_without_judge_mentions_no_criteria(self):
        import test_record
        text = record.render_report(test_record.build())
        self.assertIn('## AI 评委判分', text)
        self.assertNotIn('AI 判分不采信', text)


class RegistrationTest(unittest.TestCase):
    def test_types_registered_with_agreed_priorities(self):
        reg = pending._REGISTRY
        self.assertIs(reg.get('judge-disagreement'), judgepending.DISAGREEMENT)
        self.assertIs(reg.get('judge-spot-check'), judgepending.SPOT_CHECK)
        self.assertLess(judgepending.DISAGREEMENT.priority, judgepending.SPOT_CHECK.priority)
        self.assertFalse(judgepending.DISAGREEMENT.always)


if __name__ == '__main__':
    unittest.main()
