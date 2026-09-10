# -*- coding: utf-8 -*-
"""一键盘出「MAA 挂机助手」通用安装包。

产物：
    MAA挂机助手-安装包.exe          精简版（约 30 MB，不含 MAA 本体）
    MAA挂机助手-安装包-完整版.exe   完整版（约 300 MB，内置 MAA，装完即用）

结构：安装器 exe + 附加在尾部的 payload.zip（安装器从自身尾部定位并解压）。

用法：
    python build_installer.py               # 只出精简版
    python build_installer.py --with-maa    # 两个都出（完整版耗时长）
    python build_installer.py --skip-core   # 跳过安装器本体打包（调试 payload 时用）
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import zipfile
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
# 打包用的解释器：默认用当前跑本脚本的 Python；可用环境变量 MAA_BUILD_PYTHON 覆盖
PY = os.environ.get("MAA_BUILD_PYTHON") or sys.executable
CORE_NAME = "installer_core"
CORE_EXE = os.path.join(APP_DIR, "dist", CORE_NAME + ".exe")
MAIN_EXE = os.path.join(APP_DIR, "MAA挂机助手.exe")
MAA_DIR = os.path.join(APP_DIR, "MAA")
OUT_SLIM = os.path.join(APP_DIR, "MAA挂机助手-安装包.exe")
OUT_FULL = os.path.join(APP_DIR, "MAA挂机助手-安装包-完整版.exe")

# MAA 目录里不进安装包的运行垃圾
MAA_EXCLUDE_DIRS = {"debug", "cache", "logs"}

README = """MAA 挂机助手 · 使用说明
================================

【首次使用】
1. 双击「MAA挂机助手.exe」打开主界面
2. 首次运行会自动探测 MuMu 模拟器与 MAA 的安装位置
   （若没找到，在界面「设置」里手动填一下路径即可）
3. MuMu 模拟器需要提前安装：https://mumu.163.com/
4. 定时挂机、通知推送都在主界面「设置」里配置

【文件说明】
· MAA挂机助手.exe   主程序（关闭窗口 = 缩到托盘，定时继续跑）
· ui.html           界面文件（可选，放着可优先加载，方便自定义）
· MAA/              MAA 本体（完整版安装包才有）

【卸载】
控制面板 → 应用，或在安装目录双击 uninstall.exe
"""


def run(cmd, **kw):
    print("+ %s" % " ".join(os.path.basename(str(c)) for c in cmd))
    return subprocess.run(cmd, **kw).returncode


def build_core():
    """打包安装器本体（含界面文件）。"""
    rc = run([
        PY, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--icon", os.path.join(APP_DIR, "app.ico"),
        "--name", CORE_NAME,
        "--add-data", os.path.join(APP_DIR, "installer_ui.html") + ";.",
        "--collect-all", "webview",
        "--collect-all", "clr_loader",
        "--collect-all", "pythonnet",
        os.path.join(APP_DIR, "installer.py"),
    ], cwd=APP_DIR)
    if rc != 0:
        print("安装器本体打包失败")
        return False
    return os.path.exists(CORE_EXE)


def write_payload(zip_path: str, include_maa: bool):
    """生成 payload.zip。MAA 目录按需附带。"""
    items = [
        (MAIN_EXE, "MAA挂机助手.exe"),
        (os.path.join(APP_DIR, "ui.html"), "ui.html"),
        (os.path.join(APP_DIR, "app.ico"), "app.ico"),
    ]
    t0 = time.time()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for src, arcname in items:
            if not os.path.exists(src):
                raise FileNotFoundError(src)
            print("  + %-24s %.1f MB" % (arcname, os.path.getsize(src) / 1048576))
            zf.write(src, arcname)
        zf.writestr("使用说明.txt", README)
        if include_maa:
            count = 0
            for root, dirs, files in os.walk(MAA_DIR):
                dirs[:] = [d for d in dirs if d.lower() not in MAA_EXCLUDE_DIRS]
                for name in files:
                    p = os.path.join(root, name)
                    arc = "MAA/" + os.path.relpath(p, MAA_DIR).replace("\\", "/")
                    zf.write(p, arc)
                    count += 1
                    if count % 500 == 0:
                        print("    … MAA 已打包 %d 个文件" % count)
            print("  + MAA/ 共 %d 个文件" % count)
    print("  payload 完成：%.1f MB，用时 %.0fs"
          % (os.path.getsize(zip_path) / 1048576, time.time() - t0))


def append_payload(core_exe: str, payload_zip: str, out_path: str):
    """安装包 = 安装器 exe + 原样附加的 zip（安装器从 EOCD 定位）。"""
    with open(out_path, "wb") as out:
        with open(core_exe, "rb") as core:
            shutil.copyfileobj(core, out, 1024 * 1024)
        with open(payload_zip, "rb") as pay:
            shutil.copyfileobj(pay, out, 4 * 1024 * 1024)
    return os.path.getsize(out_path)


def verify(path: str) -> bool:
    """用安装器自己的定位逻辑验证产物。"""
    sys.path.insert(0, APP_DIR)
    import installer as ins

    old = ins.SELF_PATH
    try:
        ins.SELF_PATH = path
        zf = ins.locate_payload()
        if zf is None:
            print("  !! 验证失败：%s 定位不到 payload" % os.path.basename(path))
            return False
        names = zf.namelist()
        has_exe = "MAA挂机助手.exe" in names
        has_maa = any(n.upper().startswith("MAA/") for n in names)
        print("  验证 OK：%d 个条目，主程序=%s，含 MAA=%s"
              % (len(names), has_exe, has_maa))
        return has_exe
    finally:
        ins.SELF_PATH = old


def main():
    with_maa = "--with-maa" in sys.argv

    if not os.path.exists(MAIN_EXE):
        print("找不到主程序 %s，请先运行 build_exe.py" % MAIN_EXE)
        return 1

    if "--skip-core" not in sys.argv or not os.path.exists(CORE_EXE):
        if not build_core():
            return 1
    print("安装器本体：%.1f MB" % (os.path.getsize(CORE_EXE) / 1048576))

    slim_payload = os.path.join(APP_DIR, "build", "_payload_slim.zip")
    print("\n== 精简版 payload ==")
    write_payload(slim_payload, include_maa=False)
    size = append_payload(CORE_EXE, slim_payload, OUT_SLIM)
    print("精简版安装包：%s（%.1f MB）" % (OUT_SLIM, size / 1048576))
    ok_slim = verify(OUT_SLIM)

    ok_full = True
    if with_maa:
        full_payload = os.path.join(APP_DIR, "build", "_payload_full.zip")
        print("\n== 完整版 payload（含 MAA，耐心等）==")
        write_payload(full_payload, include_maa=True)
        size = append_payload(CORE_EXE, full_payload, OUT_FULL)
        print("完整版安装包：%s（%.1f MB）" % (OUT_FULL, size / 1048576))
        ok_full = verify(OUT_FULL)

    print("\n结论：%s" % ("全部成功" if (ok_slim and ok_full) else "有失败项，检查上方日志"))
    return 0 if (ok_slim and ok_full) else 1


if __name__ == "__main__":
    sys.exit(main())
