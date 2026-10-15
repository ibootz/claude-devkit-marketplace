"""report.md 里上一版臂与环境插件臂的段落：首段的来源与退化说明、正文的逐用例对照。

只读 run.json 的字段，不改 record.py 已有段落；没有这些字段的旧 run.json 渲染为空。
"""


def _f(x):
    return '—' if x is None else '%.2f' % x


def _d(x):
    return '—' if x is None else '%+.2f' % x


def _runs(case):
    if not case:
        return '—'
    return ' / '.join(_f(s) for s in case.get('run_scores', [])) or '—'


def _env_desc(e):
    src = e.get('plugin_id') if e.get('source') == 'installed' else '路径 %s' % e.get('path')
    sha = e.get('git_commit_sha')
    return '`%s` %s（%s%s）' % (e.get('name'), e.get('version') or '无版本号', src,
                               '，gitCommitSha `%s`' % sha[:12] if sha else '')


def head_lines(rec):
    """紧跟标题的首段：上一版从哪来或为什么退化、是否跨改名、带了哪些环境插件。"""
    pa = rec.get('previous_arm')
    if pa is None:
        return []
    lines = []
    if pa.get('degraded'):
        lines.append('> **上一版臂已退化，本次只比「不装」与「当前版」**。原因：%s。'
                     '退化报告能否作闸门内版本的已审依据，由审阅人判断。' % pa.get('reason'))
    else:
        how = '自动认定为版本号与当前不同的最近一个版本的引入提交' if pa.get('obtained_by') == 'auto' \
            else '由 --base %s 指定' % pa.get('base')
        lines.append('> 上一版：`%s` %s，快照取自提交 `%s`，%s；插件路径 `%s`。' % (
            pa.get('name'), pa.get('version'), (pa.get('commit') or '')[:12], how, pa.get('path_in_repo')))
    if pa.get('cross_rename'):
        inc = pa.get('incomparable_cases') or {}
        listed = '；'.join('%s（%s）' % (c, '、'.join('`%s`' % r for r in refs)) for c, refs in sorted(inc.items()))
        lines += ['', '> **跨改名**：上一版名为 `%s`，当前版名为 `%s`，快照原样未改名。判分规则写了 skill 全名、'
                      '因而跨臂不可比的用例：%s。' % (pa.get('name'), rec['plugin']['name'], listed or '无')]
    envs = rec.get('env_plugins') or []
    if envs:
        lines += ['', '> 环境插件：%s。' % '、'.join(_env_desc(e) for e in envs)]
    return lines + ['']


def section_lines(rec):
    """正文段落：上一版与当前版逐用例、环境插件臂逐用例。"""
    lines = []
    arms = rec.get('arms') or {}
    cur = arms.get('current') or {}
    prev = arms.get('previous')
    dp = rec.get('delta_vs_previous')
    if prev and dp:
        inc = (rec.get('previous_arm') or {}).get('incomparable_cases') or {}
        lines += ['', '## 上一版与当前版', '',
                  '| 用例 | 上一版 | 当前版 | 差（当前版 − 上一版） | 上一版逐次 | 当前版逐次 | 备注 |',
                  '|---|---|---|---|---|---|---|']
        for name in rec['cases']:
            p = prev.get('cases', {}).get(name)
            c = cur.get('cases', {}).get(name)
            lines.append('| %s | %s | %s | %s | %s | %s | %s |' % (
                name, _f(p and p.get('score')), _f(c and c.get('score')), _d(dp['cases'].get(name)),
                _runs(p), _runs(c), '跨改名不可比' if name in inc else ''))
        lines.append('| 差（当前版 − 上一版） | %s | | | | | %s |' % (
            _d(dp.get('overall')), '不含跨改名不可比的用例' if dp.get('excluded_from_overall') else ''))

    env = arms.get('current_with_env')
    de = rec.get('delta_env_vs_current')
    if env:
        lines += ['', '## 环境插件臂', '',
                  '同装环境插件只用来看有没有冲突迹象，不量化「打几折」。各环境插件：', '']
        lines += ['- %s' % _env_desc(e) for e in env.get('env_plugins') or []]
        skipped = env.get('env_not_applied_cases') or []
        if skipped:
            lines += ['', '下列用例自己声明了 `plugins` 字段，环境插件臂里没有改写，**未加载环境插件**：%s'
                      % '、'.join(skipped)]
        if de:
            lines += ['', '| 用例 | 当前版 | 当前版+环境插件 | 差 | 当前版+环境插件逐次 |', '|---|---|---|---|---|']
            for name in rec['cases']:
                c = cur.get('cases', {}).get(name)
                e = env.get('cases', {}).get(name)
                lines.append('| %s | %s | %s | %s | %s |' % (
                    name, _f(c and c.get('score')), _f(e and e.get('score')), _d(de['cases'].get(name)), _runs(e)))
    return lines
