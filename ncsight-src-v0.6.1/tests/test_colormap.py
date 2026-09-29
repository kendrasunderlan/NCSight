# -*- coding: utf-8 -*-
"""色表子系统：内嵌调色板去交错、cpt 解析、内置目录。"""

import os

import numpy as np
import pytest

from ncsight.core.colormap import (CMAP_CATALOG, binned, list_catalog,
                                   make_norm, obpg_palette, read_act,
                                   read_cpt, read_rgb_table, resolve_colormap)


def _smoothness(colors: np.ndarray) -> float:
    """相邻颜色差异总和：越小越平滑。"""
    return float(np.abs(np.diff(colors.astype(float), axis=0)).sum())


class TestObpgPalette:
    def test_去交错显著提升平滑度(self, source):
        """
        核心回归测试。
        OBPG 的 palette 变量声明为 (3,256) 看着像标准 RGB×256，
        但直接按列取色得到的是乱序颜色。去交错后相邻色差应大幅下降。
        """
        raw = np.asarray(source.ds.variables["palette"][:])
        assert raw.shape == (3, 256)

        naive = raw.T.astype("float32") / 255.0
        cmap = obpg_palette(raw)
        assert cmap is not None
        fixed = cmap.colors

        assert fixed.shape == (256, 3)
        assert _smoothness(fixed) < _smoothness(naive) / 5.0, \
            "去交错后平滑度应有数量级提升"

    def test_形状不符时返回None(self):
        assert obpg_palette(np.zeros((4, 256))) is None
        assert obpg_palette(np.zeros(256)) is None

    def test_取值范围合法(self, source):
        cm = obpg_palette(np.asarray(source.ds.variables["palette"][:]))
        assert cm.colors.min() >= 0.0 and cm.colors.max() <= 1.0


class TestCptReader:
    def test_解析RGB型(self, tmp_path):
        p = tmp_path / "test.cpt"
        p.write_text(
            "# comment\n"
            "COLOR_MODEL = RGB\n"
            "-2.0 0 0 60 -1.0 0 0 120\n"
            "-1.0 0 0 120 0.0 255 255 255\n"
            "0.0 255 255 255 1.0 200 0 0\n", encoding="utf-8")
        cm = read_cpt(str(p))
        assert cm is not None
        assert cm.range == (-2.0, 1.0)
        assert cm(0.0)[:3] != (0, 0, 0)          # 归一化后应是蓝色系

    def test_解析HSV型(self, tmp_path):
        p = tmp_path / "hsv.cpt"
        p.write_text(
            "COLOR_MODEL = HSV\n"
            "0 0 100 100 1 120 100 100\n"
            "1 120 100 100 2 240 100 100\n", encoding="utf-8")
        cm = read_cpt(str(p))
        assert cm is not None

    def test_空文件返回None(self, tmp_path):
        p = tmp_path / "empty.cpt"
        p.write_text("# nothing\n", encoding="utf-8")
        assert read_cpt(str(p)) is None

    def test_文件不存在返回None(self):
        assert read_cpt("no/such/file.cpt") is None


class TestActAndRgb:
    def test_act读取(self, tmp_path):
        p = tmp_path / "t.act"
        data = bytes([0, 0, 0] * 256)
        p.write_bytes(data)
        cm = read_act(str(p))
        assert cm is not None and cm.colors.shape == (256, 3)

    def test_act长度不足返回None(self, tmp_path):
        p = tmp_path / "short.act"
        p.write_bytes(b"\x00" * 100)
        assert read_act(str(p)) is None

    def test_rgb读取0到255(self, tmp_path):
        p = tmp_path / "t.rgb"
        p.write_text("0 0 0\n255 0 0\n0 255 0\n0 0 255\n", encoding="utf-8")
        cm = read_rgb_table(str(p))
        assert cm is not None and cm.colors.shape == (4, 3)
        assert cm.colors[1][0] == pytest.approx(1.0)

    def test_rgb读取0到1(self, tmp_path):
        p = tmp_path / "t2.rgb"
        p.write_text("0.0 0.0 0.0\n1.0 0.0 0.0\n", encoding="utf-8")
        cm = read_rgb_table(str(p))
        assert cm.colors[1][0] == pytest.approx(1.0)

    def test_rgb支持十六进制(self, tmp_path):
        p = tmp_path / "t3.rgb"
        p.write_text("#000000\n#FF0000\n", encoding="utf-8")
        cm = read_rgb_table(str(p))
        assert cm is not None and cm.colors[1][0] == pytest.approx(1.0)


class TestResolve:
    def test_自动优先用内嵌调色板(self, source):
        pal = np.asarray(source.ds.variables["palette"][:])
        cm = resolve_colormap("auto", palette_array=pal)
        assert cm.name == "OBPG_palette"

    def test_指名内置色表(self):
        cm = resolve_colormap("thermal")
        assert cm is not None
        assert cm.N >= 2

    def test_未知名字有兜底不报错(self):
        cm = resolve_colormap("这个色表不存在")
        assert cm is not None

    def test_反转(self):
        a = resolve_colormap("viridis")
        b = resolve_colormap("viridis", reverse=True)
        assert not np.allclose(a(0.25)[:3], b(0.25)[:3])

    def test_合并色表文件路径(self, tmp_path):
        p = tmp_path / "x.rgb"
        p.write_text("\n".join("%d %d %d" % (i, 255 - i, 128) for i in range(16)),
                     encoding="utf-8")
        cm = resolve_colormap(str(p))
        assert cm is not None


class TestCatalog:
    def test_目录非空且分组(self):
        cat = list_catalog()
        assert len(cat) >= 3
        for group, items in cat.items():
            assert items, "分组 %s 不应为空" % group
            for name, desc in items:
                assert isinstance(name, str) and isinstance(desc, str)
                assert name and desc

    def test_海洋学组包含thermal(self):
        names = [n for n, _ in CMAP_CATALOG["海洋学专用 (cmocean)"]]
        assert "thermal" in names and "haline" in names


class TestNorm:
    def test_离散分bin(self):
        """
        注意：matplotlib 的 BoundaryNorm.N == len(boundaries)，
        而色阶数 = len(boundaries) - 1，两者别搞混。
        """
        from matplotlib.colors import BoundaryNorm
        n = make_norm(0, 10, nbins=5, discrete=True)
        assert isinstance(n, BoundaryNorm)
        assert len(n.boundaries) == 6, "5 个色阶需要 6 条边界"

    def test_居中于零(self):
        from matplotlib.colors import TwoSlopeNorm
        n = make_norm(-3, 7, center_zero=True)
        assert isinstance(n, TwoSlopeNorm) and n.vcenter == 0

    def test_对数(self):
        from matplotlib.colors import LogNorm
        n = make_norm(0.01, 10, log=True)
        assert isinstance(n, LogNorm)

    def test_分bin取色数量正确(self):
        cm = binned(resolve_colormap("viridis"), 13)
        assert cm.colors.shape == (13, 3)          # 只保留 RGB 三通道
        assert cm.N == 13
