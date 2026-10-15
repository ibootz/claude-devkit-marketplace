"""单测声明 unit-tests.json 的 Python 实现：闸门检查命令（gate）按它跑被测插件的确定性单测。

格式（spec「2.7 确定性单测」）：
  { "tests": [ { "run": ["node", "tests/x.test.js"], "timeout_sec": 120, "platforms": ["darwin", "linux"] } ] }
- run（必填）：argv 数组，首元素是解释器名，不经 shell；工作目录固定为插件根
- timeout_sec（可选，缺省 120）：正数，超时判失败
- platforms（可选，缺省全部）：darwin / linux / win32 的非空子集
不收其它字段。

同一份声明还由本仓 pre-commit 的 JS 实现（仓根 scripts/run-unit-tests.js）读。两边的声明校验、解释器解析、
逐条状态必须一致，靠仓根 scripts/unit-tests-fixtures/ 的共用样例对齐（tests/test_unittests.py 逐个比对）。
改这里的判定规则前，先改 JS 实现与样例的 expected.json。

两处只在「怎么处置」上不同（spec 2.7 对照表）：
| 情形 | 闸门（gate_verdict） | pre-commit（precommit_verdict） |
| 未声明 | 提示「未声明单测」，不拦 | 静默 |
| 声明不合法 | 判失败 | 拦 |
| 平台不在 platforms | 跳过并提示 | 跳过并提示 |
| 解释器解析不到 | 判失败 | 跳过并警告 |
| 任一条非零或超时 | 判失败 | 拦 |
"""
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DECL_NAME = 'unit-tests.json'
DEFAULT_TIMEOUT_SEC = 120
PLATFORMS = ('darwin', 'linux', 'win32')
TOP_FIELDS = ('tests',)
TEST_FIELDS = ('run', 'timeout_sec', 'platforms')
OUTPUT_TAIL_LINES = 40
# git rev-parse --local-env-vars 不可用时的兜底清单（与 JS 实现同一份）
FALLBACK_GIT_LOCAL_ENV = (
    'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_CONFIG', 'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT',
    'GIT_OBJECT_DIRECTORY', 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_IMPLICIT_WORK_TREE', 'GIT_GRAFT_FILE',
    'GIT_INDEX_FILE', 'GIT_NO_REPLACE_OBJECTS', 'GIT_REPLACE_REF_BASE', 'GIT_PREFIX',
    'GIT_SHALLOW_FILE', 'GIT_COMMON_DIR',
)

# 逐条状态
PASSED, FAILED, TIMEOUT = 'passed', 'failed', 'timeout'
SKIPPED_PLATFORM, INTERPRETER_MISSING = 'skipped-platform', 'interpreter-missing'


def current_platform():
    """与 Node 的 process.platform 同名：darwin / linux / win32。"""
    if sys.platform.startswith('win'):
        return 'win32'
    if sys.platform.startswith('linux'):
        return 'linux'
    return sys.platform


# ---------- 声明校验 ----------

def _reject_constant(name):
    # JS 的 JSON.parse 不认 NaN / Infinity / -Infinity，Python 的 json.loads 默认认；这里拒掉以对齐
    raise ValueError('不是合法 JSON 常量：%s' % name)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _finite_positive(v):
    if not _is_number(v):
        return False
    try:
        f = float(v)
    except OverflowError:          # 超长整数：JS 解析成 Infinity，同样不合法
        return False
    return math.isfinite(f) and f > 0


def validate_declaration(text):
    """返回 (tests, errors)。errors 每项 (code, message)；code 与 JS 实现对齐：
    not-json / not-object / unknown-field / bad-tests / bad-test / bad-run / bad-timeout / bad-platforms。
    有错误时 tests 为空列表；每条 test 为 {'run', 'timeout_sec', 'platforms'}（缺省值已补齐）。"""
    errors = []

    def err(code, message):
        errors.append((code, message))

    try:
        decl = json.loads(text, parse_constant=_reject_constant)
    except ValueError as e:
        err('not-json', '不是合法 JSON：%s' % e)
        return [], errors
    if not isinstance(decl, dict):
        err('not-object', '顶层必须是对象 {"tests": [...]}')
        return [], errors
    for k in decl:
        if k not in TOP_FIELDS:
            err('unknown-field', '顶层有约定外字段 "%s"，只允许 tests' % k)
    if not isinstance(decl.get('tests'), list):
        err('bad-tests', 'tests 必填，且必须是数组')
        return [], errors
    tests = []
    for i, t in enumerate(decl['tests']):
        at = 'tests[%d]' % i
        if not isinstance(t, dict):
            err('bad-test', '%s 必须是对象' % at)
            continue
        for k in t:
            if k not in TEST_FIELDS:
                err('unknown-field', '%s 有约定外字段 "%s"，只允许 %s' % (at, k, ' / '.join(TEST_FIELDS)))
        run = t.get('run')
        if not (isinstance(run, list) and run and all(isinstance(a, str) and a != '' for a in run)):
            err('bad-run', '%s.run 必填，且必须是非空字符串组成的非空数组' % at)
        if 'timeout_sec' in t and not _finite_positive(t['timeout_sec']):
            err('bad-timeout', '%s.timeout_sec 必须是正数（秒）' % at)
        if 'platforms' in t:
            p = t['platforms']
            if not (isinstance(p, list) and p and all(isinstance(x, str) and x in PLATFORMS for x in p)):
                err('bad-platforms', '%s.platforms 必须是 %s 的非空子集' % (at, ' / '.join(PLATFORMS)))
        tests.append({'run': run, 'timeout_sec': t.get('timeout_sec', DEFAULT_TIMEOUT_SEC),
                      'platforms': t.get('platforms', list(PLATFORMS))})
    return ([] if errors else tests), errors


# ---------- 解释器解析 ----------

def find_executable(name, cwd=None, env=None, platform=None):
    """与 JS 的 findExecutable 同口径：名字带路径分隔符时相对 cwd 解析、只要求是文件；
    否则沿 PATH 找，POSIX 要求可执行位，Windows 按 PATHEXT 补扩展名（名字自带 PATHEXT 里的扩展名才按原名找）。"""
    env = os.environ if env is None else env
    platform = platform or current_platform()
    if '/' in name or '\\' in name:
        full = Path(cwd or os.getcwd()) / name
        return str(full.resolve()) if full.is_file() else None
    exts = ['']
    if platform == 'win32':
        pathext = [e for e in (env.get('PATHEXT') or '.COM;.EXE;.BAT;.CMD').split(';') if e]
        own = os.path.splitext(name)[1].upper()
        exts = [''] if own and any(e.upper() == own for e in pathext) else pathext
    for d in (env.get('PATH') or '').split(os.pathsep):
        if not d:
            continue
        for ext in exts:
            full = os.path.join(d, name + ext)
            if os.path.isfile(full) and (platform == 'win32' or os.access(full, os.X_OK)):
                return full
    return None


def default_probe(argv):
    """argv 加 --version 能否跑成功、且报的是 Python 3（老环境的 python 可能是 2，应算解析不到）。"""
    exe = find_executable(argv[0])
    if not exe:
        return False
    try:
        r = subprocess.run([exe] + list(argv[1:]) + ['--version'], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and re.search(r'^Python 3\.', (r.stdout or '') + (r.stderr or ''), re.M) is not None


def resolve_interpreter(name, cwd=None, probe=default_probe, find=None):
    """返回解析后的 argv 前缀（列表）或 None。python3 依次试 python3 → python → py -3，以 probe 成功为准；
    其余解释器只解析出可执行文件路径。"""
    find = find or (lambda n: find_executable(n, cwd=cwd))
    if name == 'python3':
        for cand in (['python3'], ['python'], ['py', '-3']):
            if probe(cand):
                return [find(cand[0]) or cand[0]] + cand[1:]
        return None
    exe = find(name)
    return [exe] if exe else None


# ---------- 执行 ----------

def child_env(base=None):
    """子进程环境去掉 git 的仓库级变量：单测常在临时目录 git init，继承 GIT_DIR 等会打到外层仓。"""
    env = dict(os.environ if base is None else base)
    names = None
    git = shutil.which('git')
    if git:
        try:
            r = subprocess.run([git, 'rev-parse', '--local-env-vars'], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                names = [n for n in r.stdout.splitlines() if n]
        except (OSError, subprocess.SubprocessError):
            names = None
    for n in names if names is not None else FALLBACK_GIT_LOCAL_ENV:
        env.pop(n, None)
    return env


def _kill_tree(proc):
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/pid', str(proc.pid), '/T', '/F'], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        try:
            proc.kill()
        except OSError:
            pass


def run_one(argv, cwd, timeout_sec, env):
    """跑一条命令，返回 {'status': passed|failed|timeout, 'code', 'output', 'ms'}。
    输出写临时文件而不是管道：单测拉起的孙进程攥着管道不放时，读管道会一直等到超时。"""
    started = time.monotonic()
    with tempfile.TemporaryFile() as out:
        kw = {'start_new_session': True} if os.name != 'nt' else {}
        try:
            proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=subprocess.STDOUT, **kw)
        except OSError as e:
            return {'status': FAILED, 'code': None, 'output': '启动失败：%s' % e,
                    'ms': int((time.monotonic() - started) * 1000)}
        timed_out = False
        try:
            proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            proc.wait()
        if not timed_out and os.name != 'nt':
            _kill_tree(proc)        # 单测已结束：进程组里残留的孙进程（后台 server、sleep &）一并收掉
        out.seek(0)
        output = out.read().decode('utf-8', 'replace')
    status = TIMEOUT if timed_out else (PASSED if proc.returncode == 0 else FAILED)
    return {'status': status, 'code': proc.returncode, 'output': output,
            'ms': int((time.monotonic() - started) * 1000)}


def run_plugin(plugin_dir, platform=None, env=None, resolve=resolve_interpreter):
    """对一个插件目录给出与 JS 实现同形的结构化结果：
    {plugin, declaration: undeclared|invalid|ok, errors: [code...], messages: [...],
     tests: [{index, run, status, code?, ms?, output?}]}"""
    plugin_dir = Path(plugin_dir)
    platform = platform or current_platform()
    result = {'plugin': plugin_dir.name, 'declaration': 'undeclared', 'errors': [], 'messages': [], 'tests': []}
    decl_path = plugin_dir / DECL_NAME
    if not decl_path.is_file():
        return result
    tests, errors = validate_declaration(decl_path.read_text(encoding='utf-8'))
    if errors:
        result.update(declaration='invalid', errors=sorted({c for c, _ in errors}), messages=[m for _, m in errors])
        return result
    result['declaration'] = 'ok'
    env = child_env() if env is None else env
    for index, t in enumerate(tests):
        entry = {'index': index, 'run': t['run']}
        result['tests'].append(entry)
        if platform not in t['platforms']:
            entry['status'] = SKIPPED_PLATFORM
            continue
        prefix = resolve(t['run'][0], cwd=str(plugin_dir))
        if not prefix:
            entry['status'] = INTERPRETER_MISSING
            continue
        entry.update(run_one(list(prefix) + list(t['run'][1:]), plugin_dir, t['timeout_sec'], env))
    return result


# ---------- 两处口径 ----------

def precommit_verdict(result):
    """pre-commit 口径（与 JS 的 precommitVerdict 一致，只用于共用样例对齐）：声明不合法、任一条失败或超时即拦。"""
    if result['declaration'] == 'invalid':
        return 'block'
    return 'block' if any(t.get('status') in (FAILED, TIMEOUT) for t in result['tests']) else 'pass'


def gate_verdict(result):
    """闸门口径：返回 (是否通过, 提示行列表)。未声明只提示；不合法、解释器解析不到、失败、超时都判失败。"""
    if result['declaration'] == 'undeclared':
        return True, ['未声明单测（插件根没有 %s），不拦' % DECL_NAME]
    if result['declaration'] == 'invalid':
        return False, ['%s 不合法，判失败：%s' % (DECL_NAME, '；'.join(result['messages']))]
    ok, lines = True, []
    for t in result['tests']:
        label = 'tests[%d] %s' % (t['index'], ' '.join(t['run']))
        st = t.get('status')
        if st == PASSED:
            lines.append('通过 %s（%.1fs）' % (label, t.get('ms', 0) / 1000))
        elif st == SKIPPED_PLATFORM:
            lines.append('跳过 %s：当前平台不在 platforms 里' % label)
        elif st == INTERPRETER_MISSING:
            ok = False
            lines.append('失败 %s：解释器 %s 解析不到' % (label, t['run'][0]))
        else:
            ok = False
            why = '超时（%.1fs）' % (t.get('ms', 0) / 1000) if st == TIMEOUT else '退出码 %s' % t.get('code')
            lines.append('失败 %s：%s' % (label, why))
            tail = (t.get('output') or '').strip().splitlines()[-OUTPUT_TAIL_LINES:]
            lines += ['    %s' % ln for ln in tail]
    if not result['tests']:
        lines.append('单测声明里没有任何单测')
    return ok, lines
