# -*- coding: utf-8 -*-
"""
主窗口
======
布局（纯白简约风格）：

    ┌─────────────────── 菜单栏 ───────────────────┐
    │ 工具栏：打开/出图/导出/配置 + 交互模式 + 面板开关  │
    ├──────────┬──────────────────────┬───────────┤
    │ 变量树    │      matplotlib      │  绘图控制   │
    │ + 属性    │        画布           │  （可折叠）  │
    ├──────────┴──────────────────────┴───────────┤
    │ 状态栏：鼠标处的经纬度与数值 | 提示 | 版本      │
    └─────────────────────────────────────────────┘

关键机制：
  * 所有面板的改动 → 更新 PlotSpec → **防抖 120ms** 后重渲染
    （拖动滑块时不会把 CPU 打满）
  * 渲染统一走 core.render()，与命令行完全同一套代码
  * 会话（Session）与单图配置（PlotSpec）都能存成 YAML
"""

from __future__ import annotations

import os
import traceback
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy,
                               QSplitter, QStatusBar, QToolBar, QVBoxLayout,
                               QWidget, QButtonGroup)

from ..config import Session, load_prefs, save_prefs
from ..core.plot.base import PlotSpec, render
from ..core.reader import NcSource, NcSourceError
from ..version import APP_NAME, APP_NAME_CN, version_info, version_string
from . import dialogs, icons
from .panels import CONTROL_PANEL_CLASSES, SourcePanel, scrollable
from .plot_view import MODES, PlotView
from .render_worker import RenderService
from .theme import UI


class MainWindow(QMainWindow):
    def __init__(self, dataset: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("%s · %s" % (APP_NAME, APP_NAME_CN))
        self.setWindowIcon(icons.app_icon())

        self._prefs = load_prefs()
        self._source: Optional[NcSource] = None
        self._session = Session.create()
        self._spec = PlotSpec()
        self._last_error = ""
        self._panels: List = []
        self._datasets: List[str] = []          # 已加载的全部数据集（时序也用它）
        self._series_paths: List[str] = []      # 时序分析用的文件集合
        self._series_panel = None

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(120)
        self._render_timer.timeout.connect(self._do_render)

        # 渲染跑在独立线程：界面永不冻结（原因见 render_worker.py 的注释）
        self._render_seq = 0            # 请求序号，用于丢弃过期结果
        self._cursor_busy = False
        self._export_pending = None     # 正在等待「全分辨率重绘后再导出」
        self.renderer = RenderService(self)
        self.renderer.done.connect(self._on_render_done)
        self.renderer.busyChanged.connect(self._on_render_busy)
        self.renderer.progress.connect(self._on_render_progress)

        self._build_ui()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._restore_geometry()

        if dataset:
            QTimer.singleShot(60, lambda: self.open_dataset(dataset))

    # ==================================================================
    # 界面构建
    # ==================================================================
    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        # 左：变量树
        self.source_panel = SourcePanel()
        self.source_panel.setMinimumWidth(210)
        self.source_panel.variableSelected.connect(self._on_variable_selected)
        self.source_panel.plotRequested.connect(self._on_plot_requested)
        # 数据集列表（多文件）—— 批量分析的入口
        self.source_panel.openFilesRequested.connect(self.open_file)
        self.source_panel.openDirRequested.connect(self.open_folder)
        self.source_panel.datasetActivated.connect(self._on_dataset_activated)
        self.source_panel.datasetsRemoved.connect(self._on_datasets_removed)

        # 中：画布
        self.plot_view = PlotView()
        self.plot_view.coordsChanged.connect(self._on_coords)
        self.plot_view.regionSelected.connect(self._on_region)
        self.plot_view.modeChanged.connect(lambda _m: self._sync_mode_buttons())

        # 右：控制面板
        self.controls_host = QWidget()
        self.controls_host.setObjectName("Panel")
        ch = QVBoxLayout(self.controls_host)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(0)
        head = QLabel("绘图控制")
        head.setStyleSheet(
            "padding:9px 12px;font-size:12.5px;color:%s;"
            "border-bottom:1px solid %s;background:%s;"
            % (UI["text"], UI["border"], UI["panel"]))
        ch.addWidget(head)

        inner = QWidget()
        inner.setObjectName("PanelBody")
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(0)
        for cls in CONTROL_PANEL_CLASSES:
            panel = cls()
            panel.changed.connect(self._on_panel_changed)
            # 时序面板有额外的 runSeries 信号，就地接上最稳 ——
            # 放到循环外面用 findChildren 找，时机上容易踩空。
            # ★ 用面板**独有**的属性判断 ★
            # runSeries 定义在 PanelBase 上，所有面板都有，用它判断会误伤。
            if hasattr(panel, "addFilesRequested"):
                panel.runSeries.connect(self._on_run_series)
                panel.addFilesRequested.connect(self.open_file)
                panel.addDirRequested.connect(self.open_folder)
                self._series_panel = panel
            self._panels.append(panel)
            il.addWidget(panel)
        il.addStretch(1)
        ch.addWidget(scrollable(inner), 1)
        self.controls_host.setMinimumWidth(250)
        self.controls_host.setMaximumWidth(420)

        splitter.addWidget(self.source_panel)
        splitter.addWidget(self.plot_view)
        splitter.addWidget(self.controls_host)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([250, 820, 300])
        self.splitter = splitter
        self.setCentralWidget(splitter)

    # ------------------------------------------------------------------
    def _build_menus(self) -> None:
        mb = self.menuBar()

        m = mb.addMenu("文件(&F)")
        self._act(m, "打开数据集…（可多选）", self.open_file, QKeySequence.Open)
        self._act(m, "打开文件夹（批量加入 nc）…", self.open_folder)
        self._act(m, "打开最近的数据", self._reopen_last)
        m.addSeparator()
        self._act(m, "保存图像…", self.export_image, QKeySequence.Save)
        self._act(m, "复制图像到剪贴板", self.copy_image)
        m.addSeparator()
        self._act(m, "导出数据…", self.export_data)
        self._act(m, "导出动画…", self.export_animation)
        self._act(m, "批量出图…", self.batch_plot)
        m.addSeparator()
        self._act(m, "保存绘图配置…", self.save_spec, "Ctrl+Shift+S")
        self._act(m, "载入绘图配置…", self.load_spec)
        m.addSeparator()
        self._act(m, "保存会话…", self.save_session)
        self._act(m, "打开会话…", self.load_session)
        m.addSeparator()
        self._act(m, "退出", self.close, QKeySequence.Quit)
        self.menu_file = m

        m = mb.addMenu("视图(&V)")
        self._act(m, "重置视图", self.reset_view, "Ctrl+0")
        m.addSeparator()
        self.act_show_left = self._act(m, "显示变量面板", self._toggle_left,
                                       "Ctrl+Alt+L", checkable=True, checked=True)
        self.act_show_right = self._act(m, "显示绘图控制面板", self._toggle_right,
                                        "Ctrl+Alt+R", checkable=True, checked=True)
        m.addSeparator()
        self._act(m, "变量过滤：只显示可制图", lambda: self._set_filter("plottable"))
        self._act(m, "变量过滤：只显示地理变量", lambda: self._set_filter("geo"))
        self._act(m, "变量过滤：显示全部", lambda: self._set_filter("all"))
        m.addSeparator()
        self._act(m, "放大变量树字号", lambda: self._bump_font(1))
        self._act(m, "缩小变量树字号", lambda: self._bump_font(-1))
        self.menu_view = m

        m = mb.addMenu("绘图(&P)")
        self._act(m, "重新出图", self.request_render, "F5")
        m.addSeparator()
        self._act(m, "快捷：距平图", lambda: self.apply_quick("anomaly"))
        self._act(m, "快捷：矢量场", lambda: self.apply_quick("vector"))
        self._act(m, "快捷：纬向平均", lambda: self.apply_quick("zonal"))
        self._act(m, "快捷：Hovmöller", lambda: self.apply_quick("hov"))
        self._act(m, "快捷：叠加等值线", lambda: self.apply_quick("contour"))
        m.addSeparator()
        self._act(m, "色标贴合数据", lambda: self._quick_scale("fit"))
        self._act(m, "色标居中于零", lambda: self._quick_scale("zero"))
        self._act(m, "切换黑白背景", self._toggle_background)
        self.menu_plot = m

        m = mb.addMenu("分析(&A)")
        self._act(m, "计算距平（相对时间平均）", self.analyze_anomaly)
        self._act(m, "区域平均时间序列", self.analyze_region_series)
        self._act(m, "矢量合成（U/V → 大小）", self.analyze_vector_magnitude)
        self.menu_analysis = m

        m = mb.addMenu("帮助(&H)")
        self._act(m, "关于 %s" % APP_NAME, self.show_about)
        self._act(m, "命令行用法提示", self.show_cli_help)
        self.menu_help = m

    def _act(self, menu, text: str, slot, shortcut=None,
             checkable: bool = False, checked: bool = False) -> QAction:
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(shortcut if isinstance(shortcut, QKeySequence)
                          else QKeySequence(shortcut))
        a.setCheckable(checkable)
        a.setChecked(checked)
        if checkable:
            a.toggled.connect(slot)
        else:
            a.triggered.connect(lambda _=False, s=slot: s())
        menu.addAction(a)
        return a

    # ------------------------------------------------------------------
    def _build_toolbar(self) -> None:
        tb = QToolBar("主工具栏")
        tb.setMovable(False)
        tb.setIconSize(tb.iconSize())
        self.addToolBar(tb)
        self.toolbar = tb

        def add(name, tip, slot, text=None):
            a = QAction(icons.line_icon(name), text or tip, self)
            a.setToolTip(tip)
            a.triggered.connect(lambda _=False, s=slot: s())
            tb.addAction(a)
            return a

        add("open", "打开 netCDF 数据集（Ctrl+O，可多选）", self.open_file, "打开")
        add("folder", "打开文件夹，批量加入 nc 文件", self.open_folder, "文件夹")
        add("chart", "重新出图（F5）", self.request_render, "出图")
        tb.addSeparator()
        add("export", "导出图像（PNG/PDF/SVG…）", self.export_image, "导出图")
        add("table", "导出数据（CSV/NPZ）", self.export_data, "导出数据")
        add("animation", "导出动画", self.export_animation, "动画")
        add("batch", "批量出图", self.batch_plot, "批量")
        tb.addSeparator()
        add("save", "保存绘图配置（可复现）", self.save_spec, "存配置")
        add("open", "载入绘图配置", self.load_spec, "读配置")
        tb.addSeparator()

        # 交互模式
        lbl = QLabel("  模式 ")
        lbl.setStyleSheet("color:%s;font-size:12px;" % UI["text_muted"])
        tb.addWidget(lbl)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons: Dict[str, QAction] = {}
        icon_for = {"pick": "info", "zoom": "zoomin", "pan": "map", "region": "mask"}
        for key, text in MODES:
            a = QAction(icons.line_icon(icon_for.get(key, "chart")), text, self)
            a.setCheckable(True)
            a.setChecked(key == "pick")
            a.setToolTip("%s模式" % text)
            a.triggered.connect(lambda _=False, k=key: self.plot_view.set_mode(k))
            tb.addAction(a)
            self.mode_buttons[key] = a
        tb.addSeparator()
        add("fit", "重置视图（Ctrl+0）", self.reset_view, "重置")
        tb.addSeparator()
        add("panel", "显示/隐藏变量面板", lambda: self.act_show_left.toggle(), None)
        add("settings", "显示/隐藏绘图控制面板", lambda: self.act_show_right.toggle(), None)

    def _build_statusbar(self) -> None:
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.coord_label = QLabel("")
        self.coord_label.setMinimumWidth(420)
        self.coord_label.setStyleSheet("color:%s;font-size:12px;" % UI["text"])
        sb.addWidget(self.coord_label, 1)

        # 进度条：算几百个文件的时序指标时要让用户看到「到哪了」，
        # 否则界面只是安静地卡着，完全无法判断是在干活还是死了。
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(
            "color:%s;font-size:12px;" % UI["text_muted"])
        self.progress_label.setVisible(False)
        sb.addPermanentWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedWidth(190)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setStyleSheet(
            "QProgressBar{border:1px solid %s;border-radius:3px;"
            "background:%s;color:%s;font-size:11px;text-align:center;}"
            "QProgressBar::chunk{background:%s;border-radius:2px;}"
            % (UI["border"], UI["panel"], UI["text"], UI["accent"]))
        self.progress_bar.setVisible(False)
        sb.addPermanentWidget(self.progress_bar)

        self.hint_label = QLabel("")
        self.hint_label.setStyleSheet("color:%s;font-size:12px;" % UI["text_muted"])
        sb.addPermanentWidget(self.hint_label)
        v = QLabel(version_string())
        v.setStyleSheet("color:%s;font-size:12px;padding-right:8px;" % UI["text_muted"])
        v.setToolTip(version_info()["milestone"])
        sb.addPermanentWidget(v)

    # ------------------------------------------------------------------
    def _on_render_progress(self, done: int, total: int, msg: str = "") -> None:
        """刷新进度条。没有进度信息的渲染（地图等）走不确定模式。"""
        try:
            if total <= 0:
                self.progress_bar.setRange(0, 0)        # 不确定：滚动条动画
                self.progress_bar.setTextVisible(False)
            else:
                self.progress_bar.setRange(0, int(total))
                self.progress_bar.setValue(max(0, min(int(done), int(total))))
                self.progress_bar.setTextVisible(True)
                self.progress_bar.setFormat("%p%  %v/%m")
            if msg:
                self.progress_label.setText(msg)
            if self._series_panel is not None and total > 0:
                self._series_panel.report_progress(done, total, msg)
        except Exception:                               # noqa: BLE001
            pass

    def _show_progress(self, on: bool, indeterminate: bool = True) -> None:
        try:
            self.progress_bar.setVisible(bool(on))
            self.progress_label.setVisible(bool(on))
            if on and indeterminate and self.progress_bar.maximum() == 0:
                pass
            if not on:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(0)
                self.progress_bar.setTextVisible(True)
                self.progress_label.setText("")
        except Exception:                               # noqa: BLE001
            pass

    def _restore_geometry(self) -> None:
        w = self._prefs.get("window") or {}
        self.resize(int(w.get("w", 1360)), int(w.get("h", 860)))

    # ==================================================================
    # 数据集
    # ==================================================================
    def open_file(self) -> None:
        """
        打开数据集 —— **支持一次选多个**。

        批量处理的第一入口。以前这里用的是单选对话框，用户从主菜单进来
        永远只能开一个文件，会以为软件不支持批量；多选能力藏在「时序分析」
        面板里，等于没做。现在主入口本身就是多选。
        """
        start = self._prefs.get("last_dir") or ""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "打开 netCDF / GRIB 数据集（可按住 Ctrl / Shift 多选）", start,
            "数据文件 (*.nc *.nc4 *.cdf *.grib *.grib2 *.grb *.grb2 *.hdf *.h5);;"
            "所有文件 (*)")
        if paths:
            self.add_datasets(paths, activate_first=True)

    def open_folder(self) -> None:
        """把一个目录下所有 nc 一次性加进来（逐日产品最常用）。"""
        start = self._prefs.get("last_dir") or ""
        d = QFileDialog.getExistingDirectory(self, "选择包含 nc 文件的文件夹", start)
        if not d:
            return
        from ..core.series import SeriesBuilder
        found = SeriesBuilder.expand([d])
        if not found:
            self._info("没有找到数据文件",
                       "该文件夹里没有 .nc / .nc4 文件：\n%s" % d)
            return
        self.add_datasets(found, activate_first=True)
        if len(found) > 1:
            self.hint_label.setText(
                "已加入 %d 个文件 —— 到右侧「时序分析」面板勾选指标，即可批量出图"
                % len(found))

    # ------------------------------------------------------------------
    def add_datasets(self, paths, activate_first: bool = False) -> None:
        """把若干文件加进数据集列表；不重复添加。"""
        exist = {os.path.abspath(p) for p in self._datasets}
        added = []
        for p in paths:
            ap = os.path.abspath(p)
            if ap not in exist:
                exist.add(ap)
                self._datasets.append(ap)
                added.append(ap)
        if not added:
            self._refresh_datasets()
            return

        # 时序面板用的是同一份清单，不再各记一套
        if self._series_panel is not None:
            try:
                self._series_panel.set_paths(list(self._datasets))
            except Exception:                           # noqa: BLE001
                pass

        if activate_first or self._source is None:
            self._refresh_datasets()
            self.open_dataset(added[0])
        else:
            self._refresh_datasets()

    def _refresh_datasets(self) -> None:
        active = self._source.path if self._source is not None else ""
        self.source_panel.set_datasets(self._datasets, active)
        n = len(self._datasets)
        if n > 1:
            self.hint_label.setText(
                "已加载 %d 个数据集 —— 右侧「时序分析」面板可批量算指标" % n)

    def _on_dataset_activated(self, path: str) -> None:
        if path and (self._source is None or path != self._source.path):
            self.open_dataset(path)

    def _on_datasets_removed(self, paths) -> None:
        if not paths:
            if self._datasets:
                ask = QMessageBox.question(
                    self, "清空数据集",
                    "移除全部 %d 个数据集？" % len(self._datasets),
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if ask != QMessageBox.Yes:
                    return
            self._datasets = []
        else:
            drop = {os.path.abspath(p) for p in paths}
            self._datasets = [p for p in self._datasets if p not in drop]
        if self._series_panel is not None:
            try:
                self._series_panel.set_paths(list(self._datasets))
            except Exception:                           # noqa: BLE001
                pass
        # 当前激活的若被移除，换到第一个；一个不剩就清空界面
        if self._source is not None and self._source.path not in self._datasets:
            try:
                self._source.close()
            except Exception:                           # noqa: BLE001
                pass
            self._source = None
        if self._datasets:
            self._refresh_datasets()
            self.open_dataset(self._datasets[0])
        else:
            self.source_panel.set_source(None)
            self.source_panel.set_datasets([], "")
            self.plot_view.prepare()
            self.plot_view.canvas.draw_idle()
            self.setWindowTitle("%s · %s" % (APP_NAME, APP_NAME_CN))

    # ------------------------------------------------------------------
    def open_dataset(self, path: str) -> None:
        try:
            src = NcSource(path)
        except NcSourceError as exc:
            self._error("无法打开数据集", str(exc))
            return
        if self._source is not None:
            self._source.close()

        self._source = src
        if os.path.abspath(path) not in {os.path.abspath(p)
                                         for p in self._datasets}:
            self._datasets.append(os.path.abspath(path))
        self._prefs["last_dir"] = os.path.dirname(path)
        recent = [p for p in self._prefs.get("recent_files", []) if p != path]
        self._prefs["recent_files"] = [path] + recent[:9]
        save_prefs(self._prefs)

        self.source_panel.set_source(src)
        for p in self._panels:
            p.set_source(src)
        self._refresh_datasets()

        fields = src.plottable()
        if fields:
            primary = src.primary_field()
            self._spec = PlotSpec(
                variable=(primary.name if primary else fields[0].name),
                preset=self._prefs.get("preset", "double"),
                cmap=self._prefs.get("cmap", "auto"))
            vi = src.variables.get(self._spec.variable)
            if vi and vi.plot_options:
                self._spec.kind = vi.plot_options[0]
            self.source_panel.select_variable(self._spec.variable)
            self._sync_panels_from_spec()
            self.request_render()
        else:
            self.hint_label.setText("该数据集没有可制图的变量")
        self.setWindowTitle("%s · %s — %s" % (APP_NAME, APP_NAME_CN,
                                              os.path.basename(path)))

    def _reopen_last(self) -> None:
        files = self._prefs.get("recent_files") or []
        if not files:
            self._info("没有历史记录", "还没有打开过任何数据集。")
            return
        if os.path.exists(files[0]):
            self.open_dataset(files[0])
        else:
            self._error("文件不存在", files[0])

    def _leave_series_mode(self) -> None:
        """用户去点变量 / 改地图参数 = 想回到普通出图，退出时序模式。"""
        if self._series_panel is not None:
            try:
                self._series_panel.set_mode(False)
            except Exception:                           # noqa: BLE001
                pass

    def _on_variable_selected(self, name: str) -> None:
        self._leave_series_mode()
        if self._source is None:
            return
        self._spec.variable = name
        vi = self._source.variables.get(name)
        if vi and vi.plot_options and self._spec.kind not in vi.plot_options:
            self._spec.kind = vi.plot_options[0]
        self._sync_panels_from_spec()
        self.request_render()

    def _on_plot_requested(self, name: str) -> None:
        self._on_variable_selected(name)

    def _set_filter(self, key: str) -> None:
        combo = self.source_panel.filter_combo
        idx = combo.findData(key)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _bump_font(self, delta: int) -> None:
        tree = self.source_panel.tree
        f = tree.font()
        size = max(7.0, min(16.0, f.pointSizeF() + delta))
        f.setPointSizeF(size)
        tree.setFont(f)
        self.source_panel.info.setStyleSheet(
            self.source_panel.info.styleSheet().replace(
                "font-size:11.5px", "font-size:%.1fpx" % (size - 1.0)))

    # ==================================================================
    # 渲染
    # ==================================================================
    def request_render(self) -> None:
        self._render_timer.start()

    def _sync_panels_from_spec(self) -> None:
        for p in self._panels:
            p.bind(self._spec)

    def _collect_spec(self) -> PlotSpec:
        spec = self._spec
        for p in self._panels:
            p.apply(spec)
        return spec

    def _do_render(self) -> None:
        """
        提交一次渲染请求。

        ★ 这里是卡顿的根治点 ★
        原来是在这里直接调用 core.render()，而一张全球 4320x8640 的场
        光建网格就要 13.4 秒 —— 全部堵在 Qt 主线程上，界面完全无响应。

        现在做两件事：
          1. 按画布像素数降采样（screen_cells），13.4 秒 → 0.25 秒；
             屏幕上根本画不出比像素更细的细节，不损失观感。
          2. 把渲染丢到工作线程，主线程立刻返回，界面始终可交互。
        """
        if self._source is None:
            return
        spec = self._collect_spec()
        spec = spec.clone(screen_cells=self._screen_cells(spec))
        self._render_seq += 1
        # 时序/谱：数据源是一批文件；其余图型用当前激活的那个数据集
        if spec.kind in ("series", "spectrum") and self._series_paths:
            target = list(self._series_paths)
        elif self._source is not None:
            target = self._source.path
        else:
            return
        self.renderer.submit(self._render_seq, target, spec)

    # ------------------------------------------------------------------
    # 时序分析（多文件）
    # ------------------------------------------------------------------
    def _wire_run_series(self) -> None:
        """把时序面板的「计算并出图」接到主窗口。"""
        try:
            from .panels import TimeSeriesPanel
            from PySide6.QtWidgets import QApplication as _QA
            for w in self.findChildren(TimeSeriesPanel) or []:
                w.runSeries.connect(self._on_run_series)
                self._series_panel = w
        except Exception:                               # noqa: BLE001
            self._series_panel = None

    def _on_run_series(self, paths: list, changes: dict) -> None:
        """时序面板请求：用这批文件、按这些参数渲染。"""
        # 先把挂起的防抖重绘停掉，否则它随后会用地图 kind 覆盖掉时序结果
        self._render_timer.stop()
        self._series_paths = list(paths or [])
        if not self._series_paths:
            self._hint("时序分析需要先添加 nc 文件")
            return
        spec = self._collect_spec()
        for k, v in (changes or {}).items():
            try:
                setattr(spec, k, v)
            except Exception:                           # noqa: BLE001
                pass
        # 时序图不做屏幕降采样（点的数量本来就少，降采样反而丢信息）
        spec = spec.clone(screen_cells=0)
        self._spec = spec
        self._render_seq += 1
        self.hint_label.setText("正在计算时序指标（%d 个文件）…"
                                % len(self._series_paths))
        self.renderer.submit(self._render_seq, list(self._series_paths), spec)

    def _hint(self, text: str) -> None:
        try:
            self.hint_label.setText(text)
        except Exception:                               # noqa: BLE001
            pass

    def _screen_cells(self, spec=None) -> int:
        """
        屏幕渲染的格点上限 ≈ 0.8 × 画布像素数。

        「每格点约 1.25 个屏幕像素」是刻意的取舍：屏幕上看不出更细的差别，
        但格点数直接决定建网格与重绘的耗时。实测 908 万档降到 60 万档，
        建网格从 13.4 秒到 0.2 秒，重绘也会跟着快一截。

        下限 25 万：窗口刚创建、布局还没完成时画布尺寸可能只有几十像素，
        照着算会得到一张过分粗糙的图。
        """
        w, h = self.plot_view.canvas_size()
        budget = max(250_000, int(w * h * 0.8))
        # 投影图里每个格点的四个角都要经 cartopy 做一次投影变换，
        # 单位格点的代价比等距圆柱高好几倍（实测 2~6 秒 vs 0.5 秒）。
        # 所以投影图把预算收紧 —— 视觉上看不出差别，但能省掉几秒等待。
        proj = getattr(spec, "projection", "") or ""
        if proj not in ("", "PlateCarree"):
            budget = max(150_000, int(budget * 0.45))
        return budget

    def _on_render_busy(self, busy: bool) -> None:
        if busy:
            self.hint_label.setText("正在渲染…")
            self._show_progress(True)
        else:
            self._show_progress(False)
        try:
            if busy and not self._cursor_busy:
                QApplication.setOverrideCursor(Qt.BusyCursor)
                self._cursor_busy = True
            elif not busy and self._cursor_busy:
                QApplication.restoreOverrideCursor()
                self._cursor_busy = False
        except Exception:                               # noqa: BLE001
            self._cursor_busy = False

    def _on_render_done(self, req_id: int, result, error: str) -> None:
        # 过期结果（期间用户又改了参数）直接丢弃，避免画面来回跳
        if req_id != self._render_seq:
            return

        if error:
            self._last_error = error
            first = error.splitlines()[0] if error else "未知错误"
            self.hint_label.setText("渲染失败：%s" % first)
            print(error)
            self._export_pending = None
            return

        self._last_error = ""

        # 这次渲染是不是为了「导出全分辨率图」？
        if self._export_pending is not None:
            job, self._export_pending = self._export_pending, None
            self._save_export(result, job)
            return

        self.plot_view.adopt(result)
        d = result.data
        if d is not None:
            try:
                from ..core.plot.base import compute_range
                lo, hi = compute_range(d, self._collect_spec())
                for p in self._panels:
                    if hasattr(p, "set_effective_range"):
                        p.set_effective_range(lo, hi)
                        break
            except Exception:                           # noqa: BLE001
                pass
            s = d.stats()
            self.hint_label.setText(
                "%s · %s  |  n=%s  min=%.4g  max=%.4g  mean=%.4g"
                % (result.spec.kind, d.name, s.get("n", 0), s.get("min", 0),
                   s.get("max", 0), s.get("mean", 0)))


    def _on_panel_changed(self) -> None:
        # 分析面板的「快捷按钮」不改 spec，而是触发一次动作
        for p in self._panels:
            if hasattr(p, "take_quick"):
                key = p.take_quick()
                if key:
                    self.apply_quick(key)
                    return
        self.request_render()

    def _on_coords(self, text: str) -> None:
        self.coord_label.setText(text)

    def _on_region(self, bbox: List[float]) -> None:
        if not bbox:
            self.reset_view()
            return
        for p in self._panels:
            if hasattr(p, "lon_min"):
                p.bbox_check.setChecked(True)
                p.lon_min.setValue(round(bbox[0], 4))
                p.lon_max.setValue(round(bbox[1], 4))
                p.lat_min.setValue(round(bbox[2], 4))
                p.lat_max.setValue(round(bbox[3], 4))
                break
        self.request_render()

    def reset_view(self) -> None:
        if self._source is None:
            return
        for p in self._panels:
            if hasattr(p, "bbox_check"):
                p.bbox_check.setChecked(False)
                break
        self.request_render()

    def _sync_mode_buttons(self) -> None:
        mode = self.plot_view.mode
        for key, act in self.mode_buttons.items():
            act.setChecked(key == mode)

    # ==================================================================
    # 快捷动作
    # ==================================================================
    def apply_quick(self, key: str) -> None:
        spec = self._collect_spec()
        if key == "anomaly":
            spec.center_zero = True
            spec.cmap = "balance"
            if hasattr(spec, "nbins"):
                spec.nbins = max(13, spec.nbins)
        elif key == "thermal":
            spec.cmap = "thermal"
        elif key == "vector":
            vi = self._source.variables.get(spec.variable) if self._source else None
            if vi is not None and vi.vector_partner:
                from ..detect import VarKind
                spec.kind = "vector"
                spec.vector_variable = vi.vector_partner
            else:
                self._info("没有找到矢量配对",
                           "变量 %s 没有配对的 U/V 分量。\n"
                           "请先在「数据」面板的「矢量配对」里手动指定。" % spec.variable)
                return
        elif key == "zonal":
            spec.kind = "zonal"
        elif key == "hov":
            spec.kind = "hovmoller"
        elif key == "contour":
            spec.show_contours = True
        else:
            return
        self._spec = spec
        self._sync_panels_from_spec()
        self.request_render()

    def _quick_scale(self, key: str) -> None:
        for p in self._panels:
            if not hasattr(p, "auto_check"):
                continue
            if key == "fit":
                p.auto_check.setChecked(True)
            elif key == "zero":
                p.zero_check.setChecked(True)
            break
        self.request_render()

    def _toggle_background(self) -> None:
        from . import theme as _t
        # 白底为主，这里只做提示（黑底需要改 style.COLORS）
        self.hint_label.setText("已保持白色背景（简约风格）")

    # ==================================================================
    # 导出 / 配置
    # ==================================================================
    def export_image(self) -> None:
        if self._source is None or not self.plot_view.has_plot:
            self._info("还没有图", "请先打开数据集并出图。")
            return
        stem = os.path.splitext(os.path.basename(self._source.path))[0]
        default = os.path.join(self._prefs.get("last_dir", ""),
                               "%s_%s.png" % (stem, self._spec.variable))
        dlg = dialogs.ExportImageDialog(self, default)
        if dlg.exec() != dlg.Accepted:
            return
        v = dlg.values()

        # ★ 不能直接保存屏幕上那张 ★
        # 屏幕渲染是按画布像素降采样过的（不这么做交互就会卡死十几秒），
        # 直接存下来等于丢细节。这里用全分辨率（screen_cells=0）重新渲染一遍
        # 再保存 —— 「屏幕快、导出真」。
        spec = self._collect_spec().clone(screen_cells=0, dpi=int(v["dpi"]))
        self._export_pending = (v, spec)
        self._render_seq += 1
        self.hint_label.setText("正在按全分辨率渲染，请稍候…")
        self.renderer.submit(self._render_seq, self._source.path, spec)

    def _save_export(self, result, job: dict) -> None:
        try:
            from ..core.export import save_figure
            path = save_figure(result.fig, job["path"], fmt=job["format"],
                               dpi=int(job["dpi"]),
                               transparent=bool(job["transparent"]))
            d = result.data
            n = d.values.size if d is not None else 0
            self.hint_label.setText("已导出 %s" % path)
            self._info("导出成功",
                       "图像已保存到：\n%s\n\n本次为全分辨率渲染（%s 个格点），"
                       "不是屏幕上的降采样预览。" % (path, format(n, ",")),
                       icon="info")
        except Exception as exc:                        # noqa: BLE001
            self._error("导出失败", str(exc))

    def copy_image(self) -> None:
        if not self.plot_view.has_plot:
            return
        from ..core.export import copy_to_clipboard
        ok = copy_to_clipboard(self.plot_view.figure, dpi=200)
        self.hint_label.setText("已复制到剪贴板" if ok else "复制失败（需要 Qt 剪贴板支持）")

    def export_data(self) -> None:
        if self._source is None:
            return
        stem = os.path.splitext(os.path.basename(self._source.path))[0]
        default = os.path.join(self._prefs.get("last_dir", ""),
                               "%s_%s.csv" % (stem, self._spec.variable))
        dlg = dialogs.ExportDataDialog(self, default)
        if dlg.exec() != dlg.Accepted:
            return
        v = dlg.values()
        try:
            from ..core import export as ex
            spec = self._collect_spec()
            if v["what"] == "overview":
                path = ex.export_overview(self._source, v["path"])
            else:
                spec = self._collect_spec()
                fd = self._source.read_field(spec.variable, spec.select)
                from ..core.grid import subset_bbox
                fd = subset_bbox(fd, spec.bbox)
                if v["what"] == "grid_npz":
                    path = ex.export_grid_npz(fd, v["path"])
                else:
                    path = ex.export_grid_csv(fd, v["path"])
            self.hint_label.setText("已导出 %s" % path)
            self._info("导出成功", "数据已保存到：\n%s" % path, icon="info")
        except Exception as exc:                        # noqa: BLE001
            self._error("导出失败", str(exc))

    def export_animation(self) -> None:
        if self._source is None:
            return
        from ..core.animate import animatable_dims, ffmpeg_available
        spec = self._collect_spec()
        dims = animatable_dims(spec, self._source)
        if not dims:
            self._info("无法导出动画",
                       "变量 %s 没有可遍历的维度。\n"
                       "动画要求变量至少三维（前几维才能逐帧遍历）。" % spec.variable)
            return
        stem = os.path.splitext(os.path.basename(self._source.path))[0]
        dlg = dialogs.AnimationDialog(self, dims,
                                      os.path.join(self._prefs.get("last_dir", ""),
                                                   "%s_%s.mp4" % (stem, spec.variable)),
                                      ffmpeg_available())
        if dlg.exec() != dlg.Accepted:
            return
        v = dlg.values()
        prog = dialogs.ProgressDialog(self, "导出动画")
        try:
            from ..core.animate import animate
            path = animate(spec, self._source, dim=v["dim"], out_path=v["path"],
                           fps=v["fps"], start=v["start"], stop=v["stop"],
                           step=v["step"],
                           progress=lambda d, t: prog.set_progress(d, t, "渲染 %d/%d" % (d, t)),
                           on_cancel=prog.cancelled)
            prog.set_progress(1, 1, "完成")
            self._info("动画已导出", path, icon="info")
        except Exception as exc:                        # noqa: BLE001
            self._error("导出动画失败", str(exc))
        finally:
            prog.finish()

    def batch_plot(self) -> None:
        dlg = dialogs.BatchDialog(self, self._prefs.get("last_dir", ""),
                                  os.path.join(self._prefs.get("last_dir", ""), "figures"))
        if dlg.exec() != dlg.Accepted:
            return
        v = dlg.values()
        if not v["input"] or not os.path.exists(v["input"]):
            self._error("路径无效", "请选择一个存在的数据目录或文件。")
            return
        from ..core.batch import batch_run, find_datasets, write_batch_report
        paths = [v["input"]] if os.path.isfile(v["input"]) else \
            find_datasets(v["input"], recursive=v["recursive"])
        if not paths:
            self._info("没有找到数据", "该目录下没有可识别的数据文件。")
            return

        spec = self._collect_spec()
        prog = dialogs.ProgressDialog(self, "批量出图")
        try:
            result = batch_run(paths, spec, out_dir=v["out"], pattern=v["pattern"],
                               fmt=v["format"], dpi=v["dpi"], over_dim=v["over_dim"],
                               progress=lambda d, t, n: prog.set_progress(d, t, n),
                               stop_flag=prog.cancelled)
            report = write_batch_report(result, os.path.join(v["out"], "_batch_report.txt"))
            self._info("批量完成",
                       "成功 %d / 失败 %d\n报告：%s"
                       % (result.n_ok, result.n_fail, report), icon="info")
        except Exception as exc:                        # noqa: BLE001
            self._error("批量出图失败", str(exc))
        finally:
            prog.finish()

    def save_spec(self) -> None:
        if self._source is None:
            return
        default = os.path.join(self._prefs.get("last_dir", ""),
                               "%s.plot.yaml" % self._spec.variable)
        path, _ = QFileDialog.getSaveFileName(self, "保存绘图配置", default,
                                              "YAML (*.yaml);;JSON (*.json)")
        if not path:
            return
        try:
            self._collect_spec().save(path)
            self.hint_label.setText("配置已保存 %s" % path)
        except Exception as exc:                        # noqa: BLE001
            self._error("保存失败", str(exc))

    def load_spec(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "载入绘图配置", self._prefs.get("last_dir", ""),
            "配置文件 (*.yaml *.yml *.json);;所有文件 (*)")
        if not path:
            return
        try:
            spec = PlotSpec.load(path)
        except Exception as exc:                        # noqa: BLE001
            self._error("载入失败", str(exc))
            return
        if self._source is None:
            self._spec = spec
            return
        if spec.variable and spec.variable not in self._source.variables:
            self._info("变量不存在",
                       "配置里的变量「%s」不在当前数据集中。" % spec.variable)
            return
        self._spec = spec
        self.source_panel.select_variable(spec.variable)
        self._sync_panels_from_spec()
        self.request_render()

    def save_session(self) -> None:
        if self._source is None:
            return
        default = os.path.join(self._prefs.get("last_dir", ""), "session.ncs.yaml")
        path, _ = QFileDialog.getSaveFileName(self, "保存会话", default,
                                              "NCSight 会话 (*.ncs.yaml);;所有文件 (*)")
        if not path:
            return
        self._session = Session.create(self._source.path)
        self._session.add(self._collect_spec())
        try:
            self._session.save(path)
            self.hint_label.setText("会话已保存 %s" % path)
        except Exception as exc:                        # noqa: BLE001
            self._error("保存失败", str(exc))

    def load_session(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开会话", self._prefs.get("last_dir", ""),
            "NCSight 会话 (*.ncs.yaml *.yaml *.json);;所有文件 (*)")
        if not path:
            return
        try:
            sess = Session.load(path)
        except Exception as exc:                        # noqa: BLE001
            self._error("打开失败", str(exc))
            return
        self._session = sess
        if sess.dataset and os.path.exists(sess.dataset):
            self.open_dataset(sess.dataset)
        cur = sess.current()
        if cur is not None:
            self._spec = cur
            self.source_panel.select_variable(cur.variable)
            self._sync_panels_from_spec()
            self.request_render()

    # ==================================================================
    # 分析（M3）
    # ==================================================================
    def analyze_anomaly(self) -> None:
        if self._source is None:
            return
        from ..core.analyze import Analyzer
        spec = self._collect_spec()
        vi = self._source.variables.get(spec.variable)
        if vi is None or vi.ndim < 2:
            self._info("无法计算距平", "该变量没有可用于平均的维度。")
            return
        dim = vi.dims[0] if vi.ndim > 2 else "time"
        if "time" in vi.dims:
            dim = "time"
        elif vi.ndim < 3:
            self._info("无法计算距平",
                       "变量 %s 没有时间维或更高维，无法求平均作为参考。" % spec.variable)
            return
        try:
            an = Analyzer(self._source)
            clim = an.composite(spec.variable, dim, "mean")
            anom = an.anomaly(spec.variable, clim, spec.select)
        except Exception as exc:                        # noqa: BLE001
            self._error("计算失败", str(exc))
            return

        # 用距平作为新的绘图数据（直接画在画布上，不改 spec 的变量）
        from ..core.plot.base import render as _render
        self._render_custom(anom, spec, title="%s 距平（相对 %s 维平均）"
                            % (anom.label, dim))

    def analyze_region_series(self) -> None:
        if self._source is None:
            return
        spec = self._collect_spec()
        vi = self._source.variables.get(spec.variable)
        if vi is None or vi.ndim < 3:
            self._info("无法提取时间序列",
                       "变量 %s 需要至少三维（含时间维）才能做区域平均序列。"
                       % spec.variable)
            return
        bbox = spec.bbox
        if not bbox:
            self._info("请先设定区域",
                       "请先用「圈选区域」模式在图上拉一个框，"
                       "或在「区域范围」里输入经纬度后重试。")
            return
        try:
            from ..core.analyze import Analyzer
            an = Analyzer(self._source)
            x, y = an.region_mean_series(spec.variable, bbox)
        except Exception as exc:                        # noqa: BLE001
            self._error("计算失败", str(exc))
            return

        self._show_series(x, y, "%s 区域平均（%s）" % (spec.variable, bbox),
                          spec.variable, vi.units)

    def _show_series(self, x, y, title: str, name: str, units: str) -> None:
        from PySide6.QtWidgets import QDialog, QVBoxLayout
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        import numpy as np
        from .. import style

        style.apply_theme(base_fontsize=9)
        d = QDialog(self)
        d.setWindowTitle(title)
        d.resize(760, 420)
        lay = QVBoxLayout(d)
        fig = Figure(figsize=(7.2, 3.6), dpi=110, facecolor="#ffffff")
        ax = fig.add_subplot(111)
        m = np.isfinite(y)
        ax.plot(x[m], y[m], color=style.COLORS["accent"], linewidth=1.2)
        ax.set_xlabel("序号 / 时间")
        ax.set_ylabel("%s [%s]" % (name, units) if units else name)
        ax.set_title(title, loc="left")
        style.tidy_axes(ax, grid=True)
        canvas = FigureCanvasQTAgg(fig)
        lay.addWidget(canvas)
        canvas.draw()
        d.exec()

    def analyze_vector_magnitude(self) -> None:
        if self._source is None:
            return
        spec = self._collect_spec()
        vi = self._source.variables.get(spec.variable)
        if vi is None or not vi.vector_partner:
            self._info("没有矢量配对",
                       "变量 %s 未找到配对的 U/V 分量。\n"
                       "可在「数据」面板的「矢量配对」里手动指定后重试。" % spec.variable)
            return
        try:
            from ..core.analyze import Analyzer
            mag = Analyzer(self._source).vector_magnitude(
                spec.variable, vi.vector_partner, spec.select)
        except Exception as exc:                        # noqa: BLE001
            self._error("计算失败", str(exc))
            return
        self._render_custom(mag, spec, title="%s / %s 矢量大小"
                            % (spec.variable, vi.vector_partner))

    def _render_custom(self, fd, spec, title: str = "") -> None:
        """直接用一份算好的 FieldData 画图（绕过变量读取）。"""
        from ..core.plot.base import (make_cmap_norm, make_figure,
                                      attach_colorbar, get_palette_array)
        from .. import style
        import numpy as np

        style.apply_theme(base_fontsize=spec.fontsize)
        spec2 = spec.clone(title=title or spec.title)
        palette = get_palette_array(self._source)
        cmap, norm, _ = make_cmap_norm(fd, spec2, palette)

        fig = self.plot_view.prepare()
        ax = fig.add_subplot(111)
        mesh = ax.pcolormesh(fd.x, fd.y, np.ma.masked_invalid(fd.values),
                             cmap=cmap, norm=norm, shading="auto", rasterized=True)
        from ..core.overlay import add_overlays_plain
        add_overlays_plain(ax, spec2.overlays)
        ax.set_xlabel("经度")
        ax.set_ylabel("纬度")
        ax.set_title(title, loc="left")
        style.tidy_axes(ax, box=True)
        attach_colorbar(fig, ax, mesh, spec2, fd.caption)

        from ..core.plot.base import RenderResult
        self.plot_view.finished(RenderResult(fig=fig, ax=ax, spec=spec2,
                                             data=fd, mappable=mesh))
        self.hint_label.setText("已显示：%s" % title)

    # ==================================================================
    # 其他
    # ==================================================================
    def _toggle_left(self, checked: bool) -> None:
        self.source_panel.setVisible(checked)

    def _toggle_right(self, checked: bool) -> None:
        self.controls_host.setVisible(checked)

    def show_about(self) -> None:
        runtime = {}
        import sys
        runtime["Python"] = sys.version.split()[0]
        for mod in ("numpy", "matplotlib", "netCDF4", "xarray", "cartopy",
                    "pyproj", "scipy", "PySide6", "cmocean", "cmcrameri"):
            try:
                m = __import__(mod)
                runtime[mod] = str(getattr(m, "__version__", "?"))
            except Exception:                           # noqa: BLE001
                runtime[mod] = "未安装"
        dialogs.AboutDialog(self, runtime)

    def show_cli_help(self) -> None:
        text = (
            "命令行与图形界面共用同一套渲染内核，所以同一张图两种方式都能出。\n\n"
            "  ncsight info  data.nc\n"
            "  ncsight plot  data.nc -v sst --projection Robinson -o sst.png\n"
            "  ncsight plot  data.nc --spec sst.plot.yaml\n"
            "  ncsight batch ./ncdata -o ./figures --format pdf\n"
            "  ncsight animate data.nc -v sst --dim time -o loop.mp4\n\n"
            "图形界面里保存的「绘图配置」(.plot.yaml) 可以直接\n"
            "用 ncsight plot --spec 复现，方便进 git 做版本管理。")
        self._info("命令行用法", text, icon="info")

    def _info(self, title: str, text: str, icon: str = "info") -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Information if icon == "info" else QMessageBox.Warning)
        box.exec()

    def _error(self, title: str, text: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Warning)
        box.exec()

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        try:
            g = self.geometry()
            self._prefs["window"] = {"w": g.width(), "h": g.height()}
            save_prefs(self._prefs)
            # 先停渲染线程（它会 close 掉工作线程自己持有的数据集句柄），
            # 再关主线程的数据集
            try:
                self.renderer.shutdown()
            except Exception:                           # noqa: BLE001
                pass
            if self._source is not None:
                self._source.close()
        except Exception:                               # noqa: BLE001
            pass
        super().closeEvent(event)
