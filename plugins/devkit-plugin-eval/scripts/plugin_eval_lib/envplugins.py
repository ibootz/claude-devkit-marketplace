"""环境插件臂：解析入参、把环境插件拷进臂组装目录、给每个用例写 plugins 字段。

入参两种（spec「2.2 离线对照」第 3 步）：
- `插件名@市场`：按 `<配置目录>/plugins/installed_plugins.json` 的 installPath 取本机当前版。同一 id 可能有
  user / project / local 多条安装记录：有 user 范围的取它，否则取 lastUpdated 最新的一条。
- 路径：该目录须有 `.claude-plugin/plugin.json`。

为什么要改写用例（2.1.300 二进制实测）：eval 没有加载额外插件的命令行参数，额外插件只能写在用例的 `plugins`
字段；写了 `plugins` 就只加载所列目录（不再自动带上被测插件），且所列目录必须在 containment root 内——target
本身就是插件时，containment root 就是 target 目录。所以环境插件拷进臂组装目录（= target）下的 ENV_DIR/<name>/，
每个用例的 `plugins` 写「臂组装目录本身 + 各环境插件目录」两类相对路径。prompt.md frontmatter 的顶层键覆盖
case.yaml 的同名键，所以有 prompt.md 就写进它的 frontmatter，否则追加到 case.yaml 末尾。
用例自己已声明 `plugins` 的不改动，返回给调用方写进报告：它在环境插件臂里不会加载环境插件。
"""
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import arms

ENV_DIR = '_plugin_eval_env'
COPY_EXCLUDE = ('.in_use', 'evals', '.git')     # .in_use/<pid> 是缓存目录里的运行时文件
_ID_RE = re.compile(r'[^@/\\\s]+@[^@/\\\s]+')
_PLUGINS_KEY = re.compile(r'^plugins\s*:')


class EnvPluginError(Exception):
    pass


@dataclass(frozen=True)
class EnvPlugin:
    spec: str                              # 用户原样传入的入参
    source: str                            # installed / path
    dir: Path
    name: str
    version: Optional[str]
    git_commit_sha: Optional[str] = None   # installed：刷新那一刻市场仓的 HEAD（不是版本引入提交）；path：所在 git 仓的 HEAD
    scope: Optional[str] = None            # installed 时取的是哪个安装范围
    plugin_id: Optional[str] = None

    def record(self):
        return {'spec': self.spec, 'source': self.source, 'plugin_id': self.plugin_id, 'name': self.name,
                'version': self.version, 'git_commit_sha': self.git_commit_sha, 'scope': self.scope,
                'path': str(self.dir)}


def config_dir(env=None):
    env = os.environ if env is None else env
    return Path(env['CLAUDE_CONFIG_DIR']).expanduser() if env.get('CLAUDE_CONFIG_DIR') else Path.home() / '.claude'


def _read_manifest(d):
    p = Path(d) / '.claude-plugin' / 'plugin.json'
    if not p.is_file():
        raise EnvPluginError('%s 下没有 .claude-plugin/plugin.json，不是插件目录' % d)
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except ValueError as e:
        raise EnvPluginError('%s 不是合法 JSON：%s' % (p, e))
    if not data.get('name'):
        raise EnvPluginError('%s 没有 name' % p)
    return data


def _git_head(d, git=None):
    git = shutil.which('git') if git is None else git
    if not git:
        return None
    proc = subprocess.run([git, '-C', str(d), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _pick_install(records):
    users = [r for r in records if r.get('scope') == 'user']
    pool = users or records
    return max(pool, key=lambda r: r.get('lastUpdated') or '')


def resolve(spec, *, env=None):
    path = Path(spec).expanduser()
    if _ID_RE.fullmatch(spec) and not path.exists():
        return _resolve_installed(spec, env)
    if not path.is_dir():
        raise EnvPluginError('环境插件 %r 既不是存在的目录，也不是「插件名@市场」形态' % spec)
    d = path.resolve()
    data = _read_manifest(d)
    return EnvPlugin(spec=spec, source='path', dir=d, name=data['name'], version=data.get('version'),
                     git_commit_sha=_git_head(d))


def _resolve_installed(spec, env):
    reg = config_dir(env) / 'plugins' / 'installed_plugins.json'
    if not reg.is_file():
        raise EnvPluginError('找不到 %s，无法按「插件名@市场」取环境插件；改传插件目录路径' % reg)
    try:
        data = json.loads(reg.read_text(encoding='utf-8'))
    except ValueError as e:
        raise EnvPluginError('%s 不是合法 JSON：%s' % (reg, e))
    records = [r for r in (data.get('plugins') or {}).get(spec) or [] if isinstance(r, dict) and r.get('installPath')]
    if not records:
        raise EnvPluginError('%s 里没有已安装的 %s（用 `claude plugin list` 查 id，或改传插件目录路径）' % (reg, spec))
    rec = _pick_install(records)
    d = Path(rec['installPath']).expanduser()
    if not d.is_dir():
        raise EnvPluginError('%s 的安装目录不存在：%s' % (spec, d))
    d = d.resolve()
    manifest = _read_manifest(d)
    return EnvPlugin(spec=spec, source='installed', dir=d, name=manifest['name'],
                     version=rec.get('version') or manifest.get('version'),
                     git_commit_sha=rec.get('gitCommitSha'), scope=rec.get('scope'), plugin_id=spec)


def check_set(env_plugins, tested_name):
    seen = set()
    for ep in env_plugins:
        if ep.name == tested_name:
            raise EnvPluginError('环境插件 %s（%s）与被测插件同名；环境插件只放被测插件以外的插件' % (ep.name, ep.spec))
        if ep.name in seen:
            raise EnvPluginError('环境插件 %s 传了不止一次' % ep.name)
        seen.add(ep.name)


def _has_plugins_key(lines):
    return any(_PLUGINS_KEY.match(ln) for ln in lines)


def _add_plugins_field(case_dir, entries):
    """给一个用例写 plugins 字段。用例已声明 plugins 时不动、返回 False。"""
    line = 'plugins: ' + json.dumps(entries, ensure_ascii=False)
    pm, cy = case_dir / 'prompt.md', case_dir / 'case.yaml'
    if cy.is_file():
        cy_text = cy.read_text(encoding='utf-8')
        if _has_plugins_key(cy_text.splitlines()):
            return False
    if pm.is_file():
        text = pm.read_text(encoding='utf-8')
        bom = '﻿' if text.startswith('﻿') else ''
        body = text[len(bom):]
        nl = '\r\n' if '\r\n' in body else '\n'
        lines = body.splitlines(keepends=True)
        if lines and lines[0].strip() == '---':
            close = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
            if close is not None:
                if _has_plugins_key(lines[1:close]):
                    return False
                lines.insert(close, line + nl)
                pm.write_text(bom + ''.join(lines), encoding='utf-8')
                return True
        pm.write_text(bom + '---' + nl + line + nl + '---' + nl + body, encoding='utf-8')
        return True
    sep = '' if not cy_text or cy_text.endswith('\n') else '\n'
    cy.write_text(cy_text + sep + line + '\n', encoding='utf-8')
    return True


def install(arm_dir, env_plugins):
    """把环境插件拷进 <arm_dir>/ENV_DIR/<name>/，给 evals/ 下每个用例写 plugins。返回未改写（自带 plugins）的用例。"""
    arm_dir = Path(arm_dir)
    base = arm_dir / ENV_DIR
    if base.exists():
        raise EnvPluginError('被测插件顶层已有 %s/，与环境插件存放目录重名' % ENV_DIR)
    targets = []
    for ep in env_plugins:
        src = Path(ep.dir)
        dest = base / ep.name

        def ignore(dirpath, names, src=src):
            return [n for n in names if Path(dirpath) == src and n in COPY_EXCLUDE]
        arms.copy_tree(src, dest, ignore=ignore)
        targets.append(dest)
    evals = arm_dir / 'evals'
    skipped = []
    for case in arms.discover_cases(evals):
        case_dir = evals / case
        entries = [Path(os.path.relpath(t, case_dir)).as_posix() for t in [arm_dir] + targets]
        if not _add_plugins_field(case_dir, entries):
            skipped.append(case)
    return skipped
