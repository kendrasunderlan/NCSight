# -*- coding: utf-8 -*-
"""
生成应用图标 NCSight.ico
=======================
图标不是外部素材，而是**用代码画出来的**（跟界面图标同一套思路）：
一个「分层色阶地图」的抽象图形 —— 深青底 + 冷暖色带 + 经纬十字。

用法：
    python scripts/make_icon.py [输出路径]

产出多尺寸 ICO（16/24/32/48/64/128/256），Windows 会按场景自动挑合适的那一档。
"""

from __future__ import annotations

import io
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyside6")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SIZES = [16, 24, 32, 48, 64, 128, 256]

# 色阶：冷 → 暖（与软件默认的海洋色表观感一致）
BANDS = ["#0ea5e9", "#22c1d6", "#38bdf8", "#7dd3a0", "#a3e635",
         "#facc15", "#fb923c", "#ef4444", "#b91c1c"]


def draw(size: int):
    """在给定像素尺寸下绘制图标，返回 PNG 字节。"""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPen

    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    # 全部按 64x64 的逻辑坐标绘制，再等比缩放到目标像素
    p.scale(size / 64.0, size / 64.0)

    # 圆角底
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#0f4c5c"))
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 11, 11)

    # 内部地图区域（留出边距）
    x0, y0, w, h = 9.0, 17.0, 46.0, 36.0

    # 天空/顶部条
    p.setBrush(QColor("#0c3b49"))
    p.drawRect(QRectF(x0, y0 - 8.0, w, 8.0))

    # 冷暖色带（竖条，模拟等值填色）
    n = len(BANDS)
    bw = w / n
    for i, col in enumerate(BANDS):
        p.setBrush(QColor(col))
        # 让色带上下略有起伏，看起来像数据而不是色卡
        amp = 1.6 * ((i % 3) - 1)
        p.drawRect(QRectF(x0 + i * bw, y0 + amp, bw + 0.45, h - abs(amp)))

    # 经纬十字（用半透明白，压住色带但不遮死）
    p.setPen(QPen(QColor(255, 255, 255, 120), 1.0))
    p.drawLine(QPointF(x0, y0 + h * 0.42), QPointF(x0 + w, y0 + h * 0.42))
    p.drawLine(QPointF(x0 + w * 0.46, y0), QPointF(x0 + w * 0.46, y0 + h))

    # 等高线（两条细弧，强化「科学绘图」的意象）
    p.setPen(QPen(QColor(255, 255, 255, 165), 1.1))
    p.setBrush(Qt.NoBrush)
    from PySide6.QtGui import QPainterPath
    for k, dy in enumerate((-6.0, 6.0)):
        path = QPainterPath()
        path.moveTo(x0 + 4, y0 + h * 0.5 + dy)
        path.cubicTo(x0 + w * 0.35, y0 + h * 0.5 + dy - 6.0,
                     x0 + w * 0.65, y0 + h * 0.5 + dy + 6.0,
                     x0 + w - 4, y0 + h * 0.5 + dy)
        p.drawPath(path)

    # 外框
    p.setPen(QPen(QColor("#0a323d"), max(0.6, 64.0 / size * 1.2)))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 11, 11)

    p.end()

    buf = io.BytesIO()
    from PySide6.QtCore import QBuffer, QIODevice
    qbuf = QBuffer()
    qbuf.open(QIODevice.WriteOnly)
    img.save(qbuf, "PNG")
    return bytes(qbuf.data())


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "NCSight.ico")

    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841

    from PIL import Image
    frames = []
    for s in SIZES:
        data = draw(s)
        im = Image.open(io.BytesIO(data)).convert("RGBA")
        frames.append(im)
        print("  绘制 %3d x %3d  (%d bytes)" % (s, s, len(data)))

    # PIL 会把第一张当主图，其余作为多尺寸帧写进 ICO
    frames[-1].save(out, format="ICO",
                    sizes=[(f.width, f.height) for f in frames],
                    append_images=frames[:-1])
    print("\n已生成图标：%s  (%d bytes)" % (out, os.path.getsize(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
