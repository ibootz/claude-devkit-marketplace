"""票 11：草稿区、退役用例退回、待审批次与写回、AI 起草（假 AI，不调模型）、草稿不进对照。"""
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import _support
from _support import tmpdir, write
from plugin_eval_lib import casefiles, clause_ai, clauses, cli, compare, drafter, drafts, gate, pending, registry
from test_compare import FakeEval, passing_preflight

NAME = 'demo-plugin'
SILENT = lambda *a: None


def at(minute):
    return lambda: datetime(2026, 10, 15, 8, minute, tzinfo=timezone.utc)


def clause(cid, criterion, status='active', **kw):
    c = {'id': cid, 'criterion': criterion, 'events': ['SessionStart'], 'status': status}
    c.update(kw)
    return c


def case_spec(slug, tags, prompt='做点事', **kw):
    s = {'slug': slug, 'tags': tags, 'prompt': prompt, 'max_turns': 4,
         'graders': [{'name': 'ok', 'type': 'regex', 'pattern': 'ok'}]}
    s.update(kw)
    return s


class FakeAI:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, prompt, schema, model):
        self.calls.append({'prompt': prompt, 'schema': schema, 'model': model})
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r, {'model': model, 'cost_usd': 0.02, 'usage': {}, 'duration_ms': 1}


class Base(unittest.TestCase):
    plugin_rel = Path('plugins') / NAME

    def setUp(self):
        self.tmp = tmpdir(self)
        self.data = self.tmp / 'data'
        self.repo = self.tmp / 'repo'
        self.plugin = self.repo / self.plugin_rel
        write(self.plugin / '.claude-plugin' / 'plugin.json', json.dumps({'name': NAME, 'version': '1.0.0'}))
        write(self.plugin / 'rules.txt', 'SENTINEL-INJECTION 原文不该给起草者\n')
        registry.register(self.data, NAME, self.repo)
        self.root = self.repo / 'plugin-evals' / NAME
        self.drafts_root = self.root / 'drafts'

    def set_list(self, *cl):
        write(self.root / clauses.LIST_FILE, json.dumps({'schema_version': 1, 'plugin': NAME, 'clauses': list(cl)}))

    def add_case(self, where, slug, tags, meta=None, **kw):
        d = (self.plugin / 'evals' if where == 'evals' else self.drafts_root) / slug
        casefiles.write_case(d, case_spec(slug, tags, **kw))
        if meta is not None:
            drafts.write_meta(d, dict({'case': slug, 'source': 'ai', 'category': 'discipline', 'status': 'open'}, **meta))
        return d

    def batch(self, minute=30, **kw):
        return drafts.create_batch(self.data, NAME, now=at(minute), log=SILENT, **kw)

    def reply(self, page, decisions, minute=40):
        code = 'PE1 %s %s %s' % (page.run_id, page.page_id, ' '.join(decisions))
        return pending.apply_reply(self.data, NAME, code, now=at(minute))


class RehangTest(Base):
    def setUp(self):
        super().setUp()
        self.set_list(clause('C001', '回复用中文'), clause('C002', '旧', 'retired', retire_reason='criterion-changed',
                                                        replaced_by=['C003']),
                      clause('C003', '新'), clause('C004', '删', 'retired', retire_reason='delete'),
                      clause('C005', '拆', 'retired', retire_reason='split', replaced_by=['C001', 'C003']))
        self.add_case('evals', 'on-c002', ['discipline', 'C002'],
                      judge=[{'id': 'j', 'criterion': 'x', 'rule': 'ok', 'clause': 'C002'}])
        self.add_case('evals', 'on-c004', ['discipline', 'C004'])
        self.add_case('evals', 'on-c005', ['discipline', 'C005'])
        self.add_case('drafts', 'draft-c002', ['discipline', 'C002'], meta={})
        sug = lambda case, rid, reason, repl, hint='': {
            'case': case, 'retired_id': rid, 'reason': reason, 'replaced_by': repl, 'suggestion': 's',
            'ai_hint': hint, 'from_run': 'r1', 'created_at': 't', 'status': 'open'}
        write(self.root / clauses.REHANG_FILE, json.dumps({'schema_version': 1, 'plugin': NAME, 'suggestions': [
            sug('evals/on-c002', 'C002', 'criterion-changed', ['C003']),
            sug('evals/on-c004', 'C004', 'delete', []),
            sug('evals/on-c005', 'C005', 'split', ['C001', 'C003'], hint='用例测的是语言，改挂 C001'),
            sug('drafts/draft-c002', 'C002', 'criterion-changed', ['C003']),
            sug('evals/gone', 'C002', 'criterion-changed', ['C003'])]}))

    def test_sync_moves_retags_and_marks_suggestions(self):
        done = dict(drafts.sync_rehang(self.repo, NAME, self.plugin, now=at(1)(), log=SILENT))
        self.assertEqual(done, {'on-c002': 'moved', 'on-c004': 'moved', 'on-c005': 'moved',
                                'draft-c002': 'annotated', 'gone': 'missing'})
        self.assertFalse((self.plugin / 'evals' / 'on-c002').exists())
        moved = self.drafts_root / 'on-c002'
        self.assertEqual(clauses.case_tags(moved), ['discipline', 'C003'])
        self.assertIn('clause: C003', (moved / 'judge' / 'j.md').read_text(encoding='utf-8'))
        meta = drafts.read_meta(moved)
        self.assertEqual((meta['source'], meta['rehang'][0]['action']), ('rehang', 'retag'))
        self.assertEqual(drafts.read_meta(self.drafts_root / 'on-c004')['rehang'][0]['action'], 'delete')
        self.assertEqual(clauses.case_tags(self.drafts_root / 'on-c005'), ['discipline', 'C001'])  # AI 提示点名其一
        self.assertEqual(clauses.case_tags(self.drafts_root / 'draft-c002'), ['discipline', 'C003'])
        doc = json.loads((self.root / clauses.REHANG_FILE).read_text(encoding='utf-8'))
        self.assertEqual([s['status'] for s in doc['suggestions']], ['moved', 'moved', 'moved', 'annotated', 'missing'])
        self.assertEqual(drafts.sync_rehang(self.repo, NAME, self.plugin, log=SILENT), [])   # 处理过的不再处理

    def test_delete_item_and_retag_item_on_page(self):
        drafts.sync_rehang(self.repo, NAME, self.plugin, now=at(1)(), log=SILENT)
        run_dir, page, _ = self.batch()
        types = {it['payload']['case']: (it['no'], it['type']) for it in page.items}
        self.assertEqual(types['on-c004'][1], 'case-draft-delete')
        self.assertEqual(types['on-c002'][1], 'case-draft')
        res = self.reply(page, ['%dA' % types['on-c004'][0], '%dA' % types['on-c002'][0]])
        self.assertFalse((self.drafts_root / 'on-c004' / 'prompt.md').exists())
        self.assertTrue((self.plugin / 'evals' / 'on-c002' / 'prompt.md').is_file())
        self.assertFalse((self.plugin / 'evals' / 'on-c002' / drafts.META_FILE).exists())
        self.assertTrue(any('baseline' in w for w in res.warnings))


    def test_list_is_read_only(self):
        """审查 11 应修 3：drafts list 不退回退役用例、不改 clause-rehang.json；page 才退回。"""
        before = (self.root / clauses.REHANG_FILE).read_text(encoding='utf-8')
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--data-dir', str(self.data), 'drafts', 'list', NAME]), 0)
        self.assertTrue((self.plugin / 'evals' / 'on-c002' / 'prompt.md').is_file())
        self.assertEqual((self.root / clauses.REHANG_FILE).read_text(encoding='utf-8'), before)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--data-dir', str(self.data), 'drafts', 'page', NAME]), 0)
        self.assertFalse((self.plugin / 'evals' / 'on-c002').exists())


class BatchTest(Base):
    def setUp(self):
        super().setUp()
        self.set_list(*[clause('C%03d' % i, '条款 %d' % i) for i in range(1, 15)])

    def test_page_limit_priority_and_writeback(self):
        for i in range(1, 13):
            self.add_case('drafts', 'd%02d' % i, ['discipline', 'C%03d' % i], meta={})
        # C011 在离线对照里已证明有差；C012 在复盘里命中过；d05 自带 probe 实测证据
        self.add_case('evals', 'proven', ['discipline', 'C011'])
        write(self.root / 'runs' / '20261014T000000Z-0.9.0-compare' / 'run.json',
              json.dumps({'kind': 'compare', 'delta': {'cases': {'proven': 0.5}}}))
        write(self.root / 'reviews' / '2026-10-14.json', json.dumps({'candidates': [{'clause_ids': ['C012']}]}))
        drafts.write_meta(self.drafts_root / 'd05', {'case': 'd05', 'source': 'history', 'category': 'discipline',
                                                    'evidence': {'proven_delta': 0.67}})
        run_dir, page, cls = self.batch()
        cases = [it['payload']['case'] for it in page.items]
        self.assertEqual(len(cases), pending.PAGE_LIMIT)
        self.assertEqual(cases[:3], ['d05', 'd11', 'd12'])
        rec = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual(rec['kind'], 'drafts')
        self.assertEqual(len(rec['not_on_page']['ready_beyond_limit']), 2)
        self.assertIn('d05', (run_dir / 'report.md').read_text(encoding='utf-8'))
        html = page.html_path.read_text(encoding='utf-8')
        self.assertIn('用例草稿', html)
        self.assertIn('条款 5', html)           # 页上给出挂的条款的判定标准

        # 页没写回前，第二批不收第一批页上的草稿
        _, page2, _ = self.batch(minute=31)
        self.assertEqual(sorted(it['payload']['case'] for it in page2.items), sorted(rec['not_on_page']['ready_beyond_limit']))

        no = {it['payload']['case']: it['no'] for it in page.items}
        self.reply(page, ['%dA' % no['d05'], '%dB' % no['d11']])
        moved = self.plugin / 'evals' / 'd05'
        self.assertEqual(casefiles.check_case_dir(moved), [])
        self.assertEqual(clauses.case_tags(moved), ['discipline', 'C005'])
        self.assertEqual([p for p in (self.drafts_root / 'd05').rglob('*') if p.is_file()], [])
        drafts.prune_empty(self.repo, NAME)                       # 留下的空目录在下一次 drafts 命令时清
        self.assertFalse((self.drafts_root / 'd05').exists())
        self.assertEqual(drafts.read_meta(self.drafts_root / 'd11')['status'], 'rejected')
        cls = drafts.classify(self.repo, NAME, self.plugin)
        self.assertIn('d11', [d.case for d, _ in cls['rejected']])
        self.assertNotIn('d05', [d.case for d, _, _ in cls['ready']])

    def test_unlinked_and_broken_drafts_stay_off_page(self):
        self.add_case('drafts', 'orphan', ['discipline'], meta={})
        self.add_case('drafts', 'skill-ok', ['skill-trigger', 'skill:x'], meta={'category': 'skill-trigger'})
        d = self.add_case('drafts', 'broken', ['discipline', 'C001'], meta={})
        (d / 'graders' / 'ok.md').unlink()
        run_dir, page, cls = self.batch()
        self.assertEqual([it['payload']['case'] for it in page.items], ['skill-ok'])
        rec = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual([x['case'] for x in rec['not_on_page']['needs_link']], ['orphan'])
        self.assertEqual([x['case'] for x in rec['not_on_page']['broken']], ['broken'])

    def test_pending_without_run_picks_drafts_run_and_gate_skips_it(self):
        self.add_case('drafts', 'd01', ['discipline', 'C001'], meta={})
        run_dir, page, _ = self.batch()
        page2 = pending.generate(self.data, NAME, now=at(45))
        self.assertEqual(page2.run_id, run_dir.name)
        self.assertIn('drafts', gate.SKIPPED_KINDS)
        self.assertIn('baseline', gate.SKIPPED_KINDS)

    def test_cli_list_and_page(self):
        self.add_case('drafts', 'd01', ['discipline', 'C001'], meta={})
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--data-dir', str(self.data), 'drafts', 'list', NAME]), 0)
            self.assertEqual(cli.main(['--data-dir', str(self.data), 'drafts', 'page', NAME]), 0)
        self.assertIn('可审', out.getvalue())
        self.assertIn('pending %s --reply' % NAME, out.getvalue())


class DraftsNotInCompareTest(Base):
    def run_compare(self):
        sandboxes, assembly = self.tmp / 'sb', self.tmp / 'asm'
        sandboxes.mkdir()
        assembly.mkdir()
        fake = FakeEval(sandboxes, {'none': False, 'current': True})
        seen = []
        orig = fake.__call__

        def spy(cmd, cwd, env, log_dir):
            arm_dir = Path(cmd[3])
            seen.append(sorted(p.relative_to(arm_dir).as_posix() for p in arm_dir.rglob('prompt.md')))
            return orig(cmd, cwd, env, log_dir)
        res = compare.run_compare(self.data, NAME, runs=1, concurrency=1, claude='/fake/claude', runner=spy,
                                  tmp_parent=assembly, sandbox_roots=[sandboxes], log=SILENT,
                                  preflight_check=passing_preflight, use_judge=False, now=at(50),
                                  clause_ai=FakeAI({'clauses': [{'criterion': 'x', 'events': ['SessionStart']}]}))
        return res, seen

    def test_drafts_never_reach_any_arm(self):
        self.set_list(clause('C001', 'x'))
        self.add_case('evals', 'real', ['discipline', 'C001'])
        self.add_case('drafts', 'draft-only', ['discipline', 'C001'], meta={})
        res, seen = self.run_compare()
        self.assertEqual(res.record['cases'], ['real'])
        self.assertTrue(seen)
        for arm in seen:
            self.assertEqual(arm, ['evals/real/prompt.md'])


class DraftsNotInCompareAtRepoRootTest(DraftsNotInCompareTest):
    plugin_rel = Path('.')


class DrafterTest(Base):
    def setUp(self):
        super().setUp()
        self.set_list(clause('C001', '派子代理时写明 model'), clause('C002', '回复用中文'), clause('C003', '先读后改'),
                      clause('C004', '退役', 'retired', retire_reason='delete'))
        self.add_case('evals', 'covered', ['discipline', 'C002'])
        write(self.plugin / 'skills' / 'sk' / 'SKILL.md', '---\nname: sk\ndescription: 中文消歧\n---\n正文 BODY-SECRET\n')
        write(self.plugin / 'agents' / 'helper.md', '---\nname: helper\ndescription: 帮手\n---\n只读检索，回摘要\n')

    def test_gaps(self):
        keys = [g['key'] for g in drafter.gaps(self.repo, NAME, self.plugin)]
        self.assertEqual(keys, ['clause:C001', 'clause:C003', 'skill-trigger:sk', 'skill-no-trigger:sk',
                                'agent-dispatch:helper', 'agent-no-dispatch:helper', 'agent-follow:helper'])
        g = {x['key']: x for x in drafter.gaps(self.repo, NAME, self.plugin)}
        self.assertEqual((g['skill-trigger:sk']['need'], g['agent-follow:helper']['need']), (2, 1))
        # 基线已满足的条款要诱导用例，≥ 2 种手法
        casefiles.set_tags(self.plugin / 'evals' / 'covered', ['discipline', 'C002', 'baseline-satisfied'])
        self.add_case('drafts', 'ind1', ['induced', 'technique:task-pressure', 'C002'], meta={})
        g = {x['key']: x for x in drafter.gaps(self.repo, NAME, self.plugin)}
        self.assertEqual(g['induced:C002']['need'], 1)
        self.assertNotIn('task-pressure', g['induced:C002']['techniques'])
        # 判为离线评不了的条款不再重试，--clauses 点名才重试
        drafter.save_skips(self.repo, NAME, {'clause:C003': {'code': 'needs-user-reply', 'reason': 'r'}})
        self.assertNotIn('clause:C003', [x['key'] for x in drafter.gaps(self.repo, NAME, self.plugin)])
        self.assertEqual([x['key'] for x in drafter.gaps(self.repo, NAME, self.plugin, only={'C003'})], ['clause:C003'])

    def test_rejected_draft_rewritten_only_when_clause_named(self):
        """B 批集成定稿第 3 条：打回的草稿自动起草时算已覆盖；--clauses 点名时不算覆盖、可重写。"""
        self.add_case('drafts', 'c001-rejected', ['discipline', 'C001'], meta={'status': drafts.STATUS_REJECTED})
        self.assertNotIn('clause:C001', [x['key'] for x in drafter.gaps(self.repo, NAME, self.plugin)])
        self.assertEqual([x['key'] for x in drafter.gaps(self.repo, NAME, self.plugin, only={'C001'})], ['clause:C001'])
        self.add_case('drafts', 'c001-open', ['discipline', 'C001'], meta={})
        self.assertEqual(drafter.gaps(self.repo, NAME, self.plugin, only={'C001'}), [])   # 有未打回的草稿仍算覆盖

    def test_prompt_forbids_injection_text_graders(self):
        p = drafter.build_prompt(NAME, drafter.gaps(self.repo, NAME, self.plugin)[:1])
        self.assertIn('SessionStart 以外的 hook 注入（UserPromptSubmit / SubagentStart / PreToolUse 等）', p)
        self.assertIn('进不了 trace，不写判这类注入文字', p)

    def test_cli_write_stopped_exit_code_is_2(self):
        ai = FakeAI(clause_ai.ClauseAIError('撞订阅用量限制或限流：429'))
        args = cli._parser().parse_args(['--data-dir', str(self.data), 'drafts', 'write', NAME, '--no-page'])
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(drafter.main(args, self.data, ai=ai), 2)

    def ai_case(self, target, slug, **kw):
        c = {'target': target, 'slug': slug, 'intent': '测 %s' % target, 'prompt': '请帮我做 %s' % slug,
             'max_turns': 6, 'allowed_tools': ['Agent'], 'graders': [
                 {'name': 'g', 'type': 'tool_used', 'tool': 'Agent', 'input_match': 'model', 'min': 1, 'arm': ''}],
             'judge': [{'id': 'j', 'criterion': '写了 model', 'rule': 'g'}]}
        c.update(kw)
        return c

    def test_draft_writes_validated_cases_records_skips_and_pages(self):
        ai = FakeAI({'cases': [
            self.ai_case('clause:C001', 'Dispatch Sets Model'),
            self.ai_case('clause:C001', 'covered'),                      # 撞名：自动改名
            self.ai_case('skill-trigger:sk', 'bad', allowed_tools=['Bash']),
            self.ai_case('skill-trigger:sk', 'sk-trigger', graders=[
                {'name': 's', 'type': 'tool_used', 'tool': 'Skill', 'input_match': 'sk', 'arm': 'both'},
                {'name': 'no-read', 'type': 'tool_used', 'tool': 'Read', 'max': 0}], judge=[]),
        ], 'skipped': [{'target': 'clause:C003', 'code': 'needs-user-reply', 'reason': '要等用户回答'}]},
            {'cases': [], 'skipped': []})
        summary = drafter.draft(self.data, NAME, ai=ai, now=at(5)(), log=SILENT)
        self.assertEqual(len(ai.calls), 1)                        # 7 个目标，一批 8 个
        p = ai.calls[0]['prompt']
        self.assertIn('派子代理时写明 model', p)
        self.assertNotIn('SENTINEL-INJECTION', p)                 # 不给注入原文
        self.assertNotIn('BODY-SECRET', p)                        # skill 只给 name 与 description
        self.assertIn('只读检索，回摘要', p)                       # agent 给定义全文
        self.assertEqual(ai.calls[0]['model'], drafter.DEFAULT_MODEL)
        self.assertEqual(summary['written'], ['dispatch-sets-model', 'covered-2', 'sk-trigger'])
        self.assertEqual([x['slug'] for x in summary['invalid']], ['bad'])
        d = self.drafts_root / 'dispatch-sets-model'
        self.assertEqual(casefiles.check_case_dir(d), [])
        self.assertEqual(clauses.case_tags(d), ['discipline', 'C001'])
        self.assertIn('clause: C001', (d / 'judge' / 'j.md').read_text(encoding='utf-8'))
        meta = drafts.read_meta(d)
        self.assertEqual((meta['source'], meta['category'], meta['clause_intent']), ('ai', 'discipline', '派子代理时写明 model'))
        self.assertEqual(clauses.case_tags(self.drafts_root / 'sk-trigger'), ['skill-trigger', 'skill:sk'])
        self.assertIn('min: 0', (self.drafts_root / 'sk-trigger' / 'graders' / 'no-read.md').read_text(encoding='utf-8'))
        skips = drafter.load_skips(self.repo, NAME)
        self.assertEqual(skips['clause:C003']['code'], 'needs-user-reply')
        self.assertAlmostEqual(summary['cost_usd'], 0.02)

        run_dir, page, _ = drafts.create_batch(self.data, NAME, now=at(6), drafting=summary, log=SILENT)
        self.assertEqual(len(page.items), 3)
        rec = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual(rec['drafting']['skipped'][0]['target'], 'clause:C003')
        self.assertIn('要等用户回答', (run_dir / 'report.md').read_text(encoding='utf-8'))

    def test_orphans_are_linked_first_and_ai_failure_stops_cleanly(self):
        self.add_case('drafts', 'history-case', ['discipline'], meta={'source': 'history', 'clause_intent': '派发带 model'})
        err = clause_ai.ClauseAIError('撞订阅用量限制或限流：429')
        ai = FakeAI({'links': [{'case': 'history-case', 'clause_ids': ['C001', 'C999'], 'reason': '测派发 model'}]}, err)
        summary = drafter.draft(self.data, NAME, ai=ai, now=at(5)(), log=SILENT)
        self.assertEqual(clauses.case_tags(self.drafts_root / 'history-case'), ['discipline', 'C001'])
        self.assertIn('C001：派子代理时写明 model', ai.calls[0]['prompt'])
        self.assertIn('撞订阅用量限制', summary['stopped'])
        self.assertEqual(summary['linked'][0]['clause_ids'], ['C001'])

    def test_cli_write_no_page_uses_model_flag(self):
        ai = FakeAI({'cases': [], 'skipped': []})
        args = cli._parser().parse_args(['--data-dir', str(self.data), 'drafts', 'write', NAME, '--model', 'm-x',
                                         '--no-page', '--limit', '2'])
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(drafter.main(args, self.data, ai=ai), 0)
        self.assertEqual(ai.calls[0]['model'], 'm-x')
        self.assertEqual(ai.calls[0]['prompt'].count('<target '), 2)

    def test_claude_caller_passes_system_prompt(self):
        seen = {}

        def run(cmd, **kw):
            seen['cmd'] = cmd

            class P:
                returncode = 0
                stdout = json.dumps({'structured_output': {'cases': []}, 'total_cost_usd': 0}).encode()
                stderr = b''
            return P()
        ai = clause_ai.claude_caller('/x/claude', run=run, system_prompt=drafter.SYSTEM_PROMPT)
        ai('p', drafter.CASE_SCHEMA, 'm')
        self.assertEqual(seen['cmd'][seen['cmd'].index('--system-prompt') + 1], drafter.SYSTEM_PROMPT)
        clause_ai.claude_caller('/x/claude', run=run)('p', {}, 'm')
        self.assertEqual(seen['cmd'][seen['cmd'].index('--system-prompt') + 1], clause_ai.SYSTEM_PROMPT)


if __name__ == '__main__':
    unittest.main()
