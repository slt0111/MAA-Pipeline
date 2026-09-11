# -*- coding: utf-8 -*-
"""build_dmg.py 在非 Mac 上可 --check / --dry-run，真正出包必须在 darwin。

跑法：
    python tests/_test_build_dmg.py
"""
from __future__ import annotations

import os
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(APP_DIR, "build_dmg.py")
PASS, FAIL = [], []


def ok(cond, title, detail=""):
    (PASS if cond else FAIL).append(title)
    extra = ""
    if detail and not cond:
        extra = "  " + str(detail)
    print("  [%s] %s%s" % ("OK" if cond else "!!", title, extra))


def run(args):
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        cwd=APP_DIR,
        capture_output=True,
        text=True,
    )


print("=== 1. --check ===")
chk = run(["--check"])
ok(chk.returncode == 0, "--check 退出 0", chk.stderr or chk.stdout[-400:])
out = chk.stdout or ""
ok("--osx-bundle-identifier" in out and "com.maapipeline.app" in out, "含 bundle id")
ok("plat.tray_macos" in out and "plat.maa_cli" in out, "hidden-import 含托盘与 maa-cli")
ok("MAA挂机助手.app" in out, "产物名是 MAA挂机助手.app")
ok("公证" in out or "notarytool" in out, "说明公证需另行处理")


print("=== 2. --dry-run ===")
dry = run(["--dry-run"])
ok(dry.returncode == 0, "--dry-run 退出 0", dry.stderr or dry.stdout[-400:])
ok("PyInstaller" in (dry.stdout or ""), "打印 PyInstaller 命令")


print("=== 3. 非 darwin 真正打包应软退出 ===")
if sys.platform != "darwin":
    real = run([])
    ok(real.returncode == 0, "Linux 上直接运行不报失败（提示去 Mac 打）", real.stdout[-300:])
    ok("macOS" in (real.stdout or "") or "Mac" in (real.stdout or ""), "提示需在 Mac 上执行")
else:
    ok(True, "当前就是 macOS，跳过「非 darwin 软退出」")


print()
print("=" * 62)
if FAIL:
    print("失败 %d 项：%s" % (len(FAIL), " / ".join(FAIL)))
    print("通过 %d 项" % len(PASS))
    sys.exit(1)
print("全部通过（%d 项）" % len(PASS))
