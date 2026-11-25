"""Layouts beyond layers / grid / sequence: tree, lanes, tasks, entities, matrix, canvas.

render.py imports this module lazily and calls LAYOUTS[mode](spec, theme, findings). Each layout
returns a scene dict:
    boxes   {id: Box}  cards drawn by render.draw_node (and checked by edge-crossing lint)
    zboxes  [Box]      zone-style bands drawn behind everything
    right, bottom      canvas extent before padding
    edges, labels, holes   edge paths, edge label svg, label holes cut out of the edges
    under, over        extra svg drawn behind the cards / above the labels
    nodes   (backs, fronts) svg, only when the layout draws its own boxes instead of draw_node
Every color comes from the theme: roles, edge, zone, text. Standard library only.
"""
from __future__ import annotations

import math
import re
from datetime import date

from render import (Box, ROUND_SHAPES, header_box, zone_title_boxes, column_width, corner_radius, draw_arrow, draw_edges, draw_node, draw_shape,
                    ellipse_segs, esc, line_seg, node_metrics, rect_segs, role_style, route, seg_hits_box, text_w,
                    top_offset, wrap, _dist, _lerp, _towards)

COLOR_KEYS = ("fill", "stroke", "color", "colour", "background", "bg", "text_color", "border")
COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgba?\(|hsla?\()")


def _f(v):
    return f"{v:.1f}"


def _text(x, y, s, size, fill, anchor="start", weight=None, maxw=None, extra=""):
    w = f' font-weight="{weight}"' if weight else ""
    m = f' data-maxw="{maxw:.0f}"' if maxw else ""
    return (f'<text x="{_f(x)}" y="{_f(y)}" font-size="{size}"{w} fill="{fill}" text-anchor="{anchor}" '
            f'dominant-baseline="central"{m}{extra}>{esc(s)}</text>')


def _overlap(a: Box, b: Box, pad=0.0) -> bool:
    return a.x < b.r - pad and b.x < a.r - pad and a.y < b.b - pad and b.y < a.b - pad


def _inside(a: Box, outer: Box) -> bool:
    return a.x >= outer.x and a.y >= outer.y and a.r <= outer.r and a.b <= outer.b


def _color_lint(items, what, findings):
    """Colors come from roles. A literal color in the spec would break theme switching, so it is reported."""
    for it in items:
        if not isinstance(it, dict):
            continue
        for k, v in it.items():
            if k in COLOR_KEYS or (isinstance(v, str) and COLOR_RE.match(v.strip())):
                findings.append(f"{what} {it.get('id', '?')!r}: {k!r} sets a color; colors come from the theme, use 'role' instead")


class Links:
    """Edge drawing with labels, shared by the layouts that compute their own paths."""

    def __init__(self, th, boxes, findings):
        self.th, self.boxes, self.findings = th, boxes, findings
        self.body, self.labels, self.holes, self.label_boxes = [], [], [], []

    def add(self, pts, key, a=None, b=None, label=None, label_seg=None, dashed=False, head=True, accent=None, both=False, check=True):
        th, E = self.th, self.th["edge"]
        if check:
            for p, q in zip(pts, pts[1:]):
                for other in self.boxes.values():
                    if other is a or other is b:
                        continue
                    if seg_hits_box(p, q, other):
                        self.findings.append(f"{key} crosses {other.id!r}; move one of them so the line has a free path")
        col = E["color"]
        if accent:
            col = role_style(th, accent if isinstance(accent, str) else "primary", self.findings, key).get("accent", col)
        width = E["width"] * (1.5 if accent and E.get("accent_wider") else 1)
        if head:
            self.body.append(draw_arrow(pts, th, col, width, key, dashed=dashed, both=both))
        else:
            segs = [line_seg(p, q) for p, q in zip(pts, pts[1:]) if _dist(p, q) > 0.01]
            if segs:
                self.body.append(draw_shape(segs, th, key, stroke=col, sw=width, dash=E.get("dash", "8 8") if dashed else None, closed=False, ends=0.6))
        if label:
            segs = list(zip(pts, pts[1:]))
            p, q = segs[label_seg] if label_seg is not None else max(segs, key=lambda s: abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1]))
            self.label((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, label)

    def label(self, mx, my, text):
        th, Lb = self.th, self.th["edge_label"]
        ls = th["layout"]["label_size"]
        tw = text_w(text, ls, th["font"]["latin_w"])
        chip = Lb.get("style") == "chip"
        w, h = tw + (16 if chip else 12), ls * (1.7 if chip else 1.5)
        lb = Box("", mx - w / 2, my - h / 2, w, h)
        for other in self.boxes.values():
            if _overlap(lb, other):
                self.findings.append(f"label {text!r} overlaps {other.id!r}; shorten the label or move the boxes apart")
        for ob in self.label_boxes:
            if _overlap(lb, ob):
                self.findings.append(f"label {text!r} overlaps another label")
        self.label_boxes.append(lb)
        if chip:
            self.labels.append(f'<rect x="{_f(lb.x)}" y="{_f(lb.y)}" width="{_f(w)}" height="{_f(h)}" rx="{Lb.get("radius", 4)}" fill="{Lb["fill"]}" stroke="{Lb.get("stroke", Lb["fill"])}" stroke-width="1"/>')
        else:
            self.holes.append(f'<rect x="{_f(lb.x)}" y="{_f(lb.y)}" width="{_f(w)}" height="{_f(h)}" rx="4" fill="#000"/>')
        self.labels.append(_text(mx, my, text, ls, Lb["text"], "middle"))

    def scene(self, **kw):
        return dict(edges=self.body, labels=self.labels, holes=self.holes, **kw)


# ---------------------------------------------------------------- nodes per layout
def _tree_roots(spec):
    t = spec.get("tree")
    return t if isinstance(t, list) else [t] if isinstance(t, dict) else []


def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n.get("children") or [])


def nodes_of(spec, mode):
    """Every node-like dict with an id: used for duplicate-id checks and the legend check."""
    if mode == "tree":
        return list(_walk(_tree_roots(spec)))
    if mode == "lanes":
        return spec.get("steps") or []
    if mode == "tasks":
        return spec.get("tasks") or []
    if mode == "entities":
        return spec.get("entities") or []
    if mode == "matrix":
        return (spec.get("matrix") or {}).get("items") or []
    if mode == "canvas":
        return (spec.get("canvas") or {}).get("elements") or []
    return []


# ---------------------------------------------------------------- tree
def layout_tree(spec, th, findings):
    """Org chart / WBS / decision tree. Parents centered over (or beside) their children."""
    L = th["layout"]
    roots = _tree_roots(spec)
    nodes = list(_walk(roots))
    colw = spec.get("col_width") or column_width(nodes, th)
    right_dir = spec.get("direction", "down") == "right"
    for n in nodes:
        tl, dl, h = node_metrics(n, th, colw)
        n["_lines"] = (tl, dl)
        n["_h"] = h
    x0, y0 = L["canvas_pad"], top_offset(spec, th)
    boxes = {}
    if not right_dir:
        depth_h = {}

        def measure(n, d):
            depth_h[d] = max(depth_h.get(d, 0), n["_h"])
            for c in n.get("children") or []:
                measure(c, d + 1)
        for r in roots:
            measure(r, 0)
        gy = L["grid_gap_y"]
        level_y, y = {}, y0
        for d in sorted(depth_h):
            level_y[d] = y
            y += depth_h[d] + gy
        sib = L["gap_x"]

        def place(n, d, left):
            kids = n.get("children") or []
            if not kids:
                cx, width = left + colw / 2, colw
            else:
                cur, first = left, None
                for c in kids:
                    w, ccx = place(c, d + 1, cur)
                    first = ccx if first is None else first
                    last = ccx
                    cur += w + sib
                width = cur - sib - left
                cx = (first + last) / 2
                if width < colw:  # a lone narrow child: keep the parent's own width
                    width = colw
            boxes[n["id"]] = Box(n["id"], cx - colw / 2, level_y[d] + (depth_h[d] - n["_h"]) / 2, colw, n["_h"], node=n)
            n["_bus"] = level_y[d] + depth_h[d] + gy / 2  # y of the horizontal bar joining its children
            return width, cx
        cur = x0
        for r in roots:
            w, _ = place(r, 0, cur)
            cur += w + sib * 2
    else:
        gx, sib = L["grid_gap_x"], L["zone_gap"]

        def place(n, d, top):
            kids = n.get("children") or []
            h = n["_h"]
            x = x0 + d * (colw + gx)
            if not kids:
                boxes[n["id"]] = Box(n["id"], x, top, colw, h, node=n)
                return h, top + h / 2
            cur, first = top, None
            for c in kids:
                ch, ccy = place(c, d + 1, cur)
                first = ccy if first is None else first
                last = ccy
                cur += ch + sib
            height = cur - sib - top
            cy = max((first + last) / 2, top + h / 2)  # a parent taller than its children block starts at top
            boxes[n["id"]] = Box(n["id"], x, cy - h / 2, colw, h, node=n)
            return max(height, h), cy
        cur = y0
        for r in roots:
            hgt, _ = place(r, 0, cur)
            cur += hgt + sib * 2
    links = Links(th, boxes, findings)
    arrows = bool(spec.get("arrows"))
    for n in nodes:
        p = boxes[n["id"]]
        for c in n.get("children") or []:
            cb = boxes[c["id"]]
            if right_dir:
                mx = p.r + L["grid_gap_x"] / 2
                pts = [(p.r, p.cy), (mx, p.cy), (mx, cb.cy), (cb.x, cb.cy)]
            else:
                my = n["_bus"]
                pts = [(p.cx, p.b), (p.cx, my), (cb.cx, my), (cb.cx, cb.y)]
            pts = [q for i, q in enumerate(pts) if i == 0 or _dist(q, pts[i - 1]) > 0.01]
            links.add(pts, f"tree {n['id']}->{c['id']}", p, cb, label=c.get("edge_label"), label_seg=len(pts) - 2,
                      dashed=c.get("edge_dashed"), head=arrows, check=True)
    for n in nodes:
        n.pop("_h", None)
        n.pop("_bus", None)
    right = max([b.r for b in boxes.values()] + [0])
    bottom = max([b.b for b in boxes.values()] + [0])
    return links.scene(boxes=boxes, zboxes=[], right=right, bottom=bottom)


# ---------------------------------------------------------------- lanes
def layout_lanes(spec, th, findings):
    """Swimlanes: one horizontal band per role, steps placed by column, edges routed like the grid."""
    L = th["layout"]
    lanes = spec.get("lanes") or []
    steps = spec.get("steps") or []
    colw = spec.get("col_width") or column_width(steps, th)
    gx, gutter, zp = L["grid_gap_x"], L["gutter"], L["zone_pad"]
    latin = th["font"]["latin_w"]
    lane_ids = [ln.get("id") for ln in lanes]
    for ln in lanes:
        if text_w(ln.get("title", ""), L["zone_title_size"], latin) > gutter - zp - 8:
            findings.append(f"lane {ln.get('id')!r}: title {ln.get('title')!r} is wider than the lane header; shorten it")
    metrics = {}
    for s in steps:
        if s.get("lane") not in lane_ids:
            findings.append(f"step {s['id']!r}: unknown lane {s.get('lane')!r}; known: {lane_ids}")
        tl, dl, h = node_metrics(s, th, colw)
        s["_lines"] = (tl, dl)
        metrics[s["id"]] = h
    seen = {}
    for s in steps:
        k = (s.get("lane"), s.get("col", 0))
        if k in seen:
            findings.append(f"steps {seen[k]!r} and {s['id']!r} share lane/col {k}")
        seen[k] = s["id"]
    ncols = max([s.get("col", 0) for s in steps] + [0]) + 1
    zone_w = gutter + ncols * colw + (ncols - 1) * gx + zp
    x0, y = L["canvas_pad"], top_offset(spec, th)
    boxes, zboxes = {}, []
    for ln in lanes:
        mine = [s for s in steps if s.get("lane") == ln.get("id")]
        rowh = max([metrics[s["id"]] for s in mine] + [L["card_min_h"]])
        lh = rowh + 2 * zp
        if ln.get("desc"):
            need = L["zone_title_size"] * 1.4 + len(wrap(ln["desc"], L["desc_size"], latin, gutter - zp - 8)) * L["desc_size"] * 1.45 + 2 * zp
            lh = max(lh, need)
        zboxes.append(Box(ln.get("id"), x0, y, zone_w, lh, zone=dict(title=ln.get("title"), desc=ln.get("desc"), dashed=ln.get("dashed"))))
        for s in mine:
            h = metrics[s["id"]]
            boxes[s["id"]] = Box(s["id"], x0 + gutter + s.get("col", 0) * (colw + gx), y + (lh - h) / 2, colw, h, node=s)
        y += lh + L["zone_gap"]
    ext = {}
    edges, labels, holes = draw_edges(spec, th, boxes, "grid", findings, header_box(spec, th) + zone_title_boxes(zboxes, th), ext)
    return dict(boxes=boxes, zboxes=zboxes, right=max(x0 + zone_w, ext.get("right", 0)), bottom=max(y - L["zone_gap"], ext.get("bottom", 0)),
                edges=edges, labels=labels, holes=holes)


# ---------------------------------------------------------------- tasks (gantt)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _when(v):
    """ISO date -> (ordinal, True); number -> (number, False); else None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v), False
    if isinstance(v, str) and DATE_RE.match(v):
        try:
            return float(date.fromisoformat(v).toordinal()), True
        except ValueError:
            return None
    return None


def _tick_label(v, is_date, fmt):
    if is_date:
        d = date.fromordinal(int(v))
        return f"{d.month}/{d.day}"
    n = int(v) if float(v).is_integer() else v
    return fmt.replace("{n}", str(n))


def layout_tasks(spec, th, findings):
    """Gantt / timeline: task bars and milestone diamonds on a time axis, optional dependency arrows."""
    L, F = th["layout"], th["font"]
    latin = F["latin_w"]
    tasks = spec.get("tasks") or []
    axis = spec.get("axis") or {}
    rows, kinds = [], set()
    for t in tasks:
        s = _when(t.get("start"))
        if s is None:
            findings.append(f"task {t['id']!r}: 'start' must be a number or a YYYY-MM-DD date, got {t.get('start')!r}")
            continue
        kinds.add(s[1])
        if t.get("milestone"):
            rows.append((t, s[0], s[0]))
            continue
        if "end" in t:
            e = _when(t["end"])
            if e is None:
                findings.append(f"task {t['id']!r}: 'end' must match 'start' (number or YYYY-MM-DD), got {t.get('end')!r}")
                continue
            kinds.add(e[1])
            end = e[0] + (1 if e[1] else 0)  # a date range includes its end day
        elif isinstance(t.get("duration"), (int, float)):
            end = s[0] + t["duration"]
        else:
            findings.append(f"task {t['id']!r}: give 'end' or 'duration', or set 'milestone': true")
            continue
        if end <= s[0]:
            findings.append(f"task {t['id']!r}: ends before it starts")
            end = s[0] + 1
        rows.append((t, s[0], end))
    if len(kinds) > 1:
        findings.append("tasks mix dates and numbers on one axis; use one kind")
    is_date = kinds == {True}
    t0 = min(r[1] for r in rows) if rows else 0
    t1 = max([r[2] for r in rows] + [t0 + 1])
    span = max(t1 - t0, 1)
    step = axis.get("step")
    if not step:
        cands = (1, 2, 7, 14, 28, 56) if is_date else (1, 2, 5, 10, 20, 50, 100, 200, 500)
        step = next((c for c in cands if span / c <= 12), cands[-1])
    t1 = t0 + math.ceil(span / step) * step
    ls = L["label_size"]
    fmt = axis.get("format", "{n}")
    tick_w = max(text_w(_tick_label(t0 + i * step, is_date, fmt), ls, latin) for i in range(int((t1 - t0) / step) + 1)) + 32
    tl_w = axis.get("width") or max(600, tick_w * (t1 - t0) / step)
    unit = tl_w / (t1 - t0)
    ts = L["title_size"]
    label_w = min(max([text_w(t.get("title", ""), ts, latin) for t in tasks] + [L["col_min"] * 0.6]) + L["zone_pad"], L["col_max"])
    x0, y0 = L["canvas_pad"], top_offset(spec, th)
    zp = L["zone_pad"]
    tl_x = x0 + zp + label_w + zp
    bar_h = round(ts * 1.5)
    pitch = bar_h + max(L["zone_gap"], 16)
    head_h = ls * 2.2
    rows_y = y0 + zp + head_h
    band = Box("tasks", x0, y0, tl_x - x0 + tl_w + max(zp, tick_w / 2), zp * 2 + head_h + pitch * len(rows) - (pitch - bar_h), zone={})
    xof = lambda v: tl_x + (v - t0) * unit
    under, boxes, info = [], {}, {}
    grid_col = th["zone"].get("dash_stroke", th["edge"]["color"])
    v, k = t0, 0
    while v <= t1 + 1e-9:
        x = xof(v)
        under.append(draw_shape([line_seg((x, rows_y - 6), (x, band.b - zp / 2))], th, f"tick:{k}", stroke=grid_col, sw=1, dash="3 5", closed=False))
        under.append(_text(x, y0 + zp + ls * 0.7, _tick_label(v, is_date, axis.get("format", "{n}")), ls, th["text"]["desc"], "middle"))
        v += step
        k += 1
    fronts, backs = [], []
    dcol = th["text"]["desc"]
    right = band.r
    for i, (t, s, e) in enumerate(rows):
        cy = rows_y + i * pitch + bar_h / 2
        fronts.append(_text(x0 + zp, cy, t.get("title", ""), ts, th["text"]["title"], "start", F["title_weight"], maxw=label_w))
        if text_w(t.get("title", ""), ts, latin) > label_w + 1:
            findings.append(f"task {t['id']!r}: title {t.get('title')!r} is wider than the label column ({label_w:.0f}px); shorten it")
        if t.get("milestone"):
            d = bar_h * 1.15
            b = Box(t["id"], xof(s) - d / 2, cy - d / 2, d, d, node={"id": t["id"], "role": t.get("role", "plain"), "shape": "diamond", "_lines": ([], [])})
        else:
            b = Box(t["id"], xof(s), cy - bar_h / 2, max((e - s) * unit, 6), bar_h, node={"id": t["id"], "role": t.get("role", "plain"), "dashed": t.get("dashed"), "_lines": ([], [])})
        boxes[t["id"]] = b
        info[t["id"]] = (s, e)
        bk, fr = draw_node(b.node, b, th, findings)
        backs.append(bk)
        fronts.append(fr)
        if t.get("desc"):
            fronts.append(_text(b.r + 10, cy, t["desc"], L["desc_size"], dcol))
            right = max(right, b.r + 10 + text_w(t["desc"], L["desc_size"], latin))
    links = Links(th, boxes, findings)
    for t, s, e in rows:
        for dep in t.get("after") or []:
            a, b = boxes.get(dep), boxes.get(t["id"])
            if a is None:
                findings.append(f"task {t['id']!r}: unknown dependency {dep!r}")
                continue
            if info[t["id"]][0] < info[dep][1] - 1e-9 and not t.get("milestone"):
                findings.append(f"task {t['id']!r} starts before its dependency {dep!r} ends")
            down = b.cy > a.cy
            ya = a.b if down else a.y
            head = th["edge"].get("head", 13)
            if b.x - a.r >= head + 16:
                mx = a.r + 10
                pts = [(a.r, a.cy), (mx, a.cy), (mx, b.cy), (b.x, b.cy)]
            else:
                x = b.x - head - 12
                pts = [(x, ya), (x, b.cy), (b.x, b.cy)] if a.x + 2 <= x <= a.r else [(a.r, a.cy), (x, a.cy), (x, b.cy), (b.x, b.cy)]
            links.add(pts, f"dependency {dep}->{t['id']}", a, b)
    marker = spec.get("marker")
    if marker:
        m = _when(marker.get("at"))
        if m is None:
            findings.append(f"marker: 'at' must be a number or a YYYY-MM-DD date, got {marker.get('at')!r}")
        else:
            x = xof(m[0])
            col = role_style(th, marker.get("role", "warn"), findings, "marker").get("accent", th["edge"]["color"])
            under.append(draw_shape([line_seg((x, rows_y - 10), (x, band.b))], th, "marker", stroke=col, sw=th["edge"]["width"], closed=False))
            if marker.get("label"):
                under.append(_text(x, band.b + ls * 0.9, marker["label"], ls, th["text"]["desc"], "middle"))
    bottom = band.b + (ls * 1.8 if marker and marker.get("label") else 0)
    return links.scene(boxes=boxes, zboxes=[band], right=right, bottom=bottom, under="".join(under), nodes=("".join(backs), "".join(fronts)))


# ---------------------------------------------------------------- entities (ER / class)
def _round_poly_r(pts, radii, k=2 / 3):
    """Closed polygon with a radius per corner (entity header: rounded top, square bottom)."""
    n, cuts = len(pts), []
    for i, c in enumerate(pts):
        prev, nxt = pts[i - 1], pts[(i + 1) % n]
        rr = min(radii[i], _dist(c, prev) / 2, _dist(c, nxt) / 2)
        cuts.append((_towards(c, prev, rr), c, _towards(c, nxt, rr)))
    segs = []
    for i, (a, c, b) in enumerate(cuts):
        if _dist(a, b) > 0.01:
            segs.append((a, _lerp(a, c, k), _lerp(b, c, k), b))
        na = cuts[(i + 1) % n][0]
        if _dist(b, na) > 0.01:
            segs.append(line_seg(b, na))
    return segs


def _field(f):
    """A field is "text" or {"name", "type", "key"} -> (key, name, type)."""
    if isinstance(f, dict):
        return str(f.get("key", "")), str(f.get("name", "")), str(f.get("type", ""))
    return "", str(f), ""


def layout_entities(spec, th, findings):
    """ER / class cards: title band plus one row per field, laid on a row/col grid; relations between cards."""
    L, F = th["layout"], th["font"]
    latin = F["latin_w"]
    ents = spec.get("entities") or []
    ts, ds = L["title_size"], L["desc_size"]
    px, py = L["card_pad_x"], L["card_pad_y"]
    kgap = ds * 0.8
    want = L["col_min"]
    for e in ents:
        want = max(want, text_w(e.get("title", ""), ts, latin) + 2 * px)
        for f in e.get("fields") or []:
            k, nm, ty = _field(f)
            w = text_w(nm, ds, latin) + (text_w(k, ds, latin) + kgap if k else 0) + (text_w(ty, ds, latin) + 2 * kgap if ty else 0)
            want = max(want, w + 2 * px)
    colw = spec.get("col_width") or min(math.ceil(want / 4) * 4, L["col_max"] * 1.3)
    cols = spec.get("columns") or max(1, math.ceil(math.sqrt(len(ents))))
    head_h = ts * 1.3 + py * 1.4
    fh = ds * 1.75
    pos = {}
    for i, e in enumerate(ents):
        pos[e["id"]] = (e.get("row", i // cols), e.get("col", i % cols))
    seen = {}
    for eid, rc in pos.items():
        if rc in seen:
            findings.append(f"entities {seen[rc]!r} and {eid!r} share row/col {rc}")
        seen[rc] = eid
    hts = {e["id"]: head_h + max(len(e.get("fields") or []), 1) * fh + py * 0.8 for e in ents}
    nrows = max([r for r, _ in pos.values()] + [0]) + 1
    row_h = {r: max([hts[i] for i, (rr, _) in pos.items() if rr == r] + [0]) for r in range(nrows)}
    gx, gy = L["grid_gap_x"] * 1.4, L["grid_gap_y"]
    x0, y = L["canvas_pad"], top_offset(spec, th)
    row_y = {}
    for r in range(nrows):
        row_y[r] = y
        y += row_h[r] + gy
    boxes = {}
    for e in ents:
        r, c = pos[e["id"]]
        boxes[e["id"]] = Box(e["id"], x0 + c * (colw + gx), row_y[r], colw, hts[e["id"]], node=e)
    backs, fronts = [], []
    C, shadow = th["card"], th.get("shadow", {})
    plain = th["roles"]["plain"]
    for e in ents:
        b = boxes[e["id"]]
        st = role_style(th, e.get("role", "plain"), findings, f"entity {e['id']!r}")
        key = f"entity:{e['id']}"
        rad = corner_radius(C, b.w, min(b.h, head_h * 2))
        if shadow.get("kind") == "offset":
            backs.append(draw_shape(rect_segs(b.x + shadow.get("dx", 0), b.y + shadow.get("dy", 0), b.w, b.h, rad), th, key + ":sh", fill=shadow["color"], opacity=shadow.get("opacity", 1)))
        outline = st.get("stroke") if st.get("stroke") not in (None, "none") else st["fill"]
        body_fill = plain["fill"] if plain["fill"] != st["fill"] else th["bg"]
        sw = st.get("stroke_width", C["stroke_width"])
        fronts.append(draw_shape(rect_segs(b.x, b.y, b.w, b.h, rad), th, key + ":body", fill=body_fill))
        hb = [(b.x, b.y), (b.r, b.y), (b.r, b.y + head_h), (b.x, b.y + head_h)]
        fronts.append(draw_shape(_round_poly_r(hb, [rad, rad, 0, 0]), th, key + ":head", fill=st["fill"]))
        fronts.append(draw_shape([line_seg((b.x, b.y + head_h), (b.r, b.y + head_h))], th, key + ":rule", stroke=outline, sw=sw, closed=False))
        fronts.append(draw_shape(rect_segs(b.x, b.y, b.w, b.h, rad), th, key, stroke=outline, sw=sw, dash=st.get("dash") or (C.get("dash") if st.get("dashed") or e.get("dashed") else None)))
        tcol = st.get("text", th["text"]["title"])
        fronts.append(_text(b.cx, b.y + head_h / 2, e.get("title", ""), ts, tcol, "middle", F["title_weight"], maxw=b.w - 2 * px + 2))
        fy = b.y + head_h + py * 0.4 + fh / 2
        name_col, meta_col = th["text"]["title"], th["text"]["desc"]
        for f in e.get("fields") or []:
            k, nm, ty = _field(f)
            x = b.x + px
            avail = b.w - 2 * px
            if k:
                fronts.append(_text(x, fy, k, ds, meta_col))
                x += text_w(k, ds, latin) + kgap
            fronts.append(_text(x, fy, nm, ds, name_col, maxw=b.r - px - x + 2 - (text_w(ty, ds, latin) + kgap if ty else 0)))
            if ty:
                fronts.append(_text(b.r - px, fy, ty, ds, meta_col, "end"))
            need = text_w(nm, ds, latin) + (text_w(k, ds, latin) + kgap if k else 0) + (text_w(ty, ds, latin) + 2 * kgap if ty else 0)
            if need > avail + 1:
                findings.append(f"entity {e['id']!r}: field {nm!r} does not fit the card; shorten it or raise col_width")
            fy += fh
    links = Links(th, boxes, findings)
    ls = L["label_size"]
    rel_pts = []
    for i, r in enumerate(spec.get("relations") or []):
        a, b = boxes.get(r.get("from")), boxes.get(r.get("to"))
        if not a or not b:
            findings.append(f"relation {i} ({r.get('from')}->{r.get('to')}): unknown entity id")
            continue
        pts = route(a, b, "grid", list(boxes.values()), header_box(spec, th), th["layout"]["zone_pad"] / 2)
        rel_pts += pts
        links.add(pts, f"relation {r['from']}->{r['to']}", a, b, label=r.get("label"), dashed=r.get("dashed"), head=bool(r.get("arrow")))
        for card, p, q in ((r.get("from_card"), pts[0], pts[1]), (r.get("to_card"), pts[-1], pts[-2])):
            if not card:
                continue
            d = _dist(p, q) or 1
            ux, uy = (q[0] - p[0]) / d, (q[1] - p[1]) / d
            if abs(uy) > 0.5:  # vertical segment: cardinality to the right of the line, near the card
                cx, cy, anchor = p[0] + 10, p[1] + uy * 18, "start"
            else:  # horizontal segment: above the line, near the card
                cx, cy, anchor = p[0] + ux * 18, p[1] - ls * 0.8, "middle"
            links.labels.append(_text(cx, cy, card, ls, th["edge_label"]["text"], anchor,
                                      extra=f' stroke="{th["bg"]}" stroke-width="5" stroke-linejoin="round" paint-order="stroke"'))
    right = max([b.r for b in boxes.values()] + [p[0] for p in rel_pts] + [0])
    bottom = max([b.b for b in boxes.values()] + [p[1] for p in rel_pts] + [0])
    return links.scene(boxes=boxes, zboxes=[], right=right, bottom=bottom, nodes=("".join(backs), "".join(fronts)))


# ---------------------------------------------------------------- matrix (2x2)
QUADRANT_ORDER = ("top-left", "top-right", "bottom-left", "bottom-right")


def layout_matrix(spec, th, findings):
    """Four quadrants on two labelled axes; items placed by x/y in 0..1 (0 = low end of the axis)."""
    L, F = th["layout"], th["font"]
    latin = F["latin_w"]
    m = spec.get("matrix") or {}
    ax, ay = m.get("x") or {}, m.get("y") or {}
    ls, ts, ds, zp = L["label_size"], L["title_size"], L["desc_size"], L["zone_pad"]
    items = m.get("items") or []
    cell = m.get("cell") or max(300, L["col_max"] + 2 * zp)
    gap = L["zone_gap"] / 2
    x0, y0 = L["canvas_pad"], top_offset(spec, th)
    left_w = ls * 2.8
    px0, py0 = x0 + left_w, y0
    size = 2 * cell + gap
    under, over = [], []
    quads = m.get("quadrants") or []
    if quads and len(quads) != 4:
        findings.append(f"matrix: 'quadrants' needs 4 entries ({', '.join(QUADRANT_ORDER)}), got {len(quads)}")
    qboxes, title_boxes = [], []
    Z = th["zone"]
    for qi in range(4):
        q = quads[qi] if qi < len(quads) and isinstance(quads[qi], dict) else {}
        qx, qy = px0 + (qi % 2) * (cell + gap), py0 + (qi // 2) * (cell + gap)
        qb = Box(f"quadrant {QUADRANT_ORDER[qi]}", qx, qy, cell, cell)
        qboxes.append(qb)
        segs = rect_segs(qx, qy, cell, cell, corner_radius(Z, cell, cell))
        if q.get("role"):
            st = role_style(th, q["role"], findings, f"quadrant {QUADRANT_ORDER[qi]}")
            dash = st.get("dash") or (th["card"].get("dash", "8 9") if st.get("dashed") else None)
            under.append(draw_shape(segs, th, f"quad:{qi}", fill=st["fill"], stroke=st.get("stroke"), sw=st.get("stroke_width", th["card"]["stroke_width"]), dash=dash))
            tcol, dcol = st.get("text", th["text"]["zone"]), st.get("desc", th["text"]["desc"])
        else:
            fill = Z["fill"] if Z.get("fill") not in (None, "none") else "none"
            stroke = Z.get("stroke") if Z.get("stroke") not in (None, "none") else Z.get("dash_stroke")
            under.append(draw_shape(segs, th, f"quad:{qi}", fill=fill, stroke=stroke if fill == "none" else Z.get("stroke"), sw=Z.get("stroke_width", 1)))
            tcol, dcol = th["text"]["zone"], th["text"]["desc"]
        ty = qy + zp + L["zone_title_size"] * 0.7
        if q.get("title"):
            under.append(_text(qx + zp, ty, q["title"], L["zone_title_size"], tcol, weight=F["zone_weight"], maxw=cell - 2 * zp))
            tw = text_w(q["title"], L["zone_title_size"], latin)
            title_boxes.append((Box(f"quadrant title {q['title']!r}", qx + zp, qy + zp, tw, L["zone_title_size"] * 1.4), q["title"]))
        if q.get("desc"):
            for j, line in enumerate(wrap(q["desc"], ds, latin, cell - 2 * zp)):
                under.append(_text(qx + zp, ty + L["zone_title_size"] * 0.9 + ds * 0.75 + j * ds * 1.45, line, ds, dcol, maxw=cell - 2 * zp))
            nlines = len(wrap(q["desc"], ds, latin, cell - 2 * zp))
            title_boxes[-1:] = [(Box(f"quadrant title {q.get('title')!r}", qx + zp, qy + zp, cell - 2 * zp, L["zone_title_size"] * 1.4 + nlines * ds * 1.45), q.get("title"))] if q.get("title") else []
    # axes: arrows along the left and bottom edges, labels outside
    E = th["edge"]
    ya = py0 + size + 12
    under.append(draw_arrow([(px0, ya), (px0 + size, ya)], th, E["color"], E["width"], "axis:x"))
    xa = px0 - 12
    under.append(draw_arrow([(xa, py0 + size), (xa, py0)], th, E["color"], E["width"], "axis:y"))
    lab_y = ya + ls * 1.2
    dc = th["text"]["desc"]
    if ax.get("low"):
        under.append(_text(px0, lab_y, ax["low"], ls, dc))
    if ax.get("high"):
        under.append(_text(px0 + size - E.get("head", 13), lab_y, ax["high"], ls, dc, "end"))
    if ax.get("label"):
        under.append(_text(px0 + size / 2, lab_y, ax["label"], ls, th["text"]["zone"], "middle", F["zone_weight"]))
    lx = x0 + ls * 0.7
    rot = lambda y: f' transform="rotate(-90 {_f(lx)} {_f(y)})"'
    if ay.get("low"):
        under.append(_text(lx, py0 + size, ay["low"], ls, dc, "start", extra=rot(py0 + size)))
    if ay.get("high"):
        under.append(_text(lx, py0 + E.get("head", 13), ay["high"], ls, dc, "end", extra=rot(py0 + E.get("head", 13))))
    if ay.get("label"):
        under.append(_text(lx, py0 + size / 2, ay["label"], ls, th["text"]["zone"], "middle", F["zone_weight"], extra=rot(py0 + size / 2)))
    plot = Box("plot", px0, py0, size, size)
    boxes, placed = {}, []
    for it in items:
        x, y = it.get("x"), it.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            findings.append(f"item {it.get('id')!r}: 'x' and 'y' must be numbers in 0..1")
            continue
        cx, cy = px0 + x * size, py0 + (1 - y) * size
        if it.get("dot"):
            r = ds * 0.45
            st = role_style(th, it.get("role", "plain"), findings, f"item {it['id']!r}")
            dotc = st.get("accent", E["color"])
            over.append(draw_shape(ellipse_segs(cx, cy, r, r), th, f"dot:{it['id']}", fill=dotc, stroke=dotc, sw=1))
            tw = text_w(it.get("title", ""), ds, latin)
            over.append(_text(cx + r + 6, cy, it.get("title", ""), ds, th["text"]["title"],
                              extra=f' stroke="{th["bg"]}" stroke-width="4" stroke-linejoin="round" paint-order="stroke"'))
            bb = Box(it["id"], cx - r, cy - ds * 0.75, 2 * r + 6 + tw, ds * 1.5)
        else:
            w = it.get("w") or min(max(text_w(it.get("title", ""), ts, latin), text_w(str(it.get("desc", "")), ds, latin)) * 1.1 + 2 * L["card_pad_x"] + 8, L["col_max"])  # 10% slack: the estimate runs narrow for handwriting fonts
            tl, dl, h = node_metrics(it, th, w)
            it["_lines"] = (tl, dl)
            bb = Box(it["id"], cx - w / 2, cy - h / 2, w, h, node=it)
            boxes[it["id"]] = bb
        if not _inside(bb, plot):
            findings.append(f"item {it['id']!r} sticks out of the plot; move x/y toward 0.5")
        else:
            for qb in qboxes:
                if _overlap(bb, qb) and not _inside(bb, qb):
                    findings.append(f"item {it['id']!r} straddles a quadrant edge; move it fully into one quadrant")
                    break
        for tb, title in title_boxes:
            if _overlap(bb, tb):
                findings.append(f"item {it['id']!r} covers the quadrant title {title!r}")
        for ob in placed:
            if _overlap(bb, ob):
                findings.append(f"items {ob.id!r} and {it['id']!r} overlap; spread their x/y apart")
        placed.append(bb)
    right = max([px0 + size] + [b.r for b in placed])
    bottom = lab_y + ls * 0.8
    return dict(boxes=boxes, zboxes=[], right=right, bottom=bottom, under="".join(under), over="".join(over))


# ---------------------------------------------------------------- canvas (free coordinates)
BOX_SHAPES = ("card", "pill", "diamond", "text") + ROUND_SHAPES
LINE_SHAPES = ("line", "arrow")


def layout_canvas(spec, th, findings):
    """Fallback: every element sets its own x/y/w/h. Colors still come from roles, geometry from the theme."""
    L = th["layout"]
    c = spec.get("canvas") or {}
    els = c.get("elements") or []
    W, H = c.get("width"), c.get("height")
    ox, oy = L["canvas_pad"], top_offset(spec, th)
    _color_lint(els, "element", findings)
    _color_lint(spec.get("edges") or [], "edge", findings)
    boxes, zboxes, lines, sized = {}, [], [], []
    for el in els:
        shape = el.get("shape", "card")
        eid = el.get("id")
        if shape in LINE_SHAPES:
            pts = el.get("points") or []
            if len(pts) < 2:
                findings.append(f"element {eid!r}: a {shape} needs 'points' with at least two [x, y] pairs")
                continue
            pts = [(ox + p[0], oy + p[1]) for p in pts]
            lines.append((el, pts))
            continue
        if shape not in BOX_SHAPES + ("zone",):
            findings.append(f"element {eid!r}: unknown shape {shape!r}; known: {', '.join(BOX_SHAPES + ('zone',) + LINE_SHAPES)}")
            shape = "card"
        x, y, w = el.get("x"), el.get("y"), el.get("w")
        if not all(isinstance(v, (int, float)) for v in (x, y, w)):
            findings.append(f"element {eid!r}: needs numeric 'x', 'y' and 'w'")
            continue
        h = el.get("h")
        if shape == "circle":
            h = h or w
            if h != w:
                findings.append(f"element {eid!r}: a circle needs w == h; use shape 'ellipse'")
        if shape == "zone":
            if not isinstance(h, (int, float)):
                findings.append(f"element {eid!r}: a zone needs 'h'")
                continue
            zb = Box(eid, ox + x, oy + y, w, h, zone=dict(title=el.get("title"), dashed=el.get("dashed"), _grid=True))
            zboxes.append(zb)
            sized.append(zb)
            continue
        if shape == "text":
            latin = th["font"]["latin_w"]
            tl = wrap(el.get("title", ""), L["title_size"], latin, w) if el.get("title") else []
            dl = wrap(el["desc"], L["desc_size"], latin, w) if el.get("desc") else []
            need = len(tl) * L["title_size"] * 1.3 + ((L["desc_gap"] if tl else 0) + len(dl) * L["desc_size"] * 1.45 if dl else 0)
        else:
            tl, dl, need = node_metrics(el, th, w)
        el["_lines"] = (tl, dl)
        if isinstance(h, (int, float)):
            if shape != "text":  # a fixed h only has to hold the text block plus half the usual padding
                need = len(tl) * L["title_size"] * 1.3 + ((L["desc_gap"] + len(dl) * L["desc_size"] * 1.45) if dl else 0) + L["card_pad_y"]
                need *= 1.7 if shape == "diamond" else 1.35 if shape in ROUND_SHAPES else 1
            if need > h + 1:
                findings.append(f"element {eid!r}: text needs {need:.0f}px of height but h is {h}; raise h or w, or shorten the text")
        else:
            h = need
        b = Box(eid, ox + x, oy + y, w, h, node=el)
        boxes[eid] = b
        sized.append(b)
    # overlap: two boxes may not intersect; a box is either fully inside a zone or clear of it
    blist = list(boxes.values())
    for i, a in enumerate(blist):
        for b in blist[i + 1:]:
            if _overlap(a, b):
                findings.append(f"elements {a.id!r} and {b.id!r} overlap; move one or shrink it")
    zts = L["zone_title_size"]
    for z in zboxes:
        tbox = Box("", z.x + L["zone_pad"] - 6, z.y + L["zone_pad"] - 4, text_w(z.zone.get("title") or "", zts, th["font"]["latin_w"]) + 12, zts * 1.4 + 4) if z.zone.get("title") else None
        for b in blist + [o for o in zboxes if o is not z]:
            if _overlap(b, z) and not _inside(b, z) and not _inside(z, b):
                findings.append(f"element {b.id!r} straddles the edge of zone {z.id!r}; put it fully inside or outside")
            elif tbox and _inside(b, z) and _overlap(b, tbox):
                findings.append(f"element {b.id!r} covers the title of zone {z.id!r}; move it down")
    if W is not None or H is not None:
        cw, ch = W or 10 ** 9, H or 10 ** 9
        for b in sized:
            if b.x < ox or b.y < oy or b.r > ox + cw or b.b > oy + ch:
                findings.append(f"element {b.id!r} goes past the canvas ({W}x{H}); move it in or enlarge the canvas")
        for el, pts in lines:
            if any(p[0] < ox or p[1] < oy or p[0] > ox + cw or p[1] > oy + ch for p in pts):
                findings.append(f"element {el.get('id')!r} goes past the canvas ({W}x{H})")
    else:
        for b in sized:
            if b.x < ox or b.y < oy:
                findings.append(f"element {b.id!r} has a negative x or y")
    zboxes.sort(key=lambda z: -z.w * z.h)  # outer zones first
    ext = {}
    edges, labels, holes = draw_edges(spec, th, boxes, "grid", findings, zone_title_boxes(zboxes, th), ext)
    if W and H and (ext.get("right", 0) > ox + W or ext.get("bottom", 0) > oy + H):
        findings.append(f"an edge or its label goes past the canvas ({W}x{H}); enlarge the canvas or move the boxes")
    E = th["edge"]
    for el, pts in lines:
        col = role_style(th, el.get("role", "plain"), findings, f"element {el.get('id')!r}").get("accent", E["color"]) if el.get("role") else E["color"]
        key = f"line:{el.get('id')}"
        if el.get("shape") == "arrow":
            edges.append(draw_arrow(pts, th, col, E["width"], key, dashed=el.get("dashed"), both=el.get("both")))
        else:
            segs = [line_seg(p, q) for p, q in zip(pts, pts[1:]) if _dist(p, q) > 0.01]
            edges.append(draw_shape(segs, th, key, stroke=col, sw=E["width"], dash=E.get("dash") if el.get("dashed") else None, closed=False, ends=0.6))
    right = ox + W if W else max([b.r for b in sized] + [p[0] for _, ps in lines for p in ps] + [ox, ext.get("right", 0)])
    bottom = oy + H if H else max([b.b for b in sized] + [p[1] for _, ps in lines for p in ps] + [oy, ext.get("bottom", 0)])
    return dict(boxes=boxes, zboxes=zboxes, right=right, bottom=bottom, edges=edges, labels=labels, holes=holes)


LAYOUTS = {"tree": layout_tree, "lanes": layout_lanes, "tasks": layout_tasks, "entities": layout_entities,
           "matrix": layout_matrix, "canvas": layout_canvas}
