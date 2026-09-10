# -*- coding: utf-8 -*-
"""
MAA 一键挂机流水线
================================================================
一键完成：启动 MuMu 模拟器 → 等待安卓系统就绪 → 确认 ADB 通路
          → 拉起 MAA 自动开始挂机 → 收尾归档（按需关闭模拟器）

界面默认走原生窗口（装了 pywebview 时），也兼容浏览器模式，带实时运行记录。

命令行：
    python pipeline.py             正常启动（原生窗口 + 托盘）
    python pipeline.py --window    强制原生窗口模式
    python pipeline.py --browser   强制浏览器模式，不弹原生窗口
    python pipeline.py --no-tray   不启用托盘图标
    python pipeline.py --selftest  自检：校验环境与各项依赖，不启动界面
"""

from __future__ import annotations

import collections
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import json
import os
import queue
import re
import shutil
import smtplib
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from email.header import Header
from email.mime.text import MIMEText
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def _base_dir():
    """数据根目录：打包成 exe 后是 exe 所在目录，源码运行时是脚本目录。
    配置、日志、MAA 都以此为基准，保证 exe 放在哪都能自洽。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _res_dir():
    """只读资源目录：打包后是 PyInstaller 的解包临时目录，源码运行时同上。"""
    return getattr(sys, "_MEIPASS", None) or _base_dir()


APP_DIR = _base_dir()
RES_DIR = _res_dir()
CFG_PATH = os.path.join(APP_DIR, "pipeline_config.json")
LOG_DIR = os.path.join(APP_DIR, "logs")


def _ui_path():
    """界面文件位置：exe 旁边若放了 ui.html 就用它（方便自定义），否则用内置的。"""
    local = os.path.join(APP_DIR, "ui.html")
    if os.path.exists(local):
        return local
    return os.path.join(RES_DIR, "ui.html")


UI_PATH = _ui_path()

CREATE_NO_WINDOW = 0x08000000

PHASES = [
    ("env", "环境自检"),
    ("launch", "启动模拟器"),
    ("ready", "等待安卓就绪"),
    ("adb", "确认 ADB 通路"),
    ("maa", "拉起 MAA 挂机"),
    ("wrap", "收尾归档"),
]
PHASE_LABEL = dict(PHASES)

MODE_PHASES = {
    "full": ["env", "launch", "ready", "adb", "maa", "wrap"],
    "emu": ["env", "launch", "ready", "adb"],
    "maa": ["env", "maa", "wrap"],
}

DEFAULT_CONFIG = {
    "mumu": {
        "cli": r"C:\Program Files\Netease\MuMu\nx_main\mumu-cli.exe",
        "adb": r"C:\Program Files\Netease\MuMu\nx_main\adb.exe",
        "vm_index": 0,
        "adb_address": "",
        "ready_timeout": 180,
        "poll_interval": 3,
        "shutdown_after_complete": True,
        "close_manager": True,
    },
    "maa": {
        "exe": os.path.join(APP_DIR, "MAA", "MAA.exe"),
        "profile": "挂机流水线",
        "start_timeout": 150,
        "mirror_logs": True,
        "close_after_complete": True,
        "close_delay": 10,
    },
    "server": {"port": 17800, "open_browser": True, "window_mode": "auto"},
    # times 为空时回退到老的单个 time 字段，保证老配置不丢设置
    "schedule": {"enabled": True, "time": "08:00", "times": [], "days": [0, 1, 2, 3, 4, 5, 6],
                 "only_if_idle": True},
    "notify": {
        "desktop": True,
        "email": {
            "enabled": False,
            "smtp_host": "",
            "smtp_port": 465,
            "use_ssl": True,
            "username": "",
            "password": "",
            "to": "",
        },
        "serverchan": {"enabled": False, "sendkey": ""},
        "pushplus": {"enabled": False, "token": "", "topic": "", "template": "txt"},
        "wxpusher": {"enabled": False, "app_token": "", "uids": ""},
        "qmsg": {"enabled": False, "key": "", "qq": "", "type": "send"},
        "webhook": {"enabled": False, "url": "", "format": "通用 JSON"},
    },
    "tray": {"enabled": True},
}

WEEK_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


# ============================================================ 基础工具


def _decode(raw: bytes) -> str:
    if not raw:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


def run_cmd(args, timeout=30, cwd=None):
    """执行命令，返回 (returncode, stdout, stderr)。永不抛异常。"""
    try:
        flags = CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.run(
            args, capture_output=True, timeout=timeout, cwd=cwd, creationflags=flags
        )
    except subprocess.TimeoutExpired:
        return -1, "", "命令执行超时（%ss）" % timeout
    except FileNotFoundError:
        return -2, "", "找不到可执行文件：%s" % args[0]
    except Exception as exc:  # noqa: BLE001
        return -3, "", "%s: %s" % (type(exc).__name__, exc)
    return proc.returncode, _decode(proc.stdout), _decode(proc.stderr)


def process_running(image_name: str) -> bool:
    rc, out, _ = run_cmd(["tasklist", "/FI", "IMAGENAME eq %s" % image_name, "/NH"], timeout=15)
    return rc == 0 and image_name.lower() in out.lower()


def brief_output(text: str, limit: int = 160) -> str:
    """把 mumu-cli 的输出压成一行可读摘要，避免把整段 JSON 塞进日志。"""
    text = (text or "").strip()
    if not text:
        return ""
    code = json_code(text)
    if code is not None:
        return "返回 code=%s" % code
    return text.splitlines()[0][:limit]


def json_code(text: str):
    try:
        data = json.loads((text or "").strip())
    except Exception:
        return None
    if isinstance(data, dict):
        for key in ("code", "error_code", "err_code"):
            if key in data:
                return data[key]
    return None


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, val in (override or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = val
    return out


class PipelineError(Exception):
    """流水线阶段失败，中断后续步骤。"""


# ============================================================ 配置


class Config:
    def __init__(self, path=CFG_PATH):
        self.path = path
        self.data = dict(DEFAULT_CONFIG)
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    self.data = deep_merge(DEFAULT_CONFIG, json.load(fh))
            except Exception:
                pass
        else:
            self.save()

    @classmethod
    def from_data(cls, data: dict, path=None):
        """用一份内存里的配置构造实例（供"测试但不保存"的场景使用）。"""
        obj = cls.__new__(cls)
        obj.path = path or CFG_PATH
        obj.data = deep_merge(DEFAULT_CONFIG, data or {})
        return obj

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get(self, *keys, default=None):
        cur = self.data
        for key in keys:
            if not isinstance(cur, dict) or key not in cur:
                return default
            cur = cur[key]
        return cur

    def set(self, value, *keys):
        cur = self.data
        for key in keys[:-1]:
            cur = cur.setdefault(key, {})
        cur[keys[-1]] = value

    # --- 派生值 ---
    @property
    def vm_index(self) -> int:
        try:
            return int(self.get("mumu", "vm_index", default=0))
        except Exception:
            return 0

    @property
    def adb_address(self) -> str:
        addr = (self.get("mumu", "adb_address", default="") or "").strip()
        if addr:
            return addr
        return "127.0.0.1:%d" % (16384 + 32 * self.vm_index)

    @property
    def maa_exe(self) -> str:
        return self.get("maa", "exe", default="")

    @property
    def maa_dir(self) -> str:
        return os.path.dirname(self.maa_exe)


# ============================================================ 路径自动探测
#
# 为什么要探测：exe 拷到另一台电脑后，模拟器和 MAA 的安装位置不一定一样。
# 配置里存的是"上一次找到的位置"，一旦失效就按常见安装位置重新找一遍，
# 找到后自动回填并保存——拷过去基本做到开箱即用，不用手填路径。

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


def _find_mumu_cli():
    drives = _drive_letters()
    for drive in drives:
        for root_rel in _MUMU_SEARCH_ROOTS:
            root = r"%s:\%s" % (drive, root_rel)
            if not os.path.isdir(root):
                continue
            # 直接命中
            for rel in _MUMU_REL_TARGETS:
                cand = os.path.join(root, rel)
                if os.path.isfile(cand):
                    return cand
            # Netease 下可能叫 MuMu / MuMuPlayer-12.0 / MuMuPlayerGlobal-12.0 …
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


def _find_maa_exe():
    cands = [
        os.path.join(APP_DIR, "MAA", "MAA.exe"),
        os.path.join(os.path.dirname(APP_DIR), "MAA", "MAA.exe"),
    ]
    for drive in _drive_letters():
        cands += [
            r"%s:\MAA\MAA.exe" % drive,
            r"%s:\Program Files\MAA\MAA.exe" % drive,
            r"%s:\Games\MAA\MAA.exe" % drive,
        ]
    return next((c for c in cands if os.path.isfile(c)), None)


def autodetect_paths(cfg: Config, log=None):
    """配置里的路径失效时，按常见安装位置重新探测，找到就回填保存。"""
    changed = []
    missing = []

    cli = (cfg.get("mumu", "cli", default="") or "").strip()
    if not os.path.isfile(cli):
        found = _find_mumu_cli()
        if found:
            cfg.set(found, "mumu", "cli")
            cfg.set(os.path.join(os.path.dirname(found), "adb.exe"), "mumu", "adb")
            changed.append("MuMu 模拟器：%s" % found)
        else:
            missing.append("MuMu 模拟器（mumu-cli.exe）")

    maa = (cfg.get("maa", "exe", default="") or "").strip()
    if not os.path.isfile(maa):
        found = _find_maa_exe()
        if found:
            cfg.set(found, "maa", "exe")
            changed.append("MAA 主程序：%s" % found)
        else:
            missing.append("MAA 主程序（MAA.exe）")

    if changed:
        cfg.save()
        if log:
            for item in changed:
                log("info", "路径自动探测 → " + item)
    if missing and log:
        for item in missing:
            log("warn", "未能自动找到 %s，请在界面「设置」里手动填路径" % item)
    return changed


# ============================================================ 日志总线


class Bus:
    """把日志与状态变化广播给所有 SSE 订阅者，同时落盘。"""

    def __init__(self):
        self._subs = set()
        self._lock = threading.Lock()
        self.recent = collections.deque(maxlen=400)

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=2000)
        with self._lock:
            self._subs.add(q)
        for item in list(self.recent):
            try:
                q.put_nowait(item)
            except queue.Full:
                break
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            self._subs.discard(q)

    def _publish(self, item: dict):
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(item)
            except queue.Full:
                pass

    def log(self, level: str, msg: str):
        item = {
            "type": "log",
            "level": level,
            "msg": msg,
            "time": dt.datetime.now().strftime("%H:%M:%S"),
            "ts": time.time(),
        }
        self.recent.append(item)
        self._publish(item)
        _append_file_log(level, msg)

    def state(self, snapshot: dict):
        item = {"type": "state", "state": snapshot}
        self._publish(item)


def _append_file_log(level: str, msg: str):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, dt.date.today().isoformat() + ".log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("[%s][%s] %s\n" % (dt.datetime.now().strftime("%H:%M:%S"), level.upper(), msg))
    except Exception:
        pass


# ============================================================ 模拟器控制


def mumu_info(cfg: Config):
    """读取模拟器实例状态，返回 dict。"""
    cli = cfg.get("mumu", "cli", default="")
    rc, out, err = run_cmd([cli, "info", "-v", str(cfg.vm_index)], timeout=25)
    if rc != 0:
        raise PipelineError("读取模拟器状态失败：%s" % (err.strip() or out.strip() or "未知错误"))
    start = out.find("{")
    if start < 0:
        raise PipelineError("模拟器状态返回异常：%s" % out.strip()[:200])
    try:
        return json.loads(out[start:])
    except Exception as exc:
        raise PipelineError("解析模拟器状态失败：%s" % exc)


def mumu_control(cfg: Config, action: str):
    cli = cfg.get("mumu", "cli", default="")
    rc, out, err = run_cmd([cli, "control", "-v", str(cfg.vm_index), action], timeout=60)
    return rc, (out + err).strip()


def mumu_main(action: str, cli: str):
    """控制 MuMu 管理器本体（main close / main launch）。"""
    rc, out, err = run_cmd([cli, "main", action], timeout=60)
    return rc, (out + err).strip()


def post_close_to_pid(pid: int) -> int:
    """给指定进程的所有顶层窗口发 WM_CLOSE，让它自己走正常退出流程。

    比直接 terminate() 温和：程序有机会保存配置、清理临时文件。
    返回成功投递的窗口数量。
    """
    user32 = ctypes.windll.user32
    WM_CLOSE = 0x0010
    count = 0

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _enum(hwnd, _lparam):
        nonlocal count
        wpid = ctypes.wintypes.DWORD()
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


# ============================================================ MAA 控制


def inject_maa_profile(cfg: Config, log):
    """把「挂机流水线」配置写入 MAA 的 gui.new.json，并返回原来的 Current 值。

    MAA 退出时会回写配置文件，所以要恢复到注入前的状态。
    """
    maa_dir = cfg.maa_dir
    maa_exe = cfg.maa_exe
    if not os.path.exists(maa_exe):
        raise PipelineError("找不到 MAA 主程序：%s" % maa_exe)

    cfg_path = os.path.join(maa_dir, "config", "gui.new.json")
    if not os.path.exists(cfg_path):
        raise PipelineError("找不到 MAA 配置文件：%s" % cfg_path)

    backup = cfg_path + ".pipeline.bak"
    if not os.path.exists(backup):
        shutil.copy2(cfg_path, backup)
        log("info", "已备份 MAA 配置到 %s" % os.path.basename(backup))

    with open(cfg_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    prev_current = data.get("Current")
    confs = data.setdefault("Configurations", {})
    base = confs.get("Default") or (next(iter(confs.values())) if confs else None)
    if base is None:
        raise PipelineError("MAA 配置里没有任何可用配置项，请先手动启动一次 MAA")

    profile_name = cfg.get("maa", "profile", default="挂机流水线")
    profile = json.loads(json.dumps(base, ensure_ascii=False))

    startup = profile.setdefault("Gui", {}).setdefault("StartUpSettings", {})
    startup["RunDirectly"] = True          # 启动即自动开始任务
    startup["StartEmulator"] = False       # 模拟器由本工具负责启动
    startup["RestartEmulatorWhenAdbFailed"] = False
    startup["SkipStartupAutoRunAfterUpdate"] = True

    connect = profile["Gui"].setdefault("ConnectSettings", {})
    connect["Config"] = "MuMuEmulator12"
    connect["AdbPath"] = cfg.get("mumu", "adb", default="")
    connect["Address"] = cfg.adb_address
    connect["AutoDetect"] = False

    confs[profile_name] = profile
    data["Current"] = profile_name

    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=4)

    log("info", "已注入 MAA 配置「%s」（RunDirectly = 启动即挂机）" % profile_name)
    return prev_current


def restore_maa_current(cfg: Config, prev_current, log):
    if prev_current is None:
        return
    cfg_path = os.path.join(cfg.maa_dir, "config", "gui.new.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("Current") != prev_current:
            data["Current"] = prev_current
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=4)
            log("info", "已把 MAA 当前配置还原为「%s」" % prev_current)
    except Exception as exc:  # noqa: BLE001
        log("warn", "还原 MAA 配置失败：%s" % exc)


# ============================================================ 流水线引擎


class Engine:
    def __init__(self, cfg: Config, bus: Bus):
        self.cfg = cfg
        self.bus = bus
        self.lock = threading.RLock()
        self.stop_evt = threading.Event()
        self.thread = None
        self.maa_proc = None
        self._prev_current = None
        self._completed = False
        self._started_evidence = False
        self._connect_failed = False
        self._tail_thread = None
        self._maasession_pos = 0
        self._maa_pending = ""        # 未读完的日志残行
        self._maa_recent = {}         # 去重：消息 -> 上次播报时间
        self.state = {
            "running": False,
            "mode": None,
            "elapsed": 0,
            "phases": {key: "pending" for key, _ in PHASES},
            "mumu": "未知",
            "adb": "未知",
            "maa": "未运行",
            "task": "—",
            "last_error": "",
            "last_run": "",
            "last_result": "",
            "runs": 0,
            "next_schedule": "",
            "started_at": "",
            "server": "",
        }

    # ---------------- 对外接口 ----------------

    def start(self, mode="full") -> tuple:
        with self.lock:
            if self.state["running"]:
                return False, "流水线正在运行中"
            self.thread = threading.Thread(target=self._run, args=(mode,), daemon=True)
            self.thread.start()
            return True, "已开始"

    def abort(self):
        self.stop_evt.set()
        self.bus.log("warn", "收到中止请求，正在停止…")

    def snapshot(self) -> dict:
        with self.lock:
            snap = json.loads(json.dumps(self.state, ensure_ascii=False))
        snap["config_summary"] = {
            "vm_index": self.cfg.vm_index,
            "adb_address": self.cfg.adb_address,
            "ready_timeout": self.cfg.get("mumu", "ready_timeout", default=180),
            "shutdown_after_complete": self.cfg.get("mumu", "shutdown_after_complete", default=True),
            "close_manager": self.cfg.get("mumu", "close_manager", default=True),
            "maa_exe": self.cfg.maa_exe,
            "maa_profile": self.cfg.get("maa", "profile", default=""),
            "maa_close_after_complete": self.cfg.get("maa", "close_after_complete", default=True),
            "maa_close_delay": self.cfg.get("maa", "close_delay", default=10),
            "schedule": normalized_schedule(self.cfg),
            "notify": normalized_notify(self.cfg),
            "notify_desktop": self.cfg.get("notify", "desktop", default=True),
            "notify_email": self.cfg.get("notify", "email", default={}),
            "port": self.cfg.get("server", "port", default=17800),
        }
        return snap

    def _publish(self):
        self.bus.state(self.snapshot())

    def log(self, level, msg):
        self.bus.log(level, msg)

    # ---------------- 状态辅助 ----------------

    def _set_phase(self, key, status):
        with self.lock:
            self.state["phases"][key] = status
        self._publish()

    def _set(self, **kwargs):
        with self.lock:
            self.state.update(kwargs)
        self._publish()

    def _reset_phases(self, mode):
        allowed = MODE_PHASES.get(mode, MODE_PHASES["full"])
        with self.lock:
            self.state["phases"] = {
                key: ("pending" if key in allowed else "skipped") for key, _ in PHASES
            }
        self._publish()

    def _begin_phase(self, key):
        self._set_phase(key, "active")
        self.log("phase", "▶ %s" % PHASE_LABEL[key])

    def _end_phase(self, key, ok=True):
        self._set_phase(key, "done" if ok else "failed")

    # ---------------- 主流程 ----------------

    def _run(self, mode):
        started = time.time()
        self.stop_evt.clear()
        self._completed = False
        self._prev_current = None
        self.maa_proc = None
        self._started_evidence = False
        self._connect_failed = False
        self._maa_pending = ""
        self._maa_recent = {}
        self._reset_phases(mode)
        self._set(
            running=True,
            mode=mode,
            elapsed=0,
            last_error="",
            task="—",
            mumu="检查中",
            adb="未知",
            maa="未运行",
            started_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.log("phase", "══ 流水线开始（模式：%s）══" % self._mode_name(mode))

        timer = threading.Thread(target=self._elapsed_ticker, args=(started,), daemon=True)
        timer.start()
        ok = True
        err = ""
        try:
            self._phase_env()
            if mode in ("full", "emu"):
                self._phase_launch()
                self._phase_ready()
                self._phase_adb()
            if mode in ("full", "maa"):
                self._phase_maa()
                self._phase_wrap()
            else:
                self.log("ok", "模拟器已就绪，可以开始挂机了")
        except PipelineError as exc:
            ok = False
            err = str(exc)
            self.log("error", err)
        except Exception as exc:  # noqa: BLE001
            ok = False
            err = "%s: %s" % (type(exc).__name__, exc)
            self.log("error", "未预期的错误：%s" % err)
            _append_file_log("error", traceback.format_exc())
        finally:
            self.stop_evt.set()
            elapsed = int(time.time() - started)
            with self.lock:
                self.state["running"] = False
                self.state["elapsed"] = elapsed
                self.state["last_error"] = err
                self.state["last_run"] = dt.datetime.now().strftime("%m-%d %H:%M")
                self.state["runs"] += 1
                self.state["last_result"] = "成功" if ok else "失败"
                for key, status in self.state["phases"].items():
                    if status == "active":
                        self.state["phases"][key] = "done" if ok else "failed"
            self._publish()
            self.log(
                "ok" if ok else "error",
                "══ 流水线结束，用时 %s ══" % _fmt_duration(elapsed),
            )
            if self.cfg.get("notify", "desktop", default=True):
                title = "MAA 挂机完成" if ok else "MAA 挂机异常"
                body = "用时 %s" % _fmt_duration(elapsed) if ok else err[:120]
                notify(title, body, self.cfg)

    def _mode_name(self, mode):
        return {"full": "一键挂机", "emu": "仅启动模拟器", "maa": "仅启动 MAA"}.get(mode, mode)

    def _elapsed_ticker(self, started):
        while not self.stop_evt.is_set():
            self._set(elapsed=int(time.time() - started))
            time.sleep(1)

    # ---------------- 各阶段 ----------------

    def _phase_env(self):
        self._begin_phase("env")
        cli = self.cfg.get("mumu", "cli", default="")
        adb = self.cfg.get("mumu", "adb", default="")
        maa = self.cfg.maa_exe

        for label, path in (("模拟器 CLI", cli), ("adb", adb), ("MAA 主程序", maa)):
            if not path or not os.path.exists(path):
                raise PipelineError("找不到%s：%s（请在配置文件里修正路径）" % (label, path))
        self.log("ok", "环境自检通过")
        self.log("info", "模拟器 CLI %s" % cli)
        self.log("info", "MAA 主程序 %s" % maa)

        info = mumu_info(self.cfg)
        started = bool(info.get("is_android_started"))
        self._set(mumu="已就绪" if started else "未启动")
        self.log(
            "info",
            "模拟器当前状态：进程 %s，安卓 %s"
            % ("已启动" if info.get("is_process_started") else "未启动",
               "已就绪" if started else "未就绪"),
        )
        if process_running("MAA.exe"):
            self.log("warn", "检测到 MAA 已在运行，为避免配置冲突，请先手动关闭它再执行")
        self._end_phase("env")

    def _phase_launch(self):
        self._begin_phase("launch")
        info = mumu_info(self.cfg)
        if info.get("is_android_started"):
            self.log("info", "模拟器已在运行，跳过启动步骤")
            self._set(mumu="已就绪")
            self._end_phase("launch")
            return
        self.log("info", "正在启动模拟器（设备索引 %d）…" % self.cfg.vm_index)
        rc, out = mumu_control(self.cfg, "launch")
        if rc != 0:
            raise PipelineError("启动模拟器失败：%s" % (out or "退出码 %s" % rc))
        code = json_code(out)
        if code not in (None, 0):
            raise PipelineError("模拟器拒绝了启动请求（code=%s）" % code)
        self.log("info", "启动指令已发送，等待安卓系统启动")
        self._set(mumu="启动中")
        self._end_phase("launch")

    def _phase_ready(self):
        self._begin_phase("ready")
        timeout = int(self.cfg.get("mumu", "ready_timeout", default=180))
        interval = max(1, int(self.cfg.get("mumu", "poll_interval", default=3)))
        deadline = time.time() + timeout
        attempt = 0
        total = max(1, timeout // interval)
        while time.time() < deadline:
            if self.stop_evt.is_set():
                raise PipelineError("已被手动中止")
            attempt += 1
            try:
                info = mumu_info(self.cfg)
                ready = bool(info.get("is_android_started"))
            except PipelineError as exc:
                self.log("warn", "状态查询失败（第 %d 次）：%s" % (attempt, exc))
                ready = False
            if ready:
                self.log("ok", "安卓系统已就绪（用时约 %d 秒）" % int(timeout - (deadline - time.time())))
                self._set(mumu="已就绪")
                self._end_phase("ready")
                return
            self.log("info", "等待安卓启动… (%d/%d) is_android_started=false" % (attempt, total))
            time.sleep(interval)
        raise PipelineError("等待安卓系统就绪超时（%d 秒），请检查模拟器是否正常启动" % timeout)

    def _phase_adb(self):
        self._begin_phase("adb")
        adb = self.cfg.get("mumu", "adb", default="")
        addr = self.cfg.adb_address
        run_cmd([adb, "start-server"], timeout=30)
        rc, out, err = run_cmd([adb, "connect", addr], timeout=30)
        text = (out + err).strip()
        if text:
            self.log("info", "adb connect %s → %s" % (addr, text.splitlines()[0][:160]))

        deadline = time.time() + 60
        while time.time() < deadline:
            if self.stop_evt.is_set():
                raise PipelineError("已被手动中止")
            rc, out, _ = run_cmd([adb, "-s", addr, "shell", "getprop", "sys.boot_completed"], timeout=20)
            if "1" in out.strip().split("\n")[0]:
                self.log("ok", "ADB 已连通 %s，sys.boot_completed=1" % addr)
                self._set(adb="已连通")
                self._end_phase("adb")
                return
            time.sleep(2)
        raise PipelineError("ADB 连接超时，无法访问 %s，请确认模拟器已进入桌面" % addr)

    def _phase_maa(self):
        self._begin_phase("maa")
        if process_running("MAA.exe"):
            raise PipelineError("MAA 正在运行，请先关闭它（本工具需要通过启动参数切换配置）")

        try:
            info = mumu_info(self.cfg)
            if not info.get("is_android_started"):
                self.log("warn", "模拟器尚未就绪，MAA 很可能连接失败；建议改用「一键挂机」")
        except PipelineError:
            pass

        self._prev_current = inject_maa_profile(self.cfg, self.log)

        log_path = os.path.join(self.cfg.maa_dir, "debug", "gui.log")
        self._maasession_pos = os.path.getsize(log_path) if os.path.exists(log_path) else 0

        self.log("info", "拉起 MAA：--config %s" % self.cfg.get("maa", "profile", default=""))
        try:
            self.maa_proc = subprocess.Popen(
                [self.cfg.maa_exe, "--config", self.cfg.get("maa", "profile", default="")],
                cwd=self.cfg.maa_dir,
            )
        except Exception as exc:  # noqa: BLE001
            raise PipelineError("启动 MAA 失败：%s" % exc)
        self._set(maa="已拉起")

        if self.cfg.get("maa", "mirror_logs", default=True):
            self._tail_thread = threading.Thread(
                target=self._tail_maa_log, args=(log_path,), daemon=True
            )
            self._tail_thread.start()

        start_timeout = int(self.cfg.get("maa", "start_timeout", default=150))
        deadline = time.time() + start_timeout
        started = False
        while time.time() < deadline and not self.stop_evt.is_set():
            if self._completed or self._started_evidence:
                started = True
                break
            if self._connect_failed:
                raise PipelineError(
                    "MAA 无法连接模拟器（%s）。请确认模拟器已启动并进入桌面后重试；"
                    "也可以直接使用「一键挂机」，它会先确保模拟器就绪" % self.cfg.adb_address
                )
            with self.lock:
                if self.state["task"] not in ("—", ""):
                    started = True
                    break
            if self.maa_proc.poll() is not None:
                raise PipelineError("MAA 进程已退出（退出码 %s）" % self.maa_proc.returncode)
            time.sleep(1)

        if started:
            self.log("ok", "MAA 已开始执行任务")
        elif self.stop_evt.is_set():
            self.log("info", "已中止，未确认任务是否开始")
        else:
            self.log(
                "warn",
                "MAA 已拉起，但 %d 秒内没有检测到任务开始。"
                "若界面停在待机状态，请检查「%s」配置是否可用"
                % (start_timeout, self.cfg.get("maa", "profile", default="")),
            )
        self._set(maa="运行中")
        self._end_phase("maa")
        self._monitor_maa()

    def _close_maa(self, reason: str):
        """关闭 MAA：先请窗口自己退出，超时再终止，最后强杀。"""
        proc = self.maa_proc
        if proc is None or proc.poll() is not None:
            return
        self.log("warn", "正在关闭 MAA（%s）…" % reason)
        try:
            post_close_to_pid(proc.pid)
        except Exception:
            pass
        try:
            proc.wait(timeout=8)
            self.log("info", "MAA 已正常退出")
            return
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=10)
            self.log("info", "MAA 已终止")
            return
        except Exception:
            pass
        try:
            proc.kill()
            self.log("warn", "MAA 未响应，已强制结束")
        except Exception:
            pass

    def _monitor_maa(self):
        self.log("info", "进入挂机监控，可随时点「中止」停止")
        auto_close = bool(self.cfg.get("maa", "close_after_complete", default=True))
        try:
            delay = max(0, int(self.cfg.get("maa", "close_delay", default=10) or 0))
        except Exception:
            delay = 10

        done_at = None
        while not self.stop_evt.is_set():
            if self.maa_proc is None or self.maa_proc.poll() is not None:
                break
            # 关键：MAA 报「任务已全部完成」后 GUI 进程并不会自己退出。
            # 必须在这里主动收尾，否则会一直空转等进程退出（旧版本即如此，
            # 表现为任务跑完但迟迟不关 MAA / 模拟器，只能手动点「中止」）。
            if self._completed:
                if done_at is None:
                    done_at = time.time()
                    if auto_close:
                        self.log("ok", "任务已全部完成，%d 秒后自动关闭 MAA 并收尾" % delay)
                    else:
                        self.log("info", "任务已全部完成（按配置保留 MAA 运行）")
                elif auto_close and time.time() - done_at >= delay:
                    self._close_maa("任务已全部完成")
                    break
            time.sleep(0.5)

        if self.stop_evt.is_set() and self.maa_proc and self.maa_proc.poll() is None:
            self._close_maa("收到中止请求")
        time.sleep(1.5)  # 给日志线程一点时间收尾
        self._set(maa="已退出")

    def _phase_wrap(self):
        self._begin_phase("wrap")
        max_wait = 10
        waited = 0
        while waited < max_wait and self._tail_thread and self._tail_thread.is_alive():
            time.sleep(0.5)
            waited += 0.5
        restore_maa_current(self.cfg, self._prev_current, self.log)

        if self._completed:
            self.log("ok", "已确认 MAA 报告「任务已全部完成」")
            if self.cfg.get("mumu", "shutdown_after_complete", default=True):
                self.log("info", "正在关闭模拟器…")
                rc, out = mumu_control(self.cfg, "shutdown")
                if rc == 0 and self._wait_mumu_stopped():
                    self.log("ok", "模拟器已关闭")
                    self._set(mumu="已关闭")
                elif rc == 0:
                    self.log("warn", "关闭指令已发送，但实例仍在运行，请手动确认")
                else:
                    self.log("warn", "关闭模拟器失败：%s" % (out or "退出码 %s" % rc))

                if self.cfg.get("mumu", "close_manager", default=True):
                    cli = self.cfg.get("mumu", "cli", default="")
                    rc, out = mumu_main("close", cli)
                    if rc == 0:
                        self.log("ok", "MuMu 管理器已关闭")
                    else:
                        self.log("info", "MuMu 管理器未能关闭：%s" % (out or "退出码 %s" % rc))
            else:
                self.log("info", "按配置保留模拟器运行")
        else:
            self.log("warn", "未检测到「任务已全部完成」，保留模拟器运行以避免误关")
        self._end_phase("wrap")

    def _wait_mumu_stopped(self, timeout=25):
        """关闭指令是异步的，确认实例进程真的退出了再往下走。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                info = mumu_info(self.cfg)
            except Exception:
                return False
            if not info.get("is_process_started"):
                return True
            time.sleep(1.5)
        return False

    # ---------------- MAA 日志镜像 ----------------

    RE_LOG_LINE = re.compile(r"^\[[\d\-. :]+\]\[(\w+)\]\[([^\]]+)\]\s*(?:<\d+>)?\s*(.*)$")
    RE_TASK_START = re.compile(r"开始任务[:：]\s*(.+?)\s*$")
    RE_TASK_DONE = re.compile(r"完成任务[:：]\s*(.+?)\s*$")
    RE_ALL_DONE = re.compile(r"任务已全部完成")
    RE_CONNECTING = re.compile(r"正在连接模拟器")
    RE_CONNECT_FAIL = re.compile(r"连接失败|[Cc]onnect(?:ion)? fail|[Ff]ailed to connect")
    RE_CONNECT_OK = re.compile(r"连接成功|已连接|[Cc]onnected successfully")
    RE_LINK_START = re.compile(r"LinkStartWithTasks|Idle: true to false")
    RE_NOISE = re.compile(r"UpdateStageList|HttpResponseLogging|ConnectionInfo|Serialize|截图")

    def _log_maa(self, level, msg, window=3.0):
        """中继 MAA 日志到界面。同一条消息在 window 秒内只播报一次，避免重复刷屏。"""
        now = time.time()
        recent = self._maa_recent
        if now - recent.get(msg, 0.0) < window:
            return
        recent[msg] = now
        self.log(level, msg)

    def _tail_maa_log(self, path):
        """跟随 MAA 日志。只要 MAA 还活着就持续跟随，不会因为战斗期间日志安静而提前退出。"""
        pos = self._maasession_pos
        idle = 0
        while not self.stop_evt.is_set():
            alive = self.maa_proc is not None and self.maa_proc.poll() is None
            if os.path.exists(path):
                try:
                    size = os.path.getsize(path)
                    if size < pos:
                        pos = 0
                    if size > pos:
                        with open(path, "r", encoding="utf-8", errors="replace") as fh:
                            fh.seek(pos)
                            chunk = fh.read()
                            pos = fh.tell()
                        idle = 0
                        pending = getattr(self, "_maa_pending", "") + chunk
                        lines = pending.split("\n")
                        self._maa_pending = lines.pop()   # 末尾可能写到一半，留到下一轮
                        for line in lines:
                            self._handle_maa_line(line.rstrip("\r"))
                    else:
                        idle += 1
                except Exception:
                    idle += 1
            else:
                idle += 1
            if not alive and idle >= 3:
                break
            time.sleep(1)

    def _handle_maa_line(self, line: str):
        if not line.strip() or self.RE_NOISE.search(line):
            return
        match = self.RE_LOG_LINE.match(line.strip())
        if not match:
            return
        level, _cls, body = match.groups()
        body = body.strip()

        if self.RE_ALL_DONE.search(body):
            self._completed = True
            self._log_maa("ok", "MAA：任务已全部完成")
            self._set(task="全部完成")
            return
        if self.RE_CONNECT_FAIL.search(body):
            self._connect_failed = True
            self._log_maa("error", "MAA：%s" % body[:200], window=8.0)
            return
        if self.RE_CONNECTING.search(body):
            self._log_maa("info", "MAA：正在连接模拟器…")
            return
        if self.RE_CONNECT_OK.search(body):
            self._started_evidence = True
            self._log_maa("ok", "MAA：已连接模拟器")
            return
        if self.RE_LINK_START.search(body):
            self._started_evidence = True
            self._log_maa("ok", "MAA：任务队列已启动", window=30.0)
            return
        if level == "ERR":
            self._log_maa("error", "MAA：%s" % body[:200])
            return
        if level == "WRN":
            self._log_maa("warn", "MAA：%s" % body[:200])
            return
        m = self.RE_TASK_START.search(body)
        if m:
            self._started_evidence = True
            self._log_maa("ok", "MAA 开始任务：%s" % m.group(1))
            self._set(task=m.group(1))
            return
        m = self.RE_TASK_DONE.search(body)
        if m:
            self.log("info", "MAA 完成任务：%s" % m.group(1))
            return


def _fmt_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "%d 秒" % seconds
    return "%d 分 %d 秒" % (seconds // 60, seconds % 60)


# ============================================================ 定时调度


class Scheduler(threading.Thread):
    def __init__(self, cfg: Config, engine: Engine, bus: Bus):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.engine = engine
        self.bus = bus
        self._fired = collections.deque(maxlen=200)
        self._last_check = None
        self.stop_evt = threading.Event()

    def run(self):
        while not self.stop_evt.is_set():
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001
                self.bus.log("warn", "定时调度检查异常：%s" % exc)
            self.stop_evt.wait(15)

    def _tick(self):
        conf = self.cfg.get("schedule", default={}) or {}
        times = schedule_times(conf)
        days = schedule_days(conf)
        now = dt.datetime.now()

        if not conf.get("enabled") or not times:
            self.engine._set(next_schedule="")  # noqa: SLF001
            self._last_check = now
            return

        self.engine._set(  # noqa: SLF001
            next_schedule=_describe_next(now, next_run(now, times, days), days, times)
        )

        # 触发判定：扫描 (上次检查, 现在] 区间内命中的所有时间点。
        # 用区间而不是"小时分钟相等"，可以补上休眠/卡顿漏掉的整分钟。
        prev = self._last_check or (now - dt.timedelta(seconds=20))
        self._last_check = now
        hits = []
        for stamp in times:
            hh, mm = [int(x) for x in stamp.split(":")]
            for offset in (0, -1):  # 跨零点时昨天的时间点也可能落在区间内
                day = (now + dt.timedelta(days=offset)).date()
                if day.weekday() not in days:
                    continue
                cand = dt.datetime.combine(day, dt.time(hh, mm))
                if prev < cand <= now:
                    hits.append(cand)

        for cand in sorted(hits):
            key = cand.strftime("%Y-%m-%d %H:%M")
            if key in self._fired:
                continue
            self._fired.append(key)
            self._fire(cand, conf)

    def _fire(self, cand: dt.datetime, conf: dict):
        label = cand.strftime("%H:%M")
        if conf.get("only_if_idle", True) and self.engine.state.get("running"):
            self.bus.log("warn", "定时触发时间到（%s），但流水线正在运行，本次跳过" % label)
            return
        self.bus.log("phase", "⏰ 定时触发（%s），开始执行一键挂机" % label)
        self.engine.start("full")


def schedule_times(conf: dict) -> list:
    """读取生效时间点：优先 times 列表，兼容历史配置里的单个 time 字段。"""
    raw = conf.get("times")
    items = []
    if isinstance(raw, list) and raw:
        items = [str(x) for x in raw]
    elif conf.get("time"):
        items = [str(conf.get("time"))]
    cleaned = []
    for item in items:
        match = re.match(r"^\s*(\d{1,2}):(\d{1,2})\s*$", item)
        if not match:
            continue
        hh, mm = int(match.group(1)), int(match.group(2))
        if 0 <= hh < 24 and 0 <= mm < 60:
            stamp = "%02d:%02d" % (hh, mm)
            if stamp not in cleaned:
                cleaned.append(stamp)
    return sorted(cleaned)


def schedule_days(conf: dict) -> list:
    """生效的星期（0=周一）。空或非法值按每天处理。"""
    days = conf.get("days")
    if not isinstance(days, list) or not days:
        return list(range(7))
    out = []
    for item in days:
        try:
            val = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= val <= 6 and val not in out:
            out.append(val)
    return sorted(out) or list(range(7))


def next_run(now: dt.datetime, times: list, days: list):
    """往后找最近一个触发时刻，最多看 8 天。"""
    for offset in range(0, 8):
        day = (now + dt.timedelta(days=offset)).date()
        if day.weekday() not in days:
            continue
        for stamp in times:
            hh, mm = [int(x) for x in stamp.split(":")]
            cand = dt.datetime.combine(day, dt.time(hh, mm))
            if cand > now:
                return cand
    return None


def _describe_next(now: dt.datetime, nxt, days: list, times: list) -> str:
    if nxt is None:
        head = "没有可用的时间点"
    else:
        mins = max(0, int((nxt - now).total_seconds() // 60))
        if mins < 1:
            tail = "不到 1 分钟"
        elif mins < 60:
            tail = "还有 %d 分钟" % mins
        elif mins < 1440:
            tail = "还有 %d 小时 %d 分" % divmod(mins, 60)
        else:
            tail = "还有 %d 天" % (mins // 1440)
        days_ahead = (nxt.date() - now.date()).days
        if days_ahead == 0:
            day_txt = "今天"
        elif days_ahead == 1:
            day_txt = "明天"
        else:
            day_txt = WEEK_NAMES[nxt.weekday()]
        head = "下次 %s（%s，%s）" % (nxt.strftime("%H:%M"), day_txt, tail)
    scope = "全周生效" if len(days) == 7 else ("生效：" + _days_text(days))
    return "%s · 每天 %d 次 · %s" % (head, len(times), scope)


def _days_text(days):
    try:
        return "、".join(WEEK_NAMES[int(d)] for d in sorted(days))
    except Exception:
        return "指定日期"


def normalized_schedule(cfg: Config) -> dict:
    """给界面用的规范化定时配置（永远带 times 数组，前端不用管兼容逻辑）。"""
    conf = cfg.get("schedule", default={}) or {}
    return {
        "enabled": bool(conf.get("enabled", True)),
        "times": schedule_times(conf),
        "days": schedule_days(conf),
        "only_if_idle": bool(conf.get("only_if_idle", True)),
    }


def normalized_notify(cfg: Config) -> dict:
    """给界面用的规范化通知配置：每个通道的字段都补齐默认值。"""
    conf = cfg.get("notify", default={}) or {}
    out = {"desktop": bool(conf.get("desktop", True))}
    for key in _SENDERS:
        sub = conf.get(key)
        if not isinstance(sub, dict):
            sub = {}
        merged = dict(DEFAULT_CONFIG["notify"].get(key) or {})
        merged.update(sub)
        merged["enabled"] = bool(sub.get("enabled"))
        out[key] = merged
    return out


# ============================================================ 通知

# 通知通道清单：key 与配置 notify.<key> 对应。
CHANNEL_LABELS = {
    "desktop": "桌面通知（托盘气泡）",
    "email": "邮件通知（QQ 邮箱可直接用）",
    "serverchan": "Server酱（推送到微信）",
    "pushplus": "PushPlus（推送到微信）",
    "wxpusher": "WxPusher（推送到微信）",
    "qmsg": "Qmsg酱（推送到 QQ）",
    "webhook": "自定义 Webhook（企业微信/钉钉/飞书）",
}

WEBHOOK_FORMATS = ("通用 JSON", "企业微信机器人", "钉钉机器人", "飞书机器人")


def _http_post(url: str, form: dict | None = None, json_body=None,
               headers: dict | None = None, timeout: int = 15):
    """极简 HTTP POST：返回 (是否拿到响应, 状态码, 响应文本)。不依赖第三方库。"""
    import urllib.error
    import urllib.parse
    import urllib.request

    data = None
    hdrs = dict(headers or {})
    if json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
    elif form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    hdrs.setdefault("User-Agent", "MAA-Pipeline/1.0")
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = str(exc)
        return True, exc.code, body
    except Exception as exc:  # noqa: BLE001
        return False, 0, "%s: %s" % (type(exc).__name__, exc)


def _pick(data: dict, *keys, default=""):
    for key in keys:
        if isinstance(data, dict) and data.get(key) not in (None, ""):
            return data[key]
    return default


def _parse(text: str):
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


def _resp_detail(text: str, limit: int = 160) -> str:
    """把接口返回压成一行可读信息。"""
    data = _parse(text)
    if isinstance(data, dict):
        for key in ("reason", "msg", "message", "error", "errmsg", "description"):
            val = data.get(key)
            if val:
                return str(val)[:limit]
        if "code" in data:
            return "code=%s" % data.get("code")
    return (text or "").strip().replace("\n", " ")[:limit]


# ---------------- 各通道发送实现 ----------------
# 每个函数返回 (是否成功, 说明文本)


def _send_email(conf: dict, title: str, body: str):
    host = (conf.get("smtp_host") or "").strip()
    to = (conf.get("to") or "").strip()
    user = (conf.get("username") or "").strip()
    if not host or not to:
        return False, "未填写 SMTP 服务器或收件邮箱"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"] = user
    msg["To"] = to
    port = int(conf.get("smtp_port") or 465)
    try:
        if conf.get("use_ssl", True):
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls()
        try:
            server.login(user, conf.get("password") or "")
            server.sendmail(user, [x.strip() for x in to.split(",") if x.strip()], msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:  # noqa: BLE001
                pass
        return True, "已发送至 %s" % to
    except Exception as exc:  # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, exc)


def _send_serverchan(conf: dict, title: str, body: str):
    key = (conf.get("sendkey") or "").strip()
    if not key:
        return False, "未填写 SendKey"
    url = "https://sctapi.ftqq.com/%s.send" % key
    ok, status, text = _http_post(url, form={"title": title[:32], "desp": body})
    if not ok:
        return False, "网络异常 %s" % text
    data = _parse(text)
    if isinstance(data, dict) and str(data.get("code")) == "0":
        return True, "已推送到微信"
    detail = _resp_detail(text)
    if "SCT" in detail.upper() or "key" in detail.lower() or "SendKey" in detail:
        detail = "SendKey 无效或已过期（%s）" % detail
    return False, detail or ("HTTP %s" % status)


def _send_pushplus(conf: dict, title: str, body: str):
    token = (conf.get("token") or "").strip()
    if not token:
        return False, "未填写 token"
    payload = {
        "token": token,
        "title": title,
        "content": body,
        "template": conf.get("template") or "txt",
    }
    topic = (conf.get("topic") or "").strip()
    if topic:
        payload["topic"] = topic
    channel = (conf.get("channel") or "wechat").strip()
    if channel and channel != "wechat":
        payload["channel"] = channel
    ok, status, text = _http_post("https://www.pushplus.plus/send", json_body=payload)
    if not ok:
        return False, "网络异常 %s" % text
    data = _parse(text)
    if isinstance(data, dict) and str(data.get("code")) == "200":
        return True, "已受理（%s）" % (data.get("msg") or "请求成功")
    return False, _resp_detail(text) or ("HTTP %s" % status)


def _send_wxpusher(conf: dict, title: str, body: str):
    token = (conf.get("app_token") or "").strip()
    if not token:
        return False, "未填写 appToken"
    uids, topics = [], []
    for item in re.split(r"[,\s;，；]+", (conf.get("uids") or "").strip()):
        if not item:
            continue
        if item.upper().startswith("UID_"):
            uids.append(item)
        elif item.isdigit():
            topics.append(int(item))
        else:
            uids.append(item)
    if not uids and not topics:
        return False, "未填写接收者（UID_xxx 或主题 ID）"
    payload = {"appToken": token, "content": "%s\n%s" % (title, body), "summary": title[:90],
               "contentType": 1}
    if uids:
        payload["uids"] = uids
    if topics:
        payload["topicIds"] = topics
    ok, status, text = _http_post("https://wxpusher.zjiecode.com/api/send/message",
                                  json_body=payload)
    if not ok:
        return False, "网络异常 %s" % text
    data = _parse(text)
    if isinstance(data, dict) and str(data.get("code")) == "1000":
        return True, "已推送到微信（%s）" % (data.get("msg") or "处理成功")
    return False, _resp_detail(text) or ("HTTP %s" % status)


def _send_qmsg(conf: dict, title: str, body: str):
    key = (conf.get("key") or "").strip()
    if not key:
        return False, "未填写 Qmsg Key"
    mode = "group" if (conf.get("type") or "send").strip() == "group" else "send"
    url = "https://qmsg.zendee.cn/%s/%s" % (mode, key)
    form = {"msg": "%s\n%s" % (title, body)}
    qq = (conf.get("qq") or "").strip()
    if qq:
        form["qq"] = qq
    ok, status, text = _http_post(url, form=form)
    if not ok:
        return False, "网络异常 %s" % text
    data = _parse(text)
    if isinstance(data, dict):
        if data.get("success"):
            return True, "已推送到 QQ（%s）" % (data.get("reason") or "操作成功")
        return False, str(data.get("reason") or _resp_detail(text))
    return False, _resp_detail(text) or ("HTTP %s" % status)


def _webhook_payload(fmt: str, title: str, body: str):
    text = "%s\n%s" % (title, body)
    fmt = (fmt or "").strip()
    if fmt == "企业微信机器人":
        return {"msgtype": "text", "text": {"content": text}}
    if fmt == "钉钉机器人":
        return {"msgtype": "text", "text": {"content": text}}
    if fmt == "飞书机器人":
        return {"msg_type": "text", "content": {"text": text}}
    return {"title": title, "content": body, "text": text,
            "channel": "maa-pipeline"}


def _send_webhook(conf: dict, title: str, body: str):
    url = (conf.get("url") or "").strip()
    if not url:
        return False, "未填写 Webhook 地址"
    if not url.lower().startswith(("http://", "https://")):
        return False, "地址需以 http:// 或 https:// 开头"
    payload = _webhook_payload(conf.get("format"), title, body)
    ok, status, text = _http_post(url, json_body=payload)
    if not ok:
        return False, "网络异常 %s" % text
    data = _parse(text)
    if isinstance(data, dict) and data.get("errcode") not in (None, 0):
        return False, _resp_detail(text)
    if isinstance(data, dict) and data.get("code") not in (None, 0, 200):
        return False, _resp_detail(text)
    return True, "已提交（HTTP %s）" % status


_SENDERS = {
    "email": _send_email,
    "serverchan": _send_serverchan,
    "pushplus": _send_pushplus,
    "wxpusher": _send_wxpusher,
    "qmsg": _send_qmsg,
    "webhook": _send_webhook,
}


def _enabled_channels(conf: dict):
    """挑出已启用的通道；desktop 只看布尔开关，其余要求 enabled 为真。"""
    active = []
    if conf.get("desktop", True):
        active.append("desktop")
    for key in _SENDERS:
        sub = conf.get(key) or {}
        if isinstance(sub, dict) and sub.get("enabled"):
            active.append(key)
    return active


def notify_all(title: str, body: str, cfg: Config, bus=None, only=None) -> list:
    """按配置发送通知，返回每个通道的结果列表（供界面回显）。"""
    conf = cfg.get("notify", default={}) or {}
    channels = only if only else _enabled_channels(conf)
    results = []

    if "desktop" in channels:
        tray = TRAY_INSTANCE
        if tray is not None and tray.active:
            tray.notify(title, body)
            results.append({"channel": "desktop", "label": CHANNEL_LABELS["desktop"],
                            "ok": True, "detail": "已弹出托盘提示"})
        else:
            results.append({"channel": "desktop", "label": CHANNEL_LABELS["desktop"],
                            "ok": False, "detail": "托盘未启用"})

    for key in channels:
        sender = _SENDERS.get(key)
        if sender is None:
            continue
        sub = conf.get(key) or {}
        label = CHANNEL_LABELS.get(key, key)
        try:
            ok, detail = sender(sub, title, body)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, "%s: %s" % (type(exc).__name__, exc)
        results.append({"channel": key, "label": label, "ok": ok, "detail": detail})

    if bus is not None:
        for item in results:
            bus.log("ok" if item["ok"] else "warn",
                    "通知·%s：%s" % (item["label"], item["detail"]))
    _append_file_log("info", "通知已发送：%s" % "、".join(
        "%s(%s)" % (r["label"], "成功" if r["ok"] else "失败") for r in results) or "无通道启用")
    return results


def notify(title: str, body: str, cfg: Config, bus=None):
    """兼容原有调用：异步发送，不阻塞主流程。"""
    if bus is None:
        bus = RUNTIME.get("bus")
    conf = cfg.get("notify", default={}) or {}
    if not _enabled_channels(conf):
        return
    threading.Thread(target=notify_all, args=(title, body, cfg, bus), daemon=True).start()



# ============================================================ 托盘图标（纯 ctypes）


WM_APP = 0x8000
WM_TRAY_CALLBACK = WM_APP + 1
WM_DESTROY = 0x0002
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
IDI_APPLICATION = 32512

MENU_OPEN, MENU_RUN, MENU_QUIT = 1001, 1002, 1003
MF_STRING = 0x0000
TPM_RETURNCMD, TPM_LEFTALIGN, TPM_BOTTOMALIGN = 0x0100, 0x0000, 0x0020

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


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wt.HWND),
        ("message", wt.UINT),
        ("wParam", wt.WPARAM),
        ("lParam", wt.LPARAM),
        ("time", wt.DWORD),
        ("pt", wt.POINT),
        ("lPrivate", wt.DWORD),
    ]


class Tray(threading.Thread):
    """系统托盘图标：双击打开界面，右键菜单可立即挂机 / 退出。"""

    _class_registered = False

    def __init__(self, cfg: Config, engine: Engine, bus: Bus, url: str):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.engine = engine
        self.bus = bus
        self.url = url
        self.active = False
        self.hwnd = None
        self._nid = NOTIFYICONDATAW()
        self._proc = None
        self._user32 = ctypes.windll.user32
        self._shell32 = ctypes.windll.shell32
        self._kernel32 = ctypes.windll.kernel32
        self._setup_signatures()

    def _setup_signatures(self):
        u = self._user32
        u.LoadIconW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
        u.LoadIconW.restype = wt.HICON
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
        u.CreatePopupMenu.argtypes = []
        u.CreatePopupMenu.restype = wt.HMENU
        u.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
        u.AppendMenuW.restype = wt.BOOL
        u.DestroyMenu.argtypes = [wt.HMENU]
        u.SetForegroundWindow.argtypes = [wt.HWND]
        u.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
        u.GetMessageW.argtypes = [ctypes.POINTER(MSG), wt.HWND, wt.UINT, wt.UINT]
        u.GetMessageW.restype = ctypes.c_int
        u.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
        u.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
        u.DispatchMessageW.restype = LRESULT
        u.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        u.PostQuitMessage.argtypes = [ctypes.c_int]
        u.DestroyWindow.argtypes = [wt.HWND]
        u.TrackPopupMenu.argtypes = [
            wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, ctypes.c_void_p
        ]
        u.TrackPopupMenu.restype = ctypes.c_int
        self._shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
        self._shell32.Shell_NotifyIconW.restype = wt.BOOL

    def run(self):
        try:
            self._create()
            self.active = True
            self.bus.log("info", "托盘图标已就绪（双击打开界面，右键可立即挂机）")
            self._loop()
        except Exception as exc:  # noqa: BLE001
            self.active = False
            self.bus.log("warn", "托盘图标初始化失败（不影响主功能）：%s" % exc)

    def _create(self):
        hinst = self._kernel32.GetModuleHandleW(None)
        self._proc = WNDPROC(self._wndproc)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = "MAAPipelineTrayWnd"
        if not Tray._class_registered:
            self._user32.RegisterClassW(ctypes.byref(wc))
            Tray._class_registered = True
        self.hwnd = self._user32.CreateWindowExW(
            0, wc.lpszClassName, "MAA-Pipeline", 0, 0, 0, 0, 0, None, None, hinst, None
        )
        if not self.hwnd:
            raise OSError("创建隐藏窗口失败")

        nid = self._nid
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY_CALLBACK
        nid.hIcon = _load_icon_handle(16) or self._user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
        nid.szTip = "MAA 一键挂机"
        if not self._shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            raise OSError("Shell_NotifyIcon(NIM_ADD) 失败")

    def _loop(self):
        msg = MSG()
        while self._user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            self._user32.TranslateMessage(ctypes.byref(msg))
            self._user32.DispatchMessageW(ctypes.byref(msg))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY_CALLBACK:
                event = lparam & 0xFFFF
                if event in (WM_RBUTTONUP,):
                    self._menu()
                elif event == WM_LBUTTONDBLCLK:
                    open_interface(self.url)
            elif msg == WM_DESTROY:
                self._user32.PostQuitMessage(0)
            return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        except Exception:
            return 0

    def _menu(self):
        menu = self._user32.CreatePopupMenu()
        self._user32.AppendMenuW(menu, MF_STRING, MENU_OPEN, "显示主界面")
        self._user32.AppendMenuW(menu, MF_STRING, MENU_RUN, "立即挂机")
        self._user32.AppendMenuW(menu, MF_STRING, MENU_QUIT, "退出")
        pt = wt.POINT()
        self._user32.GetCursorPos(ctypes.byref(pt))
        self._user32.SetForegroundWindow(self.hwnd)
        cmd = self._user32.TrackPopupMenu(
            menu, TPM_RETURNCMD | TPM_LEFTALIGN, pt.x, pt.y, 0, self.hwnd, None
        )
        self._user32.DestroyMenu(menu)
        if cmd == MENU_OPEN:
            webbrowser.open(self.url)
        elif cmd == MENU_RUN:
            self.engine.start("full")
        elif cmd == MENU_QUIT:
            self.bus.log("info", "从托盘退出")
            self.stop()
            threading.Thread(target=_shutdown, daemon=True).start()

    def notify(self, title: str, body: str):
        try:
            nid = self._nid
            nid.uFlags = NIF_INFO
            nid.szInfoTitle = title[:62]
            nid.szInfo = body[:254]
            nid.dwInfoFlags = 0x01  # NIIF_INFO
            self._shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass

    def stop(self):
        try:
            self._shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
        except Exception:
            pass
        try:
            if self.hwnd:
                self._user32.PostMessageW(self.hwnd, WM_DESTROY, 0, 0)
        except Exception:
            pass
        self.active = False


TRAY_INSTANCE = None


def _shutdown():
    time.sleep(0.6)
    os._exit(0)


# ============================================================ 原生窗口（pywebview）
WINDOW_TITLE = "MAA 一键挂机"


def has_pywebview() -> bool:
    """装了 pywebview 且能加载 WebView2 时才走原生窗口，否则自动退回浏览器。"""
    try:
        import webview  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _focus_by_win32(title: str) -> bool:
    """兜底：直接让系统把同名顶层窗口抬到最前，不依赖 pywebview 的实现细节。"""
    try:
        u = ctypes.windll.user32
        hwnd = u.FindWindowW(None, title)
        if not hwnd:
            return False
        u.ShowWindowAsync(hwnd, 9)  # SW_RESTORE
        u.SetForegroundWindow(hwnd)
        return True
    except Exception:  # noqa: BLE001
        return False


def _icon_path():
    """应用图标位置：打包后优先取内置资源，其次工具目录。"""
    for p in (os.path.join(RES_DIR, "app.ico"), os.path.join(APP_DIR, "app.ico")):
        if os.path.exists(p):
            return p
    return None


def _load_icon_handle(cx: int):
    """从 app.ico 加载指定尺寸的图标句柄；失败返回 None（调用方回退系统图标）。"""
    path = _icon_path()
    if not path:
        return None
    try:
        IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
        return ctypes.windll.user32.LoadImageW(None, path, IMAGE_ICON, cx, cx, LR_LOADFROMFILE) or None
    except Exception:  # noqa: BLE001
        return None


class NativeWindow:
    """把网页界面装进原生窗口，用起来更接近 MAA 这类桌面程序。

    - 关掉窗口不退出：最小化到托盘，挂机与定时继续在后台跑
    - 托盘双击 / 菜单「打开界面」：唤起同一个窗口，不会越开越多
    - 已有实例在跑时再次双击：唤起那个实例的窗口
    """

    def __init__(self, url: str, cfg: Config, bus: Bus):
        self.url = url
        self.cfg = cfg
        self.bus = bus
        self.win = None
        self.ready = False
        self.keep_in_tray = bool(cfg.get("tray", "enabled", default=True))

    def start(self):
        import webview

        self.win = webview.create_window(
            WINDOW_TITLE,
            self.url,
            width=1220,
            height=840,
            min_size=(960, 640),
            background_color="#F7F7F5",
        )
        try:
            self.win.events.closing += self._on_closing
        except Exception as exc:  # noqa: BLE001
            self.bus.log("warn", "窗口关闭事件未挂上：%s" % exc)
        self.ready = True
        webview.start(self._on_gui_ready)   # 阻塞在这里，直到窗口真的被关闭
        self.ready = False

    def _on_gui_ready(self):
        try:
            u = ctypes.windll.user32
            hwnd = u.FindWindowW(None, WINDOW_TITLE)
            if hwnd:
                big = _load_icon_handle(32)
                small = _load_icon_handle(16)
                if big:
                    u.SendMessageW(hwnd, 0x80, 1, big)    # WM_SETICON / ICON_BIG
                if small:
                    u.SendMessageW(hwnd, 0x80, 0, small)  # WM_SETICON / ICON_SMALL
        except Exception:  # noqa: BLE001
            pass
        self.bus.log("info", "原生窗口已打开（关闭窗口 = 最小化到托盘）")

    def _on_closing(self):
        if not self.keep_in_tray:
            return True
        try:
            self.win.hide()
        except Exception as exc:  # noqa: BLE001
            self.bus.log("warn", "窗口隐藏失败，改为直接退出：%s" % exc)
            return True
        self.bus.log("info", "窗口已最小化到托盘（双击托盘图标可重新打开）")
        tray = TRAY_INSTANCE
        if tray is not None and getattr(tray, "active", False):
            tray.notify(WINDOW_TITLE, "已最小化到托盘，挂机与定时仍在后台运行")
        return False             # 阻止真正关闭

    def show(self) -> bool:
        """从任意线程唤起窗口，成功返回 True。"""
        if not self.ready or self.win is None:
            return False
        try:
            self.win.show()
            try:
                self.win.restore()
            except Exception:  # noqa: BLE001
                pass
            return True
        except Exception as exc:  # noqa: BLE001
            self.bus.log("warn", "唤起窗口失败：%s" % exc)
        return _focus_by_win32(WINDOW_TITLE)

    def destroy(self):
        try:
            if self.win is not None:
                self.win.destroy()
        except Exception:  # noqa: BLE001
            pass


UI_INSTANCE = None


def open_interface(url: str):
    """统一入口：优先唤起原生窗口，没有窗口就退回浏览器。"""
    ui = UI_INSTANCE
    if ui is not None and ui.show():
        return
    webbrowser.open(url)


# ============================================================ HTTP 服务

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}

RUNTIME = {"cfg": None, "engine": None, "bus": None, "scheduler": None, "url": ""}

# 浏览器关页/刷新会中断 SSE 长连接，socketserver 默认会把这类正常断开
# 当成异常打印一大段 traceback。这里只屏蔽连接类异常，其他错误照常抛出。
_BENIGN = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError)


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, _BENIGN):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MAAPipeline"

    def log_message(self, *_args):
        pass

    # ---------- 工具 ----------

    def _json(self, payload, code=200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    # ---------- 路由 ----------

    def do_GET(self):
        cfg, engine, bus = RUNTIME["cfg"], RUNTIME["engine"], RUNTIME["bus"]
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            try:
                with open(UI_PATH, "rb") as fh:
                    raw = fh.read()
            except Exception:
                self._json({"error": "找不到 ui.html"}, 500)
                return
            self.send_response(200)
            self.send_header("Content-Type", MIME[".html"])
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)
            return
        if path == "/api/state":
            self._json(engine.snapshot())
            return
        if path == "/api/events":
            self._events()
            return
        if path == "/api/logs/download":
            self._download()
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        cfg, engine, bus = RUNTIME["cfg"], RUNTIME["engine"], RUNTIME["bus"]
        path = self.path.split("?")[0]
        body = self._body()

        if path == "/api/start":
            mode = body.get("mode") or "full"
            ok, msg = engine.start(mode)
            self._json({"ok": ok, "msg": msg})
            return
        if path == "/api/abort":
            engine.abort()
            self._json({"ok": True, "msg": "中止请求已发送"})
            return
        if path == "/api/config":
            incoming = body.get("config") or {}
            cfg.data = deep_merge(cfg.data, incoming)
            # 兼容字段同步：times 被清空时把老的 time 也清掉，
            # 否则会被当成"回退到单个时间"而继续触发。
            if isinstance(incoming.get("schedule"), dict):
                times = schedule_times(cfg.data.get("schedule") or {})
                cfg.data.setdefault("schedule", {})["time"] = times[0] if times else ""
            cfg.save()
            bus.log("info", "配置已保存")
            engine._publish()  # noqa: SLF001
            # 让定时器立刻按新配置重算"下次触发"，否则界面要等下一个巡检周期才更新
            sched = RUNTIME.get("scheduler")
            if sched is not None:
                try:
                    sched._tick()  # noqa: SLF001
                except Exception:  # noqa: BLE001
                    pass
            self._json({"ok": True, "msg": "配置已保存"})
            return
        if path == "/api/open-logs":
            try:
                os.startfile(LOG_DIR)
            except Exception:
                pass
            self._json({"ok": True})
            return
        if path == "/api/notify-test":
            # 支持三种用法：
            #   {}                       → 按已保存配置的全部启用通道发
            #   {"channel": "qmsg"}      → 只测某个通道（按已保存配置）
            #   {"channel":..., "config":{...}} → 用界面当前填写的内容测试，不写盘
            incoming = body.get("config")
            test_cfg = Config.from_data(deep_merge(cfg.data, incoming), cfg.path) if incoming else cfg
            channel = (body.get("channel") or "").strip() or None
            if channel and channel not in CHANNEL_LABELS:
                self._json({"ok": False, "msg": "未知通道：%s" % channel})
                return
            results = notify_all("MAA 挂机 · 测试通知",
                                 "如果你收到这条消息，说明该通道配置正确。",
                                 test_cfg, bus, only=[channel] if channel else None)
            failed = [r for r in results if not r["ok"]]
            summary = "、".join("%s：%s" % (r["label"], r["detail"]) for r in results) or "没有启用任何通道"
            self._json({
                "ok": not failed and bool(results),
                "msg": summary,
                "results": results,
            })
            return
        if path == "/api/focus":
            ui = UI_INSTANCE
            shown = bool(ui is not None and ui.show())
            if not shown:
                shown = _focus_by_win32(WINDOW_TITLE)
            self._json({"ok": True, "shown": shown})
            return
        if path == "/api/quit":
            self._json({"ok": True})
            tray = TRAY_INSTANCE
            if tray is not None:
                tray.stop()
            threading.Thread(target=_shutdown, daemon=True).start()
            return
        self._json({"error": "not found"}, 404)

    # ---------- SSE ----------

    def _events(self):
        bus = RUNTIME["bus"]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = bus.subscribe()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    item = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                payload = json.dumps(item, ensure_ascii=False)
                self.wfile.write(("data: %s\n\n" % payload).encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            bus.unsubscribe(q)

    def _download(self):
        name = dt.date.today().isoformat() + ".log"
        path = os.path.join(LOG_DIR, name)
        if not os.path.exists(path):
            self._json({"error": "今天还没有日志"}, 404)
            return
        with open(path, "rb") as fh:
            raw = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


# ============================================================ 自检


def selftest() -> int:
    print("=" * 62)
    print("MAA 一键挂机流水线 · 环境自检")
    print("=" * 62)
    problems = []

    cfg = Config()
    autodetect_paths(cfg)

    def check(label, path):
        ok = bool(path) and os.path.exists(path)
        print("  [%s] %-14s %s" % ("OK" if ok else "!!", label, path))
        if not ok:
            problems.append("%s 路径无效：%s" % (label, path))
        return ok

    print("\n[1] 依赖路径")
    check("模拟器 CLI", cfg.get("mumu", "cli", default=""))
    check("adb", cfg.get("mumu", "adb", default=""))
    check("MAA 主程序", cfg.maa_exe)
    print("  [i] MAA 目录 %s" % cfg.maa_dir)
    print("  [i] ADB 地址 %s" % cfg.adb_address)

    print("\n[2] MAA 配置文件")
    cfg_path = os.path.join(cfg.maa_dir, "config", "gui.new.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        confs = list((data.get("Configurations") or {}).keys())
        print("  [OK] 找到 gui.new.json，现有配置：%s" % "、".join(confs))
        print("  [i] 当前激活配置：%s" % data.get("Current"))
    else:
        print("  [!!] 找不到 %s" % cfg_path)
        problems.append("MAA 配置文件缺失")

    print("\n[3] 模拟器状态")
    try:
        info = mumu_info(cfg)
        print("  [OK] 实例 %s「%s」" % (info.get("index"), info.get("name")))
        print("  [i] 进程已启动：%s   安卓已就绪：%s"
              % (info.get("is_process_started"), info.get("is_android_started")))
    except PipelineError as exc:
        print("  [!!] %s" % exc)
        problems.append("无法读取模拟器状态")

    print("\n[4] MAA 进程")
    running = process_running("MAA.exe")
    print("  [%s] MAA.exe %s" % ("i" if running else "OK", "正在运行（执行流水线前需关闭）" if running else "未运行，可以执行"))

    print("\n[5] 托盘图标")
    try:
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
        print("  [i] NOTIFYICONDATAW 大小 = %d 字节（x64 期望 976）" % size)
        hinst = ctypes.windll.kernel32.GetModuleHandleW(None)

        def _st_wndproc(hwnd, msg, wparam, lparam):
            return u.DefWindowProcW(hwnd, msg, wparam, lparam)

        cb = WNDPROC(_st_wndproc)
        wc = WNDCLASSW()
        wc.lpfnWndProc = cb
        wc.hInstance = hinst
        wc.lpszClassName = "MAAPipelineSelfTest"
        atom = u.RegisterClassW(ctypes.byref(wc))
        print("  [i] RegisterClass 返回 atom = %s" % atom)
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
                print("  [OK] 托盘图标创建成功（已移除测试图标）")
            else:
                print("  [!!] Shell_NotifyIcon 返回失败")
                problems.append("托盘图标不可用")
            u.DestroyWindow(hwnd)
        else:
            print("  [!!] 隐藏窗口创建失败（atom=%s）" % atom)
            problems.append("托盘隐藏窗口创建失败")
    except Exception as exc:  # noqa: BLE001
        print("  [!!] 托盘自检异常：%s" % exc)
        problems.append("托盘自检异常")

    print("\n[6] 界面文件")
    print("  [%s] ui.html %s" % ("OK" if os.path.exists(UI_PATH) else "!!", UI_PATH))
    if not os.path.exists(UI_PATH):
        problems.append("ui.html 缺失")

    print("\n[7] 本地端口")
    port = int(cfg.get("server", "port", default=17800))
    import socket
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", port))
        print("  [OK] 端口 %d 可用" % port)
    except OSError as exc:
        print("  [!!] 端口 %d 被占用：%s" % (port, exc))
    finally:
        sock.close()

    print("\n" + "=" * 62)
    if problems:
        print("自检发现 %d 个问题：" % len(problems))
        for item in problems:
            print("  - %s" % item)
        return 1
    print("自检通过，一切就绪。")
    return 0


# ============================================================ 启动


def _is_our_service(url: str) -> bool:
    """探测该地址上跑的是不是本工具，而不是别的占用同端口的程序。"""
    import urllib.request

    try:
        with urllib.request.urlopen(url + "/api/state", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return isinstance(data, dict) and "phases" in data and "mode" in data
    except Exception:  # noqa: BLE001
        return False


def _resolve_ui_mode(cfg: Config) -> str:
    """决定界面形态：window = 原生窗口（像 MAA 那样），browser = 浏览器标签页。

    优先级：命令行参数 > 配置文件 > 自动判断（有 pywebview 就用原生窗口）。
    """
    mode = str(cfg.get("server", "window_mode", default="auto")).lower()
    if "--browser" in sys.argv:
        mode = "browser"
    elif "--window" in sys.argv:
        mode = "window"
    if mode == "auto":
        mode = "window" if has_pywebview() else "browser"
    if mode == "window" and not has_pywebview():
        mode = "browser"
    return mode


def _focus_existing(url: str) -> bool:
    """请正在运行的实例把它的窗口抬到最前，避免越开越多。"""
    import urllib.request

    try:
        req = urllib.request.Request(url + "/api/focus", data=b"{}", method="POST")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return bool(data.get("shown"))
    except Exception:  # noqa: BLE001
        return False


def main():
    global TRAY_INSTANCE, UI_INSTANCE
    if "--selftest" in sys.argv:
        sys.exit(selftest())

    no_tray = "--no-tray" in sys.argv
    cfg = Config()
    bus = Bus()
    autodetect_paths(cfg, bus.log)          # 换电脑后第一次运行自动找模拟器/MAA
    engine = Engine(cfg, bus)
    port = int(cfg.get("server", "port", default=17800))
    url = "http://127.0.0.1:%d" % port
    mode = _resolve_ui_mode(cfg)

    import socket

    # 注意：不能用 bind + SO_REUSEADDR 来判断端口占用。
    # Windows 上 SO_REUSEADDR 允许绑定已被别人占用的端口（hijack 语义），
    # 会导致"第二个实例照样起来"，两个服务抢同一个端口。
    # 这里改为主动 connect 探测，可靠且没有副作用。
    probe = socket.socket()
    probe.settimeout(1.5)
    try:
        occupied = probe.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        occupied = False
    finally:
        probe.close()

    if occupied:
        if _is_our_service(url):
            bus.log("info", "检测到已有实例在运行，正在唤起它的界面")
            if mode == "window" and _focus_existing(url):
                print("检测到已有实例在运行，已唤起它的窗口：%s" % url)
            else:
                webbrowser.open(url)
                print("检测到已有实例在运行，已打开现有界面：%s" % url)
            sys.exit(0)
        print(
            "端口 %d 已被其他程序占用，请修改 %s 里的 server.port 后重试。"
            % (port, CFG_PATH)
        )
        sys.exit(1)

    os.makedirs(LOG_DIR, exist_ok=True)
    RUNTIME.update({"cfg": cfg, "engine": engine, "bus": bus, "url": url})

    try:
        server = QuietServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        print("启动本地服务失败：%s" % exc)
        print("请确认端口 %d 未被占用，或修改 %s 里的 server.port" % (port, CFG_PATH))
        sys.exit(1)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()

    engine.state["server"] = url
    bus.log("info", "服务已启动：%s" % url)
    bus.log("info", "工具目录：%s" % APP_DIR)
    bus.log("info", "MAA 目录：%s" % cfg.maa_dir)

    scheduler = Scheduler(cfg, engine, bus)
    scheduler.start()
    RUNTIME["scheduler"] = scheduler

    sched = cfg.get("schedule", default={}) or {}
    if sched.get("enabled"):
        _times = schedule_times(sched)
        bus.log(
            "info",
            "定时挂机已启用：每天 %s" % ("、".join(_times) if _times else "（未设置时间点）"),
        )

    if not no_tray and cfg.get("tray", "enabled", default=True):
        TRAY_INSTANCE = Tray(cfg, engine, bus, url)
        TRAY_INSTANCE.start()

    try:
        if mode == "window":
            ui = NativeWindow(url, cfg, bus)
            UI_INSTANCE = ui
            RUNTIME["ui"] = ui
            bus.log("info", "正在打开原生窗口…")
            try:
                ui.start()
            except Exception as exc:  # noqa: BLE001
                UI_INSTANCE = None
                bus.log("warn", "原生窗口启动失败，改用浏览器界面：%s" % exc)
                mode = "browser"
            else:
                bus.log("info", "窗口已关闭，程序退出")
                return

        if mode == "browser" and cfg.get("server", "open_browser", default=True):
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bus.log("info", "收到退出信号")
    finally:
        scheduler.stop_evt.set()
        server.shutdown()


class _LogSink:
    """pythonw.exe 下 sys.stdout/stderr 是 None，直接写会抛 AttributeError。
    这里用文件兜底，既避免次生崩溃，也把输出留在 logs\\startup.log 里。"""

    def __init__(self, path: str):
        self._fh = None
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self._fh = open(path, "a", encoding="utf-8", buffering=1)
        except Exception:  # noqa: BLE001
            self._fh = None

    def write(self, text):
        if self._fh:
            try:
                self._fh.write(text)
            except Exception:  # noqa: BLE001
                pass
        return len(text)

    def flush(self):
        if self._fh:
            try:
                self._fh.flush()
            except Exception:  # noqa: BLE001
                pass

    def isatty(self):
        return False


# 注意：这个文件只由 Python 写（UTF-8）。
# 备用启动器 start-pipeline.vbs 走 WSH，按 ANSI/GBK 写 launcher.log，两者不要混写同一个文件，否则中文会乱码。
STARTUP_LOG = os.path.join(LOG_DIR, "startup.log")


def _report_fatal(exc: BaseException) -> str:
    """把致命错误落到 startup-error.log，返回可展示的摘要。"""
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, "startup-error.log"), "a", encoding="utf-8") as fh:
            fh.write("\n===== %s | PID %d | %s =====\n"
                     % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), os.getpid(),
                        " ".join(sys.argv)))
            fh.write(detail)
    except Exception:  # noqa: BLE001
        pass
    last = [ln for ln in detail.strip().splitlines() if ln.strip()]
    head = last[-1].strip() if last else "%s: %s" % (type(exc).__name__, exc)
    frames = [ln.strip() for ln in last if ln.strip().startswith('File "')]
    where = frames[-1] if frames else ""
    return (
        "程序启动失败，未能打开界面。\n\n"
        "%s\n%s\n\n"
        "完整信息已写入：\n%s"
        % (head, where, os.path.join(LOG_DIR, "startup-error.log"))
    )


def _show_error_box(text: str):
    """用系统原生弹窗报错，不依赖任何第三方库，pythonw 下也能看见。"""
    if os.environ.get("MAAPIPE_NO_MSGBOX"):
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, text, "MAA 一键挂机 - 启动失败", 0x10)
    except Exception:  # noqa: BLE001
        pass


def _bootstrap():
    """启动前兜底：补上被 pythonw 吞掉的输出通道，并记录一条启动足迹。"""
    global _SINK
    if sys.stdout is None or sys.stderr is None:
        _SINK = _LogSink(STARTUP_LOG)
        if sys.stdout is None:
            sys.stdout = _SINK
        if sys.stderr is None:
            sys.stderr = _SINK
    if getattr(sys, "stdin", "missing") is None:
        try:
            sys.stdin = open(os.devnull, "r", encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(STARTUP_LOG, "a", encoding="utf-8") as fh:
            fh.write("[%s] 入口启动 PID %d | %s\n"
                     % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), os.getpid(),
                        " ".join(sys.argv)))
    except Exception:  # noqa: BLE001
        pass


def _run_guarded():
    """唯一入口：任何未捕获异常都必须留下痕迹 + 弹出可见错误框。"""
    _bootstrap()
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        summary = _report_fatal(exc)
        sys.stderr.write(summary + "\n")
        _show_error_box(summary)
        sys.exit(1)


if __name__ == "__main__":
    _run_guarded()
