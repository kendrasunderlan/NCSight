# -*- coding: utf-8 -*-
"""
控制面板集合
============
每个面板都是 PanelBase 的子类，遵守同一协议（set_source / bind / apply /
changed 信号），主窗口只跟协议打交道，新增面板不需要改主窗口逻辑。
"""

from .base import PanelBase, Section, scrollable
from .source_panel import SourcePanel
from .data_panel import DataPanel
from .scale_panel import ScalePanel
from .map_panel import MapPanel
from .analysis_panel import AnalysisPanel
from .layout_panel import LayoutPanel
from .timeseries_panel import TimeSeriesPanel

# 右侧「绘图控制」里从上到下的面板顺序
CONTROL_PANEL_CLASSES = [
    DataPanel,
    ScalePanel,
    MapPanel,
    AnalysisPanel,
    LayoutPanel,
    TimeSeriesPanel,
]

__all__ = [
    "PanelBase", "Section", "scrollable",
    "SourcePanel", "DataPanel", "ScalePanel", "MapPanel",
    "AnalysisPanel", "LayoutPanel", "TimeSeriesPanel",
    "CONTROL_PANEL_CLASSES",
]
