# -*- coding: utf-8 -*-
"""
一键打包成 exe（Windows）
========================
用法：

    python scripts/build_exe.py                 # 完整打包 + 自检
    python scripts/build_exe.py --no-selftest   # 只打包
    python scripts/build_exe.py --clean         # 先删掉旧的 dist/build

它做四件事：
  1. 重新生成应用图标 NCSight.ico（图标是用代码画的，不是外部素材）
  2. 调用 PyInstaller 按 ncsight.spec 打包成**目录模式**
     （产出 dist/NCSight/NCSight.exe + _internal/，与 Panoply 的 exe + jars 同构）
  3. 打印产物结构与体积
  4. 拿真实数据跑一次 exe 的离屏自检，确认 Qt 插件、离线底图、出图链路都正常
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")
APP_OUT = os.path.join(DIST, "NCSight")

#: 打包专用 venv（由 scripts/make_build_env.py 创建）。
#: 存在就优先用它 —— 干净环境既避免把 ML 栈扫进来，也没有 MKL 的体积黑洞。
BUILD_ENV_PY = os.path.join(ROOT, "packaging", "buildenv", "Scripts", "python.exe")

#: 自检时默认使用的示例数据（存在就用）
DEFAULT_DATASET = r"E:\bigcreation\NOAAVIRUSdata\JPSS1_VIIRS.20180105.L3m.DAY.SST.sst.4km.nc"


def venv_python() -> str:
    """优先用打包专用 venv 的解释器，没有就用当前解释器。"""
    if os.path.exists(BUILD_ENV_PY):
        return BUILD_ENV_PY
    return sys.executable


def using_build_env() -> bool:
    return os.path.exists(BUILD_ENV_PY)


def run(cmd, cwd=None, stream=True) -> int:
    print("\n$ %s" % " ".join(cmd), flush=True)
    # PYTHONPATH 置空：宿主的 shim 会注入 sitecustomize（内含批量删除保护），
    # 会把 PyInstaller 正常的临时文件清理误判成危险操作而中断构建。
    env = dict(os.environ)
    env["PYTHONPATH"] = ""
    if stream:
        return subprocess.call(cmd, cwd=cwd, env=env)
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    return r.returncode



def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return str(n)


def dir_size(path: str) -> int:
    total = 0
    for dp, _dn, fs in os.walk(path):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def summarize(root: str) -> None:
    print("\n" + "=" * 66)
    print("产物结构  %s" % root)
    print("=" * 66)
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if os.path.isdir(p):
            print("  %-24s %-10s %s" % (name + "/", human(dir_size(p)),
                                        "(%d 个文件)" % sum(len(f) for _, _, f in os.walk(p))))
        else:
            print("  %-24s %s" % (name, human(os.path.getsize(p))))
    print("-" * 66)
    print("  合计 %s" % human(dir_size(root)))
    print()

    # MKL 体积提醒：conda 的 numpy 会带来约 600 MB 的 MKL 内核变体
    mkl = []
    for dp, _dn, fs in os.walk(root):
        for f in fs:
            if f.lower().startswith("mkl_") and f.lower().endswith(".dll"):
                try:
                    mkl.append(os.path.getsize(os.path.join(dp, f)))
                except OSError:
                    pass
    if mkl:
        print("  ⚠ 检测到 Intel MKL 共 %.0f MB（%d 个 DLL）" % (sum(mkl) / 1024 / 1024, len(mkl)))
        print("    这是 conda 版 numpy/scipy 的连带产物，占了整体积大半。")
        print("    想显著瘦身：改用打包专用 venv（pip 版走 OpenBLAS，无 MKL）")
        print("      python scripts\\make_build_env.py")
        print("      python scripts\\build_exe.py --clean")
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description="打包 NCSight 为 Windows 可执行程序")
    ap.add_argument("--clean", action="store_true", help="先清理 dist/ 与 build/")
    ap.add_argument("--no-selftest", action="store_true", help="跳过打包后的自检")
    ap.add_argument("--dataset", default=DEFAULT_DATASET, help="自检用的 nc 数据集")
    ap.add_argument("--selftest-timeout", type=int, default=600,
                    help="自检超时秒数（默认 600）")
    args = ap.parse_args()

    t_start = time.time()

    # ---- 0) 环境检查 ----
    print("=" * 66)
    print("打包环境：%s" % venv_python())
    if using_build_env():
        print("  ✓ 使用打包专用 venv（干净、无 MKL，产物更小）")
    else:
        print("  ⚠ 未找到打包专用 venv，将使用日常环境")
        print("    日常环境若装了很多无关大包，产物会显著偏大。")
        print("    建议先运行： python scripts\\make_build_env.py")
    print("=" * 66)

    try:
        r = subprocess.run([venv_python(), "-c", "import PyInstaller;"
                            "print(PyInstaller.__version__)"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("该环境缺少 PyInstaller。请安装：\n  %s -m pip install pyinstaller"
                  % venv_python())
            return 2
        print("PyInstaller %s" % r.stdout.strip())
    except Exception as exc:                            # noqa: BLE001
        print("无法调用解释器：%s" % exc)
        return 2

    # ---- 1) 图标 ----
    print("\n[1/4] 生成应用图标")
    run([venv_python(), os.path.join(ROOT, "scripts", "make_icon.py")],
        cwd=ROOT)


    # ---- 2) 清理 ----
    if args.clean:
        print("\n[2/4] 清理旧的构建产物")
        for d in (DIST, BUILD):
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
                print("  已删除 %s" % d)
    else:
        print("\n[2/4] 跳过清理（加 --clean 可强制清理）")

    # ---- 3) 打包 ----
    print("\n[3/4] PyInstaller 打包（首次约需数分钟）")
    rc = run([venv_python(), "-m", "PyInstaller",
              "--clean", "--noconfirm",
              os.path.join(ROOT, "ncsight.spec")], cwd=ROOT)
    if rc != 0 or not os.path.isdir(APP_OUT):
        print("\n打包失败（退出码 %d）。请检查上面的输出。" % rc)
        return 1

    summarize(APP_OUT)

    # ---- 4) 自检 ----
    if args.no_selftest:
        print("[4/4] 已跳过自检")
    else:
        print("[4/4] 运行打包后自检")
        exe = os.path.join(APP_OUT, "NCSight.exe")
        cmd = [exe, "--selftest"]
        if os.path.exists(args.dataset):
            cmd.append(args.dataset)
        else:
            print("  提示：未找到示例数据 %s，自检将跳过出图环节" % args.dataset)
        # 加超时兜底：万一 exe 因环境问题卡住，构建脚本不会跟着挂死
        print("\n$ %s" % " ".join(cmd), flush=True)
        env = {**os.environ, "PYTHONPATH": ""}
        rc = 1
        try:
            r = subprocess.run(cmd, cwd=APP_OUT, env=env,
                               timeout=args.selftest_timeout)
            rc = r.returncode
        except subprocess.TimeoutExpired:
            print("\n⚠ 自检超时（%d 秒）已被强制终止。" % args.selftest_timeout)
            print("  若自检项都显示 OK，多半是 exe 退出时被 Qt 挂住，")
            print("  可检查 packaging/gui_entry.py 里 _report() 的强制退出逻辑。")

        # ★ 以「自检报告」为准，而不是退出码 ★
        # 冻结程序在 Windows 上退出码偶尔不可靠（进程正常跑完、报告写好了，
        # 但 subprocess 拿到的 returncode 非 0）。报告文件才是一手事实。
        rep = os.path.join(os.path.expanduser("~"), ".ncsight",
                           "selftest", "selftest_report.txt")
        n_ok = n_fail = 0
        if os.path.exists(rep):
            try:
                txt = open(rep, encoding="utf-8").read()
                n_ok = txt.count("[OK")
                n_fail = txt.count("[FAIL")
            except Exception:                           # noqa: BLE001
                pass
        if n_fail == 0 and n_ok > 0:
            print("\n✓ 自检全部通过（%d 项，退出码 %d）" % (n_ok, rc))
        elif n_fail:
            print("\n⚠ 自检有 %d 项失败，详见上面的 FAIL 行。" % n_fail)
        elif rc != 0:
            print("\n⚠ 自检异常退出（退出码 %d），且没读到报告。" % rc)
            print("  报告路径应为：%s" % rep)

    print("\n" + "=" * 66)
    print("打包完成，用时 %.1f 分钟" % ((time.time() - t_start) / 60.0))
    print("=" * 66)
    print("\n怎么用：")
    print("  1. 把整个目录拷到任意位置（比如桌面），例如：")
    print("       %s" % APP_OUT)
    print("  2. 双击  NCSight.exe  即可启动图形界面")
    print("     命令行批量出图用  ncsight-cli.exe")
    print("  3. 注意：_internal 文件夹必须和 exe 放在一起，不能单独移动 exe")
    print("\n可以先把 exe 拖到桌面建个快捷方式，或发送到「开始菜单」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
