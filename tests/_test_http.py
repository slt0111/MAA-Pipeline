"""端到端联调：通过 HTTP 接口验证多时间点保存/回读、通知测试接口。

前置：程序已经在运行（本脚本直接连 127.0.0.1:17800，自己不起服务）。
注意：会临时改写真实的 schedule 配置，脚本结束时会还原成测试前的样子，
      所以不要拿它去测一个你正在用的实例的同时又期待配置不变。
"""
import json
import os
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "http://127.0.0.1:17800"
RECEIVED = []


class Hook(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        RECEIVED.append(self.rfile.read(n).decode("utf-8", "replace"))
        data = b'{"errcode":0,"errmsg":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 17999), Hook)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode("utf-8"),
                                headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


print("=== 0. 连通性 ===")
try:
    get("/api/state")
    print("  已连上运行中的实例 %s" % BASE)
except Exception as exc:
    print("  [跳过] 无法连接 %s：%s" % (BASE, exc))
    print("  请先启动「MAA 挂机助手」再跑本测试。")
    srv.shutdown()
    sys.exit(0)

print()
print("=== 1. 当前状态里的定时与通知结构 ===")
state = get("/api/state")
cs = state["config_summary"]
ORIGINAL = dict(cs["schedule"])          # 结束时还原，避免污染使用者的真实设置
print("  schedule:", json.dumps(cs["schedule"], ensure_ascii=False))
print("  notify 通道:", sorted(cs["notify"].keys()))
print("  next_schedule:", state["next_schedule"])

print()
print("=== 2. 保存两个时间点并回读 ===")
days = [0, 1, 2, 3, 4, 5, 6]
print(" ", post("/api/config", {"config": {"schedule": {
    "enabled": True, "times": ["08:00", "20:00"], "time": "08:00",
    "days": days, "only_if_idle": True}}})["msg"])
stored = json.load(open(os.path.join(APP_DIR, "pipeline_config.json"), encoding="utf-8"))["schedule"]
print("  落盘结果:", json.dumps(stored, ensure_ascii=False))
state = get("/api/state")
print("  回读 times:", state["config_summary"]["schedule"]["times"])
print("  下次触发文案:", state["next_schedule"])

print()
print("=== 3. 通知测试接口（用界面当前填写的内容测，不写盘）===")
RECEIVED.clear()
result = post("/api/notify-test", {"channel": "webhook", "config": {"notify": {"webhook": {
    "enabled": True, "url": "http://127.0.0.1:17999/hook", "format": "企业微信机器人"}}}})
print("  ok =", result["ok"], "|", result["msg"])
print("  假服务器收到:", RECEIVED[0] if RECEIVED else "(没收到)")
after = json.load(open(os.path.join(APP_DIR, "pipeline_config.json"), encoding="utf-8"))["notify"]["webhook"]
print("  测试后配置未被改动（webhook.enabled 应为 False）:", after.get("enabled"))

print()
print("=== 4. 末尾清空时间点的兼容处理 ===")
print(" ", post("/api/config", {"config": {"schedule": {
    "enabled": True, "times": [], "time": "", "days": days, "only_if_idle": True}}})["msg"])
stored = json.load(open(os.path.join(APP_DIR, "pipeline_config.json"), encoding="utf-8"))["schedule"]
print("  times=%s time=%r（老字段应同步清空）" % (stored.get("times"), stored.get("time")))
print("  next_schedule:", repr(get("/api/state")["next_schedule"]))

print()
print("=== 5. 还原为测试前的定时设置 ===")
restore_times = list(ORIGINAL.get("times") or [])
post("/api/config", {"config": {"schedule": {
    "enabled": bool(ORIGINAL.get("enabled", True)),
    "times": restore_times,
    "time": restore_times[0] if restore_times else "",
    "days": list(ORIGINAL.get("days") or days),
    "only_if_idle": bool(ORIGINAL.get("only_if_idle", True))}}})
state = get("/api/state")
now = state["config_summary"]["schedule"]
print("  当前:", json.dumps(now, ensure_ascii=False))
print("  与测试前一致:", json.dumps(now, sort_keys=True) == json.dumps(ORIGINAL, sort_keys=True))
print("  下次触发:", state["next_schedule"])
srv.shutdown()
