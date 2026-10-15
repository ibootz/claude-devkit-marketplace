"""接缝：compare 编排接上注入到达核验与常驻 token（假的 eval 运行器写子会话转录，不调模型）。"""
import json
import os
import unittest
import uuid
from pathlib import Path

import _support
from _support import tmpdir, aggregate, grader, run_result, trace_lines, write
from plugin_eval_lib import compare, registry
from test_compare import passing_preflight
from test_injection import HOOK_SRC, hook_cmd, make_hook_plugin, std_hooks

UPS_CMD = hook_cmd('inj.py')


def _att(a):
    return json.dumps({'type': 'attachment', 'uuid': str(uuid.uuid4()), 'attachment': a}, ensure_ascii=False)


class TranscriptEval:
    """按臂造 --keep-temp 沙箱：当前版臂的转录里有 SessionStart / UserPromptSubmit 注入；
    break_ups 为真时 UserPromptSubmit 那条改记为 hook 非零退出（注入丢失）。不装臂没有任何 hook 记录。"""

    def __init__(self, sandbox_root, break_ups=False):
        self.sandbox_root = Path(sandbox_root)
        self.break_ups = break_ups

    def _sandbox(self, label, arm):
        sb = self.sandbox_root / ('e-' + label)
        write(sb / 'out' / 'trace.jsonl', trace_lines())
        lines = [json.dumps({'type': 'user'})]
        if arm == 'current':
            lines.append(_att({'type': 'hook_additional_context', 'hookEvent': 'SessionStart', 'hookName': 'SessionStart',
                               'content': ['# 会话级纪律\n\n第一条：先读再写。'], 'toolUseID': 't'}))
            if self.break_ups:
                lines.append(_att({'type': 'hook_non_blocking_error', 'hookEvent': 'UserPromptSubmit',
                                   'hookName': 'UserPromptSubmit', 'command': UPS_CMD, 'exitCode': 3,
                                   'stdout': '', 'stderr': 'Failed', 'durationMs': 3, 'toolUseID': 't'}))
            else:
                lines.append(_att({'type': 'hook_additional_context', 'hookEvent': 'UserPromptSubmit',
                                   'hookName': 'UserPromptSubmit', 'content': ['# 每轮要点 abc\n\nkeep going'],
                                   'toolUseID': 't'}))
        write(sb / 'config' / 'projects' / '-tmp-cwd' / 'sid.jsonl', '\n'.join(lines) + '\n')
        return sb

    def __call__(self, cmd, cwd, env, log_dir):
        arm_dir = Path(cmd[3])
        arm = arm_dir.name
        out = Path(cmd[cmd.index('--output-dir') + 1])
        out.mkdir(parents=True, exist_ok=True)
        runs_n = int(cmd[cmd.index('--runs') + 1])
        cases = []
        for n in sorted(p.name for p in (arm_dir / 'evals').iterdir() if p.is_dir()):
            runs = [run_result({'rule': arm == 'current'},
                               trace_path=str(self._sandbox('%s-%s-%d' % (arm, n, i), arm) / 'out' / 'trace.jsonl'))
                    for i in range(runs_n)]
            cases.append((n, [grader('rule')], runs))
        (out / 'aggregate-result.json').write_text(json.dumps(aggregate(cases, root=str(arm_dir))), encoding='utf-8')
        (Path(log_dir) / 'eval.stderr').write_text('', encoding='utf-8')
        return 1, ''


class CompareInjectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.data = self.tmp / 'data'
        self.repo = self.tmp / 'repo'
        self.plugin = make_hook_plugin(self.repo / 'plugins' / 'inj-plugin', std_hooks(), name='inj-plugin')
        write(self.plugin / 'evals' / 'case-a' / 'prompt.md', '---\nname: case-a\n---\n做点事\n')
        self.sandboxes = self.tmp / 'sandboxes'
        self.sandboxes.mkdir()
        registry.register(self.data, 'inj-plugin', self.repo)

    def run_compare(self, fake):
        assembly = self.tmp / 'assembly'
        assembly.mkdir(exist_ok=True)
        return compare.run_compare(self.data, 'inj-plugin', runs=2, concurrency=1, claude='/fake/claude', runner=fake,
                                   env=dict(os.environ), tmp_parent=assembly, sandbox_roots=[self.sandboxes],
                                   log=lambda *a: None, preflight_check=passing_preflight)

    def test_arrived_check_written_and_resident_tokens_in_record_and_report(self):
        res = self.run_compare(TranscriptEval(self.sandboxes))
        check = json.loads((res.run_dir / 'injection-check.json').read_text(encoding='utf-8'))
        self.assertTrue(check['ok'], check['problems'])
        cur, none = check['arms']['current'], check['arms']['none']
        self.assertEqual((cur['runs_total'], cur['runs_arrived']), (2, 2))
        self.assertEqual([r['events'] for r in cur['runs']], [{'SessionStart': 1, 'UserPromptSubmit': 1}] * 2)
        self.assertEqual([r['events'] for r in none['runs']], [{}, {}])
        self.assertEqual(none['plugin_injections'], 0)

        rec = json.loads((res.run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertTrue(rec['injection_check']['ok'])
        self.assertEqual(rec['injection_check']['file'], 'injection-check.json')
        rt = rec['resident_tokens']['arms']['current']
        self.assertGreater(rt['by_event']['SessionStart']['tokens_est'], 0)
        self.assertEqual(set(rt['by_event']), {'SessionStart', 'UserPromptSubmit', 'SubagentStart'})
        self.assertTrue(res.record['complete'])

        report = (res.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertNotIn('注入未到达', report)
        self.assertIn('## 注入到达核验', report)
        self.assertIn('## 常驻 token（静态估算）', report)

    def test_broken_hook_flagged_in_report_first_section(self):
        res = self.run_compare(TranscriptEval(self.sandboxes, break_ups=True))
        check = json.loads((res.run_dir / 'injection-check.json').read_text(encoding='utf-8'))
        self.assertFalse(check['ok'])
        cur = check['arms']['current']
        self.assertEqual(cur['runs_not_arrived'], 2)
        verdict = cur['runs'][0]['hooks']['UserPromptSubmit||' + UPS_CMD]
        self.assertEqual((verdict['verdict'], verdict['exit_codes']), ('failed', [3]))

        report = (res.run_dir / 'report.md').read_text(encoding='utf-8')
        first_section = report.split('\n## ')[0]                # 首段：第一个二级标题之前
        self.assertIn('注入未到达', first_section)
        self.assertIn('当前版臂：2/2 个 run 有注入未到达', first_section)
        self.assertIn('退出码 3', first_section)
        # 不计分：不改变完整性与分数
        self.assertTrue(res.record['complete'])
        self.assertEqual(res.record['arms']['current']['score'], 1.0)


if __name__ == '__main__':
    unittest.main()
