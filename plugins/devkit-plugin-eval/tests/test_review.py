"""会话复盘（票 12）：合成的假会话记录，不用任何真实转录。

假会话里到处埋了 SECRET 标记（prompt、tool_result、注入正文、hook stdout），断言结果文件里一个都没有。
"""
import contextlib
import io
import json
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _support  # noqa: E402
from _support import write  # noqa: E402

from plugin_eval_lib import pending, registry, review, review_pending, review_scan  # noqa: E402

NOW = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
SECRET = 'SECRET-原文-7f3a'
GUARD_CMD = 'node ${CLAUDE_PLUGIN_ROOT}/hooks/guard.js'
SESSION_CMD = 'python3 ${CLAUDE_PLUGIN_ROOT}/hooks/session.py'
UPS_CMD = 'python3 ${CLAUDE_PLUGIN_ROOT}/hooks/ups.py'
OTHER_CMD = 'node ${CLAUDE_PLUGIN_ROOT}/hooks/other.js'
# 会话 id 是 uuid（复盘结果的指针白名单要求）
S1 = '5e55a1e1-0000-4000-8000-000000000001'
S2 = '5e55a1e1-0000-4000-8000-000000000002'
S3 = '5e55a1e1-0000-4000-8000-000000000003'
S9 = '5e55a1e1-0000-4000-8000-000000000009'
OLD = '5e55a1e1-0000-4000-8000-0000000000aa'


def _hooks(entries):
    """entries: [(事件, matcher, command)] → hooks.json 文本。"""
    out = {}
    for ev, m, cmd in entries:
        g = {'hooks': [{'type': 'command', 'command': cmd}]}
        if m:
            g['matcher'] = m
        out.setdefault(ev, []).append(g)
    return json.dumps({'hooks': out})


def _ts(minute):
    return '2026-10-15T08:%02d:00.000Z' % minute


class Fixture(object):
    def __init__(self, tc):
        self.root = _support.tmpdir(tc)
        self.repo = self.root / 'repo'
        self.cfg = self.root / 'config'
        self.data = self.root / 'data'
        self.projects = self.cfg / 'projects' / '-tmp-proj'
        g = self.repo / 'plugins' / 'demo-guard'
        write(g / '.claude-plugin' / 'plugin.json', json.dumps({'name': 'demo-guard', 'version': '2.0.0'}))
        write(g / 'hooks' / 'hooks.json', _hooks([('PreToolUse', 'Bash', GUARD_CMD), ('SessionStart', None, SESSION_CMD),
                                                  ('UserPromptSubmit', None, UPS_CMD)]))
        write(g / 'hooks' / 'guard.js', '// 演示\n')
        write(g / 'hooks' / 'session.py', 'print("# 演示守卫规则")\n')
        write(g / 'hooks' / 'ups.py', 'print("# 每轮要点甲")\n')
        q = self.repo / 'plugins' / 'quiet-plugin'
        write(q / '.claude-plugin' / 'plugin.json', json.dumps({'name': 'quiet-plugin', 'version': '0.1.0'}))
        write(self.repo / '.claude-plugin' / 'marketplace.json',
              json.dumps({'name': 'mkt', 'plugins': [], 'renames': {'old-guard': 'demo-guard', 'gone': None}}))
        other = self.root / 'installed' / 'other-plugin'
        write(other / '.claude-plugin' / 'plugin.json', json.dumps({'name': 'other-plugin', 'version': '9.9.9'}))
        write(other / 'hooks' / 'hooks.json', _hooks([('SessionStart', None, OTHER_CMD), ('PreToolUse', 'Bash', GUARD_CMD)]))
        write(self.cfg / 'plugins' / 'installed_plugins.json', json.dumps({'version': 2, 'plugins': {
            'other-plugin@mkt': [{'scope': 'project', 'projectPath': '/home/u/secret-project', 'installPath': str(other),
                                  'version': '9.9.9'}],
            'old-guard@mkt': [{'scope': 'user', 'installPath': str(self.root / 'nope'), 'version': '1.0.0'}]}}))
        registry.register(self.data, 'demo-guard', self.repo)
        registry.register(self.data, 'quiet-plugin', self.repo)

    def env(self):
        return dict(os.environ, CLAUDE_CONFIG_DIR=str(self.cfg))

    def run(self, **kw):
        kw.setdefault('hook_labels', False)
        kw.setdefault('tz', timezone.utc)
        return review.run_review(self.data, now=NOW, env=self.env(), log=lambda m: None, **kw)

    def load(self, name='demo-guard'):
        return json.loads((self.repo / 'plugin-evals' / name / 'reviews' / '2026-10-15.json').read_text(encoding='utf-8'))


def att(uuid, minute, a, **extra):
    r = {'type': 'attachment', 'uuid': uuid, 'timestamp': _ts(minute), 'sessionId': S1, 'version': '2.1.299',
         'attachment': a}
    r.update(extra)
    return r


def deny(uuid, minute, version_dir='1.0.0', plugin_dir='old-guard', check='no-cd', session=S1, trailer=True):
    text = ('PreToolUse:Bash hook error: [node /home/u/.claude/plugins/cache/mkt/%s/%s/hooks/guard.js]: '
            '[BLOCK] check=%s 不许这样做 %s' % (plugin_dir, version_dir, check, SECRET))
    if trailer:
        text += '\n\nThis hook comes from the %s@mkt plugin.' % plugin_dir
    return {'type': 'user', 'uuid': uuid, 'timestamp': _ts(minute), 'sessionId': session, 'version': '2.1.299',
            'permissionDecision': {'decision': 'reject', 'source': 'hook', 'reasonType': 'hook'},
            'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'is_error': True,
                                                     'content': text}]}}


def main_session():
    return [
        {'type': 'user', 'uuid': 'u1', 'timestamp': _ts(1), 'sessionId': S1, 'version': '2.1.299', 'entrypoint': 'cli',
         'message': {'role': 'user', 'content': '<command-name>/demo-guard:helper</command-name> %s' % SECRET}},
        att('a1', 1, {'type': 'skill_listing', 'names': ['demo-guard:helper', 'other-plugin:x', 'quiet-plugin:y', '.proj/worktrees/D-1-secret:z', 'bare'],
                      'content': SECRET}, entrypoint='cli'),
        att('a2', 1, {'type': 'hook_success', 'hookName': 'SessionStart:startup', 'hookEvent': 'SessionStart',
                      'toolUseID': 'x1', 'command': SESSION_CMD, 'stdout': '# 演示守卫规则\n%s' % SECRET,
                      'content': '', 'durationMs': 40, 'exitCode': 0}),
        att('a3', 1, {'type': 'hook_additional_context', 'hookName': 'SessionStart', 'hookEvent': 'SessionStart',
                      'toolUseID': 'SessionStart', 'content': ['# 演示守卫规则\n%s' % SECRET]}),
        att('a4', 1, {'type': 'hook_success', 'hookName': 'SessionStart:startup', 'hookEvent': 'SessionStart',
                      'toolUseID': 'x2', 'command': OTHER_CMD, 'stdout': '# 别的插件\n%s' % SECRET, 'durationMs': 5}),
        att('a5', 1, {'type': 'hook_additional_context', 'hookName': 'SessionStart', 'hookEvent': 'SessionStart',
                      'toolUseID': 'SessionStart', 'content': ['# 别的插件\n%s' % SECRET]}),
        {'type': 'assistant', 'uuid': 'm1', 'timestamp': _ts(2), 'sessionId': S1, 'version': '2.1.299',
         'attributionSkill': 'demo-guard:helper', 'attributionPlugin': 'demo-guard',
         'message': {'model': 'model-a', 'content': [
             {'type': 'tool_use', 'id': 't0', 'name': 'Skill', 'input': {'skill': 'old-guard:helper', 'args': SECRET}},
             {'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {'command': 'cd /x && %s' % SECRET}}]}},
        deny('u2', 3),
        att('a6', 3, {'type': 'hook_success', 'hookName': 'PreToolUse:Bash', 'hookEvent': 'PreToolUse', 'toolUseID': 't1',
                      'command': GUARD_CMD, 'stdout': '', 'durationMs': 120}),
        {'type': 'system', 'subtype': 'compact_boundary', 'uuid': 's1', 'timestamp': _ts(10), 'sessionId': S1,
         'version': '2.1.299', 'compactMetadata': {'trigger': 'auto'}},
        {'type': 'user', 'uuid': 'u3', 'timestamp': _ts(10), 'sessionId': S1, 'isCompactSummary': True,
         'message': {'role': 'user', 'content': '摘要 %s' % SECRET}},
        att('a7', 10, {'type': 'hook_success', 'hookName': 'SessionStart:compact', 'hookEvent': 'SessionStart',
                       'toolUseID': 'x3', 'command': SESSION_CMD, 'stdout': '# 演示守卫规则\n再来 %s' % SECRET,
                       'durationMs': 60}),
        att('a8', 10, {'type': 'hook_additional_context', 'hookName': 'SessionStart', 'hookEvent': 'SessionStart',
                       'toolUseID': 'SessionStart', 'content': ['# 演示守卫规则\n再来 %s' % SECRET]}),
        deny('u4', 11, version_dir='2.0.0', plugin_dir='demo-guard', trailer=False),
        att('a9', 12, {'type': 'hook_additional_context', 'hookName': 'UserPromptSubmit', 'hookEvent': 'UserPromptSubmit',
                       'toolUseID': 'hook-1', 'content': ['# 每轮提醒（demo-guard）\n%s' % SECRET]}),
        att('a10', 12, {'type': 'hook_additional_context', 'hookName': 'UserPromptSubmit', 'hookEvent': 'UserPromptSubmit',
                        'toolUseID': 'hook-2', 'content': ['# 每轮要点甲\n%s' % SECRET]}),
        att('a11', 12, {'type': 'hook_non_blocking_error', 'hookName': 'UserPromptSubmit', 'hookEvent': 'UserPromptSubmit',
                        'toolUseID': 'hook-3', 'command': UPS_CMD, 'stderr': SECRET, 'stdout': '', 'exitCode': 1,
                        'durationMs': 7}),
        {'type': 'assistant', 'uuid': 'm2', 'timestamp': _ts(13), 'sessionId': S1, 'version': '2.1.300',
         'message': {'model': 'model-b', 'content': [{'type': 'text', 'text': SECRET}]}},
    ]


def dump(path, recs, extra_lines=()):
    write(path, '\n'.join([json.dumps(r, ensure_ascii=False) for r in recs] + list(extra_lines)) + '\n')


def standard_sessions(fx):
    recs = main_session()
    dump(fx.projects / (S1 + '.jsonl'), recs)
    # resume 复制：历史（含 compact 边界与其后的重新注入）原样复制进新文件，再加一条新记录
    old = os.path.getmtime(fx.projects / (S1 + '.jsonl')) - 100
    os.utime(fx.projects / (S1 + '.jsonl'), (old, old))
    copy = [dict(r, sessionId=S2) for r in recs[:13]]
    copy.append(dict(deny('u9', 20, session=S2, check='other-check'), version='2.1.300'))
    dump(fx.projects / (S2 + '.jsonl'), copy)
    # 子代理里的拦截
    dump(fx.projects / S1 / 'subagents' / 'agent-abc.jsonl',
         [dict(deny('sub-u1', 5), isSidechain=True, agentId='abc')])
    # 窗口外：文件过旧整个跳过；记录过旧单条跳过
    dump(fx.projects / (OLD + '.jsonl'), [deny('old-1', 1)])
    t = time.mktime((2026, 8, 1, 0, 0, 0, 0, 0, -1))
    os.utime(fx.projects / (OLD + '.jsonl'), (t, t))
    stale = deny('stale-1', 1)
    stale['timestamp'] = '2026-08-01T00:00:00.000Z'
    dump(fx.projects / (S3 + '.jsonl'), [stale], extra_lines=['{坏行', ''])


class ReviewScanTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture(self)
        standard_sessions(self.fx)

    def test_every_registered_plugin_gets_a_file_even_with_zero_counts(self):
        out = self.fx.run()
        self.assertEqual(sorted(n for n, _, _ in out), ['demo-guard', 'quiet-plugin'])
        q = self.fx.load('quiet-plugin')
        self.assertEqual(q['kind'], 'review')
        self.assertEqual(q['signals']['blocks'], {})
        self.assertEqual(q['candidates'], [])
        self.assertEqual(q['run_id'], 'review-2026-10-15')

    def test_result_has_no_original_text_or_paths(self):
        self.fx.run()
        for name in ('demo-guard', 'quiet-plugin'):
            text = (self.fx.repo / 'plugin-evals' / name / 'reviews' / '2026-10-15.json').read_text(encoding='utf-8')
            self.assertNotIn(SECRET, text)
            self.assertNotIn('SECRET', text)
            self.assertNotIn('/home/u', text)
            self.assertNotIn('secret-project', text)
            self.assertNotIn('摘要', text)
            self.assertEqual(review.assert_no_text(json.loads(text)), [])

    def test_resume_copies_are_counted_once(self):
        self.fx.run()
        rec = self.fx.load()
        blocks = rec['signals']['blocks']
        # 主会话 2 次 + 子代理 1 次（no-cd），S2 新增 1 次（other-check）；S2 复制的那次不重复计
        self.assertEqual(blocks['hooks/guard.js#check=no-cd']['total'], 3)
        self.assertEqual(blocks['hooks/guard.js#check=other-check']['total'], 1)
        self.assertEqual(rec['signals']['skills']['demo-guard:helper'], {'slash': 1, 'tool': 1, 'attributed_records': 1})
        self.assertGreaterEqual(rec['scan']['duplicate_records'], 8)
        self.assertEqual(rec['signals']['injections']['by_event:SessionStart'], 2)

    def test_subagent_blocks_are_counted(self):
        self.fx.run()
        s = self.fx.load()['signals']['blocks']['hooks/guard.js#check=no-cd']
        self.assertEqual(s['subagent'], 1)
        self.assertEqual(s['main'], 2)
        self.assertEqual(self.fx.load()['scan']['subagent_files'], 1)

    def test_old_names_normalized_and_versions_from_cache_path(self):
        self.fx.run()
        rec = self.fx.load()
        s = rec['signals']['blocks']['hooks/guard.js#check=no-cd']
        self.assertEqual(s['plugin_versions'], {'1.0.0': 2, '2.0.0': 1})
        self.assertEqual(s['before_compact'], 2)
        self.assertEqual(s['after_compact'], 1)
        self.assertEqual(rec['scan']['field_coverage']['deny_trailer'], 3)

    def test_window_filters_old_files_and_records_and_tolerates_bad_lines(self):
        self.fx.run()
        rec = self.fx.load()
        self.assertEqual(rec['scan']['main_files'], 3)        # S1、S2、S3；OLD 超窗跳过
        self.assertGreaterEqual(rec['scan']['out_of_window_records'], 1)
        self.assertEqual(rec['scan']['bad_lines'], 1)
        self.assertEqual(rec['window']['days'], 30)
        self.assertEqual(rec['scan']['claude_code_versions'], {'2.1.299': 17, '2.1.300': 2})

    def test_injection_attribution(self):
        self.fx.run()
        inj = self.fx.load()['signals']['injections']
        self.assertEqual(inj['total'], 3)                     # 两次 SessionStart（指纹）+ 一次 UPS（插件名标签）
        self.assertEqual(inj['via:fingerprint'], 2)
        self.assertEqual(inj['via:label'], 1)
        self.assertEqual(inj['after_compact'], 2)
        self.assertEqual(self.fx.load()['scan']['unattributed_injections'], {'UserPromptSubmit': 1})
        compact = self.fx.load()['signals']['compact']
        # S2 复制来的边界与重新注入不重复计
        self.assertEqual(compact, {'has_session_start_hook': True, 'boundaries_seen': 1, 'reinjected_after': 1})

    def test_static_labels_attribute_unlabelled_injection(self):
        self.fx.run(hook_labels=True)
        inj = self.fx.load()['signals']['injections']
        self.assertEqual(inj['via:label'], 2)
        self.assertEqual(self.fx.load()['scan']['unattributed_injections'], {})

    def test_hook_errors_latency_and_environment(self):
        self.fx.run()
        rec = self.fx.load()
        self.assertEqual(rec['signals']['hook_errors']['hooks/ups.py']['total'], 1)
        lat = rec['signals']['hook_latency']
        # guard.js 的声明与已装的 other-plugin 撞名、stdout 又没有标签：归不了，不算进任何一方
        self.assertNotIn('PreToolUse|Bash|%s' % GUARD_CMD, lat)
        self.assertEqual(lat['SessionStart||%s' % SESSION_CMD]['count'], 2)
        self.assertEqual(lat['SessionStart||%s' % SESSION_CMD]['max_ms'], 60)
        env = rec['environment']
        self.assertEqual(env['claude_code_version'], '2.1.300')
        self.assertEqual(env['main_model'], 'model-b')
        # 只具名登记过的插件；未登记的（第三方、内部插件、项目级 skill 目录）只计个数
        self.assertEqual([p['name'] for p in env['co_loaded_plugins']], ['quiet-plugin'])
        self.assertEqual(env['co_loaded_unregistered_count'], 2)
        self.assertNotIn('D-1-secret', json.dumps(rec))
        self.assertEqual(rec['plugin']['installed'], [{'id': 'old-guard@mkt', 'version': '1.0.0', 'scope': 'user'}])

    def test_candidates_are_pointers_only(self):
        self.fx.run()
        cands = self.fx.load()['candidates']
        keys = sorted((c['kind'], c['rule'], c['after_compact'], c['count']) for c in cands)
        self.assertEqual(keys, [('block', 'hooks/guard.js#check=no-cd', False, 2),
                                ('block', 'hooks/guard.js#check=no-cd', True, 1),
                                ('block', 'hooks/guard.js#check=other-check', True, 1),     # S2 复制了边界，在其后
                                ('hook_error', 'hooks/ups.py', True, 1)])
        c = [c for c in cands if c['rule'].endswith('no-cd') and not c['after_compact']][0]
        self.assertEqual(c['subagent_count'], 1)
        self.assertEqual({p['uuid'] for p in c['pointers']}, {'u2', 'sub-u1'})
        self.assertEqual(sorted(c['pointers'][0]), ['agent_id', 'claude_code_version', 'plugin_version', 'session_id',
                                                    'timestamp', 'uuid'])
        self.assertEqual(c['clause_ids'], [])

    def _clauses(self, items):
        write(self.fx.repo / 'plugin-evals' / 'demo-guard' / 'clauses.json',
              json.dumps({'schema_version': 1, 'clauses': items}))

    def test_clause_ids_derived_from_events_and_hook_rules(self):
        """票 10 的 clauses.json：规则脚本挂在哪些事件（hooks.json）× 未退役条款的 events，唯一相交才映射。"""
        self._clauses([
            {'id': 'C001', 'criterion': '不用独立 cd', 'events': ['PreToolUse'], 'status': 'active'},
            {'id': 'C002', 'criterion': '旧条款', 'events': ['PreToolUse'], 'status': 'retired'},
            {'id': 'C003', 'criterion': '每轮要点', 'events': ['UserPromptSubmit'], 'status': 'active'},
            {'id': 'C004', 'criterion': '每轮另一条', 'events': ['UserPromptSubmit'], 'status': 'active'}])
        self.fx.run()
        cands = {(c['rule'], c['after_compact']): c for c in self.fx.load()['candidates']}
        guard = cands[('hooks/guard.js#check=no-cd', False)]
        self.assertEqual(guard['clause_ids'], ['C001'])              # 退役的 C002 不参与
        self.assertEqual(guard['clause_mapping']['status'], 'mapped')
        ups = cands[('hooks/ups.py', True)]
        self.assertEqual(ups['clause_ids'], [])                       # 两条都含 UserPromptSubmit：推不出
        self.assertEqual(ups['clause_mapping']['status'], 'unmapped')
        self.assertIn('C003', ups['clause_mapping']['reason'])
        page = review_pending.generate(self.fx.data, 'demo-guard', now=lambda: NOW)
        self.assertIn('未映射', page.html_path.read_text(encoding='utf-8'))

    def test_no_clause_list_means_unmapped(self):
        self.fx.run()
        for c in self.fx.load()['candidates']:
            self.assertEqual(c['clause_ids'], [])
            self.assertEqual(c['clause_mapping'], {'status': 'unmapped', 'reason': '没有可用的条款清单'})

    def test_main_model_is_per_plugin_and_no_global_model_list(self):
        self.fx.run()
        self.assertEqual(self.fx.load()['environment']['main_model'], 'model-b')
        self.assertNotIn('models', self.fx.load()['environment'])
        # quiet-plugin 只在 skill 清单里出现过，同一会话：同一个主力模型
        self.assertEqual(self.fx.load('quiet-plugin')['environment']['main_model'], 'model-b')

    def test_compact_denominator_skips_sessions_without_the_plugin(self):
        """别的会话里 compact 了、但在那之前从没出现过该插件的注入或 hook_success：不进分母。"""
        recs = [{'type': 'user', 'uuid': 'x-u1', 'timestamp': _ts(40), 'sessionId': S9, 'version': '2.1.300',
                 'message': {'role': 'user', 'content': 'hi'}},
                {'type': 'system', 'subtype': 'compact_boundary', 'uuid': 'x-s1', 'timestamp': _ts(41), 'sessionId': S9,
                 'version': '2.1.300', 'compactMetadata': {'trigger': 'auto'}}]
        dump(self.fx.projects / (S9 + '.jsonl'), recs)
        self.fx.run()
        self.assertEqual(self.fx.load()['signals']['compact']['boundaries_seen'], 1)

    def test_self_check_runs_before_scrub_and_rejects_home_paths(self):
        rec = {'note': '~/.claude/plugins/x', 'ok': 'hooks/guard.js'}
        self.assertEqual(review.assert_no_text(rec), ['$.note'])

    def test_pointer_whitelist(self):
        good = {'candidates': [{'rule': 'hooks/guard.js#check=no-cd', 'pointers': [
            {'session_id': S1, 'agent_id': 'abc', 'uuid': 'u1', 'timestamp': _ts(1), 'plugin_version': '1.0.0',
             'claude_code_version': '2.1.299'}]}], 'signals': {'blocks': {'?': {}}, 'hook_errors': {'hooks/ups.py': {}}}}
        self.assertEqual(review.check_pointers(good), [])
        bad = json.loads(json.dumps(good))
        bad['candidates'][0]['pointers'][0]['session_id'] = 'not a uuid'
        bad['candidates'][0]['pointers'][0]['timestamp'] = 'yesterday'
        bad['candidates'][0]['rule'] = 'cd /x && rm'
        bad['signals']['blocks'] = {'说了一句话': {}}
        self.assertEqual(sorted(review.check_pointers(bad)), sorted([
            '$.candidates[0].pointers[0].session_id', '$.candidates[0].pointers[0].timestamp', '$.candidates[0].rule',
            '$.signals.blocks.<key>']))

    def test_bad_pointer_in_any_plugin_writes_nothing(self):
        """先全部自检再写盘：一个插件不过，整批都不写。"""
        dump(self.fx.projects / 'not-a-uuid.jsonl', [deny('bad-1', 30, session='not-a-uuid', check='x')])
        with self.assertRaises(review.ReviewError):
            self.fx.run()
        self.assertFalse((self.fx.repo / 'plugin-evals' / 'quiet-plugin' / 'reviews').exists())
        self.assertFalse((self.fx.repo / 'plugin-evals' / 'demo-guard' / 'reviews').exists())

    def test_write_takes_the_review_lock(self):
        from plugin_eval_lib import resume
        lock = resume.RunLock(self.fx.data, 'review-demo-guard-2026-10-15')
        lock.acquire()
        try:
            with self.assertRaises(review.ReviewError):
                self.fx.run()
        finally:
            lock.release()
        self.fx.run()

    def test_date_is_local_with_offset(self):
        tz = timezone(timedelta(hours=14))               # 12:00 UTC = 次日 02:00
        out = self.fx.run(tz=tz)
        path = out[0][1]
        self.assertEqual(path.name, '2026-10-16.json')
        rec = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual((rec['date'], rec['tz_offset'], rec['date_basis']), ('2026-10-16', '+14:00', 'local'))
        self.assertEqual(rec['generated_at'], '2026-10-15T12:00:00Z')

    def test_decision_carries_across_dates_unless_version_changed(self):
        self.fx.run()
        page = review_pending.generate(self.fx.data, 'demo-guard', now=lambda: NOW)
        pending.apply_reply(self.fx.data, 'demo-guard', 'PE1 review-2026-10-15 %s 1A' % page.page_id, now=lambda: NOW)
        cid = page.items[0]['payload']['candidate_id']
        later = NOW + timedelta(days=1)
        review.run_review(self.fx.data, now=later, env=self.fx.env(), log=lambda m: None, hook_labels=False,
                          tz=timezone.utc)
        path = self.fx.repo / 'plugin-evals' / 'demo-guard' / 'reviews' / '2026-10-16.json'
        c = [c for c in json.loads(path.read_text(encoding='utf-8'))['candidates'] if c['id'] == cid][0]
        self.assertEqual(c['selection'], 'draft')
        self.assertEqual(c['carried_from']['date'], '2026-10-15')
        self.assertEqual(c['carried_from']['run_id'], 'review-2026-10-15')
        self.assertEqual(c['carried_from']['decided_at'], '2026-10-15T12:00:00Z')
        # 插件版本变了：不沿用，重新上页
        write(self.fx.repo / 'plugins' / 'demo-guard' / '.claude-plugin' / 'plugin.json',
              json.dumps({'name': 'demo-guard', 'version': '2.1.0'}))
        review.run_review(self.fx.data, now=later + timedelta(days=1), env=self.fx.env(), log=lambda m: None,
                          hook_labels=False, tz=timezone.utc)
        path = self.fx.repo / 'plugin-evals' / 'demo-guard' / 'reviews' / '2026-10-17.json'
        c = [c for c in json.loads(path.read_text(encoding='utf-8'))['candidates'] if c['id'] == cid][0]
        self.assertIsNone(c['selection'])
        self.assertIsNone(c['carried_from'])

    def test_preflight_failure_aborts(self):
        empty = self.fx.root / 'empty-config'
        (empty / 'projects').mkdir(parents=True)
        with self.assertRaises(review.preflight.PreflightFailed):
            review.run_review(self.fx.data, now=NOW, env=dict(os.environ, CLAUDE_CONFIG_DIR=str(empty)),
                              hook_labels=False, log=lambda m: None)


class ReviewPendingTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture(self)
        standard_sessions(self.fx)

    def _previous_compare(self, version, model):
        d = self.fx.repo / 'plugin-evals' / 'demo-guard' / 'runs' / '20261010T000000Z-2.0.0-compare'
        write(d / 'run.json', json.dumps({'kind': 'compare', 'run_id': d.name, 'complete': True,
                                          'claude_code_version': version, 'main_model': model}))

    def test_compare_hint_appears_when_version_or_model_changed(self):
        self._previous_compare('2.1.200', 'model-b')
        self.fx.run()
        hint = self.fx.load()['compare_hint']
        self.assertTrue(hint['suggest'])
        self.assertEqual(hint['diffs'], [{'field': 'Claude Code 版本', 'previous': '2.1.200', 'current': '2.1.300'}])
        page = review_pending.generate(self.fx.data, 'demo-guard', now=lambda: NOW)
        self.assertEqual(page.items[0]['type'], 'review-compare-hint')
        html = page.html_path.read_text(encoding='utf-8')
        self.assertIn('建议跑对照', html)
        self.assertNotIn(SECRET, html)
        res = pending.apply_reply(self.fx.data, 'demo-guard', 'PE1 review-2026-10-15 %s 1A' % page.page_id,
                                  now=lambda: NOW)
        self.assertEqual(res.changed_files, ['plugin-evals/demo-guard/reviews/2026-10-15.json'])
        self.assertEqual(self.fx.load()['compare_hint']['acknowledged_at'], '2026-10-15T12:00:00Z')

    def test_no_hint_when_same_as_previous_compare(self):
        self._previous_compare('2.1.300', 'model-b')
        self.fx.run()
        self.assertFalse(self.fx.load()['compare_hint']['suggest'])
        page = review_pending.generate(self.fx.data, 'demo-guard', now=lambda: NOW)
        self.assertNotIn('review-compare-hint', [i['type'] for i in page.items])

    def test_candidates_on_page_and_selection_written_back_and_kept_on_rerun(self):
        self.fx.run()
        page = review_pending.generate(self.fx.data, 'demo-guard', '2026-10-15', now=lambda: NOW)
        self.assertEqual([i['type'] for i in page.items], ['review-candidate'] * 4)
        self.assertTrue(page.html_path.name.startswith('review-2026-10-15'))
        self.assertNotIn(SECRET, page.html_path.read_text(encoding='utf-8'))
        args = type('A', (), {'name': 'demo-guard', 'reply': 'PE1 review-2026-10-15 %s 1A 2B' % page.page_id,
                              'run': None, 'review': None})
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(pending.main(args, self.fx.data), 0)
        self.assertIn('已写回运行 review-2026-10-15', out.getvalue())
        rec = self.fx.load()
        ids = {i['no']: i['payload']['candidate_id'] for i in page.items}
        sel = {c['id']: c['selection'] for c in rec['candidates']}
        self.assertEqual(sel[ids[1]], 'draft')
        self.assertEqual(sel[ids[2]], 'skip')
        self.assertIsNone(sel[ids[3]])
        # 同一天重跑：勾选结果按候选 id 带过去，旧页作废
        self.fx.run()
        rec2 = self.fx.load()
        sel2 = {c['id']: c['selection'] for c in rec2['candidates']}
        self.assertEqual(sel2[ids[1]], 'draft')
        self.assertIsNone(rec2['pending']['page_id'])
        self.assertEqual(rec2['pending']['history'][0]['page_id'], page.page_id)
        with self.assertRaises(pending.ReplyError):
            pending.apply_reply(self.fx.data, 'demo-guard', 'PE1 review-2026-10-15 %s 3A' % page.page_id,
                                now=lambda: NOW)
        page2 = review_pending.generate(self.fx.data, 'demo-guard', now=lambda: NOW)
        self.assertEqual(len(page2.items), 2)

    def test_bad_reply_changes_nothing(self):
        self.fx.run()
        page = review_pending.generate(self.fx.data, 'demo-guard', now=lambda: NOW)
        path = self.fx.repo / 'plugin-evals' / 'demo-guard' / 'reviews' / '2026-10-15.json'
        before = path.read_text(encoding='utf-8')
        for code in ('PE1 review-2026-10-15 %s 9A' % page.page_id,       # 序号不在页上
                     'PE1 review-2026-10-15 %s 1C' % page.page_id,       # 选项不存在
                     'PE1 review-2026-10-15 deadbeef 1A',                # 不是最新一页
                     'PE1 review-2026-10-16 %s 1A' % page.page_id):      # 没有这天的复盘
            with self.assertRaises(pending.ReplyError):
                pending.apply_reply(self.fx.data, 'demo-guard', code, now=lambda: NOW)
        self.assertEqual(path.read_text(encoding='utf-8'), before)

    def test_review_page_skips_compare_kind_collectors(self):
        """待审项类型按 kinds 过滤：复盘页不调用只适用于 compare 的类型的 collect。"""
        self.fx.run()
        calls = []
        spy = pending.ItemType(key='spy-compare', label='探针', options=(('A', '甲'),),
                               collect=lambda sub: calls.append(sub.rec.get('kind')) or [], apply=lambda *a: None)
        reg = pending.TypeRegistry()
        for t in pending._REGISTRY.all() + [spy]:
            reg.register(t)
        page = review_pending.generate(self.fx.data, 'demo-guard', now=lambda: NOW, types=reg)
        self.assertEqual(calls, [])
        self.assertTrue(page.items)
        self.assertTrue(all(i['type'].startswith('review-') for i in page.items))
        self.assertEqual({t.key for t in reg.for_kind('review')}, {'review-candidate', 'review-compare-hint'})
        self.assertNotIn('report-review', {t.key for t in reg.for_kind('review')})
        self.assertIn('clause-list', {t.key for t in reg.for_kind('clauses')})

    def test_quiet_plugin_has_nothing_pending(self):
        self.fx.run()
        with self.assertRaises(pending.NothingPending):
            review_pending.generate(self.fx.data, 'quiet-plugin', now=lambda: NOW)

    def test_more_than_ten_candidates_are_sampled(self):
        recs = [deny('many-%d' % i, 30, check='rule-%02d' % i, session=S9) for i in range(12)]
        dump(self.fx.projects / (S9 + '.jsonl'), recs)
        self.fx.run()
        page = review_pending.generate(self.fx.data, 'demo-guard', now=lambda: NOW)
        self.assertEqual(len(page.items), pending.PAGE_LIMIT)
        rec = self.fx.load()
        self.assertTrue(rec['pending']['sampled'])
        self.assertEqual(len(rec['pending']['sampled_out']), 16 - pending.PAGE_LIMIT)


class ReviewCliTest(unittest.TestCase):
    def test_review_subcommand_writes_files(self):
        from unittest import mock
        from plugin_eval_lib import cli
        fx = Fixture(self)
        standard_sessions(fx)
        with mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(fx.cfg)}), \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(['--data-dir', str(fx.data), 'review', '--days', '100000', '--no-hook-labels'])
        self.assertEqual(code, 0)
        today = datetime.now().astimezone().strftime('%Y-%m-%d')        # 复盘日期是本机本地日期
        for name in ('demo-guard', 'quiet-plugin'):
            self.assertTrue((fx.repo / 'plugin-evals' / name / 'reviews' / ('%s.json' % today)).is_file())
        self.assertIn('pending demo-guard --review %s' % today, out.getvalue())
        self.assertNotIn(SECRET, out.getvalue())

    def test_days_must_be_positive(self):
        from plugin_eval_lib import cli
        fx = Fixture(self)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--data-dir', str(fx.data), 'review', '--days', '0']), 2)


class RuleKeyTest(unittest.TestCase):
    def setUp(self):
        index = review_scan.PluginIndex({'demo-guard'}, {}, [], {})
        self.scanner = review_scan.Scanner(index, '2026-01-01T00:00:00')

    def test_script_comes_from_command_segment_not_diagnostic(self):
        text = ('PreToolUse:Agent hook error: [node /home/u/.claude/plugins/cache/mkt/demo-guard/1.0.0/hooks/guard.js]: '
                '细则见 /home/u/.claude/plugins/cache/mkt/demo-guard/1.0.0/references/x.md，%s check=naming' % SECRET)
        plugin, version, script = self.scanner._plugin_from_command(text)
        self.assertEqual((plugin, version, script), ('demo-guard', '1.0.0', 'hooks/guard.js'))
        self.assertEqual(self.scanner._rule(script, text), 'hooks/guard.js#check=naming')

    def test_old_format_without_command_keeps_plugin_but_not_diagnostic_path(self):
        # 旧版 Claude Code：方括号里是诊断标签，没有命令；诊断里的文档路径后紧跟全角逗号与正文
        text = ('PreToolUse:Agent hook error: [L1-BLOCKER] check=naming 细则见 '
                '/home/u/.claude/plugins/cache/mkt/demo-guard/1.0.0/references/x.md，%s' % SECRET)
        plugin, version, script = self.scanner._plugin_from_command(text)
        self.assertEqual((plugin, version, script), ('demo-guard', '1.0.0', None))
        self.assertEqual(self.scanner._rule(script, text), '?#check=naming')

    def test_full_width_punctuation_after_command_path_is_not_captured(self):
        text = 'PreToolUse:Bash hook error: [node /home/u/.claude/plugins/cache/mkt/demo-guard/1.0.0/hooks/g.js，%s]' % SECRET
        self.assertEqual(self.scanner._plugin_from_command(text)[2], 'hooks/g.js')


class RenamesTest(unittest.TestCase):
    def test_chain_and_removed(self):
        self.assertEqual(review_scan.resolve_renames({'a': 'b', 'b': 'c', 'x': None, 'p': 'q', 'q': 'p'}),
                         {'a': 'c', 'b': 'c'})


if __name__ == '__main__':
    unittest.main()
