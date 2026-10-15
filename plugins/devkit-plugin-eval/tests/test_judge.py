"""AI 评委（票 09）：两遍判分、分歧样本与抽检进待审页、用户裁定存金标、金标校准与不采信、评委模型配置。
评委用假 runner，不调模型；eval 用 test_compare 的 FakeEval。"""
import gzip
import io
import json
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import _support
from _support import tmpdir, write
from plugin_eval_lib import cli, compare, judge, judgepending, pending, record, registry
from test_compare import FakeEval, passing_preflight

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
        # 5 条金标用户都判通过；评委对 CRIT-A 判 fail：CRIT-A 上的金标不一致
        n_a = sum(1 for f in gold_files if 'CRIT-A' in json.loads(f.read_text(encoding='utf-8'))['criterion_text'])
        self.assertEqual(doc2['gold']['agreed'], 5 - n_a)
        self.assertAlmostEqual(doc2['gold']['agreement_rate'], (5 - n_a) / 5)
        self.assertFalse(doc2['gold']['enabled'])
        self.assertTrue(doc2['trusted'])
        self.assertEqual(len(fj2.calls), 16 + 5)

    def test_unclear_verdict_not_saved_as_gold(self):
        self.compare(FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass'))
        self._adjudicate_all('C')
        self.assertFalse((self.evals / 'gold').exists() and list((self.evals / 'gold').glob('*.json')))

    def test_low_agreement_marks_untrusted(self):
        self.compare(FakeJudge(lambda p, n: 'fail' if criterion_says('CRIT-A')(p) else 'pass'))
        self._adjudicate_all('A')
        write(self.evals / 'judge-config.json', json.dumps({'gold_agreement_threshold': 0.9, 'gold_min_samples': 3}))
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
        rec = self.run_json(self.compare(FakeJudge(lambda p, n: 'fail'), minute=5))
        self.assertTrue(rec['judge']['trusted'])
        self.assertFalse(rec['judge']['gold']['enabled'])
        self.assertIn('不足', rec['judge']['gold']['note'])


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
        fj = FakeJudge(lambda p, n: 'pass')
        res = self.compare(fj, use_judge=False)
        self.assertEqual(fj.calls, [])
        self.assertIsNone(self.run_json(res)['judge'])
        self.assertFalse((res.run_dir / 'judge.json').exists())
        self.assertIn('未调 AI 评委', (res.run_dir / 'report.md').read_text(encoding='utf-8'))

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


class PureFunctionTest(unittest.TestCase):
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
            {'type': 'system', 'subtype': 'init', 'cwd': home + '/proj', 'note': 'mail a.b@example.invalid'},
            {'type': 'assistant', 'message': {'content': [{'type': 'thinking', 'thinking': 't', 'signature': 'SIG'}]}},
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
        self.assertFalse(judge.store_sample(tmp / 'missing.jsonl', tmp / 'c.gz'))

    def test_criteria_frontmatter(self):
        tmp = tmpdir(self)
        write(tmp / 'c' / 'judge' / 'x.md', '---\nrule: g1\narms: [current, none]\n---\n标准正文\n')
        write(tmp / 'c' / 'judge' / 'empty.md', '---\nrule: g\n---\n')
        cs = judge.case_criteria(tmp, 'c')
        self.assertEqual([c['id'] for c in cs], ['x'])
        self.assertEqual(cs[0]['rule'], 'g1')
        self.assertEqual(cs[0]['arms'], ['current', 'none'])
        self.assertEqual(judge.case_criteria(tmp, 'nothing'), [])

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
