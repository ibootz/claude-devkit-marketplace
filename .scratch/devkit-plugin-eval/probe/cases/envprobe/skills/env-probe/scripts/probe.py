"""探针：打印本进程看到的插件相关环境变量与命令行参数。

判读：
- env.* 是进程环境变量，<unset> 表示 Bash 工具没有导出它。
- sq-* 是单引号参数：值为路径说明 Claude Code 在 skill 文本里做了替换；
  值仍是字面量 ${...} 说明没替换。
- dq-* 是双引号参数：替换或 shell 展开二者之一生效即为路径。
"""
import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

parser = argparse.ArgumentParser()
for flag in ("--dq-data", "--sq-data", "--dq-root", "--sq-root"):
    parser.add_argument(flag, default="<missing>")
args = parser.parse_args()

for key in ("CLAUDE_PLUGIN_DATA", "CLAUDE_PLUGIN_ROOT", "CLAUDE_SKILL_DIR", "CLAUDE_PROJECT_DIR"):
    print(f"PROBE env.{key}={os.environ.get(key, '<unset>')}")
for name in ("dq_data", "sq_data", "dq_root", "sq_root"):
    print(f"PROBE arg.{name}={getattr(args, name)!r}")
print(f"PROBE file={os.path.abspath(__file__)}")
data = args.sq_data if not args.sq_data.startswith("${") else os.environ.get("CLAUDE_PLUGIN_DATA", "")
print(f"PROBE data_dir_exists={bool(data) and os.path.isdir(data)}")
