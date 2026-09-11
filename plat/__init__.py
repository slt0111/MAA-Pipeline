# -*- coding: utf-8 -*-
"""操作系统适配层：路径探测、模拟器 / ADB / MAA 进程、窗口与通知。

流水线引擎（阶段、多账号、定时、通知、HTTP UI）保持平台无关；
本包只隔离 Win32 / mumutool / POSIX 差异。默认适配器按 ``sys.platform`` 选择。
"""

from __future__ import annotations

import sys

from plat.base import Platform
from plat.util import decode, json_code, run_cmd

__all__ = [
    "Platform",
    "create",
    "current",
    "decode",
    "detect_os",
    "json_code",
    "reset",
    "run_cmd",
    "set_current",
]

_INSTANCE: Platform | None = None


def detect_os(name: str | None = None) -> str:
    """把 sys.platform / 别名归一成 windows / macos / linux。"""
    raw = (name if name is not None else sys.platform) or ""
    raw = str(raw).strip().lower()
    if raw in ("windows", "macos", "linux"):
        return raw
    if raw.startswith("win"):
        return "windows"
    if raw == "darwin":
        return "macos"
    return "linux"


def create(name: str | None = None) -> Platform:
    kind = detect_os(name)
    if kind == "windows":
        from plat.windows import WindowsPlatform

        return WindowsPlatform()
    if kind == "macos":
        from plat.macos import MacOSPlatform

        return MacOSPlatform()
    from plat.linux import LinuxPlatform

    return LinuxPlatform()


def current() -> Platform:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = create()
    return _INSTANCE


def set_current(name_or_obj) -> Platform:
    """测试或显式覆盖当前适配器。传入平台名或 Platform 实例。"""
    global _INSTANCE
    if isinstance(name_or_obj, Platform):
        _INSTANCE = name_or_obj
    else:
        _INSTANCE = create(name_or_obj)
    return _INSTANCE


def reset() -> None:
    """清掉缓存的适配器，下次 current() 按真实 OS 重建。"""
    global _INSTANCE
    _INSTANCE = None
