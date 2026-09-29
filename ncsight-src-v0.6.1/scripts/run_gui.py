# -*- coding: utf-8 -*-
"""
开发期启动脚本
==============
等价于 `ncsight gui`，但**不需要先 pip install**，
直接在当前目录下就能跑（方便还没装包时先试界面）。

用法：
    D:\\Anaconda_new\\envs\\py39gpu\\python.exe scripts\\run_gui.py
    D:\\Anaconda_new\\envs\\py39gpu\\python.exe scripts\\run_gui.py  D:\\data\\sst.nc
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    dataset = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        from ncsight.gui.app import run
    except ImportError as exc:
        print("无法启动图形界面：%s" % exc, file=sys.stderr)
        print("请先安装 PySide6：pip install PySide6", file=sys.stderr)
        print("\n（也可以完全不装 Qt，直接用命令行：ncsight plot ...）",
              file=sys.stderr)
        return 2
    return run(dataset)


if __name__ == "__main__":
    sys.exit(main())
