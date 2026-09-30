# -*- coding: utf-8 -*-
"""
数据读取层
==========
对应 Panoply 的 `NcDataset` / `NcVariable` / `NcDataWrapper`。

设计要点：
  * 只依赖 netCDF4，不碰任何 GUI。
  * 显式关闭 netCDF4 的自动 mask_and_scale，手动走一遍 packed 解包流程。
    —— 这是必须的：netCDF4 默认已解包，若再手动乘一次 scale_factor，
       数值会错若干倍，而**空间图案仍然正确**，属于最难发现的 bug。
       本模块用 `set_auto_maskandscale(False)` 把控制权拿回来，并在
       `VarInfo` 里如实记录 scale_factor / add_offset / fill_value。
  * 远程数据集（OPeNDAP / THREDDS / S3 的 http URL）可直接传 URL 打开。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np
import netCDF4 as nc

from .detect import (
    AxisInfo, AxisRole, VarInfo, VarKind,
    classify_axis, classify_variable, detect_fill_value, detect_suggested_range,
    find_vector_partner,
)


@dataclass
class FieldData:
    """一个已经准备好的二维数据场（可直接送进绘图函数）。"""
    name: str
    values: np.ndarray                       # 二维，含 NaN 表示缺失
    x: np.ndarray                            # 横轴坐标（1D 或 2D）
    y: np.ndarray                            # 纵轴坐标（1D 或 2D）
    x_name: str = "x"
    y_name: str = "y"
    x_role: AxisRole = AxisRole.OTHER
    y_role: AxisRole = AxisRole.OTHER
    long_name: str = ""
    units: str = ""
    dims: Tuple[str, ...] = ()
    select: Dict[str, int] = field(default_factory=dict)
    attrs: Dict[str, object] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.long_name or self.name

    @property
    def caption(self) -> str:
        return "%s [%s]" % (self.label, self.units) if self.units else self.label

    @property
    def extent(self) -> Tuple[float, float, float, float]:
        """(xmin, xmax, ymin, ymax)，用于 extent 方式绘图。"""
        return (float(np.nanmin(self.x)), float(np.nanmax(self.x)),
                float(np.nanmin(self.y)), float(np.nanmax(self.y)))

    @property
    def valid_count(self) -> int:
        return int(np.count_nonzero(np.isfinite(self.values)))

    def stats(self) -> Dict[str, float]:
        v = self.values[np.isfinite(self.values)]
        if v.size == 0:
            return {"n": 0}
        return {
            "n": int(v.size),
            "min": float(v.min()),
            "max": float(v.max()),
            "mean": float(v.mean()),
            "std": float(v.std()),
            "p1": float(np.percentile(v, 1)),
            "p99": float(np.percentile(v, 99)),
        }


class NcSourceError(RuntimeError):
    pass


#: 内嵌色表变量的常见命名
_PALETTE_NAMES = {"palette", "pal", "colour_table", "color_table", "colors",
                  "colours", "ct", "lut", "colormap"}


def is_colortable(name: str, shape: Sequence[int]) -> bool:
    """
    判断某个变量是否为「内嵌色表」而非数据场。
    典型：OBPG L3 产品的 `palette`，声明为 (rgb=3, eightbitcolor=256)。
    这类变量必须排除出可制图清单，否则会被当成 (3,256) 的数据场画出来。
    """
    if name.strip().lower() in _PALETTE_NAMES:
        return True
    if len(shape) == 2 and (shape[0] == 3 and shape[1] >= 64) \
            and name.strip().lower() in _PALETTE_NAMES | {"palette"}:
        return True
    if len(shape) == 2 and shape[0] == 3 and shape[1] in (64, 128, 256, 512, 1024):
        return True
    return False


def _index_range(axis, lo: float, hi: float) -> tuple:
    """
    在一维坐标轴上找 [lo, hi] 对应的索引范围，自动兼容递增与递减。

    真实 L3 产品的纬度是**递减**的（90 → -90），不能直接 searchsorted，
    否则区域会取反。
    """
    a = np.asarray(axis, dtype="float64").ravel()
    n = a.size
    if n == 0:
        return 0, 0
    if lo > hi:
        lo, hi = hi, lo
    if a[0] <= a[-1]:
        i0 = int(np.searchsorted(a, lo, side="left"))
        i1 = int(np.searchsorted(a, hi, side="right"))
    else:
        b = a[::-1]                                  # 反成递增再查
        j0 = int(np.searchsorted(b, lo, side="left"))
        j1 = int(np.searchsorted(b, hi, side="right"))
        i0, i1 = n - j1, n - j0
    i0 = max(0, min(i0, n))
    i1 = max(0, min(i1, n))
    if i1 <= i0:
        return 0, n
    return i0, i1


class NcSource:
    """一个 netCDF 数据集 = Panoply 的 NcDataset。"""

    def __init__(self, path: str, load_axes: bool = True):
        self.path = str(path)
        if not self.path.lower().startswith(("http://", "https://", "dods://")) \
                and not os.path.exists(self.path):
            raise NcSourceError("文件不存在：%s" % self.path)
        try:
            self.ds = nc.Dataset(self.path, "r")
        except Exception as exc:                       # noqa: BLE001
            raise NcSourceError("无法打开数据集：%s\n%s" % (self.path, exc)) from exc

        self.axes: Dict[str, AxisInfo] = {}
        self.variables: Dict[str, VarInfo] = {}
        self.attrs: Dict[str, object] = {}
        self._scan(load_axes=load_axes)

    # ------------------------------------------------------------------
    # 结构扫描
    # ------------------------------------------------------------------
    def _scan(self, load_axes: bool = True) -> None:
        ds = self.ds
        self.attrs = {a: ds.getncattr(a) for a in ds.ncattrs()}
        self.dims = {name: len(d) for name, d in ds.dimensions.items()}
        self.global_attrs = self.attrs
        self.data_model = getattr(ds, "data_model", "?")

        # ---- 第 1 遍：识别每根轴 ----
        role_by_dim: Dict[str, AxisRole] = {}
        for name, var in ds.variables.items():
            if var.ndim != 1:
                continue
            ax = classify_axis(
                name=name,
                units=self._attr(var, "units", ""),
                long_name=self._attr(var, "long_name", ""),
                standard_name=self._attr(var, "standard_name", ""),
                dims=var.dimensions,
                size=var.shape[0],
                values=np.asarray(var[:], dtype="float64") if load_axes else None,
            )
            # 只有「同名维度」才作为坐标系轴
            if ax.role is not AxisRole.OTHER or name in self.dims:
                self.axes[name] = ax
                role_by_dim[name] = ax.role

        # 维度名与变量名不一致时，用维度名再兜一次
        for dim in self.dims:
            if dim not in role_by_dim:
                a = classify_axis(dim, size=self.dims[dim])
                role_by_dim[dim] = a.role
                if a.role is not AxisRole.OTHER:
                    self.axes.setdefault(dim, a)

        # ---- 第 2 遍：识别每个变量 ----
        names = list(ds.variables.keys())
        for name, var in ds.variables.items():
            attrs = {a: var.getncattr(a) for a in var.ncattrs()}
            dim_roles = [role_by_dim.get(d, AxisRole.OTHER) for d in var.dimensions]
            kind = classify_variable(name, dim_roles, var.ndim, role_by_dim)

            is_coord = name in self.axes and var.ndim == 1
            note = ""
            if not is_coord and np.issubdtype(var.dtype, np.number) is False:
                kind, note = VarKind.UNKNOWN, "非数值类型"
            if is_colortable(name, var.shape):
                kind, note = VarKind.UNKNOWN, "内嵌色表（不是数据场）"
                is_coord = True          # 借此排除出可制图清单

            vi = VarInfo(
                name=name,
                dims=tuple(var.dimensions),
                shape=tuple(var.shape),
                dtype=str(var.dtype),
                long_name=str(attrs.get("long_name", "")),
                units=str(attrs.get("units", "")),
                standard_name=str(attrs.get("standard_name", "")),
                kind=kind,
                is_coordinate=is_coord,
                suggested_range=detect_suggested_range(attrs),
                fill_value=detect_fill_value(attrs),
                scale_factor=float(attrs.get("scale_factor", 1.0) or 1.0),
                add_offset=float(attrs.get("add_offset", 0.0) or 0.0),
                has_scale_attrs=("scale_factor" in attrs or "add_offset" in attrs),
                note=note,
            )
            # 一维坐标变量自身也可以被画成折线
            if is_coord and name in self.axes and vi.kind is VarKind.UNKNOWN:
                vi.kind = VarKind.LINE_1D
            from .detect import PLOT_OPTIONS
            vi.plot_options = list(PLOT_OPTIONS.get(vi.kind, ["line"]))
            self.variables[name] = vi

        # ---- 第 3 遍：配对矢量分量 ----
        for name, vi in self.variables.items():
            partner = find_vector_partner(name, names)
            if partner and partner != name:
                pvi = self.variables.get(partner)
                if pvi is not None and pvi.shape == vi.shape and vi.shape:
                    vi.vector_partner = partner
                    if pvi.vector_partner is None:
                        pvi.vector_partner = name
                    if vi.kind is VarKind.LONLAT_FIELD:
                        vi.plot_options = list(dict.fromkeys(vi.plot_options + ["vector"]))
                        pvi.plot_options = list(dict.fromkeys(pvi.plot_options + ["vector"]))

    @staticmethod
    def _attr(var, key, default=""):
        return var.getncattr(key) if key in var.ncattrs() else default

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    @property
    def title(self) -> str:
        return str(self.attrs.get("title") or os.path.basename(self.path))

    def axis(self, name: str) -> Optional[AxisInfo]:
        return self.axes.get(name)

    def axis_by_role(self, role: AxisRole) -> Optional[AxisInfo]:
        for a in self.axes.values():
            if a.role is role:
                return a
        return None

    def lonlat_axes(self) -> Tuple[Optional[AxisInfo], Optional[AxisInfo]]:
        return self.axis_by_role(AxisRole.LAT), self.axis_by_role(AxisRole.LON)

    def plottable(self, only_geo: bool = False) -> List[VarInfo]:
        """可制图变量清单（对应 Panoply 的 Show Only Plottable Variables）。"""
        out = [v for v in self.variables.values() if v.is_plottable]
        if only_geo:
            out = [v for v in out if v.kind in (
                VarKind.LONLAT_FIELD, VarKind.LONTIME, VarKind.LATTIME,
                VarKind.LONVERT, VarKind.LATVERT)]
        return sorted(out, key=lambda v: (v.kind.value, v.name))

    def lonlat_fields(self) -> List[VarInfo]:
        return sorted([v for v in self.variables.values()
                       if v.kind is VarKind.LONLAT_FIELD],
                      key=lambda v: v.name)

    def primary_field(self) -> Optional[VarInfo]:
        """
        猜「这份数据集里用户最想画的那个变量」。

        Panoply 是直接把第一个变量丢给你，于是 L3 产品里常常一打开
        就是 qual_sst（质量标记）而不是 sst。这里的启发式依次考虑：
          1. 排除质量/标记/误差类变量（名字含 qual / flag / unc / error / mask）
          2. 优先带「建议色标范围」的变量（OBPG 会给主变量打这个标记）
          3. 优先名字出现在文件名里的变量
          4. 优先名字更短、更像「物理量」的
        """
        fields = self.lonlat_fields() or self.plottable()
        if not fields:
            return None

        bad_words = ("qual", "flag", "unc", "error", "mask", "count",
                     "nobs", "n_pixels", "palette")
        stem = os.path.splitext(os.path.basename(self.path))[0].lower()

        def score(v: VarInfo) -> tuple:
            name = v.name.lower()
            is_aux = any(w in name for w in bad_words)
            has_hint = v.suggested_range is not None
            in_name = name in stem
            return (
                0 if not is_aux else 1,          # 非辅助变量优先
                0 if has_hint else 1,            # 带建议范围优先
                0 if in_name else 1,             # 名字出现在文件名里优先
                len(v.name),                     # 名字短优先
                v.name,
            )

        return sorted(fields, key=score)[0]

    def overview(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "data_model": self.data_model,
            "title": self.title,
            "dimensions": dict(self.dims),
            "n_variables": len(self.variables),
            "n_plottable": len(self.plottable()),
            "axes": {k: {"role": v.role.value, "size": v.size, "units": v.units}
                     for k, v in self.axes.items()},
            "global_attrs": self.attrs,
        }

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def var_attrs(self, name: str) -> Dict[str, object]:
        var = self.ds.variables[name]
        return {a: var.getncattr(a) for a in var.ncattrs()}

    def read_axis(self, name: str) -> np.ndarray:
        if name not in self.ds.variables:
            # 维度没有同名变量 → 用序号代替
            return np.arange(self.dims.get(name, 0), dtype="float64")
        var = self.ds.variables[name]
        var.set_auto_maskandscale(False)
        arr = np.asarray(var[:], dtype="float64")
        var.set_auto_maskandscale(True)
        return arr

    def _decode(self, raw, vi: VarInfo) -> np.ndarray:
        """packed 解包 + 填充值 → NaN。作用范围只在这一份副本上。"""
        arr = np.asarray(raw, dtype="float64").copy()
        if vi.fill_value is not None:
            arr[arr == vi.fill_value] = np.nan
        if vi.scale_factor != 1.0:
            np.multiply(arr, vi.scale_factor, out=arr)
        if vi.add_offset != 0.0:
            np.add(arr, vi.add_offset, out=arr)
        return arr

    def read_raw(self, name: str, select: Optional[Dict[str, int]] = None,
                 window: Optional[Dict[str, tuple]] = None) -> np.ndarray:
        """
        读一个变量（可选沿非绘图维切片），返回解包后的 ndarray。

        规则：**最后两维是绘图平面**；更前面的维度按 select 取索引（缺省取 0）。
        这样 (time, lat, lon) 会返回 (lat, lon)，而 (lat, lon) 本身就完整返回。

        `window` 可以限制绘图维的读取范围与步长：`{维度名: (start, stop, step)}`。
        传了它就只有那一块会被从磁盘读出来 —— 这是把「全球 4320x8640 全读进内存
        再扔掉 98%」变成「只读需要的那一块」的关键。
        """
        if name not in self.ds.variables:
            raise NcSourceError("变量不存在：%s" % name)
        var = self.ds.variables[name]
        vi = self.variables[name]
        select = select or {}
        window = window or {}

        n_plot = min(2, var.ndim)
        idx: List[Any] = []
        for i, dim in enumerate(var.dimensions):
            if i >= var.ndim - n_plot:
                w = window.get(dim)
                idx.append(slice(*w) if w else slice(None))
            else:
                idx.append(int(select.get(dim, 0)))

        var.set_auto_maskandscale(False)
        try:
            raw = var[tuple(idx)] if idx else var[()]
        finally:
            var.set_auto_maskandscale(True)
        return self._decode(raw, vi)

    # ------------------------------------------------------------------
    def plan_read_window(self, name: str, bbox=None, max_cells: int = 0
                         ) -> Optional[Dict[str, tuple]]:
        """
        算出「该从磁盘读哪一块、用什么步长」。

        没有这一步的话，看一个 30°x30° 的小区域也要先把整幅 4320x8640
        （解包后约 300 MB）读进内存再裁掉 —— 既慢又吃内存，是界面卡顿的主要来源。

        返回 `{维度名: (start, stop, step)}`，拿不到就返回 None（调用方走全读）。
        """
        vi = self.variables.get(name)
        if vi is None or not vi.dims or len(vi.dims) < 2:
            return None
        y_dim, x_dim = vi.dims[-2], vi.dims[-1]
        x = self.read_axis(x_dim)
        y = self.read_axis(y_dim)
        if x is None or y is None or x.size < 2 or y.size < 2:
            return None

        xs, xe = 0, int(x.size)
        ys, ye = 0, int(y.size)
        if bbox and len(bbox) == 4:
            try:
                xs, xe = _index_range(x, float(bbox[0]), float(bbox[1]))
                ys, ye = _index_range(y, float(bbox[2]), float(bbox[3]))
            except Exception:                           # noqa: BLE001
                xs, xe, ys, ye = 0, int(x.size), 0, int(y.size)

        ny, nx = ye - ys, xe - xs
        if ny < 2 or nx < 2:
            return None

        sy = sx = 1
        if max_cells and max_cells > 0:
            from .grid import coarsen_strides
            sy, sx = coarsen_strides(ny, nx, int(max_cells))
        if (sy, sx) == (1, 1) and (xs, xe, ys, ye) == (0, int(x.size), 0, int(y.size)):
            return None                                 # 本来就整幅，不必包一层
        return {y_dim: (ys, ye, sy), x_dim: (xs, xe, sx)}

    def read_field(self, name: str,
                   select: Optional[Dict[str, int]] = None,
                   window: Optional[Dict[str, tuple]] = None) -> FieldData:
        """
        读出一个二维场。对多维变量，非绘图维按 `select` 取索引（默认 0）。
        返回的 FieldData 已经把 packed 数据解成物理量、缺失值转成 NaN。

        `window` 见 `read_raw` —— 传 `plan_read_window()` 的结果，
        就只从磁盘读屏幕真正需要的那一块。
        """
        vi = self.variables.get(name)
        if vi is None:
            raise NcSourceError("变量不存在：%s" % name)
        select = dict(select or {})
        if vi.kind is VarKind.UNKNOWN and vi.dims:
            raise NcSourceError("变量 %s 无法识别为可绘图类型（dims=%s）"
                                % (name, vi.dims))

        vals = self.read_raw(name, select, window=window)
        dims = vi.dims

        if vals.ndim == 1:
            ax_name = dims[0]
            ai = self.axes.get(ax_name)
            x = self.read_axis(ax_name) if ax_name in self.ds.variables \
                else np.arange(vals.size, dtype="float64")
            role = ai.role if ai else AxisRole.OTHER
            # 一维垂向廓线：坐标放纵轴，值放横轴
            if role is AxisRole.VERT:
                return FieldData(name, vals[:, None], vals[:, None], x[:, None],
                                 x_name=name, y_name=ax_name,
                                 x_role=AxisRole.OTHER, y_role=AxisRole.VERT,
                                 long_name=vi.long_name, units=vi.units,
                                 dims=dims, select=select,
                                 attrs=self.var_attrs(name))
            return FieldData(name, vals[None, :], x, None,
                             x_name=ax_name, y_name="",
                             x_role=role, y_role=AxisRole.OTHER,
                             long_name=vi.long_name, units=vi.units,
                             dims=dims, select=select,
                             attrs=self.var_attrs(name))

        y_dim, x_dim = dims[-2], dims[-1]
        x = self.read_axis(x_dim)
        y = self.read_axis(y_dim)
        # 坐标轴要用同一个窗口切，否则长度对不上（pcolormesh 会直接报错）
        if window:
            wx = window.get(x_dim)
            wy = window.get(y_dim)
            if wx:
                x = x[wx[0]:wx[1]:wx[2]]
            if wy:
                y = y[wy[0]:wy[1]:wy[2]]
        if x.size != vals.shape[1]:
            x = np.arange(vals.shape[1], dtype="float64")
        if y.size != vals.shape[0]:
            y = np.arange(vals.shape[0], dtype="float64")

        xa, ya = self.axes.get(x_dim), self.axes.get(y_dim)
        return FieldData(
            name=name,
            values=vals,
            x=x, y=y,
            x_name=x_dim, y_name=y_dim,
            x_role=xa.role if xa else AxisRole.OTHER,
            y_role=ya.role if ya else AxisRole.OTHER,
            long_name=vi.long_name, units=vi.units,
            dims=dims, select=select,
            attrs=self.var_attrs(name),
        )

    def read_pair(self, u_name: str, v_name: str,
                  select: Optional[Dict[str, int]] = None) -> Tuple[FieldData, FieldData]:
        return self.read_field(u_name, select), self.read_field(v_name, select)

    # ------------------------------------------------------------------
    def describe_text(self, name: str) -> str:
        """单个变量的属性文本（对应 Panoply 的 Info 面板）。"""
        vi = self.variables.get(name)
        if vi is None:
            return "变量不存在：%s" % name
        lines = ["变量：%s" % vi.name]
        if vi.long_name:
            lines.append("  名称     : %s" % vi.long_name)
        lines.append("  类型     : %s" % vi.dtype)
        lines.append("  维度     : (%s)  形状 %s" % (", ".join(vi.dims), vi.shape))
        lines.append("  绘图类型 : %s" % vi.kind.value)
        if vi.units:
            lines.append("  单位     : %s" % vi.units)
        if vi.standard_name:
            lines.append("  标准名   : %s" % vi.standard_name)
        if vi.has_scale_attrs:
            lines.append("  打包     : value = raw * %g + %g" % (vi.scale_factor, vi.add_offset))
        if vi.fill_value is not None:
            lines.append("  填充值   : %g" % vi.fill_value)
        if vi.suggested_range:
            lines.append("  建议范围 : %g ~ %g" % vi.suggested_range)
        if vi.vector_partner:
            lines.append("  矢量配对 : %s" % vi.vector_partner)
        if vi.note:
            lines.append("  备注     : %s" % vi.note)
        lines.append("  ── 属性 ──")
        for k, v in self.var_attrs(name).items():
            s = str(v)
            if len(s) > 200:
                s = s[:200] + " …"
            lines.append("  %-18s = %s" % (k, s))
        return "\n".join(lines)

    def describe(self) -> str:
        """整个数据集的概览文本。"""
        o = self.overview()
        lines = ["数据集：%s" % o["path"],
                 "格式   : %s" % o["data_model"],
                 "标题   : %s" % o["title"],
                 "维度   : %s" % ", ".join("%s=%d" % kv for kv in o["dimensions"].items()),
                 "变量   : %d 个（可制图 %d 个）" % (o["n_variables"], o["n_plottable"]),
                 "", "── 坐标轴 ──"]
        for k, v in self.axes.items():
            lines.append("  %-14s %-6s size=%-8d %s" % (k, v.role.value, v.size, v.units))
        lines.append("")
        lines.append("── 可制图变量 ──")
        for v in self.plottable():
            lines.append("  %-20s %-12s %-14s %s"
                         % (v.name, v.kind.value, str(v.shape), v.caption))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            self.ds.close()
        except Exception:                              # noqa: BLE001
            pass

    def __enter__(self) -> "NcSource":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __repr__(self) -> str:
        return "<NcSource %s | %d vars>" % (os.path.basename(self.path), len(self.variables))


def open_source(path: str, **kw) -> NcSource:
    return NcSource(path, **kw)
