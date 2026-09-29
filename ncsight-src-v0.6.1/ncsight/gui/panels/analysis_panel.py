# -*- coding: utf-8 -*-
"""
控制面板 · 筛选与分析（M3 科研增强）
==================================
Panoply 只会「画全图」，这里补上它最缺的两块：
  * 掩膜：抹掉陆地、按质量标记过滤、按数值区间过滤、用 shp 圈研究区
  * 快捷分析：一键切成距平图 / 矢量场 / 纬向平均 / Hovmöller
"""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QGridLayout, QVBoxLayout, QWidget

from .base import (PanelBase, Section, button, check, combo, label, line,
                   spin, two_col)


class AnalysisPanel(PanelBase):
    title = "筛选与分析"

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---------- 一键切换图型 ----------
        s = Section("快捷分析", expanded=True)
        grid = QWidget()
        g = QGridLayout(grid)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(6)
        quick = [
            ("距平图", "anomaly", "居中于零 + 发散色表，做异常/变化分析"),
            ("海温/叶绿素", "thermal", "切到海洋学专用色表"),
            ("矢量场", "vector", "用配对的 U/V 分量画风场或流场"),
            ("纬向平均", "zonal", "沿经度平均 → 随纬度变化的廓线"),
            ("Hovmöller", "hov", "时间-经度/纬度剖面"),
            ("等值线", "contour", "叠加等值线辅助读值"),
        ]
        for i, (text, key, tip) in enumerate(quick):
            b = button(text, lambda _=False, k=key: self._quick(k))
            b.setToolTip(tip)
            g.addWidget(b, i // 2, i % 2)
        s.add_widget(grid)
        s.add_widget(label(
            "「距平图」会同时把色表切到 balance 并把色标居中于零；"
            "若要看相对自身时间平均的距平，请在命令行用 analyze。", wrap=True))
        lay.addWidget(s)
        self.section_quick = s

        # ---------- 掩膜 ----------
        s2 = Section("掩膜 / 数据筛选", expanded=False)

        self.mask_land = check("抹掉陆地（只保留海洋）", False)
        self.hook(self.mask_land, "toggled")
        s2.add_row("", self.mask_land)

        self.mask_range_check = check("按数值区间保留", False)
        self.hook(self.mask_range_check, "toggled")
        s2.add_row("", self.mask_range_check)
        self.mask_lo = spin(-1e12, 1e12, 0, 0.1, 4)
        self.mask_hi = spin(-1e12, 1e12, 1, 0.1, 4)
        self.hook(self.mask_lo, "valueChanged")
        self.hook(self.mask_hi, "valueChanged")
        s2.add_row("下限", self.mask_lo)
        s2.add_row("上限", self.mask_hi)

        self.qual_combo = combo([("", "（不使用质量过滤）")], "")
        self.hook(self.qual_combo, "currentIndexChanged")
        s2.add_row("质量变量", self.qual_combo)
        self.qual_accept = line("0:2", placeholder="如 0:2 或 0,1,2")
        self.hook(self.qual_accept, "textChanged")
        s2.add_row("接受等级", self.qual_accept)

        self.mask_shp = line(placeholder="用 .shp 圈定研究区")
        self.hook(self.mask_shp, "textChanged")
        s2.add_widget(two_col(self.mask_shp,
                              button("浏览…", self._pick_shp, flat=True)))
        s2.add_widget(label(
            "提示：掩膜运算量随格点数增长，建议先在上面设定「区域范围」再打掩膜。",
            wrap=True))
        lay.addWidget(s2)
        self.section_mask = s2

        # ---------- 矢量场 ----------
        s3 = Section("矢量场参数", expanded=False)
        self.vec_step = spin(1, 200, 18, 1)
        self.hook(self.vec_step, "valueChanged")
        s3.add_row("抽样步长", self.vec_step)
        self.vec_scale = spin(0.0, 1e6, 0.0, 0.5, 2)
        self.hook(self.vec_scale, "valueChanged")
        s3.add_row("缩放 (0=自动)", self.vec_scale)
        self.vec_width = spin(0.1, 4.0, 0.7, 0.1, 2)
        self.hook(self.vec_width, "valueChanged")
        s3.add_row("箭头线宽", self.vec_width)
        self.vec_color = line("#374151")
        self.hook(self.vec_color, "textChanged")
        s3.add_row("箭头颜色", self.vec_color)
        lay.addWidget(s3)
        self.section_vec = s3

        lay.addStretch(1)

    # ------------------------------------------------------------------
    def _quick(self, key: str) -> None:
        """把快捷分析动作编码成一个信号，交给主窗口改 spec。"""
        self._pending = key
        self.changed.emit()

    def take_quick(self) -> str:
        k = getattr(self, "_pending", "")
        self._pending = ""
        return k

    def _pick_shp(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择研究区边界", "", "Shapefile (*.shp);;所有文件 (*)")
        if path:
            self.mask_shp.setText(path)

    # ------------------------------------------------------------------
    def set_source(self, source) -> None:
        super().set_source(source)
        self.qual_combo.blockSignals(True)
        self.qual_combo.clear()
        self.qual_combo.addItem("（不使用质量过滤）", "")
        if source is not None:
            for name, v in source.variables.items():
                low = name.lower()
                if ("qual" in low or "quality" in low or "flag" in low) \
                        and v.is_plottable:
                    self.qual_combo.addItem(name, name)
        self.qual_combo.blockSignals(False)

    # ------------------------------------------------------------------
    def _bind(self, spec) -> None:
        self.mask_land.setChecked(bool(spec.mask_land))
        if spec.mask_range and len(spec.mask_range) >= 2:
            self.mask_range_check.setChecked(True)
            self.mask_lo.setValue(float(spec.mask_range[0]))
            self.mask_hi.setValue(float(spec.mask_range[1]))
        else:
            self.mask_range_check.setChecked(False)
        i = self.qual_combo.findData(spec.quality_var or "")
        self.qual_combo.setCurrentIndex(max(0, i))
        self.qual_accept.setText(spec.quality_accept or "0:2")
        self.mask_shp.setText(spec.mask_shapefile or "")

        self.vec_step.setValue(int(spec.vector_step))
        self.vec_scale.setValue(float(spec.vector_scale or 0.0))
        self.vec_width.setValue(float(spec.vector_width))
        self.vec_color.setText(spec.vector_color)

    def _apply(self, spec) -> None:
        spec.mask_land = self.mask_land.isChecked()
        if self.mask_range_check.isChecked():
            spec.mask_range = [float(self.mask_lo.value()),
                               float(self.mask_hi.value())]
        else:
            spec.mask_range = None
        spec.quality_var = self.qual_combo.currentData() or None
        spec.quality_accept = self.qual_accept.text().strip() or "0:2"
        spec.mask_shapefile = self.mask_shp.text().strip() or None

        spec.vector_step = int(self.vec_step.value())
        spec.vector_scale = float(self.vec_scale.value()) or None
        spec.vector_width = float(self.vec_width.value())
        spec.vector_color = self.vec_color.text().strip() or "#374151"
