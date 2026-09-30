# -*- coding: utf-8 -*-
"""
时序 / 指标出图
===============
把一条 `TimeSeries` 和若干 `IndicatorResult` 画成一张「诊断图」：

    ┌──────────────────────────────────────────┐
    │ 原始序列 + 趋势线 + 滑动平均 + 指标角标      │  ← 主面板
    ├──────────────────────────────────────────┤
    │ 距平（柱）                                 │  ← 每个叠加型指标一块
    ├──────────────────────────────────────────┤
    │ 功率谱（横轴为周期）                        │
    └──────────────────────────────────────────┘
    │ 统计摘要 / MK 检验 / Sen 斜率 → 文字框      │
    └──────────────────────────────────────────┘

这样「选几个指标、点一下」就能得到一张可以直接放进论文或组会的诊断图，
不用再自己写循环读文件、拼时间轴、算统计量。
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np

from ... import style
from .. import indicators as ind_mod
from ..colorbar import split_label
from ..series import SeriesBuilder, TimeSeries
from .base import PlotSpec, RenderResult


def _c(key: str, default: str = "#334155") -> str:
    """安全取主题色：主题里没有这个键也不会崩。"""
    try:
        return style.COLORS.get(key) or default
    except Exception:                                   # noqa: BLE001
        return default


def _load_series(spec: PlotSpec, source, progress=None, n_ind: int = 0) -> TimeSeries:
    """把各种形态的输入统一成一条 TimeSeries。"""
    if isinstance(source, TimeSeries):
        return source
    if isinstance(source, str):
        paths = SeriesBuilder.expand([source])
    else:
        paths = SeriesBuilder.expand(list(source))
    sb = SeriesBuilder(
        paths,
        variable=spec.variable or spec.series_variable,
        region=spec.bbox,
        point=spec.series_point,
        stat=spec.series_stat or "mean",
        max_cells=int(spec.max_cells or 400_000),
        select=spec.select,
    )
    # 进度：读文件占前 80%，算指标占后 20% —— 合成一条单调的进度条
    total = max(1, len(sb.paths) + int(n_ind))
    if progress is not None:
        progress(0, total, "准备读取 %d 个文件…" % len(sb.paths))

        def _cb(i, n, name):
            progress(min(i, n), total, "读取 %d/%d：%s" % (i, n, name))
    else:
        _cb = None
    ts = sb.build(progress=_cb)
    ts.meta["builder_warnings"] = list(sb.warnings)
    return ts


def render(spec: PlotSpec, source, fig=None, ax=None,
           progress=None) -> RenderResult:
    keys = list(spec.indicators or [])
    ts = _load_series(spec, source, progress=progress, n_ind=len(keys))

    if progress is not None:
        n_files = len(getattr(source, "paths", []) or [])
        total = max(1, (ts.meta.get("n_files") or n_files) + len(keys))
        for k, key in enumerate(keys):
            progress(total - len(keys) + k, total,
                     "计算指标 %d/%d：%s" % (k + 1, len(keys),
                                             ind_mod.indicator_title(key)))
    inds = ind_mod.compute_many(keys, ts)
    if progress is not None:
        progress(total, total, "绘制…")

    # 叠加型进主面板，其余各自一块
    overlays = [r for r in inds if r.overlay and r.kind in ("line", "bars")]
    own = [r for r in inds if not (r.overlay and r.kind in ("line", "bars"))]
    panels = [r for r in own if r.kind in ("line", "bars", "spectrum")][:4]
    tables = [r for r in own if r.kind == "table"]

    if spec.kind == "spectrum":
        # 只要谱：把谱提到主面板
        spec_only = [r for r in own if r.kind == "spectrum"]
        panels = [r for r in panels if r.kind != "spectrum"]
        main_is_spectrum = bool(spec_only)
    else:
        main_is_spectrum = False

    nrows = 1 + len(panels)
    figsize = spec.figsize or style.figure_preset(spec.preset)
    if nrows > 1:
        w, h = figsize
        figsize = (w, h * min(2.6, 0.55 + 0.45 * nrows))

    if fig is None:
        fig = style.new_figure(figsize=figsize, dpi=spec.dpi)
    fig.set_facecolor(_c("bg", "#ffffff"))

    heights = [2.2] + [1.0] * len(panels)
    if nrows > 1:
        axes = fig.subplots(nrows, 1, sharex=False,
                            gridspec_kw={"height_ratios": heights,
                                         "hspace": 0.34})
    else:
        axes = np.array([fig.subplots(1, 1)])
    axes = np.atleast_1d(axes).ravel()

    main = axes[0]
    style.apply_theme(base_fontsize=spec.fontsize or 9.0)

    if main_is_spectrum:
        _draw_spectrum(main, panels.pop(0) if panels and panels[0].kind == "spectrum"
                       else own[[r.kind for r in own].index("spectrum")])
    else:
        _draw_series(main, ts, overlays, spec)

    for a, r in zip(axes[1:], panels):
        if r.kind == "spectrum":
            _draw_spectrum(a, r)
        elif r.kind == "bars":
            _draw_bars(a, r, ts)
        else:
            _draw_line(a, r, ts)
    # 主面板与下面的子面板共享时间轴刻度
    if not main_is_spectrum and len(axes) > 1:
        main.tick_params(labelbottom=False)

    # ---- 文字框：统计量与元信息 ----
    lines = []
    for r in tables:
        if r.table:
            lines.append("【%s】" % r.title)
            for k, v in r.table[:12]:
                lines.append("  %s：%s" % (k, v))
            lines.append("")
    lines += _meta_lines(ts, spec)
    lines = lines[:34]

    # 统计表放在**图下方单独留出的空白区**，而不是贴着坐标轴往下写 ——
    # 用 transAxes 的负坐标写会直接压到下一个面板上（踩过）。
    if lines:
        reserve = min(0.46, 0.055 + 0.0165 * len(lines))
    else:
        reserve = 0.06
    fig.subplots_adjust(
        left=0.105, right=0.975,
        top=0.945 if (spec.title or ts.caption()) else 0.975,
        bottom=max(0.09, reserve),
        hspace=0.30 if nrows > 1 else 0.2)
    if lines:
        fig.text(0.012, reserve - 0.02, "\n".join(lines),
                 va="top", ha="left",
                 fontsize=(spec.fontsize or 9.0) * 0.82,
                 color=_c("text_muted", "#6b7280"), linespacing=1.4,
                 bbox=dict(boxstyle="round,pad=0.45", facecolor="#f8fafc",
                           edgecolor="#e2e8f0", linewidth=0.7))

    title = spec.title or ts.caption()
    if title:
        fig.suptitle(title, fontsize=(spec.fontsize or 9.0) + 2.5,
                     color=_c("text", "#111827"), y=0.992)
    return RenderResult(fig=fig, ax=main, spec=spec, data=None,
                        mappable=None, series=ts, indicators=inds)


# ----------------------------------------------------------------------
def _draw_series(ax, ts: TimeSeries, overlays, spec: PlotSpec) -> None:
    c = style.COLORS
    x = ts.time
    y = ts.values
    show_markers = y.size <= 60
    ax.plot(x, y, color=_c("accent", "#2563eb"), linewidth=1.15,
            marker="o" if show_markers else None,
            markersize=2.6 if show_markers else 0,
            markerfacecolor="white", markeredgewidth=0.7,
            label=ts.label or ts.variable, zorder=3)
    if y.size:
        ax.axhline(float(np.mean(y)), color=_c("fg_muted", "#6b7280"), linewidth=0.7,
                   linestyle=(0, (5, 4)), zorder=1,
                   label="总平均 %.4g" % float(np.mean(y)))

    palette = [_c("bad", "#b45309"), "#b45309", "#7c3aed", "#be123c"]
    for i, r in enumerate(overlays):
        if r.kind == "bars":
            ax.bar(r.x, r.y, color=palette[i % len(palette)],
                   alpha=0.55, width=_bar_width(ts), zorder=1, label=r.label)
        else:
            ax.plot(r.x, r.y, color=palette[i % len(palette)],
                    linewidth=1.5, zorder=4, label=r.label)

    # 角标：把关键结论直接写在图里
    ann = [r.annotation for r in overlays if r.annotation]
    if ann:
        ax.text(0.015, 0.965, "\n".join(ann), transform=ax.transAxes,
                va="top", ha="left",
                fontsize=(spec.fontsize or 9.0) * 0.9,
                color=_c("fg", "#111827"),
                bbox=dict(boxstyle="round,pad=0.42", facecolor="#ffffff",
                          edgecolor="#e2e8f0", linewidth=0.7, alpha=0.94),
                zorder=8)

    ax.set_ylabel(ts.caption(), color=_c("fg", "#111827"),
                  fontsize=(spec.fontsize or 9.0))

    # ★ 明确按数据定轴范围 ★
    # 不这么做的话，「色标」面板残留的 vmin/vmax 会经 _collect_spec 传进来，
    # 把时序图纵轴拉到 -10~25 这种范围，曲线被压成一条带（踩过）。
    v = y[np.isfinite(y)]
    if v.size:
        lo, hi = float(np.min(v)), float(np.max(v))
        pad = 0.08 * (hi - lo) if hi > lo else max(1.0, abs(lo) * 0.1)
        ax.set_ylim(lo - pad, hi + pad)
    if len(x):
        ax.set_xlim(x.min(), x.max())
    ax.grid(True, color=_c("grid", "#e5e7eb"), linewidth=0.55, alpha=0.9)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=(spec.fontsize or 9.0) * 0.9,
                   colors=_c("fg_muted", "#6b7280"), length=3, width=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#d1d5db")
        ax.spines[s].set_linewidth(0.7)
    ax.margins(x=0.01)
    h, lab = ax.get_legend_handles_labels()
    if h:
        ax.legend(handles=h, labels=lab, loc="best", frameon=False,
                  fontsize=(spec.fontsize or 9.0) * 0.85, ncols=2)


def _bar_width(ts: TimeSeries) -> float:
    if ts.values.size < 2:
        return 0.6
    d = np.median(np.diff(ts.t_days()))
    return float(max(d * 0.72, 0.4)) if np.isfinite(d) else 0.6


def _draw_line(ax, r, ts: TimeSeries) -> None:
    c = style.COLORS
    ax.plot(r.x, r.y, color=_c("bad", "#b45309"), linewidth=1.2)
    ax.set_ylabel(r.ylabel or r.title, color=_c("fg", "#111827"))
    _decorate(ax, r)


def _draw_bars(ax, r, ts: TimeSeries) -> None:
    c = style.COLORS
    y = np.asarray(r.y, dtype="float64")
    colors = np.where(y >= 0, "#c2410c", "#0e7490")
    if r.x is not None and np.issubdtype(np.asarray(r.x).dtype, np.datetime64):
        ax.bar(r.x, y, color=colors, width=_bar_width(ts), align="center")
    else:
        ax.bar(np.asarray(r.x, dtype="float64"), y, color=colors, width=0.72)
    ax.axhline(0.0, color=_c("fg_muted", "#6b7280"), linewidth=0.7)
    ax.set_ylabel(r.ylabel or r.title, color=_c("fg", "#111827"))
    _decorate(ax, r)


def _draw_spectrum(ax, r) -> None:
    c = style.COLORS
    x = np.asarray(r.x, dtype="float64")
    y = np.asarray(r.y, dtype="float64")
    m = np.isfinite(x) & np.isfinite(y) & (x > 0)
    ax.semilogx(x[m], y[m], color=_c("bad", "#b45309"), linewidth=1.1)
    ax.set_xlabel(r.xlabel or "周期（天）", color=_c("fg", "#111827"))
    ax.set_ylabel(r.ylabel or "功率", color=_c("fg", "#111827"))
    if m.any():
        pk = int(np.argmax(y[m]))
        ax.plot(x[m][pk], y[m][pk], marker="v", markersize=4,
                color="#b45309", zorder=5)
    _decorate(ax, r)


def _decorate(ax, r) -> None:
    c = style.COLORS
    fs = ax.figure.get_size_inches()[1] and 9.0
    ax.grid(True, color=_c("grid", "#e5e7eb"), linewidth=0.55, alpha=0.9)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=fs * 0.88, colors=_c("fg_muted", "#6b7280"),
                   length=3, width=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#d1d5db")
        ax.spines[s].set_linewidth(0.7)
    if r.annotation:
        ax.text(0.985, 0.93, r.annotation, transform=ax.transAxes,
                va="top", ha="right", fontsize=fs * 0.86, color=_c("fg", "#111827"),
                bbox=dict(boxstyle="round,pad=0.35", facecolor="#ffffff",
                          edgecolor="#e2e8f0", linewidth=0.6, alpha=0.94))


def _meta_lines(ts: TimeSeries, spec: PlotSpec) -> List[str]:
    out = ["【数据来源】"]
    meta = ts.meta or {}
    out.append("  文件：成功 %d / 共 %d"
               % (meta.get("n_ok", 0), meta.get("n_files", 0)))
    tsrc = {"variable": "文件内 time 变量", "filename": "文件名中的日期",
            "index": "样本序号（未能识别时间）"}.get(ts.time_source, ts.time_source)
    out.append("  时间轴：%s" % tsrc)
    out.append("  统计：%s" % ts.stat)
    if ts.region:
        out.append("  区域：%.1f–%.1f°E, %.1f–%.1f°N"
                   % (ts.region[0], ts.region[1], ts.region[2], ts.region[3]))
    elif meta.get("point"):
        out.append("  单点：%.2f°E, %.2f°N" % tuple(meta["point"]))
    else:
        out.append("  区域：全球")
    for w in (meta.get("builder_warnings") or [])[:3]:
        out.append("  ⚠ %s" % w)
    return out
