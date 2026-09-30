# -*- coding: utf-8 -*-
"""
变量与坐标轴类型识别
====================
对应 Panoply 的 `NcVarTypeDetector` / `NcArrayFactory`。

Panoply 靠读取 units / standard_name / coordinates 等 CF 属性来猜「这个变量
到底是什么类型的网格」。本模块把这套判断逻辑显式化，并刻意做厚了**容错**：
属性写法不规范的 nc 文件（很常见）也能被正确识别，而不是报「无法绘图」。

识别结果分两级：
  1. AxisRole     —— 某根轴的语义：lon / lat / time / vert / other
  2. VarKind      —— 某个变量的可绘图类型：lonlat_field / lon_time /
                     lat_time / lon_vert / lat_vert / line_1d / vector / other
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple


# --------------------------------------------------------------------------
# 单位别名表：把各种不规范写法都归一到统一语义
# --------------------------------------------------------------------------
_LON_UNITS = {
    "degrees_east", "degree_east", "degrees_e", "degree_e", "dege",
    "degrees_eastward", "degrees_eastwards", "degreese", "degrees east",
    "lon", "longitude", "deg_e", "degeast",
}
_LAT_UNITS = {
    "degrees_north", "degree_north", "degrees_n", "degree_n", "degn",
    "degrees_northward", "degrees_northwards", "degreesn", "degrees north",
    "lat", "latitude", "deg_n", "degnorth",
}
_TIME_HINTS = ("since", "hours", "days", "seconds", "minutes", "months", "years")
_VERT_HINTS = ("m", "meters", "metres", "mbar", "hpa", "pa", "bar", "dbar",
               "cm", "mm", "km", "level", "sigma", "depth", "pressure", "altitude")
_VERT_STD_NAMES = {
    "depth", "height", "altitude", "air_pressure", "sea_floor_depth_below_sea_surface",
    "ocean_sigma_coordinate", "ocean_s_coordinate", "atmosphere_hybrid_sigma_pressure_coordinate",
}

# 经纬度的变量名兜底（属性缺失时用）
_LON_NAMES = {"lon", "longitude", "x", "nav_lon", "lon_rho", "lon_u", "lon_v", "TLON", "XLONG"}
_LAT_NAMES = {"lat", "latitude", "y", "nav_lat", "lat_rho", "lat_u", "lat_v", "TLAT", "XLAT"}
_TIME_NAMES = {"time", "t", "times", "juld", "date", "Time", "MT"}
_LON_LAT_PAIRS = {("lon", "lat"), ("longitude", "latitude"), ("nav_lon", "nav_lat"),
                  ("x", "y"), ("TLON", "TLAT"), ("XLONG", "XLAT")}


class AxisRole(str, Enum):
    LON = "lon"
    LAT = "lat"
    TIME = "time"
    VERT = "vert"
    OTHER = "other"


class VarKind(str, Enum):
    """可绘图类型。字符串值同时用作 PlotSpec.kind 之外的内部路由键。"""
    LONLAT_FIELD = "lonlat"        # (lat, lon) → 地图
    LONTIME = "lontime"            # (time, lon) → Hovmöller
    LATTIME = "lattime"            # (time, lat) → Hovmöller
    LONVERT = "lonvert"            # (vert, lon) → 剖面
    LATVERT = "latvert"            # (vert, lat) → 剖面
    TIMESERIES = "timeseries"      # (time,)   → 折线
    LINE_1D = "line1d"             # (x,)      → 折线
    PROFILE_1D = "profile1d"       # (vert,)   → 垂向廓线
    VECTOR_2D = "vector2d"         # (lat, lon) 的成对分量 → 矢量场
    UNKNOWN = "unknown"


# 每种 VarKind 允许的绘图方式（kind → 可选的 plot.kind 列表）
PLOT_OPTIONS: Dict[VarKind, List[str]] = {
    VarKind.LONLAT_FIELD: ["map", "vector"],
    VarKind.LONTIME: ["hovmoller"],
    VarKind.LATTIME: ["hovmoller"],
    VarKind.LONVERT: ["section"],
    VarKind.LATVERT: ["section"],
    VarKind.TIMESERIES: ["line"],
    VarKind.LINE_1D: ["line"],
    VarKind.PROFILE_1D: ["line"],
    VarKind.VECTOR_2D: ["vector", "map"],
    VarKind.UNKNOWN: ["line"],
}


@dataclass
class AxisInfo:
    name: str
    role: AxisRole
    size: int
    units: str = ""
    long_name: str = ""
    values: Optional[object] = None          # 一维坐标数组，按需填充
    reason: str = ""                          # 判定依据，便于排错

    @property
    def is_geo(self) -> bool:
        return self.role in (AxisRole.LON, AxisRole.LAT)

    @property
    def ascending(self) -> Optional[bool]:
        if self.values is None or len(self.values) < 2:
            return None
        return bool(self.values[-1] > self.values[0])


@dataclass
class VarInfo:
    name: str
    dims: Tuple[str, ...]
    shape: Tuple[int, ...]
    dtype: str
    long_name: str = ""
    units: str = ""
    standard_name: str = ""
    kind: VarKind = VarKind.UNKNOWN
    plot_options: List[str] = field(default_factory=list)
    is_coordinate: bool = False               # 是否是坐标变量本身（lat/lon/…）
    suggested_range: Optional[Tuple[float, float]] = None
    fill_value: Optional[float] = None
    scale_factor: float = 1.0
    add_offset: float = 0.0
    has_scale_attrs: bool = False
    vector_partner: Optional[str] = None      # 若是矢量分量，另一分量的名字
    note: str = ""

    @property
    def label(self) -> str:
        return self.long_name or self.name

    @property
    def ndim(self) -> int:
        """维数。注意：这是**变量本身的维数**，不是绘图平面的维数。"""
        return len(self.dims)

    @property
    def shape2d(self) -> Tuple[int, int]:
        """绘图平面的形状（最后两维）。"""
        if len(self.shape) >= 2:
            return int(self.shape[-2]), int(self.shape[-1])
        if len(self.shape) == 1:
            return 1, int(self.shape[0])
        return 0, 0

    @property
    def extra_dims(self) -> Tuple[str, ...]:
        """除绘图平面之外的维度（就是可以「切片」的那些维）。"""
        return tuple(self.dims[:max(0, len(self.dims) - 2)])

    @property
    def caption(self) -> str:
        if self.units:
            return "%s [%s]" % (self.label, self.units)
        return self.label

    @property
    def is_plottable(self) -> bool:
        return self.kind != VarKind.UNKNOWN and not self.is_coordinate


# --------------------------------------------------------------------------
# 判定逻辑
# --------------------------------------------------------------------------
def _norm_unit(u: str) -> str:
    return (u or "").strip().lower().replace("-", "_").replace(" ", "")


def classify_axis(name: str, units: str = "", long_name: str = "",
                  standard_name: str = "", dims: Sequence[str] = (),
                  size: int = 0, values=None) -> AxisInfo:
    """判断一根轴的语义。容错顺序：units → standard_name → 变量名。"""
    nu = _norm_unit(units)
    sn = (standard_name or "").strip().lower()
    nm = name.strip()

    role, reason = AxisRole.OTHER, ""

    if nu in _LON_UNITS:
        role, reason = AxisRole.LON, "units=%s" % units
    elif nu in _LAT_UNITS:
        role, reason = AxisRole.LAT, "units=%s" % units
    elif sn == "longitude":
        role, reason = AxisRole.LON, "standard_name=longitude"
    elif sn == "latitude":
        role, reason = AxisRole.LAT, "standard_name=latitude"
    elif nm in _LON_NAMES or nm.lower() in _LON_NAMES:
        role, reason = AxisRole.LON, "变量名兜底"
    elif nm in _LAT_NAMES or nm.lower() in _LAT_NAMES:
        role, reason = AxisRole.LAT, "变量名兜底"
    elif sn in ("time", "forecast_reference_time") or nm.lower() in _TIME_NAMES:
        role, reason = AxisRole.TIME, "standard_name/变量名=time"
    elif any(h in nu for h in _TIME_HINTS) and "since" in nu:
        role, reason = AxisRole.TIME, "units 含 since 时间单位"
    elif sn in _VERT_STD_NAMES:
        role, reason = AxisRole.VERT, "standard_name=%s" % sn
    elif nu in _VERT_HINTS:
        role, reason = AxisRole.VERT, "units=%s" % units
    else:
        # 名字里带 depth/level/pressure 等关键词也算垂向
        low = nm.lower()
        if any(k in low for k in ("depth", "level", "pres", "sigma", "alt", "height", "lev")):
            role, reason = AxisRole.VERT, "变量名含垂向关键词"

    # 兜底：名字叫 lon/lat 但单位是 degrees（未区分东南西北）
    if role is AxisRole.OTHER and nu in ("degrees", "degree", "deg"):
        low = nm.lower()
        if any(k in low for k in ("lon", "lon_", "_lon")):
            role, reason = AxisRole.LON, "units=degrees + 变量名含 lon"
        elif any(k in low for k in ("lat", "lat_", "_lat")):
            role, reason = AxisRole.LAT, "units=degrees + 变量名含 lat"

    return AxisInfo(name=name, role=role, size=size, units=units or "",
                    long_name=long_name or "", values=values, reason=reason)


def classify_variable(name: str, dim_roles: Sequence[AxisRole],
                      ndim: int, role_of: Dict[str, AxisRole]) -> VarKind:
    """根据各维的语义判定变量的可绘图类型。"""
    if ndim == 0:
        return VarKind.UNKNOWN
    if ndim == 1:
        r = dim_roles[0] if dim_roles else AxisRole.OTHER
        if r is AxisRole.TIME:
            return VarKind.TIMESERIES
        if r is AxisRole.VERT:
            return VarKind.PROFILE_1D
        return VarKind.LINE_1D
    if ndim == 2:
        last = dim_roles[-1] if ndim >= 1 else AxisRole.OTHER
        prev = dim_roles[-2] if ndim >= 2 else AxisRole.OTHER
        pair = {prev, last}
        if pair == {AxisRole.LAT, AxisRole.LON}:
            return VarKind.LONLAT_FIELD
        if pair == {AxisRole.LON, AxisRole.TIME}:
            return VarKind.LONTIME
        if pair == {AxisRole.LAT, AxisRole.TIME}:
            return VarKind.LATTIME
        if pair == {AxisRole.LON, AxisRole.VERT}:
            return VarKind.LONVERT
        if pair == {AxisRole.LAT, AxisRole.VERT}:
            return VarKind.LATVERT
        if AxisRole.TIME in pair:
            return VarKind.TIMESERIES
        return VarKind.LONLAT_FIELD if pair <= {AxisRole.LON, AxisRole.LAT,
                                               AxisRole.OTHER} else VarKind.LONLAT_FIELD
    # ndim >= 3：取最后两维作为绘图平面，其余作为可切片维度
    last = dim_roles[-1]
    prev = dim_roles[-2]
    pair = {prev, last}
    if pair == {AxisRole.LAT, AxisRole.LON}:
        return VarKind.LONLAT_FIELD
    if AxisRole.LON in pair and AxisRole.TIME in pair:
        return VarKind.LONTIME
    if AxisRole.LAT in pair and AxisRole.TIME in pair:
        return VarKind.LATTIME
    if AxisRole.LON in pair and AxisRole.VERT in pair:
        return VarKind.LONVERT
    if AxisRole.LAT in pair and AxisRole.VERT in pair:
        return VarKind.LATVERT
    return VarKind.UNKNOWN


_VECTOR_BASE = re.compile(r"^(.*?)(?:_)?(u|v|east|north|ew|ns|merid|zonal|meridional)$", re.I)
_VECTOR_PAIR_HINT = [
    ("u", "v"), ("u10", "v10"), ("uwnd", "vwnd"), ("east", "north"),
    ("uo", "vo"), ("us", "vs"), ("u_velocity", "v_velocity"),
    ("water_u", "water_v"), ("u_component", "v_component"),
]


def find_vector_partner(name: str, names: Sequence[str]) -> Optional[str]:
    """找出矢量分量的配对变量（u↔v / east↔north / uo↔vo …）。"""
    low = name.lower()
    for a, b in _VECTOR_PAIR_HINT:
        if low == a and b in names:
            return b
        if low == b and a in names:
            return a
        if low.endswith(a) and low[:-len(a)].rstrip("_") + b in names:
            return low[:-len(a)].rstrip("_") + b
        if low.endswith(b) and low[:-len(b)].rstrip("_") + a in names:
            return low[:-len(b)].rstrip("_") + a
    m = _VECTOR_BASE.match(low)
    if m:
        stem = m.group(1).rstrip("_")
        other = "v" if m.group(2).lower() in ("u", "east", "ew", "zonal") else "u"
        cand = (stem + other) if stem else other
        if cand in names:
            return cand
    return None


def detect_suggested_range(attrs: Dict[str, object]) -> Optional[Tuple[float, float]]:
    """从变量属性里挖出「建议色标范围」。OBPG 产品自带这类线索，直接用能省事。"""
    pairs = [
        ("display_min", "display_max"),
        ("valid_min", "valid_max"),
        ("suggested_image_scaling_minimum", "suggested_image_scaling_maximum"),
        ("data_minimum", "data_maximum"),
        ("actual_range", None),
    ]
    for lo, hi in pairs:
        if hi is None:
            v = attrs.get(lo)
            if isinstance(v, (list, tuple)) and len(v) == 2:
                try:
                    return float(v[0]), float(v[1])
                except Exception:
                    pass
            continue
        if lo in attrs and hi in attrs:
            try:
                a, b = float(attrs[lo]), float(attrs[hi])
                if b > a:
                    return a, b
            except Exception:
                pass
    return None


def detect_fill_value(attrs: Dict[str, object]) -> Optional[float]:
    for key in ("_FillValue", "missing_value", "fill_value"):
        if key in attrs:
            try:
                return float(attrs[key])
            except Exception:
                return None
    return None
