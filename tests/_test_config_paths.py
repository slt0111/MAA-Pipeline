# -*- coding: utf-8 -*-
"""MAA 主程序路径容错：误填成目录时自动补 MAA.exe，不再误导性地报「找不到配置文件」。

跑法：
    python tests/_test_config_paths.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline  # noqa: E402

PASS, FAIL = [], []


def ok(cond, title, detail=""):
    (PASS if cond else FAIL).append(title)
    extra = "  " + str(detail) if (detail and not cond) else ""
    print("  [%s] %s%s" % ("OK" if cond else "!!", title, extra))


tmp = tempfile.mkdtemp(prefix="maapipeline_paths_")
maa_dir = os.path.join(tmp, "MAA")
os.makedirs(os.path.join(maa_dir, "config"))
exe_path = os.path.join(maa_dir, "MAA.exe")
open(exe_path, "wb").close()
cfg_path = os.path.join(maa_dir, "config", "gui.new.json")
with open(cfg_path, "w", encoding="utf-8") as fh:
    json.dump(
        {
            "Current": "Default",
            "Configurations": {
                "Default": {"Gui": {"StartUpSettings": {"RunDirectly": False}}}
            },
        },
        fh,
        ensure_ascii=False,
    )


def cfg_with(maa_exe_value):
    return pipeline.Config.from_data({"maa": {"exe": maa_exe_value}})


print("=== 1. 误填目录 → 自动补 MAA.exe ===")
cfg = cfg_with(maa_dir)
ok(cfg.maa_exe == exe_path, "目录自动补成 MAA.exe", cfg.maa_exe)
ok(cfg.maa_dir == maa_dir, "推导出的 MAA 目录正确（不再上移一级）", cfg.maa_dir)
ok(
    os.path.isfile(os.path.join(cfg.maa_dir, "config", "gui.new.json")),
    "按 maa_dir 能找到 gui.new.json（原 bug 就死在这一步）",
)

print("=== 2. 正常路径 / 非法输入不受影响 ===")
ok(cfg_with(exe_path).maa_exe == exe_path, "完整 exe 路径保持不变")
ok(cfg_with("  " + exe_path + "  ").maa_exe == exe_path, "首尾空格自动清理")
ok(cfg_with('"' + exe_path + '"').maa_exe == exe_path, "带引号的路径自动清理")
empty_dir = os.path.join(tmp, "NoMAA")
os.makedirs(empty_dir)
ok(cfg_with(empty_dir).maa_exe == empty_dir, "目录里没有 MAA.exe → 原样返回，不臆造路径")
ok(cfg_with("").maa_exe == "", "空路径保持为空")

print("=== 3. 整条链路：误填目录也能跑注入（不再报找不到配置文件）===")
cfg = cfg_with(maa_dir)
try:
    prev = pipeline.inject_maa_profile(cfg, lambda *a, **k: None)
    ok(True, "inject_maa_profile 未抛异常")
    data = json.load(open(cfg_path, encoding="utf-8"))
    profile = cfg.get("maa", "profile", default="挂机流水线")
    ok(profile in data.get("Configurations", {}), "已写入「%s」配置" % profile)
    ok(data.get("Current") == profile, "Current 已切到该配置", data.get("Current"))
    ok(prev == "Default", "返回注入前的 Current 供还原", prev)
except Exception as exc:  # noqa: BLE001
    ok(False, "inject_maa_profile 未抛异常", exc)

print("=== 4. 自检：目录不再被误判为有效 ===")
ok(pipeline._path_ready(exe_path) is True, "文件路径 → 自检通过")
ok(pipeline._path_ready(empty_dir) is False, "目录路径 → 自检不通过（原逻辑会误判通过）")

print("\n结果：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
if FAIL:
    for f in FAIL:
        print("  FAILED:", f)
    sys.exit(1)
print("全部通过")
