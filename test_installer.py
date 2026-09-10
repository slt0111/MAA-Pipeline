# -*- coding: utf-8 -*-
"""安装器自动化测试：不解压到桌面、不弹窗，直接调内部安装逻辑到临时目录。"""
import os
import shutil
import sys
import tempfile
import winreg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import installer as ins

PKG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MAA挂机助手-安装包.exe")
ok = True

try:
    ins.SELF_PATH = PKG
    api = ins.InstallerApi()
    state = api.get_state()
    print("== payload 状态 ==")
    for k in ("has_payload", "payload_has_maa", "payload_mb", "webview2"):
        print("   %s = %s" % (k, state[k]))
    print("   mumu = %s" % state["mumu"])
    ok &= state["has_payload"]

    tmp = os.path.join(tempfile.gettempdir(), "maa_installer_test")
    shutil.rmtree(tmp, ignore_errors=True)
    print("\n== 安装到 %s（不建快捷方式、不启动）==" % tmp)
    api._do_install(tmp, False, False, False)
    prog = api.progress
    print("   phase=%s pct=%s msg=%s err=%s" % (prog["phase"], prog["pct"], prog["msg"], prog["error"]))
    ok &= prog["phase"] == "done"

    exe = os.path.join(tmp, "MAA挂机助手.exe")
    e1 = os.path.exists(exe)
    print("   主程序落地：%s（%.1f MB）" % (e1, os.path.getsize(exe) / 1048576 if e1 else 0))
    ok &= e1
    print("   ui.html 落地：%s" % os.path.exists(os.path.join(tmp, "ui.html")))

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ins.UNINSTALL_REG) as k:
        us = winreg.QueryValueEx(k, "UninstallString")[0]
        print("   卸载注册表 OK：%s" % us)
    print("   uninstall.exe 落地：%s" % os.path.exists(os.path.join(tmp, "uninstall.exe")))

    # 清理
    ins.remove_uninstall_key()
    shutil.rmtree(tmp, ignore_errors=True)
    print("\n清理完成")
except Exception as exc:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    ok = False

print("\n结论：%s" % ("通过" if ok else "失败"))
sys.exit(0 if ok else 1)
