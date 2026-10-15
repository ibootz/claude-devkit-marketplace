"""devkit-plugin-eval 命令行入口。

用法（Windows 把 python3 换成 python 或 py -3）：
  python3 plugin_eval.py --data-dir <数据目录> register <插件名> --repo <被测插件所在仓根>
  python3 plugin_eval.py --data-dir <数据目录> compare <插件名> [--runs 3] [-j 3] [--eval-timeout <分钟>]
  python3 plugin_eval.py --data-dir <数据目录> resume <运行目录>    # 续跑不完整的对照，只补跑判无效与未跑的 run
  python3 plugin_eval.py --data-dir <数据目录> pending <插件名> [--run <运行 id>] [--reply '<回复码>']
  python3 plugin_eval.py --data-dir <数据目录> clauses <插件名>          # 首次抽条款清单（已有清单时拒绝，改跑 compare）
  python3 plugin_eval.py --data-dir <数据目录> review [--days 30]           # 会话复盘，覆盖全部已登记插件
  python3 plugin_eval.py --data-dir <数据目录> pending <插件名> --review [<日期>]   # 复盘待审页
  python3 plugin_eval.py gate <插件目录> [--main-ref origin/main] [--json]   # 发版闸门：0 过闸、1 未过闸
从 marketplace 安装位置运行时可省略 --data-dir，按脚本路径推出 ~/.claude/plugins/data/<plugin>-<marketplace>/。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plugin_eval_lib.cli import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
