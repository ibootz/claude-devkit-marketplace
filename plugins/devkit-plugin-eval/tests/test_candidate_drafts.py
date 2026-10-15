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
        # 读不到时才按时间戳区分（C 批定稿 3）：早于保留期 → past-retention；否则记录不在 → record-gone
        self.write_review(candidate('c-aaaaaaaaaaaa', uid='u-not-there', ts='2026-09-01T09:00:06.000Z'),
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


TOOL_OUTPUT = '对账脚本每月一号凌晨两点把上月全部订单汇总成一份对账单并推送到财务共享盘'


class BatchCFixTest(CandidateBase):
    """C 批集成：审查 13 的 B1、S1–S5、L1 与主会话定稿 1–3。"""

    def with_tool_output(self):
        recs = session_records(str(self.tmp / 'work' / 'acme-billing'))
        recs[2]['message']['content'][0].update(is_error=False, content=TOOL_OUTPUT)
        write(self.session, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in recs))

    def test_copy_from_tool_result_rejected(self):
        """B1：从 tool_result 抄来的内容也拒写。"""
        self.with_tool_output()
        self.write_review(candidate('c-aaaaaaaaaaaa'))
        self.run_(FakeAI(rewrite(prompt='先读一下这段说明：' + TOOL_OUTPUT + '，再改 src 目录')))
        conv = self.conversions()['c-aaaaaaaaaaaa']
        self.assertEqual(conv['status'], 'privacy-rejected', conv)
        self.assertIn('verbatim-overlap', conv['findings'])
        self.assertEqual(self.drafts_written(), [])

    def test_public_text_exempt_from_overlap(self):
        """集成真跑后补：片段里的 Claude Code 固定文案与被测插件自己的文字，草稿照抄不算逐字重合；别的工具输出照拒。"""
        hook_msg = '这条命令被纪律守卫拦下：请改用子 shell 进入目录后再执行后续命令'
        write(self.plugin / 'hooks' / 'cd-guard.js', 'module.exports = %r;\n' % hook_msg)
        recs = session_records(str(self.tmp / 'work' / 'acme-billing'))
        recs[2]['message']['content'][0]['content'] = hook_msg
        recs.append(dict(recs[0], uuid='s1', parentUuid='u2', isCompactSummary=True,
                         message={'role': 'user', 'content': cd.CC_BOILERPLATE[0] + ' 摘要正文略。'}))
        write(self.session, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in recs))
        public = cd.public_text(self.plugin)
        self.assertIn(cd._norm(hook_msg), public)
        self.assertIn(cd._norm(cd.CC_BOILERPLATE[0]), public)
        sources = [hook_msg, cd.CC_BOILERPLATE[0] + ' 摘要正文略。', TOOL_OUTPUT]
        draft_text = ['被拦时提示：' + hook_msg, cd.CC_BOILERPLATE[0] + ' 虚构项目 pagelint 的摘要。']
        self.assertEqual(cd.privacy_findings(draft_text, source_texts=sources, public=public), {})
        self.assertIn('verbatim-overlap', cd.privacy_findings(draft_text, source_texts=sources))   # 不传豁免语料照拒
        self.assertIn('verbatim-overlap', cd.privacy_findings(['抄来：' + TOOL_OUTPUT], source_texts=sources,
                                                              public=public))
        # 走完整流程：草稿照抄 hook 文案也能写成
        self.write_review(candidate('c-aaaaaaaaaaaa'))
        self.run_(FakeAI(rewrite(prompt='进 src 目录前先想想：' + hook_msg)))
        self.assertEqual(self.conversions()['c-aaaaaaaaaaaa']['status'], 'drafted')

    def test_three_letter_terms(self):
        """S1：主机名、包名标签与 cwd 末段 ≥3 字即取，通用词不取。"""
        self.assertEqual(cd.host_terms('import com.abc.billing.Foo; git.abc.com'), {'abc', 'billing'})
        self.assertEqual(cd.host_terms('调 api.example.com 与 cdn.web.app'), set())
        self.assertIn('abc', cd._path_terms('/opt/work/abc'))
        self.assertNotIn('lib', cd._path_terms('/opt/work/lib'))
        # 3 字私有词按整词匹配：abc 命中「abc 的工具」，不命中 abcd
        self.assertIn('private-term', cd.privacy_findings(['给 abc 的工具加参数'], private_terms={'abc'}))
        self.assertEqual(cd.privacy_findings(['abcd 是虚构项目'], private_terms={'abc'}), {})

    def test_private_terms_file_and_env_union(self):
        """定稿 2：环境变量与数据目录词表取并集。"""
        write(self.data / cd.PRIVATE_TERMS_FILE, '# 公司与项目代号\nzephyrine\nquillon, other\n')
        terms = cd.configured_terms({cd.PRIVATE_TERMS_ENV: 'Envterm'}, self.data)
        self.assertEqual(terms, {'zephyrine', 'quillon', 'other', 'Envterm'})
        self.write_review(candidate('c-aaaaaaaaaaaa'))
        self.run_(FakeAI(rewrite(prompt='给内部代号 Quillon 的工具加参数，先看 src 目录')))
        self.assertIn('private-term', self.conversions()['c-aaaaaaaaaaaa']['findings'])

    def test_no_terms_warns_on_stderr_and_summary(self):
        self.write_review(candidate('c-aaaaaaaaaaaa'))
        ns = cli._parser().parse_args(['drafts', 'from-review', NAME, '--no-page'])
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(cd.main(ns, self.data, ai=FakeAI(rewrite()), injection_text=INJECTION), 0)
        self.assertIn(cd.NO_TERMS_NOTE, err.getvalue())
        self.assertIn(cd.NO_TERMS_NOTE, out.getvalue())
        self.assertIn(cd.PRIVACY_NOTE, out.getvalue())
        write(self.data / cd.PRIVATE_TERMS_FILE, 'zephyrine\n')
        self.write_review(candidate('c-aaaaaaaaaaaa'))
        for p in list(self.drafts_root.iterdir()):
            __import__('shutil').rmtree(str(p))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), redirect_stdout(out), redirect_stderr(err):
            cd.main(ns, self.data, ai=FakeAI(rewrite()), injection_text=INJECTION)
        self.assertNotIn(cd.NO_TERMS_NOTE, err.getvalue() + out.getvalue())

    def test_draft_dir_gitignored_and_mark_dropped_on_approve(self):
        """定稿 1：草稿目录有内容为 * 的 .gitignore（git status 看不到草稿）；通过后移进 evals/ 时不随搬。"""
        import shutil
        import subprocess
        self.write_review(candidate('c-aaaaaaaaaaaa'))
        self.run_(FakeAI(rewrite()))
        d = self.drafts_written()[0]
        self.assertEqual((d.path / '.gitignore').read_text(encoding='utf-8'), '*\n')
        git = shutil.which('git')
        if git:
            subprocess.run([git, 'init', '-q', str(self.repo)], check=True)
            st = subprocess.run([git, '-C', str(self.repo), 'status', '--porcelain', '--untracked-files=all'],
                                capture_output=True, text=True, check=True).stdout
            self.assertNotIn('review-', st)
            self.assertIn('plugin-evals/', st)          # 别的文件照常可见：确认 git status 本身有效
        run_dir, page, _ = self.batch()
        html = Path(page.html_path).read_text(encoding='utf-8')
        self.assertIn(cd.PRIVACY_NOTE, html)
        self.assertNotIn('===== .gitignore =====', html)
        self.reply(page, ['1A'])
        moved = self.plugin / 'evals' / d.case
        self.assertTrue((moved / 'prompt.md').is_file())
        self.assertFalse((moved / '.gitignore').exists())
        self.assertFalse((moved / drafts.META_FILE).exists())
        self.assertFalse((d.path / '.gitignore').exists())

    def test_readable_even_if_older_than_retention(self):
        """定稿 3：先试读，读得到就照常改写；读不到再按时间戳区分原因码。"""
        write(self.cfg / 'settings.json', json.dumps({'cleanupPeriodDays': 7}))
        self.write_review(candidate('c-aaaaaaaaaaaa', ts='2026-09-01T09:00:06.000Z'),
                          candidate('c-bbbbbbbbbbbb', sid=GONE_SID, ts='2026-09-01T09:00:06.000Z'),
                          candidate('c-cccccccccccc', sid=GONE_SID))
        self.run_(FakeAI(rewrite()))
        conv = self.conversions()
        self.assertEqual(conv['c-aaaaaaaaaaaa']['status'], 'drafted')
        self.assertEqual((conv['c-bbbbbbbbbbbb']['status'], conv['c-bbbbbbbbbbbb']['code']), ('void', 'past-retention'))
        self.assertEqual((conv['c-cccccccccccc']['status'], conv['c-cccccccccccc']['code']), ('void', 'file-gone'))

    def test_skipped_carried_across_dates_void_not(self):
        """S4：跨日期 skipped 也沿用（不再调 AI），void 不沿用。"""
        old = {'plugin': {'version': '1.0.0'}, 'candidates': [
            dict(candidate('c-aaaaaaaaaaaa'), conversion={'status': 'skipped', 'code': 'needs-write-tools'}),
            dict(candidate('c-bbbbbbbbbbbb'), conversion={'status': 'void', 'code': 'file-gone'})]}
        later = {'plugin': {'version': '1.0.0'}, 'candidates': [candidate('c-aaaaaaaaaaaa', selection=None),
                                                                candidate('c-bbbbbbbbbbbb', selection=None)]}
        review.carry_earlier(later, [(DATE, old)])
        self.assertEqual(later['candidates'][0]['conversion']['status'], 'skipped')
        self.assertNotIn('conversion', later['candidates'][1])

    def test_no_injection_text_marks_unchecked(self):
        """L1：取不到注入文字照常写，draft.json 记 injection_checked=false，待审页写明。"""
        self.write_review(candidate('c-aaaaaaaaaaaa'))
        s = self.run_(FakeAI(rewrite(history=[('先列一下目录', '有 src 与 tests。')])), injection_text='')
        self.assertIs(s['injection_checked'], False)
        d = self.drafts_written()[0]
        self.assertIs(d.meta['injection_checked'], False)
        run_dir, page, _ = self.batch()
        self.assertIn('未做注入核对', Path(page.html_path).read_text(encoding='utf-8'))
        self.write_review(candidate('c-bbbbbbbbbbbb'))
        self.run_(FakeAI(rewrite()))
        d2 = [x for x in self.drafts_written() if x.case != d.case][0]
        self.assertIs(d2.meta['injection_checked'], True)


class MappingReasonTest(unittest.TestCase):
    """票 13 真跑撞到：99 条条款都挂同一事件时，未映射原因把 id 全列出来超了 300 字，复盘自检整批拒写。"""

    def test_reason_stays_short(self):
        from plugin_eval_lib import review_clauses
        cl = [review_clauses.Clause('C%03d' % i, frozenset({'SessionStart'})) for i in range(1, 100)]
        ids, m = review_clauses.match(cl, 'hooks/a.js', {'hooks/a.js': {'SessionStart'}})
        self.assertEqual(ids, [])
        self.assertLessEqual(len(m['reason']), review.LONG_TEXT_LIMIT)
        self.assertIn('99 条', m['reason'])
        self.assertEqual(review.assert_no_text(m), [])


class LocateTest(unittest.TestCase):
    def test_pointer_whitelist_blocks_traversal(self):
        self.assertIsNone(cd.locate('/nonexistent', {'session_id': '../../etc/passwd'}))
        self.assertIsNone(cd.locate('/nonexistent', {'session_id': SID, 'agent_id': '../x'}))


if __name__ == '__main__':
    unittest.main()
