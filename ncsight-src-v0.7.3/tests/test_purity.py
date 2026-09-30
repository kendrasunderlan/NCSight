# -*- coding: utf-8 -*-
"""
核心纯净性测试
==============
本项目的硬约束：**`ncsight/core/` 与 `ncsight/style.py` 不得依赖 GUI 库**。

为什么这条重要：命令行版要能在没有图形环境的机器上跑 —— 服务器、超算、
CI 容器、SSH 会话。一旦 core 里 import 了 Qt，这些环境全部用不了。

这里验证的是**行为**而不是文本：直接导入 core 与 cli，然后检查
`sys.modules` 里有没有混进 GUI 相关模块。
这比 grep「有没有 import PySide6」可靠得多 —— 后者会漏掉间接依赖，
也会误报那些被 try/except 包起来的惰性导入（那类导入在无头环境下
会优雅降级，是允许的）。
"""

import subprocess
import sys

#: 一旦被 core 拉进来就说明约束被破坏了
GUI_MODULES = ("PySide6", "PyQt5", "PyQt6", "PySide2", "tkinter")


def _run_check(code: str) -> str:
    """在全新的子进程里执行，避免受当前进程已导入模块的干扰。"""
    r = subprocess.run([sys.executable, "-c", code],
                       capture_output=True, text=True, timeout=120)
    return (r.stdout + r.stderr)


def test_core导入不带进GUI():
    """导入 ncsight.core 之后，sys.modules 里不该有 GUI 模块。"""
    code = (
        "import sys\n"
        "before = set(sys.modules)\n"
        "import ncsight.core, ncsight.cli, ncsight.style\n"
        "leak = sorted({m.split('.')[0] for m in sys.modules\n"
        "               if m not in before})\n"
        "bad = [m for m in leak if m in %r]\n"
        "print('LEAK:' + ','.join(bad) if bad else 'OK')\n" % (GUI_MODULES,)
    )
    out = _run_check(code)
    assert "OK" in out, (
        "ncsight.core / ncsight.cli 把 GUI 库拉进来了，"
        "命令行将无法在无图形环境运行。\n输出：%s" % out)


def test_可以导入全部图型模块():
    """各图型模块单独导入也不应带进 GUI。"""
    mods = ["ncsight.core.plot.map_plot",
            "ncsight.core.plot.line_plot",
            "ncsight.core.plot.hovmoller",
            "ncsight.core.plot.section",
            "ncsight.core.plot.series_plot",
            "ncsight.core.series",
            "ncsight.core.indicators",
            "ncsight.core.colorbar"]
    code = (
        "import sys, importlib\n"
        "before = set(sys.modules)\n"
        "for m in %r:\n"
        "    importlib.import_module(m)\n"
        "leak = sorted({m.split('.')[0] for m in sys.modules if m not in before})\n"
        "bad = [m for m in leak if m in %r]\n"
        "print('LEAK:' + ','.join(bad) if bad else 'OK')\n" % (mods, GUI_MODULES)
    )
    out = _run_check(code)
    assert "OK" in out, "图型模块带进了 GUI 依赖：%s" % out


def test_剪切板函数在无GUI时优雅降级():
    """copy_to_clipboard 里有惰性 import，无 Qt 时必须返回 False 而不是抛异常。"""
    code = (
        "import matplotlib; matplotlib.use('Agg')\n"
        "from ncsight.core.export import copy_to_clipboard\n"
        "from ncsight import style\n"
        "fig = style.new_figure()\n"
        "r = copy_to_clipboard(fig)\n"
        "print('RESULT:%r' % (r,))\n"
    )
    out = _run_check(code)
    assert "RESULT:False" in out or "RESULT:True" in out, out
    assert "Traceback" not in out, "无 GUI 时不应抛异常：%s" % out
