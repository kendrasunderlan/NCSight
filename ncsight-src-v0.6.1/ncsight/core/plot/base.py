# -*- coding: utf-8 -*-
"""
绘图规格（PlotSpec）与渲染调度
==============================
对应 Panoply 的 `PanPlotMeta` / `PanSavedSettings`。

**这是整个软件最重要的设计。**
一个 PlotSpec 完整描述「一张图长什么样」，并且可以无损序列化成 YAML/JSON。
好处：
  * 命令行一条命令就能重画同一张图（Panoply 的 Export CL Script 想要的效果）
  * GUI 里的一切操作都归结为「改 PlotSpec → 重渲染」
  * 出图脚本可以进版本管理，图随代码可复现
  * 批量出图 = 遍历一批 PlotSpec

渲染入口只有一个：`render(spec, source)`。
"""

from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ncsight import style
from .. import colorbar as colorbar_mod
from ..colorbar import ColorbarSpec
from ..colormap import resolve_colormap, binned, make_norm
from ..overlay import OverlaySpec
from ..reader import NcSource, FieldData


# --------------------------------------------------------------------------
# 规格
# --------------------------------------------------------------------------
PLOT_KINDS: Dict[str, str] = {
    "map": "经纬度地图",
    "vector": "矢量场（风/流）",
    "line": "折线 / 时间序列",
    "hovmoller": "Hovmöller 时间-经度/纬度",
    "section": "垂直剖面",
    "zonal": "纬向平均廓线",
    # —— 多文件时序（数据源是一批 nc 文件，不是单个数据集）——
    "series": "时序曲线（多文件）",
    "spectrum": "功率谱（多文件）",
}

PROJECTIONS: List[Tuple[str, str]] = [
    ("PlateCarree", "等距圆柱（经纬度）"),
    ("Robinson", "Robinson"),
    ("Mollweide", "Mollweide"),
    ("EqualEarth", "Equal Earth"),
    ("Orthographic", "正射（从太空看）"),
    ("NorthPolarStereo", "北极立体"),
    ("SouthPolarStereo", "南极立体"),
    ("Mercator", "墨卡托"),
    ("LambertConformal", "兰勃特等角圆锥"),
    ("AlbersEqualArea", "阿尔伯斯等积圆锥"),
    ("RotatedPole", "旋转极点"),
    ("TransverseMercator", "横轴墨卡托"),
    ("UTM", "UTM 通用横轴墨卡托"),
]

COLORBAR_LOCATIONS = [
    ("right", "右侧"), ("left", "左侧"),
    ("bottom", "下方"), ("top", "上方"),
]


@dataclass
class PlotSpec:
    """一张图的完整描述。可序列化、可比较、可版本管理。"""

    # ---------- 数据选择 ----------
    kind: str = "map"
    variable: str = ""
    select: Dict[str, Any] = field(default_factory=dict)   # 维度名 -> 索引或 "min"/"max"/"mean"
    bbox: Optional[List[float]] = None                     # [lon_min, lon_max, lat_min, lat_max]
    time_index: int = 0

    # ---------- 色标 ----------
    cmap: str = "auto"
    table_path: Optional[str] = None
    vmin: Optional[float] = None
    vmax: Optional[float] = None
    nbins: int = 21
    discrete: bool = True
    reverse: bool = False
    log: bool = False
    center_zero: bool = False
    show_colorbar: bool = True
    colorbar_location: str = "right"
    colorbar_label: Optional[str] = None
    colorbar_ticks: Optional[List[float]] = None
    #: 色标外观（样式 / 尺寸 / 刻度 / 越界三角 / 标注位置）
    colorbar: ColorbarSpec = field(default_factory=ColorbarSpec)

    # ---------- 时序 / 多文件 ----------
    #: 要统计的变量（留空 = 用 variable）
    series_variable: str = ""
    #: 空间统计方式：mean / median / max / min / std / p90 / p10
    series_stat: str = "mean"
    #: 单点取值 (lon, lat)，给了就优先于 bbox
    series_point: Optional[Tuple[float, float]] = None
    #: 要计算的科学指标（见 core/indicators.py 的 INDICATOR_CATALOG）
    indicators: List[str] = field(default_factory=list)

    # ---------- 地图 ----------
    projection: str = "PlateCarree"
    lon0: float = 0.0
    lat0: float = 0.0
    overlays: OverlaySpec = field(default_factory=OverlaySpec)
    show_grid: bool = True
    grid_dx: Optional[float] = None
    grid_dy: Optional[float] = None
    grid_labels: bool = True
    show_contours: bool = False
    contour_levels: int = 8
    contour_labels: bool = True
    max_cells: int = 1_500_000              # 投影前的降采样上限

    # ---------- 性能 ----------
    #: 屏幕显示的格点上限（0 = 不限制，用全分辨率）。
    #:
    #: ★ 这是交互流畅与否的关键 ★
    #: 实测：一张 4320x8640 的全球场有 3732 万个格点，光 pcolormesh 建网格就要
    #: **13.4 秒**；降到 58 万格点只要 **0.25 秒**（53 倍）。而屏幕上根本画不出
    #: 那么细的细节 —— 一个 850x500 的画布只有 42 万个像素。
    #: 所以界面渲染时把它设成「画布像素数」，而导出/命令行保持 0（全分辨率），
    #: 做到「屏幕快、导出真」。
    screen_cells: int = 0

    # ---------- 矢量场 ----------
    vector_variable: str = ""
    vector_step: int = 18
    vector_scale: Optional[float] = None
    vector_color: str = "#374151"
    vector_width: float = 0.7
    vector_units_scale: float = 1.0

    # ---------- 掩膜 / 数据筛选（M3 科研增强）----------
    mask_land: bool = False                 # 抹掉陆地，只留海洋
    mask_polygon: Optional[List[List[float]]] = None    # [[lon,lat], ...]
    mask_shapefile: Optional[str] = None
    mask_range: Optional[List[float]] = None            # [vmin, vmax] 只保留区间内
    quality_var: Optional[str] = None       # 质量标记变量名，如 qual_sst
    quality_accept: str = "0:2"             # 接受的质量等级

    # ---------- 一维图 ----------
    xlog: bool = False
    ylog: bool = False
    marker: bool = False
    line_color: Optional[str] = None
    line_width: float = 1.2
    invert_y: bool = False                  # 垂向剖面常用（深度向下）

    # ---------- 版式 ----------
    title: Optional[str] = None
    subtitle: Optional[str] = None
    preset: str = "double"
    figsize: Optional[List[float]] = None
    dpi: int = 150
    fontsize: float = 9.0
    xlabel: Optional[str] = None
    ylabel: Optional[str] = None
    show_stats: bool = False                # 图上标注 min/max/mean

    # ---------- 导出 ----------
    outfile: Optional[str] = None

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return _clean(asdict(self))

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PlotSpec":
        d = dict(d or {})
        ov = d.pop("overlays", None)
        cb = d.pop("colorbar", None)
        params = {f.name for f in dataclasses.fields(cls)}
        unknown = set(d) - params
        kw = {k: v for k, v in d.items() if k in params}
        spec = cls(**kw)
        if isinstance(ov, dict):
            ov_params = {f.name for f in dataclasses.fields(OverlaySpec)}
            spec.overlays = OverlaySpec(**{k: v for k, v in ov.items() if k in ov_params})
        if isinstance(cb, dict):
            cb_params = {f.name for f in dataclasses.fields(ColorbarSpec)}
            spec.colorbar = ColorbarSpec(**{k: v for k, v in cb.items()
                                            if k in cb_params})
        if unknown:
            spec._unknown = sorted(unknown)          # type: ignore[attr-defined]
        return spec


    def clone(self, **changes) -> "PlotSpec":
        d = self.to_dict()
        d.update(changes)
        return PlotSpec.from_dict(d)

    def update(self, **changes) -> "PlotSpec":
        for k, v in changes.items():
            if hasattr(self, k):
                setattr(self, k, v)
        return self

    def save(self, path: str) -> str:
        path = _ensure_ext(path, ".yaml")
        _dump_yaml(self.to_dict(), path)
        return path

    @classmethod
    def load(cls, path: str) -> "PlotSpec":
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            import yaml
            data = yaml.safe_load(text)
        return cls.from_dict(data or {})


# --------------------------------------------------------------------------
# 渲染结果
# --------------------------------------------------------------------------
@dataclass
class RenderResult:
    fig: Any
    ax: Any
    spec: PlotSpec
    data: Optional[FieldData] = None
    mappable: Any = None
    #: 时序渲染时才有：序列本身与算出的指标
    series: Any = None
    indicators: List[Any] = field(default_factory=list)

    def save(self, path: Optional[str] = None, **kw) -> str:
        path = path or self.spec.outfile or "ncsight.png"
        path = os.path.abspath(path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.fig.savefig(path, **kw)
        return path


# --------------------------------------------------------------------------
# 渲染调度
# --------------------------------------------------------------------------
def resolve_kind(spec: PlotSpec, source) -> str:
    """若 spec.kind 为空或与数据不匹配，自动挑一个合适的图型。"""
    kind = (spec.kind or "").strip().lower()

    # 时序/谱：数据源是一批文件或一条序列，不依赖单个 NcSource 的变量表
    if kind in ("series", "spectrum"):
        return kind
    if source is None or not hasattr(source, "variables"):
        return kind or "map"

    vi = source.variables.get(spec.variable)
    if vi is None:
        return kind or "map"
    from ..detect import PLOT_OPTIONS
    options = PLOT_OPTIONS.get(vi.kind, ["line"])
    if kind and kind in options:
        return kind
    return options[0] if options else "line"



def compute_range(data: FieldData, spec: PlotSpec) -> Tuple[float, float]:
    """决定色标范围：用户指定 > 数据自带建议 > 稳健分位数。"""
    vmin, vmax = spec.vmin, spec.vmax
    if vmin is not None and vmax is not None:
        return float(vmin), float(vmax)

    hint = None
    sr = data.attrs.get("display_min"), data.attrs.get("display_max")
    if sr[0] is not None and sr[1] is not None:
        try:
            hint = (float(sr[0]), float(sr[1]))
        except (TypeError, ValueError):
            hint = None
    if hint is None:
        v = data.values
        v = v[np.isfinite(v)]
        if v.size:
            lo, hi = float(np.percentile(v, 1)), float(np.percentile(v, 99))
            if hi <= lo:
                hi = lo + 1.0
            hint = (lo, hi)
        else:
            hint = (0.0, 1.0)

    if vmin is None:
        vmin = hint[0]
    if vmax is None:
        vmax = hint[1]
    if vmax <= vmin:
        vmax = vmin + 1.0
    return float(vmin), float(vmax)


def make_cmap_norm(data: FieldData, spec: PlotSpec,
                   palette_array=None) -> Tuple[Any, Any, Tuple[float, float]]:
    vmin, vmax = compute_range(data, spec)
    base = resolve_colormap(spec.cmap or "auto",
                            palette_array=palette_array,
                            table_path=spec.table_path,
                            reverse=spec.reverse)
    if spec.discrete and not spec.log:
        cmap = binned(base, spec.nbins)
    else:
        cmap = base
    norm = make_norm(vmin, vmax, spec.nbins, log=spec.log,
                     center_zero=spec.center_zero, discrete=spec.discrete and not spec.log)
    return cmap, norm, (vmin, vmax)


def render(spec: PlotSpec, source,
           fig=None, ax=None) -> RenderResult:
    """
    唯一渲染入口。根据 spec.kind 分发到具体图型模块。

    `source` 的形态随图型而定：
      * 地图 / 剖面 / Hovmöller / 折线 → 一个 `NcSource`
      * 时序 / 功率谱 → 文件路径列表，或一条已构建好的 `TimeSeries`
    """
    kind = resolve_kind(spec, source)

    # 时序 / 功率谱走独立路径：它的「数据源」是一批文件或一条已构建的序列，
    # 而不是单个 NcSource（也没有 variables 表可以查），所以最先分流。
    if kind in ("series", "spectrum"):
        from . import series_plot
        return series_plot.render(spec, source, fig=fig, ax=ax)

    style.apply_theme(base_fontsize=spec.fontsize)

    if not spec.variable:
        # 用「主变量」启发式，而不是简单取第一个 ——
        # 否则 L3 产品一打开就是 qual_sst（质量标记）而不是 sst。
        try:
            primary = source.primary_field()
        except Exception:                               # noqa: BLE001
            primary = None
        if primary is None:
            raise ValueError("数据集中没有可制图的变量")
        spec.variable = primary.name

    if kind == "map":
        from . import map_plot
        return map_plot.render(spec, source, fig=fig, ax=ax)

    if kind == "vector":
        from . import vector
        return vector.render(spec, source, fig=fig, ax=ax)
    if kind == "hovmoller":
        from . import hovmoller
        return hovmoller.render(spec, source, fig=fig, ax=ax)
    if kind == "section":
        from . import section
        return section.render(spec, source, fig=fig, ax=ax)
    if kind == "zonal":
        from . import line_plot
        return line_plot.render_zonal(spec, source, fig=fig, ax=ax)
    from . import line_plot
    return line_plot.render(spec, source, fig=fig, ax=ax)


# --------------------------------------------------------------------------
# 公共工具（各图型模块共用）
# --------------------------------------------------------------------------
def get_palette_array(source: NcSource):
    """取 nc 文件内嵌的 palette 变量（若有）。"""
    for name in ("palette", "Palette", "pal"):
        if name in source.ds.variables:
            try:
                arr = np.asarray(source.ds.variables[name][:])
                if arr.ndim == 2 and arr.shape[0] == 3:
                    return arr
            except Exception:                           # noqa: BLE001
                continue
    return None


def prepare_field(fd: FieldData, spec: PlotSpec) -> FieldData:
    """
    出图前的数据准备：按 `screen_cells` 做屏幕降采样。

    只在 screen_cells > 0 时生效（GUI 会把它设成画布像素数）；
    命令行与导出保持 0，因此拿到的是全分辨率结果。
    """
    limit = int(spec.screen_cells or 0)
    if limit <= 0:
        return fd
    try:
        ny, nx = fd.values.shape
    except (AttributeError, ValueError):
        return fd
    # 只处理真正的二维平面。折线/剖面这类数据在内部是 (1, N) 或 (N, 1)，
    # 对它们抽样会把点丢掉（曲线会变形），必须跳过。
    if ny <= 1 or nx <= 1:
        return fd
    if ny * nx <= limit:
        return fd
    from ..grid import coarsen_field
    return coarsen_field(fd, limit)


def attach_colorbar(fig, ax, mappable, spec: PlotSpec, label: str = "",
                    ticks=None) -> Optional[Any]:
    """
    画色标。外观由 `spec.colorbar`（ColorbarSpec）控制，见 core/colorbar.py。

    这里做了三件事让色标「好看」：
      1. 越界三角默认按数据是否真的越界决定（auto），不再无脑两端加尖角
      2. 把 "名称 [单位]" 拆开，样式 clean 下单位并入标注，少一行字
      3. 按样式设置边框/刻度线/刻度字色，而不是 matplotlib 的粗黑默认值
    """
    if not spec.show_colorbar or mappable is None:
        return None

    cb = getattr(spec, "colorbar", None) or ColorbarSpec()
    sp = colorbar_mod.style_params(cb.style)

    loc = colorbar_mod.location_of(spec, cb)
    orientation = "horizontal" if loc in ("top", "bottom") else "vertical"

    # ---- 越界三角 ----
    try:
        norm = getattr(mappable, "norm", None)
        vmin = float(getattr(norm, "vmin", 0.0))
        vmax = float(getattr(norm, "vmax", 1.0))
        data = getattr(mappable, "get_array", lambda: None)()
        extend = colorbar_mod.resolve_extend(spec, cb, vmin, vmax, data)
    except Exception:                                   # noqa: BLE001
        extend = "neither"

    extendfrac = cb.extendfrac or sp.get("extendfrac") or 0.04
    kw = dict(orientation=orientation,
              pad=max(0.005, cb.pad),
              shrink=max(0.05, min(1.0, cb.shrink)),
              aspect=cb.aspect,
              extend=extend,
              extendfrac=extendfrac)
    if orientation == "vertical":
        kw["fraction"] = max(0.008, cb.width)
    else:
        kw["fraction"] = max(0.02, cb.width * 1.6)
    if loc in ("left", "top"):
        kw["location"] = loc

    try:
        cbar = fig.colorbar(mappable, ax=ax, **kw)
    except Exception:                                   # noqa: BLE001
        return None

    # ---- 刻度 ----
    base_fs = spec.fontsize or 9.0
    tick_fs = base_fs * sp.get("tick_size", 1.0) * (cb.tick_size_scale or 1.0)
    cbar.ax.tick_params(
        labelsize=max(5.0, tick_fs),
        length=sp.get("tick_len", 2.6) * (1.6 if cb.tick_side == "in" else 1.0),
        width=sp.get("tick_w", 0.6),
        colors=sp.get("tick_color", "#6b7280"),
        direction="in" if cb.tick_side == "in" else "out",
    )
    if sp.get("tick_len", 1) <= 0:
        cbar.ax.tick_params(length=0.0)
    fmt = colorbar_mod.build_tick_formatter(cb)
    if fmt is not None:
        cbar.ax.yaxis.set_major_formatter(fmt)
        cbar.ax.xaxis.set_major_formatter(fmt)
    vals = cb.tick_values if cb.tick_values else (ticks or spec.colorbar_ticks)
    if vals:
        try:
            cbar.set_ticks(list(vals))
        except Exception:                               # noqa: BLE001
            pass
    elif cb.nticks and cb.nticks > 1:
        try:
            bounds = np.asarray(cbar.get_ticks())
            lo = float(getattr(mappable.norm, "vmin", bounds.min()))
            hi = float(getattr(mappable.norm, "vmax", bounds.max()))
            cbar.set_ticks(np.linspace(lo, hi, int(cb.nticks)))
        except Exception:                               # noqa: BLE001
            pass

    # ---- 标注 ----
    raw = cb.label or label or ""
    name, unit = colorbar_mod.split_label(raw)
    pos = cb.label_position or "auto"
    if pos == "auto":
        # 竖色标写在下方居中（比侧着读更省事）；横色标写在右边
        pos = "right" if orientation == "horizontal" else "bottom"
    if raw and pos != "none":
        txt = name
        if unit and cb.style in ("clean", "outline", "minimal"):
            txt = "%s / %s" % (name, unit) if name else unit
        elif unit:
            txt = raw
        lfs = cb.fontsize or max(6.8, base_fs - 0.4)
        try:
            if pos == "bottom":
                cbar.ax.set_title("") if orientation == "vertical" else None
                cbar.ax.set_xlabel(txt, fontsize=lfs,
                                   color=style.COLORS["text"], labelpad=3)
                if orientation == "vertical":
                    cbar.set_label("")
                    cbar.ax.xaxis.set_label_position("bottom")
                    cbar.ax.xaxis.tick_top()
                    cbar.ax.set_xlabel(txt, fontsize=lfs,
                                       color=style.COLORS["text"], labelpad=3)
            elif pos == "top":
                cbar.ax.set_xlabel("")
                cbar.ax.set_title(txt, fontsize=lfs,
                                  color=style.COLORS["text"], pad=4)
            else:
                rot = 90 if orientation == "horizontal" else 270
                if cb.label_rotate:
                    cbar.set_label(txt, fontsize=lfs,
                                   rotation=rot if orientation == "horizontal" else 90,
                                   color=style.COLORS["text"], labelpad=7)
                else:
                    cbar.set_label(txt, fontsize=lfs,
                                   color=style.COLORS["text"], labelpad=6)
        except Exception:                               # noqa: BLE001
            try:
                cbar.set_label(txt, fontsize=lfs)
            except Exception:                           # noqa: BLE001
                pass

    # ---- 边框 / 装饰 ----
    ow = cb.outline_width if cb.outline_width >= 0 else sp.get("outline", 0.0)
    try:
        if ow and ow > 0:
            cbar.outline.set_linewidth(ow)
            cbar.outline.set_edgecolor(sp.get("outline_color", "#d1d5db"))
        else:
            cbar.outline.set_visible(False)
    except Exception:                                   # noqa: BLE001
        pass

    # 分阶描边：每个色阶之间画一道白线
    if cb.style == "banded":
        try:
            bc = sp.get("band_color", "#ffffff")
            bw = sp.get("band_width", 0.7)
            n = int(getattr(cbar.mappable.cmap, "N", 0) or 0)
            bounds = getattr(cbar.mappable.norm, "boundaries", None)
            if bounds is not None:
                for b in np.asarray(bounds)[1:-1]:
                    if orientation == "vertical":
                        cbar.ax.axhline(b, color=bc, linewidth=bw, zorder=5)
                    else:
                        cbar.ax.axvline(b, color=bc, linewidth=bw, zorder=5)
            elif n:
                import matplotlib.colors as mcolors
                lo = float(getattr(cbar.mappable.norm, "vmin", 0.0))
                hi = float(getattr(cbar.mappable.norm, "vmax", 1.0))
                for b in np.linspace(lo, hi, n + 1)[1:-1]:
                    if orientation == "vertical":
                        cbar.ax.axhline(b, color=bc, linewidth=bw, zorder=5)
                    else:
                        cbar.ax.axvline(b, color=bc, linewidth=bw, zorder=5)
        except Exception:                               # noqa: BLE001
            pass

    # 投影
    sh = sp.get("shadow")
    if sh:
        try:
            from matplotlib.patches import FancyBboxPatch
            from matplotlib.transforms import ScaledTranslation
            cbar.ax.patch.set_visible(False)
            bb = cbar.ax.get_position()
            pad = 0.012
            shp = FancyBboxPatch(
                (-pad, -pad), 1 + 2 * pad, 1 + 2 * pad,
                boxstyle="round,pad=0.0,rounding_size=0.02",
                transform=cbar.ax.transAxes, facecolor="#0f172a",
                edgecolor="none", alpha=sh.get("alpha", 0.18),
                zorder=0, clip_on=False)
            cbar.ax.add_patch(shp)
            shp.set_transform(cbar.ax.transAxes + ScaledTranslation(
                sh.get("dx", 1.6) / 72.0, sh.get("dy", -1.6) / 72.0,
                fig.dpi_scale_trans))
        except Exception:                               # noqa: BLE001
            pass

    if cb.opaque:
        try:
            cbar.ax.set_facecolor("#ffffff")
        except Exception:                               # noqa: BLE001
            pass
    return cbar

    return cbar


def stats_annotation(data: FieldData) -> str:
    s = data.stats()
    if not s.get("n"):
        return "无有效数据"
    return ("n=%d\nmin=%.4g\nmax=%.4g\nmean=%.4g\nstd=%.4g"
            % (s["n"], s["min"], s["max"], s["mean"], s["std"]))


def apply_labels(ax, spec: PlotSpec, data: Optional[FieldData] = None,
                 default_xlabel: str = "", default_ylabel: str = "") -> None:
    ax.set_xlabel(spec.xlabel or default_xlabel)
    ax.set_ylabel(spec.ylabel or default_ylabel)
    title = spec.title
    if title is None and data is not None:
        title = data.caption
    if title:
        ax.set_title(title, loc="left")
    if spec.subtitle:
        ax.text(0.0, 1.02, spec.subtitle, transform=ax.transAxes,
                ha="left", va="bottom", fontsize=max(6.5, spec.fontsize - 1.5),
                color=style.COLORS["fg_muted"])


def make_figure(spec: PlotSpec):
    figsize = tuple(spec.figsize) if spec.figsize else style.figure_preset(spec.preset)
    return style.new_figure(figsize=figsize, dpi=spec.dpi)


# --------------------------------------------------------------------------
# 内部：序列化辅助
# --------------------------------------------------------------------------
def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _ensure_ext(path: str, ext: str) -> str:
    return path if path.lower().endswith(ext) else path + ext


def _dump_yaml(data: dict, path: str) -> None:
    try:
        import yaml
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                              default_flow_style=False)
    except Exception:                                   # noqa: BLE001
        text = json.dumps(data, ensure_ascii=False, indent=2)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
