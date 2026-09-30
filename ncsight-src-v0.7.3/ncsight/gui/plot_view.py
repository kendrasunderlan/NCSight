# -*- coding: utf-8 -*-
"""
绘图画布控件
============
把 matplotlib 的 Figure 嵌进 Qt，并提供四种交互模式：

    取值    —— 鼠标移动时读出示数（状态栏显示经纬度与数值）
    框选缩放 —— 拉框放大到该区域
    平移    —— 按住拖动
    圈选区域 —— 拉框得到经纬度范围，回填到「区域范围」面板

没有用 matplotlib 自带的 NavigationToolbar —— 它那套彩色图标跟简约白主题
不搭。这里自己实现，颜色与图标跟界面统一。

性能要点：**只维护一个 Figure**。每次渲染前清空它，让渲染器在同一张图上
重建坐标轴。GeoAxes（投影图）与普通 Axes 可以在同一张图上交替出现，
不需要重建 canvas —— 这是交互流畅的关键。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_API", "pyside6")

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

import matplotlib
matplotlib.use("QtAgg", force=True)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.widgets import RectangleSelector

from ..core.detect import AxisRole

MODES = [("pick", "取值"), ("zoom", "框选缩放"), ("pan", "平移"), ("region", "圈选区域")]


class PlotView(QWidget):
    """matplotlib 画布 + 交互。"""

    coordsChanged = Signal(str)          # 状态栏文字
    regionSelected = Signal(list)        # [lon_min, lon_max, lat_min, lat_max]
    modeChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background:#ffffff;")

        self._mode = "pick"
        self._data = None
        self._selector = None
        self._pan_origin = None
        self._pan_limits = None
        self._has_plot = False

        self._figure = Figure(figsize=(7, 4), dpi=110, facecolor="#ffffff")
        self.canvas = FigureCanvas(self._figure)
        self.canvas.setStyleSheet("background:#ffffff;")
        self._connect_canvas(self.canvas)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._lay = lay
        lay.addWidget(self.canvas)

    # ------------------------------------------------------------------
    #: 当前 Figure（异步渲染时会整体替换）
    @property
    def figure(self) -> Figure:
        return self._figure

    def canvas_size(self):
        """画布像素尺寸 —— 用来决定屏幕渲染的降采样上限。"""
        try:
            sz = self.canvas.size()
            return max(1, sz.width()), max(1, sz.height())
        except Exception:                               # noqa: BLE001
            return 800, 500

    # ------------------------------------------------------------------
    # 渲染接口（主窗口调用）
    # ------------------------------------------------------------------
    def prepare(self) -> Figure:
        """
        同步渲染路径用：清空当前 Figure 并返回它。
        （异步渲染不经过这里，见 adopt()。）
        """
        self._selector = None
        self.figure.clear()
        self.figure.set_facecolor("#ffffff")
        return self.figure

    def adopt(self, result) -> None:
        """
        接管一份渲染结果。

        **这是异步渲染的关键**：Figure 是在工作线程里用非 pyplot 的方式建出来的，
        这里把它接到主线程的 Qt 画布上。

        换 Figure 时无法「就地替换」——FigureCanvasQTAgg 内部缓存着针对某个
        Figure 尺寸的渲染器，直接改 `canvas.figure` 会留下脏状态。所以干脆
        重建一个画布控件（几十毫秒，相对渲染开销可忽略），旧的那个 deleteLater。
        """
        fig = result.fig
        if fig is not self._figure:
            self._swap_canvas(fig)
        self._install_selector(result.ax)
        self._data = result.data
        self._has_plot = True
        self.canvas.draw_idle()

    #: 兼容同步渲染路径的旧名字
    finished = adopt

    def _swap_canvas(self, fig) -> None:
        old = self.canvas
        self._lay.removeWidget(old)
        old.setParent(None)

        # ★ 先"解绑"再删除 ★
        # FigureCanvasQTAgg 在构造时会把自己挂到 figure.canvas 上（反向引用）。
        # 如果直接 deleteLater() 掉画布，旧 Figure 的 .canvas 就指向了一个
        # **已销毁的 C++ 对象** —— 一旦有代码碰到它（改图、刷新、matplotlib
        # 内部回调），就是段错误级别的硬崩溃：进程直接消失，没有 traceback。
        # 这里先给它换上一个纯 Agg 画布，把引用链断开，顺手 clear 释放内存。
        old_fig = getattr(old, "figure", None)
        if old_fig is not None:
            try:
                from matplotlib.backends.backend_agg import FigureCanvasAgg
                old_fig.set_canvas(FigureCanvasAgg(old_fig))
            except Exception:                           # noqa: BLE001
                pass
            try:
                old_fig.clear()                         # 释放网格/底图对象
            except Exception:                           # noqa: BLE001
                pass
        old.deleteLater()

        canvas = FigureCanvas(fig)
        canvas.setStyleSheet("background:#ffffff;")
        self._connect_canvas(canvas)
        self._lay.addWidget(canvas)

        self.canvas = canvas
        self._figure = fig
        self._selector = None

    def _connect_canvas(self, canvas) -> None:
        canvas.mpl_connect("motion_notify_event", self._on_motion)
        canvas.mpl_connect("button_press_event", self._on_press)
        canvas.mpl_connect("button_release_event", self._on_release)
        canvas.mpl_connect("axes_leave_event",
                           lambda _e: self.coordsChanged.emit(""))

    def clear(self) -> None:
        self.figure.clear()
        self.canvas.draw_idle()
        self._data = None
        self._has_plot = False

    @property
    def has_plot(self) -> bool:
        return self._has_plot

    def save_figure(self, path: str, **kw) -> str:
        self.figure.savefig(path, **kw)
        return path

    # ------------------------------------------------------------------
    # 交互模式
    # ------------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        self._mode = mode
        if self._selector is not None:
            self._selector.set_active(mode in ("zoom", "region"))
        cursors = {"pick": Qt.CrossCursor, "zoom": Qt.CrossCursor,
                   "pan": Qt.OpenHandCursor, "region": Qt.CrossCursor}
        self.canvas.setCursor(cursors.get(mode, Qt.ArrowCursor))
        self.modeChanged.emit(mode)

    @property
    def mode(self) -> str:
        return self._mode

    def reset_view(self) -> None:
        """请求主窗口按 spec 重新渲染（回到原始范围）。"""
        self.regionSelected.emit([])

    # ------------------------------------------------------------------
    def _install_selector(self, ax) -> None:
        if self._selector is not None:
            try:
                self._selector.disconnect_events()
            except Exception:                           # noqa: BLE001
                pass
            self._selector = None
        try:
            self._selector = RectangleSelector(
                ax, self._on_rect, useblit=False, button=[1],
                interactive=False, minspanx=0.0, minspany=0.0,
                props=dict(facecolor="#2563eb", edgecolor="#2563eb",
                           alpha=0.12, linewidth=0.9))
            self._selector.set_active(self._mode in ("zoom", "region"))
        except Exception:                               # noqa: BLE001
            self._selector = None

    def _first_axes(self):
        return self.figure.axes[0] if self.figure.axes else None

    def _on_rect(self, eclick, erelease) -> None:
        if eclick.xdata is None or erelease.xdata is None:
            return
        x0, x1 = sorted([float(eclick.xdata), float(erelease.xdata)])
        y0, y1 = sorted([float(eclick.ydata), float(erelease.ydata)])
        if abs(x1 - x0) < 1e-9 or abs(y1 - y0) < 1e-9:
            return

        if self._mode == "region":
            self.regionSelected.emit([x0, x1, y0, y1])
            return

        ax = self._first_axes()
        if ax is None:
            return
        if hasattr(ax, "set_extent"):
            try:
                import cartopy.crs as ccrs
                ax.set_extent([x0, x1, y0, y1], crs=ccrs.PlateCarree())
                self.canvas.draw_idle()
                return
            except Exception:                           # noqa: BLE001
                pass
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # 鼠标取值
    # ------------------------------------------------------------------
    def _on_motion(self, event) -> None:
        if self._mode == "pan" and event.button == 1 \
                and self._pan_origin is not None and event.x is not None:
            self._do_pan(event)
            return
        if self._mode != "pick" or self._data is None:
            return
        if event.inaxes is None or event.xdata is None:
            return
        text = self._sample(event.xdata, event.ydata)
        if text:
            self.coordsChanged.emit(text)

    def _sample(self, x, y) -> str:
        d = self._data
        if d is None or d.values is None:
            return ""
        try:
            if d.x_role is AxisRole.LON and d.y_role is AxisRole.LAT \
                    and np.ndim(d.x) == 1 and np.ndim(d.y) == 1:
                xs, ys = np.asarray(d.x), np.asarray(d.y)
                ix = int(np.argmin(np.abs(xs - x)))
                iy = int(np.argmin(np.abs(ys - y)))
                val = float(d.values[iy, ix])
                shown = ("%.6g" % val) if np.isfinite(val) else "缺失"
                return "经度 %.4f°   纬度 %.4f°    %s = %s%s" % (
                    xs[ix], ys[iy], d.name, shown,
                    (" %s" % d.units) if d.units else "")
            # 非地理场（时间剖面等）
            xv = np.asarray(d.x).ravel()
            yv = np.asarray(d.y).ravel()
            if xv.size < 2 or yv.size < 2:
                return ""
            ix = int(np.argmin(np.abs(xv - x)))
            iy = int(np.argmin(np.abs(yv - y)))
            val = float(np.asarray(d.values)[iy, ix])
            return "%s = %.6g    (%s=%.4g, %s=%.4g)" % (
                d.name, val, d.x_name, xv[ix], d.y_name, yv[iy])
        except Exception:                               # noqa: BLE001
            return ""

    # ------------------------------------------------------------------
    # 平移
    # ------------------------------------------------------------------
    def _on_press(self, event) -> None:
        if self._mode != "pan" or event.button != 1:
            return
        ax = self._first_axes()
        if ax is None or event.xdata is None or event.ydata is None:
            return
        self._pan_origin = (event.xdata, event.ydata)
        self._pan_limits = (ax.get_xlim(), ax.get_ylim())

    def _do_pan(self, event) -> None:
        ax = self._first_axes()
        if ax is None or event.xdata is None:
            return
        ox, oy = self._pan_origin
        dx, dy = ox - event.xdata, oy - event.ydata
        (x0, x1), (y0, y1) = self._pan_limits
        try:
            ax.set_xlim(x0 + dx, x1 + dx)
            ax.set_ylim(y0 + dy, y1 + dy)
            self.canvas.draw_idle()
        except Exception:                               # noqa: BLE001
            pass

    def _on_release(self, event) -> None:
        self._pan_origin = None
        self._pan_limits = None

    def to_array(self):
        """把当前画布抓成 numpy 数组（预览/缩略图用）。"""
        self.canvas.draw()
        return np.asarray(self.canvas.buffer_rgba())[:, :, :3].copy()
