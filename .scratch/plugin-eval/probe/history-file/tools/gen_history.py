#!/usr/bin/env python3
"""生成合成会话历史 jsonl（虚构项目 tally，内容全部为本脚本手写，不含任何真实会话原文）。
用法：gen_history.py <变体:min|compact|long> <输出路径>
"""
import json, sys, uuid, datetime

SID = "5f0c1e2a-7b3d-4c11-9a8e-2d6b0f4e7a10"   # 虚构的会话 id
CWD = "/tmp/tally-demo"                          # 虚构的工作目录
T0 = datetime.datetime(2026, 10, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
_tick = [0]

def ts():
    _tick[0] += 7
    return (T0 + datetime.timedelta(seconds=_tick[0])).strftime("%Y-%m-%dT%H:%M:%S.000Z")

def nid():
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "tally-%d" % (_tick[0] * 1000 + len(_ids))))

_ids = []

def common(parent, full=True):
    u = str(uuid.uuid4()); _ids.append(u)
    d = {"parentUuid": parent, "isSidechain": False, "uuid": u, "timestamp": ts(), "sessionId": SID}
    if full:
        d.update({"userType": "external", "entrypoint": "cli", "cwd": CWD, "version": "2.1.300", "gitBranch": "main"})
    return d

def user(parent, text, full=True, **extra):
    d = common(parent, full); d.update({"type": "user", "message": {"role": "user", "content": text}}); d.update(extra); return d

def assistant(parent, text, full=True):
    d = common(parent, full)
    msg = {"role": "assistant", "content": [{"type": "text", "text": text}]}
    if full:
        msg = {"id": "msg_synthetic%08d" % len(_ids), "type": "message", "role": "assistant", "model": "claude-opus-5-5",
               "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None,
               "usage": {"input_tokens": 10, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}
    d.update({"type": "assistant", "message": msg}); return d

SUMMARY = open(__file__.replace("gen_history.py", "summary.txt"), encoding="utf-8").read()

TAIL = [
    ("好，CSV 导入先放一放，等我确认银行导出的列顺序再说。", "好的，CSV 导入（`tally import`）先搁置，`tally/importer.py` 保持现状不动。目前 `tally report --month` 的按月汇总与 `tally budget` 的超支提醒都已通过 `pytest -q`（42 passed）。等你拿到银行导出样例后，我再按实际列顺序补 `ColumnMap`。"),
    ("顺便问一句，报表里的金额现在是四舍五入到分吗？", "是的。`tally/money.py` 里统一用 `Decimal.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)`，也就是银行家舍入；`report.py` 只做展示格式化，不再二次舍入。这样多笔小额汇总时不会出现系统性偏高。"),
]

MODULES = ["ledger", "money", "budget", "report", "importer", "cli", "storage", "tags", "recurring", "export"]
VERBS = ["load", "save", "merge", "split", "validate", "normalize", "summarize", "format", "filter", "rollup"]

def filler_turn(i):
    m = MODULES[i % len(MODULES)]; v = VERBS[(i * 3) % len(VERBS)]
    fn = "%s_%s" % (v, m)
    q = "第 %d 个问题：帮我解释一下 `tally/%s.py` 里的 `%s`，它在什么情况下会抛异常？顺便看看有没有能简化的地方。" % (i + 1, m, fn)
    code = "\n".join([
        "def %s(rows: list[dict], *, strict: bool = False) -> list[dict]:" % fn,
        '    """%s 模块的第 %d 个辅助函数。"""' % (m, i + 1),
        "    out = []",
        "    for idx, row in enumerate(rows):",
        "        amount = row.get('amount')",
        "        if amount is None:",
        "            if strict:",
        "                raise ValueError(f'row {idx}: missing amount')",
        "            continue",
        "        cents = int(Decimal(str(amount)) * 100)",
        "        tag = (row.get('tag') or 'untagged').strip().lower()",
        "        out.append({**row, 'cents': cents, 'tag': tag, 'seq': %d})" % i,
        "    out.sort(key=lambda r: (r['date'], r['seq']))",
        "    return out",
    ])
    a = ("`%s` 接收一组原始流水行，逐行把 `amount` 换算成整数分（`cents`），并把标签统一成小写。\n\n"
         "```python\n%s\n```\n\n"
         "抛异常只有一种情况：`strict=True` 且某行缺 `amount`，此时抛 `ValueError`，消息里带行号，方便定位导入文件的第几行有问题；"
         "`strict=False` 时缺金额的行会被静默跳过。另外 `Decimal(str(amount))` 遇到非数字字符串会抛 `decimal.InvalidOperation`，"
         "这一点调用方目前没有捕获，建议在 `cli.py` 的入口统一转成友好的错误提示。\n\n"
         "可简化的地方有两处：一是 `tag` 的归一化在 `tags.py` 里已经有 `normalize_tag`，这里可以直接复用，避免两处规则漂移；"
         "二是排序键里的 `seq` 是常量 %d，对同一批数据不起区分作用，可以改用原始行号 `idx`，这样同一天的多笔流水能保持导入顺序。"
         "这两处改动都不影响对外接口，现有 `tests/test_%s.py` 的用例应能原样通过。") % (fn, code, i, m)
    return q, a

def build(variant):
    recs = []
    if variant == "min":
        u = user(None, "我在做一个叫 tally 的个人记账命令行小工具，用 Python 写，数据存 SQLite。先记住这个背景。", full=False)
        a = assistant(u["uuid"], "好的，已记下：tally 是一个 Python 编写、以 SQLite 存储的个人记账 CLI。后续有具体问题随时说。", full=False)
        return [u, a]
    # compact / long：先放一条 compact_boundary，再放 isCompactSummary 摘要
    b = common(None); b.update({"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted", "level": "info",
                               "logicalParentUuid": str(uuid.uuid4()),
                               "compactMetadata": {"trigger": "auto", "preTokens": 168000, "postTokens": 9000}})
    recs.append(b)
    s = user(b["uuid"], SUMMARY, isVisibleInTranscriptOnly=True, isCompactSummary=True)
    recs.append(s)
    parent = s["uuid"]
    turns = list(TAIL)
    if variant == "long":
        turns = [filler_turn(i) for i in range(int(sys.argv[3]) if len(sys.argv) > 3 else 24)] + turns
    for q, ans in turns:
        u = user(parent, q); recs.append(u)
        a = assistant(u["uuid"], ans); recs.append(a)
        parent = a["uuid"]
    return recs

if __name__ == "__main__":
    recs = build(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    chars = sum(len(json.dumps(r.get("message", {}), ensure_ascii=False)) for r in recs)
    print("records=%d message_chars=%d" % (len(recs), chars))
