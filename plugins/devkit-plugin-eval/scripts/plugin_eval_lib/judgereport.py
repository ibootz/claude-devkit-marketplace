"""report.md 里 AI 评委（票 09）的两段：首段醒目提示（不采信、判分出错）与「## AI 评委判分」一节。
只读 run.json 的 judge 字段（judge.summarize 的输出），不读 judge.json；待审页写回用户裁定后整节重渲。
本节内只用 ### 小标题：pending.upsert_section 按下一个 `## ` 定节尾。
是否采信三态：true 采信（已校准）、false 不采信、null 采信（未校准）。judge = {"skipped": "no-judge"} 时写明按 --no-judge 跳过。
"""
SECTION_HEADING = '## AI 评委判分'
_V = {'pass': '通过', 'fail': '不通过', 'unclear': '判不了', None: '—'}
_D = {'two-pass': '两遍判法不同', 'unclear': '两遍都判不了', 'rule-conflict': '评委与规则冲突', None: ''}


def _f(x):
    return '—' if x is None else '%.2f' % x


def trust_text(j):
    t = j.get('trusted')
    if t is True:
        return '采信'
    if t is False:
        return '**不采信**（%s）' % j.get('untrusted_reason')
    return '采信（未校准）'


def skipped(j):
    return isinstance(j, dict) and j.get('skipped') == 'no-judge'


def console_line(j):
    """compare / resume 收尾在终端打印的评委一行；没有评委段时返回 None。"""
    if not isinstance(j, dict):
        return None
    if skipped(j):
        return 'AI 评委：按 --no-judge 跳过'
    rate = (j.get('gold') or {}).get('agreement_rate')
    return 'AI 评委 %s：样本 %s、分歧 %s、抽检 %s、出错 %s；金标一致率 %s；%s' % (
        j.get('model'), j.get('samples'), j.get('disagreements'), j.get('spot_checks'), j.get('errors'),
        '—' if rate is None else '%.2f' % rate, trust_text(j).replace('**', ''))


def scoring_line(rec):
    """报告首段「判分」一行：按本次实际情况写。"""
    j = rec.get('judge')
    if skipped(j):
        return '规则 grader 定分与是否通过；AI 评委按 --no-judge 跳过'
    if j:
        return '规则 grader 定分与是否通过；AI 评委另判 %d 个样本，只作信息（见「AI 评委判分」）' % (j.get('samples') or 0)
    return '只用规则 grader（没有用例声明 AI 评委判定标准）'


def report_banner(rec):
    j = rec.get('judge')
    if not j or skipped(j):
        return []
    out = []
    if j.get('trusted') is False:
        out += ['', '> **AI 判分不采信**：%s。本次 AI 评委的判分只作参考，不能作为改插件或发版的依据。'
                % j.get('untrusted_reason')]
    if j.get('errors'):
        out += ['', '> **AI 评委有 %d 个样本判分出错**，运行判为不完整，续跑时重判。' % j['errors']]
    g = j.get('gold') or {}
    if g.get('state') == 'insufficient-errors':
        out += ['', '> **AI 评委金标校准没做成**：%s。' % g.get('note')]
    if j.get('warnings'):
        out += ['', '> **AI 评委判定标准有告警**（%d 条，见「AI 评委判分」一节）。' % len(j['warnings'])]
    return out


def section_body(rec):
    """「## AI 评委判分」整节文本（含标题行，末尾带换行）。"""
    j = rec.get('judge')
    lines = [SECTION_HEADING, '']
    if skipped(j):
        lines += ['按 --no-judge 跳过：本次未调 AI 评委，也未读 judge-config.json。', '']
        return '\n'.join(lines)
    if not j:
        lines += ['本次没有用例声明 AI 评委判定标准（用例目录下的 `judge/*.md`），未调 AI 评委。', '']
        return '\n'.join(lines)
    g = j.get('gold') or {}
    u = j.get('usage') or {}
    lines += [
        '- 评委模型：`%s`（%s；每个样本判 %d 遍）；判分明细见 `%s`' % (
            j.get('model'), j.get('model_source'), j.get('passes') or 2, j.get('file')),
        '- 样本 %d 个：两遍一致 %d、分歧 %d、出错 %d；从两遍一致的样本里抽检 %d 个；用户已裁定 %d 个' % (
            j['samples'], j['agreed'], j['disagreements'], j['errors'], j['spot_checks'], j['user_decided']),
        '- 金标校准：金标 %s 条，判成 %s 条，一致 %s 条，一致率 %s（阈值 %s，启用所需 %s 条）。%s' % (
            g.get('total'), g.get('judged'), g.get('agreed'), _f(g.get('agreement_rate')),
            '未配置' if g.get('threshold') is None else g['threshold'],
            '未配置' if g.get('min_samples') is None else g['min_samples'], g.get('note') or ''),
    ]
    for src, label in (('disagreement', '分歧样本'), ('spot-check', '抽检样本')):
        b = (g.get('by_source') or {}).get(src)
        if b:
            lines.append('  - 来自%s的金标：%d 条，判成 %d 条，一致率 %s%s' % (
                label, b['total'], b['judged'], _f(b['agreement_rate']), '（判采信与否只看这一项）'
                if src == (g.get('basis_source') or 'disagreement') else '（只记，不参与判采信）'))
    lines += [
        '- 是否采信：%s' % trust_text(j),
        '- 评委花费：$%.4f（%s，%s 次调用）' % (u.get('cost_usd') or 0, u.get('cost_basis', ''), u.get('calls', 0)),
        '',
        'AI 判分只作信息：不改规则分，也不进「是否通过」。样本通过记 1、不通过记 0；分歧样本经用户裁定后才计入。',
        '',
    ]
    if j.get('warnings'):
        lines += ['### 判定标准告警', ''] + ['- %s' % w for w in j['warnings']] + ['']
    scores = (j.get('scores') or {}).get('arms') or {}
    if scores:
        lines += ['### 各臂 AI 判分', '', '| 臂 | 用例 | AI 判分 |', '|---|---|---|']
        labels = j.get('arm_labels') or {}
        for arm, a in scores.items():
            for case, sc in sorted(a['cases'].items()):
                lines.append('| %s | %s | %s |' % (labels.get(arm) or arm, case, _f(sc)))
        lines += ['', '差（当前版 − 不装）：%s' % ('—' if (j.get('scores') or {}).get('delta_current_vs_none') is None
                                             else '%+.2f' % j['scores']['delta_current_vs_none']), '']
    flagged = j.get('flagged') or []
    if flagged:
        lines += ['### 分歧、抽检与出错的样本', '',
                  '| 样本 | 臂 | 用例 · 第几次 | 判定标准 | 类别 | 两遍 | 规则 | 用户裁定 | 金标 |',
                  '|---|---|---|---|---|---|---|---|---|']
        for f in flagged:
            kind = {'disagreement': '分歧：%s' % _D.get(f.get('disagreement'), ''), 'error': '出错'}.get(
                f.get('status'), '抽检')
            rule = '—' if f.get('rule_passed') is None else '%s=%s' % (f.get('rule_grader'),
                                                                       '通过' if f['rule_passed'] else '不通过')
            lines.append('| `%s` | %s | %s · %d | %s | %s | %s | %s | %s | %s |' % (
                f['id'], f.get('arm_label') or f['arm'], f['case'], f['run'], f['criterion'], kind,
                ' / '.join(_V.get(v, '?') for v in f.get('verdicts') or []), rule,
                _V.get(f.get('user_verdict')) if f.get('user_verdict') else '待裁定',
                '`%s`' % f['gold_id'] if f.get('gold_id') else '—'))
        lines.append('')
    return '\n'.join(lines)


def report_sections(rec):
    return [''] + section_body(rec).rstrip('\n').split('\n')
