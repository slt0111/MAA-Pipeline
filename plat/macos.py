# -*- coding: utf-8 -*-
"""macOS 适配：MuMu for Mac 的 mumutool、官方 MAA.app（优先）或 maa-cli。"""

from __future__ import annotations

import os

from plat.base import Platform
from plat.util import run_cmd, which


_MUMUTOOL_CANDIDATES = (
    "/Applications/MuMuPlayer.app/Contents/MacOS/mumutool",
    "/Applications/MuMuPlayer.app/Contents/Resources/mumutool",
    "/Applications/MuMu模拟器.app/Contents/MacOS/mumutool",
    "/Applications/MuMu模拟器.app/Contents/Resources/mumutool",
    "/Applications/MuMuPlayer Pro.app/Contents/MacOS/mumutool",
    "/Applications/MuMuNxDevice.app/Contents/MacOS/mumutool",
    os.path.expanduser("~/Applications/MuMuPlayer.app/Contents/MacOS/mumutool"),
    os.path.expanduser("~/Applications/MuMu模拟器.app/Contents/MacOS/mumutool"),
)

_MUMU_APP_NAMES = (
    "MuMuPlayer.app",
    "MuMu模拟器.app",
    "MuMuPlayer Pro.app",
    "MuMuNxDevice.app",
)

_MAA_APP_CANDIDATES = (
    "/Applications/MAA.app",
    os.path.expanduser("~/Applications/MAA.app"),
)

_MAA_SUPPORT_DIRS = (
    os.path.expanduser("~/Library/Application Support/MAA"),
    os.path.expanduser("~/Library/Application Support/maa"),
    os.path.expanduser("~/Library/Application Support/com.loong.maa"),
)


def _walk_app_for(name: str, root: str, max_depth: int = 4):
    """在 .app 包里浅层寻找名为 name 的可执行文件。"""
    if not os.path.isdir(root):
        return None
    target = name.lower()
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth > max_depth:
            dirnames[:] = []
            continue
        for fn in filenames:
            if fn.lower() == target:
                path = os.path.join(dirpath, fn)
                if os.path.isfile(path) and os.access(path, os.X_OK):
                    return path
    return None


class MacOSPlatform(Platform):
    name = "macos"
    display_name = "macOS"
    mumu_cli_label = "mumutool"
    maa_label = "MAA.app / maa-cli"
    maa_process_names = ("MAA", "MAA.exe", "maa")
    maa_connect_config = "CompatMac"

    def default_config_overlay(self, app_dir: str) -> dict:
        return {
            "mumu": {
                "cli": self.default_mumu_cli(),
                "adb": self.default_mumu_adb(),
            },
            "maa": {
                "exe": self.default_maa_exe(app_dir),
            },
        }

    def default_mumu_cli(self) -> str:
        return "/Applications/MuMuPlayer.app/Contents/MacOS/mumutool"

    def default_mumu_adb(self) -> str:
        return "/opt/homebrew/bin/adb"

    def default_maa_exe(self, app_dir: str) -> str:
        local_app = os.path.join(app_dir, "MAA.app")
        if os.path.isdir(local_app):
            return local_app
        return "/Applications/MAA.app"

    def default_adb_address(self, vm_index: int, info=None) -> str:
        """Mac 端口不是 Windows 的 16384+32*index，优先读 mumutool info。"""
        port = self._adb_port_from_info(info)
        if port:
            return "127.0.0.1:%s" % port
        return ""

    def find_mumu_cli(self):
        for path in _MUMUTOOL_CANDIDATES:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        found = which("mumutool")
        if found:
            return found
        for base in ("/Applications", os.path.expanduser("~/Applications")):
            if not os.path.isdir(base):
                continue
            try:
                names = os.listdir(base)
            except OSError:
                continue
            for name in names:
                if "mumu" not in name.lower() or not name.endswith(".app"):
                    continue
                hit = _walk_app_for("mumutool", os.path.join(base, name))
                if hit:
                    return hit
        return None

    def find_mumu_adb(self, cli_path=None):
        cands = []
        if cli_path:
            root = cli_path
            # 从 mumutool 往上找到 .app，再在包内找 adb
            while root and root != "/":
                if root.endswith(".app"):
                    hit = _walk_app_for("adb", root, max_depth=5)
                    if hit:
                        return hit
                    break
                root = os.path.dirname(root)
            cands.append(os.path.join(os.path.dirname(cli_path), "adb"))
        cands += [
            "/opt/homebrew/bin/adb",
            "/usr/local/bin/adb",
            "/Applications/MuMuPlayer.app/Contents/MacOS/adb",
            "/Applications/MuMu模拟器.app/Contents/MacOS/adb",
        ]
        for path in cands:
            if path and os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        return which("adb")

    def find_maa_exe(self, app_dir: str):
        cands = [
            os.path.join(app_dir, "MAA.app"),
            os.path.join(app_dir, "MAA", "MAA.app"),
            os.path.join(os.path.dirname(app_dir), "MAA.app"),
        ]
        cands.extend(_MAA_APP_CANDIDATES)
        for path in cands:
            if os.path.isdir(path):
                return path
            if os.path.isfile(path):
                return path
        binary = which("MAA")
        if binary:
            return binary
        cli = which("maa") or which("maa-cli")
        if cli:
            return cli
        return None

    def resolve_maa_binary(self, exe: str) -> str:
        exe = (exe or "").rstrip("/")
        if not exe:
            return ""
        if exe.endswith(".app") and os.path.isdir(exe):
            macos_dir = os.path.join(exe, "Contents", "MacOS")
            for name in ("MAA", "Maa", "MeoAsstGui", "MaaWpfGui"):
                cand = os.path.join(macos_dir, name)
                if os.path.isfile(cand):
                    return cand
            if os.path.isdir(macos_dir):
                try:
                    for name in sorted(os.listdir(macos_dir)):
                        cand = os.path.join(macos_dir, name)
                        if os.path.isfile(cand) and os.access(cand, os.X_OK):
                            return cand
                except OSError:
                    pass
            return exe
        return exe

    def resolve_maa_dir(self, exe: str, config_dir: str = "") -> str:
        if (config_dir or "").strip():
            return os.path.abspath(config_dir.strip())
        binary = self.resolve_maa_binary(exe)
        parent = os.path.dirname(binary) if binary else ""
        cands = []
        if parent:
            cands.append(parent)
            # .app/Contents/MacOS → 也看 Resources
            cands.append(os.path.normpath(os.path.join(parent, "..", "Resources")))
        if exe and exe.rstrip("/").endswith(".app"):
            cands.append(os.path.join(exe.rstrip("/"), "Contents", "MacOS"))
        cands.extend(_MAA_SUPPORT_DIRS)
        # 容器化 / 沙盒
        containers = os.path.expanduser("~/Library/Containers")
        if os.path.isdir(containers):
            try:
                for name in os.listdir(containers):
                    if "maa" not in name.lower():
                        continue
                    cands.append(os.path.join(
                        containers, name, "Data", "Library", "Application Support", "MAA"
                    ))
            except OSError:
                pass
        for cand in cands:
            if cand and os.path.isfile(os.path.join(cand, "config", "gui.new.json")):
                return cand
        return parent

    # ---- mumutool：info / open / close，不是 Windows 的 control -v launch ----

    def mumu_info_argv(self, cli: str, vm_index: int) -> list:
        return [cli, "info", str(vm_index)]

    def mumu_control_argv(self, cli: str, vm_index: int, action: str) -> list:
        mapped = {"launch": "open", "shutdown": "close", "open": "open", "close": "close"}.get(
            action, action
        )
        return [cli, mapped, str(vm_index)]

    def mumu_close_manager_argv(self, cli: str) -> list:
        # mumutool 没有 Windows 的 `main close`；用 AppleScript 退出管理器。
        return [
            "osascript", "-e",
            'tell application "System Events" to (name of processes) as text',
        ]

    def mumu_close_manager(self, cli: str):
        """尽量退出 MuMu 管理器本体（设备已由 close 关掉）。"""
        names = []
        if cli:
            root = cli
            while root and root != "/":
                if root.endswith(".app"):
                    names.append(os.path.splitext(os.path.basename(root))[0])
                    break
                root = os.path.dirname(root)
        names += ["MuMuPlayer", "MuMu模拟器", "MuMuPlayer Pro", "MuMuNxDevice"]
        last = (1, "")
        seen = set()
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            rc, out, err = run_cmd(
                ["osascript", "-e", 'quit app "%s"' % name], timeout=30
            )
            last = (rc, (out + err).strip())
            if rc == 0:
                return rc, last[1] or "已请求退出 %s" % name
        return last

    def process_running(self, image_name: str) -> bool:
        if not image_name:
            return False
        aliases = [image_name]
        if image_name.lower() in ("maa.exe", "maa"):
            aliases = ["MAA", "MAA.exe", "maa"]
        for name in aliases:
            rc, out, _ = run_cmd(["pgrep", "-x", name], timeout=10)
            if rc == 0 and out.strip():
                return True
            if super().process_running(name):
                return True
        return False

    def close_pid_gracefully(self, pid: int) -> int:
        if not pid:
            return 0
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return 0
        if pid == os.getpid():
            return 0
        rc, _, _ = run_cmd(
            ["osascript", "-e",
             'tell application "System Events" to unix id of processes contains %d' % int(pid)],
            timeout=10,
        )
        # 先请应用自己退出，再 SIGTERM
        run_cmd(
            ["osascript", "-e",
             'tell application "System Events" to set theProcs to (every process whose unix id is %d)\n'
             "repeat with p in theProcs\ntry\nquit p\nend try\nend repeat" % int(pid)],
            timeout=15,
        )
        return super().close_pid_gracefully(pid)

    def open_folder(self, path: str) -> bool:
        rc, _, _ = run_cmd(["open", path], timeout=15)
        return rc == 0

    def show_error_box(self, text: str, title: str = "MAA 一键挂机 - 启动失败") -> None:
        escaped = (text or "").replace("\\", "\\\\").replace('"', '\\"')
        title_e = (title or "").replace('"', '\\"')
        script = (
            'display dialog "%s" with title "%s" buttons {"OK"} '
            "default button 1 with icon stop" % (escaped[:900], title_e)
        )
        run_cmd(["osascript", "-e", script], timeout=30)

    def focus_window(self, title: str) -> bool:
        if not title:
            return False
        script = (
            'tell application "System Events"\n'
            '  set procs to every process whose visible is true\n'
            "  repeat with p in procs\n"
            "    try\n"
            '      if (name of windows of p as text) contains "%s" then\n'
            "        set frontmost of p to true\n"
            "        return true\n"
            "      end if\n"
            "    end try\n"
            "  end repeat\n"
            "end tell\n"
            "return false" % title.replace('"', '\\"')
        )
        rc, out, _ = run_cmd(["osascript", "-e", script], timeout=15)
        return rc == 0 and "true" in (out or "").lower()

    def desktop_notify(self, title: str, body: str) -> bool:
        t = (title or "").replace('"', '\\"')[:80]
        b = (body or "").replace('"', '\\"')[:200]
        rc, _, _ = run_cmd(
            ["osascript", "-e",
             'display notification "%s" with title "%s"' % (b, t)],
            timeout=15,
        )
        return rc == 0

    def tray_supported(self) -> bool:
        from plat.tray_macos import tray_backend_available
        return tray_backend_available() is not None

    def create_tray(self, hooks: dict):
        from plat.tray_macos import MacStatusTray
        return MacStatusTray(hooks)

    def selftest_tray(self) -> tuple:
        from plat.tray_macos import tray_backend_available
        kind = tray_backend_available()
        if kind:
            return True, [
                "  [OK] macOS 菜单栏托盘可用（后端 %s）" % kind,
                "  [i] 关窗口 = 隐藏到菜单栏，挂机与定时继续跑；二次启动会唤起已有实例",
            ], []
        return True, [
            "  [i] 未安装 AppKit / rumps / pystray：关窗后无法驻留菜单栏",
            "  [i] 源码运行请：python3 -m pip install pyobjc-framework-Cocoa",
            "  [i] 打进 .app 后一般自带 Cocoa；二次启动仍会唤起已有实例",
        ], []
