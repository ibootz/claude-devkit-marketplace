"""report.md 里条款清单的两块（票 10）：首段醒目提示（banner_lines）与「## 条款清单」一节（section_lines）。

只读 run.json 的 clause_check（clauses.check_for_run 写的 clause-check.json 原样搬进来）。不 import record：
record.render_report 调本模块。待审页确认 / 打回时，clauses._apply 按 PENDING_BANNER 的开头改写提示行。
"""

PENDING_BANNER = '> **条款清单待确认**'


def _esc(text):
    return str(text or '').replace('|', '\\|').replace('\n', ' ')


def banner_lines(rec):
    cc = rec.get('clause_check') or {}
    st = cc.get('status')
    if st == 'pending-confirmation':
        n = cc.get('proposal_counts') or {}
        what = ('尚无条款清单，本次已整份抽取 %d 条' % n.get('added', 0) if cc.get('proposal_kind') == 'extract'
                else '注入文本指纹与清单记录的不同，本次已增量重抽：新增 %d、改写 %d、退役 %d'
                % (n.get('added', 0), n.get('rewritten', 0), n.get('retired', 0)))
        return ['', '%s：%s。清单变更在待审页确认前，对照照跑，新条款在下方「条款清单」一节列「无用例」。' % (PENDING_BANNER, what)]
    if st == 'ai-error':
        return ['', '> **条款清单已过期，重抽失败**：%s。清单未改，下次对照会再试。' % '；'.join(cc.get('errors') or [])]
    if st == 'unreliable':
        h = cc.get('hooks') or {}
        bad = list(h.get('failed_hooks') or []) + ['%s（两次输出不同）' % k for k in h.get('unstable_hooks') or []]
        return ['', '> **条款清单本次未判是否过期**：注入 hook 执行失败或输出含未归一的易变内容：%s。'
                % '；'.join(bad + list(cc.get('errors') or []))]
    if st == 'error':
        return ['', '> **条款清单这一步出错**，本次未判是否过期：%s。' % '；'.join(cc.get('errors') or [])]
    return []


def section_lines(rec):
    cc = rec.get('clause_check') or {}
    st = cc.get('status')
    if not st or st == 'no-injection':
        return []
    label = {'up-to-date': '未过期（注入文本指纹与清单一致，未重抽）', 'pending-confirmation': '待确认',
             'ai-error': '已过期，重抽失败', 'unreliable': '本次未判', 'error': '出错'}.get(st, st)
    lines = ['', '## 条款清单', '',
             '- 状态：%s' % label,
             '- 本次所用条款清单指纹：`%s`' % (cc.get('list_fingerprint') or '无（尚无已确认的清单）'),
             '- 注入文本指纹：本次 `%s`；清单记录 `%s`' % (cc.get('injection_fingerprint'),
                                                cc.get('list_injection_fingerprint') or '—')]
    if cc.get('reused_from'):
        lines.append('- 清单变更沿用运行 `%s` 里尚未裁定的那份，未重抽' % cc['reused_from'])
    ai = cc.get('ai') or {}
    if ai.get('model') and not cc.get('reused_from'):
        lines.append('- 抽取模型：%s；花费（标价估算）：$%.4f' % (ai['model'], ai.get('cost_usd') or 0))
    h = cc.get('hooks') or {}
    if h.get('silent_hooks'):
        lines.append('- 空目录下没有输出的注入 hook（条件注入，这部分文字改了不会判过期）：%s'
                     % '、'.join('`%s`' % k for k in h['silent_hooks']))
    rows = cc.get('rows') or []
    if rows:
        lines += ['', '| 条款 | 判定标准 | 用例 |', '|---|---|---|']
        for r in rows:
            if r.get('status') == 'proposed':
                cases = '无用例（新条款，清单待确认）'
            elif r.get('status') == 'retired':
                cases = '退役（%s）→ %s%s' % (r.get('retire_reason'), '、'.join(r.get('replaced_by') or []) or '无替代',
                                           '；仍挂 %d 个用例，待改挂' % len(r['cases']) if r.get('cases') else '')
            else:
                cases = '、'.join(r.get('cases') or []) or '无用例'
            mark = {'rewrite': '（拟改写）', 'retire': '（拟退役 → %s）' % '、'.join(r.get('pending_replaced_by') or [])
                    if r.get('pending_replaced_by') else '（拟删除）'}.get(r.get('pending_change'), '')
            lines.append('| %s%s | %s | %s |' % (r['id'], mark, _esc(r.get('criterion')), _esc(cases)))
        lines += ['', '「无用例」不算失败（spec「2.3」首批审阅）；用例草稿由用例草稿流起草、勾选通过后才挂上。']
    return lines
