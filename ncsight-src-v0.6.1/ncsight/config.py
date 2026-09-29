# -*- coding: utf-8 -*-
"""
工程文件（Session）与配置读写
============================
对应 Panoply 的 `PanSavedSettings` / `PanPrefsSaverTask`。

概念区分：
  * PlotSpec    —— 「**一张图**」的完整描述，可独立存成 .yaml
  * Session     —— 「**一次工作**」的完整描述：打开了哪个数据集 + 一堆 PlotSpec
                   GUI 的「保存会话 / 打开会话」就是它

所有文件都是纯文本 YAML，天然适合放进 git 做版本管理，
出图参数可以跟论文一起被追溯。
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .version import __version__
from .core.plot.base import PlotSpec

SESSION_EXT = ".ncs.yaml"
SPEC_EXT = ".plot.yaml"


# --------------------------------------------------------------------------
# 单张图的配置
# --------------------------------------------------------------------------
def save_spec(spec: PlotSpec, path: str) -> str:
    if not path.lower().endswith((".yaml", ".yml", ".json")):
        path += SPEC_EXT
    return spec.save(path)


def load_spec(path: str) -> PlotSpec:
    return PlotSpec.load(path)


# --------------------------------------------------------------------------
# 整个会话
# --------------------------------------------------------------------------
@dataclass
class Session:
    """一次工作现场：一个数据集 + 若干张图的规格。"""

    dataset: str = ""
    plots: List[PlotSpec] = field(default_factory=list)
    active: int = 0
    created: str = ""
    app_version: str = __version__
    notes: str = ""

    # ---- 便捷构造 ----
    @classmethod
    def create(cls, dataset: str = "", **kw) -> "Session":
        return cls(dataset=dataset,
                   created=_dt.datetime.now().isoformat(timespec="seconds"), **kw)

    def add(self, spec: PlotSpec, make_active: bool = True) -> int:
        self.plots.append(spec)
        if make_active:
            self.active = len(self.plots) - 1
        return len(self.plots) - 1

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.plots):
            self.plots.pop(index)
            self.active = min(self.active, max(0, len(self.plots) - 1))

    def current(self) -> Optional[PlotSpec]:
        if 0 <= self.active < len(self.plots):
            return self.plots[self.active]
        return None

    # ---- 序列化 ----
    def to_dict(self) -> Dict[str, Any]:
        return {
            "ncsight_session": True,
            "app_version": self.app_version,
            "created": self.created,
            "saved": _dt.datetime.now().isoformat(timespec="seconds"),
            "dataset": self.dataset,
            "active": self.active,
            "notes": self.notes,
            "plots": [p.to_dict() for p in self.plots],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Session":
        plots = [PlotSpec.from_dict(x) for x in (d.get("plots") or [])]
        return cls(
            dataset=d.get("dataset", ""),
            plots=plots,
            active=int(d.get("active", 0) or 0),
            created=d.get("created", ""),
            app_version=d.get("app_version", __version__),
            notes=d.get("notes", ""),
        )

    def save(self, path: str) -> str:
        if not path.lower().endswith((".yaml", ".yml", ".json")):
            path += SESSION_EXT
        import json
        data = self.to_dict()
        try:
            import yaml
            text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                                  default_flow_style=False)
        except Exception:                               # noqa: BLE001
            text = json.dumps(data, ensure_ascii=False, indent=2)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    @classmethod
    def load(cls, path: str) -> "Session":
        import json
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            import yaml
            data = yaml.safe_load(text) or {}
        return cls.from_dict(data)


# --------------------------------------------------------------------------
# 用户偏好（跨会话保留）
# --------------------------------------------------------------------------
DEFAULT_PREFS: Dict[str, Any] = {
    "last_dir": "",
    "preset": "double",
    "fontsize": 9.0,
    "dpi": 150,
    "cmap": "auto",
    "nbins": 21,
    "coastline": True,
    "overlays_resolution": "110m",
    "recent_files": [],
    "window": {"w": 1360, "h": 860},
}


def prefs_path() -> str:
    base = os.path.join(os.path.expanduser("~"), ".ncsight")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "preferences.yaml")


def load_prefs() -> Dict[str, Any]:
    p = prefs_path()
    if not os.path.exists(p):
        return dict(DEFAULT_PREFS)
    try:
        import yaml
        with open(p, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        out = dict(DEFAULT_PREFS)
        out.update(data)
        return out
    except Exception:                                   # noqa: BLE001
        return dict(DEFAULT_PREFS)


def save_prefs(prefs: Dict[str, Any]) -> str:
    p = prefs_path()
    try:
        import yaml
        with open(p, "w", encoding="utf-8") as fh:
            yaml.safe_dump(prefs, fh, allow_unicode=True, sort_keys=False)
    except Exception:                                   # noqa: BLE001
        pass
    return p
