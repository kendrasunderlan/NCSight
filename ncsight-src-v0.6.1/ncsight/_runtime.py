# -*- coding: utf-8 -*-
"""
打包（frozen）环境下的资源与路径配置
==================================
用 PyInstaller 打包成 exe 之后，程序运行在「解包目录」里，且安装位置
可能在 Program Files 这种**只读**目录。有几个库默认会往用户目录或程序
目录写缓存，不打理就会出问题：

  1. **cartopy** —— 默认把 Natural Earth 底图下载到 `~/.local/share/cartopy`。
     离线环境下会一直尝试联网并失败，表现为「底图画不出来」。
     解决：优先使用随包分发的底图目录。
  2. **matplotlib** —— 会往 `~/.matplotlib` 写字体缓存。如果那个目录不可写
     （某些受限账户），第一次绘图会崩。解决：显式指定一个可写目录。
  3. **NCSight 自身的偏好设置** —— `~/.ncsight`，要保证可写。

本模块在包被 import 时自动执行（见 `ncsight/__init__.py`），
在开发环境下这些设置是无害的（只是确认一下路径存在）。
"""

from __future__ import annotations

import os
import sys
import tempfile
from typing import Optional


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打出来的包里。"""
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Optional[str]:
    """
    打包后的资源根目录。

    PyInstaller 6.x 的 onedir 模式把资源放在 `_internal/` 下，
    路径由 `sys._MEIPASS` 给出；onefile 模式则指向临时解包目录。
    """
    if not is_frozen():
        return None
    return getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)


def app_dir() -> str:
    """程序所在目录（exe 所在的目录，不是 _internal）。"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_probe")
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except Exception:                                   # noqa: BLE001
        return False


def user_data_dir() -> str:
    """
    用户数据目录（偏好设置、会话、日志）。优先 `~/.ncsight`，
    不可写时退到临时目录，保证程序不会因为写不了配置而启动失败。
    """
    primary = os.path.join(os.path.expanduser("~"), ".ncsight")
    if _writable(primary):
        return primary
    fallback = os.path.join(tempfile.gettempdir(), "ncsight")
    os.makedirs(fallback, exist_ok=True)
    return fallback


# --------------------------------------------------------------------------
# cartopy：让它优先用随包分发的底图
# --------------------------------------------------------------------------
def configure_cartopy(verbose: bool = False) -> Optional[str]:
    """
    配置 cartopy 的底图搜索路径。

    返回实际生效的底图目录（找不到就返回 None，此时 cartopy 会按默认行为
    尝试联网下载）。
    """
    candidates = []

    bd = bundle_dir()
    if bd:
        candidates.append(os.path.join(bd, "cartopy_data"))

    # 开发环境：项目内自带的资源目录（如果有的话）
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "resources", "cartopy_data"))

    chosen = None
    for c in candidates:
        if os.path.isdir(os.path.join(c, "shapefiles")):
            chosen = c
            break

    if chosen is None:
        # 退回到用户缓存目录（开发环境常见，或用户自己下载过）
        user = os.path.join(os.path.expanduser("~"), ".local", "share", "cartopy")
        if os.path.isdir(os.path.join(user, "shapefiles")):
            chosen = user

    if chosen is None:
        if verbose:
            print("[ncsight] cartopy 未找到离线底图，首次绘图可能需要联网下载")
        return None

    try:
        import cartopy
        cartopy.config["data_dir"] = chosen
        # pre_existing_data_dir 优先级最高，且不会被 cartopy 的下载逻辑覆盖
        cartopy.config["pre_existing_data_dir"] = chosen
        if verbose:
            print("[ncsight] cartopy 底图目录：%s" % chosen)
    except Exception as exc:                            # noqa: BLE001
        if verbose:
            print("[ncsight] cartopy 配置失败：%s" % exc)
        return None
    return chosen


# --------------------------------------------------------------------------
# matplotlib：保证有可写的缓存目录
# --------------------------------------------------------------------------
def configure_matplotlib(verbose: bool = False) -> Optional[str]:
    bd = bundle_dir()
    # 先用用户目录；不可写就退到临时目录
    primary = os.path.join(user_data_dir(), "mplconfig")
    if _writable(primary):
        target = primary
    else:
        target = os.path.join(tempfile.gettempdir(), "ncsight_mpl")
        os.makedirs(target, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", target)
    if verbose:
        print("[ncsight] matplotlib 缓存目录：%s" % os.environ["MPLCONFIGDIR"])
    return target


# --------------------------------------------------------------------------
def configure_all(verbose: bool = False) -> dict:
    """一次性配好所有运行时路径。返回一个信息字典，供「关于」对话框显示。"""
    info = {
        "frozen": is_frozen(),
        "app_dir": app_dir(),
        "bundle_dir": bundle_dir() or "(开发环境)",
        "user_data_dir": user_data_dir(),
    }
    info["matplotlib_cache"] = configure_matplotlib(verbose)
    info["cartopy_data"] = configure_cartopy(verbose)

    os.environ.setdefault("NCSIGHT_USER_DIR", info["user_data_dir"])
    return info


_APPLIED = False


def apply_once(verbose: bool = False) -> dict:
    """幂等执行（在包 import 时调用一次就够了）。"""
    global _APPLIED
    if not _APPLIED:
        _APPLIED = True
        return configure_all(verbose)
    return {}
