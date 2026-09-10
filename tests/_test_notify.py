
import os
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
"""验证通知通道：本地假服务器校验报文格式，外部通道校验请求是否被正确受理。"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, APP_DIR)
import pipeline  # noqa: E402

RECEIVED = []


class Hook(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace")
        RECEIVED.append({"path": self.path, "ctype": self.headers.get("Content-Type"), "body": raw})
        if self.path == "/fail":
            payload = {"errcode": 40058, "errmsg": "invalid webhook url"}
        else:
            payload = {"errcode": 0, "errmsg": "ok"}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


srv = HTTPServer(("127.0.0.1", 17999), Hook)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def cfg_with(notify):
    return pipeline.Config.from_data({"notify": notify}, path=os.path.join(APP_DIR, "_tmp_cfg.json"))


def run(label, notify, only=None):
    result = pipeline.notify_all("挂机完成", "用时 3 分 12 秒", cfg_with(notify), None, only=only)
    for item in result:
        print("   %-22s %s %s" % (item["label"], "OK  " if item["ok"] else "FAIL", item["detail"]))
    return result


print("=== 1. 本地 Webhook：四种报文格式 ===")
for fmt, expect in (("通用 JSON", "title/content"),
                    ("企业微信机器人", "msgtype/text.content"),
                    ("钉钉机器人", "msgtype/text.content"),
                    ("飞书机器人", "msg_type/content.text")):
    RECEIVED.clear()
    run(fmt, {"desktop": False, "webhook": {"enabled": True, "url": "http://127.0.0.1:17999/hook",
                                            "format": fmt}})
    body = RECEIVED[0]["body"] if RECEIVED else "(没有收到请求)"
    print("      期望含 %s → 实收: %s" % (expect, body[:150]))
    print("      Content-Type:", RECEIVED[0]["ctype"] if RECEIVED else "-")

print()
print("=== 2. Webhook 返回业务错误时的判定 ===")
run("失败路径", {"desktop": False, "webhook": {"enabled": True, "url": "http://127.0.0.1:17999/fail",
                                             "format": "企业微信机器人"}})

print()
print("=== 3. 字段缺失时的本地校验（不发网络请求）===")
run("空配置", {"desktop": False,
              "serverchan": {"enabled": True, "sendkey": ""},
              "pushplus": {"enabled": True, "token": ""},
              "wxpusher": {"enabled": True, "app_token": "", "uids": ""},
              "qmsg": {"enabled": True, "key": ""},
              "webhook": {"enabled": True, "url": ""}})
run("地址格式错误", {"desktop": False, "webhook": {"enabled": True, "url": "ftp://x.com", "format": "通用 JSON"}})

print()
print("=== 4. 外部通道：用无效凭据验证接口地址与报文格式（不会真的发出消息）===")
run("无效凭据", {"desktop": False,
               "serverchan": {"enabled": True, "sendkey": "SCT_invalid_for_test"},
               "pushplus": {"enabled": True, "token": "invalid_for_test"},
               "wxpusher": {"enabled": True, "app_token": "AT_invalid_for_test", "uids": "UID_invalid"},
               "qmsg": {"enabled": True, "key": "invalid_for_test", "qq": "10000"}})

print()
print("=== 5. 通道启用判定 ===")
conf = {"desktop": True, "serverchan": {"enabled": True}, "qmsg": {"enabled": False},
        "webhook": {"enabled": True, "url": "x"}}
print("  启用通道:", pipeline._enabled_channels(conf))
print("  规范化后的通知配置键:", sorted(pipeline.normalized_notify(
    cfg_with(conf)).keys()))
srv.shutdown()
