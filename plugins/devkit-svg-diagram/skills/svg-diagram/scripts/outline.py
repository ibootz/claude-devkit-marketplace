"""Edge ends on the drawn outline of non-rectangular nodes.

Routes in render.py end on a node's bounding box. Diamonds, pills, circles and ellipses sit inside that
box -- a rounded diamond's tips are cut back by the corner curve, about 1/16 of its width on the left and
right -- so the arrowhead stops short of the shape. snap_ends extends the first / last segment inward
until it meets the outline.
"""
from __future__ import annotations

import math


def _bezier(s, t):
    u = 1 - t
    return tuple(u ** 3 * s[0][k] + 3 * u * u * t * s[1][k] + 3 * u * t * t * s[2][k] + t ** 3 * s[3][k] for k in (0, 1))


def ray_hit(p, d, segs, steps=24):
    """Distance along the unit ray p + t*d to its first crossing with the cubic outline `segs`, or None."""
    best = None
    for s in segs:
        prev = s[0]
        for i in range(1, steps + 1):
            cur = _bezier(s, i / steps)
            ex, ey = cur[0] - prev[0], cur[1] - prev[1]
            den = d[0] * ey - d[1] * ex
            if abs(den) > 1e-9:
                wx, wy = prev[0] - p[0], prev[1] - p[1]
                t = (wx * ey - wy * ex) / den  # along the ray
                u = (wx * d[1] - wy * d[0]) / den  # along this piece of outline
                if t >= -0.01 and -1e-6 <= u <= 1 + 1e-6 and (best is None or t < best):
                    best = t
            prev = cur
    return best


def snap_ends(pts, a, b, outline):
    """pts: route from box a to box b. outline(box) -> the node's cubic segments, or None when the shape
    fills its box (cards). Returns pts with each end moved onto the drawn outline."""
    pts = list(pts)
    if len(pts) < 2:
        return pts
    for box, i, j in ((a, 0, 1), (b, -1, -2)):
        segs = outline(box)
        if not segs:
            continue
        p, q = pts[i], pts[j]
        dist = math.hypot(p[0] - q[0], p[1] - q[1])
        if not dist:
            continue
        d = ((p[0] - q[0]) / dist, (p[1] - q[1]) / dist)  # pointing into the box
        t = ray_hit(p, d, segs)
        if t and t < min(box.w, box.h) / 2:
            pts[i] = (p[0] + d[0] * t, p[1] + d[1] * t)
    return pts
