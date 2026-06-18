# -*- coding: utf-8 -*-
"""
纯 Python SVG 图表生成器（构建期，无 JS）。
所有配色用站点 CSS 变量（var(--crimson) 等），因此自动适配深浅主题。
"""
import html

# 图表系列配色（在 custom.css 里同名定义）
SERIES_COLORS = ["--crimson", "--gold", "--growth", "--c-teal", "--c-violet", "--c-amber"]


def _t(x) -> str:
    """SVG 文本转义。"""
    return html.escape(str(x), quote=True)


def _f(v) -> str:
    """格式化数值。"""
    try:
        f = float(v)
        return str(int(f)) if f.is_integer() else f"{f:.1f}"
    except (TypeError, ValueError):
        return str(v)


def line_chart_svg(title: str, x_labels: list, series: list, h: int = 320) -> str:
    """多系列折线图。series = [{"label":..,"values":[..]}]"""
    W = 760
    PT, PB, PL, PR = 46, 40, 40, 16
    plot_w = W - PL - PR
    plot_h = h - PT - PB
    n = len(x_labels)
    if n == 0:
        return _empty(title, W, h)

    all_vals = [v for s in series for v in s["values"]]
    vmax = max(all_vals) if all_vals else 1
    vmax = vmax * 1.15 if vmax > 0 else 1

    def xp(i):
        return PL + (plot_w * i / (n - 1)) if n > 1 else PL + plot_w / 2

    def yp(v):
        return PT + plot_h - (plot_h * (v / vmax) if vmax else 0)

    parts = [f'<svg class="chart line" viewBox="0 0 {W} {h}" role="img" aria-label="{_t(title)}" preserveAspectRatio="xMidYMid meet">']
    parts.append(f'<text class="ch-title" x="0" y="20">{_t(title)}</text>')

    # grid + y labels
    for g in range(5):
        gy = PT + plot_h * g / 4
        val = vmax * (1 - g / 4)
        parts.append(f'<line class="ch-grid" x1="{PL}" y1="{gy:.1f}" x2="{W-PR}" y2="{gy:.1f}"/>')
        parts.append(f'<text class="ch-axis" x="{PL-6}" y="{gy+3:.1f}" text-anchor="end">{_f(val)}</text>')

    # x labels
    step = max(1, n // 8)
    for i, lab in enumerate(x_labels):
        if i % step == 0 or i == n - 1:
            parts.append(f'<text class="ch-axis" x="{xp(i):.1f}" y="{h-14}" text-anchor="middle">{_t(lab)}</text>')

    # series
    for si, s in enumerate(series):
        color = SERIES_COLORS[si % len(SERIES_COLORS)]
        vals = s["values"]
        pts = " ".join(f"{xp(i):.1f},{yp(v):.1f}" for i, v in enumerate(vals))
        parts.append(f'<polyline class="ch-line" style="--sc:var({color})" points="{pts}" fill="none"/>')
        for i, v in enumerate(vals):
            parts.append(f'<circle class="ch-pt" style="--sc:var({color})" cx="{xp(i):.1f}" cy="{yp(v):.1f}" r="3"><title>{_t(s["label"])} {_t(x_labels[i])}: {_f(v)}</title></circle>')

    # legend
    lx = PL
    ly = 6
    for si, s in enumerate(series):
        color = SERIES_COLORS[si % len(SERIES_COLORS)]
        parts.append(f'<rect class="ch-legend-swatch" style="--sc:var({color})" x="{lx}" y="{ly}" width="10" height="10" rx="2"/>')
        parts.append(f'<text class="ch-legend" x="{lx+15}" y="{ly+9}">{_t(s["label"])}</text>')
        lx += 18 + len(s["label"]) * 9 + 16

    parts.append("</svg>")
    return "\n".join(parts)


def heatmap_svg(title: str, row_labels: list, col_labels: list, matrix: list, h=None) -> str:
    """热力图。matrix[row][col] = 数值，自动归一化到最大值。"""
    cell_w, cell_h, gap = 50, 30, 3
    lab_l, lab_t = 104, 24
    nrows = len(row_labels)
    ncols = len(col_labels)
    if nrows == 0 or ncols == 0:
        return _empty(title, 400, 120)
    W = lab_l + ncols * (cell_w + gap) + 4
    Hh = lab_t + nrows * (cell_h + gap) + 6

    flat = [matrix[r][c] for r in range(nrows) for c in range(ncols)]
    vmax = max(flat) if flat else 1

    parts = [f'<svg class="chart heat" viewBox="0 0 {W} {Hh}" role="img" aria-label="{_t(title)}" preserveAspectRatio="xMidYMid meet">']
    parts.append(f'<text class="ch-title" x="0" y="16">{_t(title)}</text>')

    # col labels (dates)
    for c, lab in enumerate(col_labels):
        cx = lab_l + c * (cell_w + gap) + cell_w / 2
        parts.append(f'<text class="ch-axis" x="{cx:.1f}" y="{lab_t-8}" text-anchor="middle">{_t(lab)}</text>')

    for r, rname in enumerate(row_labels):
        ry = lab_t + r * (cell_h + gap)
        parts.append(f'<text class="ch-rowlabel" x="{lab_l-8}" y="{ry+cell_h/2+4:.1f}" text-anchor="end">{_t(rname)}</text>')
        for c in range(ncols):
            v = matrix[r][c]
            norm = (v / vmax) if vmax else 0
            cx = lab_l + c * (cell_w + gap)
            op = round(0.10 + 0.90 * norm, 3)
            parts.append(f'<rect class="ch-cell" x="{cx:.1f}" y="{ry:.1f}" width="{cell_w}" height="{cell_h}" rx="3" style="fill-opacity:{op}"><title>{_t(rname)} {_t(col_labels[c])}: {_f(v)}</title></rect>')

    parts.append("</svg>")
    return "\n".join(parts)


def bar_chart_svg(title: str, items: list, w: int = 600, top: int = 12) -> str:
    """水平条形图。items = [(label, value)] 已排序。"""
    items = list(items)[:top]
    if not items:
        return _empty(title, w, 80)
    vmax = max((v for _, v in items), default=1)
    row_h, gap, lab_w, val_w, pt = 28, 6, 104, 52, 30
    Hh = pt + len(items) * (row_h + gap) + 6
    bar_max = w - lab_w - val_w - 8

    parts = [f'<svg class="chart bar" viewBox="0 0 {w} {Hh}" role="img" aria-label="{_t(title)}" preserveAspectRatio="xMidYMid meet">']
    parts.append(f'<text class="ch-title" x="0" y="18">{_t(title)}</text>')

    for i, (label, val) in enumerate(items):
        y = pt + i * (row_h + gap)
        bw = (val / vmax) * bar_max if vmax else 0
        parts.append(f'<text class="ch-rowlabel" x="{lab_w-8}" y="{y+row_h/2+4:.1f}" text-anchor="end">{_t(label)}</text>')
        parts.append(f'<rect class="ch-bar-track" x="{lab_w}" y="{y:.1f}" width="{bar_max:.1f}" height="{row_h}" rx="3"/>')
        parts.append(f'<rect class="ch-bar" x="{lab_w}" y="{y:.1f}" width="{bw:.1f}" height="{row_h}" rx="3"><title>{_t(label)}: {_f(val)}</title></rect>')
        parts.append(f'<text class="ch-value" x="{lab_w+bw+6:.1f}" y="{y+row_h/2+4:.1f}">{_f(val)}</text>')

    parts.append("</svg>")
    return "\n".join(parts)


def _empty(title: str, w: int, h: int) -> str:
    return (f'<svg class="chart empty" viewBox="0 0 {w} {h}" role="img" aria-label="{_t(title)}">'
            f'<text class="ch-title" x="0" y="20">{_t(title)}</text>'
            f'<text class="ch-empty" x="{w/2}" y="{h/2}" text-anchor="middle">暂无数据</text></svg>')
