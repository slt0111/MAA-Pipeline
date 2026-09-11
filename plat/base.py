# -*- coding: utf-8 -*-
"""平台适配器接口与共用规范化逻辑。"""

from __future__ import annotations

import os
import signal

from plat.util import first_json_object, json_code, run_cmd, which


class Platform:
    """各操作系统实现此接口。方法默认给出安全的 POSIX / 空实现。"""

    name = "base"
    display_name = "未知"
    mumu_cli_label = "模拟器 CLI"
    maa_label = "MAA 主程序"
    maa_process_names = ("MAA.exe", "MAA")
    maa_connect_config = "General"

    # ---------- 默认路径（写入新配置时的占位，不覆盖用户已保存的值）----------

    def default_config_overlay(self, app_dir: str) -> dict:
        return {}

    def default_mumu_cli(self) -> str:
        return ""

    def default_mumu_adb(self) -> str:
        return ""

    def default_maa_exe(self, app_dir: str) -> str:
        return os.path.join(app_dir, "MAA", "MAA.exe")

    # ---------- 探测 ----------

    def find_mumu_cli(self):
        return None

    def find_mumu_adb(self, cli_path=None):
        if cli_path:
            sibling = os.path.join(os.path.dirname(cli_path), "adb.exe")
            if os.path.isfile(sibling):
                return sibling
            sibling = os.path.join(os.path.dirname(cli_path), "adb")
            if os.path.isfile(sibling) and os.access(sibling, os.X_OK):
                return sibling
        return which("adb")

    def find_maa_exe(self, app_dir: str):
        return None

    def missing_mumu_label(self) -> str:
        return "MuMu 模拟器（%s）" % self.mumu_cli_label

    def missing_maa_label(self) -> str:
        return "%s" % self.maa_label

    # ---------- ADB ----------

    def default_adb_address(self, vm_index: int, info=None) -> str:
        port = self._adb_port_from_info(info)
        if port:
            return "127.0.0.1:%s" % port
        return "127.0.0.1:%d" % (16384 + 32 * int(vm_index or 0))

    def _adb_port_from_info(self, info):
        if not isinstance(info, dict):
            return None
        for key in ("adb_port", "adbPort", "customAdbPort", "forward_port"):
            val = info.get(key)
            if val in (None, ""):
                continue
            try:
                return int(val)
            except (TypeError, ValueError):
                text = str(val)
                if ":" in text:
                    return text.rsplit(":", 1)[-1]
                return text
        addr = info.get("adb_address") or info.get("adb") or info.get("address")
        if isinstance(addr, str) and ":" in addr:
            return addr.rsplit(":", 1)[-1]
        return None

    # ---------- 进程 ----------

    def process_running(self, image_name: str) -> bool:
        if not image_name:
            return False
        rc, out, _ = run_cmd(["pgrep", "-af", image_name], timeout=15)
        if rc != 0:
            return False
        needle = image_name.lower()
        for line in out.splitlines():
            if needle in line.lower() and "pgrep" not in line.lower():
                return True
        return False

    def maa_running(self, maa_exe: str = "") -> bool:
        names = list(self.maa_process_names)
        if maa_exe:
            base = os.path.basename(maa_exe.rstrip("/"))
            if base.endswith(".app"):
                base = base[:-4]
            if base and base not in names:
                names.append(base)
        return any(self.process_running(name) for name in names)

    # ---------- 模拟器 CLI 参数（供测试断言，不真正执行）----------

    def mumu_info_argv(self, cli: str, vm_index: int) -> list:
        return [cli, "info", "-v", str(vm_index)]

    def mumu_control_argv(self, cli: str, vm_index: int, action: str) -> list:
        mapped = {"launch": "launch", "shutdown": "shutdown"}.get(action, action)
        return [cli, "control", "-v", str(vm_index), mapped]

    def mumu_close_manager_argv(self, cli: str) -> list:
        return [cli, "main", "close"]

    def parse_mumu_info(self, text: str, vm_index: int = 0) -> dict:
        data = first_json_object(text)
        if data is None:
            raise ValueError("模拟器状态返回异常：%s" % (text or "")[:200])
        return self.normalize_mumu_info(data, vm_index)

    def normalize_mumu_info(self, raw, vm_index: int = 0) -> dict:
        """把各家 CLI 的 JSON 收成引擎使用的四个字段。"""
        if not isinstance(raw, dict):
            if isinstance(raw, list) and raw:
                item = raw[0]
                if isinstance(item, dict):
                    raw = item
                else:
                    raw = {}
            else:
                raw = {}

        data = raw
        inner = raw.get("data")
        if isinstance(inner, dict):
            data = inner
            nested = inner.get(str(vm_index)) or inner.get(vm_index)
            if isinstance(nested, dict):
                data = nested
        else:
            keyed = raw.get(str(vm_index)) or raw.get(vm_index)
            if isinstance(keyed, dict):
                data = keyed

        def pick(*names, default=None):
            for name in names:
                if isinstance(data, dict) and data.get(name) not in (None, ""):
                    return data[name]
            return default

        status = str(pick("status", "state", "player_state", "vm_state") or "").lower()
        started = pick(
            "is_process_started", "is_started", "is_running", "started",
            "process_started", "running",
        )
        android = pick(
            "is_android_started", "android_started", "is_android_running",
            "android_ready", "is_ready",
        )
        if android is None:
            android = any(token in status for token in (
                "android_started", "ready", "running", "started", "online",
            )) and "stop" not in status and "close" not in status
        if started is None:
            started = bool(android) or any(token in status for token in (
                "running", "started", "launching", "online",
            ))

        port = self._adb_port_from_info(data)
        if port is None:
            port = self._adb_port_from_info(raw)

        return {
            "index": pick("index", "vm_index", "idx") if pick("index", "vm_index", "idx") is not None else vm_index,
            "name": pick("name", "vm_name", "vmName") or "",
            "is_process_started": bool(started),
            "is_android_started": bool(android),
            "adb_port": port,
            "raw": raw,
        }

    def mumu_info(self, cli: str, vm_index: int) -> dict:
        rc, out, err = run_cmd(self.mumu_info_argv(cli, vm_index), timeout=25)
        if rc != 0:
            raise RuntimeError(err.strip() or out.strip() or "未知错误")
        try:
            return self.parse_mumu_info(out or err, vm_index)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

    def mumu_control(self, cli: str, vm_index: int, action: str):
        rc, out, err = run_cmd(self.mumu_control_argv(cli, vm_index, action), timeout=60)
        return rc, (out + err).strip()

    def mumu_close_manager(self, cli: str):
        argv = self.mumu_close_manager_argv(cli)
        if not argv:
            return 0, ""
        rc, out, err = run_cmd(argv, timeout=60)
        return rc, (out + err).strip()

    def control_rejected(self, output: str) -> bool:
        code = json_code(output)
        return code not in (None, 0)

    # ---------- MAA ----------

    def is_maa_cli(self, exe: str) -> bool:
        """maa-cli 一般是 Homebrew 的 ``maa`` / ``maa-cli``，不是 MAA.app 里的同名二进制。"""
        raw = (exe or "").rstrip("/")
        base = os.path.basename(raw).lower()
        if base == "maa-cli":
            return True
        if base != "maa":
            return False
        norm = raw.replace("\\", "/").lower()
        if ".app/contents/macos" in norm:
            return False
        return True

    def resolve_maa_binary(self, exe: str) -> str:
        return exe or ""

    def resolve_maa_dir(self, exe: str, config_dir: str = "") -> str:
        if (config_dir or "").strip():
            return os.path.abspath(config_dir.strip())
        exe = self.resolve_maa_binary(exe)
        return os.path.dirname(exe) if exe else ""

    def maa_config_path(self, maa_dir: str) -> str:
        return os.path.join(maa_dir or "", "config", "gui.new.json")

    def maa_log_path(self, maa_dir: str) -> str:
        return os.path.join(maa_dir or "", "debug", "gui.log")

    def maa_argv(self, exe: str, profile: str) -> list:
        binary = self.resolve_maa_binary(exe)
        if self.is_maa_cli(exe) or self.is_maa_cli(binary):
            if profile:
                return [binary, "-p", profile, "run"]
            return [binary, "run"]
        if profile:
            return [binary, "--config", profile]
        return [binary]

    def maa_cwd(self, exe: str, maa_dir: str) -> str:
        return maa_dir or os.path.dirname(self.resolve_maa_binary(exe) or "") or None

    def uses_gui_inject(self, exe: str) -> bool:
        return not self.is_maa_cli(exe)

    # ---------- 关闭 / 桌面 ----------

    def close_pid_gracefully(self, pid: int) -> int:
        """温和请求进程退出。返回尝试次数（Win32 是投递的窗口数）。

        不会向自身发信号：单元测试会用 os.getpid() 探测此函数是否可安全调用。
        """
        if not pid:
            return 0
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return 0
        if pid == os.getpid():
            return 0
        try:
            os.kill(pid, signal.SIGTERM)
            return 1
        except Exception:
            return 0

    def open_folder(self, path: str) -> bool:
        if not path:
            return False
        rc, _, _ = run_cmd(["xdg-open", path], timeout=15)
        return rc == 0

    def show_error_box(self, text: str, title: str = "MAA 一键挂机 - 启动失败") -> None:
        return

    def focus_window(self, title: str) -> bool:
        return False

    def apply_window_icon(self, title: str, icon_path: str | None) -> None:
        return

    def desktop_notify(self, title: str, body: str) -> bool:
        return False

    def tray_supported(self) -> bool:
        return False

    def selftest_tray(self) -> tuple:
        """返回 (ok, lines, problems)。"""
        return True, ["  [i] 当前平台不提供 Win32 托盘，跳过托盘自检"], []
