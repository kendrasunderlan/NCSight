# -*- coding: utf-8 -*-
"""
出图预设库
==========
把「常用的一整套绘图参数」存成 YAML，下次一键套用 —— 对应 Panoply 的
Saved Settings，但这些预设是纯文本、进版本管理、可以直接用命令行复用：

    ncsight plot data.nc --spec <预设名>

用法：
    from ncsight.presets import list_presets, load_preset
    for name, desc, path in list_presets():
        print(name, desc)
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from ..core.plot.base import PlotSpec

PRESET_DIR = os.path.dirname(os.path.abspath(__file__))

#: 预设名 → 一句话说明（界面下拉框里显示）
PRESET_DESCRIPTIONS = {
    "海温_全球_论文单栏": "全球海温 · 单栏 8.3cm · 50m 海岸线 · 300dpi",
    "海温_Robinson_演示": "全球海温 · Robinson 投影 · 陆海填充 · 演示用",
    "距平图_居中于零": "距平/异常 · 色标居中于零 · 发散色表 balance",
    "区域_西北太平洋": "西北太平洋区域 · 等距圆柱 · 单栏",
    "区域_抹掉陆地": "近海研究区 · 墨卡托 · 抹掉陆地只留海洋",
    "论文_双栏_带等值线": "双栏 17.1cm · 叠加 10 层等值线 · 300dpi",
}


def list_presets() -> List[Tuple[str, str, str]]:
    """返回 [(名称, 说明, 文件路径), ...]，按名称排序。"""
    out: List[Tuple[str, str, str]] = []
    if not os.path.isdir(PRESET_DIR):
        return out
    for fn in sorted(os.listdir(PRESET_DIR)):
        if not fn.lower().endswith((".yaml", ".yml")):
            continue
        name = os.path.splitext(fn)[0]
        out.append((name, PRESET_DESCRIPTIONS.get(name, ""),
                    os.path.join(PRESET_DIR, fn)))
    return out


def preset_names() -> List[str]:
    return [n for n, _d, _p in list_presets()]


def preset_path(name: str) -> Optional[str]:
    """支持「预设名」和「预设名.yaml」两种写法。"""
    for n, _d, p in list_presets():
        if name in (n, os.path.basename(p)):
            return p
    return None


def load_preset(name: str) -> PlotSpec:
    p = preset_path(name)
    if p is None:
        raise KeyError("没有这个预设：%s（可用：%s）"
                       % (name, ", ".join(preset_names())))
    return PlotSpec.load(p)


def save_preset(name: str, spec: PlotSpec) -> str:
    """把当前绘图参数存成新预设（供 GUI 的「另存为预设」用）。"""
    import re
    safe = re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "未命名预设"
    path = os.path.join(PRESET_DIR, safe + ".yaml")
    return spec.save(path)
