# -*- coding: utf-8 -*-
"""
栅格化 / 降采样 / 区域裁切
==========================
对应 Panoply 的 `NcGridder*` 系列。

这里包含一个**非常重要的工程约束**：
    Cartopy 对非等距圆柱投影是「逐点反算」的。一个 4320x8640 的场有
    3732 万个格点，直接丢给 pcolormesh + transform 会极慢甚至内存爆掉。
    Panoply 是自己实现重采样所以不卡；用 Cartopy 时必须先降采样。
    实测：降采样到百万级以内后，Robinson / 正射等投影可以秒出。
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

from .reader import FieldData

# 单次交给投影引擎的最大格点数（经验值，可按机器性能调整）
MAX_PROJECT_CELLS = 1_500_000


def coarsen_strides(ny: int, nx: int, max_cells: int) -> Tuple[int, int]:
    """
    算出一对行列抽样步长，使抽样后的格点数**尽量贴近但不超出** max_cells。

    为什么不沿用「反复折半」的老做法：那是按 2 的幂次跳，
    目标 50 万格点时 3732 万会被一路折到 14.6 万（差 3.4 倍），
    白白丢掉细节。按步长算可以得到 46 万，同样快但清楚得多。
    """
    if max_cells <= 0 or ny * nx <= max_cells:
        return 1, 1

    s = max(1, int(math.ceil(math.sqrt((ny * nx) / float(max_cells)))))
    limit = max(1, max(ny, nx))
    while s <= limit:
        cy = (ny + s - 1) // s
        cx = (nx + s - 1) // s
        if cy * cx <= max_cells:
            return s, s
        s += 1
    return s, s


def coarsen_array(arr: np.ndarray, max_cells: int = MAX_PROJECT_CELLS) -> np.ndarray:
    """按算出的步长抽样，直到格点数不超过 max_cells。"""
    if arr.ndim < 2:
        return arr
    sy, sx = coarsen_strides(arr.shape[0], arr.shape[1], max_cells)
    if (sy, sx) == (1, 1):
        return arr
    return arr[::sy, ::sx]


def coarsen_axis(axis: np.ndarray, n_target: int) -> np.ndarray:
    """按目标长度对一维坐标抽样（保留首元素，末尾可能少一格）。"""
    if axis is None or axis.size <= n_target or n_target <= 0:
        return axis
    step = max(1, int(math.ceil(axis.size / float(n_target))))
    return axis[::step]


def coarsen_field(fd: FieldData, max_cells: int = MAX_PROJECT_CELLS) -> FieldData:
    """
    对二维场做整体降采样，x/y 用**同一个步长**抽样，
    保证抽样后「数据形状」与「坐标长度」严格一致（pcolormesh 的硬要求）。
    """
    ny, nx = fd.values.shape
    if max_cells <= 0 or ny * nx <= max_cells:
        return fd

    sy, sx = coarsen_strides(ny, nx, max_cells)
    if (sy, sx) == (1, 1):
        return fd

    vals = fd.values[::sy, ::sx]
    x = fd.x[::sx] if fd.x is not None and fd.x.ndim == 1 else fd.x
    y = fd.y[::sy] if fd.y is not None and fd.y.ndim == 1 else fd.y

    return FieldData(
        name=fd.name, values=vals, x=x, y=y,
        x_name=fd.x_name, y_name=fd.y_name,
        x_role=fd.x_role, y_role=fd.y_role,
        long_name=fd.long_name, units=fd.units,
        dims=fd.dims, select=dict(fd.select), attrs=dict(fd.attrs),
    )


def _index_range(axis: np.ndarray, lo: float, hi: float) -> Tuple[int, int, int]:
    """返回 (start, stop, step)，step 为 ±1，自动适配递减轴。"""
    a = np.asarray(axis, dtype="float64")
    if a.size < 2:
        return 0, a.size, 1
    desc = a[0] > a[-1]
    if desc:
        lo, hi = max(lo, hi), min(lo, hi)
        idx = np.where((a <= lo) & (a >= hi))[0]
    else:
        idx = np.where((a >= lo) & (a <= hi))[0]
    if idx.size == 0:
        return 0, 0, 1
    return int(idx[0]), int(idx[-1]) + 1, 1


def subset_bbox(fd: FieldData,
                bbox: Optional[Sequence[float]]) -> FieldData:
    """
    按 [lon_min, lon_max, lat_min, lat_max] 裁切。

    对 lat/lon 型二维场，自动按角色判断哪根轴是经度；对普通 XY 场，
    则按 x→[0],[1] y→[2],[3] 解释。支持递减轴（如 VIIRS 的 lat 从北到南）。
    """
    if not bbox or len(bbox) != 4:
        return fd
    b0, b1, b2, b3 = [float(v) for v in bbox]

    import numpy as np
    from .detect import AxisRole

    x_is_lon = fd.x_role is AxisRole.LON
    y_is_lon = fd.y_role is AxisRole.LON

    if x_is_lon or y_is_lon:
        lon_axis = fd.x if x_is_lon else fd.y
        lat_axis = fd.y if x_is_lon else fd.x
        lon_lo, lon_hi = b0, b1
        lat_lo, lat_hi = b2, b3
    else:
        lon_axis, lat_axis = fd.x, fd.y
        lon_lo, lon_hi, lat_lo, lat_hi = b0, b1, b2, b3

    if lon_axis is None or lat_axis is None:
        return fd
    if lon_axis.ndim != 1 or lat_axis.ndim != 1:
        return fd        # 曲线网格暂不支持按 bbox 裁切

    # 处理跨 180° 经线的情况
    lon_axis_v = np.asarray(lon_axis, dtype="float64")
    if lon_hi < lon_lo:
        m = (lon_axis_v >= lon_lo) | (lon_axis_v <= lon_hi)
        li = np.where(m)[0]
        if li.size == 0:
            return fd
        l_start, l_stop = int(li[0]), int(li[-1]) + 1
    else:
        l_start, l_stop, _ = _index_range(lon_axis_v, lon_lo, lon_hi)

    a_start, a_stop, _ = _index_range(np.asarray(lat_axis, dtype="float64"),
                                      lat_lo, lat_hi)
    if l_stop <= l_start or a_stop <= a_start:
        return fd

    if x_is_lon:
        vals = fd.values[a_start:a_stop, l_start:l_stop]
        x = fd.x[l_start:l_stop]
        y = fd.y[a_start:a_stop]
    else:
        vals = fd.values[a_start:a_stop, l_start:l_stop]
        x = fd.x[l_start:l_stop]
        y = fd.y[a_start:a_stop]

    if vals.size == 0:
        return fd
    return FieldData(
        name=fd.name, values=vals, x=x, y=y,
        x_name=fd.x_name, y_name=fd.y_name,
        x_role=fd.x_role, y_role=fd.y_role,
        long_name=fd.long_name, units=fd.units,
        dims=fd.dims, select=dict(fd.select), attrs=dict(fd.attrs),
    )


def resample_regular(fd: FieldData, nx: int, ny: int,
                     method: str = "linear") -> FieldData:
    """
    把（可能是曲线网格的）场重采样到 nx×ny 的规则网格。
    使用 scipy.interpolate.griddata，适合中等规模；超大网格请改用 pyresample。
    """
    from scipy.interpolate import griddata

    X, Y = fd.x, fd.y
    if X.ndim == 1 and Y.ndim == 1:
        return fd
    pts = np.column_stack([X.ravel(), Y.ravel()])
    vals = fd.values.ravel()
    ok = np.isfinite(vals)
    xi = np.linspace(np.nanmin(X), np.nanmax(X), nx)
    yi = np.linspace(np.nanmin(Y), np.nanmax(Y), ny)
    XI, YI = np.meshgrid(xi, yi)
    zi = griddata(pts[ok], vals[ok], (XI, YI), method=method)
    return FieldData(
        name=fd.name, values=zi, x=xi, y=yi,
        x_name=fd.x_name, y_name=fd.y_name,
        x_role=fd.x_role, y_role=fd.y_role,
        long_name=fd.long_name, units=fd.units,
        dims=fd.dims, select=dict(fd.select), attrs=dict(fd.attrs),
    )


def apply_mask(fd: FieldData, mask: np.ndarray) -> FieldData:
    """把布尔掩膜（True = 需要保留）作用到场值上。"""
    m = np.asarray(mask, dtype=bool)
    if m.shape != fd.values.shape:
        return fd
    vals = np.where(m, fd.values, np.nan)
    return FieldData(
        name=fd.name, values=vals, x=fd.x, y=fd.y,
        x_name=fd.x_name, y_name=fd.y_name,
        x_role=fd.x_role, y_role=fd.y_role,
        long_name=fd.long_name, units=fd.units,
        dims=fd.dims, select=dict(fd.select), attrs=dict(fd.attrs),
    )
