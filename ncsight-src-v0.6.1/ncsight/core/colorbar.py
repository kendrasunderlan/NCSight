# -*- coding: utf-8 -*-
"""
色标（colorbar）外观系统
========================
matplotlib 默认的色标是一个带粗黑边框的方块，放在图右边、刻度朝外，
在论文插图里显得很"重"。这里把色标拆成「位置 + 样式 + 刻度 + 标注」
四组可调项，并提供几套开箱即用的样式。

样式一览（`ColorbarSpec.style`）：

===========  =====================================================
clean        **默认**。无边框、细灰刻度、小字号、单位并入标题，最轻盈
outline      极细浅灰边框，适合浅色背景上需要一点点边界感
framed       经典细黑边框，接受度最高的"教科书"外观
minimal      极简：只要色条和几根短刻度，不要任何框与刻度线
shadow       带一层柔和投影，屏幕展示/PPT 用
banded       每个色阶之间描一道白线，离散色阶时很有质感
===========  =====================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

#: 位置
LOCATIONS = [
    ("right", "右侧（默认）"),
    ("left", "左侧"),
    ("bottom", "底部（横向）"),
    ("top", "顶部（横向）"),
]

#: 样式名 → (中文名, 一句话说明)
STYLE_CATALOG: Dict[str, Tuple[str, str]] = {
    "clean":   ("简洁（推荐）", "无边框、细灰刻度、单位并入标注"),
    "outline": ("细边框", "极细浅灰描边，浅色图上更有边界感"),
    "framed":  ("经典带框", "细黑边框，教科书式观感"),
    "minimal": ("极简", "只有色条与短刻度，无框无线"),
    "shadow":  ("投影", "带柔和投影，适合 PPT / 屏幕展示"),
    "banded":  ("分阶描边", "色阶之间描白线，离散色阶时质感好"),
}

#: 每个样式的具体绘制参数
STYLE_PARAMS: Dict[str, dict] = {
    "clean": dict(
        outline=0.0, outline_color="#d1d5db",
        tick_len=2.6, tick_w=0.55, tick_color="#6b7280",
        tick_size=1.0, label_size=1.0,
        extendfrac=0.035, extend_hatch=None,
    ),
    "outline": dict(
        outline=0.5, outline_color="#cbd5e1",
        tick_len=3.0, tick_w=0.6, tick_color="#475569",
        tick_size=1.0, label_size=1.0,
        extendfrac=0.040, extend_hatch=None,
    ),
    "framed": dict(
        outline=0.7, outline_color="#111827",
        tick_len=3.4, tick_w=0.7, tick_color="#111827",
        tick_size=1.0, label_size=1.0,
        extendfrac=0.045, extend_hatch=None,
    ),
    "minimal": dict(
        outline=0.0, outline_color="#e5e7eb",
        tick_len=0.0, tick_w=0.0, tick_color="#9ca3af",
        tick_size=0.95, label_size=1.0,
        extendfrac=0.0, extend_hatch=None,
    ),
    "shadow": dict(
        outline=0.4, outline_color="#94a3b8",
        tick_len=3.0, tick_w=0.6, tick_color="#475569",
        tick_size=1.0, label_size=1.0,
        extendfrac=0.040, extend_hatch=None,
        shadow=dict(dx=1.6, dy=-1.6, alpha=0.18),
    ),
    "banded": dict(
        outline=0.5, outline_color="#9ca3af",
        tick_len=3.0, tick_w=0.6, tick_color="#475569",
        tick_size=1.0, label_size=1.0,
        extendfrac=0.040, extend_hatch=None,
        band_color="#ffffff", band_width=0.7,
    ),
}

#: 刻度格式
TICK_FORMATS = [
    ("auto", "自动"),
    ("g", "紧凑（1.2k / 3.4M）"),
    ("fixed1", "一位小数"),
    ("fixed2", "两位小数"),
    ("fixed3", "三位小数"),
    ("sci", "科学计数法"),
    ("percent", "百分比"),
]

#: 越界三角
EXTEND_MODES = [
    ("auto", "自动（数据超出范围时加）"),
    ("both", "两端都加"),
    ("neither", "两端都不加"),
    ("max", "只加上端"),
    ("min", "只加下端"),
]


@dataclass
class ColorbarSpec:
    """色标外观的全部可调项。"""

    #: 空字符串 = 沿用 PlotSpec.colorbar_location（向后兼容）
    location: str = ""
    style: str = "clean"

    # ---------- 尺寸与间距 ----------
    width: float = 0.032            # 占坐标轴宽/高的比例
    pad: float = 0.022              # 与图之间的间距
    aspect: int = 24                # 长宽比（越大越细长）
    shrink: float = 1.0             # 长度缩放

    # ---------- 越界 ----------
    extend: str = "auto"
    extendfrac: float = 0.0         # 0 = 用样式默认值

    # ---------- 刻度 ----------
    nticks: int = 0                 # 0 = 自动
    tick_format: str = "auto"
    tick_side: str = "out"          # out / in
    tick_values: Optional[List[float]] = None

    # ---------- 标注 ----------
    label: str = ""                 # 空 = 用变量的 caption
    label_position: str = "auto"    # auto / bottom / top / side / none
    label_rotate: bool = False      # 纵向旋转（竖排列名称）
    fontsize: float = 0.0           # 0 = 跟随主题

    # ---------- 其它 ----------
    tick_size_scale: float = 1.0    # 刻度字号倍数
    outline_width: float = -1.0     # <0 = 用样式默认值
    opaque: bool = False            # 是否给色条加深色背景


# ----------------------------------------------------------------------
# 中文标题的拆分：把 "Sea Surface Temperature [degree_C]" 拆成
# 标题 + 单位，样式 clean 会把单位并进标题、不再单独占位
# ----------------------------------------------------------------------
_UNIT_RE = None


def split_label(label: str) -> Tuple[str, str]:
    """把 '名称 [单位]' 拆成 (名称, 单位)。"""
    if not label:
        return "", ""
    s = label.strip()
    for open_c, close_c in (("[", "]"), ("(", ")"), ("（", "）")):
        i, j = s.rfind(open_c), s.rfind(close_c)
        if 0 <= i < j == len(s) - 1:
            return s[:i].strip(), s[i + 1:j].strip()
    return s, ""


def style_params(style: str) -> dict:
    return dict(STYLE_PARAMS.get(style) or STYLE_PARAMS["clean"])


def location_of(spec, cb: ColorbarSpec) -> str:
    """兼容旧字段：ColorbarSpec.location 为空时用 PlotSpec.colorbar_location。"""
    loc = cb.location or getattr(spec, "colorbar_location", "") or "right"
    return loc if loc in ("right", "left", "top", "bottom") else "right"


def resolve_extend(spec, cb: ColorbarSpec, vmin: float, vmax: float,
                   data) -> str:
    """
    决定是否画越界三角。

    默认 `auto`：只有当数据真的超出色标范围时才加 —— 这样既不会莫名其妙
    多出两个尖角，又不会把超出范围的值悄悄丢掉（用户看到三角就知道有越界）。
    """
    mode = (cb.extend or "auto").lower()
    if mode != "auto":
        return mode if mode in ("both", "neither", "max", "min") else "neither"
    try:
        v = np.asarray(data, dtype="float64").ravel()
        v = v[np.isfinite(v)]
        if v.size == 0:
            return "neither"
        below = bool(np.any(v < vmin))
        above = bool(np.any(v > vmax))
    except Exception:                                   # noqa: BLE001
        return "neither"
    if below and above:
        return "both"
    if above:
        return "max"
    if below:
        return "min"
    return "neither"


def build_tick_formatter(cb: ColorbarSpec):
    """按 tick_format 返回一个刻度格式化函数（或 None 表示交给 matplotlib）。"""
    from matplotlib.ticker import (FormatStrFormatter, FuncFormatter,
                                   ScalarFormatter)

    fmt = (cb.tick_format or "auto").lower()
    if fmt == "auto":
        return None
    if fmt in ("g",):
        def _g(x, _pos=None):
            try:
                return "%g" % float(x)
            except Exception:                           # noqa: BLE001
                return str(x)
        return FuncFormatter(_g)
    if fmt == "fixed1":
        return FormatStrFormatter("%.1f")
    if fmt == "fixed2":
        return FormatStrFormatter("%.2f")
    if fmt == "fixed3":
        return FormatStrFormatter("%.3f")
    if fmt == "sci":
        sf = ScalarFormatter(useMathText=True)
        sf.set_powerlimits((0, 0))
        return sf
    if fmt == "percent":
        def _p(x, _pos=None):
            try:
                return "%g%%" % (float(x) * 100.0)
            except Exception:                           # noqa: BLE001
                return str(x)
        return FuncFormatter(_p)
    return None
