"""票 13：compact 之后的回放用例——合成历史、注入文本核对、挑条款、生成草稿、回放转录清理。全部合成数据。"""
import argparse
import io
import json
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from _support import write
from plugin_eval_lib import arms, casefiles, cli, clauses, compare, drafts, registry, replay
from test_compare import FakeEval, passing_preflight
from test_drafts import NAME, SILENT, Base, FakeAI, at, clause

INJECTION = ('# 工作纪律\n派子代理前先写清期望输出，每个子代理回执逐条核对后再汇总。\n'
             '改动配置前先读完相关文档，读完再动笔，不凭记忆改。\n')


class HistoryTest(unittest.TestCase):
    def test_minimal_fields_chain_and_compact_head(self):
        sid, recs = replay.build_history('case-x', replay.TAIL)
        self.assertEqual(str(uuid.UUID(sid)), sid)
        self.assertEqual((recs[0]['type'], recs[0]['subtype']), ('system', 'compact_boundary'))
        self.assertTrue(recs[1]['isCompactSummary'])
        self.assertTrue(recs[1]['message']['content'].startswith('This session is being continued'))
        self.assertIsNone(recs[0]['parentUuid'])
        for prev, cur in zip(recs, recs[1:]):
            self.assertEqual(cur['parentUuid'], prev['uuid'])
        for r in recs:
            for k in ('type', 'uuid', 'parentUuid', 'sessionId', 'timestamp', 'isSidechain'):
                self.assertIn(k, r)
            self.assertEqual(r['sessionId'], sid)
            self.assertIs(r['isSidechain'], False)
            self.assertNotIn('cwd', r)
        self.assertEqual([r['type'] for r in recs[2:]], ['user', 'assistant'] * len(replay.TAIL))
        self.assertEqual(replay.build_history('case-x', replay.TAIL), (sid, recs))      # 同 seed 可复现
        self.assertNotEqual(replay.build_history('case-y', replay.TAIL)[0], sid)
        self.assertNotEqual(replay.HISTORY_FILE, '%s.jsonl' % sid)    # 回放子会话的转录名不会盖掉历史

    def test_no_compact_variant(self):
        _, recs = replay.build_history('s', [('问', '答')], compact=False)
        self.assertEqual([r['type'] for r in recs], ['user', 'assistant'])

    def test_template_history_has_no_injection_of_this_plugin(self):
        _, recs = replay.build_history('s', replay.TAIL)
        self.assertEqual(replay.injection_hits(replay.message_texts(recs), INJECTION), 0)

    def test_injection_overlap_detected(self):
        texts = ['前情：' + '派子代理前先写清期望输出，每个子代理回执逐条核对后再汇总。']
        self.assertGreater(replay.injection_hits(texts, INJECTION), 0)
        self.assertEqual(replay.injection_hits(['派子代理'], INJECTION), 0)      # 短于门槛不算
        self.assertEqual(replay.injection_hits(texts, ''), 0)


class CaseFilesHistoryTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, str(self.tmp), True)

    def test_render_with_history_and_scaffold(self):
        spec = {'slug': 'h-case', 'tags': ['compact-replay', 'C001'], 'prompt': '做事',
                'graders': [{'name': 'ok', 'type': 'regex', 'pattern': 'ok'}],
                'scaffold_files': [{'path': 'a.txt', 'content': 'x'}],
                'history_file': replay.HISTORY_FILE, 'history_text': '{"type":"user"}\n'}
        d = casefiles.write_case(self.tmp / 'h-case', spec)
        y = (d / 'case.yaml').read_text(encoding='utf-8')
        self.assertIn('  scaffold_script: scaffold.sh', y)
        self.assertIn('  history_file: history.jsonl', y)
        self.assertEqual((d / 'history.jsonl').read_text(encoding='utf-8'), '{"type":"user"}\n')
        self.assertEqual(casefiles.check_case_dir(d), [])

    def test_check_flags_missing_or_outside_history(self):
        d = self.tmp / 'bad'
        write(d / 'prompt.md', '---\nname: bad\n---\n做事\n')
        write(d / 'graders' / 'g.md', '---\ntype: regex\npattern: ok\n---\n')
        write(d / 'case.yaml', 'schema_version: "1.1"\nname: bad\ncontext:\n  history_file: history.jsonl\n')
        self.assertTrue(any('history_file' in p for p in casefiles.check_case_dir(d)))
        write(d / 'case.yaml', 'schema_version: "1.1"\nname: bad\ncontext:\n  history_file: ../h.jsonl\n')
        self.assertTrue(any('history_file' in p for p in casefiles.check_case_dir(d)))

    def test_case_yaml_with_history_keeps_scaffold(self):
        y = replay.case_yaml_with_history('schema_version: "1.1"\nname: old\ncontext:\n  scaffold_script: scaffold.sh\n',
                                          'new')
        self.assertIn('name: new', y)
        self.assertIn('  scaffold_script: scaffold.sh', y)
        self.assertIn('  history_file: history.jsonl', y)
        self.assertEqual(y.count('context:'), 1)
        self.assertIn('context:\n  history_file: history.jsonl', replay.case_yaml_with_history('', 'n'))


class PurgeTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, str(self.tmp), True)

    def test_purge_removes_replay_transcripts_only(self):
        arm = self.tmp / 'current'
        sid, recs = replay.build_history('c', replay.TAIL)
        c = arm / 'evals' / 'compact-a'
        write(c / 'prompt.md', '---\nname: compact-a\n---\n做事\n')
        write(c / 'graders' / 'g.md', '---\ntype: regex\npattern: ok\n---\n')
        write(c / 'case.yaml', replay.case_yaml_with_history('', 'compact-a'))
        write(c / replay.HISTORY_FILE, replay.history_text(recs))
        write(c / ('%s.jsonl' % sid), '{"转录": 1}\n')
        write(c / sid / 'subagents' / 'agent-x.jsonl', '{}\n')
        other = arm / 'evals' / 'plain'
        write(other / 'prompt.md', '---\nname: plain\n---\n做事\n')
        write(other / 'graders' / 'g.md', '---\ntype: regex\npattern: ok\n---\n')
        write(other / ('%s.jsonl' % sid), '{}\n')        # 不是回放用例：不动
        removed = replay.purge_transcripts(arm)
        self.assertEqual(sorted(removed), sorted(['compact-a/%s.jsonl' % sid, 'compact-a/%s' % sid]))
        self.assertTrue((c / replay.HISTORY_FILE).is_file())
        self.assertTrue((other / ('%s.jsonl' % sid)).is_file())
        self.assertEqual(replay.purge_transcripts(arm), [])


class CompareCleansTranscriptsTest(unittest.TestCase):
    """compare 每跑完一臂就删回放转录：--keep-assembly 留下的组装目录里也没有。"""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, str(self.tmp), True)

    def test_run_arm_purges(self):
        repo = self.tmp / 'repo'
        plugin = repo / 'plugins' / 'demo-plugin'
        write(plugin / '.claude-plugin' / 'plugin.json', json.dumps({'name': 'demo-plugin', 'version': '1.2.3'}))
        write(plugin / 'hooks' / 'inject.js', 'console.log("hi")\n')
        sid, recs = replay.build_history('cmp', replay.TAIL)
        c = plugin / 'evals' / 'compact-a'
        write(c / 'prompt.md', '---\nname: compact-a\n---\n做事\n')
        write(c / 'graders' / 'g1.md', '---\ntype: regex\ntarget: last_message\npattern: ok\n---\n')
        write(c / 'case.yaml', replay.case_yaml_with_history('', 'compact-a'))
        write(c / replay.HISTORY_FILE, replay.history_text(recs))
        data = self.tmp / 'data'
        registry.register(data, 'demo-plugin', repo)
        seen = []

        class TranscriptEval(FakeEval):
            def __call__(self, cmd, cwd, env, log_dir):
                d = Path(cmd[3]) / 'evals' / 'compact-a'
                write(d / ('%s.jsonl' % sid), '{}\n')
                write(d / sid / 'x.jsonl', '{}\n')
                seen.append(d)
                return FakeEval.__call__(self, cmd, cwd, env, log_dir)

        (self.tmp / 'sb').mkdir()
        (self.tmp / 'asm').mkdir()
        res = compare.run_compare(data, 'demo-plugin', runs=1, concurrency=1, claude='/fake/claude',
                                  runner=TranscriptEval(self.tmp / 'sb', {'none': False, 'current': True}),
                                  env={'PATH': '/usr/bin'}, tmp_parent=self.tmp / 'asm', sandbox_roots=[self.tmp / 'sb'],
                                  log=SILENT, preflight_check=passing_preflight, keep_assembly=True, use_judge=False)
        self.assertIsNotNone(res.run_dir)
        self.assertEqual(len(seen), 2)
        for d in seen:
            self.assertTrue((d / replay.HISTORY_FILE).is_file())
            self.assertFalse((d / ('%s.jsonl' % sid)).exists())
            self.assertFalse((d / sid).exists())


class GenerateTest(Base):
    def setUp(self):
        super().setUp()
        self.set_list(clause('C001', '派子代理前写清期望输出', events=['SessionStart', 'SubagentStart']),
                      clause('C002', '回复用中文', events=['UserPromptSubmit']),
                      clause('C003', '改配置前先读文档'),
                      clause('C004', '读文件先定位', events=['SessionStart']),
                      clause('C005', '退役', 'retired', retire_reason='delete'))
        # C003 有正式用例作底本（带文件桩）；C004 只有未打回的草稿作底本
        self.add_case('evals', 'read-docs', ['discipline', 'C003'],
                      scaffold_files=[{'path': 'docs/a.md', 'content': '文档'}],
                      judge=[{'id': 'j', 'criterion': '先读文档', 'rule': 'ok', 'clause': 'C003'}])
        self.add_case('drafts', 'locate-first', ['discipline', 'C004'], meta={'intent': '先定位再读'})

    def gen(self, ai=None, **kw):
        kw.setdefault('injection_text', INJECTION)
        return replay.generate(self.data, NAME, ai=ai, model='m', now=at(5)(), log=SILENT, **kw)

    def test_selection_order_and_reasons(self):
        chosen, notes = replay.select_clauses(self.repo, NAME, self.plugin)
        self.assertEqual([c['id'] for c in chosen], ['C003', 'C004', 'C001'])   # 含 SessionStart 且有底本的在前
        self.assertEqual(chosen[0]['base'][0], 'evals/read-docs')
        self.assertEqual(chosen[1]['base'][0], 'drafts/locate-first')
        self.assertIsNone(chosen[2]['base'])
        self.assertNotIn('C005', [c['id'] for c in chosen])                         # 退役不选
        only, notes = replay.select_clauses(self.repo, NAME, self.plugin, only={'C002', 'C009'})
        self.assertEqual([c['id'] for c in only], ['C002'])
        self.assertTrue(any('C009' in n for n in notes))

    def test_proven_clause_first(self):
        d = self.drafts_root / 'locate-first'
        meta = drafts.read_meta(d)
        meta['evidence'] = {'proven_delta': 0.5}
        drafts.write_meta(d, meta)
        chosen, _ = replay.select_clauses(self.repo, NAME, self.plugin)
        self.assertEqual(chosen[0]['id'], 'C004')
        self.assertIn('已证明有差', chosen[0]['reasons'])

    def test_generate_from_base_and_ai(self):
        ai = FakeAI({'cases': [{'target': 'clause:C001', 'slug': 'brief-subagent', 'intent': '派前写清输出',
                                'prompt': '把三个目录各交给一个子代理查', 'graders': [
                                    {'name': 'agent', 'type': 'tool_used', 'tool': 'Agent', 'input_match': '期望'}]}],
                     'skipped': []})
        s = self.gen(ai=ai)
        self.assertEqual(len(ai.calls), 1)
        self.assertIn('C001', ai.calls[0]['prompt'])
        self.assertEqual(len(s['written']), 3, s)
        for slug in s['written']:
            d = self.drafts_root / slug
            self.assertEqual(casefiles.check_case_dir(d), [], slug)
            meta = drafts.read_meta(d)
            self.assertEqual((meta['source'], meta['category'], meta['status']), ('compact-replay', 'compact-replay', 'open'))
            self.assertEqual(meta['replay']['injection_hits'], 0)
            tags = clauses.case_tags(d)
            self.assertEqual(tags[0], 'compact-replay')
            self.assertEqual(len(drafts.clause_ids(tags)), 1)
            hist = [json.loads(x) for x in (d / replay.HISTORY_FILE).read_text(encoding='utf-8').splitlines()]
            self.assertEqual(hist[0]['subtype'], 'compact_boundary')
            self.assertEqual(meta['replay']['history_session_id'], hist[0]['sessionId'])
            self.assertEqual(replay.injection_hits(replay.message_texts(hist), INJECTION), 0)
            self.assertIn('history_file: history.jsonl', (d / 'case.yaml').read_text(encoding='utf-8'))
        base = self.drafts_root / 'compact-read-docs'
        self.assertTrue((base / 'scaffold.sh').is_file())                          # 底本的文件桩照带
        self.assertIn('scaffold_script: scaffold.sh', (base / 'case.yaml').read_text(encoding='utf-8'))
        self.assertIn('name: compact-read-docs', (base / 'prompt.md').read_text(encoding='utf-8'))
        self.assertIn('clause: C003', (base / 'judge' / 'j.md').read_text(encoding='utf-8'))
        self.assertEqual(drafts.read_meta(base)['replay']['base_case'], 'evals/read-docs')
        self.assertTrue((self.plugin / 'evals' / 'read-docs' / 'prompt.md').is_file())   # 底本原样不动
        self.assertFalse((self.plugin / 'evals' / 'read-docs' / replay.HISTORY_FILE).exists())
        # 每插件合计 ≤3：再跑一次一个都不生成
        again = self.gen(ai=FakeAI())
        self.assertEqual(again['written'], [])

    def test_quota_counts_existing_and_skips_covered(self):
        self.add_case('drafts', 'compact-old', ['compact-replay', 'C003'],
                      meta={'source': 'compact-replay', 'category': 'compact-replay', 'status': 'rejected'})
        chosen, _ = replay.select_clauses(self.repo, NAME, self.plugin)
        self.assertEqual([c['id'] for c in chosen], ['C004', 'C001'])

    def test_history_with_injection_is_not_written(self):
        s = self.gen(ai=FakeAI(), injection_text=replay.SUMMARY, limit=1)
        self.assertEqual(s['written'], [])
        self.assertEqual(len(s['invalid']), 1)
        self.assertFalse(any(p.name.startswith('compact-') for p in self.drafts_root.iterdir()))

    def test_no_injection_text_refuses(self):
        with self.assertRaises(replay.ReplayError):
            self.gen(injection_text='   ')

    def test_no_clause_list(self):
        (self.root / clauses.LIST_FILE).unlink()
        with self.assertRaises(replay.ReplayError):
            self.gen()

    def test_page_shows_replay_and_cli_wiring(self):
        self.gen(ai=FakeAI(), limit=1)
        run_dir, page, cls = self.batch()
        self.assertIn('compact-read-docs', [it['payload']['case'] for it in page.items])
        html = Path(page.html_path).read_text(encoding='utf-8')
        self.assertIn('compact 回放', html)
        self.assertIn('history.jsonl', html)
        ns = cli._parser().parse_args(['drafts', 'compact', NAME, '--no-page', '--clauses', 'C004'])
        self.assertEqual((ns.action, ns.clauses), ('compact', 'C004'))
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            rc = replay.main(ns, self.data, ai=FakeAI(), injection_text=INJECTION)
        self.assertEqual(rc, 0)
        self.assertIn('C004', out.getvalue())
        self.assertTrue((self.drafts_root / 'compact-locate-first' / replay.HISTORY_FILE).is_file())

    def test_ai_error_stops(self):
        s = self.gen(ai=FakeAI(RuntimeError('额度用完')), only={'C001'})
        self.assertIn('额度用完', s['stopped'])
        ns = argparse.Namespace(name=NAME, clauses='C001', model=None, limit=None, no_page=True)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(replay.main(ns, self.data, ai=FakeAI(RuntimeError('x')), injection_text=INJECTION), 2)


if __name__ == '__main__':
    unittest.main()
