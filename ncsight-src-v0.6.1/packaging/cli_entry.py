# -*- coding: utf-8 -*-
"""
PyInstaller 打包入口 —— 命令行
=============================
给「批量出图」这类脚本化场景用。它是个控制台程序（有自己的黑窗口），
可以这样用：

    ncsight-cli.exe batch  D:\\ncdata  -o  D:\\figures  --format pdf
    ncsight-cli.exe plot   data.nc  -v sst  --projection Robinson  -o sst.png
    ncsight-cli.exe version -v
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    from ncsight.cli import main as cli_main
    return cli_main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
