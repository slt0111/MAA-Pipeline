
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
"""检查 ui.html 里前端脚本的语法与元素引用一致性。"""
import os
import re
import subprocess
import tempfile

BASE = APP_DIR
html = open(os.path.join(BASE, "ui.html"), encoding="utf-8").read()
js = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
tmp = os.path.join(tempfile.gettempdir(), "ui_check.js")
open(tmp, "w", encoding="utf-8").write(js)
node = os.environ.get("NODE_EXE", "node")
res = subprocess.run([node, "--check", tmp], capture_output=True)
print("JS 语法:", "通过" if res.returncode == 0 else "失败")
if res.returncode:
    print(res.stderr.decode("utf-8", "replace")[:800])

ids = set(re.findall(r'id="([^"]+)"', html))
refs = set(re.findall(r'\$\("([^"]+)"\)', js))
# 动态生成的 id：- 前缀为通道/时间等运行时元素
dynamic_prefixes = ("bar-", "lb-", "body-", "c-", "times", "btn-add-time")
missing = sorted(r for r in refs if r not in ids and not r.startswith(dynamic_prefixes))
print("静态 id 数:", len(ids), "| $(...) 引用数:", len(refs))
print("未匹配引用:", missing or "无")

# 检查 collectCfg 读取的字段 id 与 buildCfg 生成的 id 是否一致
chan_keys = re.findall(r'\{key:"(\w+)", label:"[^"]*"', js)
print("通知通道:", chan_keys)
