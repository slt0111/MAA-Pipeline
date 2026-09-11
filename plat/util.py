# -*- coding: utf-8 -*-
"""平台层共用的命令执行与 JSON 解析（不依赖 pipeline）。"""

from __future__ import annotations

import json
import os
import subprocess

CREATE_NO_WINDOW = 0x08000000


def decode(raw: bytes) -> str:
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
    return proc.returncode, decode(proc.stdout), decode(proc.stderr)


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


def first_json_object(text: str):
    """从混有日志的输出里抠出第一段 JSON 对象或数组。"""
    text = text or ""
    start_obj = text.find("{")
    start_arr = text.find("[")
    starts = [i for i in (start_obj, start_arr) if i >= 0]
    if not starts:
        return None
    start = min(starts)
    try:
        return json.loads(text[start:])
    except Exception:
        decoder = json.JSONDecoder()
        try:
            data, _ = decoder.raw_decode(text[start:])
            return data
        except Exception:
            return None


def which(name: str):
    """PATH 查找，找到返回绝对路径。"""
    if not name:
        return None
    from shutil import which as _which

    found = _which(name)
    return os.path.abspath(found) if found else None


def iter_files(candidates):
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None
