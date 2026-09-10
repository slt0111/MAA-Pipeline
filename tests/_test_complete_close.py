# -*- coding: utf-8 -*-
"""回归测试：MAA 报「任务已全部完成」后，监控循环必须主动收尾而不是无限等待。

背景 bug：_monitor_maa 只等 MAA 进程退出或用户点中止，从不检查 _completed。
而 MAA 跑完任务后 GUI 进程并不会自己退出 → 流水线卡死，MAA 与模拟器都不关。

跑法：
    python tests/_test_complete_close.py
"""
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline  # noqa: E402

CHILD = [sys.executable, "-c", "import time; time.sleep(600)"]
PASS, FAIL = [], []


def ok(cond, title, detail=""):
    (PASS if cond else FAIL).append(title)
    print("  [%s] %s%s" % ("OK" if cond else "!!", title, ("  " + str(detail)) if detail and not cond else ""))


def make_engine(close_after_complete=True, close_delay=1):
    cfg = pipeline.Config.from_data({
        "maa": {"close_after_complete": close_after_complete, "close_delay": close_delay},
    })
    engine = pipeline.Engine(cfg, pipeline.Bus())
    engine.stop_evt.clear()
    return engine


def spawn_child():
    return subprocess.Popen(CHILD, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def reap(proc):
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=5)


print("=== 1. 任务完成后自动关闭 MAA ===")
engine = make_engine(close_after_complete=True, close_delay=1)
engine.maa_proc = spawn_child()
# 模拟日志线程在 0.5 秒后识别到「任务已全部完成」
threading.Timer(0.5, lambda: setattr(engine, "_completed", True)).start()
t0 = time.time()
# 用线程跑，加超时：旧代码会在这里永久等待，测试应当失败而不是挂死
th = threading.Thread(target=engine._monitor_maa, daemon=True)
th.start()
th.join(timeout=20)
cost = time.time() - t0
ok(not th.is_alive(), "监控循环已退出（未卡死）", "旧代码在此会永久等待")
ok(engine.maa_proc.poll() is not None, "MAA 进程已被关闭")
ok(cost < 15, "监控循环及时返回", "耗时 %.1fs" % cost)
ok(engine.state.get("maa") == "已退出", "状态已更新为「已退出」", engine.state.get("maa"))
reap(engine.maa_proc)

print("=== 2. 未完成时不会误关（只有用户中止才关闭）===")
engine = make_engine(close_after_complete=True, close_delay=1)
engine.maa_proc = spawn_child()
th = threading.Thread(target=engine._monitor_maa, daemon=True)
th.start()
time.sleep(3)
ok(engine.maa_proc.poll() is None, "任务未完成时 MAA 仍在运行（不误关）")
ok(th.is_alive(), "监控循环仍在等待")
engine.stop_evt.set()
th.join(timeout=15)
ok(engine.maa_proc.poll() is not None, "点中止后 MAA 被关闭")
ok(not th.is_alive(), "中止后监控循环已退出")
reap(engine.maa_proc)

print("=== 3. 关掉「完成后自动关闭」时保持旧行为 ===")
engine = make_engine(close_after_complete=False, close_delay=1)
engine.maa_proc = spawn_child()
engine._completed = True
th = threading.Thread(target=engine._monitor_maa, daemon=True)
th.start()
time.sleep(3)
ok(engine.maa_proc.poll() is None, "按配置保留 MAA 运行")
ok(th.is_alive(), "监控循环继续等待")
engine.stop_evt.set()
th.join(timeout=15)
ok(engine.maa_proc.poll() is not None, "中止后仍能关闭 MAA")
reap(engine.maa_proc)

print("=== 4. MAA 自己退出时正常放行 ===")
engine = make_engine(close_after_complete=True, close_delay=1)
engine.maa_proc = subprocess.Popen([sys.executable, "-c", "pass"])
threading.Timer(0.5, lambda: setattr(engine, "_completed", True)).start()
t0 = time.time()
engine._monitor_maa()
ok(time.time() - t0 < 10, "MAA 自行退出时不额外等待", "耗时 %.1fs" % (time.time() - t0))

print("=== 5. 关闭动作是先礼后兵（WM_CLOSE → terminate → kill）===")
engine = make_engine()
engine.maa_proc = spawn_child()
t0 = time.time()
engine._close_maa("测试")
ok(engine.maa_proc.poll() is not None, "进程已被关闭")
ok(time.time() - t0 < 25, "关闭流程在合理时间内完成")
reap(engine.maa_proc)
ok(pipeline.post_close_to_pid(os.getpid()) >= 0, "窗口消息投递函数可安全调用")

print()
print("=" * 62)
if FAIL:
    print("失败 %d 项：%s" % (len(FAIL), " / ".join(FAIL)))
    print("通过 %d 项" % len(PASS))
    sys.exit(1)
print("全部通过（%d 项）" % len(PASS))
