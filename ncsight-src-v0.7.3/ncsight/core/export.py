# -*- coding: utf-8 -*-
"""
导出子系统
==========
对应 Panoply 的 `PanImageUtils` / `PanDataWriter` / `Export Plotted Data Grid`。

科研工作流的出口只有两类，这里都覆盖：
  1. **图**：PNG / JPEG / TIFF / PDF / SVG / EPS —— PDF 与 SVG 是矢量，
     投稿必须用它们（无损缩放，文字可编辑）。
  2. **数据**：把「正在画的那个网格」导出成 CSV / NPZ ——
     发表配图的原始数据要能追溯，Panoply 也有这个功能。
"""

from __future__ import annotations

import csv
import os
from typing import Dict, List, Optional, Sequence

import numpy as np

from .reader import NcSource, FieldData


# --------------------------------------------------------------------------
# 图像
# --------------------------------------------------------------------------
VECTOR_FORMATS = {"pdf", "svg", "eps", "ps"}
RASTER_FORMATS = {"png", "jpg", "jpeg", "tif", "tiff", "webp", "bmp"}

FORMAT_LABELS = {
    "png": "PNG 位图（预览/PPT）",
    "jpg": "JPEG 位图（小体积）",
    "tiff": "TIFF 位图（无损/印刷）",
    "pdf": "PDF 矢量（投稿首选）",
    "svg": "SVG 矢量（可编辑）",
    "eps": "EPS 矢量（部分期刊要求）",
}


def save_figure(fig, path: str, fmt: Optional[str] = None,
                dpi: int = 300, transparent: bool = False) -> str:
    """
    保存 Figure。矢量格式会忽略 dpi 的像素意义但保留线宽比例。
    """
    path = os.path.abspath(path)
    fmt = (fmt or os.path.splitext(path)[1].lstrip(".") or "png").lower()
    if fmt == "jpeg":
        fmt = "jpg"
    if fmt == "tif":
        fmt = "tiff"
    if not os.path.splitext(path)[1]:
        path += "." + fmt

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    kw = dict(format=fmt, facecolor=fig.get_facecolor())
    if fmt in VECTOR_FORMATS:
        kw["transparent"] = transparent
    else:
        kw["dpi"] = int(dpi)
    fig.savefig(path, **kw)
    return path


def figure_to_bytes(fig, fmt: str = "png", dpi: int = 150) -> bytes:
    """渲染到内存（供 GUI 预览或剪贴板使用）。"""
    import io
    buf = io.BytesIO()
    fmt = fmt.lower()
    kw = dict(format=fmt, facecolor=fig.get_facecolor())
    if fmt not in VECTOR_FORMATS:
        kw["dpi"] = dpi
    fig.savefig(buf, **kw)
    return buf.getvalue()


def copy_to_clipboard(fig, dpi: int = 150) -> bool:
    """
    把当前图复制到系统剪贴板。成功返回 True，无 GUI 环境返回 False。

    ⚠️ 这里是本项目**唯一**在 core 里 import GUI 库的地方，且刻意写成
    函数内惰性导入 + 异常兜底：命令行版在服务器 / 超算上没有 Qt 也照样能跑，
    只是这个功能不可用（返回 False）。`tests/test_purity.py` 会验证
    「导入 ncsight.core 不会把 Qt 拉进 sys.modules」，这条约束不会失守。
    """
    try:
        from PySide6.QtGui import QGuiApplication, QImage
        data = figure_to_bytes(fig, "png", dpi)
        app = QGuiApplication.instance()
        if app is None:
            return False
        img = QImage.fromData(data, "PNG")
        QGuiApplication.clipboard().setImage(img)
        return True
    except Exception:                                   # noqa: BLE001
        return False


# --------------------------------------------------------------------------
# 数据
# --------------------------------------------------------------------------
def export_grid_csv(fd: FieldData, path: str,
                    include_nan: bool = False,
                    header: bool = True) -> str:
    """
    把「正在绘制的二维网格」导出成 CSV：列 = lon,lat,value。
    NaN 默认跳过（避免输出 3000 多万行无效数据）。

    体积提醒：一张 4320×8640 的全球场，有效点 700 多万个，
    CSV 会到 180 MB 上下。要保留完整网格请优先用 export_grid_npz
    （同样的数据只有约 25 MB，且保留形状与坐标，适合二次分析）。
    """
    path = _with_ext(path, ".csv")
    x, y = fd.x, fd.y
    if np.ndim(x) == 2:
        X, Y = np.asarray(x), np.asarray(y)
    else:
        X, Y = np.meshgrid(np.asarray(x), np.asarray(y))
    V = np.asarray(fd.values)

    xs = X.ravel()
    ys = Y.ravel()
    vs = V.ravel()
    keep = np.isfinite(vs)
    if not include_nan:
        xs, ys, vs = xs[keep], ys[keep], vs[keep]

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        if header:
            w.writerow([fd.x_name or "x", fd.y_name or "y",
                        "%s%s" % (fd.name, (" [%s]" % fd.units) if fd.units else "")])
        for row in zip(xs.tolist(), ys.tolist(), vs.tolist()):
            w.writerow(["%.6g" % row[0], "%.6g" % row[1], "%.6g" % row[2]])
    return path


def export_grid_npz(fd: FieldData, path: str) -> str:
    """导出为 .npz（保留完整网格形状与坐标，适合二次分析）。"""
    path = _with_ext(path, ".npz")
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    np.savez_compressed(
        path,
        values=np.asarray(fd.values),
        x=np.asarray(fd.x), y=np.asarray(fd.y),
        x_name=fd.x_name, y_name=fd.y_name,
        name=fd.name, long_name=fd.long_name, units=fd.units,
    )
    return path


def export_series_csv(x: np.ndarray, y: np.ndarray, path: str,
                      xlabel: str = "x", ylabel: str = "y") -> str:
    path = _with_ext(path, ".csv")
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow([xlabel, ylabel])
        for a, b in zip(np.asarray(x).ravel().tolist(), np.asarray(y).ravel().tolist()):
            w.writerow([a, b])
    return path


def export_labeled_text(source: NcSource, name: str, path: str,
                        max_rows: int = 2000) -> str:
    """
    导出为带表头的纯文本（对应 Panoply 的 Export As Labeled Text）。
    大数据集会被截断，避免生成几百 MB 的文本。
    """
    path = _with_ext(path, ".txt")
    fd = source.read_field(name)
    vi = source.variables[name]
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# 数据集 : %s\n" % source.path)
        fh.write("# 变量   : %s\n" % name)
        fh.write("# 名称   : %s\n" % (vi.long_name or name))
        if vi.units:
            fh.write("# 单位   : %s\n" % vi.units)
        fh.write("# 维度   : %s 形状 %s\n" % (vi.dims, vi.shape))
        s = fd.stats()
        if s.get("n"):
            fh.write("# 统计   : n=%d min=%.6g max=%.6g mean=%.6g\n"
                     % (s["n"], s["min"], s["max"], s["mean"]))
        fh.write("#%s\n" % ("-" * 60))
        fh.write("%-14s %-14s %s\n" % (fd.x_name, fd.y_name, name))
        x, y = fd.x, fd.y
        if np.ndim(x) == 2:
            X, Y = np.asarray(x), np.asarray(y)
        else:
            X, Y = np.meshgrid(np.asarray(x), np.asarray(y))
        n = 0
        for i in range(X.shape[0]):
            for j in range(X.shape[1]):
                if n >= max_rows:
                    fh.write("... 已截断（超过 %d 行），请改用 CSV 或 NPZ 导出\n" % max_rows)
                    return path
                fh.write("%-14.6g %-14.6g %.6g\n" % (X[i, j], Y[i, j], fd.values[i, j]))
                n += 1
    return path


def export_overview(source: NcSource, path: str) -> str:
    """导出数据集结构说明（对应 Panoply 的 NcDump / Save Log As）。"""
    path = _with_ext(path, ".txt")
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(source.describe())
        fh.write("\n\n")
        for name in source.ds.variables:
            fh.write("\n" + "=" * 60 + "\n")
            fh.write(source.describe_text(name))
            fh.write("\n")
    return path


def export_spec_yaml(spec, path: str) -> str:
    """导出绘图配置（可复现出图的关键）。"""
    return spec.save(path)


# --------------------------------------------------------------------------
def _with_ext(path: str, ext: str) -> str:
    return path if path.lower().endswith(ext) else os.path.splitext(path)[0] + ext


def supported_image_formats() -> Dict[str, str]:
    return dict(FORMAT_LABELS)
