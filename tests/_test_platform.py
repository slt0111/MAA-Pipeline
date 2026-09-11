# -*- coding: utf-8 -*-
"""平台适配层：不依赖真实 MuMu / MAA，覆盖 Windows / macOS / Linux 分支。

跑法：
    python tests/_test_platform.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline  # noqa: E402
import plat  # noqa: E402
from plat.macos import MacOSPlatform
from plat.windows import WindowsPlatform
from plat.linux import LinuxPlatform

PASS, FAIL = [], []


def ok(cond, title, detail=""):
    (PASS if cond else FAIL).append(title)
    extra = ""
    if detail and not cond:
        extra = "  " + str(detail)
    print("  [%s] %s%s" % ("OK" if cond else "!!", title, extra))


print("=== 1. OS 识别 ===")
ok(plat.detect_os("win32") == "windows", "win32 → windows")
ok(plat.detect_os("Windows") == "windows", "Windows → windows")
ok(plat.detect_os("darwin") == "macos", "darwin → macos")
ok(plat.detect_os("macos") == "macos", "macos 原样")
ok(plat.detect_os("linux") == "linux", "linux")
ok(plat.detect_os("freebsd") == "linux", "其他 POSIX 归到 linux")
ok(isinstance(plat.create("windows"), WindowsPlatform), "create(windows)")
ok(isinstance(plat.create("macos"), MacOSPlatform), "create(macos)")
ok(isinstance(plat.create("linux"), LinuxPlatform), "create(linux)")


print("=== 2. ADB 地址公式：Windows 不变，Mac 不用 16384+32*index ===")
win = WindowsPlatform()
mac = MacOSPlatform()
ok(win.default_adb_address(0) == "127.0.0.1:16384", "Win 实例 0 → 16384")
ok(win.default_adb_address(1) == "127.0.0.1:16416", "Win 实例 1 → 16416")
ok(win.default_adb_address(2) == "127.0.0.1:16448", "Win 实例 2 → 16448")
ok(mac.default_adb_address(0) == "", "Mac 无 info 时不猜 Windows 端口")
ok(mac.default_adb_address(0) != "127.0.0.1:16384", "Mac 实例 0 不是 16384")
ok(mac.default_adb_address(0, info={"adb_port": 26624}) == "127.0.0.1:26624",
   "Mac 从 info.adb_port 推导")
ok(mac.default_adb_address(1, info={"customAdbPort": "5555"}) == "127.0.0.1:5555",
   "Mac 识别 customAdbPort")


print("=== 3. 模拟器 CLI 参数 ===")
ok(win.mumu_info_argv("mumu-cli.exe", 0) == ["mumu-cli.exe", "info", "-v", "0"],
   "Windows info -v")
ok(win.mumu_control_argv("mumu-cli.exe", 1, "launch") ==
   ["mumu-cli.exe", "control", "-v", "1", "launch"], "Windows control launch")
ok(win.mumu_control_argv("mumu-cli.exe", 0, "shutdown")[-1] == "shutdown",
   "Windows control shutdown")
ok(win.mumu_close_manager_argv("mumu-cli.exe") == ["mumu-cli.exe", "main", "close"],
   "Windows main close")
ok(mac.mumu_info_argv("/app/mumutool", 0) == ["/app/mumutool", "info", "0"],
   "Mac mumutool info 0")
ok(mac.mumu_control_argv("/app/mumutool", 0, "launch") == ["/app/mumutool", "open", "0"],
   "Mac launch → open")
ok(mac.mumu_control_argv("/app/mumutool", 2, "shutdown") == ["/app/mumutool", "close", "2"],
   "Mac shutdown → close")
ok(mac.mumu_close_manager_argv("x")[0] == "osascript", "Mac 关管理器走 osascript")


print("=== 4. mumutool / mumu-cli info JSON 规范化 ===")
parsed = mac.normalize_mumu_info({
    "index": 0, "name": "我的安卓",
    "is_process_started": True, "is_android_started": True,
    "adb_port": 26624,
}, 0)
ok(parsed["is_android_started"] is True and parsed["is_process_started"] is True,
   "Windows 字段原样保留")
ok(parsed["adb_port"] == 26624, "adb_port 抽出")

nested = mac.parse_mumu_info(json.dumps({
    "data": {"0": {"status": "running", "vmName": "MacVM", "customAdbPort": 16384}}
}), 0)
ok(nested["is_android_started"] is True, "Mac status=running → 安卓已就绪", nested)
ok(nested["name"] == "MacVM", "vmName → name")
ok(str(nested["adb_port"]) == "16384", "customAdbPort → adb_port")

stopped = mac.normalize_mumu_info({"status": "stopped"}, 0)
ok(stopped["is_android_started"] is False, "status=stopped 不算就绪")

try:
    mac.parse_mumu_info("not-json-at-all", 0)
    ok(False, "非 JSON 应抛错")
except ValueError:
    ok(True, "非 JSON 抛 ValueError")


print("=== 5. MAA 启动参数 / 目录 / 连接配置名 ===")
ok(win.maa_connect_config == "MuMuEmulator12", "Windows 连接配置 MuMuEmulator12")
ok(mac.maa_connect_config == "CompatMac", "Mac 连接配置 CompatMac")
ok(win.maa_argv(r"D:\MAA\MAA.exe", "挂机流水线") ==
   [r"D:\MAA\MAA.exe", "--config", "挂机流水线"], "Windows --config")
ok(mac.maa_argv("/opt/homebrew/bin/maa", "挂机流水线") ==
   ["/opt/homebrew/bin/maa", "-p", "挂机流水线", "run"], "maa-cli 用 -p / run")
ok(mac.is_maa_cli("/usr/local/bin/maa") is True, "识别 maa-cli")
ok(mac.is_maa_cli("/opt/homebrew/bin/maa-cli") is True, "识别 maa-cli 全名")
ok(mac.is_maa_cli("/Applications/MAA.app") is False, ".app 不是 cli")
ok(mac.is_maa_cli("/Applications/MAA.app/Contents/MacOS/MAA") is False,
   "MAA.app 内二进制不是 cli")
ok(mac.uses_gui_inject("/Applications/MAA.app") is True, "MAA.app 走 gui.new.json 注入")
ok(mac.uses_gui_inject("maa") is False, "maa-cli 不走 GUI 注入")
ok(win.resolve_maa_dir("/opt/MAA/MAA.exe") == "/opt/MAA", "Windows maa_dir = dirname")
ok(mac.resolve_maa_binary("/Applications/MAA.app").endswith(".app") or
   "MacOS" in mac.resolve_maa_binary("/Applications/MAA.app") or
   mac.resolve_maa_binary("/Applications/MAA.app") == "/Applications/MAA.app",
   "未安装时 .app 路径可安全解析")


print("=== 6. 切换适配器后 Config / inject 跟随平台 ===")
orig = plat.current()
try:
    pipeline.set_platform("windows")
    cfg = pipeline.Config.from_data({"mumu": {"vm_index": 1}})
    ok(cfg.adb_address == "127.0.0.1:16416", "set_platform(windows) 后公式生效", cfg.adb_address)
    ok(pipeline.host().name == "windows", "host() 指向 windows")

    pipeline.set_platform("macos")
    cfg = pipeline.Config.from_data({"mumu": {"vm_index": 0, "adb_address": ""}})
    ok(cfg.adb_address == "", "set_platform(macos) 后不套用 16384", cfg.adb_address)
    overlay = pipeline.host().default_config_overlay("/tmp")
    ok("mumutool" in overlay.get("mumu", {}).get("cli", ""), "Mac 默认 cli 含 mumutool")
    ok(overlay.get("maa", {}).get("exe", "").endswith(".app") or "MAA" in overlay.get("maa", {}).get("exe", ""),
       "Mac 默认 MAA 指向 .app")

    with tempfile.TemporaryDirectory() as tmp:
        exe = os.path.join(tmp, "MAA.exe")
        open(exe, "w").close()
        os.makedirs(os.path.join(tmp, "config"))
        gui_path = os.path.join(tmp, "config", "gui.new.json")
        with open(gui_path, "w", encoding="utf-8") as fh:
            json.dump({
                "Current": "Default",
                "Configurations": {
                    "Default": {
                        "Gui": {"StartUpSettings": {}, "ConnectSettings": {}},
                        "TaskQueue": [{"$type": "StartUpTask", "Name": "开始唤醒"}],
                    }
                },
            }, fh)
        logs = []
        cfg = pipeline.Config.from_data(
            {"maa": {"exe": exe, "profile": "挂机流水线"},
             "mumu": {"adb_address": "127.0.0.1:26624", "adb": "/opt/homebrew/bin/adb"}},
            path=os.path.join(tmp, "x.json"),
        )
        pipeline.inject_maa_profile(cfg, lambda lv, msg: logs.append(msg), account_name="4567")
        data = json.load(open(gui_path, encoding="utf-8"))
        conn = data["Configurations"]["挂机流水线"]["Gui"]["ConnectSettings"]
        ok(conn["Config"] == "CompatMac", "Mac 注入 CompatMac", conn)
        ok(conn["Address"] == "127.0.0.1:26624", "注入用户填写的 Mac 端口", conn)
        ok(conn["AdbPath"] == "/opt/homebrew/bin/adb", "注入 Mac adb")
        ok(data["Configurations"]["挂机流水线"]["TaskQueue"][0]["AccountName"] == "4567",
           "Mac 路径下切号字段仍写入")

    pipeline.set_platform("windows")
    with tempfile.TemporaryDirectory() as tmp:
        exe = os.path.join(tmp, "MAA.exe")
        open(exe, "w").close()
        os.makedirs(os.path.join(tmp, "config"))
        gui_path = os.path.join(tmp, "config", "gui.new.json")
        with open(gui_path, "w", encoding="utf-8") as fh:
            json.dump({
                "Current": "Default",
                "Configurations": {"Default": {"Gui": {"StartUpSettings": {}, "ConnectSettings": {}}}},
            }, fh)
        cfg = pipeline.Config.from_data({"maa": {"exe": exe}}, path=os.path.join(tmp, "x.json"))
        pipeline.inject_maa_profile(cfg, lambda *_: None)
        data = json.load(open(gui_path, encoding="utf-8"))
        conn = data["Configurations"]["挂机流水线"]["Gui"]["ConnectSettings"]
        ok(conn["Config"] == "MuMuEmulator12", "切回 Windows 后仍注入 MuMuEmulator12", conn)
finally:
    plat.set_current(orig)


print("=== 7. 进程检测 / 关闭自身安全 / 快照带平台 ===")
ok(pipeline.post_close_to_pid(os.getpid()) >= 0, "对自己调用 close 不会杀进程")
ok(isinstance(pipeline.process_running("definitely-not-a-real-proc-xyz"), bool),
   "process_running 在 Linux CI 返回 bool（不调 tasklist）")

# Linux 适配器不应去调 tasklist（各模块 from-import 了 run_cmd，需分别打桩）
recorded = []
import plat.base as plat_base
import plat.windows as plat_windows

orig_base_run = plat_base.run_cmd
orig_win_run = plat_windows.run_cmd


def fake_run(args, timeout=30, cwd=None):
    recorded.append(list(args))
    return 1, "", ""


plat_base.run_cmd = fake_run
plat_windows.run_cmd = fake_run
try:
    LinuxPlatform().process_running("MAA.exe")
    ok(recorded and recorded[0][0] == "pgrep", "Linux process_running 用 pgrep", recorded)
    recorded.clear()
    WindowsPlatform().process_running("MAA.exe")
    ok(recorded and recorded[0][0] == "tasklist", "Windows process_running 仍用 tasklist", recorded)
finally:
    plat_base.run_cmd = orig_base_run
    plat_windows.run_cmd = orig_win_run

pipeline.set_platform("linux")
try:
    snap = pipeline.Engine(pipeline.Config.from_data({}), pipeline.Bus()).snapshot()["config_summary"]
    ok(snap.get("platform") == "linux", "snapshot 带 platform", snap.get("platform"))
    ok("mumu_cli" in snap and "mumu_adb" in snap, "snapshot 带 cli/adb 路径字段")
finally:
    plat.set_current(orig)


print("=== 8. 老配置 schema 不被 Mac overlay 打坏 ===")
pipeline.set_platform("linux")
try:
    cfg = pipeline.Config.from_data({})
    ok("cli" in cfg.data["mumu"] and "accounts" in cfg.data["maa"], "默认键齐全")
    ok(isinstance(cfg.data["maa"]["accounts"], list), "accounts 仍是列表")
    loaded = pipeline.Config.from_data({
        "mumu": {"cli": r"C:\Program Files\Netease\MuMu\nx_main\mumu-cli.exe", "vm_index": 3},
        "maa": {"exe": r"D:\MAA\MAA.exe", "accounts": [{"name": "A", "account_name": "1"}]},
    })
    ok(loaded.get("mumu", "cli").endswith("mumu-cli.exe"), "已有 Windows 路径不被覆盖")
    ok(loaded.vm_index == 3, "vm_index 保留")
    ok(pipeline.enabled_accounts(loaded)[0]["name"] == "A", "多账号配置仍可读")
finally:
    plat.set_current(orig)


print()
print("=" * 62)
if FAIL:
    print("失败 %d 项：%s" % (len(FAIL), " / ".join(FAIL)))
    print("通过 %d 项" % len(PASS))
    sys.exit(1)
print("全部通过（%d 项）" % len(PASS))
