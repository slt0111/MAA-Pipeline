
import os
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
"""端到端联调：通过 HTTP 接口验证多时间点保存/回读、通知测试接口。"""
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

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


print("=== 1. 当前状态里的定时与通知结构 ===")
state = get("/api/state")
cs = state["config_summary"]
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
print("=== 5. 恢复为单个 08:00 ===")
print(" ", post("/api/config", {"config": {"schedule": {
    "enabled": True, "times": ["08:00"], "time": "08:00",
    "days": days, "only_if_idle": True}}})["msg"])
state = get("/api/state")
print("  当前:", json.dumps(state["config_summary"]["schedule"], ensure_ascii=False))
print("  下次触发:", state["next_schedule"])
srv.shutdown()
