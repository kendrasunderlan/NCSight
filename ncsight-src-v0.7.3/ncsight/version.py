# -*- coding: utf-8 -*-
"""
NCSight 版本信息的唯一来源（single source of truth）。

约定：
  - 任何地方需要版本号，都从这里 import，绝不硬编码。
  - 发布新版本时运行 `python scripts/release.py <major|minor|patch>`
    它会同时更新本文件的 __version__、CHANGELOG.md，并打 git tag。
版本号规则：语义化版本 MAJOR.MINOR.PATCH
  MAJOR  不兼容的接口变更
  MINOR  向后兼容的功能新增（对应里程碑 M1/M2/M3…）
  PATCH  向后兼容的缺陷修复
"""

__version__ = "0.7.3"

# 发布阶段：dev / alpha / beta / rc / stable
__stage__ = "dev"

__release_date__ = "2026-09-29"

# 应用标识
APP_NAME = "NCSight"
APP_NAME_CN = "海视"
APP_SLOGAN = "面向海洋遥感的 netCDF 可视化工作台"
APP_AUTHOR = "NCSight Contributors"
APP_LICENSE = "MIT"

# 对应 Panoply 拆解报告里的里程碑
MILESTONE = "M3 · 科研增强"


def version_string() -> str:
    """人类可读的完整版本串，用于 --version 与「关于」对话框。"""
    s = "v%s" % __version__
    if __stage__ != "stable":
        s += "-%s" % __stage__
    return s


def version_info() -> dict:
    return {
        "app": APP_NAME,
        "app_cn": APP_NAME_CN,
        "version": __version__,
        "stage": __stage__,
        "release_date": __release_date__,
        "milestone": MILESTONE,
        "string": version_string(),
    }
