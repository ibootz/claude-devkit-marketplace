#!/usr/bin/env python3
"""揭盲：把评审人贴回的回复码对上 key.json，生成结果页 HTML 并落一份 results.json。

用法：python3 reveal.py <key.json> "<回复码>" <out.html> <results.json>

回复码形如 `1A 2= 3B ｜ 1：卡在术语表；3：太长`（盲评页自动拼出）。
版本名取自文件路径里的配置目录名（如 old_rule / new_rule），所以生成目录要按
`<场景>/<配置>/outputs/<文件>` 摆放。指标由同目录的 metrics.py 计算；运行目录里有
timing.json 时一并展示。
"""
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from metrics import measure  # noqa: E402


def arm_of(p: Path) -> str:
    return p.parent.parent.name if p.parent.name == "outputs" else p.parent.name


def scenario_of(p: Path) -> str:
    return p.parent.parent.parent.name if p.parent.name == "outputs" else p.parent.parent.name


def timing_of(p: Path) -> dict:
    t = p.parent.parent / "timing.json"
    return json.loads(t.read_text(encoding="utf-8")) if t.exists() else {}


def parse(code: str) -> tuple[dict, dict]:
    picks_part, _, notes_part = code.partition("｜")
    picks = {int(n): v for n, v in re.findall(r"(\d+)\s*([ABab=?])", picks_part)}
    picks = {n: v.upper() for n, v in picks.items()}
    notes = {}
    for seg in re.split(r"[；;]", notes_part):
        m = re.match(r"\s*(\d+)\s*[：:]\s*(.+)", seg)
        if m:
            notes[int(m.group(1))] = m.group(2).strip()
    return picks, notes


def main() -> None:
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    key = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    picks, notes = parse(sys.argv[2])
    out_html, out_json = Path(sys.argv[3]), Path(sys.argv[4])

    rows, tally = [], {}
    for g in key["groups"]:
        n = g["n"]
        side = {s: Path(g[s]) for s in ("A", "B")}
        pick = picks.get(n, "?")
        winner = arm_of(side[pick]) if pick in ("A", "B") else ("平" if pick == "=" else "未选")
        tally[winner] = tally.get(winner, 0) + 1
        rows.append({
            "n": n,
            "scenario": scenario_of(side["A"]),
            "pick": pick,
            "winner": winner,
            "note": notes.get(n, ""),
            "sides": {s: {"arm": arm_of(p), "metrics": measure(p), "timing": timing_of(p),
                          "text": p.read_text(encoding="utf-8")} for s, p in side.items()},
        })
    result = {"reply": sys.argv[2], "tally": tally, "groups": rows}
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    e = html.escape
    keys = ["行数", "字数", "首个问题所在行", "问题数", "首行带类型标签", "表格数", "代码块数", "占位词数"]
    parts = []
    for r in rows:
        a, b = r["sides"]["A"], r["sides"]["B"]
        mrows = "".join(f"<tr><td>{k}</td><td>{e(str(a['metrics'][k]))}</td><td>{e(str(b['metrics'][k]))}</td></tr>" for k in keys)
        for label, s in (("耗时(秒)", "total_duration_seconds"), ("tokens", "total_tokens")):
            mrows += f"<tr><td>{label}</td><td>{a['timing'].get(s, '—')}</td><td>{b['timing'].get(s, '—')}</td></tr>"
        parts.append(f"""
<section><h2>第 {r['n']} 组 · {e(r['scenario'])}</h2>
<p class="verdict">你选了 <b>{e(r['pick'])}</b> → 胜出：<b>{e(r['winner'])}</b>{('　备注：' + e(r['note'])) if r['note'] else ''}</p>
<table class="m"><tr><th>指标</th><th>A = {e(a['arm'])}</th><th>B = {e(b['arm'])}</th></tr>{mrows}</table>
<details><summary>展开两边原文</summary><div class="pair">
<pre>{e(a['text'])}</pre><pre>{e(b['text'])}</pre></div></details></section>""")
    summary = "　".join(f"{e(k)}：{v}" for k, v in sorted(tally.items()))
    out_html.write_text(f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>揭盲结果</title>
<style>body{{margin:0;background:#f5f5f2;font:15px/1.6 -apple-system,"PingFang SC",sans-serif;color:#1d1d1f}}
header{{background:#fff;border-bottom:1px solid #e2e2de;padding:16px 28px}}h1{{margin:0;font-size:19px}}
section{{max-width:1500px;margin:20px auto;padding:0 28px}}h2{{font-size:17px}}.verdict{{font-size:16px}}
table.m{{border-collapse:collapse;background:#fff}}table.m td,table.m th{{border:1px solid #ddd;padding:4px 12px}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:10px}}
pre{{background:rgb(253,246,227);color:#3b3a36;border:1px solid #e6dcc0;padding:14px;border-radius:8px;white-space:pre-wrap;font:13px/1.6 ui-monospace,Menlo,"PingFang SC",monospace;max-height:70vh;overflow:auto}}</style>
</head><body><header><h1>揭盲结果</h1><p>胜场：{summary}　｜　回复码：{e(sys.argv[2])}</p></header>{''.join(parts)}</body></html>""", encoding="utf-8")
    print(out_html)
    print(json.dumps(tally, ensure_ascii=False))


if __name__ == "__main__":
    main()
