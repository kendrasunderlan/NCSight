# -*- coding: utf-8 -*-
"""
矢量场（风场 / 流场）
====================
对应 Panoply 的 `PanVectorControls` + `PanLLPlotMapInsert`。

用法：spec.variable 指定 u 分量，spec.vector_variable 指定 v 分量
（留空时自动用 detect 找到的配对变量）。
背景色可选：不填则只画箭头；填一个标量变量则叠加其填色作为背景。
"""

from __future__ import annotations

import numpy as np

from ncsight import style
from ..detect import AxisRole
from ..overlay import add_overlays, add_overlays_plain, cartopy_available
from .base import (PlotSpec, RenderResult, apply_labels, attach_colorbar,
                   get_palette_array, make_cmap_norm, make_figure)


def _find_pair(source, spec: PlotSpec):
    vi = source.variables.get(spec.variable)
    if vi is None:
        raise ValueError("变量不存在：%s" % spec.variable)
    partner = spec.vector_variable or vi.vector_partner
    if not partner:
        raise ValueError(
            "变量 %s 没有找到配对的矢量分量。请在 spec.vector_variable 里显式指定。"
            % spec.variable)
    return vi, partner


def render(spec: PlotSpec, source, fig=None, ax=None) -> RenderResult:
    u_vi, v_name = _find_pair(source, spec)
    u_fd = source.read_field(spec.variable, spec.select)
    v_fd = source.read_field(v_name, spec.select)

    if spec.bbox:
        from ..grid import subset_bbox
        u_fd = subset_bbox(u_fd, spec.bbox)
        v_fd = subset_bbox(v_fd, spec.bbox)
    if u_fd.values.shape != v_fd.values.shape:
        raise ValueError("u/v 分量形状不一致：%s vs %s"
                         % (u_fd.values.shape, v_fd.values.shape))

    # 背景标量场（可选）：spec.vector_variable 之外，若 spec.cmap 指定了
    # 一个已存在的变量名，就把它作为填色背景（当前版本暂不启用，留接口）
    bg_fd = None

    use_cartopy = (spec.projection != "PlateCarree") and cartopy_available()
    geo = u_fd.x_role is AxisRole.LON and u_fd.y_role is AxisRole.LAT

    if geo and use_cartopy:
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
        fd_c = u_fd
        v_c = v_fd
        from ..grid import coarsen_field
        fd_c = coarsen_field(u_fd, max_cells=spec.max_cells)
        v_c = coarsen_field(v_fd, max_cells=spec.max_cells)
        if fig is None:
            fig = style.new_figure(
                figsize=tuple(spec.figsize) if spec.figsize
                else style.figure_preset(spec.preset), dpi=spec.dpi)
        from .map_plot import _cartopy_projection
        crs = _cartopy_projection(spec.projection, spec.lon0, spec.lat0)
        ax = fig.add_subplot(111, projection=crs)
        if spec.overlays.land or spec.overlays.ocean:
            try:
                if spec.overlays.ocean:
                    ax.add_feature(cfeature.OCEAN.with_scale(spec.overlays.resolution),
                                   facecolor=style.COLORS["ocean"], edgecolor="none",
                                   zorder=1)
                if spec.overlays.land:
                    ax.add_feature(cfeature.LAND.with_scale(spec.overlays.resolution),
                                   facecolor=style.COLORS["land"], edgecolor="none",
                                   zorder=1)
            except Exception:                           # noqa: BLE001
                pass
        add_overlays(ax, spec.overlays)
        _quiver(ax, fd_c, v_c, spec, transform=ccrs.PlateCarree())
        if spec.show_grid:
            try:
                gl = ax.gridlines(draw_labels=True, linewidth=0.4,
                                  color=style.COLORS["grid"], alpha=0.85)
                gl.top_labels = gl.right_labels = False
            except Exception:                           # noqa: BLE001
                pass
        # 同理：显式持有矢量层，不要用 collections[-1] 猜
        mappable = _quiver(ax, fd_c, v_c, spec, transform=ccrs.PlateCarree())
    else:
        if fig is None:
            fig = make_figure(spec)
        if ax is None:
            ax = fig.add_subplot(111)
        add_overlays_plain(ax, spec.overlays)
        _quiver(ax, u_fd, v_fd, spec)
        if spec.show_grid:
            ax.grid(True, color=style.COLORS["grid"], linewidth=0.5, alpha=0.9, zorder=1)
        if geo:
            ax.set_xlim(float(np.nanmin(u_fd.x)), float(np.nanmax(u_fd.x)))
            ax.set_ylim(float(np.nanmin(u_fd.y)), float(np.nanmax(u_fd.y)))
        mappable = None

    # 用 u 场作为 RenderResult.data（供统计/导出用）
    xlabel = spec.xlabel or ("经度" if u_fd.x_role is AxisRole.LON else u_fd.x_name)
    ylabel = spec.ylabel or ("纬度" if u_fd.y_role is AxisRole.LAT else u_fd.y_name)
    apply_labels(ax, spec, None, xlabel, ylabel)
    style.tidy_axes(ax, grid=False, box=not use_cartopy)
    title = spec.title or ("矢量场：%s / %s" % (spec.variable, v_name))
    ax.set_title(title, loc="left")

    return RenderResult(fig=fig, ax=ax, spec=spec, data=u_fd, mappable=mappable)


def _quiver(ax, u_fd, v_fd, spec: PlotSpec, transform=None):
    step = max(1, int(spec.vector_step))
    u = np.asarray(u_fd.values)[::step, ::step] * (spec.vector_units_scale or 1.0)
    v = np.asarray(v_fd.values)[::step, ::step] * (spec.vector_units_scale or 1.0)

    if np.ndim(u_fd.x) == 2:
        X = np.asarray(u_fd.x)[::step, ::step]
        Y = np.asarray(u_fd.y)[::step, ::step]
    else:
        X, Y = np.meshgrid(np.asarray(u_fd.x), np.asarray(u_fd.y))
        X, Y = X[::step, ::step], Y[::step, ::step]

    kw = dict(color=spec.vector_color, linewidth=spec.vector_width,
              pivot="tail", zorder=8)
    if transform is not None:
        kw["transform"] = transform
    if spec.vector_scale:
        kw["scale"] = spec.vector_scale
    else:
        kw["scale_units"] = "xy"
    return ax.quiver(X, Y, u, v, **kw)
