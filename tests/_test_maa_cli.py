# -*- coding: utf-8 -*-
"""maa-cli 切号：不依赖真实 MuMu / maa，只测任务写入与 inject 分支。

跑法：
    python tests/_test_maa_cli.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline  # noqa: E402
import plat  # noqa: E402
from plat import maa_cli

PASS, FAIL = [], []


def ok(cond, title, detail=""):
    (PASS if cond else FAIL).append(title)
    extra = ""
    if detail and not cond:
        extra = "  " + str(detail)
    print("  [%s] %s%s" % ("OK" if cond else "!!", title, extra))


print("=== 1. StartUp.account_name 写入 / 补齐 ===")
tasks = [{"type": "Fight"}, {"type": "StartUp", "params": {}}]
hits = maa_cli.apply_account_name_cli(tasks, "4567")
ok(hits == 1, "命中已有 StartUp")
ok(tasks[1]["params"]["account_name"] == "4567", "写入 account_name")

bare = [{"type": "Fight"}]
maa_cli.apply_account_name_cli(bare, "张三")
ok(bare[0]["type"] == "StartUp", "没有 StartUp 时补在队首")
ok(bare[0]["params"]["account_name"] == "张三", "补齐的 StartUp 带切号")

ok(maa_cli.cli_argv("/opt/homebrew/bin/maa") ==
   ["/opt/homebrew/bin/maa", "-p", "pipeline", "run", "pipeline_farm"],
   "cli_argv 固定 profile + task")


print("=== 2. 克隆用户任务，跳过 pipeline_farm ===")
with tempfile.TemporaryDirectory() as tmp:
    tdir = os.path.join(tmp, "tasks")
    os.makedirs(tdir)
    with open(os.path.join(tdir, "daily.json"), "w", encoding="utf-8") as fh:
        json.dump({"tasks": [
            {"type": "StartUp", "params": {"start_game_enabled": True}},
            {"type": "Award"},
        ]}, fh)
    with open(os.path.join(tdir, "pipeline_farm.json"), "w", encoding="utf-8") as fh:
        json.dump({"tasks": [{"type": "Fight", "name": "不该被克隆"}]}, fh)
    cloned = maa_cli.load_user_cli_tasks(tmp)
    ok(cloned is not None and len(cloned) == 2, "克隆 daily.json")
    ok(cloned[1]["type"] == "Award", "克隆内容来自 daily 不是 pipeline_farm")

with tempfile.TemporaryDirectory() as tmp:
    tdir = os.path.join(tmp, "tasks")
    os.makedirs(tdir)
    with open(os.path.join(tdir, "farm.toml"), "w", encoding="utf-8") as fh:
        fh.write('[[tasks]]\ntype = "StartUp"\nname = "开始唤醒"\naccount_name = "old"\n\n'
                 '[[tasks]]\ntype = "Infrast"\n')
    cloned = maa_cli.load_user_cli_tasks(tmp)
    ok(cloned and cloned[0]["type"] == "StartUp", "TOML 任务可解析")
    ok(cloned[0]["params"]["account_name"] == "old", "TOML 抠出 account_name")


print("=== 3. inject_cli 写入 profile + 切号任务 ===")
with tempfile.TemporaryDirectory() as tmp:
    cfg = pipeline.Config.from_data({
        "maa": {"exe": os.path.join(tmp, "maa"), "cli_config_dir": tmp},
        "mumu": {"adb": "/opt/homebrew/bin/adb", "adb_address": "127.0.0.1:26624"},
    }, path=os.path.join(tmp, "x.json"))
    logs = []
    prev = maa_cli.inject_cli(
        cfg, lambda lv, msg: logs.append("%s|%s" % (lv, msg)),
        "4567", connect_config="CompatMac", adb_address="127.0.0.1:26624",
    )
    ok(prev is None, "cli 注入没有 GUI Current 要还原")
    prof = json.load(open(os.path.join(tmp, "profiles", "pipeline.json"), encoding="utf-8"))
    ok(prof["connection"]["config"] == "CompatMac", "连接配置 CompatMac")
    ok(prof["connection"]["address"] == "127.0.0.1:26624", "写入 ADB 地址")
    farm = json.load(open(os.path.join(tmp, "tasks", "pipeline_farm.json"), encoding="utf-8"))
    startup = [t for t in farm["tasks"] if t.get("type") == "StartUp"]
    ok(startup and startup[0]["params"]["account_name"] == "4567", "farm 任务已切号")
    ok(any("切号" in x for x in logs), "日志提到切号")


print("=== 4. inject_maa_profile 在 maa-cli 路径走 inject_cli ===")
orig = plat.current()
try:
    pipeline.set_platform("macos")
    with tempfile.TemporaryDirectory() as tmp:
        exe = os.path.join(tmp, "maa")
        open(exe, "w").close()
        os.chmod(exe, 0o755)
        cfg_dir = os.path.join(tmp, "cli-cfg")
        os.makedirs(cfg_dir)
        cfg = pipeline.Config.from_data({
            "maa": {"exe": exe, "cli_config_dir": cfg_dir, "accounts": [
                {"name": "官服", "account_name": "8901", "enabled": True},
            ]},
            "mumu": {"adb_address": "127.0.0.1:26624", "adb": "/opt/homebrew/bin/adb"},
        }, path=os.path.join(tmp, "x.json"))
        logs = []
        prev = pipeline.inject_maa_profile(cfg, lambda lv, msg: logs.append(msg), account_name="8901")
        ok(prev is None, "cli 路径返回 None")
        farm = json.load(open(os.path.join(cfg_dir, "tasks", "pipeline_farm.json"), encoding="utf-8"))
        ok(farm["tasks"][0]["params"]["account_name"] == "8901",
           "inject_maa_profile 经 cli 写入切号")
        ok(not os.path.exists(os.path.join(tmp, "config", "gui.new.json")),
           "cli 路径不写 gui.new.json")
        snap = pipeline.Engine(cfg, pipeline.Bus()).snapshot()["config_summary"]
        ok(snap.get("maa_backend") == "cli", "snapshot 标记 maa_backend=cli")
finally:
    plat.set_current(orig)


print("=== 5. 非 GUI 日志行也能标完成 ===")
engine = pipeline.Engine(pipeline.Config.from_data({}), pipeline.Bus())
engine._completed = False
engine._handle_maa_line("All tasks finished 任务已全部完成")
ok(engine._completed is True, "无 GUI 前缀的完成行仍置位 _completed")


print()
print("=" * 62)
if FAIL:
    print("失败 %d 项：%s" % (len(FAIL), " / ".join(FAIL)))
    print("通过 %d 项" % len(PASS))
    sys.exit(1)
print("全部通过（%d 项）" % len(PASS))
