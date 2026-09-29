# -*- coding: utf-8 -*-
"""
底图叠加（海岸线 / 国界 / 自定义 Shapefile）
==========================================
对应 Panoply 的 `gov.nasa.giss.map.overlay`（MWDB-II 海岸线）与 `.map.shapefile`。

Panoply 内置 MWDB-II 数据；我们用 Natural Earth（更新、更准），
由 cartopy 提供。底图数据首次使用需要联网下载，之后会缓存在
`~/.local/share/cartopy/`，可整体打包进软件实现离线运行。

本模块对「没装 cartopy」「底图缺失且无网络」都做了降级，不会让绘图崩掉。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

#: Natural Earth 图层名 → 中文说明
FEATURE_CATALOG: List[Tuple[str, str]] = [
    ("coastline", "海岸线"),
    ("land", "陆地"),
    ("ocean", "海洋"),
    ("borders", "国界"),
    ("lakes", "湖泊"),
    ("rivers", "河流"),
    ("states", "美国州界"),
]

RESOLUTIONS = [("110m", "低精度 · 快"), ("50m", "中精度"), ("10m", "高精度 · 慢")]


@dataclass
class OverlaySpec:
    coastline: bool = True
    borders: bool = False
    lakes: bool = False
    rivers: bool = False
    land: bool = False
    ocean: bool = False
    resolution: str = "110m"
    line_color: str = "#3f3f46"
    line_width: float = 0.45
    shapefile: Optional[str] = None          # 自定义边界文件
    shapefile_color: str = "#b45309"
    shapefile_width: float = 0.8

    def flags(self) -> List[str]:
        """返回所有被打开的图层名（GUI 与批量处理用）。"""
        out = []
        for k in ("coastline", "borders", "lakes", "rivers", "land", "ocean"):
            if getattr(self, k, False):
                out.append(k)
        if self.shapefile:
            out.append("shapefile")
        return out


def cartopy_available() -> bool:
    try:
        import cartopy  # noqa: F401
        return True
    except Exception:                                   # noqa: BLE001
        return False


def _cache_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".local", "share", "cartopy")


def cached_shapefiles() -> List[str]:
    """列出本机已缓存的 Natural Earth 图层（用于判断能否离线运行）。"""
    root = os.path.join(_cache_dir(), "shapefiles", "natural_earth")
    out: List[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith(".shp"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def has_offline_basemap(resolution: str = "110m") -> bool:
    for p in cached_shapefiles():
        if "ne_%s_" % resolution in os.path.basename(p):
            return True
    return False


# --------------------------------------------------------------------------
# 给 cartopy 的 GeoAxes 叠加
# --------------------------------------------------------------------------
def add_overlays(ax, spec: OverlaySpec, lons=None, lats=None) -> None:
    """在 cartopy GeoAxes 上叠加底图。若 cartopy 不可用则静默跳过。"""
    if not cartopy_available():
        return
    import cartopy.feature as cfeature

    try:
        if spec.land:
            ax.add_feature(cfeature.LAND.with_scale(spec.resolution),
                           facecolor="#f4f4f2", edgecolor="none", zorder=0.5)
        if spec.ocean:
            ax.add_feature(cfeature.OCEAN.with_scale(spec.resolution),
                           facecolor="#f0f5f9", edgecolor="none", zorder=0.4)
    except Exception:                                   # noqa: BLE001
        pass

    def _line(name, width, color):
        try:
            ax.add_feature(getattr(cfeature, name.upper()).with_scale(spec.resolution),
                           linewidth=width, edgecolor=color, facecolor="none",
                           zorder=6)
        except Exception:                               # noqa: BLE001
            pass

    if spec.coastline:
        _line("coastline", spec.line_width, spec.line_color)
    if spec.borders:
        _line("borders", spec.line_width * 0.8, spec.line_color)
    if spec.lakes:
        _line("lakes", spec.line_width * 0.7, spec.line_color)
    if spec.rivers:
        _line("rivers", spec.line_width * 0.6, "#6b7280")

    if spec.shapefile:
        _add_shapefile_cartopy(ax, spec.shapefile, spec.shapefile_color,
                               spec.shapefile_width)


def _add_shapefile_cartopy(ax, path: str, color: str, width: float) -> bool:
    try:
        import cartopy.crs as ccrs
        from cartopy.io import shapereader
        reader = shapereader.Reader(path)
        for geom in reader.geometries():
            ax.add_geometries([geom], ccrs.PlateCarree(),
                              facecolor="none", edgecolor=color,
                              linewidth=width, zorder=7)
        return True
    except Exception:                                   # noqa: BLE001
        return False


# --------------------------------------------------------------------------
# 给普通（非 cartopy）Axes 叠加 —— 等距圆柱投影下用
# --------------------------------------------------------------------------
_plain_cache = {}


def natural_earth_segments(resolution: str, category: str, name: str):
    """
    读一个 Natural Earth 图层，缓存成 [(N,2) 坐标数组]。

    两种渲染路径共用同一份缓存：等距圆柱走 `add_overlays_plain`，
    投影图走 `add_overlays_projected`。避免重复读 shapefile。
    """
    key = (resolution, category, name)
    segs = _plain_cache.get(key)
    if segs is not None:
        return segs

    segs = []
    try:
        from cartopy.io import shapereader
        shp = shapereader.natural_earth(resolution=resolution,
                                        category=category, name=name)
        for geom in shapereader.Reader(shp).geometries():
            for part in (geom.geoms if hasattr(geom, "geoms") else [geom]):
                try:
                    xs, ys = part.xy
                except Exception:                       # noqa: BLE001
                    continue
                if len(xs) > 1:
                    segs.append(np.column_stack([np.asarray(xs),
                                                 np.asarray(ys)]))
    except Exception:                                   # noqa: BLE001
        segs = []
    _plain_cache[key] = segs
    return segs


def add_overlays_projected(ax, spec: OverlaySpec, src_crs) -> None:
    """
    给投影图（cartopy GeoAxes）叠加底图。

    **为什么不用 `ax.coastlines()`**：cartopy 的 FeatureArtist 是在**每次绘制时**
    才去读几何体、做投影和裁剪的 —— 这一步跑在 GUI 主线程上，
    实测会让界面卡顿近一秒。这里改成预先读好折线、装进一个 LineCollection，
    交给 matplotlib 的常规变换链路，绘制开销降到几乎可以忽略。
    """
    from matplotlib.collections import LineCollection

    layers = []
    if spec.coastline:
        layers.append(("physical", "coastline", spec.line_width, spec.line_color))
    if spec.borders:
        layers.append(("cultural", "admin_0_boundary_lines_land",
                       spec.line_width * 0.8, spec.line_color))
    if spec.lakes:
        layers.append(("physical", "lakes", spec.line_width * 0.7, spec.line_color))
    if spec.rivers:
        layers.append(("physical", "rivers_lake_centerlines",
                       spec.line_width * 0.6, "#6b7280"))

    for category, name, width, color in layers:
        segs = natural_earth_segments(spec.resolution, category, name)
        if not segs:
            continue
        ax.add_collection(LineCollection(
            segs, colors=color, linewidths=width, capstyle="round",
            transform=src_crs, zorder=6))

    if spec.shapefile:
        try:
            from cartopy.io import shapereader
            polys = []
            for geom in shapereader.Reader(spec.shapefile).geometries():
                for part in (geom.geoms if hasattr(geom, "geoms") else [geom]):
                    try:
                        xs, ys = part.xy
                    except Exception:                   # noqa: BLE001
                        continue
                    if len(xs) > 1:
                        polys.append(np.column_stack([np.asarray(xs),
                                                      np.asarray(ys)]))
            if polys:
                ax.add_collection(LineCollection(
                    polys, colors=spec.shapefile_color,
                    linewidths=spec.shapefile_width,
                    transform=src_crs, zorder=7))
        except Exception:                               # noqa: BLE001
            pass


def add_overlays_plain(ax, spec: OverlaySpec) -> None:
    """
    在普通 matplotlib Axes 上画海岸线。用于等距圆柱投影的快速路径。
    直接读 Natural Earth shapefile，不走 cartopy 的投影引擎。
    """
    if not spec.coastline and not spec.borders and not spec.shapefile:
        return
    try:
        from cartopy.io import shapereader
    except Exception:                                   # noqa: BLE001
        return

    layers = []
    if spec.coastline:
        layers.append(("physical", "coastline", spec.line_width, spec.line_color))
    if spec.borders:
        layers.append(("cultural", "admin_0_boundary_lines_land",
                       spec.line_width * 0.8, spec.line_color))
    if spec.lakes:
        layers.append(("physical", "lakes", spec.line_width * 0.7, spec.line_color))
    if spec.rivers:
        layers.append(("physical", "rivers_lake_centerlines",
                       spec.line_width * 0.6, "#6b7280"))

    for category, name, width, color in layers:
        key = (spec.resolution, category, name)
        segs = _plain_cache.get(key)
        if segs is None:
            segs = []
            try:
                shp = shapereader.natural_earth(resolution=spec.resolution,
                                                category=category, name=name)
                reader = shapereader.Reader(shp)
                for geom in reader.geometries():
                    for part in (geom.geoms if hasattr(geom, "geoms") else [geom]):
                        try:
                            xs, ys = part.xy
                        except Exception:               # noqa: BLE001
                            continue
                        if len(xs) > 1:
                            segs.append(np.column_stack([np.asarray(xs),
                                                         np.asarray(ys)]))
            except Exception:                           # noqa: BLE001
                segs = []
            _plain_cache[key] = segs
        if not segs:
            continue
        # ★ 用 LineCollection 一次画完，而不是每条折线一个 ax.plot ★
        # 110m 海岸线有一千多条线段；逐条 plot 会产生上千个 Line2D 对象，
        # 每次重绘都要逐个走一遍绘制流程 —— 实测能占掉近一秒的界面卡顿。
        # 合并成一个集合之后，重绘几乎免费。
        try:
            from matplotlib.collections import LineCollection
            ax.add_collection(LineCollection(
                segs, colors=color, linewidths=width,
                capstyle="round", zorder=6))
        except Exception:                               # noqa: BLE001
            for pts in segs:
                ax.plot(pts[:, 0], pts[:, 1], color=color, linewidth=width,
                        solid_capstyle="round", zorder=6)

    if spec.shapefile:
        try:
            reader = shapereader.Reader(spec.shapefile)
            polys = []
            for geom in reader.geometries():
                for part in (geom.geoms if hasattr(geom, "geoms") else [geom]):
                    try:
                        xs, ys = part.xy
                    except Exception:                   # noqa: BLE001
                        continue
                    if len(xs) > 1:
                        polys.append(np.column_stack([np.asarray(xs),
                                                      np.asarray(ys)]))
            if polys:
                from matplotlib.collections import LineCollection
                ax.add_collection(LineCollection(
                    polys, colors=spec.shapefile_color,
                    linewidths=spec.shapefile_width, zorder=7))
        except Exception:                               # noqa: BLE001
            pass


def shapefile_geometry(path: str):
    """读取 shapefile 的所有几何体，供掩膜使用。"""
    try:
        from cartopy.io import shapereader
        reader = shapereader.Reader(path)
        return list(reader.geometries())
    except Exception:                                   # noqa: BLE001
        return []


def cartopy_feature(name: str, resolution: str = "110m"):
    """按名字取一个 cartopy feature 对象（给 GUI 的复选框用）。"""
    if not cartopy_available():
        return None
    import cartopy.feature as cfeature
    try:
        return getattr(cfeature, name.upper()).with_scale(resolution)
    except Exception:                                   # noqa: BLE001
        return None
