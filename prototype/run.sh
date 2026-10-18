#!/usr/bin/env bash
# 一键启动脚本（macOS / Linux）
# Windows 用户请直接执行: cd backend && python app.py
set -e
cd "$(dirname "$0")/backend"
exec python3 app.py
