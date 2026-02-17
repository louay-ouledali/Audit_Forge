"""SVG chart generation for PDF and HTML reports — fully offline, no JS dependencies."""
from __future__ import annotations

import math
from typing import Sequence


def generate_donut_svg(
    segments: Sequence[dict],
    size: int = 180,
    title: str = "",
) -> str:
    """Return an SVG donut chart.

    Each segment: ``{"label": str, "value": int|float, "color": str}``.
    """
    total = sum(s["value"] for s in segments if s["value"] > 0)
    if total == 0:
        return ""

    cx = size / 2
    title_gap = 20 if title else 0
    cy = size / 2 + title_gap
    r_out = size / 2 - 12
    r_in = r_out * 0.58

    arcs: list[str] = []
    angle = -90.0  # start from 12-o'clock

    for seg in segments:
        val = seg["value"]
        if val <= 0:
            continue
        sweep = (val / total) * 360
        if sweep >= 359.99:
            sweep = 359.99
        ea = angle + sweep
        sa_r, ea_r = math.radians(angle), math.radians(ea)

        x1o = cx + r_out * math.cos(sa_r)
        y1o = cy + r_out * math.sin(sa_r)
        x2o = cx + r_out * math.cos(ea_r)
        y2o = cy + r_out * math.sin(ea_r)
        x1i = cx + r_in * math.cos(ea_r)
        y1i = cy + r_in * math.sin(ea_r)
        x2i = cx + r_in * math.cos(sa_r)
        y2i = cy + r_in * math.sin(sa_r)
        lf = 1 if sweep > 180 else 0

        arcs.append(
            f'<path d="M{x1o:.1f},{y1o:.1f} '
            f"A{r_out:.1f},{r_out:.1f} 0 {lf},1 {x2o:.1f},{y2o:.1f} "
            f"L{x1i:.1f},{y1i:.1f} "
            f'A{r_in:.1f},{r_in:.1f} 0 {lf},0 {x2i:.1f},{y2i:.1f}Z" '
            f'fill="{seg["color"]}"/>'
        )
        angle = ea

    center = (
        f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" '
        f'font-size="20" font-weight="700" fill="#1e293b">{total}</text>'
        f'<text x="{cx}" y="{cy + 13}" text-anchor="middle" '
        f'font-size="8" fill="#64748b" letter-spacing="1">TOTAL</text>'
    )

    legend: list[str] = []
    ly = size + title_gap + 8
    active = [s for s in segments if s["value"] > 0]
    for i, seg in enumerate(active):
        pct = round(seg["value"] / total * 100, 1)
        col_x = (i % 2) * (size // 2) + 5
        row_y = ly + (i // 2) * 15
        legend.append(
            f'<rect x="{col_x}" y="{row_y}" width="8" height="8" rx="2" fill="{seg["color"]}"/>'
            f'<text x="{col_x + 12}" y="{row_y + 8}" font-size="8" fill="#475569">'
            f'{_svg_esc(seg["label"])}: {seg["value"]} ({pct}%)</text>'
        )

    legend_rows = math.ceil(len(active) / 2)
    total_h = int(ly + legend_rows * 15 + 5)

    title_el = ""
    if title:
        title_el = (
            f'<text x="{cx}" y="13" text-anchor="middle" '
            f'font-size="10" font-weight="600" fill="#1e293b">{_svg_esc(title)}</text>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{total_h}" '
        f'style="font-family:Segoe UI,sans-serif">'
        f"{title_el}{''.join(arcs)}{center}{''.join(legend)}"
        f"</svg>"
    )


def generate_hbar_svg(
    items: Sequence[dict],
    width: int = 300,
    title: str = "",
    show_pct: bool = True,
) -> str:
    """Horizontal bar chart.

    items: ``[{"label": str, "value": num, "color": str}]``.
    """
    if not items:
        return ""

    bar_h = 20
    gap = 5
    lbl_w = 90
    val_w = 45
    chart_w = width - lbl_w - val_w - 10
    mx = max(i["value"] for i in items) or 1

    title_off = 20 if title else 0
    h = title_off + len(items) * (bar_h + gap) + 8

    bars: list[str] = []
    for i, item in enumerate(items):
        y = title_off + i * (bar_h + gap) + 4
        bw = max((item["value"] / mx) * chart_w, 0)
        suffix = "%" if show_pct else ""
        bars.append(
            f'<text x="{lbl_w - 4}" y="{y + bar_h / 2 + 4}" text-anchor="end" '
            f'font-size="8" fill="#475569">{_svg_esc(str(item["label"]))}</text>'
            f'<rect x="{lbl_w}" y="{y}" width="{bw:.1f}" height="{bar_h}" '
            f'rx="3" fill="{item["color"]}" opacity="0.85"/>'
            f'<text x="{lbl_w + bw + 4:.1f}" y="{y + bar_h / 2 + 4}" '
            f'font-size="8" font-weight="600" fill="#1e293b">{item["value"]}{suffix}</text>'
        )

    title_el = ""
    if title:
        title_el = (
            f'<text x="{width / 2}" y="13" text-anchor="middle" '
            f'font-size="10" font-weight="600" fill="#1e293b">{_svg_esc(title)}</text>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h}" '
        f'style="font-family:Segoe UI,sans-serif">'
        f"{title_el}{''.join(bars)}"
        f"</svg>"
    )


def _svg_esc(text: str) -> str:
    """Escape text for safe inclusion in SVG elements."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def generate_stacked_hbar_svg(
    items: Sequence[dict],
    width: int = 400,
    title: str = "",
) -> str:
    """Stacked horizontal bar chart.

    items: ``[{"label": str, "passed": int, "failed": int}]``.
    """
    if not items:
        return ""

    bar_h = 20
    gap = 6
    lbl_w = 100
    val_w = 50
    chart_w = width - lbl_w - val_w - 10
    mx = max(i["passed"] + i["failed"] for i in items) or 1

    title_off = 22 if title else 0
    h = title_off + len(items) * (bar_h + gap) + 20  # 20 for legend

    bars: list[str] = []
    for i, item in enumerate(items):
        y = title_off + i * (bar_h + gap) + 4
        pw = (item["passed"] / mx) * chart_w
        fw = (item["failed"] / mx) * chart_w
        lbl = item["label"]
        if len(lbl) > 18:
            lbl = lbl[:16] + ".."
        bars.append(
            f'<text x="{lbl_w - 4}" y="{y + bar_h / 2 + 4}" text-anchor="end" '
            f'font-size="8" fill="#475569">{_svg_esc(lbl)}</text>'
            f'<rect x="{lbl_w}" y="{y}" width="{pw:.1f}" height="{bar_h}" fill="#22c55e" rx="2"/>'
            f'<rect x="{lbl_w + pw:.1f}" y="{y}" width="{fw:.1f}" height="{bar_h}" fill="#ef4444" rx="2"/>'
            f'<text x="{lbl_w + pw + fw + 4:.1f}" y="{y + bar_h / 2 + 4}" '
            f'font-size="7" fill="#64748b">{item["passed"] + item["failed"]}</text>'
        )

    # Legend
    ly = title_off + len(items) * (bar_h + gap) + 8
    legend = (
        f'<rect x="{lbl_w}" y="{ly}" width="8" height="8" rx="2" fill="#22c55e"/>'
        f'<text x="{lbl_w + 12}" y="{ly + 8}" font-size="7" fill="#475569">Passed</text>'
        f'<rect x="{lbl_w + 60}" y="{ly}" width="8" height="8" rx="2" fill="#ef4444"/>'
        f'<text x="{lbl_w + 72}" y="{ly + 8}" font-size="7" fill="#475569">Failed</text>'
    )

    title_el = ""
    if title:
        title_el = (
            f'<text x="{width / 2}" y="14" text-anchor="middle" '
            f'font-size="10" font-weight="600" fill="#1e293b">{_svg_esc(title)}</text>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h}" '
        f'style="font-family:Segoe UI,sans-serif">'
        f"{title_el}{''.join(bars)}{legend}"
        f"</svg>"
    )
