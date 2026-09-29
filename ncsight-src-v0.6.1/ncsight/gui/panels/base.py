# -*- coding: utf-8 -*-
"""
控制面板的公共构件与基类
=======================
每个控制面板遵守同一协议，主窗口只跟协议打交道：

    def set_source(self, source)   # 数据集变了（可为 None）
    def bind(self, spec)           # 用 spec 的值填充控件（不触发信号）
    def apply(self, spec) -> spec  # 把控件值写回 spec
    信号 changed                    # 用户改动 → 主窗口防抖后重渲染

这样新增一个控制面板不需要动主窗口的逻辑。
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSizePolicy, QSlider,
                               QSpinBox, QToolButton, QVBoxLayout, QWidget)

from ..theme import UI


# --------------------------------------------------------------------------
# 折叠分组
# --------------------------------------------------------------------------
class Section(QWidget):
    """一个可折叠的设置分组：标题栏 + 内容区。"""

    ARROW_CLOSED = "\u25b8"   # ▸
    ARROW_OPEN = "\u25be"     # ▾

    def __init__(self, title: str, expanded: bool = False, parent=None):
        super().__init__(parent)
        self._title = title
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.header = QToolButton(self)
        self.header.setText(" %s  %s" % (self.ARROW_CLOSED, title))
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setStyleSheet(
            "QToolButton{background:transparent;border:none;"
            "border-bottom:1px solid %s;padding:7px 8px;text-align:left;"
            "font-size:12.5px;color:%s;}"
            "QToolButton:hover{background:#f8fafc;color:%s;}" % (
                UI["border"], UI["text"], UI["accent"]))
        self.header.clicked.connect(self._on_toggle)
        lay.addWidget(self.header)

        self.body = QWidget(self)
        self.body.setStyleSheet("background:transparent;")
        self.form = QGridLayout(self.body)
        self.form.setContentsMargins(12, 9, 12, 12)
        self.form.setHorizontalSpacing(8)
        self.form.setVerticalSpacing(7)
        self.form.setColumnStretch(1, 1)
        lay.addWidget(self.body)

        self._row = 0
        self.set_expanded(expanded)

    def _on_toggle(self, checked: bool) -> None:
        self.set_expanded(checked)

    def set_expanded(self, expanded: bool) -> None:
        self.header.setChecked(expanded)
        self.header.setText(" %s  %s" % (
            self.ARROW_OPEN if expanded else self.ARROW_CLOSED, self._title))
        self.body.setVisible(expanded)

    def add_row(self, label: str, widget: QWidget,
                hint: str = "") -> QWidget:
        """加一行「标签 + 控件」。label 为空则控件占满整行。"""
        if label:
            lab = QLabel(label)
            lab.setStyleSheet("color:%s;font-size:12.5px;" % UI["text_muted"])
            self.form.addWidget(lab, self._row, 0, Qt.AlignRight | Qt.AlignVCenter)
            self.form.addWidget(widget, self._row, 1)
        else:
            self.form.addWidget(widget, self._row, 0, 1, 2)
        if hint:
            tip = QLabel(hint)
            tip.setStyleSheet("color:%s;font-size:11.5px;" % UI["text_muted"])
            tip.setWordWrap(True)
            self._row += 1
            self.form.addWidget(tip, self._row, 1)
        self._row += 1
        return widget

    def add_widget(self, widget: QWidget) -> QWidget:
        self.form.addWidget(widget, self._row, 0, 1, 2)
        self._row += 1
        return widget

    def add_separator(self) -> None:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:%s;" % UI["border"])
        self.form.addWidget(line, self._row, 0, 1, 2)
        self._row += 1


# --------------------------------------------------------------------------
# 控件工厂
# --------------------------------------------------------------------------
def combo(items: Iterable, current: Any = None, on_change=None) -> QComboBox:
    c = QComboBox()
    for it in items:
        if isinstance(it, (tuple, list)) and len(it) == 2:
            c.addItem(str(it[1]), it[0])
        else:
            c.addItem(str(it), it)
    if current is not None:
        set_combo_value(c, current)
    if on_change is not None:
        c.currentIndexChanged.connect(on_change)
    return c


def set_combo_value(c: QComboBox, value: Any) -> None:
    idx = c.findData(value)
    if idx < 0:
        idx = c.findText(str(value))
    c.setCurrentIndex(max(0, idx))


def spin(minimum: float, maximum: float, value: float, step: float = 1.0,
         decimals: int = 0, on_change=None, suffix: str = "") -> QWidget:
    w = QDoubleSpinBox() if decimals else QSpinBox()
    w.setRange(minimum, maximum)
    w.setSingleStep(step)
    if decimals:
        w.setDecimals(decimals)
    w.setValue(value)
    if suffix:
        w.setSuffix(suffix)
    w.setMinimumWidth(78)
    if on_change is not None:
        w.valueChanged.connect(on_change)
    return w


def check(text: str, checked: bool = False, on_change=None) -> QCheckBox:
    w = QCheckBox(text)
    w.setChecked(checked)
    if on_change is not None:
        w.toggled.connect(on_change)
    return w


def line(text: str = "", placeholder: str = "", on_change=None,
         clearable: bool = False) -> QLineEdit:
    w = QLineEdit(text)
    if placeholder:
        w.setPlaceholderText(placeholder)
    if clearable:
        w.setClearButtonEnabled(True)
    if on_change is not None:
        w.textChanged.connect(on_change)
    return w


def button(text: str, on_click=None, primary: bool = False,
           flat: bool = False) -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setProperty("primary", "true")
    if flat:
        b.setProperty("flat", "true")
    if on_click is not None:
        b.clicked.connect(on_click)
    return b


def two_col(left: QWidget, right: QWidget) -> QWidget:
    """把两个控件并排放在一格。"""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    h.addWidget(left)
    h.addWidget(right)
    return w


def label(text: str, muted: bool = True, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if muted:
        lb.setProperty("muted", "true")
        lb.setStyleSheet("color:%s;font-size:12px;" % UI["text_muted"])
    if wrap:
        lb.setWordWrap(True)
    return lb


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color:%s;" % UI["border"])
    return f


# --------------------------------------------------------------------------
# 面板基类
# --------------------------------------------------------------------------
class PanelBase(QWidget):
    """所有控制面板的基类。"""

    changed = Signal()

    #: 时序面板专用：请求主窗口用「一批文件」而不是单个数据集去渲染
    #: (文件路径列表, 要覆盖的 PlotSpec 字段)
    runSeries = Signal(list, dict)

    title: str = "面板"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = None
        self._blocked = False          # bind 期间为 True，屏蔽信号回环
        self._build()

    # ---- 子类实现 ----
    def _build(self) -> None:
        raise NotImplementedError

    # ---- 协议 ----
    def set_source(self, source) -> None:
        self._source = source

    def bind(self, spec) -> None:
        self._blocked = True
        try:
            self._bind(spec)
        finally:
            self._blocked = False

    def apply(self, spec):
        self._apply(spec)
        return spec

    # ---- 子类可覆写 ----
    def _bind(self, spec) -> None:
        pass

    def _apply(self, spec) -> None:
        pass

    # ---- 工具 ----
    def notify(self, *_args) -> None:
        if not self._blocked:
            self.changed.emit()

    def hook(self, widget, signal: str = "default") -> None:
        """把控件的常用信号接到 notify 上。"""
        try:
            if signal == "default":
                for name in ("valueChanged", "toggled", "currentIndexChanged",
                             "textChanged", "clicked"):
                    if hasattr(widget, name):
                        getattr(widget, name).connect(self.notify)
                        return
            else:
                getattr(widget, signal).connect(self.notify)
        except Exception:                               # noqa: BLE001
            pass


# --------------------------------------------------------------------------
# 滚动容器
# --------------------------------------------------------------------------
def scrollable(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(widget)
    area.setStyleSheet("QScrollArea{background:%s;border:none;}" % UI["window"])
    return area
