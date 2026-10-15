"""接缝：前置检查（硬项中止、软项照跑并标注）、check 子命令、compare 开跑前自动执行。

claude 的三次调用（eval --help、auth status、plugin validate）用假的 run 函数顶替；
hook 冒烟真执行 shell 命令（用 sys.executable 写的小脚本，不依赖本机装了什么解释器）。
"""
import io
import json
import os
import stat
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import _support
from _support import make_plugin, tmpdir, write
from plugin_eval_lib import cli, compare, envplugins, preflight, registry

PY = '"%s"' % sys.executable

EVAL_HELP_FULL = '\n'.join('  %s  说明' % f for f in (
    '--ablation <mode>', '--keep-temp', '--no-publish', '--trust-plugin', '--scaffold', '--runs <n>',
    '-j, --concurrency <n>', '--output-dir <dir>', '--report <path>', '--model <model>'))


class FakeClaude:
    """按 argv 回放 claude 子命令的输出。返回 (退出码, stdout, stderr)；退出码 None 表示没起来。"""

    def __init__(self, help_text=EVAL_HELP_FULL, logged_in=True, auth_raw=None, validate=None, version='2.1.300'):
        self.help_text = help_text
        self.logged_in = logged_in
        self.auth_raw = auth_raw
        self.validate = validate or {}    # {插件目录名: (退出码, stdout)}
        self.version = version
        self.calls = []

    def __call__(self, argv, env=None, timeout=None, cwd=None):
        self.calls.append(list(argv))
        args = list(argv[1:])
        if args[:3] == ['plugin', 'eval', '--help']:
            return 0, self.help_text, ''
        if args[:3] == ['auth', 'status', '--json']:
            if self.auth_raw is not None:
                return 0, self.auth_raw, ''
            return 0, json.dumps({'loggedIn': self.logged_in, 'email': 'someone@example.invalid'}), ''
        if args[:2] == ['plugin', 'validate']:
            name = Path(args[-1]).name
            code, out = self.validate.get(name, (0, json.dumps({'success': True, 'manifest': {'errors': []}})))
            return code, out, ''
        if args == ['--version']:
            return 0, '%s (Claude Code)\n' % self.version, ''
        return 1, '', 'unexpected %r' % args


def set_hooks(plugin_dir, commands, event='SessionStart', where='hooks.json'):
    hooks = {event: [{'matcher': '*', 'hooks': [{'type': 'command', 'command': c} for c in commands]}]}
    if where == 'hooks.json':
        write(Path(plugin_dir) / 'hooks' / 'hooks.json', json.dumps({'hooks': hooks}))
    else:
        manifest = Path(plugin_dir) / '.claude-plugin' / 'plugin.json'
        data = json.loads(manifest.read_text(encoding='utf-8'))
        data['hooks'] = hooks
        manifest.write_text(json.dumps(data), encoding='utf-8')


def item(report, item_id):
    return next(i for i in report.items if i.id == item_id)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.data = self.tmp / 'data'
        self.repo = self.tmp / 'repo'
        self.plugin = make_plugin(self.repo / 'plugins' / 'demo-plugin')
        registry.register(self.data, 'demo-plugin', self.repo)
        self.env = {'PATH': os.environ.get('PATH', '')}

    def check(self, fake=None, **kw):
        kw.setdefault('claude', '/fake/claude')
        return preflight.check_compare(data_dir=self.data, name='demo-plugin', env=self.env,
                                       run=fake or FakeClaude(), tmp_parent=self.tmp, **kw)


class HookCollectTest(Base):
    def test_reads_hooks_json_and_inline_manifest_and_dedupes(self):
        set_hooks(self.plugin, ['node ${CLAUDE_PLUGIN_ROOT}/a.js', 'node ${CLAUDE_PLUGIN_ROOT}/b.js'])
        set_hooks(self.plugin, ['node ${CLAUDE_PLUGIN_ROOT}/a.js', 'node ${CLAUDE_PLUGIN_ROOT}/c.js'],
                  event='UserPromptSubmit', where='manifest')
        specs, errors = preflight.collect_hook_commands(self.plugin)
        self.assertEqual(errors, [])
        # 与注入核验同一套枚举（injection.load_hook_specs）：plugin.json 声明在前，hooks/hooks.json 在后
        self.assertEqual([s.command for s in specs],
                         ['node ${CLAUDE_PLUGIN_ROOT}/a.js', 'node ${CLAUDE_PLUGIN_ROOT}/c.js',
                          'node ${CLAUDE_PLUGIN_ROOT}/b.js'])
        self.assertEqual(specs[0].event, 'UserPromptSubmit')

    def test_manifest_hooks_as_path_and_non_command_types_skipped(self):
        write(self.plugin / 'extra' / 'more.json', json.dumps({'hooks': {'Stop': [{'hooks': [
            {'type': 'command', 'command': 'echo x'}, {'type': 'prompt', 'prompt': '想一想'}]}]}}))
        manifest = self.plugin / '.claude-plugin' / 'plugin.json'
        data = json.loads(manifest.read_text(encoding='utf-8'))
        data['hooks'] = './extra/more.json'
        manifest.write_text(json.dumps(data), encoding='utf-8')
        specs, errors = preflight.collect_hook_commands(self.plugin)
        self.assertEqual([(s.event, s.command) for s in specs], [('Stop', 'echo x')])

    def test_missing_type_counts_as_command(self):
        """Claude Code 对缺省 type 的 hook 按 command 执行；冒烟与注入核验都要收进来（审查 04 第四节 8）。"""
        write(self.plugin / 'hooks' / 'hooks.json', json.dumps({'hooks': {'Stop': [{'hooks': [
            {'command': 'echo untyped'}]}]}}))
        specs, errors = preflight.collect_hook_commands(self.plugin)
        self.assertEqual(errors, [])
        self.assertEqual([s.command for s in specs], ['echo untyped'])

    def test_broken_hooks_json_reported(self):
        write(self.plugin / 'hooks' / 'hooks.json', '{oops')
        specs, errors = preflight.collect_hook_commands(self.plugin)
        self.assertEqual(specs, [])
        self.assertTrue(errors and 'hooks.json' in errors[0])


class HookSmokeTest(Base):
    def test_exit_126_aborts_and_names_the_command(self):
        cmd = 'exit 126'
        set_hooks(self.plugin, [PY + ' -c "print(1)"', cmd])
        rep = self.check()
        self.assertFalse(rep.passed)
        hooks = item(rep, 'hooks_reachable')
        self.assertEqual(hooks.status, preflight.FAIL)
        self.assertIn(cmd, hooks.detail)
        self.assertIn('126', hooks.detail)
        self.assertIn('exit 126', rep.render())

    def test_shim_like_interpreter_failing_under_empty_home(self):
        # 仿版本管理器 shim：真实 HOME 下有版本配置就能跑，换成空 HOME 就 exit 126。检查逻辑不认 shim 名字，只看退出码。
        shim_dir = self.tmp / 'shims'
        shim = write(shim_dir / 'fakenode.py',
                     'import os, sys\n'
                     'sys.exit(0 if os.path.exists(os.path.join(os.path.expanduser("~"), ".tool-versions")) else 126)\n')
        real_home = self.tmp / 'realhome'
        write(real_home / '.tool-versions', 'nodejs 22\n')
        cmd = '%s "%s" ${CLAUDE_PLUGIN_ROOT}/hooks/inject.js' % (PY, shim)
        set_hooks(self.plugin, [cmd], event='UserPromptSubmit')
        self.env = dict(self.env, HOME=str(real_home), USERPROFILE=str(real_home))
        rep = self.check()
        self.assertEqual(item(rep, 'hooks_reachable').status, preflight.FAIL)
        self.assertIn(cmd, item(rep, 'hooks_reachable').detail)

    def test_exit_127_command_not_found_aborts(self):
        set_hooks(self.plugin, ['devkit-plugin-eval-no-such-interpreter ${CLAUDE_PLUGIN_ROOT}/x.js'])
        rep = self.check()
        self.assertEqual(item(rep, 'hooks_reachable').status, preflight.FAIL)
        self.assertIn('127', item(rep, 'hooks_reachable').detail)

    def test_other_nonzero_is_only_a_note(self):
        set_hooks(self.plugin, [PY + ' -c "import sys; sys.exit(2)"'])
        rep = self.check()
        self.assertTrue(rep.passed)
        self.assertEqual(item(rep, 'hooks_reachable').status, preflight.OK)
        self.assertEqual([r['exit_code'] for r in rep.hook_runs], [2])
        self.assertTrue(rep.hook_runs[0]['note'])

    def test_runs_under_empty_temp_home_with_plugin_root_and_same_path(self):
        out = self.tmp / 'seen.json'
        script = write(self.plugin / 'hooks' / 'probe.py',
                       'import json, os, sys\n'
                       'json.dump({"home": os.path.expanduser("~"), "root": sys.argv[1], "path": os.environ["PATH"],'
                       ' "stdin": json.load(sys.stdin)}, open(sys.argv[2], "w"))\n')
        set_hooks(self.plugin, ['%s "${CLAUDE_PLUGIN_ROOT}/hooks/probe.py" "${CLAUDE_PLUGIN_ROOT}" "%s"' % (PY, out)],
                  event='PreToolUse')
        rep = self.check()
        self.assertTrue(rep.passed, rep.render())
        seen = json.loads(out.read_text(encoding='utf-8'))
        self.assertNotEqual(Path(seen['home']).resolve(), Path.home().resolve())
        self.assertFalse(Path(seen['home']).exists())   # 临时 HOME 用完即删
        # 在插件副本里跑：${CLAUDE_PLUGIN_ROOT} 指向副本，不指向用户工作区
        self.assertNotEqual(Path(seen['root']).resolve(), self.plugin.resolve())
        self.assertEqual(seen['path'], self.env['PATH'])
        self.assertEqual(seen['stdin']['hook_event_name'], 'PreToolUse')
        self.assertIn('tool_name', seen['stdin'])   # PreToolUse 样例输入带工具名，hook 不会因缺字段崩

    def test_python_hook_leaves_no_pycache_in_plugin_dir(self):
        write(self.plugin / 'hooks' / 'helper.py', 'X = 1\n')
        write(self.plugin / 'hooks' / 'main.py', 'import sys; sys.path.insert(0, sys.argv[1]); import helper\n')
        set_hooks(self.plugin, ['%s "${CLAUDE_PLUGIN_ROOT}/hooks/main.py" "${CLAUDE_PLUGIN_ROOT}/hooks"' % PY])
        rep = self.check()
        self.assertTrue(rep.passed, rep.render())
        self.assertEqual([r['exit_code'] for r in rep.hook_runs], [0])
        self.assertEqual(list(self.plugin.rglob('__pycache__')), [])

    def test_failure_detail_shows_plugin_root_placeholder_not_temp_copy(self):
        set_hooks(self.plugin, ['%s "${CLAUDE_PLUGIN_ROOT}/hooks/missing.py"' % PY])
        rep = self.check()
        runs = rep.hook_runs
        self.assertEqual(len(runs), 1)
        self.assertNotEqual(runs[0]['exit_code'], 0)
        text = json.dumps(runs, ensure_ascii=False) + rep.render()
        self.assertIn('${CLAUDE_PLUGIN_ROOT}', text)
        self.assertNotIn(str(self.tmp), text)
        self.assertNotIn('/private${', text)   # macOS 上 /var 实为 /private/var：替换前要先 resolve（集成审查展示问题）

    def test_symlink_to_outside_plugin_dir_still_reachable(self):
        """集成审查 N2：hook 脚本是指向插件目录外的相对符号链接时，副本跟随链接拷内容，冒烟不得 127。"""
        target = write(self.tmp / 'shared' / 'run-hook', '#!/bin/sh\nexit 0\n')
        os.chmod(target, 0o755)
        link = self.plugin / 'hooks' / 'run-hook'
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(target, link.parent), link)
        set_hooks(self.plugin, ['"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook"'])
        rep = self.check()
        self.assertTrue(rep.passed, rep.render())
        self.assertEqual([r['exit_code'] for r in rep.hook_runs], [0])

    def test_no_hooks_is_ok(self):
        rep = self.check()
        self.assertEqual(item(rep, 'hooks_reachable').status, preflight.OK)

    def test_other_plugins_smoked_too(self):
        prev = make_plugin(self.tmp / 'snapshot' / 'demo-plugin')
        set_hooks(prev, ['exit 127'])
        rep = self.check(others=[('上一版', prev)])
        self.assertIn('上一版', item(rep, 'hooks_reachable').detail)


class ClaudeItemsTest(Base):
    def test_all_pass(self):
        rep = self.check()
        self.assertTrue(rep.passed, rep.render())
        for i in ('registered', 'claude_executable', 'eval_flags', 'logged_in', 'plugin_valid', 'hooks_reachable'):
            self.assertEqual(item(rep, i).status, preflight.OK, i)
        self.assertEqual(item(rep, 'env_plugins_contained').status, preflight.SKIP)

    def test_claude_resolved_from_full_path_not_child_env(self):
        """票 04 审查①：eval 子进程环境的 PATH 去掉了 asdf shims，claude 自己可能就在 shim 后面；找 claude 用本进程完整 PATH。"""
        self.env = {'PATH': ''}
        with mock.patch.object(preflight.evalrun, 'resolve_claude', return_value='/fake/claude') as rc:
            rep = self.check(claude=None)
        self.assertEqual(item(rep, 'claude_executable').status, preflight.OK, rep.render())
        self.assertEqual(rc.call_args.kwargs.get('path'), None)

    def test_claude_not_found_aborts_and_skips_dependents(self):
        with mock.patch.object(preflight.evalrun, 'resolve_claude', side_effect=preflight.evalrun.ClaudeNotFound('无')):
            rep = self.check(claude=None)
        self.assertFalse(rep.passed)
        self.assertEqual(item(rep, 'claude_executable').status, preflight.FAIL)
        for i in ('eval_flags', 'logged_in', 'plugin_valid'):
            self.assertEqual(item(rep, i).status, preflight.SKIP, i)

    def test_missing_eval_flag_aborts(self):
        rep = self.check(FakeClaude(help_text=EVAL_HELP_FULL.replace('--keep-temp', '--keep-tmp')))
        self.assertEqual(item(rep, 'eval_flags').status, preflight.FAIL)
        self.assertIn('--keep-temp', item(rep, 'eval_flags').detail)

    def test_model_flag_required_only_when_model_given(self):
        no_model = EVAL_HELP_FULL.replace('--model <model>', '')
        self.assertTrue(self.check(FakeClaude(help_text=no_model)).passed)
        rep = self.check(FakeClaude(help_text=no_model), model='claude-opus-5-5')
        self.assertIn('--model', item(rep, 'eval_flags').detail)

    def test_not_logged_in_aborts(self):
        rep = self.check(FakeClaude(logged_in=False))
        self.assertEqual(item(rep, 'logged_in').status, preflight.FAIL)
        self.assertNotIn('example.invalid', json.dumps(rep.to_dict(), ensure_ascii=False))   # 不记账号信息

    def test_auth_status_unparseable_aborts(self):
        rep = self.check(FakeClaude(auth_raw='not json'))
        self.assertEqual(item(rep, 'logged_in').status, preflight.FAIL)

    def test_plugin_validate_failure_aborts(self):
        bad = json.dumps({'success': False, 'manifest': {'errors': [{'path': 'name', 'message': 'expected string'}]}})
        rep = self.check(FakeClaude(validate={'demo-plugin': (1, bad)}))
        self.assertEqual(item(rep, 'plugin_valid').status, preflight.FAIL)
        self.assertIn('expected string', item(rep, 'plugin_valid').detail)

    def test_unregistered_aborts(self):
        rep = preflight.check_compare(data_dir=self.data, name='ghost', env=self.env, claude='/fake/claude',
                                      run=FakeClaude(), tmp_parent=self.tmp)
        self.assertEqual(item(rep, 'registered').status, preflight.FAIL)
        self.assertIn('register', item(rep, 'registered').detail)
        self.assertEqual(item(rep, 'plugin_valid').status, preflight.SKIP)
        self.assertEqual(item(rep, 'hooks_reachable').status, preflight.SKIP)

    def test_env_plugin_outside_containment_root_aborts(self):
        root = self.tmp / 'arm'
        inside = make_plugin(root / 'env' / 'other')
        outside = make_plugin(self.tmp / 'elsewhere' / 'other')
        ok = self.check(env_plugins=[inside], containment_root=root)
        self.assertEqual(item(ok, 'env_plugins_contained').status, preflight.OK)
        bad = self.check(env_plugins=[inside, outside], containment_root=root)
        self.assertEqual(item(bad, 'env_plugins_contained').status, preflight.FAIL)
        self.assertIn('elsewhere', item(bad, 'env_plugins_contained').detail)

    def test_env_dir_name_taken_by_tested_plugin_aborts(self):
        """票 05 (d)：被测插件顶层已有 _plugin_eval_env/，环境插件拷不进臂组装目录，开跑前就拦下。"""
        env = make_plugin(self.tmp / 'envsrc' / 'env-a')
        self.assertEqual(item(self.check(env_plugins=[env]), 'env_plugins_contained').status, preflight.OK)
        (self.plugin / envplugins.ENV_DIR).mkdir()
        rep = self.check(env_plugins=[env])
        self.assertEqual(item(rep, 'env_plugins_contained').status, preflight.FAIL)
        self.assertIn(envplugins.ENV_DIR, item(rep, 'env_plugins_contained').detail)
        self.assertFalse(rep.passed)


class SoftItemsTest(unittest.TestCase):
    def test_dirty(self):
        self.assertEqual(preflight.check_dirty('abc', False).status, preflight.OK)
        warn = preflight.check_dirty('abc', True)
        self.assertEqual(warn.status, preflight.WARN)
        self.assertIn('不计入发版闸门', warn.detail)
        self.assertEqual(preflight.check_dirty(None, None).status, preflight.WARN)   # 不在 git 仓：取不到提交

    def test_version_model_vs_previous(self):
        prev = {'run_id': 'r0', 'claude_code_version': '2.1.299', 'main_model': 'claude-opus-5-5'}
        self.assertEqual(preflight.check_version_model(None, '2.1.300', 'm').status, preflight.OK)
        self.assertEqual(preflight.check_version_model(dict(prev, claude_code_version='2.1.300'),
                                                       '2.1.300', 'claude-opus-5-5').status, preflight.OK)
        w = preflight.check_version_model(prev, '2.1.300', 'claude-opus-5-5')
        self.assertEqual(w.status, preflight.WARN)
        self.assertIn('2.1.299', w.detail)
        w = preflight.check_version_model(dict(prev, claude_code_version='2.1.300'), '2.1.300', 'claude-sonnet-5-5')
        self.assertIn('claude-sonnet-5-5', w.detail)

    def test_version_model_unknown_values_are_skipped_not_passed(self):
        """票 04 审查：任一方取不到值时判 skip 并写明，不静默判通过。"""
        prev = {'run_id': 'r0', 'claude_code_version': '2.1.299', 'main_model': 'claude-opus-5-5'}
        s = preflight.check_version_model(prev, None, 'claude-opus-5-5')
        self.assertEqual(s.status, preflight.SKIP)
        self.assertIn('这次取不到', s.detail)
        s = preflight.check_version_model({'run_id': 'r0', 'claude_code_version': '2.1.299'}, '2.1.299', 'm')
        self.assertEqual(s.status, preflight.SKIP)
        self.assertIn('上次没记', s.detail)
        w = preflight.check_version_model(prev, '2.1.300', None)
        self.assertEqual(w.status, preflight.WARN)
        self.assertIn('未比较', w.detail)
        # 只比版本（check 子命令）：模型不参与
        ok = preflight.check_version_model(prev, '2.1.299', None, compare_model=False)
        self.assertEqual(ok.status, preflight.OK)

    def test_previous_compare_prefers_latest_complete_run(self):
        """票 04 审查③：最近一次是不完整运行时，「上次对照」取最近一次完整的；一次完整的都没有才取最新。"""
        tmp = tmpdir(self)
        for rid, complete in (('20261001T000000Z-1.0.0-compare', True), ('20261002T000000Z-1.0.0-compare', False)):
            write(tmp / rid / 'run.json', json.dumps({'run_id': rid, 'kind': 'compare', 'complete': complete}))
        self.assertEqual(preflight.previous_compare(tmp)['run_id'], '20261001T000000Z-1.0.0-compare')
        self.assertEqual(preflight.previous_compare(tmp, exclude='20261001T000000Z-1.0.0-compare')['run_id'],
                         '20261002T000000Z-1.0.0-compare')

    def test_previous_compare_picks_latest_other_compare_run(self):
        tmp = tmpdir(self)
        for rid, kind in (('20261001T000000Z-1.0.0-compare', 'compare'), ('20261002T000000Z-1.0.0-gate', 'gate'),
                          ('20261003T000000Z-1.0.0-compare', 'compare')):
            write(tmp / rid / 'run.json', json.dumps({'run_id': rid, 'kind': kind, 'claude_code_version': rid[:8]}))
        write(tmp / '20261004T000000Z-1.0.0-compare' / 'note.txt', '没有 run.json 的残留目录')
        self.assertEqual(preflight.previous_compare(tmp)['run_id'], '20261003T000000Z-1.0.0-compare')
        self.assertEqual(preflight.previous_compare(tmp, exclude='20261003T000000Z-1.0.0-compare')['run_id'],
                         '20261001T000000Z-1.0.0-compare')
        self.assertIsNone(preflight.previous_compare(tmp / 'nope'))


class ReviewChecksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.cfg = self.tmp / 'cfg'
        write(self.cfg / 'projects' / '-proj' / 'sid.jsonl', '{}\n')
        self.data = self.tmp / 'data'
        self.repo = self.tmp / 'repo'
        make_plugin(self.repo / 'plugins' / 'demo-plugin')
        registry.register(self.data, 'demo-plugin', self.repo)
        self.env = {'CLAUDE_CONFIG_DIR': str(self.cfg), 'PATH': ''}
        self.now = datetime(2026, 10, 15, tzinfo=timezone.utc)

    def check(self, **kw):
        kw.setdefault('now', self.now)
        return preflight.check_review(data_dir=self.data, env=self.env, run=FakeClaude(), claude='/fake/claude', **kw)

    def test_all_pass_and_respects_config_dir(self):
        rep = self.check()
        self.assertTrue(rep.passed, rep.render())
        self.assertEqual(item(rep, 'judge_logged_in').status, preflight.SKIP)

    def test_config_dir_default_is_home_dot_claude(self):
        self.assertEqual(preflight.config_dir({'HOME': '/h'}, home=lambda: Path('/h')), Path('/h') / '.claude')
        self.assertEqual(preflight.config_dir({'CLAUDE_CONFIG_DIR': '/c'}), Path('/c'))

    def test_session_dir_missing_or_empty_aborts(self):
        self.env['CLAUDE_CONFIG_DIR'] = str(self.tmp / 'nocfg')
        self.assertEqual(item(self.check(), 'sessions_readable').status, preflight.FAIL)
        (self.tmp / 'nocfg' / 'projects' / 'x').mkdir(parents=True)
        self.assertEqual(item(self.check(), 'sessions_readable').status, preflight.FAIL)

    def test_registry_empty_aborts(self):
        (self.data / 'registry.json').unlink()
        self.assertEqual(item(self.check(), 'registry_writable').status, preflight.FAIL)

    def test_repo_missing_aborts(self):
        import shutil
        shutil.rmtree(self.repo)
        rep = self.check()
        self.assertEqual(item(rep, 'registry_writable').status, preflight.FAIL)
        self.assertIn('demo-plugin', item(rep, 'registry_writable').detail)

    @unittest.skipIf(os.name == 'nt' or (hasattr(os, 'geteuid') and os.geteuid() == 0), 'chmod 只读对 Windows / root 无效')
    def test_repo_not_writable_aborts(self):
        os.chmod(self.repo, stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(os.chmod, self.repo, stat.S_IRWXU)
        self.assertEqual(item(self.check(), 'registry_writable').status, preflight.FAIL)

    def test_gap_longer_than_cleanup_period_is_soft(self):
        write(self.cfg / 'settings.json', json.dumps({'cleanupPeriodDays': 10}))
        reviews = self.repo / 'plugin-evals' / 'demo-plugin' / 'reviews'
        write(reviews / '2026-10-01.json', '{}')
        rep = self.check()
        self.assertTrue(rep.passed)
        w = item(rep, 'review_gap')
        self.assertEqual(w.status, preflight.WARN)
        self.assertIn('2026-10-01', w.detail)
        write(reviews / '2026-10-10.json', '{}')
        self.assertEqual(item(self.check(), 'review_gap').status, preflight.OK)

    def test_cleanup_default_30_days(self):
        write(self.repo / 'plugin-evals' / 'demo-plugin' / 'reviews' / '2026-09-20.json', '{}')
        self.assertEqual(item(self.check(), 'review_gap').status, preflight.OK)   # 25 天 < 30

    def test_judge_login_checked_only_when_needed(self):
        rep = preflight.check_review(data_dir=self.data, env=self.env, run=FakeClaude(logged_in=False),
                                     claude='/fake/claude', need_judge=True, now=self.now)
        self.assertEqual(item(rep, 'judge_logged_in').status, preflight.FAIL)


class CheckCliTest(Base):
    def run_cli(self, *args, fake=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(preflight, 'default_run', fake or FakeClaude()), \
                mock.patch.object(preflight.evalrun, 'resolve_claude', return_value='/fake/claude'), \
                redirect_stdout(out), redirect_stderr(err):
            code = cli.main(['--data-dir', str(self.data), 'check', *args])
        return code, out.getvalue() + err.getvalue()

    def test_check_pass(self):
        code, text = self.run_cli('demo-plugin')
        self.assertEqual(code, 0, text)
        self.assertIn('通过', text)

    def test_check_hard_failure_exits_2_and_names_command(self):
        set_hooks(self.plugin, ['exit 126'])
        code, text = self.run_cli('demo-plugin')
        self.assertEqual(code, 2)
        self.assertIn('exit 126', text)

    def test_check_reports_dirty_and_version_softly(self):
        write(self.repo / 'plugin-evals' / 'demo-plugin' / 'runs' / '20261001T000000Z-1.2.3-compare' / 'run.json',
              json.dumps({'run_id': '20261001T000000Z-1.2.3-compare', 'kind': 'compare',
                          'claude_code_version': '2.1.200', 'main_model': 'm'}))
        code, text = self.run_cli('demo-plugin')
        self.assertEqual(code, 0)
        self.assertIn('2.1.200', text)

    def test_check_covers_env_plugins_like_compare(self):
        """票 04 审查：check --env-plugin 与 compare 用同一份臂计划，环境插件的 hook 也冒烟。"""
        env = make_plugin(self.tmp / 'envsrc' / 'env-a', name='env-a')
        set_hooks(env, ['exit 127'])
        code, text = self.run_cli('demo-plugin')
        self.assertEqual(code, 0, text)
        code, text = self.run_cli('demo-plugin', '--env-plugin', str(env))
        self.assertEqual(code, 2, text)
        self.assertIn('env-a', text)
        self.assertIn('127', text)

    def test_check_base_unresolvable_aborts_like_compare(self):
        code, text = self.run_cli('demo-plugin', '--base', '0.0.1')
        self.assertEqual(code, 2)
        self.assertIn('--base 0.0.1', text)

    def test_check_unregistered_reports_registered_item(self):
        code, text = self.run_cli('nobody-plugin')
        self.assertEqual(code, 2)
        self.assertIn('nobody-plugin', text)

    def test_check_needs_name_or_review(self):
        code, _ = self.run_cli()
        self.assertEqual(code, 2)


class CompareWiringTest(Base):
    """compare 开跑前自动执行：硬项失败不跑任何臂；软项照跑，run.json 与 report.md 首段有标注。"""

    def setUp(self):
        super().setUp()
        from test_compare import FakeEval
        self.sandboxes = self.tmp / 'sandboxes'
        self.sandboxes.mkdir()
        self.assembly = self.tmp / 'assembly'
        self.assembly.mkdir()
        self.fake_eval = FakeEval(self.sandboxes, {'none': False, 'current': True})

    def run_compare(self, fake_claude=None, **kw):
        fake_claude = fake_claude or FakeClaude()
        pre = lambda **a: preflight.check_compare(run=fake_claude, **a)
        return compare.run_compare(self.data, 'demo-plugin', runs=1, concurrency=1, claude='/fake/claude',
                                   runner=self.fake_eval, env=self.env, tmp_parent=self.assembly,
                                   sandbox_roots=[self.sandboxes], log=lambda *a: None, preflight_check=pre, **kw)

    def runs_dir(self):
        return self.repo / 'plugin-evals' / 'demo-plugin' / 'runs'

    def test_hard_failure_aborts_before_any_arm(self):
        set_hooks(self.plugin, ['exit 126'])
        with self.assertRaises(preflight.PreflightFailed) as cm:
            self.run_compare()
        self.assertIn('exit 126', str(cm.exception))
        self.assertEqual(self.fake_eval.calls, [])
        self.assertFalse(self.runs_dir().exists())
        self.assertFalse((self.repo / '.gitignore').exists())   # 中止时不留任何写入

    def test_each_hard_item_aborts(self):
        cases = {
            'eval_flags': FakeClaude(help_text=''),
            'logged_in': FakeClaude(logged_in=False),
            'plugin_valid': FakeClaude(validate={'demo-plugin': (1, '{}')}),
        }
        for item_id, fake in cases.items():
            with self.assertRaises(preflight.PreflightFailed, msg=item_id) as cm:
                self.run_compare(fake)
            self.assertIn(item_id, [i.id for i in cm.exception.report.hard_failures])
        self.assertEqual(self.fake_eval.calls, [])

    def test_cli_compare_prints_preflight_failure(self):
        set_hooks(self.plugin, ['exit 126'])
        err = io.StringIO()
        with mock.patch.object(preflight, 'default_run', FakeClaude()), \
                mock.patch.object(preflight.evalrun, 'resolve_claude', return_value='/fake/claude'), \
                redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = cli.main(['--data-dir', str(self.data), 'compare', 'demo-plugin'])
        self.assertEqual(code, 2)
        self.assertIn('exit 126', err.getvalue())

    def _git(self, *args):
        import subprocess
        subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid',
                        '-c', 'commit.gpgsign=false', *args], check=True, capture_output=True)

    @unittest.skipUnless(__import__('shutil').which('git'), 'git 不可用')
    def test_dirty_runs_and_is_marked(self):
        self._git('init', '-q')
        self._git('add', '-A')
        self._git('commit', '-q', '-m', 'init')
        (self.plugin / 'hooks' / 'inject.js').write_text('changed', encoding='utf-8')
        res = self.run_compare()
        self.assertEqual(len(self.fake_eval.calls), 2)
        rec = json.loads((res.run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertTrue(rec['arms']['current']['dirty'])
        self.assertTrue(rec['preflight']['passed'])
        self.assertTrue(rec['preflight']['dirty'])
        self.assertTrue(any('未提交改动' in w for w in rec['preflight']['warnings']))
        head = (res.run_dir / 'report.md').read_text(encoding='utf-8').split('\n## ')[0]
        self.assertIn('未提交改动', head)
        self.assertIn('不计入发版闸门', head)

    @unittest.skipUnless(__import__('shutil').which('git'), 'git 不可用')
    def test_clean_tree_has_no_soft_warning(self):
        self._git('init', '-q')
        self._git('add', '-A')
        self._git('commit', '-q', '-m', 'init')
        res = self.run_compare()
        rec = json.loads((res.run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertFalse(rec['preflight']['dirty'])
        self.assertEqual(rec['preflight']['warnings'], [], rec['preflight'])
        self.assertNotIn('前置检查软项', (res.run_dir / 'report.md').read_text(encoding='utf-8'))

    def test_version_change_vs_previous_compare_marked(self):
        write(self.runs_dir() / '20261001T000000Z-1.2.3-compare' / 'run.json',
              json.dumps({'run_id': '20261001T000000Z-1.2.3-compare', 'kind': 'compare',
                          'claude_code_version': '2.1.200', 'main_model': 'claude-opus-5-5'}))
        res = self.run_compare()
        rec = json.loads((res.run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertTrue(any('2.1.200' in w for w in rec['preflight']['warnings']))
        head = (res.run_dir / 'report.md').read_text(encoding='utf-8').split('\n## ')[0]
        self.assertIn('不可直接比', head)

    def test_hook_notes_and_items_land_in_run_json(self):
        set_hooks(self.plugin, [PY + ' -c "import sys; sys.exit(3)"'])
        res = self.run_compare()
        rec = json.loads((res.run_dir / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual(rec['preflight']['hook_smoke'][0]['exit_code'], 3)
        ids = [i['id'] for i in rec['preflight']['items']]
        self.assertIn('hooks_reachable', ids)
        self.assertIn('dirty', ids)
        self.assertIn('version_model', ids)


if __name__ == '__main__':
    unittest.main()
