# -*- coding: utf-8 -*-
"""
控制面板 · 色标（Scale）
=======================
对应 Panoply 的 Scale 面板。这一块是「出图能不能直接投稿」的关键，
所以做得比较全：范围、色阶、色表、反转、对数、居中于零、越界三角。
"""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QWidget

from ...core.colormap import CMAP_CATALOG, CMAP_ALIAS
from ...core.plot.base import COLORBAR_LOCATIONS
from ..theme import UI
from .base import (PanelBase, Section, button, check, combo, label, line,
                   spin, two_col)


def _cmap_items():
    items = [("auto", "自动（优先用文件内嵌色表）")]
    for group, entries in CMAP_CATALOG.items():
        for name, desc in entries:
            items.append((name, "%s · %s" % (name, desc)))
    for alias, target in CMAP_ALIAS.items():
        if alias not in ("auto",):
            items.append((alias, "%s（别名 → %s）" % (alias, target)))
    return items


class ScalePanel(PanelBase):
    title = "色标"

    def _build(self) -> None:
        from PySide6.QtWidgets import QVBoxLayout
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---------- 范围 ----------
        s = Section("数值范围", expanded=True)
        self.vmin = spin(-1e12, 1e12, 0, 0.1, 4)
        self.vmax = spin(-1e12, 1e12, 1, 0.1, 4)
        # 手动改动数值即视为「切换到手动模式」，自动取消勾选
        self.hook(self.vmin, "valueChanged")
        self.hook(self.vmax, "valueChanged")
        s.add_row("最小值", self.vmin)
        s.add_row("最大值", self.vmax)

        b1 = button("贴合数据（1%~99%）", self._fit_data)
        b2 = button("居中于零", self._center_zero)
        s.add_widget(two_col(b1, b2))
        # ★ 默认必须是「自动」，否则首次打开会用 0/1 这种占位值当色标范围
        self.auto_check = check("自动贴合数据范围（推荐）", True)
        self.hook(self.auto_check, "toggled")
        s.add_row("", self.auto_check)
        s.add_widget(label("距平图建议：先点「居中于零」，色表选 balance / vik / RdBu_r。",
                            wrap=True))
        lay.addWidget(s)
        self.section_range = s

        # ---------- 色表 ----------
        s2 = Section("色表", expanded=True)
        self.cmap_combo = combo(_cmap_items(), "auto")
        self.hook(self.cmap_combo, "currentIndexChanged")
        s2.add_row("配色", self.cmap_combo)

        self.table_row = line(placeholder="或选择一个 .cpt / .act / .rgb 文件")
        btn = button("浏览…", self._pick_table, flat=True)
        s2.add_widget(two_col(self.table_row, btn))
        self.hook(self.table_row, "textChanged")

        self.nbins = spin(2, 256, 21, 1)
        self.hook(self.nbins, "valueChanged")
        s2.add_row("色阶数", self.nbins)

        self.discrete_check = check("离散色阶（等值填色）", True)
        self.reverse_check = check("反转色表", False)
        self.log_check = check("对数刻度", False)
        self.zero_check = check("居中于零", False)
        for w in (self.discrete_check, self.reverse_check,
                  self.log_check, self.zero_check):
            self.hook(w, "toggled")
        s2.add_row("", self.discrete_check)
        s2.add_row("", self.reverse_check)
        s2.add_row("", self.log_check)
        s2.add_row("", self.zero_check)
        lay.addWidget(s2)
        self.section_cmap = s2

        # ---------- 色标外观 ----------
        s3 = Section("色标（图例）", expanded=False)
        self.cbar_check = check("显示色标", True)
        self.hook(self.cbar_check, "toggled")
        s3.add_row("", self.cbar_check)

        self.cbar_loc = combo(COLORBAR_LOCATIONS, "right")
        self.hook(self.cbar_loc, "currentIndexChanged")
        s3.add_row("位置", self.cbar_loc)

        self.cbar_label = line(placeholder="留空则自动用「变量名 [单位]」")
        self.hook(self.cbar_label, "textChanged")
        s3.add_row("标题", self.cbar_label)

        self.ticks_edit = line(placeholder="如 0,5,10,15,20,25,30")
        self.hook(self.ticks_edit, "textChanged")
        s3.add_row("指定刻度", self.ticks_edit)
        s3.add_widget(label("刻度留空即自动取整。", wrap=True))
        lay.addWidget(s3)
        self.section_cbar = s3

        lay.addStretch(1)

    # ------------------------------------------------------------------
    def hook(self, widget, signal: str = "default") -> None:
        """
        覆写基类：数值范围的改动要顺带把「自动」取消掉，
        否则用户手工填了 min/max 却发现被自动模式覆盖，会很困惑。
        """
        if widget in (getattr(self, "vmin", None), getattr(self, "vmax", None)):
            widget.valueChanged.connect(self._on_manual_scale)
            return
        super().hook(widget, signal)

    def _on_manual_scale(self, *_args) -> None:
        if self._blocked:
            return
        if self.auto_check.isChecked():
            self.auto_check.setChecked(False)     # 会触发 toggled -> notify
        else:
            self.notify()

    def set_effective_range(self, vmin: float, vmax: float) -> None:
        """自动模式下，把实际生效的范围回显到输入框（不触发信号）。"""
        if not self.auto_check.isChecked():
            return
        self.vmin.blockSignals(True)
        self.vmax.blockSignals(True)
        try:
            self.vmin.setValue(round(float(vmin), 4))
            self.vmax.setValue(round(float(vmax), 4))
        finally:
            self.vmin.blockSignals(False)
            self.vmax.blockSignals(False)

    def _pick_table(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择色表文件", "",
            "色表文件 (*.cpt *.act *.rgb *.gct *.pal);;所有文件 (*)")
        if path:
            self.table_row.setText(path)

    def _fit_data(self) -> None:
        self.auto_check.setChecked(True)
        self.notify()

    def _center_zero(self) -> None:
        self.zero_check.setChecked(True)
        self.notify()

    # ------------------------------------------------------------------
    def _bind(self, spec) -> None:
        auto = spec.vmin is None and spec.vmax is None
        self.auto_check.setChecked(auto)
        if spec.vmin is not None:
            self.vmin.setValue(float(spec.vmin))
        if spec.vmax is not None:
            self.vmax.setValue(float(spec.vmax))
        idx = self.cmap_combo.findData(spec.cmap)
        self.cmap_combo.setCurrentIndex(max(0, idx))
        self.table_row.setText(spec.table_path or "")
        self.nbins.setValue(int(spec.nbins))
        self.discrete_check.setChecked(bool(spec.discrete))
        self.reverse_check.setChecked(bool(spec.reverse))
        self.log_check.setChecked(bool(spec.log))
        self.zero_check.setChecked(bool(spec.center_zero))
        self.cbar_check.setChecked(bool(spec.show_colorbar))
        i = self.cbar_loc.findData(spec.colorbar_location)
        self.cbar_loc.setCurrentIndex(max(0, i))
        self.cbar_label.setText(spec.colorbar_label or "")
        self.ticks_edit.setText(
            ",".join(str(t) for t in spec.colorbar_ticks)
            if spec.colorbar_ticks else "")

    def _apply(self, spec) -> None:
        spec.cmap = self.cmap_combo.currentData() or "auto"
        spec.table_path = self.table_row.text().strip() or None
        spec.nbins = int(self.nbins.value())
        spec.discrete = self.discrete_check.isChecked()
        spec.reverse = self.reverse_check.isChecked()
        spec.log = self.log_check.isChecked()
        spec.center_zero = self.zero_check.isChecked()
        spec.show_colorbar = self.cbar_check.isChecked()
        spec.colorbar_location = self.cbar_loc.currentData() or "right"
        spec.colorbar_label = self.cbar_label.text().strip() or None

        raw = self.ticks_edit.text().strip()
        if raw:
            vals = []
            for part in raw.replace(";", ",").split(","):
                try:
                    vals.append(float(part))
                except ValueError:
                    pass
            spec.colorbar_ticks = vals or None
        else:
            spec.colorbar_ticks = None

        if self.auto_check.isChecked():
            # 自动：不写死范围，交给 core 按「数据自带建议范围 → 稳健分位数」决定
            spec.vmin = None
            spec.vmax = None
        else:
            v0, v1 = float(self.vmin.value()), float(self.vmax.value())
            if v1 <= v0:
                v1 = v0 + 1.0
            spec.vmin, spec.vmax = v0, v1
