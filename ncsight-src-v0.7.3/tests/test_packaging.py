# -*- coding: utf-8 -*-
"""打包相关：运行时资源配置、出图预设库。"""

import os

import pytest

from ncsight import _runtime
from ncsight.presets import (list_presets, load_preset, preset_names,
                             preset_path, save_preset)
from ncsight.core import PlotSpec


class TestRuntime:
    def test_开发环境不是frozen(self):
        assert _runtime.is_frozen() is False
        assert _runtime.bundle_dir() is None

    def test_程序目录存在(self):
        d = _runtime.app_dir()
        assert os.path.isdir(d)
        assert os.path.exists(os.path.join(d, "ncsight", "version.py"))

    def test_用户数据目录可写(self):
        d = _runtime.user_data_dir()
        assert os.path.isdir(d)
        probe = os.path.join(d, ".probe")
        with open(probe, "w") as fh:
            fh.write("x")
        os.remove(probe)

    def test_matplotlib缓存目录被设置(self):
        target = _runtime.configure_matplotlib()
        assert target and os.path.isdir(target)
        assert os.environ.get("MPLCONFIGDIR") == target

    def test_cartopy底图目录能被找到(self):
        """
        开发机上通常已经有 cartopy 缓存；找不到也不该抛异常 ——
        只是返回 None，让 cartopy 走默认逻辑。
        """
        got = _runtime.configure_cartopy()
        if got is not None:
            assert os.path.isdir(os.path.join(got, "shapefiles"))
            import cartopy
            assert cartopy.config["data_dir"] == got

    def test_apply_once幂等(self):
        first = _runtime.apply_once()
        second = _runtime.apply_once()
        assert second == {} or first == {}
        info = _runtime.configure_all()
        for key in ("frozen", "app_dir", "user_data_dir", "matplotlib_cache"):
            assert key in info


class TestPresets:
    def test_预设非空(self):
        names = preset_names()
        assert len(names) >= 5, "内置出图预设应该有若干条"

    def test_每条预设都能解析成PlotSpec(self):
        for name, desc, path in list_presets():
            assert os.path.exists(path), path
            spec = load_preset(name)
            assert isinstance(spec, PlotSpec)
            assert spec.kind, "预设必须指定图型"

    def test_预设可带yaml后缀查询(self):
        name = preset_names()[0]
        p1 = preset_path(name)
        p2 = preset_path(name + ".yaml")
        assert p1 and p1 == p2

    def test_不存在的预设报错(self):
        with pytest.raises(KeyError):
            load_preset("根本没有这个预设")

    def test_预设往返一致(self):
        name = preset_names()[0]
        spec = load_preset(name)
        assert PlotSpec.from_dict(spec.to_dict()).to_dict() == spec.to_dict()

    def test_含掩膜的预设字段正确(self):
        """「区域_抹掉陆地」这个预设应该真的开了掩膜与墨卡托投影。"""
        spec = load_preset("区域_抹掉陆地")
        assert spec.mask_land is True
        assert spec.projection == "Mercator"
        assert spec.bbox is not None and len(spec.bbox) == 4

    def test_距平预设居中于零(self):
        spec = load_preset("距平图_居中于零")
        assert spec.center_zero is True
        assert spec.cmap == "balance"

    def test_保存自定义预设(self, tmp_path):
        spec = PlotSpec(variable="sst", cmap="viridis", nbins=9)
        p = save_preset("单元测试_临时预设", spec)
        try:
            assert os.path.exists(p)
            assert load_preset("单元测试_临时预设").nbins == 9
        finally:
            os.remove(p)

    def test_预设名做了文件名消毒(self):
        spec = PlotSpec(variable="sst")
        p = save_preset('非法/字符:测试*', spec)
        try:
            assert os.path.exists(p)
            assert "/" not in os.path.basename(p)
        finally:
            os.remove(p)
