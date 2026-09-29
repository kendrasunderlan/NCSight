# -*- coding: utf-8 -*-
"""
经纬度地图（核心图型）
=====================
对应 Panoply 的 `PanLonLatPlot`。

两条渲染路径：
  1. PlateCarree（等距圆柱）→ 用普通 matplotlib Axes，**最快最精确**，
     因为不需要做任何投影变换。
  2. 其他投影 → 用 cartopy GeoAxes，但**必须先降采样**。
     Cartopy 对非等距圆柱投影是逐点反算的；4320x8640 的场有 3732 万点，
     直接丢进去会极慢甚至爆内存。这是实测踩过的坑。

所以：屏幕上交互预览时用降采样数据（快），导出成品时可放宽 max_cells。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np

from ncsight import style
from ..detect import AxisRole
from ..grid import coarsen_field, subset_bbox
from ..overlay import (add_overlays, add_overlays_plain,
                       add_overlays_projected, cartopy_available)
from .base import (PlotSpec, RenderResult, apply_labels, attach_colorbar,
                   get_palette_array, make_cmap_norm, make_figure,
                   prepare_field, stats_annotation)


def _cartopy_projection(name: str, lon0: float, lat0: float, extent=None):
    """把投影名映射为 cartopy 的 CRS 对象。"""
    import cartopy.crs as ccrs

    lon0 = float(lon0 or 0.0)
    lat0 = float(lat0 or 0.0)
    table = {
        "PlateCarree": lambda: ccrs.PlateCarree(central_longitude=lon0),
        "Robinson": lambda: ccrs.Robinson(central_longitude=lon0),
        "Mollweide": lambda: ccrs.Mollweide(central_longitude=lon0),
        "EqualEarth": lambda: ccrs.EqualEarth(central_longitude=lon0),
        "Orthographic": lambda: ccrs.Orthographic(central_longitude=lon0,
                                                  central_latitude=lat0 or 30.0),
        "NorthPolarStereo": lambda: ccrs.NorthPolarStereo(central_longitude=lon0),
        "SouthPolarStereo": lambda: ccrs.SouthPolarStereo(central_longitude=lon0),
        "Mercator": lambda: ccrs.Mercator(central_longitude=lon0),
        "LambertConformal": lambda: ccrs.LambertConformal(central_longitude=lon0,
                                                          central_latitude=lat0 or 45.0,
                                                          standard_parallels=(30.0, 60.0)),
        "AlbersEqualArea": lambda: ccrs.AlbersEqualArea(central_longitude=lon0,
                                                        central_latitude=lat0 or 45.0,
                                                        standard_parallels=(29.5, 45.5)),
        "RotatedPole": lambda: ccrs.RotatedPole(pole_longitude=lon0,
                                                pole_latitude=lat0 or 39.25),
        "TransverseMercator": lambda: ccrs.TransverseMercator(central_longitude=lon0,
                                                              central_latitude=lat0),
        "UTM": lambda: ccrs.UTM(zone=int(abs(lon0) // 6) + 1 or 33),
    }
    factory = table.get(name)
    return factory() if factory else ccrs.PlateCarree()


def _is_regular(fd) -> bool:
    return (fd.x is not None and fd.y is not None
            and np.ndim(fd.x) == 1 and np.ndim(fd.y) == 1)


def _apply_data_masks(fd, spec: PlotSpec, source=None):
    """按 PlotSpec 上的掩膜配置过滤数据（陆地/多边形/阈值/质量标记）。"""
    need = (spec.mask_land or spec.mask_polygon or spec.mask_shapefile
            or spec.mask_range or spec.quality_var)
    if not need:
        return fd
    from .. import mask as _mask
    if spec.quality_var and source is not None:
        try:
            fd = _mask.quality_mask(fd, spec.quality_var, spec.quality_accept)
        except Exception:                               # noqa: BLE001
            pass
    if spec.mask_land:
        try:
            fd = _mask.land_mask(fd, spec.overlays.resolution)
        except Exception:                               # noqa: BLE001
            pass
    if spec.mask_polygon:
        try:
            fd = _mask.polygon_mask(fd, spec.mask_polygon)
        except Exception:                               # noqa: BLE001
            pass
    if spec.mask_shapefile:
        try:
            fd = _mask.shapefile_mask(fd, spec.mask_shapefile)
        except Exception:                               # noqa: BLE001
            pass
    if spec.mask_range:
        lo = spec.mask_range[0] if len(spec.mask_range) > 0 else None
        hi = spec.mask_range[1] if len(spec.mask_range) > 1 else None
        try:
            fd = _mask.threshold_mask(fd, lo, hi)
        except Exception:                               # noqa: BLE001
            pass
    return fd


def render(spec: PlotSpec, source, fig=None, ax=None) -> RenderResult:
    fd = source.read_field(spec.variable, spec.select)
    fd = subset_bbox(fd, spec.bbox)
    fd = _apply_data_masks(fd, spec, source)

    # 数据可能不在经纬网格上（比如 (time, lat) 被当成 map）— 兜底退回折线
    if not (_is_regular(fd) or fd.values.ndim == 2):
        from . import line_plot
        return line_plot.render(spec, source, fig=fig, ax=ax)

    # ★ 顺序很重要：先在**降采样之前**算出色标范围，
    #   这样屏幕上看的和导出的是同一个范围，不会因为降采样而轻微漂移。
    palette = get_palette_array(source)
    cmap, norm, (vmin, vmax) = make_cmap_norm(fd, spec, palette)

    # 屏幕降采样：GUI 会把 screen_cells 设成画布像素数；
    # 命令行/导出保持 0 即全分辨率。实测 3732 万格点 13.4 秒 → 58 万格点 0.25 秒。
    fd = prepare_field(fd, spec)

    geo = fd.x_role is AxisRole.LON or fd.y_role is AxisRole.LAT
    projection = spec.projection or "PlateCarree"
    use_cartopy = (projection != "PlateCarree") and cartopy_available()

    if use_cartopy:
        result = _render_projected(spec, source, fd, cmap, norm, vmin, vmax,
                                   projection, fig)
    else:
        result = _render_plain(spec, source, fd, cmap, norm, vmin, vmax,
                               geo, fig, ax)
    return result


# --------------------------------------------------------------------------
# 路径 1：等距圆柱 —— 普通 Axes，最快
# --------------------------------------------------------------------------
def _render_plain(spec, source, fd, cmap, norm, vmin, vmax, geo, fig, ax):
    if fig is None:
        fig = make_figure(spec)
    if ax is None:
        ax = fig.add_subplot(111)

    mesh = ax.pcolormesh(fd.x, fd.y, np.ma.masked_invalid(fd.values),
                         cmap=cmap, norm=norm, shading="auto",
                         rasterized=True, zorder=3)
    if not geo:
        ax.set_aspect("auto")

    if spec.show_contours:
        try:
            levels = np.linspace(vmin, vmax, max(3, spec.contour_levels))
            cs = ax.contour(fd.x, fd.y, np.ma.masked_invalid(fd.values),
                            levels=levels, colors="#5b6472",
                            linewidths=0.5, alpha=0.75, zorder=5)
            if spec.contour_labels:
                ax.clabel(cs, inline=True, fontsize=max(6.0, spec.fontsize - 2.5),
                          fmt="%.4g")
        except Exception:                               # noqa: BLE001
            pass

    add_overlays_plain(ax, spec.overlays)

    if spec.show_grid and geo:
        ax.grid(True, color=style.COLORS["grid"], linewidth=0.5, alpha=0.9, zorder=1)

    xlabel = spec.xlabel or ("经度" if fd.x_role is AxisRole.LON else fd.x_name.title())
    ylabel = spec.ylabel or ("纬度" if fd.y_role is AxisRole.LAT else fd.y_name.title())
    apply_labels(ax, spec, fd, xlabel, ylabel)
    style.tidy_axes(ax, grid=False, box=True)

    if geo:
        ax.set_xlim(float(np.nanmin(fd.x)), float(np.nanmax(fd.x)))
        ax.set_ylim(float(np.nanmin(fd.y)), float(np.nanmax(fd.y)))

    if spec.show_stats:
        ax.text(0.012, 0.985, stats_annotation(fd), transform=ax.transAxes,
                ha="left", va="top", fontsize=max(6.0, spec.fontsize - 2),
                color=style.COLORS["fg"], linespacing=1.35,
                bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=style.COLORS["spine"],
                          lw=0.5, alpha=0.88), zorder=20)

    attach_colorbar(fig, ax, mesh, spec, fd.caption)
    return RenderResult(fig=fig, ax=ax, spec=spec, data=fd, mappable=mesh)


# --------------------------------------------------------------------------
# 路径 2：投影地图 —— cartopy，必须降采样
# --------------------------------------------------------------------------
def _render_projected(spec, source, fd, cmap, norm, vmin, vmax, projection, fig):
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature

    fd = coarsen_field(fd, max_cells=spec.max_cells)
    if fig is None:
        fig = style.new_figure(figsize=tuple(spec.figsize) if spec.figsize
                               else style.figure_preset(spec.preset),
                               dpi=spec.dpi)

    extent = None
    if spec.bbox:
        extent = [spec.bbox[0], spec.bbox[1], spec.bbox[2], spec.bbox[3]]
    elif fd.x_role is AxisRole.LON and fd.y_role is AxisRole.LAT:
        extent = [float(np.nanmin(fd.x)), float(np.nanmax(fd.x)),
                  float(np.nanmin(fd.y)), float(np.nanmax(fd.y))]

    crs = _cartopy_projection(projection, spec.lon0, spec.lat0, extent)
    ax = fig.add_subplot(111, projection=crs)

    src_crs = ccrs.PlateCarree()
    mesh = ax.pcolormesh(fd.x, fd.y, np.ma.masked_invalid(fd.values),
                         transform=src_crs, cmap=cmap, norm=norm,
                         shading="auto", rasterized=True, zorder=3)

    if extent and projection in ("TransverseMercator", "UTM", "RotatedPole",
                                 "LambertConformal", "AlbersEqualArea"):
        try:
            ax.set_extent(extent, crs=src_crs)
        except Exception:                               # noqa: BLE001
            pass
    elif projection in ("NorthPolarStereo", "SouthPolarStereo"):
        try:
            ax.set_extent([-180, 180, 45, 90] if "North" in projection
                          else [-180, 180, -90, -45], crs=src_crs)
        except Exception:                               # noqa: BLE001
            pass

    if spec.overlays.land or spec.overlays.ocean:
        try:
            if spec.overlays.ocean:
                ax.add_feature(cfeature.OCEAN.with_scale(spec.overlays.resolution),
                               facecolor=style.COLORS["ocean"], edgecolor="none", zorder=1)
            if spec.overlays.land:
                ax.add_feature(cfeature.LAND.with_scale(spec.overlays.resolution),
                               facecolor=style.COLORS["land"], edgecolor="none", zorder=1)
        except Exception:                               # noqa: BLE001
            pass

    # 用预读好的折线集合叠加底图，而不是 ax.coastlines()/add_feature ——
    # 后者的 FeatureArtist 会在每次绘制时重新投影几何体，占掉近一秒主线程卡顿。
    add_overlays_projected(ax, spec.overlays, src_crs)

    if spec.show_grid:
        try:
            gl = ax.gridlines(draw_labels=spec.grid_labels, linewidth=0.4,
                              color=style.COLORS["grid"], alpha=0.85,
                              xlocs=None, ylocs=None)
            if spec.grid_labels:
                gl.top_labels = False
                gl.right_labels = False
                gl.xlabel_style = {"size": max(6.0, spec.fontsize - 2),
                                   "color": style.COLORS["fg_muted"]}
                gl.ylabel_style = {"size": max(6.0, spec.fontsize - 2),
                                   "color": style.COLORS["fg_muted"]}
        except Exception:                               # noqa: BLE001
            pass

    ax.set_title(spec.title or fd.caption, loc="left")
    if spec.subtitle:
        ax.text(0.5, 1.01, spec.subtitle, transform=ax.transAxes,
                ha="center", va="bottom", fontsize=max(6.5, spec.fontsize - 1.5),
                color=style.COLORS["fg_muted"])

    # ★ 必须显式持有数据网格的引用 ★
    # 之前这里写的是 `mappable = ax.collections[-1]`，靠「最后一个 collection 就是
    # 数据」这个假设 —— 一旦底图叠加也用 add_collection 画（比如海岸线集合），
    # 最后一个 collection 就变成海岸线了，色标会按海岸线的 0~1 归一化上色，
    # 表现为「色标范围变成 0.0–1.0」这种极隐蔽的错误。
    attach_colorbar(fig, ax, mesh, spec, fd.caption)
    return RenderResult(fig=fig, ax=ax, spec=spec, data=fd, mappable=mesh)


# --------------------------------------------------------------------------
# 矢量场叠加（供 map / vector 共用）
# --------------------------------------------------------------------------
def overlay_vectors(ax, source, spec: PlotSpec, u_fd, v_fd,
                    transform=None) -> Any:
    """在已有轴上叠加风/流矢量。"""
    ny, nx = u_fd.values.shape
    step = max(1, int(spec.vector_step))
    u = u_fd.values[::step, ::step]
    v = v_fd.values[::step, ::step]
    scale = spec.vector_units_scale or 1.0
    u = u * scale
    v = v * scale

    X, Y = np.meshgrid(u_fd.x, u_fd.y)
    X, Y = X[::step, ::step], Y[::step, ::step]
    # 曲线网格时坐标本身就是二维的，不能再抽样网格
    if u_fd.x.ndim == 2:
        X, Y = u_fd.x[::step, ::step], u_fd.y[::step, ::step]

    kw = dict(color=spec.vector_color, linewidth=spec.vector_width,
              zorder=8, pivot="tail")
    if transform is not None:
        kw["transform"] = transform
    if spec.vector_scale:
        kw["scale"] = spec.vector_scale
    else:
        kw["scale_units"] = "xy"
        kw["scale"] = None
    q = ax.quiver(X, Y, u, v, **kw)
    return q
