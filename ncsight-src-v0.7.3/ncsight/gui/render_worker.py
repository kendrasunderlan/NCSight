# -*- coding: utf-8 -*-
"""
后台渲染服务
============
**为什么需要它**：渲染必须离开 GUI 线程。

实测一张 4320x8640 的全球场，光 `pcolormesh` 建网格就要 13.4 秒。
如果这段代码跑在 Qt 主线程上，整个界面在这十几秒里完全无响应 ——
点不动、拖不动、连窗口都刷不出来，就是「卡死」的观感。

设计要点：
  * 工作线程里**自己开一个 NcSource**。netCDF4 的 Dataset 不是线程安全的，
    绝不能跨线程共用主线程那个句柄。工作线程持有自己的句柄并按路径缓存，
    路径不变就不用重新打开（打开+扫描只要 0.01 秒，成本可忽略）。
  * 渲染在**非 pyplot** 的 Figure 上完成（`style.new_figure` 直接用
    `matplotlib.figure.Figure`），因为 pyplot 维护全局注册表，非线程安全。
  * 结果（Figure + FieldData）通过信号发回主线程，由主线程挂到 Qt 画布上。
  * 主线程做**请求合并**：渲染期间用户又改了参数，只保留最后一次请求，
    等当前渲染完再跑，不会堆积一长串任务。
"""

from __future__ import annotations

import traceback
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.plot.base import PlotSpec, render
from ..core.reader import NcSource


class RenderWorker(QObject):
    """真正干活的对象的，活在子线程里。"""

    #: (req_id, result_or_None, error_text)
    done = Signal(int, object, str)
    #: (已完成的步数, 总步数, 说明文字) —— 从子线程发回，主线程刷新进度条
    progress = Signal(int, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path: Optional[str] = None
        self._source: Optional[NcSource] = None   # 只允许本线程访问

    # ------------------------------------------------------------------
    @Slot(int, object, object)
    def do_render(self, req_id: int, target, spec: PlotSpec) -> None:
        """
        target 可以是单个文件路径，也可以是路径列表。
        列表意味着「时序分析」—— 数据源是一批 nc 文件而不是一个数据集。
        """
        result = None
        error = ""
        tb = ""

        def _report(done, total, msg=""):
            try:
                self.progress.emit(int(done), int(total), str(msg))
            except Exception:                           # noqa: BLE001
                pass

        try:
            if isinstance(target, (list, tuple)):
                result = render(spec, list(target), progress=_report)
            else:
                src = self._ensure_source(target)
                result = render(spec, src, progress=_report)
        except Exception as exc:                        # noqa: BLE001
            error = "%s: %s" % (type(exc).__name__, exc)
            tb = traceback.format_exc()
        if error:
            # 把堆栈也带回主线程打印，方便定位
            error = error + "\n" + tb
        # 从子线程发信号给主线程会自动走队列连接，安全
        self.done.emit(req_id, result, error)

    def _ensure_source(self, path: str) -> NcSource:
        if self._source is not None and self._path == path:
            return self._source
        if self._source is not None:
            try:
                self._source.close()
            except Exception:                           # noqa: BLE001
                pass
            self._source = None
        self._source = NcSource(path)
        self._path = path
        return self._source

    @Slot()
    def shutdown(self) -> None:
        if self._source is not None:
            try:
                self._source.close()
            except Exception:                           # noqa: BLE001
                pass
            self._source = None


class RenderService(QObject):
    """
    对外的门面：管线程、管请求合并，主窗口只用它。

    用法：
        svc = RenderService()
        svc.done.connect(on_done)         # on_done(req_id, payload) 在主线程执行
        svc.submit(req_id, path, spec)    # 主线程调用
        svc.shutdown()                    # 关闭窗口时调用
    """

    done = Signal(int, object, str)
    busyChanged = Signal(bool)
    progress = Signal(int, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = QThread()
        self._thread.setObjectName("ncsight-render")
        self._worker = RenderWorker()
        self._worker.moveToThread(self._thread)

        # 主线程 emit -> 子线程 slot（队列连接）
        self._submit = _SubmitBridge(self._worker)
        self._worker.done.connect(self._on_done)
        self._worker.progress.connect(self._on_progress)

        self._thread.start()
        self._busy = False
        self._current_id = -1
        self._pending: Optional[tuple] = None

    # ------------------------------------------------------------------
    def submit(self, req_id: int, path, spec: PlotSpec) -> None:
        """请求渲染。若正在渲染则只保留最后一次，避免任务堆积。"""
        if self._busy:
            self._pending = (req_id, path, spec)
            return
        self._start(req_id, path, spec)

    def _start(self, req_id: int, path, spec: PlotSpec) -> None:
        self._busy = True
        self._current_id = req_id
        self.busyChanged.emit(True)
        self._submit.requested.emit(req_id, path, spec)

    def _on_progress(self, done: int, total: int, msg: str) -> None:
        # 过期请求的进度不要刷到界面上，否则进度条会来回跳
        if self._busy:
            self.progress.emit(done, total, msg)

    def _on_done(self, req_id: int, result: object, error: str) -> None:
        self._busy = False
        if req_id == self._current_id:
            self.done.emit(req_id, result, error)
        # 渲染期间攒下的最后一次请求，现在补跑
        if self._pending is not None:
            nid, npath, nspec = self._pending
            self._pending = None
            self._start(nid, npath, nspec)
        else:
            self.busyChanged.emit(False)

    @property
    def busy(self) -> bool:
        return self._busy

    def has_pending(self) -> bool:
        return self._pending is not None

    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        """关闭窗口时调用：让工作对象释放文件句柄并停掉线程。"""
        try:
            self._worker.shutdown()
        except Exception:                               # noqa: BLE001
            pass
        self._thread.quit()
        self._thread.wait(3000)


class _SubmitBridge(QObject):
    """把「主线程调用」转成「子线程执行」的信号桥。"""

    requested = Signal(int, object, object)

    def __init__(self, worker: RenderWorker, parent=None):
        super().__init__(parent)
        self.requested.connect(worker.do_render)
