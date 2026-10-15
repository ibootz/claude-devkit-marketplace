"""票 13：复盘候选转用例草稿——定位会话、过保留期作废、AI 改写（假 AI）、隐私自检、写回 conversion。全部合成数据。"""
import io
import json
import os
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from _support import write
from plugin_eval_lib import candidate_drafts as cd
from plugin_eval_lib import casefiles, cli, clauses, drafts, replay, review
from test_drafts import NAME, SILENT, Base, FakeAI, clause

DATE = '2026-10-15'
NOW = datetime(2026, 10, 15, 8, 5, tzinfo=timezone.utc)
INJECTION = '# 纪律\n进目录用绝对路径或子 shell，不发裸 cd，免得工作目录在会话里漂移。\n'
SID = str(uuid.UUID('11111111-2222-4333-8444-555555555555'))
GONE_SID = str(uuid.UUID('99999999-2222-4333-8444-555555555555'))
USER_TEXT = '帮我把 acme-billing 的发票导出改成按月分文件，顺便看下 git.acme-corp.com 上的分支'


def session_records(cwd):
    base = {'sessionId': SID, 'isSidechain': False, 'cwd': cwd, 'gitBranch': 'feat/invoice-monthly', 'version': '2.1.300'}
    recs = [
        dict(base, type='user', uuid='u1', parentUuid=None, timestamp='2026-10-14T09:00:00.000Z',
             message={'role': 'user', 'content': USER_TEXT}),
        dict(base, type='assistant', uuid='a1', parentUuid='u1', timestamp='2026-10-14T09:00:05.000Z',
             message={'role': 'assistant', 'content': [
                 {'type': 'text', 'text': '先进到导出模块目录看看现有实现。'},
                 {'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {'command': 'cd billing/export && ls'}}]}),
        dict(base, type='user', uuid='u2', parentUuid='a1', timestamp='2026-10-14T09:00:06.000Z',
             message={'role': 'user', 'content': [
                 {'type': 'tool_result', 'tool_use_id': 't1', 'is_error': True,
                  'content': 'PreToolUse:Bash hook error: 裸 cd 被拦，用子 shell'}]}),
    ]
    return recs


def candidate(cid, sid=SID, uid='u2', ts='2026-10-14T09:00:06.000Z', selection='draft', after_compact=False):
    return {'id': cid, 'kind': 'block', 'rule': 'hooks/cd-guard.js', 'count': 3, 'subagent_count': 0,
            'after_compact': after_compact, 'clause_ids': [], 'clause_mapping': {'reason': '未映射'},
            'plugin_versions': {'1.0.0': 3},
            'pointers': [{'session_id': sid, 'agent_id': None, 'uuid': uid, 'timestamp': ts,
                          'plugin_version': '1.0.0', 'claude_code_version': '2.1.300'}],
            'selection': selection, 'decided_at': '2026-10-15T08:00:00Z' if selection else None, 'carried_from': None}


def rewrite(prompt='给虚构的命令行工具 pagelint 加一个按月拆分输出的参数，先看看 src/report 目录里现在怎么写的',
            clause_ids=('C001',), history=(), summary='', skip='', graders=None):
    return {'skip_code': skip, 'clause_ids': list(clause_ids), 'clause_reason': '用例测的是进目录的方式',
            'case': {'slug': 'subdir-look', 'intent': '要看子目录时不发裸 cd', 'prompt': prompt,
                     'graders': graders or [{'name': 'no-bare-cd', 'type': 'regex', 'target': 'trace',
                                             'pattern': '"command":"cd ', 'match': 'not_contains'}],
                     'history': [{'role': r, 'text': t} for q, a in history for r, t in (('user', q), ('assistant', a))], 'compact_summary': summary}}


class CandidateBase(Base):
    def setUp(self):
        super().setUp()
        self.set_list(clause('C001', '不发裸 cd'), clause('C002', '回复用中文'))
        self.cfg = self.tmp / 'cfg'
        self.env = {'CLAUDE_CONFIG_DIR': str(self.cfg)}
        cwd = str(self.tmp / 'work' / 'acme-billing')
        self.session = self.cfg / 'projects' / '-work-acme-billing' / ('%s.jsonl' % SID)
        write(self.session, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in session_records(cwd)))
        self.review_path = self.root / 'reviews' / ('%s.json' % DATE)
        self.write_review(candidate('c-aaaaaaaaaaaa'), candidate('c-bbbbbbbbbbbb', sid=GONE_SID),
                          candidate('c-cccccccccccc', selection='skip'), candidate('c-dddddddddddd', selection=None))

    def write_review(self, *cands):
        rec = {'schema_version': 1, 'kind': review.KIND, 'run_id': 'review-' + DATE, 'date': DATE,
               'plugin': {'name': NAME, 'version': '1.0.0'}, 'candidates': list(cands), 'pending': None}
        write(self.review_path, json.dumps(rec, ensure_ascii=False, indent=2))

    def run_(self, ai, **kw):
        kw.setdefault('injection_text', INJECTION)
        return cd.run(self.data, NAME, ai=ai, model='m', now=NOW, env=self.env, log=SILENT, **kw)

    def conversions(self):
        rec = json.loads(self.review_path.read_text(encoding='utf-8'))
        return {c['id']: c.get('conversion') for c in rec['candidates']}

    def drafts_written(self):
        return [d for d in drafts.list_drafts(self.repo, NAME)]

    def all_text_on_disk(self):
        out = []
        for p in self.repo.rglob('*'):
            if p.is_file():
                out.append(p.read_text(encoding='utf-8', errors='replace'))
        return '\n'.join(out)


class ConvertTest(CandidateBase):
    def test_draft_and_void(self):
        ai = FakeAI(rewrite())
        s = self.run_(ai)
        self.assertEqual(len(ai.calls), 1)                         # 作废的不调 AI；skip / 未选的不处理
        self.assertEqual(ai.calls[0]['model'], 'm')
        prompt = ai.calls[0]['prompt']
        self.assertIn(USER_TEXT, prompt)                            # 片段只在内存里交给 AI
        self.assertIn('C001：不发裸 cd', prompt)
        conv = self.conversions()
        self.assertEqual(conv['c-aaaaaaaaaaaa']['status'], 'drafted')
        self.assertEqual(conv['c-bbbbbbbbbbbb'], {'status': 'void', 'code': 'file-gone', 'at': '2026-10-15T08:05:00Z'})
        self.assertIsNone(conv['c-cccccccccccc'])
        self.assertIsNone(conv['c-dddddddddddd'])
        ds = self.drafts_written()
        self.assertEqual(len(ds), 1)
        d = ds[0]
        self.assertEqual(d.case, conv['c-aaaaaaaaaaaa']['draft'])
        self.assertEqual((d.meta['source'], d.category), ('review-candidate', 'review-replay'))
        self.assertEqual(d.tags, ['review-replay', 'C001'])
        self.assertEqual(d.meta['review_candidate'], {'review_date': DATE, 'candidate_id': 'c-aaaaaaaaaaaa',
                                                      'kind': 'block', 'rule': 'hooks/cd-guard.js',
                                                      'after_compact': False})
        self.assertEqual(d.meta['clause_reason'], '用例测的是进目录的方式')
        self.assertEqual(d.problems, [])
        self.assertEqual(s['written'], [d.case])
        # 原文不落盘：草稿与复盘结果里都没有原会话的用户话、项目名、分支
        disk = self.all_text_on_disk()
        for secret in (USER_TEXT, 'acme-billing', 'invoice-monthly', 'acme-corp', 'billing/export'):
            self.assertNotIn(secret, disk)
        # 复盘结果写回后仍过自检
        review._self_check(NAME, json.loads(self.review_path.read_text(encoding='utf-8')))

    def test_terminal_not_reprocessed_and_dedupe_by_draft(self):
        self.run_(FakeAI(rewrite()))
        s = self.run_(FakeAI())                                       # 再跑：终态不再调 AI
        self.assertEqual(s['conversions'], {})
        # conversion 丢了（如手动重写复盘结果），草稿区里已有同一候选的草稿：不再改写
        rec = json.loads(self.review_path.read_text(encoding='utf-8'))
        for c in rec['candidates']:
            c.pop('conversion', None)
        write(self.review_path, json.dumps(rec))
        s = self.run_(FakeAI())
        self.assertEqual(s['conversions']['c-aaaaaaaaaaaa']['code'], 'already-in-drafts')
        self.assertEqual(len(self.drafts_written()), 1)

    def test_past_retention_and_record_gone(self):
        write(self.cfg / 'settings.json', json.dumps({'cleanupPeriodDays': 7}))
        self.write_review(candidate('c-aaaaaaaaaaaa', ts='2026-09-01T09:00:06.000Z'),
                          candidate('c-bbbbbbbbbbbb', uid='u-not-there'))
        s = self.run_(FakeAI())
        conv = self.conversions()
        self.assertEqual((conv['c-aaaaaaaaaaaa']['status'], conv['c-aaaaaaaaaaaa']['code']), ('void', 'past-retention'))
        self.assertEqual((conv['c-bbbbbbbbbbbb']['status'], conv['c-bbbbbbbbbbbb']['code']), ('void', 'record-gone'))
        self.assertEqual(self.drafts_written(), [])
        self.assertEqual(s['calls'], 0)

    def test_skip_code(self):
        self.write_review(candidate('c-aaaaaaaaaaaa'))
        self.run_(FakeAI(rewrite(skip='needs-write-tools')))
        self.assertEqual(self.conversions()['c-aaaaaaaaaaaa']['status'], 'skipped')
        self.assertEqual(self.conversions()['c-aaaaaaaaaaaa']['code'], 'needs-write-tools')
        self.assertEqual(self.drafts_written(), [])

    def test_unknown_clause_dropped_and_no_clause_still_pages(self):
        self.write_review(candidate('c-aaaaaaaaaaaa'))
        self.run_(FakeAI(rewrite(clause_ids=('C999',))))
        d = self.drafts_written()[0]
        self.assertEqual(d.tags, ['review-replay'])
        run_dir, page, cls = self.batch()
        self.assertEqual([it['payload']['case'] for it in page.items], [d.case])     # 不挂条款也能上页
        rec = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual(rec['batch'][0]['tier'], drafts.TIER_REVIEW)
        self.assertIn('复盘候选', Path(page.html_path).read_text(encoding='utf-8'))

    def test_after_compact_history(self):
        self.write_review(candidate('c-aaaaaaaaaaaa', after_compact=True))
        self.run_(FakeAI(rewrite(history=[('先列一下 pagelint 的目录结构', '顶层有 src、tests、docs 三个目录。')],
                                 summary='用户在给虚构工具 pagelint 加报告参数，已读完 src/cli.py。')))
        d = self.drafts_written()[0]
        hist = [json.loads(x) for x in (d.path / replay.HISTORY_FILE).read_text(encoding='utf-8').splitlines()]
        self.assertEqual(hist[0]['subtype'], 'compact_boundary')
        self.assertTrue(hist[1]['isCompactSummary'])
        self.assertEqual([h['type'] for h in hist[2:]], ['user', 'assistant'])
        self.assertTrue(d.meta['replay']['compact'])
        self.assertEqual(casefiles.check_case_dir(d.path), [])

    def test_history_with_injection_rejected(self):
        self.write_review(candidate('c-aaaaaaaaaaaa'))
        self.run_(FakeAI(rewrite(history=[('规矩：进目录用绝对路径或子 shell，不发裸 cd，免得工作目录在会话里漂移。', '好的')])))
        conv = self.conversions()['c-aaaaaaaaaaaa']
        self.assertEqual((conv['status'], conv['code']), ('invalid', 'history-has-injection'))
        self.assertEqual(self.drafts_written(), [])

    def test_invalid_spec_not_written_and_retried(self):
        self.write_review(candidate('c-aaaaaaaaaaaa'))
        self.run_(FakeAI(rewrite(graders=[{'name': 'x', 'type': 'regex'}])))
        self.assertEqual(self.conversions()['c-aaaaaaaaaaaa']['status'], 'invalid')
        self.assertEqual(self.drafts_written(), [])
        self.run_(FakeAI(rewrite()))                                   # 非终态：下次再试
        self.assertEqual(self.conversions()['c-aaaaaaaaaaaa']['status'], 'drafted')

    def test_ai_error_stops_and_exit_code(self):
        self.write_review(candidate('c-aaaaaaaaaaaa'))
        s = self.run_(FakeAI(RuntimeError('额度用完')))
        self.assertIn('额度用完', s['stopped'])
        self.assertEqual(self.conversions()['c-aaaaaaaaaaaa']['status'], 'error')

    def test_cli_wiring(self):
        self.write_review(candidate('c-aaaaaaaaaaaa'))
        ns = cli._parser().parse_args(['drafts', 'from-review', NAME, '--date', DATE, '--no-page'])
        self.assertEqual((ns.action, ns.date), ('from-review', DATE))
        out = io.StringIO()
        with mock.patch.dict(os.environ, self.env), redirect_stdout(out), redirect_stderr(io.StringIO()):
            rc = cd.main(ns, self.data, ai=FakeAI(rewrite()), injection_text=INJECTION)
        self.assertEqual(rc, 0)
        self.assertIn('已写进草稿区', out.getvalue())
        ns = cli._parser().parse_args(['drafts', 'from-review', NAME, '--date', '2026-01-01'])
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cd.main(ns, self.data, ai=FakeAI()), 2)

    def test_rerun_review_keeps_conversion(self):
        self.write_review(candidate('c-aaaaaaaaaaaa'))
        self.run_(FakeAI(rewrite()))
        old = json.loads(self.review_path.read_text(encoding='utf-8'))
        new = {'candidates': [candidate('c-aaaaaaaaaaaa', selection=None)], 'compare_hint': {}}
        merged = review.merge_previous(new, old)
        self.assertEqual(merged['candidates'][0]['conversion']['status'], 'drafted')
        later = {'plugin': {'version': '1.0.0'}, 'candidates': [candidate('c-aaaaaaaaaaaa', selection=None)]}
        review.carry_earlier(later, [(DATE, old)])
        self.assertEqual(later['candidates'][0]['conversion']['status'], 'drafted')


class PrivacyTest(CandidateBase):
    def rejected_with(self, ai_result, env_extra=None):
        self.write_review(candidate('c-aaaaaaaaaaaa'))
        if env_extra:
            self.env.update(env_extra)
        self.run_(FakeAI(ai_result))
        conv = self.conversions()['c-aaaaaaaaaaaa']
        self.assertEqual(conv['status'], 'privacy-rejected', conv)
        self.assertEqual(self.drafts_written(), [])
        self.assertFalse(self.drafts_root.exists() and any(self.drafts_root.iterdir()))
        return conv['findings']

    def test_project_name_from_cwd(self):
        self.assertIn('private-term', self.rejected_with(rewrite(prompt='给 acme-billing 加按月导出参数')))

    def test_branch_and_host_terms(self):
        self.assertIn('private-term', self.rejected_with(rewrite(prompt='在 invoice-monthly 分支上加参数')))

    def test_host_term(self):
        self.assertIn('private-term', self.rejected_with(rewrite(prompt='把 acme-corp 的报表导出改一下')))

    def test_path(self):
        self.assertIn('path', self.rejected_with(rewrite(prompt='看看 /home/dev/tool 下的 src 目录有哪些文件')))

    def test_email(self):
        addr = 'dev' + '@' + 'acme.test'
        self.assertIn('email', self.rejected_with(rewrite(prompt='把报告发给 %s 之前先看看 src 目录' % addr)))

    def test_verbatim_overlap(self):
        self.assertIn('verbatim-overlap', self.rejected_with(rewrite(prompt='请：' + USER_TEXT.replace('acme-billing', 'x'))))

    def test_configured_terms(self):
        f = self.rejected_with(rewrite(prompt='给内部代号 zephyrine 的工具加参数，先看 src 目录'),
                               env_extra={cd.PRIVATE_TERMS_ENV: 'Zephyrine, other'})
        self.assertIn('private-term', f)

    def test_findings_hold_no_text(self):
        f = self.rejected_with(rewrite(prompt='给 acme-billing 加按月导出参数'))
        self.assertTrue(all(isinstance(v, int) for v in f.values()))
        self.assertNotIn('acme-billing', self.review_path.read_text(encoding='utf-8'))

    def test_example_invalid_email_allowed(self):
        self.assertEqual(cd.privacy_findings(['联系 someone@example.invalid']), {})

    def test_host_terms_only_domains_and_packages(self):
        self.assertEqual(cd.host_terms('读 index.html 与 a.py'), set())
        self.assertEqual(cd.host_terms('拉 git.acme-corp.com 与 com.zephyr.billing.Foo'),
                         {'acme-corp', 'zephyr', 'billing'})
        self.assertEqual(cd.host_terms('见 github.com 文档'), set())


class LocateTest(unittest.TestCase):
    def test_pointer_whitelist_blocks_traversal(self):
        self.assertIsNone(cd.locate('/nonexistent', {'session_id': '../../etc/passwd'}))
        self.assertIsNone(cd.locate('/nonexistent', {'session_id': SID, 'agent_id': '../x'}))


if __name__ == '__main__':
    unittest.main()
