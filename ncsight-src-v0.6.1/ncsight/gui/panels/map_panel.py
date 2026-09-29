# -*- coding: utf-8 -*-
"""
控制面板 · 地图（Map / Overlays / Grid / Contours）
==================================================
对应 Panoply 的 Map Projection、Map Overlays、Grid、Contours 四块面板，
这里合并成一个，减少侧栏来回切换的成本。
"""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QVBoxLayout

from ...core.overlay import RESOLUTIONS, cartopy_available
from ...core.plot.base import PROJECTIONS
from ..theme import UI
from .base import (PanelBase, Section, button, check, combo, label, line,
                   spin, two_col)


class MapPanel(PanelBase):
    title = "地图"

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---------- 投影 ----------
        s = Section("投影", expanded=True)
        self.proj_combo = combo(PROJECTIONS, "PlateCarree")
        self.hook(self.proj_combo, "currentIndexChanged")
        s.add_row("投影", self.proj_combo)

        self.lon0 = spin(-360, 360, 0, 5, 1)
        self.lat0 = spin(-90, 90, 30, 5, 1)
        self.hook(self.lon0, "valueChanged")
        self.hook(self.lat0, "valueChanged")
        s.add_row("中心经度", self.lon0)
        s.add_row("中心纬度", self.lat0)
        s.add_widget(label(
            "等距圆柱最快；其余投影会先自动降采样再投影（大网格必需）。", wrap=True))
        if not cartopy_available():
            s.add_widget(label("⚠ 未检测到 cartopy，非等距圆柱投影将不可用。",
                               wrap=True))
        lay.addWidget(s)
        self.section_proj = s

        # ---------- 网格线 ----------
        s2 = Section("经纬网", expanded=True)
        self.grid_check = check("显示经纬网", True)
        self.hook(self.grid_check, "toggled")
        s2.add_row("", self.grid_check)
        self.grid_labels = check("显示刻度标签", True)
        self.hook(self.grid_labels, "toggled")
        s2.add_row("", self.grid_labels)
        lay.addWidget(s2)
        self.section_grid = s2

        # ---------- 底图叠加 ----------
        s3 = Section("底图叠加", expanded=True)
        self.res_combo = combo(RESOLUTIONS, "110m")
        self.hook(self.res_combo, "currentIndexChanged")
        s3.add_row("精度", self.res_combo)

        self.cb_coast = check("海岸线", True)
        self.cb_borders = check("国界", False)
        self.cb_lakes = check("湖泊", False)
        self.cb_rivers = check("河流", False)
        self.cb_land = check("陆地填充", False)
        self.cb_ocean = check("海洋填充", False)
        for w in (self.cb_coast, self.cb_borders, self.cb_lakes,
                  self.cb_rivers, self.cb_land, self.cb_ocean):
            self.hook(w, "toggled")
            s3.add_row("", w)

        self.line_color = line("#3f3f46")
        self.hook(self.line_color, "textChanged")
        s3.add_row("线颜色", self.line_color)
        self.line_width = spin(0.1, 4.0, 0.45, 0.05, 2)
        self.hook(self.line_width, "valueChanged")
        s3.add_row("线宽", self.line_width)

        self.shp_edit = line(placeholder="自定义 .shp（研究区/断面/EEZ）")
        self.hook(self.shp_edit, "textChanged")
        s3.add_widget(two_col(self.shp_edit,
                              button("浏览…", self._pick_shp, flat=True)))
        lay.addWidget(s3)
        self.section_overlay = s3

        # ---------- 等值线 ----------
        s4 = Section("等值线", expanded=False)
        self.contour_check = check("显示等值线", False)
        self.hook(self.contour_check, "toggled")
        s4.add_row("", self.contour_check)
        self.contour_n = spin(2, 40, 8, 1)
        self.hook(self.contour_n, "valueChanged")
        s4.add_row("层数", self.contour_n)
        self.contour_labels = check("标注数值", True)
        self.hook(self.contour_labels, "toggled")
        s4.add_row("", self.contour_labels)
        lay.addWidget(s4)
        self.section_contour = s4

        lay.addStretch(1)

    # ------------------------------------------------------------------
    def _pick_shp(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择边界文件", "", "Shapefile (*.shp);;所有文件 (*)")
        if path:
            self.shp_edit.setText(path)

    # ------------------------------------------------------------------
    def _bind(self, spec) -> None:
        i = self.proj_combo.findData(spec.projection)
        self.proj_combo.setCurrentIndex(max(0, i))
        self.lon0.setValue(float(spec.lon0 or 0))
        self.lat0.setValue(float(spec.lat0 or 0))
        self.grid_check.setChecked(bool(spec.show_grid))
        self.grid_labels.setChecked(bool(spec.grid_labels))

        ov = spec.overlays
        i = self.res_combo.findData(ov.resolution)
        self.res_combo.setCurrentIndex(max(0, i))
        self.cb_coast.setChecked(ov.coastline)
        self.cb_borders.setChecked(ov.borders)
        self.cb_lakes.setChecked(ov.lakes)
        self.cb_rivers.setChecked(ov.rivers)
        self.cb_land.setChecked(ov.land)
        self.cb_ocean.setChecked(ov.ocean)
        self.line_color.setText(ov.line_color)
        self.line_width.setValue(float(ov.line_width))
        self.shp_edit.setText(ov.shapefile or "")

        self.contour_check.setChecked(bool(spec.show_contours))
        self.contour_n.setValue(int(spec.contour_levels))
        self.contour_labels.setChecked(bool(spec.contour_labels))

    def _apply(self, spec) -> None:
        spec.projection = self.proj_combo.currentData() or "PlateCarree"
        spec.lon0 = float(self.lon0.value())
        spec.lat0 = float(self.lat0.value())
        spec.show_grid = self.grid_check.isChecked()
        spec.grid_labels = self.grid_labels.isChecked()

        ov = spec.overlays
        ov.resolution = self.res_combo.currentData() or "110m"
        ov.coastline = self.cb_coast.isChecked()
        ov.borders = self.cb_borders.isChecked()
        ov.lakes = self.cb_lakes.isChecked()
        ov.rivers = self.cb_rivers.isChecked()
        ov.land = self.cb_land.isChecked()
        ov.ocean = self.cb_ocean.isChecked()
        ov.line_color = self.line_color.text().strip() or "#3f3f46"
        ov.line_width = float(self.line_width.value())
        ov.shapefile = self.shp_edit.text().strip() or None

        spec.show_contours = self.contour_check.isChecked()
        spec.contour_levels = int(self.contour_n.value())
        spec.contour_labels = self.contour_labels.isChecked()
