"""上一版臂的来源：找「上一版」的引入提交，用 git archive 解出快照。

「上一版」（仓根 CONTEXT.md）：被测插件历史里版本号与当前版不同的最近一个版本，以该版本号首次出现时的
内容为准；可由用户用 --base <提交|版本号> 另行指定。

自动认定（spec「2.2 离线对照」第 3 步）：
1. 沿 HEAD 用 `git log --follow --date-order` 追踪 plugin.json（跨改名），得到「提交 → 当时的 plugin.json 路径
   → 版本号」序列，新到旧；
2. 序列里第一个版本号与工作目录 plugin.json 不同的，就是上一版的版本号；
3. 取该版本号在序列里最早出现的提交（引入提交）。同号跨多个提交、并行分支各自写出同号时都取最早那个。

退化（自动跳过上一版臂）：没有 git、不在 git 仓、仓里没有提交、历史里没有与当前不同的版本号、快照失败。
--base 解析不到不退化，抛 BaseNotFound（传了 --base 但没有 git、不在 git 仓、仓里没有提交同样抛）：用户点名要的基线找不到，静默只跑两臂会掩盖输入错误。
"""
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MANIFEST_REL = '.claude-plugin/plugin.json'


class BaseNotFound(Exception):
    pass


class SnapshotError(Exception):
    pass


@dataclass
class Resolution:
    degraded: bool
    reason: Optional[str] = None        # 退化原因，写进报告首段
    reason_kind: Optional[str] = None   # not-git / no-history / no-different-version / snapshot-failed
    commit: Optional[str] = None        # 上一版取自哪个提交（完整 sha）
    version: Optional[str] = None
    name: Optional[str] = None          # 该提交里 plugin.json 的 name
    path_in_repo: Optional[str] = None  # 该提交里插件目录相对仓根的 posix 路径，仓根插件为 '.'
    obtained_by: Optional[str] = None   # auto / --base
    base: Optional[str] = None          # 用户传的 --base 原文
    current_name: Optional[str] = None
    git: Optional[str] = None           # git 可执行文件路径
    toplevel: Optional[str] = None      # git 仓根

    @property
    def cross_rename(self):
        return bool(not self.degraded and self.name and self.current_name and self.name != self.current_name)

    def to_record(self):
        return {
            'degraded': self.degraded, 'reason': self.reason, 'reason_kind': self.reason_kind,
            'commit': self.commit, 'version': self.version, 'name': self.name,
            'path_in_repo': self.path_in_repo, 'obtained_by': self.obtained_by, 'base': self.base,
            'cross_rename': self.cross_rename,
        }


def _degraded(kind, reason, **kw):
    return Resolution(degraded=True, reason=reason, reason_kind=kind, **kw)


def _run(git, top, *args, binary=False, env=None):
    return subprocess.run([git, '-C', str(top), '-c', 'core.quotepath=off', *args],
                          capture_output=True, env=env, **({} if binary else {'text': True, 'encoding': 'utf-8',
                                                                                 'errors': 'replace'}))


def _manifest_at(git, top, commit, path):
    proc = _run(git, top, 'show', '%s:%s' % (commit, path))
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _history(git, top, manifest_rel):
    """[(提交 sha, 该提交里 plugin.json 的路径, 版本号, name)]，新到旧；读不出 plugin.json 的提交跳过。"""
    proc = _run(git, top, 'log', '--follow', '--date-order', '--format=%x00%H', '--name-only', 'HEAD',
                '--', manifest_rel)
    if proc.returncode != 0:
        return []
    out = []
    for chunk in proc.stdout.split('\x00')[1:]:
        lines = [ln for ln in chunk.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue      # merge 提交不带文件名
        sha, path = lines[0].strip(), lines[-1].strip()
        data = _manifest_at(git, top, sha, path)
        if data is None:
            continue
        out.append((sha, path, data.get('version'), data.get('name')))
    return out


def _plugin_dir_of(manifest_path):
    d = manifest_path[:-len(MANIFEST_REL)].rstrip('/')
    return d or '.'


def resolve(plugin_dir, current_version, *, base=None, current_name=None, git=None, ceiling=None):
    """认定上一版。git=None 时按 PATH 找；git='' 表示没有 git。ceiling 只给测试用（GIT_CEILING_DIRECTORIES）。"""
    git = shutil.which('git') if git is None else git
    plugin_dir = Path(plugin_dir).resolve()
    if current_name is None:
        try:
            current_name = json.loads((plugin_dir / MANIFEST_REL).read_text(encoding='utf-8')).get('name')
        except (OSError, ValueError):
            current_name = None
    common = {'base': base, 'current_name': current_name, 'obtained_by': '--base' if base else 'auto'}

    def degrade(kind, reason):
        # 用户点名了 --base 却连仓都没有：同「--base 解析不到」，中止而不是静默退化成两臂
        if base:
            raise BaseNotFound('传了 --base %s，但%s' % (base, reason))
        return _degraded(kind, reason, **common)

    if not git:
        return degrade('not-git', '找不到 git 可执行文件，取不到上一版')
    env = None
    if ceiling:
        env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(Path(ceiling).resolve()))
    top = _run(git, plugin_dir, 'rev-parse', '--show-toplevel', env=env)
    if top.returncode != 0:
        return degrade('not-git', '被测插件不在 git 仓里（%s），取不到上一版' % plugin_dir)
    toplevel = Path(top.stdout.strip()).resolve()
    common.update(git=git, toplevel=str(toplevel))
    if _run(git, toplevel, 'rev-parse', '--verify', '-q', 'HEAD').returncode != 0:
        return degrade('no-history', 'git 仓里还没有任何提交，取不到上一版')
    rel = Path(os.path.relpath(plugin_dir, toplevel)).as_posix()
    manifest_rel = MANIFEST_REL if rel == '.' else '%s/%s' % (rel, MANIFEST_REL)
    hist = _history(git, toplevel, manifest_rel)

    if base:
        return _resolve_base(git, toplevel, hist, base, manifest_rel, common)
    if not hist:
        return _degraded('no-history', 'git 历史里没有 %s 的提交记录（插件还没提交过），取不到上一版' % manifest_rel,
                         **common)
    # current_version 是 plugin.json 的原值：没写 version 为 None，与历史里同样没写的提交视为同号
    different = [h for h in hist if h[2] != current_version]
    if not different:
        now = '当前的 %s' % current_version if current_version is not None else '没写 version'
        return _degraded('no-different-version',
                         'git 历史里 plugin.json 的版本号一直是%s，没有与它不同的版本' % now, **common)
    prev_version = different[0][2]
    sha, path, version, name = [h for h in hist if h[2] == prev_version][-1]
    return Resolution(degraded=False, commit=sha, version=version, name=name,
                      path_in_repo=_plugin_dir_of(path), **common)


def _resolve_base(git, top, hist, base, manifest_rel, common):
    by_version = [h for h in hist if h[2] == base]
    if by_version:
        sha, path, version, name = by_version[-1]
        return Resolution(degraded=False, commit=sha, version=version, name=name,
                          path_in_repo=_plugin_dir_of(path), **common)
    proc = _run(git, top, 'rev-parse', '--verify', '-q', base + '^{commit}')
    if proc.returncode != 0:
        raise BaseNotFound('--base %s 既不是被测插件历史里出现过的版本号，也不是能解析的提交' % base)
    sha = proc.stdout.strip()
    # 该提交里 plugin.json 在哪：取 follow 序列里第一个是它祖先（或就是它）的提交当时的路径
    path = None
    for h_sha, h_path, _, _ in hist:
        if h_sha == sha or _run(git, top, 'merge-base', '--is-ancestor', h_sha, sha).returncode == 0:
            path = h_path
            break
    data = _manifest_at(git, top, sha, path) if path else None
    if data is None:
        raise BaseNotFound('--base %s（%s）里找不到被测插件的 plugin.json（追踪路径 %s）' % (base, sha[:12], manifest_rel))
    return Resolution(degraded=False, commit=sha, version=data.get('version'), name=data.get('name'),
                      path_in_repo=_plugin_dir_of(path), **common)


def _safe_extract(tf, dest):
    if hasattr(tarfile, 'data_filter'):
        tf.extractall(dest, filter='data')
        return
    root = Path(dest).resolve()
    for m in tf.getmembers():
        target = (root / m.name).resolve()
        if root != target and root not in target.parents:
            raise SnapshotError('快照里有越出目标目录的条目：%s' % m.name)
        if m.issym() or m.islnk():
            link = (target.parent / m.linkname).resolve()
            if root != link and root not in link.parents:
                raise SnapshotError('快照里有指向目录外的链接：%s → %s' % (m.name, m.linkname))
    tf.extractall(dest)


def snapshot(res, dest):
    """`git archive <提交> <插件路径>` 解到 dest，返回快照里的插件目录。失败抛 SnapshotError。"""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    args = ['archive', '--format=tar', res.commit] + ([] if res.path_in_repo == '.' else [res.path_in_repo])
    proc = _run(res.git, res.toplevel, *args, binary=True)
    if proc.returncode != 0:
        raise SnapshotError('git archive %s %s 失败：%s' % (
            res.commit[:12], res.path_in_repo, proc.stderr.decode('utf-8', 'replace').strip()))
    try:
        with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tf:
            _safe_extract(tf, dest)
    except (tarfile.TarError, OSError) as e:
        raise SnapshotError('解包快照失败：%s' % e)
    plugin_dir = dest if res.path_in_repo == '.' else dest / res.path_in_repo
    if not (plugin_dir / MANIFEST_REL).is_file():
        raise SnapshotError('快照里没有 %s/%s' % (res.path_in_repo, MANIFEST_REL))
    return plugin_dir


_GRADERS_KEY = re.compile(r'^graders\s*:')
_TOP_KEY = re.compile(r'^[A-Za-z_][\w-]*\s*:')


def _case_yaml_graders(text):
    """case.yaml 里 graders: 段的文字（顶层下一个键之前）。不解析 YAML，只按缩进切段。"""
    out, inside = [], False
    for line in text.splitlines():
        if _GRADERS_KEY.match(line):
            inside = True
        elif inside and _TOP_KEY.match(line):
            inside = False
        if inside:
            out.append(line)
    return '\n'.join(out)


def cases_naming_skills(evals_dir, cases, plugin_names):
    """判分规则里写了 `<插件名>:<skill>` 全名的用例 → 命中的全名（排序去重）。

    跨改名时 skill 全名在两臂里不同，这些用例跨臂不可比。只看判分规则：graders/*.md 与 case.yaml 的 graders 段；
    prompt 里提到全名不影响判分，不算。
    """
    names = sorted({n for n in plugin_names if n}, key=len, reverse=True)
    if not names:
        return {}
    pat = re.compile(r'(?<![\w.-])(?:%s):[A-Za-z0-9_][A-Za-z0-9_-]*' % '|'.join(re.escape(n) for n in names))
    found = {}
    for case in cases:
        d = Path(evals_dir) / case
        texts = []
        gdir = d / 'graders'
        if gdir.is_dir():
            texts += [p.read_text(encoding='utf-8', errors='replace') for p in sorted(gdir.glob('*.md'))]
        if (d / 'case.yaml').is_file():
            texts.append(_case_yaml_graders((d / 'case.yaml').read_text(encoding='utf-8', errors='replace')))
        hits = sorted({m.group(0) for t in texts for m in pat.finditer(t)})
        if hits:
            found[case] = hits
    return found
