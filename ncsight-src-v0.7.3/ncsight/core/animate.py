# -*- coding: utf-8 -*-
"""
动画导出
========
对应 Panoply 的 `PanExportAnimationTask` + JCodec。

沿着某一个维度（通常是 time）逐帧渲染并编码。
  * MP4  —— 需要系统里有 ffmpeg（推荐，体积小、兼容好）
  * GIF  —— 纯 Python（Pillow）即可，不依赖外部程序，适合塞进 PPT

帧数很多时非常耗时，建议先把 bbox 收窄或用较小的 preset。
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Callable, List, Optional, Tuple

import numpy as np

from .plot.base import PlotSpec, render
from .reader import NcSource


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def animation_output(ext: str = ".mp4") -> Optional[str]:
    """推荐输出格式；没有 ffmpeg 时降级为 gif。"""
    ext = ext.lower()
    if ext == ".mp4" and not ffmpeg_available():
        return ".gif"
    if ext in (".mp4", ".gif", ".webm"):
        return ext
    return ".mp4" if ffmpeg_available() else ".gif"


def animate(spec: PlotSpec, source: NcSource, dim: str = "time",
            out_path: str = "animation.mp4",
            fps: int = 8, start: int = 0, stop: Optional[int] = None,
            step: int = 1, progress: Optional[Callable[[int, int], None]] = None,
            on_cancel: Optional[Callable[[], bool]] = None) -> str:
    """
    沿 `dim` 维逐帧渲染并导出动画。

    参数
    ----
    dim         要遍历的维度名（如 "time"）
    out_path    输出文件；扩展名决定格式（.mp4 / .gif）
    fps         帧率
    start/stop  帧范围（stop 为 None 表示到末尾）
    step        步长
    progress    回调 (已完成帧数, 总帧数)
    on_cancel   返回 True 则中止（GUI 的取消按钮用）
    """
    import matplotlib.animation as manim
    import matplotlib.pyplot as plt

    vi = source.variables.get(spec.variable)
    if vi is None:
        raise ValueError("变量不存在：%s" % spec.variable)
    if dim not in vi.dims:
        raise ValueError("变量 %s 没有维度 %s（可选：%s）"
                         % (spec.variable, dim, ", ".join(vi.dims)))

    axis = list(vi.dims).index(dim)
    total = vi.shape[axis]
    stop = total if stop is None else min(int(stop), total)
    frames = list(range(int(start), stop, max(1, int(step))))
    if not frames:
        raise ValueError("帧范围为空")

    ext = os.path.splitext(out_path)[1].lower() or ".mp4"
    fmt = animation_output(ext)
    out_path = os.path.splitext(out_path)[0] + fmt
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)

    # 时间轴坐标（用于标题）
    try:
        coord = source.read_axis(dim)
    except Exception:                                   # noqa: BLE001
        coord = np.arange(total, dtype="float64")

    first = True
    fig = None
    ax = None
    rendered: List = []

    for i, idx in enumerate(frames):
        if on_cancel is not None and on_cancel():
            break
        sel = dict(spec.select)
        sel[dim] = int(idx)
        frame_spec = spec.clone(select=sel, outfile=None)
        if frame_spec.title is None:
            base = spec.title or ""
            frame_spec.title = "%s  %s=%s" % (base, dim, _fmt(coord[idx]))

        if first:
            res = render(frame_spec, source, fig=None, ax=None)
            fig, ax = res.fig, res.ax
            first = False
        else:
            # 复用同一对 fig/ax：清空后重画，避免创建上千个 Figure 导致内存爆掉
            ax.clear()
            render(frame_spec, source, fig=fig, ax=ax)

        fig.canvas.draw()
        rendered.append(_grab(fig))
        if progress:
            progress(i + 1, len(frames))

    if not rendered:
        raise RuntimeError("没有渲染出任何帧")

    if fmt == ".gif":
        _write_gif(rendered, out_path, fps)
    else:
        _write_mp4(rendered, out_path, fps)

    try:
        plt.close(fig)
    except Exception:                                   # noqa: BLE001
        pass
    return out_path


def _grab(fig) -> np.ndarray:
    """把当前 Figure 抓成 RGB 数组。"""
    buf = np.asarray(fig.canvas.buffer_rgba())
    return buf[:, :, :3].copy()


def _write_gif(frames: List[np.ndarray], path: str, fps: int) -> None:
    from PIL import Image
    imgs = [Image.fromarray(f) for f in frames]
    imgs[0].save(path, save_all=True, append_images=imgs[1:],
                 duration=int(1000 / max(1, fps)), loop=0, optimize=True)


def _write_mp4(frames: List[np.ndarray], path: str, fps: int) -> None:
    """优先用 ffmpeg 命令行（比 matplotlib 的 writer 更可靠）。"""
    import subprocess
    h, w = frames[0].shape[:2]
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", "%dx%d" % (w, h), "-pix_fmt", "rgb24",
        "-r", str(max(1, fps)), "-i", "-",
        "-an", "-vcodec", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "18", path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in frames:
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0 or not os.path.exists(path):
        # ffmpeg 不可用 → 降级为 GIF
        _write_gif(frames, os.path.splitext(path)[0] + ".gif", fps)


def _fmt(v) -> str:
    try:
        f = float(v)
        if abs(f) >= 1e6 or (abs(f) < 1e-3 and f != 0):
            return "%.3g" % f
        return "%.4g" % f
    except (TypeError, ValueError):
        return str(v)


def animatable_dims(spec: PlotSpec, source: NcSource) -> List[Tuple[str, int]]:
    """列出这个变量可以沿哪些维度做动画（排除绘图平面的那两维）。"""
    vi = source.variables.get(spec.variable)
    if vi is None or vi.ndim < 3:
        return []
    return [(d, vi.shape[i]) for i, d in enumerate(vi.dims[:-2])]
