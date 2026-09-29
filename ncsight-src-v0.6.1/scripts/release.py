# -*- coding: utf-8 -*-
"""
版本发布辅助脚本
================
用法：

    python scripts/release.py show                     # 显示当前版本
    python scripts/release.py bump patch               # 0.3.0 -> 0.3.1
    python scripts/release.py bump minor               # 0.3.0 -> 0.4.0
    python scripts/release.py bump minor --commit      # 同时提交并打 tag
    python scripts/release.py bump 1.0.0 --commit      # 指定确切版本号
    python scripts/release.py check                    # 一致性自检

它做四件事（顺序固定，失败即停）：
  1. 改 ncsight/version.py 的 __version__ 与 __release_date__（版本号唯一来源）
  2. 把 CHANGELOG.md 的 [Unreleased] 段落落到新版本号下
  3. 可选：git add + commit + tag vX.Y.Z
  4. 打印下一步该做什么

**为什么要有这个脚本**：手工改版本号最容易出的错是「代码里是 0.4.0、
CHANGELOG 里是 0.3.1、git tag 还是旧的」。三处不同步之后，
排查线上问题是灾难。脚本把三处绑在一起，从流程上消灭这个问题。
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_PY = os.path.join(ROOT, "ncsight", "version.py")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
PYPROJECT = os.path.join(ROOT, "pyproject.toml")


# --------------------------------------------------------------------------
def _read_version() -> str:
    with open(VERSION_PY, "r", encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not m:
        raise SystemExit("在 %s 里找不到 __version__" % VERSION_PY)
    return m.group(1)


def _parse(v: str):
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", v)
    if not m:
        raise SystemExit("版本号格式不正确：%s（应为 MAJOR.MINOR.PATCH）" % v)
    return tuple(int(x) for x in m.groups())


def _bump(current: str, part: str) -> str:
    if re.match(r"^\d+\.\d+\.\d+", part):
        return part
    major, minor, patch = _parse(current)
    if part == "major":
        return "%d.0.0" % (major + 1)
    if part == "minor":
        return "%d.%d.0" % (major, minor + 1)
    if part == "patch":
        return "%d.%d.%d" % (major, minor, patch + 1)
    raise SystemExit("未知的版本段：%s（可选 major/minor/patch 或确切版本号）" % part)


def _write_version(new: str, stage: str) -> None:
    today = dt.date.today().isoformat()
    with open(VERSION_PY, "r", encoding="utf-8") as fh:
        text = fh.read()
    text = re.sub(r'^__version__\s*=\s*["\'][^"\']+["\']',
                  '__version__ = "%s"' % new, text, count=1, flags=re.M)
    text = re.sub(r'^__stage__\s*=\s*["\'][^"\']+["\']',
                  '__stage__ = "%s"' % stage, text, count=1, flags=re.M)
    text = re.sub(r'^__release_date__\s*=\s*["\'][^"\']+["\']',
                  '__release_date__ = "%s"' % today, text, count=1, flags=re.M)
    with open(VERSION_PY, "w", encoding="utf-8") as fh:
        fh.write(text)


def _roll_changelog(new: str) -> bool:
    """
    把 [Unreleased] 的内容落到「## [new] - 日期」下，并重建一个空的 [Unreleased]。

    CHANGELOG 结构（节选）：
        ## [Unreleased]
        ### 计划中 ...
        ---
        ## [0.3.0] - 2026-09-23
        ...
    """
    if not os.path.exists(CHANGELOG):
        print("  ! 找不到 CHANGELOG.md，跳过")
        return False
    with open(CHANGELOG, "r", encoding="utf-8") as fh:
        text = fh.read()

    marker = "## [Unreleased]"
    start = text.find(marker)
    if start < 0:
        print("  ! CHANGELOG.md 里没有 [Unreleased] 段落，跳过")
        return False

    after = text[start + len(marker):]
    nxt = re.search(r"^## \[", after, re.M)
    if nxt:
        body = after[:nxt.start()]
        tail = after[nxt.start():]
    else:
        body = after
        tail = ""

    body_clean = body.strip()
    # 去掉尾部多余的分隔线
    body_clean = re.sub(r"\n-{3,}\s*$", "", body_clean).strip()
    if not body_clean:
        body_clean = "### 变更\n- （本次没有留下记录，请补充）"

    today = dt.date.today().isoformat()
    new_block = (
        "## [Unreleased]\n\n"
        "### 计划中\n- （待补充）\n\n"
        "---\n\n"
        "## [%s] - %s\n\n%s\n\n"
        "---\n\n" % (new, today, body_clean)
    )
    out = text[:start] + new_block + tail
    # 同步底部链接
    out = re.sub(r"^\[Unreleased\]: .*$",
                 "[Unreleased]: https://example.invalid/ncsight/compare/v%s...HEAD" % new,
                 out, count=1, flags=re.M)
    with open(CHANGELOG, "w", encoding="utf-8") as fh:
        fh.write(out)
    return True


def _git(*args) -> int:
    return subprocess.call(["git"] + list(args), cwd=ROOT)


def _has_git() -> bool:
    try:
        return subprocess.call(["git", "rev-parse", "--is-inside-work-tree"],
                               cwd=ROOT, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL) == 0
    except Exception:                                   # noqa: BLE001
        return False


def _working_tree_clean() -> bool:
    r = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                       capture_output=True, text=True)
    return not (r.stdout or "").strip()


# --------------------------------------------------------------------------
def cmd_show(_args) -> int:
    v = _read_version()
    print("当前版本：v%s" % v)
    if _has_git():
        r = subprocess.run(["git", "tag", "--list", "v*"], cwd=ROOT,
                           capture_output=True, text=True)
        tags = [t for t in (r.stdout or "").split() if t]
        print("已有 git tag：%s" % (", ".join(tags[-8:]) or "（无）"))
    return 0


def cmd_check(_args) -> int:
    v = _read_version()
    problems = []

    if os.path.exists(CHANGELOG):
        with open(CHANGELOG, "r", encoding="utf-8") as fh:
            text = fh.read()
        if "## [%s]" % v not in text:
            problems.append("CHANGELOG.md 里没有 ## [%s] 段落" % v)
        if "## [Unreleased]" not in text:
            problems.append("CHANGELOG.md 缺少 [Unreleased] 段落")
    else:
        problems.append("缺少 CHANGELOG.md")

    if _has_git():
        r = subprocess.run(["git", "tag", "--list", "v%s" % v], cwd=ROOT,
                           capture_output=True, text=True)
        if not (r.stdout or "").strip():
            problems.append("还没有为 v%s 打 git tag（发布时用 --commit）" % v)
        if not _working_tree_clean():
            problems.append("工作区有未提交的改动")

    print("版本一致性自检：v%s" % v)
    if not problems:
        print("  ✓ 通过")
        return 0
    for p in problems:
        print("  ✗ %s" % p)
    return 1


def cmd_bump(args) -> int:
    old = _read_version()
    new = _bump(old, args.part)
    stage = "stable" if args.stable else "dev"

    if _has_git() and not _working_tree_clean() and args.commit:
        print("工作区有未提交的改动，请先提交或加上 --allow-dirty。")
        if not args.allow_dirty:
            return 1

    print("发布：v%s -> v%s（阶段 %s）" % (old, new, stage))
    _write_version(new, stage)
    print("  ✓ 已更新 ncsight/version.py")
    if _roll_changelog(new):
        print("  ✓ 已滚动 CHANGELOG.md")

    if args.commit:
        if not _has_git():
            print("  ! 这不是一个 git 仓库，跳过提交")
        else:
            _git("add", "-A")
            _git("commit", "-m", "release: v%s" % new)
            _git("tag", "-a", "v%s" % new, "-m", "NCSight v%s" % new)
            print("  ✓ 已提交并打 tag v%s" % new)

    print("\n下一步：")
    print("  1. 复核 CHANGELOG.md 的措辞")
    print("  2. 跑测试： python -m pytest")
    if args.commit:
        print("  3. 推送：  git push && git push --tags")
    else:
        print("  3. 提交：  git add -A && git commit -m 'release: v%s'" % new)
        print("     打标签：git tag -a v%s -m 'NCSight v%s'" % (new, new))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="NCSight 版本发布辅助")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("show", help="显示当前版本与已有 tag")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("check", help="版本号与 CHANGELOG / git tag 的一致性自检")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("bump", help="提升版本号")
    s.add_argument("part", help="major / minor / patch，或确切版本号如 1.0.0")
    s.add_argument("--commit", action="store_true", help="同时 git 提交并打 tag")
    s.add_argument("--stable", action="store_true",
                   help="标记为稳定版（__stage__ = stable）")
    s.add_argument("--allow-dirty", action="store_true",
                   help="允许在脏工作区上打 tag")
    s.set_defaults(func=cmd_bump)

    args = p.parse_args(argv)
    if not getattr(args, "cmd", None):
        p.print_help()
        return 0
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
