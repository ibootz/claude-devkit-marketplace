"""接缝：不完整运行（撞订阅用量限制、中途退出）与断点续跑；闸门对不完整记录的排除。"""
import io
import json
import os
import shutil
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import _support
from _support import tmpdir, aggregate, grader, make_plugin, make_sandbox, run_result
from plugin_eval_lib import cli, compare, completeness, pending, registry, resume
from test_compare import passing_preflight

GRADERS = [grader('rule')]
LIMIT_ERROR = 'API Error: Claude AI usage limit reached|1760000000'


class ScriptedEval:
    """按臂、用例逐次出结果的假 eval。

    outcomes: {(臂, 用例): [rule 是否通过, ...]}，每跑一个 run 从队首取一个（撞限的 run 也消耗一个）。
    fail: {(臂, 用例, 本次调用内的 run 序号): error 文本}，每条只生效一次。
    no_aggregate: 臂名集合，该臂下一次调用不写汇总、退出码 2，只生效一次。
    crash_on: 臂名，跑到该臂时抛异常（模拟进程中途退出）。
    """

    def __init__(self, sandbox_root, outcomes, fail=None, no_aggregate=(), crash_on=None):
        self.sandbox_root = Path(sandbox_root)
        self.outcomes = {k: list(v) for k, v in outcomes.items()}
        self.fail = dict(fail or {})
        self.no_aggregate = set(no_aggregate)
        self.crash_on = crash_on
        self.calls = []
        self.seq = 0

    def __call__(self, cmd, cwd, env, log_dir):
        arm_dir = Path(cmd[3])
        arm = arm_dir.name
        runs = int(cmd[cmd.index('--runs') + 1])
        names = sorted(p.name for p in (arm_dir / 'evals').iterdir() if p.is_dir() and p.name != 'mocks')
        self.calls.append({'arm': arm, 'runs': runs, 'cases': names})
        if self.crash_on == arm:
            self.crash_on = None
            raise RuntimeError('模拟进程中途退出')
        (Path(log_dir) / 'eval.stderr').write_text('', encoding='utf-8')
        if arm in self.no_aggregate:
            self.no_aggregate.discard(arm)
            return 2, ''
        out = Path(cmd[cmd.index('--output-dir') + 1])
        out.mkdir(parents=True, exist_ok=True)
        cases = []
        for n in names:
            rs = []
            for i in range(runs):
                self.seq += 1
                sb = make_sandbox(self.sandbox_root, 's%d' % self.seq)
                ok = self.outcomes[(arm, n)].pop(0)
                err = self.fail.pop((arm, n, i), None)
                rs.append(run_result({'rule': ok}, error=err, trace_path=str(sb / 'out' / 'trace.jsonl')))
            cases.append((n, GRADERS, rs))
        (out / 'aggregate-result.json').write_text(json.dumps(aggregate(cases, root=str(arm_dir))), encoding='utf-8')
        return 0, ''


class ResumeTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.data = self.tmp / 'data'
        self.repo = self.tmp / 'repo'
        self.plugin = make_plugin(self.repo / 'plugins' / 'demo-plugin', cases=('case-a', 'case-b'))
        self.sandboxes = self.tmp / 'sandboxes'
        self.sandboxes.mkdir()
        self.assembly_parent = self.tmp / 'assembly'
        self.assembly_parent.mkdir()
        registry.register(self.data, 'demo-plugin', self.repo)

    def kw(self):
        return dict(claude='/fake/claude', env={'PATH': '/usr/bin'}, tmp_parent=self.assembly_parent,
                    sandbox_roots=[self.sandboxes], log=lambda *a: None, preflight_check=passing_preflight)

    def compare(self, fake, runs=3):
        # 同一用例里可能连跑两次对照：每次给不同的开跑时刻，运行目录名才不撞
        self.minute = getattr(self, 'minute', 0) + 1
        started = datetime(2026, 10, 15, 8, self.minute, tzinfo=timezone.utc)
        return compare.run_compare(self.data, 'demo-plugin', runs=runs, concurrency=2, runner=fake,
                                   now=lambda: started, **self.kw())

    def resume(self, fake, run_dir):
        return resume.resume_run(self.data, run_dir, runner=fake, **self.kw())

    @staticmethod
    def load(run_dir):
        return json.loads((Path(run_dir) / 'run.json').read_text(encoding='utf-8'))


# 一次跑完与「撞限 + 续跑」共用的逐次结果。撞限那次（current/case-a 第 2 个 run）在续跑里补一个 run，
# 补跑取到的是队列里第 4 个值 False，与一次跑完时第 2 个 run 的值相同，所以两种跑法的有效 run 多重集合相同。
ONE_SHOT = {('none', 'case-a'): [False, True, False], ('none', 'case-b'): [True, True, True],
            ('current', 'case-a'): [True, False, True], ('current', 'case-b'): [True, True, False]}
FLAKY = {('none', 'case-a'): [False, True, False], ('none', 'case-b'): [True, True, True],
         ('current', 'case-a'): [True, True, True, False], ('current', 'case-b'): [True, True, False]}


class UsageLimitTest(ResumeTestBase):
    def test_usage_limit_run_invalid_and_run_incomplete(self):
        fake = ScriptedEval(self.sandboxes, FLAKY, fail={('current', 'case-a', 1): LIMIT_ERROR})
        res = self.compare(fake)
        rec = self.load(res.run_dir)
        self.assertEqual(res.exit_code, 3)
        self.assertFalse(rec['complete'])
        self.assertFalse(rec['passed'])
        cur_a = rec['arms']['current']['cases']['case-a']
        self.assertEqual(cur_a['valid_runs'], 2)        # 撞限的 run 不进分数
        self.assertEqual(cur_a['score'], 1.0)
        self.assertEqual(rec['arms']['current']['invalid_run_count'], 1)
        self.assertTrue(any('用量限制' in r for r in rec['incomplete_reasons']), rec['incomplete_reasons'])
        report = (res.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn('resume', report)
        self.assertIsNotNone(completeness.gate_exclusion_reason(rec))

    def test_resume_reruns_only_missing_runs_and_matches_one_shot(self):
        one = self.compare(ScriptedEval(self.sandboxes, ONE_SHOT))
        one_rec = self.load(one.run_dir)

        fake = ScriptedEval(self.sandboxes, FLAKY, fail={('current', 'case-a', 1): LIMIT_ERROR})
        first = self.compare(fake)
        self.assertEqual(len(fake.calls), 2)
        res = self.resume(fake, first.run_dir)

        self.assertEqual(fake.calls[2:], [{'arm': 'current', 'runs': 1, 'cases': ['case-a']}])
        self.assertEqual(res.exit_code, 0)
        self.assertEqual(res.run_dir, first.run_dir)
        rec = self.load(first.run_dir)
        self.assertTrue(rec['complete'], rec['incomplete_reasons'])
        self.assertEqual(rec['incomplete_reasons'], [])
        self.assertIsNone(completeness.gate_exclusion_reason(rec))
        for arm in ('none', 'current'):
            self.assertEqual(rec['arms'][arm]['score'], one_rec['arms'][arm]['score'], arm)
            self.assertEqual(rec['arms'][arm]['invalid_run_count'], 0)
            for case in ('case-a', 'case-b'):
                got, want = rec['arms'][arm]['cases'][case], one_rec['arms'][arm]['cases'][case]
                self.assertAlmostEqual(got['score'], want['score'])
                self.assertEqual(sorted(got['run_scores']), sorted(want['run_scores']))
        self.assertEqual(rec['delta']['overall'], one_rec['delta']['overall'])
        self.assertEqual(rec['passed'], one_rec['passed'])
        self.assertEqual(rec['run_id'], first.run_dir.name)

        attempts = rec['resume']['attempts']
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]['reran'], {'current': {'case-a': 1}})
        self.assertEqual([(r['arm'], r['case'], r['error_kind']) for r in attempts[0]['replaced_invalid_runs']],
                         [('current', 'case-a', 'usage_limit')])
        # 合并后的汇总只留有效 run：3 个
        agg = json.loads((first.run_dir / 'arms' / 'current' / 'aggregate-result.json').read_text(encoding='utf-8'))
        case_a = [c for c in agg['cases'] if c['dir'] == 'evals/case-a'][0]
        self.assertEqual(len(case_a['arms']['with']), 3)
        self.assertTrue(all(r['error'] is None for r in case_a['arms']['with']))
        # 续跑的 trace 放在单独的子目录，不覆盖首跑的
        self.assertTrue((self.data / 'traces' / first.run_dir.name / 'resume-1' / 'current').is_dir())
        self.assertEqual(list(self.sandboxes.iterdir()), [])
        self.assertEqual(list(self.assembly_parent.iterdir()), [])
        report = (first.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn('续跑记录', report)
        self.assertIn('补跑 当前版臂 case-a × 1', report)
        self.assertNotIn('## 续跑\n', report)   # 已完整：不再给续跑办法

    def test_still_limited_on_resume_stays_incomplete_then_second_resume_completes(self):
        fake = ScriptedEval(self.sandboxes, {**FLAKY, ('current', 'case-a'): [True, True, True, True, False]},
                            fail={('current', 'case-a', 1): LIMIT_ERROR})
        first = self.compare(fake)
        fake.fail[('current', 'case-a', 0)] = LIMIT_ERROR
        r1 = self.resume(fake, first.run_dir)
        self.assertEqual(r1.exit_code, 3)
        self.assertFalse(self.load(first.run_dir)['complete'])
        r2 = self.resume(fake, first.run_dir)
        rec = self.load(first.run_dir)
        self.assertEqual(r2.exit_code, 0)
        self.assertTrue(rec['complete'])
        self.assertEqual(len(rec['resume']['attempts']), 2)
        self.assertEqual(rec['arms']['current']['cases']['case-a']['valid_runs'], 3)

    def test_runs_missing_in_different_counts_grouped_by_count(self):
        fake = ScriptedEval(self.sandboxes, {**FLAKY, ('current', 'case-a'): [True] * 5,
                                             ('current', 'case-b'): [True] * 5},
                            fail={('current', 'case-a', 0): LIMIT_ERROR, ('current', 'case-a', 2): LIMIT_ERROR,
                                  ('current', 'case-b', 1): LIMIT_ERROR})
        first = self.compare(fake)
        self.resume(fake, first.run_dir)
        reruns = sorted((c['runs'], c['cases']) for c in fake.calls[2:])
        self.assertEqual(reruns, [(1, ['case-b']), (2, ['case-a'])])
        self.assertTrue(self.load(first.run_dir)['complete'])

    def test_resume_complete_run_is_noop(self):
        fake = ScriptedEval(self.sandboxes, ONE_SHOT)
        first = self.compare(fake)
        res = self.resume(fake, first.run_dir)
        self.assertEqual(res.exit_code, 0)
        self.assertEqual(len(fake.calls), 2)

    def test_resume_refuses_when_plugin_content_changed(self):
        fake = ScriptedEval(self.sandboxes, FLAKY, fail={('current', 'case-a', 1): LIMIT_ERROR})
        first = self.compare(fake)
        (self.plugin / 'hooks' / 'inject.js').write_text('changed', encoding='utf-8')
        with self.assertRaises(resume.ResumeError) as cm:
            self.resume(fake, first.run_dir)
        self.assertIn('指纹', str(cm.exception))
        self.assertEqual(len(fake.calls), 2)

    def test_adding_case_after_first_run_does_not_widen_resume(self):
        fake = ScriptedEval(self.sandboxes, FLAKY, fail={('current', 'case-a', 1): LIMIT_ERROR})
        first = self.compare(fake)
        _support.write(self.plugin / 'evals' / 'case-new' / 'prompt.md', '---\nname: case-new\n---\nx\n')
        self.resume(fake, first.run_dir)
        self.assertEqual(fake.calls[2]['cases'], ['case-a'])
        self.assertEqual(self.load(first.run_dir)['cases'], ['case-a', 'case-b'])


class InterruptedRunTest(ResumeTestBase):
    def test_crash_midway_leaves_incomplete_run_json_and_resume_runs_missing_arm(self):
        fake = ScriptedEval(self.sandboxes, ONE_SHOT, crash_on='current')
        with self.assertRaises(RuntimeError):
            self.compare(fake)
        run_dirs = list((self.repo / 'plugin-evals' / 'demo-plugin' / 'runs').iterdir())
        self.assertEqual(len(run_dirs), 1)
        rec = self.load(run_dirs[0])
        self.assertFalse(rec['complete'])
        self.assertTrue(rec['incomplete_reasons'])
        self.assertIsNotNone(rec['arms']['none'])
        self.assertIsNone(rec['arms']['current'])
        self.assertIsNotNone(completeness.gate_exclusion_reason(rec))
        self.assertEqual(list(self.assembly_parent.iterdir()), [])

        res = self.resume(fake, run_dirs[0])
        self.assertEqual(fake.calls[2:], [{'arm': 'current', 'runs': 3, 'cases': ['case-a', 'case-b']}])
        self.assertEqual(res.exit_code, 0)
        rec = self.load(run_dirs[0])
        self.assertTrue(rec['complete'])
        self.assertAlmostEqual(rec['arms']['none']['score'], 2 / 3)

    def test_arm_without_aggregate_rerun_whole(self):
        fake = ScriptedEval(self.sandboxes, {k: v * 2 for k, v in ONE_SHOT.items()}, no_aggregate={'current'})
        first = self.compare(fake)
        self.assertFalse(self.load(first.run_dir)['complete'])
        self.resume(fake, first.run_dir)
        self.assertEqual(fake.calls[2:], [{'arm': 'current', 'runs': 3, 'cases': ['case-a', 'case-b']}])
        rec = self.load(first.run_dir)
        self.assertTrue(rec['complete'], rec['incomplete_reasons'])
        self.assertEqual(rec['arms']['current']['eval_exit_code'], 0)

    def test_resume_refused_while_run_locked_by_live_process(self):
        fake = ScriptedEval(self.sandboxes, FLAKY, fail={('current', 'case-a', 1): LIMIT_ERROR})
        first = self.compare(fake)
        lock = resume.RunLock(self.data, first.run_dir.name)
        lock.acquire()
        self.addCleanup(lock.release)
        with self.assertRaises(resume.ResumeError) as cm:
            self.resume(fake, first.run_dir)
        self.assertIn('正在', str(cm.exception))

    def test_stale_lock_of_dead_process_is_taken_over(self):
        fake = ScriptedEval(self.sandboxes, FLAKY, fail={('current', 'case-a', 1): LIMIT_ERROR})
        first = self.compare(fake)
        lock_path = resume.RunLock(self.data, first.run_dir.name).path
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(json.dumps({'pid': 2 ** 22 + 12345}), encoding='utf-8')
        self.assertEqual(self.resume(fake, first.run_dir).exit_code, 0)
        self.assertFalse(resume.RunLock(self.data, first.run_dir.name).busy())   # 锁随进程释放，文件留着无妨

    def test_lock_with_empty_file_still_held(self):
        """票 07 B1：持有者刚建好锁文件、还没写 pid 时，别的进程不能把它当死锁接管。"""
        a = resume.RunLock(self.data, 'r1').acquire()
        self.addCleanup(a.release)
        a.path.write_text('', encoding='utf-8')
        b = resume.RunLock(self.data, 'r1')
        self.assertTrue(b.busy())
        with self.assertRaises(resume.ResumeError):
            b.acquire()
        a.release()
        self.assertFalse(b.busy())
        b.acquire()
        b.release()

    def test_lock_released_when_holder_process_killed(self):
        """票 07 B1：锁由操作系统持有，持有进程被 kill -9 也自动释放，不靠判断 pid 存活。"""
        import signal
        import subprocess
        import sys
        import time
        ready = self.tmp / 'ready'
        code = ("import sys, time; sys.path.insert(0, %r)\n"
                "from plugin_eval_lib import resume\n"
                "l = resume.RunLock(%r, 'r2').acquire(); open(%r, 'w').write('1'); time.sleep(120)\n"
                % (str(Path(resume.__file__).resolve().parents[1]), str(self.data), str(ready)))
        proc = subprocess.Popen([sys.executable, '-c', code], env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        deadline = time.monotonic() + 20
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        lock = resume.RunLock(self.data, 'r2')
        self.assertTrue(lock.busy())
        with self.assertRaises(resume.ResumeError) as cm:
            lock.acquire()
        self.assertIn(str(proc.pid), str(cm.exception))
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
        self.assertFalse(lock.busy())
        lock.acquire()
        lock.release()

    def test_resume_refused_when_evals_changed(self):
        """票 07 B2：首跑之后改过用例或 grader，续跑拒绝（补跑按新判据、首跑按旧判据会静默错分）。"""
        fake = ScriptedEval(self.sandboxes, FLAKY, fail={('current', 'case-a', 1): LIMIT_ERROR})
        first = self.compare(fake)
        self.assertTrue(self.load(first.run_dir)['plugin']['evals_fingerprint']['cases']['case-a'].startswith('sha256:'))
        (self.plugin / 'evals' / 'results').mkdir(exist_ok=True)
        (self.plugin / 'evals' / 'results' / 'x.json').write_text('{}', encoding='utf-8')   # results/ 不算改用例
        prompt = self.plugin / 'evals' / 'case-a' / 'prompt.md'
        prompt.write_text(prompt.read_text(encoding='utf-8') + '多一句\n', encoding='utf-8')
        with self.assertRaises(resume.ResumeError) as cm:
            self.resume(fake, first.run_dir)
        self.assertIn('用例 case-a', str(cm.exception))

    def test_corrupt_run_json_is_resume_error(self):
        """票 07 C4：坏的 run.json 给可读的报错，不抛 traceback。"""
        fake = ScriptedEval(self.sandboxes, FLAKY, fail={('current', 'case-a', 1): LIMIT_ERROR})
        first = self.compare(fake)
        (first.run_dir / 'run.json').write_text('{"kind": "compare", ', encoding='utf-8')
        with self.assertRaises(resume.ResumeError) as cm:
            self.resume(fake, first.run_dir)
        self.assertIn('不是合法 JSON', str(cm.exception))
        (first.run_dir / 'run.json').write_text('{"kind": "compare", "complete": false}', encoding='utf-8')
        with self.assertRaises(resume.ResumeError) as cm:
            self.resume(fake, first.run_dir)
        self.assertIn('缺少续跑必需的字段', str(cm.exception))


class CliResumeTest(ResumeTestBase):
    def test_cli_resume_exit_codes(self):
        fake = ScriptedEval(self.sandboxes, FLAKY, fail={('current', 'case-a', 1): LIMIT_ERROR})
        first = self.compare(fake)
        out, err = io.StringIO(), io.StringIO()
        orig = resume.resume_run
        resume.resume_run = lambda data_dir, run_dir, **kw: orig(data_dir, run_dir, runner=fake, **self.kw())
        self.addCleanup(setattr, resume, 'resume_run', orig)
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(['--data-dir', str(self.data), 'resume', str(first.run_dir)])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn('完整：是', out.getvalue())

    def test_cli_resume_missing_run_json_exits_2(self):
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = cli.main(['--data-dir', str(self.data), 'resume', str(self.tmp / 'nowhere')])
        self.assertEqual(code, 2)
        self.assertIn('run.json', err.getvalue())


class PendingWithResumeTest(ResumeTestBase):
    """票 07 × 票 08：待审页与对照、续跑互斥；未结束的运行不出页；续跑后旧页作废、重新生成。"""

    def test_default_run_skips_unfinished_and_locked_runs(self):
        done = self.compare(ScriptedEval(self.sandboxes, ONE_SHOT))
        crash = ScriptedEval(self.sandboxes, ONE_SHOT, crash_on='current')
        with self.assertRaises(RuntimeError):
            self.compare(crash)                                    # 较新的运行停在检查点
        page = pending.generate(self.data, 'demo-plugin')
        self.assertEqual(page.run_id, done.run_dir.name)

        newest = self.compare(ScriptedEval(self.sandboxes, ONE_SHOT))
        lock = resume.RunLock(self.data, newest.run_dir.name).acquire()   # 模拟它正被续跑
        self.addCleanup(lock.release)
        self.assertEqual(pending.generate(self.data, 'demo-plugin').run_id, done.run_dir.name)
        with self.assertRaises(pending.PendingError) as cm:
            pending.generate(self.data, 'demo-plugin', run_id=newest.run_dir.name)
        self.assertIn('正在对照或续跑', str(cm.exception))

    def test_explicit_checkpoint_run_has_nothing_to_review(self):
        crash = ScriptedEval(self.sandboxes, ONE_SHOT, crash_on='current')
        with self.assertRaises(RuntimeError):
            self.compare(crash)
        run_dir = next((self.repo / 'plugin-evals' / 'demo-plugin' / 'runs').iterdir())
        with self.assertRaises(pending.NothingPending) as cm:
            pending.generate(self.data, 'demo-plugin', run_id=run_dir.name)
        self.assertIn('还没结束', str(cm.exception))

    def test_resume_supersedes_old_page_and_regenerates(self):
        fake = ScriptedEval(self.sandboxes, FLAKY, fail={('current', 'case-a', 1): LIMIT_ERROR})
        first = self.compare(fake)
        old_page = pending.generate(self.data, 'demo-plugin', run_id=first.run_dir.name)
        res = self.resume(fake, first.run_dir)
        rec = self.load(first.run_dir)
        self.assertTrue(rec['complete'])
        self.assertEqual(res.record['pending']['page_id'], rec['pending']['page_id'])
        self.assertNotIn(rec['pending']['page_id'], (None, old_page.page_id))
        self.assertEqual(rec['review']['status'], '待审')
        old_code = 'PE1 %s %s 1A' % (old_page.run_id, old_page.page_id)
        with self.assertRaises(pending.ReplyError):
            pending.apply_reply(self.data, 'demo-plugin', old_code)
        new_code = 'PE1 %s %s 1A' % (old_page.run_id, rec['pending']['page_id'])
        pending.apply_reply(self.data, 'demo-plugin', new_code)
        self.assertEqual(self.load(first.run_dir)['review']['status'], '已审')


class CompletenessTest(unittest.TestCase):
    def test_classify_usage_limit_errors(self):
        for text in (LIMIT_ERROR, "You've hit your limit · resets 3pm", 'API Error: 429 {"type":"rate_limit_error"}',
                     'Rate limit exceeded', 'you have reached your weekly usage limit'):
            self.assertEqual(completeness.classify_run_error(text), 'usage_limit', text)
        for text in ('Context limit reached', 'claude exited with code 1', '', None):
            self.assertEqual(completeness.classify_run_error(text), 'other', text)

    def test_gate_excludes_incomplete_or_unknown_completeness(self):
        self.assertIsNone(completeness.gate_exclusion_reason({'kind': 'compare', 'complete': True}))
        self.assertIn('不完整', completeness.gate_exclusion_reason(
            {'kind': 'compare', 'complete': False, 'incomplete_reasons': ['当前版臂：1 个 run 出错']}))
        self.assertIsNotNone(completeness.gate_exclusion_reason({'kind': 'compare'}))
        self.assertIsNotNone(completeness.gate_exclusion_reason({'kind': 'compare', 'complete': 'yes'}))
        self.assertIsNotNone(completeness.gate_exclusion_reason(None))


if __name__ == '__main__':
    unittest.main()
