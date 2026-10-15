"""插件目录的 git 状态：HEAD sha 与 dirty（有无未提交改动）。compare、resume、check 记进 run.json，闸门据此排除。

dirty 口径（票 14 统一，2026-10-15 票 03 审查遗留）：
- 排除插件根下的 `evals/`：与插件内容指纹的排除范围一致，补用例不让结果变成 dirty；
- 排除 compare 自己往 `.gitignore` 写的那一行（`ensure_gitignore` 写的 `<插件>/evals/results/`）：
  插件在仓根时 `.gitignore` 就在插件目录里，首次对照必然改它。`.gitignore` 相对 HEAD 只差这一行时不算改动；
- 插件在仓根时另排除 `plugin-evals/`（结果目录本身）。
取不到 git 状态（没有 git、不在 git 仓、仓里没有提交）时 dirty 为 None；闸门只认 `dirty is False`。
"""
import shutil
import subprocess
from pathlib import Path


def gitignore_line(plugin_path):
    """compare 往仓根 .gitignore 写的那一行（ensure_gitignore 与本模块共用）。"""
    return 'evals/results/' if plugin_path == '.' else '%s/evals/results/' % plugin_path.rstrip('/')


def _run(git, repo, *args):
    return subprocess.run([git, '-C', str(repo), '-c', 'core.quotepath=off', *args], capture_output=True,
                          text=True, encoding='utf-8', errors='replace')


def _lines_without(text, line):
    return [ln.rstrip('\r') for ln in text.splitlines() if ln.strip() != line]


def _gitignore_only_self_line(git, repo, plugin_path):
    """仓根 .gitignore 相对 HEAD 是否只差 compare 写的那一行（含：HEAD 里没有、工作区只有这一行）。"""
    line = gitignore_line(plugin_path)
    head = _run(git, repo, 'show', 'HEAD:./.gitignore')
    head_text = head.stdout if head.returncode == 0 else ''
    p = Path(repo) / '.gitignore'
    try:
        work_text = p.read_text(encoding='utf-8') if p.is_file() else ''
    except (OSError, UnicodeDecodeError):
        return False
    return _lines_without(head_text, line) == _lines_without(work_text, line)


def _porcelain_paths(out):
    """`git status --porcelain -z` 的输出 → 改动路径列表（改名、复制只取新路径）。"""
    fields = out.split('\0')
    paths, i = [], 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        paths.append(path)
        if 'R' in xy or 'C' in xy:
            i += 1          # 下一个字段是原路径
    return paths


def git_state(repo, plugin_path, git=None):
    """返回 (HEAD sha, dirty)。不在 git 仓、没有 git 或仓里没有提交时都是 None。"""
    git = shutil.which('git') if git is None else git
    if not git:
        return None, None
    head = _run(git, repo, 'rev-parse', '--verify', '-q', 'HEAD')
    if head.returncode != 0:
        return None, None
    if plugin_path == '.':
        scope = ['--', '.', ':(exclude)plugin-evals', ':(exclude)evals']
    else:
        p = plugin_path.rstrip('/')
        scope = ['--', p, ':(exclude)%s/evals' % p]
    st = _run(git, repo, 'status', '--porcelain', '-z', '--untracked-files=all', *scope)
    if st.returncode != 0:
        return head.stdout.strip(), None
    changed = _porcelain_paths(st.stdout)
    if plugin_path == '.' and '.gitignore' in changed and _gitignore_only_self_line(git, repo, plugin_path):
        changed.remove('.gitignore')
    return head.stdout.strip(), bool(changed)
