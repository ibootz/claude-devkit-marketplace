"""命令行：register / list / compare。

退出码：0 成功；2 用法、登记、环境类错误（含未登记）；3 对照跑完但结果不完整（用例加载失败、run 出错等）。
"""
import argparse
import json
import sys

from . import compare, datadir, evalrun, registry


def _utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure:
            reconfigure(encoding='utf-8')


def _parser():
    p = argparse.ArgumentParser(prog='plugin_eval.py', description='devkit-plugin-eval：Claude Code 插件离线对照')
    p.add_argument('--data-dir', help='用户级数据目录（registry.json 与 traces/）；skill 里传 "${CLAUDE_PLUGIN_DATA}"')
    sub = p.add_subparsers(dest='cmd', required=True)

    r = sub.add_parser('register', help='登记被测插件（登记即信任声明）')
    r.add_argument('name', help='插件名，须与 plugin.json 的 name 一致')
    r.add_argument('--repo', required=True, help='被测插件所在仓的根目录')

    sub.add_parser('list', help='列出已登记插件')

    c = sub.add_parser('compare', help='跑一次离线对照：「不装」与「当前版」两臂')
    c.add_argument('name')
    c.add_argument('--runs', type=int, default=3, help='每例每臂次数，默认 3')
    c.add_argument('-j', '--concurrency', type=int, default=3, help='eval 并发数（1-8），默认 3')
    c.add_argument('--model', help='覆盖被测模型（传给 eval --model）')
    c.add_argument('--threshold', type=float, default=1.0, help='判「是否通过」的用例分阈值，默认 1.0')
    c.add_argument('--keep-assembly', action='store_true', help='保留臂组装目录（排查用）')
    return p


def main(argv=None):
    _utf8_stdio()
    args = _parser().parse_args(argv)
    try:
        data_dir = datadir.resolve_data_dir(args.data_dir)
        if args.cmd == 'register':
            entry = registry.register(data_dir, args.name, args.repo)
            print('已登记 %s：仓 %s，插件路径 %s' % (args.name, entry['repo'], entry['plugin_path']))
            print('登记清单：%s' % (data_dir / 'registry.json'))
            return 0
        if args.cmd == 'list':
            print(json.dumps(registry.load(data_dir)['plugins'], ensure_ascii=False, indent=2))
            return 0
        res = compare.run_compare(data_dir, args.name, runs=args.runs, concurrency=args.concurrency,
                                  model=args.model, threshold=args.threshold, keep_assembly=args.keep_assembly)
    except (registry.RegistryError, datadir.DataDirError, evalrun.ClaudeNotFound, compare.CompareError) as e:
        print('错误：%s' % e, file=sys.stderr)
        return 2

    rec = res.record
    fmt = lambda x: '—' if x is None else '%.2f' % x
    print('运行目录：%s' % res.run_dir)
    print('不装 %s / 当前版 %s / 差 %s' % (fmt(rec['arms']['none']['score']), fmt(rec['arms']['current']['score']),
                                     '—' if rec['delta']['overall'] is None else '%+.2f' % rec['delta']['overall']))
    print('完整：%s；状态：%s；花费（标价估算）：$%.4f' % ('是' if rec['complete'] else '否', rec['review']['status'],
                                                rec['usage']['cost_usd']))
    for r in rec['incomplete_reasons']:
        print('  不完整原因：%s' % r)
    return res.exit_code
