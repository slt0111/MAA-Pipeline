
import os
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
"""验证多时间点定时逻辑：用可控的假时间来驱动 Scheduler._tick()。"""
import datetime as real_dt
import sys
import types

sys.path.insert(0, APP_DIR)
import pipeline  # noqa: E402

CURRENT = {"now": None}


class FakeDT(real_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return CURRENT["now"]


pipeline.dt = types.SimpleNamespace(
    datetime=FakeDT, timedelta=real_dt.timedelta, time=real_dt.time, date=real_dt.date
)

print("=== 1. 时间解析与兼容 ===")
print("times 列表     :", pipeline.schedule_times({"times": ["20:00", "08:00", "08:00", "8:5"]}))
print("只有老 time 字段:", pipeline.schedule_times({"time": "14:59"}))
print("空 times + time:", pipeline.schedule_times({"times": [], "time": "06:30"}))
print("非法值过滤     :", pipeline.schedule_times({"times": ["25:00", "ab", "12:60", "07:05"]}))
print("days 缺省      :", pipeline.schedule_days({}))
print("days 非法      :", pipeline.schedule_days({"days": [9, 1, "x", 1]}))


class FakeEngine:
    def __init__(self):
        self.state = {"running": False}
        self.snapshot_state = {}
        self.started = []

    def _set(self, **kw):
        self.snapshot_state.update(kw)

    def start(self, mode):
        self.started.append((CURRENT["now"].strftime("%Y-%m-%d %H:%M:%S"), mode))
        return True, "ok"


class FakeBus:
    def __init__(self):
        self.lines = []

    def log(self, level, msg):
        self.lines.append("%s | %s" % (level, msg))


def make_sched(cfg_data):
    cfg = pipeline.Config.from_data(cfg_data, path=os.path.join(APP_DIR, "_tmp_cfg.json"))
    eng, bus = FakeEngine(), FakeBus()
    sched = pipeline.Scheduler(cfg, eng, bus)
    return sched, eng, bus


def tick(sched, when_str):
    CURRENT["now"] = FakeDT.strptime(when_str, "%Y-%m-%d %H:%M:%S")
    sched._tick()


print()
print("=== 2. 多个时间点：08:00 与 20:00 ===")
sched, eng, bus = make_sched(
    {"schedule": {"enabled": True, "times": ["08:00", "20:00"], "days": [0, 1, 2, 3, 4, 5, 6]}}
)
print("2026-09-10 是周四" if real_dt.date(2026, 9, 10).weekday() == 3 else "日期参考错误")
tick(sched, "2026-09-10 07:59:50")
print("07:59:50 → 触发数 %d | %s" % (len(eng.started), eng.snapshot_state.get("next_schedule")))
tick(sched, "2026-09-10 08:00:05")
print("08:00:05 → 触发 %s" % (eng.started[-1] if eng.started else "无",))
tick(sched, "2026-09-10 08:00:25")
print("08:00:25 → 累计触发数 %d（不应重复）" % len(eng.started))
tick(sched, "2026-09-10 19:59:55")
print("19:59:55 → %s" % eng.snapshot_state.get("next_schedule"))
tick(sched, "2026-09-10 20:00:08")
print("20:00:08 → 累计触发数 %d | %s" % (len(eng.started), eng.started[-1]))

print()
print("=== 3. 休眠/卡顿跨过整分钟也能补触发 ===")
sched, eng, bus = make_sched({"schedule": {"enabled": True, "times": ["08:00"], "days": list(range(7))}})
tick(sched, "2026-09-10 07:58:00")
tick(sched, "2026-09-10 08:05:00")
print("07:58 → 08:05 一次巡检，触发数 %d（应为 1）" % len(eng.started))

print()
print("=== 4. 生效日期过滤 ===")
sched, eng, bus = make_sched({"schedule": {"enabled": True, "times": ["08:00"], "days": [0]}})  # 只周一
tick(sched, "2026-09-10 07:59:50")   # 周四
tick(sched, "2026-09-10 08:00:05")
print("周四触发数 %d（应为 0）| %s" % (len(eng.started), eng.snapshot_state.get("next_schedule")))
tick(sched, "2026-09-14 07:59:50")   # 下周一
tick(sched, "2026-09-14 08:00:05")
print("周一触发数 %d（应为 1）" % len(eng.started))

print()
print("=== 5. 忙碌时跳过 ===")
sched, eng, bus = make_sched({"schedule": {"enabled": True, "times": ["08:00"], "days": list(range(7))}})
eng.state["running"] = True
tick(sched, "2026-09-10 07:59:50")
tick(sched, "2026-09-10 08:00:05")
print("触发数 %d（应为 0）| 日志: %s" % (len(eng.started), bus.lines[-1] if bus.lines else "无"))

print()
print("=== 6. 关闭定时 / 清空时间点 ===")
sched, eng, bus = make_sched({"schedule": {"enabled": False, "times": ["08:00"], "days": list(range(7))}})
tick(sched, "2026-09-10 08:00:05")
print("禁用时触发数 %d | next=%r" % (len(eng.started), eng.snapshot_state.get("next_schedule")))
sched, eng, bus = make_sched({"schedule": {"enabled": True, "times": [], "time": "", "days": list(range(7))}})
tick(sched, "2026-09-10 08:00:05")
print("时间点清空时触发数 %d | next=%r" % (len(eng.started), eng.snapshot_state.get("next_schedule")))

print()
print("=== 7. 下次触发文案 ===")
conf = {"enabled": True, "times": ["08:00", "12:30", "20:00"], "days": list(range(7))}
sched, eng, bus = make_sched({"schedule": conf})
for when in ("2026-09-10 07:10:00", "2026-09-10 09:00:00", "2026-09-10 23:30:00"):
    CURRENT["now"] = FakeDT.strptime(when, "%Y-%m-%d %H:%M:%S")
    print("  %s → %s" % (when, pipeline._describe_next(CURRENT["now"],
          pipeline.next_run(CURRENT["now"], pipeline.schedule_times(conf),
                            pipeline.schedule_days(conf)),
          pipeline.schedule_days(conf), pipeline.schedule_times(conf))))
