# -*- coding: utf-8 -*-
"""绘图规格（PlotSpec）与工程的序列化 —— 可复现出图的基石。"""

import json
import os

import pytest

from ncsight.config import DEFAULT_PREFS, Session, load_prefs, save_prefs
from ncsight.core import PlotSpec
from ncsight.core.overlay import OverlaySpec


class TestPlotSpecSerialization:
    def test_默认值齐全(self):
        s = PlotSpec()
        d = s.to_dict()
        for key in ("kind", "variable", "cmap", "projection", "preset", "nbins"):
            assert key in d

    def test_往返一致(self):
        s = PlotSpec(variable="sst", kind="map", projection="Robinson",
                     cmap="thermal", nbins=13, bbox=[0, 100, -30, 30],
                     reverse=True, center_zero=True, mask_land=True,
                     vector_step=9, title="试验图")
        s.overlays.borders = True
        s.overlays.resolution = "50m"
        back = PlotSpec.from_dict(s.to_dict())
        assert back.to_dict() == s.to_dict()

    def test_yaml往返(self, tmp_path):
        s = PlotSpec(variable="sst", cmap="balance", nbins=21)
        p = str(tmp_path / "s.plot.yaml")
        s.save(p)
        assert os.path.exists(p)
        assert PlotSpec.load(p).to_dict() == s.to_dict()

    def test_json也能读(self, tmp_path):
        s = PlotSpec(variable="sst", nbins=7)
        p = str(tmp_path / "s.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(s.to_dict(), fh, ensure_ascii=False)
        assert PlotSpec.load(p).to_dict() == s.to_dict()

    def test_自动补yaml后缀(self, tmp_path):
        p = PlotSpec(variable="sst").save(str(tmp_path / "noext"))
        assert p.endswith(".yaml")

    def test_未知字段不崩溃(self):
        s = PlotSpec.from_dict({"variable": "sst", "不存在的字段": 123})
        assert s.variable == "sst"

    def test_clone不改原对象(self):
        a = PlotSpec(variable="sst", cmap="viridis")
        b = a.clone(cmap="thermal")
        assert a.cmap == "viridis" and b.cmap == "thermal"

    def test_clone可嵌套改overlays(self):
        a = PlotSpec()
        b = a.clone()
        b.overlays.coastline = False
        # clone 产生的是新对象，改 b 不应影响 a
        assert a.overlays.coastline is True

    def test_update就地改(self):
        a = PlotSpec(nbins=5)
        assert a.update(nbins=9) is a
        assert a.nbins == 9

    def test_嵌套overlays往返(self):
        s = PlotSpec(variable="sst")
        s.overlays = OverlaySpec(coastline=False, rivers=True, resolution="10m",
                                 line_width=0.9, shapefile="x.shp")
        back = PlotSpec.from_dict(s.to_dict())
        assert back.overlays.rivers is True
        assert back.overlays.resolution == "10m"
        assert back.overlays.shapefile == "x.shp"


class TestSession:
    def test_往返(self, tmp_path):
        s = Session.create("/data/a.nc")
        s.add(PlotSpec(variable="sst", cmap="thermal"))
        s.add(PlotSpec(variable="qual_sst", nbins=5))
        s.active = 1
        p = s.save(str(tmp_path / "sess"))
        assert p.endswith(".ncs.yaml")
        back = Session.load(p)
        assert back.dataset == "/data/a.nc"
        assert len(back.plots) == 2
        assert back.active == 1
        assert back.current().variable == "qual_sst"

    def test_current越界返回None(self):
        s = Session.create()
        assert s.current() is None

    def test_remove并夹紧active(self):
        s = Session.create()
        s.add(PlotSpec(variable="a"))
        s.add(PlotSpec(variable="b"))
        s.remove(1)
        assert len(s.plots) == 1 and s.active == 0

    def test_空文件能读(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("", encoding="utf-8")
        s = Session.load(str(p))
        assert s.plots == []


class TestPrefs:
    def test_默认键齐全(self):
        for k in ("last_dir", "preset", "cmap", "nbins"):
            assert k in DEFAULT_PREFS

    def test_存取不抛异常(self):
        prefs = load_prefs()
        assert isinstance(prefs, dict)
        assert "preset" in prefs
