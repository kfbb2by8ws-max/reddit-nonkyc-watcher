#!/bin/bash
cd "$(dirname "$0")"
if [ ! -f watcher.pid ]; then echo "PID 파일 없음"; exit 1; fi
PID=$(cat watcher.pid)
kill "$PID" 2>/dev/null && echo "중지됨 (PID $PID)" || echo "이미 죽어있음 (PID $PID)"
rm -f watcher.pid
