# -*- coding: utf-8 -*-
"""
Hovmöller 图（时间-经度 / 时间-纬度）
====================================
对应 Panoply 的 `PanLonTimePlot` / `PanLatTimePlot`。
研究季节内振荡、赤道波、风暴路径必备。
"""

from __future__ import annotations

import numpy as np

from ncsight import style
from ..detect import AxisRole
from .base import (PlotSpec, RenderResult, apply_labels, attach_colorbar,
                   get_palette_array, make_cmap_norm, make_figure, prepare_field,
                   stats_annotation)


def render(spec: PlotSpec, source, fig=None, ax=None) -> RenderResult:
    fd = source.read_field(spec.variable, spec.select)
    vi = source.variables[spec.variable]
    fd = _orient(fd, source, spec)

    palette = get_palette_array(source)
    cmap, norm, (vmin, vmax) = make_cmap_norm(fd, spec, palette)
    fd = prepare_field(fd, spec)   # 屏幕降采样（范围已算完，不受影响）

    if fig is None:
        fig = make_figure(spec)
    if ax is None:
        ax = fig.add_subplot(111)

    mesh = ax.pcolormesh(fd.x, fd.y, np.ma.masked_invalid(fd.values),
                         cmap=cmap, norm=norm, shading="auto",
                         rasterized=True, zorder=3)

    if spec.show_contours:
        try:
            levels = np.linspace(vmin, vmax, max(3, spec.contour_levels))
            cs = ax.contour(fd.x, fd.y, np.ma.masked_invalid(fd.values),
                            levels=levels, colors="#5b6472",
                            linewidths=0.45, alpha=0.7, zorder=5)
            if spec.contour_labels:
                ax.clabel(cs, inline=True, fontsize=max(6.0, spec.fontsize - 2.5),
                          fmt="%.4g")
        except Exception:                               # noqa: BLE001
            pass

    if spec.show_grid:
        ax.grid(True, color=style.COLORS["grid"], linewidth=0.5, alpha=0.9, zorder=1)

    xlabel = spec.xlabel or _label(fd.x_role, fd.x_name)
    ylabel = spec.ylabel or _label(fd.y_role, fd.y_name)
    apply_labels(ax, spec, fd, xlabel, ylabel)
    style.tidy_axes(ax, grid=False, box=True)

    if spec.show_stats:
        ax.text(0.012, 0.985, stats_annotation(fd), transform=ax.transAxes,
                ha="left", va="top", fontsize=max(6.0, spec.fontsize - 2),
                linespacing=1.35, color=style.COLORS["fg"],
                bbox=dict(boxstyle="round,pad=0.35", fc="white",
                          ec=style.COLORS["spine"], lw=0.5, alpha=0.9), zorder=20)

    attach_colorbar(fig, ax, mesh, spec, fd.caption)
    return RenderResult(fig=fig, ax=ax, spec=spec, data=fd, mappable=mesh)


def _label(role: AxisRole, name: str) -> str:
    return {AxisRole.TIME: "时间", AxisRole.LON: "经度", AxisRole.LAT: "纬度"}.get(role, name)


def _orient(fd, source, spec):
    """确保时间在纵轴（更接近 Hovmöller 的传统画法）。"""
    if fd.y_role is AxisRole.TIME:
        return fd
    if fd.x_role is AxisRole.TIME:
        from ..reader import FieldData
        vals = fd.values.T
        return FieldData(
            name=fd.name, values=vals, x=fd.y, y=fd.x,
            x_name=fd.y_name, y_name=fd.x_name,
            x_role=fd.y_role, y_role=fd.x_role,
            long_name=fd.long_name, units=fd.units,
            dims=tuple(reversed(fd.dims)), select=dict(fd.select),
            attrs=dict(fd.attrs),
        )
    return fd
