# -*- coding: utf-8 -*-
"""
图形界面入口
============
只负责「起一个 QApplication、设好主题、开主窗口」。
所有业务逻辑都在 core 层，GUI 只做展示与参数收集。

无界面环境下（服务器、CI）不要 import 本包 —— core + cli 已经够用了。
"""

from __future__ import annotations

import os
import sys
from typing import Optional

os.environ.setdefault("QT_API", "pyside6")


def _runtime_versions() -> dict:
    out = {"Python": sys.version.split()[0]}
    for m in ("numpy", "matplotlib", "netCDF4", "cartopy", "PySide6"):
        try:
            mod = __import__(m)
            out[m] = str(getattr(mod, "__version__", "?"))
        except Exception:                               # noqa: BLE001
            out[m] = "未安装"
    return out


def create_app(argv=None):
    """创建并配置 QApplication（幂等）。"""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication.instance()
    if app is None:
        app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("NCSight")
    app.setApplicationDisplayName("NCSight")
    app.setOrganizationName("NCSight")

    from ..version import __version__
    app.setApplicationVersion(__version__)

    # ★ 中文字体必须显式设置 ★
    # 只靠 QSS 的 font-family 在部分环境（离屏 / 容器 / 精简系统）会失效，
    # 表现为界面所有中文变成方框。这里从系统字体库里挑一个真实存在的中文字体，
    # 既设到 QApplication 级别，也注入 QSS，双保险。
    from PySide6.QtGui import QFont
    from .theme import resolve_ui_font, build_stylesheet
    fam = resolve_ui_font()
    font = QFont(fam, 9)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(build_stylesheet(fam))

    from . import icons
    app.setWindowIcon(icons.app_icon())
    return app


def run(dataset: Optional[str] = None, argv=None) -> int:
    """启动图形界面。"""
    try:
        from PySide6.QtWidgets import QApplication  # noqa: F401
    except ImportError as exc:
        print("启动失败：未安装 PySide6。请运行  pip install PySide6", file=sys.stderr)
        print("（也可以完全不装 Qt，直接用命令行：ncsight plot ...）", file=sys.stderr)
        return 2

    app = create_app(argv)
    from .main_window import MainWindow
    win = MainWindow(dataset=dataset)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else None))
