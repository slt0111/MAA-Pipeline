# -*- coding: utf-8 -*-
"""验证安装包 GUI 能否正常弹出原生窗口（用纯 Python 启动，避免 shell 拦 GUI 进程）。"""
import ctypes
import os
import subprocess
import sys
import time

PKG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MAA挂机助手-安装包.exe")
TITLE = "MAA 挂机助手 · 安装向导"

print("启动：%s" % PKG)
proc = subprocess.Popen([PKG], cwd=os.path.dirname(PKG))
deadline = time.time() + 25
hwnd = 0
while time.time() < deadline:
    time.sleep(1.5)
    hwnd = ctypes.windll.user32.FindWindowW(None, TITLE)
    if hwnd:
        break
    if proc.poll() is not None:
        print("进程已退出，退出码 = %s" % proc.returncode)
        break

print("向导窗口句柄 = %s" % hwnd)
print("窗口存在 = %s" % bool(hwnd))
alive = proc.poll() is None
print("进程存活 = %s" % alive)

if alive:
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                   capture_output=True, creationflags=0x08000000)
    print("已关闭测试窗口")
sys.exit(0 if hwnd else 1)
