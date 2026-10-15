"""调起 `claude plugin eval`：解析可执行路径、准备子进程环境、拼命令、执行。"""
import functools
import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path


class ClaudeNotFound(Exception):
    pass


# 父会话注入的会话级变量，带进 eval 子进程会让它误以为自己是某个会话的子会话（票 01 run.sh 同款清单）
SESSION_VARS = (
    'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDE_CODE_MESSAGING_SOCKET',
    'CLAUDE_CODE_MESSAGING_TOKEN', 'CLAUDE_CODE_SESSION_ATTENDED', 'CLAUDE_CODE_ENTRYPOINT',
    'CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS',
)


def resolve_claude(which=shutil.which, path=None):
    """返回 claude 可执行文件的完整路径。Windows 上 npm 装的是 claude.cmd，which 按 PATHEXT 找得到。"""
    found = which('claude', path=path)
    if not found:
        raise ClaudeNotFound('PATH 上找不到 claude 可执行文件；装好 Claude Code 后再跑')
    return found


def _is_asdf_shim(entry):
    norm = entry.replace('\\', '/').rstrip('/')
    return norm.endswith('/.asdf/shims')


def child_env(base=None, pathsep=os.pathsep):
    """复制一份环境：去掉会话级变量；PATH 去掉 asdf shims。

    asdf shim 在 eval 的临时 HOME 下 exit 126，hook 静默失效而 eval 不报错（spec「一」已实测第 2 条），
    所以 PATH 必须直接命中真实的 node。
    """
    env = dict(os.environ if base is None else base)
    for k in SESSION_VARS:
        env.pop(k, None)
    if 'PATH' in env:
        env['PATH'] = pathsep.join(p for p in env['PATH'].split(pathsep) if p and not _is_asdf_shim(p))
    return env


def build_eval_command(claude, arm_dir, output_dir, *, runs, concurrency, report_path, model=None):
    """--trust-plugin 与 --scaffold 只对已登记插件加：登记即信任声明，调用方负责先查登记。"""
    cmd = [
        str(claude), 'plugin', 'eval', str(arm_dir),
        '--ablation', 'none',
        '--keep-temp',
        '--no-publish',
        '--trust-plugin',
        '--scaffold',
        '--runs', str(runs),
        '-j', str(concurrency),
        '--output-dir', str(output_dir),
        '--report', str(report_path),
    ]
    if model:
        cmd += ['--model', model]
    return cmd


# 超时被终止时记的退出码（同 GNU timeout）。不在 0 / 1 之内，compare 据此把该臂记为不完整、可续跑。
EVAL_TIMEOUT_EXIT_CODE = 124
# 超时后先发 SIGTERM，等这么多秒再强杀
KILL_GRACE_SECONDS = 10


def _kill_tree(proc, own_group):
    """eval 会起一串 claude 子进程：POSIX 杀整个进程组（own_group 为真时 eval 是组长），Windows 用 taskkill /T。"""
    if sys.platform == 'win32':
        taskkill = shutil.which('taskkill')
        if taskkill:
            subprocess.run([taskkill, '/T', '/F', '/PID', str(proc.pid)], capture_output=True)
        else:
            proc.kill()
        return
    if not own_group:
        proc.terminate()   # 先 SIGTERM，让 eval 自己收拾它起的 claude 子进程；宽限期过了再强杀
        try:
            proc.wait(timeout=KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except OSError:
            return
        try:
            proc.wait(timeout=KILL_GRACE_SECONDS)
            return
        except subprocess.TimeoutExpired:
            continue


class _ExitOnSignal(object):
    """父进程被 SIGTERM / SIGHUP 按默认处理直接退出时，eval 会留在后台继续跑（如后台跑的 compare 被 TaskStop 停掉）：
    限时模式下 eval 在独立进程组里，整组都留下；不限时模式下 eval 与父进程同组，只有信号单发给父进程时才留下。
    这里把这两个信号转成 SystemExit（退出码 128+信号值），让 run_eval 的 except BaseException 执行到 _kill_tree。
    限时与不限时都装；只在主线程装（signal 的限制），退出时还原。"""

    SIGNALS = ('SIGTERM', 'SIGHUP')

    def __init__(self, enabled):
        self.enabled = enabled and threading.current_thread() is threading.main_thread()
        self.saved = {}

    @staticmethod
    def _raise(signum, frame):
        raise SystemExit(128 + signum)

    def __enter__(self):
        if self.enabled:
            for name in self.SIGNALS:
                sig = getattr(signal, name, None)
                if sig is not None:
                    self.saved[sig] = signal.signal(sig, self._raise)
        return self

    def __exit__(self, *exc):
        for sig, old in self.saved.items():
            signal.signal(sig, old)
        return False


def run_eval(cmd, cwd, env, log_dir, timeout=None):
    """执行一次 eval，stdout / stderr 落到 log_dir。返回 (退出码, stderr 文本)。

    退出码 1 既可能是「有用例低于阈值」也可能是「有用例加载失败」，调用方另行核对，不能当运行失败。
    timeout（秒）为 None 时不限时；超时则终止 eval 及其子进程，返回 EVAL_TIMEOUT_EXIT_CODE。
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    timed_out = False
    with open(log_dir / 'eval.stdout', 'wb') as out, open(log_dir / 'eval.stderr', 'wb') as err:
        # 限时才另起进程组（超时好整组杀）；不限时保持原样，终端 Ctrl-C 照常连带 eval 一起停
        kw = {'start_new_session': True} if timeout and sys.platform != 'win32' else {}
        with _ExitOnSignal(sys.platform != 'win32'):
            proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=out, stderr=err, stdin=subprocess.DEVNULL, **kw)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_tree(proc, bool(kw))
                proc.wait()
            except BaseException:
                _kill_tree(proc, bool(kw))   # Ctrl-C、SIGTERM / SIGHUP 等：别把 eval 子进程留在后台继续跑
                raise
    if timed_out:
        with open(log_dir / 'eval.stderr', 'a', encoding='utf-8') as err:
            err.write('\n[devkit-plugin-eval] eval 运行超时（%s 秒）被终止\n' % timeout)
    stderr = (log_dir / 'eval.stderr').read_text(encoding='utf-8', errors='replace')
    return (EVAL_TIMEOUT_EXIT_CODE if timed_out else proc.returncode), stderr


def runner_with_timeout(seconds):
    """给 compare / resume 的 runner 参数用：seconds 为空或 0 时就是 run_eval 本身。"""
    return functools.partial(run_eval, timeout=seconds) if seconds else run_eval


def find_aggregate(output_dir):
    hits = sorted(Path(output_dir).rglob('aggregate-result.json'), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def which_node(env):
    return shutil.which('node', path=env.get('PATH'))
