# -*- coding: utf-8 -*-
"""
色表（Color Table）子系统
=========================
对应 Panoply 的 `gov.nasa.giss.graphics.clut`（25 个类）。

Panoply 的色表来自 ColorBrewer / GMT / NCL / cmocean(OCM) / cmcrameri(SCM)
/ UO / JS 等多家。好消息是这些在 Python 生态里大多有现成包，所以本模块的
策略是「能白拿的就白拿」：

    优先级： 文件内嵌调色板  >  用户指定的色表文件  >  内置包  >  兜底

内置包映射：
    OCM_*  -> cmocean            海洋学专用（True Colors of Oceanography）
    SCM_*  -> cmcrameri          Scientific Colour Maps（感知均匀、色盲友好）
    MPL_*  -> matplotlib         含 viridis / magma / turbo
    CB_*   -> matplotlib         ColorBrewer 近似
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from matplotlib.colors import (Colormap, LinearSegmentedColormap, ListedColormap,
                               Normalize, BoundaryNorm)

__all__ = [
    "obpg_palette", "read_cpt", "read_act", "read_rgb_table",
    "resolve_colormap", "list_catalog", "binned", "make_norm",
    "CMAP_CATALOG",
]


# --------------------------------------------------------------------------
# 1) 从 nc 文件内嵌的 palette 变量取色表
# --------------------------------------------------------------------------
def obpg_palette(palette_array: np.ndarray) -> Optional[ListedColormap]:
    """
    读取 OBPG / SeaDAS L3 产品内嵌的 `palette` 变量。

    ★ 关键坑点 ★
    该变量声明为 (rgb=3, eightbitcolor=256)，看起来是标准 RGB×256，
    但**直接按列取色会得到乱序颜色**——相邻颜色的 RGB 差异极大
    （实测相邻色差总和 78265），画出来的图是一堆突兀的色块。

    实测规律：下标每 3 个一组才构成连续色带。按 3 路去交错后，
    相邻色差总和降到 3437（平滑度提升约 23 倍），恢复出正确的海洋色表。

    参数
    ----
    palette_array : 形状为 (3, 256) 的 uint8 数组

    返回
    ----
    ListedColormap（256 色，已去交错）；形状不符时返回 None。
    """
    p = np.asarray(palette_array)
    if p.ndim != 2 or p.shape[0] != 3:
        return None
    rgb = p.T.astype("float32") / 255.0                # (N, 3)
    # ★ 注意：不要去判断 N 能否被 3 整除！
    #   真实 OBPG 产品的 N=256，256 % 3 == 1。加这个判断会导致
    #   真实数据完全不去交错，颜色依然是错的。三段长度不等（86/85/85）
    #   正好拼回 N，直接拼接即可。
    rgb = np.concatenate([rgb[0::3], rgb[1::3], rgb[2::3]])
    rgb = np.clip(rgb, 0.0, 1.0)
    return ListedColormap(rgb, name="OBPG_palette")


# --------------------------------------------------------------------------
# 2) GMT .cpt
# --------------------------------------------------------------------------
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _cpt_color(tokens: Sequence[str], start: int, model: str) -> Optional[Tuple[float, float, float]]:
    """从 cpt 行里解析一个颜色，支持 r/g/b、#RRGGBB、h-s-v。"""
    seg = list(tokens[start:start + 3])
    if len(seg) == 1 and _HEX.match(seg[0]):
        hx = _HEX.match(seg[0]).group(1)
        return tuple(int(hx[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    if len(seg) < 3:
        return None
    try:
        vals = [float(x) for x in seg]
    except ValueError:
        return None
    if model.upper() == "HSV":
        import colorsys
        return colorsys.hsv_to_rgb(vals[0] / 360.0, vals[1] / 100.0, vals[2] / 100.0)
    # r/g/b 通常是 0-255，但也可能是 0-1
    if max(vals) <= 1.0 + 1e-9:
        return tuple(vals)
    return tuple(min(1.0, max(0.0, v / 255.0)) for v in vals)


def read_cpt(path: str) -> Optional[Colormap]:
    """解析 GMT .cpt 色表，支持连续型与分段型（含 COLOR_MODEL HSV）。"""
    if not os.path.exists(path):
        return None
    model = "RGB"
    stops: List[Tuple[float, Tuple[float, float, float]]] = []
    hard_stops: List[Tuple[float, Tuple[float, float, float]]] = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                up = line.upper()
                if up.startswith("COLOR_MODEL"):
                    model = line.split()[1] if len(line.split()) > 1 else "RGB"
                    continue
                if up[0] in ("B", "F", "N") and len(line) < 2:
                    continue
                if up.startswith("N "):
                    continue
                tok = line.replace("\t", " ").split()
                if len(tok) < 8:
                    continue
                try:
                    z0 = float(tok[0])
                    z1 = float(tok[4])
                except ValueError:
                    continue
                c0 = _cpt_color(tok, 1, model)
                c1 = _cpt_color(tok, 5, model)
                if c0 is None or c1 is None:
                    continue
                stops.append((z0, c0))
                stops.append((z1, c1))
    except Exception:                                   # noqa: BLE001
        return None

    if len(stops) < 2:
        return None

    zs = np.array([s[0] for s in stops], dtype="float64")
    cs = np.array([s[1] for s in stops], dtype="float64")
    lo, hi = float(zs.min()), float(zs.max())
    if hi <= lo:
        return None
    pos = (zs - lo) / (hi - lo)
    # 位置必须严格递增，否则 matplotlib 会报错
    keep = np.concatenate([[True], np.diff(pos) > 1e-12])
    pos, cs = pos[keep], cs[keep]
    if pos.size < 2:
        return None
    pos[0], pos[-1] = 0.0, 1.0

    # 用 from_list 构造：它接受 [(位置, (r,g,b)), ...]，跨 matplotlib 版本都稳定。
    # （老写法 data={‘red’: [(x, y0, y1), ...]} 在 matplotlib 3.10 已被拒绝）
    entries = [(float(p), (float(c[0]), float(c[1]), float(c[2])))
               for p, c in zip(pos, cs)]
    name = os.path.splitext(os.path.basename(path))[0]
    cmap = LinearSegmentedColormap.from_list(name, entries, N=256)
    cmap.range = (lo, hi)                               # type: ignore[attr-defined]
    return cmap


# --------------------------------------------------------------------------
# 3) Adobe .act  /  NCL·matplotlib .rgb
# --------------------------------------------------------------------------
def read_act(path: str) -> Optional[ListedColormap]:
    """Adobe Color Table：768 字节 = 256 × RGB。"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    if len(data) < 768:
        return None
    arr = np.frombuffer(data[:768], dtype=np.uint8).reshape(256, 3) / 255.0
    return ListedColormap(arr, name=os.path.splitext(os.path.basename(path))[0])


def read_rgb_table(path: str) -> Optional[ListedColormap]:
    """.rgb 文本色表（NCL / matplotlib 风格）：每行 r g b，取值 0-255 或 0-1。"""
    if not os.path.exists(path):
        return None
    rows: List[Tuple[float, float, float]] = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                # 以 # 开头的既可能是注释，也可能是 #RRGGBB 颜色 —— 后者要认出来
                m_hex = _HEX.match(line)
                if line.startswith(("#", "!", "//")):
                    if m_hex and len(line) in (6, 7):
                        hx = m_hex.group(1)
                        rows.append(tuple(int(hx[i:i + 2], 16) / 255.0
                                          for i in (0, 2, 4)))
                    continue
                tok = re.split(r"[\s,]+", line)
                if len(tok) == 1:
                    m2 = _HEX.match(tok[0])
                    if m2:
                        hx = m2.group(1)
                        rows.append(tuple(int(hx[i:i + 2], 16) / 255.0
                                          for i in (0, 2, 4)))
                    continue
                if len(tok) < 3:
                    continue
                try:
                    vals = [float(x) for x in tok[:3]]
                except ValueError:
                    continue
                if max(vals) > 1.0 + 1e-9:
                    vals = [v / 255.0 for v in vals]
                rows.append(tuple(vals))
    except OSError:
        return None
    if len(rows) < 2:
        return None
    arr = np.clip(np.array(rows, dtype="float32"), 0, 1)
    return ListedColormap(arr, name=os.path.splitext(os.path.basename(path))[0])


def read_table_any(path: str) -> Optional[Colormap]:
    """按扩展名自动选择解析器。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".cpt":
        return read_cpt(path)
    if ext == ".act":
        return read_act(path)
    if ext in (".rgb", ".gct", ".pal", ".txt", ".csv"):
        cm = read_rgb_table(path)
        if cm is not None:
            return cm
        if ext == ".gct":
            return read_act(path)
    return None


# --------------------------------------------------------------------------
# 4) 内置色表目录（借鉴 Panoply 的 146 个内置色表，挑海洋遥感最常用的）
# --------------------------------------------------------------------------
CMAP_CATALOG: Dict[str, List[Tuple[str, str]]] = {
    "海洋学专用 (cmocean)": [
        ("thermal", "海温 · 冷暖连续"),
        ("haline", "盐度"),
        ("algae", "藻类/叶绿素"),
        ("ice", "海冰"),
        ("solar", "太阳辐射"),
        ("speed", "流速强度"),
        ("turbid", "浊度"),
        ("deep", "深海"),
        ("dense", "密度"),
        ("matter", "有机质"),
        ("oxy", "溶解氧"),
        ("phase", "相位"),
        ("amp", "振幅"),
        ("tempo", "季节性"),
        ("curl", "旋度"),
        ("delta", "变化量"),
        ("balance", "正负平衡"),
        ("diff", "差异"),
        ("gray", "灰度"),
    ],
    "科学感知均匀 (cmcrameri)": [
        ("batlow", "通用 · 感知均匀"),
        ("batlowW", "通用（白底友好）"),
        ("vik", "双色发散 · 色盲友好"),
        ("roma", "双色发散"),
        ("broc", "双色发散"),
        ("cork", "双色发散"),
        ("berlin", "双色发散"),
        ("lisbon", "双色发散"),
        ("managua", "双色发散"),
        ("imola", "顺序"),
        ("nuuk", "顺序"),
        ("oslo", "顺序 · 冷"),
        ("lapaz", "顺序"),
        ("lajolla", "顺序"),
        ("acton", "顺序"),
        ("bamako", "顺序"),
        ("bam", "顺序"),
        ("davos", "顺序"),
        ("devon", "顺序"),
        ("grayC", "灰度"),
    ],
    "matplotlib 内置": [
        ("viridis", "感知均匀 · 默认推荐"),
        ("magma", "感知均匀 · 热感"),
        ("inferno", "感知均匀 · 热感"),
        ("plasma", "感知均匀"),
        ("cividis", "色盲友好"),
        ("turbo", "高对比彩虹（慎用）"),
        ("jet", "经典彩虹（不推荐发表）"),
        ("coolwarm", "发散 · 冷暖"),
        ("RdBu_r", "发散 · 红蓝"),
        ("Spectral_r", "发散 · 光谱"),
        ("YlOrRd", "顺序 · 黄橙红"),
        ("Blues", "顺序 · 蓝"),
        ("Greens", "顺序 · 绿"),
        ("Greys", "顺序 · 灰"),
        ("terrain", "地形"),
        ("ocean", "海洋（旧式）"),
    ],
    "ColorBrewer 近似": [
        ("RdYlBu_r", "发散 · 红黄蓝"),
        ("RdYlGn_r", "发散 · 红黄绿"),
        ("BrBG", "发散 · 棕绿"),
        ("PiYG", "发散 · 粉绿"),
        ("PuOr", "发散 · 紫橙"),
        ("YlGnBu", "顺序 · 黄绿蓝"),
        ("GnBu", "顺序 · 绿蓝"),
        ("BuPu", "顺序 · 蓝紫"),
        ("OrRd", "顺序 · 橙红"),
        ("PuBu", "顺序 · 紫蓝"),
    ],
}

# 常用别名：中英文/习惯叫法 → 实际色表名
CMAP_ALIAS: Dict[str, str] = {
    "auto": "__auto__",
    "海温": "thermal",
    "sst": "thermal",
    "盐度": "haline",
    "叶绿素": "algae",
    "chl": "algae",
    "海冰": "ice",
    "流速": "speed",
    "距平": "balance",
    "anomaly": "balance",
    "差异": "diff",
    "default": "viridis",
}


def _builtin_cmap(name: str) -> Optional[Colormap]:
    """按名字取内置色表：先 cmocean，再 cmcrameri，最后 matplotlib。"""
    try:
        import cmocean
        if hasattr(cmocean.cm, name):
            return getattr(cmocean.cm, name)
    except Exception:                                   # noqa: BLE001
        pass
    try:
        import cmcrameri.cm as cmc
        if hasattr(cmc, name):
            return getattr(cmc, name)
    except Exception:                                   # noqa: BLE001
        pass
    try:
        import matplotlib
        if name in matplotlib.colormaps:
            return matplotlib.colormaps[name]
    except Exception:                                   # noqa: BLE001
        pass
    return None


FALLBACK_STOPS = ["#2b0a3d", "#3b1f7a", "#2c5fa8", "#1f9bc9", "#26c6b0",
                  "#a8e05f", "#f7e05b", "#f2a03d", "#e0503a", "#8e1b1b"]


def fallback_colormap(name: str = "ncsight_default") -> Colormap:
    return LinearSegmentedColormap.from_list(name, FALLBACK_STOPS, N=256)


def list_catalog() -> Dict[str, List[Tuple[str, str]]]:
    return {k: list(v) for k, v in CMAP_CATALOG.items()}


def all_names() -> List[str]:
    out: List[str] = []
    for items in CMAP_CATALOG.values():
        out.extend(n for n, _ in items)
    return list(dict.fromkeys(out))


# --------------------------------------------------------------------------
# 5) 统一入口
# --------------------------------------------------------------------------
def resolve_colormap(name: str = "auto",
                     palette_array: Optional[np.ndarray] = None,
                     table_path: Optional[str] = None,
                     reverse: bool = False) -> Colormap:
    """
    解析出一个可用的 Colormap。

    参数
    ----
    name          色表名（可以是 'auto' / 别名 / 内置名 / 文件路径）
    palette_array nc 文件内嵌 palette 数组，优先级最高
    table_path    用户指定的色表文件
    reverse       是否反转
    """
    cmap: Optional[Colormap] = None

    # 1) 文件内嵌调色板
    if name in ("auto", "__auto__", "embedded", "palette") and palette_array is not None:
        cmap = obpg_palette(palette_array)

    # 2) 明确的文件路径
    if cmap is None and name and (os.path.sep in name or name.lower().endswith(
            (".cpt", ".act", ".rgb", ".gct", ".pal"))):
        cmap = read_table_any(name)

    # 3) 别名 / 内置
    if cmap is None:
        key = CMAP_ALIAS.get(name, name)
        if key not in ("__auto__",):
            cmap = _builtin_cmap(key)
        if cmap is None and key not in ("__auto__",):
            cmap = _builtin_cmap(name)

    # 4) auto 但没内嵌调色板 → 用海洋默认
    if cmap is None and name in ("auto", "__auto__", "embedded", "palette"):
        cmap = _builtin_cmap("thermal") or fallback_colormap()

    # 5) 兜底
    if cmap is None:
        cmap = fallback_colormap(str(name))

    if reverse:
        cmap = cmap.reversed()
    return cmap


def binned(cmap: Colormap, nbins: int) -> ListedColormap:
    """从任意色表等距取 nbins 个颜色，得到离散色阶（等价 Panoply 的分 bin 上色）。"""
    nbins = max(2, int(nbins))
    # 取 bin 中心位置，避免首尾被最亮/最暗两色吃掉
    pos = (np.arange(nbins) + 0.5) / nbins
    colors = np.asarray(cmap(pos))[:, :3]          # 丢掉 alpha，保持 RGB 三通道
    return ListedColormap(colors, name="%s_%d" % (getattr(cmap, "name", "cmap"), nbins))


def make_norm(vmin: float, vmax: float, nbins: int = 21,
              log: bool = False, center_zero: bool = False,
              discrete: bool = True) -> Normalize:
    """
    构造归一化器。
      center_zero → TwoSlopeNorm（做距平图的必备）
      log         → LogNorm（叶绿素/辐照度常用）
      discrete    → BoundaryNorm（等值色阶）
    """
    from matplotlib.colors import LogNorm, TwoSlopeNorm

    if vmin is None or vmax is None:
        vmax = 1.0 if vmin is None else vmin + 1.0
        vmin = 0.0 if vmin is None else vmin

    if log and vmin > 0:
        return LogNorm(vmin=vmin, vmax=vmax)

    if center_zero and vmin < 0 < vmax:
        return TwoSlopeNorm(vmin=vmin, vcenter=0.0, vmax=vmax)

    if discrete:
        bounds = np.linspace(vmin, vmax, max(2, int(nbins)) + 1)
        return BoundaryNorm(bounds, max(2, int(nbins)), clip=False)

    return Normalize(vmin=vmin, vmax=vmax)
