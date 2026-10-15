"""接缝：待审页生成（pending.generate）与回复码写回（pending.apply_reply）。"""
import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

import _support
from plugin_eval_lib import pending, record, registry

T0 = datetime(2026, 10, 15, 9, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 15, 9, 30, 0, tzinfo=timezone.utc)
RUN_ID = '20261015T080000Z-1.2.3-compare'


def _rec(run_id=RUN_ID):
    import test_record
    rec = test_record.build()
    rec['run_id'] = run_id
    return rec


def make_run(repo, run_id=RUN_ID, name='demo'):
    """在 repo/plugin-evals/<name>/runs/<run_id>/ 下写一份待审的 run.json 与 report.md。"""
    rec = _rec(run_id)
    run_dir = Path(repo) / 'plugin-evals' / name / 'runs' / run_id
    _support.write(run_dir / 'run.json', json.dumps(rec, ensure_ascii=False, indent=2) + '\n')
    _support.write(run_dir / 'report.md', record.render_report(rec))
    return run_dir


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(Path(root).rglob('*')) if p.is_file()}


def read_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


class Env(object):
    def __init__(self, tc):
        self.root = _support.tmpdir(tc)
        self.repo = self.root / 'repo'
        _support.make_plugin(self.repo / 'plugins' / 'demo', name='demo')
        self.data = self.root / 'data'
        registry.register(self.data, 'demo', self.repo)


class ReportReviewTest(unittest.TestCase):
    def setUp(self):
        self.env = Env(self)
        self.run_dir = make_run(self.env.repo)

    def test_page_shows_report_summary_and_review_option(self):
        page = pending.generate(self.env.data, 'demo', now=lambda: T0)
        self.assertTrue(page.html_path.is_file())
        self.assertFalse(str(page.html_path).startswith(str(self.env.repo)), '待审页不得落进被测仓')
        html = page.html_path.read_text(encoding='utf-8')
        self.assertIn('报告审阅', html)
        self.assertIn('已审', html)
        self.assertIn(RUN_ID, html)
        self.assertIn('离线对照报告：demo 1.2.3', html)   # report.md 正文在页上
        self.assertIn('+0.50', html)                     # 摘要里的差
        self.assertEqual(len(page.items), 1)
        rec = read_json(self.run_dir / 'run.json')
        self.assertEqual(rec['pending']['page_id'], page.page_id)
        self.assertEqual(rec['review']['status'], '待审')

    def test_reply_marks_run_reviewed(self):
        page = pending.generate(self.env.data, 'demo', now=lambda: T0)
        code = 'PE1 %s %s 1A' % (RUN_ID, page.page_id)
        res = pending.apply_reply(self.env.data, 'demo', code, now=lambda: T1)
        rec = read_json(self.run_dir / 'run.json')
        self.assertEqual(rec['review'], {'status': '已审', 'reviewed_at': '2026-10-15T09:30:00Z'})
        self.assertEqual(rec['pending']['applied_at'], '2026-10-15T09:30:00Z')
        report = (self.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn('状态：**已审**', report)
        self.assertIn('2026-10-15T09:30:00Z', report)
        self.assertNotIn('状态：**待审**', report)
        self.assertIn('run.json', ' '.join(res.changed_files))

    def test_page_code_is_tolerant_of_whitespace_and_case(self):
        page = pending.generate(self.env.data, 'demo', now=lambda: T0)
        code = '  pe1   %s\n%s 1a \n' % (RUN_ID, page.page_id)
        pending.apply_reply(self.env.data, 'demo', code, now=lambda: T1)
        self.assertEqual(read_json(self.run_dir / 'run.json')['review']['status'], '已审')

    def test_reviewed_run_yields_no_items(self):
        page = pending.generate(self.env.data, 'demo', now=lambda: T0)
        pending.apply_reply(self.env.data, 'demo', 'PE1 %s %s 1A' % (RUN_ID, page.page_id), now=lambda: T1)
        with self.assertRaises(pending.NothingPending):
            pending.generate(self.env.data, 'demo', now=lambda: T1)

    def test_latest_run_is_default_and_run_option_selects(self):
        other = '20261016T080000Z-1.2.4-compare'
        make_run(self.env.repo, other)
        self.assertEqual(pending.generate(self.env.data, 'demo', now=lambda: T0).run_id, other)
        self.assertEqual(pending.generate(self.env.data, 'demo', run_id=RUN_ID, now=lambda: T0).run_id, RUN_ID)


class BadReplyTest(unittest.TestCase):
    def setUp(self):
        self.env = Env(self)
        self.run_dir = make_run(self.env.repo)
        self.page = pending.generate(self.env.data, 'demo', now=lambda: T0)
        self.before = snapshot(self.env.root)

    def assert_rejected(self, code, **kw):
        with self.assertRaises(pending.ReplyError):
            pending.apply_reply(self.env.data, 'demo', code, now=lambda: T1, **kw)
        self.assertEqual(snapshot(self.env.root), self.before, '报错时不得改任何文件')

    def test_garbage(self):
        self.assert_rejected('随便写的')

    def test_wrong_prefix(self):
        self.assert_rejected('PE9 %s %s 1A' % (RUN_ID, self.page.page_id))

    def test_unknown_run(self):
        self.assert_rejected('PE1 20990101T000000Z-9.9.9-compare %s 1A' % self.page.page_id)

    def test_run_option_mismatch(self):
        make_run(self.env.repo, '20261016T080000Z-1.2.4-compare')
        self.before = snapshot(self.env.root)
        self.assert_rejected('PE1 %s %s 1A' % (RUN_ID, self.page.page_id), run_id='20261016T080000Z-1.2.4-compare')

    def test_stale_page_id(self):
        self.assert_rejected('PE1 %s %s 1A' % (RUN_ID, 'deadbeef'))

    def test_item_out_of_range(self):
        self.assert_rejected('PE1 %s %s 2A' % (RUN_ID, self.page.page_id))

    def test_unknown_option(self):
        self.assert_rejected('PE1 %s %s 1Z' % (RUN_ID, self.page.page_id))

    def test_duplicate_item(self):
        self.assert_rejected('PE1 %s %s 1A 1A' % (RUN_ID, self.page.page_id))

    def test_no_decisions(self):
        self.assert_rejected('PE1 %s %s' % (RUN_ID, self.page.page_id))

    def test_malformed_token(self):
        self.assert_rejected('PE1 %s %s A1' % (RUN_ID, self.page.page_id))

    def test_reused_code(self):
        code = 'PE1 %s %s 1A' % (RUN_ID, self.page.page_id)
        pending.apply_reply(self.env.data, 'demo', code, now=lambda: T1)
        self.before = snapshot(self.env.root)
        self.assert_rejected(code)

    def test_failing_writeback_changes_nothing(self):
        """写回途中某一项抛错：已暂存的其它改动也不落盘。"""
        def boom(subject, item, code, now):
            raise RuntimeError('写回失败')
        reg = pending.TypeRegistry()
        reg.register(pending.REPORT_REVIEW)
        reg.register(pending.ItemType(key='boom', label='炸', options=(('X', '炸'),),
                                      collect=lambda s: [pending.PendingItem('boom:1', '会炸的项')],
                                      apply=boom))
        page = pending.generate(self.env.data, 'demo', now=lambda: T1, types=reg)
        self.before = snapshot(self.env.root)
        with self.assertRaises(pending.ReplyError):
            pending.apply_reply(self.env.data, 'demo', 'PE1 %s %s 1A 2X' % (RUN_ID, page.page_id),
                                now=lambda: T1, types=reg)
        self.assertEqual(snapshot(self.env.root), self.before)


# ---- 扩展性：示例类型。只注册类型与写回逻辑，不碰页面框架 ----

def _demo_collect(subject):
    notes = subject.read_json('demo-notes.json') or {'notes': []}
    return [pending.PendingItem('demo-note:%s' % n['id'], '示例便签 %s' % n['id'], body=n['text'],
                                facts=(('来源', 'demo'),), payload={'note_id': n['id']})
            for n in notes['notes'] if 'verdict' not in n]


def _demo_apply(subject, item, code, now):
    notes = subject.read_json('demo-notes.json')
    for n in notes['notes']:
        if n['id'] == item['payload']['note_id']:
            n['verdict'] = {'K': 'keep', 'D': 'drop'}[code]
    subject.stage_json('demo-notes.json', notes)


DEMO_TYPE = pending.ItemType(key='demo-note', label='示例便签', options=(('K', '保留'), ('D', '丢弃')),
                             collect=_demo_collect, apply=_demo_apply, priority=50)


class ExtensibleTypeTest(unittest.TestCase):
    def setUp(self):
        self.env = Env(self)
        self.run_dir = make_run(self.env.repo)
        self.reg = pending.default_registry()
        self.reg.register(DEMO_TYPE)

    def _notes(self, n):
        _support.write(self.run_dir / 'demo-notes.json', json.dumps(
            {'notes': [{'id': 'n%02d' % i, 'text': '便签正文 %d <b>' % i} for i in range(n)]}, ensure_ascii=False))

    def test_new_type_renders_and_writes_back(self):
        self._notes(2)
        page = pending.generate(self.env.data, 'demo', now=lambda: T0, types=self.reg)
        html = page.html_path.read_text(encoding='utf-8')
        self.assertIn('示例便签', html)
        self.assertIn('保留', html)
        self.assertIn('便签正文 1 &lt;b&gt;', html)     # 正文转义
        self.assertEqual([i['type'] for i in page.items], ['report-review', 'demo-note', 'demo-note'])
        pending.apply_reply(self.env.data, 'demo', 'PE1 %s %s 2K 3D' % (RUN_ID, page.page_id),
                            now=lambda: T1, types=self.reg)
        notes = read_json(self.run_dir / 'demo-notes.json')['notes']
        self.assertEqual([n.get('verdict') for n in notes], ['keep', 'drop'])
        self.assertEqual(read_json(self.run_dir / 'run.json')['review']['status'], '待审', '未裁定报告审阅项')

    def test_global_register_type(self):
        """register_type 挂到默认注册表上，generate 不传 types 也能用。"""
        pending.register_type(DEMO_TYPE)
        self.addCleanup(pending.unregister_type, DEMO_TYPE.key)
        self._notes(1)
        page = pending.generate(self.env.data, 'demo', now=lambda: T0)
        self.assertEqual([i['type'] for i in page.items], ['report-review', 'demo-note'])

    def test_sampling_caps_page_at_ten_and_report_lists_them(self):
        self._notes(14)
        page = pending.generate(self.env.data, 'demo', now=lambda: T0, types=self.reg)
        self.assertEqual(len(page.items), pending.PAGE_LIMIT)
        self.assertEqual(page.items[0]['type'], 'report-review', '报告审阅必入页')
        self.assertEqual(page.total, 15)
        html = page.html_path.read_text(encoding='utf-8')
        self.assertEqual(len(re.findall(r'class="item"', html)), 10)
        rec = read_json(self.run_dir / 'run.json')
        self.assertTrue(rec['pending']['sampled'])
        self.assertEqual(len(rec['pending']['sampled_out']), 5)
        report = (self.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn('## 待审页抽样', report)
        self.assertIn('15 项', report)
        for it in page.items:
            self.assertIn(it['id'], report)
        for sid in rec['pending']['sampled_out']:
            self.assertIn(sid, report)
        # 同一次运行重复生成，抽样结果不变（种子取 run_id）
        page2 = pending.generate(self.env.data, 'demo', now=lambda: T1, types=self.reg)
        self.assertEqual([i['id'] for i in page2.items], [i['id'] for i in page.items])
        self.assertEqual(read_json(self.run_dir / 'run.json')['pending']['page_id'], page2.page_id)
        self.assertEqual((self.run_dir / 'report.md').read_text(encoding='utf-8').count('## 待审页抽样'), 1)

    def test_sampling_section_removed_when_not_sampled(self):
        self._notes(14)
        pending.generate(self.env.data, 'demo', now=lambda: T0, types=self.reg)
        self._notes(2)
        pending.generate(self.env.data, 'demo', now=lambda: T1, types=self.reg)
        self.assertNotIn('## 待审页抽样', (self.run_dir / 'report.md').read_text(encoding='utf-8'))
        self.assertFalse(read_json(self.run_dir / 'run.json')['pending']['sampled'])

class RobustnessTest(unittest.TestCase):
    """票 08 审查 M1 / M2 / M3 / L2。"""

    def setUp(self):
        self.env = Env(self)
        self.run_dir = make_run(self.env.repo)

    def test_writeback_failure_cleans_tmp_and_reports_written_files(self):
        page = pending.generate(self.env.data, 'demo', now=lambda: T0)
        before = (self.run_dir / 'run.json').read_bytes()
        real_replace = pending.os.replace

        def flaky(src, dst):
            if Path(dst).name == 'run.json':
                raise OSError('磁盘满')
            return real_replace(src, dst)
        code = 'PE1 %s %s 1A' % (RUN_ID, page.page_id)
        pending.os.replace = flaky
        try:
            with self.assertRaises(pending.PendingError) as cm:
                pending.apply_reply(self.env.data, 'demo', code, now=lambda: T1)
        finally:
            pending.os.replace = real_replace
        self.assertIn('run.json', str(cm.exception))
        self.assertIn('report.md', str(cm.exception))                  # 列出已写成的文件
        self.assertEqual(list(self.run_dir.glob('*.pending-tmp')), [])
        self.assertEqual((self.run_dir / 'run.json').read_bytes(), before)
        pending.apply_reply(self.env.data, 'demo', code, now=lambda: T1)   # 同一回复码重试补齐
        self.assertEqual(read_json(self.run_dir / 'run.json')['review']['status'], '已审')

    def test_corrupt_history_run_skipped_unless_selected(self):
        bad = '20261016T080000Z-1.2.4-compare'
        _support.write(self.env.repo / 'plugin-evals' / 'demo' / 'runs' / bad / 'run.json', '{坏')
        self.assertEqual(pending.generate(self.env.data, 'demo', now=lambda: T0).run_id, RUN_ID)
        with self.assertRaises(pending.PendingError):
            pending.generate(self.env.data, 'demo', run_id=bad, now=lambda: T0)

    def test_home_path_scrubbed_in_run_json_and_report(self):
        home = str(Path.home())
        reg = pending.default_registry()
        reg.register(pending.ItemType(
            key='pathy', label='带路径', options=(('K', '留'),), priority=50,
            collect=lambda s: [pending.PendingItem('pathy:%d' % i, '样本 %s/x/%d.jsonl' % (home, i),
                                                   payload={'path': '%s/x/%d.jsonl' % (home, i)}) for i in range(12)],
            apply=lambda *a: None))
        pending.generate(self.env.data, 'demo', now=lambda: T0, types=reg)
        run_json = (self.run_dir / 'run.json').read_text(encoding='utf-8')
        report = (self.run_dir / 'report.md').read_text(encoding='utf-8')
        self.assertIn('## 待审页抽样', report)
        self.assertNotIn(home + '/', run_json)
        self.assertNotIn(home + '/', report)
        self.assertIn('~/x/', run_json)

    def test_collect_error_is_pending_error(self):
        def bad(subject):
            raise ValueError('坏了')
        reg = pending.default_registry()
        reg.register(pending.ItemType(key='bad', label='坏类型', options=(('X', 'x'),), collect=bad, apply=None))
        before = snapshot(self.env.root)
        with self.assertRaises(pending.PendingError) as cm:
            pending.generate(self.env.data, 'demo', now=lambda: T0, types=reg)
        self.assertIn('坏类型', str(cm.exception))
        no_locks = lambda snap: {k: v for k, v in snap.items() if not k.startswith('data/locks/')}   # 锁文件是空壳，不算改动
        self.assertEqual(no_locks(snapshot(self.env.root)), no_locks(before))

    def test_item_without_type_is_reply_error(self):
        page = pending.generate(self.env.data, 'demo', now=lambda: T0)
        rec = read_json(self.run_dir / 'run.json')
        del rec['pending']['items'][0]['type']
        (self.run_dir / 'run.json').write_text(json.dumps(rec, ensure_ascii=False), encoding='utf-8')
        with self.assertRaises(pending.ReplyError) as cm:
            pending.apply_reply(self.env.data, 'demo', 'PE1 %s %s 1A' % (RUN_ID, page.page_id), now=lambda: T1)
        self.assertIn('没有注册写回逻辑', str(cm.exception))


class SelectTest(unittest.TestCase):
    def test_priority_then_seeded_sample_keeps_order(self):
        a = pending.ItemType(key='a', label='A', options=(('X', 'x'),), collect=None, apply=None, always=True)
        b = pending.ItemType(key='b', label='B', options=(('X', 'x'),), collect=None, apply=None, priority=10)
        c = pending.ItemType(key='c', label='C', options=(('X', 'x'),), collect=None, apply=None, priority=20)
        items = [('a', 'a:1')] + [('b', 'b:%d' % i) for i in range(4)] + [('c', 'c:%d' % i) for i in range(10)]
        types = {'a': a, 'b': b, 'c': c}
        kept, out = pending.select_items(items, types, limit=10, seed='s')
        self.assertEqual(len(kept), 10)
        self.assertEqual([k[1] for k in kept[:5]], ['a:1', 'b:0', 'b:1', 'b:2', 'b:3'])
        self.assertEqual(len(out), 5)
        self.assertTrue(all(o[1].startswith('c:') for o in out))
        cs = [k[1] for k in kept[5:]]
        self.assertEqual(cs, sorted(cs, key=lambda x: int(x.split(':')[1])), '抽中的项保持原顺序')
        self.assertEqual(pending.select_items(items, types, limit=10, seed='s'), (kept, out))


class CliTest(unittest.TestCase):
    def test_cli_generate_and_reply(self):
        import io
        from contextlib import redirect_stdout, redirect_stderr
        from plugin_eval_lib import cli
        env = Env(self)
        run_dir = make_run(env.repo)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(['--data-dir', str(env.data), 'pending', 'demo']), 0)
        m = re.search(r'PE1 \S+ ([0-9a-f]{8})', out.getvalue())
        self.assertIsNotNone(m, out.getvalue())
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--data-dir', str(env.data), 'pending', 'demo', '--reply', 'xx']), 2)
        self.assertIn('回复码', err.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--data-dir', str(env.data), 'pending', 'demo', '--reply',
                                       'PE1 %s %s 1A' % (RUN_ID, m.group(1))]), 0)
        self.assertEqual(read_json(run_dir / 'run.json')['review']['status'], '已审')


if __name__ == '__main__':
    unittest.main()
