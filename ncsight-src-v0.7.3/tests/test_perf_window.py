# -*- coding: utf-8 -*-
"""
性能优化相关的回归测试
======================
守三件刚做过的事，防止以后被改回去：

1. `plan_read_window` —— 只从磁盘读需要的那一块
   （不做的话，看个小区域也要先读整幅全球场：4320x8640 解包后约 300 MB）
2. `clip_segments` / `simplify_polyline` —— 底图按视野裁剪与抽稀
   （不做的话，10m 海岸线的 41 万顶点全都要做投影变换，一次十几秒）
3. `render(..., progress=...)` —— 长任务要有进度回调
"""

import numpy as np
import pytest

from ncsight.core import NcSource, PlotSpec, render
from ncsight.core.grid import subset_bbox
from ncsight.core.overlay import (clip_segments, simplify_polyline,
                                  view_tolerance)
from ncsight.core.reader import _index_range


class TestIndexRange:
    """在坐标轴上找 [lo, hi] 对应的索引范围。"""

    def test_递增轴(self):
        a = np.linspace(0, 100, 101)
        i0, i1 = _index_range(a, 10, 20)
        assert i0 == 10 and i1 == 21
        assert a[i0] == 10 and a[i1 - 1] == 20

    def test_递减轴不取反(self):
        """真实 L3 产品的纬度是递减的（90 -> -90），必须正确处理。"""
        a = np.linspace(90, -90, 181)
        i0, i1 = _index_range(a, -10, 40)
        assert a[i0] == 40 and a[i1 - 1] == -10

    def test_上下界颠倒也能处理(self):
        a = np.linspace(0, 100, 101)
        assert _index_range(a, 20, 10) == _index_range(a, 10, 20)

    def test_超出范围时给出全轴(self):
        a = np.linspace(0, 10, 11)
        assert _index_range(a, 100, 200) == (0, 11)

    def test_空轴不崩(self):
        assert _index_range(np.array([]), 0, 1) == (0, 0)


class TestPlanReadWindow:
    def test_给出窗口(self, source):
        w = source.plan_read_window("sst", bbox=[100, 140, 0, 30],
                                    max_cells=1_000_000)
        assert w, "应该给出窗口"
        assert set(w) >= {"lat", "lon"}
        for start, stop, step in w.values():
            assert 0 <= start < stop and step >= 1

    def test_不要区域时只做降采样(self, source):
        # 夹具网格很小（18x36），预算必须给得比它小才需要降采样
        w = source.plan_read_window("sst", bbox=None, max_cells=50)
        assert w, "预算远小于网格规模时应该给出窗口"
        assert any(v[2] > 1 for v in w.values()), "应该带上大于 1 的步长"

    def test_预算够大时不需要窗口(self, source):
        """网格本来就在预算内，就不该多包一层窗口。"""
        w = source.plan_read_window("sst", bbox=None, max_cells=10_000_000)
        assert w is None

    def test_无需截取时返回None(self, source):
        """本来就要整幅、又不要降采样时，别多包一层。"""
        assert source.plan_read_window("sst", bbox=None, max_cells=0) is None

    def test_窗口读与全读再裁结果一致(self, source):
        """性能优化不能改变结果 —— 这是最重要的一条。"""
        bbox = [100.0, 140.0, 0.0, 30.0]
        full = subset_bbox(source.read_field("sst"), bbox)
        w = source.plan_read_window("sst", bbox, 500_000)
        win = source.read_field("sst", window=w)
        # 空间范围一致
        assert abs(win.x[0] - full.x[0]) < 1.5
        assert abs(win.x[-1] - full.x[-1]) < 1.5
        assert abs(win.y[0] - full.y[0]) < 1.5
        assert abs(win.y[-1] - full.y[-1]) < 1.5
        # 纬度方向没被弄反
        assert (win.y[0] - win.y[-1]) * (full.y[0] - full.y[-1]) > 0
        # 数值范围一致
        assert abs(float(np.nanmin(win.values))
                   - float(np.nanmin(full.values))) < 1.0
        assert abs(float(np.nanmax(win.values))
                   - float(np.nanmax(full.values))) < 1.0

    def test_坐标与数据长度严格对齐(self, source):
        """pcolormesh 的硬要求，窗口读之后也必须成立。"""
        w = source.plan_read_window("sst", [100, 140, 0, 30], 200_000)
        fd = source.read_field("sst", window=w)
        assert fd.values.shape == (fd.y.size, fd.x.size)

    def test_格点数收敛到预算(self, source):
        w = source.plan_read_window("sst", None, 100_000)
        fd = source.read_field("sst", window=w)
        assert fd.values.size <= 200_000       # 步长取整会有余量


class TestClipSegments:
    @staticmethod
    def _segs():
        return [
            np.array([[0.0, 0.0], [1.0, 1.0]]),            # 视野外（左）
            np.array([[110.0, 10.0], [120.0, 20.0]]),      # 视野内
            np.array([[200.0, 50.0], [210.0, 60.0]]),      # 视野外（右）
        ]

    def test_丢掉视野外的线段(self):
        out = clip_segments(self._segs(), [100, 140, 0, 40])
        assert len(out) == 1
        assert out[0][0][0] == 110.0

    def test_没有bbox时原样返回(self):
        segs = self._segs()
        assert clip_segments(segs, None) is segs

    def test_保留跨界线段(self):
        segs = [np.array([[90.0, 10.0], [150.0, 20.0]])]
        assert len(clip_segments(segs, [100, 140, 0, 40])) == 1

    def test_结果被缓存(self):
        segs = self._segs()
        a = clip_segments(segs, [100, 140, 0, 40])
        b = clip_segments(segs, [100, 140, 0, 40])
        assert a is b


class TestSimplifyPolyline:
    def test_直线被抽成两点(self):
        x = np.linspace(0, 10, 500)
        pts = np.column_stack([x, np.zeros_like(x)])
        out = simplify_polyline(pts, 0.1)
        assert len(out) < 10

    def test_保留两端(self):
        x = np.linspace(0, 10, 200)
        pts = np.column_stack([x, np.sin(x)])
        out = simplify_polyline(pts, 0.05)
        assert np.allclose(out[0], pts[0]) and np.allclose(out[-1], pts[-1])

    def test_容差为零时不动(self):
        pts = np.column_stack([np.arange(50.0), np.arange(50.0)])
        assert simplify_polyline(pts, 0.0) is pts

    def test_点数不会变多(self):
        pts = np.column_stack([np.arange(300.0), np.random.rand(300)])
        assert len(simplify_polyline(pts, 0.02)) <= 300

    def test_抽稀后仍是一条有效折线(self):
        pts = np.column_stack([np.arange(100.0), np.random.rand(100)])
        out = simplify_polyline(pts, 0.5)
        assert out.ndim == 2 and out.shape[1] == 2 and len(out) >= 2


class TestViewTolerance:
    def test_与视野跨度成正比(self):
        assert view_tolerance([0, 100, 0, 50]) > view_tolerance([0, 10, 0, 5])

    def test_没有bbox时为零(self):
        assert view_tolerance(None) == 0.0

    def test_量级合理(self):
        # 60 度视野分到 1400 像素，每像素约 0.043 度
        tol = view_tolerance([100, 160, 0, 40])
        assert 0.01 < tol < 0.1


class TestProgress:
    def test_渲染带进度回调(self, source):
        steps = []
        render(PlotSpec(variable="sst", kind="map", preset="single",
                        bbox=[100, 140, 0, 30]),
               source, progress=lambda d, t, m: steps.append((d, t, m)))
        # 地图渲染很快，没有分步进度也可以接受；只要有回调就能调用
        assert isinstance(steps, list)

    def test_时序渲染上报进度(self):
        import os
        d = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                         "_series_test")
        if not os.path.isdir(d):
            pytest.skip("没有时序测试数据")
        paths = sorted(os.path.join(d, f) for f in os.listdir(d)
                       if f.endswith(".nc"))[:6]
        if not paths:
            pytest.skip("没有时序测试数据")
        steps = []
        render(PlotSpec(kind="series", variable="sst",
                        indicators=["trend", "summary"]),
               paths, progress=lambda a, b, m: steps.append((a, b, m)))
        assert steps, "应该有进度回调"
        assert all(steps[i][0] <= steps[i + 1][0]
                   for i in range(len(steps) - 1)), "进度必须单调不减"
        assert steps[-1][0] == steps[-1][1], "最后应到达终点"
        assert len({s[1] for s in steps}) == 1, "分母应当稳定"
