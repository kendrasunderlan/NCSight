# -*- coding: utf-8 -*-
"""
批量出图
========
这是自研软件相对 Panoply 的核心优势所在 —— Panoply 的命令行能力很弱，
而这里「批量出图」只是把 render() 放进两层循环而已。

三种批量维度，可任意组合：
  1. 跨文件   —— 遍历一个目录下所有 nc 文件（如一整年的 L3 日产品）
  2. 跨变量   —— 一次把数据集里所有变量都出图
  3. 跨维度   —— 沿 time / depth 等维度逐个索引出图

文件名模板支持占位符：
  {stem}   源文件名（不含扩展名）
  {var}    变量名
  {index}  序号
  {dim}    维度名
  {dimval} 该维度当前的取值
"""

from __future__ import annotations

import glob
import os
import traceback
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from .plot.base import PlotSpec, render
from .reader import NcSource
from .export import save_figure


SUPPORTED_GLOBS = ["*.nc", "*.nc4", "*.cdf", "*.grib", "*.grib2", "*.grb",
                   "*.grb2", "*.hdf", "*.h5", "*.hdf5"]


@dataclass
class BatchItem:
    source_path: str
    spec: PlotSpec
    out_path: str = ""
    ok: bool = False
    error: str = ""
    elapsed: float = 0.0


@dataclass
class BatchResult:
    items: List[BatchItem] = field(default_factory=list)

    @property
    def n_ok(self) -> int:
        return sum(1 for i in self.items if i.ok)

    @property
    def n_fail(self) -> int:
        return sum(1 for i in self.items if not i.ok)

    def summary(self) -> str:
        lines = ["批量完成：成功 %d / 失败 %d / 共 %d"
                 % (self.n_ok, self.n_fail, len(self.items))]
        for it in self.items:
            flag = "OK  " if it.ok else "FAIL"
            lines.append("  [%s] %s -> %s%s"
                         % (flag, os.path.basename(it.source_path),
                            os.path.basename(it.out_path),
                            "" if it.ok else ("  (%s)" % it.error)))
        return "\n".join(lines)


def find_datasets(folder: str, patterns: Optional[Sequence[str]] = None,
                  recursive: bool = True) -> List[str]:
    """在目录里找所有可读的数据集。"""
    pats = list(patterns or SUPPORTED_GLOBS)
    out: List[str] = []
    for p in pats:
        glob_pat = os.path.join(folder, "**", p) if recursive else os.path.join(folder, p)
        out.extend(glob.glob(glob_pat, recursive=recursive))
    return sorted(set(out))


def _render_name(template: str, **kw) -> str:
    safe = {k: _sanitize(str(v)) for k, v in kw.items()}
    try:
        return template.format(**safe)
    except (KeyError, IndexError):
        return template


def _sanitize(text: str) -> str:
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text.strip()


def batch_run(paths: Sequence[str], spec_template: PlotSpec,
              out_dir: str, pattern: str = "{stem}_{var}_{index}",
              fmt: str = "png", dpi: int = 300,
              over_variables: Optional[Sequence[str]] = None,
              over_dim: Optional[str] = None,
              progress: Optional[Callable[[int, int, str], None]] = None,
              stop_flag: Optional[Callable[[], bool]] = None) -> BatchResult:
    """
    执行批量出图。

    参数
    ----
    paths            数据集路径列表
    spec_template    图规格模板（每个任务从它克隆）
    out_dir          输出目录
    pattern          文件名模板
    fmt              输出格式
    over_variables   若给定，则对每个变量各出一张图
    over_dim         若给定，则沿该维度逐索引各出一张图
    """
    os.makedirs(out_dir, exist_ok=True)
    result = BatchResult()

    # 先展开成任务清单，好让进度条有确切总数
    tasks: List[tuple] = []
    for path in paths:
        try:
            with NcSource(path) as src:
                variables = list(over_variables) if over_variables else \
                    [spec_template.variable or (src.plottable()[0].name
                                                if src.plottable() else "")]
                for var in variables:
                    if over_dim and var in src.variables \
                            and over_dim in src.variables[var].dims:
                        n = src.variables[var].shape[list(src.variables[var].dims).index(over_dim)]
                    else:
                        n = 1
                    for i in range(n):
                        tasks.append((path, var, i, n))
        except Exception as exc:                        # noqa: BLE001
            result.items.append(BatchItem(source_path=path, spec=spec_template,
                                          error="打开失败：%s" % exc))

    total = len(tasks)
    for k, (path, var, index, n) in enumerate(tasks):
        if stop_flag is not None and stop_flag():
            break
        stem = os.path.splitext(os.path.basename(path))[0]
        name = _render_name(pattern, stem=stem, var=var, index=index,
                            dim=over_dim or "", dimval=index)
        out_path = os.path.join(out_dir, "%s.%s" % (name, fmt))

        item = BatchItem(source_path=path, out_path=out_path,
                         spec=spec_template.clone())
        import time
        t0 = time.time()
        try:
            spec = item.spec
            spec.variable = var
            spec.outfile = out_path
            if over_dim:
                spec.select = dict(spec.select)
                spec.select[over_dim] = index
            with NcSource(path) as src:
                res = render(spec, src)
                save_figure(res.fig, out_path, fmt=fmt, dpi=dpi)
                import matplotlib.pyplot as plt
                plt.close(res.fig)
            item.ok = True
        except Exception as exc:                        # noqa: BLE001
            item.error = "%s: %s" % (type(exc).__name__, exc)
        item.elapsed = time.time() - t0
        result.items.append(item)
        if progress:
            progress(k + 1, total, os.path.basename(out_path))

    return result


def write_batch_report(result: BatchResult, path: str) -> str:
    """把批量结果写成报告（成功/失败/耗时）。"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(result.summary())
        fh.write("\n\n")
        fh.write("%-10s %-12s %s\n" % ("状态", "耗时(s)", "输出"))
        fh.write("-" * 70 + "\n")
        for it in result.items:
            fh.write("%-10s %-12.2f %s\n"
                     % ("OK" if it.ok else "FAIL", it.elapsed,
                        it.out_path or it.source_path))
    return path
