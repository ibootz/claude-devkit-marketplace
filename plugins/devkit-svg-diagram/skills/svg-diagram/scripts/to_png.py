# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "playwright>=1.40.0",
#     "fonttools[woff]>=4.50",
# ]
# ///
"""Embed the theme's fonts into SVGs from render.py, rasterize them to PNG, and check that no text overflows.

Usage:
    uv run <skill-dir>/scripts/to_png.py out.svg [more.svg ...] [--scale 2]   # writes out.png next to each SVG
    uv run <skill-dir>/scripts/to_png.py out.svg -o /tmp/x.png
    uv run <skill-dir>/scripts/to_png.py out.svg --no-embed-fonts             # leave the SVG untouched
    uv run <skill-dir>/scripts/to_png.py --install-browser                    # first-time setup

Fonts: the SVG root's data-fonts names the families the theme draws with (Cascadia, Excalifont, Xiaolai --
the fonts Excalidraw ships, SIL OFL 1.1, see assets/fonts/LICENSE-OFL.txt). They are bundled in
<skill-dir>/assets/fonts (Xiaolai cut to GB 2312, about 2 MB in all), so nothing is downloaded. Each run
subsets them to the characters the diagram uses and writes them into the SVG as <style class="sd-fonts">,
so the SVG looks the same on machines without these fonts. Running again replaces that block (idempotent).
Characters outside the bundled set fall through to the next font in the theme's list (system fonts).

The fit check measures every <text data-maxw="N"> with the browser's real font metrics after the fonts
have loaded and reports lines wider than N -- render.py estimates widths, the browser knows them.

Exit codes: 0 ok, 1 bad input / browser missing, 2 PNG written but some text overflows (read stderr).
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

INSTALL_HINT = f"uv run '{Path(__file__).resolve()}' --install-browser"
FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FAMILIES = ("Cascadia", "Excalifont", "Xiaolai")
STYLE_RE = re.compile(r'<style class="sd-fonts">.*?</style>', re.S)
TEXT_RE = re.compile(r"<text\b([^>]*)>(.*?)</text>", re.S)
FAMILY_ATTR_RE = re.compile(r'font-family="([^"]*)"')

MEASURE_JS = """
() => {
  const out = [];
  for (const t of document.querySelectorAll('text[data-maxw]')) {
    const w = t.getComputedTextLength();
    const max = parseFloat(t.getAttribute('data-maxw'));
    if (w > max + 1) out.push({text: t.textContent, width: Math.round(w), max});
  }
  return out;
}
"""
FONTS_JS = """
async () => {
  await document.fonts.ready;
  return [...document.fonts].map(f => [f.family.replace(/"/g, ''), f.status]);
}
"""


def warn(msg: str) -> None:
    print(f"WARN fonts: {msg}", file=sys.stderr)


# ---------------------------------------------------------------- bundled fonts
def _family_index(family: str) -> dict[str, list[list[int]]]:
    """{file: [[start, end], ...]} for one bundled family, from assets/fonts/<family>/index.json."""
    path = FONTS / family / "index.json"
    if not path.is_file():
        raise RuntimeError(f"{path} missing")
    return json.loads(path.read_text(encoding="utf-8"))


def _covers(ranges: list[list[int]], cp: int) -> bool:
    lo, hi = 0, len(ranges) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        a, b = ranges[mid]
        if cp < a:
            hi = mid - 1
        elif cp > b:
            lo = mid + 1
        else:
            return True
    return False


def _unicode_range(cps: list[int]) -> str:
    out, start, prev = [], None, None
    for c in sorted(cps):
        if start is None:
            start = prev = c
        elif c == prev + 1:
            prev = c
        else:
            out.append((start, prev))
            start = prev = c
    if start is not None:
        out.append((start, prev))
    return ",".join(f"U+{a:X}" if a == b else f"U+{a:X}-{b:X}" for a, b in out)


def _subset(path: Path, cps: list[int]) -> bytes:
    from fontTools import subset
    from fontTools.ttLib import TTFont

    opts = subset.Options()
    opts.flavor = "woff2"
    opts.name_IDs = ["*"]  # keep the copyright and OFL notice inside the font
    opts.name_languages = ["*"]
    opts.layout_features = ["*"]
    opts.notdef_outline = True
    font = TTFont(path, recalcTimestamp=False)
    s = subset.Subsetter(options=opts)
    s.populate(unicodes=cps)
    s.subset(font)
    buf = io.BytesIO()
    font.flavor = "woff2"
    font.save(buf)
    return buf.getvalue()


def embed_fonts(svg: str) -> tuple[str, str]:
    """Return (svg with a fresh sd-fonts block, one-line summary). Raises nothing: problems become WARN lines."""
    svg = STYLE_RE.sub("", svg)
    m = re.search(r'<svg\b[^>]*\bdata-fonts="([^"]*)"', svg)
    if not m:
        return svg, ""
    wanted = [f for f in m.group(1).split() if f in FAMILIES]
    root_family = re.search(r'<svg\b[^>]*\bfont-family="([^"]*)"', svg)
    root_chain = html.unescape(root_family.group(1)) if root_family else ""
    indexes: dict[str, dict] = {}
    for fam in wanted:
        try:
            indexes[fam] = _family_index(fam)
        except Exception as e:
            warn(f"{fam} unavailable ({e}); the SVG falls back to system fonts for it")
    # each character goes to the first embedded family in its own font-family chain that has the glyph
    need: dict[str, set[int]] = {f: set() for f in indexes}
    for attrs, body in TEXT_RE.findall(svg):
        fm = FAMILY_ATTR_RE.search(attrs)
        chain = [c.strip().strip("'\"") for c in html.unescape(fm.group(1) if fm else root_chain).split(",")]
        chain = [c for c in chain if c in indexes]
        for ch in set(html.unescape(re.sub(r"<[^>]+>", "", body))):
            cp = ord(ch)
            if ch.isspace() and cp != 0x20:
                continue
            for fam in chain:
                if any(_covers(r, cp) for r in indexes[fam].values()):
                    need[fam].add(cp)
                    break
    faces, total = [], 0
    for fam, cps in need.items():
        if not cps:
            continue
        idx = indexes[fam]
        for fname, ranges in idx.items():
            mine = [c for c in cps if _covers(ranges, c)]
            if not mine:
                continue
            cps = cps - set(mine)
            try:
                data = _subset(FONTS / fam / fname, mine)
            except Exception as e:
                warn(f"{fam}/{fname}: subset failed ({e})")
                continue
            total += len(data)
            faces.append(
                f'@font-face{{font-family:"{fam}";src:url(data:font/woff2;base64,{base64.b64encode(data).decode()}) '
                f'format("woff2");unicode-range:{_unicode_range(mine)};}}')
    if not faces:
        return svg, ""
    style = f'<style class="sd-fonts">{"".join(faces)}</style>'
    svg = svg.replace("<defs>", "<defs>" + style, 1) if "<defs>" in svg else re.sub(r"(<svg\b[^>]*>)", r"\1<defs>" + style + "</defs>", svg, count=1)
    return svg, f"{', '.join(f for f in need if need[f])}: {len(faces)} face(s), {total // 1024 + 1} KB"


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Embed fonts, SVG -> PNG, text-fit check")
    ap.add_argument("svgs", nargs="*", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="output path (only with a single SVG)")
    ap.add_argument("--scale", type=float, default=2)
    ap.add_argument("--no-embed-fonts", action="store_true", help="do not rewrite the SVG with font subsets")
    ap.add_argument("--install-browser", action="store_true")
    a = ap.parse_args()
    if a.install_browser:
        return subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])
    if not a.svgs:
        ap.error("give at least one SVG")
    if a.output and len(a.svgs) > 1:
        ap.error("-o works with a single SVG only")
    for svg in a.svgs:
        if not svg.is_file():
            print(f"ERROR {svg}: not found", file=sys.stderr)
            return 1
    if not a.no_embed_fonts:
        for svg in a.svgs:
            text = svg.read_text(encoding="utf-8")
            new, summary = embed_fonts(text)
            if new != text:
                svg.write_text(new, encoding="utf-8")
            if summary:
                print(f"fonts {svg.name}: {summary}", file=sys.stderr)
    from playwright.sync_api import sync_playwright

    bad = 0
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # browser not installed
            print(f"ERROR cannot launch Chromium ({e.__class__.__name__}). Run: {INSTALL_HINT}", file=sys.stderr)
            return 1
        page = browser.new_page(device_scale_factor=a.scale)
        for svg in a.svgs:
            text = svg.read_text(encoding="utf-8")
            page.set_content('<html><body style="margin:0;background:transparent">' + text + "</body></html>")
            failed = sorted({fam for fam, status in page.evaluate(FONTS_JS) if status == "error"})
            if failed:
                warn(f"{svg.name}: browser could not load embedded {', '.join(failed)}; the PNG uses fallback fonts")
            box = page.locator("svg").first.bounding_box()
            page.set_viewport_size({"width": int(box["width"]) + 1, "height": int(box["height"]) + 1})
            out = a.output or svg.with_suffix(".png")
            page.locator("svg").first.screenshot(path=str(out))
            print(out)
            for o in page.evaluate(MEASURE_JS):
                bad += 1
                print(f"OVERFLOW {svg.name}: {o['text']!r} is {o['width']}px, box allows {o['max']:.0f}px "
                      f"-- shorten it, add a line break, or raise col_width", file=sys.stderr)
        browser.close()
    return 2 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
