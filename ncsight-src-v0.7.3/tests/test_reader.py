# -*- coding: utf-8 -*-
"""数据读取层：packed 解包、内嵌色表排除、主轴启发式。"""

import numpy as np
import pytest

from ncsight.core.detect import VarKind
from tests.conftest import NC_FILL, SCALE


class TestScan:
    def test_坐标轴识别(self, source):
        assert source.axis("lat").role.value == "lat"
        assert source.axis("lon").role.value == "lon"
        assert source.axis("lat").units == "degrees_north"

    def test_变量类型(self, source):
        assert source.variables["sst"].kind is VarKind.LONLAT_FIELD
        assert source.variables["qual_sst"].kind is VarKind.LONLAT_FIELD
        assert source.variables["lat"].is_coordinate

    def test_内嵌色表被排除出可制图清单(self, source):
        names = [v.name for v in source.plottable()]
        assert "palette" not in names, "palette 是色表，不该被当成数据场"
        assert "sst" in names and "qual_sst" in names

    def test_打包信息被如实记录(self, source):
        vi = source.variables["sst"]
        assert vi.has_scale_attrs
        assert vi.scale_factor == pytest.approx(SCALE)
        assert vi.fill_value == pytest.approx(NC_FILL)

    def test_建议范围来自属性(self, source):
        assert source.variables["sst"].suggested_range == (-2.0, 45.0)


class TestPrimaryField:
    def test_主轴不会选到质量变量(self, source):
        """这是踩过的坑：Panoply 直接给第一个变量，L3 产品常打开就是 qual_sst。"""
        assert source.primary_field().name == "sst"


class TestReadField:
    def test_packed解包正确(self, source):
        """解包后必须是物理量（摄氏度），不是原始整数。"""
        fd = source.read_field("sst")
        v = fd.values[np.isfinite(fd.values)]
        assert v.size > 0
        assert -5.0 < v.min() < 35.0, "值域应该像海温，而不是 int16 原始值"
        assert v.max() < 60.0

    def test_填充值转成NaN而不是参与统计(self, source):
        fd = source.read_field("sst")
        assert np.isnan(fd.values).any(), "应该有陆地区域的缺失值"
        # 原始填充值 -32767 绝不该出现在解包结果里
        assert not np.any(fd.values == pytest.approx(NC_FILL * SCALE))

    def test_不会重复应用scale_factor(self, source):
        """
        关键回归测试：netCDF4 默认已解包，若再乘一次 scale_factor，
        数值会缩小 200 倍 —— 而空间图案仍然正确，极难发现。
        """
        fd = source.read_field("sst")
        s = fd.stats()
        assert s["max"] > 5.0, "数值量级明显偏小，多半是重复解包了"

    def test_坐标与轴角色(self, source):
        fd = source.read_field("sst")
        assert fd.x_role.value == "lon"
        assert fd.y_role.value == "lat"
        assert fd.x.shape == (36,)
        assert fd.y.shape == (18,)
        assert fd.y[0] > fd.y[-1], "测试数据模拟真实 L3 产品的递减纬度轴"

    def test_caption带单位(self, source):
        assert source.read_field("sst").caption == "Sea Surface Temperature [degree_C]"

    def test_不存在的变量报错(self, source):
        from ncsight.core.reader import NcSourceError
        with pytest.raises(NcSourceError):
            source.read_field("no_such_var")


class TestDescribe:
    def test_概览包含关键信息(self, source):
        text = source.describe()
        assert "sst" in text and "lonlat" in text

    def test_变量属性文本(self, source):
        text = source.describe_text("sst")
        assert "scale_factor" in text or "打包" in text
        assert "degree_C" in text
