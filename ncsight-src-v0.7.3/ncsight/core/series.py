# -*- coding: utf-8 -*-
"""
多文件时序构建
==============
**这是"把一堆逐日卫星数据变成一条时间序列"的核心。**

实际科研里最常见的形态是：一个变量、很多天的 L3 逐日产品（文件名里带日期），
想直接看它的区域平均随时间怎么变、有没有趋势、周期是多少。
传统做法要先写脚本循环读文件、算区域平均、拼时间轴 —— 门槛就在这儿。

本模块处理三件事：

1. **时间识别**（三级兜底，这是最容易出错的地方）
   ① 文件里的 time 变量 + units（最可靠）
   ② 文件名里的日期（逐日产品靠这个，形如 ...20180105... 或 ....2018005.）
   ③ 都没有 → 用样本序号，并在结果里明确标注"时间轴为序号"
2. **统一网格**：不同文件的网格可能不同（甚至分辨率不同），
   统一先裁到共同区域、再用固定的抽样步长，保证每个时次的空间权重一致
3. **区域/点统计**：区域平均默认按 cos(纬度) 加权 —— 等距圆柱网格上
   高纬度的格点代表更小的实际面积，不加权会系统性偏冷/偏暖

产出 `TimeSeries`（时间 + 值 + 单位 + 元信息），后续所有指标都作用在它上面。
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .detect import AxisRole
from .reader import NcSource, NcSourceError

#: 空间统计方式
STATS = [
    ("mean", "区域平均"),
    ("median", "区域中位数"),
    ("max", "区域最大"),
    ("min", "区域最小"),
    ("std", "区域标准差"),
    ("p90", "区域 90 分位"),
    ("p10", "区域 10 分位"),
]


# ----------------------------------------------------------------------
# 文件名日期识别
# ----------------------------------------------------------------------
_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # 20180105 / 2018-01-05 / 2018_01_05
    (re.compile(r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})"), "ymd"),
    # 年积日：.2018005. 或 _2018005_
    (re.compile(r"[-_.](20\d{2})(\d{3})[-_.]"), "ydoy"),
    # 只有年月：2018-01 / 201801
    (re.compile(r"(20\d{2})[-_.]?(\d{2})(?!\d)"), "ym"),
]


def parse_date_from_name(path: str) -> Optional[np.datetime64]:
    """
    从文件名里抠日期。逐日卫星产品的文件名几乎都带 YYYYMMDD 或 YYYYDDD。

    支持：
        20180105                  形如 JPSS1_VIIRS.20180105.L3m.DAY...
        2018-01-05 / 2018_01_05
        .2018005.                 年积日
        2018-01                   只有年月 → 取当月 1 日
    """
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]

    for pat, kind in _PATTERNS:
        m = pat.search(stem)
        if not m:
            continue
        try:
            if kind == "ymd":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if 1 <= mo <= 12 and 1 <= d <= 31:
                    return np.datetime64("%04d-%02d-%02d" % (y, mo, d), "s")
            elif kind == "ydoy":
                y, doy = int(m.group(1)), int(m.group(2))
                if 1 <= doy <= 366:
                    return (np.datetime64("%04d-01-01" % y, "s")
                            + np.timedelta64(doy - 1, "D"))
            elif kind == "ym":
                y, mo = int(m.group(1)), int(m.group(2))
                if 1 <= mo <= 12:
                    return np.datetime64("%04d-%02d-01" % (y, mo), "s")
        except Exception:                               # noqa: BLE001
            continue
    return None


# ----------------------------------------------------------------------
def decode_time_axis(source: NcSource) -> Optional[np.ndarray]:
    """
    读文件里的时间轴，返回 datetime64 数组；读不到返回 None。

    优先用 CF 的 units（'days since 1981-01-01' 之类），
    netCDF4 能直接转；非标准日历（360_day 等）走 cftime。
    """
    for name in ("time", "Time", "TIME", "t", "date", "Date", "times"):
        if name not in source.ds.variables:
            continue
        var = source.ds.variables[name]
        units = getattr(var, "units", None)
        if not units:
            continue
        try:
            raw = np.asarray(var[:]).ravel()
        except Exception:                               # noqa: BLE001
            continue
        calendar = getattr(var, "calendar", "standard")
        try:
            import netCDF4
            dts = netCDF4.num2date(raw, units, calendar,
                                   only_use_cftime_datetimes=False)
            out = []
            for d in np.atleast_1d(dts):
                try:
                    out.append(np.datetime64(
                        "%04d-%02d-%02dT%02d:%02d:%02d" % (
                            d.year, d.month, d.day,
                            getattr(d, "hour", 0), getattr(d, "minute", 0),
                            getattr(d, "second", 0)), "s"))
                except Exception:                       # noqa: BLE001
                    out.append(np.datetime64("NaT"))
            arr = np.array(out, dtype="datetime64[s]")
            if np.any(~np.isnat(arr)):
                return arr
        except Exception:                               # noqa: BLE001
            continue
    return None


# ----------------------------------------------------------------------
@dataclass
class TimeSeries:
    """一条时间序列：时间 + 值 + 元信息。所有指标都作用在它上面。"""

    time: np.ndarray                       # datetime64[s]
    values: np.ndarray                     # float64
    label: str = ""                        # 图例名
    units: str = ""
    long_name: str = ""
    variable: str = ""
    stat: str = "mean"
    region: Optional[List[float]] = None
    time_source: str = "index"             # metavar: 时间轴的来源
    meta: Dict[str, object] = field(default_factory=dict)

    # ---------------------------------------------------------------
    def __len__(self) -> int:
        return int(self.values.size)

    @property
    def valid(self) -> np.ndarray:
        return np.isfinite(self.values)

    def clean(self) -> "TimeSeries":
        m = self.valid
        return TimeSeries(
            time=self.time[m], values=self.values[m].astype("float64"),
            label=self.label, units=self.units, long_name=self.long_name,
            variable=self.variable, stat=self.stat, region=self.region,
            time_source=self.time_source, meta=dict(self.meta))

    def sort(self) -> "TimeSeries":
        idx = np.argsort(self.time)
        return TimeSeries(
            time=self.time[idx], values=self.values[idx],
            label=self.label, units=self.units, long_name=self.long_name,
            variable=self.variable, stat=self.stat, region=self.region,
            time_source=self.time_source, meta=dict(self.meta))

    def t_years(self) -> np.ndarray:
        """时间换算成"年"（浮点），用于线性回归。"""
        t = self.time.astype("datetime64[D]").astype("int64").astype("float64")
        return t / 365.2425

    def t_days(self) -> np.ndarray:
        return self.time.astype("datetime64[D]").astype("int64").astype("float64")

    def stats(self) -> Dict[str, float]:
        v = self.values[self.valid]
        if v.size == 0:
            return {"n": 0}
        return {
            "n": int(v.size),
            "mean": float(np.mean(v)),
            "std": float(np.std(v, ddof=1)) if v.size > 1 else 0.0,
            "min": float(np.min(v)),
            "max": float(np.max(v)),
            "median": float(np.median(v)),
        }

    def caption(self) -> str:
        s = self.label or self.long_name or self.variable or "值"
        return "%s [%s]" % (s, self.units) if self.units else s


# ----------------------------------------------------------------------
class SeriesBuilder:
    """
    从一批 nc 文件里构建一条时间序列。

    参数
    ----
    paths        : 文件路径列表（顺序无所谓，内部会按时间排序）
    variable     : 变量名。留空则自动挑「主轴变量」（避开 qual_* 之类质量标记）
    region       : [lon_min, lon_max, lat_min, lat_max]，None = 全球
    point        : (lon, lat)，给了就取最近格点（优先于 region）
    stat         : 空间统计方式，见 STATS
    max_cells    : 空间降采样上限。跨文件必须用**同一步长**，
                   否则不同时次的空间权重会不一致
    """

    def __init__(self, paths: Sequence[str], variable: str = "",
                 region: Optional[Sequence[float]] = None,
                 point: Optional[Sequence[float]] = None,
                 stat: str = "mean", max_cells: int = 400_000,
                 select: Optional[Dict[str, int]] = None):
        self.paths = [p for p in paths if p and os.path.exists(p)]
        self.variable = variable
        self.region = list(region) if region else None
        self.point = tuple(point) if point else None
        self.stat = stat if stat in dict(STATS) else "mean"
        self.max_cells = int(max_cells)
        self.select = dict(select or {})
        self.warnings: List[str] = []

    # ------------------------------------------------------------------
    @staticmethod
    def expand(patterns: Sequence[str]) -> List[str]:
        """把通配符 / 目录展开成文件列表（方便命令行直接粘一串路径）。"""
        out: List[str] = []
        for p in patterns:
            if os.path.isdir(p):
                out += sorted(glob.glob(os.path.join(p, "*.nc")))
                out += sorted(glob.glob(os.path.join(p, "*.nc4")))
            elif any(ch in p for ch in "*?["):
                out += sorted(glob.glob(p))
            else:
                out.append(p)
        seen, uniq = set(), []
        for p in out:
            ap = os.path.abspath(p)
            if ap not in seen:
                seen.add(ap)
                uniq.append(ap)
        return uniq

    # ------------------------------------------------------------------
    def pick_variable(self, sources: Sequence[NcSource]) -> str:
        """在所有文件的公共可制图变量里挑一个主变量。"""
        if self.variable:
            return self.variable
        first = None
        for s in sources:
            try:
                pf = s.primary_field()
            except Exception:                           # noqa: BLE001
                pf = None
            if pf is not None:
                first = first or pf.name
        if first is None:
            raise NcSourceError("这些文件里没有找到可制图的变量")
        return first

    # ------------------------------------------------------------------
    def build(self, progress=None, should_stop=None) -> TimeSeries:
        if not self.paths:
            raise NcSourceError("没有可用的文件")

        times: List[np.datetime64] = []
        values: List[float] = []
        index_only: List[int] = []
        src_kind = None
        label = units = long_name = ""
        variable = self.variable
        ok_files, bad_files = 0, []

        # —— 第一遍：先探明时间轴来源与变量 ——
        probe: List[Optional[np.datetime64]] = []
        for p in self.paths:
            probe.append(parse_date_from_name(p))

        for i, path in enumerate(self.paths):
            if should_stop is not None and should_stop():
                break
            if progress is not None:
                progress(i, len(self.paths), os.path.basename(path))
            try:
                src = NcSource(path)
            except Exception as exc:                    # noqa: BLE001
                bad_files.append((os.path.basename(path), str(exc)))
                continue
            try:
                if not variable:
                    variable = self.pick_variable([src])

                # ★ 按窗口读 ★
                # 时序通常只关心一个区域。不这么做的话，每个文件都要先把
                # 整幅全球场读进内存（4320x8640 解包后约 300 MB）再裁掉 99%，
                # 几百个文件下来又慢又吃内存。
                window = None
                try:
                    window = src.plan_read_window(variable, self.region,
                                                  self.max_cells)
                except Exception:                       # noqa: BLE001
                    window = None
                fd = src.read_field(variable, self.select, window=window)
                fd = self._spatial_subset(fd, already_windowed=bool(window))

                # 时间：① 文件内 time 变量  ② 文件名  ③ 序号
                t_arr = decode_time_axis(src)
                t = None
                if t_arr is not None and t_arr.size:
                    t = np.asarray(t_arr).ravel()[0]
                    src_kind = src_kind or "variable"
                elif probe[i] is not None:
                    t = probe[i]
                    src_kind = src_kind or "filename"
                if t is None:
                    t = np.datetime64("NaT")
                    src_kind = "index"

                val = self._reduce(fd)
                if not np.isfinite(val):
                    bad_files.append((os.path.basename(path), "该时次无有效数据"))
                    continue
                times.append(t)
                values.append(float(val))
                label = label or fd.long_name or variable
                units = units or fd.units
                long_name = long_name or fd.long_name
                ok_files += 1
            except Exception as exc:                    # noqa: BLE001
                bad_files.append((os.path.basename(path), str(exc)))
            finally:
                try:
                    src.close()
                except Exception:                       # noqa: BLE001
                    pass

        # —— 时间轴兜底：全都没有时间就退回序号 ——
        if src_kind is None:
            src_kind = "index"
        if all(np.isnat(np.datetime64(t)) for t in times):
            self.warnings.append("未能从文件或文件名识别时间，横轴改用样本序号")
            base = np.datetime64("1970-01-01", "s")
            times = [base + np.timedelta64(k, "D") for k in range(len(times))]
            src_kind = "index"

        if not values:
            raise NcSourceError("所有文件都没能取出数据（%d 个失败）"
                                % len(bad_files))
        if bad_files:
            self.warnings.append("%d 个文件被跳过" % len(bad_files))

        ts = TimeSeries(
            time=np.array(times, dtype="datetime64[s]"),
            values=np.array(values, dtype="float64"),
            label="%s %s" % (label or variable,
                             {"mean": "区域平均", "median": "区域中位数",
                              "max": "区域最大", "min": "区域最小",
                              "std": "区域标准差", "p90": "区域90分位",
                              "p10": "区域10分位"}.get(self.stat, "")),
            units=units, long_name=long_name, variable=variable,
            stat=self.stat, region=self.region, time_source=src_kind,
            meta={"n_files": len(self.paths), "n_ok": ok_files,
                  "n_bad": len(bad_files), "bad_files": bad_files[:20],
                  "warnings": list(self.warnings),
                  "point": self.point},
        ).sort()
        return ts

    # ------------------------------------------------------------------
    def _spatial_subset(self, fd, already_windowed: bool = False):
        """裁到指定区域/点，并按固定上限降采样（跨文件步长一致）。"""
        from .grid import coarsen_field, subset_bbox

        # ★ 先降采样再裁切：这样所有文件用的是同一个步长，
        #   各时次的空间权重完全一致，序列才可比。
        # 已经按窗口读过（区域与步长都定好了）就不用重复做。
        if self.max_cells > 0 and not already_windowed:
            fd = coarsen_field(fd, self.max_cells)

        if self.point is not None and fd.x is not None and fd.y is not None:
            lon, lat = float(self.point[0]), float(self.point[1])
            xi = int(np.argmin(np.abs(np.asarray(fd.x, dtype="float64") - lon)))
            yi = int(np.argmin(np.abs(np.asarray(fd.y, dtype="float64") - lat)))
            vals = fd.values[yi:yi + 1, xi:xi + 1]
            from .reader import FieldData
            return FieldData(
                name=fd.name, values=vals, x=fd.x[xi:xi + 1], y=fd.y[yi:yi + 1],
                x_name=fd.x_name, y_name=fd.y_name,
                x_role=fd.x_role, y_role=fd.y_role,
                long_name=fd.long_name, units=fd.units, dims=fd.dims,
                select=dict(fd.select), attrs=dict(fd.attrs))

        if self.region:
            fd = subset_bbox(fd, self.region)
        return fd

    # ------------------------------------------------------------------
    def _reduce(self, fd) -> float:
        """按 stat 在空间上归约成一个数（区域平均默认做 cos(纬度) 加权）。"""
        vals = np.asarray(fd.values, dtype="float64")
        if vals.ndim == 1:
            vals = vals[None, :]
        good = np.isfinite(vals)
        if not good.any():
            return float("nan")

        stat = self.stat
        if stat == "mean":
            w = self._weights(fd, vals.shape)
            w = np.where(good, w, 0.0)
            tot = w.sum()
            if tot <= 0:
                return float("nan")
            return float((np.where(good, vals, 0.0) * w).sum() / tot)

        v = vals[good]
        if stat == "median":
            return float(np.median(v))
        if stat == "max":
            return float(np.max(v))
        if stat == "min":
            return float(np.min(v))
        if stat == "std":
            return float(np.std(v, ddof=1)) if v.size > 1 else 0.0
        if stat == "p90":
            return float(np.percentile(v, 90))
        if stat == "p10":
            return float(np.percentile(v, 10))
        return float(np.mean(v))

    @staticmethod
    def _weights(fd, shape) -> np.ndarray:
        """cos(纬度) 面积权重；拿不到纬度就退化成等权。"""
        try:
            y = np.asarray(fd.y, dtype="float64").ravel()
            if y.size == shape[0] and fd.y_role is AxisRole.LAT:
                w = np.cos(np.deg2rad(y))
                w = np.clip(w, 1e-6, None)
                return np.repeat(w[:, None], shape[1], axis=1)
        except Exception:                               # noqa: BLE001
            pass
        return np.ones(shape, dtype="float64")
