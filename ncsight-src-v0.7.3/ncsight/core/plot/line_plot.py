# -*- coding: utf-8 -*-
"""
折线 / 时间序列 / 纬向平均廓线
==============================
对应 Panoply 的 `PanXTimePlot` / `PanHorizontalLinePlot` /
`PanZonalAverageLinePlot`。
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from ncsight import style
from ..detect import AxisRole
from .base import (PlotSpec, RenderResult, apply_labels, make_figure,
                   stats_annotation)


def _role_label(role: AxisRole, name: str) -> str:
    return {
        AxisRole.LON: "经度", AxisRole.LAT: "纬度",
        AxisRole.TIME: "时间", AxisRole.VERT: name or "垂向",
    }.get(role, name or "")


def render(spec: PlotSpec, source, fig=None, ax=None) -> RenderResult:
    fd = source.read_field(spec.variable, spec.select)
    vi = source.variables[spec.variable]

    if fig is None:
        fig = make_figure(spec)
    if ax is None:
        ax = fig.add_subplot(111)

    vals = np.asarray(fd.values)

    # ---- 决定横纵轴数据 ----
    if vi.ndim == 1 and fd.y_role is AxisRole.VERT:
        # 垂向廓线：数值在横轴，深度在纵轴
        xs = vals.ravel()
        ys = np.asarray(fd.y).ravel()
        xlabel = _role_label(AxisRole.OTHER, fd.name)
        ylabel = _role_label(AxisRole.VERT, fd.y_name or fd.y_name)
        xlabel = fd.caption
    elif vi.ndim == 1:
        xs = np.asarray(fd.x).ravel()
        ys = vals.ravel()
        xlabel = _role_label(fd.x_role, fd.x_name)
        ylabel = fd.caption
    else:
        # 二维变量：沿一维取平均后画廓线
        return render_zonal(spec, source, fig=fig, ax=ax)

    mask = np.isfinite(xs) & np.isfinite(ys)
    ax.plot(xs[mask], ys[mask],
            color=spec.line_color or style.COLORS["accent"],
            linewidth=spec.line_width,
            marker="o" if spec.marker else None,
            markersize=3.2, markerfacecolor="white",
            markeredgewidth=0.8, zorder=5)

    if spec.xlog and np.all(xs[mask] > 0):
        ax.set_xscale("log")
    if spec.ylog and np.all(ys[mask] > 0):
        ax.set_yscale("log")
    if spec.invert_y:
        ax.invert_yaxis()

    apply_labels(ax, spec, fd, spec.xlabel or xlabel, spec.ylabel or ylabel)
    style.tidy_axes(ax, grid=True, box=False)

    if spec.show_stats:
        ax.text(0.985, 0.97, stats_annotation(fd), transform=ax.transAxes,
                ha="right", va="top", fontsize=max(6.0, spec.fontsize - 2),
                linespacing=1.35, color=style.COLORS["fg"],
                bbox=dict(boxstyle="round,pad=0.35", fc="white",
                          ec=style.COLORS["spine"], lw=0.5, alpha=0.9))

    return RenderResult(fig=fig, ax=ax, spec=spec, data=fd, mappable=None)


def render_zonal(spec: PlotSpec, source, fig=None, ax=None) -> RenderResult:
    """
    纬向平均 / 经向平均廓线。

    对 (lat, lon) 场：沿经度平均 → 得到随纬度变化的廓线（最常用）。
    spec.select 里可用 "average_axis" 指定沿哪根轴平均（默认自动挑经纬度中最长的那根）。
    """
    fd = source.read_field(spec.variable, spec.select)
    if spec.bbox:
        from ..grid import subset_bbox
        fd = subset_bbox(fd, spec.bbox)

    vals = np.asarray(fd.values, dtype="float64")
    if vals.ndim != 2:
        return render(spec, source, fig=fig, ax=ax)

    avg_axis = spec.select.get("average_axis")
    if avg_axis not in ("x", "y"):
        # 自动：如果 y 轴是纬度（廓线随纬度变化），则沿 x 平均
        avg_axis = "x" if fd.y_role is AxisRole.LAT else "y"

    with np.errstate(invalid="ignore"):
        if avg_axis == "x":
            prof = np.nanmean(vals, axis=1)
            coord = np.asarray(fd.y).ravel()
            c_role, c_name = fd.y_role, fd.y_name
            avg_name = fd.x_name
        else:
            prof = np.nanmean(vals, axis=0)
            coord = np.asarray(fd.x).ravel()
            c_role, c_name = fd.x_role, fd.x_name
            avg_name = fd.y_name

    if fig is None:
        fig = make_figure(spec)
    if ax is None:
        ax = fig.add_subplot(111)

    mask = np.isfinite(prof) & np.isfinite(coord)
    ax.plot(coord[mask], prof[mask],
            color=spec.line_color or style.COLORS["accent"],
            linewidth=spec.line_width,
            marker="o" if spec.marker else None, markersize=3.0,
            markerfacecolor="white", markeredgewidth=0.8, zorder=5)
    ax.axhline(0, color=style.COLORS["spine"], linewidth=0.6, zorder=1)

    xlabel = spec.xlabel or _role_label(c_role, c_name)
    ylabel = spec.ylabel or "%s（沿 %s 平均）" % (fd.caption, avg_name)
    if spec.invert_y:
        ax.invert_yaxis()
    apply_labels(ax, spec, None, xlabel, ylabel)
    style.tidy_axes(ax, grid=True, box=False)

    return RenderResult(fig=fig, ax=ax, spec=spec, data=fd, mappable=None)
