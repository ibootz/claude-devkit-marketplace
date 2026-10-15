"""票 10：条款清单的抽取、过期判定、增量重抽、退役与待审页写回（假 AI，不调模型）。"""
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import _support
from _support import tmpdir, write
from plugin_eval_lib import cli, clause_ai, clausereport, clauses, compare, pending, registry
from test_compare import FakeEval, passing_preflight

# hook：读插件根下的 rules.txt 原样输出，再附上每次都变的内容（时间、UUID、时间戳、临时 cwd、插件根路径）
HOOK_PY = r'''
import datetime, os, sys, time, uuid
root = os.environ["CLAUDE_PLUGIN_ROOT"]
sys.stdin.read()
text = open(os.path.join(root, "rules.txt"), encoding="utf-8").read()
extra = os.environ.get("PE_TEST_EXTRA", "")
print(text)
print("生成于 %s（%s），会话 %s，时间戳 %d / %d" % (datetime.datetime.now().isoformat(), time.strftime("%H:%M:%S"),
      uuid.uuid4(), int(time.time()), int(time.time() * 1000)))
print("当前目录 %s，插件在 %s，今天 %s" % (os.getcwd(), root, datetime.date.today().isoformat()))
'''
RANDOM_PY = 'import random, sys\nsys.stdin.read()\nprint("幸运数字 %d" % random.randint(0, 10 ** 6))\n'
SILENT_PY = 'import sys\nsys.stdin.read()\n'
RULES = '1. 回复一律用简体中文。\n2. 派子代理时写明 model 参数。\n'


def py_cmd(script):
    return '"%s" "${CLAUDE_PLUGIN_ROOT}/hooks/%s"' % (sys.executable, script)


def make_inject_plugin(root, rules=RULES, scripts=('inject.py',), events=('SessionStart',), name='demo-plugin',
                       cases=(('case-a', ['C001']),)):
    root = Path(root)
    write(root / '.claude-plugin' / 'plugin.json', json.dumps({'name': name, 'version': '1.0.0'}))
    write(root / 'rules.txt', rules)
    write(root / 'hooks' / 'inject.py', HOOK_PY)
    write(root / 'hooks' / 'lucky.py', RANDOM_PY)
    write(root / 'hooks' / 'silent.py', SILENT_PY)
    hooks = {}
    for ev in events:
        hooks[ev] = [{'matcher': '*', 'hooks': [{'type': 'command', 'command': py_cmd(s)} for s in scripts]}]
    write(root / 'hooks' / 'hooks.json', json.dumps({'hooks': hooks}))
    for c, tags in cases:
        write(root / 'evals' / c / 'prompt.md', '---\nname: %s\ntags: [%s]\n---\n做点事\n' % (c, ', '.join(tags)))
        write(root / 'evals' / c / 'graders' / 'g1.md', '---\ntype: regex\ntarget: last_message\npattern: ok\n---\n')
    return root


class FakeAI:
    """按调用顺序返回预设结果；记下每次的 prompt 与 schema。"""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, prompt, schema, model):
        self.calls.append({'prompt': prompt, 'schema': schema, 'model': model})
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r, {'model': model, 'cost_usd': 0.01, 'usage': {}, 'duration_ms': 1}


EXTRACT = {'clauses': [{'criterion': '回复用简体中文', 'events': ['SessionStart']},
                       {'criterion': '派子代理时写明 model 参数', 'events': ['SessionStart']}]}


def at(minute):
    return lambda: datetime(2026, 10, 15, 8, minute, tzinfo=timezone.utc)


class NormalizationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)

    def test_volatile_content_does_not_change_fingerprint(self):
        """构造用例：注入文字里有时间、时刻、日期、UUID、秒级与毫秒级时间戳、临时 cwd、插件根路径，两次指纹相同。"""
        plugin = make_inject_plugin(self.tmp / 'p')
        a = clauses.capture_injection(plugin, tmp_parent=self.tmp)
        b = clauses.capture_injection(plugin, tmp_parent=self.tmp)
        self.assertTrue(a.reliable, a.summary())
        self.assertEqual(a.fingerprint, b.fingerprint)
        for token in ('<DATETIME>', '<TIME>', '<UUID>', '<EPOCH>', '<DATE>', '<HOOK_TMP>', '${CLAUDE_PLUGIN_ROOT}'):
            self.assertIn(token, a.text)
        self.assertIn('回复一律用简体中文', a.text)
        self.assertNotIn(str(self.tmp), a.text)

    def test_fingerprint_tracks_text_only(self):
        plugin = make_inject_plugin(self.tmp / 'p')
        base = clauses.capture_injection(plugin, tmp_parent=self.tmp).fingerprint
        # 改脚本名与 matcher、加一个不注入的 hook：文字没变，指纹不变
        (plugin / 'hooks' / 'inject.py').rename(plugin / 'hooks' / 'renamed.py')
        write(plugin / 'hooks' / 'hooks.json', json.dumps({'hooks': {'SessionStart': [
            {'matcher': 'startup', 'hooks': [{'type': 'command', 'command': py_cmd('renamed.py')},
                                             {'type': 'command', 'command': py_cmd('silent.py')}]}]}}))
        cap = clauses.capture_injection(plugin, tmp_parent=self.tmp)
        self.assertEqual(cap.fingerprint, base)
        self.assertEqual(len(cap.silent), 1)   # 条件注入记为残余不确定
        # 改一句文字：指纹变
        write(plugin / 'rules.txt', RULES.replace('简体中文', '中文'))
        self.assertNotEqual(clauses.capture_injection(plugin, tmp_parent=self.tmp).fingerprint, base)

    def test_unnormalizable_randomness_marks_unreliable(self):
        plugin = make_inject_plugin(self.tmp / 'p', scripts=('inject.py', 'lucky.py'))
        cap = clauses.capture_injection(plugin, tmp_parent=self.tmp)
        self.assertFalse(cap.reliable)
        self.assertEqual(len(cap.unstable), 1)
        self.assertIn('lucky.py', cap.unstable[0])

    def test_failing_hook_marks_unreliable(self):
        """与 injection.run_hook 同口径：只有超时与退出码 2 算失败。"""
        plugin = make_inject_plugin(self.tmp / 'p')
        write(plugin / 'hooks' / 'hooks.json', json.dumps({'hooks': {'SessionStart': [
            {'hooks': [{'type': 'command', 'command': 'exit 2'}]}]}}))
        cap = clauses.capture_injection(plugin, tmp_parent=self.tmp)
        self.assertFalse(cap.reliable)
        self.assertIn('退出码 2', cap.failed[0])

    def test_nonzero_exit_with_output_still_counts_as_injection(self):
        plugin = make_inject_plugin(self.tmp / 'p')
        write(plugin / 'hooks' / 'fail1.py', 'import sys\nsys.stdin.read()\nprint("规则：退出码 1 也注入")\nsys.exit(1)\n')
        write(plugin / 'hooks' / 'hooks.json', json.dumps({'hooks': {'SessionStart': [
            {'hooks': [{'type': 'command', 'command': py_cmd('fail1.py')}]}]}}))
        cap = clauses.capture_injection(plugin, tmp_parent=self.tmp)
        self.assertTrue(cap.reliable, cap.summary())
        self.assertEqual(cap.failed, [])
        self.assertIn('退出码 1 也注入', cap.text)

    def test_normalize_text_rules(self):
        s = clauses.normalize_text('a  \r\n2026-10-15T08:01:02.5Z 2026年10月15日 1760515200 1760515200123 '
                                   'abcdef0123456789abcd 版本 2.1.300 与 4.1.0\n\n', home='/home/u')
        self.assertEqual(s, 'a\n<DATETIME> <DATE> <EPOCH> <EPOCH> <HEX> 版本 2.1.300 与 4.1.0')
        self.assertEqual(clauses.normalize_text('/home/u/x', home='/home/u'), '~/x')


class TagsTest(unittest.TestCase):
    def test_tag_forms(self):
        self.assertEqual(clauses._tags_from_text('name: x\ntags: [C001, "C002"]\n'), ['C001', 'C002'])
        self.assertEqual(clauses._tags_from_text('tags:\n  - C003\n  - C004\nmax_turns: 3\n'), ['C003', 'C004'])
        self.assertEqual(clauses._tags_from_text('tags: C005\n'), ['C005'])
        self.assertEqual(clauses._tags_from_text('name: x\n'), [])


class ValidateTest(unittest.TestCase):
    OLD = [{'id': 'C001', 'criterion': 'a', 'status': 'active'}, {'id': 'C002', 'criterion': 'b', 'status': 'active'},
           {'id': 'C003', 'criterion': 'c', 'status': 'retired'}]

    def check_bad(self, obj, needle):
        with self.assertRaises(clause_ai.ClauseAIError) as cm:
            clause_ai.validate_delta(dict({'added': [], 'rewritten': [], 'retired': []}, **obj), self.OLD)
        self.assertIn(needle, str(cm.exception))

    def test_rejects_bad_deltas(self):
        n = [{'ref': 'N1', 'criterion': 'x', 'events': []}]
        self.check_bad({'retired': [{'id': 'C003', 'reason': 'delete', 'replaced_by': [], 'rehang_hint': ''}]}, '已退役')
        self.check_bad({'added': n, 'retired': [{'id': 'C001', 'reason': 'split', 'replaced_by': ['N1'],
                                                 'rehang_hint': ''}]}, '至少两条')
        self.check_bad({'added': n, 'retired': [{'id': 'C001', 'reason': 'delete', 'replaced_by': ['N1'],
                                                 'rehang_hint': ''}]}, '不应写替代')
        self.check_bad({'retired': [{'id': 'C001', 'reason': 'merge', 'replaced_by': ['N9'], 'rehang_hint': ''}]},
                       'N9')
        self.check_bad({'retired': [{'id': 'C001', 'reason': 'criterion-changed', 'replaced_by': ['C003'],
                                     'rehang_hint': ''}]}, 'C003')
        self.check_bad({'added': [{'ref': 'C9', 'criterion': 'x', 'events': []}]}, 'ref')
        self.check_bad({'rewritten': [{'id': 'C001', 'criterion': 'z'}],
                        'retired': [{'id': 'C001', 'reason': 'delete', 'replaced_by': [], 'rehang_hint': ''}]}, '两次')


class ClaudeCallerTest(unittest.TestCase):
    def fake_run(self, rc, payload, stderr=b''):
        def run(cmd, **kw):
            self.cmd, self.kw = cmd, kw
            return subprocess.CompletedProcess(cmd, rc, json.dumps(payload).encode('utf-8'), stderr)
        return run

    def test_success_reads_structured_output(self):
        ai = clause_ai.claude_caller('/x/claude', run=self.fake_run(0, {
            'is_error': False, 'structured_output': {'clauses': []}, 'total_cost_usd': 0.02,
            'usage': {'input_tokens': 3, 'output_tokens': 4}}))
        obj, meta = ai('提示', clause_ai.EXTRACT_SCHEMA, 'claude-fable-5-1')
        self.assertEqual(obj, {'clauses': []})
        self.assertEqual(meta['cost_usd'], 0.02)
        for flag in ('-p', '--json-schema', '--no-session-persistence', '--strict-mcp-config'):
            self.assertIn(flag, self.cmd)
        self.assertEqual(self.cmd[self.cmd.index('--tools') + 1], '')
        self.assertEqual(self.cmd[self.cmd.index('--model') + 1], 'claude-fable-5-1')
        self.assertEqual(self.kw['input'].decode('utf-8'), '提示')

    def test_usage_limit_reported(self):
        ai = clause_ai.claude_caller('/x/claude', run=self.fake_run(1, {'is_error': True,
                                                                       'result': 'Claude usage limit reached'}))
        with self.assertRaises(clause_ai.ClauseAIError) as cm:
            ai('p', {}, 'm')
        self.assertIn('撞订阅用量限制', str(cm.exception))


class LifecycleTest(unittest.TestCase):
    """端到端：clauses 单跑抽取 → 待审页确认 → 对照（不变 / 改一句 / 复用 / 拆分 / 打回）。"""

    def setUp(self):
        self.tmp = tmpdir(self)
        self.data = self.tmp / 'data'
        self.repo = self.tmp / 'repo'
        self.plugin = make_inject_plugin(self.repo / 'plugins' / 'demo-plugin',
                                         cases=(('case-a', ['C001']), ('case-b', ['C002', 'discipline'])))
        registry.register(self.data, 'demo-plugin', self.repo)
        self.sandboxes = self.tmp / 'sandboxes'
        self.sandboxes.mkdir()
        self.assembly = self.tmp / 'assembly'
        self.assembly.mkdir()
        self.root = self.repo / 'plugin-evals' / 'demo-plugin'

    def compare(self, ai, minute):
        return compare.run_compare(
            self.data, 'demo-plugin', runs=1, concurrency=1, claude='/fake/claude',
            runner=FakeEval(self.sandboxes, {'none': False, 'current': True}), env=None,
            tmp_parent=self.assembly, sandbox_roots=[self.sandboxes], log=lambda *a: None,
            preflight_check=passing_preflight, clause_ai=ai, now=at(minute))

    def page(self, run_id):
        return pending.generate(self.data, 'demo-plugin', run_id=run_id, now=at(59))

    def reply(self, page, decisions):
        code = 'PE1 %s %s %s' % (page.run_id, page.page_id, ' '.join(decisions))
        return pending.apply_reply(self.data, 'demo-plugin', code, now=at(59))

    def clause_no(self, page):
        return [it['no'] for it in page.items if it['type'] == 'clause-list']

    def extract_and_confirm(self):
        ai = FakeAI(EXTRACT)
        cc, run_dir, page = clauses.run_clauses(self.data, 'demo-plugin', ai=ai, tmp_parent=self.assembly,
                                                now=at(0), log=lambda *a: None)
        self.assertEqual(cc['status'], clauses.STATUS_PENDING)
        self.assertEqual(len(ai.calls), 1)
        self.assertIn('回复一律用简体中文', ai.calls[0]['prompt'])
        self.assertEqual(ai.calls[0]['model'], clause_ai.DEFAULT_MODEL)
        self.assertEqual([it['type'] for it in page.items], ['clause-list'])   # 单跑只有这 1 项
        self.assertFalse((self.root / clauses.LIST_FILE).exists())               # 确认前不落盘
        res = self.reply(page, ['1A'])
        self.assertIn('plugin-evals/demo-plugin/clauses.json', res.changed_files)
        return run_dir

    def load_list(self):
        return json.loads((self.root / clauses.LIST_FILE).read_text(encoding='utf-8'))

    def test_extract_confirm_writes_list_with_ids_criteria_fingerprint(self):
        run_dir = self.extract_and_confirm()
        lst = self.load_list()
        self.assertEqual([(c['id'], c['criterion'], c['status']) for c in lst['clauses']],
                         [('C001', '回复用简体中文', 'active'), ('C002', '派子代理时写明 model 参数', 'active')])
        cap = clauses.capture_injection(self.plugin, tmp_parent=self.assembly)
        self.assertEqual(lst['injection_fingerprint'], cap.fingerprint)
        self.assertEqual((self.root / clauses.SNAPSHOT_FILE).read_text(encoding='utf-8'), cap.text)
        rec = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual(rec['kind'], 'clauses')
        self.assertEqual(rec['clause_check']['decision']['status'], 'confirmed')
        self.assertIn('条款清单变更已确认', (run_dir / 'report.md').read_text(encoding='utf-8'))
        # 单跑只在尚无清单时执行：已有清单时拒绝，不调 AI、不建运行目录（重抽是对照的第一步）
        ai = FakeAI()
        before = sorted(p.name for p in (self.root / 'runs').iterdir())
        with self.assertRaises(clauses.ClauseError) as cm:
            clauses.run_clauses(self.data, 'demo-plugin', ai=ai, tmp_parent=self.assembly, now=at(1),
                                log=lambda *a: None)
        self.assertIn('已有条款清单，重抽是跑对照的第一步，请改跑 compare', str(cm.exception))
        self.assertEqual(ai.calls, [])
        self.assertEqual(sorted(p.name for p in (self.root / 'runs').iterdir()), before)
        # 确认后 clause-check.json 的 status 同步改成 confirmed
        cc = json.loads((run_dir / clauses.CHECK_FILE).read_text(encoding='utf-8'))
        self.assertEqual(cc['status'], clauses.STATUS_CONFIRMED)
        self.assertEqual(rec['clause_check']['status'], clauses.STATUS_CONFIRMED)
        self.assertIn('清单变更已在待审页确认', '\n'.join(clausereport.section_lines(rec)))

    def test_unchanged_text_compare_does_not_reextract_or_add_pending_item(self):
        self.extract_and_confirm()
        ai = FakeAI()
        res = self.compare(ai, 10)
        self.assertEqual(ai.calls, [])
        rec = res.record
        self.assertEqual(rec['clause_check']['status'], clauses.STATUS_UP_TO_DATE)
        self.assertEqual(rec['clause_list_fingerprint'], clauses.list_fingerprint(self.load_list()))
        self.assertFalse((res.run_dir / clauses.PROPOSAL_FILE).exists())
        page = self.page(res.run_dir.name)
        self.assertEqual([it['type'] for it in page.items], ['report-review'])
        report = (res.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertNotIn('条款清单待确认', report)
        self.assertIn('| C001 | 回复用简体中文 | case-a |', report)

    def test_one_sentence_change_yields_one_incremental_item_and_banner(self):
        self.extract_and_confirm()
        write(self.plugin / 'rules.txt', RULES + '3. 结论先行。\n')
        delta = {'added': [{'ref': 'N1', 'criterion': '回复先给结论', 'events': ['SessionStart']}],
                 'rewritten': [], 'retired': []}
        ai = FakeAI(delta)
        res = self.compare(ai, 10)
        self.assertEqual(len(ai.calls), 1)
        prompt = ai.calls[0]['prompt']
        self.assertIn('+3. 结论先行。', prompt)                 # 只给 diff …
        self.assertIn('"C001"', prompt)                          # … 加旧清单
        self.assertEqual(ai.calls[0]['schema'], clause_ai.DELTA_SCHEMA)
        cc = res.record['clause_check']
        self.assertEqual((cc['status'], cc['stale'], cc['proposal_kind']), (clauses.STATUS_PENDING, True, 'delta'))
        self.assertTrue(res.record['complete'])                  # 未确认照跑
        page = self.page(res.run_dir.name)
        self.assertEqual(sorted(it['type'] for it in page.items), ['clause-list', 'report-review'])
        report = (res.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn('> **条款清单待确认**', report)
        self.assertIn('| C003 | 回复先给结论 | 无用例（新条款，清单待确认） |', report)
        # 确认后清单只多一条新 id，旧 id 不动
        self.reply(page, ['%dA' % self.clause_no(page)[0]])
        self.assertEqual([c['id'] for c in self.load_list()['clauses']], ['C001', 'C002', 'C003'])
        self.assertIn('条款清单变更已确认', (res.run_dir / 'report.md').read_text(encoding='utf-8'))

    def test_unconfirmed_proposal_is_reused_not_reextracted(self):
        self.extract_and_confirm()
        write(self.plugin / 'rules.txt', RULES + '3. 结论先行。\n')
        delta = {'added': [{'ref': 'N1', 'criterion': '回复先给结论', 'events': ['SessionStart']}],
                 'rewritten': [], 'retired': []}
        first = self.compare(FakeAI(delta), 10)
        ai = FakeAI()
        second = self.compare(ai, 11)
        self.assertEqual(ai.calls, [])
        self.assertEqual(second.record['clause_check']['reused_from'], first.run_dir.name)
        prop = json.loads((second.run_dir / clauses.PROPOSAL_FILE).read_text(encoding='utf-8'))
        self.assertEqual([a['id'] for a in prop['added']], ['C003'])
        # 在新页上确认后，旧页的条款项作废（清单已变）
        p2 = self.page(second.run_dir.name)
        self.reply(p2, ['%dA' % self.clause_no(p2)[0]])
        p1 = self.page(first.run_dir.name)
        self.assertEqual(self.clause_no(p1), [])

    def test_split_retires_old_id_with_replacements_and_never_reallocates(self):
        self.extract_and_confirm()
        write(self.plugin / 'rules.txt', RULES.replace('2. 派子代理时写明 model 参数。',
                                                       '2. 派子代理时写明 model。\n3. 派子代理时写明 name。'))
        delta = {'added': [{'ref': 'N1', 'criterion': '派子代理时写明 model 参数', 'events': ['SessionStart']},
                           {'ref': 'N2', 'criterion': '派子代理时写明 name 参数', 'events': ['SessionStart']}],
                 'rewritten': [{'id': 'C001', 'criterion': '回复一律用简体中文'}],
                 'retired': [{'id': 'C002', 'reason': 'split', 'replaced_by': ['N1', 'N2'],
                              'rehang_hint': '考 model 的改挂到N1，考 name 的改挂 N2'}]}
        res = self.compare(FakeAI(delta), 10)
        report = (res.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn('C002（拟退役 → C003、C004）', report)
        page = self.page(res.run_dir.name)
        self.reply(page, ['%dA' % self.clause_no(page)[0]])
        lst = self.load_list()
        by_id = {c['id']: c for c in lst['clauses']}
        self.assertEqual(by_id['C002']['status'], 'retired')
        self.assertEqual(by_id['C002']['retire_reason'], 'split')
        self.assertEqual(by_id['C002']['replaced_by'], ['C003', 'C004'])
        self.assertEqual(by_id['C001']['criterion'], '回复一律用简体中文')            # 改写保留 id
        self.assertEqual(by_id['C001']['history'][0]['criterion'], '回复用简体中文')
        self.assertEqual(clauses.retired_ids(lst), ['C002'])
        # 旧 id 不再分配：下一个号从最大号往后
        self.assertEqual(clauses.allocate_ids(self.repo, 'demo-plugin', 2), ['C005', 'C006'])
        # 挂在 C002 上的用例出改挂建议
        rehang = json.loads((self.root / clauses.REHANG_FILE).read_text(encoding='utf-8'))
        self.assertEqual([(s['case'], s['retired_id'], s['suggestion']) for s in rehang['suggestions']],
                         [('evals/case-b', 'C002', '从 C003、C004 中选一条改挂')])
        self.assertEqual(rehang['suggestions'][0]['ai_hint'], '考 model 的改挂到C003，考 name 的改挂 C004')
        # 下一次对照：退役条款仍列在报告里，标出挂着的用例待改挂
        res2 = self.compare(FakeAI(), 11)
        report2 = (res2.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn('退役（split）→ C003、C004；仍挂 1 个用例，待改挂', report2)

    def test_reject_keeps_list_and_next_run_reextracts_with_fresh_ids(self):
        self.extract_and_confirm()
        before = self.load_list()
        write(self.plugin / 'rules.txt', RULES + '3. 结论先行。\n')
        delta = {'added': [{'ref': 'N1', 'criterion': '回复先给结论', 'events': ['SessionStart']}],
                 'rewritten': [], 'retired': []}
        res = self.compare(FakeAI(delta), 10)
        page = self.page(res.run_dir.name)
        self.reply(page, ['%dB' % self.clause_no(page)[0]])
        self.assertEqual(self.load_list(), before)
        self.assertIn('条款清单变更已打回', (res.run_dir / 'report.md').read_text(encoding='utf-8'))
        cc = json.loads((res.run_dir / clauses.CHECK_FILE).read_text(encoding='utf-8'))
        self.assertEqual(cc['status'], clauses.STATUS_REJECTED)
        rec = json.loads((res.run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertIn('条款清单变更已打回', '\n'.join(clausereport.banner_lines(rec)))
        self.assertIn('提案已打回，未入清单', '\n'.join(clausereport.section_lines(rec)))
        ai = FakeAI(delta)
        res2 = self.compare(ai, 11)
        self.assertEqual(len(ai.calls), 1)                       # 打回的不复用，重新抽
        prop = json.loads((res2.run_dir / clauses.PROPOSAL_FILE).read_text(encoding='utf-8'))
        self.assertEqual([a['id'] for a in prop['added']], ['C004'])   # 被打回提案用过的 C003 也不再分配

    def test_pending_without_run_picks_clauses_run_and_lists_it_as_earlier(self):
        """pending 不带 --run 时也认 kind=clauses 的运行；较早仍有待判项的 clauses 运行列进「较早待审」。"""
        _, run_dir, _ = clauses.run_clauses(self.data, 'demo-plugin', ai=FakeAI(EXTRACT), tmp_parent=self.assembly,
                                            now=at(0), log=lambda *a: None)
        page = pending.generate(self.data, 'demo-plugin', now=at(59))
        self.assertEqual(page.run_id, run_dir.name)
        self.assertEqual([it['type'] for it in page.items], ['clause-list'])
        res = self.compare(FakeAI(), 10)        # 清单未确认：对照沿用这份提案，不重抽
        earlier = pending._earlier_with_items(self.data, self.repo, res.run_dir, pending._REGISTRY)
        self.assertIn(run_dir.name, [rid for rid, _ in earlier])

    def test_rejected_pair_is_never_reused_even_if_another_run_has_it_pending(self):
        """两次对照产出同一组（基线清单、新指纹）的提案：在其中一份上打回后，另一份未裁定的也不再复用。"""
        self.extract_and_confirm()
        write(self.plugin / 'rules.txt', RULES + '3. 结论先行。\n')
        delta = {'added': [{'ref': 'N1', 'criterion': '回复先给结论', 'events': ['SessionStart']}],
                 'rewritten': [], 'retired': []}
        first = self.compare(FakeAI(delta), 10)
        # 构造：第二个运行独立抽出同一组提案（不复用第一份）
        orig = clauses.find_reusable
        clauses.find_reusable = lambda *a, **kw: None
        try:
            second = self.compare(FakeAI(delta), 11)
        finally:
            clauses.find_reusable = orig
        p1 = self.page(first.run_dir.name)
        self.reply(p1, ['%dB' % self.clause_no(p1)[0]])          # 在较早那份上打回
        ai = FakeAI(delta)
        third = self.compare(ai, 12)
        self.assertEqual(len(ai.calls), 1)                       # 不复用第二份（同一组已被打回），重新抽
        self.assertIsNone(third.record['clause_check']['reused_from'])
        self.assertNotEqual(second.run_dir, third.run_dir)

    def test_corrupt_list_does_not_abort_compare(self):
        self.extract_and_confirm()
        write(self.root / clauses.LIST_FILE, '{坏的 JSON')
        res = self.compare(FakeAI(), 10)
        self.assertTrue(res.record['complete'])
        cc = res.record['clause_check']
        self.assertEqual(cc['status'], clauses.STATUS_ERROR)
        self.assertIsNone(cc['list_fingerprint'])
        self.assertIsNone(res.record['clause_list_fingerprint'])
        self.assertIn('条款清单这一步出错', (res.run_dir / 'report.md').read_text(encoding='utf-8'))
        self.assertEqual(clauses.used_ids(self.repo, 'demo-plugin'), {'C001', 'C002'})   # 清单损坏时 used_ids 不抛，按提案避让

    def test_ai_failure_does_not_abort_compare(self):
        self.extract_and_confirm()
        write(self.plugin / 'rules.txt', RULES + '3. 结论先行。\n')
        res = self.compare(FakeAI(clause_ai.ClauseAIError('撞订阅用量限制或限流：x')), 10)
        self.assertTrue(res.record['complete'])
        self.assertEqual(res.record['clause_check']['status'], clauses.STATUS_AI_ERROR)
        self.assertIn('条款清单已过期，重抽失败', (res.run_dir / 'report.md').read_text(encoding='utf-8'))
        self.assertEqual(self.clause_no(self.page(res.run_dir.name)), [])

    def test_no_list_compare_extracts_and_report_lists_new_clauses_without_cases(self):
        res = self.compare(FakeAI(EXTRACT), 10)
        cc = res.record['clause_check']
        self.assertEqual((cc['status'], cc['stale'], cc['proposal_kind']), (clauses.STATUS_PENDING, False, 'extract'))
        self.assertIsNone(res.record['clause_list_fingerprint'])
        report = (res.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn('尚无条款清单，本次已整份抽取 2 条', report)
        self.assertIn('| C001 | 回复用简体中文 | 无用例（新条款，清单待确认） |', report)

    def test_resume_keeps_clause_check_without_reextracting(self):
        from plugin_eval_lib import resume
        from test_resume import ScriptedEval
        outcomes = {(arm, c): [True] * 4 for arm in ('none', 'current') for c in ('case-a', 'case-b')}
        fake = ScriptedEval(self.sandboxes, outcomes, crash_on='current')
        ai = FakeAI(EXTRACT)
        with self.assertRaises(RuntimeError):
            compare.run_compare(self.data, 'demo-plugin', runs=1, concurrency=1, claude='/fake/claude', runner=fake,
                                env=None, tmp_parent=self.assembly, sandbox_roots=[self.sandboxes],
                                log=lambda *a: None, preflight_check=passing_preflight, clause_ai=ai, now=at(10))
        run_dir = next((self.root / 'runs').iterdir())
        res = resume.resume_run(self.data, run_dir, claude='/fake/claude', runner=fake, tmp_parent=self.assembly,
                                sandbox_roots=[self.sandboxes], log=lambda *a: None,
                                preflight_check=passing_preflight)
        self.assertEqual(len(ai.calls), 1)                       # 续跑不重抽
        self.assertTrue(res.record['complete'])
        self.assertEqual(res.record['clause_check']['status'], clauses.STATUS_PENDING)
        self.assertIn('> **条款清单待确认**', (run_dir / 'report.md').read_text(encoding='utf-8'))

    def test_cli_clauses_subcommand(self):
        out, err = io.StringIO(), io.StringIO()
        orig = clauses.default_ai
        clauses.default_ai = lambda **kw: FakeAI(EXTRACT)
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(['--data-dir', str(self.data), 'clauses', 'demo-plugin'])
        finally:
            clauses.default_ai = orig
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn('清单变更（首次抽取）：新增 2、改写 0、退役 0', out.getvalue())
        self.assertIn('--run ', out.getvalue())


class ReportTest(unittest.TestCase):
    def test_no_injection_renders_nothing(self):
        rec = {'clause_check': {'status': 'no-injection'}}
        self.assertEqual(clausereport.banner_lines(rec) + clausereport.section_lines(rec), [])

    def test_record_fields_absent_file(self):
        self.assertEqual(clauses.record_fields(Path('/nonexistent-dir-pe10')), {})


if __name__ == '__main__':
    unittest.main()
