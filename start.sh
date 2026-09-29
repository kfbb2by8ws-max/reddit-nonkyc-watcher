#!/bin/bash
cd "$(dirname "$0")"
if [ -f watcher.pid ] && kill -0 "$(cat watcher.pid)" 2>/dev/null; then
  echo "이미 실행 중 (PID $(cat watcher.pid))"; exit 1
fi
nohup python3 watcher.py --loop >> watcher.out 2>&1 &
echo $! > watcher.pid
echo "시작됨 (PID $!)"
