"""前置检查（spec「2.6 前置检查」）。

两级：硬项失败即中止，不提供绕过开关；软项照跑，记进 run.json 的 preflight 字段并在 report.md 首段标注。

离线对照前（check_compare）：
  硬：被测插件已登记、claude 可执行、eval 参数齐（读 `claude plugin eval --help` 做特性探测，不比版本号）、
      已登录（`claude auth status --json` 的 loggedIn）、`claude plugin validate` 通过、
      有环境插件时它们在 containment root 内、hook 解释器可达（冒烟）。
  软：工作区有未提交改动（check_dirty）；Claude Code 版本或主力模型与上次对照不同（check_version_model）。
会话复盘前（check_review）：会话目录可定位可读非空、登记清单非空且各仓可写（硬）；距上次复盘天数超过
  cleanupPeriodDays（软）；要调 AI 评委时查登录态（硬）。

hook 冒烟：临时空 HOME + 与 eval 子进程相同的 PATH，在插件副本里把每条 hooks 配置里的 command 经 shell 真执行一次
（CLAUDE_PLUGIN_ROOT 指向副本，带 PYTHONDONTWRITEBYTECODE=1，不往用户工作区写东西）。
exit 126 / 127 判不可达（版本管理器 shim 在空 HOME 下取不到版本即 126，解释器不在 PATH 上即 127）；
其它非零码、超时只记提示，不中止——冒烟的 stdin 样例与 eval 实际传给 hook 的不同，hook 对输入敏感时会误报。
检查逻辑不认任何 shim 名字；平台差异只在三处：配置目录定位（config_dir）、Python 解释器解析（本模块不需要，
调 Python 一律 sys.executable）、claude 可执行路径（evalrun.resolve_claude）。shell 执行在 Windows 上走 cmd.exe，未实测。
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import envplugins, evalrun, injection, registry

HARD, SOFT = 'hard', 'soft'
OK, FAIL, SKIP, WARN = 'ok', 'fail', 'skip', 'warn'
STATUS_TEXT = {OK: '通过', FAIL: '失败', SKIP: '跳过', WARN: '注意'}

UNREACHABLE_EXIT_CODES = (126, 127)
# compare 拼的 eval 命令用到的参数（evalrun.build_eval_command）；--model 只在传了 --model 时才要求
REQUIRED_EVAL_FLAGS = ('--ablation', '--keep-temp', '--no-publish', '--trust-plugin', '--scaffold', '--runs',
                       '--concurrency', '--output-dir', '--report')
CLAUDE_TIMEOUT_SEC = 120
HOOK_TIMEOUT_SEC = 60
DEFAULT_CLEANUP_PERIOD_DAYS = 30   # 官方 settings 文档 Default: 30（票 01 报告第五节）
DETAIL_MAX = 300


@dataclass
class Item:
    id: str
    label: str
    level: str
    status: str
    detail: str = ''

    def to_dict(self):
        return {'id': self.id, 'label': self.label, 'level': self.level, 'status': self.status, 'detail': self.detail}


@dataclass
class Report:
    kind: str                                   # compare / review
    items: list = field(default_factory=list)
    hook_runs: list = field(default_factory=list)
    dirty: object = None                        # 软项 dirty 的取值：True / False / None（不在 git 仓）
    claude: object = None                       # 解析出的 claude 路径，供调用方复用

    def add(self, item):
        self.items = [i for i in self.items if i.id != item.id] + [item]
        return item

    @property
    def hard_failures(self):
        return [i for i in self.items if i.level == HARD and i.status == FAIL]

    @property
    def warnings(self):
        return [i for i in self.items if i.level == SOFT and i.status == WARN]

    @property
    def passed(self):
        return not self.hard_failures

    def to_dict(self):
        return {
            'kind': self.kind,
            'passed': self.passed,
            'dirty': self.dirty,
            'warnings': [i.detail for i in self.warnings],
            'items': [i.to_dict() for i in self.items],
            'hook_smoke': list(self.hook_runs),
        }

    def render(self):
        lines = ['前置检查（%s）：%s' % ('离线对照' if self.kind == 'compare' else '会话复盘',
                                    '通过' if self.passed else '硬项失败，中止')]
        for i in self.items:
            lines.append('  [%s][%s] %s%s' % ('硬' if i.level == HARD else '软', STATUS_TEXT[i.status], i.label,
                                            '：' + i.detail if i.detail else ''))
        notes = [r for r in self.hook_runs if r.get('note')]
        if notes:
            lines.append('  hook 冒烟提示（不中止）：')
            lines += ['    - [%s] %s：%s' % (r['plugin'], r['command'], r['note']) for r in notes]
        return '\n'.join(lines)


class PreflightFailed(Exception):
    def __init__(self, report):
        super().__init__(report.render())
        self.report = report


def default_run(argv, env=None, timeout=CLAUDE_TIMEOUT_SEC, cwd=None):
    """执行外部命令，返回 (退出码, stdout, stderr)。起不来或超时时退出码为 None。"""
    try:
        p = subprocess.run([str(a) for a in argv], env=env, cwd=cwd, capture_output=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None, '', '超时（%s 秒）' % timeout
    except OSError as e:
        return None, '', str(e)
    dec = lambda b: (b or b'').decode('utf-8', errors='replace')
    return p.returncode, dec(p.stdout), dec(p.stderr)


def _short(text, limit=DETAIL_MAX):
    text = ' '.join((text or '').split())
    return text if len(text) <= limit else text[:limit] + '…'


def _runner(run):
    return run or default_run   # 调用时取模块属性，测试可 mock.patch preflight.default_run


# ---------- hook 冒烟 ----------

def _load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def collect_hook_commands(plugin_dir):
    """返回 (specs, errors)。specs 是 injection.HookSpec 列表，按 command 去重、保序。

    与注入核验共用 injection.load_hook_specs：来源是 plugin.json 的 hooks 字段（内联对象，或相对插件根的路径 /
    路径数组）与默认的 hooks/hooks.json，只收 command 型；prompt / agent 类型不起进程，不在冒烟范围。
    """
    errors, specs, seen = [], [], set()
    for spec in injection.load_hook_specs(plugin_dir, errors=errors):
        if spec.command not in seen:
            seen.add(spec.command)
            specs.append(spec)
    return specs, errors


_COPY_SKIP_TOP = ('.git', 'evals', 'plugin-evals')


def _plugin_copy(plugin_dir, dest):
    """冒烟在插件副本里跑：hook 往 ${CLAUDE_PLUGIN_ROOT} 写的东西（如 __pycache__）不落进用户工作区、不让它显示 dirty。"""
    src = Path(plugin_dir)

    def ignore(dirpath, names):
        top = [n for n in names if Path(dirpath) == src and n in _COPY_SKIP_TOP]
        return top + [n for n in names if n == '__pycache__']
    shutil.copytree(src, dest, symlinks=True, ignore=ignore)
    return dest


def smoke_hooks(plugins, env, tmp_parent=None):
    """plugins: [(标签, 插件目录)]。返回 (Item, runs)。runs 每项记 plugin / event / command / exit_code / note。

    每个插件拷一份副本，CLAUDE_PLUGIN_ROOT 指向副本；执行走 injection.run_hook（与常驻 token 静态执行同一入口，
    带 PYTHONDONTWRITEBYTECODE=1）。报错里的临时路径换回 <临时HOME> / ${CLAUDE_PLUGIN_ROOT}。
    """
    runs, unreachable, errors = [], [], []
    home = Path(tempfile.mkdtemp(prefix='devkit-plugin-eval-home-', dir=tmp_parent))
    try:
        hook_env = dict(env)
        hook_env.update(HOME=str(home), USERPROFILE=str(home))
        hook_env.pop('CLAUDE_CONFIG_DIR', None)
        for n, (label, plugin_dir) in enumerate(plugins):
            plugin_dir = Path(plugin_dir).resolve()
            specs, errs = collect_hook_commands(plugin_dir)
            errors += ['%s：%s' % (label, e) for e in errs]
            if not specs:
                continue
            try:
                copy = _plugin_copy(plugin_dir, home / 'plugins' / str(n))
            except (OSError, shutil.Error) as e:
                errors.append('%s：拷插件副本失败，未冒烟：%s' % (label, _short(str(e))))
                continue

            def clean(text, copy=copy):
                return (text or '').replace(str(copy), '${CLAUDE_PLUGIN_ROOT}').replace(str(home), '<临时HOME>')
            for s in specs:
                rec = {'plugin': label, 'event': s.event, 'command': s.command, 'exit_code': None, 'note': ''}
                r = injection.run_hook(s, copy, env=hook_env, work_parent=home / 'work', max_timeout=HOOK_TIMEOUT_SEC)
                first = clean(r['stderr_first'])
                if r['timed_out']:
                    rec['note'] = '超时（%s 秒），未判定可达性' % r['timeout']
                else:
                    rec['exit_code'] = r['exit_code']
                    if r['exit_code'] in UNREACHABLE_EXIT_CODES:
                        unreachable.append('[%s] `%s`（%s）退出码 %d%s' % (
                            label, s.command, s.event, r['exit_code'], '：' + _short(first, 160) if first else ''))
                    elif r['exit_code'] != 0:
                        rec['note'] = '退出码 %d（只作提示：冒烟输入与真实输入不同）%s' % (
                            r['exit_code'], '：' + _short(first, 160) if first else '')
                runs.append(rec)
    finally:
        shutil.rmtree(home, ignore_errors=True)

    label = 'hook 解释器可达（临时空 HOME + 同一 PATH 冒烟）'
    if unreachable or errors:
        detail = '；'.join(unreachable + errors)
        if unreachable:
            detail = ('以下 hook 命令在 eval 子会话里会静默失效（126 = 解释器起不来，常见于版本管理器 shim 在空 HOME '
                      '下取不到版本；127 = PATH 上找不到）。改用 PATH 直达真实解释器后重跑：' + detail)
        return Item('hooks_reachable', label, HARD, FAIL, detail), runs
    return Item('hooks_reachable', label, HARD, OK, '%d 条 command 已执行' % len(runs)), runs


# ---------- claude 相关硬项 ----------

def check_eval_flags(claude, env, run, model=None):
    label = 'claude plugin eval 参数齐（--help 特性探测）'
    code, out, err = run([claude, 'plugin', 'eval', '--help'], env=env)
    if code != 0:
        return Item('eval_flags', label, HARD, FAIL, '`claude plugin eval --help` 退出码 %s：%s' % (code, _short(err or out)))
    need = REQUIRED_EVAL_FLAGS + (('--model',) if model else ())
    missing = [f for f in need if not re.search(r'(?<![\w-])%s(?![\w-])' % re.escape(f), out)]
    if missing:
        return Item('eval_flags', label, HARD, FAIL, '当前 claude 的 plugin eval 缺参数：%s；升级 Claude Code 后重跑'
                    % ' '.join(missing))
    return Item('eval_flags', label, HARD, OK)


def check_logged_in(claude, env, run, item_id='logged_in', label='已登录（claude auth status）'):
    """只读 loggedIn 一个字段；输出里的账号邮箱、组织不记录。"""
    code, out, err = run([claude, 'auth', 'status', '--json'], env=env)
    try:
        logged = json.loads(out).get('loggedIn') if code is not None else None
    except (ValueError, AttributeError):
        logged = None
    if logged is True:
        return Item(item_id, label, HARD, OK)
    if logged is False:
        return Item(item_id, label, HARD, FAIL, '未登录：先运行 claude 完成登录（/login）')
    return Item(item_id, label, HARD, FAIL, '`claude auth status --json` 读不出 loggedIn（退出码 %s）：%s'
                % (code, _short(err or out, 160)))


def check_validate(claude, plugins, env, run):
    label = '插件结构合法（claude plugin validate）'
    bad = []
    for name, d in plugins:
        code, out, err = run([claude, 'plugin', 'validate', '--json', str(d)], env=env)
        if code == 0:
            continue
        msgs = []
        try:
            rep = json.loads(out)
            for part in [rep.get('manifest') or {}] + list(rep.get('contents') or []):
                msgs += ['%s: %s' % (e.get('path'), e.get('message')) for e in (part.get('errors') or [])]
        except (ValueError, AttributeError):
            pass
        bad.append('[%s] 退出码 %s：%s' % (name, code, _short('; '.join(msgs) or err or out, 200)))
    if bad:
        return Item('plugin_valid', label, HARD, FAIL, '；'.join(bad))
    return Item('plugin_valid', label, HARD, OK)


def check_containment(root, paths):
    label = '环境插件在 containment root 内'
    if not paths:
        return Item('env_plugins_contained', label, HARD, SKIP, '无环境插件臂')
    if root is None:
        return Item('env_plugins_contained', label, HARD, FAIL, '有环境插件却没给 containment root')
    root = Path(root).resolve()
    outside = []
    for p in paths:
        rp = Path(p).resolve()
        if rp != root and root not in rp.parents:
            outside.append(str(p))
    if outside:
        return Item('env_plugins_contained', label, HARD, FAIL,
                    'eval 只从 containment root（%s）内加载用例 plugins 字段列的插件；以下不在其内：%s'
                    % (root, ', '.join(outside)))
    return Item('env_plugins_contained', label, HARD, OK)


def check_env_layout(plugin_dir, env_plugins):
    """compare 开跑前臂组装目录还没建，拿不到拷贝后的路径：改查拷贝布局本身。

    环境插件由 envplugins.install 拷进 <臂组装目录>/_plugin_eval_env/<名>/，臂组装目录就是 eval 的 target，
    也就是 containment root，按构造在其内；唯一会让拷贝落空的是被测插件顶层已有同名目录，在这里提前拦下，
    不等到第 4 臂才报错。
    """
    env_dir = envplugins.ENV_DIR
    label = '环境插件在 containment root 内'
    if plugin_dir is not None and (Path(plugin_dir) / env_dir).exists():
        return Item('env_plugins_contained', label, HARD, FAIL,
                    '被测插件顶层已有 %s/，与环境插件存放目录重名，环境插件拷不进臂组装目录' % env_dir)
    names = '、'.join(getattr(ep, 'name', str(ep)) for ep in env_plugins)
    return Item('env_plugins_contained', label, HARD, OK,
                '%s 拷进臂组装目录（eval 的 containment root）下的 %s/，按构造在其内' % (names, env_dir))


# ---------- 软项 ----------

def check_dirty(head_sha, dirty):
    label = '工作区无未提交改动'
    if dirty is None:
        return Item('dirty', label, SOFT, WARN, '取不到 git 状态（不在 git 仓或没有 git），无法确认结果对应哪个提交；'
                    '这份结果不计入发版闸门')
    if dirty:
        return Item('dirty', label, SOFT, WARN, '插件目录有未提交改动（HEAD %s），照跑；run.json 记 dirty，'
                    '这份结果不计入发版闸门' % (head_sha or '?')[:12])
    return Item('dirty', label, SOFT, OK, 'HEAD %s' % (head_sha or '?')[:12])


def previous_compare(runs_dir, exclude=None):
    """runs/ 下的「上次对照」run.json：优先取最近一次完整（complete=true）的离线对照，一次完整的都没有才取最近一次
    （按运行目录名排序，目录名以 UTC 时间开头）。没有则 None。"""
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        return None
    latest = None
    for d in sorted((p for p in runs_dir.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        if d.name == exclude or not (d / 'run.json').is_file():
            continue
        try:
            rec = json.loads((d / 'run.json').read_text(encoding='utf-8'))
        except (ValueError, OSError):
            continue
        if not isinstance(rec, dict) or rec.get('kind') != 'compare':
            continue
        if rec.get('complete') is True:
            return rec
        latest = latest or rec
    return latest


def check_version_model(prev, claude_version, main_model, *, compare_model=True):
    """compare_model=False 时只比版本（check 子命令：主力模型要跑完才知道，--model 传的别名也不能拿来比完整 id）。
    任一方取不到值的字段不比，判 skip 并写明，不静默判通过。"""
    label = 'Claude Code 版本与主力模型同上次对照' if compare_model else 'Claude Code 版本同上次对照'
    if not prev:
        return Item('version_model', label, SOFT, OK, '无上次对照')
    fields = [('Claude Code 版本', prev.get('claude_code_version'), claude_version)]
    if compare_model:
        fields.append(('主力模型', prev.get('main_model'), main_model))
    diffs = ['%s %s → %s' % (n, old, new) for n, old, new in fields if old and new and old != new]
    unknown = ['%s（%s）' % (n, '上次没记' if not old else '这次取不到') for n, old, new in fields if not (old and new)]
    if diffs:
        return Item('version_model', label, SOFT, WARN, '与上次对照（%s）相比：%s；照跑，与上次结果不可直接比%s'
                    % (prev.get('run_id'), '，'.join(diffs), '；未比较：%s' % '、'.join(unknown) if unknown else ''))
    if unknown:
        return Item('version_model', label, SOFT, SKIP, '与上次对照（%s）相比：%s，未比较'
                    % (prev.get('run_id'), '、'.join(unknown)))
    return Item('version_model', label, SOFT, OK, '上次对照 %s' % prev.get('run_id'))


def claude_version(claude, env, run):
    code, out, _ = run([claude, '--version'], env=env)
    m = re.match(r'\s*(\S+)', out or '') if code == 0 else None
    return m.group(1) if m else None


# ---------- 汇总 ----------

def check_compare(*, data_dir, name, env, claude=None, model=None, others=(), env_plugins=(), containment_root=None,
                  run=None, tmp_parent=None, soft=False):
    """离线对照的硬项；soft=True 时（check 子命令单跑）顺带算软项。

    others：除被测插件外也要 validate 与冒烟的插件 [(标签, 目录)]，如上一版快照、环境插件。
    env_plugins / containment_root：有环境插件臂时传，查它们是否在臂组装目录内。
    claude 用本进程的完整 PATH 找（同 compare / resume）：env 是 eval 子进程的环境（已去掉 asdf shims），
    claude 本身可能装在 shim 后面，拿 env 的 PATH 找会误报「找不到 claude」（集成口径 04①）。
    compare 自己算软项：dirty 在写 .gitignore 之后取，版本与模型在跑完后用实际值比。
    """
    run = _runner(run)
    rep = Report('compare')
    plugin_dir = entry = None
    try:
        entry = registry.lookup(data_dir, name)
        plugin_dir = registry.plugin_dir(entry)
        # 只记仓内相对路径：run.json 入库，仓根绝对路径不在家目录下时 scrub_home 换不掉
        rep.add(Item('registered', '被测插件已登记', HARD, OK, '仓内路径 %s' % entry['plugin_path']))
    except registry.RegistryError as e:
        rep.add(Item('registered', '被测插件已登记', HARD, FAIL, str(e)))

    try:
        claude = claude or evalrun.resolve_claude()
        rep.claude = claude
        rep.add(Item('claude_executable', 'claude 可执行', HARD, OK, str(claude)))
    except evalrun.ClaudeNotFound as e:
        claude = None
        rep.add(Item('claude_executable', 'claude 可执行', HARD, FAIL, str(e)))

    plugins = ([('当前版', plugin_dir)] if plugin_dir else []) + list(others)
    if claude:
        rep.add(check_eval_flags(claude, env, run, model))
        rep.add(check_logged_in(claude, env, run))
        if plugins:
            rep.add(check_validate(claude, plugins, env, run))
        else:
            rep.add(Item('plugin_valid', '插件结构合法（claude plugin validate）', HARD, SKIP, '被测插件未登记'))
    else:
        for i, label in (('eval_flags', 'claude plugin eval 参数齐（--help 特性探测）'),
                         ('logged_in', '已登录（claude auth status）'),
                         ('plugin_valid', '插件结构合法（claude plugin validate）')):
            rep.add(Item(i, label, HARD, SKIP, 'claude 不可执行'))
    if env_plugins and containment_root is None:
        rep.add(check_env_layout(plugin_dir, env_plugins))
    else:
        rep.add(check_containment(containment_root, list(env_plugins)))
    if plugins:
        hooks_item, rep.hook_runs = smoke_hooks(plugins, env, tmp_parent)
        rep.add(hooks_item)
    else:
        rep.add(Item('hooks_reachable', 'hook 解释器可达（临时空 HOME + 同一 PATH 冒烟）', HARD, SKIP, '被测插件未登记'))

    if soft and entry:
        from .compare import git_state   # 延迟导入：compare 依赖本模块
        head, dirty = git_state(entry['repo'], entry['plugin_path'])
        rep.dirty = dirty
        rep.add(check_dirty(head, dirty))
        prev = previous_compare(Path(entry['repo']) / 'plugin-evals' / name / 'runs')
        cur_version = claude_version(claude, env, run) if claude else None
        item = rep.add(check_version_model(prev, cur_version, None, compare_model=False))
        if prev:
            item.detail += '；主力模型要跑完才知道，compare 跑完后再比一次'
    return rep


def config_dir(env, home=Path.home):
    """配置目录：CLAUDE_CONFIG_DIR，缺省 ~/.claude。三处平台差异之一（家目录由 Path.home 按平台取）。"""
    if env.get('CLAUDE_CONFIG_DIR'):
        return Path(env['CLAUDE_CONFIG_DIR']).expanduser()
    return home() / '.claude'


def _cleanup_period_days(cfg):
    try:
        v = _load_json(cfg / 'settings.json').get('cleanupPeriodDays')
    except (ValueError, OSError, AttributeError):
        v = None
    return (v, '设置') if isinstance(v, int) and v >= 1 else (DEFAULT_CLEANUP_PERIOD_DAYS, '默认')


def _has_jsonl(root):
    for _, _, files in os.walk(root):
        if any(f.endswith('.jsonl') for f in files):
            return True
    return False


def _last_review(plugins):
    """各仓 plugin-evals/<plugin>/reviews/ 下文件名以 YYYY-MM-DD 开头的最大日期。"""
    best = None
    for name, entry in plugins.items():
        d = Path(entry['repo']) / 'plugin-evals' / name / 'reviews'
        if not d.is_dir():
            continue
        for f in d.iterdir():
            m = re.match(r'(\d{4}-\d{2}-\d{2})', f.name)
            if m:
                try:
                    day = datetime.strptime(m.group(1), '%Y-%m-%d').replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                best = day if best is None or day > best else best
    return best


def check_review(*, data_dir, env, need_judge=False, claude=None, run=None, now=None):
    run = _runner(run)
    now = now or datetime.now(timezone.utc)
    rep = Report('review')
    cfg = config_dir(env)
    projects = cfg / 'projects'
    label = '会话目录可定位、可读、非空'
    if not projects.is_dir():
        rep.add(Item('sessions_readable', label, HARD, FAIL, '%s 不存在（配置目录取自 CLAUDE_CONFIG_DIR，缺省 ~/.claude）'
                     % projects))
    elif not os.access(projects, os.R_OK | os.X_OK):
        rep.add(Item('sessions_readable', label, HARD, FAIL, '%s 不可读' % projects))
    elif not _has_jsonl(projects):
        rep.add(Item('sessions_readable', label, HARD, FAIL, '%s 下没有会话记录（*.jsonl）' % projects))
    else:
        rep.add(Item('sessions_readable', label, HARD, OK, str(projects)))

    label = '登记清单非空、各仓路径存在且可写'
    try:
        plugins = registry.load(data_dir)['plugins']
    except registry.RegistryError as e:
        plugins = {}
        rep.add(Item('registry_writable', label, HARD, FAIL, str(e)))
    else:
        bad = []
        for name, entry in sorted(plugins.items()):
            repo = Path(entry['repo'])
            if not repo.is_dir():
                bad.append('%s：仓路径不存在 %s' % (name, repo))
            elif not os.access(repo, os.W_OK | os.X_OK):
                bad.append('%s：仓路径不可写 %s' % (name, repo))
        if not plugins:
            rep.add(Item('registry_writable', label, HARD, FAIL, '登记清单为空：先用 register 登记被测插件'))
        elif bad:
            rep.add(Item('registry_writable', label, HARD, FAIL, '；'.join(bad)))
        else:
            rep.add(Item('registry_writable', label, HARD, OK, '%d 个插件' % len(plugins)))

    days, origin = _cleanup_period_days(cfg)
    last = _last_review(plugins)
    label = '距上次复盘不超过 cleanupPeriodDays'
    if last is None:
        rep.add(Item('review_gap', label, SOFT, OK, '无上次复盘记录；会话保留 %d 天（%s）' % (days, origin)))
    else:
        gap = (now - last).days
        if gap > days:
            rep.add(Item('review_gap', label, SOFT, WARN,
                         '上次复盘 %s，距今 %d 天，超过会话保留期 %d 天（%s）：%s 至 %s 之间的会话已被清理，本次复盘未覆盖'
                         % (last.strftime('%Y-%m-%d'), gap, days, origin, last.strftime('%Y-%m-%d'),
                            datetime.fromtimestamp(now.timestamp() - days * 86400, timezone.utc).strftime('%Y-%m-%d'))))
        else:
            rep.add(Item('review_gap', label, SOFT, OK, '上次复盘 %s，距今 %d 天；保留期 %d 天（%s）'
                         % (last.strftime('%Y-%m-%d'), gap, days, origin)))

    label = '已登录（要调 AI 评委时）'
    if not need_judge:
        rep.add(Item('judge_logged_in', label, HARD, SKIP, '本次不调 AI 评委'))
    else:
        try:
            claude = claude or evalrun.resolve_claude()
            rep.add(check_logged_in(claude, env, run, 'judge_logged_in', label))
        except evalrun.ClaudeNotFound as e:
            rep.add(Item('judge_logged_in', label, HARD, FAIL, str(e)))
    return rep
