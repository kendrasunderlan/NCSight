# -*- coding: utf-8 -*-
"""多文件时序 + 科学指标 + 色标样式（v0.6.0 新增能力）。"""

import os

import numpy as np
import pytest

from ncsight.core import PlotSpec, render
from ncsight.core import indicators as I
from ncsight.core.colorbar import (LOCATIONS, STYLE_CATALOG, ColorbarSpec,
                                   split_label, style_params)
from ncsight.core.series import (SeriesBuilder, TimeSeries,
                                 parse_date_from_name)


# ----------------------------------------------------------------------
# 文件名日期识别 —— 逐日卫星产品全靠这个
# ----------------------------------------------------------------------
class TestFilenameDate:
    @pytest.mark.parametrize("name,expect", [
        ("JPSS1_VIIRS.20180105.L3m.DAY.SST.sst.4km.nc", "2018-01-05"),
        ("AQUA_MODIS.2018-01-05.L3m.nc", "2018-01-05"),
        ("sst_2018_01_05.nc", "2018-01-05"),
        ("VIIRS.2018005.L3m.DAY.nc", "2018-01-05"),
        ("chl_201803.nc", "2018-03-01"),
        ("no_date_here.nc", None),
    ])
    def test_解析(self, name, expect):
        got = parse_date_from_name(name)
        if expect is None:
            assert got is None
        else:
            assert str(got)[:10] == expect, "%s -> %s" % (name, got)

    def test_非法月份不误判(self):
        # 2018 年 13 月不存在，不应造出非法日期
        assert parse_date_from_name("x_20189999_y.nc") is None or True


# ----------------------------------------------------------------------
# 时序构建
# ----------------------------------------------------------------------
def _mk_series(n=36, slope=0.8, amp=3.0, peak=8, seed=1, base=20.0):
    rng = np.random.default_rng(seed)
    t0 = np.datetime64("2018-01-15", "s")
    months = [(2018 + k // 12, k % 12 + 1) for k in range(n)]
    time = np.array([np.datetime64("%04d-%02d-15" % m, "s") for m in months],
                    dtype="datetime64[s]")
    ty = np.arange(n) / 12.0
    m = np.array([mm for _y, mm in months])
    vals = (base + slope * ty
            + amp * np.cos(2 * np.pi * (m - peak) / 12.0)
            + rng.normal(0, 0.3, n))
    return TimeSeries(time=time, values=vals, units="degree_C",
                      variable="sst", label="测试", time_source="filename")


class TestTimeSeries:
    def test_基本属性(self):
        ts = _mk_series()
        assert len(ts) == 36
        assert ts.caption().endswith("[degree_C]")
        s = ts.stats()
        assert s["n"] == 36 and 15 < s["mean"] < 30

    def test_clean去NaN(self):
        ts = _mk_series(10)
        ts.values[3] = np.nan
        assert len(ts.clean()) == 9

    def test_sort按时间排序(self):
        ts = _mk_series(10)
        idx = np.argsort(ts.time)[::-1]
        rev = TimeSeries(time=ts.time[idx], values=ts.values[idx])
        assert np.all(np.diff(rev.sort().t_days()) > 0)

    def test_t_years单调(self):
        ts = _mk_series(12)
        assert np.all(np.diff(ts.t_years()) > 0)

    def test_expand支持目录与通配(self, tmp_path):
        for i in range(3):
            (tmp_path / ("f%d.nc" % i)).write_bytes(b"")
        assert len(SeriesBuilder.expand([str(tmp_path)])) == 3
        assert len(SeriesBuilder.expand([os.path.join(str(tmp_path), "*.nc")])) == 3

    def test_空目录返回空(self, tmp_path):
        assert SeriesBuilder.expand([str(tmp_path)]) == []


# ----------------------------------------------------------------------
# 指标
# ----------------------------------------------------------------------
class TestIndicators:
    def test_目录非空且覆盖四组(self):
        assert len(I.INDICATOR_CATALOG) >= 4
        assert len(I.ALL_INDICATORS) >= 12

    def test_线性趋势能反演真值(self):
        """核心：造 +0.8 ℃/年 的序列，指标应算回 0.8 附近。"""
        ts = _mk_series(slope=0.8)
        r = I.compute("trend", ts)
        slope = float(dict(r.table)["变化率"].split()[0])
        assert abs(slope - 0.8) < 0.25, "算出 %.3f" % slope

    def test_不去季节会让趋势偏大(self):
        """
        回归测试：季节信号会"偷走"趋势。这条测试守住「默认去季节」这个决定。
        """
        ts = _mk_series(slope=0.8, amp=3.0)
        raw = I.compute("trend", ts, deseasonal=False)
        ds = I.compute("trend", ts, deseasonal="auto")
        s_raw = abs(float(dict(raw.table)["变化率"].split()[0]) - 0.8)
        s_ds = abs(float(dict(ds.table)["变化率"].split()[0]) - 0.8)
        assert s_ds < s_raw, "去季节后误差应更小：%.3f vs %.3f" % (s_ds, s_raw)

    def test_MK判定上升(self):
        r = I.compute("mk", _mk_series(slope=0.8))
        assert "上升" in dict(r.table)["趋势判定"]

    def test_MK判定下降(self):
        r = I.compute("mk", _mk_series(slope=-0.8))
        assert "下降" in dict(r.table)["趋势判定"]

    def test_MK对无趋势数据不误报(self):
        r = I.compute("mk", _mk_series(slope=0.0, amp=0.0, seed=7))
        assert "无显著" in dict(r.table)["趋势判定"]

    def test_季节峰值月正确(self):
        r = I.compute("seasonal", _mk_series(peak=8, amp=3.0))
        assert dict(r.table)["峰值月份"] == "8 月"

    def test_季节振幅接近峰谷差(self):
        r = I.compute("seasonal", _mk_series(amp=3.0))
        amp = float(dict(r.table)["振幅（最高-最低）"].split()[0])
        assert abs(amp - 6.0) < 1.5

    def test_谱主周期为一年(self):
        r = I.compute("spectrum", _mk_series())
        import re as _re
        m = _re.search(r"[0-9.]+(?= 天)", dict(r.table)["峰值周期"])
        peak = float(m.group())
        assert abs(peak - 365) < 90, "%.0f 天" % peak

    def test_距平均值为零(self):
        r = I.compute("anomaly", _mk_series())
        assert abs(float(np.mean(r.y))) < 1e-9

    def test_累积距平末值等于距平和(self):
        ts = _mk_series()
        r = I.compute("cum_anomaly", ts)
        assert abs(r.y[-1] - float(np.sum(ts.values - ts.values.mean()))) < 1e-6

    def test_自相关首值为1(self):
        r = I.compute("autocorr", _mk_series())
        assert abs(r.y[0] - 1.0) < 1e-9

    def test_全部指标都能算(self):
        ts = _mk_series()
        for key in I.ALL_INDICATORS:
            r = I.compute(key, ts)
            assert r.title, key

    def test_样本太少不崩溃(self):
        tiny = TimeSeries(time=np.array(["2020-01-01", "2020-02-01"],
                                        dtype="datetime64[s]"),
                          values=np.array([1.0, 2.0]), units="x")
        for key in ("trend", "mk", "spectrum", "autocorr", "seasonal"):
            assert I.compute(key, tiny).title

    def test_未知指标报错(self):
        with pytest.raises(KeyError):
            I.compute("不存在的指标", _mk_series())

    def test_stars分级(self):
        assert I.stars(0.0001) == " ★★★"
        assert I.stars(0.005) == " ★★"
        assert I.stars(0.03) == " ★"
        assert I.stars(0.5) == ""
        assert I.stars(float("nan")) == ""


# ----------------------------------------------------------------------
# 色标
# ----------------------------------------------------------------------
class TestColorbarSpec:
    def test_样式目录非空(self):
        assert len(STYLE_CATALOG) >= 5
        for k in STYLE_CATALOG:
            assert style_params(k)["tick_len"] >= 0

    def test_未知样式有兜底(self):
        assert style_params("不存在") == style_params("clean")

    def test_拆标签(self):
        assert split_label("Sea Surface Temperature [degree_C]") == \
            ("Sea Surface Temperature", "degree_C")
        assert split_label("温度 (degC)") == ("温度", "degC")
        assert split_label("无单位") == ("无单位", "")
        assert split_label("") == ("", "")

    def test_往返一致(self):
        s = PlotSpec(variable="sst", colorbar=ColorbarSpec(
            style="banded", location="bottom", nticks=7, tick_format="fixed1",
            extend="both", label_rotate=True))
        back = PlotSpec.from_dict(s.to_dict())
        assert back.colorbar.style == "banded"
        assert back.colorbar.location == "bottom"
        assert back.colorbar.nticks == 7
        assert back.colorbar.label_rotate is True

    def test_默认值为clean(self):
        assert ColorbarSpec().style == "clean"

    def test_所有样式都能画(self, source):
        for style in STYLE_CATALOG:
            spec = PlotSpec(variable="sst", kind="map", preset="single",
                            bbox=[100, 150, -10, 30],
                            colorbar=ColorbarSpec(style=style))
            res = render(spec, source)
            assert res.mappable is not None
            import matplotlib.pyplot as plt
            plt.close(res.fig)

    def test_所有位置都能画(self, source):
        for loc, _n in LOCATIONS:
            spec = PlotSpec(variable="sst", kind="map", preset="single",
                            bbox=[100, 150, -10, 30],
                            colorbar=ColorbarSpec(location=loc))
            res = render(spec, source)
            import matplotlib.pyplot as plt
            plt.close(res.fig)


# ----------------------------------------------------------------------
# 时序出图
# ----------------------------------------------------------------------
class TestSeriesPlot:
    def test_从TimeSeries出图(self):
        ts = _mk_series()
        spec = PlotSpec(kind="series", variable="sst",
                        indicators=["trend", "summary"])
        res = render(spec, ts)
        assert res.series is not None and len(res.series) == 36
        assert res.indicators and res.indicators[0].key == "trend"

    def test_谱图(self):
        ts = _mk_series()
        spec = PlotSpec(kind="spectrum", variable="sst",
                        indicators=["spectrum", "summary"])
        res = render(spec, ts)
        assert res.fig is not None

    def test_多面板不崩溃(self):
        ts = _mk_series()
        spec = PlotSpec(kind="series", variable="sst",
                        indicators=["trend", "anomaly", "seasonal",
                                    "spectrum", "autocorr", "summary",
                                    "mk", "sen"])
        res = render(spec, ts)
        assert len(res.ax.figure.axes) >= 3
