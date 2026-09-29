# -*- coding: utf-8 -*-
"""导出与分析算子。"""

import os

import numpy as np
import pytest

from ncsight.core import analyze, export as ex


class TestExportGrid:
    def test_csv有表头且可解析(self, field, tmp_path):
        p = ex.export_grid_csv(field, str(tmp_path / "g.csv"))
        with open(p, encoding="utf-8-sig") as fh:
            lines = fh.read().strip().splitlines()
        assert len(lines) > 1
        assert "lon" in lines[0] and "lat" in lines[0]
        cols = lines[1].split(",")
        assert len(cols) == 3
        float(cols[0]); float(cols[1]); float(cols[2])

    def test_默认跳过NaN(self, field, tmp_path):
        p = ex.export_grid_csv(field, str(tmp_path / "g.csv"))
        n_csv = sum(1 for _ in open(p, encoding="utf-8-sig")) - 1
        assert n_csv == field.valid_count

    def test_可选保留NaN(self, field, tmp_path):
        p = ex.export_grid_csv(field, str(tmp_path / "g2.csv"), include_nan=True)
        n_csv = sum(1 for _ in open(p, encoding="utf-8-sig")) - 1
        assert n_csv == field.values.size

    def test_npz保留形状与坐标(self, field, tmp_path):
        p = ex.export_grid_npz(field, str(tmp_path / "g.npz"))
        d = np.load(p, allow_pickle=True)
        assert d["values"].shape == field.values.shape
        assert d["x"].shape == field.x.shape
        assert str(d["units"]) == field.units

    def test_自动补扩展名(self, field, tmp_path):
        assert ex.export_grid_csv(field, str(tmp_path / "noext")).endswith(".csv")
        assert ex.export_grid_npz(field, str(tmp_path / "noext")).endswith(".npz")


class TestExportText:
    def test_带表头的文本(self, source, tmp_path):
        p = ex.export_labeled_text(source, "sst", str(tmp_path / "t.txt"))
        text = open(p, encoding="utf-8").read()
        assert "数据集" in text and "sst" in text and "degree_C" in text

    def test_行数被截断保护(self, source, tmp_path):
        p = ex.export_labeled_text(source, "sst", str(tmp_path / "t2.txt"),
                                   max_rows=10)
        text = open(p, encoding="utf-8").read()
        assert "已截断" in text

    def test_结构说明(self, source, tmp_path):
        p = ex.export_overview(source, str(tmp_path / "ov.txt"))
        text = open(p, encoding="utf-8").read()
        assert "坐标轴" in text or "可制图变量" in text


class TestExportFigure:
    def test_多种格式(self, source, tmp_path):
        import matplotlib.pyplot as plt
        from ncsight.core import PlotSpec, render
        res = render(PlotSpec(variable="sst", kind="map", preset="single"), source)
        for fmt in ("png", "pdf", "svg"):
            p = ex.save_figure(res.fig, str(tmp_path / ("f." + fmt)), fmt=fmt, dpi=100)
            assert os.path.exists(p) and os.path.getsize(p) > 500
        plt.close(res.fig)

    def test_矢量格式忽略dpi不报错(self, source, tmp_path):
        import matplotlib.pyplot as plt
        from ncsight.core import PlotSpec, render
        res = render(PlotSpec(variable="sst", kind="map", preset="single"), source)
        p = ex.save_figure(res.fig, str(tmp_path / "v.pdf"), dpi=9999)
        assert os.path.getsize(p) > 500
        plt.close(res.fig)


class TestCombine:
    def test_距平(self, field):
        ref = analyze.wrap_like(field, np.full_like(field.values, 20.0), "ref")
        a = analyze.combine(field, ref, "difference")
        assert a.long_name.endswith("距平") or "−" in a.long_name
        v = a.values[np.isfinite(a.values)]
        assert abs(float(np.mean(v))) < 20.0

    def test_矢量合成(self, field):
        ref = analyze.wrap_like(field, np.ones_like(field.values) * 3.0, "v")
        m = analyze.combine(field, ref, "magnitude")
        assert np.allclose(np.nanmax(m.values),
                           np.nanmax(np.hypot(field.values, 3.0)), equal_nan=True)

    def test_形状不一致报错(self, field):
        bad = analyze.wrap_like(field, np.zeros((3, 3)), "bad")
        with pytest.raises(ValueError):
            analyze.combine(field, bad, "difference")

    def test_未知运算报错(self, field):
        with pytest.raises(ValueError):
            analyze.combine(field, field, "不存在的运算")


class TestAnalyzer:
    def test_合成(self, source):
        an = analyze.Analyzer(source)
        clim = an.composite("sst", "lat", "mean")   # 用纬度维演示聚合
        assert clim.values.ndim == 2

    def test_平滑(self, field):
        s = analyze.smooth(field, sigma=1.5)
        assert s.values.shape == field.values.shape
        # 平滑后极值应被削弱
        assert np.nanmax(s.values) <= np.nanmax(field.values) + 1e-9

    def test_梯度(self, field):
        g = analyze.gradient_magnitude(field)
        assert g.values.shape == field.values.shape
        assert np.nanmax(g.values) >= 0

    def test_区域时间序列接口存在(self, source):
        an = analyze.Analyzer(source)
        assert hasattr(an, "region_mean_series")
        assert hasattr(an, "point_series")
        assert hasattr(an, "vector_magnitude")
