# -*- coding: utf-8 -*-
"""把 pipeline.py + ui.html 打包成单个 exe：MAA挂机助手.exe

用法：
    build_exe.py              完整打包（先跑自检再打包）
    build_exe.py --skip-test  跳过打包前自检
"""

from __future__ import annotations

import os
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
# 打包用的解释器：默认直接用「当前跑本脚本的 Python」（需已装 pyinstaller/pywebview/Pillow）。
# 需要指定独立虚拟环境时设环境变量 MAA_BUILD_PYTHON 即可。
PY = os.environ.get("MAA_BUILD_PYTHON") or sys.executable
EXE_NAME = "MAA挂机助手"
DIST_DIR = os.path.join(APP_DIR, "dist")
BUILD_DIR = os.path.join(APP_DIR, "build")


def run(cmd, **kw):
    print("+ %s" % " ".join(os.path.basename(c) if os.sep in str(c) else str(c) for c in cmd))
    return subprocess.run(cmd, **kw).returncode


def main():
    if not os.path.exists(PY):
        print("找不到打包用的 Python：%s" % PY)
        return 1

    # 打包前自检（用打包环境跑，能提前暴露缺模块等问题）
    if "--skip-test" not in sys.argv:
        rc = run([PY, os.path.join(APP_DIR, "pipeline.py"), "--selftest"])
        if rc != 0:
            print("自检未通过（退出码 %d），中止打包" % rc)
            return rc

    args = [
        PY, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--icon", os.path.join(APP_DIR, "app.ico"),
        "--name", EXE_NAME,
        "--version-file", os.path.join(APP_DIR, "version_info.py"),
        "--add-data", os.path.join(APP_DIR, "ui.html") + ";.",
        "--add-data", os.path.join(APP_DIR, "app.ico") + ";.",
        # pywebview 在 Windows 走 pythonnet/EdgeChromium，这些运行时文件必须带上
        "--collect-all", "webview",
        "--collect-all", "clr_loader",
        "--collect-all", "pythonnet",
        "--hidden-import", "plat",
        "--hidden-import", "plat.windows",
        "--hidden-import", "plat.macos",
        "--hidden-import", "plat.linux",
        "--hidden-import", "plat.base",
        "--hidden-import", "plat.util",
        os.path.join(APP_DIR, "pipeline.py"),
    ]
    rc = run(args, cwd=APP_DIR)
    if rc != 0:
        print("PyInstaller 失败（退出码 %d）" % rc)
        return rc

    exe = os.path.join(DIST_DIR, EXE_NAME + ".exe")
    if not os.path.exists(exe):
        print("未找到产物：%s" % exe)
        return 1
    print("\n打包完成：%s（%.1f MB）" % (exe, os.path.getsize(exe) / 1048576))
    return 0


if __name__ == "__main__":
    sys.exit(main())
