#!/usr/bin/env python3
"""
non-KYC crypto card 관련 Reddit 글 탐지 → 텔레그램 포워딩.

  python watcher.py --once        한 번만 돌고 종료 (테스트/크론용)
  python watcher.py --loop        데몬 (기본 5분 간격)
  python watcher.py --once --dry  텔레그램 안 보내고 콘솔에만 출력
"""
import argparse
import json
import logging
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import notify
import rss_source

HERE = pathlib.Path(__file__).resolve().parent
# DATA_DIR 로 상태 파일 위치를 옮길 수 있다 (컨테이너 퍼시스턴트 볼륨용)
DATA_DIR = pathlib.Path(os.getenv("DATA_DIR", HERE))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SEEN_PATH = DATA_DIR / "seen.json"
SEEN_TTL_DAYS = 30

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler(DATA_DIR / "watcher.log"),
              logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("watcher")


# ── 중복 제거 ───────────────────────────────────────────────
def load_seen():
    if not SEEN_PATH.exists():
        return {}
    try:
        return json.loads(SEEN_PATH.read_text())
    except Exception:
        log.warning("seen.json 파손 — 초기화")
        return {}


def save_seen(seen):
    cutoff = time.time() - SEEN_TTL_DAYS * 86400
    pruned = {k: v for k, v in seen.items() if v > cutoff}
    tmp = SEEN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(pruned, sort_keys=True) + "\n")
    tmp.replace(SEEN_PATH)


# ── 매칭 ────────────────────────────────────────────────────
def _crypto_pat(t):
    if not t.isascii():
        return re.escape(t)                 # 한글은 조사가 붙으니 부분일치
    tail = r"\b" if len(t) <= 4 else ""     # 짧은 약어는 양쪽 경계 (eth ⊄ ethics)
    return rf"\b{re.escape(t)}{tail}"


_CRYPTO_RE = re.compile("|".join(_crypto_pat(t) for t in config.CRYPTO_TERMS))


def match(post):
    text = f"{post.get('title','')} {post.get('selftext','')}".lower()

    if any(x in text for x in config.EXCLUDE_TERMS):
        return None

    card = [t for t in config.CARD_TERMS if t in text]
    nokyc = [t for t in config.NOKYC_TERMS if t in text]
    if not card or not nokyc:
        return None
    if not _CRYPTO_RE.search(f"{text} {post.get('subreddit','').lower()}"):
        return None

    intent = [t for t in config.INTENT_TERMS if t in text]
    return {"terms": card[:2] + nokyc[:2], "intent": bool(intent)}


# ── 수집 ────────────────────────────────────────────────────
def collect(client):
    posts, seen_ids = [], set()

    for group in config.SUBREDDIT_GROUPS:
        try:
            for p in client.new_posts_group(group):
                if p["id"] not in seen_ids:
                    seen_ids.add(p["id"])
                    posts.append(p)
        except Exception as e:
            log.warning("그룹 수집 실패 [%s]: %s", "+".join(group), e)

    if not getattr(config, "ENABLE_SEARCH", True):
        if config.SEARCH_QUERIES:
            log.info("검색 비활성 (ENABLE_SEARCH=0) — 서브레딧 피드만 사용")
    else:
      for q in config.SEARCH_QUERIES:
        try:
            for p in client.search(q):
                if p["id"] not in seen_ids:
                    seen_ids.add(p["id"])
                    posts.append(p)
        except Exception as e:
            log.warning("검색 실패 [%s]: %s", q, e)

    return posts


def run_once(client, seen, dry=False, show_all=False):
    now = time.time()
    posts = collect(client)
    log.info("수집 %d건", len(posts))

    if show_all:
        print(f"\n─── 수집된 {len(posts)}건 (매칭여부 / r/서브 / 제목) ───")
        for p in sorted(posts, key=lambda x: -x.get("created_utc", 0)):
            mk = "✅" if match(p) else "  "
            mins = (now - p.get("created_utc", now)) / 60
            print(f"{mk} {mins:5.0f}분전  r/{p.get('subreddit',''):<22} {p.get('title','')[:66]}")
        print()

    hits = 0
    for p in posts:
        pid = p.get("id")
        if not pid or pid in seen:
            continue

        age = now - p.get("created_utc", now)
        if age > config.MAX_AGE_HOURS * 3600:
            continue

        m = match(p)
        if not m:
            continue

        msg = notify.format_post(p, m, age)
        if dry:
            print("\n" + "=" * 60 + "\n" + msg)
        else:
            try:
                notify.send_html(msg)
            except Exception as e:
                log.error("포워딩 실패 %s: %s", pid, e)
                continue          # seen 처리 안 함 → 다음 턴에 재시도
            time.sleep(1)         # 텔레그램 레이트리밋

        seen[pid] = now
        hits += 1
        log.info("포워딩: r/%s | %s", p.get("subreddit"), p.get("title", "")[:70])

    if not dry:
        save_seen(seen)
    log.info("이번 턴 %d건 포워딩", hits)
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--dry", action="store_true", help="텔레그램 전송 안 함")
    ap.add_argument("--show-all", action="store_true",
                    help="매칭 안 된 글까지 전부 제목 출력 (필터 점검용)")
    args = ap.parse_args()

    if not args.once and not args.loop:
        ap.error("--once 또는 --loop 중 하나를 줘")

    client = rss_source.from_env()
    seen = load_seen()

    if args.once:
        run_once(client, seen, args.dry, args.show_all)
        return

    log.info("워처 시작 — %d초 간격, 서브레딧 %d개, 검색 쿼리 %d개",
             config.POLL_INTERVAL_SECONDS, len(config.SUBREDDITS),
             len(config.SEARCH_QUERIES))
    while True:
        try:
            run_once(client, seen, args.dry, args.show_all)
        except Exception as e:
            log.exception("턴 실패: %s", e)
        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
