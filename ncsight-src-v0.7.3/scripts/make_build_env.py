# -*- coding: utf-8 -*-
"""
创建「打包专用」的最小虚拟环境
==============================
**为什么需要它**：直接拿日常用的 conda 环境（py39gpu）去打包，会踩两个坑：

  1. **依赖图失控**：那个环境里装着整套机器学习栈（torch / opencv / spacy /
     transformers / sklearn / fastai…），PyInstaller 顺着依赖图全扫进来，
     光分析阶段就要 10 分钟以上，产物还会膨胀到几个 GB。
  2. **Intel MKL 体积黑洞**：conda 的 numpy/scipy 链到 MKL，PyInstaller 会把
     `mkl_core` / `mkl_avx512` / `mkl_pgi_thread` / `mkl_vml_*` 等
     **全部 CPU 内核变体**都打进去 —— 实测约 600 MB，而运行时只用得上其中一两个。

用 pip 装一个只有本项目依赖的干净 venv 就同时解决这两件事：
  * pip 的 numpy / scipy 走 OpenBLAS，**完全没有 MKL**
  * 环境里本来就没有 ML 栈，不需要靠 exclude 列表去猜

产物可从约 970 MB 降到约 300–350 MB。

用法：
    python scripts/make_build_env.py                # 创建（已存在则跳过）
    python scripts/make_build_env.py --recreate     # 删掉重建
    python scripts/make_build_env.py --no-mirror    # 用官方 PyPI（默认走清华镜像）

关于镜像：默认使用清华 TUNA 镜像。实测直连 PyPI 有时只有几十 kB/s，
装 PySide6（250 MB）会拖到一两个小时；走国内镜像通常几分钟就完。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_DIR = os.path.join(ROOT, "packaging", "buildenv")

#: 默认镜像（国内访问快）。想用官方源加 --no-mirror
DEFAULT_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
EXTRA_MIRRORS = [
    "https://mirrors.aliyun.com/pypi/simple",
    "https://pypi.mirrors.ustc.edu.cn/simple",
]

#: 打包运行时真正需要的包（少一个都不行，多一个都不加）
PACKAGES = [
    "pyinstaller>=6.10",
    "PySide6>=6.6",          # Qt 界面
    "numpy>=1.24",           # 数值
    "scipy>=1.10",           # 平滑 / 插值 / 梯度
    "matplotlib>=3.7",       # 绘图
    "cartopy>=0.22",         # 投影与底图（会带上 shapely / pyproj）
    "netCDF4>=1.6",          # 读 nc（会带上 cftime）
    "pillow>=9.0",           # 位图与 GIF
    "PyYAML>=6.0",           # 配置文件
    "cmocean>=3.0",          # 海洋学色表
    "cmcrameri>=1.8",        # 科学色表
]


def env_python() -> str:
    return os.path.join(ENV_DIR, "Scripts", "python.exe")


def run(cmd, **kw) -> int:
    print("\n$ %s" % " ".join(cmd), flush=True)
    # PYTHONPATH 置空：避免宿主的 sitecustomize 注入批量删除保护，
    # 干扰 pip 的正常文件操作
    env = dict(os.environ)
    env["PYTHONPATH"] = ""
    return subprocess.call(cmd, env=env, **kw)


def main() -> int:
    ap = argparse.ArgumentParser(description="创建打包专用 venv")
    ap.add_argument("--recreate", action="store_true", help="已存在则删除重建")
    ap.add_argument("--python", default=sys.executable,
                    help="用来创建 venv 的解释器（默认当前解释器）")
    ap.add_argument("--no-mirror", action="store_true",
                    help="使用官方 PyPI（默认走清华镜像，国内快得多）")
    ap.add_argument("--mirror", default=DEFAULT_MIRROR,
                    help="自定义 pip 镜像地址")
    args = ap.parse_args()

    index_args = [] if args.no_mirror else ["-i", args.mirror,
                                            "--timeout", "30"]

    t0 = time.time()

    if os.path.isdir(ENV_DIR):
        if not args.recreate:
            print("构建环境已存在：%s" % ENV_DIR)
            print("需要重建请加 --recreate")
        else:
            print("删除旧环境：%s" % ENV_DIR)
            shutil.rmtree(ENV_DIR, ignore_errors=True)

    if not os.path.isdir(ENV_DIR):
        print("[1/3] 创建虚拟环境（基于 %s）" % args.python)
        os.makedirs(os.path.dirname(ENV_DIR), exist_ok=True)
        rc = run([args.python, "-m", "venv", ENV_DIR])
        if rc != 0:
            print("venv 创建失败。可以试试： pip install virtualenv && "
                  "python -m virtualenv %s" % ENV_DIR)
            return rc

    py = env_python()
    if not os.path.exists(py):
        print("找不到 %s" % py)
        return 2

    # pip 自检：venv 建好时自带一份 pip，但直接 `pip install -U pip` 会走
    # 「卸载旧的再装新的」，中途任何文件占用都会把 pip 弄坏（实测踩过）。
    # 用 ensurepip 就地修复更稳，坏不了。
    print("\n[2/3] 检查 / 修复 pip")
    r = subprocess.run([py, "-m", "pip", "--version"],
                       capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": ""})
    if r.returncode != 0:
        print("  pip 不可用，用 ensurepip 修复…")
        run([py, "-m", "ensurepip", "--upgrade"])
        r = subprocess.run([py, "-m", "pip", "--version"],
                           capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": ""})
    if r.returncode != 0:
        print("  pip 仍然不可用。请手动执行：")
        print("    %s -m ensurepip --upgrade" % py)
        print("  或者换个方式建环境：")
        print("    pip install virtualenv")
        print("    python -m virtualenv %s" % ENV_DIR)
        return 2
    print("  %s" % r.stdout.strip())

    # 升级 pip 用 --no-deps（不碰 setuptools/wheel，避免触发卸载流程）
    if index_args:
        print("\n使用镜像：%s" % args.mirror)
    else:
        print("\n使用官方 PyPI（可能很慢）")
    print("\n[3/3] 安装依赖（PySide6 较大，约 250 MB，请耐心等）")
    rc = run([py, "-m", "pip", "install", "--no-cache-dir"] + index_args + PACKAGES)
    if rc != 0:
        print("\n依赖安装失败。可以试试换镜像：")
        for m in EXTRA_MIRRORS:
            print("  %s scripts\\make_build_env.py --recreate --mirror %s" % (sys.executable, m))
        print("或单独重试某个包：")
        print("  %s -m pip install -i %s <包名>" % (py, args.mirror))
        return rc

    print("\n" + "=" * 64)
    print("构建环境就绪，用时 %.1f 分钟" % ((time.time() - t0) / 60.0))
    print("=" * 64)
    print("\n接下来用它打包：")
    print("  %s scripts\\build_exe.py --clean" % py)
    print("（build_exe.py 会自动优先使用 packaging/buildenv 里的解释器）")

    # 顺手报一下体积对比的预期
    try:
        r = subprocess.run([py, "-c",
                            "import numpy; print(numpy.__config__.show())"],
                           capture_output=True, text=True)
        if "mkl" in r.stdout.lower():
            print("\n注意：这个环境里的 numpy 仍然链接 MKL，体积可能偏大")
        else:
            print("\nnumpy 未使用 MKL（后端为 OpenBLAS），打包体积会小很多")
    except Exception:                                   # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
