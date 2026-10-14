#!/usr/bin/env python3
"""把成对的 markdown 文本做成一页盲评 HTML：每组左右随机摆放，人只选 A / B / 差不多。

用法：python3 build_blind_ab.py <pairs.json> <out.html> <key.json>

pairs.json 形如：
{
  "title": "页面标题",
  "instructions": "页首给评审人的一段说明",
  "groups": [
    {"scenario": "这一组的情境，一两句", "x": "版本一的 md 路径", "y": "版本二的 md 路径"}
  ]
}

左右摆放由随机数决定，对照写进 key.json（评完才读），HTML 里不出现文件名与版本名。
页面底部按选择拼出一行回复码（如 `1A 2= 3B`），评审人复制后贴回对话即可。
只用标准库；markdown 在浏览器里用 marked 渲染，取不到 CDN 时退回原文显示。
"""
import json
import random
import secrets
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    pairs_path, out_html, key_path = (Path(p) for p in sys.argv[1:])
    cfg = json.loads(pairs_path.read_text(encoding="utf-8"))
    base = pairs_path.parent

    seed = secrets.randbits(32)
    rng = random.Random(seed)
    groups, key = [], {"seed": seed, "groups": []}
    for i, g in enumerate(cfg["groups"], 1):
        x, y = (base / g["x"]).resolve(), (base / g["y"]).resolve()
        left, right = (x, y) if rng.random() < 0.5 else (y, x)
        groups.append({
            "n": i,
            "scenario": g.get("scenario", ""),
            "a": left.read_text(encoding="utf-8"),
            "b": right.read_text(encoding="utf-8"),
        })
        key["groups"].append({"n": i, "A": str(left), "B": str(right)})

    data = json.dumps(
        {"title": cfg["title"], "instructions": cfg.get("instructions", ""), "groups": groups},
        ensure_ascii=False,
    ).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", data).replace("__TITLE__", cfg["title"])
    out_html.write_text(html, encoding="utf-8")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_html)


TEMPLATE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>__TITLE__</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  :root { --bg:#f5f5f2; --card:#fff; --ink:#1d1d1f; --mute:#6b6b70; --line:#e2e2de; --acc:#2f6fed; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:15px/1.6 -apple-system,"PingFang SC","Helvetica Neue",sans-serif; }
  header { position:sticky; top:0; z-index:5; background:var(--card); border-bottom:1px solid var(--line);
           padding:14px 28px; display:flex; gap:18px; align-items:center; flex-wrap:wrap; }
  header h1 { font-size:18px; margin:0; }
  header .code { font:600 15px ui-monospace,Menlo,monospace; background:#eef3ff; padding:6px 12px; border-radius:6px; }
  header button { border:0; background:var(--acc); color:#fff; padding:7px 14px; border-radius:6px; cursor:pointer; font-size:14px; }
  .intro { max-width:1100px; margin:18px auto 0; padding:0 28px; color:var(--mute); white-space:pre-line; }
  section { max-width:1600px; margin:22px auto; padding:0 28px; }
  .ghead { display:flex; align-items:baseline; gap:14px; margin-bottom:10px; }
  .ghead h2 { margin:0; font-size:17px; }
  .ghead .sc { color:var(--mute); }
  .pair { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  .side { background:rgb(253,246,227); color:#3b3a36; border:1px solid #e6dcc0; border-radius:10px; overflow:hidden; display:flex; flex-direction:column; }
  .side .label { background:#f1e7c9; padding:8px 14px; font-weight:600; letter-spacing:1px; }
  .side .body { padding:14px 18px; max-height:78vh; overflow:auto;
                font:14px/1.65 ui-monospace,"SF Mono",Menlo,"PingFang SC",monospace; }
  .body h1 { font-size:15px; text-decoration:underline; margin:14px 0 6px; }
  .body h2, .body h3 { font-size:14px; margin:14px 0 6px; color:#1d1d1f; }
  .body p { margin:6px 0; }
  .body .gap { height:1.2em; }
  .body table { border-collapse:collapse; margin:8px 0; font-size:13px; }
  .body th, .body td { border:1px solid #d9cfb2; padding:3px 8px; vertical-align:top; }
  .body th { background:#f1e7c9; }
  .body code { color:#a1401a; }
  .body pre { background:#f4ecd4; border:1px solid #e6dcc0; padding:8px 10px; border-radius:6px; overflow:auto; }
  .body pre code { color:#3b3a36; }
  .body hr { border:0; border-top:1px solid #d9cfb2; }
  .body strong { color:#000; }
  .vote { display:flex; gap:10px; align-items:center; margin-top:12px; flex-wrap:wrap; }
  .vote label { background:var(--card); border:1px solid var(--line); border-radius:6px; padding:6px 14px; cursor:pointer; }
  .vote input { margin-right:6px; }
  .vote textarea { flex:1; min-width:280px; height:38px; border:1px solid var(--line); border-radius:6px; padding:6px 10px; font:inherit; }
</style></head>
<body>
<header>
  <h1>__TITLE__</h1>
  <span>回复码：</span><span class="code" id="code">（还没选）</span>
  <button id="copy">复制回复码</button><span id="tip" style="color:var(--mute)"></span>
</header>
<div class="intro" id="intro"></div>
<div id="groups"></div>
<script>
const DATA = __DATA__;
// 按终端观感渲染：单换行保留为换行（breaks），连续两个及以上空行保留为一段额外留白
const md = s => (window.marked ? marked.parse(s.replace(/\n{3,}/g, '\n\n<div class="gap"></div>\n\n'), {breaks: true}) :'<pre>' + s.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])) + '</pre>');
document.getElementById('intro').textContent = DATA.instructions;
const root = document.getElementById('groups');
for (const g of DATA.groups) {
  const s = document.createElement('section');
  s.innerHTML = `
    <div class="ghead"><h2>第 ${g.n} 组</h2><span class="sc"></span></div>
    <div class="pair">
      <div class="side"><div class="label">A</div><div class="body">${md(g.a)}</div></div>
      <div class="side"><div class="label">B</div><div class="body">${md(g.b)}</div></div>
    </div>
    <div class="vote">
      <label><input type="radio" name="g${g.n}" value="A">A 更好</label>
      <label><input type="radio" name="g${g.n}" value="B">B 更好</label>
      <label><input type="radio" name="g${g.n}" value="=">差不多</label>
      <textarea id="note${g.n}" placeholder="卡在哪句、哪个结构（可不填）"></textarea>
    </div>`;
  s.querySelector('.sc').textContent = g.scenario;
  root.appendChild(s);
}
function code() {
  const picks = [], notes = [];
  for (const g of DATA.groups) {
    const v = document.querySelector(`input[name=g${g.n}]:checked`);
    picks.push(g.n + (v ? v.value : '?'));
    const t = document.getElementById('note' + g.n).value.trim();
    if (t) notes.push(g.n + '：' + t);
  }
  return picks.join(' ') + (notes.length ? ' ｜ ' + notes.join('；') : '');
}
document.addEventListener('input', () => { document.getElementById('code').textContent = code(); });
document.getElementById('copy').onclick = async () => {
  await navigator.clipboard.writeText(code());
  document.getElementById('tip').textContent = '已复制，贴回对话即可';
};
</script>
</body></html>
"""

if __name__ == "__main__":
    main()
