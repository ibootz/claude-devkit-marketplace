"""会话复盘读条款清单的最小接口：给复盘候选标「命中条款 id」。

条款清单由票 10 落地（文件名、完整字段都归票 10 定）。本模块只约定复盘要用的最小读取面，集成时由票 10 对齐：
- 清单文件放 `<仓>/plugin-evals/<插件>/` 下，按 CLAUSE_FILES 依次找第一个存在的；
- 顶层是 {"clauses": [...]}，每条至少有 `id`；`retired: true` 的退役条款不参与归属；
- 可选 `review_signals`：字符串列表，写复盘信号键（见 signal_keys），任一相等即算命中。
  没写 `review_signals` 的条款不会被自动命中——复盘只看机械信号，不读条款的判定标准原文去猜。

清单不存在、读不出或格式不对时返回空清单并带一句说明，复盘照跑，候选的 clause_ids 为空。
"""
import json
from dataclasses import dataclass
from pathlib import Path

CLAUSE_FILES = ('clauses.json',)   # 暂定：票 10 定下文件名后改这里


@dataclass(frozen=True)
class Clause:
    id: str
    signals: tuple


def load(plugin_evals_dir):
    """返回 ([Clause], 说明或 None)。只收未退役、带 review_signals 的条款。"""
    d = Path(plugin_evals_dir)
    for name in CLAUSE_FILES:
        p = d / name
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError) as e:
            return [], '条款清单 %s 读不出（%s），候选不标条款 id' % (name, type(e).__name__)
        items = data.get('clauses') if isinstance(data, dict) else None
        if not isinstance(items, list):
            return [], '条款清单 %s 没有 clauses 列表，候选不标条款 id' % name
        out = []
        for c in items:
            if not isinstance(c, dict) or not isinstance(c.get('id'), str) or c.get('retired'):
                continue
            sigs = c.get('review_signals')
            if isinstance(sigs, list):
                sigs = tuple(s for s in sigs if isinstance(s, str) and s)
                if sigs:
                    out.append(Clause(c['id'], sigs))
        return out, None
    return [], None


def signal_keys(kind, rule):
    """一个候选能被条款认领的全部信号键：`<kind>:<rule>`；rule 带 `#check=<x>` 时另加 `<kind>:<脚本>` 与 `check=<x>`。"""
    keys = ['%s:%s' % (kind, rule)]
    script, _, check = rule.partition('#check=')
    if check:
        keys += ['%s:%s' % (kind, script), 'check=%s' % check]
    return keys


def match(clauses, kind, rule):
    keys = set(signal_keys(kind, rule))
    return sorted({c.id for c in clauses if keys.intersection(c.signals)})
