"""
Sparkline rendering helpers (Phase 3.5).

Produces a small SVG <polyline> for use in watchlist rows. We avoid
adding a new dependency (e.g. dash_svg) by inlining the SVG inside an
`html.Img` element via a data URL. This keeps the watchlist row a pure
Dash render with no client-side JS.

When real recent-close data is available (e.g. last 20 daily closes
from `storage.load_daily_data`), pass it as `values`. Otherwise call
`seeded_values()` to generate a deterministic line per stock id —
this matches the reference PNG behavior where every favorite has a
visible line, even before historical data is fetched.
"""

from __future__ import annotations

import urllib.parse
from typing import List, Optional

from dash import html


# Token-aligned colors. Kept as raw hex because SVG needs literal values.
_UP_COLOR = "#EF5350"      # var(--up)
_DOWN_COLOR = "#26A69A"    # var(--down)
_FLAT_COLOR = "#888888"


def seeded_values(seed: int, points: int = 24, vol: float = 0.55) -> List[float]:
    """Deterministic walk in [0, 1] to feed `render_spark()` as a fallback.

    Mirrors design/afs/data.jsx::sparkPath so the visual matches the
    reference PNGs even when the backend has no real history yet.
    """
    if seed <= 0:
        seed = 1
    x = seed * 9301 + 49297
    ys: List[float] = []
    y = 0.5  # start at midline
    for _ in range(points):
        x = (x * 9301 + 49297) % 233280
        r = x / 233280
        y += (r - 0.5) * vol * 0.4
        if y < 0.05:
            y = 0.05
        elif y > 0.95:
            y = 0.95
        ys.append(y)
    return ys


def _resolve_color(direction: str) -> str:
    if direction == "down":
        return _DOWN_COLOR
    if direction == "flat":
        return _FLAT_COLOR
    return _UP_COLOR


def render_spark(
    values: Optional[List[float]],
    direction: str = "up",
    w: int = 56,
    h: int = 20,
    seed: Optional[int] = None,
) -> html.Img:
    """Return an inline SVG sparkline as `html.Img`.

    `values` are arbitrary numeric samples; they are min/max-normalized
    to fit the height. When `values` is empty/None, a seeded fallback
    is generated from `seed` (typically the integer stock id).
    """
    if not values:
        norm = seeded_values(seed or 1)
    else:
        v_min = min(values)
        v_max = max(values)
        if v_max <= v_min:
            norm = [0.5] * len(values)
        else:
            span = v_max - v_min
            norm = [(v - v_min) / span for v in values]

    if len(norm) < 2:
        norm = norm * 2 if norm else [0.5, 0.5]

    pad = 2
    usable_h = max(1, h - pad * 2)
    dx = w / (len(norm) - 1)
    parts: List[str] = []
    for i, n in enumerate(norm):
        x = round(i * dx, 1)
        # invert y: high value => smaller y
        y = round(pad + (1.0 - n) * usable_h, 1)
        parts.append(f"{'M' if i == 0 else 'L'}{x} {y}")
    path_d = " ".join(parts)
    color = _resolve_color(direction)

    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {w} {h}'"
        f" width='{w}' height='{h}'>"
        f"<path d='{path_d}' fill='none' stroke='{color}'"
        f" stroke-width='1.2' stroke-linejoin='round' stroke-linecap='round'/></svg>"
    )
    src = "data:image/svg+xml;utf8," + urllib.parse.quote(svg)
    return html.Img(
        src=src,
        width=w,
        height=h,
        className="watch-spark",
        alt="",
        draggable="false",
    )
