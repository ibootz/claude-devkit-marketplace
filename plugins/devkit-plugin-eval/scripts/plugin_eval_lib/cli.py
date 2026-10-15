"""命令行：register / list / check / compare / resume / pending / clauses / review / gate / drafts / baseline。

退出码：0 成功；2 用法、登记、环境类错误（含未登记、前置检查硬项失败）；3 对照跑完但结果不完整（用例加载失败、run 出错等）。
gate 另用 1 表示未过闸。
"""
import argparse
import json
import sys

from . import armplan, baseline, clauses, compare, datadir, drafts, evalrun, gate, judge, judgereport, pending, preflight, \
    registry, resume, review


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

    k = sub.add_parser('check', help='单跑前置检查（compare 开跑前也自动执行）；硬项失败退出码 2')
    k.add_argument('name', nargs='?', help='被测插件名：查离线对照前的各项')
    k.add_argument('--model', help='compare 打算传的 --model（顺带查 eval 支不支持该参数）')
    k.add_argument('--review', action='store_true', help='查会话复盘前的各项')
    k.add_argument('--judge', action='store_true', help='与 --review 同用：本次要调 AI 评委，加查登录态')
    k.add_argument('--base', metavar='提交|版本号', help='同 compare --base：冒烟与 validate 覆盖这一版快照')
    k.add_argument('--env-plugin', action='append', default=[], metavar='插件名@市场|路径',
                   help='同 compare --env-plugin：冒烟、validate 与 containment 覆盖这些环境插件')

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
    c.add_argument('--eval-timeout', type=float, default=0, help='每次调 eval 的超时（分钟），超时终止并记为不完整、可续跑；默认 0 不限时')
    c.add_argument('--clause-model', help='条款清单过期时抽取用的模型，缺省 %s' % clauses.clause_ai.DEFAULT_MODEL)
    c.add_argument('--judge-model', help='AI 评委模型；缺省取 plugin-evals/<插件>/judge-config.json 的 model，再缺省 %s'
                   % judge.DEFAULT_MODEL)
    c.add_argument('--no-judge', action='store_true', help='本次不调 AI 评委（用例里的 judge/ 判定标准不判）')

    rs = sub.add_parser('resume', help='续跑一次不完整的对照：已完成的 run 不重跑，只补跑判无效与未跑的 run')
    rs.add_argument('run_dir', help='运行目录：<仓>/plugin-evals/<插件>/runs/<run_id>')
    rs.add_argument('--keep-assembly', action='store_true', help='保留臂组装目录（排查用）')
    rs.add_argument('--eval-timeout', type=float, default=0, help='同 compare --eval-timeout')

    pending.add_parser(sub)

    g = sub.add_parser('gate', help='发版闸门：判当前版本能否发布（退出码 0 过闸、1 未过闸、2 用法错误）；推 main 前手动跑')
    g.add_argument('plugin_dir', help='被测插件目录（含 .claude-plugin/plugin.json）；不要求已登记')
    g.add_argument('--main-ref', help='查漏检用的 main 分支引用；缺省依次试 origin/main、main、origin/master、master')
    g.add_argument('--since', metavar='提交', help='漏检起算的提交；缺省取 main 上首次入库 plugin-evals/<插件名>/ 的提交')
    g.add_argument('--json', action='store_true', help='输出结构化结果')

    clauses.add_parser(sub)
    review.add_parser(sub)
    drafts.add_parser(sub)       # 用例草稿（票 11）
    baseline.add_parser(sub)     # 基线已满足判定（票 11）
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


def _check_compare(args, data_dir):
    """与 compare 开跑前同一套臂计划：上一版快照（--base 或自动认定）与 --env-plugin 都进冒烟、validate、containment。
    未登记时不建计划，交给 check_compare 报「已登记」不通过；其余目标错误（无用例、--base 解析不到等）照 compare 中止。"""
    log = lambda msg: print(msg, file=sys.stderr)
    try:
        entry, plugin_dir, manifest, evals_src, cases, extra_exclude = compare.load_target(data_dir, args.name)
    except registry.NotRegistered:
        return preflight.check_compare(data_dir=data_dir, name=args.name, env=evalrun.child_env(),
                                       model=args.model, soft=True)
    plan = compare.plan_for(plugin_dir, args.name, manifest, cases, evals_src, extra_exclude, base=args.base,
                            env_plugins=args.env_plugin, log=log)
    try:
        return preflight.check_compare(data_dir=data_dir, name=args.name, env=evalrun.child_env(), model=args.model,
                                       others=plan.preflight_targets(), env_plugins=plan.env_plugins, soft=True)
    finally:
        plan.cleanup()


def _check(args, data_dir):
    if not args.name and not args.review:
        print('错误：check 要给被测插件名（查离线对照前的各项），或 --review（查会话复盘前的各项）', file=sys.stderr)
        return 2
    reports = []
    if args.name:
        reports.append(_check_compare(args, data_dir))
    if args.review:
        reports.append(preflight.check_review(data_dir=data_dir, env=evalrun.child_env(), need_judge=args.judge))
    for rep in reports:
        print(rep.render())
    return 0 if all(r.passed for r in reports) else 2


def main(argv=None):
    _utf8_stdio()
    args = _parser().parse_args(argv)
    if args.cmd == 'gate':           # 只读插件目录与仓内 runs/，不用用户级数据目录
        return gate.main(args)
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
        if args.cmd == 'check':      # check、pending 没有 --eval-timeout，要排在读它之前
            return _check(args, data_dir)
        if args.cmd == 'pending':
            return pending.main(args, data_dir)
        if args.cmd == 'clauses':
            return clauses.main(args, data_dir)
        if args.cmd == 'review':
            return review.main(args, data_dir)
        if args.cmd == 'drafts':
            return drafts.main(args, data_dir)
        if args.cmd == 'baseline':
            return baseline.main(args, data_dir)
        runner = evalrun.runner_with_timeout(args.eval_timeout * 60 if args.eval_timeout else None)
        if args.cmd == 'resume':
            res = resume.resume_run(data_dir, args.run_dir, runner=runner, keep_assembly=args.keep_assembly)
        else:
            res = compare.run_compare(data_dir, args.name, runs=args.runs, concurrency=args.concurrency,
                                      model=args.model, threshold=args.threshold, keep_assembly=args.keep_assembly,
                                      base=args.base, env_plugins=args.env_plugin, runner=runner,
                                      clause_model=args.clause_model,
                                      judge_model=args.judge_model, use_judge=not args.no_judge)
    except (registry.RegistryError, datadir.DataDirError, evalrun.ClaudeNotFound, compare.CompareError,
            armplan.ArmSourceError, preflight.PreflightFailed, resume.ResumeError, judge.JudgeConfigError) as e:
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
    line = judgereport.console_line(rec.get('judge'))
    if line:
        print(line)
    for r in rec['incomplete_reasons']:
        print('  不完整原因：%s' % r)
    if not rec['complete']:
        print('续跑（已完成的 run 不重跑，只补跑判无效与未跑的 run）：%s' % resume.resume_hint(res.run_dir, data_dir))
    return res.exit_code
