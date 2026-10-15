"""会话复盘读条款清单：给复盘候选标「命中条款 id」。格式按票 10 的 clauses.json，不新增要用户手填的字段。

- 清单：`<仓>/plugin-evals/<插件>/clauses.json`，顶层 {"clauses": [...]}，每条有 `id`（C%03d）、`events`
  （条款出自哪些 hook 事件的注入文字）与 `status`；只有 status=active 的参与归属（退役判断同票 10 的 retired_ids）。
- 映射（推导，不读条款原文去猜）：候选的规则键里有脚本相对路径（`hooks/guard.js#check=x` 取 `hooks/guard.js`）；
  被测插件 hooks.json 里挂这个脚本的事件集合，与条款的 events 有交集的未退役条款恰好一条时，记这一条。
  零条或多条都算推不出：clause_ids 为空，clause_mapping 如实记「未映射」与原因。
- 清单不存在、读不出或格式不对时返回空清单并带一句说明，复盘照跑，候选全部「未映射」。
"""
import json
from dataclasses import dataclass
from pathlib import Path

LIST_FILE = 'clauses.json'          # 与票 10 的 clauses.LIST_FILE 同名（不 import clauses：避免导入期循环）


@dataclass(frozen=True)
class Clause:
    id: str
    events: tuple


def load(plugin_evals_dir):
    """返回 ([Clause], 说明或 None)。只收 status=active 的条款；没有清单时说明为 None、清单为空。"""
    p = Path(plugin_evals_dir) / LIST_FILE
    if not p.is_file():
        return [], None
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        return [], '条款清单 %s 读不出（%s），候选都不标条款 id' % (LIST_FILE, type(e).__name__)
    items = data.get('clauses') if isinstance(data, dict) else None
    if not isinstance(items, list):
        return [], '条款清单 %s 没有 clauses 列表，候选都不标条款 id' % LIST_FILE
    out = []
    for c in items:
        if not isinstance(c, dict) or not isinstance(c.get('id'), str) or c.get('status') != 'active':
            continue
        events = tuple(e for e in c.get('events') or [] if isinstance(e, str))
        out.append(Clause(c['id'], events))
    return out, None


def script_of(rule):
    return (rule or '?').partition('#check=')[0]


def match(clauses, rule, script_events, has_list=True):
    """(clause_ids, clause_mapping)。script_events：{脚本相对路径: {事件}}（被测插件 hooks.json 推出）。"""
    if not has_list:
        return [], {'status': 'unmapped', 'reason': '没有可用的条款清单'}
    script = script_of(rule)
    events = script_events.get(script) or set()
    if not events:
        return [], {'status': 'unmapped', 'reason': '规则脚本 %s 不在被测插件的 hooks.json 里，推不出事件' % script}
    hits = sorted(c.id for c in clauses if events.intersection(c.events))
    if len(hits) == 1:
        return hits, {'status': 'mapped', 'reason': '脚本挂在 %s，与该条款的 events 唯一相交' % '、'.join(sorted(events))}
    if not hits:
        return [], {'status': 'unmapped', 'reason': '没有未退役条款的 events 含 %s' % '、'.join(sorted(events))}
    return [], {'status': 'unmapped', 'reason': '%d 条未退役条款的 events 都含 %s（%s），推不出是哪一条'
                % (len(hits), '、'.join(sorted(events)), '、'.join(hits))}
