#!/bin/sh
# macOS / Linux 源码启动（Windows 请用 start-pipeline.vbs 或直接 python pipeline.py）
cd "$(dirname "$0")"
exec python3 pipeline.py "$@"
