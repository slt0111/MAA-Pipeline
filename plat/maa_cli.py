# -*- coding: utf-8 -*-
"""maa-cli 配置注入：按账号写入 StartUp.account_name，并固定连接 profile。

任务文件：``$MAA_CONFIG_DIR/tasks/pipeline_farm.json``
连接配置：``$MAA_CONFIG_DIR/profiles/pipeline.json``
启动：``maa -p pipeline run pipeline_farm``
"""

from __future__ import annotations

import json
import os
import re

from plat.util import run_cmd

CLI_PROFILE = "pipeline"
CLI_TASK = "pipeline_farm"

_STARTUP_TYPES = ("startup", "start_up", "startuptask")


def is_startup_cli_task(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    typ = str(item.get("type") or item.get("Type") or "")
    return typ.lower() in _STARTUP_TYPES


def apply_account_name_cli(tasks: list, account_name: str) -> int:
    """把 account_name 写入任务列表里的 StartUp；没有则在队首补一条。"""
    account_name = (account_name or "").strip()
    hits = 0
    for item in tasks:
        if not is_startup_cli_task(item):
            continue
        params = item.get("params")
        if not isinstance(params, dict):
            params = {}
            item["params"] = params
        params["account_name"] = account_name
        hits += 1
    if hits == 0:
        tasks.insert(0, {
            "name": "开始唤醒",
            "type": "StartUp",
            "params": {"start_game_enabled": True, "account_name": account_name},
        })
        hits = 1
    return hits


def default_cli_tasks() -> list:
    """没有可克隆的用户任务时，写一套接近日常的默认链（可再改 pipeline_farm.json）。"""
    return [
        {"name": "开始唤醒", "type": "StartUp", "params": {"start_game_enabled": True}},
        {"type": "Fight"},
        {"type": "Infrast"},
        {"type": "Award"},
    ]


def resolve_cli_config_dir(exe: str = "", override: str = "") -> str:
    """优先级：显式覆盖 → 环境变量 → ``maa dir config`` → 常见目录。"""
    if (override or "").strip():
        return os.path.abspath(override.strip())
    env = (os.environ.get("MAA_CONFIG_DIR") or "").strip()
    if env:
        return os.path.abspath(env)
    if exe:
        rc, out, err = run_cmd([exe, "dir", "config"], timeout=15)
        text = (out or err or "").strip()
        if rc == 0 and text:
            line = text.splitlines()[0].strip()
            if line and not line.lower().startswith("error"):
                return line
    home = os.path.expanduser("~")
    cands = [
        os.path.join(home, "Library", "Application Support", "com.loong.maa", "config"),
        os.path.join(home, ".config", "maa"),
    ]
    for path in cands:
        if os.path.isdir(path):
            return path
    return cands[0]


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _tasks_from_doc(doc) -> list | None:
    if isinstance(doc, list):
        return [item for item in doc if isinstance(item, dict)]
    if isinstance(doc, dict):
        raw = doc.get("tasks")
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
    return None


def load_user_cli_tasks(config_dir: str) -> list | None:
    """尽量克隆用户已有的日常任务，避免只跑开始唤醒。"""
    tasks_dir = os.path.join(config_dir, "tasks")
    if not os.path.isdir(tasks_dir):
        return None
    names = []
    try:
        names = os.listdir(tasks_dir)
    except OSError:
        return None
    prefer = []
    rest = []
    for name in names:
        low = name.lower()
        if low.startswith("pipeline_farm"):
            continue
        path = os.path.join(tasks_dir, name)
        if not os.path.isfile(path):
            continue
        if low.endswith((".json", ".toml", ".yaml", ".yml")):
            bucket = prefer if any(k in low for k in ("daily", "default", "farm")) else rest
            bucket.append(path)
    for path in prefer + rest:
        if path.endswith(".json"):
            try:
                found = _tasks_from_doc(_read_json(path))
            except Exception:
                continue
            if found:
                return json.loads(json.dumps(found, ensure_ascii=False))
        else:
            # 极简 TOML/YAML：只抠 [[tasks]] + type / account_name，完整文件仍优先 JSON
            try:
                text = open(path, encoding="utf-8").read()
            except Exception:
                continue
            parsed = _tasks_from_tomlish(text)
            if parsed:
                return parsed
    return None


_TOML_TASK = re.compile(
    r"\[\[tasks\]\](.*?)(?=\[\[tasks\]\]|\Z)", re.S | re.I
)
_TOML_TYPE = re.compile(r'^\s*type\s*=\s*"([^"]+)"', re.M)
_TOML_NAME = re.compile(r'^\s*name\s*=\s*"([^"]+)"', re.M)
_TOML_ACCOUNT = re.compile(r'account_name\s*=\s*"([^"]+)"')


def _tasks_from_tomlish(text: str) -> list:
    out = []
    for block in _TOML_TASK.findall(text or ""):
        typ = _TOML_TYPE.search(block)
        if not typ:
            continue
        item = {"type": typ.group(1)}
        name = _TOML_NAME.search(block)
        if name:
            item["name"] = name.group(1)
        acc = _TOML_ACCOUNT.search(block)
        params = {}
        if acc:
            params["account_name"] = acc.group(1)
        if "start_game_enabled" in block:
            params.setdefault("start_game_enabled", True)
        if params:
            item["params"] = params
        out.append(item)
    return out


def write_cli_connection_profile(config_dir: str, adb_path: str, address: str, connect_config: str) -> str:
    os.makedirs(os.path.join(config_dir, "profiles"), exist_ok=True)
    path = os.path.join(config_dir, "profiles", CLI_PROFILE + ".json")
    data = {
        "connection": {
            "adb_path": adb_path or "adb",
            "address": address or "",
            "config": connect_config or "CompatMac",
        }
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return path


def write_cli_farm_task(config_dir: str, tasks: list) -> str:
    os.makedirs(os.path.join(config_dir, "tasks"), exist_ok=True)
    path = os.path.join(config_dir, "tasks", CLI_TASK + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"tasks": tasks}, fh, ensure_ascii=False, indent=2)
    return path


def cli_argv(exe: str, profile: str = CLI_PROFILE, task: str = CLI_TASK) -> list:
    return [exe, "-p", profile, "run", task]


def inject_cli(cfg, log, account_name="", *, connect_config="CompatMac", adb_address="") -> None:
    """写入本轮 maa-cli 任务与连接配置。返回 None（没有 GUI Current 要还原）。"""
    exe = cfg.maa_exe if hasattr(cfg, "maa_exe") else cfg.get("maa", "exe", default="")
    override = ""
    if hasattr(cfg, "get"):
        override = cfg.get("maa", "cli_config_dir", default="") or ""
    config_dir = resolve_cli_config_dir(exe, override)
    adb = ""
    if hasattr(cfg, "get"):
        adb = cfg.get("mumu", "adb", default="") or ""
    write_cli_connection_profile(config_dir, adb, adb_address, connect_config)

    tasks = load_user_cli_tasks(config_dir)
    cloned = bool(tasks)
    if not tasks:
        tasks = default_cli_tasks()
        if log:
            log("info", "maa-cli 未找到可克隆的日常任务，已写入默认链（可改 %s/tasks/）" % config_dir)
    else:
        if log:
            log("info", "已克隆用户 maa-cli 任务（%d 项）再写入切号" % len(tasks))

    account_name = (account_name or "").strip()
    hits = apply_account_name_cli(tasks, account_name)
    path = write_cli_farm_task(config_dir, tasks)
    extra = "，切号「%s」" % account_name if account_name else "（不切号）"
    if log:
        log("info", "已注入 maa-cli 任务 %s（StartUp %d 处%s）" % (os.path.basename(path), hits, extra))
        if not cloned and not account_name:
            log("info", "未配置账号片段时，maa-cli 按当前登录号跑一轮")
    return None
