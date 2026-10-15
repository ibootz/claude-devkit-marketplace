"""票 15：规则判分子集（gaterun）、闸门提示「建议跑对照」与超 7 天复盘提醒。用真 git 造临时仓，假 eval 运行器，不调模型。"""
import io
import json
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from _support import tmpdir, write
from test_compare import FakeEval, passing_preflight
from test_gate import GIT, NAME, Repo, ok_tests

from plugin_eval_lib import (cli, clauses, compare, gate, gatehints, gaterun, judge, pending, preflight, registry,
                             reviewgap, scoring)

HOOK_PY = ('import os, sys\nsys.stdin.read()\n'
           'print(open(os.path.join(os.environ["CLAUDE_PLUGIN_ROOT"], "rules.txt"), encoding="utf-8").read())\n')
SKILL_MD = '---\nname: helper\ndescription: %s\n---\n\n正文\n'
LLM_GRADER = '---\ntype: llm\nprompt: 回答好不好\n---\n'
RULE_GRADER = '---\ntype: regex\ntarget: last_message\npattern: ok\n---\n'


def no_static(specs, env, tmp_parent=None):
    """假 eval 的转录里没有注入：不给静态画像，注入核验按对照臂处理（注入核验本身见 test_injection_check.py）。"""
    return {s.key: None for s in specs}


def boom(*a, **kw):
    raise AssertionError('规则子集不该调到这里')


@unittest.skipUnless(GIT, 'git 不可用')
class Base(unittest.TestCase):
    """仓里一个闸门外的插件：1.0.0 → 1.1.0（minor），带注入 hook、一个 skill、一个 agent、两个用例。"""

    def setUp(self):
        self.tmp = tmpdir(self)
        (self.tmp / 'repo').mkdir()
        self.r = Repo(self.tmp / 'repo')
        p = self.r.plugin
        self.r.set_version('1.0.0')
        write(p / 'rules.txt', '1. 回复一律用简体中文。\n')
        write(p / 'hooks' / 'say.py', HOOK_PY)
        write(p / 'hooks' / 'hooks.json', json.dumps({'hooks': {'SessionStart': [{'matcher': '*', 'hooks': [
            {'type': 'command', 'command': '"%s" "${CLAUDE_PLUGIN_ROOT}/hooks/say.py"' % sys.executable}]}]}}))
        write(p / 'skills' / 'helper' / 'SKILL.md', SKILL_MD % '帮你做事。用户说「帮忙」时使用')
        write(p / 'agents' / 'worker.md', '---\nname: worker\ndescription: 干活\n---\n你是干活的。\n')
        write(p / 'evals' / 'case-a' / 'prompt.md', '---\nname: case-a\n---\n做点事\n')
        write(p / 'evals' / 'case-a' / 'graders' / 'g1.md', RULE_GRADER)
        write(p / 'evals' / 'case-b' / 'prompt.md', '---\nname: case-b\n---\n写段话\n')
        write(p / 'evals' / 'case-b' / 'graders' / 'quality.md', LLM_GRADER)
        self.r.commit('初版')
        self.r.set_version('1.1.0')
        self.r.commit('升 1.1.0')
        self.data = self.tmp / 'data'
        self.sandboxes = self.tmp / 'sandboxes'
        self.sandboxes.mkdir()
        self.asm = self.tmp / 'asm'
        self.asm.mkdir()
        self.now = datetime(2026, 10, 15, 4, 0, tzinfo=timezone.utc)

    def subset(self, fake=None, real_static=False, **kw):
        if not (self.data / 'registry.json').exists():
            registry.register(self.data, NAME, self.r.root)
        fake = fake or FakeEval(self.sandboxes, {'current': True})
        self.fake = fake
        kw.setdefault('preflight_check', passing_preflight)
        if real_static:
            return self._subset(fake, **kw)
        with mock.patch.object(compare, 'static_profiles', no_static):
            return self._subset(fake, **kw)

    def _subset(self, fake, **kw):
        return gaterun.run_subset(self.data, NAME, runs=2, concurrency=1, claude='/fake/claude', runner=fake,
                                  env={'PATH': '/usr/bin'}, tmp_parent=self.asm, sandbox_roots=[self.sandboxes],
                                  log=lambda *a: None, **kw)

    def gate(self, **kw):
        kw.setdefault('unit_runner', ok_tests)
        kw.setdefault('now', self.now)
        return gate.evaluate(self.r.plugin, **kw)

    def suggestion_lines(self, res):
        return [n for n in res.data['notes'] if gatehints.SUGGESTION in n]


# ---------------- 规则子集 ----------------

class RuleSubsetRunTest(Base):
    def test_gate_kind_record_one_arm_rule_cases_only(self):
        with mock.patch.object(judge, 'run', boom), mock.patch.object(clauses, 'check_for_run', boom):
            res = self.subset()
        self.assertEqual(res.exit_code, 0)
        self.assertRegex(res.run_dir.name, r'^\d{8}T\d{6}Z-1\.1\.0-gate$')
        rec = json.loads((res.run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual(rec['kind'], 'gate')
        for k in ('version', 'fingerprint'):
            self.assertIn(k, rec['plugin'])
        self.assertEqual(rec['plugin']['fingerprint'], self.r.fp())
        self.assertTrue(rec['complete'])
        self.assertTrue(rec['passed'])
        self.assertEqual(rec['claude_code_versions'], ['2.1.300'])
        self.assertIs(rec['preflight']['dirty'], False)
        self.assertIsNone(rec['review'])
        self.assertEqual(rec['judge'], {'skipped': gaterun.JUDGE_SKIPPED})
        self.assertIsNone(rec['arms']['none'])
        self.assertIsNone(rec['delta'])
        self.assertEqual(rec['cases'], ['case-a'])
        self.assertIn('case-b', rec['rule_subset']['excluded_cases'])
        # 只跑一臂、只装了 case-a；with-only 的 marker grader 照计分
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(Path(self.fake.calls[0]['cmd'][3]).name, 'current')
        self.assertEqual(rec['arms']['current']['cases']['case-a']['excluded_graders'], {})
        self.assertTrue(rec['injection_check']['ok'], rec['injection_check'])
        self.assertTrue((res.run_dir / 'report.md').read_text(encoding='utf-8').startswith('# 规则判分子集'))
        self.assertFalse((res.run_dir / 'judge.json').exists())
        self.assertFalse((res.run_dir / 'clause-check.json').exists())
        self.assertEqual(list(self.asm.iterdir()), [])

    def test_injection_not_arrived_rejected_by_gate(self):
        res = self.subset(real_static=True)      # 假转录里没有注入：核验判未到达
        self.assertFalse(res.record['injection_check']['ok'])
        g = self.gate()
        self.assertFalse(g.passed)
        self.assertIn('injection_check.ok=false', g.data['rejected_same_version'][0]['reasons'][-1])

    def test_no_pending_page(self):
        res = self.subset()
        with self.assertRaises(pending.NothingPending):
            pending.generate(self.data, NAME)
        with self.assertRaises(pending.NothingPending):
            pending.generate(self.data, NAME, run_id=res.run_dir.name)
        self.assertFalse((self.data / 'pending').exists())

    def test_failing_rule_not_passed(self):
        res = self.subset(FakeEval(self.sandboxes, {'current': False}))
        self.assertTrue(res.record['complete'])
        self.assertFalse(res.record['passed'])

    def test_preflight_hard_failure_aborts_before_run_dir(self):
        def failing(**kw):
            rep = preflight.Report('compare')
            rep.add(preflight.Item('logged_in', '已登录', preflight.HARD, preflight.FAIL, '未登录'))
            return rep
        with self.assertRaises(preflight.PreflightFailed):
            self.subset(preflight_check=failing)
        self.assertFalse((self.r.root / 'plugin-evals' / NAME / 'runs').exists())

    def test_real_preflight_called_with_subset_env(self):
        seen = {}

        def spy(**kw):
            seen.update(kw)
            return preflight.Report('compare')
        self.subset(preflight_check=spy)
        self.assertEqual(seen['name'], NAME)
        self.assertNotIn('others', seen)     # 不建臂计划：没有上一版快照、环境插件要冒烟

    def test_no_rule_case_is_error(self):
        shutil.rmtree(self.r.plugin / 'evals' / 'case-a')
        with self.assertRaises(gaterun.GateRunError):
            self.subset()

    def test_plugin_dir_must_match_registry(self):
        with self.assertRaises(gaterun.GateRunError):
            self.subset(plugin_dir=self.tmp)

    def test_select_rule_cases_keeps_unknown(self):
        ev = self.tmp / 'ev'
        write(ev / 'no-graders' / 'prompt.md', 'x')
        write(ev / 'yaml' / 'case.yaml', 'name: y\ngraders:\n  - type: llm\n')
        write(ev / 'yaml' / 'graders' / 'q.md', LLM_GRADER)
        write(ev / 'mixed' / 'prompt.md', 'x')
        write(ev / 'mixed' / 'graders' / 'q.md', LLM_GRADER)
        write(ev / 'mixed' / 'graders' / 'r.md', '---\ntype: "tool_used"\ntool: Agent\narm: with-only\n---\n')
        run, skipped = gaterun.select_rule_cases(ev, ['mixed', 'no-graders', 'yaml'])
        self.assertEqual(run, ['mixed', 'no-graders', 'yaml'])
        self.assertEqual(skipped, {})


class CountWithOnlyTest(unittest.TestCase):
    def test_single_arm_counts_with_only_but_not_paid(self):
        case = {'graders': [{'name': 'r', 'type': 'regex', 'config': {}},
                            {'name': 'm', 'type': 'regex', 'config': {'arm': 'with-only'}},
                            {'name': 's', 'type': 'tool_used', 'config': {'tool': 'Skill'}},
                            {'name': 'q', 'type': 'llm', 'config': {}}],
                'arms': {'with': [{'error': None, 'graders': [{'name': 'r', 'passed': True},
                                                               {'name': 'm', 'passed': False},
                                                               {'name': 's', 'passed': True},
                                                               {'name': 'q', 'passed': False}]}]}}
        self.assertEqual(scoring.score_case(case)['score'], 1.0)
        one = scoring.score_case(case, count_with_only=True)
        self.assertAlmostEqual(one['score'], 2 / 3)
        self.assertEqual(list(one['excluded_graders']), ['q'])


class SubsetThenGateTest(Base):
    def test_outside_gate_subset_passes_gate(self):
        before = self.gate()
        self.assertFalse(before.passed)
        self.assertIsNone(before.data['rule_subset_needed'])
        self.assertTrue(any('--run-subset' in ln for ln in before.lines))
        self.subset()
        after = self.gate()
        self.assertTrue(after.passed, '\n'.join(after.lines))
        self.assertEqual([a['kind'] for a in after.data['basis']], ['gate'])

    def test_cli_run_subset_then_regate(self):
        registry.register(self.data, NAME, self.r.root)
        fake = FakeEval(self.sandboxes, {'current': True})
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(gaterun.evalrun, 'runner_with_timeout', return_value=fake), \
                mock.patch.object(gaterun.preflight, 'check_compare', passing_preflight), \
                mock.patch.object(gaterun.evalrun, 'resolve_claude', return_value='/fake/claude'), \
                mock.patch.object(gate.unittests, 'run_plugin', ok_tests), \
                mock.patch.object(compare, 'static_profiles', no_static), \
                redirect_stdout(out), redirect_stderr(err):
            code = cli.main(['--data-dir', str(self.data), 'gate', str(self.r.plugin), '--run-subset', '--runs', '1'])
        self.assertEqual(code, 0, out.getvalue() + err.getvalue())
        self.assertIn('规则子集运行目录', err.getvalue())
        self.assertIn('采信 runs/', out.getvalue())
        self.assertIn('结论：过闸', out.getvalue())

    def test_major_bump_does_not_run_subset(self):
        self.r.set_version('2.0.0')
        self.r.commit('升 2.0.0')
        err = io.StringIO()
        with mock.patch.object(gaterun, 'run_subset', boom), mock.patch.object(gate.unittests, 'run_plugin', ok_tests), \
                redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = cli.main(['--data-dir', str(self.data), 'gate', str(self.r.plugin), '--run-subset'])
        self.assertEqual(code, 1)
        self.assertIn('不跑规则子集：闸门内版本', err.getvalue())

    def test_dirty_subset_not_accepted(self):
        write(self.r.plugin / 'rules.txt', '改了没提交\n')
        rec = self.subset().record
        self.assertIs(rec['preflight']['dirty'], True)
        self.assertIn('有未提交改动', '；'.join(rec['preflight']['warnings']))


# ---------------- 提示：建议跑对照 ----------------

class CompareSuggestionTest(Base):
    def setUp(self):
        super().setUp()
        cap = clauses.capture_injection(self.r.plugin, tmp_parent=self.asm)
        self.assertTrue(cap.injecting, cap.summary())
        # 上次对照（1.0.0 时跑的）记下的注入文本指纹
        self.r.add_run('20261001T000000Z-1.0.0-compare', {
            'kind': 'compare', 'plugin': {'name': NAME, 'version': '1.0.0', 'fingerprint': 'sha256:old'},
            'clause_check': {'status': 'up-to-date', 'injection_fingerprint': cap.fingerprint,
                             'normalization': clauses.NORMALIZATION['name']}})

    def test_unchanged_no_suggestion(self):
        res = self.gate(tmp_parent=self.asm)
        self.assertEqual(self.suggestion_lines(res), [])
        self.assertIsNone(res.data['compare_suggestion'])

    def test_injection_text_changed_exactly_one_line(self):
        write(self.r.plugin / 'rules.txt', '1. 回复一律用简体中文。\n2. 派子代理时写明 model。\n')
        res = self.gate(tmp_parent=self.asm)
        lines = [ln for ln in res.lines if gatehints.SUGGESTION in ln]
        self.assertEqual(len(lines), 1, '\n'.join(res.lines))
        self.assertIn('注入文本指纹相对上次对照 runs/20261001T000000Z-1.0.0-compare 变了', lines[0])
        self.assertEqual(len(res.data['compare_suggestion']['reasons']), 1)

    def test_skill_description_changed(self):
        write(self.r.plugin / 'skills' / 'helper' / 'SKILL.md', SKILL_MD % '帮你做事。用户说「帮忙」或「搭把手」时使用')
        self.r.commit('改 description')
        res = self.gate(tmp_parent=self.asm)
        lines = [ln for ln in res.lines if gatehints.SUGGESTION in ln]
        self.assertEqual(len(lines), 1, '\n'.join(res.lines))
        self.assertIn('相对上一版 1.0.0：skill `helper` 的 description 改了', lines[0])

    def test_skill_body_only_change_no_suggestion(self):
        write(self.r.plugin / 'skills' / 'helper' / 'SKILL.md',
              (SKILL_MD % '帮你做事。用户说「帮忙」时使用') + '\n多写一段正文\n')
        self.r.commit('改正文')
        self.assertEqual(self.suggestion_lines(self.gate(tmp_parent=self.asm)), [])

    def test_agent_and_injection_and_description_merge_into_one(self):
        write(self.r.plugin / 'agents' / 'worker.md', '---\nname: worker\ndescription: 干活\n---\n你是认真干活的。\n')
        write(self.r.plugin / 'skills' / 'new-one' / 'SKILL.md', SKILL_MD % '新技能')
        write(self.r.plugin / 'rules.txt', '变了\n')
        self.r.commit('一起改')
        res = self.gate(tmp_parent=self.asm)
        lines = self.suggestion_lines(res)
        self.assertEqual(len(lines), 1)
        for needle in ('注入文本指纹', '新增 skill `new-one`', 'agent `worker.md` 的定义改了'):
            self.assertIn(needle, lines[0])

    def test_baseline_falls_back_to_clause_list(self):
        shutil.rmtree(self.r.root / 'plugin-evals' / NAME / 'runs')
        write(self.r.root / 'plugin-evals' / NAME / 'clauses.json', json.dumps({
            'injection_fingerprint': 'sha256:' + '0' * 64, 'normalization': clauses.NORMALIZATION['name']}))
        lines = self.suggestion_lines(self.gate(tmp_parent=self.asm))
        self.assertEqual(len(lines), 1)
        self.assertIn('条款清单 clauses.json', lines[0])

    def test_no_baseline_only_note(self):
        shutil.rmtree(self.r.root / 'plugin-evals' / NAME / 'runs')
        res = self.gate(tmp_parent=self.asm)
        self.assertEqual(self.suggestion_lines(res), [])
        self.assertTrue(any('本次不比较注入文本' in n for n in res.data['notes']))

    def test_covered_by_compare_of_current_content(self):
        write(self.r.plugin / 'rules.txt', '变了\n')
        self.r.commit('改注入')
        self.r.add_run('20261002T000000Z-1.1.0-compare', {
            'kind': 'compare', 'plugin': {'name': NAME, 'version': '1.1.0', 'fingerprint': self.r.fp()},
            'clause_check': {'status': 'unreliable', 'injection_fingerprint': 'sha256:x'}})
        res = self.gate(tmp_parent=self.asm)
        self.assertEqual(self.suggestion_lines(res), [])
        self.assertTrue(any('已跑过离线对照 runs/20261002T000000Z-1.1.0-compare' in n for n in res.data['notes']))

    def test_suggestion_does_not_change_verdict(self):
        write(self.r.plugin / 'rules.txt', '变了\n')
        self.r.commit('改注入')
        self.assertEqual(self.gate(tmp_parent=self.asm).data['passed'], False)   # 缺依据才不过闸，与提示无关
        self.subset()
        res = self.gate(tmp_parent=self.asm)
        self.assertTrue(res.passed)
        self.assertEqual(len(self.suggestion_lines(res)), 1)


class DescriptionParseTest(unittest.TestCase):
    def test_block_and_inline(self):
        self.assertEqual(gatehints.description_of('---\nname: a\ndescription: 一行\nx: 1\n---\n'), '一行')
        self.assertEqual(gatehints.description_of('---\ndescription: |\n  第一行\n  第二行\nname: a\n---\n'),
                         '|\n第一行\n第二行')
        self.assertIsNone(gatehints.description_of('no frontmatter'))
        self.assertIsNone(gatehints.description_of('---\nname: a\n---\ndescription: 正文里的不算\n'))


# ---------------- 提示：超 7 天复盘 ----------------

class ReviewReminderTest(Base):
    def reviews(self, day):
        write(self.r.root / 'plugin-evals' / NAME / 'reviews' / ('%s.json' % day.isoformat()), '{}')

    def today(self):
        return reviewgap.today_local(self.now)

    def test_gate_reminds_after_8_days_not_7(self):
        self.reviews(self.today() - timedelta(days=8))
        res = self.gate()
        self.assertIn('已 8 天，超过 7 天', res.data['review_reminder'])
        self.assertIn(res.data['review_reminder'], res.data['notes'])
        self.reviews(self.today() - timedelta(days=7))
        self.assertIsNone(self.gate().data['review_reminder'])

    def test_gate_reminds_when_never_reviewed(self):
        self.assertIn('还没有会话复盘记录', self.gate().data['review_reminder'])

    def test_compare_logs_reminder(self):
        self.reviews(self.today() - timedelta(days=8))
        registry.register(self.data, NAME, self.r.root)
        logs = []
        with mock.patch.object(clauses, 'check_for_run', lambda **kw: None):
            compare.run_compare(self.data, NAME, runs=1, concurrency=1, claude='/fake/claude',
                                runner=FakeEval(self.sandboxes, {'none': False, 'previous': True, 'current': True}),
                                env={'PATH': '/usr/bin'}, tmp_parent=self.asm, sandbox_roots=[self.sandboxes],
                                log=logs.append, preflight_check=passing_preflight, use_judge=False,
                                now=lambda: self.now)
        hits = [m for m in logs if '超过 7 天：建议先跑会话复盘' in m]
        self.assertEqual(len(hits), 1, logs)

    def test_local_date_not_utc_midnight(self):
        # 东八区 10-15 上午 08:00（UTC 10-15 00:00）写的复盘文件名是 10-15；UTC 10-22 20:00 是东八区 10-23 → 8 天
        tz8 = timezone(timedelta(hours=8))
        d = Path(self.tmp / 'rv')
        write(d / '2026-10-15.json', '{}')
        self.assertIsNotNone(reviewgap.reminder(d, now=datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc), tz=tz8))
        self.assertIsNone(reviewgap.reminder(d, now=datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc), tz=tz8))

    def test_never_reviewed_mentions_registry(self):
        self.assertIn('未登记需先登记', self.gate().data['review_reminder'])


# ---------------- B 批集成：审查 15 应修与定稿口径 ----------------

def failing_tests(plugin_dir, platform=None):
    return {'plugin': Path(plugin_dir).name, 'declaration': 'declared', 'errors': [], 'messages': [],
            'tests': [{'index': 0, 'run': ['python3', '-m', 'unittest'], 'status': 'failed', 'code': 1, 'ms': 10,
                       'output': 'FAILED'}]}


class HintErrorsDoNotBreakGateTest(Base):
    def test_corrupt_clause_list_gate_still_concludes(self):
        """没有上次对照、clauses.json 损坏：「建议跑对照」算不成，gate 照常给结论（审查 15 应修 1）。"""
        write(self.r.root / 'plugin-evals' / NAME / 'clauses.json', '{坏的 JSON')
        res = self.gate(tmp_parent=self.asm)
        self.assertFalse(res.passed)      # 缺依据：照常判未过闸
        self.assertIsNone(res.data['compare_suggestion'])
        self.assertTrue(any(n.startswith('提示计算出错') for n in res.data['notes']), res.data['notes'])
        self.assertTrue(res.lines[-1].startswith('结论：未过闸'))

    def test_reminder_error_recorded_in_notes(self):
        with mock.patch.object(reviewgap, 'reminder', side_effect=OSError('读不了 reviews/')):
            res = self.gate(tmp_parent=self.asm)
        self.assertIsNone(res.data['review_reminder'])
        self.assertTrue(any('距上次复盘的天数没算成' in n for n in res.data['notes']))

    def test_cli_exit_code_unaffected(self):
        write(self.r.root / 'plugin-evals' / NAME / 'clauses.json', '{坏的 JSON')
        with mock.patch.object(gate.unittests, 'run_plugin', ok_tests), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = cli.main(['gate', str(self.r.plugin)])
        self.assertEqual(code, 1)         # 1 = 未过闸，不是崩溃


class SubsetNeededReasonTest(Base):
    def test_failing_unit_tests_do_not_run_subset(self):
        res = self.gate(unit_runner=failing_tests)
        self.assertIn('单测声明未通过', res.data['rule_subset_needed'])
        self.assertFalse(any('--run-subset' in ln for ln in res.lines))

    def test_cli_failing_tests_never_calls_run_subset(self):
        err = io.StringIO()
        with mock.patch.object(gaterun, 'run_subset', boom), \
                mock.patch.object(gate.unittests, 'run_plugin', failing_tests), \
                redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = cli.main(['--data-dir', str(self.data), 'gate', str(self.r.plugin), '--run-subset'])
        self.assertEqual(code, 1)
        self.assertIn('不跑规则子集：单测声明未通过', err.getvalue())

    def test_not_in_git_does_not_run_subset(self):
        res = self.gate(git='')           # 读不到 git：top=None
        self.assertIn('不在 git 仓里', res.data['rule_subset_needed'])

    def test_reason_order(self):
        self.assertIsNone(gate.subset_needed_reason(False, False, [], [], tests_ok=True, in_git=True))
        self.assertIn('单测', gate.subset_needed_reason(False, False, [], [], tests_ok=False, in_git=False))
        self.assertIn('git', gate.subset_needed_reason(False, False, [], [], tests_ok=True, in_git=False))


class ThresholdTest(Base):
    def test_default_threshold_text_in_report_and_gate(self):
        res = self.subset()
        self.assertEqual(res.record['threshold'], 1.0)
        self.assertIn('threshold=1.0：每例全部 run 都过', (res.run_dir / 'report.md').read_text(encoding='utf-8'))
        g = self.gate()
        self.assertTrue(g.passed)
        self.assertIn('规则子集 threshold=1.0：每例全部 run 都过', '\n'.join(g.lines))
        self.assertEqual(g.data['rule_subset_threshold'], 1.0)

    def test_cli_threshold_passed_to_subset(self):
        registry.register(self.data, NAME, self.r.root)
        seen = {}

        def spy(*a, **kw):
            seen.update(kw)
            raise gaterun.GateRunError('只看参数')
        with mock.patch.object(gaterun, 'run_subset', spy), mock.patch.object(gate.unittests, 'run_plugin', ok_tests), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = cli.main(['--data-dir', str(self.data), 'gate', str(self.r.plugin), '--run-subset',
                             '--threshold', '0.5'])
        self.assertEqual(code, 2)
        self.assertEqual(seen['threshold'], 0.5)

    def test_gate_hint_line_mentions_threshold(self):
        self.assertTrue(any('threshold=1.0：每例全部 run 都过' in ln for ln in self.gate().lines))


class NoScorableGraderTest(Base):
    def test_no_scorable_rule_grader_is_incomplete_not_failed(self):
        """定稿第 6 条：全部用例都没有可计分的规则 grader → complete=False；gate 不采信，也不报「规则子集未通过」。"""
        unscored = {'score': None, 'cases': {'case-a': {'score': None, 'run_scores': [None, None],
                                                        'excluded_graders': {}, 'no_scored_graders': True}},
                    'invalid_run_count': 0}
        with mock.patch.object(gaterun.scoring, 'score_arm', return_value=unscored):
            res = self.subset()
        self.assertFalse(res.record['complete'])
        self.assertEqual(res.exit_code, 3)
        self.assertIn(gaterun.NO_SCORABLE_REASON, res.record['incomplete_reasons'])
        g = self.gate()
        self.assertFalse(g.passed)
        reasons = '；'.join(g.data['rejected_same_version'][0]['reasons'])
        self.assertIn('没有可计分的规则 grader', reasons)
        self.assertNotIn('规则子集未通过', reasons)


if __name__ == '__main__':
    unittest.main()
