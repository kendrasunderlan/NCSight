# -*- coding: utf-8 -*-
"""
绘图图型子包
============
每个模块实现一种图型，统一签名：

    render(spec: PlotSpec, source: NcSource, fig=None, ax=None) -> RenderResult

新增图型的步骤：
  1. 在本目录加一个模块，实现 render()
  2. 在 base.PLOT_KINDS 里登记中文名
  3. 在 base.render() 的分发表里加一行
  4. 在 ncsight/core/plot/__init__.py 的 __all__ 里导出
"""

from .base import (PlotSpec, RenderResult, render, PLOT_KINDS, PROJECTIONS,
                   COLORBAR_LOCATIONS, compute_range, make_cmap_norm,
                   attach_colorbar, stats_annotation, resolve_kind)
from .series_plot import render as render_series

__all__ = [
    "PlotSpec", "RenderResult", "render", "PLOT_KINDS", "PROJECTIONS",
    "COLORBAR_LOCATIONS", "compute_range", "make_cmap_norm",
    "attach_colorbar", "stats_annotation", "resolve_kind",
    "render_series",
]
