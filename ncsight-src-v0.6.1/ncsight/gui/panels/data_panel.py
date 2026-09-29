# -*- coding: utf-8 -*-
"""
控制面板 · 数据（Array(s)）
==========================
对应 Panoply 的 Array(s) 面板：选变量、多功能维切片、划区域。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ...core.detect import VarKind
from ...core.plot.base import PLOT_KINDS
from ..theme import UI
from .base import PanelBase, Section, button, check, combo, label, line, spin, two_col


class DataPanel(PanelBase):
    title = "数据"

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---------- 变量与图型 ----------
        s = Section("变量与图型", expanded=True)
        self.var_combo = combo([], None)
        self.hook(self.var_combo, "currentIndexChanged")
        s.add_row("变量", self.var_combo)

        self.kind_combo = combo([(k, v) for k, v in PLOT_KINDS.items()], "map")
        self.hook(self.kind_combo, "currentIndexChanged")
        s.add_row("图型", self.kind_combo)

        self.pair_combo = combo([], None)
        self.hook(self.pair_combo, "currentIndexChanged")
        s.add_row("矢量配对", self.pair_combo)
        lay.addWidget(s)
        self.section_var = s

        # ---------- 切片 ----------
        self.slice_section = Section("维度切片", expanded=True)
        lay.addWidget(self.slice_section)

        # ---------- 区域 ----------
        s3 = Section("区域范围（经纬度）", expanded=False)
        self.lon_min = spin(-360, 360, 0, 1, 2)
        self.lon_max = spin(-360, 360, 0, 1, 2)
        self.lat_min = spin(-90, 90, 0, 1, 2)
        self.lat_max = spin(-90, 90, 0, 1, 2)
        for w in (self.lon_min, self.lon_max, self.lat_min, self.lat_max):
            self.hook(w, "valueChanged")
        s3.add_row("经度 起", self.lon_min)
        s3.add_row("经度 止", self.lon_max)
        s3.add_row("纬度 起", self.lat_min)
        s3.add_row("纬度 止", self.lat_max)
        self.bbox_check = check("启用区域裁切", False)
        self.hook(self.bbox_check, "toggled")
        s3.add_row("", self.bbox_check)
        b1 = button("用整幅范围填充", self._fill_full_extent, flat=True)
        b2 = button("清空", self._clear_bbox, flat=True)
        s3.add_widget(two_col(b1, b2))
        s3.add_widget(label("提示：先在图上框选区域后点「填入」，可自动带回坐标。",
                            wrap=True))
        lay.addWidget(s3)
        self.section_bbox = s3
        self._slice_widgets: List = []
        lay.addStretch(1)

    # ------------------------------------------------------------------
    def _fill_full_extent(self) -> None:
        if self._source is None:
            return
        lat_ax, lon_ax = self._source.lonlat_axes()
        if lon_ax is None or lat_ax is None:
            return
        self.lon_min.setValue(min(lon_ax.values))
        self.lon_max.setValue(max(lon_ax.values))
        self.lat_min.setValue(min(lat_ax.values))
        self.lat_max.setValue(max(lat_ax.values))
        self.bbox_check.setChecked(True)
        self.notify()

    def _clear_bbox(self) -> None:
        self.bbox_check.setChecked(False)
        self.notify()

    # ------------------------------------------------------------------
    def set_source(self, source) -> None:
        super().set_source(source)
        self.var_combo.blockSignals(True)
        self.var_combo.clear()
        if source is not None:
            for v in source.plottable():
                self.var_combo.addItem("%s  ·  %s" % (v.name, v.kind.value), v.name)
        self.var_combo.blockSignals(False)
        self._rebuild_slice_controls()

    def _current_var(self):
        if self._source is None:
            return None
        return self._source.variables.get(self.var_combo.currentData() or "")

    def _rebuild_slice_controls(self) -> None:
        """按当前变量的维度重建切片控件。"""
        # 清空旧控件
        while self.slice_section.form.count():
            item = self.slice_section.form.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.slice_section._row = 0
        self._slice_widgets = []

        vi = self._current_var()
        if vi is None:
            self.slice_section.add_widget(label("先打开数据集"))
            return
        n_plot = min(2, vi.ndim)
        extra = vi.dims[:max(0, vi.ndim - n_plot)]
        if not extra:
            self.slice_section.add_widget(
                label("该变量是二维场，无需切片。"))
            return
        for i, dim in enumerate(extra):
            size = vi.shape[i]
            w = spin(0, max(0, size - 1), 0, 1)
            w.setToolTip("沿 %s 维取第几层（共 %d 层）" % (dim, size))
            self.hook(w, "valueChanged")
            self.slice_section.add_row("%s (0-%d)" % (dim, size - 1), w)
            self._slice_widgets.append((dim, w))

    # ------------------------------------------------------------------
    def _bind(self, spec) -> None:
        if spec.variable:
            idx = self.var_combo.findData(spec.variable)
            if idx >= 0:
                self.var_combo.setCurrentIndex(idx)
        self._rebuild_pair_combo(spec)
        idx = self.kind_combo.findData(spec.kind)
        if idx >= 0:
            self.kind_combo.setCurrentIndex(idx)
        else:
            self.kind_combo.setCurrentIndex(0)

        for dim, w in self._slice_widgets:
            w.setValue(int(spec.select.get(dim, 0) or 0))

        if spec.bbox and len(spec.bbox) == 4:
            self.bbox_check.setChecked(True)
            self.lon_min.setValue(spec.bbox[0])
            self.lon_max.setValue(spec.bbox[1])
            self.lat_min.setValue(spec.bbox[2])
            self.lat_max.setValue(spec.bbox[3])
        else:
            self.bbox_check.setChecked(False)

    def _rebuild_pair_combo(self, spec) -> None:
        self.pair_combo.blockSignals(True)
        self.pair_combo.clear()
        self.pair_combo.addItem("（无）", "")
        if self._source is not None:
            vi = self._source.variables.get(spec.variable)
            for name, v in self._source.variables.items():
                if name != spec.variable and v.is_plottable:
                    self.pair_combo.addItem(name, name)
            if vi and vi.vector_partner:
                idx = self.pair_combo.findData(vi.vector_partner)
                if idx >= 0:
                    self.pair_combo.setCurrentIndex(idx)
        idx = self.pair_combo.findData(spec.vector_variable or "")
        if idx >= 0:
            self.pair_combo.setCurrentIndex(idx)
        self.pair_combo.blockSignals(False)

    def _apply(self, spec) -> None:
        spec.variable = self.var_combo.currentData() or spec.variable
        spec.kind = self.kind_combo.currentData() or spec.kind
        spec.vector_variable = self.pair_combo.currentData() or ""

        for dim, w in self._slice_widgets:
            spec.select[dim] = int(w.value())

        if self.bbox_check.isChecked():
            spec.bbox = [self.lon_min.value(), self.lon_max.value(),
                         self.lat_min.value(), self.lat_max.value()]
            if spec.bbox[0] >= spec.bbox[1] or spec.bbox[2] >= spec.bbox[3]:
                spec.bbox = None
        else:
            spec.bbox = None
