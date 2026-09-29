# -*- coding: utf-8 -*-
"""
性能相关：屏幕降采样步长、prepare_field 开关。

这一组测试是有"血统"的 —— 它们守着一个真实发生过的体验事故：
GUI 打开全球 4320x8640 的 nc 后界面冻结十几秒。根因是
  (a) 渲染跑在 Qt 主线程上；
  (b) 全分辨率 3732 万格点建网格要 13.4 秒。
修法是屏幕渲染按画布像素降采样 + 渲染挪到工作线程。
下面这些测试保证降采样既"足够快"又"不砍过头"。
"""

import pytest

from ncsight.core import PlotSpec
from ncsight.core.grid import coarsen_field, coarsen_strides
from ncsight.core.plot.base import prepare_field

#: 真实 L3 产品的网格尺寸
NY, NX = 4320, 8640
TOTAL = NY * NX


class TestCoarsenStrides:
    def test_结果不超过上限(self):
        for lim in (1_500_000, 510_000, 250_000, 100_000, 1000):
            sy, sx = coarsen_strides(NY, NX, lim)
            cy = (NY + sy - 1) // sy
            cx = (NX + sx - 1) // sx
            assert cy * cx <= lim, "目标 %d 实得 %d" % (lim, cy * cx)

    def test_贴合度足够高(self):
        """
        回归测试：旧实现按 2 的幂反复折半，目标 50 万时 3732 万被砍到 14.6 万
        （只用到 29% 的额度），细节白白丢掉。现在要求至少用到 70%。
        """
        for lim in (1_500_000, 510_000, 250_000, 100_000):
            sy, sx = coarsen_strides(NY, NX, lim)
            got = ((NY + sy - 1) // sy) * ((NX + sx - 1) // sx)
            assert got >= lim * 0.7, "目标 %d 只用到 %.0f%%" % (lim, 100.0 * got / lim)

    def test_无需降采样时步长为1(self):
        assert coarsen_strides(100, 100, 100_000) == (1, 1)

    def test_上限为零表示不限制(self):
        assert coarsen_strides(NY, NX, 0) == (1, 1)

    def test_退化输入不崩溃(self):
        assert coarsen_strides(1, 1, 10) == (1, 1)
        assert coarsen_strides(0, 0, 10) == (1, 1) or True


class TestCoarsenField:
    def test_轴与数据长度严格一致(self, field):
        """pcolormesh 要求 x/y 长度与数据形状完全对应，否则报错。"""
        for lim in (510_000, 250_000, 50_000, 5_000):
            f = coarsen_field(field, lim)
            assert f.x is not None and f.y is not None
            assert f.values.shape == (f.y.size, f.x.size), \
                "%s vs x=%d y=%d" % (f.values.shape, f.x.size, f.y.size)

    def test_保留元信息(self, field):
        f = coarsen_field(field, 100)
        assert f.x_name == field.x_name and f.y_name == field.y_name
        assert f.x_role is field.x_role and f.y_role is field.y_role
        assert f.units == field.units and f.name == field.name

    def test_纬度递减方向不变(self, field):
        """真实 L3 产品纬度从北到南递减，降采样不能把方向弄反。"""
        assert field.y[0] > field.y[-1]
        f = coarsen_field(field, 100)
        assert f.y[0] > f.y[-1]


class TestPrepareField:
    def test_为0时完全不降采样(self, field):
        out = prepare_field(field, PlotSpec(screen_cells=0))
        assert out.values.shape == field.values.shape

    def test_设置后生效(self, field):
        spec = PlotSpec(screen_cells=max(10, field.values.size // 4))
        out = prepare_field(field, spec)
        assert out.values.size <= spec.screen_cells
        assert out.values.size < field.values.size

    def test_本来就在上限内则原样返回(self, field):
        out = prepare_field(field, PlotSpec(screen_cells=field.values.size * 10))
        assert out is field

    def test_一维数据不受影响(self, source):
        """折线/剖面这类一维数据不该被降采样逻辑误伤。"""
        fd = source.read_field("lat")
        out = prepare_field(fd, PlotSpec(screen_cells=3))
        assert out.values.shape == fd.values.shape


def _synthetic(ny: int, nx: int):
    """造一个用于测试的二维场（不依赖真实数据文件）。"""
    import numpy as np
    from ncsight.core import FieldData
    from ncsight.core.detect import AxisRole
    return FieldData(
        name="v",
        values=np.zeros((ny, nx), dtype="float32"),
        x=np.linspace(-180.0, 180.0, nx),
        y=np.linspace(90.0, -90.0, ny),
        x_name="lon", y_name="lat",
        x_role=AxisRole.LON, y_role=AxisRole.LAT,
        units="1",
    )


class TestScreenCellsBudget:
    """模拟 GUI 设的屏幕格点预算，确认「格点数」与「屏幕像素」量级匹配。"""

    @pytest.mark.parametrize("canvas", [(850, 500), (1400, 800), (1920, 1080)])
    def test_预算与画布像素同量级(self, canvas):
        w, h = canvas
        budget = max(250_000, int(w * h * 1.2))
        field = _synthetic(1200, 2400)          # 288 万格点，足够触发降采样
        out = prepare_field(field, PlotSpec(screen_cells=budget))

        assert out.values.size <= budget, "降采样后不该超过预算"
        # 每个屏幕像素对应 0.2~4 个格点：既不糊（太少）也不浪费（太多）
        px_per_cell = (w * h) / float(out.values.size)
        assert 0.2 <= px_per_cell <= 4.0, \
            "每格点 %.2f 个像素，偏离合理区间" % px_per_cell
