# -*- coding: utf-8 -*-
"""在 macOS 上把本工具打成 MAA挂机助手.app 并装进 .dmg。

必须在 Mac 上跑（PyInstaller 的 Mach-O / .app 无法在 Linux 交叉编出来）。
不附带 MuMu / MAA。签名与公证是可选项，默认打未签名包。

用法：
    python3 build_dmg.py              # 本机是 Mac 时：打包 + 生成 dmg
    python3 build_dmg.py --skip-test  # 跳过 --selftest
    python3 build_dmg.py --dry-run    # 只打印将要执行的命令（Linux CI 可用）
    python3 build_dmg.py --check      # 检查脚本完整性后退出

环境变量：
    MAA_BUILD_PYTHON     打包用的解释器
    MAA_CODESIGN_ID      若设置则 codesign --deep --force（Developer ID Application: …）
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PY = os.environ.get("MAA_BUILD_PYTHON") or sys.executable
APP_NAME = "MAA挂机助手"
BUNDLE_ID = "com.maapipeline.app"
DIST_DIR = os.path.join(APP_DIR, "dist")
BUILD_DIR = os.path.join(APP_DIR, "build")
DMG_NAME = "MAA挂机助手.dmg"


def add_data_sep() -> str:
    return ";" if os.name == "nt" else ":"


def pyinstaller_args() -> list:
    sep = add_data_sep()
    args = [
        PY, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onedir", "--windowed",
        "--name", APP_NAME,
        "--osx-bundle-identifier", BUNDLE_ID,
        "--add-data", os.path.join(APP_DIR, "ui.html") + sep + ".",
        "--add-data", os.path.join(APP_DIR, "app.ico") + sep + ".",
        "--collect-all", "webview",
        "--hidden-import", "plat",
        "--hidden-import", "plat.windows",
        "--hidden-import", "plat.macos",
        "--hidden-import", "plat.linux",
        "--hidden-import", "plat.base",
        "--hidden-import", "plat.util",
        "--hidden-import", "plat.maa_cli",
        "--hidden-import", "plat.tray_macos",
        os.path.join(APP_DIR, "pipeline.py"),
    ]
    icon = os.path.join(APP_DIR, "app.ico")
    if os.path.exists(icon):
        args[args.index("--name"):args.index("--name")]  # keep stable
        # --icon 插在 --name 之后
        name_at = args.index("--name")
        args[name_at + 2:name_at + 2] = ["--icon", icon]
    return args


def dmg_cmd(app_path: str, dmg_path: str) -> list:
    return [
        "hdiutil", "create",
        "-volname", APP_NAME,
        "-srcfolder", app_path,
        "-ov", "-format", "UDZO",
        dmg_path,
    ]


def codesign_cmd(app_path: str, identity: str) -> list:
    return [
        "codesign", "--deep", "--force", "--options", "runtime",
        "--sign", identity, app_path,
    ]


def run(cmd, dry=False, **kw):
    printable = " ".join(cmd)
    print("+ %s" % printable)
    if dry:
        return 0
    return subprocess.run(cmd, **kw).returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="打包 macOS .app + .dmg")
    parser.add_argument("--skip-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    argv_pi = pyinstaller_args()
    if args.check or args.dry_run:
        print("PyInstaller 参数：")
        print(" ", " ".join(argv_pi))
        print("产物：%s" % os.path.join(DIST_DIR, APP_NAME + ".app"))
        print("镜像：%s" % os.path.join(DIST_DIR, DMG_NAME))
        print("签名：%s" % ("将使用 " + os.environ["MAA_CODESIGN_ID"]
                          if os.environ.get("MAA_CODESIGN_ID") else "跳过（未设 MAA_CODESIGN_ID）"))
        print("公证：本脚本不提交 notarytool，需在 Apple 开发者账号下另行处理")
        if args.check:
            if "--osx-bundle-identifier" not in argv_pi or BUNDLE_ID not in argv_pi:
                print("检查失败：缺少 bundle id")
                return 2
            if "plat.tray_macos" not in argv_pi:
                print("检查失败：未打进托盘模块")
                return 2
            print("检查通过。真正出包请在 macOS 上运行：python3 build_dmg.py")
            return 0

    if sys.platform != "darwin" and not args.dry_run:
        print("当前不是 macOS，无法生成 Mach-O / .app。")
        print("请在 Mac 上执行：  python3 build_dmg.py")
        print("或先在本机跑：      python3 build_dmg.py --dry-run / --check")
        return 0

    if not args.skip_test and not args.dry_run:
        rc = run([PY, os.path.join(APP_DIR, "pipeline.py"), "--selftest"])
        if rc != 0:
            print("自检未通过（退出码 %d）。若只想看打包命令，用 --skip-test 或 --dry-run。" % rc)
            return rc

    rc = run(argv_pi, dry=args.dry_run, cwd=APP_DIR)
    if rc != 0:
        print("PyInstaller 失败（退出码 %d）" % rc)
        return rc

    app_path = os.path.join(DIST_DIR, APP_NAME + ".app")
    if not args.dry_run and not os.path.isdir(app_path):
        print("未找到 %s" % app_path)
        return 1

    identity = (os.environ.get("MAA_CODESIGN_ID") or "").strip()
    if identity:
        rc = run(codesign_cmd(app_path, identity), dry=args.dry_run)
        if rc != 0:
            print("codesign 失败（退出码 %d）" % rc)
            return rc
    else:
        print("未设置 MAA_CODESIGN_ID，跳过 codesign。Gatekeeper 可能拦截未签名应用。")

    dmg_path = os.path.join(DIST_DIR, DMG_NAME)
    if not args.dry_run and os.path.exists(dmg_path):
        os.remove(dmg_path)
    rc = run(dmg_cmd(app_path, dmg_path), dry=args.dry_run)
    if rc != 0:
        print("hdiutil 失败（退出码 %d）" % rc)
        return rc

    if args.dry_run:
        print("dry-run 结束（未真正调用 PyInstaller / hdiutil）")
        return 0

    size = os.path.getsize(dmg_path) / 1048576 if os.path.exists(dmg_path) else 0
    print("\n打包完成：%s（%.1f MB）" % (dmg_path, size))
    print("内含：%s" % app_path)
    print("不含 MuMu / MAA。公证请另行：xcrun notarytool submit …")
    return 0


if __name__ == "__main__":
    sys.exit(main())
