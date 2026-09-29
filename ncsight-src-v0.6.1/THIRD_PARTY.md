# 第三方组件与许可

NCSight 自身的代码以 **MIT** 许可发布（见 [LICENSE](LICENSE)）。
但它依赖若干第三方库，**发布打包好的 exe 时**这些库的许可也必须遵守。

下面按「是否随 exe 一起分发」分类。

---

## 一、随 exe 一起分发的组件（发布二进制时必须遵守）

| 组件 | 许可 | 说明 |
|---|---|---|
| **PySide6 / Qt 6** | **LGPL-3.0**（另有商业授权） | ⚠️ 见下方专门说明 |
| **cartopy** | **LGPL-3.0** | 与 Qt 同属弱著佐权，需允许替换 |
| matplotlib | PSF-based（类 BSD） | 宽松 |
| numpy | BSD-3-Clause | 宽松 |
| scipy | BSD-3-Clause | 宽松 |
| netCDF4-python | MIT | 宽松 |
| h5netcdf / h5py | BSD-3-Clause | 宽松 |
| pyproj | MIT | 宽松 |
| shapely | BSD-3-Clause | 宽松 |
| PyYAML | MIT | 宽松 |
| pillow | MIT-CMU | 宽松 |
| cmocean | MIT | 宽松 |
| cmcrameri | MIT | 宽松 |
| imageio | BSD-2-Clause | 宽松 |
| Natural Earth 数据 | Public Domain | 底图（110m/50m/10m） |

### ⚠️ 关于 LGPL（PySide6 / Qt）

Qt 和 cartopy 是 **LGPL-3.0**。LGPL 允许你在自己的程序里链接它们、
甚至一起分发，但要求：

1. **必须允许最终用户替换这些库的版本**（也就是"可重新链接"）。
   NCSight 打包时采用的是 **onedir 模式**（`_internal/` 里放的是独立的
   `.dll` / `.pyd` 文件，不是单文件自解压），用户可以直接替换
   `_internal/PySide6/` 或 `_internal/cartopy/` 下的库文件 ——
   **这一条已经满足**。
2. **必须附带 LGPL 全文**，并声明使用了这些库以及其许可。
   本文件即承担声明作用；发布二进制时请一并提供 Qt 与 cartopy 的
   LGPL-3.0 文本（可从各自仓库获取，或写清获取地址）。
3. **不得修改这些库后闭源分发**。NCSight 没有修改它们。

> 如果你打算以**商业闭源**方式分发，需要购买 Qt 的商业授权，
> 或改用不依赖 PySide6 的构建（NCSight 的内核 `core/` 与 CLI
> **完全不依赖 Qt**，可以只用命令行版本，此时不涉及 LGPL）。

### 关于 Natural Earth 底图

Natural Earth 数据属于 **公有领域（Public Domain）**，可自由分发，
无需署名（但仍建议在文档中提及数据来源）。

---

## 二、仅在从源码安装时才用到（不随 exe 分发）

这些是可选依赖，只在启用对应功能时用到：

| 组件 | 许可 | 用途 |
|---|---|---|
| xarray | Apache-2.0 | 备用读取后端 |
| dask | BSD-3-Clause | 超大文件分块读取 |
| ffmpeg（外部可执行文件） | LGPL-2.1+ / GPL（视构建） | 导出 MP4。NCSight 不打包它，需要用户自行安装；不装也能用 GIF |

---

## 三、设计上的说明

NCSight 刻意做了「**内核不含 GUI 依赖**」的约束
（`ncsight/core/` 与 `ncsight/style.py` 里不允许 `import` 任何 GUI 库）。
这带来一个许可上的好处：**命令行版本不链接 Qt，不受 LGPL 约束**，
如果你需要完全宽松的许可，可以只用 CLI 部分。

---

## 四、版权与引用声明

NCSight 的实现参考了 NASA Panoply 的功能设计（Panoply 为公开的
科研可视化工具，其源码与资源的使用遵循其自身条款）。NCSight 为
独立重写实现，不包含 Panoply 的原始代码。

本项目使用的**色表**来自 cmocean、cmcrameri 与 matplotlib 的内置色表，
均以各自的宽松许可发布；作者姓名建议在论文中按各自要求引用：

- Thyng, K. M., Greene, C. A., Hetland, R. D., Zimmerle, H. M., & DiMarco, S. F. (2016).
  True colors of oceanography. *Oceanography*, 29(3), 10.
- Crameri, F. (2018). Scientific colour maps. *Zenodo*. https://doi.org/10.5281/zenodo.1243862
