# -*- coding: utf-8 -*-
"""
NCSight · 面向海洋遥感的 netCDF 可视化工作台

设计铁律（继承自 Panoply 拆解报告的教训）：
    core/ 与 style/ 里绝对不允许 import 任何 GUI 库。
    这样 GUI 出图与命令行批处理出图走的是同一套函数。

目录导航：
    ncsight.core      内核：读取 / 识别 / 栅格化 / 色表 / 底图 / 绘图 / 分析
    ncsight.style     matplotlib 白色简约主题与中文字体
    ncsight.config    PlotSpec 与 YAML/JSON 的互转（可复现出图的关键）
    ncsight.cli       命令行入口
    ncsight.gui       PySide6 界面层（可选的，不装 Qt 也能用 CLI）
"""

from .version import (
    __version__,
    APP_NAME,
    APP_NAME_CN,
    APP_SLOGAN,
    version_info,
    version_string,
)

# 打包成 exe 后，必须在任何库使用之前把资源路径摆正
# （cartopy 底图目录、matplotlib 缓存目录等）。开发环境下这些设置无害，
# 但为了不拖慢 `import ncsight`，只在 frozen 时自动执行。
import sys as _sys
if getattr(_sys, "frozen", False):
    try:
        from ._runtime import apply_once
        RUNTIME_INFO = apply_once()
    except Exception:                                   # noqa: BLE001
        RUNTIME_INFO = {}
else:
    RUNTIME_INFO = {}

__all__ = [
    "__version__",
    "APP_NAME",
    "APP_NAME_CN",
    "APP_SLOGAN",
    "version_info",
    "version_string",
    "RUNTIME_INFO",
]
