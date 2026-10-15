"""接缝：从 trace 汇总 token / 模型；把 --keep-temp 沙箱搬到用户级 traces/ 并清理。"""
import unittest
from pathlib import Path

import _support
from _support import tmpdir, make_sandbox, write, trace_lines
from plugin_eval_lib import traces


class SummarizeTraceTest(unittest.TestCase):
    def test_first_init_model_and_usage(self):
        p = write(tmpdir(self) / 't.jsonl', trace_lines('claude-opus-5-5'))
        s = traces.summarize_trace(p)
        self.assertEqual(s['main_model'], 'claude-opus-5-5')
        self.assertEqual(s['usage']['claude-opus-5-5']['input_tokens'], 10)
        self.assertEqual(s['usage']['claude-opus-5-5']['cost_usd'], 0.5)

    def test_multiple_result_lines_take_last_snapshot(self):
        # 2.1.300 实测：派后台子代理时 trace 有多条 result，每条都是累计值，不能相加
        import json
        lines = [{'type': 'system', 'subtype': 'init', 'model': 'm'}]
        for cost in (0.1, 0.1, 0.3):
            lines.append({'type': 'result', 'modelUsage': {'m': {'inputTokens': 1, 'costUSD': cost}}})
        p = write(tmpdir(self) / 't.jsonl', '\n'.join(json.dumps(x) for x in lines) + '\n')
        u = traces.summarize_trace(p)['usage']['m']
        self.assertEqual(u['cost_usd'], 0.3)
        self.assertEqual(u['input_tokens'], 1)

    def test_missing_or_broken_trace(self):
        tmp = tmpdir(self)
        self.assertEqual(traces.summarize_trace(tmp / 'nope.jsonl'), {'main_model': None, 'usage': {}})
        p = write(tmp / 'bad.jsonl', 'not json\n{"type":"system","subtype":"init","model":"m"}\n')
        self.assertEqual(traces.summarize_trace(p)['main_model'], 'm')

    def test_merge_usage(self):
        a = {'m': {'input_tokens': 1, 'output_tokens': 2, 'cache_read_input_tokens': 3,
                   'cache_creation_input_tokens': 4, 'cost_usd': 0.5}}
        total = traces.merge_usage([a, a, {}])
        self.assertEqual(total['by_model']['m']['input_tokens'], 2)
        self.assertEqual(total['input_tokens'], 2)
        self.assertEqual(total['cache_creation_input_tokens'], 8)
        self.assertAlmostEqual(total['cost_usd'], 1.0)


class HarvestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)

    def test_moves_trace_and_transcripts_then_removes_sandbox(self):
        sb = make_sandbox(self.tmp, 'abc')
        dest = self.tmp / 'traces' / 'run' / 'none' / 'case-1'
        warnings = traces.harvest_sandbox(sb / 'out' / 'trace.jsonl', dest, allowed_roots=[self.tmp])
        self.assertEqual(warnings, [])
        self.assertTrue((dest / 'trace.jsonl').exists())
        self.assertTrue((dest / 'projects' / '-tmp-cwd' / 'sid.jsonl').exists())
        self.assertFalse(sb.exists())

    def test_refuses_dirs_that_do_not_look_like_sandbox(self):
        d = self.tmp / 'precious'
        write(d / 'out' / 'trace.jsonl', trace_lines())
        warnings = traces.harvest_sandbox(d / 'out' / 'trace.jsonl', self.tmp / 'dest', allowed_roots=[self.tmp])
        self.assertTrue(warnings)
        self.assertTrue(d.exists())

    def test_refuses_sandbox_outside_allowed_roots(self):
        other = tmpdir(self)
        sb = make_sandbox(other, 'zzz', readonly=False)
        warnings = traces.harvest_sandbox(sb / 'out' / 'trace.jsonl', self.tmp / 'dest', allowed_roots=[self.tmp])
        self.assertTrue(warnings)
        self.assertTrue(sb.exists())

    def test_missing_trace_path_is_warning(self):
        self.assertTrue(traces.harvest_sandbox(None, self.tmp / 'dest', allowed_roots=[self.tmp]))


if __name__ == '__main__':
    unittest.main()
