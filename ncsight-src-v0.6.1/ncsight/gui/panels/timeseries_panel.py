# -*- coding: utf-8 -*-
"""
时序分析面板
============
把「一个变量 + 很多天的卫星数据」变成一条时间序列，并一键算出科学指标。

这是本软件对科研流程提升最大的一块：以前要写脚本循环读几百个文件、
算区域平均、拼时间轴、再逐个算趋势/谱/季节循环；现在选好文件点一下就行。

面板里能做：
  * 添加多个 nc 文件（支持多选、也支持直接加整个文件夹）
  * 选变量、选区域统计方式（区域平均/最大/最小/中位数/分位数…）
  * 勾选要算的科学指标（趋势、MK 检验、Sen 斜率、季节循环、功率谱、自相关…）
  * 一键出「诊断图」或只出「功率谱」
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ...core.indicators import INDICATOR_CATALOG
from ...core.series import STATS, SeriesBuilder
from ..theme import UI
from .base import PanelBase, Section, button, label, two_col


class TimeSeriesPanel(PanelBase):
    title = "时序分析"
    icon_name = "series"

    #: 请求主窗口弹文件对话框 —— 数据集清单由主窗口统一持有，
    #: 面板不自己维护一份副本，避免两处状态不一致。
    addFilesRequested = Signal()
    addDirRequested = Signal()

    def _build(self) -> None:
        self._paths: list[str] = []
        self._built = False
        self._want_spectrum = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(8)

        # ---------- 数据文件 ----------
        s = Section("数据文件", expanded=True)
        self.count_label = label("尚未添加文件", wrap=True)
        s.add_widget(self.count_label)

        b_add = button("＋ 添加 nc 文件…", self._add_files)
        b_dir = button("添加整个文件夹…", self._add_dir)
        s.add_widget(two_col(b_add, b_dir))

        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(112)
        self.file_list.setStyleSheet(
            "QListWidget{background:%s;border:1px solid %s;border-radius:5px;"
            "font-size:11px;}" % (UI["panel"], UI["border"]))
        s.add_widget(self.file_list)

        b_clear = button("清空", self._clear)
        b_hint = button("说明", self._show_help)
        s.add_widget(two_col(b_clear, b_hint))
        lay.addWidget(s)

        # ---------- 统计口径 ----------
        s2 = Section("统计口径", expanded=True)
        self.var_combo = QComboBox()
        self.var_combo.setEditable(True)
        s2.add_row("变量", self.var_combo)

        self.stat_combo = QComboBox()
        for key, name in STATS:
            self.stat_combo.addItem(name, key)
        s2.add_row("空间统计", self.stat_combo)

        s2.add_widget(label(
            "区域平均默认按 cos(纬度) 加权。区域范围沿用「数据」面板里的设置；"
            "也可以在那里用「圈选区域」模式在图上拉框。", wrap=True))
        lay.addWidget(s2)

        # ---------- 指标 ----------
        s3 = Section("科学指标", expanded=True)
        self._checks: dict[str, QCheckBox] = {}
        default_on = {"trend", "running", "summary", "mk", "sen"}
        for group, items in INDICATOR_CATALOG.items():
            head = label("<b>%s</b>" % group)
            head.setTextFormat(Qt.RichText)
            s3.add_widget(head)
            grid = QWidget()
            g = QGridLayout(grid)
            g.setContentsMargins(4, 0, 0, 6)
            g.setSpacing(3)
            for i, (key, name, desc) in enumerate(items):
                cb = QCheckBox(name)
                cb.setChecked(key in default_on)
                cb.setToolTip(desc)
                self._checks[key] = cb
                g.addWidget(cb, i // 2, i % 2)
            s3.add_widget(grid)

        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 2, 0, 0)
        h.setSpacing(4)
        b_all = button("全选", lambda: self._set_all(True))
        b_none = button("全不选", lambda: self._set_all(False))
        h.addWidget(b_all); h.addWidget(b_none)
        s3.add_widget(row)
        lay.addWidget(s3)

        # ---------- 执行 ----------
        s4 = Section("出图", expanded=True)
        # ★ 显式的模式开关 ★
        # 时序面板必须参与 _collect_spec()，否则任何一个防抖重绘都会把
        # 「时序」结果覆盖回地图。用一个开关表达"现在处于时序模式"。
        self.mode_check = QCheckBox("用时序模式出图")
        self.mode_check.setToolTip(
            "勾上后，画布显示时序诊断图；取消勾选或点左侧变量即回到地图模式")
        s4.add_widget(self.mode_check)

        b_run = button("计算并绘制诊断图", self._run)
        b_run.setObjectName("primaryButton")
        s4.add_widget(b_run)
        b_spec = button("只画功率谱", self._run_spectrum)
        b_all = button("全部指标 + 谱", self._run_all)
        s4.add_widget(two_col(b_spec, b_all))
        self.status = label("", wrap=True)
        s4.add_widget(self.status)
        lay.addWidget(s4)

        self._placeholder = label(
            "先添加文件，再点「计算并绘制」。\n"
            "时间轴优先读文件里的 time 变量，读不到就从文件名的日期"
            "（如 20180105）解析，都没有才退回序号。", wrap=True)
        lay.addWidget(self._placeholder)

    # ------------------------------------------------------------------
    # 文件管理
    # ------------------------------------------------------------------
    def _refresh_list(self) -> None:
        self.file_list.clear()
        for p in self._paths:
            it = QListWidgetItem(os.path.basename(p))
            it.setToolTip(p)
            self.file_list.addItem(it)
        n = len(self._paths)
        if n == 0:
            self.count_label.setText("尚未添加文件")
        else:
            self.count_label.setText("已添加 <b>%d</b> 个文件" % n)
            self.count_label.setTextFormat(Qt.RichText)
        self._built = False
        if self._paths:
            self._probe_variables()

    def _add_files(self) -> None:
        # 交给主窗口统一处理：清单只有一份
        self.addFilesRequested.emit()

    def _add_dir(self) -> None:
        self.addDirRequested.emit()

    def set_paths(self, paths) -> None:
        """主窗口把数据集清单推过来（清单的唯一持有者是主窗口）。"""
        ap = []
        for p in (paths or []):
            p = os.path.abspath(p)
            if p not in ap:
                ap.append(p)
        if ap == self._paths:
            return
        self._paths = ap
        self.var_combo.clear()
        self._refresh_list()

    def _extend(self, paths) -> None:
        seen = set(os.path.abspath(p) for p in self._paths)
        added = 0
        for p in paths:
            ap = os.path.abspath(p)
            if ap not in seen:
                seen.add(ap)
                self._paths.append(ap)
                added += 1
        self._refresh_list()
        self.status.setText("新增 %d 个文件" % added)

    def _clear(self) -> None:
        self._paths = []
        self._refresh_list()
        self.status.setText("已清空")

    def _probe_variables(self) -> None:
        """从第一个文件里读出可制图变量，填进下拉框。"""
        if self.var_combo.count():
            return
        try:
            from ...core.reader import NcSource
            src = NcSource(self._paths[0])
            names = [v.name for v in src.plottable()]
            src.close()
            for n in names:
                self.var_combo.addItem(n)
            self._built = True
        except Exception as exc:                        # noqa: BLE001
            self.status.setText("读取变量列表失败：%s" % exc)

    # ------------------------------------------------------------------
    def _set_all(self, on: bool) -> None:
        for cb in self._checks.values():
            cb.setChecked(on)

    def selected_indicators(self) -> list:
        return [k for k, cb in self._checks.items() if cb.isChecked()]

    def _show_help(self) -> None:
        self.status.setText(
            "时间轴识别顺序：① 文件里的 time 变量 → ② 文件名中的日期 → ③ 样本序号。")

    # ------------------------------------------------------------------
    # 触发主窗口渲染
    # ------------------------------------------------------------------
    def _emit(self, kind: str, indicators: list) -> None:
        if hasattr(self, "mode_check"):
            self.mode_check.setChecked(True)
        if not self._paths:
            self._status_error("请先添加 nc 文件")
            return
        inds = indicators if indicators else self.selected_indicators()
        if not inds:
            self._status_error("请至少勾选一个指标")
            return
        var = self.var_combo.currentText().strip()
        self.status.setText("正在计算 %d 个文件 × %d 个指标…"
                            % (len(self._paths), len(inds)))
        changes = {
            "kind": kind,
            "indicators": list(inds),
            "series_stat": self.stat_combo.currentData() or "mean",
            "series_variable": var,
            "variable": var,
        }
        self.runSeries.emit(list(self._paths), changes)

    def _status_error(self, msg: str) -> None:
        self.status.setText(msg)

    def _run(self) -> None:
        self._want_spectrum = False
        self._emit("series", [])

    def _run_spectrum(self) -> None:
        self._want_spectrum = True
        self._emit("spectrum", ["spectrum", "summary"])

    def _run_series_mode(self) -> None:
        self._want_spectrum = False

    def _run_all(self) -> None:
        self._want_spectrum = False
        inds = ["trend", "mk", "sen", "running", "summary", "anomaly",
                "seasonal", "spectrum", "autocorr", "variability"]
        self._emit("series", inds)

    # ------------------------------------------------------------------
    # 参与 PlotSpec 的收集：勾了时序模式才改 spec
    def _apply(self, spec) -> None:
        if not (hasattr(self, "mode_check") and self.mode_check.isChecked()):
            return
        if not self._paths:
            return
        inds = self.selected_indicators()
        spec.kind = "spectrum" if getattr(self, "_want_spectrum", False) else "series"
        if inds:
            spec.indicators = list(inds)
        spec.series_stat = self.stat_combo.currentData() or "mean"
        var = self.var_combo.currentText().strip()
        if var:
            spec.series_variable = var
        spec.screen_cells = 0            # 时序点少，不做降采样
        # 清掉「色标」面板残留的 vmin/vmax / 对数轴等设置：
        # 那些是给地图色标用的，套到时序曲线上会把纵轴拉得离谱。
        spec.vmin = None
        spec.vmax = None
        spec.log = False
        spec.center_zero = False

    def set_mode(self, on: bool) -> None:
        """外部（主窗口）切换时序模式。"""
        if hasattr(self, "mode_check"):
            self.mode_check.setChecked(bool(on))

    def report(self, text: str) -> None:
        self.status.setText(text)
