# -*- coding: utf-8 -*-
"""坐标轴与变量类型识别（对应 Panoply 的 NcVarTypeDetector）。"""

from ncsight.core.detect import (AxisRole, VarKind, classify_axis,
                                 classify_variable, detect_fill_value,
                                 detect_suggested_range, find_vector_partner)


class TestClassifyAxis:
    def test_标准单位(self):
        assert classify_axis("lat", units="degrees_north").role is AxisRole.LAT
        assert classify_axis("lon", units="degrees_east").role is AxisRole.LON

    def test_单位写法不规范也能认出来(self):
        # 真实数据里这三种写法都出现过
        assert classify_axis("y", units="degree_N").role is AxisRole.LAT
        assert classify_axis("x", units="Degrees_East").role is AxisRole.LON
        assert classify_axis("nav_lat", units="").role is AxisRole.LAT

    def test_degrees兜底(self):
        assert classify_axis("longitude", units="degrees").role is AxisRole.LON
        assert classify_axis("latitude", units="degrees").role is AxisRole.LAT

    def test_靠standard_name(self):
        assert classify_axis("yy", standard_name="latitude").role is AxisRole.LAT
        assert classify_axis("xx", standard_name="longitude").role is AxisRole.LON

    def test_时间轴(self):
        assert classify_axis("time", units="days since 1950-01-01").role is AxisRole.TIME
        assert classify_axis("time", units="").role is AxisRole.TIME

    def test_垂向轴(self):
        assert classify_axis("depth", units="m").role is AxisRole.VERT
        assert classify_axis("lev", standard_name="depth").role is AxisRole.VERT

    def test_无关变量(self):
        assert classify_axis("sst", units="degree_C").role is AxisRole.OTHER

    def test_判定依据可追溯(self):
        a = classify_axis("lat", units="degrees_north")
        assert "degrees_north" in a.reason


class TestClassifyVariable:
    def test_经纬场(self):
        roles = [AxisRole.LAT, AxisRole.LON]
        assert classify_variable("sst", roles, 2, {}) is VarKind.LONLAT_FIELD

    def test_三维时间场仍识别为经纬场(self):
        roles = [AxisRole.TIME, AxisRole.LAT, AxisRole.LON]
        assert classify_variable("sst", roles, 3, {}) is VarKind.LONLAT_FIELD

    def test_hovmoller双向(self):
        assert classify_variable("a", [AxisRole.LON, AxisRole.TIME], 2, {}) is VarKind.LONTIME
        assert classify_variable("b", [AxisRole.LAT, AxisRole.TIME], 2, {}) is VarKind.LATTIME

    def test_剖面(self):
        assert classify_variable("a", [AxisRole.VERT, AxisRole.LAT], 2, {}) is VarKind.LATVERT

    def test_一维(self):
        assert classify_variable("t", [AxisRole.TIME], 1, {}) is VarKind.TIMESERIES
        assert classify_variable("d", [AxisRole.VERT], 1, {}) is VarKind.PROFILE_1D
        assert classify_variable("x", [AxisRole.OTHER], 1, {}) is VarKind.LINE_1D


class TestVectorPairing:
    def test_常见命名(self):
        names = ["u10", "v10", "sst"]
        assert find_vector_partner("u10", names) == "v10"
        assert find_vector_partner("v10", names) == "u10"

    def test_ocean模式命名(self):
        names = ["uo", "vo"]
        assert find_vector_partner("uo", names) == "vo"

    def test_下划线前缀(self):
        names = ["water_u", "water_v"]
        assert find_vector_partner("water_u", names) == "water_v"

    def test_无配对返回None(self):
        assert find_vector_partner("sst", ["sst", "lat"]) is None


class TestAttrHints:
    def test_建议范围优先级(self):
        attrs = {"display_min": -2.0, "display_max": 45.0,
                 "valid_min": 0.0, "valid_max": 100.0}
        assert detect_suggested_range(attrs) == (-2.0, 45.0)

    def test_actual_range二元组(self):
        assert detect_suggested_range({"actual_range": [1.0, 9.0]}) == (1.0, 9.0)

    def test_范围非法则忽略(self):
        assert detect_suggested_range({"display_min": 5.0, "display_max": 1.0}) is None

    def test_填充值(self):
        assert detect_fill_value({"_FillValue": -32767}) == -32767.0
        assert detect_fill_value({}) is None
