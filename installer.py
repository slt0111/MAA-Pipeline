# -*- coding: utf-8 -*-
"""MAA 挂机助手 · 通用安装器

思路：最终安装包 = 安装器 exe + 附加在文件尾部的 payload.zip。
安装器启动时从自身尾部定位 ZIP，把内容解压到用户选择的目录，
然后创建快捷方式、写卸载信息。全程不需要管理员权限（默认装到 LOCALAPPDATA）。

用法：
    installer.exe                     打开安装向导
    installer.exe --uninstall         卸载（由安装目录里的 uninstall.exe 触发）
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import shutil
import struct
import subprocess
import sys
import threading
import winreg
import zipfile

if getattr(sys, "frozen", False):
    SELF_PATH = os.path.abspath(sys.executable)
else:
    SELF_PATH = os.path.abspath(__file__)

APP_TITLE = "MAA 挂机助手 · 安装向导"
DEFAULT_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "MAA-Pipeline"
)
UNINSTALL_REG = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MAA-Pipeline"
EXE_NAME = "MAA挂机助手.exe"
LINK_NAME = "MAA 一键挂机.lnk"


# ============================================================ payload（自身尾部 ZIP）

def locate_payload():
    """安装包尾部附加了一个 ZIP；从 EOCD 反推 ZIP 起点并打开。"""
    size = os.path.getsize(SELF_PATH)
    with open(SELF_PATH, "rb") as fh:
        fh.seek(max(0, size - 65536))
        tail = fh.read()
    pos = tail.rfind(b"PK\x05\x06")
    if pos < 0:
        return None
    eocd_abs = size - len(tail) + pos
    cd_size, cd_offset = struct.unpack_from("<II", tail, pos + 12)
    zip_start = (eocd_abs - cd_size) - cd_offset
    if zip_start < 0:
        return None
    fh = open(SELF_PATH, "rb")
    fh.seek(zip_start)
    try:
        return zipfile.ZipFile(fh)
    except Exception:
        fh.close()
        return None


# ============================================================ 环境检测

_WEBVIEW2_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
]


def webview2_installed() -> bool:
    for hive, path in _WEBVIEW2_KEYS:
        try:
            with winreg.OpenKey(hive, path) as k:
                pv, _ = winreg.QueryValueEx(k, "pv")
                if pv and pv != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


_MUMU_REL = [r"nx_main\mumu-cli.exe", r"shell\mumu-cli.exe"]
_MUMU_ROOTS = [
    r"Program Files\Netease", r"Program Files (x86)\Netease",
    r"Netease", r"Games\Netease", r"MuMu", r"Program Files",
]


def find_mumu():
    for drive in "CDEFGH":
        if not os.path.isdir("%s:\\" % drive):
            continue
        for root_rel in _MUMU_ROOTS:
            root = r"%s:\%s" % (drive, root_rel)
            if not os.path.isdir(root):
                continue
            for rel in _MUMU_REL:
                cand = os.path.join(root, rel)
                if os.path.isfile(cand):
                    return cand
            try:
                names = os.listdir(root)
            except OSError:
                continue
            for name in names:
                if "mumu" not in name.lower():
                    continue
                for rel in _MUMU_REL:
                    cand = os.path.join(root, name, rel)
                    if os.path.isfile(cand):
                        return cand
    return None


# ============================================================ 快捷方式（纯 ctypes 调 IShellLink）

_CLSCTX_INPROC_SERVER = 0x1
LRESULT = ctypes.c_long


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, text):
        parts = text.strip("{}").split("-")
        g = cls()
        g.Data1 = int(parts[0], 16)
        g.Data2 = int(parts[1], 16)
        g.Data3 = int(parts[2], 16)
        tail = parts[3] + parts[4]
        for i in range(8):
            g.Data4[i] = int(tail[i * 2:i * 2 + 2], 16)
        return g


_CLSID_SHELLLINK = _GUID.parse("00021401-0000-0000-C000-000000000046")
_IID_ISHELLLINKW = _GUID.parse("000214F9-0000-0000-C000-000000000046")
_IID_IPERSISTFILE = _GUID.parse("0000010B-0000-0000-C000-000000000046")

_ole32 = ctypes.oledll.ole32
_ole32.CoCreateInstance.argtypes = [
    ctypes.POINTER(_GUID), ctypes.c_void_p, wt.DWORD,
    ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p),
]
_ole32.CoCreateInstance.restype = ctypes.c_long


def _vfn(ptr, index, prototype):
    """取 COM 接口虚表里第 index 个函数。"""
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    addr = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[index]
    return prototype(addr)


def create_lnk(target: str, lnk_path: str, workdir: str, desc: str, icon: str) -> bool:
    """创建 .lnk 快捷方式，成功返回 True。"""
    try:
        _ole32.CoInitialize(None)
        shell_link = ctypes.c_void_p()
        hr = _ole32.CoCreateInstance(
            ctypes.byref(_CLSID_SHELLLINK), None, _CLSCTX_INPROC_SERVER,
            ctypes.byref(_IID_ISHELLLINKW), ctypes.byref(shell_link),
        )
        if hr != 0 or not shell_link:
            return False

        t_set_path = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_wchar_p)
        t_set_dir = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_wchar_p)
        t_set_desc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_wchar_p)
        t_set_icon = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
        t_qi = ctypes.WINFUNCTYPE(
            LRESULT, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))
        t_release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
        t_save = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)

        _vfn(shell_link, 20, t_set_path)(shell_link, target)
        _vfn(shell_link, 9, t_set_dir)(shell_link, workdir)
        _vfn(shell_link, 7, t_set_desc)(shell_link, desc)
        _vfn(shell_link, 17, t_set_icon)(shell_link, icon, 0)

        persist = ctypes.c_void_p()
        _vfn(shell_link, 0, t_qi)(
            shell_link, ctypes.byref(_IID_IPERSISTFILE), ctypes.byref(persist))
        ok = False
        if persist:
            hr = _vfn(persist, 6, t_save)(persist, lnk_path, 1)
            ok = (hr == 0)
            _vfn(persist, 2, t_release)(persist)
        _vfn(shell_link, 2, t_release)(shell_link)
        return ok and os.path.exists(lnk_path)
    except Exception:
        return False


# ============================================================ 注册表卸载项

def write_uninstall_key(install_dir: str):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REG) as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, "MAA 挂机助手")
        winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, "1.2.0")
        winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ,
                          os.path.join(install_dir, EXE_NAME))
        winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, install_dir)
        winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ,
                          '"%s" --uninstall' % os.path.join(install_dir, "uninstall.exe"))
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, "MAA-Pipeline")


def remove_uninstall_key():
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REG)
    except OSError:
        pass


# ============================================================ 安装逻辑（JS 可调用）

class InstallerApi:
    def __init__(self):
        self.zf = locate_payload()
        self.payload_has_maa = False
        self.payload_bytes = 0
        if self.zf is not None:
            names = self.zf.namelist()
            self.payload_has_maa = any(n.upper().startswith("MAA/") for n in names)
            self.payload_bytes = sum(i.file_size for i in self.zf.infolist())
        self.progress = {"phase": "idle", "pct": 0, "msg": "", "error": ""}

    def get_state(self):
        return {
            "default_dir": DEFAULT_DIR,
            "has_payload": self.zf is not None,
            "payload_has_maa": self.payload_has_maa,
            "payload_mb": round(self.payload_bytes / 1048576),
            "mumu": find_mumu(),
            "webview2": webview2_installed(),
        }

    def pick_dir(self):
        import webview

        if not webview.windows:
            return None
        dlg = getattr(webview, "FOLDER_DIALOG", 2)
        result = webview.windows[0].create_file_dialog(dlg)
        if result:
            return result[0] if isinstance(result, (list, tuple)) else result
        return None

    def get_progress(self):
        return dict(self.progress)

    def install(self, target_dir, make_desktop=True, make_menu=True, launch_after=True):
        threading.Thread(
            target=self._do_install,
            args=(target_dir, bool(make_desktop), bool(make_menu), bool(launch_after)),
            daemon=True,
        ).start()
        return True

    def _set(self, phase, pct, msg=""):
        self.progress.update({"phase": phase, "pct": pct, "msg": msg})

    def _do_install(self, target_dir, make_desktop, make_menu, launch_after):
        try:
            target_dir = os.path.abspath(target_dir)
            if self.zf is None:
                raise RuntimeError("安装包数据缺失（payload 未找到）")

            self._set("run", 5, "创建目录…")
            os.makedirs(target_dir, exist_ok=True)

            infos = [i for i in self.zf.infolist()]
            total = max(1, len(infos))
            root_abs = os.path.abspath(target_dir) + os.sep
            for idx, info in enumerate(infos):
                name = info.filename.replace("\\", "/")
                dest = os.path.normpath(os.path.join(target_dir, name))
                if not (dest == os.path.abspath(target_dir) or dest.startswith(root_abs)):
                    continue                       # 防路径穿越
                if info.is_dir():
                    os.makedirs(dest, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with self.zf.open(info) as src, open(dest, "wb") as out:
                        shutil.copyfileobj(src, out, 1024 * 1024)
                if idx % 30 == 0 or idx == total - 1:
                    pct = 10 + int(70 * (idx + 1) / total)
                    self._set("run", pct, "释放文件 %d/%d" % (idx + 1, total))

            exe_path = os.path.join(target_dir, EXE_NAME)
            if not os.path.isfile(exe_path):
                raise RuntimeError("安装数据里缺少 %s" % EXE_NAME)

            self._set("run", 85, "创建快捷方式…")
            icon = exe_path + ",0"
            desc = "启动模拟器 → 等待就绪 → 拉起 MAA 自动挂机"
            if make_desktop:
                desktop = os.path.join(
                    os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop")
                if os.path.isdir(desktop):
                    create_lnk(exe_path, os.path.join(desktop, LINK_NAME),
                               target_dir, desc, icon)
            if make_menu:
                menu = os.path.join(
                    os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                    "Start Menu", "Programs")
                if os.path.isdir(menu):
                    create_lnk(exe_path, os.path.join(menu, LINK_NAME),
                               target_dir, desc, icon)

            self._set("run", 92, "写入卸载信息…")
            shutil.copyfile(SELF_PATH, os.path.join(target_dir, "uninstall.exe"))
            write_uninstall_key(target_dir)

            self._set("done", 100, "安装完成")
            if launch_after:
                subprocess.Popen([exe_path], cwd=target_dir)
        except Exception as exc:  # noqa: BLE001
            self.progress.update({"phase": "error", "pct": 100, "msg": "",
                                  "error": "%s: %s" % (type(exc).__name__, exc)})


def run_uninstall():
    """卸载：确认 → 删快捷方式/注册表 → 清空安装目录（自身延迟删除）。"""
    install_dir = os.path.dirname(SELF_PATH)
    text = "确定要卸载 MAA 挂机助手吗？\n\n安装目录（含日志与配置）将被删除：\n%s" % install_dir
    MB_OKCANCEL, IDOK, MB_ICONQUESTION = 0x1, 1, 0x20
    if ctypes.windll.user32.MessageBoxW(
            None, text, "卸载确认", MB_OKCANCEL | MB_ICONQUESTION) != IDOK:
        return 0
    desktop = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop")
    menu = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                        "Start Menu", "Programs")
    for d in (desktop, menu):
        try:
            p = os.path.join(d, LINK_NAME)
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass
    remove_uninstall_key()
    for name in os.listdir(install_dir):
        p = os.path.join(install_dir, name)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
        except OSError:
            pass
    try:
        MOVEFILE_DELAY_UNTIL_REBOOT = 0x4
        ctypes.windll.kernel32.MoveFileExW(install_dir, None, MOVEFILE_DELAY_UNTIL_REBOOT)
    except Exception:
        pass
    ctypes.windll.user32.MessageBoxW(
        None, "已卸载完成。个别被占用的文件将在重启后自动清理。", "卸载", 0x40)
    return 0


# ============================================================ 入口

def main():
    if "--uninstall" in sys.argv:
        return run_uninstall()

    import webview

    api = InstallerApi()
    candidates = [
        os.path.join(os.path.dirname(SELF_PATH), "installer_ui.html"),
        os.path.join(getattr(sys, "_MEIPASS", "") or ".", "installer_ui.html"),
    ]
    ui = next((c for c in candidates if os.path.exists(c)), None)
    if ui is None:
        ctypes.windll.user32.MessageBoxW(
            None, "找不到安装界面文件 installer_ui.html", APP_TITLE, 0x10)
        return 1
    webview.create_window(
        APP_TITLE, ui, js_api=api,
        width=720, height=600, resizable=False,
        background_color="#F7F7F5",
    )
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
