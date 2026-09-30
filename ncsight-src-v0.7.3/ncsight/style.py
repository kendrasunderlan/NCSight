# -*- coding: utf-8 -*-
"""
绘图主题：简约白色风格
=====================
统一所有出图的视觉规范：白底、细线、小字号、克制的配色。
目标是「直接能插进论文」的观感，而不是花哨。

中文字体在这里统一处理——matplotlib 默认不含中文字体，
不设的话所有中文标题都会变成方框。
"""

from __future__ import annotations

import os
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")          # 默认无界面后端；GUI 会自行切到 Qt 后端
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams

# --------------------------------------------------------------------------
# 白色简约配色令牌
# --------------------------------------------------------------------------
COLORS = {
    "bg": "#ffffff",
    "fg": "#1f2937",           # 主文字（近黑，不用纯黑，更柔和）
    "fg_muted": "#6b7280",     # 次要文字
    "grid": "#e5e7eb",         # 网格线（很浅）
    "spine": "#d1d5db",        # 坐标轴框线
    "accent": "#2563eb",       # 强调色（界面与高亮）
    "accent_soft": "#eff6ff",
    "land": "#f5f5f4",
    "ocean": "#f8fafc",
    "coastline": "#3f3f46",
    "bad": "#dc2626",
}

# 界面用中性色（GUI 也复用这一套，保证图与界面观感一致）
UI = {
    "window": "#ffffff",
    "panel": "#fafafa",
    "panel_alt": "#f4f4f5",
    "border": "#e4e4e7",
    "border_strong": "#d4d4d8",
    "text": "#18181b",
    "text_muted": "#71717a",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "accent_soft": "#eff6ff",
    "ok": "#16a34a",
    "warn": "#d97706",
    "bad": "#dc2626",
}

FONT_CANDIDATES = [
    "Microsoft YaHei", "微软雅黑", "MSYH",
    "Source Han Sans SC", "Noto Sans CJK SC", "Noto Sans SC",
    "PingFang SC", "Hiragino Sans GB",
    "SimHei", "黑体",
    "WenQuanYi Micro Hei", "DejaVu Sans",
]


def available_cjk_font() -> Optional[str]:
    """找出本机第一个可用的中文字体。"""
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in FONT_CANDIDATES:
        if name in installed:
            return name
    return None


#: 记录上一次应用主题的参数，避免重复写全局 rcParams。
#: 这不只是省时间 —— 渲染跑在工作线程里，而 rcParams 是**全局可变状态**，
#: 每次渲染都去改它、主线程又在读它，理论上会打架。参数没变就直接返回，
#: 实际运行中几乎不会真的在渲染时改到它。
_APPLIED_KEY = None
_CJK_FONT = None


def apply_theme(base_fontsize: float = 9.0,
                cjk_font: Optional[str] = None,
                use_latex: bool = False,
                force: bool = False) -> Optional[str]:
    """
    应用白色简约主题。返回实际使用的中文字体名（可能为 None）。

    幂等：相同参数重复调用会直接返回，不再改写全局 rcParams。
    """
    global _APPLIED_KEY, _CJK_FONT

    key = (round(float(base_fontsize), 2), cjk_font, bool(use_latex))
    if not force and _APPLIED_KEY == key:
        return _CJK_FONT

    font = cjk_font or available_cjk_font()

    params = {
        # 画布
        "figure.facecolor": COLORS["bg"],
        "figure.edgecolor": COLORS["bg"],
        "figure.dpi": 110,
        "savefig.facecolor": COLORS["bg"],
        "savefig.edgecolor": COLORS["bg"],
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.08,

        # 坐标轴
        "axes.facecolor": COLORS["bg"],
        "axes.edgecolor": COLORS["spine"],
        "axes.linewidth": 0.7,
        "axes.labelcolor": COLORS["fg"],
        "axes.labelsize": base_fontsize,
        "axes.titlesize": base_fontsize + 2,
        "axes.titleweight": "normal",
        "axes.titlelocation": "left",
        "axes.titlepad": 8,
        "axes.grid": False,
        "axes.axisbelow": True,
        "axes.spines.top": False,
        "axes.spines.right": False,

        # 刻度
        "xtick.color": COLORS["fg_muted"],
        "ytick.color": COLORS["fg_muted"],
        "xtick.labelsize": base_fontsize - 0.5,
        "ytick.labelsize": base_fontsize - 0.5,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "xtick.major.width": 0.7,
        "ytick.major.width": 0.7,
        "xtick.major.size": 3.0,
        "ytick.major.size": 3.0,
        "xtick.minor.size": 1.6,
        "ytick.minor.size": 1.6,

        # 网格（默认关闭，需要时在图上开，且用很浅的灰）
        "grid.color": COLORS["grid"],
        "grid.linewidth": 0.5,
        "grid.alpha": 0.9,

        # 线
        "lines.linewidth": 1.1,
        "lines.markersize": 3.5,
        "lines.solid_capstyle": "round",
        "patch.linewidth": 0.6,

        # 图例
        "legend.frameon": False,
        "legend.fontsize": base_fontsize - 0.5,
        "legend.handlelength": 1.6,
        "legend.borderpad": 0.3,
        "legend.labelspacing": 0.35,

        # 色标（outline 的线宽/颜色不是 rcParam，改在 attach_colorbar 里设）

        # 等值线
        "contour.negative_linestyle": "dashed",
        "contour.linewidth": 0.7,

        # 字体
        "font.size": base_fontsize,
        "font.family": "sans-serif",
        "font.sans-serif": ([font] if font else []) + FONT_CANDIDATES,
        "axes.unicode_minus": False,     # 中文字体下负号会变方框，必须关
        "mathtext.fontset": "dejavusans",
        "pdf.fonttype": 42,              # 投稿要求：字体嵌入且可编辑
        "ps.fonttype": 42,
        "svg.fonttype": "none",          # SVG 里文字保持为文字，可编辑
    }

    # 只设置当前 matplotlib 版本真正支持的参数，保证跨版本可用
    valid = set(rcParams.keys())
    rcParams.update({k: v for k, v in params.items() if k in valid})

    if use_latex:
        try:
            rcParams["text.usetex"] = True
            rcParams["font.family"] = "serif"
        except Exception:                               # noqa: BLE001
            pass

    _APPLIED_KEY = key
    _CJK_FONT = font
    return font


# --------------------------------------------------------------------------
# 期刊常用的图幅预设（对应 Panoply 的 Plot Size 那一堆档位，但更实用）
# --------------------------------------------------------------------------
CM_PER_INCH = 2.54

FIGURE_PRESETS = {
    "single":      (8.3, 6.0),    # 单栏（GRL/JGR 单栏 8.3 cm 宽）
    "single_wide": (8.3, 5.0),
    "double":      (17.1, 10.0),  # 双栏（17.1 cm 宽）
    "double_wide": (17.1, 8.0),
    "square":      (12.0, 12.0),
    "slide":       (10.0, 5.6),   # 16:9 汇报用
    "a4_land":     (27.7, 19.0),
}

FIGURE_PRESET_LABELS = {
    "single": "单栏 8.3 cm（论文）",
    "single_wide": "单栏宽扁 8.3 cm",
    "double": "双栏 17.1 cm（论文）",
    "double_wide": "双栏宽扁 17.1 cm",
    "square": "正方形 12 cm",
    "slide": "幻灯片 16:9",
    "a4_land": "A4 横向",
}


def cm_figsize(width_cm: float, height_cm: float):
    return (width_cm / CM_PER_INCH, height_cm / CM_PER_INCH)


def figure_preset(name: str):
    w_cm, h_cm = FIGURE_PRESETS.get(name, FIGURE_PRESETS["double"])
    return cm_figsize(w_cm, h_cm)


def new_figure(figsize=None, preset: str = "double", dpi: int = 150):
    """
    建一个符合主题的白底 Figure。

    注意：这里刻意用 `matplotlib.figure.Figure` 而不是 `plt.figure()`。
    pyplot 维护着一份全局的 Figure 注册表，**不是线程安全的**；
    而本软件会把渲染放到工作线程里跑（否则界面会卡死），
    所以在工作线程里绝不能碰 pyplot。直接构造 Figure 既安全又干净。
    """
    from matplotlib.figure import Figure
    if figsize is None:
        figsize = figure_preset(preset)
    return Figure(figsize=figsize, dpi=dpi, facecolor=COLORS["bg"])


def tidy_axes(ax, grid: bool = False, box: bool = False):
    """统一坐标轴外观：默认只留左/下轴脊；box=True 时四边都有细框（地图常用）。"""
    for side in ("left", "bottom", "top", "right"):
        ax.spines[side].set_visible(box or side in ("left", "bottom"))
        if ax.spines[side].get_visible():
            ax.spines[side].set_linewidth(0.7)
            ax.spines[side].set_color(COLORS["spine"])
    if grid:
        ax.grid(True, color=COLORS["grid"], linewidth=0.5, alpha=0.9, zorder=0)
    return ax
