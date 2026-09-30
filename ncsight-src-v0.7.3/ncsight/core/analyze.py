# -*- coding: utf-8 -*-
"""
科学分析算子（M3 科研增强）
==========================
对应 Panoply 的数组组合功能（Combine as Difference / Average /
Vector Magnitude），但做得更彻底 —— Panoply 只能做这 4 种，这里直接
接入 numpy/scipy，梯度、平滑、趋势、EOF 都能往后加。

所有算子都遵守同一约定：
  输入输出都是 FieldData，缺失值一律用 NaN 表示，不引入掩膜数组的复杂度。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .reader import NcSource, FieldData


# --------------------------------------------------------------------------
# 构造器
# --------------------------------------------------------------------------
def _wrap(fd: FieldData, values: np.ndarray, name: str,
          long_name: str = "", units: str = "") -> FieldData:
    return FieldData(
        name=name, values=values, x=fd.x, y=fd.y,
        x_name=fd.x_name, y_name=fd.y_name,
        x_role=fd.x_role, y_role=fd.y_role,
        long_name=long_name or name, units=units or fd.units,
        dims=fd.dims, select=dict(fd.select), attrs=dict(fd.attrs),
    )


def combine(a: FieldData, b: FieldData, op: str = "difference",
            label: str = "") -> FieldData:
    """
    两个场的组合运算。

    op:
      difference  a - b      （距平、变化量）
      sum         a + b
      average     (a + b)/2
      ratio       a / b
      product     a * b
      magnitude   hypot(a, b) （把 U/V 合成风速/流速）★ 对应 Panoply
      compare     保持 a 不变，仅用于并置对比（返回 a）
    """
    if a.values.shape != b.values.shape:
        raise ValueError("两个场形状不一致：%s vs %s"
                         % (a.values.shape, b.values.shape))
    op = op.lower()
    with np.errstate(invalid="ignore", divide="ignore"):
        if op == "difference":
            v = a.values - b.values
            default_label = "%s − %s" % (a.label, b.label)
        elif op == "sum":
            v = a.values + b.values
            default_label = "%s + %s" % (a.label, b.label)
        elif op == "average":
            v = (a.values + b.values) / 2.0
            default_label = "%s 与 %s 平均" % (a.label, b.label)
        elif op == "ratio":
            v = a.values / b.values
            default_label = "%s / %s" % (a.label, b.label)
        elif op == "product":
            v = a.values * b.values
            default_label = "%s × %s" % (a.label, b.label)
        elif op in ("magnitude", "hypot"):
            v = np.hypot(a.values, b.values)
            default_label = "√(%s² + %s²)" % (a.name, b.name)
        elif op == "compare":
            v = a.values.copy()
            default_label = a.label
        else:
            raise ValueError("未知的组合方式：%s" % op)

    units = a.units
    if op == "magnitude" and b.units and b.units != a.units:
        units = a.units
    return _wrap(a, v, label or default_label, label or default_label, units)


class Analyzer:
    """
    针对一个已打开的数据集做多维分析。
    典型用法：
        an = Analyzer(src)
        clim = an.composite("sst", "time")            # 时间维平均
        anom = an.anomaly("sst", clim)                # 距平
    """

    def __init__(self, source: NcSource):
        self.src = source

    # ------------------------------------------------------------------
    # 沿维度聚合
    # ------------------------------------------------------------------
    def reduce_dim(self, name: str, dim: str, how: str = "mean",
                   select: Optional[Dict[str, int]] = None) -> FieldData:
        """
        沿某个维度做聚合，把该维压成一个值。
        how: mean / min / max / std / sum / median
        """
        fd = self.src.read_field(name, {**(select or {}), dim: 0})
        vi = self.src.variables[name]
        if dim not in vi.dims:
            raise ValueError("变量 %s 没有维度 %s" % (name, vi.dims))

        axis = list(vi.dims).index(dim)
        # 读全维（把该维的 select 去掉）
        sel = dict(select or {})
        sel.pop(dim, None)
        full = self.src.read_raw(name, sel)

        fn = {"mean": np.nanmean, "min": np.nanmin, "max": np.nanmax,
              "std": np.nanstd, "sum": np.nansum, "median": np.nanmedian}
        if how not in fn:
            raise ValueError("未知聚合方式：%s" % how)
        with np.errstate(invalid="ignore"):
            reduced = fn[how](full, axis=axis)

        # 目标场（去掉该维后的剩余维度）
        out_dims = [d for i, d in enumerate(vi.dims) if i != axis]
        if len(out_dims) < 2:
            out_dims = out_dims + out_dims[:1]
        target = out_dims[-2:] if len(out_dims) >= 2 else out_dims
        return self._as_field(reduced, target, name,
                              "%s（沿 %s %s）" % (fd.label, dim, how))

    def _as_field(self, arr: np.ndarray, dims: Sequence[str], src_name: str,
                  long_name: str) -> FieldData:
        """把任意 2D ndarray 包装成有正确坐标的 FieldData。"""
        arr = np.asarray(arr, dtype="float64")
        while arr.ndim < 2:
            arr = arr[None, :]
        y_dim, x_dim = dims[-2], dims[-1]
        x = self.src.read_axis(x_dim)
        y = self.src.read_axis(y_dim)
        if x.size != arr.shape[1]:
            x = np.arange(arr.shape[1], dtype="float64")
        if y.size != arr.shape[0]:
            y = np.arange(arr.shape[0], dtype="float64")
        ax, ay = self.src.axes.get(x_dim), self.src.axes.get(y_dim)
        vi = self.src.variables.get(src_name)
        try:
            attrs = self.src.var_attrs(src_name)
        except Exception:                               # noqa: BLE001
            attrs = {}
        return FieldData(
            name=src_name, values=arr, x=x, y=y,
            x_name=x_dim, y_name=y_dim,
            x_role=ax.role if ax else None,
            y_role=ay.role if ay else None,
            long_name=long_name,
            units=vi.units if vi else "",
            dims=tuple(dims),
            attrs=attrs,
        )

    def composite(self, name: str, dim: str = "time",
                  how: str = "mean") -> FieldData:
        """多时次合成（时间维平均/中位/极值）。"""
        return self.reduce_dim(name, dim, how)

    # ------------------------------------------------------------------
    # 距平
    # ------------------------------------------------------------------
    def anomaly(self, name: str, reference: FieldData,
                select: Optional[Dict[str, int]] = None) -> FieldData:
        """距平 = 当前场 − 参考场（常为气候态）。"""
        now = self.src.read_field(name, select)
        if now.values.shape != reference.values.shape:
            raise ValueError("场与参考场的形状不一致：%s vs %s"
                             % (now.values.shape, reference.values.shape))
        return combine(now, reference, "difference", "%s 距平" % now.label)

    def anomaly_vs_mean(self, name: str, dim: str = "time",
                        select: Optional[Dict[str, int]] = None) -> FieldData:
        """以自身沿某维的平均作为参考，直接算距平（最省事的做法）。"""
        clim = self.composite(name, dim, "mean")
        return self.anomaly(name, clim, select)

    # ------------------------------------------------------------------
    # 两文件对比
    # ------------------------------------------------------------------
    @staticmethod
    def cross_compare(src_a: NcSource, var_a: str,
                      src_b: NcSource, var_b: str,
                      op: str = "difference",
                      select: Optional[Dict[str, int]] = None) -> FieldData:
        """两个不同文件/变量的对比（例如两个时次、两个模式）。"""
        a = src_a.read_field(var_a, select)
        b = src_b.read_field(var_b, select)
        label = "%s − %s" % (var_a, var_b) if op == "difference" else ""
        return combine(a, b, op, label)

    # ------------------------------------------------------------------
    # 矢量合成
    # ------------------------------------------------------------------
    def vector_magnitude(self, u_name: str, v_name: Optional[str] = None,
                         select: Optional[Dict[str, int]] = None) -> FieldData:
        """把 U/V 分量合成为风速/流速。"""
        vi = self.src.variables.get(u_name)
        partner = v_name or (vi.vector_partner if vi else None)
        if not partner:
            raise ValueError("未找到 %s 的配对分量" % u_name)
        u = self.src.read_field(u_name, select)
        v = self.src.read_field(partner, select)
        return combine(u, v, "magnitude", "流速/风速（%s/%s 合成）" % (u_name, partner))

    # ------------------------------------------------------------------
    # 区域 / 点上的时间序列
    # ------------------------------------------------------------------
    def region_mean_series(self, name: str, bbox: Sequence[float],
                           dim: str = "time") -> Tuple[np.ndarray, np.ndarray]:
        """
        取一个经纬区域内的平均值随时间的曲线。
        返回 (坐标数组, 序列数组)，坐标可能是 time / 序号。
        """
        from .grid import subset_bbox
        fd = self.src.read_field(name, {d: 0 for d in self.src.variables[name].dims
                                       if d not in (self.src.variables[name].dims[-2],
                                                    self.src.variables[name].dims[-1])})
        fd = subset_bbox(fd, list(bbox))

        vi = self.src.variables[name]
        if dim not in vi.dims:
            raise ValueError("变量 %s 没有维度 %s" % (name, dim))
        axis = list(vi.dims).index(dim)

        # 只读该维的前后范围：逐层读取 + 区域平均
        n = vi.shape[axis]
        series = np.full(n, np.nan)
        other = {d: 0 for d in vi.dims if d != dim}
        for i in range(n):
            sel = dict(other)
            sel[dim] = i
            layer = self.src.read_field(name, sel)
            layer = subset_bbox(layer, list(bbox))
            v = layer.values
            v = v[np.isfinite(v)]
            if v.size:
                series[i] = float(v.mean())

        coord: np.ndarray
        if dim in self.src.ds.variables:
            coord = self.src.read_axis(dim)
        else:
            coord = np.arange(n, dtype="float64")
        if coord.size != series.size:
            coord = np.arange(series.size, dtype="float64")
        return coord, series

    def point_series(self, name: str, lon: float, lat: float,
                     dim: str = "time", window: int = 2) -> Tuple[np.ndarray, np.ndarray]:
        """单点（或小窗口内平均）的时间序列。"""
        r = abs(lon) + abs(lat) + 1.0
        bbox = [lon - 0.5, lon + 0.5, lat - 0.5, lat + 0.5]
        return self.region_mean_series(name, bbox, dim)


# --------------------------------------------------------------------------
# 常用后处理
# --------------------------------------------------------------------------
def smooth(fd: FieldData, sigma: float = 1.0) -> FieldData:
    """高斯平滑（抑制噪声/云污染带来的斑点）。"""
    from scipy.ndimage import gaussian_filter
    v = np.asarray(fd.values, dtype="float64")
    filled = np.where(np.isfinite(v), v, np.nan)
    nan_mask = ~np.isfinite(filled)
    if nan_mask.all():
        return fd
    tmp = np.where(nan_mask, np.nanmean(filled), filled)
    out = gaussian_filter(tmp, sigma=sigma, mode="nearest")
    out[nan_mask] = np.nan
    return _wrap(fd, out, fd.name, "%s（平滑 σ=%.1f）" % (fd.label, sigma))


def gradient_magnitude(fd: FieldData) -> FieldData:
    """场强梯度（做锋面 / 涡旋边界检测用）。"""
    v = np.asarray(fd.values, dtype="float64")
    dy = _spacing(fd.y)
    dx = _spacing(fd.x)
    gy, gx = np.gradient(v, dy, dx)
    g = np.hypot(gx, gy)
    return _wrap(fd, g, fd.name + "_grad", "%s 梯度强度" % fd.label, "%s/km" % fd.units)


def _spacing(axis: np.ndarray) -> float:
    a = np.asarray(axis, dtype="float64").ravel()
    if a.size < 2:
        return 1.0
    d = float(np.nanmedian(np.abs(np.diff(a))))
    return d if d > 0 else 1.0


def wrap_like(fd: FieldData, values: np.ndarray, name: str,
              long_name: str = "", units: str = "") -> FieldData:
    """
    用一个已有场做模板，包装出一份新的场（保留坐标、轴角色、属性）。

    这是本模块所有算子的公共出口 —— 对外暴露成公开名字，
    方便在测试与用户脚本里直接构造派生场。
    """
    return _wrap(fd, values, name, long_name, units)
