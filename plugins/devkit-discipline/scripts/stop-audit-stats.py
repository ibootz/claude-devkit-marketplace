#!/usr/bin/env python3
"""回合末审查（hooks/stop-audit.js）的运行统计：按判定路径汇总成功、失败次数与耗时。

读 stop-audit.js 写的日志（默认 $TMPDIR/devkit-stop-audit.log，连同轮转出的 .1 一起读），
输出三张表：
  1. 每条判定路径（third-party 第三方 / fallback 第三方失败后回落订阅 / subscription 订阅）
     的成功、失败次数，成功率，成功判定的平均、中位、P90 耗时；
  2. 失败原因分布（timeout 超时、exit-nonzero 退出码非 0、no-structured-output 没有结构化输出、
     bad-verdict-text 文字判定解析不了、no-budget 预算用完没回落 等）；
  3. 整次审查（kind=run）按「是否开第三方」分组的次数、打回次数与平均、P90 耗时。

用法：
  python3 stop-audit-stats.py                 # 全部记录
  python3 stop-audit-stats.py --days 3        # 只看最近 3 天
  python3 stop-audit-stats.py --log /path/to/devkit-stop-audit.log
  python3 stop-audit-stats.py --json          # 输出 JSON，便于再加工
Windows 上把 python3 换成 python 或 py -3。

4.19.0 之前只记失败、不记成功，混进来会把成功率算低；所以默认只统计带 audit 字段的行与 kind=run 行
（4.19.0 起的格式），--all 才把旧行一起算。
"""
import argparse
import datetime as dt
import json
import os
import statistics
import sys
import tempfile
from collections import Counter, defaultdict

ROUTES = ('third-party', 'fallback', 'subscription')


def default_log():
    return os.environ.get('DEVKIT_STOP_AUDIT_LOG') or os.path.join(tempfile.gettempdir(), 'devkit-stop-audit.log')


def read_rows(log, since, include_legacy=False):
    rows = []
    for f in (log + '.1', log):
        try:
            with open(f, encoding='utf-8') as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if not include_legacy and r.get('kind') != 'run' and 'audit' not in r:
                        continue
                    if since:
                        try:
                            at = dt.datetime.fromisoformat(str(r.get('at', '')).replace('Z', '+00:00'))
                        except ValueError:
                            continue
                        if at < since:
                            continue
                    rows.append(r)
        except OSError:
            pass
    return rows


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))]


def sec(ms):
    return '-' if ms is None else f'{ms / 1000:.1f}s'


def summarize(rows):
    by_route = defaultdict(lambda: {'ok': 0, 'fail': 0, 'ok_ms': [], 'fail_kinds': Counter()})
    runs = defaultdict(lambda: {'n': 0, 'blocked': 0, 'ms': []})
    first = last = None
    for r in rows:
        at = r.get('at')
        if at:
            first = at if first is None or at < first else first
            last = at if last is None or at > last else last
        kind = r.get('kind')
        if kind == 'run':
            g = runs['third-party on' if r.get('thirdParty') else 'third-party off']
            g['n'] += 1
            g['blocked'] += 1 if r.get('blocked') else 0
            if isinstance(r.get('ms'), (int, float)):
                g['ms'].append(r['ms'])
            continue
        route = r.get('route') or 'subscription'  # 旧失败行没有 route，那时只有订阅路
        g = by_route[route]
        if kind == 'ok':
            g['ok'] += 1
            if isinstance(r.get('ms'), (int, float)):
                g['ok_ms'].append(r['ms'])
        else:
            g['fail'] += 1
            g['fail_kinds'][kind] += 1
    out = {'range': [first, last], 'routes': {}, 'runs': {}}
    for route in list(ROUTES) + sorted(k for k in by_route if k not in ROUTES):
        if route not in by_route:
            continue
        g = by_route[route]
        n = g['ok'] + g['fail']
        ms = g['ok_ms']
        out['routes'][route] = {
            'total': n, 'ok': g['ok'], 'fail': g['fail'],
            'ok_rate': round(g['ok'] / n, 3) if n else None,
            'avg_ms': round(statistics.mean(ms)) if ms else None,
            'median_ms': round(statistics.median(ms)) if ms else None,
            'p90_ms': pct(ms, 0.9),
            'fail_kinds': dict(g['fail_kinds'].most_common()),
        }
    for k, g in sorted(runs.items()):
        out['runs'][k] = {
            'n': g['n'], 'blocked': g['blocked'],
            'avg_ms': round(statistics.mean(g['ms'])) if g['ms'] else None,
            'p90_ms': pct(g['ms'], 0.9),
        }
    return out


def print_table(s, log):
    print(f'日志：{log}（连同 .1）')
    print(f'时间范围：{s["range"][0] or "-"} ～ {s["range"][1] or "-"}（UTC）')
    print()
    print('| 判定路径 | 总次数 | 成功 | 失败 | 成功率 | 成功平均耗时 | 中位 | P90 | 失败原因 |')
    print('|---|---|---|---|---|---|---|---|---|')
    names = {'third-party': '第三方', 'fallback': '回落订阅', 'subscription': '订阅'}
    for route, g in s['routes'].items():
        rate = '-' if g['ok_rate'] is None else f'{g["ok_rate"] * 100:.1f}%'
        kinds = '、'.join(f'{k} {v}' for k, v in g['fail_kinds'].items()) or '-'
        print(f'| {names.get(route, route)}（{route}） | {g["total"]} | {g["ok"]} | {g["fail"]} | {rate} | '
              f'{sec(g["avg_ms"])} | {sec(g["median_ms"])} | {sec(g["p90_ms"])} | {kinds} |')
    if not s['routes']:
        print('| （无记录；4.19.0 之前的旧行默认不算，加 --all 才算） | | | | | | | | |')
    print()
    print('| 整次审查 | 次数 | 打回 | 平均耗时 | P90 |')
    print('|---|---|---|---|---|')
    for k, g in s['runs'].items():
        label = '开第三方' if k == 'third-party on' else '只走订阅'
        print(f'| {label} | {g["n"]} | {g["blocked"]} | {sec(g["avg_ms"])} | {sec(g["p90_ms"])} |')
    if not s['runs']:
        print('| （无记录） | | | | |')


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description='回合末审查运行统计')
    ap.add_argument('--log', default=default_log(), help='日志路径，默认 $TMPDIR/devkit-stop-audit.log')
    ap.add_argument('--days', type=float, help='只统计最近 N 天')
    ap.add_argument('--json', action='store_true', help='输出 JSON')
    ap.add_argument('--all', action='store_true', help='连 4.19.0 之前的旧格式行一起算（旧版只记失败，成功率会偏低）')
    a = ap.parse_args()
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=a.days) if a.days else None
    s = summarize(read_rows(a.log, since, a.all))
    if a.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
    else:
        print_table(s, a.log)


if __name__ == '__main__':
    main()
