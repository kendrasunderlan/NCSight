# -*- coding: utf-8 -*-
"""
命令行接口
==========
对应 Panoply 的 `PanoplyCL` —— 但比它好用得多。

设计原则：
  * 图形界面与命令行**共用同一套 core 渲染函数**，所见即所得。
  * 任何 PlotSpec 字段都能用 `--set key=value` 覆盖，所以不用为每个
    参数写一个 flag，新功能天然可脚本化。
  * 出图配置可导出成 YAML，进版本管理，实现「图随代码可复现」。

用法速览
--------
    ncsight info  data.nc
    ncsight plot  data.nc -v sst -o sst.png --projection Robinson
    ncsight plot  data.nc --spec sst.plot.yaml
    ncsight plot  data.nc -v sst --set bbox=[100,180,-20,45] --set cmap=thermal
    ncsight spec  data.nc -v sst -o sst.plot.yaml      # 生成配置模板
    ncsight batch ./ncdata -o ./figures --projection Robinson
    ncsight animate data.nc -v sst --dim time -o loop.mp4 --fps 8
    ncsight gui   data.nc
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from .version import (APP_NAME, APP_NAME_CN, version_info, version_string,
                      MILESTONE)
from .core.reader import NcSource, NcSourceError
from .core.plot.base import PlotSpec, render, PLOT_KINDS, PROJECTIONS


# --------------------------------------------------------------------------
# 参数解析辅助
# --------------------------------------------------------------------------
def _parse_value(text: str) -> Any:
    """把命令行字符串转成合适的 Python 值（支持 list / bool / number / null）。"""
    try:
        import yaml
        return yaml.safe_load(text)
    except Exception:                                   # noqa: BLE001
        pass
    low = text.strip().lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _apply_sets(spec: PlotSpec, pairs: Optional[List[str]]) -> PlotSpec:
    """应用 --set key=value（支持点号路径，如 overlays.coastline=false）。"""
    for item in pairs or []:
        if "=" not in item:
            raise SystemExit("--set 参数格式应为 key=value，收到：%s" % item)
        key, _, raw = item.partition("=")
        key = key.strip()
        value = _parse_value(raw)
        if "." in key:
            head, _, tail = key.partition(".")
            target = getattr(spec, head, None)
            if target is not None and hasattr(target, tail):
                setattr(target, tail, value)
            else:
                raise SystemExit("未知的配置项：%s" % key)
        elif hasattr(spec, key):
            setattr(spec, key, value)
        else:
            raise SystemExit("未知的配置项：%s（可用 --list-options 查看）" % key)
    return spec


def _add_common_plot_args(s: argparse.ArgumentParser) -> None:
    """
    所有出图类子命令共享的便捷参数。

    设计说明：只有**最高频**的选项才给专门的 flag；其余任何 PlotSpec 字段
    一律用 `--set key=value` 覆盖。这样既保证了常用场景的输入简洁，
    又不会因为新增功能就不断往命令行里加参数。
    """
    s.add_argument("--projection", help="投影，如 Robinson（见 ncsight options）")
    s.add_argument("--cmap", help="色表，如 thermal / balance / viridis")
    s.add_argument("--kind", help="图型：map/vector/line/hovmoller/section/zonal")
    s.add_argument("--bbox", nargs=4, type=float, metavar=("LON0", "LON1", "LAT0", "LAT1"),
                   help="区域范围")
    s.add_argument("--preset", help="图幅预设：single/double/square/slide/a4_land")
    s.add_argument("--vmin", type=float, help="色标下限")
    s.add_argument("--vmax", type=float, help="色标上限")
    s.add_argument("--nbins", type=int, help="色阶数")
    s.add_argument("--title", help="图标题")
    s.add_argument("--fontsize", type=float, help="基准字号")
    s.add_argument("--land", action="store_true", help="叠加陆地填充")
    s.add_argument("--ocean", action="store_true", help="叠加海洋填充")
    s.add_argument("--no-coastline", action="store_true", help="不画海岸线")
    s.add_argument("--contours", action="store_true", help="叠加等值线")
    s.add_argument("--stats", action="store_true", help="标注统计量")


# 便捷参数 → PlotSpec 字段的映射（值为 None/False 时跳过）
_COMMON_MAP = [
    ("projection", "projection", None),
    ("cmap", "cmap", None),
    ("kind", "kind", None),
    ("bbox", "bbox", None),
    ("preset", "preset", None),
    ("vmin", "vmin", None),
    ("vmax", "vmax", None),
    ("nbins", "nbins", None),
    ("title", "title", None),
    ("fontsize", "fontsize", None),
]

_COMMON_MAP_OVERLAY = [
    ("land", "land"),
    ("ocean", "ocean"),
]


def _apply_common(spec: PlotSpec, args) -> PlotSpec:
    for attr, field, _ in _COMMON_MAP:
        val = getattr(args, attr, None)
        if val is not None:
            setattr(spec, field, val)
    for attr, field in _COMMON_MAP_OVERLAY:
        if getattr(args, attr, False):
            setattr(spec.overlays, field, True)
    if getattr(args, "no_coastline", False):
        spec.overlays.coastline = False
    if getattr(args, "contours", False):
        spec.show_contours = True
    if getattr(args, "stats", False):
        spec.show_stats = True
    return spec


def _load_spec(args) -> PlotSpec:
    spec = PlotSpec.load(args.spec) if getattr(args, "spec", None) else PlotSpec()
    spec = _apply_common(spec, args)
    if getattr(args, "variable", None):
        spec.variable = args.variable
    if getattr(args, "out", None):
        spec.outfile = args.out
    return _apply_sets(spec, getattr(args, "set", None))


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------
def cmd_info(args) -> int:
    try:
        with NcSource(args.dataset) as src:
            if args.json:
                data = src.overview()
                data["plottable"] = [
                    {"name": v.name, "kind": v.kind.value, "shape": list(v.shape),
                     "units": v.units, "plot_options": v.plot_options}
                    for v in src.plottable()]
                print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
            else:
                print(src.describe())
                if args.verbose:
                    for v in src.plottable():
                        print("\n" + "=" * 68)
                        print(src.describe_text(v.name))
        return 0
    except NcSourceError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 2


def cmd_plot(args) -> int:
    spec = _load_spec(args)
    try:
        with NcSource(args.dataset) as src:
            if not spec.variable:
                primary = src.primary_field()
                if primary is None:
                    print("错误：数据集中没有可制图的变量", file=sys.stderr)
                    return 2
                spec.variable = primary.name
                print("已自动选择变量：%s（可用 -v 指定）" % spec.variable)
            res = render(spec, src)
            out = args.out or spec.outfile or _default_out(args.dataset, spec.variable)
            fmt = args.format or os.path.splitext(out)[1].lstrip(".") or "png"
            from .core.export import save_figure
            path = save_figure(res.fig, out, fmt=fmt, dpi=args.dpi)
            print("已输出：%s" % path)
            if args.save_spec:
                sp = spec.save(args.save_spec)
                print("绘图配置已保存：%s" % sp)
        return 0
    except (NcSourceError, ValueError) as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 2


def cmd_spec(args) -> int:
    """生成一份绘图配置模板（可编辑后再用 plot --spec 复用）。"""
    try:
        with NcSource(args.dataset) as src:
            _pf = src.primary_field()
            var = args.variable or (_pf.name if _pf else "")
            spec = PlotSpec(variable=var)
            vi = src.variables.get(var)
            if vi:
                spec.kind = vi.plot_options[0] if vi.plot_options else "map"
            path = spec.save(args.out or "%s.plot.yaml" % (var or "spec"))
            print("配置模板已生成：%s" % path)
            print("编辑后可用：ncsight plot %s --spec %s" % (args.dataset, path))
        return 0
    except NcSourceError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 2


def cmd_animate(args) -> int:
    from .core.animate import animate, ffmpeg_available, animatable_dims
    spec = _load_spec(args)
    try:
        with NcSource(args.dataset) as src:
            if not spec.variable:
                cands = [v for v in src.plottable() if v.ndim >= 3]
                if not cands:
                    print("错误：没有 ≥3 维的变量可以做动画", file=sys.stderr)
                    return 2
                spec.variable = cands[0].name
            dims = animatable_dims(spec, src)
            if not dims:
                print("错误：变量 %s 没有可动画的维度" % spec.variable, file=sys.stderr)
                print("       可动画维度需要 ≥3 维（前几维才能遍历）", file=sys.stderr)
                return 2
            dim = args.dim or dims[0][0]
            if not ffmpeg_available() and args.out.lower().endswith(".mp4"):
                print("提示：未检测到 ffmpeg，将自动导出为 GIF")
            print("沿 %s 维动画（共 %d 帧可选）" % (dim, dict(dims).get(dim, 0)))

            def _progress(done, total_):
                sys.stdout.write("\r  渲染中 %d/%d" % (done, total_))
                sys.stdout.flush()

            path = animate(spec, src, dim=dim, out_path=args.out or "animation.mp4",
                           fps=args.fps, step=args.step, progress=_progress)
            print("\n已输出：%s" % path)
        return 0
    except (NcSourceError, ValueError, RuntimeError) as exc:
        print("\n错误：%s" % exc, file=sys.stderr)
        return 2


def cmd_batch(args) -> int:
    from .core.batch import batch_run, find_datasets, write_batch_report
    spec = _load_spec(args)

    if os.path.isfile(args.input):
        paths = [args.input]
    else:
        paths = find_datasets(args.input, patterns=args.include,
                             recursive=not args.no_recursive)
    if not paths:
        print("错误：在 %s 里没有找到数据文件" % args.input, file=sys.stderr)
        return 2
    print("找到 %d 个数据集" % len(paths))

    over_vars = args.variables.split(",") if args.variables else None
    total_done = [0]

    def _progress(done, total, name):
        total_done[0] = done
        sys.stdout.write("\r  出图 %d/%d  %-40s" % (done, total, name[:40]))
        sys.stdout.flush()

    result = batch_run(paths, spec, out_dir=args.out, pattern=args.pattern,
                       fmt=args.format, dpi=args.dpi,
                       over_variables=over_vars, over_dim=args.over_dim,
                       progress=_progress)
    print("\n" + result.summary())
    if args.report:
        write_batch_report(result, args.report)
        print("报告已写入：%s" % args.report)
    return 0 if result.n_fail == 0 else 1


def cmd_timeseries(args) -> int:
    """多文件时序 + 科学指标。"""
    from .core import PlotSpec, render
    from .core.indicators import ALL_INDICATORS, indicator_title
    from .core.series import SeriesBuilder

    paths = SeriesBuilder.expand(args.inputs)
    if not paths:
        print("没有找到任何 nc 文件", file=sys.stderr)
        return 2
    print("共 %d 个文件" % len(paths))

    inds_raw = (args.indicators or "").strip()
    if inds_raw.lower() in ("all", "*"):
        inds = list(ALL_INDICATORS)
    else:
        inds = [s.strip() for s in inds_raw.split(",") if s.strip()]
    if args.spectrum:
        inds = ["spectrum", "summary"]

    spec = PlotSpec(
        kind="spectrum" if args.spectrum else "series",
        variable=args.variable or "",
        series_variable=args.variable or "",
        series_stat=args.stat,
        bbox=list(args.bbox) if args.bbox else None,
        series_point=tuple(args.point) if args.point else None,
        indicators=inds,
        preset=args.preset,
        dpi=args.dpi,
        title=args.title or None,
    )
    try:
        res = render(spec, paths)
    except Exception as exc:                            # noqa: BLE001
        print("计算失败：%s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 1

    out = res.save(args.out)
    print("已输出：%s" % out)

    ts = res.series
    if ts is not None:
        print("")
        print("序列：%s" % ts.caption())
        print("  文件 %d 个（成功 %d），时间轴来源：%s"
              % (ts.meta.get("n_files", 0), ts.meta.get("n_ok", 0),
                 ts.time_source))
        for w in (ts.meta.get("builder_warnings") or []):
            print("  ⚠ %s" % w)
    for r in (res.indicators or []):
        if r.annotation:
            print("  %-16s %s" % (indicator_title(r.key), r.annotation))
        for k, v in (r.table or [])[:3]:
            print("      %-14s %s" % (k, v))
    return 0


def cmd_export(args) -> int:
    """把数据导出成 CSV / NPZ / 文本（对应 Panoply 的 Export Data）。"""
    from .core import export as ex
    try:
        with NcSource(args.dataset) as src:
            if args.all_overview:
                path = ex.export_overview(src, args.out)
            else:
                _pf = src.primary_field()
                var = args.variable or (_pf.name if _pf else "")
                spec = _load_spec(args)
                fd = src.read_field(var, spec.select)
                n = fd.valid_count
                if args.format == "csv":
                    if n > 3_000_000:
                        print("提示：该场有 %d 个有效点，CSV 体积可能超过 100 MB。"
                              % n)
                        print("      如需完整网格，建议改用 --format npz（体积小约 7 倍）。")
                    path = ex.export_grid_csv(fd, args.out)
                elif args.format == "npz":
                    path = ex.export_grid_npz(fd, args.out)
                else:
                    path = ex.export_labeled_text(src, var, args.out)
            print("已导出：%s" % path)
        return 0
    except NcSourceError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 2


def cmd_gui(args) -> int:
    try:
        from .gui.app import run as run_gui
    except ImportError as exc:
        print("错误：无法启动图形界面（%s）" % exc, file=sys.stderr)
        print("       请确认已安装 PySide6：pip install PySide6", file=sys.stderr)
        return 2
    return run_gui(args.dataset)


def cmd_version(args) -> int:
    vi = version_info()
    print("%s (%s) %s" % (vi["app"], vi["app_cn"], vi["string"]))
    print("阶段    : %s" % vi["stage"])
    print("里程碑  : %s" % vi["milestone"])
    print("发布日期: %s" % vi["release_date"])
    if args.verbose:
        print("\n── 运行环境 ──")
        print("Python  : %s" % sys.version.split()[0])
        for mod in ("numpy", "matplotlib", "netCDF4", "xarray", "cartopy",
                    "pyproj", "scipy", "PySide6", "cmocean", "cmcrameri", "yaml"):
            try:
                m = __import__(mod)
                print("%-11s: %s" % (mod, getattr(m, "__version__", "?")))
            except Exception:                           # noqa: BLE001
                print("%-11s: 未安装" % mod)
    return 0


def cmd_options(args) -> int:
    """列出所有可用的图型、投影、配置项（写脚本时的速查）。"""
    print("── 图型 (kind) ──")
    for k, v in PLOT_KINDS.items():
        print("  %-12s %s" % (k, v))
    print("\n── 投影 (projection) ──")
    for k, v in PROJECTIONS:
        print("  %-20s %s" % (k, v))
    print("\n── PlotSpec 可配置项（用 --set key=value 覆盖）──")
    import dataclasses
    for f in dataclasses.fields(PlotSpec):
        d = f.default if f.default is not dataclasses.MISSING else \
            (f.default_factory() if f.default_factory is not dataclasses.MISSING else None)  # type: ignore
        print("  %-22s %s" % (f.name, type(d).__name__))
    return 0


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def _default_out(dataset: str, variable: str) -> str:
    stem = os.path.splitext(os.path.basename(dataset))[0]
    return "%s_%s.png" % (stem, variable or "plot")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ncsight",
        description="%s (%s) —— %s" % (APP_NAME, APP_NAME_CN,
                                       "面向海洋遥感的 netCDF 可视化工作台"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  ncsight info  data.nc\n"
               "  ncsight plot  data.nc -v sst --projection Robinson -o sst.png\n"
               "  ncsight plot  data.nc --spec sst.plot.yaml\n"
               "  ncsight batch ./ncdata -o ./figures\n"
               "  ncsight gui   data.nc\n")
    p.add_argument("-V", "--version", action="store_true", help="显示版本信息")
    sub = p.add_subparsers(dest="command")

    # info
    s = sub.add_parser("info", help="查看数据集结构")
    s.add_argument("dataset")
    s.add_argument("--json", action="store_true", help="以 JSON 输出")
    s.add_argument("-v", "--verbose", action="store_true", help="显示每个变量的完整属性")
    s.set_defaults(func=cmd_info)

    # plot
    s = sub.add_parser("plot", help="出一张图")
    s.add_argument("dataset")
    s.add_argument("-v", "--variable", help="变量名")
    s.add_argument("-o", "--out", help="输出文件（扩展名决定格式）")
    s.add_argument("--format", help="强制输出格式：png/jpg/tiff/pdf/svg/eps")
    s.add_argument("--dpi", type=int, default=300, help="位图分辨率（默认 300）")
    s.add_argument("--spec", help="从 YAML 配置加载绘图参数")
    s.add_argument("--save-spec", help="把本次参数另存为 YAML（可复现）")
    s.add_argument("--set", action="append", metavar="K=V",
                   help="覆盖任意 PlotSpec 字段，可重复使用")
    _add_common_plot_args(s)
    s.set_defaults(func=cmd_plot)

    # spec
    s = sub.add_parser("spec", help="生成绘图配置模板")
    s.add_argument("dataset")
    s.add_argument("-v", "--variable")
    s.add_argument("-o", "--out")
    s.set_defaults(func=cmd_spec)

    # animate
    s = sub.add_parser("animate", help="沿某个维度导出动画")
    s.add_argument("dataset")
    s.add_argument("-v", "--variable")
    s.add_argument("--dim", help="要遍历的维度名（如 time / depth）")
    s.add_argument("-o", "--out", default="animation.mp4")
    s.add_argument("--fps", type=int, default=8)
    s.add_argument("--step", type=int, default=1)
    s.add_argument("--spec")
    s.add_argument("--set", action="append", metavar="K=V")
    _add_common_plot_args(s)
    s.set_defaults(func=cmd_animate)

    # batch
    s = sub.add_parser("batch", help="批量出图（目录或单个文件）")
    s.add_argument("input", help="数据目录或单个文件")
    s.add_argument("-o", "--out", default="figures", help="输出目录")
    s.add_argument("--pattern", default="{stem}_{var}",
                   help="文件名模板，占位符：{stem} {var} {index} {dim} {dimval}")
    s.add_argument("--format", default="png")
    s.add_argument("--dpi", type=int, default=300)
    s.add_argument("--variables", help="逗号分隔的变量名；留空则用变量树第一个")
    s.add_argument("--over-dim", help="沿该维度逐个索引出图，如 time")
    s.add_argument("--include", action="append", help="额外的文件名通配符")
    s.add_argument("--no-recursive", action="store_true", help="不递归子目录")
    s.add_argument("--report", help="把结果写成报告文件")
    s.add_argument("-v", "--variable")
    s.add_argument("--spec")
    s.add_argument("--set", action="append", metavar="K=V")
    _add_common_plot_args(s)
    s.set_defaults(func=cmd_batch)

    # export
    # ---- timeseries：多文件时序 + 科学指标 ----
    p_ts = sub.add_parser("timeseries",
                          help="多个 nc 文件 → 时序 + 科学指标（趋势/MK/季节/谱…）")
    p_ts.add_argument("inputs", nargs="+",
                      help="nc 文件、通配符或文件夹（可多个）")
    p_ts.add_argument("-o", "--out", required=True, help="输出图像路径")
    p_ts.add_argument("-v", "--variable", default="", help="变量名（默认自动选主轴变量）")
    p_ts.add_argument("--stat", default="mean",
                      help="空间统计：mean/median/max/min/std/p90/p10")
    p_ts.add_argument("--bbox", nargs=4, type=float, metavar=("LON0","LON1","LAT0","LAT1"),
                      help="区域范围")
    p_ts.add_argument("--point", nargs=2, type=float, metavar=("LON","LAT"),
                      help="取单点（优先于 --bbox）")
    p_ts.add_argument("--indicators", default="trend,mk,sen,running,summary",
                      help="要计算的指标，逗号分隔；'all' 表示全部")
    p_ts.add_argument("--spectrum", action="store_true", help="只画功率谱")
    p_ts.add_argument("--preset", default="double", help="图幅预设")
    p_ts.add_argument("--dpi", type=int, default=150)
    p_ts.add_argument("--title", default="")
    p_ts.set_defaults(func=cmd_timeseries)

    s = sub.add_parser("export", help="导出数据为 CSV / NPZ / 文本")
    s.add_argument("dataset")
    s.add_argument("-v", "--variable")
    s.add_argument("-o", "--out", required=True)
    s.add_argument("--format", choices=["csv", "npz", "text"], default="csv")
    s.add_argument("--all-overview", action="store_true",
                   help="导出整个数据集的结构说明")
    s.set_defaults(func=cmd_export)

    # gui
    s = sub.add_parser("gui", help="启动图形界面")
    s.add_argument("dataset", nargs="?", help="启动时自动打开的数据集")
    s.set_defaults(func=cmd_gui)

    # version / options
    s = sub.add_parser("version", help="显示版本与运行环境")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_version)

    s = sub.add_parser("options", help="列出所有可用图型/投影/配置项")
    s.set_defaults(func=cmd_options)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "version", False) and not getattr(args, "command", None):
        return cmd_version(argparse.Namespace(verbose=True))
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
