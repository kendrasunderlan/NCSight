# -*- coding: utf-8 -*-
"""
NCSight 图形界面层（PySide6）
============================
本包**可以被完全跳过**：不装 PySide6 时，`ncsight` 的核心功能与命令行
依然照常工作。这是刻意设计的 —— 科研软件不该把「画图」和「开界面」绑死。

模块划分：
    app.py          入口：QApplication + 主题 + 主窗口
    theme.py        白色简约 QSS
    icons.py        全部用 QPainter 现画的矢量图标（仓库里没有二进制资源）
    main_window.py  主窗口：菜单/工具栏/状态栏/防抖渲染
    plot_view.py    嵌 matplotlib 的画布 + 取值/缩放/平移/圈选四种交互
    dialogs.py      关于、导出图像、导出数据、动画、批量、进度
    panels/         各控制面板（数据/色标/地图/筛选分析/版式）
"""

from .app import run, create_app

__all__ = ["run", "create_app"]
