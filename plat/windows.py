# -*- coding: utf-8 -*-
"""Windows 适配：mumu-cli.exe、MAA.exe、tasklist、WM_CLOSE、托盘相关 Win32。"""

from __future__ import annotations

import os

from plat.base import Platform
from plat.util import run_cmd


_MUMU_REL_TARGETS = [r"nx_main\mumu-cli.exe", r"shell\mumu-cli.exe"]
_MUMU_SEARCH_ROOTS = [
    r"Program Files\Netease",
    r"Program Files (x86)\Netease",
    r"Netease",
    r"Games\Netease",
    r"MuMu",
    r"Program Files",
]


def _drive_letters():
    out = []
    for letter in "CDEFGH":
        if os.path.isdir("%s:\\" % letter):
            out.append(letter)
    return out


class WindowsPlatform(Platform):
    name = "windows"
    display_name = "Windows"
    mumu_cli_label = "mumu-cli.exe"
    maa_label = "MAA 主程序（MAA.exe）"
    maa_process_names = ("MAA.exe",)
    maa_connect_config = "MuMuEmulator12"

    def default_mumu_cli(self) -> str:
        return r"C:\Program Files\Netease\MuMu\nx_main\mumu-cli.exe"

    def default_mumu_adb(self) -> str:
        return r"C:\Program Files\Netease\MuMu\nx_main\adb.exe"

    def default_maa_exe(self, app_dir: str) -> str:
        return os.path.join(app_dir, "MAA", "MAA.exe")

    def default_adb_address(self, vm_index: int, info=None) -> str:
        addr_port = self._adb_port_from_info(info)
        if addr_port:
            return "127.0.0.1:%s" % addr_port
        return "127.0.0.1:%d" % (16384 + 32 * int(vm_index or 0))

    def find_mumu_cli(self):
        drives = _drive_letters()
        for drive in drives:
            for root_rel in _MUMU_SEARCH_ROOTS:
                root = r"%s:\%s" % (drive, root_rel)
                if not os.path.isdir(root):
                    continue
                for rel in _MUMU_REL_TARGETS:
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
                    for rel in _MUMU_REL_TARGETS:
                        cand = os.path.join(root, name, rel)
                        if os.path.isfile(cand):
                            return cand
        return None

    def find_mumu_adb(self, cli_path=None):
        if cli_path:
            sibling = os.path.join(os.path.dirname(cli_path), "adb.exe")
            if os.path.isfile(sibling):
                return sibling
        return None

    def find_maa_exe(self, app_dir: str):
        cands = [
            os.path.join(app_dir, "MAA", "MAA.exe"),
            os.path.join(os.path.dirname(app_dir), "MAA", "MAA.exe"),
        ]
        for drive in _drive_letters():
            cands += [
                r"%s:\MAA\MAA.exe" % drive,
                r"%s:\Program Files\MAA\MAA.exe" % drive,
                r"%s:\Games\MAA\MAA.exe" % drive,
            ]
        return next((c for c in cands if os.path.isfile(c)), None)

    def process_running(self, image_name: str) -> bool:
        rc, out, _ = run_cmd(
            ["tasklist", "/FI", "IMAGENAME eq %s" % image_name, "/NH"], timeout=15
        )
        return rc == 0 and image_name.lower() in out.lower()

    def close_pid_gracefully(self, pid: int) -> int:
        """给指定进程的所有顶层窗口发 WM_CLOSE。"""
        try:
            import ctypes
            import ctypes.wintypes as wt
        except Exception:
            return 0
        try:
            user32 = ctypes.windll.user32
        except Exception:
            return 0
        WM_CLOSE = 0x0010
        count = 0

        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def _enum(hwnd, _lparam):
            nonlocal count
            wpid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                count += 1
            return True

        try:
            user32.EnumWindows(_enum, 0)
        except Exception:
            pass
        return count

    def open_folder(self, path: str) -> bool:
        try:
            os.startfile(path)  # type: ignore[attr-defined]
            return True
        except Exception:
            return False

    def show_error_box(self, text: str, title: str = "MAA 一键挂机 - 启动失败") -> None:
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
        except Exception:
            pass

    def focus_window(self, title: str) -> bool:
        try:
            import ctypes

            u = ctypes.windll.user32
            hwnd = u.FindWindowW(None, title)
            if not hwnd:
                return False
            u.ShowWindowAsync(hwnd, 9)
            u.SetForegroundWindow(hwnd)
            return True
        except Exception:
            return False

    def apply_window_icon(self, title: str, icon_path: str | None) -> None:
        if not icon_path or not os.path.exists(icon_path):
            return
        try:
            import ctypes

            u = ctypes.windll.user32
            hwnd = u.FindWindowW(None, title)
            if not hwnd:
                return
            IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
            big = u.LoadImageW(None, icon_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            small = u.LoadImageW(None, icon_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
            if big:
                u.SendMessageW(hwnd, 0x80, 1, big)
            if small:
                u.SendMessageW(hwnd, 0x80, 0, small)
        except Exception:
            pass

    def tray_supported(self) -> bool:
        return True

    def selftest_tray(self) -> tuple:
        """保留与历史 --selftest 相同的 Win32 托盘探测。"""
        lines = []
        problems = []
        try:
            import ctypes
            import ctypes.wintypes as wt

            LRESULT = ctypes.c_ssize_t
            WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wt.DWORD),
                    ("Data2", wt.WORD),
                    ("Data3", wt.WORD),
                    ("Data4", ctypes.c_byte * 8),
                ]

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [
                    ("style", wt.UINT),
                    ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wt.HINSTANCE),
                    ("hIcon", wt.HICON),
                    ("hCursor", wt.HANDLE),
                    ("hbrBackground", wt.HBRUSH),
                    ("lpszMenuName", wt.LPCWSTR),
                    ("lpszClassName", wt.LPCWSTR),
                ]

            class NOTIFYICONDATAW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wt.DWORD),
                    ("hWnd", wt.HWND),
                    ("uID", wt.UINT),
                    ("uFlags", wt.UINT),
                    ("uCallbackMessage", wt.UINT),
                    ("hIcon", wt.HICON),
                    ("szTip", wt.WCHAR * 128),
                    ("dwState", wt.DWORD),
                    ("dwStateMask", wt.DWORD),
                    ("szInfo", wt.WCHAR * 256),
                    ("uVersion", wt.UINT),
                    ("szInfoTitle", wt.WCHAR * 64),
                    ("dwInfoFlags", wt.DWORD),
                    ("guidItem", GUID),
                    ("hBalloonIcon", wt.HICON),
                ]

            NIM_ADD, NIM_DELETE = 0, 2
            NIF_ICON, NIF_TIP = 0x02, 0x04
            IDI_APPLICATION = 32512

            u = ctypes.windll.user32
            u.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
            u.DefWindowProcW.restype = LRESULT
            u.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
            u.RegisterClassW.restype = wt.ATOM
            u.CreateWindowExW.argtypes = [
                wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p,
            ]
            u.CreateWindowExW.restype = wt.HWND
            u.LoadIconW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
            u.LoadIconW.restype = wt.HICON
            u.DestroyWindow.argtypes = [wt.HWND]
            size = ctypes.sizeof(NOTIFYICONDATAW)
            lines.append("  [i] NOTIFYICONDATAW 大小 = %d 字节（x64 期望 976）" % size)
            hinst = ctypes.windll.kernel32.GetModuleHandleW(None)

            def _st_wndproc(hwnd, msg, wparam, lparam):
                return u.DefWindowProcW(hwnd, msg, wparam, lparam)

            cb = WNDPROC(_st_wndproc)
            wc = WNDCLASSW()
            wc.lpfnWndProc = cb
            wc.hInstance = hinst
            wc.lpszClassName = "MAAPipelineSelfTest"
            atom = u.RegisterClassW(ctypes.byref(wc))
            lines.append("  [i] RegisterClass 返回 atom = %s" % atom)
            hwnd = u.CreateWindowExW(
                0, "MAAPipelineSelfTest", "t", 0, 0, 0, 0, 0, None, None, hinst, None
            )
            if hwnd:
                nid = NOTIFYICONDATAW()
                nid.cbSize = size
                nid.hWnd = hwnd
                nid.uID = 99
                nid.uFlags = NIF_ICON | NIF_TIP
                nid.hIcon = u.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
                nid.szTip = "selftest"
                added = ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
                if added:
                    ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                    lines.append("  [OK] 托盘图标创建成功（已移除测试图标）")
                else:
                    lines.append("  [!!] Shell_NotifyIcon 返回失败")
                    problems.append("托盘图标不可用")
                u.DestroyWindow(hwnd)
            else:
                lines.append("  [!!] 隐藏窗口创建失败（atom=%s）" % atom)
                problems.append("托盘隐藏窗口创建失败")
            return not problems, lines, problems
        except Exception as exc:  # noqa: BLE001
            lines.append("  [!!] 托盘自检异常：%s" % exc)
            problems.append("托盘自检异常")
            return False, lines, problems
