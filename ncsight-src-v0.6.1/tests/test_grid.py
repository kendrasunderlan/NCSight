# -*- coding: utf-8 -*-
"""栅格化：降采样、区域裁切。"""

import numpy as np
import pytest

from ncsight.core.grid import (coarsen_array, coarsen_field, subset_bbox,
                               MAX_PROJECT_CELLS)


class TestCoarsen:
    def test_大数组被压到上限以内(self):
        a = np.zeros((4000, 4000))
        out = coarsen_array(a, max_cells=100_000)
        assert out.shape[0] * out.shape[1] <= 100_000

    def test_小数组保持原样(self):
        a = np.zeros((10, 10))
        assert coarsen_array(a, max_cells=1000) is a

    def test_降采样不改变数值范围(self):
        a = np.arange(1000.0).reshape(25, 40)
        out = coarsen_array(a, max_cells=200)
        assert out.min() == pytest.approx(a.min())
        assert out.max() <= a.max()

    def test_降采样场坐标同步(self, field):
        """坐标轴必须跟数据同长度，否则 pcolormesh 会报维度不匹配。"""
        small = coarsen_field(field, max_cells=100)
        assert small.values.shape == (small.y.size, small.x.size)
        assert small.values.shape[0] * small.values.shape[1] <= 100

    def test_已经在限额内时原样返回(self, field):
        assert coarsen_field(field, max_cells=10**9) is field


class TestSubsetBbox:
    def test_基本裁切(self, field):
        out = subset_bbox(field, [0, 60, -30, 30])
        assert out.values.shape[0] < field.values.shape[0]
        assert out.values.shape[1] < field.values.shape[1]
        assert out.x.min() >= 0 and out.x.max() <= 60
        assert out.y.min() >= -30 and out.y.max() <= 30

    def test_正确处理递减纬度轴(self, field):
        """
        真实 L3 产品的 lat 是从北到南递减的。
        如果按「递增轴」的假设写裁切，会切出空数组或反向结果。
        """
        assert field.y[0] > field.y[-1], "前置条件：测试数据纬度递减"
        out = subset_bbox(field, [-180, 180, 0, 40])
        assert out.values.size > 0
        assert out.y.max() <= 40.0 + 1e-6
        assert out.y.min() >= 0.0 - 1e-6

    def test_空bbox原样返回(self, field):
        assert subset_bbox(field, None) is field
        assert subset_bbox(field, []) is field

    def test_范围之外不崩溃(self, field):
        out = subset_bbox(field, [500, 600, -90, -80])
        assert out is field or out.values.size > 0

    def test_坐标与数据长度一致(self, field):
        out = subset_bbox(field, [0, 60, -30, 30])
        assert out.values.shape == (out.y.size, out.x.size)

    def test_跨180度经线(self, field):
        out = subset_bbox(field, [170, -170, -20, 20])
        assert out.values.size >= 0        # 不崩溃即可
