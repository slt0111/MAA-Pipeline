# -*- coding: utf-8 -*-
"""macOS 菜单栏托盘：菜单文案与后端探测（无 AppKit 时不创建真实图标）。

跑法：
    python tests/_test_tray_macos.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plat.macos import MacOSPlatform
from plat.tray_macos import MacStatusTray, menu_labels, tray_backend_available
from plat.windows import WindowsPlatform

PASS, FAIL = [], []


def ok(cond, title, detail=""):
    (PASS if cond else FAIL).append(title)
    extra = ""
    if detail and not cond:
        extra = "  " + str(detail)
    print("  [%s] %s%s" % ("OK" if cond else "!!", title, extra))


print("=== 1. 菜单与 Windows 对齐 ===")
labels = menu_labels()
ok(labels[0] == "显示主界面", "第一项：显示主界面")
ok("立即挂机" in labels, "含立即挂机")
ok("中止" in labels, "含中止（Mac 多一项）")
ok(labels[-1] == "退出", "最后一项：退出")


print("=== 2. 后端探测不崩 ===")
kind = tray_backend_available()
ok(kind in (None, "appkit", "rumps", "pystray"), "探测返回已知值", kind)
print("  [i] 当前环境托盘后端：%s" % (kind or "无（Linux CI 预期）"))

mac = MacOSPlatform()
ok((mac.tray_supported() is True) == (kind is not None), "tray_supported 与探测一致")
tray = mac.create_tray({"open": lambda: None, "run": lambda: None, "quit": lambda: None})
ok(isinstance(tray, MacStatusTray), "create_tray 返回 MacStatusTray")
ok(tray.active is False, "未 start 时 inactive")

if kind is None:
    try:
        tray.start()
        ok(False, "无后端时 start 应失败")
    except RuntimeError:
        ok(True, "无后端时 start 抛 RuntimeError")
else:
    try:
        tray.start()
        ok(tray.active is True, "有后端时 start 成功")
        tray.stop()
    except Exception as exc:
        ok(False, "有后端时 start 不应失败", exc)


print("=== 3. Windows 托盘路径未改 ===")
win = WindowsPlatform()
ok(win.tray_supported() is True, "Windows tray_supported 仍为 True")
ok(win.create_tray({}) is None, "Windows create_tray 仍为 None（走 Win32 Tray）")


print()
print("=" * 62)
if FAIL:
    print("失败 %d 项：%s" % (len(FAIL), " / ".join(FAIL)))
    print("通过 %d 项" % len(PASS))
    sys.exit(1)
print("全部通过（%d 项）" % len(PASS))
