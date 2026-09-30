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
# --------------------------------------------------------------------------
# 图层读取与缓存
# --------------------------------------------------------------------------
_plain_cache = {}

#: 视野裁剪 + 抽稀的结果缓存（键里带 bbox 与容差）
_clip_cache = {}

#: 超过这个顶点数就不交给 shapely 抽稀 —— Douglas-Peucker 是递归实现，
#: 几何体太大时 GEOS 可能把 C 栈用穿，那是段错误级别的硬崩溃
#: （进程直接消失、连 traceback 都没有，在打包环境里尤其难查）。
_SHAPELY_MAX_POINTS = 200_000


def read_shapefile_parts(path: str) -> list:
    """
    读一个 shapefile 的折线/多边形顶点，返回 [(N,2) 坐标数组]。

    ★ 为什么不用 cartopy 的 `shapereader.Reader` ★
    它在 `__init__` 里会为每个 shp 创建一个 `pyproj.CRS`（从 WKT 解析）。
    而 **PROJ 的全局状态不是线程安全的** —— 渲染跑在工作线程里，
    如果这个「首次创建 CRS」撞上主线程也在用 PROJ，就会直接
    `access violation` 闪退。实测抓到的栈：

        pyproj/crs/crs.py:350 in __init__
        ← cartopy/io/shapereader.py:145 in __init__
        ← ncsight/core/overlay.py in add_overlays_plain   （渲染工作线程）
        主线程当时正在跑 Qt 事件循环

    我们画海岸线只需要**坐标本身**，根本用不到 CRS。
    pyshp（`shapefile`）是纯 Python、不碰 PROJ，从根上避免这个问题。
    （pyshp 是 cartopy 的依赖，装机必有；万一没有再退回 cartopy。）
    """
    try:
        import shapefile as pyshp
    except Exception:                                   # noqa: BLE001
        return _read_parts_via_cartopy(path)

    out = []
    try:
        reader = pyshp.Reader(path)
        try:
            for shp in reader.iterShapes():
                pts = getattr(shp, "points", None)
                if not pts:
                    continue
                parts = list(shp.parts) + [len(pts)]
                for k in range(len(parts) - 1):
                    seg = pts[parts[k]:parts[k + 1]]
                    if len(seg) > 1:
                        out.append(np.asarray(seg, dtype="float64"))
        finally:
            try:
                reader.close()
            except Exception:                           # noqa: BLE001
                pass
    except Exception:                                   # noqa: BLE001
        return _read_parts_via_cartopy(path)
    return out


def _read_parts_via_cartopy(path: str) -> list:
    """兜底路径：pyshp 不可用时才走，注意它有上面说的线程安全问题。"""
    out = []
    try:
        from cartopy.io import shapereader
        for geom in shapereader.Reader(path).geometries():
            for part in (geom.geoms if hasattr(geom, "geoms") else [geom]):
                try:
                    xs, ys = part.xy
                except Exception:                       # noqa: BLE001
                    continue
                if len(xs) > 1:
                    out.append(np.column_stack([np.asarray(xs),
                                                np.asarray(ys)]))
    except Exception:                                   # noqa: BLE001
        pass
    return out


def natural_earth_segments(resolution: str, category: str, name: str):
    """
    读一个 Natural Earth 图层，缓存成 [(N,2) 坐标数组]。

    两种渲染路径共用同一份缓存：等距圆柱走 `add_overlays_plain`，
    投影图走 `add_overlays_projected`。避免重复读 shapefile。

    `natural_earth()` 只负责「把数据文件找出来」（必要时下载），
    **不创建 CRS**，是安全的；真正的读取交给 pyshp。
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
        segs = read_shapefile_parts(shp)
    except Exception:                                   # noqa: BLE001
        segs = []
    _plain_cache[key] = segs
    return segs


# --------------------------------------------------------------------------
# 视野裁剪与抽稀
# --------------------------------------------------------------------------
def simplify_polyline(pts: np.ndarray, tol: float) -> np.ndarray:
    """
    按容差抽稀一条折线。优先用 shapely 的 Douglas-Peucker（保形最好），
    否则退化成「按累计弧长等距取样」。

    为什么要抽稀：投影图里每个顶点都要经 cartopy 做一次投影变换。
    10m 海岸线有 41 万个顶点，屏幕上一条线最多占两三个像素，
    绝大多数的点根本画不出来 —— 抽稀掉它们纯粹是省时间。

    ⚠️ 超长折线不走 shapely：Douglas-Peucker 是递归实现，几何体太大时
    GEOS 可能把 C 栈用穿 —— 那是段错误级别的硬崩溃。
    """
    if tol <= 0 or pts is None or len(pts) < 3:
        return pts
    if len(pts) <= _SHAPELY_MAX_POINTS:
        try:
            from shapely.geometry import LineString
            g = LineString(pts).simplify(tol, preserve_topology=False)
            out = np.asarray(g.coords, dtype="float64")
            if out.ndim == 2 and len(out) >= 2:
                return out
        except Exception:                               # noqa: BLE001
            pass
    return _stride_decimate(pts, tol)


def _stride_decimate(pts: np.ndarray, tol: float) -> np.ndarray:
    """按累计弧长等距取样（纯向量化，不依赖 GEOS，超长折线也能安全处理）。"""
    try:
        d = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
        cum = np.concatenate(([0.0], np.cumsum(d)))
        if cum[-1] <= tol:
            return pts[[0, -1]]
        idx = np.searchsorted(cum, np.arange(0.0, cum[-1], tol), side="left")
        idx = np.unique(np.clip(np.append(idx, len(pts) - 1), 0, len(pts) - 1))
        return pts[idx] if idx.size >= 2 else pts
    except Exception:                                   # noqa: BLE001
        return pts


def view_tolerance(bbox, target_px: int = 1400) -> float:
    """
    由视野跨度推出「一个屏幕像素对应多少度」，作为抽稀容差。
    抽稀到亚像素级就够了 —— 再细的顶点画不出来，只会拖慢投影变换。
    """
    if not bbox or len(bbox) != 4 or target_px <= 0:
        return 0.0
    span = max(abs(float(bbox[1]) - float(bbox[0])),
               abs(float(bbox[3]) - float(bbox[2])), 1e-6)
    return span / float(target_px)


def clip_segments(segs, bbox, pad: float = 3.0, tol: float = 0.0):
    """
    按视野范围过滤线段 + 按容差抽稀。

    **为什么必须做**：10m 海岸线有 4133 条线段、41 万个顶点。只看 30°x30°
    的区域时，99% 的线段在视野外；剩下的顶点也绝大多数细于一个屏幕像素。
    但 matplotlib（尤其经 cartopy 投影时）仍要逐个处理 ——
    实测切一次高精度底图要 6~20 秒，几乎全耗在这上面。
    """
    if not bbox or len(bbox) != 4:
        return segs
    key = ((id(segs),) + tuple(round(float(b), 3) for b in bbox)
           + (round(pad, 2), round(tol, 5)))
    hit = _clip_cache.get(key)
    if hit is not None:
        return hit

    lon0, lon1 = sorted((float(bbox[0]), float(bbox[1])))
    lat0, lat1 = sorted((float(bbox[2]), float(bbox[3])))
    out = []
    for s in segs:
        try:
            x0 = float(np.min(s[:, 0])); x1 = float(np.max(s[:, 0]))
            y0 = float(np.min(s[:, 1])); y1 = float(np.max(s[:, 1]))
        except Exception:                               # noqa: BLE001
            continue
        if x1 < lon0 - pad or x0 > lon1 + pad:
            continue
        if y1 < lat0 - pad or y0 > lat1 + pad:
            continue
        out.append(simplify_polyline(s, tol) if tol > 0 else s)

    if len(_clip_cache) > 64:
        _clip_cache.clear()
    _clip_cache[key] = out
    return out


def add_overlays(ax, spec: OverlaySpec, bbox=None) -> None:
    """
    叠加底图（通用入口）。

    现在两种渲染路径都走同一条实现 —— 预读折线 + LineCollection，
    且 shapefile 一律用 pyshp 读（**不在工作线程里创建 pyproj CRS**，
    原因见 read_shapefile_parts 的说明）。
    """
    add_overlays_plain(ax, spec, bbox=bbox)


def add_overlays_projected(ax, spec: OverlaySpec, src_crs, bbox=None) -> None:
    """
    给投影图（cartopy GeoAxes）叠加底图。

    **为什么不用 `ax.coastlines()` / `add_feature`**：cartopy 的 FeatureArtist
    是在**每次绘制时**才去读几何体、做投影和裁剪的 —— 这一步跑在 GUI 主线程上，
    实测会让界面卡顿近一秒。这里改成预先读好折线、装进一个 LineCollection，
    交给 matplotlib 的常规变换链路。

    另外 `add_overlays` 已经统一到 plain 实现上，所以这里与它逻辑一致。
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

    tol = view_tolerance(bbox)
    for category, name, width, color in layers:
        segs = clip_segments(
            natural_earth_segments(spec.resolution, category, name), bbox,
            tol=tol)
        if not segs:
            continue
        ax.add_collection(LineCollection(
            segs, colors=color, linewidths=width, capstyle="round",
            transform=src_crs, zorder=6))

    if spec.shapefile:
        try:
            polys = clip_segments(read_shapefile_parts(spec.shapefile), bbox,
                                  tol=tol)
            if polys:
                ax.add_collection(LineCollection(
                    polys, colors=spec.shapefile_color,
                    linewidths=spec.shapefile_width,
                    transform=src_crs, zorder=7))
        except Exception:                               # noqa: BLE001
            pass


def add_overlays_plain(ax, spec: OverlaySpec, bbox=None) -> None:
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
        # 统一走 pyshp 读取（缓存 + 不在工作线程里创建 pyproj CRS）
        segs = natural_earth_segments(spec.resolution, category, name)
        segs = clip_segments(segs, bbox, tol=view_tolerance(bbox))
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
    """读取 shapefile 的坐标数组，供掩膜使用（pyshp，不碰 pyproj）。"""
    return read_shapefile_parts(path)


def shapefile_paths(path: str):
    """把 shapefile 读成 matplotlib Path 列表（掩膜用）。"""
    return parts_to_paths(read_shapefile_parts(path))


def parts_to_paths(parts):
    from matplotlib.path import Path
    out = []
    for arr in parts or []:
        try:
            a = np.asarray(arr, dtype="float64")
            if a.ndim == 2 and a.shape[0] >= 3:
                out.append(Path(a))
        except Exception:                               # noqa: BLE001
            continue
    return out


def cartopy_feature(name: str, resolution: str = "110m"):
    """按名字取一个 cartopy feature 对象（给 GUI 的复选框用）。"""
    if not cartopy_available():
        return None
    import cartopy.feature as cfeature
    try:
        return getattr(cfeature, name.upper()).with_scale(resolution)
    except Exception:                                   # noqa: BLE001
        return None
