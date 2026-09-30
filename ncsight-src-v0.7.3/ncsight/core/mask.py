# -*- coding: utf-8 -*-
"""
掩膜（Masking / 区域裁剪）
=========================
Panoply 只会画全图，掩膜得靠外部工具。这里是它的一个明显短板，
所以我们做得直接一点：

  * land_mask / ocean_mask   —— 只保留陆地 / 只保留海洋
  * polygon_mask            —— 任意多边形（研究区、断面、EEZ…）
  * shapefile_mask          —— 直接读 .shp 当掩膜
  * quality_mask            —— 用质量标记变量过滤低质量像元
  * threshold_mask          —— 按数值范围过滤（如只保留 > 0 的值）

实现说明：使用 matplotlib.path.Path.contains_points，纯 C 实现，比
逐点多边形判断快得多。但 4320x8640 = 3732 万点仍然需要几秒到几十秒，
建议先 bbox 裁剪再打掩膜（grid.subset_bbox）。
"""

from __future__ import annotations

import os
from typing import List, Optional, Sequence, Tuple

import numpy as np

from .reader import NcSource, FieldData


def _wrap(fd: FieldData, values: np.ndarray, note: str = "") -> FieldData:
    return FieldData(
        name=fd.name, values=values, x=fd.x, y=fd.y,
        x_name=fd.x_name, y_name=fd.y_name,
        x_role=fd.x_role, y_role=fd.y_role,
        long_name=(fd.long_name + (("（%s）" % note) if note else "")),
        units=fd.units, dims=fd.dims,
        select=dict(fd.select), attrs=dict(fd.attrs),
    )


def _grid_points(fd: FieldData) -> np.ndarray:
    """把 x/y 展平成 (N, 2) 的点集，供 contains_points 使用。"""
    x, y = fd.x, fd.y
    if np.ndim(x) == 2:
        X, Y = np.asarray(x), np.asarray(y)
    else:
        X, Y = np.meshgrid(np.asarray(x), np.asarray(y))
    return np.column_stack([X.ravel(), Y.ravel()])


def _apply(fd: FieldData, keep: np.ndarray, note: str) -> FieldData:
    mask = np.asarray(keep, dtype=bool).reshape(fd.values.shape)
    return _wrap(fd, np.where(mask, fd.values, np.nan), note)


# --------------------------------------------------------------------------
# 陆 / 海
# --------------------------------------------------------------------------
def _land_geometries(resolution: str = "110m"):
    try:
        from cartopy.io import shapereader
        from .overlay import read_shapefile_parts
        shp = shapereader.natural_earth(resolution=resolution,
                                        category="physical", name="land")
        # 用 pyshp 读坐标，避免在工作线程里创建 pyproj CRS（会段错误闪退）
        return read_shapefile_parts(shp)
    except Exception:                                   # noqa: BLE001
        return []


def _paths_from_geometries(geoms) -> List:
    """
    把几何体转成 matplotlib Path 列表。

    现在 geoms 通常是 **坐标数组列表**（由 pyshp 读出，见
    overlay.read_shapefile_parts）；也兼容 shapely 几何体对象，
    以防别处还传旧的进来。
    """
    from matplotlib.path import Path
    paths = []
    for g in geoms:
        if isinstance(g, np.ndarray):
            if g.ndim == 2 and g.shape[0] >= 3:
                paths.append(Path(g))
            continue
        parts = g.geoms if hasattr(g, "geoms") else [g]
        for p in parts:
            try:
                xs, ys = p.exterior.xy if hasattr(p, "exterior") else p.xy
            except Exception:                           # noqa: BLE001
                continue
            if len(xs) < 3:
                continue
            paths.append(Path(np.column_stack([xs, ys])))
    return paths


def land_mask(fd: FieldData, resolution: str = "110m",
              invert: bool = False) -> FieldData:
    """
    陆海掩膜。invert=False 时返回**只保留海洋**（日常最常用，把陆地抹掉）；
    invert=True 时返回只保留陆地。
    """
    geoms = _land_geometries(resolution)
    if not geoms:
        return fd
    paths = _paths_from_geometries(geoms)
    if not paths:
        return fd
    pts = _grid_points(fd)
    onland = np.zeros(pts.shape[0], dtype=bool)
    for p in paths:
        bb = p.get_extents()
        sel = ((pts[:, 0] >= bb.xmin - 1e-9) & (pts[:, 0] <= bb.xmax + 1e-9) &
               (pts[:, 1] >= bb.ymin - 1e-9) & (pts[:, 1] <= bb.ymax + 1e-9))
        if not sel.any():
            continue
        onland[sel] |= p.contains_points(pts[sel])
    keep = onland if invert else ~onland
    return _apply(fd, keep, "陆地" if invert else "海洋")


def ocean_mask(fd: FieldData, resolution: str = "110m") -> FieldData:
    return land_mask(fd, resolution, invert=False)


# --------------------------------------------------------------------------
# 多边形 / Shapefile
# --------------------------------------------------------------------------
def polygon_mask(fd: FieldData, polygon: Sequence[Sequence[float]],
                 invert: bool = False) -> FieldData:
    """polygon 为 [(lon, lat), ...] 的闭合或不闭合列表。"""
    from matplotlib.path import Path
    pts_poly = np.asarray(polygon, dtype="float64")
    if pts_poly.ndim != 2 or pts_poly.shape[0] < 3:
        return fd
    if not np.allclose(pts_poly[0], pts_poly[-1]):
        pts_poly = np.vstack([pts_poly, pts_poly[0]])
    keep = Path(pts_poly).contains_points(_grid_points(fd))
    if invert:
        keep = ~keep
    return _apply(fd, keep, "多边形掩膜" + ("（反选）" if invert else ""))


def shapefile_mask(fd: FieldData, shp_path: str,
                   invert: bool = False) -> FieldData:
    """用 .shp 里的所有多边形作为掩膜区域。"""
    if not os.path.exists(shp_path):
        return fd
    try:
        from .overlay import shapefile_paths
        paths = shapefile_paths(shp_path)
    except Exception:                                   # noqa: BLE001
        return fd
    if not paths:
        return fd
    pts = _grid_points(fd)
    inside = np.zeros(pts.shape[0], dtype=bool)
    for p in paths:
        bb = p.get_extents()
        sel = ((pts[:, 0] >= bb.xmin - 1e-9) & (pts[:, 0] <= bb.xmax + 1e-9) &
               (pts[:, 1] >= bb.ymin - 1e-9) & (pts[:, 1] <= bb.ymax + 1e-9))
        if not sel.any():
            continue
        inside[sel] |= p.contains_points(pts[sel])
    return _apply(fd, ~inside if invert else inside,
                  "形状文件掩膜" + ("（反选）" if invert else ""))


# --------------------------------------------------------------------------
# 数值 / 质量
# --------------------------------------------------------------------------
def threshold_mask(fd: FieldData, vmin: Optional[float] = None,
                   vmax: Optional[float] = None,
                   outside: bool = False) -> FieldData:
    """按数值范围过滤。默认保留 [vmin, vmax] 内的点。"""
    v = fd.values
    keep = np.isfinite(v)
    if vmin is not None:
        keep &= (v >= vmin)
    if vmax is not None:
        keep &= (v <= vmax)
    if outside:
        keep = np.isfinite(v) & ~keep
    return _apply(fd, keep, "阈值掩膜")


def quality_mask(fd: FieldData, quality_var: str = "qual_sst",
                 accept: str = "0:2") -> FieldData:
    """
    用数据集里的质量标记变量过滤低质量像元。
    accept 形如 "0:2"（保留 0~2 级）或 "0,1,2"。
    """
    src = getattr(fd, "_source", None)
    if src is None:
        return fd
    if quality_var not in src.ds.variables:
        return fd
    qfd = src.read_field(quality_var, fd.select)
    q = qfd.values
    if np.asarray(q).shape != fd.values.shape:
        return fd

    keep = np.isfinite(np.asarray(q, dtype="float64"))
    levels = set()
    text = str(accept).strip()
    try:
        if ":" in text:
            a, b = text.split(":", 1)
            lo, hi = int(float(a)), int(float(b))
            levels = set(range(min(lo, hi), max(lo, hi) + 1))
        else:
            levels = {int(float(t)) for t in text.replace(";", ",").split(",") if t.strip()}
    except ValueError:
        return fd
    if not levels:
        return fd
    keep &= np.isin(np.asarray(q), sorted(levels))
    return _apply(fd, keep, "质量掩膜(%s ∈ %s)" % (quality_var, sorted(levels)))


def apply_masks(fd: FieldData, spec) -> FieldData:
    """按 PlotSpec 上的掩膜配置一次性应用（供绘图流程调用）。"""
    out = fd
    res = getattr(spec.overlays, "resolution", "110m")
    if getattr(spec, "mask_land", False):
        out = land_mask(out, res)
    if getattr(spec, "mask_polygon", None):
        out = polygon_mask(out, spec.mask_polygon)
    if getattr(spec, "mask_shapefile", None):
        out = shapefile_mask(out, spec.mask_shapefile)
    if getattr(spec, "mask_range", None):
        r = spec.mask_range
        out = threshold_mask(out, r[0] if len(r) > 0 else None,
                             r[1] if len(r) > 1 else None)
    return out
