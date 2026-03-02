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
        f'viewBox="0 0 {size} {total_h}" '
        f'style="font-family:Segoe UI,sans-serif;max-width:100%;height:auto">'
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
        f'viewBox="0 0 {width} {h}" '
        f'style="font-family:Segoe UI,sans-serif;max-width:100%;height:auto">'
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
        f'viewBox="0 0 {width} {h}" '
        f'style="font-family:Segoe UI,sans-serif;max-width:100%;height:auto">'
        f"{title_el}{''.join(bars)}{legend}"
        f"</svg>"
    )


# ---------------------------------------------------------------------------
# Risk Heatmap (groups × severity → cell intensity)
# ---------------------------------------------------------------------------

def generate_risk_heatmap_svg(
    groups: Sequence[dict],
    width: int = 500,
) -> str:
    """SVG risk heatmap grid — rows = groups, columns = severity levels.

    Each group dict: ``{"name": str, "sev_counts": {"critical": int, "high": int, ...}}``.
    Returns empty string if no data.
    """
    if not groups:
        return ""

    severity_levels = ["critical", "high", "medium", "low", "informational"]
    sev_labels = ["CRIT", "HIGH", "MED", "LOW", "INFO"]
    sev_colors = {
        "critical":      (220, 38, 38),   # red
        "high":          (234, 88, 12),   # orange
        "medium":        (217, 119, 6),   # amber
        "low":           (37, 99, 235),   # blue
        "informational": (107, 114, 128), # gray
    }

    cell_w = 60
    cell_h = 28
    lbl_w = 140
    hdr_h = 24
    pad = 4

    # Truncate group names
    rows = []
    for g in groups:
        lbl = g["name"]
        if len(lbl) > 22:
            lbl = lbl[:20] + ".."
        rows.append({"label": lbl, "sev_counts": g.get("sev_counts", {})})

    total_w = lbl_w + len(severity_levels) * (cell_w + pad) + 10
    total_h = hdr_h + len(rows) * (cell_h + pad) + 10
    title_h = 22
    total_h += title_h

    # Find max count for intensity scaling
    max_count = 1
    for r in rows:
        for sev in severity_levels:
            max_count = max(max_count, r["sev_counts"].get(sev, 0))

    parts: list[str] = []


    # Title
    parts.append(
        f'<text x="{total_w / 2}" y="14" text-anchor="middle" '
        f'font-size="10" font-weight="600" fill="#1e293b">Risk Heatmap - Failed Rules by Group &amp; Severity</text>'
    )

    # Column headers
    for ci, lbl in enumerate(sev_labels):
        x = lbl_w + ci * (cell_w + pad) + cell_w / 2
        parts.append(
            f'<text x="{x}" y="{title_h + hdr_h - 6}" text-anchor="middle" '
            f'font-size="8" font-weight="700" fill="#475569">{lbl}</text>'
        )

    # Rows
    for ri, row in enumerate(rows):
        y = title_h + hdr_h + ri * (cell_h + pad)

        # Row label
        parts.append(
            f'<text x="{lbl_w - 6}" y="{y + cell_h / 2 + 4}" text-anchor="end" '
            f'font-size="8" fill="#475569">{_svg_esc(row["label"])}</text>'
        )

        for ci, sev in enumerate(severity_levels):
            x = lbl_w + ci * (cell_w + pad)
            count = row["sev_counts"].get(sev, 0)

            if count == 0:
                fill = "#f1f5f9"
                text_color = "#94a3b8"
            else:
                r, g, b = sev_colors[sev]
                intensity = min(count / max_count, 1.0)
                # Blend towards white for low counts
                alpha = 0.15 + 0.85 * intensity
                fr = int(255 + (r - 255) * alpha)
                fg = int(255 + (g - 255) * alpha)
                fb = int(255 + (b - 255) * alpha)
                fill = f"rgb({fr},{fg},{fb})"
                text_color = "#1e293b" if intensity < 0.6 else "#fff"

            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell_w}" height="{cell_h}" rx="4" fill="{fill}" '
                f'stroke="#e2e8f0" stroke-width="1"/>'
                f'<text x="{x + cell_w / 2}" y="{y + cell_h / 2 + 4}" text-anchor="middle" '
                f'font-size="9" font-weight="600" fill="{text_color}">{count}</text>'
            )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="{total_h}" '
        f'viewBox="0 0 {total_w} {total_h}" '
        f'style="font-family:Segoe UI,sans-serif;max-width:100%;height:auto">'
        f"{''.join(parts)}"
        f"</svg>"
    )


# ---------------------------------------------------------------------------
# Mini Donut (small, for inline per-group usage)
# ---------------------------------------------------------------------------

def generate_mini_donut_svg(passed: int, failed: int, errors: int = 0, size: int = 64) -> str:
    """Tiny inline donut — suitable for embedding beside group headers."""
    total = passed + failed + errors
    if total == 0:
        return ""

    cx = size / 2
    cy = size / 2
    r_out = size / 2 - 4
    r_in = r_out * 0.55

    segments = []
    if passed:
        segments.append({"value": passed, "color": "#22c55e"})
    if failed:
        segments.append({"value": failed, "color": "#ef4444"})
    if errors:
        segments.append({"value": errors, "color": "#8b5cf6"})

    arcs: list[str] = []
    angle = -90.0
    for seg in segments:
        sweep = (seg["value"] / total) * 360
        if sweep >= 359.99:
            sweep = 359.99
        if sweep <= 0:
            continue
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

    # Center percentage
    pct = round((passed / total) * 100)
    center = (
        f'<text x="{cx}" y="{cy + 3}" text-anchor="middle" '
        f'font-size="10" font-weight="700" fill="#1e293b">{pct}%</text>'
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" '
        f'style="font-family:Segoe UI,sans-serif;max-width:100%;height:auto">'
        f"{''.join(arcs)}{center}"
        f"</svg>"
    )


# ---------------------------------------------------------------------------
# False-Positive Suspect Gauge
# ---------------------------------------------------------------------------

def generate_fp_gauge_svg(
    high: int,
    medium: int,
    low: int,
    total_failed: int,
    width: int = 280,
) -> str:
    """Semi-circular gauge showing false-positive suspect distribution.

    Parameters
    ----------
    high, medium, low : int
        Count of suspects at each confidence level.
    total_failed : int
        Total FAIL findings (denominator for percentage).
    """
    total_suspects = high + medium + low
    if total_suspects == 0:
        return ""

    pct = round((total_suspects / total_failed) * 100, 1) if total_failed > 0 else 0
    h = 180
    cx = width / 2
    cy = h - 30

    r = 80
    stroke_w = 16

    # Background arc (180 degrees, left to right)
    bg_arc = (
        f'<path d="M{cx - r},{cy} A{r},{r} 0 0,1 {cx + r},{cy}" '
        f'fill="none" stroke="#e2e8f0" stroke-width="{stroke_w}" stroke-linecap="round"/>'
    )

    # Segments: high (red), medium (amber), low (blue)
    segments = []
    if high > 0:
        segments.append({"value": high, "color": "#dc2626"})
    if medium > 0:
        segments.append({"value": medium, "color": "#d97706"})
    if low > 0:
        segments.append({"value": low, "color": "#3b82f6"})

    arcs_svg: list[str] = []
    angle_start = 180  # left side (pi radians)
    total_angle = 180  # sweep spans 180 degrees

    for seg in segments:
        sweep = (seg["value"] / total_suspects) * total_angle
        angle_end = angle_start + sweep
        sa_r = math.radians(angle_start)
        ea_r = math.radians(angle_end)
        x1 = cx + r * math.cos(sa_r)
        y1 = cy + r * math.sin(sa_r)
        x2 = cx + r * math.cos(ea_r)
        y2 = cy + r * math.sin(ea_r)
        lf = 1 if sweep > 180 else 0
        arcs_svg.append(
            f'<path d="M{x1:.1f},{y1:.1f} A{r},{r} 0 {lf},1 {x2:.1f},{y2:.1f}" '
            f'fill="none" stroke="{seg["color"]}" stroke-width="{stroke_w}" stroke-linecap="butt"/>'
        )
        angle_start = angle_end

    # Center text
    center = (
        f'<text x="{cx}" y="{cy - 12}" text-anchor="middle" '
        f'font-size="22" font-weight="800" fill="#1e293b">{total_suspects}</text>'
        f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" '
        f'font-size="8" fill="#64748b" letter-spacing="0.5">SUSPECTS ({pct}%)</text>'
    )

    # Legend
    legend_y = h - 10
    legend = (
        f'<rect x="{cx - 95}" y="{legend_y}" width="8" height="8" rx="2" fill="#dc2626"/>'
        f'<text x="{cx - 83}" y="{legend_y + 8}" font-size="7.5" fill="#475569">High: {high}</text>'
        f'<rect x="{cx - 30}" y="{legend_y}" width="8" height="8" rx="2" fill="#d97706"/>'
        f'<text x="{cx - 18}" y="{legend_y + 8}" font-size="7.5" fill="#475569">Med: {medium}</text>'
        f'<rect x="{cx + 35}" y="{legend_y}" width="8" height="8" rx="2" fill="#3b82f6"/>'
        f'<text x="{cx + 47}" y="{legend_y + 8}" font-size="7.5" fill="#475569">Low: {low}</text>'
    )

    title_el = (
        f'<text x="{cx}" y="14" text-anchor="middle" '
        f'font-size="10" font-weight="600" fill="#1e293b">Potential False Positives</text>'
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h}" '
        f'viewBox="0 0 {width} {h}" '
        f'style="font-family:Segoe UI,sans-serif;max-width:100%;height:auto">'
        f"{title_el}{bg_arc}{''.join(arcs_svg)}{center}{legend}"
        f"</svg>"
    )


# ---------------------------------------------------------------------------
# Category Treemap — shows section compliance as proportional rectangles
# ---------------------------------------------------------------------------

def generate_treemap_svg(
    categories: Sequence[dict],
    width: int = 500,
    height: int = 200,
    title: str = "",
) -> str:
    """Simple single-row treemap for category compliance.

    categories: ``[{"label": str, "total": int, "passed": int, "failed": int}]``.
    Each rectangle is proportional to total count, colored by compliance %.
    """
    if not categories:
        return ""

    grand_total = sum(c["total"] for c in categories)
    if grand_total == 0:
        return ""

    title_h = 24 if title else 0
    legend_h = 20
    total_h = title_h + height + legend_h + 8
    map_y = title_h + 4
    map_h = height - 8

    parts: list[str] = []

    if title:
        parts.append(
            f'<text x="{width / 2}" y="14" text-anchor="middle" '
            f'font-size="10" font-weight="600" fill="#1e293b">{_svg_esc(title)}</text>'
        )

    x = 4
    usable_w = width - 8
    for cat in sorted(categories, key=lambda c: c["total"], reverse=True):
        frac = cat["total"] / grand_total
        rect_w = max(frac * usable_w, 20)  # min 20px

        comp = round((cat["passed"] / cat["total"]) * 100) if cat["total"] > 0 else 0
        # Color: green (>= 80), amber (>= 50), red (< 50)
        if comp >= 80:
            fill = "#22c55e"
            text_fill = "#fff"
        elif comp >= 50:
            fill = "#f59e0b"
            text_fill = "#fff"
        else:
            fill = "#ef4444"
            text_fill = "#fff"

        parts.append(
            f'<rect x="{x:.1f}" y="{map_y}" width="{rect_w:.1f}" height="{map_h}" '
            f'rx="4" fill="{fill}" opacity="0.85" stroke="#fff" stroke-width="2"/>'
        )

        # Label inside rectangle (only if wide enough)
        if rect_w > 45:
            lbl = cat["label"]
            if len(lbl) > 14:
                lbl = lbl[:12] + ".."
            mid_x = x + rect_w / 2
            parts.append(
                f'<text x="{mid_x:.1f}" y="{map_y + map_h / 2 - 4}" text-anchor="middle" '
                f'font-size="8" font-weight="700" fill="{text_fill}">{_svg_esc(lbl)}</text>'
                f'<text x="{mid_x:.1f}" y="{map_y + map_h / 2 + 10}" text-anchor="middle" '
                f'font-size="9" font-weight="600" fill="{text_fill}">{comp}%</text>'
                f'<text x="{mid_x:.1f}" y="{map_y + map_h / 2 + 22}" text-anchor="middle" '
                f'font-size="7" fill="{text_fill}" opacity="0.8">{cat["total"]} rules</text>'
            )
        x += rect_w

    # Legend
    ly = title_h + height + 4
    parts.append(
        f'<rect x="4" y="{ly}" width="8" height="8" rx="2" fill="#22c55e"/>'
        f'<text x="16" y="{ly + 8}" font-size="7.5" fill="#475569">≥80% compliant</text>'
        f'<rect x="110" y="{ly}" width="8" height="8" rx="2" fill="#f59e0b"/>'
        f'<text x="122" y="{ly + 8}" font-size="7.5" fill="#475569">50-79%</text>'
        f'<rect x="185" y="{ly}" width="8" height="8" rx="2" fill="#ef4444"/>'
        f'<text x="197" y="{ly + 8}" font-size="7.5" fill="#475569">&lt;50%</text>'
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{total_h}" '
        f'viewBox="0 0 {width} {total_h}" '
        f'style="font-family:Segoe UI,sans-serif;max-width:100%;height:auto">'
        f"{''.join(parts)}"
        f"</svg>"
    )


# ---------------------------------------------------------------------------
# Compliance Radar / Spider Chart — multi-axis category comparison
# ---------------------------------------------------------------------------

def generate_radar_svg(
    categories: Sequence[dict],
    size: int = 280,
    title: str = "",
) -> str:
    """Radar/spider chart for category-level compliance.

    categories: ``[{"label": str, "compliance": float}]`` (0-100 values).
    """
    n = len(categories)
    if n < 3:
        return ""

    title_h = 22 if title else 0
    legend_h = 16
    total_h = size + title_h + legend_h
    cx = size / 2
    cy = size / 2 + title_h
    r_max = size / 2 - 40  # Leave room for labels

    parts: list[str] = []

    if title:
        parts.append(
            f'<text x="{cx}" y="14" text-anchor="middle" '
            f'font-size="10" font-weight="600" fill="#1e293b">{_svg_esc(title)}</text>'
        )

    # Draw concentric guide rings at 25%, 50%, 75%, 100%
    for pct in (25, 50, 75, 100):
        r_ring = r_max * pct / 100
        ring_points = []
        for i in range(n):
            angle = math.radians(360 * i / n - 90)
            px = cx + r_ring * math.cos(angle)
            py = cy + r_ring * math.sin(angle)
            ring_points.append(f"{px:.1f},{py:.1f}")
        ring_points.append(ring_points[0])  # close
        parts.append(
            f'<polygon points="{" ".join(ring_points)}" '
            f'fill="none" stroke="#e2e8f0" stroke-width="0.8"/>'
        )
        # Percentage label on first axis
        angle0 = math.radians(-90)
        lx = cx + r_ring * math.cos(angle0) + 4
        ly_r = cy + r_ring * math.sin(angle0) + 3
        parts.append(
            f'<text x="{lx:.1f}" y="{ly_r:.1f}" font-size="6" fill="#94a3b8">{pct}%</text>'
        )

    # Draw axis lines
    for i in range(n):
        angle = math.radians(360 * i / n - 90)
        px = cx + r_max * math.cos(angle)
        py = cy + r_max * math.sin(angle)
        parts.append(
            f'<line x1="{cx}" y1="{cy}" x2="{px:.1f}" y2="{py:.1f}" '
            f'stroke="#e2e8f0" stroke-width="0.8"/>'
        )

    # Draw data polygon
    data_points = []
    dot_parts: list[str] = []
    for i, cat in enumerate(categories):
        comp = min(max(cat["compliance"], 0), 100)
        r_val = r_max * comp / 100
        angle = math.radians(360 * i / n - 90)
        px = cx + r_val * math.cos(angle)
        py = cy + r_val * math.sin(angle)
        data_points.append(f"{px:.1f},{py:.1f}")

        # Data point dot
        dot_color = "#22c55e" if comp >= 80 else "#f59e0b" if comp >= 50 else "#ef4444"
        dot_parts.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{dot_color}" stroke="#fff" stroke-width="1.5"/>'
        )

    parts.append(
        f'<polygon points="{" ".join(data_points)}" '
        f'fill="rgba(59,130,246,0.15)" stroke="#3b82f6" stroke-width="1.8"/>'
    )
    parts.extend(dot_parts)

    # Axis labels (outside the chart)
    for i, cat in enumerate(categories):
        angle = math.radians(360 * i / n - 90)
        label_r = r_max + 18
        lx = cx + label_r * math.cos(angle)
        ly_l = cy + label_r * math.sin(angle)
        anchor = "middle"
        if abs(math.cos(angle)) > 0.3:
            anchor = "start" if math.cos(angle) > 0 else "end"

        lbl = cat["label"]
        if len(lbl) > 12:
            lbl = lbl[:10] + ".."
        parts.append(
            f'<text x="{lx:.1f}" y="{ly_l:.1f}" text-anchor="{anchor}" '
            f'font-size="7.5" font-weight="600" fill="#475569">{_svg_esc(lbl)}</text>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{total_h}" '
        f'viewBox="0 0 {size} {total_h}" '
        f'style="font-family:Segoe UI,sans-serif;max-width:100%;height:auto">'
        f"{''.join(parts)}"
        f"</svg>"
    )


# ---------------------------------------------------------------------------
# Compliance Waterfall — shows compliance flow from total to category deductions
# ---------------------------------------------------------------------------

def generate_waterfall_svg(
    categories: Sequence[dict],
    total_rules: int,
    total_passed: int,
    width: int = 500,
    title: str = "",
) -> str:
    """Waterfall chart showing how each category contributes to overall failures.

    categories: ``[{"label": str, "failed": int}]`` — sorted by failed desc is recommended.
    """
    if not categories or total_rules == 0:
        return ""

    bar_h = 22
    gap = 6
    lbl_w = 110
    val_w = 50
    chart_w = width - lbl_w - val_w - 10
    title_h = 24 if title else 0
    n_rows = len(categories) + 2  # +2 for start (total) and end (final compliance)
    h = title_h + n_rows * (bar_h + gap) + 10

    parts: list[str] = []

    if title:
        parts.append(
            f'<text x="{width / 2}" y="14" text-anchor="middle" '
            f'font-size="10" font-weight="600" fill="#1e293b">{_svg_esc(title)}</text>'
        )

    # Scale: max bar = total_rules
    scale = chart_w / total_rules if total_rules > 0 else 1

    running = total_rules
    row_idx = 0

    def _draw_bar(label: str, value: int, running_val: int, color: str, is_total: bool = False):
        nonlocal row_idx
        y = title_h + row_idx * (bar_h + gap) + 4

        # Label
        parts.append(
            f'<text x="{lbl_w - 4}" y="{y + bar_h / 2 + 4}" text-anchor="end" '
            f'font-size="8" font-weight="{"700" if is_total else "400"}" fill="#475569">'
            f'{_svg_esc(label)}</text>'
        )

        if is_total:
            bw = running_val * scale
            parts.append(
                f'<rect x="{lbl_w}" y="{y}" width="{bw:.1f}" height="{bar_h}" '
                f'rx="3" fill="{color}" opacity="0.9"/>'
            )
        else:
            # Floating bar showing the deduction
            start_x = lbl_w + running_val * scale
            bw = value * scale
            parts.append(
                f'<rect x="{start_x:.1f}" y="{y}" width="{bw:.1f}" height="{bar_h}" '
                f'rx="3" fill="{color}" opacity="0.85"/>'
            )
            # Connector line from previous bar
            parts.append(
                f'<line x1="{lbl_w + (running_val + value) * scale:.1f}" y1="{y}" '
                f'x2="{lbl_w + (running_val + value) * scale:.1f}" y2="{y + bar_h + gap}" '
                f'stroke="#cbd5e1" stroke-width="1" stroke-dasharray="3,2"/>'
            )

        # Value label
        bw_actual = (running_val if is_total else value) * scale
        parts.append(
            f'<text x="{lbl_w + bw_actual + 6:.1f}" y="{y + bar_h / 2 + 4}" '
            f'font-size="8" font-weight="600" fill="#1e293b">'
            f'{"" if is_total else "-"}{value}</text>'
        )

        row_idx += 1

    # Starting bar: Total Rules
    _draw_bar("Total Rules", total_rules, total_rules, "#3b82f6", is_total=True)

    # Category deductions (sorted by failed count desc)
    sorted_cats = sorted(categories, key=lambda c: c["failed"], reverse=True)
    for cat in sorted_cats:
        if cat["failed"] <= 0:
            continue
        running -= cat["failed"]
        _draw_bar(cat["label"], cat["failed"], running, "#ef4444")

    # Final compliance bar
    _draw_bar("Compliant", total_passed, total_passed, "#22c55e", is_total=True)

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h}" '
        f'viewBox="0 0 {width} {h}" '
        f'style="font-family:Segoe UI,sans-serif;max-width:100%;height:auto">'
        f"{''.join(parts)}"
        f"</svg>"
    )
