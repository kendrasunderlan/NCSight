# -*- coding: utf-8 -*-
"""
Qt 界面主题：简约白色风格
========================
与 matplotlib 主题（ncsight.style）共用同一套色值，保证「界面」和「出的图」
观感一致 —— 这是成品软件和实验脚本的差别所在。

设计准则：
  * 白底、浅灰分隔、单一强调色（蓝）
  * 无渐变、无阴影、无圆角滥用；只用 1px 细线与 4-6px 圆角
  * 字号克制（9pt 正文 / 10pt 标题），行距舒展
  * 所有控件在 hover / focus 时有明确但轻微的状态反馈
"""

from __future__ import annotations

from ..style import UI, COLORS


#: 界面字体候选（按优先级）。与 matplotlib 的候选表保持一致的思路：
#: 中文字体必须显式指定，否则 Qt 会退回到不含 CJK 字形的默认字体，
#: 表现就是满屏方框（□□□）。这在离屏 / 容器环境里尤其容易踩到。
UI_FONT_CANDIDATES = [
    "Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑",
    "Source Han Sans SC", "Noto Sans CJK SC", "Noto Sans SC",
    "PingFang SC", "Hiragino Sans GB",
    "SimHei", "黑体",
    "WenQuanYi Micro Hei", "DengXian",
    "Segoe UI",
]


def resolve_ui_font() -> str:
    """挑一个本机真实存在的中文字体名。找不到就退回逻辑字体名。"""
    try:
        from PySide6.QtGui import QFontDatabase
        families = set(QFontDatabase.families())
        for name in UI_FONT_CANDIDATES:
            if name in families:
                return name
    except Exception:                                   # noqa: BLE001
        pass
    return "Microsoft YaHei"


def build_stylesheet(font_family: str = None) -> str:
    """生成全局 QSS。font_family 由 resolve_ui_font() 决定。"""
    fam = font_family or resolve_ui_font()
    return f"""
/* ---------- 基础 ---------- */
QWidget {{
    background: {UI['window']};
    color: {UI['text']};
    font-family: "{fam}";
    font-size: 13px;
}}
QMainWindow::separator {{ background: {UI['border']}; width: 1px; height: 1px; }}

/* ---------- 菜单栏 ---------- */
QMenuBar {{
    background: {UI['window']};
    border-bottom: 1px solid {UI['border']};
    padding: 1px 4px;
}}
QMenuBar::item {{ padding: 5px 10px; background: transparent; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {UI['accent_soft']}; color: {UI['accent']}; }}
QMenu {{
    background: {UI['window']};
    border: 1px solid {UI['border_strong']};
    border-radius: 6px;
    padding: 5px;
}}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {UI['accent_soft']}; color: {UI['accent']}; }}
QMenu::item:disabled {{ color: {UI['text_muted']}; }}
QMenu::separator {{ height: 1px; background: {UI['border']}; margin: 4px 8px; }}

/* ---------- 工具栏 ---------- */
QToolBar {{
    background: {UI['window']};
    border-bottom: 1px solid {UI['border']};
    padding: 5px 8px;
    spacing: 4px;
}}
QToolBar::separator {{ background: {UI['border']}; width: 1px; margin: 4px 6px; }}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 5px 9px;
    color: {UI['text']};
}}
QToolButton:hover {{ background: {UI['accent_soft']}; border-color: #dbeafe; }}
QToolButton:pressed {{ background: #dbeafe; }}
QToolButton:checked {{ background: {UI['accent_soft']}; border-color: #bfdbfe;
                       color: {UI['accent']}; }}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: {UI['window']};
    border: 1px solid {UI['border_strong']};
    border-radius: 5px;
    padding: 5px 14px;
    min-height: 22px;
    color: {UI['text']};
}}
QPushButton:hover {{ background: #f8fafc; border-color: #a1a1aa; }}
QPushButton:pressed {{ background: #f1f5f9; }}
QPushButton:disabled {{ color: #a1a1aa; background: #fafafa; border-color: {UI['border']}; }}
QPushButton[primary="true"] {{
    background: {UI['accent']}; color: #ffffff; border-color: {UI['accent']};
}}
QPushButton[primary="true"]:hover {{ background: {UI['accent_hover']}; }}
QPushButton[flat="true"] {{ border: none; padding: 4px 8px; }}
QPushButton[flat="true"]:hover {{ background: #f4f4f5; }}

/* ---------- 输入控件 ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {UI['window']};
    border: 1px solid {UI['border_strong']};
    border-radius: 5px;
    padding: 4px 8px;
    min-height: 20px;
    selection-background-color: {UI['accent']};
    selection-color: #ffffff;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {UI['accent']};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background: #fafafa; color: #a1a1aa;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{ width: 15px; border: none;
    background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ width: 7px; height: 7px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ width: 7px; height: 7px; }}

QComboBox {{
    background: {UI['window']};
    border: 1px solid {UI['border_strong']};
    border-radius: 5px;
    padding: 4px 8px;
    min-height: 20px;
}}
QComboBox:hover {{ border-color: #a1a1aa; }}
QComboBox:focus {{ border-color: {UI['accent']}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {UI['window']};
    border: 1px solid {UI['border_strong']};
    border-radius: 6px;
    padding: 4px;
    selection-background-color: {UI['accent_soft']};
    selection-color: {UI['accent']};
    outline: none;
}}

QCheckBox, QRadioButton {{ spacing: 7px; padding: 2px 0; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {UI['border_strong']};
    background: {UI['window']};
}}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: 7px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {UI['accent']}; }}
QCheckBox::indicator:checked {{ background: {UI['accent']}; border-color: {UI['accent']};
    image: none; }}
QRadioButton::indicator:checked {{ background: {UI['accent']}; border-color: {UI['accent']};
    border-width: 4px; }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background: #f4f4f5; border-color: {UI['border']}; }}

/* ---------- 滑块 ---------- */
QSlider::groove:horizontal {{
    height: 3px; background: {UI['border_strong']}; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background: {UI['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {UI['window']}; border: 2px solid {UI['accent']};
    width: 11px; height: 11px; margin: -5px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: {UI['accent_soft']}; }}

/* ---------- 分组框 ---------- */
QGroupBox {{
    border: 1px solid {UI['border']};
    border-radius: 6px;
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
    background: {UI['window']};
    font-weight: normal;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: {UI['text_muted']};
    font-size: 12px;
}}

/* ---------- 树 / 列表 / 表格 ---------- */
QTreeWidget, QTreeView, QListWidget, QListView, QTableWidget, QTableView {{
    background: {UI['window']};
    border: 1px solid {UI['border']};
    border-radius: 6px;
    outline: none;
    alternate-background-color: #fcfcfd;
}}
QTreeWidget::item, QListView::item, QTableView::item {{ padding: 3px 4px; border: none; }}
QTreeWidget::item:hover, QListView::item:hover {{ background: #f4f4f5; }}
QTreeWidget::item:selected, QListView::item:selected, QTableView::item:selected {{
    background: {UI['accent_soft']}; color: {UI['accent']};
}}
QTreeWidget::branch {{ background: transparent; }}
QHeaderView::section {{
    background: {UI['panel_alt']};
    color: {UI['text_muted']};
    border: none;
    border-bottom: 1px solid {UI['border']};
    border-right: 1px solid {UI['border']};
    padding: 5px 7px;
    font-size: 12px;
}}
QHeaderView::section:last {{ border-right: none; }}

/* ---------- 标签页 ---------- */
QTabWidget::pane {{ border: none; background: {UI['window']}; }}
QTabBar::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 7px 14px;
    color: {UI['text_muted']};
}}
QTabBar::tab:hover {{ color: {UI['text']}; }}
QTabBar::tab:selected {{ color: {UI['accent']}; border-bottom-color: {UI['accent']}; }}

/* ---------- 滚动条 ---------- */
QScrollArea {{ border: none; background: {UI['window']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: #d4d4d8; border-radius: 5px; min-height: 28px; margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: #a1a1aa; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: #d4d4d8; border-radius: 5px; min-width: 28px; margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{ background: #a1a1aa; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- 分隔条 ---------- */
QSplitter::handle {{ background: {UI['border']}; width: 1px; height: 1px; }}
QSplitter::handle:hover {{ background: {UI['border_strong']}; }}

/* ---------- 状态栏 ---------- */
QStatusBar {{
    background: {UI['window']};
    border-top: 1px solid {UI['border']};
    color: {UI['text_muted']};
    font-size: 12px;
}}
QStatusBar::item {{ border: none; }}

/* ---------- 对话框 ---------- */
QDialog {{ background: {UI['window']}; }}
QDialogButtonBox QPushButton {{ min-width: 72px; }}

/* ---------- 提示 ---------- */
QToolTip {{
    background: #1f2937; color: #f9fafb; border: none;
    border-radius: 4px; padding: 5px 8px; font-size: 12px;
}}

/* ---------- 进度条 ---------- */
QProgressBar {{
    border: 1px solid {UI['border']}; border-radius: 5px;
    background: {UI['panel_alt']}; text-align: center; height: 18px;
    font-size: 12px; color: {UI['text_muted']};
}}
QProgressBar::chunk {{ background: {UI['accent']}; border-radius: 4px; }}
"""


# 侧栏分组标题样式（用在自绘的折叠面板上）
SECTION_TITLE_QSS = f"""
QToolButton {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {UI['border']};
    padding: 8px 10px;
    text-align: left;
    font-size: 12.5px;
    color: {UI['text']};
}}
QToolButton:hover {{ background: #f8fafc; }}
"""

PANEL_QSS = f"""
QWidget#Panel {{
    background: {UI['panel']};
    border-left: 1px solid {UI['border']};
}}
QWidget#PanelBody {{ background: {UI['panel']}; }}
"""

CHIP_LABEL_QSS = f"""
QLabel[chip="true"] {{
    background: {UI['accent_soft']};
    color: {UI['accent']};
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 11.5px;
}}
QLabel[muted="true"] {{ color: {UI['text_muted']}; font-size: 12px; }}
"""
