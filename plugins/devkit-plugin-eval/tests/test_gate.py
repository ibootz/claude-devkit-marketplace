"""发版闸门（票 14）：采信判据、闸门内外、eval-skip、漏检、单测声明接入、命令行。用真 git 造临时仓，不联网。"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from _support import SCRIPTS, tmpdir, write

from plugin_eval_lib import fingerprint, gate

GIT = shutil.which('git')
NAME = 'devkit-demo'


def ok_tests(plugin_dir, platform=None):
    return {'plugin': Path(plugin_dir).name, 'declaration': 'undeclared', 'errors': [], 'messages': [], 'tests': []}


def run_rec(version, fp, *, kind='compare', reviewed=True, complete=True, dirty=False, inj_ok=True, passed=True,
            versions=('2.1.300',), degraded=None, first_run_dirty=None):
    rec = {
        'schema_version': 1, 'kind': kind, 'run_id': 'x',
        'plugin': {'name': NAME, 'version': version, 'fingerprint': fp},
        'complete': complete, 'incomplete_reasons': [] if complete else ['某臂：1 个 run 出错'],
        'passed': passed,
        'review': {'status': '已审' if reviewed else '待审', 'reviewed_at': '2026-10-15T01:00:00Z' if reviewed else None},
        'injection_check': {'ok': inj_ok, 'problems': [] if inj_ok else ['当前版臂：注入未到达']},
        'claude_code_versions': list(versions),
        'preflight': {'dirty': dirty},
        'arms': {'none': {'source': 'stub'}, 'current': {'source': 'working-tree', 'dirty': dirty},
                 'previous': {'source': 'git-snapshot', 'dirty': None}},
    }
    if first_run_dirty is not None:
        rec['preflight']['first_run'] = {'dirty': first_run_dirty}
    if degraded:
        rec['previous_arm'] = {'degraded': True, 'reason_kind': degraded, 'reason': '…'}
    return rec


class Repo:
    def __init__(self, root):
        self.root = Path(root)
        self.git('init', '-q', '-b', 'main')
        self.plugin = self.root / 'plugins' / NAME

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid',
                               *args], check=True, capture_output=True, text=True).stdout.strip()

    def set_version(self, version):
        write(self.plugin / '.claude-plugin' / 'plugin.json',
              '{\n  "name": "%s",\n  "version": "%s",\n  "description": "demo",\n  "author": {"name": "t"}\n}\n'
              % (NAME, version))

    def commit(self, msg, trailers=()):
        self.git('add', '-A')
        body = msg + ('\n\n' + '\n'.join(trailers) if trailers else '')
        self.git('commit', '-q', '-m', body)
        return self.git('rev-parse', 'HEAD')

    def fp(self):
        return fingerprint.plugin_fingerprint(self.plugin)

    def add_run(self, run_id, rec):
        write(self.root / 'plugin-evals' / NAME / 'runs' / run_id / 'run.json', json.dumps(rec, ensure_ascii=False))


@unittest.skipUnless(GIT, 'git 不可用')
class GateTestBase(unittest.TestCase):
    def setUp(self):
        self.r = Repo(tmpdir(self))
        self.r.set_version('1.0.0')
        write(self.r.plugin / 'hooks' / 'inject.js', 'console.log("hi")\n')
        write(self.r.plugin / 'evals' / 'case-a' / 'prompt.md', 'do\n')
        self.r.commit('初版')

    def gate(self, **kw):
        kw.setdefault('unit_runner', ok_tests)
        return gate.evaluate(self.r.plugin, **kw)


class AcceptTest(GateTestBase):
    def test_reviewed_compare_with_same_fingerprint_passes(self):
        self.r.add_run('20261015T000000Z-1.0.0-compare', run_rec('1.0.0', self.r.fp()))
        res = self.gate()
        self.assertTrue(res.passed, '\n'.join(res.lines))
        self.assertEqual([a['run_id'] for a in res.data['basis']], ['20261015T000000Z-1.0.0-compare'])
        self.assertIn('结论：过闸', res.lines[-1])

    def test_edit_outside_evals_after_review_fails_but_new_case_does_not(self):
        self.r.add_run('r1', run_rec('1.0.0', self.r.fp()))
        write(self.r.plugin / 'evals' / 'case-b' / 'prompt.md', 'new case\n')
        write(self.r.plugin / 'evals' / 'case-a' / 'prompt.md', 'tweaked\n')
        self.assertTrue(self.gate().passed)            # 只补 evals/ 用例不影响
        write(self.r.plugin / 'hooks' / 'inject.js', 'console.log("changed")\n')
        self.r.commit('改 hook')                       # 先提交：未提交改动另有专门的未过闸原因（见 DirtyWorkspaceTest）
        res = self.gate()
        self.assertFalse(res.passed)
        self.assertIn('插件内容指纹与当前不一致', res.data['rejected_same_version'][0]['reasons'][0])
        self.assertIn('结论：未过闸（缺可采信的评测依据）', res.lines[-1])

    def test_pending_review_not_accepted(self):
        self.r.add_run('r1', run_rec('1.0.0', self.r.fp(), reviewed=False))
        res = self.gate()
        self.assertFalse(res.passed)
        self.assertTrue(any('待审报告不能作发版依据' in x for x in res.data['rejected_same_version'][0]['reasons']))

    def test_other_version_ignored(self):
        self.r.add_run('r0', run_rec('0.9.0', self.r.fp()))
        res = self.gate()
        self.assertFalse(res.passed)
        self.assertEqual(res.data['other_runs'], 1)


class ExcludeTest(GateTestBase):
    """dirty、不完整、注入未到达、版本混用的规则子集都不采信。"""

    def assertRejected(self, rec, needle):
        self.r.add_run('r1', rec)
        res = self.gate()
        self.assertFalse(res.passed, '\n'.join(res.lines))
        reasons = res.data['rejected_same_version'][0]['reasons']
        self.assertTrue(any(needle in x for x in reasons), reasons)

    def test_dirty_true(self):
        self.assertRejected(run_rec('1.0.0', self.r.fp(), dirty=True), 'preflight.dirty=true')

    def test_dirty_null_not_clean(self):
        """dirty=null（不在 git 仓）不能当干净：判据是 `dirty is False`。"""
        self.assertRejected(run_rec('1.0.0', self.r.fp(), dirty=None), 'null（取不到 git 状态）')

    def test_resumed_run_latest_dirty(self):
        """续跑过的运行读 preflight.dirty（最后一次续跑时）：首跑干净、续跑时 dirty 不采信。"""
        rec = run_rec('1.0.0', self.r.fp(), first_run_dirty=False)
        rec['preflight']['dirty'] = True
        self.assertRejected(rec, 'preflight.dirty=true')

    def test_old_record_without_preflight_falls_back_to_arm(self):
        rec = run_rec('1.0.0', self.r.fp())
        del rec['preflight']
        rec['arms']['current']['dirty'] = None
        self.assertRejected(rec, 'arms.current.dirty=null')

    def test_no_dirty_record(self):
        rec = run_rec('1.0.0', self.r.fp())
        del rec['preflight']
        rec['arms'] = {}
        self.assertRejected(rec, '没有 dirty 记录')

    def test_incomplete(self):
        self.assertRejected(run_rec('1.0.0', self.r.fp(), complete=False), '运行不完整')

    def test_missing_complete_field(self):
        rec = run_rec('1.0.0', self.r.fp())
        del rec['complete']
        self.assertRejected(rec, '没有 complete 字段')

    def test_injection_not_arrived(self):
        self.assertRejected(run_rec('1.0.0', self.r.fp(), inj_ok=False), 'injection_check.ok=false')

    def test_gate_kind_not_passed(self):
        self.assertRejected(run_rec('1.0.0', self.r.fp(), kind='gate', reviewed=False, passed=False), '规则子集未通过')

    def test_gate_kind_mixed_claude_versions(self):
        self.assertRejected(run_rec('1.0.0', self.r.fp(), kind='gate', reviewed=False,
                                    versions=('2.1.300', '2.1.301')), 'Claude Code 版本混用')

    def test_bad_json(self):
        write(self.r.root / 'plugin-evals' / NAME / 'runs' / 'r1' / 'run.json', '{')
        res = self.gate()
        self.assertFalse(res.passed)
        self.assertEqual(res.data['other_runs'], 1)


class NotesTest(GateTestBase):
    def test_resumed_run_first_dirty_then_committed_accepted_with_note(self):
        """首跑时未提交、续跑前提交了：续跑保证指纹不变，最后一次续跑 dirty=false 即可追溯到提交，采信并提示。"""
        rec = run_rec('1.0.0', self.r.fp(), first_run_dirty=True)
        rec['arms']['current']['dirty'] = True
        self.r.add_run('r1', rec)
        res = self.gate()
        self.assertTrue(res.passed, '\n'.join(res.lines))
        self.assertIn('首跑时 arms.current.dirty=true', res.data['basis'][0]['notes'][0])

    def test_reviewed_compare_with_mixed_versions_accepted_with_note(self):
        self.r.add_run('r1', run_rec('1.0.0', self.r.fp(), versions=('2.1.300', '2.1.301')))
        res = self.gate()
        self.assertTrue(res.passed)
        self.assertTrue(any('版本混用' in n for n in res.data['basis'][0]['notes']))

    def test_degraded_reports_noted_by_reason_kind(self):
        self.r.add_run('r1', run_rec('1.0.0', self.r.fp(), degraded='no-different-version'))
        self.r.add_run('r2', run_rec('1.0.0', self.r.fp(), degraded='snapshot-failed'))
        res = self.gate()
        self.assertTrue(res.passed)
        notes = {a['run_id']: a['notes'] for a in res.data['basis']}
        self.assertIn('新插件首评', notes['r1'][0])
        self.assertIn('snapshot-failed', notes['r2'][0])
        self.assertIn('只比了不装', notes['r2'][0])

    def test_gate_kind_passed_accepted_outside_gate(self):
        self.r.add_run('r1', run_rec('1.0.0', self.r.fp(), kind='gate', reviewed=False))
        res = self.gate()
        self.assertTrue(res.passed)
        self.assertEqual(res.data['basis'][0]['kind'], 'gate')


class CoverageTest(GateTestBase):
    """major 升版与 eval-required: 的版本只认已审的离线对照。"""

    def test_major_bump_rejects_rule_subset(self):
        self.r.set_version('2.0.0')
        self.r.commit('升 2.0.0')
        self.r.add_run('g', run_rec('2.0.0', self.r.fp(), kind='gate', reviewed=False))
        res = self.gate()
        self.assertTrue(res.data['gated'])
        self.assertIn('major 升版（1.0.0 → 2.0.0）', res.data['gated_by'][0])
        self.assertFalse(res.passed)
        self.r.add_run('c', run_rec('2.0.0', self.r.fp()))
        self.assertTrue(self.gate().passed)

    def test_eval_required_trailer_gates_minor_bump(self):
        self.r.set_version('1.1.0')
        self.r.commit('升 1.1.0', trailers=['eval-required: 改了注入文本'])
        self.r.add_run('g', run_rec('1.1.0', self.r.fp(), kind='gate', reviewed=False))
        res = self.gate()
        self.assertTrue(res.data['gated'])
        self.assertIn('eval-required: 改了注入文本', res.data['gated_by'][0])
        self.assertFalse(res.passed)

    def test_minor_bump_accepts_rule_subset(self):
        self.r.set_version('1.1.0')
        self.r.commit('升 1.1.0')
        self.r.add_run('g', run_rec('1.1.0', self.r.fp(), kind='gate', reviewed=False))
        res = self.gate()
        self.assertFalse(res.data['gated'])
        self.assertTrue(res.passed)

    def test_uncommitted_bump_noted(self):
        self.r.set_version('1.1.0')
        res = self.gate()
        self.assertTrue(any('尚未提交' in n for n in res.data['notes']))


class DirtyWorkspaceTest(GateTestBase):
    """工作区 dirty 不是 False 时直接判未过闸（票 14 应修 1）。"""

    def test_uncommitted_change_blocks_even_with_matching_report(self):
        self.r.add_run('r1', run_rec('1.0.0', self.r.fp()))
        write(self.r.plugin / 'hooks' / 'extra.js', '// 未提交\n')
        self.r.add_run('r2', run_rec('1.0.0', self.r.fp()))   # 已审内容 = 工作区内容
        res = self.gate()
        self.assertFalse(res.passed)
        self.assertEqual(res.data['blockers'], [gate.DIRTY_BLOCKER])
        self.assertIn('插件目录有未提交改动（不含 evals/），先提交再跑 gate', res.lines[-1])

    def test_worktree_equals_reviewed_content_but_head_differs(self):
        reviewed_fp = self.r.fp()
        self.r.add_run('r1', run_rec('1.0.0', reviewed_fp))   # 在提交 A 上审过
        write(self.r.plugin / 'hooks' / 'inject.js', 'console.log("B")\n')
        self.r.commit('提交 B')                               # HEAD 变成 B
        write(self.r.plugin / 'hooks' / 'inject.js', 'console.log("hi")\n')   # 工作区退回 A 的内容，未提交
        self.assertEqual(self.r.fp(), reviewed_fp)
        res = self.gate()
        self.assertEqual([a['run_id'] for a in res.data['basis']], ['r1'])   # 依据本身照采信
        self.assertFalse(res.passed)                                         # 但 HEAD 不是已审内容：未过闸
        self.assertEqual(res.data['blockers'], [gate.DIRTY_BLOCKER])

    def test_evals_only_change_does_not_block(self):
        self.r.add_run('r1', run_rec('1.0.0', self.r.fp()))
        write(self.r.plugin / 'evals' / 'case-z' / 'prompt.md', '补一个用例\n')
        self.assertTrue(self.gate().passed)


class GateIntegrationTest(GateTestBase):
    """A 批集成：clauses 运行跳过、AI 判分不采信提示、新插件首版说明、eval-required 宽松识别。"""

    def test_clauses_runs_are_skipped(self):
        self.r.add_run('20261015T000000Z-1.0.0-clauses', {'kind': 'clauses', 'plugin': {'name': NAME, 'version': '1.0.0'}})
        res = self.gate()
        self.assertEqual(res.data['rejected_same_version'], [])
        self.assertEqual(res.data['other_runs'], 0)

    def test_untrusted_judge_report_still_accepted_with_prominent_note(self):
        rec = run_rec('1.0.0', self.r.fp())
        rec['judge'] = {'trusted': False}
        self.r.add_run('r1', rec)
        res = self.gate()
        self.assertTrue(res.passed, '\n'.join(res.lines))
        self.assertEqual(res.data['judge_untrusted'], ['r1'])
        self.assertIn('- **注意：本报告 AI 判分不采信，已审时由用户判断**（runs/r1）', res.lines)

    def test_first_version_of_new_plugin_noted_and_not_gated(self):
        res = self.gate()
        self.assertFalse(res.data['gated'])
        self.assertTrue(any(n.startswith('新插件首个版本') for n in res.data['notes']), res.data['notes'])
        self.r.set_version('2.0.0')
        self.r.commit('升 2.0.0')
        self.assertFalse(any(n.startswith('新插件首个版本') for n in self.gate().data['notes']))

    def test_eval_required_followed_by_blank_line_and_signature(self):
        self.r.set_version('1.1.0')
        self.r.commit('升 1.1.0', trailers=['eval-required: 改了注入文本', '', 'Co-Authored-By: t <t@example.invalid>'])
        res = self.gate()
        self.assertTrue(res.data['gated'])
        self.assertIn('eval-required: 改了注入文本', res.data['gated_by'][0])
        self.assertTrue(any(n.startswith('警告：') and 'eval-required' in n for n in res.data['notes']), res.data['notes'])

    def test_eval_skip_outside_trailer_warns_and_does_not_pass(self):
        self.r.set_version('1.1.0')
        self.r.commit('升 1.1.0', trailers=['eval-skip: 只改 README', '', 'Co-Authored-By: t <t@example.invalid>'])
        res = self.gate()
        self.assertFalse(res.data['passed_via_skip'])
        self.assertTrue(any(n.startswith('警告：') and 'eval-skip' in n for n in res.data['notes']), res.data['notes'])


class SkipTest(GateTestBase):
    def test_eval_skip_passes_and_lists_every_skip(self):
        self.r.set_version('1.1.0')
        self.r.commit('升 1.1.0 紧急修复', trailers=['eval-skip: 线上故障先止血'])
        self.r.set_version('2.0.0')
        self.r.commit('升 2.0.0', trailers=['eval-skip: 只改了 README'])
        res = self.gate()
        self.assertTrue(res.passed, '\n'.join(res.lines))
        self.assertTrue(res.data['passed_via_skip'])
        self.assertEqual([(s['version'], s['reason']) for s in res.data['skip_records']],
                         [('2.0.0', '只改了 README'), ('1.1.0', '线上故障先止血')])
        text = '\n'.join(res.lines)
        self.assertIn('1.1.0（提交', text)
        self.assertIn('线上故障先止血', text)
        self.assertIn('经 eval-skip: 放行', res.lines[-1])

    def test_skip_does_not_waive_unit_tests(self):
        self.r.set_version('1.1.0')
        self.r.commit('升', trailers=['eval-skip: 急'])
        write(self.r.plugin / 'unit-tests.json', json.dumps({'tests': [{'run': [sys.executable, 'bad.py']}]}))
        write(self.r.plugin / 'bad.py', 'import sys; sys.exit(1)\n')
        res = gate.evaluate(self.r.plugin)
        self.assertFalse(res.passed)
        self.assertIn('单测未通过', res.lines[-1])


class UnitTestsWiringTest(GateTestBase):
    def test_failing_unit_test_blocks_even_with_basis(self):
        write(self.r.plugin / 'unit-tests.json', json.dumps({'tests': [{'run': [sys.executable, 'bad.py']}]}))
        write(self.r.plugin / 'bad.py', 'import sys; sys.exit(2)\n')
        self.r.add_run('r1', run_rec('1.0.0', self.r.fp()))
        res = gate.evaluate(self.r.plugin)
        self.assertTrue(res.data['eval_ok'])
        self.assertFalse(res.passed)

    def test_undeclared_hints_only(self):
        self.r.add_run('r1', run_rec('1.0.0', self.r.fp()))
        res = gate.evaluate(self.r.plugin)
        self.assertTrue(res.passed)
        self.assertIn('未声明单测', '\n'.join(res.lines))


class LeakTest(GateTestBase):
    """闸门内版本推到 main 时既无已审报告、也无 eval-skip:，列为漏检。"""

    def setUp(self):
        super().setUp()
        self.r.add_run('r-1.0.0', run_rec('1.0.0', self.r.fp()))
        self.r.commit('入库 1.0.0 的已审对照')       # plugin-evals/ 首次入库：漏检起算点

    def test_major_bump_without_report_or_skip_is_leak(self):
        self.r.set_version('2.0.0')
        intro = self.r.commit('升 2.0.0')
        self.r.set_version('2.1.0')
        self.r.commit('升 2.1.0')                    # 闸门外，不算漏检
        res = self.gate()
        self.assertEqual(res.data['main_ref'], 'main')
        self.assertEqual([(x['version'], x['intro_commit']) for x in res.data['leaks']], [('2.0.0', intro)])
        self.assertIn('没有该版本的已审离线对照报告', res.data['leaks'][0]['why'])
        self.assertIn('2.0.0（major 升版（1.0.0 → 2.0.0）', '\n'.join(res.lines))

    def test_eval_required_without_report_is_leak(self):
        self.r.set_version('1.1.0')
        self.r.commit('升 1.1.0', trailers=['eval-required: 改了 skill description'])
        self.r.set_version('1.2.0')
        self.r.commit('升 1.2.0')
        self.assertEqual([x['version'] for x in self.gate().data['leaks']], ['1.1.0'])

    def test_eval_required_followed_by_blank_line_and_signature_without_report_is_leak(self):
        """漏检检查与当前版本判定同口径：eval-required: 后跟空行与署名段（git 不认 trailer）也算进闸门。"""
        self.r.set_version('1.1.0')
        self.r.commit('升 1.1.0', trailers=['eval-required: 改了注入文本', '', 'Co-Authored-By: t <t@example.invalid>'])
        self.r.set_version('1.2.0')
        self.r.commit('升 1.2.0')
        leaks = self.gate().data['leaks']
        self.assertEqual([x['version'] for x in leaks], ['1.1.0'])
        self.assertIn('eval-required: 改了注入文本', leaks[0]['gated_by'])

    def test_skip_or_matching_reviewed_report_not_leak(self):
        self.r.set_version('2.0.0')
        self.r.commit('升 2.0.0', trailers=['eval-skip: 急'])
        self.r.set_version('3.0.0')
        self.r.commit('升 3.0.0')
        self.r.add_run('r-3.0.0', run_rec('3.0.0', self.r.fp()))
        self.r.commit('入库 3.0.0 的已审对照')
        res = self.gate()
        self.assertEqual(res.data['leaks'], [])
        self.assertTrue(res.passed)

    def test_reviewed_report_for_different_content_is_leak(self):
        self.r.set_version('2.0.0')
        self.r.add_run('r-2.0.0', run_rec('2.0.0', self.r.fp()))
        self.r.commit('升 2.0.0 并入库已审对照')
        write(self.r.plugin / 'hooks' / 'inject.js', 'console.log("审后改")\n')
        self.r.commit('审后改内容不升版')
        leaks = self.gate().data['leaks']
        self.assertEqual([x['version'] for x in leaks], ['2.0.0'])
        self.assertIn('评的内容与推到 main 的不一致', leaks[0]['why'])

    def test_versions_before_evaluation_started_not_traced(self):
        r = Repo(tmpdir(self))
        r.set_version('1.0.0')
        r.commit('初版')
        r.set_version('2.0.0')
        r.commit('升 2.0.0')                         # 还没有 plugin-evals/，不追溯
        res = gate.evaluate(r.plugin, unit_runner=ok_tests)
        self.assertEqual(res.data['leaks'], [])
        self.assertTrue(any('漏检从首份评测记录入库起算' in n for n in res.data['notes']))
        res = gate.evaluate(r.plugin, unit_runner=ok_tests, since=r.git('rev-list', '--max-parents=0', 'HEAD'))
        self.assertEqual([x['version'] for x in res.data['leaks']], ['2.0.0'])


@unittest.skipUnless(GIT, 'git 不可用')
class CliTest(unittest.TestCase):
    def test_exit_codes_without_data_dir(self):
        r = Repo(tmpdir(self))
        r.set_version('1.0.0')
        r.commit('初版')
        cmd = [sys.executable, str(SCRIPTS / 'plugin_eval.py'), 'gate', str(r.plugin)]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('结论：未过闸', p.stdout)
        r.add_run('r1', run_rec('1.0.0', r.fp()))
        p = subprocess.run(cmd + ['--json'], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(json.loads(p.stdout)['passed'])
        p = subprocess.run([sys.executable, str(SCRIPTS / 'plugin_eval.py'), 'gate', str(r.root / 'nope')],
                           capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 2)


if __name__ == '__main__':
    unittest.main()
