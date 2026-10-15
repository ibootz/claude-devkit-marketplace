"""被测插件登记清单 <数据目录>/registry.json。

登记即信任声明：只有登记过的插件，compare 才会给 eval 加 --trust-plugin（及 --scaffold）。
文件形态：
{
  "schema_version": 1,
  "plugins": {
    "<插件名>": {"repo": "<仓根绝对路径>", "plugin_path": "plugins/<插件名>" 或 ".", "registered_at": "<UTC ISO>"}
  }
}
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


class RegistryError(Exception):
    pass


class NotRegistered(RegistryError):
    pass


def _registry_path(data_dir):
    return Path(data_dir) / 'registry.json'


def load(data_dir):
    p = _registry_path(data_dir)
    if not p.exists():
        return {'schema_version': SCHEMA_VERSION, 'plugins': {}}
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except ValueError as e:
        raise RegistryError('%s 不是合法 JSON：%s' % (p, e))
    data.setdefault('plugins', {})
    return data


def _save(data_dir, data):
    p = _registry_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, p)


def _manifest_name(plugin_dir):
    manifest = plugin_dir / '.claude-plugin' / 'plugin.json'
    if not manifest.is_file():
        return None
    try:
        return json.loads(manifest.read_text(encoding='utf-8')).get('name')
    except ValueError:
        return None


def locate_plugin(repo, name):
    """在仓里找插件目录：先 plugins/<name>/，再仓根本身。返回相对仓根的 posix 路径。"""
    repo = Path(repo)
    for rel in ('plugins/' + name, '.'):
        d = repo / rel
        found = _manifest_name(d)
        if found == name:
            return rel
        if found is not None and rel != '.':
            raise RegistryError('%s/.claude-plugin/plugin.json 的 name 是 %r，与登记名 %r 不一致' % (d, found, name))
    raise RegistryError('在 %s 下找不到插件 %r：既没有 plugins/%s/.claude-plugin/plugin.json，'
                        '仓根的 plugin.json 也不是这个名字' % (repo, name, name))


def register(data_dir, name, repo):
    repo = Path(repo).expanduser().resolve()
    if not repo.is_dir():
        raise RegistryError('仓路径不存在：%s' % repo)
    rel = locate_plugin(repo, name)
    data = load(data_dir)
    entry = {'repo': str(repo), 'plugin_path': rel,
             'registered_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    data['plugins'][name] = entry
    data['schema_version'] = SCHEMA_VERSION
    _save(data_dir, data)
    return dict(entry, name=name)


def lookup(data_dir, name):
    entry = load(data_dir)['plugins'].get(name)
    if entry is None:
        raise NotRegistered(
            '插件 %s 未登记，拒绝跑对照。登记即声明信任它的代码与用例，先运行：\n'
            '  python3 plugin_eval.py register %s --repo <被测插件所在仓的根目录>' % (name, name))
    return dict(entry, name=name)


def plugin_dir(entry):
    return (Path(entry['repo']) / entry['plugin_path']).resolve()
