#!/usr/bin/env python3
"""Render a diagram spec (JSON) to a themed SVG. Standard library only.

Usage:
    python3 render.py spec.json -o out.svg            # render; lint findings go to stderr
    python3 render.py spec.json -o out.svg --theme brutal   # override the spec's theme
    python3 render.py --extract out.svg               # print the spec embedded in a rendered SVG
    python3 render.py --themes                        # list theme names

Exit codes: 0 ok, 1 bad input, 2 rendered but lint found problems (read stderr, fix the spec, re-run).
Windows: replace python3 with python or py -3.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
THEMES = json.loads((HERE.parent / "themes" / "themes.json").read_text(encoding="utf-8"))
META_RE = re.compile(r'<metadata id="diagram-spec"><!\[CDATA\[(.*?)\]\]></metadata>', re.S)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


# ---------------------------------------------------------------- text metrics
def char_w(ch: str, size: float, latin: float) -> float:
    o = ord(ch)
    if o >= 0x2E80 or 0xFF00 <= o <= 0xFFEF:  # CJK, full-width punctuation
        return size
    if ch == " ":
        return size * min(latin, 0.6)
    return size * latin


def text_w(s: str, size: float, latin: float) -> float:
    return sum(char_w(c, size, latin) for c in s)


NO_LINE_START = set("，。、；：？！）》」』】,.;:?!)]}%")


def is_cjk(ch: str) -> bool:
    o = ord(ch)
    return o >= 0x2E80 or 0xFF00 <= o <= 0xFFEF


def is_orphan(line: str) -> bool:
    """A wrapped last line holding one CJK character (plus closing punctuation), e.g. 「象」 or 「象。」."""
    core = [c for c in line if c not in NO_LINE_START]
    return len(core) == 1 and is_cjk(core[0]) and all(is_cjk(c) or c in NO_LINE_START for c in line)


def _fix_orphan(lines: list[str], size: float, latin: float, maxw: float) -> None:
    """Pull the previous line's last CJK character down so the last line holds at least two."""
    if len(lines) < 2 or not is_orphan(lines[-1]):
        return
    prev = lines[-2]
    k = 1
    while k < len(prev) and prev[-k] in NO_LINE_START:
        k += 1
    moved = prev[-k:]
    if len(prev) - k < 2 or not is_cjk(moved[0]) or not all(is_cjk(c) or c in NO_LINE_START for c in moved):
        return
    if text_w(moved + lines[-1], size, latin) > maxw:
        return
    lines[-2], lines[-1] = prev[:-k].rstrip(), moved + lines[-1]


def wrap(s: str, size: float, latin: float, maxw: float) -> list[str]:
    """Greedy wrap: break at spaces/punctuation for Latin, anywhere for CJK; no single-CJK-character last line."""
    out: list[str] = []
    for para in s.split("\n"):
        lines: list[str] = []
        line = ""
        tokens = re.findall(r"[A-Za-z0-9_\-./:@#()\[\]{}<>=+*&%$!?'\"`~|^]+|\s+|.", para)
        for t in tokens:
            if text_w(line + t, size, latin) <= maxw or not line or t in NO_LINE_START:
                line += t
            else:
                lines.append(line.rstrip())
                line = t.lstrip()
        lines.append(line.rstrip())
        _fix_orphan(lines, size, latin, maxw)
        out.extend(lines)
    return out


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------- spec checks
class SpecError(Exception):
    pass


def load_spec(path: Path) -> dict:
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SpecError(f"{path}: invalid JSON: {e}")
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    return spec


# ---------------------------------------------------------------- layout
class Box:
    __slots__ = ("id", "x", "y", "w", "h", "node", "zone")

    def __init__(self, id, x, y, w, h, node=None, zone=None):
        self.id, self.x, self.y, self.w, self.h, self.node, self.zone = id, x, y, w, h, node, zone

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    @property
    def r(self):
        return self.x + self.w

    @property
    def b(self):
        return self.y + self.h


ROUND_SHAPES = ("circle", "ellipse")
ROUND_TEXT_SHARE = 0.72  # share of an ellipse's width that holds text


def node_metrics(n: dict, th: dict, colw: float) -> tuple[list[str], list[str], float]:
    L = th["layout"]
    latin = th["font"]["latin_w"]
    inner = colw * n.get("span", 1) + L["gap_x"] * (n.get("span", 1) - 1) - 2 * L["card_pad_x"]
    if n.get("shape") == "diamond":
        inner *= 0.62
    elif n.get("shape") in ROUND_SHAPES:
        inner *= ROUND_TEXT_SHARE
    tl = wrap(n.get("title", ""), L["title_size"], latin, inner)
    dl = wrap(n["desc"], L["desc_size"], latin, inner) if n.get("desc") else []
    h = 2 * L["card_pad_y"] + len(tl) * L["title_size"] * 1.3
    if dl:
        h += L["desc_gap"] + len(dl) * L["desc_size"] * 1.45
    if n.get("shape") == "diamond":
        h *= 1.7
    elif n.get("shape") in ROUND_SHAPES:
        h *= 1.35
    return tl, dl, max(h, L["card_min_h"])


def column_width(nodes: list[dict], th: dict) -> float:
    L = th["layout"]
    latin = th["font"]["latin_w"]
    want = L["col_min"]
    for n in nodes:
        if n.get("span", 1) != 1:
            continue
        w = text_w(n.get("title", ""), L["title_size"], latin) + 2 * L["card_pad_x"]
        for line in str(n.get("desc", "")).split("\n"):
            w = max(w, text_w(line, L["desc_size"], latin) + 2 * L["card_pad_x"])
        want = max(want, w)
    return min(math.ceil(want / 4) * 4, L["col_max"])


def layout_layers(spec, th, findings):
    L = th["layout"]
    zones = spec.get("zones") or []
    all_nodes = [n for z in zones for n in z.get("nodes", [])]
    colw = spec.get("col_width") or column_width(all_nodes, th)
    ncols = max([sum(n.get("span", 1) for n in z.get("nodes", [])) for z in zones] + [1])
    gutter = L["gutter"]
    x0 = L["canvas_pad"]
    y = top_offset(spec, th)
    inner_w = ncols * colw + (ncols - 1) * L["gap_x"]
    zone_w = gutter + inner_w + L["zone_pad"]
    boxes, zboxes = {}, []
    for zi, z in enumerate(zones):
        metrics = [node_metrics(n, th, colw) for n in z.get("nodes", [])]
        rowh = max([m[2] for m in metrics] + [L["card_min_h"]])
        zh = rowh + 2 * L["zone_pad"]
        if z.get("desc"):
            need = L["zone_title_size"] * 1.4 + len(wrap(z["desc"], L["desc_size"], th["font"]["latin_w"], gutter - L["zone_pad"] - 8)) * L["desc_size"] * 1.45 + 2 * L["zone_pad"]
            zh = max(zh, need)
        zb = Box(z.get("id", f"zone{zi}"), x0, y, zone_w, zh, zone=z)
        zboxes.append(zb)
        used = sum(n.get("span", 1) for n in z.get("nodes", []))
        shift = 0
        if z.get("align") == "center":
            shift = (ncols - used) * (colw + L["gap_x"]) / 2
        cx = x0 + gutter + shift
        for n, (tl, dl, h) in zip(z.get("nodes", []), metrics):
            span = n.get("span", 1)
            w = colw * span + L["gap_x"] * (span - 1)
            hh = rowh if z.get("equal_height", True) else h
            b = Box(n["id"], cx, y + L["zone_pad"] + (rowh - hh) / 2, w, hh, node=n)
            b.node["_lines"] = (tl, dl)
            boxes[n["id"]] = b
            cx += w + L["gap_x"]
        y += zh + L["zone_gap"]
    return boxes, zboxes, x0 + zone_w, y - L["zone_gap"]


def layout_grid(spec, th, findings):
    L = th["layout"]
    nodes = spec.get("nodes") or []
    colw = spec.get("col_width") or column_width(nodes, th)
    gx, gy = L["grid_gap_x"], L["grid_gap_y"]
    metrics = {n["id"]: node_metrics(n, th, colw) for n in nodes}
    rows = {}
    for n in nodes:
        rows.setdefault(n.get("row", 0), []).append(n)
    row_h = {r: max(metrics[n["id"]][2] for n in ns) for r, ns in rows.items()}
    groups = spec.get("groups") or []
    gpad = L["zone_pad"]
    top_extra = (L["zone_title_size"] * 1.6) if groups else 0
    x0 = L["canvas_pad"] + (gpad if groups else 0)
    y_cursor = top_offset(spec, th) + (gpad + top_extra if groups else 0)
    row_y = {}
    for r in range(0, max(rows) + 1 if rows else 0):
        row_y[r] = y_cursor
        y_cursor += row_h.get(r, L["card_min_h"]) + gy
    boxes = {}
    for n in nodes:
        tl, dl, h = metrics[n["id"]]
        span = n.get("span", 1)
        w = colw * span + gx * (span - 1)
        r, c = n.get("row", 0), n.get("col", 0)
        rh = row_h[r]
        b = Box(n["id"], x0 + c * (colw + gx), row_y[r] + (rh - h) / 2, w, h, node=n)
        n["_lines"] = (tl, dl)
        boxes[n["id"]] = b
    zboxes = []
    for gi, g in enumerate(groups):
        members = [boxes[i] for i in g.get("nodes", []) if i in boxes]
        missing = [i for i in g.get("nodes", []) if i not in boxes]
        if missing:
            findings.append(f"group {g.get('title')!r}: unknown node ids {missing}")
        if not members:
            continue
        gx0 = min(b.x for b in members) - gpad
        gy0 = min(b.y for b in members) - gpad - top_extra
        gx1 = max(b.r for b in members) + gpad
        gy1 = max(b.b for b in members) + gpad
        zboxes.append(Box(g.get("id", f"group{gi}"), gx0, gy0, gx1 - gx0, gy1 - gy0, zone=dict(g, _grid=True)))
    right = max([b.r for b in boxes.values()] + [z.r for z in zboxes] + [0])
    bottom = max([b.b for b in boxes.values()] + [z.b for z in zboxes] + [0])
    return boxes, zboxes, right, bottom


def layout_sequence(spec, th, findings):
    """Participants in a row on top, lifelines down, messages stacked top to bottom."""
    L = th["layout"]
    parts = spec.get("participants") or []
    colw = spec.get("col_width") or column_width(parts, th)
    gap = L["grid_gap_x"]
    x0, y0 = L["canvas_pad"], top_offset(spec, th)
    metrics = [node_metrics(n, th, colw) for n in parts]
    head_h = max([m[2] for m in metrics] + [L["card_min_h"]])
    boxes = {}
    for i, (n, (tl, dl, _)) in enumerate(zip(parts, metrics)):
        n["_lines"] = (tl, dl)
        boxes[n["id"]] = Box(n["id"], x0 + i * (colw + gap), y0, colw, head_h, node=n)
    step = L["grid_gap_y"] * 0.8
    msgs = spec.get("messages") or []
    bottom = y0 + head_h + step * (len(msgs) + 0.6)
    right = x0 + len(parts) * (colw + gap) - gap
    for i, m in enumerate(msgs):  # a self-call label sticks out to the right of its lifeline
        b = boxes.get(m.get("from"))
        if b and m.get("from") == m.get("to") and m.get("label"):
            right = max(right, b.cx + 36 + text_w(f"{i + 1}. {m['label']}", L["label_size"], th["font"]["latin_w"]))
    return boxes, [], right, bottom




def top_offset(spec, th):
    L = th["layout"]
    y = L["canvas_pad"]
    if spec.get("title"):
        y += L["diagram_title_size"] * 1.3
    if spec.get("subtitle"):
        y += L["desc_size"] * 1.6 + (th["title_rule"] + 10 if th.get("title_rule") else 0)
    return y + (L["title_gap"] if spec.get("title") else 0)


# ---------------------------------------------------------------- edge routing
DETOUR_GAP = 20  # px between a detouring edge and the cards it goes around; draw_edges passes half the
# theme's zone_pad instead, so a detour runs between card and zone border rather than on the border


def _route_candidates(a: Box, b: Box, mode: str, blockers: list, gap: float = DETOUR_GAP) -> list[list[tuple[float, float]]]:
    """Paths from a to b, the plain default first; the rest are tried only when the default crosses a card."""
    ov_x = min(a.r, b.r) - max(a.x, b.x)
    ov_y = min(a.b, b.b) - max(a.y, b.y)
    right, down = b.cx > a.cx, b.cy > a.cy
    sx, ex = (a.r, b.x) if right else (a.x, b.r)  # facing sides
    sy, ey = (a.b, b.y) if down else (a.y, b.b)  # facing top / bottom
    if ov_y > 8 and (b.x >= a.r or a.x >= b.r):  # side by side
        y = max(a.y, b.y) + ov_y / 2
        out = [[(sx, y), (ex, y)]]
        if blockers:  # go over or under the cards in between
            top = min(o.y for o in blockers) - gap
            bot = max(o.b for o in blockers) + gap
            out += [[(a.cx, a.y), (a.cx, top), (b.cx, top), (b.cx, b.y)],
                    [(a.cx, a.b), (a.cx, bot), (b.cx, bot), (b.cx, b.b)]]
        return out
    if ov_x > 8:  # stacked
        x = max(a.x, b.x) + ov_x / 2
        out = [[(x, sy), (x, ey)]]
        if blockers:  # go round the right or left of the cards in between
            rx = max([a.r, b.r] + [o.r for o in blockers]) + gap
            lx = min([a.x, b.x] + [o.x for o in blockers]) - gap
            out += [[(a.r, a.cy), (rx, a.cy), (rx, b.cy), (b.r, b.cy)],
                    [(a.x, a.cy), (lx, a.cy), (lx, b.cy), (b.x, b.cy)]]
        return out
    hv = [(sx, a.cy), (b.cx, a.cy), (b.cx, ey)]  # leave sideways, enter top / bottom
    vh = [(a.cx, sy), (a.cx, b.cy), (ex, b.cy)]  # leave top / bottom, enter sideways
    zv = lambda my: [(a.cx, sy), (a.cx, my), (b.cx, my), (b.cx, ey)]
    zh = lambda mx: [(sx, a.cy), (mx, a.cy), (mx, b.cy), (ex, b.cy)]
    near = lambda s, e: (s + (e - s) * 0.2, e - (e - s) * 0.2)
    out = [hv] if mode == "grid" and abs(a.cy - b.cy) < abs(a.cx - b.cx) else [zv((sy + ey) / 2)]
    out += [hv, vh, zv((sy + ey) / 2), *map(zv, near(sy, ey))]
    if b.x >= a.r or a.x >= b.r:  # a horizontal gap exists between the two cards
        out += [zh((sx + ex) / 2), *map(zh, near(sx, ex))]
    return out


def route(a: Box, b: Box, mode: str, obstacles=None, soft=(), gap: float = DETOUR_GAP) -> list[tuple[float, float]]:
    """Orthogonal path from a to b. With `obstacles` (all boxes), the first candidate path that crosses
    no third card wins; `soft` boxes (zone titles, the diagram header) are avoided too when some path allows,
    never at the price of crossing a card. When every candidate crosses a card, the default comes back and
    the caller lints it. Paths leaving the canvas (negative x / y) are never picked."""
    cards = [o for o in (obstacles or []) if o is not a and o is not b]
    hits = lambda pts, boxes: [o for o in boxes if any(seg_hits_box(p, q, o) for p, q in zip(pts, pts[1:]))]
    first = _route_candidates(a, b, mode, [])[0]
    blockers = hits(first, cards + list(soft))
    if not blockers:
        return first
    cands = [pts for pts in _route_candidates(a, b, mode, [o for o in blockers if o in cards] or blockers, gap)[1:]
             if min(min(p) for p in pts) >= 4]
    for pts in cands:
        if not hits(pts, cards + list(soft)):
            return pts
    if not hits(first, cards):
        return first
    for pts in cands:
        if not hits(pts, cards):
            return pts
    return first


def seg_hits_box(p, q, box: Box, pad=2) -> bool:
    x0, x1 = sorted((p[0], q[0]))
    y0, y1 = sorted((p[1], q[1]))
    return x1 > box.x + pad and x0 < box.r - pad and y1 > box.y + pad and y0 < box.b - pad



# ---------------------------------------------------------------- geometry
# A shape is a list of cubic segments (p0, c1, c2, p3). Crisp themes print it as one path. Themes with
# "rough" redraw every segment twice with small seeded offsets and fill one wobbly outline -- the way
# Excalidraw's hand-drawn export draws -- so the wobble is real geometry, not a filter, and the same
# spec always produces byte-identical SVG.
K_QUAD = 2 / 3      # Excalidraw's corner: a quadratic curve through the corner point
K_CIRCLE = 0.5523   # quarter circle, for pill ends


def _lerp(p, q, t):
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)


def _dist(p, q):
    return math.hypot(q[0] - p[0], q[1] - p[1])


def _towards(p, q, d):
    """Move from p toward q by d (never past q)."""
    L = _dist(p, q)
    return q if L <= d else _lerp(p, q, d / L) if L else p


def _p(pt):
    return f"{pt[0]:.2f},{pt[1]:.2f}"


def line_seg(p, q):
    return (p, _lerp(p, q, 1 / 3), _lerp(p, q, 2 / 3), q)


def round_poly(pts, r, k=K_QUAD):
    """Closed polygon with every corner cut back by r along both edges and joined by a curve."""
    n, cuts = len(pts), []
    for i, c in enumerate(pts):
        prev, nxt = pts[i - 1], pts[(i + 1) % n]
        rr = min(r, _dist(c, prev) / 2, _dist(c, nxt) / 2)
        cuts.append((_towards(c, prev, rr), c, _towards(c, nxt, rr)))
    segs = []
    for i, (a, c, b) in enumerate(cuts):
        if _dist(a, b) > 0.01:
            segs.append((a, _lerp(a, c, k), _lerp(b, c, k), b))
        na = cuts[(i + 1) % n][0]
        if _dist(b, na) > 0.01:
            segs.append(line_seg(b, na))
    return segs


def rect_segs(x, y, w, h, r, k=K_QUAD):
    return round_poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], r, k)


def ellipse_segs(cx, cy, rx, ry):
    """Four quarter arcs, clockwise from the right-most point."""
    kx, ky = rx * K_CIRCLE, ry * K_CIRCLE
    e, s_, w, n = (cx + rx, cy), (cx, cy + ry), (cx - rx, cy), (cx, cy - ry)
    return [(e, (cx + rx, cy + ky), (cx + kx, cy + ry), s_), (s_, (cx - kx, cy + ry), (cx - rx, cy + ky), w),
            (w, (cx - rx, cy - ky), (cx - kx, cy - ry), n), (n, (cx + kx, cy - ry), (cx + rx, cy - ky), e)]


def corner_radius(spec, w, h):
    """`radius` is a fixed radius, or the cap when `radius_ratio` is set (Excalidraw: 25% of the short side, at most 32)."""
    r = spec.get("radius", 0)
    ratio = spec.get("radius_ratio")
    return min(r, ratio * min(w, h)) if ratio else r


def seg_path(segs, closed=True):
    d = "M" + _p(segs[0][0]) + "".join(f" C{_p(c1)} {_p(c2)} {_p(p3)}" for _, c1, c2, p3 in segs)
    return d + (" Z" if closed else "")


class Rnd:
    """xorshift32 seeded from the element key with crc32, so re-renders are deterministic."""

    def __init__(self, key: str):
        self.s = zlib.crc32(key.encode("utf-8")) or 1

    def __call__(self) -> float:
        s = self.s
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= s >> 17
        s ^= (s << 5) & 0xFFFFFFFF
        self.s = s
        return s / 4294967296

    def jit(self, p, a):
        return (p[0] + (self() * 2 - 1) * a, p[1] + (self() * 2 - 1) * a)


def _rough_pass(segs, rnd, amp, ends):
    out = []
    for p0, c1, c2, p3 in segs:
        a = min(amp, _dist(p0, p3) / 20 + 0.5)  # short segments (corners, arrowheads) wobble less
        out.append(f"M{_p(rnd.jit(p0, a * ends))} C{_p(rnd.jit(c1, a))} {_p(rnd.jit(c2, a))} {_p(rnd.jit(p3, a * ends))}")
    return " ".join(out)


def _rough_fill(segs, rnd, amp):
    d = "M" + _p(segs[0][0])
    for p0, c1, c2, p3 in segs:
        a = min(amp * 2, _dist(p0, p3) / 12 + 0.5)
        d += f" C{_p(rnd.jit(c1, a))} {_p(rnd.jit(c2, a))} {_p(p3)}"
    return d + " Z"


def draw_shape(segs, th, key, fill="none", stroke="none", sw=1.0, dash=None, closed=True, opacity=None, ends=0.0):
    """One shape, crisp or rough. `ends` > 0 also wobbles segment end points (open lines)."""
    op = f' opacity="{opacity}"' if opacity is not None else ""
    da = f' stroke-dasharray="{dash}"' if dash else ""
    has_stroke = stroke not in (None, "none")
    R = th.get("rough")
    if not R:
        st = f' stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round" stroke-linecap="round"' if has_stroke else ""
        return f'<path d="{seg_path(segs, closed)}" fill="{fill if closed else "none"}"{st}{da}{op}/>'
    rnd, amp = Rnd(key), R.get("amp", 2)
    parts = []
    if closed and fill not in (None, "none"):
        parts.append(f'<path d="{_rough_fill(segs, rnd, amp)}" fill="{fill}"/>')
    if has_stroke:
        d = _rough_pass(segs, rnd, amp, ends)
        if not dash:  # dashed strokes get one pass, like Excalidraw; two would fill the gaps
            d += " " + _rough_pass(segs, rnd, amp, ends)
        parts.append(f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{sw}" stroke-linecap="round"{da}/>')
    s = "".join(parts)
    return f"<g{op}>{s}</g>" if op else s


def arrow_head(tip, frm, th, color, sw, key):
    """Filled triangle that is also stroked with round joins, as Excalidraw draws it."""
    E = th["edge"]
    length = E.get("head", 13)
    half = length * E.get("head_ratio", 0.46)
    d = _dist(frm, tip) or 1
    ux, uy = (tip[0] - frm[0]) / d, (tip[1] - frm[1]) / d
    bx, by = tip[0] - ux * length, tip[1] - uy * length
    b1, b2 = (bx - uy * half, by + ux * half), (bx + uy * half, by - ux * half)
    if th.get("rough"):
        segs = [line_seg(tip, b1), line_seg(b1, b2), line_seg(b2, tip)]
        return draw_shape(segs, th, key, fill=color, stroke=color, sw=sw, ends=0.4)
    return f'<path d="M{_p(tip)} L{_p(b1)} L{_p(b2)} Z" fill="{color}" stroke="{color}" stroke-width="{sw}" stroke-linejoin="round"/>'


def draw_arrow(pts, th, color, width, key, dashed=False, both=False):
    """Polyline plus explicit arrowheads. The tip stops just short of the target outline."""
    E = th["edge"]
    head = E.get("head", 13)
    pts = list(pts)
    gap = width / 2 + 1
    pts[-1] = _towards(pts[-1], pts[-2], gap)
    if both:
        pts[0] = _towards(pts[0], pts[1], gap)
    line = list(pts)
    line[-1] = _towards(line[-1], line[-2], head * 0.6)  # end inside the head so a dash never pokes through
    if both:
        line[0] = _towards(line[0], line[1], head * 0.6)
    segs = [line_seg(p, q) for p, q in zip(line, line[1:]) if _dist(p, q) > 0.01]
    dash = E.get("dash", "8 8") if dashed else None
    out = draw_shape(segs, th, key, stroke=color, sw=width, dash=dash, closed=False, ends=0.6) if segs else ""
    out += arrow_head(pts[-1], pts[-2], th, color, width, key + ">")
    if both:
        out += arrow_head(pts[0], pts[1], th, color, width, key + "<")
    return out


# ---------------------------------------------------------------- sequence
def draw_sequence(spec, th, boxes, bottom, findings):
    """Lifelines and message arrows; returns (body, labels, label holes)."""
    E, L = th["edge"], th["layout"]
    body, labels = [], []
    for b in boxes.values():
        body.append(f'<path d="M{b.cx:.1f},{b.b:.1f} L{b.cx:.1f},{bottom:.1f}" stroke="{th["zone"].get("dash_stroke", E["color"])}" stroke-width="1" stroke-dasharray="4 4" fill="none"/>')
    if not boxes:
        return body, labels, []
    step = L["grid_gap_y"] * 0.8
    y = max(b.b for b in boxes.values()) + step * 0.8
    ls = L["label_size"]
    for i, m in enumerate(spec.get("messages") or []):
        a, b = boxes.get(m.get("from")), boxes.get(m.get("to"))
        if not a or not b:
            findings.append(f"message {i} ({m.get('from')}->{m.get('to')}): unknown participant id")
            continue
        col = E["color"]
        if m.get("accent"):
            col = role_style(th, m["accent"] if isinstance(m["accent"], str) else "primary", findings, f"message {i}").get("accent", col)
        if a is b:  # self call: small loop on the right
            x, w = a.cx, 32
            pts = [(x, y - 9), (x + w, y - 9), (x + w, y + 9), (x, y + 9)]
            lx, anchor = x + w + 10, "start"
        else:
            pts = [(a.cx, y), (b.cx, y)]
            lx, anchor = (a.cx + b.cx) / 2, "middle"
        body.append(draw_arrow(pts, th, col, E["width"], f"msg{i}", dashed=m.get("dashed")))
        if m.get("label"):
            num = f'{i + 1}. ' if spec.get("numbered", True) else ""
            text = num + m["label"]
            ly = y - ls * 0.95 if a is not b else y
            labels.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="{ls}" fill="{th["edge_label"]["text"]}" text-anchor="{anchor}" dominant-baseline="central" stroke="{th["bg"]}" stroke-width="5" stroke-linejoin="round" paint-order="stroke">{esc(text)}</text>')
            if a is not b and text_w(text, ls, th["font"]["latin_w"]) > abs(b.cx - a.cx) - 12:
                findings.append(f"message label {text!r} is wider than the gap between its lifelines; shorten it or raise col_width")
        y += step
    return body, labels, []


# ---------------------------------------------------------------- drawing
def role_style(th, role, findings, where):
    roles = th["roles"]
    if role not in roles:
        findings.append(f"{where}: unknown role {role!r}; known: {', '.join(roles)}")
        role = "plain"
    return roles[role]


def shape_segs(n, b: Box, th):
    shape = n.get("shape", "card")
    C = th["card"]
    if shape == "diamond":
        pts = [(b.cx, b.y), (b.r, b.cy), (b.cx, b.b), (b.x, b.cy)]
        cut = _dist(pts[0], pts[1]) * 0.25 if C.get("radius_ratio") else C.get("radius", 0) * 1.2
        return round_poly(pts, cut)
    if shape == "pill":
        return rect_segs(b.x, b.y, b.w, b.h, b.h / 2, K_CIRCLE)
    if shape in ROUND_SHAPES:
        return ellipse_segs(b.cx, b.cy, b.w / 2, b.h / 2)
    return rect_segs(b.x, b.y, b.w, b.h, corner_radius(C, b.w, b.h))


def draw_node(n, b: Box, th, findings):
    L, F = th["layout"], th["font"]
    st = role_style(th, n.get("role", "plain"), findings, f"node {n['id']!r}")
    dashed = n.get("dashed") or st.get("dashed")
    C = th["card"]
    sw = C.get("dash_width", C["stroke_width"]) if dashed else C["stroke_width"]
    sw = st.get("stroke_width", sw)  # roles told apart by line weight (ligne)
    dash = st.get("dash") or (C.get("dash", "8 9") if dashed else None)
    bare = n.get("shape") == "text"  # free text: no outline, no shadow
    back, parts = [], []
    shadow = th.get("shadow", {})
    kind = shadow.get("kind")
    key = f"node:{n['id']}"
    # back layer: offset shadow (mac: faint, brutal: solid) or isometric side face
    if kind == "offset" and not dashed and not bare:
        sb = Box("", b.x + shadow.get("dx", 0), b.y + shadow.get("dy", 0), b.w, b.h)
        back.append(draw_shape(shape_segs(n, sb, th), th, key + ":sh", fill=shadow["color"], opacity=shadow.get("opacity", 1)))
    if kind == "extrude" and not dashed and n.get("shape", "card") == "card":
        d = shadow["depth"]
        side = st.get("side", shadow.get("color", "#d1d1d6"))
        pts = [(b.r, b.y + 4), (b.r + d, b.y + 4 + d), (b.r + d, b.b + d), (b.x + 4 + d, b.b + d), (b.x + 4, b.b), (b.r, b.b)]
        back.append(draw_shape(round_poly(pts, 0), th, key + ":side", fill=side, stroke=st["stroke"], sw=sw))
    if not bare:
        parts.append(draw_shape(shape_segs(n, b, th), th, key, fill=st["fill"], stroke=st.get("stroke"), sw=sw, dash=dash))
    if C.get("accent_bar") and not dashed and not bare:  # swiss
        parts.append(f'<rect x="{b.x:.1f}" y="{b.y:.1f}" width="{C["accent_bar"]}" height="{b.h:.1f}" fill="{st.get("accent", st["stroke"])}"/>')
    # text
    tl, dl = n.get("_lines", ([n.get("title", "")], []))
    ts, ds = L["title_size"], L["desc_size"]
    block = len(tl) * ts * 1.3 + ((L["desc_gap"] + len(dl) * ds * 1.45) if dl else 0)
    align = C.get("text_align", "middle")
    if n.get("shape") in ("diamond", "pill", "text") + ROUND_SHAPES:
        align = "middle"
    tx = b.cx if align == "middle" else b.x + L["card_pad_x"] + (C.get("accent_bar") or 0)
    maxw = b.w - 2 * L["card_pad_x"] + 2
    if n.get("shape") == "diamond":
        maxw = b.w * 0.62 + 4
    elif n.get("shape") in ROUND_SHAPES:
        maxw = b.w * ROUND_TEXT_SHARE + 4
    elif bare:
        maxw = b.w + 2
    for line, size in [(l, ts) for l in tl] + [(l, ds) for l in dl]:
        if text_w(line, size, F["latin_w"]) > maxw * 1.05:
            findings.append(f"node {n['id']!r}: {line!r} is wider than its card and has no break point; shorten it, add \\n, or raise col_width")
    for lines, src in ((tl, n.get("title", "")), (dl, n.get("desc") or "")):
        authored = {p.strip() for p in str(src).split("\n")}  # a short line the author put after \n is intended
        for prev, line in zip(lines, lines[1:]):
            if is_orphan(line) and line not in authored:
                findings.append(f"node {n['id']!r}: line {line!r} after {prev!r} is a single character on its own line; reword, add \\n earlier, or raise col_width")
    y = b.cy - block / 2
    tcol = st.get("text", th["text"]["title"]) if not bare else th["text"]["title"]
    dcol = st.get("desc", th["text"]["desc"]) if not bare else th["text"]["desc"]
    for line in tl:
        y += ts * 1.3 / 2
        parts.append(
            f'<text x="{tx:.1f}" y="{y:.1f}" font-size="{ts}" font-weight="{F["title_weight"]}" fill="{tcol}" '
            f'text-anchor="{align}" dominant-baseline="central" data-maxw="{maxw:.0f}">{esc(line)}</text>')
        y += ts * 1.3 / 2
    if dl:
        y += L["desc_gap"]
        for line in dl:
            y += ds * 1.45 / 2
            parts.append(
                f'<text x="{tx:.1f}" y="{y:.1f}" font-size="{ds}" fill="{dcol}" text-anchor="{align}" '
                f'dominant-baseline="central" data-maxw="{maxw:.0f}">{esc(line)}</text>')
            y += ds * 1.45 / 2
    return "".join(back), "".join(parts)


def draw_zone(zb: Box, th):
    z, L, Z = zb.zone, th["layout"], th["zone"]
    parts = []
    dashed = z.get("dashed")
    key = f"zone:{zb.id}"
    if Z.get("style") == "rule":  # swiss: heavy top rule, no box
        parts.append(f'<rect x="{zb.x}" y="{zb.y}" width="{zb.w}" height="{Z["rule"]}" fill="{Z["stroke"]}"/>')
    else:
        segs = rect_segs(zb.x, zb.y, zb.w, zb.h, corner_radius(Z, zb.w, zb.h))
        if dashed:
            parts.append(draw_shape(segs, th, key, stroke=Z.get("dash_stroke", "#aeaeb2"), sw=1.5, dash="8 9"))
        else:
            parts.append(draw_shape(segs, th, key, fill=Z["fill"], stroke=Z.get("stroke"), sw=Z.get("stroke_width", 1)))
    ts = L["zone_title_size"]
    tx, ty = zb.x + L["zone_pad"], zb.y + L["zone_pad"] + ts * 0.7
    if Z.get("style") == "rule":
        ty = zb.y + Z["rule"] + L["zone_pad"] * 0.5 + ts * 0.7
    if Z.get("highlight") and z.get("title"):  # sketchnote: marker swipe behind the title
        w = text_w(z["title"], ts, th["font"]["latin_w"]) + 12
        hl = draw_shape(rect_segs(tx - 6, ty - ts * 0.55, w, ts * 1.1, 3), th, key + ":hl", fill=Z["highlight"])
        parts.append(f'<g transform="rotate(-1 {tx:.1f} {ty:.1f})">{hl}</g>')
    if z.get("title"):
        parts.append(f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="{ts}" font-weight="{th["font"]["zone_weight"]}" fill="{th["text"]["zone"]}" dominant-baseline="central">{esc(z["title"])}</text>')
    if z.get("desc") and not z.get("_grid"):
        maxw = L["gutter"] - L["zone_pad"] - 8
        y = ty + ts * 0.9
        for line in wrap(z["desc"], L["desc_size"], th["font"]["latin_w"], maxw):
            y += L["desc_size"] * 1.45 / 2
            parts.append(f'<text x="{tx:.1f}" y="{y:.1f}" font-size="{L["desc_size"]}" fill="{th["text"]["desc"]}" dominant-baseline="central" data-maxw="{maxw:.0f}">{esc(line)}</text>')
            y += L["desc_size"] * 1.45 / 2
    return "".join(parts)


def zone_title_boxes(zboxes, th) -> list:
    """Boxes around zone titles; edges route around them so a line never strikes through a title."""
    L, Z, out = th["layout"], th["zone"], []
    ts = L["zone_title_size"]
    for zb in zboxes:
        if not zb.zone.get("title"):
            continue
        ty = zb.y + (Z["rule"] + L["zone_pad"] * 0.5 if Z.get("style") == "rule" else L["zone_pad"]) + ts * 0.7
        out.append(Box(f"title:{zb.id}", zb.x + L["zone_pad"] - 4, ty - ts * 0.65, text_w(zb.zone["title"], ts, th["font"]["latin_w"]) + 8, ts * 1.3))
    return out


def header_box(spec, th) -> list:
    """The diagram title and subtitle band, for edges to route around."""
    if not (spec.get("title") or spec.get("subtitle")):
        return []
    return [Box("header", 0, 0, 1e5, top_offset(spec, th) - th["layout"].get("title_gap", 0) / 2)]


def draw_edges(spec, th, boxes, mode, findings, avoid=(), extent=None):
    """Returns (edge paths, label svg, label holes). A `gap` label sits in a hole cut out of the edges.
    `avoid`: extra boxes (zone titles) routing steers around; `extent`: dict that receives the right / bottom
    reached by edges and labels, so a detour outside the cards still fits on the canvas."""
    E, Lb = th["edge"], th["edge_label"]
    body, labels, holes, label_boxes, tips = [], [], [], [], {}
    ext = extent if extent is not None else {}
    for i, e in enumerate(spec.get("edges") or []):
        a, b = boxes.get(e.get("from")), boxes.get(e.get("to"))
        if not a or not b:
            findings.append(f"edge {i} ({e.get('from')}->{e.get('to')}): unknown node id")
            continue
        pts = route(a, b, mode, list(boxes.values()), avoid, th["layout"]["zone_pad"] / 2)
        ext["right"] = max([ext.get("right", 0)] + [p[0] for p in pts])
        ext["bottom"] = max([ext.get("bottom", 0)] + [p[1] for p in pts])
        tip = (round(pts[-1][0] / 6), round(pts[-1][1] / 6))  # arrowheads within ~6px draw as one blob
        if tip in tips:
            findings.append(f"edges {tips[tip]} and {e['from']}->{e['to']} end at the same point, their arrowheads stack; move one source to another row/col, or merge them")
        tips.setdefault(tip, f"{e['from']}->{e['to']}")
        for p, q in zip(pts, pts[1:]):
            for other in boxes.values():
                if other is a or other is b:
                    continue
                if seg_hits_box(p, q, other):
                    findings.append(f"edge {e['from']}->{e['to']} crosses node {other.id!r}; reorder nodes or use grid layout")
        col = E["color"]
        if e.get("accent"):
            col = role_style(th, e["accent"] if isinstance(e["accent"], str) else "primary", findings, f"edge {i}").get("accent", E["color"])
        width = E["width"] * (1.5 if e.get("accent") and E.get("accent_wider") else 1)
        body.append(draw_arrow(pts, th, col, width, f"edge:{e['from']}>{e['to']}:{i}", dashed=e.get("dashed"), both=e.get("both")))
        if e.get("label"):
            segs = sorted(zip(pts, pts[1:]), key=lambda s: -(abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1])))
            ls = th["layout"]["label_size"]
            tw = text_w(e["label"], ls, th["font"]["latin_w"])
            chip = Lb.get("style") == "chip"
            w, h = tw + (16 if chip else 12), ls * (1.7 if chip else 1.5)
            # on the line at a segment midpoint, longest segment first; then beside the line (a detour runs
            # close to the cards it goes round, leaving no room on it); else on the longest segment
            spots = [((p[0] + q[0]) / 2, (p[1] + q[1]) / 2) for p, q in segs]
            for p, q in segs:
                mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
                if abs(p[0] - q[0]) < 1:  # vertical: left or right of it
                    spots += [(mx + w / 2 + 6, my), (mx - w / 2 - 6, my)]
                else:  # horizontal: above or below it
                    spots += [(mx, my - h / 2 - 4), (mx, my + h / 2 + 4)]
            clear = lambda bx: bx.x >= 0 and not any(seg_hits_box((bx.x, bx.y), (bx.r, bx.b), o, pad=0) for o in list(boxes.values()) + label_boxes)
            for mx, my in spots + spots[:1]:
                lb = Box("", mx - w / 2, my - h / 2, w, h)
                if clear(lb):
                    break
            ext["right"] = max(ext.get("right", 0), lb.r)
            ext["bottom"] = max(ext.get("bottom", 0), lb.b)
            for other in boxes.values():
                if seg_hits_box((lb.x, lb.y), (lb.r, lb.b), other, pad=0):
                    findings.append(f"label {e['label']!r} overlaps node {other.id!r}; shorten the label or leave an empty row/col between the nodes")
            for ob in label_boxes:
                if seg_hits_box((lb.x, lb.y), (lb.r, lb.b), ob, pad=0):
                    findings.append(f"label {e['label']!r} overlaps another label")
            label_boxes.append(lb)
            if chip:
                labels.append(f'<rect x="{lb.x:.1f}" y="{lb.y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{Lb.get("radius", 4)}" fill="{Lb["fill"]}" stroke="{Lb.get("stroke", Lb["fill"])}" stroke-width="1"/>')
            else:
                holes.append(f'<rect x="{lb.x:.1f}" y="{lb.y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="4" fill="#000"/>')
            labels.append(f'<text x="{mx:.1f}" y="{my:.1f}" font-size="{ls}" fill="{Lb["text"]}" text-anchor="middle" dominant-baseline="central">{esc(e["label"])}</text>')
    return body, labels, holes


def draw_legend(spec, th, x, y, findings):
    items = spec.get("legend")
    if not items:
        return "", 0
    L = th["layout"]
    ls = L["label_size"]
    latin = th["font"]["latin_w"]
    my = y + ls * 0.6
    parts = [f'<text x="{x}" y="{my:.1f}" font-size="{ls}" font-weight="{th["font"]["zone_weight"]}" fill="{th["text"]["zone"]}" dominant-baseline="central">图例</text>']
    cx = x + text_w("图例", ls, latin) + 20
    sw_w, sw_h = ls * 1.5, ls * 1.15
    for k, it in enumerate(items):
        if "edge" in it:
            parts.append(draw_arrow([(cx, my), (cx + 40, my)], th, th["edge"]["color"], th["edge"]["width"], f"legend:{k}", dashed=it["edge"] == "dashed"))
            cx += 50
        else:
            st = role_style(th, it.get("role", "plain"), findings, "legend")
            dash = st.get("dash") or ("4 3" if st.get("dashed") else None)
            stroke = st["stroke"] if st.get("stroke") not in (None, "none") else st["fill"]
            segs = rect_segs(cx, my - sw_h / 2, sw_w, sw_h, min(corner_radius(th["card"], sw_w, sw_h), 6))
            parts.append(draw_shape(segs, th, f"legend:{k}", fill=st["fill"], stroke=stroke, sw=min(st.get("stroke_width", 1), 2.5), dash=dash))
            cx += sw_w + 8
        parts.append(f'<text x="{cx:.1f}" y="{my:.1f}" font-size="{ls}" fill="{th["text"]["desc"]}" dominant-baseline="central">{esc(it["label"])}</text>')
        cx += text_w(it["label"], ls, latin) + 28
    return "".join(parts), cx


def draw_code(spec, th, x, y):
    blocks = spec.get("code") or []
    if not blocks:
        return "", y, x
    C, L = th["code"], th["layout"]
    size = L["desc_size"]
    parts, right = [], x
    for k, blk in enumerate(blocks):
        lines = [blk["title"]] + blk.get("lines", []) if blk.get("title") else blk.get("lines", [])
        w = max(text_w(l, size, 0.6) for l in lines) + 40
        h = len(lines) * size * 1.5 + (44 if C.get("dots") else 30)
        r = min(C["radius"], 0.25 * min(w, h))
        parts.append(draw_shape(rect_segs(x, y, w, h, r), th, f"code:{k}", fill=C["bg"], stroke=C["stroke"], sw=1))
        if C.get("dots"):
            for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
                parts.append(f'<circle cx="{x + 18 + i * 15}" cy="{y + 16}" r="4.5" fill="{c}"/>')
        ty = y + (30 if C.get("dots") else 15)
        for i, l in enumerate(lines):
            ty += size * 1.5 / 2
            col = C["comment"] if (i == 0 and blk.get("title")) or l.lstrip().startswith(("//", "#", "--")) else C["text"]
            parts.append(f'<text x="{x + 20}" y="{ty:.1f}" font-size="{size}" fill="{col}" font-family="{esc(th["font"]["code"])}" dominant-baseline="central" xml:space="preserve">{esc(l)}</text>')
            ty += size * 1.5 / 2
        right = max(right, x + w)
        y += h + L["zone_gap"]
    return "".join(parts), y - L["zone_gap"], right


# Layout keys in priority order. The first three are drawn here; the rest live in layouts.py.
LAYOUT_KEYS = ("zones", "nodes", "participants", "tree", "lanes", "tasks", "entities", "matrix", "canvas")
BASE_MODES = {"zones": "layers", "nodes": "grid", "participants": "sequence"}


def _extra():
    """layouts.py imports helpers from this file; register it under its module name first, so running
    render.py as a script does not load a second copy of it."""
    sys.modules.setdefault("render", sys.modules[__name__])
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import layouts
    return layouts


def _strip_lines(o):
    """Drop the wrapped-line cache render.py adds to node dicts, at any depth (tree children nest)."""
    if isinstance(o, dict):
        o.pop("_lines", None)
        for v in o.values():
            _strip_lines(v)
    elif isinstance(o, list):
        for v in o:
            _strip_lines(v)


def render(spec: dict, theme_name: str | None = None) -> tuple[str, list[str]]:
    findings: list[str] = []
    name = theme_name or spec.get("theme") or "mac"
    if name not in THEMES:
        raise SpecError(f"unknown theme {name!r}; known: {', '.join(THEMES)}")
    th = THEMES[name]
    L, F = th["layout"], th["font"]
    present = [k for k in LAYOUT_KEYS if spec.get(k)]
    if len(present) > 1:
        findings.append(f"more than one layout key {present}: drew {present[0]!r}, ignored {present[1:]}; one diagram takes one layout, split the rest into another spec")
    if not present:
        findings.append(f"no layout key: give one of {', '.join(LAYOUT_KEYS)}; a misspelled key (e.g. 'node', 'zone') or an empty list draws nothing")
    key = present[0] if present else "nodes"
    mode = BASE_MODES.get(key, key)
    extra = None if mode in BASE_MODES.values() else _extra()
    if mode == "layers":
        all_nodes = [n for z in spec.get("zones", []) for n in z.get("nodes", [])]
    elif mode in ("grid", "sequence"):
        all_nodes = spec.get(key) or []
    else:
        all_nodes = extra.nodes_of(spec, mode)
    ids = [n.get("id") for n in all_nodes]
    dup = {i for i in ids if ids.count(i) > 1}
    if None in ids:
        raise SpecError("every node needs an 'id'")
    if dup:
        raise SpecError(f"duplicate node ids: {sorted(dup)}")
    if mode == "grid":
        seen = {}
        for n in spec.get("nodes", []):
            k = (n.get("row", 0), n.get("col", 0))
            if k in seen:
                findings.append(f"nodes {seen[k]!r} and {n['id']!r} share row/col {k}")
            seen[k] = n["id"]
    under = over = ""
    custom_nodes = None
    if extra:
        sc = extra.LAYOUTS[mode](spec, th, findings)
        boxes, zboxes, right, bottom = sc["boxes"], sc["zboxes"], sc["right"], sc["bottom"]
        edges, labels, holes = sc.get("edges", []), sc.get("labels", []), sc.get("holes", [])
        under, over, custom_nodes = sc.get("under", ""), sc.get("over", ""), sc.get("nodes")
    else:
        layout = {"layers": layout_layers, "grid": layout_grid, "sequence": layout_sequence}[mode]
        boxes, zboxes, right, bottom = layout(spec, th, findings)
        if mode == "sequence":
            edges, labels, holes = draw_sequence(spec, th, boxes, bottom, findings)
        else:
            ext = {}
            edges, labels, holes = draw_edges(spec, th, boxes, mode, findings, header_box(spec, th) + zone_title_boxes(zboxes, th), ext)
            right, bottom = max(right, ext.get("right", 0)), max(bottom, ext.get("bottom", 0))
    pad = L["canvas_pad"]
    y = bottom + L["section_gap"]
    code_svg, code_bottom, code_right = draw_code(spec, th, pad, y)
    if spec.get("code"):
        y = code_bottom + L["section_gap"]
    legend_svg, legend_right = draw_legend(spec, th, pad, y, findings)
    if spec.get("legend"):
        y += L["label_size"] * 1.2
    else:
        y -= L["section_gap"]
    used_roles = {n.get("role", "plain") for n in all_nodes}
    if len(used_roles - {"plain"}) >= 2 and not spec.get("legend"):
        findings.append(f"roles {sorted(used_roles - {'plain'})} carry meaning but there is no legend")
    width = max(right, code_right, legend_right) + pad
    height = y + pad
    title_svg = ""
    if spec.get("title"):
        ty = pad + L["diagram_title_size"] * 0.65
        title_svg += f'<text x="{pad}" y="{ty:.1f}" font-size="{L["diagram_title_size"]}" font-weight="{F["diagram_title_weight"]}" fill="{th["text"]["title"]}" dominant-baseline="central" font-family="{esc(F.get("display", F["family"]))}">{esc(spec["title"])}</text>'
        if th.get("title_rule"):
            title_svg += f'<rect x="{pad}" y="{ty + L["diagram_title_size"] * 0.75:.1f}" width="56" height="{th["title_rule"]}" fill="{th["text"].get("accent", th["text"]["title"])}"/>'
    if spec.get("subtitle"):
        sy = pad + L["diagram_title_size"] * 1.3 + L["desc_size"] * 0.8 + (th["title_rule"] + 10 if th.get("title_rule") else 0)
        title_svg += f'<text x="{pad}" y="{sy:.1f}" font-size="{L["desc_size"]}" fill="{th["text"]["desc"]}" dominant-baseline="central">{esc(spec["subtitle"])}</text>'
    zones_svg = "".join(draw_zone(z, th) for z in zboxes)
    if custom_nodes is not None:  # layouts that draw their own boxes (entities, gantt rows)
        backs_svg, nodes_svg = custom_nodes
    else:
        drawn = [draw_node(b.node, b, th, findings) for b in boxes.values()]
        backs_svg, nodes_svg = "".join(d[0] for d in drawn), "".join(d[1] for d in drawn)
    # Edge labels sit in holes cut out of the edges. The mask is canvas-sized in user space:
    # an objectBoundingBox mask on a group holding one straight line has zero height and hides it.
    mask_def, mask_attr = "", ""
    if holes:
        mask_def = (f'<mask id="edge-gaps" maskUnits="userSpaceOnUse" x="0" y="0" width="{width:.0f}" height="{height:.0f}">'
                    f'<rect width="{width:.0f}" height="{height:.0f}" fill="#fff"/>{"".join(holes)}</mask>')
        mask_attr = ' mask="url(#edge-gaps)"'
    clean = json.loads(json.dumps(spec, ensure_ascii=False, default=str))
    clean["theme"] = name  # 记下实际用的主题：--theme 覆盖过时，回取的描述照样复现同一张图
    _strip_lines(clean)
    meta = json.dumps(clean, ensure_ascii=False, indent=1).replace("]]>", "]]]]><![CDATA[>")
    fonts = f' data-fonts="{" ".join(F["embed"])}"' if F.get("embed") else ""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}" '
        f'font-family="{esc(F["family"])}" data-theme="{name}"{fonts}>'
        f'<metadata id="diagram-spec"><![CDATA[{meta}]]></metadata>'
        f'<defs>{mask_def}</defs><rect width="100%" height="100%" fill="{th["bg"]}"/>'
        f'{title_svg}{zones_svg}{under}{backs_svg}<g class="edges"{mask_attr}>{"".join(edges)}</g>{nodes_svg}{"".join(labels)}{over}{code_svg}{legend_svg}</svg>'
    )
    return svg, findings



def main() -> int:
    ap = argparse.ArgumentParser(description="Render a diagram spec JSON to a themed SVG")
    ap.add_argument("spec", nargs="?", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--theme")
    ap.add_argument("--extract", type=Path, help="print the spec embedded in a rendered SVG")
    ap.add_argument("--themes", action="store_true", help="list themes")
    a = ap.parse_args()
    if a.themes:
        for k, v in THEMES.items():
            print(f"{k}\t{v.get('label', '')}")
        return 0
    if a.extract:
        m = META_RE.search(a.extract.read_text(encoding="utf-8"))
        if not m:
            print(f"{a.extract}: no embedded spec", file=sys.stderr)
            return 1
        print(m.group(1).replace("]]]]><![CDATA[>", "]]>"))
        return 0
    if not a.spec:
        ap.error("spec is required")
    try:
        spec = load_spec(a.spec)
        svg, findings = render(spec, a.theme)
    except SpecError as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1
    out = a.output or a.spec.with_suffix(".svg")
    out.write_text(svg, encoding="utf-8")
    print(out)
    for f in findings:
        print(f"LINT {f}", file=sys.stderr)
    return 2 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
