# -*- coding: utf-8 -*-
"""
主窗口构造冒烟测试
==================
**这个文件是因为一次真实事故而加的。**

当时给状态栏加进度条，漏了 `QProgressBar` 的 import。pytest 244 项全过 ——
因为没有任何一个用例真的去**构造主窗口**。问题是等打完包、
跑 exe 自检才暴露出来的，白等了十分钟。

所以这里做一件很朴素的事：把主窗口建起来，检查关键部件在位。
它是我最快的一道防线，比 exe 自检早十分钟发现问题。
"""

import os

import pytest

# 必须在导入 PySide6 之前设置
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    yield a


@pytest.fixture(scope="module")
def win(app):
    from ncsight.gui.main_window import MainWindow
    w = MainWindow()
    yield w
    try:
        w.close()
    except Exception:                                   # noqa: BLE001
        pass


class TestMainWindowConstructs:
    def test_能构造出来(self, win):
        assert win is not None

    def test_状态栏部件齐全(self, win):
        """踩过的坑：加进度条时漏了 QProgressBar 的 import。"""
        sb = win.statusBar()
        assert sb is not None
        assert win.coord_label is not None
        assert win.hint_label is not None
        assert win.progress_bar is not None
        assert win.progress_label is not None
        # 进度条初始应当是隐藏的
        assert win.progress_bar.isVisible() is False

    def test_进度条能刷新(self, win):
        win._on_render_progress(3, 10, "读取 3/10")
        assert win.progress_bar.maximum() == 10
        assert win.progress_bar.value() == 3
        win._on_render_progress(0, 0, "不确定进度")
        assert win.progress_bar.maximum() == 0        # 不确定模式
        win._show_progress(False)
        assert win.progress_bar.value() == 0

    def test_三块主区域都在(self, win):
        assert win.source_panel is not None
        assert win.plot_view is not None
        assert win.splitter is not None

    def test_控制面板都建起来了(self, win):
        titles = [p.title for p in win._panels]
        assert len(titles) >= 5, titles
        assert "时序分析" in titles, titles

    def test_渲染服务已启动(self, win):
        assert win.renderer is not None
        assert not win.renderer.busy
        assert not win.renderer.has_pending()

    def test_时序面板已接线(self, win):
        """踩过的坑：接线调用早于面板创建，findChildren 找不到。"""
        assert win._series_panel is not None

    def test_数据集列表起始为空(self, win):
        assert win._datasets == []
        assert win.source_panel.ds_list.count() == 0

    def test_主入口是多选对话框(self, win):
        """踩过的坑：主入口曾是单选，用户以为软件不支持批量。"""
        import inspect
        src = inspect.getsource(type(win).open_file)
        assert "getOpenFileNames" in src
        assert hasattr(win, "open_folder")
