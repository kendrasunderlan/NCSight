# -*- coding: utf-8 -*-
"""
对话框集合
==========
关于 / 导出图像 / 导出数据 / 动画 / 批量出图 / 距平分析。
全部用代码构建，不依赖 .ui 文件，方便进版本管理。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QSpinBox, QDoubleSpinBox, QVBoxLayout, QWidget)

from ..core import export as ex
from ..version import (APP_NAME, APP_NAME_CN, APP_SLOGAN, version_info)
from .theme import UI


def _dlg(parent, title: str, width: int = 460) -> Tuple[QDialog, QVBoxLayout]:
    d = QDialog(parent)
    d.setWindowTitle(title)
    d.setMinimumWidth(width)
    lay = QVBoxLayout(d)
    lay.setContentsMargins(16, 16, 16, 14)
    lay.setSpacing(12)
    return d, lay


def _buttons(d: QDialog, ok_text: str = "确定") -> QDialogButtonBox:
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.button(QDialogButtonBox.Ok).setText(ok_text)
    bb.button(QDialogButtonBox.Cancel).setText("取消")
    bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    return bb


# --------------------------------------------------------------------------
class AboutDialog(QDialog):
    def __init__(self, parent=None, runtime: Optional[Dict[str, str]] = None):
        d, lay = _dlg(self, "关于 %s" % APP_NAME, 500)
        d.setParent(parent)
        vi = version_info()

        title = QLabel("%s · %s" % (APP_NAME, APP_NAME_CN))
        title.setStyleSheet("font-size:17px;font-weight:500;color:%s;" % UI["text"])
        lay.addWidget(title)
        lay.addWidget(QLabel(APP_SLOGAN))

        info = QPlainTextEdit()
        info.setReadOnly(True)
        info.setMinimumHeight(220)
        lines = [
            "版本      : %s" % vi["string"],
            "阶段      : %s" % vi["stage"],
            "里程碑    : %s" % vi["milestone"],
            "发布日期  : %s" % vi["release_date"],
            "",
            "设计蓝本  : NASA Panoply 5.7.1（拆解报告见工作区根目录）",
            "定位      : 面向海洋遥感的 netCDF 可视化工作台",
            "",
            "── 运行环境 ──",
        ]
        for k, v in (runtime or {}).items():
            lines.append("%-10s: %s" % (k, v))
        info.setPlainText("\n".join(lines))
        info.setStyleSheet(
            "QPlainTextEdit{border:1px solid %s;border-radius:6px;background:%s;"
            "font-family:Consolas,monospace;font-size:12px;padding:8px;}"
            % (UI["border"], UI["panel"]))
        lay.addWidget(info)

        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.button(QDialogButtonBox.Ok).setText("关闭")
        bb.accepted.connect(d.accept)
        lay.addWidget(bb)
        d.exec()


# --------------------------------------------------------------------------
class ExportImageDialog(QDialog):
    """导出图像：格式 / DPI / 路径。"""

    def __init__(self, parent=None, default_path: str = "ncsight.png"):
        d, lay = _dlg(self, "导出图像")
        d.setParent(parent)
        self._d = d

        form = QFormLayout()
        form.setSpacing(9)

        self.path_edit = QLineEdit(default_path)
        browse = QPushButton("浏览…")
        browse.setProperty("flat", "true")
        browse.clicked.connect(self._browse)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addWidget(self.path_edit, 1)
        h.addWidget(browse)
        form.addRow("保存到", row)

        self.fmt_combo = QComboBox()
        for k, label in ex.FORMAT_LABELS.items():
            self.fmt_combo.addItem("%s — %s" % (k.upper(), label), k)
        self.fmt_combo.currentIndexChanged.connect(self._sync_ext)
        form.addRow("格式", self.fmt_combo)

        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(50, 1200)
        self.dpi_spin.setValue(300)
        self.dpi_spin.setSingleStep(50)
        form.addRow("DPI（位图）", self.dpi_spin)

        self.transparent = QCheckBox("透明背景（仅矢量格式有效）")
        form.addRow("", self.transparent)

        lay.addLayout(form)
        lay.addWidget(_muted(lay))
        lay.addWidget(_buttons(d, "导出"))

    def _browse(self) -> None:
        fmt = self.fmt_combo.currentData()
        path, _ = QFileDialog.getSaveFileName(
            self._d, "保存图像", self.path_edit.text(),
            "%s (*.%s);;所有文件 (*)" % (fmt.upper(), fmt))
        if path:
            self.path_edit.setText(path)

    def _sync_ext(self) -> None:
        fmt = self.fmt_combo.currentData()
        stem = os.path.splitext(self.path_edit.text())[0]
        self.path_edit.setText("%s.%s" % (stem, fmt))

    def values(self) -> Dict[str, object]:
        return {
            "path": self.path_edit.text().strip(),
            "format": self.fmt_combo.currentData(),
            "dpi": int(self.dpi_spin.value()),
            "transparent": self.transparent.isChecked(),
        }


def _muted(lay) -> QLabel:
    lb = QLabel("提示：投稿插图请选 PDF 或 SVG —— 矢量、无损缩放、文字可编辑。")
    lb.setWordWrap(True)
    lb.setStyleSheet("color:%s;font-size:11.5px;" % UI["text_muted"])
    return lb


# --------------------------------------------------------------------------
class ExportDataDialog(QDialog):
    """导出数据：CSV / NPZ / 文本。"""

    def __init__(self, parent=None, default_dir: str = ""):
        d, lay = _dlg(self, "导出数据")
        d.setParent(parent)
        self._d = d
        form = QFormLayout()
        form.setSpacing(9)

        self.what_combo = QComboBox()
        self.what_combo.addItem("当前绘制的二维网格 → CSV", "grid_csv")
        self.what_combo.addItem("当前绘制的二维网格 → NPZ（保留形状）", "grid_npz")
        self.what_combo.addItem("整份数据集的结构说明 → TXT", "overview")
        form.addRow("导出内容", self.what_combo)

        self.path_edit = QLineEdit(default_dir)
        browse = QPushButton("浏览…")
        browse.setProperty("flat", "true")
        browse.clicked.connect(self._browse)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.path_edit, 1)
        h.addWidget(browse)
        form.addRow("保存到", row)

        lay.addLayout(form)
        lay.addWidget(_muted(lay))
        lay.addWidget(_buttons(d, "导出"))

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self._d, "保存数据", self.path_edit.text(),
            "CSV (*.csv);;NPZ (*.npz);;文本 (*.txt);;所有文件 (*)")
        if path:
            self.path_edit.setText(path)

    def values(self) -> Dict[str, object]:
        return {"what": self.what_combo.currentData(),
                "path": self.path_edit.text().strip()}


# --------------------------------------------------------------------------
class AnimationDialog(QDialog):
    """导出动画：维度 / 帧范围 / 帧率 / 输出。"""

    def __init__(self, parent=None, dims: Optional[List[Tuple[str, int]]] = None,
                 default_dir: str = "animation.mp4", has_ffmpeg: bool = True):
        d, lay = _dlg(self, "导出动画")
        d.setParent(parent)
        self._d = d
        form = QFormLayout()
        form.setSpacing(9)

        self.dim_combo = QComboBox()
        for name, size in (dims or []):
            self.dim_combo.addItem("%s（共 %d 帧）" % (name, size), (name, size))
        form.addRow("遍历维度", self.dim_combo)

        self.start_spin = QSpinBox(); self.start_spin.setRange(0, 100000)
        self.stop_spin = QSpinBox(); self.stop_spin.setRange(0, 100000)
        self.stop_spin.setValue(0)
        self.stop_spin.setSpecialValueText("到末尾")
        form.addRow("起始帧", self.start_spin)
        form.addRow("结束帧", self.stop_spin)

        self.step_spin = QSpinBox(); self.step_spin.setRange(1, 1000)
        self.step_spin.setValue(1)
        form.addRow("步长", self.step_spin)

        self.fps_spin = QSpinBox(); self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(8)
        form.addRow("帧率 fps", self.fps_spin)

        self.path_edit = QLineEdit(default_dir)
        browse = QPushButton("浏览…")
        browse.setProperty("flat", "true")
        browse.clicked.connect(self._browse)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.path_edit, 1)
        h.addWidget(browse)
        form.addRow("保存到", row)

        lay.addLayout(form)
        tip = ("未检测到 ffmpeg，将自动导出为 GIF。" if not has_ffmpeg
               else "MP4 需要 ffmpeg；GIF 不依赖外部程序。")
        lb = QLabel(tip)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:%s;font-size:11.5px;" % UI["text_muted"])
        lay.addWidget(lb)
        lay.addWidget(_buttons(d, "开始导出"))

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self._d, "保存动画", self.path_edit.text(),
            "MP4 (*.mp4);;GIF (*.gif);;所有文件 (*)")
        if path:
            self.path_edit.setText(path)

    def values(self) -> Dict[str, object]:
        dim = self.dim_combo.currentData() or ("time", 0)
        return {
            "dim": dim[0],
            "start": int(self.start_spin.value()),
            "stop": int(self.stop_spin.value()) or None,
            "step": int(self.step_spin.value()),
            "fps": int(self.fps_spin.value()),
            "path": self.path_edit.text().strip(),
        }


# --------------------------------------------------------------------------
class BatchDialog(QDialog):
    """批量出图：输入目录 / 输出目录 / 命名模板。"""

    def __init__(self, parent=None, default_in: str = "", default_out: str = "figures"):
        d, lay = _dlg(self, "批量出图", 520)
        d.setParent(parent)
        self._d = d
        form = QFormLayout()
        form.setSpacing(9)

        self.in_edit = QLineEdit(default_in)
        form.addRow("输入", self._row(self.in_edit, self._pick_in))

        self.out_edit = QLineEdit(default_out)
        form.addRow("输出目录", self._row(self.out_edit, self._pick_out))

        self.pattern_edit = QLineEdit("{stem}_{var}")
        form.addRow("命名模板", self.pattern_edit)

        self.fmt_combo = QComboBox()
        for k in ("png", "pdf", "svg", "jpg", "tiff"):
            self.fmt_combo.addItem(k.upper(), k)
        form.addRow("格式", self.fmt_combo)

        self.dpi_spin = QSpinBox(); self.dpi_spin.setRange(50, 1200)
        self.dpi_spin.setValue(300)
        form.addRow("DPI", self.dpi_spin)

        self.recursive = QCheckBox("递归子目录")
        self.recursive.setChecked(True)
        form.addRow("", self.recursive)

        self.overdim_edit = QLineEdit()
        self.overdim_edit.setPlaceholderText("如 time（留空则只出一张）")
        form.addRow("沿维度遍历", self.overdim_edit)

        lay.addLayout(form)
        lb = QLabel("命名模板占位符：{stem} 源文件名 · {var} 变量名 · {index} 序号 · "
                    "{dim} 维度名 · {dimval} 维度取值")
        lb.setWordWrap(True)
        lb.setStyleSheet("color:%s;font-size:11.5px;" % UI["text_muted"])
        lay.addWidget(lb)
        lay.addWidget(_buttons(d, "开始批量"))

    def _row(self, edit: QLineEdit, cb) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addWidget(edit, 1)
        b = QPushButton("浏览…")
        b.setProperty("flat", "true")
        b.clicked.connect(cb)
        h.addWidget(b)
        return w

    def _pick_in(self) -> None:
        p = QFileDialog.getExistingDirectory(self._d, "选择数据目录", self.in_edit.text())
        if p:
            self.in_edit.setText(p)

    def _pick_out(self) -> None:
        p = QFileDialog.getExistingDirectory(self._d, "选择输出目录", self.out_edit.text())
        if p:
            self.out_edit.setText(p)

    def values(self) -> Dict[str, object]:
        return {
            "input": self.in_edit.text().strip(),
            "out": self.out_edit.text().strip(),
            "pattern": self.pattern_edit.text().strip() or "{stem}_{var}",
            "format": self.fmt_combo.currentData(),
            "dpi": int(self.dpi_spin.value()),
            "recursive": self.recursive.isChecked(),
            "over_dim": self.overdim_edit.text().strip() or None,
        }


# --------------------------------------------------------------------------
class ProgressDialog(QDialog):
    """带进度与取消的模态对话框（批量/动画共用）。"""

    def __init__(self, parent=None, title: str = "处理中", cancellable: bool = True):
        d, lay = _dlg(self, title, 420)
        d.setParent(parent)
        d.setModal(True)
        self._d = d
        self._cancelled = False

        self.label = QLabel("准备中…")
        self.label.setWordWrap(True)
        lay.addWidget(self.label)

        from PySide6.QtWidgets import QProgressBar
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        lay.addWidget(self.bar)

        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addStretch(1)
        if cancellable:
            b = QPushButton("取消")
            b.clicked.connect(self._cancel)
            h.addWidget(b)
        lay.addWidget(row)

    def _cancel(self) -> None:
        self._cancelled = True
        self.label.setText("正在取消…")

    def cancelled(self) -> bool:
        return self._cancelled

    def set_progress(self, done: int, total: int, text: str = "") -> None:
        self.bar.setRange(0, max(1, total))
        self.bar.setValue(done)
        self.label.setText(text or ("%d / %d" % (done, total)))
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

    def finish(self) -> None:
        self._d.accept()
