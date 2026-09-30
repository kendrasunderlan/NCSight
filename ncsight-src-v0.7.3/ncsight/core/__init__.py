# -*- coding: utf-8 -*-
"""
NCSight 内核层
==============
本包（含其所有子模块）**绝对不允许 import 任何 GUI 库**。
这是保证「界面出图」与「命令行批处理出图」走同一套代码的前提，
也是 Panoply 没能做到、因而难以自动化的根因。
"""

from .reader import NcSource, FieldData, NcSourceError, open_source
from .detect import (AxisRole, VarKind, AxisInfo, VarInfo,
                     PLOT_OPTIONS, classify_axis, classify_variable)
from .colormap import (resolve_colormap, obpg_palette, read_cpt, read_act,
                       read_table_any, list_catalog, binned, make_norm,
                       CMAP_CATALOG)
from .grid import (coarsen_field, coarsen_array, subset_bbox,
                   resample_regular, MAX_PROJECT_CELLS)
from .overlay import OverlaySpec, add_overlays, add_overlays_plain, \
    cached_shapefiles, cartopy_available
from .plot.base import (PlotSpec, RenderResult, render, PLOT_KINDS,
                        PROJECTIONS)
from .colorbar import (ColorbarSpec, STYLE_CATALOG as CBAR_STYLES,
                       LOCATIONS as CBAR_LOCATIONS)
from .series import TimeSeries, SeriesBuilder, parse_date_from_name
from . import indicators

__all__ = [
    "NcSource", "FieldData", "NcSourceError", "open_source",
    "AxisRole", "VarKind", "AxisInfo", "VarInfo", "PLOT_OPTIONS",
    "classify_axis", "classify_variable",
    "resolve_colormap", "obpg_palette", "read_cpt", "read_act",
    "read_table_any", "list_catalog", "binned", "make_norm", "CMAP_CATALOG",
    "coarsen_field", "coarsen_array", "subset_bbox", "resample_regular",
    "MAX_PROJECT_CELLS",
    "OverlaySpec", "add_overlays", "add_overlays_plain", "cached_shapefiles",
    "cartopy_available",
    "PlotSpec", "RenderResult", "render", "PLOT_KINDS", "PROJECTIONS",
    "ColorbarSpec", "CBAR_STYLES", "CBAR_LOCATIONS",
    "TimeSeries", "SeriesBuilder", "parse_date_from_name", "indicators",
]
