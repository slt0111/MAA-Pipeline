#!/bin/sh
# 在 macOS 上生成 MAA挂机助手.app + .dmg（不附带 MuMu / MAA）。
# 用法：./scripts/build_dmg.sh [--skip-test|--dry-run|--check]
set -e
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
exec python3 "$ROOT/build_dmg.py" "$@"
