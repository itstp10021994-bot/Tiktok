#!/usr/bin/env bash
# Chạy lịch đăng TikTok (macOS / Linux)
cd "$(dirname "$0")"
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
exec "$PY" -m tiktok_scheduler run "$@"
