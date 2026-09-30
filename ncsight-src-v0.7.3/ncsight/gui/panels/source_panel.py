# -*- coding: utf-8 -*-
"""
左侧数据源面板
==============
对应 Panoply 的 Sources 窗口（变量树 + Info 面板）。

比 Panoply 多做的事：
  * 变量按「可绘图类型」分组显示，而不是一串平铺的英文名
  * 每个变量后面直接标出中文类型与形状，扫一眼就知道能画成什么
  * 双击变量 = 出图（Panoply 是选中后点工具栏按钮）
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ...core.detect import VarKind
from ..theme import UI
from .base import label, scrollable

# 分组标题（按 VarKind 归类），顺序即显示顺序
GROUP_ORDER = [
    (VarKind.LONLAT_FIELD, "全球/区域场（可制地图）"),
    (VarKind.VECTOR_2D, "矢量场（风/流）"),
    (VarKind.LATTIME, "Hovmöller · 纬度-时间"),
    (VarKind.LONTIME, "Hovmöller · 经度-时间"),
    (VarKind.LATVERT, "剖面 · 纬度-深度"),
    (VarKind.LONVERT, "剖面 · 经度-深度"),
    (VarKind.TIMESERIES, "时间序列"),
    (VarKind.PROFILE_1D, "垂向廓线"),
    (VarKind.LINE_1D, "一维曲线"),
    (VarKind.UNKNOWN, "其他"),
]

FILTERS = [
    ("plottable", "只显示可制图变量"),
    ("geo", "只显示地理变量"),
    ("all", "显示全部变量"),
]


class SourcePanel(QWidget):
    """数据集列表 + 变量树 + 属性信息。"""

    variableSelected = Signal(str)
    plotRequested = Signal(str)

    #: 用户点了「打开 nc 文件…」/「打开文件夹…」—— 由主窗口弹对话框
    openFilesRequested = Signal()
    openDirRequested = Signal()
    #: 用户双击/单击了某个数据集，要把它切成当前激活的
    datasetActivated = Signal(str)
    #: 要移除某些数据集（传路径列表；空列表 = 清空全部）
    datasetsRemoved = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = None
        self._items: Dict[str, QTreeWidgetItem] = {}
        self._datasets: List[str] = []
        self._active = ""
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 标题
        head = QWidget()
        hl = QVBoxLayout(head)
        hl.setContentsMargins(12, 10, 12, 8)
        hl.setSpacing(6)
        self.title_label = QLabel("未打开数据集")
        self.title_label.setStyleSheet(
            "font-size:13px;color:%s;font-weight:500;" % UI["text"])
        self.title_label.setWordWrap(True)
        hl.addWidget(self.title_label)
        self.meta_label = label("")
        self.meta_label.setWordWrap(True)
        hl.addWidget(self.meta_label)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("筛选变量…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._refresh)
        bar.addWidget(self.filter_edit, 1)
        hl.addLayout(bar)

        self.filter_combo = QComboBox()
        for key, text in FILTERS:
            self.filter_combo.addItem(text, key)
        self.filter_combo.currentIndexChanged.connect(self._refresh)
        hl.addWidget(self.filter_combo)

        lay.addWidget(head)

        # ------------------------------------------------------------------
        # 数据集列表（多文件）
        # ------------------------------------------------------------------
        # 批量分析的第一入口。放在变量树**上方**，因为「我加载了哪几个文件」
        # 是比「有哪些变量」更上位的信息。
        ds_box = QWidget()
        dl = QVBoxLayout(ds_box)
        dl.setContentsMargins(12, 0, 12, 8)
        dl.setSpacing(5)

        self.ds_title = QLabel("数据集（0）")
        self.ds_title.setStyleSheet(
            "font-size:11.5px;color:%s;font-weight:600;" % UI["text"])
        dl.addWidget(self.ds_title)

        row = QHBoxLayout()
        row.setSpacing(5)
        self.btn_add_files = QPushButton("＋ 打开 nc 文件…")
        self.btn_add_files.setToolTip("可按住 Ctrl / Shift 一次选中多个文件")
        self.btn_add_files.clicked.connect(self.openFilesRequested.emit)
        row.addWidget(self.btn_add_files, 1)
        self.btn_add_dir = QPushButton("文件夹…")
        self.btn_add_dir.setToolTip("把一个目录下所有 .nc / .nc4 一次性加进来")
        self.btn_add_dir.clicked.connect(self.openDirRequested.emit)
        row.addWidget(self.btn_add_dir)
        dl.addLayout(row)

        self.ds_list = QListWidget()
        self.ds_list.setMaximumHeight(108)
        self.ds_list.setToolTip("单击切换当前数据集；双击变量列表里的变量即出图")
        self.ds_list.itemClicked.connect(self._on_dataset_clicked)
        self.ds_list.setStyleSheet(
            "QListWidget{border:1px solid %s;border-radius:5px;background:%s;"
            "font-size:11.5px;}" % (UI["border"], UI["panel"]))
        dl.addWidget(self.ds_list)

        row2 = QHBoxLayout()
        row2.setSpacing(5)
        self.btn_remove = QPushButton("移除选中")
        self.btn_remove.clicked.connect(self._remove_selected)
        row2.addWidget(self.btn_remove)
        self.btn_clear_ds = QPushButton("清空")
        self.btn_clear_ds.clicked.connect(lambda: self.datasetsRemoved.emit([]))
        row2.addWidget(self.btn_clear_ds)
        self.ds_hint = QLabel("")
        self.ds_hint.setStyleSheet("font-size:10.5px;color:%s;"
                                  % UI.get("text_muted", UI.get("muted", "#6b7280")))
        self.ds_hint.setWordWrap(True)
        row2.addWidget(self.ds_hint, 1)
        dl.addLayout(row2)

        lay.addWidget(ds_box)

        # 变量树
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAlternatingRowColors(False)
        self.tree.setIndentation(12)
        self.tree.setUniformRowHeights(True)
        self.tree.itemSelectionChanged.connect(self._on_selection)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setStyleSheet(
            "QTreeWidget{border:none;border-top:1px solid %s;"
            "border-bottom:1px solid %s;background:%s;}"
            % (UI["border"], UI["border"], UI["window"]))
        lay.addWidget(self.tree, 1)

        # 信息区
        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setPlaceholderText("选中变量后这里显示它的维度、单位、属性……")
        self.info.setStyleSheet(
            "QPlainTextEdit{border:none;border-top:1px solid %s;background:%s;"
            "font-family:Consolas,'Cascadia Mono',monospace;font-size:11.5px;"
            "color:%s;padding:8px;}" % (UI["border"], UI["panel"], UI["text"]))
        self.info.setMinimumHeight(160)
        lay.addWidget(self.info)

    # ------------------------------------------------------------------
    # 数据集列表（多文件）—— 主窗口是唯一的数据持有者，这里只负责显示
    # ------------------------------------------------------------------
    def set_datasets(self, paths, active: str = "") -> None:
        """刷新数据集列表。paths 由主窗口给出，面板不自己维护副本。"""
        self._datasets = list(paths or [])
        self._active = active or (self._datasets[0] if self._datasets else "")
        self.ds_list.clear()
        for p in self._datasets:
            import os
            it = QListWidgetItem(os.path.basename(p))
            it.setToolTip(p)
            if p == self._active:
                it.setText("● " + it.text())
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            self.ds_list.addItem(it)
        n = len(self._datasets)
        self.ds_title.setText("数据集（%d）" % n)
        if n == 0:
            self.ds_hint.setText("可一次选多个文件")
        elif n == 1:
            self.ds_hint.setText("再加几个就能做时序分析")
        else:
            self.ds_hint.setText("已可批量分析")

    def datasets(self) -> List[str]:
        return list(self._datasets)

    def active_dataset(self) -> str:
        return self._active

    def _on_dataset_clicked(self, item: QListWidgetItem) -> None:
        row = self.ds_list.row(item)
        if 0 <= row < len(self._datasets):
            self.datasetActivated.emit(self._datasets[row])

    def _remove_selected(self) -> None:
        rows = sorted({self.ds_list.row(i) for i in self.ds_list.selectedItems()},
                      reverse=True)
        if not rows:
            self.datasetsRemoved.emit([] if not self._datasets else [])
            return
        # 全部选中 = 清空
        if len(rows) == len(self._datasets):
            self.datasetsRemoved.emit([])
            return
        self.datasetsRemoved.emit([self._datasets[r] for r in rows])

    # ------------------------------------------------------------------
    # 数据源
    # ------------------------------------------------------------------
    def set_source(self, source) -> None:
        self._source = source
        self._items.clear()
        self.tree.clear()
        self.info.clear()

        if source is None:
            self.title_label.setText("未打开数据集")
            self.meta_label.setText("")
            return

        import os
        self.title_label.setText(os.path.basename(source.path))
        self.title_label.setToolTip(source.path)
        t = source.title
        geo = "地理" if source.axis_by_role is not None else ""
        self.meta_label.setText(
            "%s\n%s · %d 个变量（可制图 %d）"
            % (t if t and t != os.path.basename(source.path) else "",
               source.data_model, len(source.variables), len(source.plottable())))
        self._refresh()

    def current_variable(self) -> Optional[str]:
        items = self.tree.selectedItems()
        while items:
            it = items[0]
            name = it.data(0, Qt.UserRole)
            if name:
                return name
            items = self.tree.selectedItems() or []
            break
        return None

    # ------------------------------------------------------------------
    # 树构建
    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        if self._source is None:
            return
        self.tree.clear()
        self._items.clear()

        text = self.filter_edit.text().strip().lower()
        mode = self.filter_combo.currentData() or "plottable"

        src = self._source
        if mode == "all":
            varlist = list(src.variables.values())
        elif mode == "geo":
            varlist = [v for v in src.variables.values()
                       if v.kind in (VarKind.LONLAT_FIELD, VarKind.LATTIME,
                                     VarKind.LONTIME, VarKind.LATVERT, VarKind.LONVERT)]
        else:
            varlist = src.plottable()

        groups: Dict[VarKind, List] = {}
        for v in varlist:
            if text and text not in v.name.lower() and text not in v.label.lower():
                continue
            groups.setdefault(v.kind, []).append(v)

        for kind, gname in GROUP_ORDER:
            items = groups.get(kind)
            if not items:
                continue
            top = QTreeWidgetItem(self.tree, [gname])
            top.setFlags(Qt.ItemIsEnabled)
            top.setForeground(0, self.tree.palette().mid())
            f = top.font(0)
            f.setPointSizeF(max(7.5, f.pointSizeF() - 1.0))
            top.setFont(0, f)
            for v in sorted(items, key=lambda x: x.name):
                child = QTreeWidgetItem(top, [self._item_text(v)])
                child.setData(0, Qt.UserRole, v.name)
                child.setToolTip(0, self._tooltip(v))
                self._items[v.name] = child
            top.setExpanded(True)

        if not self._items:
            placeholder = QTreeWidgetItem(self.tree, ["没有匹配的变量"])
            placeholder.setFlags(Qt.ItemIsEnabled)

    def _item_text(self, v) -> str:
        shape = "×".join(str(s) for s in v.shape)
        caption = v.label
        if len(caption) > 26:
            caption = caption[:25] + "…"
        return "%s\n%s" % (v.name, "%s  %s" % (caption, shape))

    def _tooltip(self, v) -> str:
        lines = ["变量：%s" % v.name, "名称：%s" % v.label,
                 "类型：%s" % v.kind.value, "形状：%s" % (v.shape,)]
        if v.units:
            lines.append("单位：%s" % v.units)
        lines.append("可画：%s" % ", ".join(v.plot_options))
        if v.vector_partner:
            lines.append("矢量配对：%s" % v.vector_partner)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    def _on_selection(self) -> None:
        name = None
        for it in self.tree.selectedItems():
            n = it.data(0, Qt.UserRole)
            if n:
                name = n
                break
        if name is None:
            return
        self.variableSelected.emit(name)
        if self._source is not None:
            self.info.setPlainText(self._source.describe_text(name))

    def _on_double_click(self, item, _col) -> None:
        name = item.data(0, Qt.UserRole)
        if name:
            self.plotRequested.emit(name)

    def select_variable(self, name: str) -> None:
        it = self._items.get(name)
        if it is not None:
            self.tree.setCurrentItem(it)
            self.tree.scrollToItem(it)
