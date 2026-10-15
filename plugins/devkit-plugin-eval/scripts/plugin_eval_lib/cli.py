"""命令行：register / list / compare。

退出码：0 成功；2 用法、登记、环境类错误（含未登记）；3 对照跑完但结果不完整（用例加载失败、run 出错等）。
"""
import argparse
import json
import sys

from . import armplan, compare, datadir, evalrun, registry


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

    c = sub.add_parser('compare', help='跑一次离线对照：不装、上一版（取得到才跑）、当前版，可加环境插件臂')
    c.add_argument('name')
    c.add_argument('--runs', type=int, default=3, help='每例每臂次数，默认 3')
    c.add_argument('-j', '--concurrency', type=int, default=3, help='eval 并发数（1-8），默认 3')
    c.add_argument('--model', help='覆盖被测模型（传给 eval --model）')
    c.add_argument('--threshold', type=float, default=1.0, help='判「是否通过」的用例分阈值，默认 1.0')
    c.add_argument('--keep-assembly', action='store_true', help='保留臂组装目录（排查用）')
    c.add_argument('--base', metavar='提交|版本号',
                   help='上一版改用这个提交或版本号（版本号取它的引入提交）；缺省自动认定')
    c.add_argument('--env-plugin', action='append', default=[], metavar='插件名@市场|路径',
                   help='加一个「当前版+环境插件」臂；可重复，多个环境插件同装在这一个臂里')
    return p


def _print_extra_arms(rec, fmt):
    pa = rec.get('previous_arm') or {}
    if pa.get('degraded'):
        print('上一版臂已退化：%s' % pa.get('reason'))
    elif rec['arms'].get('previous'):
        d = rec['delta_vs_previous']['overall']
        print('上一版 %s（%s）%s / 差（当前版 − 上一版）%s%s' % (
            pa.get('version'), (pa.get('commit') or '')[:12], fmt(rec['arms']['previous']['score']),
            '—' if d is None else '%+.2f' % d, '；跨改名' if pa.get('cross_rename') else ''))
    env = rec['arms'].get('current_with_env')
    if env:
        print('当前版+环境插件（%s）%s' % ('、'.join(e['name'] for e in env.get('env_plugins', [])), fmt(env['score'])))


def main(argv=None):
    _utf8_stdio()
    args = _parser().parse_args(argv)
    try:
        data_dir = datadir.resolve_data_dir(args.data_dir)
        if args.cmd == 'register':
            entry = registry.register(data_dir, args.name, args.repo)
            print('已登记 %s：仓 %s，插件路径 %s' % (args.name, entry['repo'], entry['plugin_path']))
            print('登记清单：%s' % (data_dir / 'registry.json'))
            print(registry.TRUST_SCOPE)
            return 0
        if args.cmd == 'list':
            print(json.dumps(registry.load(data_dir)['plugins'], ensure_ascii=False, indent=2))
            return 0
        res = compare.run_compare(data_dir, args.name, runs=args.runs, concurrency=args.concurrency,
                                  model=args.model, threshold=args.threshold, keep_assembly=args.keep_assembly,
                                  base=args.base, env_plugins=args.env_plugin)
    except (registry.RegistryError, datadir.DataDirError, evalrun.ClaudeNotFound, compare.CompareError,
            armplan.ArmSourceError) as e:
        print('错误：%s' % e, file=sys.stderr)
        return 2

    rec = res.record
    fmt = lambda x: '—' if x is None else '%.2f' % x
    print('运行目录：%s' % res.run_dir)
    print('不装 %s / 当前版 %s / 差 %s' % (fmt(rec['arms']['none']['score']), fmt(rec['arms']['current']['score']),
                                     '—' if rec['delta']['overall'] is None else '%+.2f' % rec['delta']['overall']))
    _print_extra_arms(rec, fmt)
    print('完整：%s；状态：%s；花费（标价估算）：$%.4f' % ('是' if rec['complete'] else '否', rec['review']['status'],
                                                rec['usage']['cost_usd']))
    for r in rec['incomplete_reasons']:
        print('  不完整原因：%s' % r)
    return res.exit_code
