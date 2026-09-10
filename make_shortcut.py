# -*- coding: utf-8 -*-
"""
在桌面创建「MAA 一键挂机」快捷方式。

不依赖 pywin32，直接用 ctypes 调用 Windows 的 IShellLink / IPersistFile 接口。
生成后会立刻回读一次，确认快捷方式可解析。

用法： python make_shortcut.py
"""

import ctypes
import ctypes.wintypes as wt
import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(APP_DIR, "pipeline.py")
VBS = os.path.join(APP_DIR, "start-pipeline.vbs")
EXE = os.path.join(APP_DIR, "MAA挂机助手.exe")

# 优先用打包好的独立 exe（不依赖 Python），回退到 pythonw / VBS 启动器
if os.path.exists(EXE):
    TARGET = EXE
    ARGUMENTS = ""
    ICON = EXE + ",0"
    LAUNCH_MODE = "独立 exe"
else:
    # 没打包 exe 时，退回到用 pythonw 直接跑脚本：
    # 优先当前解释器同目录的 pythonw.exe，其次工具目录下的便携 Python
    PY_CANDIDATES = []
    cur = sys.executable
    if cur:
        PY_CANDIDATES.append(os.path.join(os.path.dirname(cur), "pythonw.exe"))
    PY_CANDIDATES.append(os.path.join(APP_DIR, "python", "pythonw.exe"))
    _PY = next((p for p in PY_CANDIDATES if os.path.exists(p)), None)
    if _PY:
        TARGET = _PY
        ARGUMENTS = '"%s"' % SCRIPT
        ICON = os.path.join(APP_DIR, "app.ico")
        LAUNCH_MODE = "直接调用 pythonw（不经脚本宿主）"
    else:
        # 找不到 pythonw 时退回 VBS 启动器（它内部还有一层 PATH 兜底）
        TARGET = r"C:\Windows\System32\wscript.exe"
        ARGUMENTS = '"%s"' % VBS
        ICON = VBS
        LAUNCH_MODE = "经 VBS 启动器"

WORKDIR = APP_DIR
DESCRIPTION = "启动模拟器 → 等待安卓就绪 → 拉起 MAA 自动挂机"
LINK_NAME = "MAA 一键挂机.lnk"

CLSCTX_INPROC_SERVER = 0x1


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, text):
        text = text.strip("{}")
        parts = text.split("-")
        guid = cls()
        guid.Data1 = int(parts[0], 16)
        guid.Data2 = int(parts[1], 16)
        guid.Data3 = int(parts[2], 16)
        tail = parts[3] + parts[4]
        for i in range(8):
            guid.Data4[i] = int(tail[i * 2:i * 2 + 2], 16)
        return guid


CLSID_SHELLLINK = GUID.parse("00021401-0000-0000-C000-000000000046")
IID_ISHELLLINKW = GUID.parse("000214F9-0000-0000-C000-000000000046")
IID_IPERSISTFILE = GUID.parse("0000010B-0000-0000-C000-000000000046")

ole32 = ctypes.oledll.ole32
ole32.CoCreateInstance.argtypes = [
    ctypes.POINTER(GUID), ctypes.c_void_p, wt.DWORD,
    ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p),
]
ole32.CoCreateInstance.restype = ctypes.c_long


def vfn(ptr, index, prototype):
    """取出 COM 接口虚表里第 index 个函数的可调用对象。"""
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    addr = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[index]
    return prototype(addr)


LRESULT = ctypes.c_long


def create(lnk_path: str) -> str:
    ole32.CoInitialize(None)
    shell_link = ctypes.c_void_p()
    ole32.CoCreateInstance(
        ctypes.byref(CLSID_SHELLLINK), None, CLSCTX_INPROC_SERVER,
        ctypes.byref(IID_ISHELLLINKW), ctypes.byref(shell_link),
    )

    p_set_path = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_wchar_p)
    p_set_args = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_wchar_p)
    p_set_dir = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_wchar_p)
    p_set_desc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_wchar_p)
    p_set_icon = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
    p_qi = ctypes.WINFUNCTYPE(
        LRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
    )
    p_release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)

    vfn(shell_link, 20, p_set_path)(shell_link, TARGET)
    vfn(shell_link, 11, p_set_args)(shell_link, ARGUMENTS)
    vfn(shell_link, 9, p_set_dir)(shell_link, WORKDIR)
    vfn(shell_link, 7, p_set_desc)(shell_link, DESCRIPTION)
    vfn(shell_link, 17, p_set_icon)(shell_link, ICON, 0)

    persist = ctypes.c_void_p()
    vfn(shell_link, 0, p_qi)(
        shell_link, ctypes.byref(IID_IPERSISTFILE), ctypes.byref(persist)
    )
    if not persist:
        raise OSError("获取 IPersistFile 失败")

    p_save = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
    p_getpath = ctypes.WINFUNCTYPE(
        LRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int,
        ctypes.c_void_p, ctypes.c_uint,
    )

    hr = vfn(persist, 6, p_save)(persist, lnk_path, 1)
    if hr != 0:
        raise OSError("保存快捷方式失败，HRESULT=0x%08X" % (hr & 0xFFFFFFFF))

    # 回读验证
    buf = ctypes.create_unicode_buffer(1024)
    vfn(shell_link, 3, p_getpath)(shell_link, buf, 1024, None, 0)
    resolved = buf.value

    vfn(persist, 2, p_release)(persist)
    vfn(shell_link, 2, p_release)(shell_link)
    return resolved


def main():
    desktop = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop")
    if not os.path.isdir(desktop):
        print("找不到桌面目录：%s" % desktop)
        return 1
    lnk = os.path.join(desktop, LINK_NAME)
    try:
        resolved = create(lnk)
    except Exception as exc:  # noqa: BLE001
        print("创建失败：%s" % exc)
        return 1
    ok = os.path.exists(lnk)
    print("快捷方式：%s" % lnk)
    print("文件存在：%s" % ok)
    print("启动目标：%s" % TARGET)
    print("参数：%s" % ARGUMENTS)
    print("启动方式：%s" % LAUNCH_MODE)
    print("目标解析：%s" % resolved)
    if ok and resolved:
        print("结果：成功")
        return 0
    print("结果：需要人工检查")
    return 1


if __name__ == "__main__":
    sys.exit(main())
