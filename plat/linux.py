# -*- coding: utf-8 -*-
"""Linux 适配：给 CI / 无模拟器主机用。不假装能驱动 MuMu。"""

from __future__ import annotations

from plat.base import Platform


class LinuxPlatform(Platform):
    name = "linux"
    display_name = "Linux"
    mumu_cli_label = "模拟器 CLI"
    maa_label = "MAA 主程序"
    maa_process_names = ("MAA.exe", "MAA", "maa")
    maa_connect_config = "CompatPOSIXShell"

    def default_adb_address(self, vm_index: int, info=None) -> str:
        # 与历史 Windows 公式一致，避免 Linux CI 上现有测试/默认值漂移。
        port = self._adb_port_from_info(info)
        if port:
            return "127.0.0.1:%s" % port
        return "127.0.0.1:%d" % (16384 + 32 * int(vm_index or 0))

    def selftest_tray(self) -> tuple:
        return True, ["  [i] Linux 无 Win32 托盘，跳过托盘自检"], []
