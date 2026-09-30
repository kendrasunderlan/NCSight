# -*- coding: utf-8 -*-
"""
PyInstaller 打包配置（目录模式）
==============================
产出结构与 Panoply 的「exe + jars 文件夹」是同一个思路：

    dist/NCSight/
    ├── NCSight.exe            ← 双击这个（图形界面，无控制台窗口）
    ├── ncsight-cli.exe        ← 命令行版（批量出图用）
    └── _internal/             ← 所有依赖、底图、预设，不要删
        ├── cartopy_data/      ← 离线底图（Natural Earth 110m/50m/10m）
        ├── ncsight/presets/   ← 出图预设
        └── ...                ← Python 运行时、PySide6、matplotlib 等

**为什么用目录模式而不是单文件（onefile）**：
单文件每次启动都要把几百 MB 解压到临时目录，冷启动要十几秒，且容易被
杀软反复扫描。目录模式启动快得多，也便于用户自行替换底图/预设。
这也是 Panoply 的做法。

用法：
    pyinstaller --clean --noconfirm ncsight.spec
或者直接跑 scripts/build_exe.py（会顺带生成图标并做启动自检）。
"""

import glob
import os
import sys

from PyInstaller.utils.hooks import collect_data_files

# PyInstaller 是用 exec() 执行 spec 的，没有 __file__。
# 它自己会注入 SPECPATH（spec 文件所在目录），用它；顺便兜个底。
ROOT = globals().get("SPECPATH") or os.path.dirname(os.path.abspath(
    globals().get("__file__", ".")))

# ----------------------------------------------------------------------
# 0) 补齐解释器自带的运行库 DLL（★ 踩过的坑 ★）
# ----------------------------------------------------------------------
# conda 系解释器的布局比较特殊：
#     _ctypes.pyd         放在 <env>/DLLs/
#     它依赖的 ffi-8.dll  放在 <env>/Library/bin/
# PyInstaller 分析 _ctypes.pyd 的导入表去找 ffi-8.dll 时找不到，于是不打进包，
# 结果 exe 一启动就报：
#     ImportError: DLL load failed while importing _ctypes: 找不到指定的模块。
# 这个错误发生在 PyInstaller 自己的启动钩子里，表现为程序「静默卡住」，
# 非常难定位。这里显式把这些运行库带上。
_EXTRA_DLL_PATTERNS = ("ffi*.dll", "libffi*.dll",
                       "vcruntime14*.dll", "msvcp14*.dll")

_DLL_DIRS = [
    os.path.join(sys.base_prefix, "Library", "bin"),
    os.path.join(sys.base_prefix, "DLLs"),
    os.path.join(os.path.dirname(sys.base_prefix), "DLLs"),
    os.path.dirname(sys.base_prefix),          # 例如 D:\Anaconda_new\DLLs
]

_extra_binaries = []
for _d in _DLL_DIRS:
    if not os.path.isdir(_d):
        continue
    for _pat in _EXTRA_DLL_PATTERNS:
        for _p in glob.glob(os.path.join(_d, _pat)):
            item = (_p, ".")
            if item not in _extra_binaries:
                _extra_binaries.append(item)
            print("[spec] 补入运行库 DLL：%s" % os.path.basename(_p))

if not any("ffi" in os.path.basename(p).lower() for p, _ in _extra_binaries):
    print("[spec] ⚠ 没找到 ffi*.dll —— 打出来的 exe 很可能报 _ctypes 加载失败！")
    print("       请确认解释器来自 conda，并检查 <env>/Library/bin 是否存在")


# ----------------------------------------------------------------------
# 1) 随包分发的数据
# ----------------------------------------------------------------------
datas = []

# cartopy 离线底图：从用户缓存里取，拷进包的 cartopy_data/shapefiles
_cartopy_src = os.environ.get(
    "CARTOPY_SHAPEFILES",
    os.path.join(os.path.expanduser("~"), ".local", "share", "cartopy"))
if os.path.isdir(os.path.join(_cartopy_src, "shapefiles")):
    datas.append((os.path.join(_cartopy_src, "shapefiles"), "cartopy_data/shapefiles"))
    print("[spec] 打包 cartopy 底图：%s" % _cartopy_src)
else:
    print("[spec] 警告：没找到 cartopy 底图缓存，打出来的包首次绘图需要联网")
    print("       缓存位置应为：%s" % os.path.join(_cartopy_src, "shapefiles"))

# 出图预设库
_presets = os.path.join(ROOT, "ncsight", "presets")
if os.path.isdir(_presets):
    datas.append((_presets, "ncsight/presets"))

# 第三方库自带的数据
for pkg in ("cartopy", "cmocean", "cmcrameri", "pyproj", "netCDF4", "cftime"):
    try:
        datas += collect_data_files(pkg)
    except Exception as exc:                            # noqa: BLE001
        print("[spec] collect_data_files(%s) 跳过：%s" % (pkg, exc))

# ----------------------------------------------------------------------
# 2) 隐式导入（PyInstaller 静态分析抓不到的）
# ----------------------------------------------------------------------
hiddenimports = [
    "shapefile",   # pyshp：读 Natural Earth，避免在渲染线程里创建 pyproj CRS
    
    # 界面
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "PySide6.QtSvg",
    "PySide6.QtSvgWidgets", "PySide6.QtPrintSupport",
    # matplotlib 的 Qt 后端与我们要用的输出格式
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_qt",
    "matplotlib.backends.backend_agg",
    "matplotlib.backends.backend_pdf",
    "matplotlib.backends.backend_svg",
    # 地图
    "cartopy.crs", "cartopy.feature", "cartopy.io.shapereader",
    "cartopy.mpl.geoaxes", "cartopy.mpl.ticker",
    "shapely", "shapely.geometry", "shapely.ops", "shapely.prepared",
    "pyproj", "pyproj.crs", "pyproj.database",
    # 数据
    "netCDF4", "cftime",
    # 科学计算（只用到 ndimage / interpolate / spatial）
    "scipy", "scipy.ndimage", "scipy.interpolate", "scipy.spatial",
    # 其他
    "yaml", "PIL", "PIL.Image", "numpy", "encodings.idna",
    "cmocean", "cmcrameri", "cmcrameri.cm",
]

# ----------------------------------------------------------------------
# 3) 排除不需要的东西
# ----------------------------------------------------------------------
# 背景：这台机器的 conda 环境（py39gpu）里装了整套机器学习栈。
# PyInstaller 顺着依赖图会把 torch / opencv / spacy / transformers /
# sklearn / fastai 之类全部扫进来 —— 实测光是分析阶段就跑了 10 分钟还没完，
# 打出来的包也会膨胀到几个 GB，而这些**一行都用不到**。
#
# 这里显式把它们挡掉。NCSight 的运行时依赖只有：
#   numpy / matplotlib / PySide6 / netCDF4 / cartopy / shapely / pyproj /
#   scipy / pillow / pyyaml / cmocean / cmcrameri / cftime
# 只要这些在，功能就是完整的。
#
# ⚠ 排除的模块如果被**无条件 import**，运行时会 ImportError。
#    所以每次改完 excludes，务必跑一遍 `NCSight.exe --selftest` 验证。
_ML_STACK = [
    "torch", "torchvision", "torchaudio", "torchtext", "torchgen",
    "timm", "fastai", "fastprogress", "fastcore",
    "sklearn", "scikit-learn", "lightgbm", "xgboost", "catboost",
    "transformers", "tokenizers", "datasets", "huggingface_hub", "safetensors",
    "cv2", "onnx", "onnxruntime",
    "tensorflow", "keras", "jax", "jaxlib",
    "numba", "llvmlite",
    "nltk", "spacy", "thinc", "srsly", "langcodes", "catalogue",
    "confection", "wasabi", "preshed", "cymem", "murmurhash", "blis",
    "gensim", "wordcloud", "textblob",
    "statsmodels", "patsy", "sympy",
    "pdfminer", "pypdfium2", "PyPDF2", "pdfplumber", "fitz", "pymupdf",
    "pygame", "moviepy", "imageio_ffmpeg",
    "paperscraper", "unstructured", "nougat", "marker", "layoutparser",
    "praw", "newspaper", "feedparser", "bs4", "beautifulsoup4",
]

_WEB_STACK = [
    "bokeh", "panel", "holoviews", "datashader", "plotly", "kaleido",
    "dash", "streamlit", "flask", "django", "tornado", "aiohttp",
    "google", "googleapiclient", "grpc", "proto", "protobuf",
    "mako", "jinja2", "markupsafe",
]

_UNUSED_SCIENTIFIC = [
    # 本工程不使用（已 grep 确认无 import），但环境里装着，属于纯体积负担
    "pandas", "xarray", "dask", "distributed", "partd",
    "numexpr", "bottleneck", "tables", "h5netcdf",
    "networkx", "igraph", "pyarrow",
]

_DEV_AND_GUI_EXTRA = [
    # 别的 Qt 绑定 —— 只留 PySide6
    "PyQt5", "PyQt6", "PySide2", "qtpy",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml",
    "PySide6.QtMultimedia", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtNetworkAuth",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSerialPort",
    "PySide6.QtRemoteObjects", "PySide6.QtSensors", "PySide6.QtTest",
    # matplotlib 用不到的交互后端
    "matplotlib.backends.backend_tkagg",
    "matplotlib.backends.backend_wx",
    "matplotlib.backends.backend_gtk3",
    "matplotlib.backends.backend_webagg",
    # 开发工具
    "IPython", "jupyter", "jupyterlab", "notebook", "nbformat", "nbconvert",
    "pytest", "_pytest", "sphinx", "docutils", "pydoc_data",
    "tkinter", "_tkinter", "Tkinter",
    "sqlite3", "test", "lib2to3",
    # 各库自带的测试数据
    "cartopy.tests", "shapely.tests", "matplotlib.tests", "numpy.tests",
    "scipy.tests", "netCDF4.tests", "PIL.tests",
]

excludes = sorted(set(_ML_STACK + _WEB_STACK + _UNUSED_SCIENTIFIC
                      + _DEV_AND_GUI_EXTRA))

# ----------------------------------------------------------------------
# 4) 分析
# ----------------------------------------------------------------------
COMMON = dict(
    pathex=[ROOT],
    binaries=_extra_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

a_gui = Analysis([os.path.join(ROOT, "packaging", "gui_entry.py")], **COMMON)
a_cli = Analysis([os.path.join(ROOT, "packaging", "cli_entry.py")], **COMMON)

pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data)
pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data)

ICON = os.path.join(ROOT, "NCSight.ico")
if not os.path.exists(ICON):
    ICON = None

exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name="NCSight",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                 # 双击运行时不弹黑窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name="ncsight-cli",
    debug=False,
    strip=False,
    upx=False,
    console=True,                  # 命令行版保留控制台以显示进度
    icon=ICON,
)

# 两个 exe 共享同一份 _internal（PyInstaller 的 COLLECT 会自动去重）
coll = COLLECT(
    exe_gui,
    exe_cli,
    a_gui.binaries,
    a_gui.datas,
    a_cli.binaries,
    a_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NCSight",
)
