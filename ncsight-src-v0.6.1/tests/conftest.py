# -*- coding: utf-8 -*-
"""
测试夹具
========
**不依赖任何真实数据文件** —— 这里现场生成一个「迷你 VIIRS」风格的
netCDF 文件，包含本项目踩过的所有坑：

  * int16 packed 数据（scale_factor / add_offset / _FillValue）
  * OBPG 风格的「交错存储」palette 变量
  * lat 递减 / lon 递增（跟真实 L3 产品一致）
  * CF 属性（units / standard_name / long_name）
  * suggested_image_scaling_minimum/maximum 可视化线索

这样测试可以离线、快速、可重复地跑，也顺便把解析逻辑的正确性钉死。
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NC_FILL = -32767
SCALE = 0.005


def _make_palette() -> np.ndarray:
    """构造一个「交错存储」的 3x256 调色板（模拟 OBPG 的排列方式）。"""
    n = 256
    t = np.linspace(0, 1, n)
    # 三条连续的色带
    r = np.clip(255 * np.abs(np.sin(t * np.pi * 1.5)), 0, 255)
    g = np.clip(255 * np.abs(np.cos(t * np.pi * 0.9)), 0, 255)
    b = np.clip(255 * (1 - t), 0, 255)
    rgb = np.stack([r, g, b], axis=1).astype(np.uint8)      # (256, 3)
    # 交错回去：模拟真实文件的存储顺序
    flat = rgb
    inter = np.empty_like(flat)
    inter[0::3], inter[1::3], inter[2::3] = flat[:86], flat[86:171], flat[171:]
    return inter.T                                          # (3, 256)


@pytest.fixture(scope="session")
def sample_path(tmp_path_factory) -> str:
    """生成一个迷你 nc 文件，返回路径。"""
    import netCDF4 as nc

    d = tmp_path_factory.mktemp("ncsight_data")
    path = str(d / "mini_viirs_l3m_sst.nc")

    ds = nc.Dataset(path, "w", format="NETCDF4")
    ds.title = "MINI VIIRSJ1 Level-3 Standard Mapped Image"
    ds.Conventions = "CF-1.6 ACDD-1.3"
    ds.instrument = "VIIRS"
    ds.map_projection = "Equidistant Cylindrical"

    nlat, nlon = 18, 36
    ds.createDimension("lat", nlat)
    ds.createDimension("lon", nlon)
    ds.createDimension("rgb", 3)
    ds.createDimension("eightbitcolor", 256)

    lat_v = ds.createVariable("lat", "f4", ("lat",))
    lat_v.units = "degrees_north"
    lat_v.standard_name = "latitude"
    lat_v.long_name = "Latitude"
    lat_v[:] = np.linspace(85.0, -85.0, nlat).astype("f4")     # 递减，同真实产品

    lon_v = ds.createVariable("lon", "f4", ("lon",))
    lon_v.units = "degrees_east"
    lon_v.standard_name = "longitude"
    lon_v.long_name = "Longitude"
    lon_v[:] = np.linspace(-175.0, 175.0, nlon).astype("f4")

    # 一个平滑的「海温」场：赤道暖、极地冷，加一块陆地空洞
    lat2, lon2 = np.meshgrid(lat_v[:], lon_v[:], indexing="ij")
    field = 28.0 - 0.28 * np.abs(lat2) + 3.0 * np.cos(np.radians(lon2) * 2.0)
    land = (np.abs(lat2 - 30) < 8) & (np.abs(lon2 - 60) < 15)
    field = np.where(land, np.nan, field)

    sst = ds.createVariable("sst", "i2", ("lat", "lon"),
                            fill_value=NC_FILL)
    sst.long_name = "Sea Surface Temperature"
    sst.units = "degree_C"
    sst.standard_name = "sea_surface_temperature"
    sst.valid_min = -1000
    sst.valid_max = 10000
    sst.display_min = -2.0
    sst.display_max = 45.0
    sst.suggested_image_scaling_minimum = -2.0
    sst.suggested_image_scaling_maximum = 45.0

    # ★ 顺序很重要 ★
    # netCDF4 在**写入时**也会应用 scale_factor/add_offset。
    # 如果先声明 scale_factor 再写 packed 整数，写入的会是 packed/scale
    #（本例会被放大 200 倍，直接溢出 int16），读回来就完全不对了。
    # 正确做法：先把原始整数写进去，再声明打包参数。
    packed = np.where(np.isnan(field), float(NC_FILL), np.round(field / SCALE))
    sst[:] = packed.astype("i2")
    sst.scale_factor = SCALE
    sst.add_offset = 0.0

    qual = ds.createVariable("qual_sst", "u1", ("lat", "lon"), fill_value=255)
    qual.long_name = "Quality Levels, Sea Surface Temperature"
    qual.valid_min = 0
    qual.valid_max = 5
    q = np.zeros((nlat, nlon), dtype="u1")
    q[::3, ::4] = 1
    q[1::5, 2::7] = 2
    qual[:] = q

    pal = ds.createVariable("palette", "u1", ("rgb", "eightbitcolor"))
    pal[:] = _make_palette()

    ds.close()
    return path


@pytest.fixture()
def source(sample_path):
    from ncsight.core import NcSource
    src = NcSource(sample_path)
    yield src
    src.close()


@pytest.fixture()
def field(source):
    return source.read_field("sst")


@pytest.fixture()
def spec():
    from ncsight.core import PlotSpec
    return PlotSpec(variable="sst", kind="map")
