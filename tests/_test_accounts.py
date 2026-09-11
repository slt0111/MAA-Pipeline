# -*- coding: utf-8 -*-
"""多账号顺序挂机：配置规范化、切号写入、失败跳过并继续、单账号兼容。

跑法：
    python tests/_test_accounts.py
"""
import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline  # noqa: E402

PASS, FAIL = [], []


def ok(cond, title, detail=""):
    (PASS if cond else FAIL).append(title)
    extra = ""
    if detail and not cond:
        extra = "  " + str(detail)
    print("  [%s] %s%s" % ("OK" if cond else "!!", title, extra))


print("=== 1. 账号列表规范化（老配置 / 空列表兼容）===")
ok(pipeline.normalized_accounts({}) == [], "空 dict → 空列表")
ok(pipeline.normalized_accounts(pipeline.Config.from_data({})) == [], "默认配置 → 空列表")
ok(pipeline.enabled_accounts({"maa": {"accounts": []}}) == [], "显式空列表 → 不启用任何账号")

raw = pipeline.normalized_accounts({
    "maa": {
        "accounts": [
            {"name": " 主号 ", "account_name": " 4567 ", "enabled": True},
            {"name": "", "account": "张三"},
            {"name": "停用", "account_name": "0000", "enabled": False},
            {"name": "", "account_name": ""},
            "skip-me",
        ]
    }
})
ok(len(raw) == 3, "丢掉空项与非 dict", raw)
ok(raw[0] == {"name": "主号", "account_name": "4567", "enabled": True}, "修剪空白", raw[0])
ok(raw[1]["name"] == "张三" and raw[1]["account_name"] == "张三", "account 别名且缺显示名时回退", raw[1])
ok(raw[2]["enabled"] is False, "enabled=false 保留")
ok([a["name"] for a in pipeline.enabled_accounts({"maa": {"accounts": raw}})] == ["主号", "张三"],
   "enabled_accounts 只返回启用项")
ok(pipeline.account_label(None) == "当前登录", "隐式单账号标签")
ok(pipeline.account_label({"name": "主号"}, 1, 2) == "1/2 主号", "多账号带序号")


print("=== 2. 切号写入 TaskQueue / 兼容字段 ===")
profile = {
    "Gui": {"StartUpSettings": {}, "ConnectSettings": {}},
    "TaskQueue": [
        {"$type": "StartUpTask", "Name": "开始唤醒", "IsEnable": True, "AccountName": ""},
        {"$type": "FightTask", "Name": "刷理智", "AccountName": "不该动"},
        {"TaskType": "StartUp", "AccountName": "旧值"},
    ],
}
hits = pipeline.apply_account_name(profile, "4567")
ok(hits == 2, "命中两个开始唤醒任务", hits)
ok(profile["TaskQueue"][0]["AccountName"] == "4567", "新版 $type=StartUpTask")
ok(profile["TaskQueue"][0]["AccountSwitchEnabled"] is True, "同时打开 AccountSwitchEnabled")
ok(profile["TaskQueue"][1]["AccountName"] == "不该动", "不改其它任务")
ok(profile["TaskQueue"][2]["AccountName"] == "4567", "TaskType=StartUp 也能写")
ok(profile["Gui"]["StartUpSettings"]["AccountName"] == "4567", "兼容 StartUpSettings.AccountName")
ok(profile["Start"]["AccountName"] == "4567", "兼容 Start.AccountName")

empty = {"Gui": {}, "TaskQueue": [{"$type": "FightTask"}]}
ok(pipeline.apply_account_name(empty, "abc") == 0, "没有开始唤醒时返回 0")
ok(empty["Gui"]["StartUpSettings"]["AccountName"] == "abc", "即使没命中任务也写入兼容字段")


print("=== 3. inject_maa_profile 按账号写入并保留 Current ===")
logs = []


def _log(level, msg):
    logs.append("%s|%s" % (level, msg))


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
                    "TaskQueue": [
                        {"$type": "StartUpTask", "Name": "开始唤醒", "AccountName": ""},
                    ],
                }
            },
        }, fh, ensure_ascii=False)

    cfg = pipeline.Config.from_data({"maa": {"exe": exe, "profile": "挂机流水线"}}, path=os.path.join(tmp, "x.json"))
    prev = pipeline.inject_maa_profile(cfg, _log, account_name="8901")
    ok(prev == "Default", "返回注入前的 Current", prev)
    data = json.load(open(gui_path, encoding="utf-8"))
    ok(data["Current"] == "挂机流水线", "Current 切到流水线配置")
    injected = data["Configurations"]["挂机流水线"]
    ok(injected["TaskQueue"][0]["AccountName"] == "8901", "注入后的开始唤醒带切号")
    ok(injected["Gui"]["StartUpSettings"]["RunDirectly"] is True, "仍然 RunDirectly")
    ok(os.path.exists(gui_path + ".pipeline.bak"), "首次注入会备份")
    ok(data["Configurations"]["Default"]["TaskQueue"][0]["AccountName"] == "", "不改 Default 里的账号")

    pipeline.restore_maa_current(cfg, prev, _log)
    restored = json.load(open(gui_path, encoding="utf-8"))
    ok(restored["Current"] == "Default", "还原 Current")


print("=== 4. 多账号顺序跑 + 失败跳过并继续 ===")
calls = []


def fake_launch(self, account_name="", force_close=False):
    calls.append((account_name, force_close, self.state.get("account")))
    if account_name == "bad":
        self._completed = False
        return
    if account_name == "boom":
        raise pipeline.PipelineError("账号启动失败：boom")
    if account_name == "abort-after":
        self._completed = True
        self.stop_evt.set()
        return
    self._completed = True


def make_engine(accounts):
    cfg = pipeline.Config.from_data({"maa": {"accounts": accounts, "exe": "/no/maa"}})
    engine = pipeline.Engine(cfg, pipeline.Bus())
    engine.stop_evt.clear()
    engine._launch_and_monitor_maa = fake_launch.__get__(engine)  # noqa: B009
    return engine


orig_running = pipeline.process_running
orig_info = pipeline.mumu_info
pipeline.process_running = lambda _name: False
pipeline.mumu_info = lambda _cfg: {"is_android_started": True}

try:
    calls.clear()
    engine = make_engine([
        {"name": "A", "account_name": "111", "enabled": True},
        {"name": "B", "account_name": "222", "enabled": True},
        {"name": "C", "account_name": "333", "enabled": False},
    ])
    engine._phase_maa()
    ok([c[0] for c in calls] == ["111", "222"], "只跑启用账号且按顺序", calls)
    ok(calls[0][1] is True and calls[1][1] is False, "非末号 force_close，末号尊重原关闭策略", calls)
    ok(engine._completed is True, "全部成功后 _completed 为真")
    ok(engine._account_failure_message() == "", "全部成功没有失败摘要")

    calls.clear()
    engine = make_engine([])
    engine._phase_maa()
    ok(calls == [("", False, "当前登录")], "空列表走单账号隐式一轮（不切号）", calls)
    ok(engine._account_failure_message() == "", "空列表不把没跑完算成整轮失败")

    calls.clear()
    engine = make_engine([{"name": "仅一个", "account_name": "only", "enabled": True}])
    engine._phase_maa()
    ok(len(calls) == 1 and calls[0][0] == "only" and calls[0][1] is False,
       "单个启用账号不强制关窗", calls)

    calls.clear()
    engine = make_engine([
        {"name": "先成", "account_name": "ok1", "enabled": True},
        {"name": "失败号", "account_name": "bad", "enabled": True},
        {"name": "还要跑", "account_name": "ok2", "enabled": True},
    ])
    raised = None
    try:
        engine._phase_maa()
    except pipeline.PipelineError as exc:
        raised = str(exc)
    ok(raised is None, "某一号没跑完不中断整轮", raised)
    ok([c[0] for c in calls] == ["ok1", "bad", "ok2"], "失败后继续跑后续账号", calls)
    ok(engine._completed is False, "有失败时 _completed 为假（不关模拟器）")
    ok(engine._account_failure_message() == "完成 2/3 个账号，失败：失败号",
       "失败摘要列出失败号", engine._account_failure_message())
    ok(engine._result_label(False) == "部分失败", "有成功也有失败 → 部分失败")
    title, body = engine._notify_copy(False, 90, engine._account_failure_message())
    ok(title == "MAA 挂机部分失败" and "失败号" in body, "通知区分部分失败", (title, body))

    calls.clear()
    engine = make_engine([
        {"name": "炸", "account_name": "boom", "enabled": True},
        {"name": "还能跑", "account_name": "ok1", "enabled": True},
    ])
    raised = None
    try:
        engine._phase_maa()
    except pipeline.PipelineError as exc:
        raised = str(exc)
    ok(raised is None, "单号启动失败在多账号下跳过", raised)
    ok([c[0] for c in calls] == ["boom", "ok1"], "启动失败后仍跑下一号", calls)
    ok(any(not r["ok"] and r["name"] == "炸" for r in engine._account_results), "炸号记入失败列表")

    calls.clear()
    engine = make_engine([{"name": "炸", "account_name": "boom", "enabled": True}])
    raised = None
    try:
        engine._phase_maa()
    except pipeline.PipelineError as exc:
        raised = str(exc)
    ok(raised == "账号启动失败：boom", "单账号启动失败仍原样抛出", raised)

    calls.clear()
    engine = make_engine([{"name": "仅一个", "account_name": "bad", "enabled": True}])
    raised = None
    try:
        engine._phase_maa()
    except pipeline.PipelineError as exc:
        raised = str(exc)
    ok(raised is None, "单账号没跑完不抛错（历史行为）", raised)
    ok(engine._account_failure_message() == "", "单账号没跑完不算整轮失败摘要")

    calls.clear()
    engine = make_engine([
        {"name": "先成再中止", "account_name": "abort-after", "enabled": True},
        {"name": "不该跑", "account_name": "ok2", "enabled": True},
    ])
    raised = None
    try:
        engine._phase_maa()
    except pipeline.PipelineError as exc:
        raised = str(exc)
    ok(raised == "已被手动中止", "用户中止仍停整轮", raised)
    ok([c[0] for c in calls] == ["abort-after"], "中止后不再跑下一号", calls)
finally:
    pipeline.process_running = orig_running
    pipeline.mumu_info = orig_info


print("=== 4b. 切号前 MAA 残留：短重试后整轮失败 ===")
engine = pipeline.Engine(pipeline.Config.from_data({}), pipeline.Bus())
engine.stop_evt.clear()
engine.maa_proc = None
hits = {"n": 0}


def flaky(_name):
    hits["n"] += 1
    return hits["n"] < 3


pipeline.process_running = flaky
try:
    engine._ensure_maa_stopped(timeout=2, interval=0.01)
    ok(hits["n"] >= 3, "残留进程会短重试直到退出", hits)
    pipeline.process_running = lambda _n: True
    raised = None
    try:
        engine._ensure_maa_stopped(timeout=0.05, interval=0.01)
    except pipeline.PipelineError as exc:
        raised = str(exc)
    ok(raised and "仍在运行" in raised, "重试后仍在则整轮失败", raised)

    sticky = {"on": False}
    leftover_calls = []

    def leftover_launch(self, account_name="", force_close=False):
        leftover_calls.append(account_name)
        self._completed = True
        sticky["on"] = True

    pipeline.process_running = lambda _n: sticky["on"]
    engine = make_engine([
        {"name": "A", "account_name": "111", "enabled": True},
        {"name": "B", "account_name": "222", "enabled": True},
    ])
    engine._launch_and_monitor_maa = leftover_launch.__get__(engine)  # noqa: B009
    engine._maa_stop_timeout = 0.05
    engine._maa_stop_interval = 0.01
    raised = None
    try:
        engine._phase_maa()
    except pipeline.PipelineError as exc:
        raised = str(exc)
    ok(raised and "仍在运行" in raised, "切下一号时关不掉 MAA 则整轮失败", raised)
    ok(leftover_calls == ["111"], "关不掉时不会拉起下一号", leftover_calls)
finally:
    pipeline.process_running = orig_running


print("=== 5. 快照带上 accounts，监控 force_close 仍兼容旧测试调用 ===")
cfg = pipeline.Config.from_data({
    "maa": {"accounts": [{"name": "主号", "account_name": "12", "enabled": True}]}
})
engine = pipeline.Engine(cfg, pipeline.Bus())
snap = engine.snapshot()["config_summary"]
ok(snap["accounts"] == [{"name": "主号", "account_name": "12", "enabled": True}],
   "snapshot.config_summary.accounts", snap.get("accounts"))

# _monitor_maa() 无参仍可调用（旧回归测试依赖）
engine.stop_evt.set()
th = threading.Thread(target=engine._monitor_maa, daemon=True)
th.start()
th.join(timeout=5)
ok(not th.is_alive(), "_monitor_maa() 无参可调用且能退出")


print()
print("=" * 62)
if FAIL:
    print("失败 %d 项：%s" % (len(FAIL), " / ".join(FAIL)))
    print("通过 %d 项" % len(PASS))
    sys.exit(1)
print("全部通过（%d 项）" % len(PASS))
