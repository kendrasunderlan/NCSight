# -*- coding: utf-8 -*-
"""
界面图标
========
全部用 QPainter 现画，**不引入任何二进制资源文件**。

这样做的好处：
  * 仓库里没有 .png/.ico，diff 干净，代码即资源
  * 图标颜色跟随主题色，改一处全局生效
  * 想加图标只需在 _DRAWERS 里加一个函数

图标统一 1.6px 线宽、圆头端点，风格与「简约白色」一致。
"""

from __future__ import annotations

from typing import Callable, Dict

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .theme import UI


def _pen(color: str, width: float = 1.6) -> QPen:
    p = QPen(QColor(color))
    p.setWidthF(width)
    p.setCapStyle(Qt.RoundCap)
    p.setJoinStyle(Qt.RoundJoin)
    return p


# --------------------------------------------------------------------------
# 各个图标的绘制函数（画在 24x24 的逻辑坐标系里）
# --------------------------------------------------------------------------
def _open(p: QPainter, c: str) -> None:
    p.setPen(_pen(c))
    path = QPainterPath()
    path.moveTo(3, 18)
    path.lineTo(3, 6)
    path.lineTo(9.5, 6)
    path.lineTo(11.5, 8.5)
    path.lineTo(21, 8.5)
    path.lineTo(21, 18)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(3, 18), QPointF(21, 18))


def _chart(p: QPainter, c: str) -> None:
    p.setPen(_pen(c))
    p.drawLine(QPointF(4, 3.5), QPointF(4, 20.5))
    p.drawLine(QPointF(4, 20.5), QPointF(21, 20.5))
    path = QPainterPath()
    path.moveTo(7, 16)
    path.lineTo(11, 10.5)
    path.lineTo(14.5, 13.5)
    path.lineTo(20, 6.5)
    p.drawPath(path)


def _map(p: QPainter, c: str) -> None:
    p.setPen(_pen(c))
    p.drawEllipse(QRectF(4, 4, 16, 16))
    p.drawLine(QPointF(4, 12), QPointF(20, 12))
    p.drawEllipse(QRectF(8.5, 4, 7, 16))
    p.drawLine(QPointF(5.5, 7.5), QPointF(18.5, 7.5))
    p.drawLine(QPointF(5.5, 16.5), QPointF(18.5, 16.5))


def _export(p: QPainter, c: str) -> None:
    p.setPen(_pen(c))
    p.drawLine(QPointF(12, 4), QPointF(12, 14.5))
    path = QPainterPath()
    path.moveTo(7.5, 10.5)
    path.lineTo(12, 15)
    path.lineTo(16.5, 10.5)
    p.drawPath(path)
    path2 = QPainterPath()
    path2.moveTo(4.5, 16.5)
    path2.lineTo(4.5, 20)
    path2.lineTo(19.5, 20)
    path2.lineTo(19.5, 16.5)
    p.drawPath(path2)


def _save(p: QPainter, c: str) -> None:
    p.setPen(_pen(c))
    path = QPainterPath()
    path.moveTo(4.5, 4.5)
    path.lineTo(16, 4.5)
    path.lineTo(19.5, 8)
    path.lineTo(19.5, 19.5)
    path.lineTo(4.5, 19.5)
    path.closeSubpath()
    p.drawPath(path)
    p.drawRect(QRectF(8, 4.5, 8, 5.5))
    p.drawRect(QRectF(7.5, 13, 9, 6.5))


def _refresh(p: QPainter, c: str) -> None:
    p.setPen(_pen(c))
    path = QPainterPath()
    path.arcMoveTo(QRectF(4.5, 4.5, 15, 15), 55)
    path.arcTo(QRectF(4.5, 4.5, 15, 15), 55, 265)
    p.drawPath(path)
    p.drawLine(QPointF(15.2, 4.2), QPointF(15.8, 8.6))
    p.drawLine(QPointF(15.8, 8.6), QPointF(11.6, 7.6))


def _grid(p: QPainter, c: str) -> None:
    p.setPen(_pen(c, 1.4))
    for v in (4.5, 12, 19.5):
        p.drawLine(QPointF(v, 4.5), QPointF(v, 19.5))
        p.drawLine(QPointF(4.5, v), QPointF(19.5, v))


def _zoomin(p: QPainter, c: str) -> None:
    p.setPen(_pen(c))
    p.drawEllipse(QRectF(4.5, 4.5, 12, 12))
    p.drawLine(QPointF(15.5, 15.5), QPointF(20, 20))
    p.drawLine(QPointF(8, 10.5), QPointF(13, 10.5))
    p.drawLine(QPointF(10.5, 8), QPointF(10.5, 13))


def _zoomout(p: QPainter, c: str) -> None:
    p.setPen(_pen(c))
    p.drawEllipse(QRectF(4.5, 4.5, 12, 12))
    p.drawLine(QPointF(15.5, 15.5), QPointF(20, 20))
    p.drawLine(QPointF(8, 10.5), QPointF(13, 10.5))


def _fit(p: QPainter, c: str) -> None:
    p.setPen(_pen(c))
    p.drawRect(QRectF(4.5, 4.5, 15, 15))
    p.drawLine(QPointF(8.5, 8.5), QPointF(11.5, 8.5))
    p.drawLine(QPointF(8.5, 8.5), QPointF(8.5, 11.5))
    p.drawLine(QPointF(15.5, 15.5), QPointF(12.5, 15.5))
    p.drawLine(QPointF(15.5, 15.5), QPointF(15.5, 12.5))


def _animation(p: QPainter, c: str) -> None:
    p.setPen(_pen(c))
    p.drawRect(QRectF(3.5, 5.5, 17, 13))
    for i, y in enumerate((8.5, 11, 13.5)):
        p.setPen(_pen(c, 1.6 - i * 0.35))
        p.drawLine(QPointF(6.5, y), QPointF(17.5 - i * 1.5, y))
    p.setPen(_pen(c))
    path = QPainterPath()
    path.moveTo(10, 9.5)
    path.lineTo(10, 14.5)
    path.lineTo(14.5, 12)
    path.closeSubpath()
    p.drawPath(path)


def _batch(p: QPainter, c: str) -> None:
    p.setPen(_pen(c))
    p.drawRect(QRectF(3.5, 3.5, 10, 10))
    p.drawRect(QRectF(10.5, 10.5, 10, 10))


def _panel(p: QPainter, c: str) -> None:
    p.setPen(_pen(c))
    p.drawRect(QRectF(3.5, 4.5, 17, 15))
    p.drawLine(QPointF(14.5, 4.5), QPointF(14.5, 19.5))


def _settings(p: QPainter, c: str) -> None:
    p.setPen(_pen(c))
    p.drawEllipse(QRectF(8.5, 8.5, 7, 7))
    import math
    for k in range(6):
        a = math.radians(k * 60)
        p.drawLine(QPointF(12 + 7.0 * math.cos(a), 12 + 7.0 * math.sin(a)),
                   QPointF(12 + 9.5 * math.cos(a), 12 + 9.5 * math.sin(a)))


def _info(p: QPainter, c: str) -> None:
    p.setPen(_pen(c))
    p.drawEllipse(QRectF(3.5, 3.5, 17, 17))
    p.drawLine(QPointF(12, 10.5), QPointF(12, 17))
    p.drawPoint(QPointF(12, 7.4))


def _table(p: QPainter, c: str) -> None:
    p.setPen(_pen(c, 1.3))
    p.drawRect(QRectF(3.5, 5.5, 17, 13))
    p.drawLine(QPointF(3.5, 10), QPointF(20.5, 10))
    p.drawLine(QPointF(3.5, 14.5), QPointF(20.5, 14.5))
    p.drawLine(QPointF(10.5, 5.5), QPointF(10.5, 18.5))


def _mask(p: QPainter, c: str) -> None:
    p.setPen(_pen(c))
    path = QPainterPath()
    path.addEllipse(QRectF(3.5, 5.5, 12, 12))
    p.drawPath(path)
    path2 = QPainterPath()
    path2.addEllipse(QRectF(8.5, 5.5, 12, 12))
    p.drawPath(path2)


_DRAWERS: Dict[str, Callable[[QPainter, str], None]] = {
    "open": _open, "chart": _chart, "map": _map, "export": _export,
    "save": _save, "refresh": _refresh, "grid": _grid, "zoomin": _zoomin,
    "zoomout": _zoomout, "fit": _fit, "animation": _animation,
    "batch": _batch, "panel": _panel, "settings": _settings,
    "info": _info, "table": _table, "mask": _mask,
}


def line_icon(name: str, color: str = None, size: int = 20) -> QIcon:
    """生成一个线性图标。name 见 _DRAWERS；未知名字返回空图标。"""
    color = color or UI["text"]
    drawer = _DRAWERS.get(name)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    if drawer is None:
        return QIcon(pm)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    scale = size / 24.0
    p.scale(scale, scale)
    drawer(p, color)
    p.end()
    return QIcon(pm)


def app_icon(size: int = 64) -> QIcon:
    """应用图标：一个「色块地图」的抽象图形。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    s = size / 64.0
    p.scale(s, s)

    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#0d9488"))
    p.drawRoundedRect(QRectF(8, 10, 48, 44), 6, 6)

    colors = ["#0ea5e9", "#38bdf8", "#a3e635", "#facc15", "#fb923c", "#ef4444"]
    w = 48 / len(colors)
    for i, col in enumerate(colors):
        p.setBrush(QColor(col))
        p.drawRect(QRectF(8 + i * w, 22, w + 0.6, 32))
    p.setBrush(QColor("#0d9488"))
    p.drawRect(QRectF(8, 10, 48, 12))
    p.setBrush(QColor("#ffffff"))
    p.setPen(QPen(QColor("#0f766e"), 1.4))
    p.drawLine(QPointF(14, 16), QPointF(26, 16))
    p.drawLine(QPointF(20, 11), QPointF(20, 21))
    p.setPen(Qt.NoPen)
    p.end()
    return QIcon(pm)


def make_icon_set(color: str = None) -> Dict[str, QIcon]:
    return {name: line_icon(name, color) for name in _DRAWERS}
