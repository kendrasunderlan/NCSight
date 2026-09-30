# -*- coding: utf-8 -*-
"""渲染冒烟测试：每种图型都能跑通，且产出非空图形。"""

import matplotlib
matplotlib.use("Agg")

import numpy as np
import pytest

from ncsight.core import PlotSpec, render


def _render_ok(spec, source):
    res = render(spec, source)
    assert res.fig is not None
    assert res.ax is not None
    # 必须真的画了东西
    assert res.ax.collections or res.ax.lines or res.ax.images
    import matplotlib.pyplot as plt
    plt.close(res.fig)
    return res


class TestMapPlots:
    def test_等距圆柱(self, source):
        r = _render_ok(PlotSpec(variable="sst", kind="map",
                                projection="PlateCarree", preset="single"), source)
        assert r.data is not None
        assert r.mappable is not None

    def test_其他投影(self, source):
        _render_ok(PlotSpec(variable="sst", kind="map", projection="Robinson",
                            preset="single"), source)

    def test_区域裁切(self, source):
        r = _render_ok(PlotSpec(variable="sst", kind="map",
                                bbox=[0, 90, -30, 30], preset="single"), source)
        assert r.data.values.shape[0] < 18

    def test_等值线叠加(self, source):
        r = _render_ok(PlotSpec(variable="sst", kind="map",
                                show_contours=True, contour_levels=6,
                                preset="single"), source)
        # 等值线会额外产生 collections
        assert len(r.ax.collections) >= 2

    def test_色标居中于零(self, source):
        _render_ok(PlotSpec(variable="sst", kind="map", center_zero=True,
                            cmap="balance", preset="single"), source)

    def test_对数刻度不崩溃(self, source):
        # sst 有负值，log 会被 make_norm 自动忽略，不应抛异常
        _render_ok(PlotSpec(variable="sst", kind="map", log=True,
                            preset="single"), source)

    def test_统计标注(self, source):
        _render_ok(PlotSpec(variable="sst", kind="map", show_stats=True,
                            preset="single"), source)

    def test_自动选变量(self, source):
        r = _render_ok(PlotSpec(variable="", kind="map", preset="single"), source)
        assert r.spec.variable == "sst"

    def test_色标位置(self, source):
        for loc in ("right", "bottom"):
            _render_ok(PlotSpec(variable="sst", kind="map",
                                colorbar_location=loc, preset="single"), source)


class TestOtherKinds:
    def test_一维折线(self, source):
        _render_ok(PlotSpec(variable="lat", kind="line", preset="single"), source)

    def test_纬向平均(self, source):
        _render_ok(PlotSpec(variable="sst", kind="zonal", preset="single"), source)

    def test_矢量场缺配对时报友好错误(self, source):
        with pytest.raises(ValueError) as ei:
            render(PlotSpec(variable="sst", kind="vector", preset="single"), source)
        assert "配对" in str(ei.value) or "vector_variable" in str(ei.value)


class TestMaskIntegration:
    def test_掩膜配置生效(self, source):
        base = _render_ok(PlotSpec(variable="sst", kind="map",
                                   preset="single"), source)
        n0 = base.data.valid_count
        masked = _render_ok(PlotSpec(variable="sst", kind="map",
                                     mask_range=[15, 25], preset="single"), source)
        assert masked.data.valid_count < n0, "阈值掩膜应该减少有效点"

    def test_质量掩膜(self, source):
        r = _render_ok(PlotSpec(variable="sst", kind="map", quality_var="qual_sst",
                                quality_accept="0:1", preset="single"), source)
        assert r.data.valid_count > 0


class TestColorbarMappable:
    """
    色标必须绑定到**数据网格**，不能靠 `ax.collections[-1]` 去猜。

    这里守着一个真实踩过的坑：投影渲染路径原本写的是
    `mappable = ax.collections[-1]`。后来底图叠加改成用 add_collection 画，
    最后一个 collection 就变成了海岸线 —— 色标于是按海岸线的 0~1 归一化，
    表现是「色标范围显示 0.0–1.0」，而且图看着还挺正常，极难发现。
    """

    def test_投影图的色标取自数据范围(self, source):
        spec = PlotSpec(variable="sst", kind="map", projection="Robinson",
                        preset="single")
        res = _render_ok(spec, source)
        assert res.mappable is not None
        norm = getattr(res.mappable, "norm", None)
        assert norm is not None
        # 测试数据的 display_min/max = (-2, 45)，色标应该是这个范围
        assert norm.vmax > 5.0, "色标上限只有 %.3g，说明取到了底图对象" % norm.vmax
        assert norm.vmin < 5.0

    def test_等距圆柱同样取自数据范围(self, source):
        spec = PlotSpec(variable="sst", kind="map", projection="PlateCarree",
                        preset="single")
        res = _render_ok(spec, source)
        assert res.mappable.norm.vmax > 5.0

    def test_叠加底图不会污染色标(self, source):
        """开了海岸线/国界之后色标范围仍应不变。"""
        spec = PlotSpec(variable="sst", kind="map", projection="Robinson",
                        preset="single")
        spec.overlays.coastline = True
        spec.overlays.borders = True
        res = _render_ok(spec, source)
        assert res.mappable.norm.vmax > 5.0
        # 而且底图确实画上去了（collections 不止一个）
        assert len(res.ax.collections) >= 2


class TestTheme:
    def test_中文字体被设置(self):
        from ncsight import style
        style.apply_theme()
        from matplotlib import rcParams
        assert rcParams["font.sans-serif"]
        assert rcParams["axes.unicode_minus"] is False

    def test_图幅预设(self):
        from ncsight.style import FIGURE_PRESETS, figure_preset
        for name in FIGURE_PRESETS:
            w, h = figure_preset(name)
            assert w > 0 and h > 0

    def test_单栏宽度符合期刊要求(self):
        from ncsight.style import cm_figsize
        w_in, _ = cm_figsize(8.3, 6.0)
        assert abs(w_in * 2.54 - 8.3) < 1e-6
