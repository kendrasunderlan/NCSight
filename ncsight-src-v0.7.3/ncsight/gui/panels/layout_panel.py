# -*- coding: utf-8 -*-
"""
控制面板 · 版式（Layout / Labels）
=================================
对应 Panoply 的 Layout 与 Labels 面板，外加它那一长串 Plot Size 档位 ——
但我们不做 17 档尺寸，而是按期刊实际需要的宽度给预设。
"""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout

from ...style import FIGURE_PRESETS, FIGURE_PRESET_LABELS
from .base import (PanelBase, Section, check, combo, label, line, spin,
                   two_col)

_PRESET_ITEMS = [(k, "%s  ·  %.1f×%.1f cm" % (FIGURE_PRESET_LABELS.get(k, k),
                                              v[0], v[1]))
                 for k, v in FIGURE_PRESETS.items()]


class LayoutPanel(PanelBase):
    title = "版式"

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---------- 图幅 ----------
        s = Section("图幅尺寸", expanded=True)
        self.preset_combo = combo(_PRESET_ITEMS, "double")
        self.hook(self.preset_combo, "currentIndexChanged")
        s.add_row("预设", self.preset_combo)

        self.use_custom = check("自定义尺寸（英寸）", False)
        self.hook(self.use_custom, "toggled")
        s.add_row("", self.use_custom)
        self.w_in = spin(1.0, 80.0, 6.7, 0.1, 2)
        self.h_in = spin(1.0, 80.0, 3.9, 0.1, 2)
        self.hook(self.w_in, "valueChanged")
        self.hook(self.h_in, "valueChanged")
        s.add_row("宽", self.w_in)
        s.add_row("高", self.h_in)

        self.dpi = spin(50, 1200, 150, 10)
        self.hook(self.dpi, "valueChanged")
        s.add_row("屏幕 DPI", self.dpi)
        s.add_widget(label(
            "导出位图时用工具栏的导出对话框单独指定 DPI（默认 300）。", wrap=True))
        lay.addWidget(s)
        self.section_size = s

        # ---------- 文字 ----------
        s2 = Section("标题与标签", expanded=True)
        self.title_edit = line(placeholder="留空 = 自动用变量名 [单位]")
        self.hook(self.title_edit, "textChanged")
        s2.add_row("主标题", self.title_edit)

        self.subtitle_edit = line(placeholder="可选，显示在标题下方")
        self.hook(self.subtitle_edit, "textChanged")
        s2.add_row("副标题", self.subtitle_edit)

        self.xlabel_edit = line(placeholder="留空 = 自动（经度/纬度/时间…）")
        self.hook(self.xlabel_edit, "textChanged")
        s2.add_row("横轴标签", self.xlabel_edit)

        self.ylabel_edit = line(placeholder="留空 = 自动")
        self.hook(self.ylabel_edit, "textChanged")
        s2.add_row("纵轴标签", self.ylabel_edit)

        self.fontsize = spin(5.0, 24.0, 9.0, 0.5, 1)
        self.hook(self.fontsize, "valueChanged")
        s2.add_row("基准字号", self.fontsize)

        self.stats_check = check("图上标注统计量（n/min/max/mean/std）", False)
        self.hook(self.stats_check, "toggled")
        s2.add_row("", self.stats_check)

        self.invert_check = check("纵轴反向（深度向下）", False)
        self.hook(self.invert_check, "toggled")
        s2.add_row("", self.invert_check)
        lay.addWidget(s2)
        self.section_text = s2

        lay.addStretch(1)

    # ------------------------------------------------------------------
    def _bind(self, spec) -> None:
        i = self.preset_combo.findData(spec.preset)
        self.preset_combo.setCurrentIndex(max(0, i))
        if spec.figsize:
            self.use_custom.setChecked(True)
            self.w_in.setValue(float(spec.figsize[0]))
            self.h_in.setValue(float(spec.figsize[1]))
        else:
            self.use_custom.setChecked(False)
            from ...style import figure_preset
            w, h = figure_preset(spec.preset)
            self.w_in.setValue(w)
            self.h_in.setValue(h)
        self.dpi.setValue(int(spec.dpi))
        self.title_edit.setText(spec.title or "")
        self.subtitle_edit.setText(spec.subtitle or "")
        self.xlabel_edit.setText(spec.xlabel or "")
        self.ylabel_edit.setText(spec.ylabel or "")
        self.fontsize.setValue(float(spec.fontsize))
        self.stats_check.setChecked(bool(spec.show_stats))
        self.invert_check.setChecked(bool(spec.invert_y))

    def _apply(self, spec) -> None:
        spec.preset = self.preset_combo.currentData() or "double"
        spec.figsize = ([float(self.w_in.value()), float(self.h_in.value())]
                        if self.use_custom.isChecked() else None)
        spec.dpi = int(self.dpi.value())
        spec.title = self.title_edit.text().strip() or None
        spec.subtitle = self.subtitle_edit.text().strip() or None
        spec.xlabel = self.xlabel_edit.text().strip() or None
        spec.ylabel = self.ylabel_edit.text().strip() or None
        spec.fontsize = float(self.fontsize.value())
        spec.show_stats = self.stats_check.isChecked()
        spec.invert_y = self.invert_check.isChecked()
