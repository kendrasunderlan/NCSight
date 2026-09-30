# 更新日志

本文件记录 NCSight 的所有重要变更。
格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

版本号与里程碑的对应关系：

| 版本  | 里程碑 | 主题 |
|-------|--------|------|
| 0.1.0 | M1     | 最小可用内核与命令行 |
| 0.2.0 | M2     | 白色简约图形界面 |
| 0.3.0 | M3     | 科研增强（掩膜 / 分析 / 动画 / 批量） |

---

## [Unreleased]

### 计划中
- （待补充）

---

## [0.7.3] - 2026-09-29

### 计划中
- （待补充）

---

## [0.7.2] - 2026-09-29

### 计划中
- （待补充）

---

## [0.7.1] - 2026-09-29

### 计划中
- （待补充）

---

## [0.7.0] - 2026-09-29

### 修复
- **中/高精度底图卡死**：切换 50m / 10m 底图或勾选国界时界面长时间无响应。
  两处根因：
  - 底图叠加会把**全球**的海岸线全部加进去，哪怕只看 30°x30° 的区域。
    10m 海岸线有 4133 条线段、41 万个顶点，视野外的 99% 仍要逐个做投影变换。
    现在按视野包围盒先粗筛，再按「一个屏幕像素」的容差抽稀
    （优先用 shapely 的 Douglas-Peucker，无 shapely 则按弧长等距取样）
  - 投影图里每个格点的四个角都要经 cartopy 变换，单位格点代价比等距圆柱
    高好几倍 —— 投影图的屏幕格点预算相应收紧
  - 效果（区域 60°x50°，屏幕预算 60 万格点）：
    等距圆柱 **10m 14.6s → 0.5s（28 倍）**；Robinson **10m 19.5s → 4.1s**

### 新增
- **进度条**：状态栏右下角显示进度与百分比，时序面板同步回显，形如
  「读取 12/36：TEST_SST_20191215.nc（33%）」。算几百个文件的指标时
  不再是一片安静的黑箱
- `render(spec, source, progress=...)` 全链路支持进度回调；时序的读文件与
  算指标合成一条单调进度（读文件在前、指标在后）

### 优化
- **只从磁盘读需要的那一块**（`NcSource.plan_read_window`）。
  以前看一个小区域也要先把整幅全球场读进内存（4320x8640 解包后约 300 MB）
  再裁掉 98%；现在按区域 + 屏幕预算算出窗口与步长，只读那一片
  - 单张地图：**峰值内存 641 MB → 30 MB**，等距圆柱 4.5s → 0.5s
  - 时序构建：**1.58 秒/文件 → 0.10 秒/文件（16 倍）**，
    365 个文件从约 575 秒降到约 35 秒；数值与旧路径完全一致
- 时序面板的「用时序模式出图」开关参与 `PlotSpec` 收集，
  避免防抖重绘把时序结果覆盖回地图

### 文档
- 新增 **`时序分析使用指南.md`**：逐指标说明（是什么 / 怎么读 / 什么时候用）、
  36 个月合成数据的完整实战案例（真值 0.80 ℃/年 → 算得 0.711）、
  以及「季节信号会偷走趋势」这个最大的坑

---

## [0.6.1] - 2026-09-28

### 修复
- **多文件入口做对了**：用户反馈「还是只能打开一个 nc 文件」。
  能力其实做出来了，但入口没做对 —— 主菜单的「打开数据集」仍是单选对话框，
  多选藏在「时序分析」面板里，等于没做
  - 主菜单改为多选对话框，新增「打开文件夹（批量加入 nc）…」
  - 左侧面板顶部新增数据集列表：能看到加载了几个、单击切换、可移除/清空
  - 时序面板改为共用主窗口的数据集清单，不再各记一套
- 时序面板的 `runSeries` 信号没接上（`_wire_run_series` 在面板创建之前调用，
  `findChildren` 返回空），「计算并绘制」按钮点了没反应
- 时序图两处排版：统计表压住下方面板；纵轴范围被「色标」面板残留的
  vmin/vmax/对数轴带偏

---

## [0.6.0] - 2026-09-24

### 新增
- **色标外观系统**：6 种开箱可用样式（`clean` / `outline` / `framed` /
  `minimal` / `shadow` / `banded`）× 4 个位置（上下左右），
  另有宽度、间距、刻度数量与格式、越界三角、标注位置等细项
  - `ColorbarSpec` 可序列化，能进 YAML 配置
  - 默认样式换成 `clean`：无粗黑边框、细灰刻度、单位并入标注
  - 越界三角改为 `auto` —— 只在数据真的超出色标范围时才画，不再无脑加尖角
- **多文件时序分析**（`core/series.py`）：一次添加多个 nc 文件，自动拼成时间序列。
  时间轴三级兜底：文件内 `time` 变量 → **文件名中的日期**
  （`20180105` / `2018-01-05` / `.2018005.` 年积日 / `201803`）→ 样本序号
  - 区域平均默认按 cos(纬度) 面积加权（等距圆柱网格上不加权会系统性偏暖）
  - 空间统计：平均 / 中位数 / 最大 / 最小 / 标准差 / P90 / P10
  - 支持单点取值
- **14 个科学指标**（`core/indicators.py`），一键计算：
  - 基本统计：统计摘要、距平、累积距平、滑动平均
  - 趋势与检验：线性趋势（含 95% 置信区间与 p 值）、Mann-Kendall 检验、
    Sen's 斜率
  - 周期与相关：季节循环、去季节、功率谱（FFT）、自相关
  - 变率与极值：变率与有效自由度、逐月距平、极值/超阈值统计
- **时序诊断图**（`core/plot/series_plot.py`）：一张图里叠出原始序列 +
  趋势线 + 滑动平均 + 距平 + 季节循环 + 功率谱，并附统计量表与数据来源说明
- 新图型 `series` / `spectrum`；界面新增「时序分析」面板；
  命令行新增 `ncsight timeseries` 子命令

### 修复
- **趋势会被季节信号带偏**：造一条真值 +0.80 ℃/年、季节振幅 3 ℃ 的
  36 个月序列，直接拟合得到 1.25 ℃/年（**偏高 57%**）——
  因为样本里季节项的相位与时间项并不严格正交。现在线性趋势 / MK / Sen
  **默认先去季节**，回到 0.71。有回归测试守着
  （`test_不去季节会让趋势偏大`）

---

## [0.5.0] - 2026-09-24

### 新增
- 界面渲染全面提速：打开数据集到出图 **13.4 秒 → 0.9 秒**，
  期间界面不再冻结（实测主线程最长卡顿 0 ms）
  - `PlotSpec.screen_cells`：屏幕渲染按画布像素数降采样。
    全球 4320x8640（3732 万格点）光建网格就要 13.4 秒，
    降到 58 万格点只要 0.25 秒；而屏幕上根本画不出更细的细节
  - 渲染移入独立工作线程（`gui/render_worker.py`），主线程始终可交互；
    支持请求合并，连续拖参数不会堆积任务
  - 状态栏显示「正在渲染…」并切换忙碌光标
  - 导出图像时**自动按全分辨率重新渲染**，做到「屏幕快、导出真」
- `core/grid.py` 的降采样改为按步长精确逼近上限（原来按 2 的幂折半，
  目标 50 万格点时只用到 29% 的额度，白白丢细节；现在 >90%）

### 修复
- **色标范围可能显示成 0.0–1.0**：投影渲染路径用 `ax.collections[-1]`
  猜色标对象，底图叠加一旦也走 `add_collection`，最后一个 collection
  就变成海岸线，色标于是按 0~1 归一化。改为显式持有数据网格引用，
  并补了回归测试。（这个错误很隐蔽：图看着正常，只有色标数值是错的）
- 投影图的底图叠加不再用 cartopy 的 `coastlines()` / `add_feature` ——
  它的 FeatureArtist 在**每次绘制时**才投影几何体，占掉近一秒主线程卡顿；
  改为预读折线 + `LineCollection`（等距圆柱路径也一并优化）
- `prepare_field` 不再对折线/剖面这类 (1,N) 数据做降采样（会丢点）
- `style.apply_theme` 改为幂等：参数不变时不再改写全局 rcParams，
  避免工作线程与主线程争用

---

## [0.4.0] - 2026-09-23

### 新增
- **可双击运行的 Windows 可执行程序**（`NCSight.exe`）
  - 目录模式分发：`NCSight.exe` + `ncsight-cli.exe` + `_internal/`，
    结构与 Panoply 的「exe + jars」一致；终端用户不需要装 Python / conda
  - 离线底图随包分发（`_internal/cartopy_data/`），无网络也能画海岸线
  - 出图预设库随包分发
  - `scripts/build_exe.py`：一条命令完成「生成图标 → 打包 → 自动自检」
  - `NCSight.exe --selftest`：离屏验证 Qt 插件 / 离线底图 / 打开数据 / 出图 / 存盘
    整条链路，比人工双击试错可靠
  - `scripts/make_build_env.py`：创建打包专用最小 venv
    （避开日常环境里的 ML 依赖图，并用 OpenBLAS 版 numpy/scipy 替代 MKL，
    产物从约 970 MB 降到约 390 MB）
- `ncsight/_runtime.py`：冻结环境下的资源路径配置
  （cartopy 底图目录、matplotlib 可写缓存目录、用户数据目录降级）
- 应用图标 `NCSight.ico`，由 `scripts/make_icon.py` 用代码绘制（多尺寸 16–256）

### 修复
- 冻结环境下自检不退出：自检结束改用 `os._exit()` 强制终止，
  避免 Qt / 字体管理器残留线程把进程挂住导致打包脚本卡死
- 自检原本渲染全球全分辨率图，耗时数分钟易被误判为卡死；
  改为小区域快检，同时新增 `--selftest-timeout` 兜底

### 计划中
- 曲线网格（swath）的原生支持，接 `pyresample`
- 自定义色表编辑器
- EOF / 功率谱 / 趋势检验等时序分析
- 多图对比模式（上下分屏 / 差值图）
- 导出 KMZ 供 Google Earth 查看

---

## [0.3.0] - 2026-09-23

### 里程碑
M3 · 科研增强：补上 Panoply 最缺的掩膜、分析与批处理能力。

### 新增
- `core/mask.py` —— 掩膜子系统
  - `land_mask` / `ocean_mask`：基于 Natural Earth 陆地多边形抹掉陆地
  - `polygon_mask` / `shapefile_mask`：用任意多边形或 `.shp` 圈定研究区
  - `threshold_mask`：按数值区间过滤
  - `quality_mask`：用质量标记变量（如 `qual_sst`）过滤低质量像元
- `core/analyze.py` —— 分析算子
  - `Analyzer.composite`：沿任意维度做 mean/min/max/std/median 合成
  - `Analyzer.anomaly` / `anomaly_vs_mean`：距平（相对气候态或自身时间平均）
  - `Analyzer.cross_compare`：跨文件/跨变量对比
  - `Analyzer.vector_magnitude`：U/V 合成风速/流速
  - `Analyzer.region_mean_series` / `point_series`：区域平均时间序列
  - `smooth` / `gradient_magnitude`：高斯平滑与梯度强度（锋面检测）
- `core/export.py` —— 导出子系统
  - 图像：PNG / JPEG / TIFF / **PDF / SVG / EPS**（矢量，投稿用）
  - 数据：`export_grid_csv` / `export_grid_npz` / `export_labeled_text`
  - `export_overview`：整份数据集的结构说明
  - `copy_to_clipboard`：一键复制到剪贴板
- `core/animate.py` —— 沿任意维度导出动画（MP4 优先，无 ffmpeg 自动降级 GIF）
- `core/batch.py` —— 批量出图
  - 支持跨文件 / 跨变量 / 跨维度三种批量
  - 文件名模板占位符：`{stem} {var} {index} {dim} {dimval}`
  - 产出 `_batch_report.txt` 记录成功/失败/耗时
- GUI 新增「筛选与分析」面板、动画/批量/导出对话框
- GUI 新增四种画布交互模式：取值、框选缩放、平移、圈选区域

### 变更
- `PlotSpec` 新增掩膜相关字段（`mask_land` / `mask_polygon` /
  `mask_shapefile` / `mask_range` / `quality_var` / `quality_accept`）
- `OverlaySpec` 新增 `ocean` 图层开关

---

## [0.2.0] - 2026-09-23

### 里程碑
M2 · 白色简约图形界面：不写代码也能出图。

### 新增
- `gui/theme.py` —— 全局白色简约 QSS（与 matplotlib 主题共用同一套色值）
- `gui/icons.py` —— 全部用 QPainter 现画的矢量图标，仓库内**无二进制资源**
- `gui/main_window.py` —— 主窗口
  - 三栏布局：变量树 / 画布 / 可折叠控制面板
  - 完整中文菜单（文件 / 视图 / 绘图 / 分析 / 帮助）
  - 面板改动 → 防抖 120ms → 重渲染（拖滑块不打满 CPU）
  - 状态栏实时显示鼠标处的经纬度与数值
- `gui/plot_view.py` —— matplotlib 画布 + 四种交互模式
- `gui/panels/` —— 五个控制面板：数据 / 色标 / 地图 / 筛选分析 / 版式
- `gui/dialogs.py` —— 关于、导出图像、导出数据、动画、批量、进度对话框
- `config.py` —— 会话（Session）与用户偏好的保存/载入
- 命令行新增 `ncsight gui [数据集]`

### 变更
- 变量树按「可绘图类型」分组，并标出中文类型与形状
- 变量过滤三档：只显示可制图 / 只显示地理变量 / 显示全部

---

## [0.1.0] - 2026-09-23

### 里程碑
M1 · 最小可用内核与命令行：打通「读 nc → 出图 → 存文件」。

### 新增
- 工程骨架与版本管理：`version.py` 作为版本号唯一来源，
  语义化版本 + Keep a Changelog + git tag 三件套
- `core/detect.py` —— 变量与坐标轴识别（对应 Panoply 的 `NcVarTypeDetector`）
  - 单位/标准名/变量名三级容错，属性写得不规范也能识别
  - 判定 latitude/longitude/time/vertical 四种轴语义
  - 判定 10 种可绘图类型，并自动配对 U/V 矢量分量
- `core/reader.py` —— 数据读取（对应 `NcDataset` / `NcDataWrapper`）
  - **显式关闭 netCDF4 的自动解包**，手动走 packed 解包流程
  - 内嵌色表变量（如 OBPG 的 `palette`）自动排除出可制图清单
- `core/colormap.py` —— 色表子系统（对应 `graphics.clut`）
  - **OBPG 内嵌调色板自动去交错**（实测相邻色差降低约 23 倍）
  - 支持 `.cpt` / `.act` / `.rgb` / `.gct` 文件解析
  - 内置色表目录：cmocean / cmcrameri / matplotlib / ColorBrewer 共 70+
- `core/grid.py` —— 降采样、区域裁切、曲面网格重采样
  - **投影前自动降采样**（Cartopy 逐点投影的必需前置步骤）
- `core/overlay.py` —— 海岸线 / 国界 / 湖泊 / 河流 / Shapefile 叠加
- `core/plot/` —— 绘图内核
  - `base.py`：`PlotSpec` 完整可序列化规格 + 渲染调度
  - `map_plot.py` / `line_plot.py` / `hovmoller.py` / `section.py` / `vector.py`
- `style.py` —— matplotlib 白色简约主题 + 中文字体自动探测 + 期刊图幅预设
- `cli.py` —— 命令行：`info` / `plot` / `spec` / `animate` / `batch` /
  `export` / `gui` / `version` / `options`
  - 任意 `PlotSpec` 字段都可用 `--set key=value` 覆盖

### 修复
（首个版本，无）

### 已知限制
- 曲线网格（swath）暂只做直出，未走正式重采样
- `.cpt` 解析未支持带 alpha 通道的分段型
- 动画导出建议帧数控制在数百帧以内

---

[Unreleased]: https://example.invalid/ncsight/compare/v0.7.3...HEAD
[0.3.0]: https://example.invalid/ncsight/compare/v0.2.0...v0.3.0
[0.2.0]: https://example.invalid/ncsight/compare/v0.1.0...v0.2.0
[0.1.0]: https://example.invalid/ncsight/releases/tag/v0.1.0
