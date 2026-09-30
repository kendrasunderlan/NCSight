# -*- coding: utf-8 -*-
"""命令行接口：每个子命令都能跑通，且与 core 行为一致。"""

import json
import os

import pytest

from ncsight.cli import main
from ncsight.version import __version__


class TestBasicCommands:
    def test_version(self, capsys):
        assert main(["version"]) == 0
        out = capsys.readouterr().out
        assert __version__ in out

    def test_version_verbose列出环境(self, capsys):
        assert main(["version", "-v"]) == 0
        out = capsys.readouterr().out
        assert "numpy" in out and "matplotlib" in out

    def test_options列出图型与投影(self, capsys):
        assert main(["options"]) == 0
        out = capsys.readouterr().out
        assert "map" in out and "Robinson" in out and "PlotSpec" in out

    def test_无参数打印帮助(self, capsys):
        assert main([]) == 0
        assert "ncsight" in capsys.readouterr().out


class TestInfo:
    def test_文本输出(self, sample_path, capsys):
        assert main(["info", sample_path]) == 0
        out = capsys.readouterr().out
        assert "sst" in out and "lonlat" in out

    def test_json输出(self, sample_path, capsys):
        assert main(["info", sample_path, "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert "dimensions" in data
        assert any(v["name"] == "sst" for v in data["plottable"])

    def test_verbose显示变量属性(self, sample_path, capsys):
        assert main(["info", sample_path, "-v"]) == 0
        assert "scale_factor" in capsys.readouterr().out

    def test_文件不存在返回2(self, capsys):
        assert main(["info", "不存在的文件.nc"]) == 2

    def test_自动选主变量而非质量变量(self, sample_path, capsys):
        main(["info", sample_path])
        out = capsys.readouterr().out
        # 可制图清单里 sst 应该在，且 palette 不该出现
        assert "palette" not in out.split("可制图变量")[-1]


class TestPlot:
    def test_默认出图(self, sample_path, tmp_path, capsys):
        out = str(tmp_path / "a.png")
        assert main(["plot", sample_path, "-o", out]) == 0
        assert os.path.exists(out) and os.path.getsize(out) > 500
        assert "已输出" in capsys.readouterr().out

    def test_指定变量与投影(self, sample_path, tmp_path):
        out = str(tmp_path / "b.pdf")
        assert main(["plot", sample_path, "-v", "sst", "--projection", "Robinson",
                     "--preset", "single", "-o", out]) == 0
        assert os.path.exists(out)

    def test_set覆盖任意字段(self, sample_path, tmp_path):
        out = str(tmp_path / "c.png")
        assert main(["plot", sample_path, "-v", "sst",
                     "--set", "nbins=7", "--set", "cmap=thermal",
                     "--set", "overlays.coastline=false",
                     "-o", out]) == 0
        assert os.path.exists(out)

    def test_导出配置模板(self, sample_path, tmp_path, capsys):
        out = str(tmp_path / "spec.yaml")
        assert main(["spec", sample_path, "-v", "sst", "-o", out]) == 0
        assert os.path.exists(out)
        from ncsight.core import PlotSpec
        assert PlotSpec.load(out).variable == "sst"

    def test_配置往返复现同一张图(self, sample_path, tmp_path):
        spec_path = str(tmp_path / "repro.yaml")
        assert main(["spec", sample_path, "-v", "sst", "-o", spec_path]) == 0
        o1 = str(tmp_path / "o1.png")
        o2 = str(tmp_path / "o2.png")
        assert main(["plot", sample_path, "-o", o1, "--spec", spec_path]) == 0
        assert main(["plot", sample_path, "-o", o2, "--spec", spec_path]) == 0
        assert os.path.getsize(o1) == os.path.getsize(o2), "同一配置应产出同样的图"

    def test_未知配置项报错(self, sample_path, tmp_path, capsys):
        with pytest.raises(SystemExit):
            main(["plot", sample_path, "--set", "根本不存在=1",
                  "-o", str(tmp_path / "x.png")])

    def test_保存本次参数为新配置(self, sample_path, tmp_path):
        out = str(tmp_path / "o.png")
        sp = str(tmp_path / "saved.yaml")
        assert main(["plot", sample_path, "-v", "sst", "--cmap", "thermal",
                     "-o", out, "--save-spec", sp]) == 0
        from ncsight.core import PlotSpec
        assert PlotSpec.load(sp).cmap == "thermal"


class TestExportCommand:
    def test_csv(self, sample_path, tmp_path, capsys):
        out = str(tmp_path / "g.csv")
        assert main(["export", sample_path, "-v", "sst", "--format", "csv",
                     "-o", out]) == 0
        assert os.path.getsize(out) > 100

    def test_npz(self, sample_path, tmp_path):
        out = str(tmp_path / "g.npz")
        assert main(["export", sample_path, "-v", "sst", "--format", "npz",
                     "-o", out]) == 0
        assert os.path.exists(out)

    def test_数据集结构说明(self, sample_path, tmp_path):
        out = str(tmp_path / "ov.txt")
        assert main(["export", sample_path, "--all-overview", "-o", out]) == 0
        assert "sst" in open(out, encoding="utf-8").read()


class TestBatchCommand:
    def test_批量出图(self, sample_path, tmp_path, capsys):
        import shutil
        d = tmp_path / "data"
        d.mkdir()
        for i in range(2):
            shutil.copy(sample_path, str(d / ("f%d.nc" % i)))
        outdir = str(tmp_path / "figs")
        assert main(["batch", str(d), "-o", outdir, "--format", "png",
                     "--dpi", "80", "-v", "sst"]) == 0
        pngs = [f for f in os.listdir(outdir) if f.endswith(".png")]
        assert len(pngs) == 2

    def test_报告文件(self, sample_path, tmp_path):
        outdir = str(tmp_path / "figs2")
        rep = str(tmp_path / "report.txt")
        assert main(["batch", sample_path, "-o", outdir, "-v", "sst",
                     "--dpi", "70", "--report", rep]) == 0
        assert os.path.exists(rep)

    def test_空目录返回2(self, tmp_path, capsys):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert main(["batch", str(empty), "-o", str(tmp_path / "o")]) == 2
