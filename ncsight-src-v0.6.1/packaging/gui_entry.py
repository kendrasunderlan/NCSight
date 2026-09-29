# -*- coding: utf-8 -*-
"""
PyInstaller 打包入口 —— 图形界面
===============================
这是一个**项目根目录下的薄壳脚本**，不放在 ncsight 包里面。

为什么不直接把 `ncsight/gui/app.py` 当入口？
因为 PyInstaller 会把入口脚本当成 `__main__` 执行且不设 `__package__`，
包内模块里的相对导入（如 `from ..version import ...`）会直接失败。
用这个只做绝对导入的薄壳最稳。
"""

from __future__ import annotations

import os
import sys

# 打包后这些路径不用管；开发环境直接跑本文件时，把项目根加进 sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    argv = sys.argv[1:]

    # ---- 自检模式：不打界面，离屏把整条链路跑一遍 ----
    # 打包后用它验证「Qt 插件齐不齐、底图在不在、能不能出图」，
    # 免去手工双击试错。
    if "--selftest" in argv:
        return _selftest([a for a in argv if a != "--selftest"])

    dataset = None
    args = [a for a in argv if not a.startswith("-")]
    if args:
        dataset = args[0]

    try:
        from ncsight.gui.app import run
    except ImportError as exc:
        _fail("无法加载图形界面组件：\n%s" % exc)
        return 2
    except Exception as exc:                            # noqa: BLE001
        _fail("启动失败：\n%s: %s" % (type(exc).__name__, exc))
        return 3

    try:
        return run(dataset)
    except Exception as exc:                            # noqa: BLE001
        import traceback
        tb = traceback.format_exc()
        try:
            os.makedirs(os.path.join(os.path.expanduser("~"), ".ncsight"), exist_ok=True)
            log = os.path.join(os.path.expanduser("~"), ".ncsight", "crash.log")
            with open(log, "a", encoding="utf-8") as fh:
                fh.write("\n" + "=" * 70 + "\n" + tb)
        except Exception:                               # noqa: BLE001
            log = "(无法写入日志)"
        _fail("程序异常退出：\n%s: %s\n\n详细堆栈已写入：\n%s\n\n%s"
              % (type(exc).__name__, exc, log, tb[-1200:]))
        return 4


def _selftest(rest) -> int:
    """离屏自检：验证打包后的运行环境是否完整。"""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    out_dir = None
    dataset = None
    for i, a in enumerate(rest):
        if a == "--outdir" and i + 1 < len(rest):
            out_dir = rest[i + 1]
        elif not a.startswith("-") and not a.startswith("--"):
            dataset = a
    out_dir = out_dir or os.path.join(os.path.expanduser("~"), ".ncsight", "selftest")
    os.makedirs(out_dir, exist_ok=True)

    lines = []
    ok = True
    log_path = os.path.join(out_dir, "selftest_trace.log")

    def note(name, status, extra=""):
        nonlocal ok
        if not status:
            ok = False
        msg = "[%s] %-24s %s" % ("OK  " if status else "FAIL", name, extra)
        lines.append(msg)
        print(msg, flush=True)
        # 同时逐行落盘：万一自检卡住被强杀，也能知道停在哪一步
        try:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:                               # noqa: BLE001
            pass

    try:
        open(log_path, "w", encoding="utf-8").close()
    except Exception:                                   # noqa: BLE001
        pass
    print("自检开始（追踪日志：%s）" % log_path, flush=True)

    # 1) 版本与运行环境
    try:
        import ncsight
        from ncsight._runtime import configure_all
        info = configure_all()
        note("ncsight 导入", True, ncsight.version_string())
        note("运行模式", True, "打包(frozen)" if info.get("frozen") else "源码")
        note("程序目录", True, info.get("app_dir", ""))
        note("底图目录", bool(info.get("cartopy_data")),
             info.get("cartopy_data") or "未找到（首次绘图将尝试联网）")
    except Exception as exc:                            # noqa: BLE001
        note("ncsight 导入", False, str(exc))
        return _report(lines, ok, out_dir)

    # 2) 关键依赖
    for mod in ("numpy", "matplotlib", "cartopy", "pyproj", "netCDF4",
                "PySide6.QtWidgets", "scipy", "cmocean", "cmcrameri", "yaml"):
        try:
            m = __import__(mod, fromlist=["__version__"])
            note("依赖 %s" % mod, True, getattr(m, "__version__", ""))
        except Exception as exc:                        # noqa: BLE001
            note("依赖 %s" % mod, False, str(exc))

    # 3) 离线底图真的能读到
    try:
        from cartopy.io import shapereader
        shp = shapereader.natural_earth(resolution="110m",
                                        category="physical", name="coastline")
        note("离线海岸线", os.path.exists(shp), os.path.basename(shp))
    except Exception as exc:                            # noqa: BLE001
        note("离线海岸线", False, str(exc))

    # 4) Qt 平台插件
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        note("Qt 平台插件", True, app.platformName())
    except Exception as exc:                            # noqa: BLE001
        note("Qt 平台插件", False, str(exc))
        return _report(lines, ok, out_dir)

    # 5) 主窗口能建起来
    try:
        from ncsight.gui.main_window import MainWindow
        win = MainWindow()
        note("主窗口构建", True)
    except Exception as exc:                            # noqa: BLE001
        note("主窗口构建", False, str(exc))
        return _report(lines, ok, out_dir)

    # 6) 有真实数据就跑一遍完整链路
    if dataset and os.path.exists(dataset):
        try:
            import time as _t
            from PySide6.QtWidgets import QApplication as QA

            # 6a) 打开数据集：只验证「能打开、变量树填好、主轴选对」，
            #     立刻停掉防抖定时器 —— 否则会触发一次全球 4320x8640 的
            #     完整渲染，在冻结环境里要几分钟，让人误以为卡死。
            t0 = _t.time()
            win.open_dataset(dataset)
            win._render_timer.stop()
            QA.processEvents()
            note("打开数据集", win._source is not None,
                 "%s（%.1f 秒）" % (win._spec.variable, _t.time() - t0))
            note("变量树已填充", len(win.source_panel._items) > 0,
                 "%d 个可制图变量" % len(win.source_panel._items))

            # 6b) 用 core 直接跑一次「小区域 + Robinson 投影」的渲染。
            #     这一步覆盖的是真正容易在打包后出问题的部分：
            #     netCDF4 读取 → packed 解包 → 内嵌调色板 → cartopy 投影 →
            #     海岸线叠加 → matplotlib 画布 → 存盘。
            from ncsight.core import PlotSpec, render as core_render
            var = win._spec.variable
            spec = PlotSpec(variable=var, kind="map", projection="Robinson",
                            bbox=[110.0, 140.0, 5.0, 35.0], preset="single",
                            nbins=15, show_stats=True)
            t1 = _t.time()
            res = core_render(spec, win._source, fig=win.plot_view.prepare())
            win.plot_view.finished(res)
            QA.processEvents()
            note("投影渲染（小区域）", res.data is not None,
                 "%d 个有效点（%.1f 秒）" % (res.data.valid_count, _t.time() - t1))

            png = os.path.join(out_dir, "selftest.png")
            t2 = _t.time()
            win.plot_view.figure.savefig(png, dpi=110)
            note("保存图像", os.path.getsize(png) > 1000,
                 "%s（%.1f 秒）" % (os.path.basename(png), _t.time() - t2))

            # 6c) 导出数据链路
            from ncsight.core import export as ex
            csv = os.path.join(out_dir, "selftest.csv")
            ex.export_grid_csv(res.data, csv)
            note("导出 CSV", os.path.getsize(csv) > 100,
                 "%d 行" % (sum(1 for _ in open(csv, encoding="utf-8-sig")) - 1))
        except Exception as exc:                        # noqa: BLE001
            import traceback
            note("真实数据链路", False, "%s: %s" % (type(exc).__name__, exc))
            lines.append(traceback.format_exc())
    else:
        note("真实数据链路", True, "跳过（未提供数据集）")

    return _report(lines, ok, out_dir)


def _report(lines, ok, out_dir) -> int:
    path = os.path.join(out_dir, "selftest_report.txt")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        print("\n自检报告：%s" % path)
    except Exception:                                   # noqa: BLE001
        pass
    print("\n自检结果：%s" % ("全部通过" if ok else "存在失败项"))
    rc = 0 if ok else 1

    # ★ 必须强制退出 ★
    # 自检过程建过 QApplication 与 matplotlib Figure；正常 return 之后，
    # 进程会被 Qt / 字体管理器留下的非守护线程挂住而不退出 ——
    # 表现就是调用方（build_exe.py）一直等在那里。用 os._exit 直接结束。
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.quit()
    except Exception:                                   # noqa: BLE001
        pass
    os._exit(rc)



def _fail(message: str) -> None:
    """双击运行时没有控制台，用消息框把错误显示出来，而不是静默退出。"""
    sys.stderr.write(message + "\n")
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, "NCSight 启动失败", 0x10)
    except Exception:                                   # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(main())
