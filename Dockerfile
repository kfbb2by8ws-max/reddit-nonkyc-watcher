FROM python:3.12-slim

# 의존성 없음 (stdlib 만 사용)
WORKDIR /app
COPY watcher.py config.py notify.py rss_source.py check_ip.py ./

# 상태 파일(seen.json, feed_cache.json, watcher.log)은 볼륨에 둔다
ENV DATA_DIR=/data
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Dubai
VOLUME ["/data"]

CMD ["python", "watcher.py", "--loop"]
