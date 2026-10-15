"""用户级数据目录：放 registry.json 与全量 trace 缓存 traces/。

取值顺序：
1. 命令行 --data-dir（SKILL.md 里写 `--data-dir "${CLAUDE_PLUGIN_DATA}"`，加载时被替换成绝对路径）；
2. 环境变量 CLAUDE_PLUGIN_DATA（Bash 工具调起的进程里拿不到，见票 01 报告第四节，留作兼容）；
3. 按本脚本路径推：marketplace 安装的插件在
   `<配置目录>/plugins/cache/<marketplace>/<plugin>/<version>/...`，数据目录是
   `<配置目录>/plugins/data/<plugin>-<marketplace>/`，id 里字母、数字、`_`、`-` 以外的字符换成 `-`。
推不出来（如从源码仓直接跑、或 --plugin-dir 加载）就报错，要求显式传 --data-dir。
"""
import os
import re
from pathlib import Path


class DataDirError(Exception):
    pass


def _sanitize(plugin_id):
    return re.sub(r'[^A-Za-z0-9_-]', '-', plugin_id)


def derive_from_script_path(script_path):
    parts = Path(script_path).resolve().parts if Path(script_path).exists() else Path(script_path).parts
    for i in range(len(parts) - 3):
        if parts[i] == 'plugins' and parts[i + 1] == 'cache':
            marketplace, plugin = parts[i + 2], parts[i + 3]
            config_root = Path(*parts[:i]) if i else Path(parts[0])
            return config_root / 'plugins' / 'data' / _sanitize('%s-%s' % (plugin, marketplace))
    return None


def resolve_data_dir(cli_value, env=None, script_path=None):
    env = os.environ if env is None else env
    if cli_value:
        return Path(cli_value).expanduser().resolve()
    if env.get('CLAUDE_PLUGIN_DATA'):
        return Path(env['CLAUDE_PLUGIN_DATA'])
    derived = derive_from_script_path(script_path or __file__)
    if derived is not None:
        return derived
    raise DataDirError(
        '推不出用户级数据目录：本脚本不在 <配置目录>/plugins/cache/<marketplace>/<plugin>/<version>/ 下。'
        '请用 --data-dir 显式传入（skill 里写 --data-dir "${CLAUDE_PLUGIN_DATA}"）。')
