"""调起 `claude plugin eval`：解析可执行路径、准备子进程环境、拼命令、执行。"""
import os
import shutil
import subprocess
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


def run_eval(cmd, cwd, env, log_dir):
    """执行一次 eval，stdout / stderr 落到 log_dir。返回 (退出码, stderr 文本)。

    退出码 1 既可能是「有用例低于阈值」也可能是「有用例加载失败」，调用方另行核对，不能当运行失败。
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / 'eval.stdout', 'wb') as out, open(log_dir / 'eval.stderr', 'wb') as err:
        proc = subprocess.run(cmd, cwd=str(cwd), env=env, stdout=out, stderr=err, stdin=subprocess.DEVNULL)
    stderr = (log_dir / 'eval.stderr').read_text(encoding='utf-8', errors='replace')
    return proc.returncode, stderr


def find_aggregate(output_dir):
    hits = sorted(Path(output_dir).rglob('aggregate-result.json'), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def which_node(env):
    return shutil.which('node', path=env.get('PATH'))
